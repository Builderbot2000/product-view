"""Harness for the pre-LLM embedding-route upgrade trials (llm-trials.md,
"Embedding route: upgrade trials"). Importable; run from the repo root with
`.venv/Scripts/python.exe -X utf8`, and put the repo root on sys.path
(`sys.path.insert(0, ".")`) before `from trials.prellm import harness`.

API
---
The fix stack lives in trials/prellm/stack.py: `stack.run(end, order_seed, stack.FINAL)`
-> (window, labels, info) on any window end date; `stack.window(end, opts)` and
`stack.cluster(w, order_seed, opts)` separately. Group S results and verdicts:
trials/runs/prellm/result-S.md; final dev clustering:
trials/runs/prellm/stack/clusters-dev.json.

Data
    w = load_window(end="2026-09-22", months=4, stream="negative"|"all")
        Window of complaint units (the old pipeline's units: cached MiniLM
        segments re-joined at 0.45). Window covers created_at in
        [end + 1 day - round(months * 30.44) days, end + 1 day). "negative" is the
        old star stream (1-3 stars, 20+ chars, translation not dropped); "all" is
        every star. Fields, row-aligned over units:
          w.texts, w.vectors (n, 384, L2-normalised), w.review_id, w.seq,
          w.stars, w.thumbs, w.created_at, w.spans (char span in the review's
          English text, or None), w.keys [(review_id, seq)], w.rows (reviews).
        w.subset(idx, stream="name") keeps only those units (U4 uses it).

Clustering (B0 = the old code path)
    cfg = ClusterConfig()          k 10, band 20-30, min size 5, cohesion 0.35,
                                   Leiden seed 42, vague set-aside on
    labels = cluster_b0(w, order_seed=0, cfg=cfg)
        np.int array over w's units: >= 0 issue cluster, -1 Miscellaneous
        (unclustered / filtered), -2 general bucket. Labels are canonical:
        renumbered by size (largest 0). The input order is permuted by
        order_seed before graph building and mapped back.
    Swappable steps (what cluster_b0 is made of; trials/prellm/stack.py composes
    its own pipeline from them):
        vague_mask(w)                         -> bool, the old vague.py set-aside
        leiden_search(vectors, cfg, order_seed) -> local labels (-1 unclustered), info
        centres(w, labels)                    -> {label: unit-norm centre}
        canonical(labels)                     -> renumbered labels

Gold and measures
    g = gold(w, slice="v1")    V1 points mapped onto w's units. slice "v2" raises
                               unless env PRELLM_HELDOUT=1.
        g.unit_labels {unit index: frozenset of labels} for every unit of a slice
        review in w ("X" = overlaps no point); g.points (dicts: n, review_id,
        stars, quote, labels, issues, units, status); g.counts.
    m = evaluate(w, labels, slice="v1", g=None)
        dict: P, R, tone, grab_bags, split, coverage, misc_share, general_share,
        n_clusters, quote_precision {closeness, thumbs}, clusters (table rows),
        mostly_U, plus counts. Definitions follow the spec table exactly; see
        evaluate's docstring.
    r = run_orders(fn, w, n=5, slice="v1")
        fn(order_seed) -> labels over w. Returns medians, [min, max] ranges,
        mean pairwise ARI over all w units, per-order measures and runtimes.

Output
    titles(w, labels)                -> {label: {"title", "keywords"}} (old c-TF-IDF +
                                        sentence titles; -2 bucket title, -1 Misc)
    save_clustering(path, w, labels, measures=None, extra=None)
    d = load_clustering(path)        the JSON dict
    labels = labels_from(d, w)       saved labels mapped onto a window by
                                     (review_id, seq); units not in the file -> -1

Saved JSON shape
    {"meta": {end, months, stream, start, n_units, n_reviews, saved_at, ...extra},
     "units": [{"review_id", "seq", "label"}...]          (every window unit),
     "clusters": [{"id", "title", "keywords", "size", "n_reviews", "cohesion",
                   "centre": [384 floats] (issue clusters only),
                   "members": [{"unit", "text", "review_id", "seq", "created_at",
                                "stars", "thumbs_up", "closeness"}...]   (closest first)}...]
                 (issue clusters by size, then id -2 general bucket, id -1 Miscellaneous),
     "measures": evaluate(...) output or null}
"""
from __future__ import annotations

