import base64
import hashlib
import uuid

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.db import DatabaseError
from django.test import SimpleTestCase

from admin.db_router import ServiceDatabaseRouter

from .models import Organization, Subscription, User
from .pii import reveal
from .stats import Sources, cumulative, latest, pct
from .tiers import limits


class ServiceDatabaseRouterTests(SimpleTestCase):
    router = ServiceDatabaseRouter()

    def test_reads_go_to_owning_service(self):
        self.assertEqual(self.router.db_for_read(Organization), 'identity')

    def test_writes_are_refused(self):
        with self.assertRaises(PermissionError):
            self.router.db_for_write(Organization)

    def test_never_migrates_service_dbs(self):
        self.assertFalse(self.router.allow_migrate('identity', 'auth'))
        self.assertFalse(self.router.allow_migrate('default', 'servicedata'))
        self.assertIsNone(self.router.allow_migrate('default', 'auth'))


class LimitsTests(SimpleTestCase):
    def sub(self, **overrides):
        fields = {'tier': 'CORE', 'programme_limit_override': None, 'user_limit_override': None,
                  'ai_credit_allowance_override_usd': None, **overrides}
        return Subscription(**fields)

    def test_tier_defaults(self):
        self.assertEqual(limits(self.sub()), {'programmes': 2, 'users': None, 'ai_usd': 1.0})

    def test_overrides_win_including_zero(self):
        lim = limits(self.sub(programme_limit_override=0, ai_credit_allowance_override_usd=9.0))
        self.assertEqual((lim['programmes'], lim['ai_usd']), (0, 9.0))

    def test_no_subscription_is_unlimited(self):
        self.assertEqual(limits(None), {'programmes': None, 'users': None, 'ai_usd': None})


class StatsTests(SimpleTestCase):
    def test_failed_source_degrades_once(self):
        src, calls = Sources(), []

        def boom():
            calls.append(1)
            raise DatabaseError('down')

        self.assertEqual(src.fetch('agent', boom, 'fallback'), 'fallback')
        self.assertEqual(src.fetch('agent', boom, 'again'), 'again')
        self.assertEqual((len(calls), src.down), (1, ['agent']))

    def test_pct_and_cumulative_and_latest(self):
        self.assertIsNone(pct(5, None))
        self.assertEqual(pct(3, 4), 75)
        self.assertEqual(cumulative(10, [1, 0, 2]), [11, 11, 13])
        self.assertEqual(latest({'a': 1, 'b': 5}, {'a': 3, 'b': None}), {'a': 3, 'b': 5})


class PiiTests(SimpleTestCase):
    KEY = base64.b64encode(b'k' * 32).decode()
    USER_ID = '0123456789abcdef0123456789abcdef'

    def encrypt(self, text, salt='salt-value', iv='iv-value-not-12-bytes'):
        hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt.encode(), info=str(uuid.UUID(self.USER_ID)).encode())
        key = hkdf.derive(base64.b64decode(self.KEY))
        return base64.b64encode(AESGCM(key).encrypt(hashlib.sha256(iv.encode()).digest()[:12], text.encode(), None)).decode()

    def user(self):
        return User(id=self.USER_ID, salt='salt-value', iv='iv-value-not-12-bytes',
                    name_ciphertext=self.encrypt('Ada'), email_ciphertext=self.encrypt('ada@example.com'))

    def test_decrypts_with_key(self):
        with self.settings(MASTER_SECRET_KEY=self.KEY):
            self.assertEqual(reveal(self.user()), {'name': 'Ada', 'email': 'ada@example.com', 'decrypted': True})

    def test_without_or_with_wrong_key_falls_back(self):
        hidden = {'name': None, 'email': None, 'decrypted': False}
        with self.settings(MASTER_SECRET_KEY=''):
            self.assertEqual(reveal(self.user()), hidden)
        with self.settings(MASTER_SECRET_KEY=base64.b64encode(b'x' * 32).decode()):
            self.assertEqual(reveal(self.user()), hidden)
