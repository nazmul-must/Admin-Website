"""Organization data assembled from several service databases."""

from django.db.models import Count, Max, Q, Sum

from servicedata.models import (
    VERSION_BYTES,
    AccessDecision,
    AgentSession,
    AiUsageEvent,
    AuditLog,
    Document,
    DocumentVersion,
    IngestionLog,
    Member,
    Notification,
    Organization,
    OrgAiKey,
    PlanRun,
    Programme,
    Subscription,
    User,
    WorkItem,
)
from servicedata.pii import reveal
from servicedata.stats import count_by, daily, latest, month_start, pct, since
from servicedata.tiers import CREDITS_PER_USD, limits, tier_name


def subscriptions(src):
    return src.fetch(
        'identity',
        lambda: {s.org_id: s for s in Subscription.objects.filter(deleted_at__isnull=True)},
        {},
    )


def org_rows(src, q='', tier='', status=''):
    """One summary row per live organization, newest first."""

    def identity():
        orgs = Organization.objects.filter(deleted_at__isnull=True).order_by('-created_at')
        if q:
            orgs = orgs.filter(
                Q(name__icontains=q) | Q(subdomain__icontains=q) | Q(id=q.replace('-', '').lower())
            )
        live = Member.objects.filter(deleted_at__isnull=True)
        return (
            list(orgs),
            count_by(live, 'org_id', Count('user_id', distinct=True)),
            count_by(Programme.objects.filter(deleted_at__isnull=True), 'org_id'),
            count_by(AuditLog.objects.all(), 'org_id', Max('created_at')),
        )

    orgs, users, programmes, audited = src.fetch('identity', identity, ([], {}, {}, {}))
    subs = subscriptions(src)
    month = month_start()
    ai = src.fetch(
        'agent',
        lambda: count_by(AiUsageEvent.objects.filter(created_at__gte=month), 'org_id', Sum('cost_usd')),
        {},
    )
    ai_seen = src.fetch('agent', lambda: count_by(AiUsageEvent.objects.all(), 'org_id', Max('created_at')), {})
    live_docs = Document.objects.filter(deleted_at__isnull=True)
    docs = src.fetch('document', lambda: count_by(live_docs, 'organization_id'), {})
    docs_seen = src.fetch('document', lambda: count_by(live_docs, 'organization_id', Max('updated_at')), {})
    last_seen = latest(audited, ai_seen, docs_seen)

    rows = []
    for org in orgs:
        sub = subs.get(org.id)
        if tier and (sub is None or sub.tier != tier):
            continue
        if status and (sub is None or sub.status != status):
            continue
        lim = limits(sub)
        spent = ai.get(org.id) or 0
        rows.append({
            'org': org,
            'sub': sub,
            'tier': tier_name(sub.tier if sub else None),
            'users': users.get(org.id, 0),
            'user_limit': lim['users'],
            'programmes': programmes.get(org.id, 0),
            'programme_limit': lim['programmes'],
            'ai_usd': spent,
            'ai_pct': pct(spent, lim['ai_usd']),
            'docs': docs.get(org.id, 0),
            'last_seen': last_seen.get(org.id),
        })
    return rows


