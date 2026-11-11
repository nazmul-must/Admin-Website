"""Typed contracts for the services' admin query replies (the `data` of a success reply).

Every query the admin site calls is listed in `REPLIES`; `rpc.query` validates the reply
against it before any page code reads it. That gives three guarantees:

- A key the pages read is always there. A service that changes a reply's shape is shown as
  down (banner) instead of breaking the page with a KeyError.
- Only fields declared as datetimes or dates are parsed. A customer-typed string that looks
  like a date (an org called "2026-01-31") stays a string.
- Datetimes are always timezone-aware: a naive value is UTC, as the services document.

Keys of id- or day-keyed maps stay strings ('YYYY-MM-DD', canonical UUIDs, or "null" for a
NULL group). Keys the admin site does not read are not declared and are dropped.
The owning service's `features/admin_query` holds the source of each shape; keep the two
in step when a query changes.
"""

from datetime import UTC, date, datetime
from typing import Annotated, Any, NotRequired, TypedDict

from pydantic import AfterValidator, TypeAdapter


def _assume_utc(moment: datetime) -> datetime:
    """Attach UTC to a naive datetime; leave an aware one unchanged."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_assume_utc)]
Daily = dict[str, int]  # {'YYYY-MM-DD': count}, only days with rows
DailyMoney = dict[str, float]  # {'YYYY-MM-DD': USD}
Counts = dict[str, int]  # {group value: count}
Money = dict[str, float]  # {group value: USD}
LatestById = dict[str, UtcDatetime | None]  # {id: newest timestamp}
Number = int | float


# ----- Identity ----------------------------------------------------------------------------


class Tier(TypedDict):
    """One tier of Identity's tier.config.json; None limits mean unlimited."""

    display_name: NotRequired[str]
    programme_limit: NotRequired[int | None]
    user_limit: NotRequired[int | None]
    ai_credit_allowance_usd: NotRequired[float | None]


class Org(TypedDict):
    """Identity's admin org object."""

    id: str
    name: str
    org_type: str | None
    subdomain: str | None
    parent_id: str | None
    created_at: UtcDatetime | None


class User(TypedDict):
    """Identity's admin user object. Name and email are None when Identity can't decrypt them."""

    id: str
    name: str | None
    email: str | None
    email_verified: bool
    mfa_method: str | None
    created_at: UtcDatetime | None
    deleted_at: UtcDatetime | None


class Membership(TypedDict):
    """A live member row as `user_list` returns it."""

    id: str
    user_id: str
    org_id: str
    programme_id: str | None
    is_owner: bool


class Member(Membership):
    """Identity's full admin member object."""

    is_external: bool
    is_org_active: bool
    created_at: UtcDatetime | None


class Programme(TypedDict):
    """Identity's admin programme object."""

    id: str
    name: str
    org_id: str | None
    currency: str | None
    start_date: date | None
    is_active: bool | None
    created_at: UtcDatetime | None


class Subscription(TypedDict):
    """Identity's admin subscription object."""

    id: str
    org_id: str
    tier: str
    status: str
    seats: int | None
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    stripe_price_id: str | None
    current_period_start: UtcDatetime | None
    current_period_end: UtcDatetime | None
    cancel_at_period_end: bool
    programme_limit_override: int | None
    user_limit_override: int | None
    ai_credit_allowance_override_usd: float | None
    created_at: UtcDatetime | None
    updated_at: UtcDatetime | None


class AuditEntry(TypedDict):
    """Identity's admin audit object."""

    id: str
    org_id: str | None
    member_id: str | None
    action: str | None
    target_type: str | None
    target_id: str | None
    created_at: UtcDatetime | None


class BillingEvent(TypedDict):
    """Identity's admin Stripe webhook event object."""

    id: str
    stripe_event_id: str
    event_type: str
    processed_at: UtcDatetime | None
    outcome: str | None
    created_at: UtcDatetime | None


class Directory(TypedDict):
    """Identity `directory`: id lookups over all rows, deleted included."""

    org_names: dict[str, str]
    member_orgs: dict[str, str | None]
    programme_orgs: dict[str, str | None]
    org_last_audit: LatestById


class OrgListRow(TypedDict):
    """One row of Identity `org_list`."""

    org: Org
    users: int
    programmes: int
    last_audit: UtcDatetime | None


class OrgDetail(TypedDict):
    """Identity `org_detail`."""

    org: Org
    parent: Org | None
    children: list[Org]
    subscription: Subscription | None
    members: list[Member]
    users: dict[str, User]
    programmes: list[Programme]
    audit: list[AuditEntry]
    activity: Daily


class UserList(TypedDict):
    """Identity `user_list`."""

    users: list[User]
    memberships: list[Membership]
    org_names: dict[str, str]
    member_last_audit: LatestById


class UserDetail(TypedDict):
    """Identity `user_detail`."""

    account: User
    members: list[Member]
    org_names: dict[str, str]
    programme_names: dict[str, str]
    actions_by: list[AuditEntry]
    changes_to: list[AuditEntry]
    activity: Daily


class Overview(TypedDict):
    """Identity `overview`."""

    orgs: int
    orgs_new: int
    orgs_before: int
    org_daily: Daily
    users: int
    users_new: int
    programmes: int
    newest: list[Org]


