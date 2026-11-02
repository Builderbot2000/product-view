"""Blind answer keys for matching reviews to the fixed topics (report-design.md §9).

    .venv/Scripts/python.exe -X utf8 trials/topics/key.py sheet t1    # writes the label sheet
    # label trials/runs/topics/<slice>/labels.txt:  <review_id> <seq> <labels...>

Every unit the method sees (1-3 star stream, segments re-joined at 0.45, as the
embedding-route trials) of 120 reviews drawn from the slice's window is labelled from
the review text alone, against the topic list in matrix.sample.yaml, before any run
on the window. Labels:
  <topic id>  the unit is a complaint about that topic (several allowed)
  O           a specific complaint no topic covers ("no topic" in the report)
  G           general opinion, praise, or a complaint with no feature named
  N           not a complaint (a question, a thank-you, noise)
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trials.prellm import harness as H  # noqa: E402

OUT = ROOT / "trials" / "runs" / "topics"
MATRIX = ROOT / "matrix.sample.yaml"
NON_TOPIC = {"O", "G", "N"}

# slice -> window end (4 months). T1 is the demo window (development); T2 is held out
# and labelled before any run on it.
SLICES = {"t1": "2026-09-22", "t2": "2024-06-30"}
DRAW = 120


def topics() -> dict:
    return yaml.safe_load(MATRIX.read_text(encoding="utf-8"))["topics"]


def window(slice_: str) -> H.Window:
    return H.load_window(SLICES[slice_], 4, "negative", merge_threshold=0.45)


def drawn(w: H.Window) -> list[str]:
    """DRAW reviews of the window's stream, seed 0."""
    ids = sorted({r["review_id"] for r in w.rows})
    return sorted(random.Random(0).sample(ids, min(DRAW, len(ids))))


def sheet(slice_: str) -> None:
    w = window(slice_)
    text = {r["review_id"]: r for r in w.rows}
    d = OUT / slice_
    d.mkdir(parents=True, exist_ok=True)
    L = [f"# {slice_.upper()} topic label sheet (window ends {SLICES[slice_]}; no matching shown)", ""]
    n = 0
    for rid in drawn(w):
        r = text[rid]
        L.append(f"\n### {rid} ({r['score']}★)\n{' '.join(r['text'].split())}")
        for i in [i for i in range(len(w)) if w.review_id[i] == rid]:
            n += 1
            L.append(f"{rid} {int(w.seq[i])} :: {' '.join(w.texts[i].split())}")
    (d / "label-sheet.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"{n} units from {DRAW} reviews; window has {len(w)} units, {len(w.rows)} reviews")


def load(slice_: str) -> dict[tuple[str, int], frozenset]:
    """(review_id, seq) -> labels; every label is a topic id or one of O, G, N."""
    known = set(topics()) | NON_TOPIC
    lab = {}
    for line in (OUT / slice_ / "labels.txt").read_text(encoding="utf-8").splitlines():
        parts = line.split("#")[0].split()
        if not parts:
            continue
        bad = set(parts[2:]) - known
        if bad or not parts[2:]:
            raise ValueError(f"{slice_}: bad labels {bad or 'none'} in: {line}")
        lab[(parts[0], int(parts[1]))] = frozenset(parts[2:])
    return lab


if __name__ == "__main__":
    if sys.argv[1] == "sheet":
        sheet(sys.argv[2])
