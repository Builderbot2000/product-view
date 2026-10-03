"""(G) Publish -- `pv publish`: push an HTML page to Confluence over REST.

Replaces the manual zip import. The page is converted to storage format
(storage.py), then created, or updated in place if a page with the same title
already exists in the space, so every run becomes a new version in the page
history rather than a new page. Images and inline SVGs are uploaded as
attachments of that page.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

from . import storage
from .confluence import Client, ConfluenceError

log = logging.getLogger(__name__)


def _html_title(html: str) -> str | None:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    return " ".join(unescape(m.group(1)).split()) if m else None


def cmd_publish(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.is_file():
        print(f"no such file: {path}", file=sys.stderr)
        return 2
    html = path.read_text(encoding="utf-8")
    title = args.title or _html_title(html) or path.stem
    try:
        page = storage.convert(html, base_dir=path.parent)
    except FileNotFoundError as exc:
        print(f"publish: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        out = Path("out") / f"{path.stem}.storage.xhtml"
        out.parent.mkdir(exist_ok=True)
        out.write_text(page.body, encoding="utf-8")
        print(f"dry run: title {title!r}, {len(page.body):,} chars of storage format "
              f"-> {out}")
        for att in page.attachments:
            print(f"  attachment {att.filename} ({att.media_type}, {len(att.data):,} bytes)")
        return 0

    if not args.space:
        print("publish: no space key; pass --space or set confluence.space in config.yaml",
              file=sys.stderr)
        return 2
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    try:
        client = Client.from_env()
        result, created = client.upsert_page(
            args.space, title, page.body, parent_id=args.parent_id,
            message=f"pv publish {stamp}")
        uploaded, unchanged = client.sync_attachments(result["id"], page.attachments)
    except ConfluenceError as exc:
        print(f"publish: {exc}", file=sys.stderr)
        return 1

    verb = "created" if created else f"updated to version {result['version']['number']}"
    print(f"{verb}: {title!r} in space {args.space}; attachments: "
          f"{uploaded} uploaded, {unchanged} unchanged")
    print(client.page_url(result))
    return 0


def add_parser(sub) -> None:
    p = sub.add_parser(
        "publish", help="create or update a Confluence page from an HTML file")
    p.add_argument("file", help="HTML file to publish")
    p.add_argument("--space", help="Confluence space key (the KEY in /wiki/spaces/KEY/)")
    p.add_argument("--title", help="page title; default: the HTML <title>, else the filename")
    p.add_argument("--parent-id", help="create new pages under this page ID")
    p.add_argument("--dry-run", action="store_true",
                   help="convert only: write the storage format to out/ and list "
                        "attachments, without contacting Confluence")
    p.set_defaults(func=cmd_publish)
