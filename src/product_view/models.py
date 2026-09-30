"""The normalized review record.

This schema is the contract between ingestion and everything downstream. The
Play Store scraper is one producer of it; the future internal feed will be
another. Nothing outside `ingest/` should know what a Play Store review dict
looks like.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


def _iso(dt: datetime | None) -> str | None:
    """Normalize to UTC ISO-8601. Play returns naive UTC datetimes."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Review:
    review_id: str
    app_id: str
    source: str
    lang: str
    country: str
    content: str
    score: int
    thumbs_up: int
    created_at: str | None
    app_version: str | None = None
    review_created_version: str | None = None
    reply_content: str | None = None
    replied_at: str | None = None
    fetched_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    content_hash: str = ""

    def __post_init__(self) -> None:
        if not self.content_hash:
            object.__setattr__(self, "content_hash", content_hash(self.content or ""))

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_play_store(
        cls, raw: dict, app_id: str, lang: str, country: str
    ) -> "Review":
        """Map one google-play-scraper dict onto the normalized schema.

        `userName` and `userImage` are deliberately dropped. Pain point
        clustering never needs reviewer identity, and not collecting it beats
        collecting it and having to justify the retention later.
        """
        return cls(
            review_id=raw["reviewId"],
            app_id=app_id,
            source="google_play",
            lang=lang,
            country=country,
            content=raw.get("content") or "",
            score=raw.get("score") or 0,
            thumbs_up=raw.get("thumbsUpCount") or 0,
            created_at=_iso(raw.get("at")),
            app_version=raw.get("appVersion"),
            review_created_version=raw.get("reviewCreatedVersion"),
            reply_content=raw.get("replyContent"),
            replied_at=_iso(raw.get("repliedAt")),
        )


@dataclass(frozen=True)
class PainPoint:
    """A cluster of related complaints, synthesized into something a PM can read.

    Clustered per complaint unit, counted per review: `size` is the number of
    distinct reviews that raise it, so one review can count toward several
    pain points, and `unit_count` is how many complaint units that took.

    The read-side contract: `cluster/pipeline.py` builds these as dicts and
    `store.py` persists them to real columns, then anything presenting a pain
    point -- `pv painpoints` today, the dashboard later -- rebuilds them
    through `from_row` so both read identical data.

    Every sortable statistic is a flat attribute rather than a field inside
    `stats`, because the audience re-ranks this table by whichever column
    answers their question.
    """

    run_id: str
    pain_point_id: str
    polarity: str
    title: str
    message: str
    keywords: list[str]
    canonical_review_id: str
    # The medoid unit: the words of the canonical review that placed it here.
    canonical_text: str

    size: int
    unit_count: int
    # Share of its reviews in which this is the only pain point raised. Low
    # means it mostly rides along beside other complaints -- the signature of
    # generic sentiment ("worst bank ever") rather than a specific problem.
    sole_share: float
    pct_of_stream: float
    mean_score: float
    pct_one_star: float
    thumbs_up_total: int
    cohesion: float

    first_seen: str | None
    last_seen: str | None
    peak_month: str | None
    peak_count: int
    count_90d: int
    count_365d: int

    impact: float
    impact_components: dict[str, float]

    # MMR-selected against the centroid, so they span the range of phrasing.
    # The five most *central* members would be near-identical restatements of
    # the canonical quote.
    representative_review_ids: list[str]

    # Raw {"YYYY-MM": n}. Divide by the run's `corpus_monthly_json` for
    # share-of-month: in a 35x spike month every cluster rises on raw counts,
    # and only the share separates cause from passenger.
    monthly_counts: dict[str, int]

    @classmethod
    def from_row(cls, row) -> "PainPoint":
        import json as _json

        return cls(
            run_id=row["run_id"],
            pain_point_id=row["pain_point_id"],
            polarity=row["polarity"],
            title=row["title"],
            message=row["message"],
            keywords=_json.loads(row["keywords_json"] or "[]"),
            canonical_review_id=row["canonical_review_id"],
            canonical_text=row["canonical_text"],
            size=row["size"],
            unit_count=row["unit_count"],
            sole_share=row["sole_share"],
            pct_of_stream=row["pct_of_stream"],
            mean_score=row["mean_score"],
            pct_one_star=row["pct_one_star"],
            thumbs_up_total=row["thumbs_up_total"],
            cohesion=row["cohesion"],
            first_seen=row["first_seen"],
            last_seen=row["last_seen"],
            peak_month=row["peak_month"],
            peak_count=row["peak_count"],
            count_90d=row["count_90d"],
            count_365d=row["count_365d"],
            impact=row["impact"],
            impact_components={
                "recency_volume": row["c_recency"],
                "severity": row["c_severity"],
                "momentum": row["c_momentum"],
                "endorsement": row["c_endorsement"],
            },
            representative_review_ids=_json.loads(row["representative_json"] or "[]"),
            monthly_counts=_json.loads(row["monthly_counts_json"] or "{}"),
        )
