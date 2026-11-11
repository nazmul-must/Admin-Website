"""Realistic admin query replies for tests: one valid `data` per query in contracts.REPLIES.

`fake_send` stands in for `rpc._send`, so tests run the real JSON decoding and contract
validation. The org is deliberately named like a date: such a name must stay a string.
"""

import json
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from unittest import mock

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.utils import timezone

from . import rpc, tiers

ORG = "11111111-1111-1111-1111-111111111111"
USER = "22222222-2222-2222-2222-222222222222"
MEMBER = "33333333-3333-3333-3333-333333333333"
PROGRAMME = "44444444-4444-4444-4444-444444444444"
ORG_NAME = "2026-01-31"  # customer-typed text that looks like a date
WHEN = "2026-10-01T09:30:00"  # naive, as some services send: read as UTC


def replies() -> dict[tuple[str, str], Any]:
    """A valid reply `data` for every query, with today's date in the daily maps."""
    today = timezone.localdate().isoformat()
    soon = (timezone.now() + timedelta(days=3)).isoformat()
    org = {
        "id": ORG,
        "name": ORG_NAME,
        "org_type": "BUSINESS",
        "subdomain": "acme",
        "parent_id": None,
        "created_at": WHEN,
    }
    user = {
        "id": USER,
        "name": "Ada Example",
        "email": "ada@yopmail.com",
        "email_verified": True,
        "mfa_method": None,
        "created_at": WHEN,
        "deleted_at": None,
    }
    membership = {
        "id": MEMBER,
        "user_id": USER,
        "org_id": ORG,
        "programme_id": PROGRAMME,
        "is_owner": True,
    }
    member = {**membership, "is_external": False, "is_org_active": True, "created_at": WHEN}
    programme = {
        "id": PROGRAMME,
        "name": "Kickoff",
        "org_id": ORG,
        "currency": "EUR",
        "start_date": "2026-01-31",
        "is_active": True,
        "created_at": WHEN,
    }
    subscription = {
        "id": "55555555-5555-5555-5555-555555555555",
        "org_id": ORG,
        "tier": "CORE",
        "status": "PAST_DUE",
        "seats": 3,
        "stripe_customer_id": "cus_1",
        "stripe_subscription_id": "sub_1",
        "stripe_price_id": None,
        "current_period_start": WHEN,
        "current_period_end": soon,
        "cancel_at_period_end": False,
        "programme_limit_override": None,
        "user_limit_override": 5,
        "ai_credit_allowance_override_usd": None,
        "created_at": WHEN,
        "updated_at": WHEN,
    }
    audit = {
        "id": "66666666-6666-6666-6666-666666666666",
        "org_id": ORG,
        "member_id": MEMBER,
        "action": "update",
        "target_type": "user",
        "target_id": USER,
        "created_at": WHEN,
    }
    totals = {"cost": 0.9, "prompt": 100, "completion": 50, "calls": 3}
    one_day = {today: 1}
    return {
        ("identity", "tiers"): {
            "core": {
                "display_name": "Core",
                "programme_limit": 2,
                "user_limit": None,
                "ai_credit_allowance_usd": 1.0,
            }
        },
        ("identity", "subscriptions"): [subscription],
        ("identity", "directory"): {
            "org_names": {ORG: ORG_NAME},
            "member_orgs": {MEMBER: ORG},
            "programme_orgs": {PROGRAMME: ORG},
            "org_last_audit": {ORG: WHEN},
        },
        ("identity", "org_list"): [{"org": org, "users": 1, "programmes": 1, "last_audit": WHEN}],
        ("identity", "org_detail"): {
            "org": org,
            "parent": None,
            "children": [],
            "subscription": subscription,
            "members": [member],
            "users": {USER: user},
            "programmes": [programme],
            "audit": [audit],
            "activity": one_day,
        },
        ("identity", "user_list"): {
            "users": [user],
            "memberships": [membership],
            "org_names": {ORG: ORG_NAME},
            "member_last_audit": {MEMBER: WHEN},
        },
        ("identity", "user_detail"): {
            "account": user,
            "members": [member],
            "org_names": {ORG: ORG_NAME},
            "programme_names": {PROGRAMME: "Kickoff"},
            "actions_by": [audit],
            "changes_to": [audit],
            "activity": one_day,
        },
        ("identity", "overview"): {
            "orgs": 1,
            "orgs_new": 1,
            "orgs_before": 0,
            "org_daily": one_day,
            "users": 1,
            "users_new": 1,
            "programmes": 1,
            "newest": [org],
        },
        ("identity", "growth"): {
            "orgs": one_day,
            "users": one_day,
            "members": one_day,
            "programmes": one_day,
            "orgs_before": 0,
            "users_before": 0,
            "org_types": {"BUSINESS": 1},
            "all_orgs": [ORG],
            "multi_user": [],
            "with_programme": [ORG],
            "verified": 1,
            "mfa": 0,
            "user_total": 1,
        },
        ("identity", "billing_events"): {
            "by_type": {"invoice.paid": 2},
            "by_outcome": {"null": 1, "ok": 1},
            "daily": {today: 2},
            "latest": [
                {
                    "id": "77777777-7777-7777-7777-777777777777",
                    "stripe_event_id": "evt_1",
                    "event_type": "invoice.paid",
                    "processed_at": None,
                    "outcome": None,
                    "created_at": WHEN,
                }
            ],
            "unprocessed": 1,
        },
        ("agent", "org_usage"): {"cost_by_org": {ORG: 0.9}, "last_by_org": {ORG: WHEN}},
        ("agent", "org_detail"): {
            "period": totals,
            "lifetime": {"cost": 1.5, "calls": 5},
            "daily_cost": {today: 0.9},
            "by_feature": {"chat": 0.9},
            "by_model": {"model-a": 0.9},
            "key": {
                "id": "88888888-8888-8888-8888-888888888888",
                "org_id": ORG,
                "limit_usd": 1.0,
                "last_usage_usd": 0.9,
                "synced_at": WHEN,
                "disabled": False,
                "created_at": WHEN,
            },
            "plan_runs": {"FAILED": 1},
            "sessions": 2,
            "ingestion": {"COMPLETE": 1},
        },
        ("agent", "member_usage"): {
            "window": totals,
            "daily_cost": {today: 0.9},
            "by_feature": {"chat": 0.9},
            "sessions": 1,
            "plan_runs": {},
        },
        ("agent", "dashboard"): {
            "totals": totals,
            "orgs_using": 1,
            "cost": {today: 0.9},
            "prompt": {today: 100},
            "completion": {today: 50},
            "by_model": {"model-a": 0.9},
            "by_feature": {"chat": 0.9},
            "calls_by_feature": {"chat": 3},
            "mtd_by_org": {ORG: 0.9},
            "runs_ok": one_day,
            "runs_failed": {},
            "runs_by_status": {"FAILED": 1, "COMPLETE": 3},
            "sessions": one_day,
            "ingestion": {"null": 1},
            "keys_disabled": 0,
            "keys_stale": 0,
            "keys": 1,
        },
        ("authorization", "member_last_access"): {MEMBER: WHEN},
        ("authorization", "member_access"): {
            "allow": {today: 3},
            "deny": one_day,
            "deny_by_action": {"delete": 1},
            "total": 4,
            "last": WHEN,
        },
        ("authorization", "engagement"): {
            "daily_members": {today: [MEMBER]},
            "wau": 1,
            "mau": 1,
            "by_member": {MEMBER: 4},
        },
        ("authorization", "access"): {
            "total": 4,
            "denied": 1,
            "allow": {today: 3},
            "deny": one_day,
            "deny_by_action": {"delete": 1},
            "deny_by_source": {"rbac": 1},
            "allow_by_source": {"rbac": 3},
            "top_denied": [[MEMBER, 1]],
            "members": 1,
        },
        ("document", "summary"): {
            "by_org": {ORG: 2},
            "last_by_org": {ORG: WHEN},
            "daily": {today: 2},
            "total": 2,
        },
        ("document", "org_detail"): {
            "count": 2,
            "by_programme": {PROGRAMME: 2},
            "versions": 3,
            "bytes": 2048,
            "daily": {today: 2},
        },
        ("document", "member_uploads"): {"uploads": 1, "bytes": 1024, "daily": one_day},
        ("planning", "summary"): {"total": 5, "by_programme": {PROGRAMME: 5}, "daily": {today: 5}},
        ("planning", "programme_items"): {
            "count": 5,
            "by_programme": {PROGRAMME: 5},
            "by_type": {"TASK": 5},
            "by_rag": {"GREEN": 5},
        },
        ("notification", "member_notes"): {"total": 3, "unread": 1, "by_channel": {"email": 3}},
        ("notification", "unread_by_member"): {MEMBER: 1},
    }


