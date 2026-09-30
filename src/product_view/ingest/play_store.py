"""Google Play Store review scraper.

Everything specific to `google-play-scraper` lives here, including its private
continuation-token type. If the library breaks on a Play redesign, this is the
only file that should need attention.

Paginates with an explicit continuation token rather than using
`reviews_all()`: that helper buffers the entire result set in memory with no
checkpointing, so at RBC's volume a single network blip loses the whole run.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Callable, Iterator

from google_play_scraper import Sort, app, reviews
from google_play_scraper.features.reviews import _ContinuationToken

from ..models import Review

log = logging.getLogger(__name__)

# Locale codes worth probing for a Canadian listing. Play partitions reviews by
# `lang`, so fetching only `en` silently drops whole slices of the corpus.
DEFAULT_LANGS = [
    "en", "fr", "zh", "es", "ko", "ru", "ar", "uk", "pt",
    "tr", "it", "ja", "pl", "vi", "de", "ro", "fa", "he",
]


def fetch_app_metadata(app_id: str, lang: str = "en", country: str = "ca") -> dict:
    """Snapshot the store listing's own numbers.

    The dashboard needs these as honest denominators: `ratings` counts every
    star given, `reviews` counts only those with text, and the gap between them
    is why a text corpus reads far more negative than the displayed score.
    """
    a = app(app_id, lang=lang, country=country)
    return {
        "app_id": app_id,
        "lang": lang,
        "country": country,
        "title": a.get("title"),
        "score": a.get("score"),
        "ratings": a.get("ratings"),
        "reviews": a.get("reviews"),
        "histogram": a.get("histogram"),
        "installs": a.get("installs"),
        "version": a.get("version"),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }

# The endpoint refuses to serve more than this per request.
MAX_PAGE_SIZE = 200

_TOKEN_SLOTS = (
    "token",
    "lang",
    "country",
    "sort",
    "count",
    "filter_score_with",
    "filter_device_with",
)


def token_to_state(token: _ContinuationToken | None) -> dict | None:
    """Flatten the library's private token into something JSON can hold."""
    if token is None or getattr(token, "token", None) is None:
        return None
    return {slot: getattr(token, slot) for slot in _TOKEN_SLOTS}


def state_to_token(state: dict | None) -> _ContinuationToken | None:
    """Rebuild a continuation token from a saved state dict.

    Positional construction in exact slot order — the class has no keyword
    constructor and no `__dict__`.
    """
    if not state:
        return None
    try:
        return _ContinuationToken(*[state[slot] for slot in _TOKEN_SLOTS])
    except (KeyError, TypeError):
        log.warning("saved continuation token is unusable; starting from newest")
        return None


class PlayStoreSource:
    name = "google_play"

    def __init__(
        self,
        app_id: str,
        lang: str = "en",
        country: str = "ca",
        page_size: int = MAX_PAGE_SIZE,
        sleep_seconds: float = 1.0,
        max_retries: int = 5,
        on_checkpoint: Callable[[dict | None, int], None] | None = None,
    ) -> None:
        self.app_id = app_id
        self.lang = lang
        self.country = country
        self.page_size = min(page_size, MAX_PAGE_SIZE)
        self.sleep_seconds = sleep_seconds
        self.max_retries = max_retries
        # Called after each page so the caller can persist progress; a fetch
        # interrupted at page 40 should resume there, not at page 1.
        self.on_checkpoint = on_checkpoint

    def _page(self, token: _ContinuationToken | None) -> tuple[list[dict], object]:
        """One request, with backoff. Play throttles rather than erroring."""
        delay = self.sleep_seconds
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                return reviews(
                    self.app_id,
                    lang=self.lang,
                    country=self.country,
                    sort=Sort.NEWEST,
                    count=self.page_size,
                    continuation_token=token,
                )
            except Exception as exc:  # the library raises a grab-bag of types
                last_error = exc
                delay = min(delay * 2, 60) or 2
                log.warning(
                    "page failed (%s: %s); retry %d/%d in %.1fs",
                    type(exc).__name__,
                    exc,
                    attempt + 1,
                    self.max_retries,
                    delay,
                )
                time.sleep(delay)
        raise RuntimeError(f"giving up after {self.max_retries} retries") from last_error

    def fetch(
        self,
        max_reviews: int | None = None,
        known_ids: set[str] | None = None,
        overlap_pages: int = 2,
        resume_state: dict | None = None,
    ) -> Iterator[Review]:
        """Yield reviews newest-first.

        `known_ids` turns this into an incremental top-up: once a page is
        entirely reviews we already hold, we keep going for `overlap_pages`
        more (edited reviews resurface out of order) and then stop.
        """
        known_ids = known_ids or set()
        token = state_to_token(resume_state)
        yielded = 0
        pages_all_known = 0

        while True:
            raw_page, token = self._page(token)
            if not raw_page:
                log.info("no more reviews available")
                break

            new_in_page = 0
            for raw in raw_page:
                if raw["reviewId"] in known_ids:
                    continue
                new_in_page += 1
                yield Review.from_play_store(raw, self.app_id, self.lang, self.country)
                yielded += 1
                if max_reviews is not None and yielded >= max_reviews:
                    log.info("hit max_reviews=%d", max_reviews)
                    if self.on_checkpoint:
                        self.on_checkpoint(token_to_state(token), yielded)
                    return

            if self.on_checkpoint:
                self.on_checkpoint(token_to_state(token), yielded)

            if new_in_page == 0:
                pages_all_known += 1
                if pages_all_known > overlap_pages:
                    log.info("caught up: %d consecutive known pages", pages_all_known)
                    break
            else:
                pages_all_known = 0

            if token is None or getattr(token, "token", None) is None:
                log.info("continuation exhausted after %d reviews", yielded)
                break

            time.sleep(self.sleep_seconds)
