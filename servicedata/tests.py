"""Tests for the RPC client, reply contracts, tier limits and the date-series helpers."""

import json
import logging
from datetime import UTC, date, datetime
from typing import Any
from unittest import mock

from django.test import SimpleTestCase

from . import rpc, tiers
from .contracts import REPLIES
from .fake_replies import ORG, ORG_NAME, fake_send, replies
from .stats import Sources, cumulative, day_range, fill_series, latest, pct, series
from .tiers import limits, usage_level

TIERS = {
    "core": {
        "display_name": "Core",
        "programme_limit": 2,
        "user_limit": None,
        "ai_credit_allowance_usd": 1.0,
    }
}


class LimitsTests(SimpleTestCase):
    """Effective limits: tier defaults, per-org overrides, no subscription."""

    def setUp(self) -> None:
        patcher = mock.patch.dict(tiers._cache, {"tiers": TIERS})
        patcher.start()
        self.addCleanup(patcher.stop)

    def sub(self, **overrides: object) -> Any:
        return {
            "tier": "CORE",
            "programme_limit_override": None,
            "user_limit_override": None,
            "ai_credit_allowance_override_usd": None,
            **overrides,
        }

    def test_tier_defaults(self) -> None:
        self.assertEqual(limits(self.sub()), {"programmes": 2, "users": None, "ai_usd": 1.0})

    def test_overrides_win_including_zero(self) -> None:
        lim = limits(self.sub(programme_limit_override=0, ai_credit_allowance_override_usd=9.0))
        self.assertEqual((lim["programmes"], lim["ai_usd"]), (0, 9.0))

    def test_no_subscription_is_unlimited(self) -> None:
        self.assertEqual(limits(None), {"programmes": None, "users": None, "ai_usd": None})

    def test_usage_level_thresholds(self) -> None:
        levels = [usage_level(p) for p in (None, 79, 80, 99, 100, 150)]
        self.assertEqual(levels, [None, None, "amber", "amber", "red", "red"])


class TiersCacheTests(SimpleTestCase):
    """The tier catalogue is cached only once Identity answered."""

    def test_identity_down_is_not_cached(self) -> None:
        down = rpc.ServiceUnavailable("down")
        with (
            mock.patch.dict(tiers._cache, clear=True),
            mock.patch.object(rpc, "query", side_effect=[down, TIERS]) as q,
        ):
            self.assertEqual(tiers.tiers(), {})
            self.assertEqual(tiers.tiers(), TIERS)
            self.assertEqual(tiers.tiers(), TIERS)
        self.assertEqual(q.call_count, 2)


class StatsTests(SimpleTestCase):
    """Per-request degradation and the series helpers."""

    def test_failed_service_degrades_once(self) -> None:
        src = Sources()
        with mock.patch.object(rpc, "query", side_effect=rpc.ServiceUnavailable("down")) as q:
            self.assertEqual(src.query("agent", "org_usage", "fallback"), "fallback")
            self.assertEqual(src.query("agent", "dashboard", "again"), "again")
        self.assertEqual((q.call_count, src.down), (1, ["agent"]))
        self.assertEqual(src.page_context({})["down"], ["Agent (AI)"])

    def test_series_zero_fills_oldest_first(self) -> None:
        days = day_range(3)
        by_day = {days[0].isoformat(): 2, days[2].isoformat(): None, "1999-01-01": 9}
        self.assertEqual(series(by_day, 3), [2, 0, 0])

    def test_fill_series_copies_and_passes_none_through(self) -> None:
        days = day_range(3)
        original = {"d": {days[1].isoformat(): 4}, "other": 1}
        self.assertEqual(fill_series(original, 3, "d"), {"d": [0, 4, 0], "other": 1})
        self.assertEqual(original["d"], {days[1].isoformat(): 4})
        self.assertIsNone(fill_series(None, 3, "d"))

    def test_pct_and_cumulative_and_latest(self) -> None:
        self.assertIsNone(pct(5, None))
        self.assertEqual(pct(3, 4), 75)
        self.assertEqual(cumulative(10, [1, 0, 2]), [11, 11, 13])
        newer = datetime(2026, 1, 3, tzinfo=UTC)
        older = datetime(2026, 1, 1, tzinfo=UTC)
        merged = latest({"a": older, "b": newer}, {"a": newer, "b": None})
        self.assertEqual(merged, {"a": newer, "b": newer})


