"""Platform analytics that Grafana does not cover: tenants, billing, AI spend,
product adoption and access decisions. Grafana keeps HTTP/GraphQL/outbox health."""

from collections import defaultdict
from datetime import timedelta

from django.db.models import Count, Max, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from accounts.decorators import view_required
from servicedata.models import (
    AccessDecision,
    AgentSession,
    AiUsageEvent,
    AuditLog,
    BillingEvent,
    Document,
    IngestionLog,
    Member,
    Notification,
    Organization,
    OrgAiKey,
    PlanRun,
    Programme,
    User,
    WorkItem,
)
from servicedata.stats import (
    Sources,
    count_by,
    cumulative,
    daily,
    day_range,
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


def _org_names(src):
    return src.fetch('identity', lambda: dict(Organization.objects.values_list('id', 'name')), {})


def _member_orgs(src):
    """member_id -> org_id, for services that only record member ids."""
    return src.fetch('identity', lambda: dict(Member.objects.values_list('id', 'org_id')), {})


def _credits(values):
    return [round((v or 0) * CREDITS_PER_USD) for v in values]


def _attention(src, names, subs):
    """Organizations an operator should look at now."""
    now = timezone.now()
    month_ai = src.fetch(
        'agent',
        lambda: count_by(AiUsageEvent.objects.filter(created_at__gte=month_start()), 'org_id', Sum('cost_usd')),
        {},
    )
    items = []
    for org_id, sub in subs.items():
        name = names.get(org_id, org_id)
        if sub.status in PROBLEM_STATUSES:
            items.append((org_id, name, f'Subscription {sub.status.lower()}', 'red'))
        if sub.cancel_at_period_end:
            end = sub.current_period_end.strftime('%Y-%m-%d') if sub.current_period_end else 'period end'
            items.append((org_id, name, f'Cancels on {end}', 'red'))
        elif sub.current_period_end and now <= sub.current_period_end <= now + timedelta(days=7):
            items.append((org_id, name, f'Period ends {sub.current_period_end:%Y-%m-%d}', 'amber'))
        used = pct(month_ai.get(org_id), limits(sub)['ai_usd'])
        if used is not None and used >= 80:
            items.append((org_id, name, f'AI credits at {used}% of allowance', 'red' if used >= 100 else 'amber'))
    return [{'org_id': i, 'name': n, 'reason': r, 'level': lvl} for i, n, r, lvl in items]


@view_required
def overview(request):
    src = Sources()
    days = window(request, 90)
    x = labels(days)
    recent = since(30)

    def identity():
        orgs = Organization.objects.filter(deleted_at__isnull=True)
        users = User.objects.filter(deleted_at__isnull=True)
        return {
            'orgs': orgs.count(),
            'orgs_new': orgs.filter(created_at__gte=recent).count(),
            'orgs_before': orgs.filter(created_at__lt=since(days)).count(),
            'org_daily': daily(orgs, days),
            'users': users.count(),
            'users_new': users.filter(created_at__gte=recent).count(),
            'programmes': Programme.objects.filter(deleted_at__isnull=True).count(),
            'newest': list(orgs.order_by('-created_at')[:8]),
        }

    idn = src.fetch('identity', identity)
    subs = subscriptions(src)
    names = _org_names(src)
    ai_mtd = src.fetch('agent', lambda: AiUsageEvent.objects.filter(created_at__gte=month_start()).aggregate(c=Sum('cost_usd'))['c'] or 0, None)
    docs = src.fetch('document', lambda: Document.objects.filter(deleted_at__isnull=True).count())
    items = src.fetch('planning', lambda: WorkItem.objects.filter(deleted_at__isnull=True).count())

    tier_mix = defaultdict(int)
    status_mix = defaultdict(int)
    for s in subs.values():
        tier_mix[tier_name(s.tier)] += 1
        status_mix[s.status.lower()] += 1
    paid = sum(1 for s in subs.values() if s.status == 'ACTIVE' and s.tier != 'POC')

    charts = {
        'tier': chart('doughnut', [], dict(tier_mix)) if tier_mix else None,
        'status': chart('doughnut', [], dict(status_mix)) if status_mix else None,
    }
    if idn:
        charts['signups'] = chart('bar', x, {'New organizations': idn['org_daily']})
        charts['total'] = chart('line', x, {'Organizations': cumulative(idn['orgs_before'], idn['org_daily'])})

    return src.render(request, 'analytics/overview.html', {
        'days': days, 'idn': idn, 'charts': charts, 'paid': paid,
        'past_due': sum(1 for s in subs.values() if s.status in PROBLEM_STATUSES),
        'ai_mtd': ai_mtd, 'docs': docs, 'items': items,
        'attention': _attention(src, names, subs),
        'subs': subs,
    })


@view_required
def growth(request):
    src = Sources()
    days = window(request, 90)
    x = labels(days)
    start = since(days)

    def identity():
        orgs = Organization.objects.filter(deleted_at__isnull=True)
        users = User.objects.filter(deleted_at__isnull=True)
        members = Member.objects.filter(deleted_at__isnull=True)
        return {
            'orgs': daily(orgs, days),
            'users': daily(users, days),
            'members': daily(members, days),
            'programmes': daily(Programme.objects.filter(deleted_at__isnull=True), days),
            'orgs_before': orgs.filter(created_at__lt=start).count(),
            'users_before': users.filter(created_at__lt=start).count(),
            'org_types': count_by(orgs, 'org_type'),
            'all_orgs': set(orgs.values_list('id', flat=True)),
            'multi_user': {o for o, n in count_by(members, 'org_id', Count('user_id', distinct=True)).items() if n >= 2},
            'with_programme': set(Programme.objects.filter(deleted_at__isnull=True).values_list('org_id', flat=True)),
            'programme_org': dict(Programme.objects.values_list('id', 'org_id')),
            'verified': users.filter(email_verified=True).count(),
            'mfa': users.exclude(mfa_method__isnull=True).exclude(mfa_method='').count(),
            'user_total': users.count(),
        }

    idn = src.fetch('identity', identity)
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

        work_programmes = src.fetch('planning', lambda: set(
            WorkItem.objects.filter(deleted_at__isnull=True).values_list('programme_id', flat=True).distinct()), set())
        with_work = {idn['programme_org'].get(p) for p in work_programmes}
        with_docs = src.fetch('document', lambda: set(
            Document.objects.filter(deleted_at__isnull=True).values_list('organization_id', flat=True).distinct()), set())
        with_ai = src.fetch('agent', lambda: set(AiUsageEvent.objects.values_list('org_id', flat=True).distinct()), set())
        total = len(idn['all_orgs'])
        steps = [
            ('Signed up', idn['all_orgs']),
            ('Invited a 2nd user', idn['multi_user']),
            ('Created a programme', idn['with_programme']),
            ('Planned work items', with_work),
            ('Uploaded documents', with_docs),
            ('Used AI', with_ai),
        ]
        funnel = [{'label': lbl, 'n': len(ids & idn['all_orgs']), 'pct': pct(len(ids & idn['all_orgs']), total)} for lbl, ids in steps]
        charts['funnel'] = chart('bar', [f['label'] for f in funnel], {'Organizations': [f['n'] for f in funnel]}, horizontal=True)

    return src.render(request, 'analytics/growth.html', {'days': days, 'idn': idn, 'charts': charts, 'funnel': funnel})


@view_required
def billing(request):
    src = Sources()
    days = window(request, 90)
    subs = subscriptions(src)
    names = _org_names(src)
    now = timezone.now()

    tiers_seen = sorted({tier_name(s.tier) for s in subs.values()})
    statuses = sorted({s.status for s in subs.values()})
    matrix = [
        {'tier': t, 'cells': [sum(1 for s in subs.values() if tier_name(s.tier) == t and s.status == st) for st in statuses]}
        for t in tiers_seen
    ]
    renewals = sorted(
        (s for s in subs.values() if s.current_period_end and now <= s.current_period_end <= now + timedelta(days=30)),
        key=lambda s: s.current_period_end,
    )
    overrides = [
        s for s in subs.values()
        if s.programme_limit_override is not None or s.user_limit_override is not None
        or s.ai_credit_allowance_override_usd is not None
    ]

    def events():
        recent = BillingEvent.objects.filter(created_at__gte=since(days))
        return {
            'by_type': count_by(recent, 'event_type'),
            'by_outcome': count_by(recent, 'outcome'),
            'daily': daily(BillingEvent.objects.all(), days),
            'latest': list(BillingEvent.objects.order_by('-created_at')[:20]),
            'unprocessed': BillingEvent.objects.filter(processed_at__isnull=True).count(),
        }

    ev = src.fetch('identity', events)
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
        'problems': [s for s in subs.values() if s.status in PROBLEM_STATUSES or s.cancel_at_period_end],
        'seats': sum(s.seats or 0 for s in subs.values()),
        'stripe_linked': sum(1 for s in subs.values() if s.stripe_subscription_id),
        'paid': sum(1 for s in subs.values() if s.status == 'ACTIVE' and s.tier != 'POC'),
        'enterprise': sum(1 for s in subs.values() if s.tier == 'ENTERPRISE'),
    })


