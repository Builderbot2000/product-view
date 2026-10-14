"""The issue stage: reviews -> points -> issues, kept in a persistent codebook.

The method validated in llm-trials.md ("Viability test", re-run with
selection), after LLooM (Lam et al., CHI 2024):

1. Distill: each review's complaint and praise points, as exact quotes, each
   restated as a short neutral bullet.
2. Score against the codebook: every point is checked against every live
   concept of its side (or its `nearest` few). Earlier concepts never change;
   new reviews are counted against them first.
3. Loop on the leftovers (points matching no issue):
   - Cluster their bullets (embedding, UMAP, HDBSCAN; outliers stay out).
   - Synthesize: name each specific problem in a cluster, with an
     inclusion criterion.
   - Screen: a breadth check drops broad concepts and sends general
     opinions to general sentiment; a new concept whose definition means the
     same as a live one (issue or general group) joins it instead
     (BERTopic `merge_models`).
   - Score the new concepts, then Select: an integer program keeps the new
     concepts that cover most points with least overlap, the live ones fixed
     in (GoalEx, Wang et al. 2023). Nothing is ever merged by shared points.
   - File each selected issue under one area from a fixed, app-agnostic list.
4. Record parent links where one issue's matches contain most of another's
   (Sanderson & Croft 1999). Reported, never merged.

The first run over an empty codebook mints from every point (round 0); later
runs only from what the codebook does not already cover.

Cost. Scoring is nearly all of it, and minting is what makes it grow with the
square of the corpus: every candidate is scored against every point, and the
number of candidates grows with the points. `mint_sample` caps that: new
concepts are formed and selected on a fixed-size random sample of the points,
and only the kept ones are then scored on the rest (TopicGPT, TnT-LLM: build
the categories on a sample, then assign everything). Assigning is linear, so
cost then grows with the corpus, not its square. `nearest` and
`compact_scores` cut the scoring calls further; `estimate()` prints what a
run would cost before it starts.
"""

from __future__ import annotations

import hashlib
import logging
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np

from ..store import Store
from . import prompts as P
from .codebook import Codebook, now
from .llm import LLM, Req, arr, enum, obj

log = logging.getLogger(__name__)

SCALE = {"A": 1.0, "B": 0.75, "C": 0.5, "D": 0.25, "E": 0.0}
SIDES = ("complaint", "praise")
SHOWN = 25          # points shown to synthesize, closest to the cluster centre first
PARENT_INSIDE = 0.8
SAMPLE_SEED = 0


@dataclass
class IssueConfig:
    window_months: int = 12        # reviews this recent are distilled and grouped
    min_chars: int = 20
    sides: tuple[str, ...] = SIDES
    min_cluster_size: int = 4      # HDBSCAN; validated at 100 reviews a slice
    min_cluster_share: float = 0.0  # if set, min size is at least this share of the points clustered
    threshold: float = 0.75        # a score at or above this is a match (B = a clear case)
    loops: int = 1                 # rounds of minting from leftovers per run
    batch: int = 15                # points per scoring call
    compact_scores: bool = False   # scores as a bare list of letters, not {n, answer} objects
    nearest: int = 0               # score each point only against its N nearest concepts (0: all)
    mint_sample: int = 0           # form and select new concepts on at most this many points (0: all)
    join: float = 0.7              # definition similarity at which a join is checked
    overlap_cost: float = 1.0      # selection: cost of each repeated match
    concept_cost: float = 2.0      # selection: cost of each concept kept
    areas: dict[str, str] = field(default_factory=dict)   # area id -> "Name: description"


# --- side-specific prompts ----------------------------------------------------

PROMPTS = {
    "complaint": dict(synthesize=P.SYNTHESIZE, breadth=P.BREADTH, confirm=P.CONFIRM, score=P.SCORE,
                      what="failure"),
    "praise": dict(synthesize=P.SYNTHESIZE_PRAISE, breadth=P.BREADTH_PRAISE,
                   confirm=P.CONFIRM_PRAISE, score=P.SCORE_PRAISE, what="liked"),
}