class ContractTests(SimpleTestCase):
    """Replies are parsed by their contract, not by guessing from string shapes."""

    def query(self, service: str, name: str, data: object) -> Any:
        send = fake_send({(service, name): data})
        with mock.patch.object(rpc, "_send", side_effect=send):
            return rpc.query(service, name)

    def test_every_fake_reply_matches_its_contract(self) -> None:
        self.assertEqual(set(replies()), set(REPLIES))
        for (service, name), data in replies().items():
            with self.subTest(query=f"{service}.{name}"):
                self.query(service, name, data)

    def test_date_like_text_stays_text(self) -> None:
        directory = self.query("identity", "directory", replies()[("identity", "directory")])
        self.assertEqual(directory["org_names"][ORG], ORG_NAME)
        bad_date = {**replies()[("identity", "directory")], "org_names": {ORG: "2026-02-30"}}
        self.assertEqual(
            self.query("identity", "directory", bad_date)["org_names"][ORG], "2026-02-30"
        )

    def test_declared_datetimes_and_dates_are_parsed_utc(self) -> None:
        detail = self.query("identity", "org_detail", replies()[("identity", "org_detail")])
        self.assertEqual(detail["org"]["created_at"], datetime(2026, 10, 1, 9, 30, tzinfo=UTC))
        self.assertEqual(detail["programmes"][0]["start_date"], date(2026, 1, 31))
        self.assertIsInstance(detail["org"]["name"], str)

    def test_reply_missing_a_key_marks_the_service_down(self) -> None:
        rows = [{"org": replies()[("identity", "org_detail")]["org"], "users": 1}]
        src = Sources()
        with (
            mock.patch.object(
                rpc, "_send", side_effect=fake_send({("identity", "org_list"): rows})
            ),
            self.assertLogs("servicedata.stats", logging.WARNING) as logs,
        ):
            self.assertEqual(src.query("identity", "org_list", []), [])
        self.assertEqual(src.down, ["identity"])
        self.assertIn("0.programmes: missing", logs.output[0])

    def test_contract_errors_do_not_log_values(self) -> None:
        user = {**replies()[("identity", "user_list")]["users"][0], "email_verified": "maybe"}
        data = {**replies()[("identity", "user_list")], "users": [user]}
        with self.assertRaises(rpc.ServiceUnavailable) as caught:
            self.query("identity", "user_list", data)
        self.assertNotIn("ada@yopmail.com", str(caught.exception))
        self.assertNotIn("maybe", str(caught.exception))

    def test_error_and_non_json_replies_raise(self) -> None:
        with (
            mock.patch.object(rpc, "_send", return_value=b'{"status": "error", "message": "boom"}'),
            self.assertRaisesMessage(rpc.ServiceUnavailable, "identity.tiers: boom"),
        ):
            rpc.query("identity", "tiers")
        with (
            mock.patch.object(rpc, "_send", return_value=b"<html>"),
            self.assertRaisesMessage(rpc.ServiceUnavailable, "not JSON"),
        ):
            rpc.query("identity", "tiers")

    def test_params_are_sent_as_json(self) -> None:
        send = fake_send()
        with mock.patch.object(rpc, "_send", side_effect=send) as call:
            rpc.query("planning", "summary", since=datetime(2026, 1, 1, tzinfo=UTC))
        sent = json.loads(call.call_args.args[1])
        self.assertEqual(sent, {"query": "summary", "params": {"since": "2026-01-01T00:00:00Z"}})
