"""Exact cosine kNN graph — the structure a vector database maintains.

**A deliberate simplification worth stating:** at ~13,000 vectors an exact kNN
via chunked numpy matmul takes a couple of seconds. HNSW (what Qdrant and
pgvector use underneath) is an *approximation* that only starts paying for
itself around 10^6 vectors. Adding it here would be cargo-culting the
vector-database aesthetic while making results approximate and the dependency
list longer. The interface leaves room to swap in ANN when the corpus
justifies it.

Vectors arrive L2-normalized from the encoder, so a dot product *is* cosine
similarity.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

CHUNK = 1024


@dataclass(frozen=True)
class KnnGraph:
    """Neighbour indices and similarities, both shape (n, k), self excluded."""

    indices: np.ndarray
    similarities: np.ndarray

    @property
    def n(self) -> int:
        return int(self.indices.shape[0])

    @property
    def k(self) -> int:
        return int(self.indices.shape[1])

    def edges(self, min_similarity: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
        """Undirected edge list as (pairs, weights), deduped.

        kNN is asymmetric, so a mutually-nearest pair appears twice; left as-is
        it would be double-weighted in community detection. Vectorized rather
        than looped because the granularity search calls this once per
        iteration -- a Python loop over 195,000 directed edges is seconds each
        time, for an edge list that never changes.
        """
        n, k = self.indices.shape
        src = np.repeat(np.arange(n, dtype=np.int64), k)
        dst = self.indices.ravel().astype(np.int64)
        weights = self.similarities.ravel().astype(np.float64)

        keep = (weights >= min_similarity) & (src != dst)
        src, dst, weights = src[keep], dst[keep], weights[keep]

        lo = np.minimum(src, dst)
        hi = np.maximum(src, dst)
        key = lo * n + hi
        uniq, inverse = np.unique(key, return_inverse=True)

        # Keep the stronger of the two directed readings of each pair.
        best = np.zeros(uniq.shape[0], dtype=np.float64)
        np.maximum.at(best, inverse, weights)

        pairs = np.column_stack((uniq // n, uniq % n)).astype(np.int32)
        return pairs, best


def build_knn(vectors: np.ndarray, k: int = 15) -> KnnGraph:
    """Exact top-k cosine neighbours for every row."""
    n = vectors.shape[0]
    k = min(k, max(1, n - 1))
    idx_out = np.empty((n, k), dtype=np.int32)
    sim_out = np.empty((n, k), dtype=np.float32)

    for start in range(0, n, CHUNK):
        stop = min(start + CHUNK, n)
        sims = vectors[start:stop] @ vectors.T          # (chunk, n) cosine
        # Exclude self before selecting, or every row's best match is itself.
        rows = np.arange(stop - start)
        sims[rows, np.arange(start, stop)] = -np.inf

        part = np.argpartition(-sims, kth=k - 1, axis=1)[:, :k]
        part_sims = np.take_along_axis(sims, part, axis=1)
        order = np.argsort(-part_sims, axis=1)          # exact order within the top-k
        idx_out[start:stop] = np.take_along_axis(part, order, axis=1)
        sim_out[start:stop] = np.take_along_axis(part_sims, order, axis=1)

    return KnnGraph(indices=idx_out, similarities=sim_out)


def centroid(vectors: np.ndarray) -> np.ndarray:
    """Mean of member vectors, renormalized so it stays on the unit sphere."""
    c = vectors.mean(axis=0)
    norm = np.linalg.norm(c)
    return (c / norm if norm else c).astype(np.float32)


def cohesion(vectors: np.ndarray, center: np.ndarray | None = None) -> float:
    """Mean cosine of members to their centroid — the incoherence filter."""
    if vectors.shape[0] == 0:
        return 0.0
    c = centroid(vectors) if center is None else center
    return float(np.mean(vectors @ c))
