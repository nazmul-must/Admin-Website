"""Query helpers shared by the admin pages."""

import logging
from datetime import datetime, time, timedelta

from django.db import DatabaseError
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.shortcuts import render
from django.utils import timezone

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
    """Tracks which service databases failed during one request.

    The admin site must stay useful while parts of the product are down, so a
    failed source returns `default` and the page shows a banner instead of a 500.
    `fn` must evaluate its querysets (list/dict/aggregate), not return lazy ones.
    """

    def __init__(self):
        self.down = []

    def fetch(self, service, fn, default=None):
        if service in self.down:
            return default
        try:
            return fn()
        except DatabaseError:
            logger.exception('%s database unavailable', service)
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


def daily(qs, days, agg=None, field='created_at'):
    """One value per day for the last `days` days, oldest first, zero-filled."""
    dates = day_range(days)
    rows = (
        qs.filter(**{f'{field}__gte': start_of(dates[0])})
        .annotate(day=TruncDate(field))
        .values('day')
        .annotate(v=agg or Count('id'))
        .order_by()
    )
    by_day = {r['day']: r['v'] or 0 for r in rows}
    return [by_day.get(d, 0) for d in dates]


def cumulative(start, values):
    out, total = [], start
    for v in values:
        total += v
        out.append(total)
    return out


def count_by(qs, field, agg=None):
    """{field value: aggregate} for a queryset, default aggregate = row count."""
    return dict(qs.values(field).annotate(v=agg or Count('id')).order_by().values_list(field, 'v'))


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
