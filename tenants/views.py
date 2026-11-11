"""Organization and user list/detail pages."""

from typing import Any

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render

from accounts.decorators import view_required
from admin.charts import chart, ranked, to_credits
from servicedata.stats import Sources, labels, window
from servicedata.tiers import CREDITS_PER_USD, subscriptions, tiers

from .selectors import org_detail, org_rows
from .user_selectors import user_detail, user_rows


def _list_template(request: HttpRequest, template: str, table_id: str) -> str:
    """The whole page, or only its table when HTMX re-runs the search."""
    return f"{template}#{table_id}" if request.headers.get("HX-Request") else template


def _shared_charts(detail: dict[str, Any], day_labels: list[str]) -> dict[str, Any]:
    """Charts both detail pages show: activity, access decisions and AI credits."""
    charts = {"activity": chart("bar", day_labels, {"Audit events": detail["activity"]})}
    if detail["access"]:
        allowed, denied = detail["access"]["allow"], detail["access"]["deny"]
        charts["access"] = chart(
            "bar", day_labels, {"Allowed": allowed, "Denied": denied}, stacked=True
        )
    if detail["ai"]:
        daily_credits = to_credits(detail["ai"]["daily_cost"])
        charts["ai_cost"] = chart("line", day_labels, {"Credits": daily_credits})
    return charts


def _unavailable_or_404(
    request: HttpRequest, src: Sources, object_id: str, what: str
) -> HttpResponse:
    """Identity is down: say so. Identity is up: the object does not exist."""
    if src.down:
        context = src.page_context({"object_id": object_id})
        return render(request, "tenants/org_unavailable.html", context)
    raise Http404(f"{what} not found")


@view_required
def org_list(request: HttpRequest) -> HttpResponse:
    """Organizations with search and tier/status filters."""
    src = Sources()
    q = request.GET.get("q", "").strip()
    tier = request.GET.get("tier", "")
    status = request.GET.get("status", "")
    subs = subscriptions(src)
    context = {
        "rows": org_rows(src, subs, q, tier, status),
        "q": q,
        "tier": tier,
        "status": status,
        "tiers": [(key.upper(), t.get("display_name", key)) for key, t in tiers().items()],
        "statuses": sorted({s["status"] for s in subs.values()}),
    }
    template = _list_template(request, "tenants/org_list.html", "org-table")
    return render(request, template, src.page_context(context))


@view_required
def org_detail_view(request: HttpRequest, org_id: str) -> HttpResponse:
    """One organization: subscription, limits vs usage, activity, people and programmes."""
    src = Sources()
    days = window(request, 30)
    detail = org_detail(src, org_id, days)
    if detail is None:
        return _unavailable_or_404(request, src, org_id, "Organization")

    day_labels = labels(days)
    charts = _shared_charts(detail, day_labels)
    if detail["ai"] and detail["ai"]["by_feature"]:
        charts["ai_feature"] = chart("doughnut", [], ranked(detail["ai"]["by_feature"]))
    if detail["plan"] and detail["plan"]["by_type"]:
        charts["work_types"] = chart("doughnut", [], ranked(detail["plan"]["by_type"]))
    if detail["docs"]:
        created = {"Documents created": detail["docs"]["daily"]}
        charts["docs"] = chart("bar", day_labels, created)

    context = {**detail, "charts": charts, "days": days, "credits_per_usd": CREDITS_PER_USD}
    return render(request, "tenants/org_detail.html", src.page_context(context))


@view_required
def user_list(request: HttpRequest) -> HttpResponse:
    """Users with search and org/verification/MFA filters."""
    src = Sources()
    filters = {k: request.GET.get(k, "").strip() for k in ("q", "org", "verified", "mfa")}
    rows, orgs = user_rows(src, **filters)
    template = _list_template(request, "tenants/user_list.html", "user-table")
    return render(request, template, src.page_context({"rows": rows, "orgs": orgs, **filters}))


@view_required
def user_detail_view(request: HttpRequest, user_id: str) -> HttpResponse:
    """One user: memberships, activity, access, AI, uploads and notifications."""
    src = Sources()
    days = window(request, 30)
    detail = user_detail(src, user_id, days)
    if detail is None:
        return _unavailable_or_404(request, src, user_id, "User")

    charts = _shared_charts(detail, labels(days))
    if detail["docs"]:
        uploads = {"Document versions uploaded": detail["docs"]["daily"]}
        charts["uploads"] = chart("bar", labels(days), uploads)
    context = {**detail, "charts": charts, "days": days}
    return render(request, "tenants/user_detail.html", src.page_context(context))
