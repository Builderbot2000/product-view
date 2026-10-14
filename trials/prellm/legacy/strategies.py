"""Pluggable cluster strategies behind one interface.

Cluster quality on real review text is genuinely hard to predict from theory,
so rather than betting on one algorithm, every candidate implements the same
Protocol and emits an identical integer label array. Everything downstream --
synthesis, scoring, the PainPoint object, storage -- consumes only that array,
so switching is a flag and never a code change. A new strategy is one class
and one registry entry.

`-1` means noise. Only HDBSCAN produces it natively; for the others noise is
removed by post-filtering (see `granularity.filter_clusters`), which keeps noise
handling identical across strategies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from .graph import KnnGraph


@dataclass(frozen=True)
class NativeKnob:
    """How one strategy exposes granularity, so the search can drive it.

    Each algorithm names this differently (`resolution`, `distance_threshold`,
    `min_cluster_size`), which would make them incomparable. The runner
    binary-searches within `lo`..`hi` instead, and callers only ever speak in
    target cluster counts.
    """

    name: str
    lo: float
    hi: float
    higher_means_more_clusters: bool
    integer: bool = False
    # Cluster count responds exponentially to resolution and to
    # min_cluster_size, so the search interpolates those geometrically --
    # linearly it would spend every iteration in the top of the range.
    # distance_threshold is genuinely linear over its narrow band.
    log_scale: bool = True


class ClusterStrategy(Protocol):
    name: str
    knob: NativeKnob

    def fit(self, vectors: np.ndarray, knn: KnnGraph, native_param: float) -> np.ndarray:
        """Return an integer label per row; -1 means noise."""
        ...


class LeidenStrategy:
    """Community detection on the cosine kNN graph.

    The vector-database-native approach: it uses only *relative* neighbour
    ranks, sidestepping the distance concentration that degrades density
    methods in 384 dimensions. Deterministic with a fixed seed, and it handles
    very uneven cluster sizes -- which ours are, given one month holds 13% of
    the corpus.
    """

    name = "leiden"
    knob = NativeKnob("resolution", lo=0.05, hi=60.0, higher_means_more_clusters=True)

    def __init__(self, seed: int = 42) -> None:
        self.seed = seed

    @staticmethod
    def available() -> bool:
        try:
            import igraph  # noqa: F401
            import leidenalg  # noqa: F401
        except ImportError:
            return False
        return True

    def fit(self, vectors: np.ndarray, knn: KnnGraph, native_param: float) -> np.ndarray:
        import igraph as ig
        import leidenalg as la

        pairs, weights = knn.edges()
        g = ig.Graph(n=knn.n, edges=pairs.tolist(), directed=False)
        g.es["weight"] = weights.tolist()
        partition = la.find_partition(
            g,
            la.RBConfigurationVertexPartition,
            weights="weight",
            resolution_parameter=float(native_param),
            seed=self.seed,
        )
        return np.asarray(partition.membership, dtype=np.int32)


class AgglomerativeStrategy:
    """scikit-learn only, fully deterministic, and it yields a dendrogram --
    so pain-point -> sub-issue drill-down comes free later. Relies on absolute
    distances, which is less trustworthy than neighbour ranks at 384 dims.
    """

    name = "agglomerative"
    knob = NativeKnob(
        "distance_threshold", lo=0.05, hi=1.30,
        higher_means_more_clusters=False, log_scale=False,
    )

    @staticmethod
    def available() -> bool:
        return True

    def fit(self, vectors: np.ndarray, knn: KnnGraph, native_param: float) -> np.ndarray:
        from sklearn.cluster import AgglomerativeClustering

        model = AgglomerativeClustering(
            n_clusters=None,
            distance_threshold=float(native_param),
            metric="cosine",
            linkage="average",
        )
        return model.fit_predict(vectors).astype(np.int32)


class HdbscanStrategy:
    """Built into scikit-learn 1.3+, so still no extra dependency, and the one
    strategy with an explicit noise class. On L2-normalized vectors euclidean
    is monotonic with cosine, so it runs on the right geometry directly.
    Density estimation does degrade in 384 dimensions without reduction --
    which is what the optional umap variant would address.
    """

    name = "hdbscan"
    knob = NativeKnob("min_cluster_size", lo=5, hi=600, higher_means_more_clusters=False, integer=True)

    @staticmethod
    def available() -> bool:
        try:
            from sklearn.cluster import HDBSCAN  # noqa: F401
        except ImportError:
            return False
        return True

    def fit(self, vectors: np.ndarray, knn: KnnGraph, native_param: float) -> np.ndarray:
        from sklearn.cluster import HDBSCAN

        model = HDBSCAN(
            min_cluster_size=max(2, int(native_param)),
            metric="euclidean",
            # "auto" picks a ball-tree, which degenerates at 384 dimensions:
            # measured 54.2s against 2.4s for brute force on 6,000 vectors,
            # and the granularity search calls this up to ten times. Cost is
            # flat in min_cluster_size either way, since the expense is
            # building the hierarchy, not extracting clusters from it.
            algorithm="brute",
            copy=True,
        )
        return model.fit_predict(vectors).astype(np.int32)


_REGISTRY = {
    LeidenStrategy.name: LeidenStrategy,
    AgglomerativeStrategy.name: AgglomerativeStrategy,
    HdbscanStrategy.name: HdbscanStrategy,
}


def get_strategy(name: str, seed: int = 42) -> ClusterStrategy:
    try:
        cls = _REGISTRY[name]
    except KeyError:
        raise ValueError(
            f"unknown strategy {name!r}; choose from {', '.join(_REGISTRY)}"
        ) from None
    if not cls.available():
        raise RuntimeError(
            f"strategy {name!r} needs dependencies that are not installed "
            f"(leiden requires igraph + leidenalg)"
        )
    return cls(seed=seed) if cls is LeidenStrategy else cls()


def available_strategies() -> list[str]:
    return [name for name, cls in _REGISTRY.items() if cls.available()]