def distiller(llm: LLM) -> str:
    """Model + prompt version: points from another distiller are never mixed in."""
    digest = hashlib.sha256((P.DISTILL + P.SUMMARIZE).encode()).hexdigest()[:8]
    return f"{llm.cfg.provider}:{llm.model('fast')}:{digest}"


def _norm(s: str) -> str:
    return " ".join(s.split()).lower()


# --- 1. distill -----------------------------------------------------------------

QUOTE_FMT = obj({"points": arr(obj({"quote": {"type": "string"}, "kind": enum("complaint", "praise")}))})
BULLET_FMT = obj({"bullets": arr(obj({"n": {"type": "integer"}, "bullet": {"type": "string"}}))})


def distill(llm: LLM, texts: dict[str, str]) -> dict[str, list[dict]]:
    """Each review's points. Two passes over all reviews (quotes, then bullets), so
    that with the Batch API each pass is one batch."""
    ids = list(texts)
    found = llm.run([Req(P.DISTILL, f"Review:\n{texts[r]}", QUOTE_FMT) for r in ids],
                    label="distill quotes")
    quotes = {r: [p for p in got["points"] if p["quote"].strip()] for r, got in zip(ids, found)}
    has = [r for r in ids if quotes[r]]

    def listing(r: str) -> str:
        return "\n".join(f"{j}. \"{p['quote']}\"" for j, p in enumerate(quotes[r], 1))

    said = llm.run([Req(P.SUMMARIZE, f"Review:\n{texts[r]}\n\nQuotes:\n{listing(r)}", BULLET_FMT)
                    for r in has], label="distill bullets")
    bullets = {r: {b["n"]: b["bullet"] for b in got["bullets"]} for r, got in zip(has, said)}
    return {r: [dict(seq=j, side=p["kind"], quote=p["quote"], exact=_norm(p["quote"]) in _norm(texts[r]),
                     bullet=bullets.get(r, {}).get(j) or p["quote"])
                for j, p in enumerate(quotes[r], 1)]
            for r in ids}


# --- 3a. cluster and synthesize --------------------------------------------------

def cluster(vecs: np.ndarray, min_size: int, seed: int = 42) -> np.ndarray:
    """UMAP to 5 dimensions, then HDBSCAN. -1 = outlier, left unassigned."""
    import umap
    from sklearn.cluster import HDBSCAN

    if len(vecs) < max(2 * min_size, 6):
        return np.full(len(vecs), -1)
    low = umap.UMAP(n_neighbors=min(15, len(vecs) - 1), n_components=5, min_dist=0.0,
                    metric="cosine", random_state=seed).fit_transform(vecs)
    return HDBSCAN(min_cluster_size=min_size, algorithm="brute", copy=True).fit_predict(low)


def synthesize(llm: LLM, side: str, bullets: list[str], vecs: np.ndarray,
               groups: list[list[int]]) -> list[dict]:
    """Candidate concepts in each cluster; a mixed cluster gives several."""
    what = PROMPTS[side]["what"]
    fmt = obj({"concepts": arr(obj({"feature": {"type": "string"}, what: {"type": "string"},
                                    "name": {"type": "string"}, "criterion": {"type": "string"},
                                    "points": arr({"type": "integer"})}))})
    shown = []
    for members in groups:
        centre = vecs[members].mean(axis=0)
        shown.append(sorted(members, key=lambda i: -float(vecs[i] @ centre))[:SHOWN])
    got = llm.run([Req(PROMPTS[side]["synthesize"],
                       "Points:\n" + "\n".join(f"{j}. {bullets[i]}" for j, i in enumerate(s, 1)),
                       fmt, "strong") for s in shown], label="synthesize")
    out = []
    for s, answer in zip(shown, got):
        for c in answer["concepts"]:
            own = sorted({s[n - 1] for n in c["points"] if 1 <= n <= len(s)})
            if len(own) >= 2:
                out.append(dict(name=c["name"].strip(), criterion=c["criterion"].strip(), built_from=own,
                                kind="issue", status="live", scores={}))
    return out


