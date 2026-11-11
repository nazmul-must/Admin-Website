"""User data assembled from several services' admin queries."""

from collections import defaultdict
from typing import Any

from servicedata.contracts import Membership, User
from servicedata.stats import Sources, fill_series, latest, series, since

from .selectors import person, scope_label

NO_USERS = {"users": [], "memberships": [], "org_names": {}, "member_last_audit": {}}


def _matches_search(row: dict[str, Any], q: str) -> bool:
    """Whether the search text is in the user's id (dashed or hex), name or email."""
    q = q.lower()
    user_id = row["user"]["id"]
    fields = (user_id, user_id.replace("-", ""), row["name"], row["email"])
    return any(q in (v or "").lower() for v in fields)


def _matches_filters(user: User, org_ids: list[str], org: str, verified: str, mfa: str) -> bool:
    """Whether a user passes the org, email-verified and MFA filters (empty = any)."""
    if org and org not in org_ids:
        return False
    if verified and user["email_verified"] != (verified == "yes"):
        return False
    return not (mfa and bool(user["mfa_method"]) != (mfa == "on"))


def _user_row(
    user: User, mine: list[Membership], org_names: dict[str, str], member_seen: dict[str, Any]
) -> dict[str, Any]:
    """One users-list row: orgs, membership counts and last activity."""
    org_ids = list(dict.fromkeys(m["org_id"] for m in mine))
    seen = [member_seen[m["id"]] for m in mine if m["id"] in member_seen]
    return {
        "user": user,
        **person(user),
        "org_ids": org_ids,
        "orgs": [(o, org_names.get(o, o)) for o in org_ids],
        "memberships": len(mine),
        "owner_of": sum(1 for m in mine if m["is_owner"] and not m["programme_id"]),
        "last_seen": max(seen) if seen else None,
    }


def user_rows(
    src: Sources, q: str = "", org: str = "", verified: str = "", mfa: str = ""
) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    """One summary row per live user, newest first, and the (id, name) org filter options.

    ponytail: Identity returns every user and the search runs here; fine for
    thousands of users. Move search and paging into Identity's query beyond that.
    """
    directory = src.query("identity", "user_list", NO_USERS)
    checked = src.query("authorization", "member_last_access", {})
    member_seen = latest(directory["member_last_audit"], checked)
    org_names = directory["org_names"]

    by_user: dict[str, list[Membership]] = defaultdict(list)
    for m in directory["memberships"]:
        by_user[m["user_id"]].append(m)

    rows = []
    for user in directory["users"]:
        row = _user_row(user, by_user.get(user["id"], []), org_names, member_seen)
        if not _matches_filters(user, row["org_ids"], org, verified, mfa):
            continue
        if q and not _matches_search(row, q):
            continue
        rows.append(row)
    return rows, sorted(org_names.items(), key=lambda kv: kv[1].lower())


def user_detail(src: Sources, user_id: str, days: int) -> dict[str, Any] | None:
    """Everything the admin knows about one user. None if the user does not exist."""
    start = since(days)
    identity = src.query("identity", "user_detail", user_id=user_id, since=start)
    if identity is None:
        return None
    member_ids = [m["id"] for m in identity["members"]]

    def member_query(service: str, name: str, *daily: str, **params: Any) -> dict[str, Any] | None:
        """One service's data for the user's members; None with no members or when it is down."""
        if not member_ids:
            return None
        return fill_series(src.query(service, name, member_ids=member_ids, **params), days, *daily)

    memberships = [
        {
            "m": m,
            "org": identity["org_names"].get(m["org_id"], m["org_id"]),
            "scope": scope_label(m["programme_id"], identity["programme_names"]),
        }
        for m in identity["members"]
    ]
    return {
        **identity,
        **person(identity["account"]),
        "activity": series(identity["activity"], days),
        "memberships": memberships,
        "org_count": len(identity["org_names"]),
        "access": member_query("authorization", "member_access", "allow", "deny", since=start),
        "ai": member_query("agent", "member_usage", "daily_cost", since=start),
        "docs": member_query("document", "member_uploads", "daily", since=start),
        "notes": member_query("notification", "member_notes"),
    }
