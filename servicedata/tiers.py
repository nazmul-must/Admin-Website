"""Tier limits from Identity-Backend's tier.config.json.

ponytail: read from Identity's repo file locally; serve it from Identity's
admin API once that exists, so the deployed admin site needs no repo checkout.
"""

import json
from functools import lru_cache

from django.conf import settings

CREDITS_PER_USD = 100  # 1 AI credit = $0.01 (see tier.config.json)


@lru_cache
def tiers():
    try:
        return json.loads(settings.TIER_CONFIG_PATH.read_text())['tiers']
    except (OSError, ValueError, KeyError):
        return {}


def tier_name(tier):
    if not tier:
        return 'No subscription'
    return tiers().get(tier.lower(), {}).get('display_name') or tier.replace('_', ' ').title()


def limits(sub):
    """Effective limits for a subscription; None means unlimited. Per-org overrides win."""
    if sub is None:
        return {'programmes': None, 'users': None, 'ai_usd': None}
    tier = tiers().get(sub.tier.lower(), {})

    def pick(override, key):
        return override if override is not None else tier.get(key)

    return {
        'programmes': pick(sub.programme_limit_override, 'programme_limit'),
        'users': pick(sub.user_limit_override, 'user_limit'),
        'ai_usd': pick(sub.ai_credit_allowance_override_usd, 'ai_credit_allowance_usd'),
    }