# --- 3b. screen -----------------------------------------------------------------

def same(llm: LLM, side: str, a: dict, b: dict) -> bool:
    fmt = obj({"answer": enum("same", "different")})
    pair = f"1. {a['name']}: {a['criterion']}\n2. {b['name']}: {b['criterion']}"
    return llm.chat(PROMPTS[side]["confirm"], pair, fmt)["answer"] == "same"


def screen(llm: LLM, side: str, new: list[dict], frozen: list[dict], join: float) -> None:
    from ..embed.encoder import encode

    fmt = obj({"answer": enum("specific", "broad", "general")})
    verdicts = llm.run([Req(PROMPTS[side]["breadth"], f"{c['name']}: {c['criterion']}", fmt)
                        for c in new], label="breadth")
    for c, v in zip(new, verdicts):
        if v["answer"] == "broad":
            c["status"] = "broad"
        elif v["answer"] == "general":
            c["kind"] = "general"
    # Checked against general groups too: their points stay in the leftover pool
    # (a specific issue may still form from them), so they are proposed again.
    # The same/different calls stay live: each depends on the one before.
    issues = frozen
    if not issues:
        return
    fvec = encode([f"{f['name']}. {f['criterion']}" for f in issues], show_progress=False)
    for c in new:
        if c["status"] != "live":
            continue
        sims = fvec @ encode([f"{c['name']}. {c['criterion']}"], show_progress=False)[0]
        for k in np.argsort(-sims):
            if sims[k] < join:
                break
            if same(llm, side, issues[k], c):
                c["status"], c["merged_into"] = "joined", issues[k]["concept_id"]
                break


# --- 2, 3c. score and select ------------------------------------------------------

def score_many(llm: LLM, side: str, jobs: list[tuple[dict, list[int]]], bullets: list[str],
               batch: int, compact: bool) -> list[dict[int, float]]:
    """Scores for each (concept, points) job, all in one `run` (one batch with the Batch API)."""
    plan, reqs = [], []
    for k, (c, which) in enumerate(jobs):
        system = PROMPTS[side]["score"] + (P.COMPACT if compact else "")
        system = system.format(name=c["name"], criterion=c["criterion"])
        for s in range(0, len(which), batch):
            chunk = which[s:s + batch]
            if compact:
                fmt = obj({"answers": dict(arr(enum(*SCALE)), minItems=len(chunk), maxItems=len(chunk))})
            else:
                fmt = obj({"scores": arr(obj({"n": {"type": "integer"}, "answer": enum(*SCALE)}))})
            listing = "\n".join(f"{j}. {bullets[i]}" for j, i in enumerate(chunk, 1))
            reqs.append(Req(system, f"Points:\n{listing}", fmt))
            plan.append((k, chunk))
    out: list[dict[int, float]] = [{} for _ in jobs]
    for (k, chunk), answer in zip(plan, llm.run(reqs, label="score")):
        if compact:
            got = dict(enumerate(answer["answers"], 1))
        else:
            got = {g["n"]: g["answer"] for g in answer["scores"]}
        for j, i in enumerate(chunk, 1):
            out[k][i] = SCALE.get(got.get(j, "E"), 0.0)   # unanswered: no match
    return out


def nearest_sets(vecs: np.ndarray, universe: list[int], peers: list[dict], k: int) -> list[set[int]]:
    """For each peer concept, the points (of universe) that have it among their k nearest
    concepts. Peers are every concept in play: the live ones and this round's candidates."""
    from ..embed.encoder import encode

    cv = encode([f"{c['name']}. {c['criterion']}" for c in peers], show_progress=False)
    near = np.argsort(-(vecs[universe] @ cv.T), axis=1)[:, :k]
    out: list[set[int]] = [set() for _ in peers]
    for row, i in enumerate(universe):
        for j in near[row]:
            out[j].add(i)
    return out


