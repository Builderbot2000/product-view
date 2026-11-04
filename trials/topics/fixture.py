"""Write the acceptance check's fixtures (production-plan.md step 4) from the trial data.

    .venv/Scripts/python.exe -X utf8 trials/topics/fixture.py

For each answer key (t1: development, t2: held out) it writes every complaint review
of the key's window as the trials read it, and copies the key. With them, the 22
topics the keys were labelled against, frozen. `pv check-matching` reads only these.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trials.topics import key as K  # noqa: E402

DST = ROOT / "src" / "product_view" / "topics" / "acceptance"


def main() -> None:
    DST.mkdir(parents=True, exist_ok=True)
    topics = K.topics()
    (DST / "topics.yaml").write_text(
        "# The 22 topics both answer keys were labelled against (matrix.sample.yaml,\n"
        "# 2026-11-02). Frozen: the check scores against these, whatever matrix is deployed.\n"
        + yaml.safe_dump({"topics": topics}, sort_keys=False, allow_unicode=True, width=1000),
        encoding="utf-8")
    for s in K.SLICES:
        w = K.window(s)
        with (DST / f"{s}.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
            for r in sorted(w.rows, key=lambda r: r["review_id"]):
                fh.write(json.dumps({"review_id": r["review_id"], "created_at": r["created_at"],
                                     "score": r["score"], "text": r["text"]},
                                    ensure_ascii=False) + "\n")
        shutil.copyfile(K.OUT / s / "labels.txt", DST / f"{s}.key")
        drawn = set(K.drawn(w))
        keyed = {l.split()[0] for l in (K.OUT / s / "labels.txt").read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.startswith("#")}
        assert drawn == keyed, f"{s}: key reviews differ from the drawn reviews"
        print(f"{s}: window {w.start} .. {K.SLICES[s]}, {len(w.rows)} reviews, {len(drawn)} keyed")


if __name__ == "__main__":
    main()
