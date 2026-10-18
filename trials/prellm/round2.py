"""Embedding route, round 2 (llm-trials.md, "Embedding route, round 2"): steer the
embedding with an instruction-tuned embedder (W1) and let the model review whole
clusters (W2), on top of the round-1 final stack (U2 + U4 + U6).

    .venv/Scripts/python.exe -X utf8 trials/prellm/round2.py v1 [run names...]
    PRELLM_HELDOUT=1 .venv/Scripts/python.exe -X utf8 trials/prellm/round2.py final-v2

Output: trials/runs/prellm/R2/<variant>/<run>.json and labels-<run>.npy, as run_s.py.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trials.prellm import harness as H, stack as S  # noqa: E402
from trials.prellm.legacy import graph  # noqa: E402

EMBEDDER = "Qwen/Qwen3-Embedding-0.6B"
INSTRUCTION = ("Identify the specific app feature and the problem with it that this sentence "
               "from a mobile app review complains about")
CACHE = H.OUT / "cache"
END_DEV, END_HELD = "2026-09-22", "2026-02-28"


@dataclass(frozen=True)
class R2Options:
    stack: S.StackOptions = S.FINAL
    w1: bool = True                 # instructed embedder for clustering
    w2: bool = True                 # model reviews each cluster: specific or general
    instruction: str = INSTRUCTION
    review_shown: int = 12
    review: str = "two-way"         # W2 prompt: "two-way" (specific/general) or "breadth" (specific/broad/general)
    merge: float = 0.45             # W3: segments re-joined into units at this cosine; > 1 keeps segments apart
    band: tuple[int, int] = (20, 30)  # clusters the band search aims for, before the review
    min_size: int = 5               # smallest cluster kept (round 8: 3 lets small issues form one)
    merge_pairs: int = 0            # M: > 0 = each kept cluster's this many nearest are put to the
                                    # model as merge candidates (reduce after over-clustering)
    reassign: bool = False          # W4: Misc units join the nearest kept issue cluster at the pull bar
                                    # (BERTopic reduce_outliers, embeddings strategy)
    unit_verdicts: bool = False     # W5: a classifier trained on the cluster verdicts judges each unit
    rescue_bar: str = "pull"        # W5 rescue: "pull" (global bar) or "member" (cluster's 10th-pct member)
    context: bool = False           # S3: embed each unit with its neighbouring units (contextual chunks)
    second_look: bool = False       # W6:a second review on members spread across the cluster; a
                                    # cluster stays specific only if both reviews say so (self-consistency)
    standalone: str = ""            # S: "spread" or "centre" = kept clusters get a stand-alone check
                                    # on those members; "not" sends the cluster to Miscellaneous
    abtt: int = 0                   # A: all-but-the-top (Mu & Viswanath 2018): the window's mean and
                                    # this many top principal directions leave the vectors
    neutral: bool = False           # N: no wording taken from this app in prompts or the set-aside
    cause: str = ""                 # C: symptom units join the cause cluster their review names;
                                    # "code" (Ca, asymmetric confidence) or "model" (Cb, one call per pair)
    cause_lift: float = 0.0         # F: C's rules also need this lift (round 7: 1.5)
    eac: float = 0.0                # E: > 0 = evidence accumulation; the minimum cluster size as a
                                    # share of the units (varied-resolution base runs, HDBSCAN cut)
    eac_outliers: float = 0.0       # E: noise units join the cluster they co-occur with most, at this
                                    # mean co-association (BERTopic reduce_outliers); 0 = off

    def drop(self, fix: str) -> "R2Options":
        if fix in ("W1", "W2"):
            return replace(self, **{fix.lower(): False})
        return replace(self, stack=self.stack.drop(fix))


# ------------------------------------------------------------------- W1 ----

@lru_cache(maxsize=1)
def _embedder():
    import torch
    from sentence_transformers import SentenceTransformer
    torch.set_num_threads(max(1, (torch.get_num_threads() or 4)))
    return SentenceTransformer(EMBEDDER, device="cpu")


def embed(texts, instruction: str = INSTRUCTION) -> np.ndarray:
    """Unit-normalised instructed embeddings, cached on disk by (instruction, text)."""
    tag = hashlib.sha1(f"{EMBEDDER}|{instruction}".encode()).hexdigest()[:10]
    path = CACHE / f"emb-{tag}.npz"
    CACHE.mkdir(parents=True, exist_ok=True)
    have: dict[str, np.ndarray] = {}
    if path.exists():
        z = np.load(path, allow_pickle=False)
        have = dict(zip(z["keys"].tolist(), z["vecs"]))
    key = lambda t: hashlib.sha1(t.encode("utf-8")).hexdigest()  # noqa: E731
    todo = sorted({t for t in texts if key(t) not in have}, key=len)
    if todo:
        t0 = time.perf_counter()
        if os.environ.get("PRELLM_CPU_EMBED") == "1":
            v = _embedder().encode(todo, prompt=f"Instruct: {instruction}\nQuery: ", batch_size=16,
                                   normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
        else:
            v = embed_gpu(todo, instruction)
        for t, x in zip(todo, v):
            have[key(t)] = x.astype(np.float32)
        ks = sorted(have)
        np.savez(path, keys=np.array(ks), vecs=np.stack([have[k] for k in ks]))
        print(f"  embedded {len(todo)} new texts in {time.perf_counter() - t0:.0f}s", flush=True)
    return np.ascontiguousarray(np.stack([have[key(t)] for t in texts]), dtype=np.float32)


GPU_EMBEDDER = "qwen3-embedding:0.6b"
# Ollama's address; OLLAMA_HOST moves it when Windows reserves the default port at boot
OLLAMA = "http://" + os.environ.get("OLLAMA_HOST", "127.0.0.1:11434").removeprefix("http://")


def embed_gpu(texts: list[str], instruction: str) -> np.ndarray:
    """The same model served by Ollama on the GPU (same-text cosine with the CPU build
    0.9997 on 200 V1 units), so new texts join the CPU cache."""
    import urllib.request
    out = []
    for i in range(0, len(texts), 64):
        body = json.dumps({"model": GPU_EMBEDDER,
                           "input": [f"Instruct: {instruction}\nQuery: {t}" for t in texts[i:i + 64]]}).encode()
        req = urllib.request.Request(f"{OLLAMA}/api/embed", body, {"Content-Type": "application/json"})
        out.append(np.array(json.load(urllib.request.urlopen(req, timeout=600))["embeddings"], dtype=np.float32))
    v = np.vstack(out)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def nn3(vectors: np.ndarray) -> np.ndarray:
    return graph.build_knn(vectors, k=3).similarities[:, 2]


def quantile_map(src: np.ndarray, dst: np.ndarray):
    """Monotone map from one space's similarities to another's, through their
    third-nearest-neighbour similarity distributions over the same units (label-free)."""
    s, d = np.sort(src), np.sort(dst)
    return lambda x: float(np.quantile(d, np.searchsorted(s, x) / len(s)))


# ------------------------------------------------------------------- W2 ----

REVIEW = """You see sentences taken from reviews of a mobile app. They were grouped because they are similar. Decide what the group as a whole is about. Pick one answer:
specific: most sentences describe the same specific problem with one part of the app (a screen, an action, a setting, a kind of device, sign-in, installing or updating, the app failing to open), even in different words.
general: most sentences are general opinions or feelings about the app, the company or its service (bad app, worst bank, frustrating, switching banks, support is useless), naming no specific feature or fault.