@view_required
def ai_usage(request):
    src = Sources()
    days = window(request, 30)
    x = labels(days)
    start = since(days)
    names = _org_names(src)
    subs = subscriptions(src)

    def agent():
        usage = AiUsageEvent.objects.all()
        recent = usage.filter(created_at__gte=start)
        runs = PlanRun.objects.filter(deleted_at__isnull=True)
        keys = OrgAiKey.objects.filter(deleted_at__isnull=True)
        return {
            'totals': recent.aggregate(cost=Sum('cost_usd'), prompt=Sum('prompt_tokens'),
                                       completion=Sum('completion_tokens'), calls=Count('id')),
            'orgs_using': recent.values('org_id').distinct().count(),
            'cost': daily(usage, days, Sum('cost_usd')),
            'prompt': daily(usage, days, Sum('prompt_tokens')),
            'completion': daily(usage, days, Sum('completion_tokens')),
            'by_model': count_by(recent, 'model', Sum('cost_usd')),
            'by_feature': count_by(recent, 'feature', Sum('cost_usd')),
            'calls_by_feature': count_by(recent, 'feature'),
            'mtd_by_org': count_by(usage.filter(created_at__gte=month_start()), 'org_id', Sum('cost_usd')),
            'runs_ok': daily(runs.exclude(status__in=['FAILED', 'failed', 'ERROR', 'error']), days),
            'runs_failed': daily(runs.filter(status__in=['FAILED', 'failed', 'ERROR', 'error']), days),
            'runs_by_status': count_by(runs.filter(created_at__gte=start), 'status'),
            'sessions': daily(AgentSession.objects.filter(deleted_at__isnull=True), days),
            'ingestion': count_by(IngestionLog.objects.filter(created_at__gte=start), 'status'),
            'keys_disabled': keys.filter(disabled=True).count(),
            'keys_stale': keys.filter(synced_at__lt=timezone.now() - timedelta(days=1)).count(),
            'keys': keys.count(),
        }

    ai = src.fetch('agent', agent)
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
    names = _org_names(src)
    member_org = _member_orgs(src)

    def authorization():
        decisions = AccessDecision.objects.filter(created_at__gte=start)
        pairs = list(decisions.annotate(day=TruncDate('created_at')).values_list('day', 'member_id').distinct())
        return {
            'pairs': pairs,
            'wau': AccessDecision.objects.filter(created_at__gte=since(7)).values('member_id').distinct().count(),
            'mau': AccessDecision.objects.filter(created_at__gte=since(30)).values('member_id').distinct().count(),
            'last_by_member': count_by(AccessDecision.objects.all(), 'member_id', Max('created_at')),
            'by_member': count_by(decisions, 'member_id'),
        }

    authz = src.fetch('authorization', authorization)
    charts = {}
    active_members = defaultdict(int)  # org -> distinct active members in window
    org_last = {}
    if authz:
        dau, dao = defaultdict(set), defaultdict(set)
        for day, member in authz['pairs']:
            dau[day].add(member)
            if member in member_org:
                dao[day].add(member_org[member])
        dates = day_range(days)
        charts['dau'] = chart('line', x, {
            'Active members': [len(dau[d]) for d in dates],
            'Active organizations': [len(dao[d]) for d in dates],
        })
        for member in authz['by_member']:
            if member in member_org:
                active_members[member_org[member]] += 1
        for member, when in authz['last_by_member'].items():
            org = member_org.get(member)
            if org and (org not in org_last or when > org_last[org]):
                org_last[org] = when

    audited = src.fetch('identity', lambda: count_by(AuditLog.objects.all(), 'org_id', Max('created_at')), {})
    live_docs = Document.objects.filter(deleted_at__isnull=True)
    docs = src.fetch('document', lambda: count_by(live_docs, 'organization_id'), {})
    docs_daily = src.fetch('document', lambda: daily(live_docs, days))
    programme_org = src.fetch('identity', lambda: dict(Programme.objects.values_list('id', 'org_id')), {})
    items_by_programme = src.fetch('planning', lambda: count_by(WorkItem.objects.filter(deleted_at__isnull=True), 'programme_id'), {})
    items_daily = src.fetch('planning', lambda: daily(WorkItem.objects.filter(deleted_at__isnull=True), days))
    ai_window = src.fetch('agent', lambda: count_by(AiUsageEvent.objects.filter(created_at__gte=start), 'org_id', Sum('cost_usd')), {})
    unread = src.fetch('notification', lambda: count_by(Notification.objects.filter(deleted_at__isnull=True, read=False), 'member_id'), {})

    items_by_org = defaultdict(int)
    for programme, n in items_by_programme.items():
        if programme in programme_org:
            items_by_org[programme_org[programme]] += n
    unread_by_org = defaultdict(int)
    for member, n in unread.items():
        if member in member_org:
            unread_by_org[member_org[member]] += n

    last_seen = latest(audited, org_last)
    cutoff = timezone.now() - timedelta(days=DORMANT_DAYS)
    rows = sorted(
        (
            {
                'org_id': org_id, 'name': name, 'last_seen': last_seen.get(org_id),
                'active_members': active_members.get(org_id, 0), 'docs': docs.get(org_id, 0),
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
    if docs_daily is not None:
        created['Documents'] = docs_daily
    if items_daily is not None:
        created['Work items'] = items_daily
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
    start = since(days)
    names = _org_names(src)
    member_org = _member_orgs(src)

    def authorization():
        decisions = AccessDecision.objects.filter(created_at__gte=start)
        denies = decisions.filter(effect='DENY')
        return {
            'total': decisions.count(),
            'denied': denies.count(),
            'allow': daily(AccessDecision.objects.filter(effect='ALLOW'), days),
            'deny': daily(AccessDecision.objects.filter(effect='DENY'), days),
            'deny_by_action': count_by(denies, 'action'),
            'deny_by_source': count_by(denies, 'source'),
            'allow_by_source': count_by(decisions.filter(effect='ALLOW'), 'source'),
            'top_denied': sorted(count_by(denies, 'member_id').items(), key=lambda kv: kv[1], reverse=True)[:15],
            'members': decisions.values('member_id').distinct().count(),
        }

    a = src.fetch('authorization', authorization)
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
