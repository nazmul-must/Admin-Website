from django.contrib.auth.decorators import login_required
from django.http import Http404

from analytics.charts import chart, ranked
from servicedata.stats import Sources, labels, window
from servicedata.tiers import CREDITS_PER_USD, tiers

from servicedata import pii

from .selectors import org_detail, org_rows, subscriptions
from .user_selectors import user_detail, user_rows


@login_required
def org_list(request):
    src = Sources()
    q = request.GET.get('q', '').strip()
    tier = request.GET.get('tier', '')
    status = request.GET.get('status', '')
    context = {
        'rows': org_rows(src, q, tier, status),
        'q': q,
        'tier': tier,
        'status': status,
        'tiers': [(key.upper(), t.get('display_name', key)) for key, t in tiers().items()],
        'statuses': sorted({s.status for s in subscriptions(src).values()}),
    }
    template = 'tenants/org_list.html'
    if request.headers.get('HX-Request'):
        template += '#org-table'
    return src.render(request, template, context)


@login_required
def org_detail_view(request, org_id):
    src = Sources()
    days = window(request, 30)
    d = org_detail(src, org_id, days)
    if d is None:
        if src.down:
            return src.render(request, 'tenants/org_unavailable.html', {'org_id': org_id})
        raise Http404('Organization not found')

    x = labels(days)
    charts = {
        'activity': chart('bar', x, {'Audit events': d['activity']}),
    }
    if d['ai']:
        charts['ai_cost'] = chart('line', x, {'Credits': [round((v or 0) * CREDITS_PER_USD) for v in d['ai']['daily_cost']]})
        if d['ai']['by_feature']:
            charts['ai_feature'] = chart('doughnut', [], ranked(d['ai']['by_feature']))
    if d['access']:
        charts['access'] = chart('bar', x, {'Allowed': d['access']['allow'], 'Denied': d['access']['deny']}, stacked=True)
    if d['plan'] and d['plan']['by_type']:
        charts['work_types'] = chart('doughnut', [], ranked(d['plan']['by_type']))
    if d['docs']:
        charts['docs'] = chart('bar', x, {'Documents created': d['docs']['daily']})

    return src.render(request, 'tenants/org_detail.html', {**d, 'charts': charts, 'days': days, 'credits_per_usd': CREDITS_PER_USD})


@login_required
def user_list(request):
    src = Sources()
    filters = {k: request.GET.get(k, '').strip() for k in ('q', 'org', 'verified', 'mfa')}
    rows, orgs = user_rows(src, **filters)
    context = {'rows': rows, 'orgs': orgs, 'pii_enabled': pii.enabled(), **filters}
    template = 'tenants/user_list.html'
    if request.headers.get('HX-Request'):
        template += '#user-table'
    return src.render(request, template, context)


@login_required
def user_detail_view(request, user_id):
    src = Sources()
    days = window(request, 30)
    d = user_detail(src, user_id, days)
    if d is None:
        if src.down:
            return src.render(request, 'tenants/org_unavailable.html', {'org_id': user_id})
        raise Http404('User not found')

    x = labels(days)
    charts = {'activity': chart('bar', x, {'Audit events': d['activity']})}
    if d['access']:
        charts['access'] = chart('bar', x, {'Allowed': d['access']['allow'], 'Denied': d['access']['deny']}, stacked=True)
    if d['ai']:
        charts['ai_cost'] = chart('line', x, {'Credits': [round((v or 0) * CREDITS_PER_USD) for v in d['ai']['daily_cost']]})
    if d['docs']:
        charts['uploads'] = chart('bar', x, {'Document versions uploaded': d['docs']['daily']})

    return src.render(request, 'tenants/user_detail.html', {**d, 'charts': charts, 'days': days, 'pii_enabled': pii.enabled()})
