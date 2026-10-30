"""User data assembled from several services' admin queries."""

from collections import defaultdict

from servicedata.stats import fill, latest, series, since

from .selectors import person


def _matches(row, q):
    q = q.lower()
    user_id = row['user']['id']
    return any(q in (v or '').lower() for v in (user_id, user_id.replace('-', ''), row['name'], row['email']))


def user_rows(src, q='', org='', verified='', mfa=''):
    """One summary row per live user, newest first.

    ponytail: Identity returns every user and the search runs here; fine for
    thousands of users. Move search and paging into Identity's query beyond that.
    """
    d = src.query('identity', 'user_list', {'users': [], 'memberships': [], 'org_names': {}, 'member_last_audit': {}})
    checked = src.query('authorization', 'member_last_access', {})
    member_seen = latest(d['member_last_audit'], checked)
    org_names = d['org_names']

    by_user = defaultdict(list)
    for m in d['memberships']:
        by_user[m['user_id']].append(m)

    rows = []
    for u in d['users']:
        mine = by_user.get(u['id'], [])
        org_ids = list(dict.fromkeys(m['org_id'] for m in mine))
        if org and org not in org_ids:
            continue
        if verified and u['email_verified'] != (verified == 'yes'):
            continue
        if mfa and bool(u['mfa_method']) != (mfa == 'on'):
            continue
        seen = [member_seen[m['id']] for m in mine if m['id'] in member_seen]
        row = {
            'user': u,
            **person(u),
            'orgs': [(o, org_names.get(o, o)) for o in org_ids],
            'memberships': len(mine),
            'owner_of': sum(1 for m in mine if m['is_owner'] and not m['programme_id']),
            'last_seen': max(seen) if seen else None,
        }
        if q and not _matches(row, q):
            continue
        rows.append(row)
    return rows, sorted(org_names.items(), key=lambda kv: kv[1].lower())


def user_detail(src, user_id, days):
    """Everything the admin knows about one user. None if the user does not exist."""
    start = since(days)
    d = src.query('identity', 'user_detail', user_id=user_id, since=start)
    if d is None:
        return None
    member_ids = [m['id'] for m in d['members']]
    empty = not member_ids

    memberships = [
        {
            'm': m,
            'org': d['org_names'].get(m['org_id'], m['org_id']),
            'scope': d['programme_names'].get(m['programme_id'], 'Programme (deleted)') if m['programme_id'] else 'Organization',
        }
        for m in d['members']
    ]

    def ask(service, name, *daily, **params):
        if empty:
            return None
        return fill(src.query(service, name, member_ids=member_ids, **params), days, *daily)

    return {
        **d,
        **person(d['account']),
        'activity': series(d['activity'], days),
        'memberships': memberships,
        'org_count': len(d['org_names']),
        'access': ask('authorization', 'member_access', 'allow', 'deny', since=start),
        'ai': ask('agent', 'member_usage', 'daily_cost', since=start),
        'docs': ask('document', 'member_uploads', 'daily', since=start),
        'notes': ask('notification', 'member_notes'),
    }
