"""Subscriptions, tier limits and how close an org is to them.

Tier limits come from Identity's `tiers` admin query (its tier.config.json).
ponytail: cached for the life of the process once fetched; a tier.config.json change
needs an admin site restart. Add a TTL if tiers start changing without deploys.
"""

from typing import Any, Literal

from . import rpc
from .contracts import Subscription, Tier
from .stats import Sources

CREDITS_PER_USD = 100  # 1 AI credit = $0.01 (see tier.config.json)
NEAR_LIMIT_PCT = 80  # amber from here
AT_LIMIT_PCT = 100  # red from here

_cache: dict[str, dict[str, Tier]] = {}


def tiers() -> dict[str, Tier]:
    """{tier key: config}; {} while Identity is unreachable (not cached, so it retries)."""
    if "tiers" not in _cache:
        try:
            _cache["tiers"] = rpc.query("identity", "tiers") or {}
        except rpc.ServiceUnavailable:
            return {}
    return _cache["tiers"]


def subscriptions(src: Sources) -> dict[str, Subscription]:
    """Every live subscription, keyed by org id."""
    return {s["org_id"]: s for s in src.query("identity", "subscriptions", [])}


def tier_name(tier: str | None) -> str:
    """Display name of a tier key, e.g. 'CORE' -> 'Core'."""
    if not tier:
        return "No subscription"
    return tiers().get(tier.lower(), {}).get("display_name") or tier.replace("_", " ").title()


def limits(sub: Subscription | None) -> dict[str, Any]:
    """Effective limits for a subscription; None means unlimited. Per-org overrides win."""
    if sub is None:
        return {"programmes": None, "users": None, "ai_usd": None}
    tier = tiers().get(sub["tier"].lower(), {})

    def pick(override: float | None, key: str) -> Any:
        return override if override is not None else tier.get(key)

    return {
        "programmes": pick(sub["programme_limit_override"], "programme_limit"),
        "users": pick(sub["user_limit_override"], "user_limit"),
        "ai_usd": pick(sub["ai_credit_allowance_override_usd"], "ai_credit_allowance_usd"),
    }


def usage_level(pct: int | None) -> Literal["red", "amber"] | None:
    """RAG level of a usage percentage: red at or over the limit, amber near it, else None."""
    if pct is None or pct < NEAR_LIMIT_PCT:
        return None
    return "red" if pct >= AT_LIMIT_PCT else "amber"
