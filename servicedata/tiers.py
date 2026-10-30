"""Tier limits, served by Identity's `tiers` admin query (its tier.config.json).

ponytail: cached for the life of the process once fetched; a tier.config.json change
needs an admin site restart. Add a TTL if tiers start changing without deploys.
"""

from . import rpc

CREDITS_PER_USD = 100  # 1 AI credit = $0.01 (see tier.config.json)

_cache = {}


def tiers():
    """{tier key: config}; {} while Identity is unreachable (not cached, so it retries)."""
    if 'tiers' not in _cache:
        try:
            _cache['tiers'] = rpc.query('identity', 'tiers') or {}
        except rpc.ServiceUnavailable:
            return {}
    return _cache['tiers']


def tier_name(tier):
    if not tier:
        return 'No subscription'
    return tiers().get(tier.lower(), {}).get('display_name') or tier.replace('_', ' ').title()


def limits(sub):
    """Effective limits for a subscription; None means unlimited. Per-org overrides win."""
    if sub is None:
        return {'programmes': None, 'users': None, 'ai_usd': None}
    tier = tiers().get(sub['tier'].lower(), {})

    def pick(override, key):
        return override if override is not None else tier.get(key)

    return {
        'programmes': pick(sub['programme_limit_override'], 'programme_limit'),
        'users': pick(sub['user_limit_override'], 'user_limit'),
        'ai_usd': pick(sub['ai_credit_allowance_override_usd'], 'ai_credit_allowance_usd'),
    }
