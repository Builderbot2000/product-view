"""Spike: cluster LLM-extracted problem statements with the production graph code.

Reads the JSONL from spike/llm_refine.py (or llm_extract.py), embeds each extracted problem, builds
the kNN graph and runs Leiden at several resolutions with a range cap that sets
isolated statements aside as Miscellaneous. Prints groups by distinct reviews.

    .venv/Scripts/python.exe -X utf8 spike/llm_cluster.py out/llm-spike/extract-qwen3.5_9b-v4-recent-refined-v2.jsonl --show 4
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from product_view.cluster.graph import build_knn, centroid
from product_view.cluster.strategies import LeidenStrategy
from product_view.embed.encoder import encode


MISC = -1


def capped_labels(vecs, strategy, res, k, reach, pull):
    """Leiden labels with a range cap. A statement whose 3rd-nearest neighbour
    is less similar than `reach` has no neighbourhood and goes to MISC before
    clustering; after clustering, a member less similar than `pull` to its
    cluster's centre goes to MISC too."""
    n = len(vecs)
    labels = np.full(n, MISC, dtype=np.int32)
    third = build_knn(vecs, k).similarities[:, min(2, k - 1)]
    keep = np.where(third >= reach)[0]
    sub = vecs[keep]
    got = strategy.fit(sub, build_knn(sub, k), res)
    for lab in np.unique(got):
        members = np.where(got == lab)[0]
        sims = sub[members] @ centroid(sub[members])
        ok = members[sims >= pull]
        labels[keep[ok]] = lab
    return labels


def groups_of(labels, issues):
    g = defaultdict(list)
    for lab, item in zip(labels, issues):
        g[int(lab)].append(item)
    misc = g.pop(MISC, [])
    return sorted(g.values(), key=lambda m: -len({r for r, _ in m})), misc


def summary(name, groups, misc, min_reviews):
    sizes = [len({r for r, _ in m}) for m in groups]
    big = [s for s in sizes if s >= min_reviews]
    print(f"{name}: {len(groups)} groups, {len(big)} with >={min_reviews} reviews; "
          f"misc {len(misc)} statements; top sizes {sizes[:10]}")


def show(groups, misc, min_reviews, limit):
    for m in groups[:limit]:
        rids = {r for r, _ in m}
        if len(rids) < min_reviews:
            continue
        ph = Counter(p.lower() for _, p in m)
        print(f"\n[{len(rids)}] {ph.most_common(1)[0][0]}")
        print("    " + "; ".join(p for p, _ in ph.most_common(6)))
    print(f"\n[MISC {len(misc)}]")
    print("    " + "; ".join(p for _, p in misc[:40]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl", type=Path)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--min", type=int, default=3)
    ap.add_argument("--reach", type=float, default=0.4, help="3rd-neighbour similarity floor")
    ap.add_argument("--pull", type=float, default=0.4, help="member-to-centre similarity floor")
    ap.add_argument("--show", type=float, default=None, help="resolution to print in full")
    args = ap.parse_args()

    rows = [json.loads(l) for l in args.jsonl.open(encoding="utf-8")]
    issues = [(r["review_id"], i["problem"]) for r in rows for i in r["extraction"]["issues"]]
    vecs = encode([p for _, p in issues], show_progress=False)
    print(f"{len(rows)} reviews, {len(issues)} problems, reach>={args.reach} pull>={args.pull}\n")

    leiden = LeidenStrategy(seed=42)
    for res in (1, 2, 4, 8):
        lab = capped_labels(vecs, leiden, res, args.k, args.reach, args.pull)
        summary(f"leiden res={res}", *groups_of(lab, issues), args.min)

    if args.show is not None:
        print(f"\n===== leiden res={args.show} =====")
        lab = capped_labels(vecs, leiden, args.show, args.k, args.reach, args.pull)
        show(*groups_of(lab, issues), args.min, 40)


if __name__ == "__main__":
    main()
