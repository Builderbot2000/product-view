"""The code-fix stack for the embedding route (llm-trials.md, "Embedding route:
upgrade trials", group S): U1, U2, U3, U4 and U6 as switchable options on top
of the B0 path in harness.py.

    from trials.prellm import stack
    opts = stack.FINAL                              # the final stack (U2+U4+U6)
    w, labels, info = stack.run("2026-09-22", order_seed=0, opts=opts)
    # w is the window the labels refer to (the sentiment-filtered all-star window
    # when U4 is on, the star stream otherwise); labels as in harness (-1 Misc,
    # -2 general bucket). info: joins, parent links, per-step counts.
    w = stack.window("2026-02-28", opts)            # the window alone
    labels, info = stack.cluster(w, order_seed, opts)

The fixes:
- U1 specificity: sum of corpus IDF (all cached segments as documents) over a
  unit's distinct content words (vague.py's word lists remove stop, sentiment
  and generic banking words). Units below `spec_min` go to the general bucket
  before clustering, on top of the old vague set-aside.
- U2 range cap: reach (third-nearest-neighbour cosine among the units being
  clustered below `reach` -> Miscellaneous before clustering), pull (member
  below `pull` cosine to its cluster centre -> Miscellaneous after), then the
  min-size and cohesion-floor filter again, so weak clusters are held back.
  Quotes ranked by closeness (save_clustering sorts members by it).
- U3 duplicate join: cluster pairs whose centres reach `join` cosine are joined,
  closest pair first, each cluster at most once (never chained). Parent links
  are reported, not merged: B is under A when >= 80% of B's members are at
  least as close to A's centre as A's own 20th-percentile member.
- U4 sentence sentiment: the all-star window, each unit classified by
  cardiffnlp/twitter-roberta-base-sentiment-latest; kept when
  P(negative) >= `neg_min` and P(negative) >= P(positive) (v2 on: neg_min 0, so
  negative outweighs positive and neutral is ignored).
- Search (every stack run, `search="flank"`): see band_search; the old search
  lands on the descending flank once the reach cap thins the graph.
- U6 consensus: the B0 Leiden search over `runs` input orders (seeds
  order_seed*1000 + i), a co-association matrix (share of runs two units share
  a cluster), its graph thresholded at `tau` (Lancichinetti & Fortunato 2012),
  then the same Leiden band search once on that graph.
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trials.prellm import harness as H  # noqa: E402
from trials.prellm.legacy import granularity, graph, vague  # noqa: E402

SENTIMENT_MODEL = "cardiffnlp/twitter-roberta-base-sentiment-latest"
CACHE = H.OUT / "cache"


@dataclass(frozen=True)
class StackOptions:
    u1: bool = True
    u2: bool = True
    u3: bool = True
    u4: bool = True
    u6: bool = True
    spec_min: float = 6.0        # U1
    reach: float = 0.40          # U2, before
    pull: float = 0.50           # U2, after
    join: float = 0.85           # U3
    neg_min: float = 0.40        # U4
    runs: int = 20               # U6
    tau: float = 0.5             # U6
    search: str = "flank"        # "flank" (band_search) or "legacy" (old granularity.search)

    def drop(self, fix: str) -> "StackOptions":
        return replace(self, **{fix.lower(): False})


B0_LIKE = StackOptions(u1=False, u2=False, u3=False, u4=False, u6=False)

# The final stack after rule 2 on variant v2 (trials/runs/prellm/result-S.md):
# U2 + U4 + U6 with the flank search; U1 and U3 removed as dead weight.
FINAL = StackOptions(u1=False, u3=False, spec_min=6.0, reach=0.40, pull=0.50, join=0.75,
                     neg_min=0.0, runs=20, tau=0.5, search="flank")


# ------------------------------------------------------------------ U1 ----

@lru_cache(maxsize=1)
def corpus_idf() -> dict[str, float]:
    """IDF of each token over every cached segment (the whole corpus)."""
    import math
    import sqlite3
    db = sqlite3.connect(ROOT / "data" / "cache.db")
    df, n = {}, 0
    for (text,) in db.execute("SELECT text FROM segments WHERE model = ?", (H.MODEL,)):
        n += 1
        for t in set(vague._TOKEN.findall(text.lower())):
            df[t] = df.get(t, 0) + 1
    return {t: math.log(n / c) for t, c in df.items()} | {"__max__": math.log(n)}


def specificity(texts) -> np.ndarray:
    idf = corpus_idf()
    out = []
    for t in texts:
        words = set(vague._content_words(t))
        out.append(sum(idf.get(x, idf["__max__"]) for x in words))
    return np.array(out)


# ------------------------------------------------------------------ U4 ----

def sentiment(texts) -> np.ndarray:
    """(n, 3) probabilities [negative, neutral, positive], cached on disk by text."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / "sentiment.json"
    cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    key = lambda t: hashlib.sha1(t.encode("utf-8")).hexdigest()  # noqa: E731
    todo = sorted({t for t in texts if key(t) not in cache})
    if todo:
        from transformers import pipeline
        clf = pipeline("text-classification", model=SENTIMENT_MODEL, top_k=None,
                       truncation=True, max_length=256)
        for t, res in zip(todo, clf(todo, batch_size=32)):
            d = {r["label"]: r["score"] for r in res}
            cache[key(t)] = [d["negative"], d["neutral"], d["positive"]]
        path.write_text(json.dumps(cache), encoding="utf-8")
    return np.array([cache[key(t)] for t in texts])


