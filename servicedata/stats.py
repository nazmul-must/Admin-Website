"""Query helpers shared by the admin pages: per-request service access and date series."""

import logging
from collections.abc import Iterable, Mapping
from datetime import date, datetime, time, timedelta
from typing import Any

from django.http import HttpRequest
from django.utils import timezone

from . import rpc

logger = logging.getLogger(__name__)

SERVICE_LABELS = {
    "identity": "Identity",
    "agent": "Agent (AI)",
    "authorization": "Authorization",
    "document": "Document",
    "planning": "Planning",
    "notification": "Notification",
}
WINDOWS = (30, 90, 365)


class Sources:
    """Runs admin queries for one request and tracks which services failed.

    The admin site must stay useful while parts of the product are down, so a
    failed service returns `default` and the page shows a banner instead of a 500.
    After one failure the service is skipped for the rest of the request.
    """

    def __init__(self) -> None:
        """Start a request with every service assumed up."""
        self.down: list[str] = []

    def query(self, service: str, name: str, default: Any = None, **params: Any) -> Any:
        """The query's validated data, or `default` when the service is down."""
        if service in self.down:
            return default
        try:
            return rpc.query(service, name, **params)
        except rpc.ServiceUnavailable as e:
            logger.warning("admin query %s.%s failed: %s", service, name, e)
            self.down.append(service)
            return default

    def page_context(self, context: dict[str, Any]) -> dict[str, Any]:
        """`context` plus what base.html needs: the down-service banner and the window picker."""
        return {"windows": WINDOWS, **context, "down": [SERVICE_LABELS[s] for s in self.down]}


def window(request: HttpRequest, default: int = 90) -> int:
    """Reporting window in days from ?days=, limited to WINDOWS."""
    try:
        days = int(request.GET.get("days", default))
    except ValueError:
        return default
    return days if days in WINDOWS else default


def start_of(day: date) -> datetime:
    """Midnight at the start of `day`, in the site's time zone."""
    return timezone.make_aware(datetime.combine(day, time.min), timezone.get_current_timezone())


def day_range(days: int) -> list[date]:
    """The last `days` dates, oldest first, ending today."""
    today = timezone.localdate()
    return [today - timedelta(days=i) for i in range(days - 1, -1, -1)]


def since(days: int) -> datetime:
    """Start of the first day of a `days`-long window ending today."""
    return start_of(day_range(days)[0])


def month_start() -> datetime:
    """Start of the current calendar month."""
    return start_of(timezone.localdate().replace(day=1))


def labels(days: int) -> list[str]:
    """Chart x-axis labels for a `days`-long window."""
    return [d.strftime("%d %b") for d in day_range(days)]


def series(by_day: Mapping[str, float] | None, days: int) -> list[float]:
    """A daily map {'YYYY-MM-DD': value} as one value per day, oldest first, zero-filled."""
    by_day = by_day or {}
    return [by_day.get(d.isoformat()) or 0 for d in day_range(days)]


def fill_series(data: Mapping[str, Any] | None, days: int, *keys: str) -> dict[str, Any] | None:
    """A copy of a query result with the daily maps under `keys` turned into series.

    None (service down) passes through.
    """
    if data is None:
        return None
    return {**data, **{key: series(data[key], days) for key in keys}}


def cumulative(start: float, values: Iterable[float]) -> list[float]:
    """Running total of `values`, starting from `start`."""
    out, total = [], start
    for v in values:
        total += v
        out.append(total)
    return out


def pct(used: float | None, limit: float | None) -> int | None:
    """Percent of a limit used; None when the limit is unlimited/unknown."""
    if not limit:
        return None
    return round(100 * (used or 0) / limit)


def latest(*maps: Mapping[str, datetime | None]) -> dict[str, datetime]:
    """Merge {key: datetime} maps keeping the most recent value per key."""
    out: dict[str, datetime] = {}
    for d in maps:
        for k, v in d.items():
            if v and (k not in out or v > out[k]):
                out[k] = v
    return out
