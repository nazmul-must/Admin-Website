from django import template

from servicedata.tiers import CREDITS_PER_USD

register = template.Library()


@register.filter
def credits(usd):
    """USD amount -> AI credits (1 credit = $0.01)."""
    return round((usd or 0) * CREDITS_PER_USD)


@register.filter
def get(mapping, key):
    return mapping.get(key) if mapping else None


@register.filter
def pct_class(pct):
    """Tailwind fill for a usage bar: brand teal, then RAG amber/red near and over the limit."""
    if pct is None:
        return 'bg-muted-foreground/40'
    if pct >= 100:
        return 'bg-rag-red'
    if pct >= 80:
        return 'bg-rag-amber'
    return 'bg-primary'


@register.filter
def status_class(status):
    return {
        'ACTIVE': 'bg-secondary text-secondary-foreground',
        'TRIALING': 'border-blue-200 bg-blue-50 text-blue-700',
        'PAST_DUE': 'border-amber-200 bg-amber-50 text-amber-700',
        'PENDING': 'bg-muted text-muted-foreground',
    }.get(status, 'border-red-200 bg-red-50 text-red-700')
