"""Complaint units: re-join adjacent segments that make the same point.

`embed/segment.py` splits every review finely and on purpose over-splits:
"It opens a sheet to verify my identity" / "I never get the push
notification" is one complaint told in two sentences. Walking each review in
reading order, a segment joins the unit before it when its vector agrees with
that unit's running centroid (TextTiling, with embeddings for the lexical
overlap). What comes out is the thing clustered: one complaint, possibly
several per review.

This runs at cluster time from cached segment vectors, so `merge_threshold`
is a clustering knob -- tuning it never means re-embedding. A unit's vector is
the normalized mean of its segments, the same reading an encoder would give
the joined text, without a second encoding pass.

Measured on the negative stream at 0.45: 36,015 segments -> 32,723 units, 2.5
per review.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

DEFAULT_MERGE_THRESHOLD = 0.45


@dataclass
class Units:
    """Row-aligned: unit i came from `review_idx[i]` and says `texts[i]`."""

    review_idx: np.ndarray   # index into the stream's review rows
    seq: np.ndarray          # position of the unit within its review
    texts: list[str]
    vectors: np.ndarray      # (n_units, dim), L2-normalized

    def __len__(self) -> int:
        return len(self.texts)


def _unit(vec_sum: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vec_sum)
    return vec_sum / norm if norm else vec_sum


def build(
    segments_per_review: list[list[tuple[str, np.ndarray]]],
    threshold: float = DEFAULT_MERGE_THRESHOLD,
) -> Units:
    """`segments_per_review[r]` is review r's segments in reading order."""
    review_idx: list[int] = []
    seqs: list[int] = []
    texts: list[str] = []
    vectors: list[np.ndarray] = []

    for r, segments in enumerate(segments_per_review):
        # Each group is [texts, vector sum]; a segment extends the last group
        # when it agrees with that group's centroid.
        groups: list[list] = []
        for text, vec in segments:
            if groups and float(vec @ _unit(groups[-1][1])) >= threshold:
                groups[-1][0].append(text)
                groups[-1][1] = groups[-1][1] + vec
            else:
                groups.append([[text], vec.astype(np.float64)])
        for seq, (group_texts, vec_sum) in enumerate(groups):
            review_idx.append(r)
            seqs.append(seq)
            texts.append(". ".join(group_texts))
            vectors.append(_unit(vec_sum))

    return Units(
        review_idx=np.asarray(review_idx, dtype=np.int64),
        seq=np.asarray(seqs, dtype=np.int32),
        texts=texts,
        vectors=np.vstack(vectors).astype(np.float32) if vectors
        else np.zeros((0, 0), dtype=np.float32),
    )
