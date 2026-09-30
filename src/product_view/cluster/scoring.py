"""Impact scoring and the per-pain-point time series.

Four components, each converted to a **percentile rank** across clusters --
robust to the outliers min-max normalization would let dominate -- then
weighted into 0-100. **All four component values are stored on the object, not
just the total.** A PM who asks "why is this ranked #1" gets an answer instead
of a black box, and that answerability is what decides whether the dashboard
gets trusted or ignored.

**Calibration note, measured against this corpus.** The original design used
`tau=180` days and a 90-day momentum window. At 180 days only 3.6% of the
13,050-review negative stream carried any weight, and the 90-day window held
231 reviews -- about 5 per cluster, which is noise at a 0.20 weight. Defaults
here are 365/365: effective mass rises to 8.8%, and the momentum window holds
809 reviews (~16 per cluster). Both remain configurable.

Recency weighting is what makes "cluster all 15 years, rank by recency" work:
a 2016 issue still forms its cluster and keeps its history for the trend line,
but it sinks in the ranking unless it is still live.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

import numpy as np

DEFAULT_TAU_DAYS = 365
DEFAULT_MOMENTUM_WINDOW_DAYS = 365


@dataclass(frozen=True)
class Weights:
    recency: float = 0.40
    severity: float = 0.25
    momentum: float = 0.20
    endorsement: float = 0.15


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def monthly_counts(dates: Sequence[datetime]) -> dict[str, int]:
    """Raw `{"YYYY-MM": n}`. Deliberately raw: paired with the run-level corpus
    totals, share-of-month is derivable without any further machinery.

    That pairing matters here. October 2024 holds 1,663 negative reviews --
    35x the monthly baseline of ~48 -- so *every* cluster spikes that month on
    raw counts alone. Only dividing by the corpus total separates the pain
    points that drove the event from those merely carried along by it.
    """
    return dict(sorted(Counter(d.strftime("%Y-%m") for d in dates).items()))


def percentile_rank(values: Sequence[float]) -> np.ndarray:
    """Rank to [0,1]. Ties share the average rank."""
    from scipy.stats import rankdata

    arr = np.asarray(values, dtype=np.float64)
    if arr.size == 0:
        return arr
    if arr.size == 1:
        return np.array([1.0])
    return (rankdata(arr, method="average") - 1) / (arr.size - 1)


def cluster_stats(
    scores: Sequence[int],
    thumbs: Sequence[int],
    dates: Sequence[datetime | None],
    polarity: str,
    now: datetime,
    tau_days: float = DEFAULT_TAU_DAYS,
    momentum_window_days: float = DEFAULT_MOMENTUM_WINDOW_DAYS,
) -> dict:
    """Raw (un-ranked) statistics for one cluster."""
    valid = [d for d in dates if d is not None]
    ages = [(now - d).days for d in valid]
    n = max(len(scores), 1)

    mean_score = float(np.mean(scores)) if scores else 0.0
    if polarity == "negative":
        share_extreme = sum(1 for s in scores if s == 1) / n
        intensity = share_extreme + max(0.0, 3.0 - mean_score)
    else:
        share_extreme = sum(1 for s in scores if s == 5) / n
        intensity = share_extreme + max(0.0, mean_score - 3.0)

    recency_volume = sum(math.exp(-a / tau_days) for a in ages)
    in_window = sum(1 for a in ages if a <= momentum_window_days)
    # The fraction of this cluster that falls inside the window. The design
    # states momentum as (cluster's share of the window) / (its share of all
    # time); that equals this figure times N/W, and N and W are identical for
    # every cluster in a run -- so after percentile ranking the two are the
    # same ordering. Stored as the rank, so the constant drops out.
    momentum = in_window / n

    months = monthly_counts(valid)
    peak_month, peak_count = ("", 0)
    if months:
        peak_month, peak_count = max(months.items(), key=lambda kv: kv[1])

    return {
        "size": len(scores),
        "mean_score": mean_score,
        "pct_one_star": 100.0 * sum(1 for s in scores if s == 1) / n,
        "thumbs_up_total": int(sum(thumbs)),
        "first_seen": min(valid).strftime("%Y-%m-%d") if valid else None,
        "last_seen": max(valid).strftime("%Y-%m-%d") if valid else None,
        "peak_month": peak_month or None,
        "peak_count": int(peak_count),
        "count_90d": sum(1 for a in ages if a <= 90),
        "count_365d": sum(1 for a in ages if a <= 365),
        "monthly_counts": months,
        "_recency_volume": recency_volume,
        "_intensity": intensity,
        "_momentum": momentum,
        "_endorsement": math.log1p(sum(thumbs)),
    }


def apply_impact(stats: list[dict], weights: Weights = Weights()) -> list[dict]:
    """Percentile-rank each raw component across clusters, then combine to 0-100."""
    if not stats:
        return stats

    ranks = {
        "c_recency": percentile_rank([s["_recency_volume"] for s in stats]),
        "c_severity": percentile_rank([s["_intensity"] for s in stats]),
        "c_momentum": percentile_rank([s["_momentum"] for s in stats]),
        "c_endorsement": percentile_rank([s["_endorsement"] for s in stats]),
    }
    for i, row in enumerate(stats):
        for key, values in ranks.items():
            row[key] = float(values[i])
        row["impact"] = round(
            100.0
            * (
                weights.recency * row["c_recency"]
                + weights.severity * row["c_severity"]
                + weights.momentum * row["c_momentum"]
                + weights.endorsement * row["c_endorsement"]
            ),
            2,
        )
        for key in ("_recency_volume", "_intensity", "_momentum", "_endorsement"):
            row.pop(key, None)
    return stats
