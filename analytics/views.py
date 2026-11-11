"""Platform analytics pages that Grafana does not cover: tenants, billing, AI spend,
product adoption and access decisions. Grafana keeps HTTP/GraphQL/outbox health.

Each view reads its data from `selectors` and only builds charts and renders.
"""

from typing import Any

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from accounts.decorators import view_required
from admin.charts import chart, ranked, to_credits
from servicedata.stats import Sources, cumulative, labels, window

from . import selectors


def _bar_ranking(counts: dict[str, float], name: str, top: int = 10) -> dict[str, Any] | None:
    """Horizontal bar of the largest `counts`; None when there is nothing to rank."""
    if not counts:
        return None
    by_size = ranked(counts, top)
    return chart("bar", list(by_size), {name: list(by_size.values())}, horizontal=True)


def _doughnut(counts: dict[str, float]) -> dict[str, Any] | None:
    """Doughnut of the largest `counts`; None when empty."""
    return chart("doughnut", [], ranked(counts)) if counts else None


@view_required
def overview(request: HttpRequest) -> HttpResponse:
    """Platform overview: totals, signups, subscription mix and what needs attention."""
    src = Sources()
    days = window(request, 90)
    data = selectors.overview(src, days)
    charts = {
        "tier": chart("doughnut", [], data["tier_mix"]) if data["tier_mix"] else None,
        "status": chart("doughnut", [], data["status_mix"]) if data["status_mix"] else None,
    }
    identity = data["idn"]
    if identity:
        day_labels = labels(days)
        new_orgs = identity["org_daily"]
        total = cumulative(identity["orgs_before"], new_orgs)
        charts["signups"] = chart("bar", day_labels, {"New organizations": new_orgs})
        charts["total"] = chart("line", day_labels, {"Organizations": total})
    context = {**data, "days": days, "charts": charts}
    return render(request, "analytics/overview.html", src.page_context(context))


@view_required
def growth(request: HttpRequest) -> HttpResponse:
    """Signups, cumulative growth, org types and the activation funnel."""
    src = Sources()
    days = window(request, 90)
    data = selectors.growth(src, days)
    identity, funnel, charts = data["idn"], data["funnel"], {}
    if identity:
        day_labels = labels(days)
        charts["signups"] = chart(
            "line",
            day_labels,
            {
                "Organizations": identity["orgs"],
                "Users": identity["users"],
                "Memberships": identity["members"],
                "Programmes": identity["programmes"],
            },
        )
        charts["cumulative"] = chart(
            "line",
            day_labels,
            {
                "Organizations": cumulative(identity["orgs_before"], identity["orgs"]),
                "Users": cumulative(identity["users_before"], identity["users"]),
            },
        )
        org_types = {k.lower(): v for k, v in identity["org_types"].items()}
        charts["types"] = chart("doughnut", [], org_types)
        steps = {"Organizations": [step["n"] for step in funnel]}
        charts["funnel"] = chart("bar", [s["label"] for s in funnel], steps, horizontal=True)
    context = {**data, "days": days, "charts": charts}
    return render(request, "analytics/growth.html", src.page_context(context))


@view_required
def billing(request: HttpRequest) -> HttpResponse:
    """Tier x status, renewals, problem subscriptions, overrides and Stripe events."""
    src = Sources()
    days = window(request, 90)
    data = selectors.billing(src, days)
    by_tier = {row["tier"]: sum(row["cells"]) for row in data["matrix"]}
    charts = {"tier": chart("doughnut", [], by_tier) if data["subs"] else None}
    if data["ev"]:
        charts["events"] = chart("bar", labels(days), {"Stripe events": data["ev"]["daily"]})
        charts["types"] = _bar_ranking(data["ev"]["by_type"], "Events")
    context = {**data, "days": days, "charts": charts}
    return render(request, "analytics/billing.html", src.page_context(context))


@view_required
def ai_usage(request: HttpRequest) -> HttpResponse:
    """AI credits and tokens, by model and feature, plan runs, ingestion and top orgs."""
    src = Sources()
    days = window(request, 30)
    data = selectors.ai_usage(src, days)
    ai, charts = data["ai"], {}
    if ai:
        day_labels = labels(days)
        by_model = {k: to_credits([v])[0] for k, v in ranked(ai["by_model"]).items()}
        by_feature = ranked(ai["by_feature"])
        runs = {"Succeeded / running": ai["runs_ok"], "Failed": ai["runs_failed"]}
        tokens = {"Prompt": ai["prompt"], "Completion": ai["completion"]}
        charts = {
            "cost": chart("line", day_labels, {"Credits": to_credits(ai["cost"])}),
            "tokens": chart("bar", day_labels, tokens, stacked=True),
            "model": chart("doughnut", [], by_model) if by_model else None,
            "feature": chart(
                "bar",
                list(by_feature),
                {"Credits": to_credits(by_feature.values())},
                horizontal=True,
            )
            if by_feature
            else None,
            "runs": chart("bar", day_labels, runs, stacked=True),
            "sessions": chart("bar", day_labels, {"Agent sessions": ai["sessions"]}),
            "ingestion": _doughnut(ai["ingestion"]),
        }
    context = {**data, "days": days, "charts": charts}
    return render(request, "analytics/ai_usage.html", src.page_context(context))


@view_required
def engagement(request: HttpRequest) -> HttpResponse:
    """Active members and orgs, feature adoption and dormant orgs."""
    src = Sources()
    days = window(request, 30)
    data = selectors.engagement(src, days)
    day_labels = labels(days)
    charts: dict[str, Any] = {}
    if data["authz"]:
        members, orgs = selectors.daily_active(data["authz"], data["member_org"], days)
        series = {"Active members": members, "Active organizations": orgs}
        charts["dau"] = chart("line", day_labels, series)
    if data["rows"]:
        used = selectors.adoption(data["rows"])
        charts["adoption"] = chart("bar", list(used), {"Organizations": list(used.values())})
    created = {}
    if data["docs"]:
        created["Documents"] = data["docs"]["daily"]
    if data["items"]:
        created["Work items"] = data["items"]["daily"]
    charts["created"] = chart("line", day_labels, created) if created else None
    context = {**data, "days": days, "charts": charts}
    return render(request, "analytics/engagement.html", src.page_context(context))


@view_required
def access(request: HttpRequest) -> HttpResponse:
    """Allowed vs denied permission checks, denials by action and source, most-denied members."""
    src = Sources()
    days = window(request, 30)
    data = selectors.access(src, days)
    decisions, charts = data["a"], {}
    if decisions:
        daily = {"Allowed": decisions["allow"], "Denied": decisions["deny"]}
        charts = {
            "daily": chart("bar", labels(days), daily, stacked=True),
            "deny_action": _bar_ranking(decisions["deny_by_action"], "Denials"),
            "deny_source": _doughnut(decisions["deny_by_source"]),
            "allow_source": _doughnut(decisions["allow_by_source"]),
        }
    context = {**data, "days": days, "charts": charts}
    return render(request, "analytics/access.html", src.page_context(context))
