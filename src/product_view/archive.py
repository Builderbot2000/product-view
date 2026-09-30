"""JSONL archive of raw normalized reviews.

JSONL rather than CSV as the canonical store: review text is full of newlines,
quotes, and emoji, it appends safely mid-run, and it survives a crash without
corrupting what was already written. CSV is available as an export for anyone
who wants to open the data in a spreadsheet.

SQLite replaces this later (see project.md); nothing here assumes it won't.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

from .models import Review

# Written explicitly rather than derived from the dataclass, so a field rename
# downstream can't silently change the on-disk column order.
CSV_COLUMNS = [
    "review_id",
    "app_id",
    "source",
    "lang",
    "country",
    "created_at",
    "score",
    "thumbs_up",
    "app_version",
    "review_created_version",
    "content",
    "reply_content",
    "replied_at",
    "fetched_at",
    "content_hash",
]


def dataset_slug(app_id: str, lang: str, country: str) -> str:
    return f"{app_id}_{lang}_{country}"


def iter_corpus(raw_dir: Path, app_id: str, country: str) -> Iterator[dict]:
    """Merge every language archive for one app+country, deduped by review_id.

    Play partitions reviews by `lang`, and the partitions overlap: `zh-CN`
    returns the same reviews as `zh`, and several locale codes fall back to the
    English pool entirely. So merging has to dedupe, not just concatenate.
    """
    seen: set[str] = set()
    for path in sorted(raw_dir.glob(f"{app_id}_*_{country}.jsonl")):
        for row in ReviewArchive(path).read():
            if row["review_id"] not in seen:
                seen.add(row["review_id"])
                yield row


def corpus_known_ids(raw_dir: Path, app_id: str, country: str) -> set[str]:
    return {row["review_id"] for row in iter_corpus(raw_dir, app_id, country)}


class ReviewArchive:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path = self.path.with_suffix(".state.json")

    # --- reads -------------------------------------------------------------

    def read(self) -> Iterator[dict]:
        if not self.path.exists():
            return
        # utf-8 explicitly: Windows still defaults to cp1252 and review text is
        # full of emoji and accented French.
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)

    def known_ids(self) -> set[str]:
        return {row["review_id"] for row in self.read()}

    def count(self) -> int:
        return sum(1 for _ in self.read())

    # --- writes ------------------------------------------------------------

    def append(self, reviews: Iterable[Review]) -> Iterator[Review]:
        """Append reviews, yielding each once it is durably written.

        A generator rather than a batch call so the caller's count stays
        accurate when a run is interrupted, and so nothing buffers in memory.
        Flushes per record: an interrupted backfill keeps everything it pulled.
        """
        seen: set[str] = set()
        with self.path.open("a", encoding="utf-8", newline="\n") as fh:
            for review in reviews:
                if review.review_id in seen:
                    continue  # guards --full re-walks and overlap pages
                seen.add(review.review_id)
                fh.write(json.dumps(review.to_dict(), ensure_ascii=False) + "\n")
                fh.flush()
                yield review

    def export_csv(self, out_path: Path) -> int:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        rows = 0
        # newline="" is required on Windows or csv writes \r\r\n.
        with out_path.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            for row in self.read():
                writer.writerow(row)
                rows += 1
        return rows

    # --- resume state ------------------------------------------------------

    def load_state(self) -> dict:
        if not self.state_path.exists():
            return {}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def save_state(self, token_state: dict | None, fetched: int) -> None:
        payload = {
            "continuation_token": token_state,
            "last_fetch_count": fetched,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.state_path)  # atomic on both POSIX and Windows

    def clear_state(self) -> None:
        self.state_path.unlink(missing_ok=True)
