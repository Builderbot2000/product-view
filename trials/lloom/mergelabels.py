"""Merge labels-carried.txt with blind labels for new concepts (labels-new.txt) into labels.txt.

labels-new.txt: `concept Cxxx verdict` lines, and `Cxxx n n n ...` (the points that concept covers).
A point given a concept loses its G / U / N mark.

    .venv/Scripts/python.exe -X utf8 trials/lloom/mergelabels.py trials/runs/cc-v1
"""
import sys
from pathlib import Path

d = Path(sys.argv[1])
head, gold, add = [], {}, {}
for line in (d / "labels-carried.txt").read_text(encoding="utf-8").splitlines():
    parts = line.split("#")[0].split()
    if parts and parts[0].isdigit():
        gold[int(parts[0])] = parts[1:]
    else:
        head.append(line)
for line in (d / "labels-new.txt").read_text(encoding="utf-8").splitlines():
    parts = line.split("#")[0].split()
    if not parts:
        continue
    if parts[0] == "concept":
        head.append(line)
    else:
        for n in map(int, parts[1:]):
            add.setdefault(n, []).append(parts[0])
for n, cs in add.items():
    gold[n] = [x for x in gold[n] if x not in ("G", "U", "N")] + cs
(d / "labels.txt").write_text("\n".join(head + [f"{n} {' '.join(gold[n])}" for n in sorted(gold)]) + "\n",
                              encoding="utf-8")
print(len(gold), "points;", sum(map(len, add.values())), "new concept labels")
