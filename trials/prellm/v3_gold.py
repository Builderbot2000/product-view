"""Unit-level gold labels for the V3 held-out slice (llm-trials.md, round 4, "Decided
2026-10-14"): every unit of the 100 October 2024 reviews of sel-v3 that the method
clusters (1-3 star stream, segments re-joined at 0.45) is labelled from the review text
alone, so there are no X units.

    .venv/Scripts/python.exe -X utf8 trials/prellm/v3_gold.py sheet   # writes the label sheet
    # label trials/runs/prellm/v3/labels.txt:  <review_id> <seq> <labels...>
    from trials.prellm import v3_gold; g = v3_gold.gold(w)              # a harness.Gold

The sheet shows review text and units only: no clustering is run or read.
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trials.prellm import harness as H  # noqa: E402

END = "2024-10-31"
DIR = H.OUT / "v3"
SEL = H.SEL / "sel-v3"


def v3_ids() -> set[str]:
    return {json.loads(l)["review_id"] for l in (SEL / "bullets.jsonl").open(encoding="utf-8")} | {
        r["review_id"] for r in slice_reviews()}


def slice_reviews() -> list[dict]:
    """sel-v3's reviews: lloom.sample(100, month 2024-10, seed 0)."""
    import random
    db = H._db()
    rows = db.execute(
        """SELECT r.review_id, COALESCE(t.content_en, r.content), r.score, r.created_at
             FROM reviews r LEFT JOIN cache.translations t USING (review_id)
            WHERE length(r.content) >= 20 AND substr(r.created_at, 1, 7) = '2024-10'
            ORDER BY r.created_at DESC""").fetchall()
    if len(rows) > 100:
        rows = sorted(random.Random(0).sample(rows, 100), key=lambda r: r[3], reverse=True)
    return [dict(review_id=a, text=b, score=c, created_at=d) for a, b, c, d in rows]


def sheet() -> None:
    w = H.load_window(END, 4, "negative", merge_threshold=0.45)
    revs = slice_reviews()
    ids = {r["review_id"] for r in revs}
    concepts = [c for c in json.loads((SEL / "concepts.json").read_text(encoding="utf-8"))
                if c["status"] == "live"]
    DIR.mkdir(parents=True, exist_ok=True)
    L = ["# V3 unit label sheet (no clustering shown)", "", "## Concepts", ""]
    for c in concepts:
        L.append(f"- {c['id']} [{c['kind']}] {c['name']}: {c['criterion']}")
    L += ["", "Labels: issue concept ids; G (general opinion, or a general concept, or C006);"
          " U (specific, no concept); N (not a complaint).", "", "## Units", ""]
    n = 0
    for r in revs:
        units = [i for i in range(len(w)) if w.review_id[i] == r["review_id"]]
        if not units:
            continue
        L.append(f"\n### {r['review_id']} ({r['score']}★)\n{' '.join(r['text'].split())}")
        for i in units:
            n += 1
            L.append(f"{r['review_id']} {int(w.seq[i])} :: {' '.join(w.texts[i].split())}")
    (DIR / "label-sheet.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"{n} units from {sum(1 for r in revs if any(w.review_id == r['review_id']))} reviews "
          f"(of {len(revs)}; others are 4-5 stars or not in the stream)")


def gold(w: H.Window) -> H.Gold:
    if os.environ.get("PRELLM_HELDOUT") != "1":
        raise PermissionError("V3 is held out: set PRELLM_HELDOUT=1 only for the final run")
    lab = {}
    for line in (DIR / "labels.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].split()
        if line:
            lab[(line[0], int(line[1]))] = frozenset(line[2:])
    unit_labels, points = {}, []
    for i, key in enumerate(zip(w.review_id.tolist(), w.seq.tolist())):
        if key in lab:
            unit_labels[i] = lab[key]
            issues = H._issues(lab[key])
            # each labelled unit is its own "point" for recall
            points.append(dict(n=len(points) + 1, review_id=key[0], stars=int(w.stars[i]), quote=w.texts[i],
                               labels=set(lab[key]), issues=issues, units=[i], status="unit"))
    missing = set(lab) - set(zip(w.review_id.tolist(), w.seq.tolist()))
    counts = dict(Counter(x for s in unit_labels.values() for x in s if x in "GUN"),
                  labelled_units=len(unit_labels), units_with_issue=sum(bool(p["issues"]) for p in points),
                  issue_points=sum(bool(p["issues"]) for p in points), labels_not_in_window=len(missing))
    return H.Gold(slice="v3", unit_labels=unit_labels, points=points, counts=counts)


if __name__ == "__main__":
    if sys.argv[1] == "sheet":
        sheet()
