"""Topic counts for one reporting period, read from the latest matching run.

Everything is derived here from the raw rows in topics.db (which units
matched which topic) and reviews.db (dates, stars, versions, text). Every
number is a count of distinct reviews (D10), and the period, "usual" and the
change test are periods.py's. A topic's row (`TopicCounts`) holds its
`Series`, this period's quotes and app versions.

"No topic" is a complaint review none of whose units matched a topic: the
gaps in the topic list (D18). It is reported as a count with examples, never
as a topic.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..matching.store import TopicStore
from ..matrix import Matrix
from ..periods import Period, Series
from ..store import COMPLAINTS, Store


# Quote rank, lowest shown first. A match the classifier was sure of is wrong
# far less often than one the model decided (2026-11-04 sample: about 1 in 22
# against 8 in 40), and a piece of a few words ("Nope, sign out") shows little
# even when it is right. Counts never depend on this, only which quotes show.
QUOTE_RANK = {"sure": 0, "model": 1}
SHORT_QUOTE_WORDS = 5          # fewer words than this: shown only when nothing better is


def quote_rank(how: str, text: str) -> int:
    return 2 if len(text.split()) < SHORT_QUOTE_WORDS else QUOTE_RANK.get(how, 1)


def _dt(text: str) -> datetime:
    d = datetime.fromisoformat(text)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


@dataclass
class Quote:
    text: str
    score: int
    thumbs: int
    created: datetime
    version: str | None
    rank: int = 0                 # lower shows first: how surely the quote fits its topic
    full: str = ""                # the whole review, when the quote is a part of it


@dataclass
class TopicCounts:
    """One topic's row on a page: its reviews per period and this period's quotes."""
    name: str
    series: Series
    quotes_now: dict[str, Quote] = field(default_factory=dict)   # review id -> its quote
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

    def recent_quotes(self, n: int = 3) -> list[Quote]:
        """This period's quotes: surest fit first (`rank`), then most thumbs-up, then newest."""
        return sorted(self.quotes_now.values(),
                      key=lambda q: (q.rank, -q.thumbs, -q.created.timestamp()))[:n]


# --- orderings (D12) --------------------------------------------------------

CHANGE_ORDER = {"new": 0, "up": 1, "down": 2, "steady": 3, "quiet": 4}


def by_volume(topics: list[TopicCounts]) -> list[TopicCounts]:
    """This period's count, then the usual level."""
    return sorted(topics, key=lambda t: (-t.now, -t.usual, t.name))


def by_change(topics: list[TopicCounts]) -> list[TopicCounts]:
    """New, then up (largest excess first), then down; steady topics dropped."""
    moved = [t for t in topics if t.change in ("new", "up", "down")]
    return sorted(moved, key=lambda t: (CHANGE_ORDER[t.change], -(t.now - t.usual)
                                        if t.change != "down" else t.now - t.usual))


# --- the report ---------------------------------------------------------------

@dataclass
class TopicReport:
    run: dict
    matrix: Matrix
    period: Period
    topics: dict[str, TopicCounts]      # topic id -> its counts
    total: Series                       # every complaint review
    no_topic: Series                    # complaint reviews with no topic
    no_topic_now: list[Quote]           # this period's, most liked first
    versions_now: Counter = field(default_factory=Counter)
    min_chars: int = 0
    short_window: bool = False          # the run matched fewer periods than the trend shows

    def of(self, topic_ids) -> list[TopicCounts]:
        return [self.topics[t] for t in topic_ids]

    def union(self, topic_ids) -> Series:
        """Distinct reviews on any of these topics."""
        s = Series(self.period)
        for t in topic_ids:
            s.union(self.topics[t].series)
        return s


def load(store: Store, topic_db: Path, matrix: Matrix, days: int, baseline: int,
         min_chars: int = 20) -> TopicReport | None:
    """The latest finished run, sliced into periods. None when there is no run."""
    if not topic_db.exists():
        return None
    with TopicStore(topic_db) as ts:
        run = ts.latest()
        if run is None:
            return None
        run = dict(run)
        units = ts.units(run["run_id"])
        matches = ts.matches(run["run_id"])

    end = _dt(run["window_end"])
    period = Period(end, days, baseline)
    short = _dt(run["window_start"]) > end - (period.end - period.start) * period.n_buckets

    rows = {r["review_id"]: r for r in store.stream(COMPLAINTS, min_chars=min_chars)
            if r["created_at"]}
    quote = {(u["review_id"], u["seq"]): u["quote"] for u in units}
    topics = {t.id: TopicCounts(t.name, Series(period))
              for t in matrix.topics.values()}
    on_topic: set[str] = set()
    for m in matches:
        counts, r = topics.get(m["topic_id"]), rows.get(m["review_id"])
        if counts is None or r is None:    # a topic since removed, or a review since dropped
            continue
        rid = m["review_id"]
        created = _dt(r["created_at"])
        counts.series.add(created, rid)
        on_topic.add(rid)
        if period.bucket(created) == 0:
            # One quote per review and topic: the review's surest-fitting piece.
            text = quote[(rid, m["seq"])]
            rank = quote_rank(m["how"], text)
            held = counts.quotes_now.get(rid)
            if held is None:
                counts.versions_now[r["app_version"] or "unknown"] += 1
            if held is None or rank < held.rank:
                counts.quotes_now[rid] = Quote(text, r["score"], r["thumbs_up"] or 0, created,
                                              r["app_version"], rank,
                                              " ".join((r["content_en"] or "").split()))

    seen = {u["review_id"] for u in units}
    total, no_topic = Series(period), Series(period)
    no_topic_now: list[Quote] = []
    versions: Counter = Counter()
    for rid, r in rows.items():
        created = _dt(r["created_at"])
        if period.bucket(created) is None:
            continue
        total.add(created, rid)
        if rid not in seen:               # newer than the run, or outside its window
            continue
        if period.bucket(created) == 0:
            versions[r["app_version"] or "unknown"] += 1
        if rid not in on_topic:
            no_topic.add(created, rid)
            if period.bucket(created) == 0:
                no_topic_now.append(Quote(" ".join((r["content_en"] or "").split()), r["score"],
                                          r["thumbs_up"] or 0, created, r["app_version"]))
    no_topic_now.sort(key=lambda q: (-q.thumbs, -q.created.timestamp()))
    return TopicReport(run, matrix, period, topics, total, no_topic, no_topic_now, versions,
                       min_chars, short)