import difflib
import json
import os
import random
import re
import sqlite3
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from itertools import combinations
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trials.prellm.legacy import (  # noqa: E402
    granularity, graph, strategies, synthesize, units as units_mod, vague,
)

MODEL = "all-MiniLM-L6-v2"
OUT = ROOT / "trials" / "runs" / "prellm"
SEL = ROOT / "trials" / "runs"
MISC, GENERAL = -1, -2


# ---------------------------------------------------------------- encoder ----

@lru_cache(maxsize=1)
def _encoder():
    from sentence_transformers import SentenceTransformer
    # Default HF cache (the model is there); the old encoder's cache folder is empty.
    return SentenceTransformer(f"sentence-transformers/{MODEL}")


def encode(texts) -> np.ndarray:
    v = _encoder().encode(list(texts), batch_size=256, convert_to_numpy=True,
                          normalize_embeddings=True, show_progress_bar=False)
    return np.ascontiguousarray(v, dtype=np.float32)


# ----------------------------------------------------------------- window ----

def _db():
    db = sqlite3.connect(ROOT / "data" / "reviews.db")
    db.execute("ATTACH ? AS cache", (str(ROOT / "data" / "cache.db"),))
    return db


def window_bounds(end: str, months: int = 4) -> tuple[str, str]:
    stop = date.fromisoformat(end) + timedelta(days=1)
    start = stop - timedelta(days=round(months * 30.44))
    return start.isoformat(), stop.isoformat()


@dataclass
class Window:
    end: str
    months: int
    stream: str
    start: str
    rows: list[dict]              # reviews in the window's stream
    texts: list[str]
    vectors: np.ndarray
    review_id: np.ndarray
    seq: np.ndarray
    stars: np.ndarray
    thumbs: np.ndarray
    created_at: np.ndarray
    spans: list                   # (start, end) in the review's English text, or None
    info: dict = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.texts)

    @property
    def keys(self) -> list[tuple[str, int]]:
        return list(zip(self.review_id.tolist(), self.seq.tolist()))

    def subset(self, idx, stream: str | None = None) -> "Window":
        idx = np.asarray(idx, dtype=np.int64)
        rids = set(self.review_id[idx].tolist())
        return Window(
            end=self.end, months=self.months, stream=stream or self.stream,
            start=self.start, rows=[r for r in self.rows if r["review_id"] in rids],
            texts=[self.texts[i] for i in idx], vectors=self.vectors[idx],
            review_id=self.review_id[idx], seq=self.seq[idx], stars=self.stars[idx],
            thumbs=self.thumbs[idx], created_at=self.created_at[idx],
            spans=[self.spans[i] for i in idx], info=dict(self.info, parent_units=len(self)),
        )


def _segment_spans(text: str, segs: list[str]) -> list:
    """Find each cached segment in the review text, in reading order."""
    out, cur = [], 0
    low = text.lower()
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


def _groups(vecs: list, threshold: float) -> list[list[int]]:
    """Segment indices of each unit: the same rule as legacy units.build."""
    groups: list[list] = []
    for k, vec in enumerate(vecs):
        if groups and float(vec @ units_mod._unit(groups[-1][1])) >= threshold:
            groups[-1][0].append(k)
            groups[-1][1] = groups[-1][1] + vec
        else:
            groups.append([[k], vec.astype(np.float64)])
    return [g[0] for g in groups]