def select(new: list[dict], frozen_hits: list[set[int]], hits: list[set[int]], n: int,
           overlap_cost: float, concept_cost: float) -> list[bool]:
    """Which new concepts to keep: maximise covered points - overlap_cost * repeated
    matches - concept_cost * concepts kept, with the frozen concepts fixed in."""
    from scipy.optimize import Bounds, LinearConstraint, milp

    k = len(new)
    if not k:
        return []
    covered = set().union(*frozen_hits) if frozen_hits else set()
    cost = np.concatenate([[overlap_cost * len(h) + concept_cost for h in hits],
                           np.full(n, -(1 + overlap_cost))])
    A = np.zeros((n, k + n))
    for j, h in enumerate(hits):
        for i in h:
            A[i, j] = -1.0
    A[np.arange(n), k + np.arange(n)] = 1.0
    ub = np.array([1.0 if i in covered else 0.0 for i in range(n)])
    res = milp(cost, constraints=LinearConstraint(A, -np.inf, ub),
               integrality=np.ones(k + n), bounds=Bounds(0, 1))
    if res.x is None:
        raise RuntimeError(f"selection failed: {res.message}")
    return [bool(x > 0.5) for x in res.x[:k]]


def file_areas(llm: LLM, cs: list[dict], areas: dict[str, str]) -> list[str | None]:
    if not areas or not cs:
        return [None] * len(cs)
    listing = "\n".join(f"- {a}: {d}" for a, d in areas.items())
    fmt = obj({"area": enum(*areas)})
    got = llm.run([Req(P.AREA.format(areas=listing), f"{c['name']}: {c['criterion']}", fmt) for c in cs],
                  label="area")
    return [g["area"] for g in got]


def parents(live: list[dict], hits: dict[str, set[int]]) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    issues = [c for c in live if c["kind"] == "issue"]
    for c in issues:
        best, out[c["concept_id"]] = 0.0, None
        b = hits[c["concept_id"]]
        for p in issues:
            a = hits[p["concept_id"]]
            if p is c or len(b) < 3 or len(a) <= len(b):
                continue
            inside = len(a & b) / len(b)
            if inside >= PARENT_INSIDE and len(a & b) / len(a) < PARENT_INSIDE and inside > best:
                best, out[c["concept_id"]] = inside, p["concept_id"]
    return out


# --- the stage ----------------------------------------------------------------------

def window_reviews(store: Store, cfg: IssueConfig) -> tuple[list, str]:
    """Reviews in the window, all star ratings (a 4-star review can hold a complaint)."""
    (newest,) = store.conn.execute("SELECT max(created_at) FROM reviews").fetchone()
    if newest is None:
        return [], ""
    end = datetime.fromisoformat(newest)
    start = (end - timedelta(days=round(cfg.window_months * 30.44))).isoformat()
    rows = store.conn.execute(
        """SELECT r.review_id, COALESCE(t.content_en, r.content) AS text, r.score, r.created_at
             FROM reviews r LEFT JOIN translations t ON t.review_id = r.review_id
            WHERE r.created_at >= ? AND LENGTH(TRIM(r.content)) >= ?
              AND (t.review_id IS NULL OR t.content_en IS NOT NULL)
            ORDER BY r.created_at""", (start, cfg.min_chars)).fetchall()
    return rows, start


def update(store: Store, book: Codebook, llm: LLM, cfg: IssueConfig) -> list[dict]:
    """Distill new reviews, then bring each side's codebook up to date."""
    reviews, start = window_reviews(store, cfg)
    if not reviews:
        print("no reviews in the window")
        return []
    dist = distiller(llm)
    todo = book.undistilled([r["review_id"] for r in reviews], dist)
    print(f"window: {len(reviews)} reviews since {start[:10]}; {len(todo)} to distill ({llm.describe()})")
    text = {r["review_id"]: r["text"] for r in reviews}

    # Saved in slices, so an interrupted run keeps what it distilled (the model's
    # answers are cached either way).
    step = max(llm.cfg.batch_requests if llm.batching else 200, 1)
    for s in range(0, len(todo), step):
        for rid, points in distill(llm, {r: text[r] for r in todo[s:s + step]}).items():
            book.save_points(rid, dist, points)

    ids = {r["review_id"] for r in reviews}
    return [update_side(book, llm, cfg, side, dist, ids, len(reviews), start) for side in cfg.sides]


