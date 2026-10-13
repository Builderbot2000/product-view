"""Issues for one reporting period, read from the issue codebook.

The report is a periodic overview (report-design.md D15): it counts what was
said in the reporting period, against the periods before it. Issues come
from the codebook (issues.db), which spans the issue window and keeps each
issue's identity from run to run; this module only slices its matches by
date. Each issue is filed under one product area (chosen when the issue was
formed, from the app-agnostic list in curation.yaml), and areas map to roles
(D16). Every number is a count of distinct reviews (D10).
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..issues.codebook import Codebook
from ..store import Store

OTHER = "other"
SPARK_PERIODS = 12        # bars in every trend sparkline
SIGNIFICANCE = 0.05       # Poisson tail probability that counts as a change
MIN_CHANGE = 3            # fewer reviews than this never count as a change
SIDE = {"negative": "complaint", "positive": "praise"}


# --- taxonomy ---------------------------------------------------------------

@dataclass(frozen=True)
class Area:
    id: str
    name: str
    description: str = ""


@dataclass(frozen=True)
class Role:
    id: str
    name: str
    areas: tuple[str, ...]
    charts: tuple[str, ...] = ()   # extra charts on the role's page: versions


@dataclass
class Taxonomy:
    areas: dict[str, Area]
    roles: dict[str, Role]

    def area_name(self, area_id: str) -> str:
        return self.areas[area_id].name if area_id in self.areas else "Other"


def load_taxonomy(path: Path) -> Taxonomy:
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    data = data or {}
    areas = {k: Area(k, v["name"], v.get("description", ""))
             for k, v in (data.get("areas") or {}).items()}
    roles = {k: Role(k, v["name"], tuple(v.get("areas", [])), tuple(v.get("charts", [])))
             for k, v in (data.get("roles") or {}).items()}
    for role in roles.values():
        for a in role.areas:
            if a not in areas:
                raise ValueError(f"{path}: role {role.id!r} names unknown area {a!r}")
    return Taxonomy(areas, roles)


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
    def area(self) -> str:
        return self.areas[0] if self.areas else OTHER

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
        """This period's quotes, most thumbs-up first, then newest."""
        return sorted(self.quotes_now.values(),
                      key=lambda q: (-q.thumbs, -q.created.timestamp()))[:n]


@dataclass
class Stream:
    polarity: str
    run: dict
    period: Period
    issues: list[Issue]
    total: Series                       # every review in the star-rating stream
    unmatched_now: list[Quote]          # this period's stream reviews under no issue
    versions_now: Counter
    min_chars: int = 0                  # shorter reviews were left out

    def of_kind(self, kind: str) -> list[Issue]:
        return [i for i in self.issues if i.kind == kind]

    def in_areas(self, areas: tuple[str, ...] | list[str]) -> list[Issue]:
        return [i for i in self.of_kind("issue") if set(i.areas) & set(areas)]

    def area_series(self, area: str) -> Series:
        s = Series(self.period)
        for i in self.of_kind("issue"):
            if i.area == area:
                s.union(i.series)
        return s


def _dt(text: str) -> datetime:
    d = datetime.fromisoformat(text)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def report_period(store: Store, run: dict, days: int, baseline: int) -> Period:
    """End the period with the day of the newest review the run could see.

    Not the run date: reviews are fetched before a run, so the days between
    the fetch and the run hold nothing and would read as a sudden drop.
    """
    (newest,) = store.conn.execute(
        "SELECT max(created_at) FROM reviews WHERE created_at <= ?",
        (run["started_at"],)).fetchone()
    last = _dt(newest)
    end = datetime(last.year, last.month, last.day, tzinfo=timezone.utc) + timedelta(days=1)
    return Period(end, days, baseline)


def load_stream(store: Store, book: Codebook, polarity: str, days: int, baseline: int,
                threshold: float, min_chars: int = 20) -> Stream | None:
    """One stream's issues: the codebook's live concepts of that side, counted
    from their matches (a point scoring at or above `threshold`).

    Issue counts include every star rating, since a 4-star review can hold a
    complaint; the stream's total is still its star-rating stream (1-3 or 4-5
    stars), which is what the pages call negative and positive reviews.
    """
    side = SIDE[polarity]
    run = book.latest_run(side)
    if run is None:
        return None
    run = dict(run)
    period = report_period(store, run, days, baseline)

    issues: dict[str, Issue] = {}
    for c in book.concepts(side):
        kind = "issue" if c["kind"] == "issue" else "mood"
        issues[c["concept_id"]] = Issue(c["name"], kind, polarity,
                                        [c["area"] or OTHER] if kind == "issue" else [],
                                        Series(period))

    members = book.members(side, threshold)
    meta = {r["review_id"]: r for r in _review_meta(store, {m["review_id"] for m in members})}
    on_issue: set[str] = set()
    for m in members:                   # closest first, per concept
        issue, r = issues.get(m["concept_id"]), meta.get(m["review_id"])
        if issue is None or r is None or not r["created_at"]:
            continue
        rid = m["review_id"]
        if not issue.typical:
            issue.typical = m["quote"]
        issue.all_time.add(rid)
        created = _dt(r["created_at"])
        issue.series.add(created, rid)
        if issue.kind == "issue":
            on_issue.add(rid)
        if period.bucket(created) == 0 and rid not in issue.quotes_now:
            issue.quotes_now[rid] = Quote(" ".join(m["quote"].split()), r["score"],
                                          r["thumbs_up"] or 0, created, r["app_version"])
            issue.versions_now[r["app_version"] or "unknown"] += 1

    total = Series(period)
    unmatched: list[Quote] = []
    versions: Counter = Counter()
    for row in store.stream(polarity, min_chars=min_chars):
        if not row["created_at"]:
            continue
        created = _dt(row["created_at"])
        total.add(created, row["review_id"])
        if period.bucket(created) == 0:
            versions[row["app_version"] or "unknown"] += 1
            if row["review_id"] not in on_issue:
                unmatched.append(Quote(" ".join((row["content_en"] or "").split()),
                                       row["score"], row["thumbs_up"] or 0, created,
                                       row["app_version"]))
    unmatched.sort(key=lambda q: (-q.thumbs, -q.created.timestamp()))
    return Stream(polarity, run, period, list(issues.values()), total, unmatched, versions,
                  min_chars)


def _review_meta(store: Store, review_ids: set[str]) -> list:
    ids = sorted(review_ids)
    out = []
    for i in range(0, len(ids), 900):     # SQLite's variable limit
        chunk = ids[i:i + 900]
        out += store.conn.execute(
            f"SELECT review_id, score, thumbs_up, created_at, app_version FROM reviews "
            f"WHERE review_id IN ({','.join('?' * len(chunk))})", chunk).fetchall()
    return out


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