Examples from another domain:
- "driver map froze again" / "can't see where my driver is" / "tracking stops updating" -> specific
- "worst delivery app ever" / "this company does not care" / "so disappointed, deleting it" -> general"""


# The validated breadth definition (issues/prompts.py BREADTH, 37 of 38 on V1), applied to a
# cluster's members instead of a concept's name and criterion.
REVIEW_BREADTH = """You see sentences taken from reviews of a mobile app. They were grouped because they are similar. Decide what the group as a whole is about. Pick one answer:
specific: most sentences name one feature (a screen, an action, a setting, a kind of device or connection, or the app failing to open or run at all) and one kind of failure, so one product team would know where to look. Different wordings of the same failure still count.
broad: the sentences name no single feature (the app as a whole is buggy, slow, has errors, crashes, malfunctions, does not work, is hard to use, or got worse after updates; reinstalling did not fix it), or they mix several different features.
general: feelings or opinions (frustration, annoyance, regret, distrust, telling others to avoid the app, deleting it, switching banks) about the app, a process, the company or its service, naming no fault; or the quality of customer support.

Examples from another domain:
- "driver map froze again" / "can't see where my driver is" / "tracking stops updating" -> specific
- "app crashes as soon as I open it" / "closes on launch every time" -> specific
- "app is so buggy" / "constant errors" / "still broken after reinstalling" / "the new design is confusing" -> broad
- "promo code rejected" / "driver map freezes" / "card declined" -> broad
- "worst delivery app ever" / "avoid this company" / "deleting it" / "support is useless" -> general"""


# The breadth review at the level one product team owns (as the synthesize prompt pitches
# concepts): one part of the app, the failure details may differ.
REVIEW_OWNER = """You see sentences taken from reviews of a mobile app. They were grouped because they are similar. Decide what the group as a whole is about. Pick one answer:
specific: most sentences are about one part of the app (a screen, an action such as paying or signing in, a setting, a kind of device or connection, or the app failing to open or run at all) and say it fails, is blocked, is missing or works badly, so one product team would know where to look. The details may differ (an error, a limit, a crash or a fee on the same action).
broad: the sentences name no single part of the app (the app as a whole is buggy, slow, has errors, crashes, malfunctions, does not work, is hard to use, or got worse after updates; reinstalling did not fix it), or they mix several different parts of the app.
general: feelings or opinions (frustration, annoyance, regret, distrust, telling others to avoid the app, deleting it, switching banks) about the app, a process, the company or its service, naming no fault; or the quality of customer support.

Examples from another domain:
- "driver map froze again" / "can't see where my driver is" / "tracking stops updating" -> specific
- "promo code rejected" / "promo code expired too early" / "can't combine two promo codes" -> specific
- "app crashes as soon as I open it" / "closes on launch every time" -> specific
- "app is so buggy" / "constant errors" / "still broken after reinstalling" / "the new design is confusing" -> broad
- "promo code rejected" / "driver map freezes" / "card declined" -> broad
- "worst delivery app ever" / "avoid this company" / "deleting it" / "support is useless" -> general"""


# Round 5, S2: REVIEW_OWNER with the validated breadth example back in: an error message
# with no screen or action named is broad.
REVIEW_OWNER2 = REVIEW_OWNER.replace(
    "or got worse after updates; reinstalling did not fix it)",
    "or got worse after updates; reinstalling did not fix it; an error message such as \"something "
    "went wrong\" or \"technical difficulties\" with no screen or action named)").replace(
    '- "app is so buggy" / "constant errors"',
    '- "sorry, something went wrong" / "always technical issues" / "error every time I open it, no '
    'idea why" -> broad\n- "app is so buggy" / "constant errors"')

# Round 6, N: REVIEW_OWNER2 with nothing taken from this app: no banking words, and the
# error-message examples reworded as the generic category (the first rewording dropped
# "technical issues", generic English, and let that cluster through on V2).
REVIEW_OWNER3 = REVIEW_OWNER.replace("switching banks", "switching to a competitor").replace(
    "or got worse after updates; reinstalling did not fix it)",
    "or got worse after updates; reinstalling did not fix it; a generic error, glitch or outage "
    "message (technical issues, an error occurred, try again later) with no screen or action named)").replace(
    '- "app is so buggy" / "constant errors"',
    '- "oops, an error occurred" / "always technical issues" / "error pops up every time, no idea why" '
    '-> broad\n- "app is so buggy" / "constant errors"')

# Round 11, P: REVIEW_OWNER3 with the stand-alone test (Li et al. 2016, sentence specificity in
# context): sentences that name no part of the app on their own are general, and a group
# held together by a common word over different problems is broad.
REVIEW_OWNER4 = REVIEW_OWNER3.replace(
    "or they mix several different parts of the app.",
    "or they mix several different parts of the app, even when they share a common word such as "
    "\"account\", \"app\" or \"phone\".").replace(
    "or the quality of customer support.",
    "or the quality of customer support. Also general: sentences that name no part of the app and "
    "no fault on their own and only make sense with the rest of their review (remarks, asides, "
    "thanks, describing what one owns or did).").replace(
    '- "worst delivery app ever"',
    '- "it\'s only a year old....really" / "thanks a lot guys" / "I just bought a new bike" / '
    '"apparently that isn\'t good enough" -> general\n- "worst delivery app ever"')

BRAND_WORDS = {"rbc", "royal", "canada", "canadian"}


def vague_neutral(w: H.Window) -> np.ndarray:
    """The old set-aside without this app's brand words and banking anchor (round 6, N)."""
    from trials.prellm.legacy import vague as V
    generic = V.GENERIC_WORDS - BRAND_WORDS
    anchors = [a.replace("switching banks", "switching to a competitor") for a in V.ANCHORS]
    near = (w.vectors @ np.asarray(H.encode(anchors), dtype=np.float32).T).max(axis=1) >= V.ANCHOR_SIMILARITY
    n_content = np.array([sum(1 for t in V._TOKEN.findall(x.lower())
                              if t not in generic and t.split("'")[0] not in generic) for x in w.texts])
    return (n_content == 0) | (near & (n_content <= V.MAX_CONTENT_WORDS))


