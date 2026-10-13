"""Spike: the LLooM design (llm-trials.md, "Design as it stands") end to end on a local model.

Distill (exact quotes tagged complaint/praise, then one neutral bullet per
quote) -> Cluster (embed, UMAP, HDBSCAN; outliers stay unassigned) ->
Synthesize (name + inclusion criterion per cluster) -> Review (merge
redundant concepts, mark general-opinion ones) -> Score (every bullet against
every concept, or its nearest concepts) -> Loop (unmatched bullets go round
again). Concepts are written to concepts.json with stable ids.

Every model call goes through chat() and is cached by its full request, so a
stopped run resumes and a repeated run is free. Output goes to
out/llm-spike/lloom-<tag>/: concepts.json, bullets.jsonl and report.md.

    .venv/Scripts/python.exe -X utf8 spike/lloom.py --n 200
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sqlite3
import time
import urllib.request
from collections import Counter
from pathlib import Path

import numpy as np

from product_view.embed.encoder import encode

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out" / "llm-spike"
OLLAMA = "http://127.0.0.1:11434/api/chat"
SCALE = {"A": 1.0, "B": 0.75, "C": 0.5, "D": 0.25, "E": 0.0}

DISTILL = """You read Google Play reviews of a mobile app and pull out every point the reviewer makes about the app: each complaint and each piece of praise.

Rules:
- Copy each point as an exact quote from the review: the shortest run of consecutive words that still makes sense on its own. Do not reword, fix spelling or translate.
- One entry per distinct point. Keep a complaint whole: a cause with its effect, an error message with the action that triggered it.
- Tag each entry "complaint" (something wrong, missing or disliked, sarcasm included) or "praise" (something that works or is liked).
- Include general opinions too ("worst app ever", "love it"); a later step sorts specific from general.
- Return an empty list if the review makes no point about the app.

Example from another domain. Review: "Love the restaurant choice but the driver map freezes every time and support never answers. 2 stars"
-> {"quote": "Love the restaurant choice", "kind": "praise"}, {"quote": "the driver map freezes every time", "kind": "complaint"}, {"quote": "support never answers", "kind": "complaint"}"""

SUMMARIZE = """You rewrite points quoted from a review of a mobile app as short neutral bullets.

For each numbered quote, write one bullet of 4-10 words that says what the point is about and what happens, in plain neutral words. Drop tone, insults and sarcasm. Use the review for context (what "it" refers to) but add nothing it does not say. Write in English.

Examples from another domain:
- "the driver map freezes every time" -> "driver tracking map freezes"
- "support never answers" -> "support does not respond to messages"
- "Love the restaurant choice" -> "wide choice of restaurants"
- "worst app ever lol" -> "general dislike of the app\""""

SYNTHESIZE = """You find the specific problems in a group of points taken from reviews of a mobile app.

You see a numbered list of short points grouped because their wording is similar. The grouping is rough: a group often mixes two or three different problems, plus general opinions and one-offs.

Return one concept for each specific problem in the list that two or more points describe. Pitch each concept at the level one product team would own: points about the same feature with the same kind of failure belong together even when the details differ (old phones, tablets and a new phone model are all "app not supported on this device"). Keep different features apart even when the symptom is the same. For each concept:
- feature: the one part of the app it is about: a screen, an action, a setting, or a kind of device (1-4 words). Never "the app" as a whole unless the points are about the app failing to open or run at all.
- failure: the one thing that goes wrong with it (1-6 words).
- name: 2-6 words joining the two, specific enough that a product team knows where to look ("Driver map freezes", not "App problems").
- criterion: one sentence starting "The point says" that names that feature and that failure. Do not join different features or failures with "or" to cover more points.
- points: the numbers of every point that describes this problem.
Leave out general opinions, feelings and one-offs; they are handled later. Return an empty list only if the points are all general opinions or all different.

Example from another domain. Points: 1. driver map freezes 2. map stops updating during delivery 3. app crashes at checkout 4. live tracking map never loads 5. terrible service 6. checkout crashes when paying by card 7. app closes when I tap pay
-> {"feature": "driver map", "failure": "freezes or stops updating", "name": "Driver map freezes", "criterion": "The point says the live map tracking the driver freezes, stops updating or never loads.", "points": [1, 2, 4]}
-> {"feature": "checkout", "failure": "app crashes", "name": "Checkout crashes on payment", "criterion": "The point says the app crashes or closes while the user is paying at checkout.", "points": [3, 6, 7]}
(5 is a general opinion and is left out.)
Points: 1. app won't run on my old phone 2. not available for my tablet 3. doesn't support the new Pixel 4. app says device not compatible
-> one concept: {"feature": "device support", "failure": "app not supported", "name": "App not supported on some devices", "criterion": "The point says the app does not install, run or appear as available on the user's phone, tablet or device model.", "points": [1, 2, 3, 4]}"""

