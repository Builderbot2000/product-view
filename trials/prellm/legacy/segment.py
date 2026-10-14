"""Split a review into fine segments -- the first half of complaint extraction.

A review is not one complaint. Long reviews list several ("e-transfer fails,
fees went up, and the branch was no help"), and embedding the whole review
averages those into a vector near the corpus centre: the "RBC is bad" region.
On the whole-review run of 2026-09-23 that was exactly what topped the
ranking. Clusters built from such reviews read as generic because their
vectors *are* generic.

Splitting is rule-based, no LLM: sentence boundaries, then clause boundaries
that usually open a new point ("but", "however", "also", "plus", ";").
Plain "and" is deliberately not a boundary -- "log in and check my balance" is
one thing.

This deliberately over-splits. A narrative comes apart into steps
("Downloaded this app" / "Did an e-transfer" / "RBC blocked my transfer"),
and each step alone has lost its complaint. The clustering stage re-joins
adjacent segments whose vectors agree (`cluster/units.py`), so the final unit
is one complaint however many sentences the user took to say it. Splitting
fine here and merging there keeps the merge threshold a clustering knob:
tuning it never means re-embedding.

Measured on the negative stream: 13,030 reviews -> 36,015 segments (2.76 per
review; 32% of reviews stay whole).
"""

from __future__ import annotations

import re

# Bump when the rules below change: cached segment vectors carry the version
# they were split with, and `pv embed` redoes any review split under another.
SPLITTER_VERSION = "1"

# Sentence ends, line breaks, and a sentence end jammed against the next
# capital with no space ("slow.The update"), which mobile keyboards produce.
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+|(?<=[.!?])(?=[A-Z])")
_CLAUSE = re.compile(
    r"\s*(?:;|\s-\s|,?\s+\b(?:but|however|also|plus|additionally|on top of that|"
    r"and also|and now|and then|another thing|not to mention|besides)\b)\s+",
    re.I,
)
_WORD = re.compile(r"[a-z0-9']+", re.I)

# A fragment shorter than this ("Thanks RBC", "Why?") carries no complaint of
# its own; it is dropped rather than left to cluster with other scraps.
MIN_WORDS = 3


def word_count(text: str) -> int:
    return len(_WORD.findall(text))


def split(text: str) -> list[str]:
    """Fine segments in reading order. Never empty for non-blank text: a
    review too short to split is kept whole, so every review stays in the
    stream."""
    out: list[str] = []
    for sentence in _SENTENCE.split(text or ""):
        for clause in _CLAUSE.split(sentence):
            clause = clause.strip(" ,.-")
            if word_count(clause) >= MIN_WORDS:
                out.append(clause)
    if not out and text and text.strip():
        out.append(text.strip())
    return out
