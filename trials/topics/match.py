"""Match review units to the fixed topics: zero-shot anchors, then seeded refinement.

    .venv/Scripts/python.exe -X utf8 trials/topics/match.py A t1     # variants A, B, C (topic-trials.md)

Writes trials/runs/topics/<slice>/<variant>.json (scores) and <variant>-sample.md
(matches to read). Embeds through Ollama on OLLAMA_HOST (default 127.0.0.1:11600);
PRELLM_CPU_EMBED=1 uses the much slower CPU build of the same model.
"""
from __future__ import annotations

import json
import os
import random
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("OLLAMA_HOST", "127.0.0.1:11600")

from trials.prellm import round2 as R  # noqa: E402
from trials.topics import key as K  # noqa: E402

INSTRUCTION = ("Given a sentence from a mobile banking app review, identify the app feature "
               "it complains about")
NULLS = ["This app is bad and I am unhappy with it", "I am going to switch to another bank",
         "It doesn't work", "Terrible service, very frustrating"]


@dataclass(frozen=True)
class Variant:
    margin: float = 0.0       # a topic must beat the best null anchor by this much
    delta: float = 0.03       # ... and be within this of the unit's best topic
    refine: int = 0           # iterations of seeded refinement (B)
    seed_margin: float = 0.05  # units this sure seed a refined anchor
    leftovers: bool = False   # C: cluster the unmatched units for reading
    examples: bool = False    # round 2: anchors from model-written example complaints
    knn: int = 0              # F: similarity = mean of the k nearest examples; 0 = prototype
    classifier: bool = False  # round 3: one-vs-rest logistic regression on the examples
    self_train: float = 0.0   # H: units at this probability join the training set; 0 = off


VARIANTS = {"A": Variant(), "B": Variant(refine=3), "C": Variant(refine=3, leftovers=True),
            "D": Variant(examples=True), "E": Variant(examples=True, refine=3),
            "F": Variant(examples=True, knn=3),
            "G": Variant(examples=True, classifier=True),
            "H": Variant(examples=True, classifier=True, self_train=0.9)}

EXPAND = """You help a product team sort reviews of their mobile banking app by app feature.

Feature: {name}
What it covers: {description}

Other features on the list, which are NOT this one: {siblings}

Write {n} short complaints, one per line, that a user might post in an app store review about this feature and no other on the list. Vary the wording, length and tone the way real reviews do (some angry, some plain, some with typos); describe problems, missing options and annoyances. Write only the complaints, no numbering."""

EXPAND_NULL = """You help a product team sort reviews of their mobile banking app by app feature.

Write {n} short complaints, one per line, that a user might post in an app store review WITHOUT naming any feature of the app: general anger, the app or bank being bad, leaving for another bank, "it doesn't work", sarcasm, demands to fix it. Vary the wording, length and tone the way real reviews do. Write only the complaints, no numbering."""
EXPAND_OFFLIST = """You help a product team sort reviews of their mobile banking app by app feature.

The team's feature list is: {names}

Write {n} short complaints, one per line, that a user might post in an app store review about a feature or part of a banking app or bank that is NOT on this list. Cover many different features. Vary the wording, length and tone the way real reviews do. Write only the complaints, no numbering."""
N_EXAMPLES = 12