REVIEW = """You tidy a list of concepts found in reviews of a mobile app. Each concept has an id, a name, an inclusion criterion and the number of points it was built from.

Return:
- merge: groups of ids that are duplicates: the same feature with the same failure, worded differently. For each group, state the one feature and the one failure they share. If you cannot name a single shared feature and a single shared failure, they are not duplicates. Concepts that share only a symptom (both crash, both show an error, both loop) but are about different features, devices or steps are not duplicates. Never merge a specific concept into a broad one. Different actions are different features even when both involve the same step (sending money and setting up a device are different, even if both ask for verification). A narrower case of the same failure on the same feature is a duplicate (the back of a card failing to scan is a case of card scanning failing).
- general: ids of concepts that are only a general opinion of the app, the company or its service, naming no specific feature, screen, action or fault ("app is bad", "general dissatisfaction", "great app"). A concept that names a fault (not supported, cannot install, does not connect) is never general.
Leave everything else alone. Empty lists are fine.

Examples from another domain:
- "Driver map freezes" and "Live tracking stops updating" -> merge (feature: driver map; failure: stops updating)
- "Driver map freezes" and "App crashes at checkout" -> do not merge (different features, shared symptom)
- "App crashes on older phones" and "App crashes at checkout" -> do not merge (a device problem and a checkout problem)
- "Promo codes rejected" and "App does not work properly" -> do not merge (specific into broad)
- "Menu photos fail to load" and "Dish photos missing on some restaurants" -> merge (feature: menu photos; failure: do not load)
- "Terrible delivery service" -> general"""

CONFIRM = """You check whether two concepts found in reviews of a mobile app are duplicates.

They are duplicates only if they are about the same feature (the same screen, action, setting or kind of device) and the same kind of failure. Different actions are different features even when both involve the same step, such as a verification check. Sharing a symptom (both crash, both show an error) is not enough.

Examples from another domain:
- "Driver map freezes" / "Live tracking stops updating" -> same
- "Promo codes rejected" / "Card payment declined at checkout" -> different (both at checkout, different features)
- "Driver map freezes" / "App crashes at checkout" -> different"""

BREADTH = """You judge one concept found in reviews of a mobile app. Pick one answer:
specific: it names one feature (a screen, an action, a setting, a kind of device or connection, or the app failing to open or run at all) and one kind of failure, so one product team would know where to look. Two wordings of the same failure joined by "or" are still specific ("fails or is blocked", "freezes or stops updating").
broad: it names no single feature (the app as a whole is buggy, slow, has errors, malfunctions or does not work), or it joins two different features ("checkout or tracking").
general: a feeling or opinion (frustration, annoyance, embarrassment, regret, distrust) about the app, a process, the company or its service, naming no fault; or the quality of customer support.

Examples from another domain:
- "Driver map freezes": the point says the live driver map freezes or stops updating -> specific
- "Promo code rejected or not applied": the point says a promo code is refused or has no effect at checkout -> specific
- "App crashes on startup": the point says the app closes as soon as it is opened -> specific
- "App is buggy and slow": the point says the app has bugs, errors or performance problems -> broad
- "App shows errors and crashes": the point says the app crashes or shows error messages, with no screen or action named -> broad
- "App still broken after reinstalling": the point says reinstalling did not fix the app -> broad
- "Checkout or tracking fails": the point says checkout fails or the driver map does not load -> broad
- "Checkout is frustrating": the point says paying is annoying or stressful -> general
- "Support is unhelpful": the point says support staff do not solve the problem -> general"""

SCORE = """You check points taken from reviews of a mobile app against one concept.

Concept: {name}
Criterion: {criterion}

For each numbered point, pick one answer:
A: the point is about the feature in the criterion and describes the failure in the criterion.
B: the point describes a clear case of it in other words (a named device for a device problem, a named step of the same action).
C: a near miss: the same feature with a different failure, or the same failure (crash, error, loop) on a different feature.
D: about something else.
E: a general opinion or feeling that names no specific feature or fault.
Judge only what the point says. Sharing a word or a symptom is not enough: a crash while scanning an ID is C for a concept about crashes on older phones."""


