"""The ingestion swap point.

Anything that can produce `Review` records satisfies this. Today that is the
Play Store scraper; later it will be the internal feed, and swapping one for
the other should touch no code outside this package.
"""

from __future__ import annotations

from typing import Iterator, Protocol

from ..models import Review


class ReviewSource(Protocol):
    name: str

    def fetch(self, since_id: str | None = None) -> Iterator[Review]:
        """Yield reviews newest-first, stopping at `since_id` if given."""
        ...