def complaint_mask(w: H.Window, opts: StackOptions) -> np.ndarray:
    p = sentiment(w.texts)
    return (p[:, 0] >= opts.neg_min) & (p[:, 0] >= p[:, 2])


def window(end: str, opts: StackOptions = FINAL, months: int = 4) -> H.Window:
    if not opts.u4:
        return H.load_window(end, months, "negative")
    w = H.load_window(end, months, "all")
    keep = np.flatnonzero(complaint_mask(w, opts))
    sub = w.subset(keep, stream=f"all+sentiment>={opts.neg_min}")
    sub.info["sentiment_kept"] = int(len(keep))
    return sub


# ---------------------------------------------------------------- search ----

GRID = np.exp(np.linspace(np.log(0.05), np.log(60.0), 40))


def band_search(strategy, vectors, knn, cfg: H.ClusterConfig):
    """Fix to the old band search, used by every stack run: the post-filter cluster
    count is unimodal in the resolution, and the old sweep accepts the first in-band
    setting it meets, which after the reach cap is often on the descending flank
    (most units in fragments below min size, sent to Miscellaneous). This scans a
    fixed log grid of resolutions and keeps, among in-band settings, the one that
    clusters the most units; with none in band, the one closest to the band."""
    lo, hi = cfg.band
    best, best_key = None, None
    for r in GRID:
        lab = strategy.fit(vectors, knn, float(r))
        clusters, uncl = granularity.filter_clusters(lab, vectors, cfg.min_size, cfg.cohesion_floor)
        n = len(clusters)
        dist = 0 if lo <= n <= hi else min(abs(n - lo), abs(n - hi))
        key = (dist, uncl)
        if best_key is None or key < best_key:
            best, best_key = (float(r), clusters, n), key
    r, clusters, n = best
    out = np.full(len(vectors), H.MISC, dtype=np.int64)
    for new, (_, members) in enumerate(sorted(clusters.items())):
        out[members] = new
    return out, {"n_clusters": n, "param": r, "converged": best_key[0] == 0,
                 "unclustered": best_key[1]}


def base_cluster(vectors, cfg: H.ClusterConfig, order_seed: int, search: str = "flank"):
    """B0's kNN + Leiden on a permuted order, with the stack's band search."""
    if search == "legacy":
        return H.leiden_search(vectors, cfg, order_seed)
    n = len(vectors)
    labels = np.full(n, H.MISC, dtype=np.int64)
    if n < cfg.min_size:
        return labels, {"n_clusters": 0}
    from trials.prellm.legacy.strategies import LeidenStrategy
    perm = np.random.default_rng(order_seed).permutation(n)
    v = vectors[perm]
    local, info = band_search(LeidenStrategy(seed=cfg.leiden_seed), v, graph.build_knn(v, k=cfg.knn_k), cfg)
    labels[perm] = local
    return labels, info


# ------------------------------------------------------------------ U6 ----

class _GraphLeiden:
    """A strategy for granularity.search that clusters a fixed weighted graph."""

    def __init__(self, pairs, weights, n, seed=42):
        from trials.prellm.legacy.strategies import LeidenStrategy
        self.name, self.knob = "consensus-leiden", LeidenStrategy.knob
        self.pairs, self.weights, self.n, self.seed = pairs, weights, n, seed

    def fit(self, vectors, knn, native_param):
        import igraph as ig
        import leidenalg as la
        g = ig.Graph(n=self.n, edges=self.pairs.tolist(), directed=False)
        g.es["weight"] = self.weights.tolist()
        part = la.find_partition(g, la.RBConfigurationVertexPartition, weights="weight",
                                 resolution_parameter=float(native_param), seed=self.seed)
        return np.asarray(part.membership, dtype=np.int32)


