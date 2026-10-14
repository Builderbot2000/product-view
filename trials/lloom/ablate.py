"""Score ablation for the cost controls (llm-trials.md, "Cost controls").

Scores the round-0 candidates of a validated run (trials/runs/sel-v1) on all of its
points under one scoring variant, with no selection afterwards, and compares the matches
with the gold labels. Isolates the scorer from everything else.

    .venv/Scripts/python.exe -X utf8 trials/lloom/ablate.py --batch 15            # the validated scorer (cached)
    .venv/Scripts/python.exe -X utf8 trials/lloom/ablate.py --batch 15 --compact
    .venv/Scripts/python.exe -X utf8 trials/lloom/ablate.py --batch 30
    .venv/Scripts/python.exe -X utf8 trials/lloom/ablate.py --batch 15 --nearest 10
"""
import argparse
import json
from pathlib import Path

import numpy as np

from concurrent.futures import ThreadPoolExecutor

from lloom import OUT, Model, OpenAIModel, score
from product_view.embed.encoder import encode
from viability import parse

ap = argparse.ArgumentParser()
ap.add_argument("--batch", type=int, default=15)
ap.add_argument("--compact", action="store_true")
ap.add_argument("--nearest", type=int, default=0)
ap.add_argument("--model", default="qwen3.5:9b", help="an Ollama model, or gpt-* through the OpenAI API")
ap.add_argument("--effort", default="none", help="gpt-*: reasoning_effort")
ap.add_argument("--anchor", action="store_true", help="scorer variant S1: the name sets the feature")
ap.add_argument("--feature", action="store_true", help="scorer variant S2: a yes/no feature check before the letter")
ap.add_argument("--run", default="sel-v1", help="sel-v1 (tuning) or sel-v2 (held out)")
ap.add_argument("--budget", type=float, default=1.0, help="gpt-*: stop before spending past this (USD)")
args = ap.parse_args()

run = OUT / args.run
bullets = {b["id"]: b for b in map(json.loads, (run / "bullets.jsonl").open(encoding="utf-8"))}
order = json.loads((run / "scores-complaint.json").read_text(encoding="utf-8"))["bullets"]
points = [bullets[i] for i in order]
# every round-0 candidate that went on to be scored (past the breadth check)
# sel-v2: every scored concept, carried V1 ones included (its labels cover them all)
cands = [c for c in json.loads((run / "concepts.json").read_text(encoding="utf-8"))
         if (c["round"] == 0 or args.run != "sel-v1") and c["status"] in ("live", "unselected")
         and c["kind"] == "issue"]
gold: dict[int, set] = {}
for f in [run / "labels.txt"] + ([OUT / "cc-v1" / "labels.txt"] if args.run == "sel-v1" else []):   # cc-v1: blind labels for unselected ones
    for n, g in parse(f)[2].items():
        gold.setdefault(n, set()).update(g)
labelled = {x for g in gold.values() for x in g}

which = {c["id"]: list(range(len(points))) for c in cands}
if args.nearest:
    vecs = encode([b["bullet"] for b in points], show_progress=False)
    cv = encode([f"{c['name']}. {c['criterion']}" for c in cands], show_progress=False)
    near = np.argsort(-(vecs @ cv.T), axis=1)[:, :args.nearest]
    for j, c in enumerate(cands):
        which[c["id"]] = sorted({i for i in range(len(points)) if j in near[i]} | set(c["built_from"]))

gpt = args.model.startswith("gpt")
m = OpenAIModel(args.model, args.effort, args.budget) if gpt else Model(args.model, OUT / f"lloom-calls-{args.model.replace(':', '_')}.jsonl")
tp = fp = fn = 0
strict = [0, 0]   # matches and right ones counting A only (threshold 1.0)
print(f"{args.model}{' (' + args.effort + ')' if gpt else ''} on {args.run}: batch {args.batch}, compact {args.compact}, "
      f"nearest {args.nearest}, anchor {args.anchor}, feature {args.feature}")
todo = [c for c in cands if c["id"] in labelled]
with ThreadPoolExecutor(16 if gpt else 1) as pool:   # the Ollama Model is not thread-safe
    scored = list(pool.map(lambda c: score(m, c, points, which[c["id"]], args.batch, args.compact, args.anchor, args.feature), todo))
for c, got in zip(todo, scored):
    hit = {i + 1 for i, v in got.items() if v >= 0.75}
    gt = {n for n, g in gold.items() if c["id"] in g}
    tp += len(hit & gt); fp += len(hit - gt); fn += len(gt - hit)
    a_only = {i + 1 for i, v in got.items() if v >= 1.0}
    strict[0] += len(a_only); strict[1] += len(a_only & gt)
    print(f"  {c['id']} {c['name'][:44]:44} matched {len(hit):3}  right {len(hit & gt):3}  of {len(gt):3}")
print(f"A only: precision {strict[1]}/{strict[0]} = {strict[1] / max(strict[0], 1):.0%}   "
      f"recall {strict[1]}/{tp + fn} = {strict[1] / (tp + fn):.0%}")
print(f"precision {tp}/{tp + fp} = {tp / (tp + fp):.0%}   recall {tp}/{tp + fn} = {tp / (tp + fn):.0%}   "
      f"({m.calls} calls made, {m.hits} cached{', ' + m.llm.spend() if gpt else ''})")