@lru_cache(maxsize=1)
def _llm():
    from product_view.issues.llm import LLM, LLMConfig
    return LLM(LLMConfig(base_url=OLLAMA), CACHE / "llm-calls.db")


def review_clusters(w: H.Window, labels: np.ndarray, shown: int, how: str = "two-way",
                    spread: bool = False) -> dict[int, str]:
    """One call per cluster on its `shown` members closest to the centre, or with `spread`
    on `shown` members evenly spaced across the closeness ranking (the second look)."""
    from product_view.issues.llm import Req, enum, obj
    prompt, answers = {"breadth": (REVIEW_BREADTH, ("specific", "broad", "general")),
                       "owner": (REVIEW_OWNER, ("specific", "broad", "general")),
                       "owner2": (REVIEW_OWNER2, ("specific", "broad", "general")),
                       "owner3": (REVIEW_OWNER3, ("specific", "broad", "general")),
                       "owner4": (REVIEW_OWNER4, ("specific", "broad", "general"))}.get(
        how, (REVIEW, ("specific", "general")))
    cents = H.centres(w, labels)
    ids = sorted(cents)
    reqs = []
    for l in ids:
        m = np.flatnonzero(labels == l)
        ranked = m[np.argsort(-(w.vectors[m] @ cents[l]), kind="stable")]
        if spread:
            top = ranked[np.unique(np.linspace(0, len(ranked) - 1, min(shown, len(ranked))).round().astype(int))]
        else:
            top = ranked[:shown]
        listing = "\n".join(f"- {' '.join(w.texts[i].split())[:200]}" for i in top)
        reqs.append(Req(prompt, f"Sentences:\n{listing}", obj({"answer": enum(*answers)})))
    got = _llm().run(reqs, label="cluster review") if reqs else []
    return {l: g["answer"] for l, g in zip(ids, got)}


STANDALONE = """You see sentences taken from reviews of a mobile app, grouped because they are similar. Read each sentence on its own, without guessing what the rest of its review said. Pick one answer:
one: most sentences, each on its own, name the same part of the app (a screen, an action such as paying or signing in, a setting, a kind of device or connection, or the app failing to open) and a problem with it.
not: most sentences name no part of the app on their own (remarks, asides, thanks, describing what one owns or did, reactions), or they describe different problems that only share a common word.

Examples from another domain:
- "driver map froze again" / "can't see where my driver is" / "tracking stops updating" -> one
- "promo code rejected" / "promo code expired too early" / "can't combine two promo codes" -> one
- "it's only a year old....really" / "thanks a lot guys" / "I just bought a new bike" / "apparently that isn't good enough" -> not
- "my order never came" / "order history is empty" / "can't cancel my order" / "order total is wrong" -> not"""


def standalone_check(w: H.Window, labels: np.ndarray, ids: list, shown: int, how: str) -> dict:
    """S (round 12; sentence specificity in context, Li et al. 2016): one call per kept cluster
    on its members spread across the closeness ranking ("spread") or closest to the centre."""
    from product_view.issues.llm import Req, enum, obj
    cents = H.centres(w, labels)
    reqs = []
    for l in ids:
        m = np.flatnonzero(labels == l)
        ranked = m[np.argsort(-(w.vectors[m] @ cents[l]), kind="stable")]
        if how == "spread":
            top = ranked[np.unique(np.linspace(0, len(ranked) - 1, min(shown, len(ranked))).round().astype(int))]
        else:
            top = ranked[:shown]
        listing = "\n".join(f"- {' '.join(w.texts[i].split())[:200]}" for i in top)
        reqs.append(Req(STANDALONE, f"Sentences:\n{listing}", obj({"answer": enum("one", "not")})))
    got = _llm().run(reqs, label="stand-alone check") if reqs else []
    return {l: g["answer"] for l, g in zip(ids, got)}


# ------------------------------------------------------------- pipeline ----

@dataclass
class Prepared:
    w: H.Window            # the window, vectors in the clustering space
    vague: np.ndarray      # the old set-aside, computed on MiniLM
    cfg: H.ClusterConfig
    stack: S.StackOptions  # thresholds mapped into the clustering space
    mapping: dict


def window(end: str, opts: R2Options, months: int = 4) -> H.Window:
    """stack.window with the unit merge threshold as a setting (W3)."""
    so = opts.stack
    if not so.u4:
        return H.load_window(end, months, "negative", merge_threshold=opts.merge)
    w = H.load_window(end, months, "all", merge_threshold=opts.merge)
    keep = np.flatnonzero(S.complaint_mask(w, so))
    sub = w.subset(keep, stream=f"all+sentiment>={so.neg_min}")
    sub.info["sentiment_kept"] = int(len(keep))
    return sub


CONTEXT_INSTRUCTION = ("Identify the specific app feature and the problem with it that the sentence "
                       "from a mobile app review complains about; the surrounding text only shows what "
                       "the sentence refers to")


