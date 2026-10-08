"""Issues for one reporting period, derived from a clustering run plus curation.

The report is a periodic overview (report-design.md D15): it counts what was
said in the reporting period, against the periods before it. Clustering
still spans all history, because that is what gives issues stable, well-fed
definitions; this module only slices the run's members by date.

An issue is one or more pain points under one label (D8, D14). Clusters are
matched to curated labels through *anchor reviews*, not cluster ids, so the
curation survives the re-clustering every scheduled run does. Each issue is
filed under product areas, and areas map to roles (D16). Every number is
recomputed here from `pain_point_members` as distinct reviews (D10).
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..cluster.vague import BUCKET_TITLES, focus
from ..models import PainPoint
from ..store import Store

KINDS = ("issue", "mood", "outcome", "hide")
OTHER = "other"
SPARK_PERIODS = 12        # bars in every trend sparkline
SIGNIFICANCE = 0.05       # Poisson tail probability that counts as a change
MIN_CHANGE = 3            # fewer reviews than this never count as a change


# --- taxonomy ---------------------------------------------------------------

@dataclass(frozen=True)
class Area:
    id: str
    name: str
    keywords: tuple[str, ...]


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
    labels: dict[str, dict[str, dict]]   # polarity -> label -> {kind, areas, anchors}
    fold_focus_below: float = 0.2        # uncurated clusters less focused than this -> mood bucket

    def area_name(self, area_id: str) -> str:
        return self.areas[area_id].name if area_id in self.areas else "Other"

    def classify(self, pp: PainPoint) -> list[str]:
        """File an uncurated cluster by keyword hits; best area first."""
        words = {k.lower() for k in pp.keywords} | set(pp.title.lower().split())
        hits = {a.id: sum(1 for k in a.keywords if k in words) for a in self.areas.values()}
        best = max(hits.values(), default=0)
        return [next(a for a, n in hits.items() if n == best)] if best else [OTHER]


def load_taxonomy(path: Path) -> Taxonomy:
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    data = data or {}
    areas = {k: Area(k, v["name"], tuple(w.lower() for w in v.get("keywords", [])))
             for k, v in (data.get("areas") or {}).items()}
    roles = {k: Role(k, v["name"], tuple(v.get("areas", [])), tuple(v.get("charts", [])))
             for k, v in (data.get("roles") or {}).items()}
    labels = data.get("issues") or {}
    for role in roles.values():
        for a in role.areas:
            if a not in areas:
                raise ValueError(f"{path}: role {role.id!r} names unknown area {a!r}")
    for polarity, entries in labels.items():
        for label, e in (entries or {}).items():
            if e.get("kind", "issue") not in KINDS:
                raise ValueError(f"{path}: {polarity} {label!r}: kind must be one of {KINDS}")
            for a in e.get("areas", []):
                if a not in areas:
                    raise ValueError(f"{path}: {polarity} {label!r}: unknown area {a!r}")
    return Taxonomy(areas, roles, labels, float(data.get("fold_focus_below", 0.2)))


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
    kind: str
    polarity: str
    areas: list[str]
    curated: bool
    series: Series
    members: list[PainPoint] = field(default_factory=list)   # largest first
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
        """The largest member's medoid unit: the standing "in users' words"."""
        lead = self.members[0]
        return " ".join((lead.canonical_text or lead.title).split())

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
    total: Series                       # every review in the stream
    unmatched_now: list[Quote]          # this period's reviews in no cluster
    versions_now: Counter

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


