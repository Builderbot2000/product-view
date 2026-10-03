"""(F) Report -- `pv report`: periodic Confluence pages from the latest runs.

One page tree per report (report-design.md D4): a hub with every area, and
one child page per role holding only that role's areas (D16). Pages are
Confluence storage format plus SVG charts (D1, D2), written to one folder per
page under --out, and with --publish pushed straight to Confluence: the hub
first, then each role page under it. Titles are stable, so each run is a new
version of the same pages and the page history is the archive.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..store import Store
from .issues import load_stream, load_taxonomy


def cmd_report(args: argparse.Namespace) -> int:
    from . import pages

    try:
        taxonomy = load_taxonomy(Path(args.curation))
    except (ValueError, KeyError) as exc:
        print(f"report: {exc}", file=sys.stderr)
        return 2
    with Store(Path(args.data_dir) / "reviews.db") as store:
        streams = {pol: load_stream(store, pol, taxonomy, args.period_days,
                                    args.baseline_periods, args.min_chars)
                   for pol in ("negative", "positive")}
        if streams["negative"] is None:
            print("report: no negative run yet; run `pv cluster` first", file=sys.stderr)
            return 1
        built = pages.build_all(store, streams["negative"], streams["positive"],
                                taxonomy, args.app_id, args.title)

    out = Path(args.out)
    for spec in built:
        folder = out / spec.key
        folder.mkdir(parents=True, exist_ok=True)
        for old in folder.glob("*.svg"):
            old.unlink()
        (folder / "page.storage.xhtml").write_text(spec.page.body, encoding="utf-8")
        for att in spec.page.attachments:
            (folder / att.filename).write_bytes(att.data)
        print(f"{spec.key:10} {spec.title!r}: {len(spec.page.body):,} chars, "
              f"{len(spec.page.attachments)} charts -> {folder}")

    if not args.publish:
        return 0
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


def add_parser(sub, common) -> None:
    p = sub.add_parser("report", help="build the periodic Confluence report pages")
    common(p)
    p.add_argument("--period-days", type=int,
                   help="length of the reporting period (default from config: 28)")
    p.add_argument("--baseline-periods", type=int,
                   help="'usual' = mean of this many periods before it (default: 6)")
    p.add_argument("--curation", help="areas, roles, labels (default: curation.yaml)")
    p.add_argument("--min-chars", type=int)
    p.add_argument("--out", default="out/report", help="output folder (default: out/report)")
    p.add_argument("--publish", action="store_true", help="also publish to Confluence")
    p.add_argument("--space", help="Confluence space key")
    p.add_argument("--title", help="hub page title (default: 'Product View: <app id>')")
    p.add_argument("--parent-id", help="create the hub under this page ID")
    p.set_defaults(func=cmd_report)
