"""Chart.js configs built server-side; static/js/charts.js renders them."""

from collections.abc import Iterable, Mapping
from typing import Any

from servicedata.tiers import CREDITS_PER_USD

# Pro3AI data-vis series (design system §3.5), then slate for overflow.
COLORS = ["#0d9488", "#E76E50", "#0f172a", "#2A9D90", "#E8C468", "#F4A462", "#274754", "#94a3b8"]
NAMED = {"Allowed": "#0d9488", "Denied": "#E53F2C", "Failed": "#E53F2C"}


def chart(
    kind: str,
    labels: Iterable[str],
    series: Mapping[str, Any],
    stacked: bool = False,
    horizontal: bool = False,
) -> dict[str, Any]:
    """`series` maps dataset label -> values. For doughnuts it maps slice label -> value.
    Series named in NAMED keep a fixed colour (e.g. Denied is always red)."""
    if kind == "doughnut":
        labels = [str(k) for k in series]
        datasets = [
            {"data": list(series.values()), "backgroundColor": COLORS[: len(series)] or COLORS}
        ]
    else:
        datasets = [
            {
                "label": name,
                "data": list(values),
                "backgroundColor": NAMED.get(name, COLORS[i % len(COLORS)]),
                "borderColor": NAMED.get(name, COLORS[i % len(COLORS)]),
                "tension": 0.3,
                "pointRadius": 0,
                "borderWidth": 2,
            }
            for i, (name, values) in enumerate(series.items())
        ]
    options = {
        "responsive": True,
        "maintainAspectRatio": False,
        "interaction": {"mode": "index", "intersect": False},
        "plugins": {
            "legend": {"position": "bottom", "display": kind == "doughnut" or len(series) > 1}
        },
    }
    if kind != "doughnut":
        options["scales"] = {
            "x": {"stacked": stacked, "ticks": {"maxTicksLimit": 12, "precision": 0}},
            "y": {"stacked": stacked, "beginAtZero": True, "ticks": {"precision": 0}},
        }
        if horizontal:
            options["indexAxis"] = "y"
    return {
        "type": kind,
        "data": {"labels": list(labels), "datasets": datasets},
        "options": options,
    }


def ranked(counts: Mapping[str, float], top: int = 10) -> dict[str, float]:
    """Largest-first {label: value}; a NULL group ('null' on the wire) is shown as '(none)'."""
    items = sorted(counts.items(), key=lambda kv: kv[1] or 0, reverse=True)[:top]
    return {("(none)" if k == "null" else k): v for k, v in items}


def to_credits(usd_values: Iterable[float | None]) -> list[int]:
    """USD amounts as AI credits (1 credit = $0.01)."""
    return [round((v or 0) * CREDITS_PER_USD) for v in usd_values]
