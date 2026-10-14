"""One granularity knob across every strategy.

Each algorithm exposes granularity through a different native parameter, which
would normally make them incomparable. Instead granularity is expressed as a
**target cluster count**, and the runner binary-searches each strategy's native
knob until the count lands in the band. Two benefits beyond convenience:
strategies become directly comparable because they are held at the *same*
cluster count, and a PM can say "show me fewer, broader themes" without knowing
what a resolution parameter is.

**The search targets the POST-filter count** -- clusters surviving
`min_cluster_size` and `cohesion_floor` -- so the band means what a reader
thinks it means. Each iteration therefore applies filtering before counting.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import numpy as np

from .graph import KnnGraph, cohesion
from .strategies import ClusterStrategy

log = logging.getLogger(__name__)

PRESETS: dict[str, tuple[int, int]] = {
    "broad": (15, 25),
    "balanced": (40, 60),
    "fine": (80, 120),
}

MAX_ITERATIONS = 12


def resolve_band(granularity: str | tuple[int, int] | dict) -> tuple[int, int]:
    if isinstance(granularity, str):
        try:
            return PRESETS[granularity]
        except KeyError:
            raise ValueError(
                f"unknown granularity {granularity!r}; "
                f"choose from {', '.join(PRESETS)} or give a target band"
            ) from None
    if isinstance(granularity, dict):
        return int(granularity["target_min"]), int(granularity["target_max"])
    lo, hi = granularity
    return int(lo), int(hi)


def filter_clusters(
    labels: np.ndarray,
    vectors: np.ndarray,
    min_cluster_size: int,
    cohesion_floor: float,
) -> tuple[dict[int, np.ndarray], int]:
    """Keep coherent, large-enough clusters; everything else becomes noise.

    Returns `({label: member_row_indices}, unclustered_count)`. The unclustered
    count is always reported to the caller -- hiding what fraction of feedback
    the analysis misses is the fastest way to make the tool untrustworthy.
    """
    kept: dict[int, np.ndarray] = {}
    unclustered = 0
    for label in np.unique(labels):
        rows = np.flatnonzero(labels == label)
        if label == -1 or rows.size < min_cluster_size:
            unclustered += rows.size
            continue
        if cohesion(vectors[rows]) < cohesion_floor:
            unclustered += rows.size
            continue
        kept[int(label)] = rows
    return kept, unclustered


@dataclass
class SearchResult:
    native_param: float
    labels: np.ndarray
    clusters: dict[int, np.ndarray]
    unclustered: int
    n_clusters: int
    iterations: int
    converged: bool
    trace: list[tuple[float, int]] = field(default_factory=list)


def search(
    strategy: ClusterStrategy,
    vectors: np.ndarray,
    knn: KnnGraph,
    band: tuple[int, int],
    min_cluster_size: int,
    cohesion_floor: float,
    max_iterations: int = MAX_ITERATIONS,
) -> SearchResult:
    """Binary-search the strategy's native knob to hit the target band."""
    target_min, target_max = band
    center = (target_min + target_max) / 2
    knob = strategy.knob

    def param_at(x: float) -> float:
        """Map x in [0,1] to the native parameter, x=1 always meaning more clusters."""
        t = x if knob.higher_means_more_clusters else 1.0 - x
        if knob.log_scale:
            raw = math.exp(
                math.log(knob.lo) + t * (math.log(knob.hi) - math.log(knob.lo))
            )
        else:
            raw = knob.lo + t * (knob.hi - knob.lo)
        return float(round(raw)) if knob.integer else float(raw)

    def evaluate(x: float) -> tuple[float, SearchResult]:
        param = param_at(x)
        labels = strategy.fit(vectors, knn, param)
        clusters, unclustered = filter_clusters(
            labels, vectors, min_cluster_size, cohesion_floor
        )
        n = len(clusters)
        log.info(
            "  [%s] %s=%.4g -> %d clusters (post-filter)",
            strategy.name, knob.name, param, n,
        )
        return param, SearchResult(
            native_param=param, labels=labels, clusters=clusters,
            unclustered=unclustered, n_clusters=n, iterations=0,
            converged=target_min <= n <= target_max,
        )

    trace: list[tuple[float, int]] = []
    evaluated: list[tuple[float, int]] = []   # (x, post-filter count)
    best: SearchResult | None = None
    fits = 0

    def record(x: float) -> SearchResult:
        nonlocal best, fits
        param, result = evaluate(x)
        fits += 1
        trace.append((param, result.n_clusters))
        evaluated.append((x, result.n_clusters))
        if best is None or abs(result.n_clusters - center) < abs(best.n_clusters - center):
            best = result
        return result

    # Coarse sweep first, then bisect inside the bracket it finds.
    #
    # The post-filter cluster count is *unimodal*, not monotonic: it rises as
    # communities split, peaks, then collapses toward zero once they split so
    # finely that every one falls below min_cluster_size and is discarded.
    # Bisection alone cannot survive that -- its first probe may already sit on
    # the descending side, and the half containing the peak gets excluded
    # before any evidence exists that it was the right half. The sweep locates
    # the ascending flank, where the search is genuinely monotonic.
    sweep_xs = [0.1, 0.3, 0.5, 0.7, 0.9]
    sweep: list[tuple[float, int]] = []
    for x in sweep_xs:
        result = record(x)
        if result.converged:
            result.iterations = fits
            result.trace = trace
            return result
        sweep.append((x, result.n_clusters))

    # Bracket the interval where the sweep steps across the target band. This
    # is the common case and it must be checked before anything about the peak:
    # with a generous min_cluster_size the curve often just rises across the
    # whole sweep, putting the "peak" at the last sample while the band sits
    # far below it.
    lo_x = hi_x = None
    for (xa, na), (xb, nb) in zip(sweep, sweep[1:]):
        if na < target_min and nb > target_max:
            lo_x, hi_x = xa, xb
            break

    if lo_x is None:
        # No crossing sampled. Bracket the highest point instead: the true peak
        # lies between its neighbours, so that interval contains the ascending
        # flank. A coarse sweep can badly under-sample the peak, which is why
        # its height is never used to declare the band unreachable.
        peak_i = max(range(len(sweep)), key=lambda i: sweep[i][1])
        lo_x = sweep[peak_i - 1][0] if peak_i > 0 else 0.0
        hi_x = sweep[peak_i + 1][0] if peak_i + 1 < len(sweep) else 1.0

    while fits < max_iterations:
        x = (lo_x + hi_x) / 2
        result = record(x)
        if result.converged:
            result.iterations = fits
            result.trace = trace
            return result
        if result.n_clusters > target_max:
            hi_x = x
        else:
            # Too few clusters is ambiguous on a unimodal curve: the knob may
            # be below the peak (communities still too coarse) or beyond it
            # (communities so fine they all fail min_cluster_size). If some
            # lower x already produced more surviving clusters, we are past
            # the peak and must come back down.
            past_peak = any(px < x and pn > result.n_clusters for px, pn in evaluated[:-1])
            if past_peak:
                hi_x = x
            else:
                lo_x = x

    assert best is not None
    if best.n_clusters < target_min:
        log.warning(
            "[%s] could not reach %d-%d clusters in %d fits; the best any knob "
            "setting produced was %d. Lower --min-cluster-size, widen the band, "
            "or set --native-override directly.",
            strategy.name, target_min, target_max, fits, best.n_clusters,
        )
    else:
        log.warning(
            "[%s] did not converge in %d fits; using %s=%.4g (%d clusters, target %d-%d)",
            strategy.name, fits, knob.name, best.native_param,
            best.n_clusters, target_min, target_max,
        )
    best.iterations = fits
    best.trace = trace
    return best
