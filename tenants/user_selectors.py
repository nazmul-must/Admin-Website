"""User data assembled from several service databases."""

from collections import defaultdict

from django.db.models import Count, Max, Sum

from servicedata.models import (
    VERSION_BYTES,
    AccessDecision,
    AgentSession,
    AiUsageEvent,
    AuditLog,
    DocumentVersion,
    Member,
    Notification,
    Organization,
    PlanRun,
    Programme,
    User,
)
from servicedata.pii import reveal
from servicedata.stats import count_by, daily, latest, since


def _matches(row, q):
    q = q.lower()
    return any(q in (v or '').lower() for v in (row['user'].id, row['name'], row['email']))


def user_rows(src, q='', org='', verified='', mfa=''):
    """One summary row per live user, newest first.

    ponytail: decrypts every user to search name/email in Python; fine for
    thousands of users. Move search to Identity's admin API beyond that.
    """

    def identity():
        return (
            list(User.objects.filter(deleted_at__isnull=True).order_by('-created_at')),
            list(Member.objects.filter(deleted_at__isnull=True).values_list('id', 'user_id', 'org_id', 'programme_id', 'is_owner')),
            dict(Organization.objects.filter(deleted_at__isnull=True).values_list('id', 'name')),
            count_by(AuditLog.objects.exclude(member_id=None), 'member_id', Max('created_at')),
        )

    users, members, org_names, audited = src.fetch('identity', identity, ([], [], {}, {}))
    checked = src.fetch('authorization', lambda: count_by(AccessDecision.objects.all(), 'member_id', Max('created_at')), {})
    member_seen = latest(audited, checked)

    by_user = defaultdict(list)
    for member_id, user_id, org_id, programme_id, is_owner in members:
        by_user[user_id].append((member_id, org_id, programme_id, is_owner))

    rows = []
    for u in users:
        mine = by_user.get(u.id, [])
        org_ids = list(dict.fromkeys(o for _, o, _, _ in mine))
        if org and org not in org_ids:
            continue
        if verified and u.email_verified != (verified == 'yes'):
            continue
        if mfa and bool(u.mfa_method) != (mfa == 'on'):
            continue
        seen = [member_seen[m] for m, _, _, _ in mine if m in member_seen]
        row = {
            'user': u,
            **reveal(u),
            'orgs': [(o, org_names.get(o, o)) for o in org_ids],
            'memberships': len(mine),
            'owner_of': sum(1 for _, _, p, owner in mine if owner and not p),
            'last_seen': max(seen) if seen else None,
        }
        if q and not _matches(row, q):
            continue
        rows.append(row)
    return rows, sorted(org_names.items(), key=lambda kv: kv[1].lower())


def user_detail(src, user_id, days):
    """Everything the admin knows about one user. None if the user does not exist."""

    def identity():
        user = User.objects.filter(id=user_id).first()
        if user is None:
            return None
        members = list(Member.objects.filter(user_id=user_id, deleted_at__isnull=True).order_by('created_at'))
        ids = [m.id for m in members]
        return {
            'account': user,
            'members': members,
            'org_names': dict(Organization.objects.filter(id__in={m.org_id for m in members}).values_list('id', 'name')),
            'programme_names': dict(Programme.objects.filter(id__in={m.programme_id for m in members if m.programme_id}).values_list('id', 'name')),
            'actions_by': list(AuditLog.objects.filter(member_id__in=ids).order_by('-created_at')[:25]),
            'changes_to': list(AuditLog.objects.filter(target_id__in=[*ids, user_id]).order_by('-created_at')[:15]),
            'activity': daily(AuditLog.objects.filter(member_id__in=ids), days),
        }

    d = src.fetch('identity', identity)
    if d is None:
        return None
    member_ids = [m.id for m in d['members']]
    start = since(days)
    empty = not member_ids

    memberships = [
        {
            'm': m,
            'org': d['org_names'].get(m.org_id, m.org_id),
            'scope': d['programme_names'].get(m.programme_id, 'Programme (deleted)') if m.programme_id else 'Organization',
        }
        for m in d['members']
    ]

    def authorization():
        decisions = AccessDecision.objects.filter(member_id__in=member_ids)
        return {
            'allow': daily(decisions.filter(effect='ALLOW'), days),
            'deny': daily(decisions.filter(effect='DENY'), days),
            'deny_by_action': count_by(decisions.filter(effect='DENY', created_at__gte=start), 'action'),
            'total': decisions.filter(created_at__gte=start).count(),
            'last': decisions.aggregate(last=Max('created_at'))['last'],
        }

    def agent():
        usage = AiUsageEvent.objects.filter(member_id__in=member_ids)
        recent = usage.filter(created_at__gte=start)
        return {
            'window': recent.aggregate(cost=Sum('cost_usd'), calls=Count('id'),
                                       prompt=Sum('prompt_tokens'), completion=Sum('completion_tokens')),
            'daily_cost': daily(usage, days, Sum('cost_usd')),
            'by_feature': count_by(recent, 'feature', Sum('cost_usd')),
            'sessions': AgentSession.objects.filter(member_id__in=member_ids, deleted_at__isnull=True).count(),
            'plan_runs': count_by(PlanRun.objects.filter(member_id__in=member_ids, deleted_at__isnull=True), 'status'),
        }

    def document():
        versions = DocumentVersion.objects.filter(created_by__in=member_ids, deleted_at__isnull=True)
        return {
            'uploads': versions.count(),
            'bytes': versions.aggregate(b=Sum(VERSION_BYTES))['b'] or 0,
            'daily': daily(versions, days),
        }

    def notification():
        notes = Notification.objects.filter(member_id__in=member_ids, deleted_at__isnull=True)
        return {'total': notes.count(), 'unread': notes.filter(read=False).count(), 'by_channel': count_by(notes, 'channel')}

    return {
        **d,
        **reveal(d['account']),
        'memberships': memberships,
        'org_count': len(d['org_names']),
        'access': None if empty else src.fetch('authorization', authorization),
        'ai': None if empty else src.fetch('agent', agent),
        'docs': None if empty else src.fetch('document', document),
        'notes': None if empty else src.fetch('notification', notification),
    }
