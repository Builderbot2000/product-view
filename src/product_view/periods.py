"""Reporting periods, and the change test that reads a count as up, down or new.

The report is a periodic overview (report-design.md D15): it counts what was
said in the reporting period, against the equal periods before it. A `Series`
holds the distinct reviews per period (D10); `Series.change` tests this
period's count against "usual", the mean of the baseline periods.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

SPARK_PERIODS = 12        # bars in every trend sparkline
SIGNIFICANCE = 0.05       # Poisson tail probability that counts as a change
MIN_CHANGE = 3            # fewer reviews than this never count as a change


def periods_shown(baseline: int) -> int:
    """Periods a report shows: its trend, and the baseline behind "usual".
    Matching covers the same window."""
    return max(SPARK_PERIODS, baseline + 1)


@dataclass(frozen=True)
class Period:
    """The reporting period and the equal-length periods before it.

    Period 0 ends at `end` (exclusive); period k covers the `days` before
    period k-1. The baseline is the mean of periods 1..`baseline`.
    """
    end: datetime
    days: int
    baseline: int

    @property
    def start(self) -> datetime:
        return self.end - timedelta(days=self.days)

    @property
    def n_buckets(self) -> int:
        return periods_shown(self.baseline)

    def bucket(self, created: datetime) -> int | None:
        if created >= self.end:
            return None
        k = (self.end - created) // timedelta(days=self.days)
        return k if k < self.n_buckets else None

    def label(self) -> str:
        last = self.end - timedelta(days=1)
        return f"{self.start:%b} {self.start.day} – {last:%b} {last.day}, {last.year}"


def _poisson_cdf(k: int, mu: float) -> float:
    """P(X <= k) for X ~ Poisson(mu)."""
    if k < 0:
        return 0.0
    term = total = math.exp(-mu)
    for i in range(1, k + 1):
        term *= mu / i
        total += term
    return min(1.0, total)


@dataclass
class Series:
    """Distinct reviews per period, newest first: buckets[0] is this period."""
    period: Period
    ids: list[set[str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.ids:
            self.ids = [set() for _ in range(self.period.n_buckets)]

    def add(self, created: datetime, review_id: str) -> None:
        k = self.period.bucket(created)
        if k is not None:
            self.ids[k].add(review_id)

    def union(self, other: "Series") -> None:
        for mine, theirs in zip(self.ids, other.ids):
            mine |= theirs

    @property
    def counts(self) -> list[int]:
        return [len(s) for s in self.ids]

    @property
    def now(self) -> int:
        return len(self.ids[0])

    @property
    def usual(self) -> float:
        prior = self.counts[1:self.period.baseline + 1]
        return sum(prior) / len(prior) if prior else 0.0

    @property
    def change(self) -> str:
        """new | up | down | steady | quiet, tested against a Poisson baseline.

        Counts per period are small (a 28-day period holds ~70 negative
        reviews across ~25 topics), so a ratio alone would flag 1 -> 3 as
        "x3". The test asks whether this period's count is surprising given
        the baseline rate, and ignores anything under MIN_CHANGE reviews.
        """
        now, usual = self.now, self.usual
        if now == 0 and usual < 0.5:
            return "quiet"
        if usual == 0:
            return "new" if now >= MIN_CHANGE else "steady"
        if now >= MIN_CHANGE and 1 - _poisson_cdf(now - 1, usual) < SIGNIFICANCE:
            return "up"
        if usual >= MIN_CHANGE and _poisson_cdf(now, usual) < SIGNIFICANCE:
            return "down"
        return "steady"

    def spark(self) -> list[int]:
        """The last SPARK_PERIODS counts, oldest first."""
        return self.counts[:SPARK_PERIODS][::-1]
