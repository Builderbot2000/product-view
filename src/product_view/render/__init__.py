"""(F) Report -- `pv report`: periodic Confluence pages.

Team pages and member reports (report-design.md D20), from the latest topic
matching run (topics.db) and the team -> member -> topic matrix: one page per
team, and under it one report per member covering only their topics. They
sit under the overview page (`report.overview`), which stays as it is until
it is revised for the matrix.

`--hub` builds the earlier pages instead: the overview hub and one page per
role, from the issue codebook (issues.db, D16). Kept while the overview page
still comes from it.

Pages are Confluence storage format plus SVG charts (D1, D2), written to one
folder per page under --out, and with --publish pushed straight to
Confluence, parents before children. Titles are stable, so each run is a new
version of the same pages and the page history is the archive.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .. import config
from ..store import Store
from .pages import PageSpec


def _hub_pages(args: argparse.Namespace) -> list[PageSpec] | int:
    from ..issues.codebook import Codebook
    from . import pages
    from .issues import load_stream, load_taxonomy

    try:
        taxonomy = load_taxonomy(Path(args.curation))
    except (ValueError, KeyError) as exc:
        print(f"report: {exc}", file=sys.stderr)
        return 2
    book_path = Path(args.data_dir) / "issues.db"
    if not book_path.exists():
        print("report: no issues yet; run `pv issues` first", file=sys.stderr)
        return 1
    threshold = config.get(args.config, "issues.threshold")
    with Store(Path(args.data_dir) / "reviews.db") as store, Codebook(book_path) as book:
        streams = {pol: load_stream(store, book, pol, args.period_days, args.baseline_periods,
                                    threshold, args.min_chars)
                   for pol in ("negative", "positive")}
        if streams["negative"] is None:
            print("report: no complaint issues yet; run `pv issues` first", file=sys.stderr)
            return 1
        return pages.build_all(store, streams["negative"], streams["positive"],
                               taxonomy, args.app_id, args.title, args.app_name)


def overview_title(args: argparse.Namespace) -> str:
    return (config.get(args.config, "report.overview")
            or args.title or f"Product View @ {args.app_name or args.app_id}")


def _team_pages(args: argparse.Namespace) -> list[PageSpec] | int:
    from ..topics import load_matrix, topic_db
    from . import team_pages, topics

    matrix = load_matrix(args)
    if matrix is None:
        return 2
    with Store(Path(args.data_dir) / "reviews.db") as store:
        report = topics.load(store, topic_db(args), matrix, args.period_days,
                             args.baseline_periods, args.min_chars)
        if report is None:
            print("report: no topic matches yet; run `pv match` first", file=sys.stderr)
            return 1
        if report.run["topic_hash"] != matrix.topic_hash:
            print("report: the matrix's topics changed since the last `pv match`; run it again",
                  file=sys.stderr)
            return 1
        if report.short_window:
            print(f"report: warning: run {report.run['run_id']} matched a shorter window than "
                  "the trend shows; older periods will read low", file=sys.stderr)
        return team_pages.build_all(store, report, overview_title(args))


def write(built: list[PageSpec], out: Path) -> None:
    for spec in built:
        folder = out / spec.key
        folder.mkdir(parents=True, exist_ok=True)
        for old in folder.glob("*.svg"):
            old.unlink()
        (folder / "page.storage.xhtml").write_text(spec.page.body, encoding="utf-8")
        for att in spec.page.attachments:
            (folder / att.filename).write_bytes(att.data)
        print(f"{spec.key:32} {spec.title!r}: {len(spec.page.body):,} chars, "
              f"{len(spec.page.attachments)} charts -> {folder}")


def publish(args: argparse.Namespace, built: list[PageSpec]) -> int:
    if not args.space:
        print("report: no space key; pass --space or set confluence.space in config.yaml",
              file=sys.stderr)
        return 2
    from ..publish import ConfluenceError, publish_tree

    try:
        publish_tree(args.space, [(s.title, s.page, s.parent) for s in built],
                     root_parent_id=args.parent_id)
    except ConfluenceError as exc:
        print(f"report: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    built = _hub_pages(args) if args.hub else _team_pages(args)
    if isinstance(built, int):
        return built
    write(built, Path(args.out))
    return publish(args, built) if args.publish else 0


def add_parser(sub, common) -> None:
    p = sub.add_parser("report", help="build the periodic Confluence report pages")
    common(p)
    p.add_argument("--hub", action="store_true",
                   help="the earlier overview hub and role pages, from the issue codebook")
    p.add_argument("--matrix", help="matrix file (default: $PV_MATRIX, else matrix.yaml, "
                                    "else matrix.sample.yaml)")
    p.add_argument("--period-days", type=int,
                   help="length of the reporting period (default from config: 28)")
    p.add_argument("--baseline-periods", type=int,
                   help="'usual' = mean of this many periods before it (default: 6)")
    p.add_argument("--curation", help="--hub: areas and roles (default: curation.yaml)")
    p.add_argument("--min-chars", type=int)
    p.add_argument("--out", default="out/report", help="output folder (default: out/report)")
    p.add_argument("--publish", action="store_true", help="also publish to Confluence")
    p.add_argument("--space", help="Confluence space key")
    p.add_argument("--title", help="overview page title (default: 'Product View @ <app name>')")
    p.add_argument("--app-name", help="app name for the overview title (default: the app id)")
    p.add_argument("--parent-id", help="create the top page(s) under this page ID")
    p.set_defaults(func=cmd_report)
