"""Platform analytics data assembled from several services' admin queries.

Views turn these results into charts; nothing here renders.
"""

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

from servicedata.contracts import Directory, Subscription
from servicedata.stats import Sources, day_range, fill_series, latest, month_start, pct, since
from servicedata.tiers import limits, subscriptions, tier_name, usage_level

PROBLEM_STATUSES = {
    "PAST_DUE",
    "UNPAID",
    "INCOMPLETE",
    "INCOMPLETE_EXPIRED",
    "CANCELED",
    "CANCELLED",
}
FAILED_RUN_STATUSES = ("failed", "error")
DORMANT_DAYS = 14
ENDING_SOON_DAYS = 7
RENEWAL_DAYS = 30
TOP_ORGS = 15
NO_DIRECTORY = {"org_names": {}, "member_orgs": {}, "programme_orgs": {}, "org_last_audit": {}}


def directory(src: Sources) -> Directory:
    """Identity's id lookups (all orgs, deleted too); empty maps while Identity is down."""
    return src.query("identity", "directory", NO_DIRECTORY)


def is_paid(sub: Subscription) -> bool:
    """An active subscription on a paid tier (POC is free)."""
    return sub["status"] == "ACTIVE" and sub["tier"] != "POC"


def is_problem(sub: Subscription) -> bool:
    """A subscription in a failed or cancelled state."""
    return sub["status"] in PROBLEM_STATUSES


def _subscription_alerts(sub: Subscription, now: datetime) -> list[tuple[str, str]]:
    """(reason, level) pairs for a subscription that needs an operator's eye."""
    alerts = []
    if is_problem(sub):
        alerts.append((f"Subscription {sub['status'].lower()}", "red"))
    end = sub["current_period_end"]
    if sub["cancel_at_period_end"]:
        alerts.append((f"Cancels on {end:%Y-%m-%d}" if end else "Cancels at period end", "red"))
    elif end and now <= end <= now + timedelta(days=ENDING_SOON_DAYS):
        alerts.append((f"Period ends {end:%Y-%m-%d}", "amber"))
    return alerts


def attention(
    names: dict[str, str], subs: dict[str, Subscription], month_ai: dict[str, float]
) -> list[dict[str, str]]:
    """Organizations an operator should look at now. `month_ai` = {org_id: AI USD this month}."""
    now = timezone.now()
    items = []
    for org_id, sub in subs.items():
        alerts = _subscription_alerts(sub, now)
        used = pct(month_ai.get(org_id), limits(sub)["ai_usd"])
        level = usage_level(used)
        if level:
            alerts.append((f"AI credits at {used}% of allowance", level))
        name = names.get(org_id, org_id)
        items += [{"org_id": org_id, "name": name, "reason": r, "level": lvl} for r, lvl in alerts]
    return items


def overview(src: Sources, days: int) -> dict[str, Any]:
    """Platform totals, signups, subscription mix and the needs-attention list."""
    identity = src.query("identity", "overview", since=since(days), recent=since(30))
    subs = subscriptions(src)
    month_ai = src.query("agent", "org_usage", since=month_start())
    docs = src.query("document", "summary", since=since(days))
    items = src.query("planning", "summary", since=since(days))
    cost_by_org = month_ai["cost_by_org"] if month_ai else {}
    tier_mix: dict[str, int] = defaultdict(int)
    status_mix: dict[str, int] = defaultdict(int)
    for s in subs.values():
        tier_mix[tier_name(s["tier"])] += 1
        status_mix[s["status"].lower()] += 1
    return {
        "idn": fill_series(identity, days, "org_daily"),
        "subs": subs,
        "tier_mix": dict(tier_mix),
        "status_mix": dict(status_mix),
        "paid": sum(1 for s in subs.values() if is_paid(s)),
        "past_due": sum(1 for s in subs.values() if is_problem(s)),
        "ai_mtd": sum(v or 0 for v in cost_by_org.values()) if month_ai else None,
        "docs": docs["total"] if docs else None,
        "items": items["total"] if items else None,
        "attention": attention(directory(src)["org_names"], subs, cost_by_org),
    }


def _funnel(src: Sources, growth: dict[str, Any], start: datetime) -> list[dict[str, Any]]:
    """Activation funnel: how many orgs reached each step, out of all live orgs."""
    programme_org = directory(src)["programme_orgs"]
    work_programmes = src.query("planning", "summary", {}, since=start).get("by_programme", {})
    with_docs = src.query("document", "summary", {}, since=start).get("by_org", {})
    with_ai = src.query("agent", "org_usage", {}, since=start).get("last_by_org", {})
    all_orgs = set(growth["all_orgs"])
    steps = [
        ("Signed up", all_orgs),
        ("Invited a 2nd user", set(growth["multi_user"])),
        ("Created a programme", set(growth["with_programme"])),
        ("Planned work items", {programme_org.get(p) for p in work_programmes}),
        ("Uploaded documents", set(with_docs)),
        ("Used AI", set(with_ai)),
    ]
    funnel = []
    for label, ids in steps:
        reached = len(ids & all_orgs)
        funnel.append({"label": label, "n": reached, "pct": pct(reached, len(all_orgs))})
    return funnel