def load_window(end: str = "2026-09-22", months: int = 4, stream: str = "negative",
                min_chars: int = 20, merge_threshold: float = units_mod.DEFAULT_MERGE_THRESHOLD
                ) -> Window:
    if stream not in ("negative", "all"):
        raise ValueError(stream)
    start, stop = window_bounds(end, months)
    db = _db()
    rows = [dict(zip(("review_id", "text", "score", "thumbs_up", "created_at"), r)) for r in db.execute(
        f"""SELECT r.review_id, COALESCE(t.content_en, r.content), r.score, r.thumbs_up, r.created_at
              FROM reviews r LEFT JOIN cache.translations t ON t.review_id = r.review_id
             WHERE r.created_at >= ? AND r.created_at < ? AND r.score > 0
               {"AND r.score <= 3" if stream == "negative" else ""}
               AND LENGTH(TRIM(r.content)) >= ?
               AND (t.review_id IS NULL OR t.content_en IS NOT NULL)
             ORDER BY r.review_id""", (start, stop, min_chars))]
    segs: dict[str, list] = {}
    ids = [r["review_id"] for r in rows]
    for i in range(0, len(ids), 900):
        chunk = ids[i:i + 900]
        for rid, text, blob in db.execute(
                f"SELECT review_id, text, vector FROM cache.segments WHERE model = ? "
                f"AND review_id IN ({','.join('?' * len(chunk))}) ORDER BY review_id, seq",
                (MODEL, *chunk)):
            segs.setdefault(rid, []).append((text, np.frombuffer(blob, dtype=np.float32)))
    missing = [r["review_id"] for r in rows if r["review_id"] not in segs]
    rows = [r for r in rows if r["review_id"] in segs]
    per_review = [segs[r["review_id"]] for r in rows]
    u = units_mod.build(per_review, merge_threshold)

    # Spans: mirror units.build's grouping to know which segments make each unit.
    spans, seg_miss = [], 0
    for r, seglist in zip(rows, per_review):
        ss = _segment_spans(r["text"], [t for t, _ in seglist])
        seg_miss += sum(s is None for s in ss)
        for grp in _groups([v for _, v in seglist], merge_threshold):
            part = [ss[k] for k in grp]
            spans.append((part[0][0], part[-1][1]) if part[0] and part[-1] else None)
    assert len(spans) == len(u), "span grouping out of step with units.build"

    rr = [rows[int(j)] for j in u.review_idx]
    w = Window(
        end=end, months=months, stream=stream, start=start, rows=rows, texts=u.texts,
        vectors=u.vectors, review_id=np.array([r["review_id"] for r in rr], dtype=object),
        seq=u.seq.astype(np.int64), stars=np.array([r["score"] for r in rr], dtype=np.int64),
        thumbs=np.array([r["thumbs_up"] or 0 for r in rr], dtype=np.int64),
        created_at=np.array([r["created_at"] for r in rr], dtype=object), spans=spans,
        info={"reviews_without_segments": len(missing), "segments_not_found": seg_miss,
              "units_without_span": sum(s is None for s in spans)},
    )
    return w


# ------------------------------------------------------------- clustering ----

@dataclass
class ClusterConfig:
    knn_k: int = 10
    band: tuple[int, int] = (20, 30)
    min_size: int = 5
    cohesion_floor: float = 0.35
    leiden_seed: int = 42
    set_aside_vague: bool = True


def vague_mask(w: Window) -> np.ndarray:
    """The old vague.py set-aside (word list + anchor similarity)."""
    return vague.vague_mask(w.texts, w.vectors, encode)