def _match_labels(store: Store, run_id: str, labels: dict[str, dict]) -> dict[str, str]:
    """pain_point_id -> curated label, by the anchor reviews each cluster holds.

    Anchors are the medoid reviews of the clusters as curated. An anchor
    belongs to the cluster it is still the medoid of; failing that (after a
    re-cluster), to the cluster where its unit is most central, since a
    review raising several problems sits in several clusters. A cluster
    takes the label with most anchors; ties go to the label listed first.
    """
    anchor_label = {rid: label for label, e in labels.items() for rid in e.get("anchors", [])}
    order = {label: n for n, label in enumerate(labels)}
    home: dict[str, tuple[float, str]] = {}
    if anchor_label:
        q = ",".join("?" * len(anchor_label))
        for pp_id, rid, sim in store.conn.execute(
                f"SELECT pain_point_id, review_id, similarity FROM pain_point_members "
                f"WHERE run_id = ? AND review_id IN ({q})", (run_id, *anchor_label)):
            if rid not in home or sim > home[rid][0]:
                home[rid] = (sim, pp_id)
        for pp_id, rid in store.conn.execute(
                f"SELECT pain_point_id, canonical_review_id FROM pain_points "
                f"WHERE run_id = ? AND canonical_review_id IN ({q})", (run_id, *anchor_label)):
            home[rid] = (math.inf, pp_id)
    # The set-aside bucket is its own thing; an anchor that fell into it must
    # not hand it a curated label (it would then be filed as that issue).
    bucket = {r[0] for r in store.conn.execute(
        "SELECT pain_point_id FROM pain_points WHERE run_id = ? AND title IN (?, ?)",
        (run_id, *BUCKET_TITLES.values()))}
    votes: dict[str, Counter] = {}
    for rid, (_, pp_id) in home.items():
        if pp_id in bucket:
            continue
        votes.setdefault(pp_id, Counter())[anchor_label[rid]] += 1
    return {pp_id: min(c, key=lambda lb: (-c[lb], order[lb])) for pp_id, c in votes.items()}


def load_stream(store: Store, polarity: str, taxonomy: Taxonomy, days: int,
                baseline: int, min_chars: int = 20) -> Stream | None:
    run = store.latest_run(polarity)
    if run is None:
        return None
    run = dict(run)
    period = report_period(store, run, days, baseline)
    labels = taxonomy.labels.get(polarity, {})
    matched = _match_labels(store, run["run_id"], labels)

    # How tightly each cluster's units point at one thing (vague.focus).
    unit_texts: dict[str, list[str]] = {}
    for row in store.conn.execute(
            "SELECT pain_point_id, unit_text FROM pain_point_members WHERE run_id = ?",
            (run["run_id"],)):
        unit_texts.setdefault(row[0], []).append(row[1] or "")

    groups: dict[str, Issue] = {}
    hidden: set[str] = set()
    for row in store.pain_points(run["run_id"], sort="size", limit=10_000):
        pp = PainPoint.from_row(row)
        label = matched.get(pp.pain_point_id)
        entry = labels.get(label, {}) if label else {}
        kind = entry.get("kind", "issue")
        if label is None and pp.title in BUCKET_TITLES.values():
            kind = "mood"
        elif (label is None and taxonomy.fold_focus_below > 0
              and focus(unit_texts.get(pp.pain_point_id, [])) < taxonomy.fold_focus_below):
            # An uncurated cluster that points at nothing in particular joins
            # the bucket; curated issues and outcomes are never folded.
            label, kind = BUCKET_TITLES[polarity], "mood"
            entry = {}
        if kind == "hide":
            hidden.add(pp.pain_point_id)
            continue
        if label is None:
            label = pp.title
            areas = [] if kind == "mood" else taxonomy.classify(pp)
        else:
            areas = list(entry.get("areas") or ([] if kind != "issue" else [OTHER]))
        issue = groups.get(label)
        if issue is None:
            issue = groups[label] = Issue(label, kind, polarity, areas, label in labels,
                                          Series(period))
        issue.members.append(pp)          # already largest first

    owner = {pp.pain_point_id: i for i in groups.values() for pp in i.members}
    clustered: set[str] = set()
    for row in store.member_reviews(run["run_id"]):
        clustered.add(row["review_id"])
        issue = owner.get(row["pain_point_id"])
        if issue is None:
            continue
        rid = row["review_id"]
        issue.all_time.add(rid)
        if not row["created_at"]:
            continue
        created = _dt(row["created_at"])
        issue.series.add(created, rid)
        # Rows come most-central unit first, so a review's first unit wins.
        if period.bucket(created) == 0 and rid not in issue.quotes_now:
            issue.quotes_now[rid] = Quote(" ".join((row["unit_text"] or "").split()),
                                          row["score"], row["thumbs_up"] or 0, created,
                                          row["app_version"])
            issue.versions_now[row["app_version"] or "unknown"] += 1

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
            if row["review_id"] not in clustered:
                unmatched.append(Quote(" ".join((row["content_en"] or "").split()),
                                       row["score"], row["thumbs_up"] or 0, created,
                                       row["app_version"]))
    unmatched.sort(key=lambda q: (-q.thumbs, -q.created.timestamp()))
    return Stream(polarity, run, period, list(groups.values()), total, unmatched, versions)


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
