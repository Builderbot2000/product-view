"""Pipeline commands: db build and translate. Each reads and writes through the
stores, so either re-runs in isolation.
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


def open_llm(args: argparse.Namespace):
    from .llm import LLM, LLMConfig

    return LLM(LLMConfig.from_config(config.get(args.config, "llm")),
               Path(args.data_dir) / "cache.db")


def add_parsers(sub, common) -> None:
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

