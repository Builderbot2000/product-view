"""CLI for Product View.

Each command lives with the code it runs; this file only assembles them:

  fetch, export, info, langs   ingest/commands.py   the JSONL archive
  db build, translate          prepare.py           reviews.db, ready to match
  matrix                       matrix.py            the team -> member -> topic file
  match, check-matching        matching/            reviews matched to topics
  report                       report/build.py      the Confluence page tree
  publish                      publish/pages.py     one page from a file
  cycle                        cycle.py             all of it once, for a scheduler

Defaults come from config.yaml; any flag given on the command line wins.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone

from . import config, cycle, matrix, prepare
from .ingest import commands as ingest
from .matching import check, run as matching
from .publish import pages as publish
from .report import build as report


class JsonFormatter(logging.Formatter):
    """One JSON object per line, for log collectors (PV_LOG_JSON=1)."""

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({"time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
                           "level": record.levelname, "logger": record.name,
                           "message": record.getMessage()}, ensure_ascii=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pv", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument(
        "--config", default=None,
        help=f"YAML config (default: ./{config.DEFAULT_PATH} if present)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # Flags that config.yaml can supply default to None; config.apply() fills
    # whatever the command line left unset.
    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--app-id")
        p.add_argument(
            "--lang",
            help="locale code, or a comma-separated list (e.g. en,fr,zh); "
                 "used only with --no-all-langs",
        )
        p.add_argument("--country")
        p.add_argument("--data-dir")

    ingest.add_parsers(sub, common)
    prepare.add_parsers(sub, common)
    matching.add_parser(sub, common)
    matrix.add_parser(sub)
    check.add_parser(sub, common)
    report.add_parser(sub, common)
    cycle.add_parser(sub, common)
    publish.add_parser(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    # Review text is full of emoji and accents, and commands such as
    # `pv matrix` print it. A default Windows console is cp1252 or gbk and raises
    # UnicodeEncodeError on the first French quote, so the command dies on
    # output rather than on anything real. Library code already writes files
    # with an explicit encoding; this covers the terminal.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):  # not a real tty, or already fixed
            pass

    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if os.environ.get("PV_LOG_JSON") == "1":   # for a platform's log collector
        for handler in logging.getLogger().handlers:
            handler.setFormatter(JsonFormatter())
    # Loading the embedding model logs every HTTP request it makes to the model hub.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        config.apply(args, config.load(args.config))
    except config.ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
