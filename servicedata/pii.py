"""Decrypt Identity user names/emails when MASTER_SECRET_KEY is configured.

Mirrors pro3ai_generic.utils.encrypt_decrypt: AES-GCM with a per-user key from
HKDF(master, salt=user.salt, info=str(user UUID)); IV = user.iv, hashed to 12
bytes when it is not already 12 bytes. Without the key, callers show ciphertext.

ponytail: this copies Identity's master PII key into the admin app. Replace with
an Identity admin API (decrypting on Identity's side) before deploying.
"""

import base64
import hashlib
import logging
import uuid

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings

logger = logging.getLogger(__name__)


def enabled():
    return bool(settings.MASTER_SECRET_KEY)


def _iv(iv):
    raw = iv.encode()
    return raw if len(raw) == 12 else hashlib.sha256(raw).digest()[:12]


def _key(user_id, salt):
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt.encode(), info=str(uuid.UUID(user_id)).encode())
    return hkdf.derive(base64.b64decode(settings.MASTER_SECRET_KEY))


def decrypt(user_id, ciphertext, salt, iv):
    return AESGCM(_key(user_id, salt)).decrypt(_iv(iv), base64.b64decode(ciphertext), None).decode()


def reveal(user):
    """{'name', 'email', 'decrypted'}; name/email are None when not decryptable."""
    if user is None or not enabled():
        return {'name': None, 'email': None, 'decrypted': False}
    try:
        key = AESGCM(_key(user.id, user.salt))
        iv = _iv(user.iv)
        return {
            'name': key.decrypt(iv, base64.b64decode(user.name_ciphertext), None).decode(),
            'email': key.decrypt(iv, base64.b64decode(user.email_ciphertext), None).decode(),
            'decrypted': True,
        }
    except (InvalidTag, ValueError):
        logger.warning('could not decrypt user %s (wrong MASTER_SECRET_KEY?)', user.id)
        return {'name': None, 'email': None, 'decrypted': False}