class Growth(TypedDict):
    """Identity `growth`."""

    orgs: Daily
    users: Daily
    members: Daily
    programmes: Daily
    orgs_before: int
    users_before: int
    org_types: Counts
    all_orgs: list[str]
    multi_user: list[str]
    with_programme: list[str]
    verified: int
    mfa: int
    user_total: int


class BillingEvents(TypedDict):
    """Identity `billing_events`."""

    by_type: Counts
    by_outcome: Counts
    daily: Daily
    latest: list[BillingEvent]
    unprocessed: int


# ----- Agent -------------------------------------------------------------------------------


class UsageTotals(TypedDict):
    """Agent usage totals: USD cost, tokens and calls."""

    cost: float
    prompt: int
    completion: int
    calls: int


class LifetimeUsage(TypedDict):
    """Agent lifetime usage of one org."""

    cost: float
    calls: int


class AiKey(TypedDict):
    """Agent's per-org AI key record (never the key material)."""

    id: str
    org_id: str
    limit_usd: float
    last_usage_usd: float
    synced_at: UtcDatetime | None
    disabled: bool
    created_at: UtcDatetime | None


class OrgUsage(TypedDict):
    """Agent `org_usage`."""

    cost_by_org: Money
    last_by_org: LatestById


class AgentOrgDetail(TypedDict):
    """Agent `org_detail`."""

    period: UsageTotals
    lifetime: LifetimeUsage
    daily_cost: DailyMoney
    by_feature: Money
    by_model: Money
    key: AiKey | None
    plan_runs: Counts
    sessions: int
    ingestion: Counts


class MemberUsage(TypedDict):
    """Agent `member_usage`."""

    window: UsageTotals
    daily_cost: DailyMoney
    by_feature: Money
    sessions: int
    plan_runs: Counts


class AiDashboard(TypedDict):
    """Agent `dashboard`."""

    totals: UsageTotals
    orgs_using: int
    cost: DailyMoney
    prompt: Daily
    completion: Daily
    by_model: Money
    by_feature: Money
    calls_by_feature: Counts
    mtd_by_org: Money
    runs_ok: Daily
    runs_failed: Daily
    runs_by_status: Counts
    sessions: Daily
    ingestion: Counts
    keys_disabled: int
    keys_stale: int
    keys: int


# ----- Authorization -----------------------------------------------------------------------


class MemberAccess(TypedDict):
    """Authorization `member_access`."""

    allow: Daily
    deny: Daily
    deny_by_action: Counts
    total: int
    last: UtcDatetime | None


class Engagement(TypedDict):
    """Authorization `engagement`."""

    daily_members: dict[str, list[str]]
    wau: int
    mau: int
    by_member: Counts


class Access(TypedDict):
    """Authorization `access`."""

    total: int
    denied: int
    allow: Daily
    deny: Daily
    deny_by_action: Counts
    deny_by_source: Counts
    allow_by_source: Counts
    top_denied: list[tuple[str, int]]
    members: int


# ----- Document, Planning, Notification ----------------------------------------------------


class DocumentSummary(TypedDict):
    """Document `summary`."""

    by_org: Counts
    last_by_org: LatestById
    daily: Daily
    total: int


class DocumentOrgDetail(TypedDict):
    """Document `org_detail`."""

    count: int
    by_programme: Counts
    versions: int
    bytes: Number
    daily: Daily


class MemberUploads(TypedDict):
    """Document `member_uploads`."""

    uploads: int
    bytes: Number
    daily: Daily


class PlanningSummary(TypedDict):
    """Planning `summary`."""

    total: int
    by_programme: Counts
    daily: Daily


class ProgrammeItems(TypedDict):
    """Planning `programme_items`."""

    count: int
    by_programme: Counts
    by_type: Counts
    by_rag: Counts


class MemberNotes(TypedDict):
    """Notification `member_notes`."""

    total: int
    unread: int
    by_channel: Counts


REPLIES: dict[tuple[str, str], TypeAdapter[Any]] = {
    key: TypeAdapter(shape)
    for key, shape in {
        ("identity", "tiers"): dict[str, Tier],
        ("identity", "subscriptions"): list[Subscription],
        ("identity", "directory"): Directory,
        ("identity", "org_list"): list[OrgListRow],
        ("identity", "org_detail"): OrgDetail | None,
        ("identity", "user_list"): UserList,
        ("identity", "user_detail"): UserDetail | None,
        ("identity", "overview"): Overview,
        ("identity", "growth"): Growth,
        ("identity", "billing_events"): BillingEvents,
        ("agent", "org_usage"): OrgUsage,
        ("agent", "org_detail"): AgentOrgDetail,
        ("agent", "member_usage"): MemberUsage,
        ("agent", "dashboard"): AiDashboard,
        ("authorization", "member_last_access"): LatestById,
        ("authorization", "member_access"): MemberAccess,
        ("authorization", "engagement"): Engagement,
        ("authorization", "access"): Access,
        ("document", "summary"): DocumentSummary,
        ("document", "org_detail"): DocumentOrgDetail,
        ("document", "member_uploads"): MemberUploads,
        ("planning", "summary"): PlanningSummary,
        ("planning", "programme_items"): ProgrammeItems,
        ("notification", "member_notes"): MemberNotes,
        ("notification", "unread_by_member"): Counts,
    }.items()
}
"""Reply contract per (service, query). A query missing here is a programming error."""
