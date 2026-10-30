import json
from datetime import date, datetime, timezone
from unittest import mock

from django.test import SimpleTestCase

from . import rpc, tiers
from .stats import Sources, cumulative, day_range, fill, latest, pct, series
from .tiers import limits

TIERS = {'core': {'display_name': 'Core', 'programme_limit': 2, 'user_limit': None, 'ai_credit_allowance_usd': 1.0}}


class LimitsTests(SimpleTestCase):
    def setUp(self):
        patcher = mock.patch.dict(tiers._cache, {'tiers': TIERS})
        patcher.start()
        self.addCleanup(patcher.stop)

    def sub(self, **overrides):
        return {'tier': 'CORE', 'programme_limit_override': None, 'user_limit_override': None,
                'ai_credit_allowance_override_usd': None, **overrides}

    def test_tier_defaults(self):
        self.assertEqual(limits(self.sub()), {'programmes': 2, 'users': None, 'ai_usd': 1.0})

    def test_overrides_win_including_zero(self):
        lim = limits(self.sub(programme_limit_override=0, ai_credit_allowance_override_usd=9.0))
        self.assertEqual((lim['programmes'], lim['ai_usd']), (0, 9.0))

    def test_no_subscription_is_unlimited(self):
        self.assertEqual(limits(None), {'programmes': None, 'users': None, 'ai_usd': None})


class TiersCacheTests(SimpleTestCase):
    def test_identity_down_is_not_cached(self):
        with mock.patch.dict(tiers._cache, clear=True), \
                mock.patch.object(rpc, 'query', side_effect=[rpc.ServiceUnavailable('down'), TIERS]) as q:
            self.assertEqual(tiers.tiers(), {})
            self.assertEqual(tiers.tiers(), TIERS)
            self.assertEqual(tiers.tiers(), TIERS)
        self.assertEqual(q.call_count, 2)


class StatsTests(SimpleTestCase):
    def test_failed_service_degrades_once(self):
        src = Sources()
        with mock.patch.object(rpc, 'query', side_effect=rpc.ServiceUnavailable('down')) as q:
            self.assertEqual(src.query('agent', 'org_usage', 'fallback'), 'fallback')
            self.assertEqual(src.query('agent', 'dashboard', 'again'), 'again')
        self.assertEqual((q.call_count, src.down), (1, ['agent']))

    def test_series_zero_fills_oldest_first(self):
        days = day_range(3)
        by_day = {days[0].isoformat(): 2, days[2].isoformat(): None, '1999-01-01': 9}
        self.assertEqual(series(by_day, 3), [2, 0, 0])
        self.assertEqual(fill({'d': {days[1].isoformat(): 4}}, 3, 'd'), {'d': [0, 4, 0]})
        self.assertIsNone(fill(None, 3, 'd'))

    def test_pct_and_cumulative_and_latest(self):
        self.assertIsNone(pct(5, None))
        self.assertEqual(pct(3, 4), 75)
        self.assertEqual(cumulative(10, [1, 0, 2]), [11, 11, 13])
        self.assertEqual(latest({'a': 1, 'b': 5}, {'a': 3, 'b': None}), {'a': 3, 'b': 5})


class RpcReplyTests(SimpleTestCase):
    def test_revives_datetimes_and_dates_but_not_keys(self):
        raw = json.dumps({'status': 'success', 'data': {
            'created_at': '2026-10-01T09:30:00', 'start_date': '2026-01-31',
            'daily': {'2026-10-01': 3}, 'name': 'Acme',
        }})
        data = json.loads(raw, object_hook=rpc._revive)['data']
        self.assertEqual(data['created_at'], datetime(2026, 10, 1, 9, 30, tzinfo=timezone.utc))
        self.assertEqual(data['start_date'], date(2026, 1, 31))
        self.assertEqual(data['daily'], {'2026-10-01': 3})
        self.assertEqual(data['name'], 'Acme')

    def test_error_reply_raises(self):
        with mock.patch.object(rpc, '_call', return_value=b'{"status": "error", "message": "boom"}'):
            with self.assertRaisesMessage(rpc.ServiceUnavailable, 'identity.tiers: boom'):
                rpc.query('identity', 'tiers')

    def test_success_reply_returns_data(self):
        with mock.patch.object(rpc, '_call', return_value=b'{"status": "success", "data": [1]}') as call:
            self.assertEqual(rpc.query('planning', 'summary', since=datetime(2026, 1, 1, tzinfo=timezone.utc)), [1])
        sent = json.loads(call.call_args.args[1])
        self.assertEqual(sent, {'query': 'summary', 'params': {'since': '2026-01-01T00:00:00Z'}})
