"""(G) Publish -- `pv publish`: push a page to Confluence over REST.

Replaces the manual zip import. The page is created, or updated in place if a
page with the same title already exists in the space, so every run becomes a
new version in the page history rather than a new page. Images and SVGs are
uploaded as attachments of that page.

Two inputs:

- an HTML file, converted to storage format (storage.py). Plain tables at
  best; kept for the probes.
- a storage-format file (`.xhtml`, as `pv report` writes), passed through as
  is. Attachments are the files its `ri:attachment` elements name, read from
  the same folder, and the page is set to full width (report-design.md D1, D3).
"""

from __future__ import annotations

import argparse
import logging
import mimetypes
import re
import sys
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

from . import storage
from .confluence import Client, ConfluenceError

log = logging.getLogger(__name__)

STORAGE_SUFFIX = ".xhtml"


def _html_title(html: str) -> str | None:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    return " ".join(unescape(m.group(1)).split()) if m else None


def load_storage(path: Path) -> storage.StoragePage:
    """A storage-format file plus the attachments it references."""
    body = path.read_text(encoding="utf-8")
    atts = []
    for name in dict.fromkeys(re.findall(r'<ri:attachment ri:filename="([^"]+)"', body)):
        file = path.parent / unescape(name)
        if not file.is_file():
            raise FileNotFoundError(f"attachment {name!r} referenced but not found in {path.parent}")
        media = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        atts.append(storage.Attachment(file.name, file.read_bytes(), media))
    return storage.StoragePage(body, atts)


def _publish(client: Client, space: str, title: str, page: storage.StoragePage,
             parent_id: str | None, full_width: bool) -> dict:
    """Create or update one page and its attachments; prints the result."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    result, created = client.upsert_page(
        space, title, page.body, parent_id=parent_id, message=f"pv publish {stamp}")
    uploaded, unchanged = client.sync_attachments(result["id"], page.attachments)
    if full_width:
        client.set_full_width(result["id"])
    verb = "created" if created else f"updated to version {result['version']['number']}"
    print(f"{verb}: {title!r} in space {space}; attachments: "
          f"{uploaded} uploaded, {unchanged} unchanged")
    print(f"  {client.page_url(result)}")
    return result


def push(space: str, title: str, page: storage.StoragePage, *,
         parent_id: str | None = None, full_width: bool = False) -> int:
    try:
        _publish(Client.from_env(), space, title, page, parent_id, full_width)
    except ConfluenceError as exc:
        print(f"publish: {exc}", file=sys.stderr)
        return 1
    return 0


def publish_tree(space: str, pages: list[tuple[str, storage.StoragePage, str | None]],
                 root_parent_id: str | None = None) -> None:
    """Publish (title, page, parent title) in order; a parent must come
    before its children. New pages are created under their parent; an
    existing page keeps its place in the tree. Storage pages, so full width.
    Raises ConfluenceError."""
    client = Client.from_env()
    ids: dict[str, str] = {}
    for title, page, parent in pages:
        parent_id = ids[parent] if parent else root_parent_id
        ids[title] = _publish(client, space, title, page, parent_id, full_width=True)["id"]


def cmd_publish(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.is_file():
        print(f"no such file: {path}", file=sys.stderr)
        return 2
    native = path.suffix == STORAGE_SUFFIX
    try:
        if native:
            page = load_storage(path)
            title = args.title or path.name.removesuffix(".storage.xhtml").removesuffix(STORAGE_SUFFIX)
        else:
            html = path.read_text(encoding="utf-8")
            title = args.title or _html_title(html) or path.stem
            page = storage.convert(html, base_dir=path.parent)
    except FileNotFoundError as exc:
        print(f"publish: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        if native:
            print(f"dry run: title {title!r}, {len(page.body):,} chars of storage format "
                  f"(passed through)")
        else:
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
    return push(args.space, title, page, parent_id=args.parent_id, full_width=native)


def add_parser(sub) -> None:
    p = sub.add_parser(
        "publish", help="create or update a Confluence page from an HTML or storage-format file")
    p.add_argument("file", help=f"HTML file, or storage format ({STORAGE_SUFFIX}) to pass through")
    p.add_argument("--space", help="Confluence space key (the KEY in /wiki/spaces/KEY/)")
    p.add_argument("--title", help="page title; default: the HTML <title>, else the filename")
    p.add_argument("--parent-id", help="create new pages under this page ID")
    p.add_argument("--dry-run", action="store_true",
                   help="convert only: write the storage format to out/ and list "
                        "attachments, without contacting Confluence")
    p.set_defaults(func=cmd_publish)
