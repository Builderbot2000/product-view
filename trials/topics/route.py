"""Round 4: the classifier (H) decides sure units; the local model decides ambiguous ones.

    .venv/Scripts/python.exe -X utf8 trials/topics/route.py I     # one unit per call
    .venv/Scripts/python.exe -X utf8 trials/topics/route.py J     # 10 units per call

Model answers are cached in trials/runs/topics/llm-cache.json by prompt, so a rerun
costs nothing; timings are of the first, uncached run.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("OLLAMA_HOST", "127.0.0.1:11600")  # before round2 reads it

from trials.prellm import round2 as R  # noqa: E402
from trials.topics import key as K, match as Mt  # noqa: E402

SURE, SECOND, NONE = 0.8, 0.5, 0.4    # gate (topic-trials.md, round 4)
OPTION_P, MAX_OPTIONS, CONTEXT = 0.3, 5, 400
BATCH = {"I": 1, "J": 10, "K": 1, "L": 5, "M": 1, "N": 1, "O": 1}
NONE_OPTION = {"K", "L"}   # round 5: every item ends with an explicit "none" option
MISC_WEAK = {"M": 0.6, "O": 0.6}   # round 6: misc below this best-topic probability
MISC_GENERIC = {"N", "O"}          # round 6: misc if nearer the generic examples than the best topic's
CACHE = K.OUT / "llm-cache.json"

PROMPT = """You sort complaints from app store reviews of a mobile banking app by app feature.

For each item below you get one sentence from a review (SENTENCE), the whole review for \
context (REVIEW), and a short list of candidate features (OPTIONS). Say which of the options \
the SENTENCE itself complains about. Choose several only if the sentence clearly complains \
about each; choose none if it is general opinion, praise, or about something not in its \
options. Use the review only to understand what the sentence refers to.

{items}

