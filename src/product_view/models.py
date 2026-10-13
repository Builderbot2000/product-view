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

        `userName` and `userImage` are deliberately dropped. Grouping
        reviews into issues never needs reviewer identity, and not collecting it beats
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