def leiden_search(vectors: np.ndarray, cfg: ClusterConfig, order_seed: int = 0,
                  strategy=None) -> tuple[np.ndarray, dict]:
    """The old path: permute, exact kNN, Leiden, binary search for the post-filter
    band with the min-size and cohesion filter. Returns labels in the input order
    (-1 = unclustered) and search info."""
    n = len(vectors)
    labels = np.full(n, MISC, dtype=np.int64)
    if n < cfg.min_size:
        return labels, {"n_clusters": 0}
    perm = np.random.default_rng(order_seed).permutation(n)
    v = vectors[perm]
    knn = graph.build_knn(v, k=cfg.knn_k)
    strat = strategy or strategies.LeidenStrategy(seed=cfg.leiden_seed)
    res = granularity.search(strat, v, knn, cfg.band, cfg.min_size, cfg.cohesion_floor)
    local = np.full(n, MISC, dtype=np.int64)
    for new, (_, members) in enumerate(sorted(res.clusters.items())):
        local[members] = new
    labels[perm] = local
    return labels, {"n_clusters": res.n_clusters, "param": res.native_param,
                    "converged": res.converged, "fits": res.iterations}


def canonical(labels: np.ndarray) -> np.ndarray:
    """Renumber issue clusters by size (largest 0), ties by first member index."""
    labels = np.asarray(labels, dtype=np.int64)
    out = labels.copy()
    ids = [l for l in np.unique(labels) if l >= 0]
    ids.sort(key=lambda l: (-int(np.sum(labels == l)), int(np.flatnonzero(labels == l)[0])))
    for new, l in enumerate(ids):
        out[labels == l] = new
    return out


def centres(w: Window, labels: np.ndarray) -> dict[int, np.ndarray]:
    return {int(l): graph.centroid(w.vectors[labels == l]) for l in np.unique(labels) if l >= 0}


def cluster_b0(w: Window, order_seed: int = 0, cfg: ClusterConfig | None = None) -> np.ndarray:
    cfg = cfg or ClusterConfig()
    labels = np.zeros(len(w), dtype=np.int64)
    if cfg.set_aside_vague:
        labels[vague_mask(w)] = GENERAL
    elig = np.flatnonzero(labels == 0)
    local, _ = leiden_search(w.vectors[elig], cfg, order_seed)
    labels[elig] = local
    return canonical(labels)


# ------------------------------------------------------------------- gold ----

_QUOTES = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', " ": " "})


def _norm_map(text: str) -> tuple[str, list[int]]:
    """Lower-case, unify quotes, collapse whitespace; keep a map to original offsets."""
    out, idx, prev_space = [], [], False
    for i, ch in enumerate(text.translate(_QUOTES).lower()):
        if ch.isspace():
            if prev_space or not out:
                continue
            ch, prev_space = " ", True
        else:
            prev_space = False
        out.append(ch)
        idx.append(i)
    return "".join(out), idx


def _norm(s: str) -> str:
    return _norm_map(s)[0].strip()


def slice_reviews(slice: str) -> list[dict]:
    """The selection run's review sets (trials/lloom/lloom.py `sample`): V1 = newest 100
    of 20+ chars, all stars; V2 = 100 at random (seed 0) from February 2026."""
    db = _db()
    month = {"v1": None, "v2": "2026-02"}[slice]
    rows = db.execute(
        f"""SELECT r.review_id, COALESCE(t.content_en, r.content), r.score, r.created_at
            FROM reviews r LEFT JOIN cache.translations t USING (review_id)
            WHERE length(r.content) >= 20 {"AND substr(r.created_at, 1, 7) = ?" if month else ""}
            ORDER BY r.created_at DESC {"" if month else "LIMIT ?"}""",
        (month,) if month else (100,)).fetchall()
    if month and len(rows) > 100:
        rows = sorted(random.Random(0).sample(rows, 100), key=lambda r: r[3], reverse=True)
    return [dict(review_id=a, text=b, score=c, created_at=d) for a, b, c, d in rows]


def _parse_labels(path: Path):
    judged, gold = {}, {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].split()
        if not line:
            continue
        if line[0] == "concept":
            judged[line[1]] = line[2]
        elif line[0] == "dup":
            continue
        else:
            gold[int(line[0])] = set(line[1:])
    return judged, gold