def _chat(prompt: str) -> str:
    import urllib.request
    body = json.dumps({"model": "qwen3.5:9b", "stream": False, "think": False,
                       "options": {"temperature": 0.0, "seed": 0},
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(f"{R.OLLAMA}/api/chat", body, {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=600))["message"]["content"]


def _lines(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        line = line.strip().lstrip("-*•0123456789.) ").strip().strip('"')
        if len(line) >= 8:
            out.append(line)
    return out


def expansions(topics: dict) -> dict[str, list[str]]:
    """Example complaints per topic and for the null class: one model call each, cached."""
    path = K.OUT / "expansions.json"
    have = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    names = {t: topics[t]["name"] for t in topics}
    prompts = {t: EXPAND.format(name=names[t], description=topics[t]["description"], n=N_EXAMPLES,
                                siblings="; ".join(n for x, n in names.items() if x != t))
               for t in topics}
    prompts["_null"] = EXPAND_NULL.format(n=N_EXAMPLES)
    prompts["_offlist"] = EXPAND_OFFLIST.format(n=2 * N_EXAMPLES, names="; ".join(names.values()))
    for t, prompt in prompts.items():
        if have.get(t, {}).get("prompt") != prompt:
            have[t] = {"prompt": prompt, "examples": _lines(_chat(prompt))}
            print(f"  expanded {t}: {len(have[t]['examples'])} examples", flush=True)
    path.write_text(json.dumps(have, indent=1, ensure_ascii=False), encoding="utf-8")
    return {t: have[t]["examples"] for t in prompts}


def documents(texts: list[str]) -> np.ndarray:
    """Anchors are documents: no instruction (Qwen3-Embedding's query/document split)."""
    if os.environ.get("PRELLM_CPU_EMBED") == "1":
        v = R._embedder().encode(texts, normalize_embeddings=True, convert_to_numpy=True,
                                 show_progress_bar=False)
    else:
        import urllib.request
        body = json.dumps({"model": R.GPU_EMBEDDER, "input": texts}).encode()
        req = urllib.request.Request(f"{R.OLLAMA}/api/embed", body, {"Content-Type": "application/json"})
        v = _unit(np.array(json.load(urllib.request.urlopen(req, timeout=600))["embeddings"]))
    return np.ascontiguousarray(v, dtype=np.float32)


def _unit(v: np.ndarray) -> np.ndarray:
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def _sim(U: np.ndarray, A, knn: int) -> np.ndarray:
    """(units, anchors): cosine to each anchor; an anchor given as an example set scores
    the mean of its knn nearest examples."""
    if not knn:
        return U @ np.asarray(A).T
    return np.stack([np.sort(U @ E.T, axis=1)[:, -min(knn, len(E)):].mean(axis=1) for E in A], axis=1)


def assign(U: np.ndarray, T, Z, v: Variant):
    """Boolean (units, topics) matches, and each unit's best topic margin over the null."""
    sim = _sim(U, T, v.knn)
    null = _sim(U, Z, v.knn).max(axis=1)
    margin = sim - null[:, None]
    best = sim.max(axis=1, keepdims=True)
    return (margin >= v.margin) & (sim >= best - v.delta), margin


def match(U: np.ndarray, T0: np.ndarray, Z0: np.ndarray, v: Variant):
    T, Z = T0.copy(), Z0.copy()
    M, margin = assign(U, T, Z, v)
    for _ in range(v.refine):
        for t in range(len(T)):
            seeds = M[:, t] & (margin[:, t] >= v.seed_margin)
            if seeds.any():
                T[t] = _unit(T0[t] + _unit(U[seeds].mean(axis=0)))
        sure_null = margin.max(axis=1) <= -v.seed_margin
        if sure_null.any():
            Z = np.vstack([Z0, _unit(U[sure_null].mean(axis=0))])
        M, margin = assign(U, T, Z, v)
    return M, margin


def classify(U: np.ndarray, sets: list, negatives: np.ndarray, v: Variant):
    """One-vs-rest logistic regression on the example embeddings; (units, topics) matches
    at probability >= 0.5, and the probabilities (returned as the 'margin', minus 0.5)."""
    from sklearn.linear_model import LogisticRegression
    X = np.vstack([*sets, negatives])
    y = np.concatenate([np.full(len(E), t) for t, E in enumerate(sets)] + [np.full(len(negatives), -1)])
    Y = np.stack([y == t for t in range(len(sets))], axis=1)

    def fit_predict(X, Y):
        P = np.zeros((len(U), Y.shape[1]))
        for t in range(Y.shape[1]):
            clf = LogisticRegression(C=1.0, class_weight="balanced", max_iter=2000).fit(X, Y[:, t])
            P[:, t] = clf.predict_proba(U)[:, 1]
        return P

    P = fit_predict(X, Y)
    if v.self_train:
        sure = P >= v.self_train
        X2 = np.vstack([X, U[sure.any(axis=1)]])
        Y2 = np.vstack([Y, sure[sure.any(axis=1)]])
        P = fit_predict(X2, Y2)
    return P >= 0.5, P - 0.5


def score(w, M: np.ndarray, ids: list[str], lab: dict) -> dict:
    drawn = set(K.drawn(w))
    got, want = defaultdict(set), defaultdict(set)
    for i, (rid, seq) in enumerate(w.keys):
        if rid in drawn:
            got[rid] |= {ids[t] for t in np.flatnonzero(M[i])}
    for (rid, _), labels in lab.items():
        want[rid] |= labels - K.NON_TOPIC
    pairs_got = {(r, t) for r in drawn for t in got[r]}
    pairs_want = {(r, t) for r in drawn for t in want[r]}
    tp = len(pairs_got & pairs_want)
    no_topic = [r for r in drawn if not want[r]]
    per = {}
    for t in ids:
        g = {r for r, x in pairs_got if x == t}
        k = {r for r, x in pairs_want if x == t}
        if len(k) >= 3:
            per[t] = dict(key=len(k), got=len(g), P=len(g & k) / len(g) if g else None,
                          R=len(g & k) / len(k))
    # unit level, for diagnosis
    idx = {key: i for i, key in enumerate(w.keys)}
    ut = ug = uw = 0
    for key_, labels in lab.items():
        i = idx.get(key_)
        if i is None:
            continue
        gt = {ids[t] for t in np.flatnonzero(M[i])}
        wt = labels - K.NON_TOPIC
        ut, ug, uw = ut + len(gt & wt), ug + len(gt), uw + len(wt)
    return dict(
        M1_precision=tp / len(pairs_got) if pairs_got else 0.0,
        M2_recall=tp / len(pairs_want),
        M3_false_alarm=sum(bool(got[r]) for r in no_topic) / len(no_topic),
        pairs=dict(got=len(pairs_got), key=len(pairs_want), right=tp),
        no_topic_reviews=len(no_topic), unit_P=ut / ug if ug else 0.0, unit_R=ut / uw,
        window_units=len(w), window_unmatched=int((~M.any(axis=1)).sum()), per_topic=per)


def sample_md(w, M, margin, ids, names, lab, v: Variant, rng: random.Random) -> str:
    L = []
    for t, tid in enumerate(ids):
        members = np.flatnonzero(M[:, t])
        L.append(f"\n## {names[tid]} ({tid}): {len(members)} units")
        for i in rng.sample(list(members), min(8, len(members))):
            mark = ""
            if w.keys[i] in lab:
                mark = " ✓" if tid in lab[w.keys[i]] else f" ✗ key: {' '.join(sorted(lab[w.keys[i]]))}"
            L.append(f"- {margin[i, t]:+.3f} {' '.join(w.texts[i].split())[:160]}{mark}")
    un = np.flatnonzero(~M.any(axis=1))
    L.append(f"\n## No topic: {len(un)} units")
    if v.leftovers and len(un) > 5:
        from scipy.cluster.hierarchy import fcluster, linkage
        U = w.vec_topics[un]
        cl = fcluster(linkage(U, method="average", metric="cosine"), t=0.45, criterion="distance")
        groups = sorted(((c, un[cl == c]) for c in set(cl)), key=lambda x: -len(x[1]))
        for c, mem in [g for g in groups if len(g[1]) >= 4][:15]:
            L.append(f"\n### group of {len(mem)}")
            for i in mem[:6]:
                L.append(f"- {' '.join(w.texts[i].split())[:160]}")
    else:
        for i in rng.sample(list(un), min(15, len(un))):
            L.append(f"- {' '.join(w.texts[i].split())[:160]}")
    return "\n".join(L) + "\n"


def main(name: str, slice_: str = "t1") -> None:
    v = VARIANTS[name]
    if slice_ != "t1" and os.environ.get("TOPICS_HELDOUT") != "1":
        raise PermissionError(f"{slice_} is held out: set TOPICS_HELDOUT=1 only for the final run")
    topics = K.topics()
    ids = list(topics)
    names = {t: topics[t]["name"] for t in ids}
    w = K.window(slice_)
    U = R.embed(w.texts, INSTRUCTION)
    w.vec_topics = U
    if v.examples:
        ex = expansions(topics)
        sets = [R.embed(ex[t], INSTRUCTION) for t in ids]
        null = R.embed(ex["_null"], INSTRUCTION)
        if v.classifier:
            neg = np.vstack([null, R.embed(ex["_offlist"], INSTRUCTION)])
            T0 = Z0 = None
        elif v.knn:
            T0, Z0 = sets, [null]
        else:
            T0 = np.stack([_unit(E.mean(axis=0)) for E in sets])
            Z0 = _unit(null.mean(axis=0))[None, :]
    else:
        T0 = documents([f"{topics[t]['name']}: {topics[t]['description']}" for t in ids])
        Z0 = documents(NULLS)
    M, margin = classify(U, sets, neg, v) if v.classifier else match(U, T0, Z0, v)
    lab = K.load(slice_)
    s = score(w, M, ids, lab)
    d = K.OUT / slice_
    (d / f"{name}.json").write_text(json.dumps(s, indent=1), encoding="utf-8")
    (d / f"{name}-sample.md").write_text(
        sample_md(w, M, margin, ids, names, lab, v, random.Random(0)), encoding="utf-8")
    print(f"{name} on {slice_}: P {s['M1_precision']:.0%}  R {s['M2_recall']:.0%}  "
          f"false alarm {s['M3_false_alarm']:.0%} ({s['no_topic_reviews']} no-topic reviews)  "
          f"pairs {s['pairs']}  unit P {s['unit_P']:.0%} R {s['unit_R']:.0%}  "
          f"unmatched {s['window_unmatched']}/{s['window_units']}")
    for t, p in s["per_topic"].items():
        print(f"  {t:24} key {p['key']:2}  got {p['got']:2}  "
              f"P {'-' if p['P'] is None else f'{p[chr(80)]:.0%}':>4}  R {p['R']:.0%}")


if __name__ == "__main__":
    main(*sys.argv[1:])
