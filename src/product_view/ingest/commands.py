"""Ingest commands: `fetch` pulls raw reviews into the JSONL archive, `export`
converts it to CSV, `info` summarizes what is on disk, `langs` probes locale
coverage.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from collections import Counter
from pathlib import Path

from .archive import CSV_COLUMNS, ReviewArchive, corpus_known_ids, dataset_slug, iter_corpus
from .play_store import DEFAULT_LANGS, MAX_PAGE_SIZE, PlayStoreSource, fetch_app_metadata


def _raw_dir(args: argparse.Namespace) -> Path:
    return Path(args.data_dir) / "raw"


def _archive_for(args: argparse.Namespace, lang: str) -> ReviewArchive:
    slug = dataset_slug(args.app_id, lang, args.country)
    return ReviewArchive(_raw_dir(args) / f"{slug}.jsonl")


def _langs(args: argparse.Namespace) -> list[str]:
    if args.all_langs:
        return list(DEFAULT_LANGS)
    return [part.strip() for part in args.lang.split(",") if part.strip()]


def cmd_fetch(args: argparse.Namespace) -> int:
    log = logging.getLogger("fetch")
    langs = _langs(args)

    # Deduped across every language archive: Play's locale partitions overlap,
    # so a review pulled under `zh` must not be rewritten under `zh-CN`.
    known = corpus_known_ids(_raw_dir(args), args.app_id, args.country)
    log.info("corpus holds %d reviews across all languages", len(known))

    meta = fetch_app_metadata(args.app_id, langs[0], args.country)
    _save_metadata(args, meta)
    log.info(
        "store listing: score %.2f | %s ratings | %s with text",
        meta["score"] or 0,
        meta["ratings"],
        meta["reviews"],
    )

    grand_total = 0
    for lang in langs:
        archive = _archive_for(args, lang)
        resume_state = None
        if args.resume:
            resume_state = archive.load_state().get("continuation_token")

        source = PlayStoreSource(
            app_id=args.app_id,
            lang=lang,
            country=args.country,
            page_size=args.page_size,
            sleep_seconds=args.sleep,
            on_checkpoint=archive.save_state,
        )
        stream = source.fetch(
            max_reviews=args.max_reviews,
            known_ids=set() if args.full else known,
            resume_state=resume_state,
        )

        written = 0
        try:
            for review in archive.append(stream):
                known.add(review.review_id)
                written += 1
                if written % 500 == 0:
                    log.info("  [%s] ... %d new", lang, written)
        except KeyboardInterrupt:
            log.warning("interrupted — progress saved, re-run with --resume")
            return 130
        grand_total += written
        log.info("[%s] +%d new (corpus now %d)", lang, written, len(known))

    log.info("total new reviews: %d | corpus size: %d", grand_total, len(known))
    return 0


def _save_metadata(args: argparse.Namespace, meta: dict) -> None:
    """Append a listing snapshot; the dashboard needs real denominators."""
    path = Path(args.data_dir) / "meta" / f"{args.app_id}_{args.country}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(meta, ensure_ascii=False) + "\n")


def cmd_langs(args: argparse.Namespace) -> int:
    """Probe locales for reviews the current corpus is missing."""
    log = logging.getLogger("langs")
    known = corpus_known_ids(_raw_dir(args), args.app_id, args.country)
    log.info("probing %d locales against %d known reviews", len(DEFAULT_LANGS), len(known))
    from google_play_scraper import Sort, reviews as gp_reviews

    rows = []
    for lang in DEFAULT_LANGS:
        try:
            page, _ = gp_reviews(
                args.app_id, lang=lang, country=args.country,
                sort=Sort.NEWEST, count=MAX_PAGE_SIZE,
            )
        except Exception as exc:
            print(f"  {lang:6} error: {type(exc).__name__}")
            continue
        novel = sum(1 for r in page if r["reviewId"] not in known)
        rows.append((lang, len(page), novel))
        time.sleep(0.25)

    print(f"{'lang':6} {'first page':>11} {'unseen':>7}")
    for lang, got, novel in sorted(rows, key=lambda r: -r[2]):
        flag = "  <- has unfetched reviews" if novel else ""
        print(f"{lang:6} {got:>11} {novel:>7}{flag}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    rows = list(iter_corpus(_raw_dir(args), args.app_id, args.country))
    if not rows:
        print(f"no archives under {_raw_dir(args)} — run `pv fetch` first", file=sys.stderr)
        return 1
    out = (
        Path(args.out)
        if args.out
        else Path(args.data_dir) / "export" / f"{args.app_id}_{args.country}.csv"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {out}")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    scores: Counter = Counter()
    langs: Counter = Counter()
    versions: Counter = Counter()
    dates: list[str] = []
    total = 0
    for row in iter_corpus(_raw_dir(args), args.app_id, args.country):
        total += 1
        scores[row["score"]] += 1
        langs[row.get("lang", "?")] += 1
        if row.get("app_version"):
            versions[row["app_version"]] += 1
        if row.get("created_at"):
            dates.append(row["created_at"])

    if not total:
        print(f"no archives under {_raw_dir(args)}")
        return 1

    print(f"corpus:   {args.app_id} / {args.country} ({len(langs)} locales)")
    print(f"reviews:  {total}")
    if dates:
        print(f"range:    {min(dates)[:10]} .. {max(dates)[:10]}")
    mean = sum(s * n for s, n in scores.items()) / total
    print(f"mean:     {mean:.2f}")
    print("scores:")
    for score in range(5, 0, -1):
        n = scores.get(score, 0)
        bar = "#" * round(40 * n / total)
        print(f"  {score}* {n:>6} {100 * n / total:5.1f}%  {bar}")
    print("locales:")
    for lang, n in langs.most_common(8):
        print(f"  {lang:<8} {n}")

    # Contrast against the store's own numbers. The corpus always reads more
    # negative than the listing score, and showing both stops that looking like
    # a bug when a PM cross-checks it.
    meta_path = Path(args.data_dir) / "meta" / f"{args.app_id}_{args.country}.jsonl"
    if meta_path.exists():
        snaps = [json.loads(l) for l in meta_path.open(encoding="utf-8") if l.strip()]
        if snaps:
            m = snaps[-1]
            print("store listing (for contrast):")
            print(f"  displayed score   {m['score']:.2f}")
            print(f"  total ratings     {m['ratings']}")
            print(f"  with text         {m['reviews']}")
            h = m.get("histogram") or []
            if h:
                ht = sum(h)
                print(f"  ratings 5*        {h[4]} ({100 * h[4] / ht:.1f}%)")
                print(f"  our text 5*       {scores.get(5, 0)} "
                      f"({100 * scores.get(5, 0) / total:.1f}%)")
                print("  -> happy raters mostly leave no text; that gap is expected")
    return 0


def add_fetch_options(p: argparse.ArgumentParser) -> None:
    """Fetch tuning, shared by `pv fetch` and `pv cycle`."""
    p.add_argument(
        "--all-langs",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=f"fetch every locale Play partitions reviews by "
             f"({len(DEFAULT_LANGS)} of them); on by default",
    )
    p.add_argument("--max-reviews", type=int)
    p.add_argument("--page-size", type=int, help=f"max {MAX_PAGE_SIZE}")
    p.add_argument("--sleep", type=float, help="seconds between pages")


def add_parsers(sub, common) -> None:
    p_fetch = sub.add_parser("fetch", help="scrape reviews into the JSONL archive")
    common(p_fetch)
    add_fetch_options(p_fetch)
    p_fetch.add_argument(
        "--resume",
        action="store_true",
        help="continue a deep backfill from the saved continuation token",
    )
    p_fetch.add_argument(
        "--full",
        action="store_true",
        help="ignore existing IDs (re-walk everything; still deduped on write)",
    )
    p_fetch.set_defaults(func=cmd_fetch)

    p_export = sub.add_parser("export", help="export the archive to CSV")
    common(p_export)
    p_export.add_argument("--out")
    p_export.set_defaults(func=cmd_export)

    p_info = sub.add_parser("info", help="summarize the archive")
    common(p_info)
    p_info.set_defaults(func=cmd_info)

    p_langs = sub.add_parser("langs", help="probe locales for unfetched reviews")
    common(p_langs)
    p_langs.set_defaults(func=cmd_langs)
