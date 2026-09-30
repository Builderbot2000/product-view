"""Sentence embeddings, cached in SQLite by (review_id, model).

`all-MiniLM-L6-v2` over `content_en` — the original text for English reviews,
the translation for French ones — so an English-only model covers 100% of the
corpus. Vectors are L2-normalized, which makes cosine similarity a plain dot
product everywhere downstream.

Native `max_seq_length` is 256 and only 7 reviews of 17,948 exceed it, so no
chunking.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Sequence

import numpy as np

MODEL_NAME = "all-MiniLM-L6-v2"
DIM = 384
BATCH_SIZE = 256

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _model(name: str = MODEL_NAME):
    from sentence_transformers import SentenceTransformer

    from ..lang.translate import cache_dir

    log.info("loading %s (first run downloads ~90 MB)", name)
    return SentenceTransformer(name, cache_folder=cache_dir())


def encode(texts: Sequence[str], name: str = MODEL_NAME, show_progress: bool = True) -> np.ndarray:
    """Encode to an L2-normalized float32 array of shape (len(texts), DIM)."""
    vectors = _model(name).encode(
        list(texts),
        batch_size=BATCH_SIZE,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=show_progress,
    )
    return np.ascontiguousarray(vectors, dtype=np.float32)


def to_blob(vector: np.ndarray) -> bytes:
    return np.ascontiguousarray(vector, dtype=np.float32).tobytes()


def from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def stack(blobs: Sequence[bytes]) -> np.ndarray:
    """Rebuild a (n, DIM) matrix from stored BLOBs."""
    return np.vstack([from_blob(b) for b in blobs]).astype(np.float32)