@dataclass
class Gold:
    slice: str
    unit_labels: dict            # unit index -> frozenset(labels); "X" = overlaps no point
    points: list[dict]
    counts: dict


def gold(w: Window, slice: str = "v1") -> Gold:
    """Map each labelled point's quote onto the window units it overlaps.

    Labels: a concept judged `broad` becomes G; G/U/N stay; specific concept ids are
    issues. Matching: the quote is found in the review's English text after
    lower-casing, unifying curly quotes and collapsing whitespace; failing that,
    difflib's matching blocks are used when they cover >= 80% of the quote (fuzzy).
    A unit overlaps a quote when their character spans share >= 3 characters; a unit
    with no span (segment not found in the text) falls back to token overlap
    (>= 50% of the quote's tokens). A point with no overlapping unit in the window is
    'outside' (review not in the window's units, e.g. 4-5 stars on the star stream,
    or a filtered unit) or 'no_unit' (review present, quote only on dropped text)."""
    if slice == "v2" and os.environ.get("PRELLM_HELDOUT") != "1":
        raise PermissionError("V2 is held out: set PRELLM_HELDOUT=1 only for the final run")
    d = SEL / f"sel-{slice}"
    bullets = {b["id"]: b for b in map(json.loads, (d / "bullets.jsonl").open(encoding="utf-8"))}
    order = json.loads((d / "scores-complaint.json").read_text(encoding="utf-8"))["bullets"]
    judged, labels = _parse_labels(d / "labels.txt")
    texts = {r["review_id"]: r for r in slice_reviews(slice)}
    by_review: dict[str, list[int]] = {}
    for i, rid in enumerate(w.review_id):
        by_review.setdefault(rid, []).append(i)

    unit_labels = {i: set() for rid in texts for i in by_review.get(rid, [])}
    points, counts = [], Counter()
    for n, bid in enumerate(order, 1):
        b = bullets[bid]
        raw = labels.get(n, set())
        lab = {("G" if judged.get(x) == "broad" else x) for x in raw}
        issues = {x for x in lab if x not in ("G", "U", "N")}
        rid = b["review_id"]
        text = texts[rid]["text"] if rid in texts else ""
        nt, mp = _norm_map(text)
        q = _norm(b["quote"])
        span, how = None, "unmatched"
        j = nt.find(q) if q else -1
        if j >= 0:
            span, how = (mp[j], mp[j + len(q) - 1] + 1), "exact"
        elif q:
            sm = difflib.SequenceMatcher(None, nt, q, autojunk=False)
            blocks = [bl for bl in sm.get_matching_blocks() if bl.size >= 3]
            if blocks and sum(bl.size for bl in blocks) >= 0.8 * len(q):
                span, how = (mp[blocks[0].a], mp[blocks[-1].a + blocks[-1].size - 1] + 1), "fuzzy"
        hit = []
        qtok = set(re.findall(r"[a-z0-9']+", q))
        for i in by_review.get(rid, []):
            s = w.spans[i]
            if s is not None and span is not None:
                if min(s[1], span[1]) - max(s[0], span[0]) >= 3:
                    hit.append(i)
            elif s is None and qtok:
                ut = set(re.findall(r"[a-z0-9']+", _norm(w.texts[i])))
                if len(ut & qtok) >= 0.5 * len(qtok):
                    hit.append(i)
                    how = how + "+tokens"
        status = how if hit else ("no_unit" if rid in by_review else "outside")
        counts[status] += 1
        for i in hit:
            unit_labels[i] |= lab
        points.append(dict(n=n, review_id=rid, stars=b["score"], quote=b["quote"], labels=lab,
                           issues=issues, units=hit, status=status))
    unit_labels = {i: frozenset(s) if s else frozenset({"X"}) for i, s in unit_labels.items()}
    counts = dict(counts)
    counts.update(
        points=len(points), issue_points=sum(bool(p["issues"]) for p in points),
        slice_reviews=len(texts), slice_reviews_in_window=sum(1 for r in texts if r in by_review),
        labelled_units=len(unit_labels),
        x_units=sum(1 for s in unit_labels.values() if s == {"X"}),
        units_with_issue=sum(1 for s in unit_labels.values() if s - {"G", "U", "N", "X"}),
    )
    return Gold(slice=slice, unit_labels=unit_labels, points=points, counts=counts)


