"""Periods, counts and quotes: what every report page is made of.

The report is a periodic overview (report-design.md D15): it counts what was
said in the reporting period, against the periods before it. A row on a page
(`Issue`, which the topic pages fill per topic) holds a `Series` of distinct
reviews per period (D10), this period's quotes and app versions. The change
test (`Series.change`) decides what reads as up, down or new.

`load_taxonomy` reads the product areas in curation.yaml, which `pv issues`
files its issues under.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

SPARK_PERIODS = 12        # bars in every trend sparkline
SIGNIFICANCE = 0.05       # Poisson tail probability that counts as a change
MIN_CHANGE = 3            # fewer reviews than this never count as a change


# --- taxonomy ---------------------------------------------------------------

@dataclass(frozen=True)
class Area:
    id: str
    name: str
    description: str = ""


@dataclass
class Taxonomy:
    areas: dict[str, Area]


def load_taxonomy(path: Path) -> Taxonomy:
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    data = data or {}
    return Taxonomy({k: Area(k, v["name"], v.get("description", ""))
                     for k, v in (data.get("areas") or {}).items()})


# --- periods and change -----------------------------------------------------

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
        return max(SPARK_PERIODS, self.baseline + 1)

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
        reviews across ~25 issues), so a ratio alone would flag 1 -> 3 as
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


# --- issues -----------------------------------------------------------------

@dataclass
class Quote:
    text: str
    score: int
    thumbs: int
    created: datetime
    version: str | None
    rank: int = 0                 # lower shows first: how surely the quote fits its topic


@dataclass
class Issue:
    label: str
    kind: str                     # issue | mood (general sentiment, no single thing to fix)
    polarity: str
    areas: list[str]
    series: Series
    typical: str = ""             # the closest-matching point of all time
    all_time: set[str] = field(default_factory=set)
    quotes_now: dict[str, Quote] = field(default_factory=dict)
    versions_now: Counter = field(default_factory=Counter)

    @property
    def now(self) -> int:
        return self.series.now

    @property
    def usual(self) -> float:
        return self.series.usual

    @property
    def change(self) -> str:
        return self.series.change

    @property
    def quote(self) -> str:
        """The standing "in users' words": the point that fits the issue best."""
        return " ".join(self.typical.split())

    def recent_quotes(self, n: int = 3) -> list[Quote]:
        """This period's quotes: surest fit first (`rank`), then most thumbs-up, then newest."""
        return sorted(self.quotes_now.values(),
                      key=lambda q: (q.rank, -q.thumbs, -q.created.timestamp()))[:n]


# --- orderings (D12) --------------------------------------------------------

CHANGE_ORDER = {"new": 0, "up": 1, "down": 2, "steady": 3, "quiet": 4}


def by_volume(issues: list[Issue]) -> list[Issue]:
    """This period's count, then the usual level."""
    return sorted(issues, key=lambda i: (-i.now, -i.usual, i.label))


def by_change(issues: list[Issue]) -> list[Issue]:
    """New, then up (largest excess first), then down; steady issues dropped."""
    moved = [i for i in issues if i.change in ("new", "up", "down")]
    return sorted(moved, key=lambda i: (CHANGE_ORDER[i.change], -(i.now - i.usual)
                                        if i.change != "down" else i.now - i.usual))
