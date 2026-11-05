"""Reviews into complaint units: fine segments, re-joined where they agree.

The units the topic trials matched (trials/topics, through
trials/prellm/harness.load_window), rebuilt from the same two steps:

1. Split each review finely by rule: sentence ends, then the clause openers
   that usually start a new point ("but", "however", "also", ";"). Plain
   "and" is not a boundary. Fragments under 3 words are dropped. This
   over-splits on purpose: a narrative comes apart into steps.
2. Walk each review in reading order and join a segment to the unit before
   it when its MiniLM vector agrees with that unit's running centroid
   (cosine >= 0.45). One unit is one complaint, however many sentences the
   reviewer took to say it.

Splitting and joining are part of the validated method; their constants are
not configuration.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

MERGE_THRESHOLD = 0.45
MIN_WORDS = 3

_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+|(?<=[.!?])(?=[A-Z])")
_CLAUSE = re.compile(
    r"\s*(?:;|\s-\s|,?\s+\b(?:but|however|also|plus|additionally|on top of that|"
    r"and also|and now|and then|another thing|not to mention|besides)\b)\s+",
    re.I,
)
_WORD = re.compile(r"[a-z0-9']+", re.I)


def split(text: str) -> list[str]:
    """Fine segments in reading order. A review too short to split is kept
    whole, so every review has at least one segment."""
    out: list[str] = []
    for sentence in _SENTENCE.split(text or ""):
        for clause in _CLAUSE.split(sentence):
            clause = clause.strip(" ,.-")
            if len(_WORD.findall(clause)) >= MIN_WORDS:
                out.append(clause)
    if not out and text and text.strip():
        out.append(text.strip())
    return out


@dataclass(frozen=True)
class Unit:
    review_id: str
    seq: int          # position within the review
    text: str         # the segments joined, as the method reads it
    quote: str        # the same stretch of the review as the reviewer wrote it


def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n else v


def _spans(text: str, segs: list[str]) -> list[tuple[int, int] | None]:
    """Where each segment sits in the review, in reading order."""
    out, cur, low = [], 0, text.lower()
    for s in segs:
        i = text.find(s, cur)
        if i < 0:
            i = low.find(s.lower(), cur)
        if i < 0:
            out.append(None)
            continue
        out.append((i, i + len(s)))
        cur = i + len(s)
    return out


def build(reviews: list[tuple[str, str]], encode) -> list[Unit]:
    """Units of (review_id, text) pairs. `encode(texts)` returns unit-length
    MiniLM vectors, one row per text."""
    segs = [split(text) for _, text in reviews]
    flat = [s for ss in segs for s in ss]
    vecs = encode(flat) if flat else np.zeros((0, 0), dtype=np.float32)
    units: list[Unit] = []
    k = 0
    for (rid, text), ss in zip(reviews, segs):
        groups: list[list] = []          # [segment indexes, vector sum]
        for j in range(len(ss)):
            v = vecs[k + j]
            if groups and float(v @ _unit(groups[-1][1])) >= MERGE_THRESHOLD:
                groups[-1][0].append(j)
                groups[-1][1] = groups[-1][1] + v
            else:
                groups.append([[j], v.astype(np.float64)])
        k += len(ss)
        spans = _spans(text, ss)
        for seq, (idx, _) in enumerate(groups):
            joined = ". ".join(ss[j] for j in idx)
            first, last = spans[idx[0]], spans[idx[-1]]
            quote = text[first[0]:last[1]] if first and last else joined
            units.append(Unit(rid, seq, joined, " ".join(quote.split())))
    return units
