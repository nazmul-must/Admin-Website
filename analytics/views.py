"""Platform analytics that Grafana does not cover: tenants, billing, AI spend,
product adoption and access decisions. Grafana keeps HTTP/GraphQL/outbox health."""

from collections import defaultdict
from datetime import timedelta

from django.utils import timezone

from accounts.decorators import view_required
from servicedata.stats import (
    Sources,
    cumulative,
    day_range,
    fill,
    labels,
    latest,
    month_start,
    pct,
    since,
    window,
)
from servicedata.tiers import CREDITS_PER_USD, limits, tier_name
from tenants.selectors import subscriptions

from .charts import chart, ranked

PROBLEM_STATUSES = {'PAST_DUE', 'UNPAID', 'INCOMPLETE', 'INCOMPLETE_EXPIRED', 'CANCELED', 'CANCELLED'}
DORMANT_DAYS = 14


def _directory(src):
    """Identity's id lookups: org_names, member_orgs, programme_orgs, org_last_audit (all orgs, deleted too)."""
    return src.query('identity', 'directory', {'org_names': {}, 'member_orgs': {}, 'programme_orgs': {}, 'org_last_audit': {}})


def _credits(values):
    return [round((v or 0) * CREDITS_PER_USD) for v in values]


def _attention(names, subs, month_ai):
    """Organizations an operator should look at now. `month_ai` = {org_id: AI USD this month}."""
    now = timezone.now()
    items = []
    for org_id, sub in subs.items():
        name = names.get(org_id, org_id)
        if sub['status'] in PROBLEM_STATUSES:
            items.append((org_id, name, f"Subscription {sub['status'].lower()}", 'red'))
        end = sub['current_period_end']
        if sub['cancel_at_period_end']:
            items.append((org_id, name, f"Cancels on {end.strftime('%Y-%m-%d') if end else 'period end'}", 'red'))
        elif end and now <= end <= now + timedelta(days=7):
            items.append((org_id, name, f'Period ends {end:%Y-%m-%d}', 'amber'))
        used = pct(month_ai.get(org_id), limits(sub)['ai_usd'])
        if used is not None and used >= 80:
            items.append((org_id, name, f'AI credits at {used}% of allowance', 'red' if used >= 100 else 'amber'))
    return [{'org_id': i, 'name': n, 'reason': r, 'level': lvl} for i, n, r, lvl in items]


@view_required
def overview(request):
    src = Sources()
    days = window(request, 90)
    x = labels(days)

    idn = fill(src.query('identity', 'overview', since=since(days), recent=since(30)), days, 'org_daily')
    subs = subscriptions(src)
    names = _directory(src)['org_names']
    month_ai = src.query('agent', 'org_usage', since=month_start())
    docs = src.query('document', 'summary', since=since(days))
    items = src.query('planning', 'summary', since=since(days))

    tier_mix = defaultdict(int)
    status_mix = defaultdict(int)
    for s in subs.values():
        tier_mix[tier_name(s['tier'])] += 1
        status_mix[s['status'].lower()] += 1
    paid = sum(1 for s in subs.values() if s['status'] == 'ACTIVE' and s['tier'] != 'POC')

    charts = {
        'tier': chart('doughnut', [], dict(tier_mix)) if tier_mix else None,
        'status': chart('doughnut', [], dict(status_mix)) if status_mix else None,
    }
    if idn:
        charts['signups'] = chart('bar', x, {'New organizations': idn['org_daily']})
        charts['total'] = chart('line', x, {'Organizations': cumulative(idn['orgs_before'], idn['org_daily'])})

    return src.render(request, 'analytics/overview.html', {
        'days': days, 'idn': idn, 'charts': charts, 'paid': paid,
        'past_due': sum(1 for s in subs.values() if s['status'] in PROBLEM_STATUSES),
        'ai_mtd': sum(v or 0 for v in month_ai['cost_by_org'].values()) if month_ai else None,
        'docs': docs['total'] if docs else None,
        'items': items['total'] if items else None,
        'attention': _attention(names, subs, month_ai['cost_by_org'] if month_ai else {}),
        'subs': subs,
    })


