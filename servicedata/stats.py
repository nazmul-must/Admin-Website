"""Query helpers shared by the admin pages."""

import logging
from datetime import datetime, time, timedelta

from django.shortcuts import render
from django.utils import timezone

from . import rpc

logger = logging.getLogger(__name__)

SERVICE_LABELS = {
    'identity': 'Identity',
    'agent': 'Agent (AI)',
    'authorization': 'Authorization',
    'document': 'Document',
    'planning': 'Planning',
    'notification': 'Notification',
}
WINDOWS = (30, 90, 365)


class Sources:
    """Runs admin queries for one request and tracks which services failed.

    The admin site must stay useful while parts of the product are down, so a
    failed service returns `default` and the page shows a banner instead of a 500.
    After one failure the service is skipped for the rest of the request.
    """

    def __init__(self):
        self.down = []

    def query(self, service, name, default=None, **params):
        if service in self.down:
            return default
        try:
            return rpc.query(service, name, **params)
        except rpc.ServiceUnavailable as e:
            logger.warning('admin query %s.%s failed: %s', service, name, e)
            self.down.append(service)
            return default

    def render(self, request, template, context):
        context['down'] = [SERVICE_LABELS[s] for s in self.down]
        context.setdefault('windows', WINDOWS)
        return render(request, template, context)


def window(request, default=90):
    """Reporting window in days from ?days=, limited to WINDOWS."""
    try:
        days = int(request.GET.get('days', default))
    except ValueError:
        return default
    return days if days in WINDOWS else default


def start_of(day):
    return timezone.make_aware(datetime.combine(day, time.min), timezone.get_current_timezone())


def day_range(days):
    """The last `days` dates, oldest first, ending today."""
    today = timezone.localdate()
    return [today - timedelta(days=i) for i in range(days - 1, -1, -1)]


def since(days):
    return start_of(day_range(days)[0])


def month_start():
    return start_of(timezone.localdate().replace(day=1))


def labels(days):
    return [d.strftime('%d %b') for d in day_range(days)]


def series(by_day, days):
    """A service's daily map {'YYYY-MM-DD': value} as one value per day, oldest first, zero-filled."""
    by_day = by_day or {}
    return [by_day.get(d.isoformat()) or 0 for d in day_range(days)]


def fill(d, days, *keys):
    """Turn the daily maps under `keys` of a query result into series, in place. None passes through."""
    if d:
        for key in keys:
            d[key] = series(d[key], days)
    return d


def cumulative(start, values):
    out, total = [], start
    for v in values:
        total += v
        out.append(total)
    return out


def pct(used, limit):
    """Percent of a limit used; None when the limit is unlimited/unknown."""
    if not limit:
        return None
    return round(100 * (used or 0) / limit)


def latest(*dicts):
    """Merge {key: datetime} dicts keeping the most recent value per key."""
    out = {}
    for d in dicts:
        for k, v in d.items():
            if v and (k not in out or v > out[k]):
                out[k] = v
    return out
