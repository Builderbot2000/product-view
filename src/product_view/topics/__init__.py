"""Topic matching -- `pv match`: complaint reviews matched to the matrix's topics.

The window is the reports' window: every period a report shows, which is the
reporting period and the periods before it that its trend and "usual" need
(render/topics.py). It ends on the day of the newest review. Each run
re-matches the whole window and stores the result as a new run in topics.db.
Cost is in the model calls, and those are cached, so a weekly run pays only
for units it has not seen before.

`pv matrix` checks the matrix file and prints who owns what.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import config
from .. import matrix as mx
from ..store import Store

STREAM = "negative"   # complaints only (report-design.md D17): 1-3 star reviews


def topic_db(args: argparse.Namespace) -> Path:
    return Path(args.data_dir) / "topics.db"


def window(store: Store, period_days: int, periods: int) -> tuple[datetime, datetime]:
    """[start, end): `periods` periods ending on the newest review's day."""
    (newest,) = store.conn.execute("SELECT max(created_at) FROM reviews").fetchone()
    if not newest:
        raise LookupError("no reviews: fetch and build the database first")
    last = datetime.fromisoformat(newest)
    end = datetime(last.year, last.month, last.day, tzinfo=timezone.utc) + timedelta(days=1)
    return end - timedelta(days=period_days * periods), end


def _dt(text: str) -> datetime:
    d = datetime.fromisoformat(text)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def open_embedder(args: argparse.Namespace):
    from .embed import Embedder

    sec = config.get(args.config, "embed")
    return Embedder(Path(args.data_dir) / "cache.db", sec["backend"], sec["base_url"])


def run_match(args: argparse.Namespace, matrix: mx.Matrix,
              since: datetime | None = None, until: datetime | None = None) -> str:
    """One matching run over the window; returns its run id. Raises on failure,
    after marking the run failed."""
    import numpy as np

    from ..commands import open_llm
    from ..render.topics import periods_shown
    from . import method, units as um
    from .store import TopicStore

    report = config.get(args.config, "report")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    llm = open_llm(args)
    emb = open_embedder(args)
    with Store(Path(args.data_dir) / "reviews.db") as store, TopicStore(topic_db(args)) as ts:
        start, end = window(store, report["period_days"],
                            periods_shown(report["baseline_periods"]))
        start, end = since or start, until or end
        rows = [r for r in store.stream(STREAM, min_chars=args.min_chars)
                if r["created_at"] and start <= _dt(r["created_at"]) < end]
        ts.start(run_id, matrix=str(matrix.path), topic_hash=matrix.topic_hash,
                 chat_model=llm.describe(), embed_model=emb.describe(),
                 window_start=start.isoformat(), window_end=end.isoformat(), reviews=len(rows))
        try:
            llm.check()
            t0 = time.time()
            print(f"matching {len(rows)} complaint reviews, {start:%Y-%m-%d} to "
                  f"{end - timedelta(days=1):%Y-%m-%d}, against {len(matrix.topics)} topics "
                  f"({matrix.path}{', sample content' if matrix.is_sample else ''})", flush=True)
            text = {r["review_id"]: r["content_en"] for r in rows}
            units = um.build([(r["review_id"], r["content_en"]) for r in rows], emb.minilm)
            print(f"  {len(units)} units", flush=True)

            topics = list(matrix.topics.values())
            ex = method.examples(matrix.topics, llm)
            U = emb.qwen([u.text for u in units], method.INSTRUCTION)
            sets = [emb.qwen(ex[t.id], method.INSTRUCTION) for t in topics]
            neg = np.vstack([emb.qwen(ex[method.NULL], method.INSTRUCTION),
                             emb.qwen(ex[method.OFFLIST], method.INSTRUCTION)])
            P = (method.probabilities(U, sets, neg) if len(units)
                 else np.zeros((0, len(topics))))
            routed = method.gate(P)
            n = {k: routed.route.count(k) for k in ("sure", "model", "misc")}
            print(f"  {n['sure']} sure, {n['misc']} misc, {n['model']} for the model "
                  f"({emb.computed} texts embedded, {time.time() - t0:.0f}s)", flush=True)
            method.ask(llm, P, routed, topics, [u.text for u in units],
                       [text[u.review_id] for u in units], label="model")

            unit_rows = [(u.review_id, u.seq, routed.route[i], topics[int(routed.best[i])].id,
                          round(float(routed.p1[i]), 4), u.text, u.quote)
                         for i, u in enumerate(units)]
            match_rows = sorted({(units[i].review_id, units[i].seq, topics[t].id, how)
                                 for i, t, how in routed.matches})
            ts.finish(run_id, unit_rows, match_rows, units=len(units), sure=n["sure"],
                      model=n["model"], misc=n["misc"], calls=llm.calls)
        except BaseException as exc:
            ts.fail(run_id, f"{type(exc).__name__}: {exc}")
            raise
        finally:
            emb.close()
            llm.close()
    matched = len({(r, s) for r, s, _, _ in match_rows})
    reviews = len({r for r, _, _, _ in match_rows})
    print(f"  run {run_id}: {len(match_rows)} matches on {matched} units, {reviews} of "
          f"{len(rows)} reviews have a topic; {llm.calls} model calls, {llm.hits} from cache"
          + (f"; {routed.off_option} answers outside the options ignored"
             if routed.off_option else ""))
    return run_id


def load_matrix(args: argparse.Namespace) -> mx.Matrix | None:
    try:
        return mx.load(getattr(args, "matrix", None))
    except mx.MatrixError as exc:
        print(f"matrix: {exc}", file=sys.stderr)
        return None


def _date(text: str | None) -> datetime | None:
    if not text:
        return None
    d = datetime.fromisoformat(text)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def cmd_match(args: argparse.Namespace) -> int:
    from ..issues.llm import LLMError
    from .embed import EmbedError

    matrix = load_matrix(args)
    if matrix is None:
        return 2
    until = _date(args.until)
    try:
        run_match(args, matrix, _date(args.since), until + timedelta(days=1) if until else None)
    except (LLMError, EmbedError, LookupError, ValueError) as exc:
        print(f"match: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_matrix(args: argparse.Namespace) -> int:
    matrix = load_matrix(args)
    if matrix is None:
        return 2
    print(f"{matrix.path}: {len(matrix.topics)} topics, {len(matrix.teams)} teams, "
          f"{sum(len(t.members) for t in matrix.teams.values())} members; topic hash "
          f"{matrix.topic_hash}" + (" (sample content)" if matrix.is_sample else ""))
    for team in matrix.teams.values():
        print(f"\n{team.name}" + (f"  <{team.mailing_list}>" if team.mailing_list else ""))
        for m in team.members:
            print(f"  {m.name} <{m.email}>")
            for t in m.topics:
                print(f"    {matrix.topics[t].name}")
    return 0


def add_parsers(sub, common) -> None:
    p = sub.add_parser("match", help="match complaint reviews to the matrix's topics")
    common(p)
    p.add_argument("--matrix", help=f"matrix file (default: ${mx.ENV_PATH}, else "
                                    f"{mx.REAL}, else {mx.SAMPLE})")
    p.add_argument("--min-chars", type=int)
    p.add_argument("--since", help="first day to match (default: the reports' window)")
    p.add_argument("--until", help="last day to match (default: the newest review's day)")
    p.set_defaults(func=cmd_match)

    p = sub.add_parser("matrix", help="check the team, member and topic matrix")
    p.add_argument("--matrix", help="matrix file")
    p.set_defaults(func=cmd_matrix)