@view_required
def growth(request):
    src = Sources()
    days = window(request, 90)
    x = labels(days)
    start = since(days)

    idn = fill(src.query('identity', 'growth', since=start), days, 'orgs', 'users', 'members', 'programmes')
    charts, funnel = {}, []
    if idn:
        charts['signups'] = chart('line', x, {
            'Organizations': idn['orgs'], 'Users': idn['users'], 'Memberships': idn['members'], 'Programmes': idn['programmes'],
        })
        charts['cumulative'] = chart('line', x, {
            'Organizations': cumulative(idn['orgs_before'], idn['orgs']),
            'Users': cumulative(idn['users_before'], idn['users']),
        })
        charts['types'] = chart('doughnut', [], {k.lower(): v for k, v in idn['org_types'].items()})

        programme_org = _directory(src)['programme_orgs']
        work_programmes = src.query('planning', 'summary', {}, since=start).get('by_programme', {})
        with_work = {programme_org.get(p) for p in work_programmes}
        with_docs = set(src.query('document', 'summary', {}, since=start).get('by_org', {}))
        with_ai = set(src.query('agent', 'org_usage', {}, since=start).get('last_by_org', {}))
        all_orgs = set(idn['all_orgs'])
        total = len(all_orgs)
        steps = [
            ('Signed up', all_orgs),
            ('Invited a 2nd user', set(idn['multi_user'])),
            ('Created a programme', set(idn['with_programme'])),
            ('Planned work items', with_work),
            ('Uploaded documents', with_docs),
            ('Used AI', with_ai),
        ]
        funnel = [{'label': lbl, 'n': len(ids & all_orgs), 'pct': pct(len(ids & all_orgs), total)} for lbl, ids in steps]
        charts['funnel'] = chart('bar', [f['label'] for f in funnel], {'Organizations': [f['n'] for f in funnel]}, horizontal=True)

    return src.render(request, 'analytics/growth.html', {'days': days, 'idn': idn, 'charts': charts, 'funnel': funnel})


@view_required
def billing(request):
    src = Sources()
    days = window(request, 90)
    subs = subscriptions(src)
    names = _directory(src)['org_names']
    now = timezone.now()

    tiers_seen = sorted({tier_name(s['tier']) for s in subs.values()})
    statuses = sorted({s['status'] for s in subs.values()})
    matrix = [
        {'tier': t, 'cells': [sum(1 for s in subs.values() if tier_name(s['tier']) == t and s['status'] == st) for st in statuses]}
        for t in tiers_seen
    ]
    renewals = sorted(
        (s for s in subs.values() if s['current_period_end'] and now <= s['current_period_end'] <= now + timedelta(days=30)),
        key=lambda s: s['current_period_end'],
    )
    overrides = [
        s for s in subs.values()
        if s['programme_limit_override'] is not None or s['user_limit_override'] is not None
        or s['ai_credit_allowance_override_usd'] is not None
    ]

    ev = fill(src.query('identity', 'billing_events', since=since(days)), days, 'daily')
    charts = {
        'tier': chart('doughnut', [], {t: sum(r['cells']) for t, r in zip(tiers_seen, matrix)}) if subs else None,
    }
    if ev:
        charts['events'] = chart('bar', labels(days), {'Stripe events': ev['daily']})
        by_type = ranked(ev['by_type'])
        charts['types'] = chart('bar', list(by_type), {'Events': list(by_type.values())}, horizontal=True) if by_type else None

    return src.render(request, 'analytics/billing.html', {
        'days': days, 'subs': subs, 'names': names, 'charts': charts, 'ev': ev,
        'statuses': statuses, 'matrix': matrix, 'renewals': renewals, 'overrides': overrides,
        'problems': [s for s in subs.values() if s['status'] in PROBLEM_STATUSES or s['cancel_at_period_end']],
        'seats': sum(s['seats'] or 0 for s in subs.values()),
        'stripe_linked': sum(1 for s in subs.values() if s['stripe_subscription_id']),
        'paid': sum(1 for s in subs.values() if s['status'] == 'ACTIVE' and s['tier'] != 'POC'),
        'enterprise': sum(1 for s in subs.values() if s['tier'] == 'ENTERPRISE'),
    })


@view_required
def ai_usage(request):
    src = Sources()
    days = window(request, 30)
    x = labels(days)
    names = _directory(src)['org_names']
    subs = subscriptions(src)

    ai = fill(
        src.query('agent', 'dashboard', since=since(days), month_start=month_start(),
                  stale_before=timezone.now() - timedelta(days=1)),
        days, 'cost', 'prompt', 'completion', 'runs_ok', 'runs_failed', 'sessions',
    )
    charts, top = {}, []
    if ai:
        charts['cost'] = chart('line', x, {'Credits': _credits(ai['cost'])})
        charts['tokens'] = chart('bar', x, {'Prompt': ai['prompt'], 'Completion': ai['completion']}, stacked=True)
        charts['model'] = chart('doughnut', [], {k: round((v or 0) * CREDITS_PER_USD) for k, v in ranked(ai['by_model']).items()}) if ai['by_model'] else None
        charts['feature'] = chart('bar', list(ranked(ai['by_feature'])), {'Credits': _credits(ranked(ai['by_feature']).values())}, horizontal=True) if ai['by_feature'] else None
        charts['runs'] = chart('bar', x, {'Succeeded / running': ai['runs_ok'], 'Failed': ai['runs_failed']}, stacked=True)
        charts['sessions'] = chart('bar', x, {'Agent sessions': ai['sessions']})
        charts['ingestion'] = chart('doughnut', [], ranked(ai['ingestion'])) if ai['ingestion'] else None
        for org_id, usd in sorted(ai['mtd_by_org'].items(), key=lambda kv: kv[1] or 0, reverse=True)[:15]:
            allowance = limits(subs.get(org_id))['ai_usd']
            top.append({'org_id': org_id, 'name': names.get(org_id, org_id), 'usd': usd,
                        'allowance': allowance, 'pct': pct(usd, allowance)})
        runs_total = sum(ai['runs_by_status'].values())
        failed = sum(n for s, n in ai['runs_by_status'].items() if (s or '').lower() in ('failed', 'error'))
        ai['run_failure_pct'] = pct(failed, runs_total)

    return src.render(request, 'analytics/ai_usage.html', {'days': days, 'ai': ai, 'charts': charts, 'top': top})


