"""Orchestration: stream -> units -> graph -> strategy -> filter -> synthesize -> score.

The unit clustered is a *complaint*, not a review (`units.py`): a review that
raises three problems contributes three units and can land in three pain
points. Every reader-facing statistic is still counted in distinct reviews --
`size` is "reviews mentioning this" -- so a user who repeats one point twice
counts once.

Kept out of cli.py so the CLI stays argument parsing and presentation, which is
how the ingest stage is already structured.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

from ..embed import encoder
from ..store import Store
from ..embed import segment
from . import scoring, synthesize, units as units_mod
from .granularity import SearchResult, filter_clusters, resolve_band, search
from .graph import build_knn, centroid, cohesion
from .strategies import available_strategies, get_strategy

log = logging.getLogger(__name__)


@dataclass
class ClusterConfig:
    polarity: str = "negative"
    algorithm: str = "leiden"
    granularity: str = "balanced"
    min_cluster_size: int = 25
    cohesion_floor: float = 0.35
    knn_k: int = 15
    seed: int = 42
    min_chars: int = 20
    merge_threshold: float = units_mod.DEFAULT_MERGE_THRESHOLD
    tau_days: float = scoring.DEFAULT_TAU_DAYS
    momentum_window_days: float = scoring.DEFAULT_MOMENTUM_WINDOW_DAYS
    lexrank_max_members: int = synthesize.LEXRANK_MAX_MEMBERS
    native_override: float | None = None
    top_keywords: int = 8
    supporting_quotes: int = 5


def _pain_point_id(medoid_review_id: str, medoid_text: str) -> str:
    """Derived from the medoid unit, so it stays stable across runs for as long
    as the cluster's most typical complaint does. The review id alone is not
    enough: two units of one review can be the medoids of two clusters. Full
    centroid matching across runs is deferred; within-run history already
    carries every trend line.
    """
    key = f"{medoid_review_id}\n{medoid_text}".encode("utf-8")
    return "pp_" + hashlib.sha256(key).hexdigest()[:8]


def load_stream(store: Store, cfg: ClusterConfig, app_id: str | None = None):
    """Stream review rows, plus the complaint units they split into."""
    rows = store.stream(cfg.polarity, min_chars=cfg.min_chars, app_id=app_id)
    if not rows:
        raise RuntimeError(
            f"no reviews in the {cfg.polarity} stream - run 'pv db build' first"
        )
    ids = [r["review_id"] for r in rows]
    segments = store.load_segments(encoder.MODEL_NAME, ids)
    missing = [i for i in ids if i not in segments]
    if missing:
        raise RuntimeError(
            f"{len(missing)} of {len(ids)} stream reviews have no segments - "
            f"run 'pv embed' first"
        )
    per_review = [
        [(text, encoder.from_blob(blob)) for text, blob in segments[i]] for i in ids
    ]
    return rows, units_mod.build(per_review, cfg.merge_threshold)


def synthesize_clusters(
    rows, units: units_mod.Units, result: SearchResult, cfg: ClusterConfig,
    now: datetime,
) -> list[dict]:
    """Turn surviving clusters into fully-populated pain point records."""
    # Largest first, so where two clusters would reach for the same title
    # sentence the bigger one keeps it.
    labels = sorted(result.clusters, key=lambda l: (-len(result.clusters[l]), l))

    log.info("c-TF-IDF over %d clusters", len(labels))
    keywords_by_cluster = synthesize.ctfidf(
        {label: [units.texts[i] for i in result.clusters[label]] for label in labels},
        top_k=cfg.top_keywords,
    )

    # Which pain points each review reaches, for `sole_share`.
    reached: dict[int, set[int]] = {}
    for label in labels:
        for r in units.review_idx[result.clusters[label]]:
            reached.setdefault(int(r), set()).add(label)

    stream_size = len(rows)
    taken: set[str] = set()
    records: list[dict] = []
    for n, label in enumerate(labels, 1):
        member_units = result.clusters[label]
        member_vectors = units.vectors[member_units]
        member_texts = [units.texts[i] for i in member_units]
        center = centroid(member_vectors)
        similarities = member_vectors @ center

        medoid_unit = int(member_units[synthesize.medoid(member_vectors, center)])
        medoid_row = rows[int(units.review_idx[medoid_unit])]
        keywords = keywords_by_cluster.get(label, [])

        title = synthesize.sentence_title(member_texts, similarities, keywords, taken)
        taken.add(title.lower())

        # LexRank over the most typical members only -- the whole cluster
        # would be a bigger pass than the corpus.
        order = np.argsort(-similarities)[: cfg.lexrank_max_members]
        message = synthesize.build_message(
            [member_texts[i] for i in order],
            encode_fn=lambda s: encoder.encode(s, show_progress=False),
        )

        # MMR runs over units, but quotes are shown per review: over-pick, then
        # keep each review's first appearance.
        picks = synthesize.mmr_select(
            member_vectors, center, k=cfg.supporting_quotes * 2, lam=0.7
        )
        representative: list[int] = []
        for p in picks:
            r = int(units.review_idx[member_units[p]])
            if r not in representative:
                representative.append(r)
        representative = representative[: cfg.supporting_quotes]

        reviews = np.unique(units.review_idx[member_units])
        stats = scoring.cluster_stats(
            scores=[rows[i]["score"] for i in reviews],
            thumbs=[rows[i]["thumbs_up"] or 0 for i in reviews],
            dates=[scoring.parse_date(rows[i]["created_at"]) for i in reviews],
            polarity=cfg.polarity,
            now=now,
            tau_days=cfg.tau_days,
            momentum_window_days=cfg.momentum_window_days,
        )
        stats.update(
            {
                "pain_point_id": _pain_point_id(
                    medoid_row["review_id"], units.texts[medoid_unit]),
                "polarity": cfg.polarity,
                "title": title,
                "message": message,
                "keywords_json": json.dumps(keywords, ensure_ascii=False),
                "canonical_review_id": medoid_row["review_id"],
                "canonical_text": units.texts[medoid_unit],
                "unit_count": int(len(member_units)),
                # Generic complaints ("worst bank ever", "please fix") ride
                # along with specific ones; a pain point that is rarely the
                # only thing its reviewers raise is likely one of them. Stored,
                # not filtered: the reader decides what to sort away.
                "sole_share": round(
                    float(np.mean([len(reached[int(r)]) == 1 for r in reviews])), 4),
                "pct_of_stream": round(100.0 * len(reviews) / stream_size, 3),
                "cohesion": round(cohesion(member_vectors, center), 4),
                "centroid": encoder.to_blob(center),
                "_member_units": member_units,
                "_similarities": similarities,
                "_representative": representative,
            }
        )
        records.append(stats)
        if n % 10 == 0:
            log.info("  synthesized %d/%d clusters", n, len(labels))

    ids = [r["pain_point_id"] for r in records]
    if len(set(ids)) != len(ids):
        # INSERT OR REPLACE would otherwise drop one of the pair silently.
        raise RuntimeError("pain_point_id collision within one run")

    scoring.apply_impact(records)
    return records


def run(store: Store, cfg: ClusterConfig, app_id: str | None = None) -> dict:
    """Execute one clustering run and persist it. Returns a summary."""
    started = datetime.now(timezone.utc)
    now = started

    rows, units = load_stream(store, cfg, app_id)
    vectors = units.vectors
    log.info(
        "%s stream: %d reviews -> %d complaint units (merge >= %.2f)",
        cfg.polarity, len(rows), len(units), cfg.merge_threshold,
    )

    log.info("building exact cosine kNN (k=%d)", cfg.knn_k)
    knn = build_knn(vectors, k=cfg.knn_k)

    strategy = get_strategy(cfg.algorithm, seed=cfg.seed)
    band = resolve_band(cfg.granularity)
    min_size = cfg.min_cluster_size

    if cfg.native_override is not None:
        labels = strategy.fit(vectors, knn, cfg.native_override)
        clusters, unclustered = filter_clusters(
            labels, vectors, min_size, cfg.cohesion_floor
        )
        result = SearchResult(
            native_param=cfg.native_override, labels=labels, clusters=clusters,
            unclustered=unclustered, n_clusters=len(clusters), iterations=0,
            converged=True,
        )
    else:
        log.info(
            "searching %s for %d-%d clusters (post-filter)",
            strategy.knob.name, band[0], band[1],
        )
        result = search(strategy, vectors, knn, band, min_size, cfg.cohesion_floor)

    # Units are what cluster, but the reader's question is "how many reviews
    # does this analysis say nothing about" -- a review is only uncovered when
    # none of its units reached a pain point.
    covered = (
        np.unique(np.concatenate([units.review_idx[m] for m in result.clusters.values()]))
        if result.clusters else np.array([], dtype=np.int64)
    )
    uncovered_reviews = len(rows) - len(covered)
    log.info(
        "%d clusters, %d of %d units unclustered; %d reviews (%.1f%%) uncovered",
        result.n_clusters, result.unclustered, len(units),
        uncovered_reviews, 100.0 * uncovered_reviews / len(rows),
    )

    if not result.clusters:
        # Otherwise this surfaces several frames later as an opaque
        # "empty vocabulary" from the vectorizer.
        raise RuntimeError(
            f"no clusters survived filtering at {strategy.knob.name}="
            f"{result.native_param:.4g} (min_cluster_size={min_size}, "
            f"cohesion_floor={cfg.cohesion_floor}). Lower --min-cluster-size or "
            f"--cohesion-floor, or set --native-override to pick the knob directly."
        )

    records = synthesize_clusters(rows, units, result, cfg, now)

    run_id = started.strftime("%Y-%m-%dT%H:%M:%SZ") + f"_{cfg.polarity}"
    corpus_monthly = scoring.monthly_counts(
        [d for d in (scoring.parse_date(r["created_at"]) for r in rows) if d]
    )

    store.clear_run(run_id)
    store.save_run(
        {
            "run_id": run_id,
            "started_at": started.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "app_id": app_id,
            "polarity": cfg.polarity,
            "algorithm": cfg.algorithm,
            "granularity": str(cfg.granularity),
            "seed": cfg.seed,
            "params": {
                "native_param": result.native_param,
                "knob": strategy.knob.name,
                "band": list(band),
                "min_cluster_size": min_size,
                "cohesion_floor": cfg.cohesion_floor,
                "knn_k": cfg.knn_k,
                "tau_days": cfg.tau_days,
                "momentum_window_days": cfg.momentum_window_days,
                "min_chars": cfg.min_chars,
                "merge_threshold": cfg.merge_threshold,
                "splitter": segment.SPLITTER_VERSION,
                "embed_model": encoder.MODEL_NAME,
                "search_trace": result.trace,
                "converged": result.converged,
            },
            "stream_size": len(rows),
            "unit_count": len(units),
            "unclustered": result.unclustered,
            "uncovered_reviews": uncovered_reviews,
            "corpus_monthly": corpus_monthly,
        }
    )

    members: list[tuple[str, str, str, int, str, float]] = []
    for rec in records:
        rec["run_id"] = run_id
        rec["monthly_counts_json"] = json.dumps(rec.pop("monthly_counts"))
        member_units = rec.pop("_member_units")
        similarities = rec.pop("_similarities")
        for u, sim in zip(member_units, similarities):
            members.append((
                run_id, rec["pain_point_id"],
                rows[int(units.review_idx[u])]["review_id"],
                int(units.seq[u]), units.texts[u], float(sim),
            ))
        rec["representative_json"] = json.dumps(
            [rows[i]["review_id"] for i in rec.pop("_representative", [])]
        )

    store.save_pain_points(run_id, records)
    store.save_members(members)

    return {
        "run_id": run_id,
        "clusters": result.n_clusters,
        "unit_count": len(units),
        "unclustered": result.unclustered,
        "uncovered_reviews": uncovered_reviews,
        "stream_size": len(rows),
        "native_param": result.native_param,
        "knob": strategy.knob.name,
        "converged": result.converged,
        "members": len(members),
    }


def compare(store: Store, cfg: ClusterConfig, app_id: str | None = None) -> list[dict]:
    """Run every available strategy at the same target band and report metrics.

    Cluster quality on real review text is hard to predict from theory, so the
    default is meant to be settled by looking at actual output rather than by
    argument.
    """
    from sklearn.metrics import silhouette_score

    _, units = load_stream(store, cfg, app_id)
    vectors = units.vectors
    knn = build_knn(vectors, k=cfg.knn_k)
    band = resolve_band(cfg.granularity)
    min_size = cfg.min_cluster_size

    out = []
    for name in available_strategies():
        log.info("comparing strategy %s", name)
        strategy = get_strategy(name, seed=cfg.seed)
        result = search(strategy, vectors, knn, band, min_size, cfg.cohesion_floor)

        assigned = np.full(len(units), -1, dtype=np.int32)
        for new_label, (_, member_rows) in enumerate(sorted(result.clusters.items())):
            assigned[member_rows] = new_label
        mask = assigned >= 0

        sil = float("nan")
        if result.n_clusters >= 2 and int(mask.sum()) > result.n_clusters:
            sil = float(
                silhouette_score(
                    vectors[mask], assigned[mask], metric="cosine",
                    sample_size=min(3000, int(mask.sum())), random_state=cfg.seed,
                )
            )
        mean_cohesion = (
            float(np.mean([cohesion(vectors[r]) for r in result.clusters.values()]))
            if result.clusters
            else 0.0
        )

        out.append(
            {
                "strategy": name,
                "knob": f"{strategy.knob.name}={result.native_param:.4g}",
                "clusters": result.n_clusters,
                "noise_pct": 100.0 * result.unclustered / len(units),
                "cohesion": mean_cohesion,
                "silhouette": sil,
                "converged": result.converged,
            }
        )
    return out