class Model:
    """One door to the model, with a cache keyed by the full request."""

    def __init__(self, model: str, cache: Path):
        self.model, self.path = model, cache
        self.cache = {}
        if cache.exists():
            for line in cache.open(encoding="utf-8"):
                row = json.loads(line)
                self.cache[row["key"]] = row["out"]
        self.calls = self.hits = 0
        self.seconds = 0.0

    def chat(self, system: str, user: str, schema: dict) -> dict:
        key = hashlib.sha256(json.dumps([self.model, system, user, schema]).encode()).hexdigest()
        if key in self.cache:
            self.hits += 1
            return self.cache[key]
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "format": schema,
            "stream": False,
            "think": False,
            "options": {"temperature": 0, "seed": 0},
        }
        t0 = time.time()
        req = urllib.request.Request(OLLAMA, json.dumps(body).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=600) as resp:
            out = json.loads(json.loads(resp.read())["message"]["content"])
        self.seconds += time.time() - t0
        self.calls += 1
        self.cache[key] = out
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"key": key, "out": out}, ensure_ascii=False) + "\n")
        return out


def obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props)}


def arr(item: dict) -> dict:
    return {"type": "array", "items": item}


def sample(n: int, negative_only: bool, month: str | None = None, seed: int = 0) -> list[dict]:
    """The newest n reviews, or with `month` (YYYY-MM) n picked at random from that month."""
    db = sqlite3.connect(ROOT / "data" / "reviews.db")
    db.execute("ATTACH ? AS cache", (str(ROOT / "data" / "cache.db"),))
    rows = db.execute(
        f"""SELECT r.review_id, COALESCE(t.content_en, r.content), r.score, r.created_at
            FROM reviews r LEFT JOIN cache.translations t USING (review_id)
            WHERE length(r.content) >= 20 {"AND r.score <= 3" if negative_only else ""}
            {"AND substr(r.created_at, 1, 7) = ?" if month else ""}
            ORDER BY r.created_at DESC {"" if month else "LIMIT ?"}""",
        (month,) if month else (n,),
    ).fetchall()
    if month and len(rows) > n:
        rows = sorted(random.Random(seed).sample(rows, n), key=lambda r: r[3], reverse=True)
    return [dict(review_id=a, text=b, score=c, created_at=d) for a, b, c, d in rows]


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


# ---- Distill -------------------------------------------------------------

def distill(m: Model, reviews: list[dict]) -> list[dict]:
    quote_fmt = obj({"points": arr(obj({"quote": {"type": "string"},
                                        "kind": {"type": "string", "enum": ["complaint", "praise"]}}))})
    bullet_fmt = obj({"bullets": arr(obj({"n": {"type": "integer"}, "bullet": {"type": "string"}}))})
    bullets = []
    t0 = time.time()
    for i, r in enumerate(reviews, 1):
        points = [p for p in m.chat(DISTILL, f"Review:\n{r['text']}", quote_fmt)["points"] if p["quote"].strip()]
        if points:
            listing = "\n".join(f"{j}. \"{p['quote']}\"" for j, p in enumerate(points, 1))
            got = m.chat(SUMMARIZE, f"Review:\n{r['text']}\n\nQuotes:\n{listing}", bullet_fmt)["bullets"]
            by_n = {b["n"]: b["bullet"] for b in got}
            for j, p in enumerate(points, 1):
                bullets.append(dict(
                    id=f"{r['review_id']}#{j}", review_id=r["review_id"], score=r["score"],
                    kind=p["kind"], quote=p["quote"], exact=norm(p["quote"]) in norm(r["text"]),
                    bullet=by_n.get(j) or p["quote"],
                ))
        if i % 25 == 0 or i == len(reviews):
            print(f"  distill {i}/{len(reviews)}  {time.time() - t0:.0f}s")
    return bullets


# ---- Cluster -------------------------------------------------------------

def cluster(vecs: np.ndarray, min_size: int) -> np.ndarray:
    """UMAP to 5 dimensions, then HDBSCAN. -1 = outlier, left unassigned."""
    import umap
    from sklearn.cluster import HDBSCAN

    if len(vecs) < max(2 * min_size, 6):
        return np.full(len(vecs), -1)
    low = umap.UMAP(n_neighbors=min(15, len(vecs) - 1), n_components=5, min_dist=0.0,
                    metric="cosine", random_state=42).fit_transform(vecs)
    return HDBSCAN(min_cluster_size=min_size, algorithm="brute").fit_predict(low)


# ---- Synthesize / Review -------------------------------------------------

class Concepts:
    def __init__(self, slice_: str = ""):
        self.items: list[dict] = []
        self.slice = slice_

    def live(self) -> list[dict]:
        return [c for c in self.items if c["status"] == "live"]

    def load(self, path: Path) -> None:
        """Carry an earlier slice's concepts forward: same ids, no members in this slice yet."""
        for c in json.loads(path.read_text(encoding="utf-8")):
            c.pop("matches", None)
            if c["status"] == "live":
                c["carried"], c["frozen"], c["built_from"] = True, True, []
            self.items.append(c)

    def add(self, name, criterion, built_from, rnd, merged_from=()):
        c = dict(id=f"C{len(self.items) + 1:03d}", name=name, criterion=criterion, built_from=sorted(built_from),
                 round=rnd, slice=self.slice, kind="issue", status="live", merged_from=list(merged_from),
                 merged_into=None, carried=False)
        self.items.append(c)
        return c


