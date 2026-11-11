"""Sign-in throttling: after MAX_FAILURES failed sign-ins for one email, that email is locked
until LOCKOUT_SECONDS have passed since its first failure.

Counted per email, not per IP: behind the ingress every request comes from the proxy's
address, so an IP limit would lock everyone out at once.
ponytail: counts live in Django's default cache (LocMemCache, one per process), so with N
workers an attacker gets N x MAX_FAILURES tries per window. Point CACHES at a shared backend
(database or Redis) when the site runs more than one worker; operator SSO + MFA replaces this.
"""

import hashlib

from django.core.cache import cache

MAX_FAILURES = 5
LOCKOUT_SECONDS = 15 * 60


def _key(email: str) -> str:
    """Cache key for an email's failure count (hashed: safe for any cache backend)."""
    return "signin-failures:" + hashlib.sha256(email.encode()).hexdigest()


def is_locked(email: str) -> bool:
    """Whether sign-in for this email is locked by too many recent failures."""
    return cache.get(_key(email), 0) >= MAX_FAILURES


def record_failure(email: str) -> None:
    """Count one failed sign-in for this email."""
    key = _key(email)
    cache.add(key, 0, LOCKOUT_SECONDS)
    try:
        cache.incr(key)
    except ValueError:  # expired between add() and incr()
        cache.set(key, 1, LOCKOUT_SECONDS)


def clear(email: str) -> None:
    """Forget the failures after a successful sign-in."""
    cache.delete(_key(email))
