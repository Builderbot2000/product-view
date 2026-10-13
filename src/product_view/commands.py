"""Pipeline commands: db build, translate, issues, run.

Separate from cli.py, which owns argument parsing and the ingest stage. Each
command reads and writes through the stores, so any stage re-runs in isolation.

Three files, split by what they are: reviews.db is derived and rebuilt from
the JSONL archive by `db build` (and so `run`); cache.db holds model output
that can be recomputed (translations, model answers); issues.db is the issue
codebook, which is kept, because an issue's identity across runs is the point.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .archive import iter_corpus
from .store import Store, reset

log = logging.getLogger(__name__)


def _db_path(args: argparse.Namespace) -> Path:
    return Path(args.data_dir) / "reviews.db"


def _open(args: argparse.Namespace) -> Store:
    return Store(_db_path(args))


# --- db build --------------------------------------------------------------

def cmd_db_build(args: argparse.Namespace) -> int:
    raw_dir = Path(args.data_dir) / "raw"
    # Clean every time: reviews.db is derived, and anything left over from an
    # earlier build or run is stale. The archive and cache.db are untouched.
    # Opening first lets a pre-split database hand its translations and
    # embeddings to cache.db before the file is deleted.
    _open(args).close()
    reset(_db_path(args))
    with _open(args) as store:
        rows = iter_corpus(raw_dir, args.app_id, args.country)
        n = store.upsert_reviews(rows)

        meta_path = Path(args.data_dir) / "meta" / f"{args.app_id}_{args.country}.jsonl"
        snaps = 0
        if meta_path.exists():
            with meta_path.open(encoding="utf-8") as fh:
                snaps = store.upsert_app_metadata(
                    json.loads(line) for line in fh if line.strip()
                )

        print(f"reviews:       {store.count('reviews')} ({n} written)")
        print(f"app_metadata:  {store.count('app_metadata')} snapshots ({snaps} written)")
        print(f"database:      {_db_path(args)} (rebuilt clean)")
        print(f"cache:         {store.cache_path} "
              f"({store.count('translations')} translations kept)")
    return 0


# --- translate -------------------------------------------------------------

def cmd_translate(args: argparse.Namespace) -> int:
    from .lang import detect, translate as mt

    with _open(args) as store:
        pending = store.untranslated(min_chars=args.min_chars)
        if not pending:
            print("nothing to translate — every review is already routed")
            return 0

        print(f"routing {len(pending)} reviews by detected language...")
        passthrough: list[tuple] = []
        to_translate: list[tuple] = []
        dropped: list[tuple] = []
        now = datetime.now(timezone.utc).isoformat()

        for row in pending:
            lang, confidence, action = detect.route(row["content"])
            if action == "drop":
                dropped.append((row["review_id"], lang, confidence, None, None, now))
            elif action == "translate":
                to_translate.append((row["review_id"], lang, confidence, row["content"]))
            else:
                passthrough.append(
                    (row["review_id"], lang, confidence, row["content"], None, now)
                )

        print(f"  english / passthrough : {len(passthrough)}")
        print(f"  french   -> translate : {len(to_translate)}")
        print(f"  non-latin -> dropped  : {len(dropped)}")

        store.save_translations(passthrough)
        store.save_translations(dropped)

        if to_translate:
            # Persist each batch as it lands rather than buffering the run.
            # Beam-search decoding on CPU takes tens of minutes at this scale,
            # and an interrupted run should keep what it already produced:
            # re-running then translates only the remainder, because
            # `untranslated()` skips whatever is already stored.
            total = len(to_translate)
            done = 0
            for indices, batch in mt.translate_batches([r[3] for r in to_translate]):
                store.save_translations(
                    [
                        (
                            to_translate[i][0],   # review_id
                            to_translate[i][1],   # detected lang
                            to_translate[i][2],   # confidence
                            english,
                            mt.MODEL_NAME,
                            now,
                        )
                        for i, english in zip(indices, batch)
                    ]
                )
                done += len(batch)
                print(f"    translated {done}/{total}", flush=True)

        # Dropping the non-Latin reviews is the right trade; dropping them
        # silently would be the actual mistake.
        if dropped:
            print(f"\nDROPPED {len(dropped)} non-Latin-script reviews "
                  f"(no translation model): they are excluded from the issues.")
        print("\ndetected languages:")
        for row in store.translation_summary()[:10]:
            note = f"  ({row['dropped']} dropped)" if row["dropped"] else ""
            print(f"  {row['detected_lang'] or '?':<6} {row['n']:>6}{note}")
    return 0


# --- issues ----------------------------------------------------------------

def issue_config(args: argparse.Namespace):
    from .issues.pipeline import IssueConfig
    from .render.issues import load_taxonomy

    sec = config.get(args.config, "issues")
    tax = load_taxonomy(Path(args.curation))
    return IssueConfig(
        window_months=args.window_months,
        min_chars=args.min_chars,
        sides=tuple(sec["sides"]),
        min_cluster_size=sec["min_cluster_size"],
        threshold=sec["threshold"],
        loops=sec["loops"],
        batch=sec["batch"],
        nearest=sec["nearest"],
        join=sec["join"],
        overlap_cost=sec["overlap_cost"],
        concept_cost=sec["concept_cost"],
        areas={a.id: f"{a.name}: {a.description}" if a.description else a.name
               for a in tax.areas.values()},
    )


def open_llm(args: argparse.Namespace):
    from .issues.llm import LLM, LLMConfig

    return LLM(LLMConfig.from_config(config.get(args.config, "llm")),
               Path(args.data_dir) / "cache.db")


def cmd_issues(args: argparse.Namespace) -> int:
    from .issues import pipeline
    from .issues.codebook import Codebook
    from .issues.llm import LLMError

    cfg = issue_config(args)
    llm = open_llm(args)
    try:
        llm.check()
        with _open(args) as store, Codebook(Path(args.data_dir) / "issues.db") as book:
            pipeline.update(store, book, llm, cfg)
    except LLMError as exc:
        print(f"issues: {exc}", file=sys.stderr)
        return 1
    finally:
        print(f"\nmodel calls: {llm.calls} made, {llm.hits} from cache, "
              f"{llm.seconds / 60:.1f} min in the model")
        llm.close()
    print("\ninspect with: pv issues show")
    return 0


def cmd_issues_show(args: argparse.Namespace) -> int:
    from .issues.codebook import Codebook

    path = Path(args.data_dir) / "issues.db"
    if not path.exists():
        print("no issues yet: run `pv issues` first", file=sys.stderr)
        return 1
    threshold = config.get(args.config, "issues.threshold")
    with Codebook(path) as book:
        for side in config.get(args.config, "issues.sides"):
            run = book.latest_run(side)
            reviews: dict[str, set[str]] = {}
            quotes: dict[str, list[str]] = {}
            for m in book.members(side, threshold):
                reviews.setdefault(m["concept_id"], set()).add(m["review_id"])
                quotes.setdefault(m["concept_id"], []).append(m["quote"])
            concepts = sorted(book.concepts(side), key=lambda c: -len(reviews.get(c["concept_id"], ())))
            print(f"\n== {side}: {len(concepts)} live concepts"
                  + (f" (last run {run['started_at']}, {run['model']})" if run else ""))
            for kind in ("issue", "general"):
                print(f"\n  {'issues' if kind == 'issue' else 'general sentiment'}:")
                for c in concepts:
                    if c["kind"] != kind:
                        continue
                    parent = f"  (inside {c['parent']})" if c["parent"] else ""
                    print(f"  {c['concept_id']} {len(reviews.get(c['concept_id'], ())):5} reviews  "
                          f"[{c['area'] or '-'}] {c['name']}{parent}")
                    if args.detail:
                        print(f"        {c['criterion']}")
                        for q in quotes.get(c["concept_id"], [])[:3]:
                            print(f"        “{' '.join(q.split())[:150]}”")
    return 0


# --- run -------------------------------------------------------------------

def cmd_run(args: argparse.Namespace) -> int:
    """The whole pipeline: [fetch ->] db build -> translate -> issues.

    Translations and model answers are cached and the codebook is kept, so a
    run costs only what is genuinely new: new reviews are distilled and scored
    against the existing issues, and only what they don't cover can form new
    ones.
    """
    if args.fetch:
        from .cli import cmd_fetch

        args.resume = False   # a top-up, never a backfill
        args.full = False
        print("== fetch")
        if rc := cmd_fetch(args):
            return rc

    for name, step in (("db build", cmd_db_build),
                       ("translate", cmd_translate),
                       ("issues", cmd_issues)):
        print(f"\n== {name}")
        if rc := step(args):
            return rc
    return 0


def add_parsers(sub, common, add_fetch_options) -> None:
    """Register the pipeline subcommands onto the existing parser."""
    p_db = sub.add_parser("db", help="database maintenance")
    db_sub = p_db.add_subparsers(dest="db_command", required=True)
    p_build = db_sub.add_parser(
        "build", help="rebuild reviews.db clean from the JSONL archive")
    common(p_build)
    p_build.set_defaults(func=cmd_db_build)

    p_tr = sub.add_parser("translate", help="detect language, translate French to English")
    common(p_tr)
    p_tr.add_argument("--min-chars", type=int)
    p_tr.set_defaults(func=cmd_translate)

    p_is = sub.add_parser(
        "issues", help="group what reviews say into issues, kept in the codebook (issues.db)")
    common(p_is)
    add_issue_options(p_is)
    p_is.set_defaults(func=cmd_issues)
    is_sub = p_is.add_subparsers(dest="issues_command")
    p_show = is_sub.add_parser("show", help="list the codebook's live issues")
    common(p_show)
    p_show.add_argument("--detail", action="store_true", help="criteria and example quotes")
    p_show.set_defaults(func=cmd_issues_show)

    p_run = sub.add_parser("run", help="full pipeline: db build, translate, issues")
    common(p_run)
    p_run.add_argument("--fetch", action="store_true",
                       help="top up the archive from the Play Store first")
    add_issue_options(p_run)
    add_fetch_options(p_run)
    p_run.set_defaults(func=cmd_run)


def add_issue_options(p: argparse.ArgumentParser) -> None:
    """Issue-stage flags. Unset flags take their value from config.yaml."""
    p.add_argument("--min-chars", type=int)
    p.add_argument("--window-months", type=int,
                   help="distill and group reviews this recent (default from config: 12)")
    p.add_argument("--curation", help="areas and roles (default: curation.yaml)")
