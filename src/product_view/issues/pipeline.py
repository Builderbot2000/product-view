"""The issue stage: reviews -> points -> issues, kept in a persistent codebook.

The method validated in llm-trials.md ("Viability test", re-run with
selection), after LLooM (Lam et al., CHI 2024):

1. Distill: each review's complaint and praise points, as exact quotes, each
   restated as a short neutral bullet.
2. Score against the codebook: every point is checked against every live
   concept of its side. Earlier concepts never change; new reviews are
   counted against them first.
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
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np

from ..store import Store
from . import prompts as P
from .codebook import Codebook, now
from .llm import LLM, arr, enum, obj

log = logging.getLogger(__name__)

SCALE = {"A": 1.0, "B": 0.75, "C": 0.5, "D": 0.25, "E": 0.0}
SIDES = ("complaint", "praise")
SHOWN = 25          # points shown to synthesize, closest to the cluster centre first
PARENT_INSIDE = 0.8


@dataclass
class IssueConfig:
    window_months: int = 12        # reviews this recent are distilled and grouped
    min_chars: int = 20
    sides: tuple[str, ...] = SIDES
    min_cluster_size: int = 4      # HDBSCAN; validated at 100 reviews a slice
    threshold: float = 0.75        # a score at or above this is a match (B = a clear case)
    loops: int = 1                 # rounds of minting from leftovers per run
    batch: int = 15                # points per scoring call
    nearest: int = 0               # score each point only against its N nearest concepts (0: all)
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

def distill_review(llm: LLM, text: str) -> list[dict]:
    quote_fmt = obj({"points": arr(obj({"quote": {"type": "string"},
                                        "kind": enum("complaint", "praise")}))})
    bullet_fmt = obj({"bullets": arr(obj({"n": {"type": "integer"}, "bullet": {"type": "string"}}))})
    points = [p for p in llm.chat(P.DISTILL, f"Review:\n{text}", quote_fmt)["points"]
              if p["quote"].strip()]
    if not points:
        return []
    listing = "\n".join(f"{j}. \"{p['quote']}\"" for j, p in enumerate(points, 1))
    got = llm.chat(P.SUMMARIZE, f"Review:\n{text}\n\nQuotes:\n{listing}", bullet_fmt)["bullets"]
    by_n = {b["n"]: b["bullet"] for b in got}
    return [dict(seq=j, side=p["kind"], quote=p["quote"], exact=_norm(p["quote"]) in _norm(text),
                 bullet=by_n.get(j) or p["quote"])
            for j, p in enumerate(points, 1)]


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
               members: list[int]) -> list[dict]:
    """Candidate concepts in one cluster; a mixed cluster gives several."""
    what = PROMPTS[side]["what"]
    fmt = obj({"concepts": arr(obj({"feature": {"type": "string"}, what: {"type": "string"},
                                    "name": {"type": "string"}, "criterion": {"type": "string"},
                                    "points": arr({"type": "integer"})}))})
    centre = vecs[members].mean(axis=0)
    shown = sorted(members, key=lambda i: -float(vecs[i] @ centre))[:SHOWN]
    listing = "\n".join(f"{j}. {bullets[i]}" for j, i in enumerate(shown, 1))
    out = []
    for c in llm.chat(PROMPTS[side]["synthesize"], f"Points:\n{listing}", fmt, tier="strong")["concepts"]:
        own = sorted({shown[n - 1] for n in c["points"] if 1 <= n <= len(shown)})
        if len(own) >= 2:
            out.append(dict(name=c["name"].strip(), criterion=c["criterion"].strip(), built_from=own,
                            kind="issue", status="live"))
    return out


# --- 3b. screen -----------------------------------------------------------------

def judge(llm: LLM, side: str, c: dict) -> str:
    fmt = obj({"answer": enum("specific", "broad", "general")})
    return llm.chat(PROMPTS[side]["breadth"], f"{c['name']}: {c['criterion']}", fmt)["answer"]


def same(llm: LLM, side: str, a: dict, b: dict) -> bool:
    fmt = obj({"answer": enum("same", "different")})
    pair = f"1. {a['name']}: {a['criterion']}\n2. {b['name']}: {b['criterion']}"
    return llm.chat(PROMPTS[side]["confirm"], pair, fmt)["answer"] == "same"


def screen(llm: LLM, side: str, new: list[dict], frozen: list[dict], join: float) -> None:
    from ..embed.encoder import encode

    verdicts = llm.map(lambda c: judge(llm, side, c), new)
    for c, v in zip(new, verdicts):
        if v == "broad":
            c["status"] = "broad"
        elif v == "general":
            c["kind"] = "general"
    # Checked against general groups too: their points stay in the leftover pool
    # (a specific issue may still form from them), so they are proposed again.
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

def score_concept(llm: LLM, side: str, c: dict, bullets: list[str], which: list[int],
                  batch: int) -> dict[int, float]:
    fmt = obj({"scores": arr(obj({"n": {"type": "integer"}, "answer": enum(*SCALE)}))})
    system = PROMPTS[side]["score"].format(name=c["name"], criterion=c["criterion"])
    chunks = [which[s:s + batch] for s in range(0, len(which), batch)]

    def one(chunk: list[int]) -> dict[int, float]:
        listing = "\n".join(f"{j}. {bullets[i]}" for j, i in enumerate(chunk, 1))
        got = {g["n"]: g["answer"] for g in llm.chat(system, f"Points:\n{listing}", fmt)["scores"]}
        return {i: SCALE.get(got.get(j, "E"), 0.0) for j, i in enumerate(chunk, 1)}  # unanswered: no match

    out: dict[int, float] = {}
    for part in llm.map(one, chunks):
        out.update(part)
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


def file_area(llm: LLM, c: dict, areas: dict[str, str]) -> str | None:
    if not areas:
        return None
    listing = "\n".join(f"- {a}: {d}" for a, d in areas.items())
    fmt = obj({"area": enum(*areas)})
    return llm.chat(P.AREA.format(areas=listing), f"{c['name']}: {c['criterion']}", fmt)["area"]


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

    # Saved per review, so an interrupted run keeps what it distilled.
    llm.map(lambda rid: book.save_points(rid, dist, distill_review(llm, text[rid])),
            todo, label="distill", every=100)

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

    live = [dict(r) for r in book.concepts(side)]
    hits: dict[str, set[int]] = {}

    def score_into(c: dict) -> None:
        """Score c on the points it has no score for yet; store raw; keep its matches."""
        have = book.scored(c["concept_id"]) if c.get("concept_id") else {}
        known = {index[p]: s for p, s in have.items() if p in index}
        which = [i for i in range(n) if i not in known]
        if cfg.nearest and which:
            cv = encode([f"{x['name']}. {x['criterion']}" for x in live + [c]], show_progress=False)
            near = np.argsort(-(vecs @ cv.T), axis=1)[:, :cfg.nearest]
            mine = len(cv) - 1 if c not in live else live.index(c)
            which = [i for i in which if mine in near[i] or i in c.get("built_from", [])]
        got = score_concept(llm, side, c, bullets, which, cfg.batch) if which else {}
        known.update(got)
        c["scores"] = known
        if c.get("concept_id"):
            book.save_scores(c["concept_id"], {pid[i]: s for i, s in got.items()})
        hits[c.get("concept_id") or id(c)] = {i for i, s in known.items() if s >= cfg.threshold}

    print(f"scoring against {len(live)} live concepts")
    for c in live:
        score_into(c)

    def leftovers() -> list[int]:
        issue = [c for c in live if c["kind"] == "issue"]
        broad = {c["concept_id"] for c in issue if len(hits[c["concept_id"]]) >= n / 2}
        covered = set().union(*(hits[c["concept_id"]] for c in issue if c["concept_id"] not in broad)) \
            if issue else set()
        return [i for i in range(n) if i not in covered]

    stats = dict(carried=len(live), minted=0, broad=0, joined=0, unselected=0, general=0)
    first = 0 if not live else 1
    for rnd in range(first, cfg.loops + 1):
        pool = leftovers()
        labels = cluster(vecs[pool], cfg.min_cluster_size)
        groups = [[pool[i] for i in np.where(labels == lab)[0]] for lab in sorted(set(labels) - {-1})]
        print(f"round {rnd}: {len(pool)} uncovered points -> {len(groups)} clusters")
        if not groups:
            break
        new = [c for cs in llm.map(lambda g: synthesize(llm, side, bullets, vecs, g), groups) for c in cs]
        for c in new:
            c["round"] = rnd
        screen(llm, side, new, live, cfg.join)
        scored = [c for c in new if c["status"] == "live"]
        for c in scored:
            score_into(c)
        cand = [c for c in scored if c["kind"] == "issue"]
        frozen = [hits[c["concept_id"]] for c in live if c["kind"] == "issue"]
        keep = select(cand, frozen, [hits[id(c)] for c in cand], n, cfg.overlap_cost, cfg.concept_cost)
        for c, k in zip(cand, keep):
            if not k:
                c["status"] = "unselected"
        for c in new:
            if c["status"] == "live" and c["kind"] == "issue":
                c["area"] = file_area(llm, c, cfg.areas)
            c["built_from"] = [pid[i] for i in c["built_from"]]
            c["concept_id"] = book.add_concept(side, c, run["run_id"])
            stats[c["status"] if c["status"] != "live" else ("general" if c["kind"] == "general"
                                                               else "minted")] += 1
            if c["status"] == "live":
                book.save_scores(c["concept_id"], {pid[i]: s for i, s in c["scores"].items()})
                hits[c["concept_id"]] = hits.pop(id(c))
                live.append(c)
            print(f"  {c['status']:10} {c['kind']:7} {c['concept_id']} {len(hits.get(c['concept_id'], ())):4}"
                  f"  {c['name']}" + (f" -> {c['merged_into']}" if c.get("merged_into") else ""))

        if not any(c["status"] == "live" for c in new):
            break   # the leftovers are unchanged, so another round would propose the same

    book.set_parents(parents(live, hits))
    covered = n - len(leftovers())
    stats["covered_points"] = covered
    run.update(finished_at=now(), stats=stats)
    book.save_run(run)
    print(f"{side}: {covered}/{n} points ({covered / n:.0%}) under an issue; "
          f"{stats['minted']} new issues, {stats['general']} new general groups, "
          f"{stats['broad']} broad, {stats['joined']} joined, {stats['unselected']} not selected")
    return run