def synthesize(m: Model, bullets: list[dict], vecs: np.ndarray, members: list[int]) -> list[tuple[str, str, list[int]]]:
    """Concepts in a cluster, largest first, as (name, criterion, members). A mixed cluster gives several."""
    fmt = obj({"concepts": arr(obj({"feature": {"type": "string"}, "failure": {"type": "string"},
                                    "name": {"type": "string"}, "criterion": {"type": "string"},
                                    "points": arr({"type": "integer"})}))})
    centre = vecs[members].mean(axis=0)
    shown = sorted(members, key=lambda i: -float(vecs[i] @ centre))[:25]  # closest to the centre first
    listing = "\n".join(f"{j}. {bullets[i]['bullet']}" for j, i in enumerate(shown, 1))
    out = []
    for c in m.chat(SYNTHESIZE, f"Points:\n{listing}", fmt)["concepts"]:
        own = sorted({shown[n - 1] for n in c["points"] if 1 <= n <= len(shown)})
        if len(own) >= 2:
            out.append((c["name"].strip(), c["criterion"].strip(), own))
    return sorted(out, key=lambda c: -len(c[2]))


def same(m: Model, a: dict, b: dict) -> bool:
    fmt = obj({"answer": {"type": "string", "enum": ["same", "different"]}})
    pair = f"1. {a['name']}: {a['criterion']}\n2. {b['name']}: {b['criterion']}"
    return m.chat(CONFIRM, pair, fmt)["answer"] == "same"


def review(m: Model, concepts: Concepts, bullets, vecs, rnd: int) -> None:
    live = concepts.live()
    if len(live) < 2:
        return
    fmt = obj({"merge": arr(obj({"ids": arr({"type": "string"}), "feature": {"type": "string"},
                                 "failure": {"type": "string"}})),
               "general": arr({"type": "string"})})
    if all(c.get("carried") for c in live):
        return
    listing = "\n".join(f"{c['id']} | {c['name']} | {c['criterion']} | "
                        + ("earlier" if c.get("carried") else f"{len(c['built_from'])} points") for c in live)
    got = m.chat(REVIEW, f"Concepts:\n{listing}", fmt)
    by_id = {c["id"]: c for c in live}
    for cid in got["general"]:
        if cid in by_id and not by_id[cid].get("carried"):
            by_id[cid]["kind"] = "general"
    used = set()
    for group in got["merge"]:
        group = [g for g in dict.fromkeys(group["ids"]) if g in by_id and g not in used]
        old = [g for g in group if by_id[g].get("carried")]
        if old:
            # a new concept may join an earlier one, which keeps its id and wording; earlier ones never merge
            anchor = old[0]
            for g in group:
                if not by_id[g].get("carried") and same(m, by_id[anchor], by_id[g]):
                    by_id[g]["status"], by_id[g]["merged_into"] = "merged", anchor
                    used.add(g)
            continue
        if len(group) < 2:
            continue
        # one yes/no call per proposed member against the largest concept in the group
        anchor = max(group, key=lambda g: len(by_id[g]["built_from"]))
        group = [anchor] + [g for g in group if g != anchor and same(m, by_id[anchor], by_id[g])]
        if len(group) < 2:
            continue
        used.update(group)
        members = sorted({i for g in group for i in by_id[g]["built_from"]})
        named = synthesize(m, bullets, vecs, members)
        if not named:
            continue
        name, crit, _ = named[0]
        new = concepts.add(name, crit, members, rnd, merged_from=group)
        if all(by_id[g]["kind"] == "general" for g in group):
            new["kind"] = "general"
        for g in group:
            by_id[g]["status"], by_id[g]["merged_into"] = "merged", new["id"]


# ---- Score ---------------------------------------------------------------

def score(m: Model, c: dict, bullets: list[dict], which: list[int], batch: int) -> dict[int, float]:
    fmt = obj({"scores": arr(obj({"n": {"type": "integer"},
                                  "answer": {"type": "string", "enum": list(SCALE)}}))})
    system = SCORE.format(name=c["name"], criterion=c["criterion"])
    out = {}
    for s in range(0, len(which), batch):
        chunk = which[s:s + batch]
        listing = "\n".join(f"{j}. {bullets[i]['bullet']}" for j, i in enumerate(chunk, 1))
        got = {g["n"]: g["answer"] for g in m.chat(system, f"Points:\n{listing}", fmt)["scores"]}
        for j, i in enumerate(chunk, 1):
            out[i] = SCALE.get(got.get(j, "E"), 0.0)  # an unanswered point counts as no match
    return out