def growth(src: Sources, days: int) -> dict[str, Any]:
    """Signup series and the activation funnel; `idn` is None while Identity is down."""
    start = since(days)
    identity = src.query("identity", "growth", since=start)
    series = fill_series(identity, days, "orgs", "users", "members", "programmes")
    return {"idn": series, "funnel": _funnel(src, series, start) if series else []}


def _tier_status_matrix(
    subs: Iterable[Subscription], statuses: list[str]
) -> tuple[list[str], list[dict[str, Any]]]:
    """Tier names seen, and one row per tier counting its subscriptions per status."""
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for s in subs:
        counts[(tier_name(s["tier"]), s["status"])] += 1
    tiers_seen = sorted({tier for tier, _ in counts})
    matrix = [{"tier": t, "cells": [counts[(t, st)] for st in statuses]} for t in tiers_seen]
    return tiers_seen, matrix


def _has_override(sub: Subscription) -> bool:
    """Whether any of the subscription's limits is overridden for this org."""
    overrides = (
        "programme_limit_override",
        "user_limit_override",
        "ai_credit_allowance_override_usd",
    )
    return any(sub[key] is not None for key in overrides)


def _renews_soon(sub: Subscription, now: datetime) -> bool:
    """Whether the subscription's period ends within RENEWAL_DAYS."""
    end = sub["current_period_end"]
    return bool(end and now <= end <= now + timedelta(days=RENEWAL_DAYS))


def billing(src: Sources, days: int) -> dict[str, Any]:
    """Subscription mix, renewals, problem subscriptions, overrides and Stripe events."""
    subs = subscriptions(src)
    rows = list(subs.values())
    now = timezone.now()
    statuses = sorted({s["status"] for s in rows})
    tiers_seen, matrix = _tier_status_matrix(rows, statuses)
    events = src.query("identity", "billing_events", since=since(days))
    return {
        "subs": subs,
        "names": directory(src)["org_names"],
        "ev": fill_series(events, days, "daily"),
        "statuses": statuses,
        "tiers_seen": tiers_seen,
        "matrix": matrix,
        "renewals": sorted(
            (s for s in rows if _renews_soon(s, now)), key=lambda s: s["current_period_end"] or now
        ),
        "overrides": [s for s in rows if _has_override(s)],
        "problems": [s for s in rows if is_problem(s) or s["cancel_at_period_end"]],
        "seats": sum(s["seats"] or 0 for s in rows),
        "stripe_linked": sum(1 for s in rows if s["stripe_subscription_id"]),
        "paid": sum(1 for s in rows if is_paid(s)),
        "enterprise": sum(1 for s in rows if s["tier"] == "ENTERPRISE"),
    }


def _top_ai_orgs(
    mtd_by_org: dict[str, float], names: dict[str, str], subs: dict[str, Subscription]
) -> list[dict[str, Any]]:
    """The orgs that spent most AI this month, against their allowance."""
    top = []
    for org_id, usd in sorted(mtd_by_org.items(), key=lambda kv: kv[1] or 0, reverse=True)[
        :TOP_ORGS
    ]:
        allowance = limits(subs.get(org_id))["ai_usd"]
        top.append(
            {
                "org_id": org_id,
                "name": names.get(org_id, org_id),
                "usd": usd,
                "allowance": allowance,
                "pct": pct(usd, allowance),
            }
        )
    return top


def ai_usage(src: Sources, days: int) -> dict[str, Any]:
    """Agent's AI dashboard plus the top-spending orgs; `ai` is None while Agent is down."""
    names = directory(src)["org_names"]
    subs = subscriptions(src)
    dashboard = src.query(
        "agent",
        "dashboard",
        since=since(days),
        month_start=month_start(),
        stale_before=timezone.now() - timedelta(days=1),
    )
    ai = fill_series(
        dashboard, days, "cost", "prompt", "completion", "runs_ok", "runs_failed", "sessions"
    )
    if ai is None:
        return {"ai": None, "top": []}
    runs = ai["runs_by_status"]
    failed = sum(n for s, n in runs.items() if (s or "").lower() in FAILED_RUN_STATUSES)
    ai["run_failure_pct"] = pct(failed, sum(runs.values()))
    return {"ai": ai, "top": _top_ai_orgs(ai["mtd_by_org"], names, subs)}