def update_side(book: Codebook, llm: LLM, cfg: IssueConfig, side: str, dist: str,
                ids: set[str], n_reviews: int, start: str) -> dict:
    from ..embed.encoder import encode

    run = dict(run_id=f"{now()}_{side}_{uuid.uuid4().hex[:6]}", side=side, started_at=now(),
               model=llm.describe(), window_start=start, reviews=n_reviews)
    rows = book.points(side, dist, ids)
    run["points"] = len(rows)
    print(f"\n== {side}: {len(rows)} points")
    if not rows:
        run["finished_at"] = now()
        book.save_run(run)
        return run
    pid = [r["point_id"] for r in rows]
    bullets = [r["bullet"] for r in rows]
    index = {p: i for i, p in enumerate(pid)}
    vecs = encode(bullets, show_progress=False)
    n = len(rows)

    def hits(c: dict) -> set[int]:
        return {i for i, s in c["scores"].items() if s >= cfg.threshold}

    def score(cs: list[dict], universe: list[int], peers: list[dict]) -> None:
        """Score each concept on the points of universe it has no score for yet (or, with
        `nearest`, only those that have it among their nearest peers); store live ones' raw."""
        near = (nearest_sets(vecs, universe, peers, cfg.nearest)
                if cfg.nearest and len(peers) > cfg.nearest else None)
        jobs = []
        for c in cs:
            which = [i for i in universe if i not in c["scores"]]
            if near is not None:
                mine = near[next(j for j, p in enumerate(peers) if p is c)] | set(c.get("built_from", ()))
                which = [i for i in which if i in mine]
            jobs.append((c, which))
        jobs = [(c, w) for c, w in jobs if w]
        for (c, _), got in zip(jobs, score_many(llm, side, jobs, bullets, cfg.batch, cfg.compact_scores)):
            c["scores"].update(got)
            if c.get("concept_id"):
                book.save_scores(c["concept_id"], {pid[i]: s for i, s in got.items()})

    live = []
    for r in book.concepts(side):
        c = dict(r)
        c["scores"] = {index[p]: s for p, s in book.scored(c["concept_id"]).items() if p in index}
        c["built_from"] = []      # carried: no members of its own to force in
        live.append(c)
    print(f"scoring against {len(live)} live concepts")
    score(live, list(range(n)), live)

    def leftovers() -> list[int]:
        issue = [c for c in live if c["kind"] == "issue"]
        hit = [hits(c) for c in issue]
        covered = set().union(*(h for h in hit if len(h) < n / 2)) if issue else set()
        return [i for i in range(n) if i not in covered]

    # Minting works on a fixed random sample of the points, so its cost stops growing
    # with the corpus; what it keeps is then scored on everything.
    sample = (sorted(random.Random(SAMPLE_SEED).sample(range(n), cfg.mint_sample))
              if cfg.mint_sample and n > cfg.mint_sample else list(range(n)))
    if len(sample) < n:
        print(f"minting on a sample of {len(sample)} of {n} points")
    in_sample = set(sample)

    stats = dict(carried=len(live), minted=0, broad=0, joined=0, unselected=0, general=0)
    first = 0 if not live else 1
    for rnd in range(first, cfg.loops + 1):
        pool = [i for i in leftovers() if i in in_sample]
        size = max(cfg.min_cluster_size, round(cfg.min_cluster_share * len(pool)))
        labels = cluster(vecs[pool], size)
        groups = [[pool[i] for i in np.where(labels == lab)[0]] for lab in sorted(set(labels) - {-1})]
        print(f"round {rnd}: {len(pool)} uncovered points -> {len(groups)} clusters (min size {size})")
        if not groups:
            break
        new = synthesize(llm, side, bullets, vecs, groups)
        for c in new:
            c["round"] = rnd
        screen(llm, side, new, live, cfg.join)
        scored = [c for c in new if c["status"] == "live"]
        score(scored, sample, live + scored)

        # Select on the sample: positions in it stand for the points.
        pos = {i: k for k, i in enumerate(sample)}
        cand = [c for c in scored if c["kind"] == "issue"]
        frozen = [{pos[i] for i in hits(c) if i in pos} for c in live if c["kind"] == "issue"]
        keep = select(cand, frozen, [{pos[i] for i in hits(c) if i in pos} for c in cand], len(sample),
                      cfg.overlap_cost, cfg.concept_cost)
        for c, k in zip(cand, keep):
            if not k:
                c["status"] = "unselected"
        kept = [c for c in new if c["status"] == "live"]
        if len(sample) < n:
            score(kept, list(range(n)), live + kept)
        kept_issues = [c for c in kept if c["kind"] == "issue"]
        for c, area in zip(kept_issues, file_areas(llm, kept_issues, cfg.areas)):
            c["area"] = area

        for c in new:
            c["built_from"] = [pid[i] for i in c["built_from"]]
            c["concept_id"] = book.add_concept(side, c, run["run_id"])
            stats[c["status"] if c["status"] != "live" else ("general" if c["kind"] == "general"
                                                               else "minted")] += 1
            if c["status"] == "live":
                book.save_scores(c["concept_id"], {pid[i]: s for i, s in c["scores"].items()})
                live.append(c)
            print(f"  {c['status']:10} {c['kind']:7} {c['concept_id']} {len(hits(c)):4}"
                  f"  {c['name']}" + (f" -> {c['merged_into']}" if c.get("merged_into") else ""))

        if not kept:
            break   # the leftovers are unchanged, so another round would propose the same

    book.set_parents(parents(live, {c["concept_id"]: hits(c) for c in live}))
    covered = n - len(leftovers())
    stats["covered_points"] = covered
    run.update(finished_at=now(), stats=stats)
    book.save_run(run)
    print(f"{side}: {covered}/{n} points ({covered / n:.0%}) under an issue; "
          f"{stats['minted']} new issues, {stats['general']} new general groups, "
          f"{stats['broad']} broad, {stats['joined']} joined, {stats['unselected']} not selected")
    return run