def score_all(m, concepts, bullets, vecs, scores, args) -> None:
    """Fill scores[cid] for every live concept that has none yet."""
    todo = [c for c in concepts.live() if c["id"] not in scores]
    if not todo:
        return
    cvecs = {c["id"]: encode([f"{c['name']}. {c['criterion']}"], show_progress=False)[0] for c in concepts.live()}
    t0 = time.time()
    for k, c in enumerate(todo, 1):
        if args.nearest:
            # each bullet is scored only against its `nearest` closest live concepts (plus its own cluster)
            ids = list(cvecs)
            mat = np.stack([cvecs[i] for i in ids])
            near = np.argsort(-(vecs @ mat.T), axis=1)[:, :args.nearest]
            col = ids.index(c["id"])
            which = sorted({i for i in range(len(bullets)) if col in near[i]} | set(c["built_from"]))
        else:
            which = list(range(len(bullets)))
        got = score(m, c, bullets, which, args.batch)
        scores[c["id"]] = [got.get(i) for i in range(len(bullets))]
        print(f"  score {k}/{len(todo)} {c['id']} {c['name']!r}: "
              f"{sum(1 for v in got.values() if v >= args.threshold)} match  {time.time() - t0:.0f}s")


def merge_overlaps(m, concepts, bullets, vecs, scores, args, rnd) -> None:
    """Merge issue concepts whose matches mostly coincide (trial 13, fault 1).

    Two new concepts are named together and the result is scored afresh. When one is
    carried from an earlier slice it keeps its id and wording and takes the other's matches.
    """
    while True:
        issue = [c for c in concepts.live() if c["kind"] == "issue" and c["id"] in scores]
        hit = {c["id"]: matches(scores, c["id"], args.threshold) for c in issue}
        best = None
        for x, a in enumerate(issue):
            for b in issue[x + 1:]:
                ha, hb = hit[a["id"]], hit[b["id"]]
                small = min(len(ha), len(hb))
                if small < 3 or (a.get("carried") and b.get("carried")):
                    continue
                r = len(ha & hb) / small
                if r >= args.overlap and (best is None or r > best[0]):
                    best = (r, a, b)
        if best is None:
            return
        r, a, b = best
        keep = a if a.get("carried") else b if b.get("carried") else None
        if keep is not None:
            gone = b if keep is a else a
            scores[keep["id"]] = [max(x or 0.0, y or 0.0) for x, y in zip(scores[keep["id"]], scores[gone["id"]])]
            gone["status"], gone["merged_into"] = "merged", keep["id"]
            print(f"  overlap {r:.0%}: {gone['id']} {gone['name']!r} -> {keep['id']} {keep['name']!r} (carried)")
            continue
        union = sorted(hit[a["id"]] | hit[b["id"]])
        named = synthesize(m, bullets, vecs, union)
        if not named:
            # nothing nameable in common: the larger keeps the shared points
            a, b = sorted((a, b), key=lambda c: -len(hit[c["id"]]))
            scores[b["id"]] = [None if i in hit[a["id"]] else v for i, v in enumerate(scores[b["id"]])]
            print(f"  overlap {r:.0%}: {b['id']} cedes shared points to {a['id']}")
            continue
        name, crit, _ = named[0]
        new = concepts.add(name, crit, union, rnd, merged_from=[a["id"], b["id"]])
        for g in (a, b):
            g["status"], g["merged_into"] = "merged", new["id"]
        print(f"  overlap {r:.0%}: {a['id']} {a['name']!r} + {b['id']} {b['name']!r} -> {new['id']} {name!r}")
        score_all(m, concepts, bullets, vecs, scores, args)


def leftovers(concepts, scores, bullets, args) -> list[int]:
    """Loop: bullets with no issue match, or matching only issue concepts that cover half the data."""
    issue = [c for c in concepts.live() if c["kind"] == "issue"]
    hit = {c["id"]: matches(scores, c["id"], args.threshold) for c in issue}
    broad = {cid for cid, h in hit.items() if len(h) >= len(bullets) / 2}
    return [i for i in range(len(bullets)) if not any(i in h for cid, h in hit.items() if cid not in broad)]


# ---- Select (GoalEx), frozen codebook, subsumption -------------------------

def judge(m: Model, c: dict) -> str:
    fmt = obj({"answer": {"type": "string", "enum": ["specific", "broad", "general"]}})
    return m.chat(BREADTH, f"{c['name']}: {c['criterion']}", fmt)["answer"]