# --------------------------------------------------------------- measures ----

def _issues(s) -> set:
    return set(s) - {"G", "U", "N", "X"}


def evaluate(w: Window, labels: np.ndarray, slice: str = "v1", g: Gold | None = None,
             names: dict | None = None) -> dict:
    """Spec measures over the slice's labelled units (every unit of a slice review in w;
    'X' when it overlaps no point).

    Issue clusters: labels >= 0 (not -2 general bucket, not -1 Miscellaneous).
    Credited issue: the issue label most labelled units carry (ties: lowest id);
      none when no labelled unit carries an issue.
    P: over labelled units in issue clusters, share whose labels include the cluster's
      credited issue (G, X, U, N and other issues are misses; clusters with no
      credited issue contribute misses only).
    R: of slice points with an issue label (all stars), share with at least one unit
      in a cluster credited with one of its issues.
    Tone: issue clusters with >= 3 labelled units, more than half of them G-or-X only.
    Grab-bags: issue clusters with >= 5 labelled units and P < 50%.
    Split: issues credited to two or more clusters.
    Coverage: share of window units in issue clusters.
    Mostly-U: issue clusters with >= 2 labelled units, more than half carrying U (none
      under the round-10 rule, which leaves U-only units out of the key).
    Quote precision: per credited cluster, the top 5 labelled members by closeness to
      the centre vs by thumbs-up (ties by unit index); pooled share carrying the issue.
    """
    g = g or gold(w, slice)
    labels = np.asarray(labels)
    names = names or {}
    cents = centres(w, labels)
    ul = g.unit_labels
    if os.environ.get("PRELLM_U_RULE", "exclude") == "exclude":
        # Round 10 rule: U ("no other review of the 100-review sample shares it") is judged on
        # the sample while clusters span the whole window, so U units leave the key (neither
        # right nor wrong). PRELLM_U_RULE=wrong restores the rule of rounds 4-9.
        ul = {i: s for i, s in ul.items() if not ("U" in s and not _issues(s))}
    rows, credited = [], {}
    hits = total = 0
    qp_close = [0, 0]
    qp_thumb = [0, 0]
    for l in sorted(cents):
        members = np.flatnonzero(labels == l)
        lab = [i for i in members if i in ul]
        cnt = Counter(x for i in lab for x in _issues(ul[i]))
        issue = min(cnt, key=lambda k: (-cnt[k], k)) if cnt else None
        ok = sum(1 for i in lab if issue in ul[i]) if issue else 0
        credited[l] = issue
        hits += ok
        total += len(lab)
        gx = sum(1 for i in lab if ul[i] <= {"G", "X"})
        nu = sum(1 for i in lab if "U" in ul[i])
        maj = Counter(x for i in lab for x in ul[i]).most_common(1)
        if issue and lab:
            close = w.vectors[lab] @ cents[l]
            by_close = [lab[j] for j in np.argsort(-close, kind="stable")[:5]]
            by_thumb = sorted(lab, key=lambda i: (-w.thumbs[i], i))[:5]
            qp_close[0] += sum(issue in ul[i] for i in by_close); qp_close[1] += len(by_close)
            qp_thumb[0] += sum(issue in ul[i] for i in by_thumb); qp_thumb[1] += len(by_thumb)
        rows.append(dict(
            id=int(l), size=int(len(members)), labelled=len(lab), credited=issue,
            precision=(ok / len(lab)) if lab else None, majority=maj[0][0] if maj else None,
            g_or_x=gx, u=nu, title=names.get(int(l), {}).get("title") if names else None,
            tone=len(lab) >= 3 and gx > len(lab) / 2,
            grab_bag=len(lab) >= 5 and (ok / len(lab)) < 0.5,
            mostly_u=len(lab) >= 2 and nu > len(lab) / 2,
        ))
    issue_pts = [p for p in g.points if p["issues"]]
    if os.environ.get("PRELLM_R_RULE", "pair") == "pair":
        # Round 13 rule: a review's complaint counts once. Each (review, issue) pair is
        # recalled when any of its units sits in a cluster credited with that issue, so a
        # fragment filed by its review's cause is not a point of its own.
        # PRELLM_R_RULE=point restores per-point recall (rounds 4-12).
        pairs: dict = {}
        for p in issue_pts:
            for x in p["issues"]:
                pairs.setdefault((p["review_id"], x), []).extend(p["units"])
        issue_pts = [dict(issues={x}, units=u) for (_, x), u in pairs.items()]
    recalled = sum(
        1 for p in issue_pts
        if any(labels[i] >= 0 and credited.get(int(labels[i])) in p["issues"] for i in p["units"]))
    per_issue = Counter(v for v in credited.values() if v)
    n = len(w)
    return dict(
        P=hits / total if total else 0.0,
        R=recalled / len(issue_pts) if issue_pts else 0.0,
        tone=sum(r["tone"] for r in rows),
        grab_bags=sum(r["grab_bag"] for r in rows),
        split=sum(1 for v in per_issue.values() if v >= 2),
        coverage=float(np.mean(labels >= 0)) if n else 0.0,
        misc_share=float(np.mean(labels == MISC)) if n else 0.0,
        general_share=float(np.mean(labels == GENERAL)) if n else 0.0,
        n_clusters=len(cents),
        quote_precision=dict(
            closeness=qp_close[0] / qp_close[1] if qp_close[1] else None,
            thumbs=qp_thumb[0] / qp_thumb[1] if qp_thumb[1] else None, n=qp_close[1]),
        labelled_in_issue_clusters=total,
        labelled_in_general=sum(1 for i in ul if labels[i] == GENERAL),
        labelled_in_misc=sum(1 for i in ul if labels[i] == MISC),
        issue_points=len(issue_pts), recalled_points=recalled,
        split_issues=sorted(k for k, v in per_issue.items() if v >= 2),
        clusters=rows,
        mostly_U=[r for r in rows if r["mostly_u"]],
    )