def _sum_by_org(counts: dict[str, int], org_of: dict[str, str | None]) -> dict[str, int]:
    """Roll per-member or per-programme counts up to their org (unknown ids are skipped)."""
    by_org: dict[str, int] = defaultdict(int)
    for key, n in counts.items():
        org = org_of.get(key)
        if org:
            by_org[org] += n
    return by_org


def _activity(
    src: Sources, authz: dict[str, Any] | None, member_org: dict[str, str | None]
) -> tuple[dict[str, int], dict[str, datetime]]:
    """Active members per org in the window, and each org's last access check (all time)."""
    if not authz:
        return {}, {}
    active_members = _sum_by_org(dict.fromkeys(authz["by_member"], 1), member_org)
    org_last: dict[str, datetime] = {}
    for member, when in src.query("authorization", "member_last_access", {}).items():
        org = member_org.get(member)
        if org and when and (org not in org_last or when > org_last[org]):
            org_last[org] = when
    return active_members, org_last


def daily_active(
    authz: dict[str, Any], member_org: dict[str, str | None], days: int
) -> tuple[list[int], list[int]]:
    """Per day of the window: distinct active members, and distinct orgs they belong to."""
    daily = [set(authz["daily_members"].get(d.isoformat(), ())) for d in day_range(days)]
    members = [len(day) for day in daily]
    orgs = [len({member_org[m] for m in day if member_org.get(m)}) for day in daily]
    return members, orgs


def engagement(src: Sources, days: int) -> dict[str, Any]:
    """Active members and orgs, feature adoption and dormant orgs over the window."""
    start = since(days)
    lookups = directory(src)
    names, member_org = lookups["org_names"], lookups["member_orgs"]
    authz = src.query(
        "authorization", "engagement", since=start, since_7=since(7), since_30=since(30)
    )
    active_members, org_last = _activity(src, authz, member_org)
    docs = fill_series(src.query("document", "summary", since=start), days, "daily")
    items = fill_series(src.query("planning", "summary", since=start), days, "daily")
    ai_window = src.query("agent", "org_usage", {}, since=start).get("cost_by_org", {})
    unread = src.query("notification", "unread_by_member", {})

    items_by_org = _sum_by_org(items["by_programme"] if items else {}, lookups["programme_orgs"])
    unread_by_org = _sum_by_org(unread, member_org)
    docs_by_org = docs["by_org"] if docs else {}
    last_seen = latest(lookups["org_last_audit"], org_last)
    cutoff = timezone.now() - timedelta(days=DORMANT_DAYS)
    rows = [
        {
            "org_id": org_id,
            "name": name,
            "last_seen": last_seen.get(org_id),
            "active_members": active_members.get(org_id, 0),
            "docs": docs_by_org.get(org_id, 0),
            "items": items_by_org.get(org_id, 0),
            "ai_usd": ai_window.get(org_id) or 0,
            "unread": unread_by_org.get(org_id, 0),
            "dormant": org_id not in last_seen or last_seen[org_id] < cutoff,
        }
        for org_id, name in names.items()
    ]
    rows.sort(key=lambda r: (r["last_seen"] is not None, r["last_seen"] or 0), reverse=True)
    return {
        "authz": authz,
        "member_org": member_org,
        "docs": docs,
        "items": items,
        "rows": rows,
        "dormant": sum(1 for r in rows if r["dormant"]),
        "dormant_days": DORMANT_DAYS,
    }


def adoption(rows: list[dict[str, Any]]) -> dict[str, int]:
    """How many orgs used each feature in the window."""
    return {
        "Documents": sum(1 for r in rows if r["docs"]),
        "Planning": sum(1 for r in rows if r["items"]),
        "AI": sum(1 for r in rows if r["ai_usd"]),
        "Active in window": sum(1 for r in rows if r["active_members"]),
    }


def access(src: Sources, days: int) -> dict[str, Any]:
    """Allow/deny decisions and the most-denied members; `a` is None while Authorization is down."""
    lookups = directory(src)
    names, member_org = lookups["org_names"], lookups["member_orgs"]
    decisions = fill_series(
        src.query("authorization", "access", since=since(days)), days, "allow", "deny"
    )
    if decisions is None:
        return {"a": None, "top": []}
    decisions["deny_pct"] = pct(decisions["denied"], decisions["total"])
    top = []
    for member, n in decisions["top_denied"]:
        org = member_org.get(member)
        top.append({"member": member, "org_id": org, "org": names.get(org or "", "—"), "n": n})
    return {"a": decisions, "top": top}