def screen(m, concepts, new: list[dict], args) -> None:
    """Breadth check, then the frozen-codebook join: a new concept that means the same as a
    frozen one is dropped (its points were already scored against the frozen one). Shared
    points never merge anything (BERTopic merge_models; a codebook changes only by revision)."""
    frozen = [c for c in concepts.live() if c.get("frozen") and c["kind"] == "issue"]
    fvec = encode([f"{c['name']}. {c['criterion']}" for c in frozen], show_progress=False) if frozen else None
    for c in new:
        verdict = judge(m, c)
        if verdict == "broad":
            c["status"] = "broad"
            continue
        if verdict == "general":
            c["kind"] = "general"
            continue
        if fvec is None:
            continue
        sims = fvec @ encode([f"{c['name']}. {c['criterion']}"], show_progress=False)[0]
        for k in np.argsort(-sims):
            if sims[k] < args.join:
                break
            if same(m, frozen[k], c):
                c["status"], c["merged_into"] = "joined", frozen[k]["id"]
                break
    for c in new:
        if c["status"] != "live":
            print(f"  {c['status']}: {c['id']} {c['name']!r}" + (f" -> {c['merged_into']}" if c["merged_into"] else ""))


def select(concepts, new: list[dict], scores, n: int, args) -> None:
    """Pick the new issue concepts that cover most bullets with least overlap (GoalEx, Wang et al. 2023).

    maximise  covered - overlap_cost * (assignments - covered) - concept_cost * chosen,
    with frozen concepts fixed in. An overlapping concept loses to the one it repeats.
    """
    from scipy.optimize import Bounds, LinearConstraint, milp

    cand = [c for c in new if c["status"] == "live" and c["kind"] == "issue"]
    if not cand:
        return
    fixed = [c for c in concepts.live() if c.get("frozen") and c["kind"] == "issue"]
    covered = set().union(*(matches(scores, c["id"], args.threshold) for c in fixed)) if fixed else set()
    hit = [matches(scores, c["id"], args.threshold) for c in cand]
    k, lam, mu = len(cand), args.overlap_cost, args.concept_cost
    # variables: x_j (choose concept j), then y_i (bullet i covered)
    cost = np.concatenate([[lam * len(h) + mu for h in hit], np.full(n, -(1 + lam))])
    A = np.zeros((n, k + n))
    for j, h in enumerate(hit):
        for i in h:
            A[i, j] = -1.0
    A[np.arange(n), k + np.arange(n)] = 1.0
    ub = np.array([1.0 if i in covered else 0.0 for i in range(n)])  # y_i <= sum x_j (+1 if already covered)
    res = milp(cost, constraints=LinearConstraint(A, -np.inf, ub), integrality=np.ones(k + n),
               bounds=Bounds(0, 1))
    chosen = res.x[:k] > 0.5
    for c, keep, h in zip(cand, chosen, hit):
        if keep:
            c["frozen"] = True
        else:
            c["status"] = "unselected"
        print(f"  {'select' if keep else 'drop  '} {c['id']} {len(h):3} {c['name']!r}")


def subsume(concepts, scores, args) -> None:
    """Parent links where one concept's matches contain most of another's (Sanderson & Croft 1999)."""
    issue = [c for c in concepts.live() if c["kind"] == "issue"]
    hit = {c["id"]: matches(scores, c["id"], args.threshold) for c in issue}
    for c in issue:
        c["parent"] = None
        best = 0.0
        for p in issue:
            a, b = hit[p["id"]], hit[c["id"]]
            if p is c or len(b) < 3 or len(a) <= len(b):
                continue
            inside = len(a & b) / len(b)
            if inside >= 0.8 and len(a & b) / len(a) < 0.8 and inside > best:
                best, c["parent"] = inside, p["id"]


# ---- Report --------------------------------------------------------------

def matches(scores, cid, threshold):
    return {i for i, v in enumerate(scores[cid]) if v is not None and v >= threshold}


