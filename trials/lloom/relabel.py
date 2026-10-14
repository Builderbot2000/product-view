"""Carry gold labels from a validated run to a re-run of the same slice (llm-trials.md,
"Cost controls"). Points are identical when distill is answered from the cache, so a
label keyed by point number still applies; concept ids are mapped by name + criterion.

    .venv/Scripts/python.exe -X utf8 trials/lloom/relabel.py trials/runs/sel-v1 trials/runs/cc-v1

Writes NEW/labels-carried.txt: the old labels under the new ids, labels naming a concept
the new run doesn't have dropped, and a header listing the new run's live issue concepts
that have no labels yet (to be labelled blind before `viability.py score`).
"""
import json
import sys
from pathlib import Path

from viability import load, parse

old, new = Path(sys.argv[1]), Path(sys.argv[2])
p_old, _, _ = load(old)
p_new, live_new, _ = load(new)
assert [b["id"] for b in p_old] == [b["id"] for b in p_new], "points differ: labels cannot carry over"
key = lambda c: (c["name"], c["criterion"])   # noqa: E731
every_old = json.loads((old / "concepts.json").read_text(encoding="utf-8"))
old_id = {key(c): c["id"] for c in every_old}
judged, dups, gold = parse(old / "labels.txt")
labelled = set(judged) | {x for g in gold.values() for x in g}
to_new = {old_id[key(c)]: c["id"] for c in live_new if key(c) in old_id}
fresh = [c for c in live_new if c["kind"] == "issue" and old_id.get(key(c)) not in labelled]
L = [f"# Carried from {old.name} by relabel.py. Concepts still to label blind:"]
L += [f"#   {c['id']} {c['name']}: {c['criterion']}" for c in fresh]
L += [f"concept {to_new[c]} {v}" for c, v in judged.items() if c in to_new]
L += [f"dup {to_new[a]} {to_new[b]}" for a, b in dups if a in to_new and b in to_new]
for n in sorted(gold):
    ids = [to_new[x] for x in gold[n] if x in to_new] + [x for x in gold[n] if x in "GUN"]
    L.append(f"{n} {' '.join(ids) or 'U'}")
(new / "labels-carried.txt").write_text("\n".join(L) + "\n", encoding="utf-8")
print(f"{len(to_new)} concepts mapped; {len(fresh)} live issue concepts need labels:")
for c in fresh:
    print(f"  {c['id']} {c['name']}: {c['criterion']}")