# --- estimate -------------------------------------------------------------------------

# Rates measured in the viability runs (llm-trials.md; trials/runs/sel-v*).
POINTS_PER_REVIEW = 2.6        # complaint 2.2 + praise 0.35
COMPLAINT_SHARE = 0.86         # of points, before any are distilled
POINTS_PER_CLUSTER = 14        # HDBSCAN at min size 4: 268 points -> 19 clusters
CONCEPTS_PER_CLUSTER = 1.1
SCORED_SHARE = 0.85            # candidates past the breadth check and join
KEPT_SHARE = 0.45              # scored candidates the selection keeps
UNCOVERED_SHARE = 0.6          # points left over after a round
CHARS_PER_TOKEN = 4.0
OUT_TOKENS = dict(quotes=60, bullets=45, synthesize=120, breadth=8, area=8)


def estimate(store: Store, book: Codebook, llm: LLM, cfg: IssueConfig) -> float:
    """Print what `update` would call and cost, from the codebook's current state and
    the rates above. A rough guide (about 2x either way), not counting reasoning tokens."""
    reviews, _ = window_reviews(store, cfg)
    if not reviews:
        print("no reviews in the window")
        return 0.0
    dist = distiller(llm)
    ids = {r["review_id"] for r in reviews}
    todo = book.undistilled(list(ids), dist)
    text = {r["review_id"]: r["text"] for r in reviews}
    review_tok = sum(len(text[r]) for r in (todo or ids)) / max(len(todo or ids), 1) / CHARS_PER_TOKEN
    tok = lambda s: len(s) / CHARS_PER_TOKEN   # noqa: E731
    rows: list[tuple[str, float, float, float, str]] = []   # step, calls, in, out, model

    def add(step: str, calls: float, t_in: float, t_out: float, tier: str = "fast") -> None:
        if calls > 0:
            rows.append((step, calls, calls * t_in, calls * t_out, llm.model(tier)))

    add("distill quotes", len(todo), tok(P.DISTILL) + review_tok + 20, OUT_TOKENS["quotes"])
    add("distill bullets", 0.9 * len(todo), tok(P.SUMMARIZE) + review_tok + 60, OUT_TOKENS["bullets"])

    existing = {s: len(book.points(s, dist, ids)) for s in SIDES}
    have = sum(existing.values())
    for side in cfg.sides:
        share = existing[side] / have if have else (COMPLAINT_SHARE if side == "complaint"
                                                    else 1 - COMPLAINT_SHARE)
        fresh = len(todo) * POINTS_PER_REVIEW * share
        n = existing[side] + fresh
        rows_side = book.points(side, dist, ids)
        bullet_tok = (sum(len(r["bullet"]) for r in rows_side) / len(rows_side) / CHARS_PER_TOKEN + 3
                      if rows_side else 12)
        b = cfg.batch
        score_in = tok(PROMPTS[side]["score"]) + 45 + b * bullet_tok
        score_out = 2 * b + 8 if cfg.compact_scores else 11 * b + 6

        def pairs(points: float, concepts: float, among: float) -> float:
            """Point-concept pairs to score, with the nearest filter among `among` peers."""
            if cfg.nearest and among > cfg.nearest:
                return points * cfg.nearest * concepts / among
            return points * concepts

        live = len(book.concepts(side))
        add(f"{side}: score new points on {live} live", pairs(fresh, live, live) / b, score_in, score_out)
        m = min(n, cfg.mint_sample) if cfg.mint_sample else n
        pool = m * (UNCOVERED_SHARE if live else 1.0)
        for rnd in range(0 if not live else 1, cfg.loops + 1):
            clusters = pool / POINTS_PER_CLUSTER
            cands = clusters * CONCEPTS_PER_CLUSTER
            scored = cands * SCORED_SHARE
            kept = scored * KEPT_SHARE
            add(f"{side}: synthesize (round {rnd})", clusters, tok(PROMPTS[side]["synthesize"]) + 25 * bullet_tok,
                OUT_TOKENS["synthesize"], "strong")
            add(f"{side}: breadth (round {rnd})", cands, tok(PROMPTS[side]["breadth"]) + 45, OUT_TOKENS["breadth"])
            add(f"{side}: score candidates (round {rnd})", pairs(m, scored, live + scored) / b, score_in, score_out)
            if m < n:
                add(f"{side}: score kept on the rest (round {rnd})", pairs(n - m, kept, live + kept) / b,
                    score_in, score_out)
            add(f"{side}: area (round {rnd})", kept, 400, OUT_TOKENS["area"])
            live += kept
            pool *= UNCOVERED_SHARE

    total = 0.0
    priced = bool(llm.cfg.prices)
    print(f"estimate for {len(reviews)} reviews in the window, {len(todo)} to distill "
          f"({llm.describe()}):\n")
    print(f"  {'step':48} {'calls':>10} {'tokens in':>13} {'tokens out':>12}" + ("  {:>9}".format("USD") if priced else ""))
    for step, calls, t_in, t_out, model in rows:
        usd = llm.cost(model, t_in, t_out)
        total += usd
        print(f"  {step:48} {calls:10,.0f} {t_in:13,.0f} {t_out:12,.0f}" + (f"  {usd:9.2f}" if priced else ""))
    calls = sum(r[1] for r in rows)
    print(f"\n  {'total':48} {calls:10,.0f}" + (f" {'':26}  {total:9.2f}" if priced else ""))
    if not priced:
        print("\n  (no llm.prices set: token counts only)")
    print("\n  Rough: rates from the viability runs, tokens from character counts; reasoning tokens"
          "\n  (billed as output) are not included. Cached answers would make the real run cheaper.")
    return total
