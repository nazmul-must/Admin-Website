"""`/health/`: whether the admin site itself is up, for probes and the outside-in prober."""

import logging

from django.db import DatabaseError, connection
from django.http import HttpRequest, JsonResponse

logger = logging.getLogger(__name__)


def health(_request: HttpRequest) -> JsonResponse:
    """200 when the site's own database answers, 503 when it does not.

    Product services are deliberately not checked: the admin site must stay up, and report
    them as down, when they fail. No sign-in needed; nothing about the data is returned.
    """
    try:
        connection.ensure_connection()
    except DatabaseError:
        logger.exception("health: database unavailable")
        return JsonResponse({"status": "error"}, status=503)
    return JsonResponse({"status": "ok"})