@view_required
def engagement(request):
    src = Sources()
    days = window(request, 30)
    x = labels(days)
    start = since(days)
    directory = _directory(src)
    names, member_org = directory['org_names'], directory['member_orgs']

    authz = src.query('authorization', 'engagement', since=start, since_7=since(7), since_30=since(30))
    charts = {}
    active_members = defaultdict(int)  # org -> distinct active members in window
    org_last = {}
    if authz:
        daily_members = [set(authz['daily_members'].get(d.isoformat(), ())) for d in day_range(days)]
        charts['dau'] = chart('line', x, {
            'Active members': [len(members) for members in daily_members],
            'Active organizations': [len({member_org[m] for m in members if m in member_org}) for members in daily_members],
        })
        for member in authz['by_member']:
            if member in member_org:
                active_members[member_org[member]] += 1
        for member, when in src.query('authorization', 'member_last_access', {}).items():
            org = member_org.get(member)
            if org and (org not in org_last or when > org_last[org]):
                org_last[org] = when

    docs = fill(src.query('document', 'summary', since=start), days, 'daily')
    items = fill(src.query('planning', 'summary', since=start), days, 'daily')
    ai_window = src.query('agent', 'org_usage', {}, since=start).get('cost_by_org', {})
    unread = src.query('notification', 'unread_by_member', {})
    programme_org = directory['programme_orgs']

    items_by_org = defaultdict(int)
    for programme, n in (items['by_programme'] if items else {}).items():
        if programme in programme_org:
            items_by_org[programme_org[programme]] += n
    unread_by_org = defaultdict(int)
    for member, n in unread.items():
        if member in member_org:
            unread_by_org[member_org[member]] += n

    docs_by_org = docs['by_org'] if docs else {}
    last_seen = latest(directory['org_last_audit'], org_last)
    cutoff = timezone.now() - timedelta(days=DORMANT_DAYS)
    rows = sorted(
        (
            {
                'org_id': org_id, 'name': name, 'last_seen': last_seen.get(org_id),
                'active_members': active_members.get(org_id, 0), 'docs': docs_by_org.get(org_id, 0),
                'items': items_by_org.get(org_id, 0), 'ai_usd': ai_window.get(org_id) or 0,
                'unread': unread_by_org.get(org_id, 0),
                'dormant': not last_seen.get(org_id) or last_seen[org_id] < cutoff,
            }
            for org_id, name in names.items()
        ),
        key=lambda r: (r['last_seen'] is not None, r['last_seen'] or 0),
        reverse=True,
    )
    adoption = {
        'Documents': sum(1 for r in rows if r['docs']),
        'Planning': sum(1 for r in rows if r['items']),
        'AI': sum(1 for r in rows if r['ai_usd']),
        'Active in window': sum(1 for r in rows if r['active_members']),
    }
    charts['adoption'] = chart('bar', list(adoption), {'Organizations': list(adoption.values())}) if rows else None
    created = {}
    if docs:
        created['Documents'] = docs['daily']
    if items:
        created['Work items'] = items['daily']
    charts['created'] = chart('line', x, created) if created else None

    return src.render(request, 'analytics/engagement.html', {
        'days': days, 'authz': authz, 'charts': charts, 'rows': rows,
        'dormant': sum(1 for r in rows if r['dormant']), 'dormant_days': DORMANT_DAYS,
    })


@view_required
def access(request):
    src = Sources()
    days = window(request, 30)
    x = labels(days)
    directory = _directory(src)
    names, member_org = directory['org_names'], directory['member_orgs']

    a = fill(src.query('authorization', 'access', since=since(days)), days, 'allow', 'deny')
    charts, top = {}, []
    if a:
        a['deny_pct'] = pct(a['denied'], a['total'])
        charts['daily'] = chart('bar', x, {'Allowed': a['allow'], 'Denied': a['deny']}, stacked=True)
        charts['deny_action'] = chart('bar', list(ranked(a['deny_by_action'])), {'Denials': list(ranked(a['deny_by_action']).values())}, horizontal=True) if a['deny_by_action'] else None
        charts['deny_source'] = chart('doughnut', [], ranked(a['deny_by_source'])) if a['deny_by_source'] else None
        charts['allow_source'] = chart('doughnut', [], ranked(a['allow_by_source'])) if a['allow_by_source'] else None
        for member, n in a['top_denied']:
            org = member_org.get(member)
            top.append({'member': member, 'org_id': org, 'org': names.get(org, '—'), 'n': n})

    return src.render(request, 'analytics/access.html', {'days': days, 'a': a, 'charts': charts, 'top': top})