def consensus(vectors: np.ndarray, cfg: H.ClusterConfig, order_seed: int, runs: int, tau: float,
              search: str = "flank"):
    n = len(vectors)
    co = np.zeros((n, n), dtype=np.float32)
    for i in range(runs):
        lab, _ = base_cluster(vectors, cfg, order_seed * 1000 + i, search)
        for l in np.unique(lab[lab >= 0]):
            m = np.flatnonzero(lab == l)
            co[np.ix_(m, m)] += 1
    co /= runs
    np.fill_diagonal(co, 0)
    iu = np.triu_indices(n, 1)
    keep = co[iu] >= tau
    pairs = np.column_stack((iu[0][keep], iu[1][keep])).astype(np.int32)
    weights = co[iu][keep].astype(np.float64)
    strat = _GraphLeiden(pairs, weights, n, cfg.leiden_seed)
    if search == "legacy":
        res = granularity.search(strat, vectors, None, cfg.band, cfg.min_size, cfg.cohesion_floor)
        labels = np.full(n, H.MISC, dtype=np.int64)
        for new, (_, members) in enumerate(sorted(res.clusters.items())):
            labels[members] = new
        return labels, {"edges": int(keep.sum()), "n_clusters": res.n_clusters,
                        "param": res.native_param, "converged": res.converged}
    labels, info = band_search(strat, vectors, None, cfg)
    return labels, dict(info, edges=int(keep.sum()))


# --------------------------------------------------------------- pipeline ----

def _refilter(w, labels, cfg):
    for l in np.unique(labels[labels >= 0]):
        m = np.flatnonzero(labels == l)
        if len(m) < cfg.min_size or graph.cohesion(w.vectors[m]) < cfg.cohesion_floor:
            labels[m] = H.MISC
    return labels


def join_duplicates(w, labels, threshold):
    """Join clusters whose centres reach `threshold`; each cluster joins at most once."""
    cents = H.centres(w, labels)
    ids = sorted(cents)
    pairs = []
    for a in range(len(ids)):
        for b in range(a + 1, len(ids)):
            s = float(cents[ids[a]] @ cents[ids[b]])
            if s >= threshold:
                pairs.append((s, ids[a], ids[b]))
    used, joins = set(), []
    for s, a, b in sorted(pairs, reverse=True):
        if a in used or b in used:
            continue
        used |= {a, b}
        labels[labels == b] = a
        joins.append({"into": int(a), "from": int(b), "cosine": round(s, 4)})
    return labels, joins


def parent_links(w, labels, contain=0.8, core=0.2):
    cents = H.centres(w, labels)
    links = []
    for a, ca in cents.items():
        ma = np.flatnonzero(labels == a)
        radius = float(np.quantile(w.vectors[ma] @ ca, core))
        for b in cents:
            if b == a:
                continue
            mb = np.flatnonzero(labels == b)
            if len(mb) > len(ma):
                continue
            share = float(np.mean(w.vectors[mb] @ ca >= radius))
            if share >= contain:
                links.append({"parent": int(a), "child": int(b), "share": round(share, 3)})
    return links


def cluster(w: H.Window, order_seed: int = 0, opts: StackOptions = FINAL,
            cfg: H.ClusterConfig | None = None) -> tuple[np.ndarray, dict]:
    cfg = cfg or H.ClusterConfig()
    info: dict = {"opts": asdict(opts)}
    labels = np.zeros(len(w), dtype=np.int64)
    labels[H.vague_mask(w)] = H.GENERAL
    info["vague"] = int(np.sum(labels == H.GENERAL))
    if opts.u1:
        low = (specificity(w.texts) < opts.spec_min) & (labels == 0)
        labels[low] = H.GENERAL
        info["u1_general"] = int(low.sum())
    if opts.u2:
        elig = np.flatnonzero(labels == 0)
        knn = graph.build_knn(w.vectors[elig], k=3)
        far = elig[knn.similarities[:, 2] < opts.reach]
        labels[far] = H.MISC
        info["u2_reach_misc"] = int(len(far))
    elig = np.flatnonzero(labels == 0)
    if opts.u6:
        local, info["core"] = consensus(w.vectors[elig], cfg, order_seed, opts.runs, opts.tau, opts.search)
    else:
        local, info["core"] = base_cluster(w.vectors[elig], cfg, order_seed, opts.search)
    labels[elig] = local
    if opts.u2:
        cents = H.centres(w, labels)
        pulled = 0
        for l, c in cents.items():
            m = np.flatnonzero(labels == l)
            out = m[w.vectors[m] @ c < opts.pull]
            labels[out] = H.MISC
            pulled += len(out)
        before = int(np.sum(labels == H.MISC))
        labels = _refilter(w, labels, cfg)
        info["u2_pull_misc"] = pulled
        info["u2_held_back"] = int(np.sum(labels == H.MISC)) - before
    if opts.u3:
        labels, info["joins"] = join_duplicates(w, labels, opts.join)
    labels = H.canonical(labels)
    info["parents"] = parent_links(w, labels)
    return labels, info


def run(end: str = "2026-09-22", order_seed: int = 0, opts: StackOptions = FINAL,
        months: int = 4):
    w = window(end, opts, months)
    labels, info = cluster(w, order_seed, opts)
    return w, labels, info
