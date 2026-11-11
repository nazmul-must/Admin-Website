"""Organization data assembled from several services' admin queries."""

from typing import Any

from servicedata.contracts import Member, OrgDetail, Programme, Subscription, User
from servicedata.stats import Sources, fill_series, latest, month_start, pct, series, since
from servicedata.tiers import CREDITS_PER_USD, limits, tier_name

NO_PLAN = {"count": 0, "by_programme": {}, "by_type": {}, "by_rag": {}}
NO_NOTES = {"total": 0, "unread": 0}


def person(user: User | None) -> dict[str, Any]:
    """Template fields for a user: Identity returns names/emails decrypted, or null when it can't."""
    name = user["name"] if user else None
    return {"name": name, "email": user["email"] if user else None, "decrypted": name is not None}


def scope_label(programme_id: str | None, programme_names: dict[str, str]) -> str:
    """What a membership covers: the whole organization, or one programme."""
    if not programme_id:
        return "Organization"
    return programme_names.get(programme_id, "Programme (deleted)")


def _matches_filters(sub: Subscription | None, tier: str, status: str) -> bool:
    """Whether an org's subscription passes the tier and status filters (empty = any)."""
    if tier and (sub is None or sub["tier"] != tier):
        return False
    return not (status and (sub is None or sub["status"] != status))


def org_rows(
    src: Sources, subs: dict[str, Subscription], q: str = "", tier: str = "", status: str = ""
) -> list[dict[str, Any]]:
    """One summary row per live organization, newest first. `subs` is subscriptions(src)."""
    orgs = src.query("identity", "org_list", [], q=q)
    month = month_start()
    ai = src.query("agent", "org_usage", {}, since=month)
    docs = src.query("document", "summary", {}, since=month)
    cost_by_org = ai.get("cost_by_org", {})
    docs_by_org = docs.get("by_org", {})
    last_seen = latest(
        {r["org"]["id"]: r["last_audit"] for r in orgs},
        ai.get("last_by_org", {}),
        docs.get("last_by_org", {}),
    )

    rows = []
    for r in orgs:
        org = r["org"]
        sub = subs.get(org["id"])
        if not _matches_filters(sub, tier, status):
            continue
        lim = limits(sub)
        spent = cost_by_org.get(org["id"]) or 0
        rows.append(
            {
                "org": org,
                "sub": sub,
                "tier": tier_name(sub["tier"] if sub else None),
                "users": r["users"],
                "user_limit": lim["users"],
                "programmes": r["programmes"],
                "programme_limit": lim["programmes"],
                "ai_usd": spent,
                "ai_pct": pct(spent, lim["ai_usd"]),
                "docs": docs_by_org.get(org["id"], 0),
                "last_seen": last_seen.get(org["id"]),
            }
        )
    return rows


def _people(identity: OrgDetail) -> list[dict[str, Any]]:
    """One row per membership, with the member's user and what the membership covers."""
    programme_names = {p["id"]: p["name"] for p in identity["programmes"]}
    people = []
    for m in identity["members"]:
        user = identity["users"].get(m["user_id"])
        people.append(
            {
                "m": m,
                "user": user,
                **person(user),
                "scope": scope_label(m["programme_id"], programme_names),
                "email_verified": user["email_verified"] if user else None,
                "mfa": user["mfa_method"] if user else None,
            }
        )
    return people


def _other_services(
    src: Sources, org_id: str, identity: OrgDetail, days: int, period_start: Any
) -> dict[str, Any]:
    """AI, documents, planning, access and notifications for one org. A key is None when
    its service is down."""
    window_start = since(days)
    member_ids = [m["id"] for m in identity["members"]]
    programme_ids = [p["id"] for p in identity["programmes"]]
    ai = src.query(
        "agent", "org_detail", org_id=org_id, since=window_start, period_start=period_start
    )
    docs = src.query("document", "org_detail", org_id=org_id, since=window_start)
    plan = NO_PLAN
    if programme_ids:
        plan = src.query("planning", "programme_items", programme_ids=programme_ids)
    access, notes = None, NO_NOTES
    if member_ids:
        access = src.query(
            "authorization", "member_access", member_ids=member_ids, since=window_start
        )
        notes = src.query("notification", "member_notes", member_ids=member_ids)
    return {
        "ai": fill_series(ai, days, "daily_cost"),
        "docs": fill_series(docs, days, "daily"),
        "plan": plan,
        "access": fill_series(access, days, "allow", "deny"),
        "notes": notes,
    }


def _usage(
    lim: dict[str, Any], users: int, programmes: int, ai: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Limits vs usage bars: users, programmes and (when Agent is up) AI credits this period."""
    usage = [
        {"label": "Users", "used": users, "limit": lim["users"], "pct": pct(users, lim["users"])},
        {
            "label": "Programmes",
            "used": programmes,
            "limit": lim["programmes"],
            "pct": pct(programmes, lim["programmes"]),
        },
    ]
    if ai is not None:
        used = ai["period"]["cost"] or 0
        allowance = lim["ai_usd"]
        usage.append(
            {
                "label": "AI credits (this period)",
                "used": round(used * CREDITS_PER_USD),
                "limit": round(allowance * CREDITS_PER_USD) if allowance is not None else None,
                "pct": pct(used, allowance),
            }
        )
    return usage


def _programme_rows(
    programmes: list[Programme], members: list[Member], services: dict[str, Any]
) -> list[dict[str, Any]]:
    """Per-programme members, work items and documents."""
    plan, docs = services["plan"], services["docs"]
    return [
        {
            "p": p,
            "members": sum(1 for m in members if m["programme_id"] == p["id"]),
            "work_items": plan["by_programme"].get(p["id"], 0) if plan else None,
            "docs": docs["by_programme"].get(p["id"], 0) if docs else None,
        }
        for p in programmes
    ]


def org_detail(src: Sources, org_id: str, days: int) -> dict[str, Any] | None:
    """Everything the admin knows about one organization. None if it does not exist."""
    identity = src.query("identity", "org_detail", org_id=org_id, since=since(days))
    if identity is None:
        return None
    sub, members, programmes = identity["subscription"], identity["members"], identity["programmes"]
    period_start = (sub["current_period_start"] if sub else None) or month_start()
    services = _other_services(src, org_id, identity, days, period_start)
    lim = limits(sub)
    user_count = len({m["user_id"] for m in members})
    return {
        **identity,
        **services,
        "sub": sub,
        "activity": series(identity["activity"], days),
        "tier": tier_name(sub["tier"] if sub else None),
        "limits": lim,
        "usage": _usage(lim, user_count, len(programmes), services["ai"]),
        "people": _people(identity),
        "user_count": user_count,
        "owners": sum(1 for m in members if m["is_owner"] and not m["programme_id"]),
        "external": sum(1 for m in members if m["is_external"]),
        "programme_rows": _programme_rows(programmes, members, services),
        "period_start": period_start,
    }