def contextual_texts(w: H.Window, end: str) -> list[str]:
    """S3: each unit with the units before and after it in the same review (from the full
    window, so a neighbour filtered out of w still gives context)."""
    full = H.load_window(end, w.months, "all", merge_threshold=0.45)
    by_review: dict[str, dict[int, str]] = {}
    for rid, seq, t in zip(full.review_id.tolist(), full.seq.tolist(), full.texts):
        by_review.setdefault(rid, {})[seq] = " ".join(t.split())
    out = []
    for rid, seq, t in zip(w.review_id.tolist(), w.seq.tolist(), w.texts):
        units = by_review.get(rid, {})
        before, after = units.get(seq - 1, ""), units.get(seq + 1, "")
        out.append(f"Sentence: {' '.join(t.split())}\nSurrounding text: {before[:200]} [...] {after[:200]}")
    return out


def prepare(end: str, opts: R2Options) -> Prepared:
    base = window(end, opts)
    vague = vague_neutral(base) if opts.neutral else H.vague_mask(base)
    cfg, so, mapping = H.ClusterConfig(band=opts.band, min_size=opts.min_size), opts.stack, {}
    if not opts.w1:
        return Prepared(base, vague, cfg, so, mapping)
    if opts.context:
        v = embed(contextual_texts(base, end), CONTEXT_INSTRUCTION)
    else:
        v = embed(base.texts, opts.instruction)
    if opts.abtt:
        v = all_but_the_top(v, opts.abtt)
    w = replace(base, vectors=v, info=dict(base.info, embedder=EMBEDDER))
    elig = np.flatnonzero(~vague)
    f = quantile_map(nn3(base.vectors[elig]), nn3(v[elig]))
    mapping = dict(reach=f(so.reach), pull=f(so.pull), cohesion=f(cfg.cohesion_floor))
    so = replace(so, reach=mapping["reach"], pull=mapping["pull"])
    cfg = replace(cfg, cohesion_floor=mapping["cohesion"])
    return Prepared(w, vague, cfg, so, mapping)


def all_but_the_top(v: np.ndarray, d: int) -> np.ndarray:
    """A (Mu & Viswanath 2018): remove the common mean and the top d principal directions,
    which carry what every unit shares (frequent words), then renormalise."""
    x = v - v.mean(axis=0)
    _, _, vt = np.linalg.svd(x, full_matrices=False)
    x = x - (x @ vt[:d].T) @ vt[:d]
    return (x / np.linalg.norm(x, axis=1, keepdims=True)).astype(np.float32)


def unit_verdicts(w: H.Window, labels: np.ndarray, before: np.ndarray, verdict: dict[int, str],
                  vague: np.ndarray, pull: float, rescue_bar: str = "pull") -> tuple[np.ndarray, dict]:
    """W5 (TnT-LLM's pattern): each reviewed unit takes its cluster's verdict as a label; a
    logistic regression on the vectors, cross-fitted over 5 folds, gives every unit its own
    verdict. Kept-cluster units judged general or broad leave; units outside the issue
    clusters (not the vague set-aside) judged specific join the nearest kept cluster at the
    pull bar."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold

    train = np.flatnonzero(before >= 0)
    y = np.array([verdict[int(l)] for l in before[train]])
    pred = np.empty(len(w), dtype=object)
    classes = sorted(set(y))
    if len(classes) < 2:
        return labels, {"skipped": "one verdict only"}
    folds = min(5, min(int((y == c).sum()) for c in classes))
    if folds >= 2:
        for a, b in StratifiedKFold(folds, shuffle=True, random_state=0).split(train, y):
            clf = LogisticRegression(max_iter=2000).fit(w.vectors[train[a]], y[a])
            pred[train[b]] = clf.predict(w.vectors[train[b]])
    else:
        pred[train] = y
    rest = np.flatnonzero((before < 0) & ~vague)
    if len(rest):
        pred[rest] = LogisticRegression(max_iter=2000).fit(w.vectors[train], y).predict(w.vectors[rest])

    out = labels.copy()
    kept = np.flatnonzero(labels >= 0)
    gen_out = kept[pred[kept] == "general"]
    broad_out = kept[pred[kept] == "broad"]
    out[gen_out], out[broad_out] = H.GENERAL, H.MISC
    cents = H.centres(w, out)
    rescued = 0
    if cents:
        ids = sorted(cents)
        mat = np.stack([cents[l] for l in ids])
        outside = np.flatnonzero((out < 0) & ~vague)
        cand = outside[pred[outside] == "specific"]
        if len(cand):
            sims = w.vectors[cand] @ mat.T
            best = sims.argmax(axis=1)
            if rescue_bar == "member":
                # as close to the centre as the cluster's own 10th-percentile member
                floor = np.array([np.quantile(w.vectors[out == l] @ cents[l], 0.1) for l in ids])
                ok = sims[np.arange(len(cand)), best] >= floor[best]
            else:
                ok = sims[np.arange(len(cand)), best] >= pull
            out[cand[ok]] = np.array(ids)[best[ok]]
            rescued = int(ok.sum())
    agree = float(np.mean(pred[train] == y))
    return out, {"general_out": int(len(gen_out)), "broad_out": int(len(broad_out)), "rescued": rescued,
                 "agreement_with_cluster_verdict": round(agree, 3)}


def prepare_settings(p: Prepared, opts: R2Options) -> Prepared:
    """p's window and vectors with opts' stack switches, band and (mapped) thresholds."""
    so, cfg = opts.stack, H.ClusterConfig(band=opts.band, min_size=opts.min_size)
    if p.mapping:
        so = replace(so, reach=p.mapping["reach"], pull=p.mapping["pull"])
        cfg = replace(cfg, cohesion_floor=p.mapping["cohesion"])
    return replace(p, stack=so, cfg=cfg)


def cluster(p: Prepared, order_seed: int, opts: R2Options) -> tuple[np.ndarray, dict]:
    w, so, cfg = p.w, p.stack, p.cfg
    info: dict = {"mapping": p.mapping}
    labels = np.zeros(len(w), dtype=np.int64)
    labels[p.vague] = H.GENERAL
    if so.u2:
        elig = np.flatnonzero(labels == 0)
        far = elig[nn3(w.vectors[elig]) < so.reach]
        labels[far] = H.MISC
        info["reach_misc"] = int(len(far))
    elig = np.flatnonzero(labels == 0)
    if opts.eac:
        local, info["core"] = evidence_accumulation(w.vectors[elig], cfg, order_seed, so.runs, opts.eac,
                                                    outliers=opts.eac_outliers)
    elif so.u6:
        local, info["core"] = S.consensus(w.vectors[elig], cfg, order_seed, so.runs, so.tau, so.search)
    else:
        local, info["core"] = S.base_cluster(w.vectors[elig], cfg, order_seed, so.search)
    labels[elig] = local
    if so.u2:
        for l, c in H.centres(w, labels).items():
            m = np.flatnonzero(labels == l)
            labels[m[w.vectors[m] @ c < so.pull]] = H.MISC
        labels = S._refilter(w, labels, cfg)
    labels = H.canonical(labels)
    reviewed = H.centres(w, labels)           # every cluster the review sees, kept or not
    before = labels.copy()
    verdict = {l: "specific" for l in reviewed}
    if opts.w2:
        verdict = review_clusters(w, labels, opts.review_shown, opts.review)
        if opts.second_look:
            again = review_clusters(w, labels, opts.review_shown, opts.review, spread=True)
            # specific only if both say so; otherwise the non-specific answer stands
            verdict = {l: v if v != "specific" else again[l] for l, v in verdict.items()}
            info["w6_changed"] = sum(1 for l in verdict if again[l] != "specific" and verdict[l] == again[l]
                                     and again[l] != "specific")
        if opts.standalone:
            # S (round 12): a check that only removes; kept clusters whose sentences, each on
            # its own, don't name one part of the app go to Miscellaneous
            keep = [l for l, v in verdict.items() if v == "specific"]
            sa = standalone_check(w, labels, keep, opts.review_shown, opts.standalone)
            for l in keep:
                if sa[l] == "not":
                    verdict[l] = "broad"
            info["s_removed"] = [l for l in keep if sa[l] == "not"]
        gen =[l for l, v in verdict.items() if v == "general"]
        broad = [l for l, v in verdict.items() if v == "broad"]
        for l in gen:
            labels[labels == l] = H.GENERAL
        for l in broad:
            labels[labels == l] = H.MISC
        info["w2_general"], info["w2_broad"] = gen, broad
        info["w2_calls"] = len(verdict)
    if opts.reassign and reviewed:
        # Nearest centre among all reviewed clusters: a unit closest to a removed (broad or
        # general) cluster stays out; one closest to a kept cluster joins it at the pull bar.
        ids = sorted(reviewed)
        mat = np.stack([reviewed[l] for l in ids])
        misc = np.flatnonzero(labels == H.MISC)
        sims = w.vectors[misc] @ mat.T
        best = sims.argmax(axis=1)
        top = np.array(ids)[best]
        ok = (sims[np.arange(len(misc)), best] >= so.pull) & np.array(
            [verdict[l] == "specific" for l in top], dtype=bool)
        labels[misc[ok]] = top[ok]
        info["w4_reassigned"] = int(ok.sum())
    if opts.unit_verdicts and opts.w2 and reviewed:
        labels, info["w5"] = unit_verdicts(w, labels, before, verdict, p.vague, so.pull, opts.rescue_bar)
    if opts.merge_pairs:
        labels, info["merge"] = merge_clusters(w, labels, opts.merge_pairs, opts.review_shown)
    if opts.cause:
        labels, info["cause"] = attribute_causes(w, labels, opts.cause, min_lift=opts.cause_lift)
    labels = H.canonical(labels)
    return labels, info


# ------------------------------------------------------------------- M ----

MERGE = """You see two groups of sentences taken from reviews of a mobile app. Each group was judged to be about one specific problem. Decide whether both groups describe the same problem, so that one product team would fix them together as one issue. Pick one answer:
same: both groups are about the same part of the app (the same screen, action, setting, kind of device or step) failing in the same way, even if worded differently or describing different moments of the same step.
different: the groups are about different parts of the app, or different failures of the same part that would be fixed separately.

