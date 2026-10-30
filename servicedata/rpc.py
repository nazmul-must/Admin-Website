"""RabbitMQ RPC client for the services' admin read queries (the CQRS query side).

Every service answers `{"query": name, "params": {...}}` on the `admin` exchange, routing key
`admin.query.<service>` (plus RABBITMQ_SUFFIX, as pro3ai_generic appends it), and replies
`{"status": "success", "data": ...}` or `{"status": "error", "message": ...}`. The contract
for each query lives next to its consumer in the owning service.

Replies come back over RabbitMQ direct reply-to, so no reply queue is declared. One blocking
connection per thread; a broken connection is reopened on the next call.
ponytail: calls on one page run one after another; publish them together and collect the
replies by correlation id if pages get slow.
"""

import json
import logging
import re
import threading
import time
import uuid
from datetime import date, datetime, timezone

import pika
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder

logger = logging.getLogger(__name__)

EXCHANGE = 'admin'
REPLY_TO = 'amq.rabbitmq.reply-to'
_DATETIME = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}')
_DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')

_local = threading.local()


class ServiceUnavailable(Exception):
    """The service did not answer in time, refused the query or could not be reached."""


def _revive(obj):
    """JSON object hook: ISO datetime/date string values become aware datetimes/dates (UTC
    when naive). Keys are left alone, so daily maps stay keyed by 'YYYY-MM-DD'."""
    for key, value in obj.items():
        if isinstance(value, str):
            if _DATETIME.match(value):
                parsed = datetime.fromisoformat(value)
                obj[key] = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            elif _DATE.match(value):
                obj[key] = date.fromisoformat(value)
    return obj


def _on_reply(_channel, _method, props, body):
    _local.replies[props.correlation_id] = body


def _on_return(_channel, _method, props, _body):
    _local.returned.add(props.correlation_id)


def _connect():
    conn = pika.BlockingConnection(pika.URLParameters(settings.RABBITMQ_URL))
    channel = conn.channel()
    channel.add_on_return_callback(_on_return)
    channel.basic_consume(REPLY_TO, _on_reply, auto_ack=True)
    _local.conn, _local.channel, _local.replies, _local.returned = conn, channel, {}, set()


def _reset():
    conn = getattr(_local, 'conn', None)
    _local.conn = _local.channel = None
    if conn is not None and conn.is_open:
        try:
            conn.close()
        except pika.exceptions.AMQPError:
            pass


def _call(service, body):
    if getattr(_local, 'channel', None) is None or _local.channel.is_closed:
        _connect()
    _local.replies.clear()  # calls run one at a time per thread: anything left is a late reply
    correlation_id = uuid.uuid4().hex
    timeout = settings.ADMIN_RPC_TIMEOUT
    _local.channel.basic_publish(
        exchange=EXCHANGE,
        routing_key=f'admin.query.{service}{settings.RABBITMQ_SUFFIX}',
        body=body,
        properties=pika.BasicProperties(
            reply_to=REPLY_TO,
            correlation_id=correlation_id,
            content_type='application/json',
            expiration=str(int(timeout * 1000)),  # nobody waits for a reply after this
        ),
        mandatory=True,  # no bound queue = the service never started: fail fast
    )
    deadline = time.monotonic() + timeout
    while correlation_id not in _local.replies:
        if correlation_id in _local.returned:
            _local.returned.discard(correlation_id)
            raise ServiceUnavailable(f'{service}: no consumer bound to admin.query.{service}')
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ServiceUnavailable(f'{service}: no reply within {timeout}s')
        _local.conn.process_data_events(time_limit=remaining)
    return _local.replies.pop(correlation_id)


def query(service, name, **params):
    """Run one admin query on `service` and return its `data`. Raises ServiceUnavailable."""
    body = json.dumps({'query': name, 'params': params}, cls=DjangoJSONEncoder).encode()
    for attempt in (1, 2):  # a dropped idle connection gets one reconnect; reads are idempotent
        try:
            raw = _call(service, body)
            break
        except pika.exceptions.AMQPError as e:
            _reset()
            if attempt == 2:
                raise ServiceUnavailable(f'{service}: broker unavailable ({e!r})') from e
    reply = json.loads(raw, object_hook=_revive)
    if reply.get('status') != 'success':
        raise ServiceUnavailable(f"{service}.{name}: {reply.get('message', 'error reply')}")
    return reply.get('data')
