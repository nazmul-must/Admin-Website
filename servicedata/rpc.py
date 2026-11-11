"""RabbitMQ RPC client for the services' admin read queries (the CQRS query side).

Every service answers `{"query": name, "params": {...}}` on the `admin` exchange, routing key
`admin.query.<service>` (plus RABBITMQ_SUFFIX, as pro3ai_generic appends it), and replies
`{"status": "success", "data": ...}` or `{"status": "error", "message": ...}`. The reply's
`data` is validated against its contract in `contracts.REPLIES`.

Replies come back over RabbitMQ direct reply-to, so no reply queue is declared. One blocking
connection per thread; a broken connection is reopened on the next call. That is why the site
runs under WSGI (sync or threaded workers) only: there is no ASGI entry point.
ponytail: calls on one page run one after another; publish them together and collect the
replies by correlation id if pages get slow.
"""

import contextlib
import json
import logging
import threading
import time
import uuid
from typing import Any

import pika
import pika.exceptions
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from pika.adapters.blocking_connection import BlockingChannel
from pika.spec import Basic, BasicProperties
from pydantic import ValidationError

from .contracts import REPLIES

logger = logging.getLogger(__name__)

EXCHANGE = "admin"
REPLY_TO = "amq.rabbitmq.reply-to"
SHOWN_PROBLEMS = 3  # contract violations named in the log line

_local = threading.local()


class ServiceUnavailable(Exception):
    """The service did not answer in time, refused the query, could not be reached, or sent
    a reply that does not match the query's contract."""


def _on_reply(
    _channel: BlockingChannel, _method: Basic.Deliver, props: BasicProperties, body: bytes
) -> None:
    """Keep a reply until the caller waiting for its correlation id collects it."""
    _local.replies[props.correlation_id] = body


def _on_return(
    _channel: BlockingChannel, _method: Basic.Return, props: BasicProperties, _body: bytes
) -> None:
    """Note a request the broker could not route (no queue bound for that service)."""
    _local.returned.add(props.correlation_id)


def _connect() -> None:
    """Open this thread's connection and start consuming direct reply-to."""
    conn = pika.BlockingConnection(pika.URLParameters(settings.RABBITMQ_URL))
    channel = conn.channel()
    channel.add_on_return_callback(_on_return)
    channel.basic_consume(REPLY_TO, _on_reply, auto_ack=True)
    _local.conn, _local.channel, _local.replies, _local.returned = conn, channel, {}, set()


def _reset() -> None:
    """Drop this thread's connection so the next call reconnects."""
    conn = getattr(_local, "conn", None)
    _local.conn = _local.channel = None
    if conn is not None and conn.is_open:
        with contextlib.suppress(pika.exceptions.AMQPError):
            conn.close()


def _call(service: str, body: bytes) -> bytes:
    """Publish one request to `service` and wait for its raw reply.

    Raises:
        ServiceUnavailable: no queue is bound for the service, or no reply came in time.
        pika.exceptions.AMQPError, OSError: the broker connection failed.
    """
    if getattr(_local, "channel", None) is None or _local.channel.is_closed:
        _connect()
    _local.replies.clear()  # calls run one at a time per thread: anything left is a late reply
    correlation_id = uuid.uuid4().hex
    timeout = settings.ADMIN_RPC_TIMEOUT
    _local.channel.basic_publish(
        exchange=EXCHANGE,
        routing_key=f"admin.query.{service}{settings.RABBITMQ_SUFFIX}",
        body=body,
        properties=pika.BasicProperties(
            reply_to=REPLY_TO,
            correlation_id=correlation_id,
            content_type="application/json",
            expiration=str(int(timeout * 1000)),  # nobody waits for a reply after this
        ),
        mandatory=True,  # no bound queue = the service never started: fail fast
    )
    deadline = time.monotonic() + timeout
    while correlation_id not in _local.replies:
        if correlation_id in _local.returned:
            _local.returned.discard(correlation_id)
            raise ServiceUnavailable(f"{service}: no consumer bound to admin.query.{service}")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ServiceUnavailable(f"{service}: no reply within {timeout}s")
        _local.conn.process_data_events(time_limit=remaining)
    return _local.replies.pop(correlation_id)


def _send(service: str, body: bytes) -> bytes:
    """`_call`, reconnecting once on a broken connection (OSError: DNS failure, socket errors).

    A dropped idle connection gets one reconnect; reads are idempotent, so resending is safe.
    """
    try:
        return _call(service, body)
    except (pika.exceptions.AMQPError, OSError):
        _reset()
    try:
        return _call(service, body)
    except (pika.exceptions.AMQPError, OSError) as e:
        _reset()
        raise ServiceUnavailable(f"{service}: broker unavailable ({e!r})") from e


def _validation_summary(error: ValidationError) -> str:
    """Where the reply broke its contract, without the values: replies carry decrypted PII."""
    problems = [
        f"{'.'.join(str(part) for part in e['loc']) or '<data>'}: {e['type']}"
        for e in error.errors(include_input=False)
    ]
    hidden = len(problems) - SHOWN_PROBLEMS
    return "; ".join(problems[:SHOWN_PROBLEMS]) + (f" (+{hidden} more)" if hidden > 0 else "")


def query(service: str, name: str, **params: Any) -> Any:
    """Run one admin query on `service` and return its validated `data`.

    Raises:
        ServiceUnavailable: the service is unreachable, refused the query, or replied with
            something that does not match the query's contract.
    """
    contract = REPLIES[(service, name)]
    body = json.dumps({"query": name, "params": params}, cls=DjangoJSONEncoder).encode()
    raw = _send(service, body)
    try:
        reply = json.loads(raw)
    except ValueError as e:
        raise ServiceUnavailable(f"{service}.{name}: reply is not JSON") from e
    if not isinstance(reply, dict) or reply.get("status") != "success":
        message = reply.get("message", "error reply") if isinstance(reply, dict) else "bad reply"
        raise ServiceUnavailable(f"{service}.{name}: {message}")
    try:
        return contract.validate_python(reply.get("data"))
    except ValidationError as e:
        raise ServiceUnavailable(
            f"{service}.{name}: reply breaks its contract: {_validation_summary(e)}"
        ) from e