Examples from another domain:
- A "driver map froze" / "can't see my driver" and B "tracking stops updating" / "driver location wrong" -> same
- A "promo code rejected" and B "card declined at checkout" -> different
- A "can't log in" and B "password reset email never arrives" -> different"""


def merge_clusters(w: H.Window, labels: np.ndarray, k: int, shown: int) -> tuple[np.ndarray, dict]:
    """M (reduce after over-clustering; Janssens et al. 2025, LLM-assisted topic merging):
    each kept cluster's k nearest kept clusters by centre are candidate pairs; one call per
    pair on the members closest to each centre; pairs judged the same merge (union-find)."""
    from product_view.issues.llm import Req, enum, obj
    cents = H.centres(w, labels)
    ids = sorted(cents)
    if len(ids) < 2:
        return labels, {"pairs": 0, "merged": 0}
    mat = np.stack([cents[l] for l in ids])
    sim = mat @ mat.T
    np.fill_diagonal(sim, -1)
    pairs = sorted({tuple(sorted((ids[a], ids[b]))) for a in range(len(ids))
                    for b in np.argsort(-sim[a])[:k]})

    def listing(l):
        m = np.flatnonzero(labels == l)
        top = m[np.argsort(-(w.vectors[m] @ cents[l]), kind="stable")[:shown // 2]]
        return "\n".join(f"- {' '.join(w.texts[i].split())[:200]}" for i in top)

    reqs = [Req(MERGE, f"Group A:\n{listing(a)}\n\nGroup B:\n{listing(b)}", obj({"answer": enum("same", "different")}))
            for a, b in pairs]
    got = _llm().run(reqs, label="cluster merge")
    parent = {l: l for l in ids}

    def root(l):
        while parent[l] != l:
            parent[l] = parent[parent[l]]
            l = parent[l]
        return l

    same = [(a, b) for (a, b), g in zip(pairs, got) if g["answer"] == "same"]
    for a, b in same:
        ra, rb = root(a), root(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    out = labels.copy()
    for l in ids:
        out[labels == l] = root(l)
    return out, {"pairs": len(pairs), "same": [list(p) for p in same],
                 "clusters_before": len(ids), "clusters_after": len({root(l) for l in ids})}


# ------------------------------------------------------------------- E ----

def evidence_accumulation(vectors: np.ndarray, cfg: H.ClusterConfig, order_seed: int, runs: int,
                          frac: float, min_samples: int = 5, outliers: float = 0.0) -> tuple[np.ndarray, dict]:
    """E (Fred & Jain 2005): base runs at varied granularity, then the co-association
    matrix cut by stability (HDBSCAN, excess of mass) with a minimum cluster size that is
    a share of the window. The band search runs once, to place the resolution range."""
    from sklearn.cluster import HDBSCAN
    from trials.prellm.legacy import granularity
    from trials.prellm.legacy.strategies import LeidenStrategy
    n = len(vectors)
    if n < cfg.min_size:
        return np.full(n, H.MISC, dtype=np.int64), {"n_clusters": 0}
    _, pilot = S.base_cluster(vectors, cfg, order_seed)
    r_star = pilot["param"]
    rng = np.random.default_rng(order_seed)
    strat = LeidenStrategy(seed=cfg.leiden_seed)
    co = np.zeros((n, n), dtype=np.float32)
    for i in range(runs):
        perm = rng.permutation(n)
        v = vectors[perm]
        r = r_star * float(np.exp(rng.uniform(np.log(0.25), np.log(2.0))))
        lab = strat.fit(v, graph.build_knn(v, k=cfg.knn_k), r)
        clusters, _ = granularity.filter_clusters(lab, v, cfg.min_size, cfg.cohesion_floor)
        for members in clusters.values():
            m = perm[members]
            co[np.ix_(m, m)] += 1
    co /= runs
    np.fill_diagonal(co, 1.0)
    mcs = max(cfg.min_size, int(round(frac * n)))
    hd = HDBSCAN(metric="precomputed", min_cluster_size=mcs, min_samples=min_samples,
                 cluster_selection_method="eom").fit((1.0 - co).astype(np.float64))
    lab = hd.labels_.astype(np.int64)
    clusters, uncl = granularity.filter_clusters(lab, vectors, cfg.min_size, cfg.cohesion_floor)
    out = np.full(n, H.MISC, dtype=np.int64)
    for new, (_, members) in enumerate(sorted(clusters.items())):
        out[members] = new
    joined = 0
    if outliers and len(clusters):
        ids = sorted(set(out[out >= 0].tolist()))
        noise = np.flatnonzero(out < 0)
        aff = np.stack([co[np.ix_(noise, np.flatnonzero(out == l))].mean(axis=1) for l in ids], axis=1)
        best = aff.argmax(axis=1)
        ok = aff[np.arange(len(noise)), best] >= outliers
        out[noise[ok]] = np.array(ids)[best[ok]]
        joined = int(ok.sum())
    return out, {"n_clusters": len(clusters), "r_star": r_star, "min_cluster_size": mcs,
                 "noise": int((lab < 0).sum()), "unclustered": int(uncl), "outliers_joined": joined}


# ------------------------------------------------------------------- C ----

CAUSE = """You see two groups of sentences from reviews of a mobile app, then reviews that contain a sentence from both groups. Decide how the two problems relate. Pick one answer:
a_from_b: what group A describes is what the user sees because of the problem in group B (B is the cause).
b_from_a: what group B describes is what the user sees because of the problem in group A (A is the cause).
independent: two separate problems that happen to be mentioned in the same review.