def report(concepts, bullets, scores, args, m, elapsed) -> str:
    live = concepts.live()
    issue = [c for c in live if c["kind"] == "issue"]
    general = [c for c in live if c["kind"] == "general"]
    hit = {c["id"]: matches(scores, c["id"], args.threshold) for c in live}
    n = len(bullets)
    any_issue = set().union(*(hit[c["id"]] for c in issue)) if issue else set()
    any_general = set().union(*(hit[c["id"]] for c in general)) if general else set()
    per_bullet = Counter(i for c in issue for i in hit[c["id"]])
    rids = {b["review_id"] for b in bullets}
    rids_hit = {bullets[i]["review_id"] for i in any_issue}

    L = [f"# LLooM spike: {args.side}s, {args.tag}", ""]
    L += [f"- Model `{args.model}`; {m.calls} calls made, {m.hits} from cache, {m.seconds / 60:.1f} min in the model; "
          f"wall {elapsed / 60:.1f} min",
          f"- Scoring: {'nearest ' + str(args.nearest) if args.nearest else 'every bullet against every concept'}, "
          f"threshold {args.threshold}, HDBSCAN min size {args.min_size}, loops {args.loops}",
          f"- {n} {args.side} bullets from {len(rids)} reviews",
          f"- **Coverage:** {len(any_issue)} bullets ({len(any_issue) / max(n, 1):.0%}) match an issue concept; "
          f"{len(any_general - any_issue)} match only a general concept; "
          f"{n - len(any_issue | any_general)} match nothing",
          f"- Reviews with at least one issue match: {len(rids_hit)} of {len(rids)}",
          f"- Bullets matching 2+ issue concepts: {sum(1 for v in per_bullet.values() if v >= 2)}",
          f"- {len(issue)} issue concepts, {len(general)} general, "
          f"{sum(1 for c in concepts.items if c['status'] == 'merged')} merged away", ""]

    L += ["## Issue concepts", "",
          "Self-fit = share of the cluster the concept was built from that scores as a match on it. "
          "Low self-fit means the cluster was a grab-bag.", ""]
    for c in sorted(issue, key=lambda c: -len({bullets[i]['review_id'] for i in hit[c['id']]})):
        h = hit[c["id"]]
        self_fit = len(h & set(c["built_from"])) / max(len(c["built_from"]), 1)
        nrev = len({bullets[i]["review_id"] for i in h})
        L.append(f"### {c['id']} {c['name']} — {nrev} reviews")
        L.append(f"*{c['criterion']}*  ")
        L.append(f"Round {c['round']}; built from {len(c['built_from'])}, matched {len(h)}, self-fit {self_fit:.0%}"
                 + (f"; merged from {', '.join(c['merged_from'])}" if c["merged_from"] else ""))
        L.append("")
        for i in sorted(h, key=lambda i: -scores[c["id"]][i])[:6]:
            L.append(f"- {bullets[i]['bullet']}  ·  \"{bullets[i]['quote'][:120]}\" ({bullets[i]['score']}★)")
        misfits = [i for i in c["built_from"] if i not in h]
        if misfits:
            L.append(f"- *built from but not matched:* " + "; ".join(bullets[i]["bullet"] for i in misfits[:6]))
        L.append("")

    L += ["## General concepts", ""]
    for c in general:
        L.append(f"- {c['id']} **{c['name']}** ({len(hit[c['id']])} bullets): {c['criterion']}")
    pairs = Counter()
    for i, k in per_bullet.items():
        if k >= 2:
            on = sorted(c["id"] for c in issue if i in hit[c["id"]])
            pairs.update((a, b) for x, a in enumerate(on) for b in on[x + 1:])
    L += ["", "## Most-shared concept pairs (possible redundancy)", ""]
    name = {c["id"]: c["name"] for c in live}
    for (a, b), k in pairs.most_common(8):
        L.append(f"- {k}: {a} {name[a]} / {b} {name[b]}")
    left = [i for i in range(n) if i not in any_issue | any_general]
    L += ["", f"## Unmatched ({len(left)})", "", "; ".join(bullets[i]["bullet"] for i in left), ""]
    return "\n".join(L)