SCALARS = ("P", "R", "tone", "grab_bags", "split", "coverage", "misc_share",
           "general_share", "n_clusters", "qp_close", "qp_thumbs")


def ari(a, b) -> float:
    from sklearn.metrics import adjusted_rand_score
    return float(adjusted_rand_score(a, b))


def run_orders(fn, w: Window, n: int = 5, slice: str = "v1", seeds=None) -> dict:
    """fn(order_seed) -> labels over w. Medians, ranges, mean pairwise ARI."""
    g = gold(w, slice)
    seeds = list(seeds) if seeds is not None else list(range(n))
    labs, meas, secs = [], [], []
    for s in seeds:
        t = time.perf_counter()
        lab = np.asarray(fn(s))
        secs.append(time.perf_counter() - t)
        m = evaluate(w, lab, slice, g)
        m["qp_close"] = m["quote_precision"]["closeness"]
        m["qp_thumbs"] = m["quote_precision"]["thumbs"]
        labs.append(lab)
        meas.append(m)
    out = {"median": {}, "range": {}}
    for k in SCALARS:
        vals = [m[k] for m in meas if m[k] is not None]
        out["median"][k] = statistics.median(vals) if vals else None
        out["range"][k] = [min(vals), max(vals)] if vals else None
    pairs = [ari(a, b) for a, b in combinations(labs, 2)]
    out["ARI"] = float(np.mean(pairs)) if pairs else None
    out["ARI_range"] = [min(pairs), max(pairs)] if pairs else None
    out["seconds"] = secs
    out["per_order"] = [{k: m[k] for k in SCALARS} for m in meas]
    out["labels"] = labs
    out["measures"] = meas
    out["gold_counts"] = g.counts
    return out