Examples from another domain:
- A "can't place an order" / B "the app says my phone is no longer supported" -> a_from_b
- A "driver map freezes" / B "promo code rejected" -> independent"""


def attribute_causes(w: H.Window, labels: np.ndarray, how: str, min_sup: int = 3,
                     min_conf: float = 0.10, max_p: float = 0.05, min_share: float = 0.25,
                     min_lift: float = 0.0):
    """C: co-occurrence association rules between kept clusters over the window's reviews
    (implicit-aspect identification, Hai et al. 2011, with clusters for aspects). For a
    rule S -> C, where S is the symptom side, the units of S whose own review has a unit
    in C move to C; S keeps the rest and the rule is reported as a parent link. A pair is
    a candidate when the reviews with both are more than chance allows (one-sided Fisher
    exact test, Webb 2007): in an incident month a cause is common, so lift stays low."""
    from scipy.stats import fisher_exact
    kept = sorted(int(l) for l in np.unique(labels) if l >= 0)
    if len(kept) < 2:
        return labels, {"rules": []}
    by_review: dict[str, set[int]] = {}
    for rid, l in zip(w.review_id.tolist(), labels.tolist()):
        if l >= 0:
            by_review.setdefault(rid, set()).add(int(l))
    n_rev = len(by_review)
    n = {l: sum(l in s for s in by_review.values()) for l in kept}
    shared = {l: sum(l in s and len(s) > 1 for s in by_review.values()) / n[l] for l in kept}
    both = {}
    for s in by_review.values():
        for a in s:
            for b in s:
                if a != b:
                    both[(a, b)] = both.get((a, b), 0) + 1
    conf = {k: v / n[k[0]] for k, v in both.items()}
    lift = {k: conf[k] / (n[k[1]] / n_rev) for k in both}
    def p_value(a, b):
        v = both[(a, b)]
        return fisher_exact([[v, n[a] - v], [n[b] - v, n_rev - n[a] - n[b] + v]], alternative="greater")[1]
    cand = [(a, b) for (a, b), v in both.items() if a < b and v >= min_sup and p_value(a, b) <= max_p
            and max(lift[(a, b)], lift[(b, a)]) >= min_lift]
    rules = []                           # (symptom, cause)
    if how == "code":
        for a, b in cand:
            s, c = (a, b) if conf[(a, b)] > conf[(b, a)] else (b, a)
            if conf[(s, c)] >= min_conf and shared[s] >= min_share:
                rules.append((s, c))
    else:
        from product_view.issues.llm import Req, enum, obj
        cents = H.centres(w, labels)
        reqs = []
        for a, b in cand:
            def top(l, k=4):
                m = np.flatnonzero(labels == l)
                return m[np.argsort(-(w.vectors[m] @ cents[l]), kind="stable")[:k]]
            rids = sorted(rid for rid, s in by_review.items() if a in s and b in s)[:6]
            pair = []
            for rid in rids:
                m = np.flatnonzero(w.review_id == rid)
                ta = " / ".join(" ".join(w.texts[i].split())[:150] for i in m if labels[i] == a)
                tb = " / ".join(" ".join(w.texts[i].split())[:150] for i in m if labels[i] == b)
                pair.append(f"- A: {ta}\n  B: {tb}")
            body = ("Group A:\n" + "\n".join(f"- {' '.join(w.texts[i].split())[:150]}" for i in top(a)) +
                    "\n\nGroup B:\n" + "\n".join(f"- {' '.join(w.texts[i].split())[:150]}" for i in top(b)) +
                    "\n\nReviews with both:\n" + "\n".join(pair))
            reqs.append(Req(CAUSE, body, obj({"answer": enum("a_from_b", "b_from_a", "independent")})))
        got = _llm().run(reqs, label="cause check") if reqs else []
        for (a, b), g in zip(cand, got):
            s, c = {"a_from_b": (a, b), "b_from_a": (b, a)}.get(g["answer"], (None, None))
            if s is not None and conf[(s, c)] >= min_conf:
                rules.append((s, c))
    causes: dict[int, list[int]] = {}
    for s, c in rules:
        causes.setdefault(s, []).append(c)
    out = labels.copy()
    moved = 0
    for i in np.flatnonzero(labels >= 0):
        s = int(labels[i])
        here = by_review.get(w.review_id[i], set())
        opts_ = [c for c in causes.get(s, []) if c in here]
        if opts_:
            out[i] = max(opts_, key=lambda c: (conf[(s, c)], -c))
            moved += 1
    return out, {"candidates": len(cand), "rules": [dict(symptom=s, cause=c, conf=round(conf[(s, c)], 3),
                                                         lift=round(lift[(s, c)], 2), reviews=both[(s, c)])
                                                    for s, c in rules], "moved": moved}


# ------------------------------------------------------------------ runs ----

BUNDLE = R2Options()
VARIANTS = {
    "v1": BUNDLE,
    # v2: W2 uses the validated breadth definition (broad clusters leave the issue list);
    # W3: segments are clustered as they are, not re-joined into units
    "v2": R2Options(review="breadth", merge=1.01),
    # v3: the review removes about half the clusters, so aim for more before it; W4 brings
    # outliers back to the issue cluster they would pass the pull bar for
    "v3": R2Options(review="breadth", merge=1.01, band=(35, 50), reassign=True),
    # round 3, v1: v3 with W4 corrected (nearest of all reviewed clusters; see llm-trials.md)
    "r3v1": R2Options(review="breadth", merge=1.01, band=(35, 50), reassign=True),
    # round 3, v2: r3v1 with the drop-one dead weight removed: W3 (units, not segments),
    # W4, U2 (range cap) and U4 (sentiment filter: the star stream instead)
    "r3v2": R2Options(stack=replace(S.FINAL, u2=False, u4=False), review="breadth", merge=0.45,
                      band=(35, 50), reassign=False),
    # round 3, v3: r3v2 with a finer band: mixed clusters still lose specific units to the
    # general bucket and join ID checks with trusted device
    "r3v3": R2Options(stack=replace(S.FINAL, u2=False, u4=False), review="breadth", merge=0.45,
                      band=(45, 60), reassign=False),
    # round 4, v1: round 3 v2 + W5 (unit-level verdicts from a classifier on the cluster verdicts)
    "r4v1": R2Options(stack=replace(S.FINAL, u2=False, u4=False), review="breadth", merge=0.45,
                      band=(35, 50), reassign=False, unit_verdicts=True),
    # round 4, v2: + W6 (second review on members spread across the cluster)
    "r4v2": R2Options(stack=replace(S.FINAL, u2=False, u4=False), review="breadth", merge=0.45,
                      band=(35, 50), reassign=False, unit_verdicts=True, second_look=True),
    # round 4, v3: v2 with the review pitched at what one product team owns
    "r4v3": R2Options(stack=replace(S.FINAL, u2=False, u4=False), review="owner", merge=0.45,
                      band=(35, 50), reassign=False, unit_verdicts=True, second_look=True),
    # round 5, v1: S1 consensus over 100 runs + S2 error-message example back in the review
    "r5v1": R2Options(stack=replace(S.FINAL, u2=False, u4=False, runs=100), review="owner2", merge=0.45,
                      band=(35, 50), reassign=False, unit_verdicts=True, second_look=True),
    # round 5, v2: W5's rescue judged against each cluster's own spread
    "r5v2": R2Options(stack=replace(S.FINAL, u2=False, u4=False, runs=100), review="owner2", merge=0.45,
                      band=(35, 50), reassign=False, unit_verdicts=True, second_look=True, rescue_bar="member"),
    # round 5, v3: v2 + S3 contextual unit embeddings
    "r5v3": R2Options(stack=replace(S.FINAL, u2=False, u4=False, runs=100), review="owner2", merge=0.45,
                      band=(35, 50), reassign=False, unit_verdicts=True, second_look=True, rescue_bar="member",
                      context=True),
    # round 6, v1: round 5 v2 + N (neutral wording) + Ca (symptom units join the cause cluster
    # their review names; rules by co-occurrence, code only)
    "r6v1": R2Options(stack=replace(S.FINAL, u2=False, u4=False, runs=100), review="owner3", merge=0.45,
                      band=(35, 50), reassign=False, unit_verdicts=True, second_look=True, rescue_bar="member",
                      neutral=True, cause="code"),
}
# round 6, v2: v1 with N's error-message wording fixed (v1 ran with the first wording, which
# dropped "technical issues"); the options are the same, the prompt text differs
VARIANTS["r6v2"] = VARIANTS["r6v1"]
# round 7: E (evidence accumulation, minimum cluster size a share of the window) + F (lift floor)
VARIANTS["r7v1"] = replace(VARIANTS["r6v2"], eac=0.005, cause_lift=1.5)
VARIANTS["r7v2"] = replace(VARIANTS["r6v2"], eac=0.01, cause_lift=1.5)
# round 7, v3: v1 + noise units join the cluster they co-occur with most (mean co-association >= 0.2)
VARIANTS["r7v3"] = replace(VARIANTS["r7v1"], eac_outliers=0.2)
# round 8: finer clusters before the review (over-cluster; the review and W5 decide what stays)
VARIANTS["r8v1"] = replace(VARIANTS["r6v2"], band=(50, 70))
VARIANTS["r8v2"] = replace(VARIANTS["r6v2"], band=(60, 85))
VARIANTS["r8v3"] = replace(VARIANTS["r8v1"], min_size=3)
# round 9: r8v2 + M (the reduce step: merge kept clusters the model judges the same issue)
VARIANTS["r9v1"] = replace(VARIANTS["r8v2"], merge_pairs=2)
# round 11: A (all-but-the-top, 2 directions) and P (stand-alone test in the cluster review)
VARIANTS["r11v1"] = replace(VARIANTS["r8v2"], abtt=2, review="owner4")
VARIANTS["r11v2"] = replace(VARIANTS["r8v2"], abtt=2)
VARIANTS["r11v3"] = replace(VARIANTS["r8v2"], review="owner4")
# round 12: r8v2 + S (a stand-alone check on kept clusters that can only remove them)
VARIANTS["r12v1"] = replace(VARIANTS["r8v2"], standalone="spread")
VARIANTS["r12v2"] = replace(VARIANTS["r8v2"], standalone="centre")


def configs(base: R2Options, names: set[str]):
    drops = [("W1", base.drop("W1")), ("W2", base.drop("W2")), ("W3", replace(base, merge=0.45)),
             ("W4", replace(base, reassign=False)), ("band", replace(base, band=(20, 30))),
             ("W5", replace(base, unit_verdicts=False)), ("W6", replace(base, second_look=False)),
             ("U2", base.drop("U2")), ("U4", base.drop("U4")), ("U6", base.drop("U6")),
             ("N", replace(base, neutral=False, review="owner2")), ("C", replace(base, cause="")),
             ("E", replace(base, eac=0.0)), ("F", replace(base, cause_lift=0.0))]
    plan = [("R2", base)] + [(f"R2-{f}", o) for f, o in drops]
    return [(n, o) for n, o in plan if not names or n in names]


def run_one(name: str, opts: R2Options, end: str, slice_: str, out: Path, prepared: dict) -> dict:
    # Only the window and its vectors are shared between runs; the thresholds and the
    # cluster settings (band, U2, U6) come from this run's options.
    key = (opts.w1, opts.stack.u4, opts.instruction, opts.merge, opts.context, opts.neutral, opts.abtt, end)
    if key not in prepared:
        prepared[key] = prepare(end, opts)
    p = prepare_settings(prepared[key], opts)
    infos = []

    def fn(s):
        lab, info = cluster(p, s, opts)
        infos.append(info)
        return lab

    t = time.perf_counter()
    r = H.run_orders(fn, p.w, n=5, slice=slice_)
    labs = r.pop("labels")
    np.save(out / f"labels-{name}.npy", np.vstack(labs))
    r["infos"], r["opts"] = infos, asdict(opts)
    r["window"] = {"stream": p.w.stream, "units": len(p.w), "reviews": len(p.w.rows), "info": p.w.info}
    bars = [m["P"] >= 0.6 and m["R"] >= 0.6 and m["tone"] <= 1 and m["grab_bags"] <= 1 for m in r["measures"]]
    r["orders_passing"] = int(sum(bars))
    (out / f"{name}.json").write_text(json.dumps(r, indent=1, default=H._jsonable), encoding="utf-8")
    md, rg = r["median"], r["range"]
    print(f"{name:8s} {time.perf_counter() - t:6.1f}s units {len(p.w):4d}  "
          f"P {md['P']:.3f} [{rg['P'][0]:.3f}-{rg['P'][1]:.3f}]  R {md['R']:.3f} [{rg['R'][0]:.3f}-{rg['R'][1]:.3f}]  "
          f"tone {md['tone']} [{rg['tone'][0]}-{rg['tone'][1]}]  grab {md['grab_bags']} "
          f"[{rg['grab_bags'][0]}-{rg['grab_bags'][1]}]  split {md['split']}  ARI {r['ARI']:.3f}  "
          f"cov {md['coverage']:.2f} misc {md['misc_share']:.2f} gen {md['general_share']:.2f} "
          f"k {md['n_clusters']}  pass {r['orders_passing']}/5", flush=True)
    return r


END_V3 = "2024-10-31"
END_V4 = "2025-10-31"
END_V5 = "2025-06-30"
END_V6 = "2025-02-28"
_gold = H.gold


def _gold_any(w, slice="v1"):
    """V3 has unit-level labels (v3_gold.py); V1 and V2 the point labels of sel-v1/v2."""
    if slice == "v3":
        from trials.prellm import v3_gold
        return v3_gold.gold(w)
    if slice in ("v4", "v5", "v6"):
        from trials.prellm import unit_gold
        return unit_gold.gold(w, slice)
    return _gold(w, slice)


H.gold = _gold_any   # run_orders looks gold up at call time


def main():
    """round2.py VARIANT [runs...]       development on V1
       round2.py dev2-VARIANT [runs...]  development on V2 (spent as held-out since round 4)
       round2.py final-VARIANT           held-out V2 (round 4)
       round2.py final3-VARIANT          held-out V3, once (needs PRELLM_HELDOUT=1)
       round2.py dev3-VARIANT [runs...]  development on V3 (spent as held-out in round 5)
       round2.py final4-VARIANT          held-out V4, once (needs PRELLM_HELDOUT=1)"""
    variant = sys.argv[1]
    names = set(sys.argv[2:])
    mode, _, key = variant.partition("-") if "-" in variant else ("", "", variant)
    end, slice_ = {"": (END_DEV, "v1"), "dev2": (END_HELD, "v2"), "final": (END_HELD, "v2"),
                   "final3": (END_V3, "v3"), "dev3": (END_V3, "v3"), "final4": (END_V4, "v4"),
                   "dev4": (END_V4, "v4"), "final5": (END_V5, "v5"), "dev1": (END_DEV, "v1"),
                   "dev5": (END_V5, "v5"), "final6": (END_V6, "v6")}[mode]
    if mode in ("dev2", "dev3", "dev4", "dev5"):
        os.environ["PRELLM_HELDOUT"] = "1"   # V2 is development data from round 5 on
    base = VARIANTS[key]
    out = H.OUT / "R2" / variant
    out.mkdir(parents=True, exist_ok=True)
    prepared: dict = {}
    plan = [("R2", base)] if mode.startswith("final") else configs(base, names)
    for name, opts in plan:
        run_one(name, opts, end, slice_, out, prepared)


if __name__ == "__main__":
    main()