Answer with one entry per item, using the item numbers and the option ids."""

ITEM = """ITEM {n}
SENTENCE: {sentence}
REVIEW: {review}
OPTIONS:
{options}"""

SCHEMA = {"type": "object", "properties": {"answers": {"type": "array", "items": {
    "type": "object", "properties": {"item": {"type": "integer"},
                                     "topics": {"type": "array", "items": {"type": "string"}}},
    "required": ["item", "topics"]}}}, "required": ["answers"]}


def _chat(prompt: str, cache: dict) -> tuple[dict, bool]:
    key = hashlib.sha1(prompt.encode("utf-8")).hexdigest()
    if key in cache:
        return cache[key], False
    body = json.dumps({"model": "qwen3.5:9b", "stream": False, "think": False, "format": SCHEMA,
                       "options": {"temperature": 0.0, "seed": 0, "num_ctx": 16384},
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(f"{R.OLLAMA}/api/chat", body, {"Content-Type": "application/json"})
    out = json.loads(json.load(urllib.request.urlopen(req, timeout=900))["message"]["content"])
    cache[key] = out
    return out, True


def gate(P: np.ndarray):
    s = np.sort(P, axis=1)
    p1, p2 = s[:, -1], s[:, -2]
    sure = (p1 >= SURE) & (p2 < SECOND)
    none = p1 < NONE
    return sure, none, ~(sure | none)


def main(name: str, slice_: str = "t1") -> None:
    batch = BATCH[name]
    topics = K.topics()
    ids = list(topics)
    w = K.window(slice_)
    U = R.embed(w.texts, Mt.INSTRUCTION)
    ex = Mt.expansions(topics)
    sets = [R.embed(ex[t], Mt.INSTRUCTION) for t in ids]
    neg = np.vstack([R.embed(ex["_null"], Mt.INSTRUCTION), R.embed(ex["_offlist"], Mt.INSTRUCTION)])
    _, P = Mt.classify(U, sets, neg, Mt.VARIANTS["H"])
    P = P + 0.5
    sure, none, amb = gate(P)
    misc = np.zeros(len(P), dtype=bool)
    if name in MISC_WEAK:
        misc |= ~none & (P.max(axis=1) < MISC_WEAK[name])
    if name in MISC_GENERIC:
        def unit(X):
            return X / np.linalg.norm(X, axis=1, keepdims=True)

        def near(E):
            return (unit(U) @ unit(E).T).max(axis=1)
        best = P.argmax(axis=1)
        own = np.stack([near(sets[t]) for t in range(len(ids))], axis=1)[np.arange(len(P)), best]
        misc |= ~none & (near(R.embed(ex["_null"], Mt.INSTRUCTION)) > own)
    sure, amb = sure & ~misc, amb & ~misc

    M = np.zeros_like(P, dtype=bool)
    M[sure, P[sure].argmax(axis=1)] = True
    review = {r["review_id"]: " ".join(r["text"].split()) for r in w.rows}
    todo = np.flatnonzero(amb)
    options = {}
    for i in todo:
        order = [t for t in np.argsort(-P[i]) if P[i, t] >= OPTION_P][:MAX_OPTIONS]
        options[i] = order or [int(P[i].argmax())]

    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    t0, calls, fresh, bad = time.perf_counter(), 0, 0, 0
    for start in range(0, len(todo), batch):
        chunk = todo[start:start + batch]
        items = []
        for n, i in enumerate(chunk, 1):
            opts = "\n".join(f"- {ids[t]}: {topics[ids[t]]['name']} ({topics[ids[t]]['description']})"
                             for t in options[i])
            if name in NONE_OPTION:
                opts += "\n- none: general opinion or praise, or a problem with something not listed above"
            text = review[w.review_id[i]]
            items.append(ITEM.format(n=n, sentence=" ".join(w.texts[i].split()), options=opts,
                                     review=text[:CONTEXT] + ("…" if len(text) > CONTEXT else "")))
        out, new = _chat(PROMPT.format(items="\n\n".join(items)), cache)
        calls, fresh = calls + 1, fresh + new
        got = {a.get("item"): a.get("topics", []) for a in out.get("answers", [])}
        for n, i in enumerate(chunk, 1):
            allowed = {ids[t]: t for t in options[i]}
            for tid in got.get(n, []):
                if tid in allowed:
                    M[i, allowed[tid]] = True
                elif tid != "none":
                    bad += 1
        if fresh and calls % 10 == 0:
            CACHE.write_text(json.dumps(cache), encoding="utf-8")
            print(f"  {start + len(chunk)}/{len(todo)} units, {time.perf_counter() - t0:.0f}s", flush=True)
    CACHE.write_text(json.dumps(cache), encoding="utf-8")
    secs = time.perf_counter() - t0

    lab = K.load(slice_)
    s = Mt.score(w, M, ids, lab)
    s.update(routed=int(amb.sum()), sure=int(sure.sum()), none=int(none.sum()), calls=calls,
             misc_units=int(misc.sum()), misc_reviews=len({w.review_id[i] for i in np.flatnonzero(misc)}),
             fresh_calls=fresh, seconds=round(secs, 1), off_option_answers=bad, batch=batch)
    d = K.OUT / slice_
    (d / f"{name}.json").write_text(json.dumps(s, indent=1), encoding="utf-8")
    np.save(d / f"{name}-matches.npy", M)
    (d / f"{name}-sample.md").write_text(
        Mt.sample_md(w, M, np.where(M, 1.0, 0.0), ids, {t: topics[t]["name"] for t in ids}, lab,
                     Mt.VARIANTS["H"], random.Random(0)), encoding="utf-8")
    print(f"{name} on {slice_}: P {s['M1_precision']:.0%}  R {s['M2_recall']:.0%}  "
          f"false alarm {s['M3_false_alarm']:.0%}  pairs {s['pairs']}  unit P {s['unit_P']:.0%} "
          f"R {s['unit_R']:.0%}\n  routed {s['routed']}/{len(w)} units in {calls} calls "
          f"({fresh} new), {secs:.0f}s; answers outside the options: {bad}; "
          f"misc {s['misc_units']} units / {s['misc_reviews']} reviews")
    for t, p in s["per_topic"].items():
        print(f"  {t:24} key {p['key']:2}  got {p['got']:2}  "
              f"P {'-' if p['P'] is None else format(p['P'], '.0%'):>4}  R {p['R']:.0%}")


if __name__ == "__main__":
    main(*sys.argv[1:])