# ----------------------------------------------------------------- output ----

def titles(w: Window, labels: np.ndarray) -> dict:
    """Old synthesis: c-TF-IDF keywords and a central short member as title,
    largest cluster first so it keeps a contested title."""
    labels = np.asarray(labels)
    ids = sorted((int(l) for l in np.unique(labels) if l >= 0),
                 key=lambda l: (-int(np.sum(labels == l)), l))
    out = {}
    if ids:
        kw = synthesize.ctfidf({l: [w.texts[i] for i in np.flatnonzero(labels == l)] for l in ids})
        taken: set[str] = set()
        for l in ids:
            m = np.flatnonzero(labels == l)
            c = graph.centroid(w.vectors[m])
            t = synthesize.sentence_title([w.texts[i] for i in m], w.vectors[m] @ c, kw.get(l, []), taken)
            taken.add(t.lower())
            out[l] = {"title": t, "keywords": kw.get(l, [])}
    out[GENERAL] = {"title": vague.BUCKET_TITLE, "keywords": []}
    out[MISC] = {"title": "Miscellaneous", "keywords": []}
    return out


def _member(w: Window, i: int, c) -> dict:
    return dict(unit=int(i), text=w.texts[i], review_id=w.review_id[i], seq=int(w.seq[i]),
                created_at=w.created_at[i], stars=int(w.stars[i]), thumbs_up=int(w.thumbs[i]),
                closeness=round(float(w.vectors[i] @ c), 4) if c is not None else None)


def save_clustering(path, w: Window, labels: np.ndarray, measures: dict | None = None,
                    extra: dict | None = None, names: dict | None = None) -> Path:
    labels = np.asarray(labels)
    names = names or titles(w, labels)
    cents = centres(w, labels)
    clusters = []
    for l in sorted(cents, key=lambda l: (-int(np.sum(labels == l)), l)) + [GENERAL, MISC]:
        m = np.flatnonzero(labels == l)
        c = cents.get(l)
        mem = [_member(w, i, c) for i in m]
        if c is not None:
            mem.sort(key=lambda x: -x["closeness"])
        clusters.append(dict(
            id=int(l), title=names.get(l, {}).get("title"), keywords=names.get(l, {}).get("keywords", []),
            size=int(len(m)), n_reviews=int(len(set(w.review_id[m].tolist()))),
            cohesion=round(graph.cohesion(w.vectors[m], c), 4) if c is not None and len(m) else None,
            centre=[round(float(x), 6) for x in c] if c is not None else None, members=mem))
    meas = None
    if measures is not None:
        meas = {k: v for k, v in measures.items() if k not in ("labels",)}
    doc = dict(
        meta=dict(end=w.end, months=w.months, stream=w.stream, start=w.start, n_units=len(w),
                  n_reviews=len(set(w.review_id.tolist())),
                  saved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  window_info=w.info, **(extra or {})),
        units=[dict(review_id=r, seq=int(s), label=int(l)) for r, s, l in zip(w.review_id, w.seq, labels)],
        clusters=clusters, measures=meas)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1, default=_jsonable), encoding="utf-8")
    return path


def _jsonable(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (set, frozenset)):
        return sorted(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o))


def load_clustering(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def labels_from(saved: dict, w: Window) -> np.ndarray:
    m = {(u["review_id"], u["seq"]): u["label"] for u in saved["units"]}
    return np.array([m.get(k, MISC) for k in w.keys], dtype=np.int64)
