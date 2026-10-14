"""Save the final stack's dev clustering (order seed 0) and check a held-out-window
run without evaluating it.

    .venv/Scripts/python.exe -X utf8 trials/prellm/final_s.py            # dev save + tables
    .venv/Scripts/python.exe -X utf8 trials/prellm/final_s.py 2026-02-28 # counts only
"""
from __future__ import annotations

import os
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from trials.prellm import harness as H, stack as S  # noqa: E402


def dev():
    t = time.perf_counter()
    w, labels, info = S.run("2026-09-22", 0, S.FINAL)
    secs = time.perf_counter() - t
    names = H.titles(w, labels)
    m = H.evaluate(w, labels, "v1", names=names)
    path = H.save_clustering(H.OUT / "stack" / "clusters-dev.json", w, labels, measures=m,
                             names=names, extra={"opts": info["opts"], "order_seed": 0,
                                                 "step_info": {k: v for k, v in info.items() if k != "opts"},
                                                 "seconds": round(secs, 1)})
    print(path, f"{secs:.1f}s", {k: m[k] for k in ("P", "R", "tone", "grab_bags", "split", "coverage", "n_clusters")})
    print("| id | size | labelled | credited | P | majority | flags | title |")
    print("|---|---|---|---|---|---|---|---|")
    for r in m["clusters"]:
        flags = ",".join(f for f in ("tone", "grab_bag", "mostly_u") if r[f])
        p = "" if r["precision"] is None else f"{r['precision']:.0%}"
        print(f"| {r['id']} | {r['size']} | {r['labelled']} | {r['credited'] or ''} | {p} | {r['majority'] or ''} | {flags} | {r['title']} |")
    g = H.gold(w, "v1")
    for r in m["mostly_U"]:
        print(f"\n## mostly-U cluster {r['id']}: {r['title']}  keywords {names[r['id']]['keywords']}")
        for i in np.flatnonzero(labels == r["id"]):
            tag = sorted(g.unit_labels[i]) if i in g.unit_labels else ""
            print(f"  {tag} {w.texts[i][:140]}")
    print("general", int(np.sum(labels == H.GENERAL)), "misc", int(np.sum(labels == H.MISC)), "parents", info["parents"],
          "joins", info.get("joins"))


def counts(end: str):
    assert os.environ.get("PRELLM_HELDOUT") != "1" or end == "2026-09-22"
    t = time.perf_counter()
    w, labels, info = S.run(end, 0, S.FINAL)
    c = Counter(labels.tolist())
    print(f"window ending {end}: {len(w)} units, {len(w.rows)} reviews, "
          f"{sum(1 for l in c if l >= 0)} clusters, sizes {sorted((v for k, v in c.items() if k >= 0), reverse=True)}, "
          f"general {c.get(-2, 0)}, misc {c.get(-1, 0)}, {time.perf_counter() - t:.1f}s")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        counts(sys.argv[1])
    else:
        dev()
