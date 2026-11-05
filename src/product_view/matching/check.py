"""`pv check-matching`: the acceptance check for a deployment's models
(production-plan.md step 4).

A new host brings a new chat model, and maybe another build of the embedding
model. Before go-live, and after any model change, this runs the configured
models through the same matching code as `pv match` on two fixed windows and
scores the result against hand-written answer keys:

- t1, the development window (2026-05-24 .. 2026-09-22, 294 complaint reviews);
- t2, the held-out window (2024-03-01 .. 2024-06-30, 204 complaint reviews).

Each key labels every review of 120 drawn from its window. The whole window is
matched, not just those 120, because the classifier trains on every unit it
sees (self-training); scoring then reads only the keyed reviews.

The fixtures ship inside the package (matching/acceptance/): the reviews (public
app-store text), the keys (review ids and labels) and the 22 topics the keys
were labelled against. The check uses those topics, never the deployed matrix,
so it runs before the real matrix exists and its result means the same thing
on every host.

Scores, per review and topic pair, as in the trials (trials/topics/match.py):
  precision    matched pairs the key agrees with
  recall       key pairs that were matched
  false alarm  keyed reviews with no topic that got one anyway
Pass: precision >= 70%, recall >= 60%, false alarm <= 25%, on both windows.
The method itself scored 84 / 67 / 13 on t1 and 78 / 65 / 12 on t2.

`--matrix FILE` scores that file's topic descriptions instead of the frozen
ones, for working on descriptions: it must have the same 22 topic ids, since
the keys are written against them. t1 is the window the demo reports come
from, so judge description changes on t2.

Exit 0 on a pass, 1 on a fail or an error. Each run is written to
<data_dir>/checks/<time>.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path

from .. import matrix as mx
from ..llm import LLMError
from ..matrix import Topic
from .embed import EmbedError
from .run import match_reviews, open_embedder, open_llm

WINDOWS = {"t1": "development", "t2": "held out"}
PASS = {"precision": 0.70, "recall": 0.60, "false_alarm": 0.25}
METHOD = {"t1": (0.84, 0.67, 0.13), "t2": (0.78, 0.65, 0.12)}   # validated scores
NON_TOPIC = {"O", "G", "N"}   # labels: no topic fits / general opinion / not a complaint


def _fixture(name: str) -> str:
    return resources.files(__package__).joinpath("acceptance", name).read_text(encoding="utf-8")


def topics() -> dict[str, Topic]:
    import yaml

    data = yaml.safe_load(_fixture("topics.yaml"))["topics"]
    return {tid: Topic(tid, t["name"], " ".join(t["description"].split()))
            for tid, t in data.items()}


def reviews(window: str) -> list[tuple[str, str]]:
    rows = [json.loads(line) for line in _fixture(f"{window}.jsonl").splitlines() if line.strip()]
    return [(r["review_id"], r["text"]) for r in rows]


def key(window: str, known: set[str]) -> dict[str, set[str]]:
    """review id -> the topics the key gives it (empty: no topic)."""
    want: dict[str, set[str]] = {}
    for line in _fixture(f"{window}.key").splitlines():
        parts = line.split("#")[0].split()
        if not parts:
            continue
        labels = set(parts[2:])
        bad = labels - known - NON_TOPIC
        if bad or not labels:
            raise ValueError(f"{window}.key: bad labels {bad or 'none'} in: {line}")
        want.setdefault(parts[0], set()).update(labels - NON_TOPIC)
    return want


@dataclass
class Score:
    precision: float
    recall: float
    false_alarm: float
    pairs_got: int
    pairs_key: int
    pairs_right: int
    no_topic_reviews: int

    @property
    def passed(self) -> bool:
        return (self.precision >= PASS["precision"] and self.recall >= PASS["recall"]
                and self.false_alarm <= PASS["false_alarm"])


def score(got: dict[str, set[str]], want: dict[str, set[str]]) -> Score:
    pg = {(r, t) for r in want for t in got.get(r, ())}
    pw = {(r, t) for r, ts in want.items() for t in ts}
    right = len(pg & pw)
    none = [r for r, ts in want.items() if not ts]
    return Score(precision=right / len(pg) if pg else 0.0,
                 recall=right / len(pw) if pw else 0.0,
                 false_alarm=sum(bool(got.get(r)) for r in none) / len(none) if none else 0.0,
                 pairs_got=len(pg), pairs_key=len(pw), pairs_right=right,
                 no_topic_reviews=len(none))


def _detail(window: str, got: dict, want: dict, text: dict) -> None:
    """Every keyed review the matching got wrong: topics missed and topics added."""
    for rid in sorted(want):
        g, k = got.get(rid, set()), want[rid]
        if g != k:
            print(f"    {rid[:8]} missed {sorted(k - g) or '-'} added {sorted(g - k) or '-'} | "
                  f"{' '.join(text[rid].split())[:160]}")


def cmd_check(args: argparse.Namespace) -> int:
    tmap = topics()
    if args.matrix:
        try:
            cand = mx.load(args.matrix).topics
        except mx.MatrixError as exc:
            print(f"check-matching: {exc}", file=sys.stderr)
            return 2
        if set(cand) != set(tmap):
            print(f"check-matching: {args.matrix} must have the keys' {len(tmap)} topic ids; "
                  f"missing {sorted(set(tmap) - set(cand))}, extra {sorted(set(cand) - set(tmap))}",
                  file=sys.stderr)
            return 2
        tmap = {t: cand[t] for t in tmap}
    windows = args.window or list(WINDOWS)
    llm, emb = open_llm(args), open_embedder(args)
    record = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "topics": args.matrix or "frozen",
              "chat_model": llm.describe(), "embed_model": emb.describe(), "windows": {}}
    ok = True
    try:
        llm.check()
        for w in windows:
            print(f"{w} ({WINDOWS[w]} window):", flush=True)
            units, routed, cols = match_reviews(reviews(w), tmap, llm, emb)
            got: dict[str, set[str]] = {}
            for i, t, _ in routed.matches:
                got.setdefault(units[i].review_id, set()).add(cols[t].id)
            if args.detail:
                _detail(w, got, key(w, set(tmap)), dict(reviews(w)))
            s = score(got, key(w, set(tmap)))
            ok &= s.passed
            mp, mr, mf = METHOD[w]
            print(f"  precision {s.precision:.0%}  recall {s.recall:.0%}  false alarm "
                  f"{s.false_alarm:.0%}  -> {'PASS' if s.passed else 'FAIL'}"
                  f"   (validated: {mp:.0%} / {mr:.0%} / {mf:.0%})", flush=True)
            record["windows"][w] = {**s.__dict__, "passed": s.passed, "units": len(units),
                                    "routes": {k: routed.route.count(k)
                                               for k in ("sure", "model", "misc")},
                                    "off_option_answers": routed.off_option}
    except (LLMError, EmbedError, ValueError) as exc:
        print(f"check-matching: {exc}", file=sys.stderr)
        return 1
    finally:
        emb.close()
        llm.close()
    record["passed"] = ok
    out = Path(args.data_dir) / "checks"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(record, indent=1), encoding="utf-8")
    bar = (f"precision >= {PASS['precision']:.0%}, recall >= {PASS['recall']:.0%}, "
           f"false alarm <= {PASS['false_alarm']:.0%}")
    print(f"{'PASS' if ok else 'FAIL'}: {llm.describe()} with {emb.describe()} ({bar}); "
          f"{llm.calls} model calls, {llm.hits} from cache; record in {path}")
    return 0 if ok else 1


def add_parser(sub, common) -> None:
    p = sub.add_parser("check-matching",
                       help="score the configured models against the answer keys "
                            "(run before go-live and after any model change)")
    common(p)
    p.add_argument("--window", action="append", choices=list(WINDOWS),
                   help="check only this window (repeatable; default: both)")
    p.add_argument("--matrix", help="score this file's topic descriptions instead of the "
                                    "frozen ones (same topic ids)")
    p.add_argument("--detail", action="store_true",
                   help="list every keyed review the matching got wrong")
    p.set_defaults(func=cmd_check)
