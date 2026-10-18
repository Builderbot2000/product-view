"""Blind unit-level gold labels for a held-out month (as v3_gold.py, for any month).

    .venv/Scripts/python.exe -X utf8 trials/prellm/unit_gold.py sheet v4   # writes the label sheet
    # label trials/runs/prellm/<slice>/labels.txt:  <review_id> <seq> <labels...>
    from trials.prellm import unit_gold; g = unit_gold.gold(w, "v4")      # a harness.Gold

Every unit the method clusters (1-3 star stream, segments re-joined at 0.45) of 100
reviews sampled from the month is labelled from the review text alone, before any run
on the month. The sheet shows review text and units only: no clustering is run or read.
Labels: issue ids minted while labelling; G (general opinion, or customer support);
U (specific, no issue another review of the slice shares); N (not a complaint).
"""
from __future__ import annotations

import os
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trials.prellm import harness as H  # noqa: E402

# slice -> (window end, sampled months); V4's window is the newest whose 4 months overlap
# no earlier slice's window (rule set before the month was read). October 2025 alone has
# 61 reviews, so the draw is from the window's last two months, as V1 spans two.
SLICES = {"v4": ("2025-10-31", ("2025-09", "2025-10")),
          # V5 (round 7): the newest 4-month window overlapping no earlier slice, same draw rule
          "v5": ("2025-06-30", ("2025-05", "2025-06")),
          # V6 (round 11): Nov 2024-Feb 2025, between V3 and V5, same draw rule
          "v6": ("2025-02-28", ("2025-01", "2025-02")),
          # V7 (round 13): Mar-Jun 2024, the 4 months before V3, same draw rule
          "v7": ("2024-06-30", ("2024-05", "2024-06"))}


def slice_reviews(slice_: str) -> list[dict]:
    """100 reviews of the months, seed 0 (lloom.sample's draw, as v3_gold)."""
    months = SLICES[slice_][1]
    rows = H._db().execute(
        f"""SELECT r.review_id, COALESCE(t.content_en, r.content), r.score, r.created_at
             FROM reviews r LEFT JOIN cache.translations t USING (review_id)
            WHERE length(r.content) >= 20 AND substr(r.created_at, 1, 7) IN ({",".join("?" * len(months))})
            ORDER BY r.created_at DESC""", months).fetchall()
    if len(rows) > 100:
        rows = sorted(random.Random(0).sample(rows, 100), key=lambda r: r[3], reverse=True)
    return [dict(review_id=a, text=b, score=c, created_at=d) for a, b, c, d in rows]


def sheet(slice_: str) -> None:
    w = H.load_window(SLICES[slice_][0], 4, "negative", merge_threshold=0.45)
    revs = slice_reviews(slice_)
    d = H.OUT / slice_
    d.mkdir(parents=True, exist_ok=True)
    L = [f"# {slice_.upper()} unit label sheet (no clustering shown)", ""]
    n = 0
    for r in revs:
        units = [i for i in range(len(w)) if w.review_id[i] == r["review_id"]]
        if not units:
            continue
        L.append(f"\n### {r['review_id']} ({r['score']}★)\n{' '.join(r['text'].split())}")
        for i in units:
            n += 1
            L.append(f"{r['review_id']} {int(w.seq[i])} :: {' '.join(w.texts[i].split())}")
    (d / "label-sheet.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"{n} units from {sum(1 for r in revs if any(w.review_id == r['review_id']))} reviews "
          f"(of {len(revs)}; others are 4-5 stars or not in the stream)")


def gold(w: H.Window, slice_: str) -> H.Gold:
    if os.environ.get("PRELLM_HELDOUT") != "1":
        raise PermissionError(f"{slice_} is held out: set PRELLM_HELDOUT=1 only for the final run")
    lab = {}
    for line in (H.OUT / slice_ / "labels.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].split()
        if line:
            lab[(line[0], int(line[1]))] = frozenset(line[2:])
    unit_labels, points = {}, []
    for i, key in enumerate(zip(w.review_id.tolist(), w.seq.tolist())):
        if key in lab:
            unit_labels[i] = lab[key]
            issues = H._issues(lab[key])
            points.append(dict(n=len(points) + 1, review_id=key[0], stars=int(w.stars[i]), quote=w.texts[i],
                               labels=set(lab[key]), issues=issues, units=[i], status="unit"))
    missing = set(lab) - set(zip(w.review_id.tolist(), w.seq.tolist()))
    counts = dict(Counter(x for s in unit_labels.values() for x in s if x in "GUN"),
                  labelled_units=len(unit_labels), units_with_issue=sum(bool(p["issues"]) for p in points),
                  issue_points=sum(bool(p["issues"]) for p in points), labels_not_in_window=len(missing))
    return H.Gold(slice=slice_, unit_labels=unit_labels, points=points, counts=counts)


if __name__ == "__main__":
    if sys.argv[1] == "sheet":
        sheet(sys.argv[2])