def fake_send(overrides: dict[tuple[str, str], Any] | None = None) -> Callable[[str, bytes], bytes]:
    """A stand-in for `rpc._send` answering every query from `replies()`, with `overrides`."""
    data = {**replies(), **(overrides or {})}

    def send(service: str, body: bytes) -> bytes:
        name = json.loads(body)["query"]
        return json.dumps({"status": "success", "data": data[(service, name)]}).encode()

    return send


class PageTestCase(TestCase):
    """Signed in as a Monitor, with every service answering from `replies()`.

    Call `self.answer(overrides)` or `self.fail_all()` to change what services send.
    """

    def setUp(self) -> None:
        self.user = User.objects.create_user("monitor@yopmail.com", password="x")
        self.user.groups.add(Group.objects.get(name="Monitor"))
        self.client.force_login(self.user)
        patcher = mock.patch.object(rpc, "_send", side_effect=fake_send())
        self.send = patcher.start()
        self.addCleanup(patcher.stop)
        cache = mock.patch.dict(tiers._cache, clear=True)
        cache.start()
        self.addCleanup(cache.stop)

    def answer(self, overrides: dict[tuple[str, str], Any]) -> None:
        """Make services send `overrides` for those queries from now on."""
        self.send.side_effect = fake_send(overrides)

    def fail_all(self) -> None:
        """Every service is unreachable."""
        self.send.side_effect = rpc.ServiceUnavailable("down")