def org_detail(src, org_id, days):
    """Everything the admin knows about one organization. None if it does not exist."""

    def identity():
        org = Organization.objects.filter(id=org_id).first()
        if org is None:
            return None
        members = list(Member.objects.filter(org_id=org_id, deleted_at__isnull=True).order_by('created_at'))
        return {
            'org': org,
            'parent': Organization.objects.filter(id=org.parent_id).first() if org.parent_id else None,
            'children': list(Organization.objects.filter(parent_id=org_id, deleted_at__isnull=True)),
            'sub': Subscription.objects.filter(org_id=org_id, deleted_at__isnull=True).first(),
            'members': members,
            'users': {u.id: u for u in User.objects.filter(id__in={m.user_id for m in members})},
            'programmes': list(Programme.objects.filter(org_id=org_id, deleted_at__isnull=True).order_by('created_at')),
            'audit': list(AuditLog.objects.filter(org_id=org_id).order_by('-created_at')[:25]),
            'activity': daily(AuditLog.objects.filter(org_id=org_id), days),
        }

    d = src.fetch('identity', identity)
    if d is None:
        return None
    sub, members, programmes = d['sub'], d['members'], d['programmes']
    member_ids = [m.id for m in members]
    programme_ids = [p.id for p in programmes]
    programme_names = {p.id: p.name for p in programmes}
    window_start = since(days)

    # --- people ---
    people = []
    for m in members:
        u = d['users'].get(m.user_id)
        people.append({
            'm': m,
            'user': u,
            **reveal(u),
            'scope': programme_names.get(m.programme_id, 'Programme (deleted)') if m.programme_id else 'Organization',
            'email_verified': u.email_verified if u else None,
            'mfa': u.mfa_method if u else None,
        })
    user_count = len({m.user_id for m in members})

    # --- AI ---
    period_start = (sub.current_period_start if sub else None) or month_start()

    def agent():
        usage = AiUsageEvent.objects.filter(org_id=org_id)
        recent = usage.filter(created_at__gte=window_start)
        return {
            'period': usage.filter(created_at__gte=period_start).aggregate(
                cost=Sum('cost_usd'), prompt=Sum('prompt_tokens'),
                completion=Sum('completion_tokens'), calls=Count('id'),
            ),
            'lifetime': usage.aggregate(cost=Sum('cost_usd'), calls=Count('id')),
            'daily_cost': daily(usage, days, Sum('cost_usd')),
            'by_feature': count_by(recent, 'feature', Sum('cost_usd')),
            'by_model': count_by(recent, 'model', Sum('cost_usd')),
            'key': OrgAiKey.objects.filter(org_id=org_id, deleted_at__isnull=True).first(),
            'plan_runs': count_by(PlanRun.objects.filter(org_id=org_id, deleted_at__isnull=True), 'status'),
            'sessions': AgentSession.objects.filter(org_id=org_id, deleted_at__isnull=True).count(),
            'ingestion': count_by(IngestionLog.objects.filter(org_id=org_id), 'status'),
        }

    ai = src.fetch('agent', agent)

    # --- documents ---
    def document():
        docs = Document.objects.filter(organization_id=org_id, deleted_at__isnull=True)
        versions = DocumentVersion.objects.filter(document_id__in=docs.values('id'), deleted_at__isnull=True)
        return {
            'count': docs.count(),
            'by_programme': count_by(docs, 'programme_id'),
            'versions': versions.count(),
            'bytes': versions.aggregate(b=Sum(VERSION_BYTES))['b'] or 0,
            'daily': daily(docs, days),
        }

    docs = src.fetch('document', document)

    # --- planning ---
    def planning():
        items = WorkItem.objects.filter(programme_id__in=programme_ids, deleted_at__isnull=True)
        return {
            'count': items.count(),
            'by_programme': count_by(items, 'programme_id'),
            'by_type': count_by(items, 'type'),
            'by_rag': count_by(items, 'rag'),
        }

    plan = src.fetch('planning', planning) if programme_ids else {'count': 0, 'by_programme': {}, 'by_type': {}, 'by_rag': {}}

    # --- access ---
    def authorization():
        decisions = AccessDecision.objects.filter(member_id__in=member_ids)
        return {
            'allow': daily(decisions.filter(effect='ALLOW'), days),
            'deny': daily(decisions.filter(effect='DENY'), days),
            'deny_by_action': count_by(decisions.filter(effect='DENY', created_at__gte=window_start), 'action'),
            'last': decisions.aggregate(last=Max('created_at'))['last'],
        }

    access = src.fetch('authorization', authorization) if member_ids else None

    def notification():
        notes = Notification.objects.filter(member_id__in=member_ids, deleted_at__isnull=True)
        return {'total': notes.count(), 'unread': notes.filter(read=False).count()}

    notes = src.fetch('notification', notification) if member_ids else {'total': 0, 'unread': 0}

    # --- limits vs usage ---
    lim = limits(sub)
    ai_used = (ai['period']['cost'] or 0) if ai else None
    usage = [
        {'label': 'Users', 'used': user_count, 'limit': lim['users'], 'pct': pct(user_count, lim['users'])},
        {'label': 'Programmes', 'used': len(programmes), 'limit': lim['programmes'], 'pct': pct(len(programmes), lim['programmes'])},
    ]
    if ai_used is not None:
        usage.append({
            'label': 'AI credits (this period)',
            'used': round(ai_used * CREDITS_PER_USD),
            'limit': round(lim['ai_usd'] * CREDITS_PER_USD) if lim['ai_usd'] is not None else None,
            'pct': pct(ai_used, lim['ai_usd']),
        })

    programme_rows = [
        {
            'p': p,
            'members': sum(1 for m in members if m.programme_id == p.id),
            'work_items': plan['by_programme'].get(p.id, 0) if plan else None,
            'docs': docs['by_programme'].get(p.id, 0) if docs else None,
        }
        for p in programmes
    ]

    return {
        **d,
        'tier': tier_name(sub.tier if sub else None),
        'limits': lim,
        'usage': usage,
        'people': people,
        'user_count': user_count,
        'owners': sum(1 for m in members if m.is_owner and not m.programme_id),
        'external': sum(1 for m in members if m.is_external),
        'programme_rows': programme_rows,
        'period_start': period_start,
        'ai': ai,
        'docs': docs,
        'plan': plan,
        'access': access,
        'notes': notes,
    }
