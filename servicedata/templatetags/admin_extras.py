"""Template filters for service data: AI credits, map lookup and status colours."""

from collections.abc import Mapping
from typing import Any

from django import template

from servicedata.tiers import CREDITS_PER_USD, usage_level

register = template.Library()

USAGE_BAR_CLASSES = {None: "bg-primary", "amber": "bg-rag-amber", "red": "bg-rag-red"}


@register.filter(name="credits")
def usd_to_credits(usd: float | None) -> int:
    """USD amount -> AI credits (1 credit = $0.01)."""
    return round((usd or 0) * CREDITS_PER_USD)


@register.filter(name="get")
def mapping_value(mapping: Mapping[Any, Any] | None, key: Any) -> Any:
    """`mapping[key]` in a template, None when missing."""
    return mapping.get(key) if mapping else None


@register.filter
def pct_class(pct: int | None) -> str:
    """Tailwind fill for a usage bar: brand teal, then RAG amber/red near and over the limit."""
    if pct is None:
        return "bg-muted-foreground/40"
    return USAGE_BAR_CLASSES[usage_level(pct)]


@register.filter
def status_class(status: str) -> str:
    """Badge classes for a subscription status."""
    return {
        "ACTIVE": "bg-secondary text-secondary-foreground",
        "TRIALING": "border-blue-200 bg-blue-50 text-blue-700",
        "PAST_DUE": "border-amber-200 bg-amber-50 text-amber-700",
        "PENDING": "bg-muted text-muted-foreground",
    }.get(status, "border-red-200 bg-red-50 text-red-700")
