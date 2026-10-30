"""Organization data assembled from several services' admin queries."""

from servicedata.stats import fill, latest, month_start, pct, series, since
from servicedata.tiers import CREDITS_PER_USD, limits, tier_name


def person(user):
    """Template fields for a user: Identity returns names/emails decrypted, or null when it can't."""
    name = user['name'] if user else None
    return {'name': name, 'email': user['email'] if user else None, 'decrypted': name is not None}


def subscriptions(src):
    return {s['org_id']: s for s in src.query('identity', 'subscriptions', [])}


def org_rows(src, subs, q='', tier='', status=''):
    """One summary row per live organization, newest first. `subs` is subscriptions(src)."""
    orgs = src.query('identity', 'org_list', [], q=q)
    month = month_start()
    ai = src.query('agent', 'org_usage', {}, since=month)
    docs = src.query('document', 'summary', {}, since=month)
    cost_by_org = ai.get('cost_by_org', {})
    docs_by_org = docs.get('by_org', {})
    last_seen = latest(
        {r['org']['id']: r['last_audit'] for r in orgs},
        ai.get('last_by_org', {}),
        docs.get('last_by_org', {}),
    )

    rows = []
    for r in orgs:
        org = r['org']
        sub = subs.get(org['id'])
        if tier and (sub is None or sub['tier'] != tier):
            continue
        if status and (sub is None or sub['status'] != status):
            continue
        lim = limits(sub)
        spent = cost_by_org.get(org['id']) or 0
        rows.append({
            'org': org,
            'sub': sub,
            'tier': tier_name(sub['tier'] if sub else None),
            'users': r['users'],
            'user_limit': lim['users'],
            'programmes': r['programmes'],
            'programme_limit': lim['programmes'],
            'ai_usd': spent,
            'ai_pct': pct(spent, lim['ai_usd']),
            'docs': docs_by_org.get(org['id'], 0),
            'last_seen': last_seen.get(org['id']),
        })
    return rows


def org_detail(src, org_id, days):
    """Everything the admin knows about one organization. None if it does not exist."""
    window_start = since(days)
    d = src.query('identity', 'org_detail', org_id=org_id, since=window_start)
    if d is None:
        return None
    sub, members, programmes = d['subscription'], d['members'], d['programmes']
    member_ids = [m['id'] for m in members]
    programme_ids = [p['id'] for p in programmes]
    programme_names = {p['id']: p['name'] for p in programmes}

    # --- people ---
    people = []
    for m in members:
        u = d['users'].get(m['user_id'])
        people.append({
            'm': m,
            'user': u,
            **person(u),
            'scope': programme_names.get(m['programme_id'], 'Programme (deleted)') if m['programme_id'] else 'Organization',
            'email_verified': u['email_verified'] if u else None,
            'mfa': u['mfa_method'] if u else None,
        })
    user_count = len({m['user_id'] for m in members})

    # --- other services ---
    period_start = (sub['current_period_start'] if sub else None) or month_start()
    ai = fill(src.query('agent', 'org_detail', org_id=org_id, since=window_start, period_start=period_start), days, 'daily_cost')
    docs = fill(src.query('document', 'org_detail', org_id=org_id, since=window_start), days, 'daily')
    plan = (
        src.query('planning', 'programme_items', programme_ids=programme_ids) if programme_ids
        else {'count': 0, 'by_programme': {}, 'by_type': {}, 'by_rag': {}}
    )
    access = fill(
        src.query('authorization', 'member_access', member_ids=member_ids, since=window_start), days, 'allow', 'deny',
    ) if member_ids else None
    notes = src.query('notification', 'member_notes', member_ids=member_ids) if member_ids else {'total': 0, 'unread': 0}

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
            'members': sum(1 for m in members if m['programme_id'] == p['id']),
            'work_items': plan['by_programme'].get(p['id'], 0) if plan else None,
            'docs': docs['by_programme'].get(p['id'], 0) if docs else None,
        }
        for p in programmes
    ]

    return {
        **d,
        'sub': sub,
        'activity': series(d['activity'], days),
        'tier': tier_name(sub['tier'] if sub else None),
        'limits': lim,
        'usage': usage,
        'people': people,
        'user_count': user_count,
        'owners': sum(1 for m in members if m['is_owner'] and not m['programme_id']),
        'external': sum(1 for m in members if m['is_external']),
        'programme_rows': programme_rows,
        'period_start': period_start,
        'ai': ai,
        'docs': docs,
        'plan': plan,
        'access': access,
        'notes': notes,
    }
