"""Topic counts for one reporting period, read from the latest matching run.

Everything is derived here from the raw rows in topics.db (which units
matched which topic) and reviews.db (dates, stars, versions, text). Every
number is a count of distinct reviews (D10), and the period, "usual" and the
change test are the ones the earlier pages use (render/issues.py).

"No topic" is a complaint review none of whose units matched a topic: the
gaps in the topic list (D18). It is reported as a count with examples, never
as a topic.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..matrix import Matrix
from ..store import Store
from .issues import SPARK_PERIODS, Issue, Period, Quote, Series


# Quote rank, lowest shown first. A match the classifier was sure of is wrong
# far less often than one the model decided (2026-11-04 sample: about 1 in 22
# against 8 in 40), and a piece of a few words ("Nope, sign out") shows little
# even when it is right. Counts never depend on this, only which quotes show.
QUOTE_RANK = {"sure": 0, "model": 1}
SHORT_QUOTE_WORDS = 5          # fewer words than this: shown only when nothing better is


def quote_rank(how: str, text: str) -> int:
    return 2 if len(text.split()) < SHORT_QUOTE_WORDS else QUOTE_RANK.get(how, 1)


def periods_shown(baseline: int) -> int:
    """Periods a report shows: its trend, and the baseline behind "usual"."""
    return max(SPARK_PERIODS, baseline + 1)


def _dt(text: str) -> datetime:
    d = datetime.fromisoformat(text)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


@dataclass
class TopicReport:
    run: dict
    matrix: Matrix
    period: Period
    topics: dict[str, Issue]            # topic id -> its counts, as an Issue row
    total: Series                       # every complaint review
    no_topic: Series                    # complaint reviews with no topic
    no_topic_now: list[Quote]           # this period's, most liked first
    versions_now: Counter = field(default_factory=Counter)
    min_chars: int = 0
    short_window: bool = False          # the run matched fewer periods than the trend shows

    def of(self, topic_ids) -> list[Issue]:
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
    from ..topics import STREAM
    from ..topics.store import TopicStore

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

    rows = {r["review_id"]: r for r in store.stream(STREAM, min_chars=min_chars)
            if r["created_at"]}
    quote = {(u["review_id"], u["seq"]): u["quote"] for u in units}
    topics = {t.id: Issue(t.name, "issue", "negative", [], Series(period))
              for t in matrix.topics.values()}
    on_topic: set[str] = set()
    for m in matches:
        issue, r = topics.get(m["topic_id"]), rows.get(m["review_id"])
        if issue is None or r is None:    # a topic since removed, or a review since dropped
            continue
        rid = m["review_id"]
        created = _dt(r["created_at"])
        issue.series.add(created, rid)
        issue.all_time.add(rid)
        on_topic.add(rid)
        if period.bucket(created) == 0:
            # One quote per review and topic: the review's surest-fitting piece.
            text = quote[(rid, m["seq"])]
            rank = quote_rank(m["how"], text)
            held = issue.quotes_now.get(rid)
            if held is None:
                issue.versions_now[r["app_version"] or "unknown"] += 1
            if held is None or rank < held.rank:
                issue.quotes_now[rid] = Quote(text, r["score"], r["thumbs_up"] or 0, created,
                                              r["app_version"], rank)

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