# ---- Main ----------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200, help="newest N reviews of 20+ characters")
    ap.add_argument("--month", help="YYYY-MM: N reviews at random from this month instead of the newest")
    ap.add_argument("--seed", type=int, default=0, help="random seed for --month")
    ap.add_argument("--prior", type=Path, help="concepts.json of an earlier slice: score against it first, "
                                               "then mint only from the leftovers")
    ap.add_argument("--overlap", type=float, default=0.0,
                    help="merge issue concepts whose matches overlap this share of the smaller (0 = off)")
    ap.add_argument("--name", help="output folder name (default: built from the settings)")
    ap.add_argument("--select", action="store_true",
                    help="replace Review and merging: breadth check, frozen-codebook join, ILP selection")
    ap.add_argument("--join", type=float, default=0.7, help="--select: definition similarity to test a join")
    ap.add_argument("--overlap-cost", type=float, default=1.0, help="--select: cost of each repeated match")
    ap.add_argument("--concept-cost", type=float, default=2.0, help="--select: cost of each concept chosen")
    ap.add_argument("--negative-only", action="store_true", help="only reviews of 3 stars or fewer (sample B)")
    ap.add_argument("--side", choices=["complaint", "praise"], default="complaint")
    ap.add_argument("--model", default="qwen3.5:9b")
    ap.add_argument("--min-size", type=int, default=3, help="HDBSCAN min_cluster_size")
    ap.add_argument("--threshold", type=float, default=0.75, help="score at or above this is a match (B = agree)")
    ap.add_argument("--nearest", type=int, default=0, help="score each bullet against its N nearest concepts only")
    ap.add_argument("--batch", type=int, default=15, help="bullets per scoring call")
    ap.add_argument("--loops", type=int, default=1)
    ap.add_argument("--dry", action="store_true", help="stop after naming and tidying round 0; print the concepts")
    args = ap.parse_args()
    args.tag = (f"n{args.n}{'-neg' if args.negative_only else ''}-m{args.min_size}"
                f"{'-near' + str(args.nearest) if args.nearest else ''}-t{args.threshold}-l{args.loops}")

    if args.month:
        args.tag = f"{args.month}-s{args.seed}-" + args.tag
    if args.overlap:
        args.tag += f"-o{args.overlap}"
    if args.select:
        args.tag += "-select"
    if args.prior:
        args.tag += "-prior"
    out = OUT / (args.name or f"lloom-{args.tag}")
    out.mkdir(parents=True, exist_ok=True)
    m = Model(args.model, OUT / f"lloom-calls-{args.model.replace(':', '_')}.jsonl")
    t0 = time.time()

    reviews = sample(args.n, args.negative_only, args.month, args.seed)
    every = distill(m, reviews)
    with (out / "bullets.jsonl").open("w", encoding="utf-8") as f:
        for b in every:
            f.write(json.dumps(b, ensure_ascii=False) + "\n")
    bullets = [b for b in every if b["kind"] == args.side]
    kinds = Counter(b["kind"] for b in every)
    print(f"{len(reviews)} reviews -> {kinds['complaint']} complaints, {kinds['praise']} praise; "
          f"{sum(b['exact'] for b in every)}/{len(every)} quotes exact; "
          f"{sum(1 for b in every if b['kind'] == 'complaint' and b['score'] >= 4)} complaints in 4-5 star reviews")

    vecs = encode([b["bullet"] for b in bullets], show_progress=False)
    concepts, scores = Concepts(args.name or args.tag), {}
    pool = list(range(len(bullets)))
    rounds = range(args.loops + 1)
    if args.prior:
        # score this slice against the carried concepts first; only the leftovers loop and mint
        concepts.load(args.prior)
        print(f"carried {len(concepts.live())} live concepts from {args.prior}")
        score_all(m, concepts, bullets, vecs, scores, args)
        if args.overlap:
            merge_overlaps(m, concepts, bullets, vecs, scores, args, 0)
        pool = leftovers(concepts, scores, bullets, args)
        rounds = range(1, args.loops + 1)
    for rnd in rounds:
        labels = cluster(vecs[pool], args.min_size)
        groups = [[pool[i] for i in np.where(labels == lab)[0]] for lab in sorted(set(labels) - {-1})]
        print(f"round {rnd}: {len(pool)} bullets -> {len(groups)} clusters, {int((labels == -1).sum())} outliers")
        if not groups:
            break
        new = []
        for g in groups:
            for name, crit, own in synthesize(m, bullets, vecs, g):
                new.append(concepts.add(name, crit, own, rnd))
        if args.select:
            screen(m, concepts, new, args)
        else:
            review(m, concepts, bullets, vecs, rnd)
        if args.dry:
            for c in concepts.items:
                came = " <- " + ",".join(c["merged_from"]) if c["merged_from"] else ""
                print(f"{c['id']} {c['kind']:7} {c['status']:6} {len(c['built_from']):3} {c['name']}{came}")
                print(f"      {c['criterion']}")
            return
        score_all(m, concepts, bullets, vecs, scores, args)
        if args.select:
            select(concepts, new, scores, len(bullets), args)
        elif args.overlap:
            merge_overlaps(m, concepts, bullets, vecs, scores, args, rnd)
        pool = leftovers(concepts, scores, bullets, args)
    if args.select:
        subsume(concepts, scores, args)

    (out / "concepts.json").write_text(json.dumps(
        [c | {"matches": sorted(matches(scores, c["id"], args.threshold)) if c["id"] in scores else []}
         if c["status"] == "live" else c
         for c in concepts.items], ensure_ascii=False, indent=1), encoding="utf-8")
    (out / f"scores-{args.side}.json").write_text(json.dumps(
        {"bullets": [b["id"] for b in bullets], "scores": scores}), encoding="utf-8")
    text = report(concepts, bullets, scores, args, m, time.time() - t0)
    (out / f"report-{args.side}.md").write_text(text, encoding="utf-8")
    print("\n" + text.split("## Issue concepts")[0])
    print(f"Report: {out / f'report-{args.side}.md'}")


if __name__ == "__main__":
    main()
