"""SQLite store for reviews -- everything derived from the raw JSONL archive.

Two files here, split by what they cost to recreate:

- `reviews.db` -- reviews and listing snapshots. Rebuilt clean from the JSONL
  archive on every `pv run` / `pv db build`.
- `cache.db` -- translations (keyed by review_id), plus the model answers the
  issue stage caches there (issues/llm.py). Model output that costs real time
  to recompute, so it survives the rebuild. It is ATTACHed as schema `cache`;
  SQLite resolves unqualified table names across attached databases, so
  queries join the two as if they were one.

The issue codebook is a third file, issues.db (issues/codebook.py), kept
across runs. JSONL stays the landing zone and is never touched here, so
deleting reviews.db or cache.db is never data loss.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator, Sequence

SCHEMA = """
CREATE TABLE IF NOT EXISTS reviews (
    review_id              TEXT PRIMARY KEY,
    app_id                 TEXT NOT NULL,
    source                 TEXT,
    lang                   TEXT,
    country                TEXT,
    content                TEXT NOT NULL,
    score                  INTEGER,
    thumbs_up              INTEGER,
    created_at             TEXT,
    app_version            TEXT,
    review_created_version TEXT,
    reply_content          TEXT,
    replied_at             TEXT,
    fetched_at             TEXT,
    content_hash           TEXT
);
CREATE INDEX IF NOT EXISTS ix_reviews_score   ON reviews(score);
CREATE INDEX IF NOT EXISTS ix_reviews_created ON reviews(created_at);

CREATE TABLE IF NOT EXISTS app_metadata (
    fetched_at     TEXT PRIMARY KEY,
    app_id         TEXT,
    score          REAL,
    ratings        INTEGER,
    reviews        INTEGER,
    histogram_json TEXT,
    installs       TEXT,
    version        TEXT
);
"""

# No REFERENCES clauses: SQLite foreign keys cannot cross database files.
CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache.translations (
    review_id      TEXT PRIMARY KEY,
    detected_lang  TEXT,
    confidence     REAL,
    content_en     TEXT,
    model          TEXT,
    translated_at  TEXT
);
CREATE INDEX IF NOT EXISTS cache.ix_translations_lang ON translations(detected_lang);
"""

# Tables a pre-split reviews.db may still hold in `main`, moved to `cache`.
CACHE_TABLES = ("translations",)

# Left in reviews.db by earlier versions and no longer used: whole-review
# vectors, then the embedding-clustering results (replaced by the issue stage).
# cache.db may still hold the old `segments` table; nothing reads it.
OBSOLETE_TABLES = ("embeddings", "runs", "pain_points", "pain_point_members")

_REVIEW_COLUMNS = (
    "review_id", "app_id", "source", "lang", "country", "content", "score",
    "thumbs_up", "created_at", "app_version", "review_created_version",
    "reply_content", "replied_at", "fetched_at", "content_hash",
)


def reset(path: Path) -> None:
    """Delete a database file and its WAL sidecars, so the next open is clean."""
    path = Path(path)
    for p in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        p.unlink(missing_ok=True)


class Store:
    def __init__(self, path: Path, cache_path: Path | None = None) -> None:
        self.path = Path(path)
        self.cache_path = Path(cache_path) if cache_path else self.path.with_name("cache.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("ATTACH DATABASE ? AS cache", (str(self.cache_path),))
        self.conn.execute("PRAGMA cache.journal_mode=WAL")
        self.conn.executescript(CACHE_SCHEMA)
        self._move_cache_out_of_main()
        self.conn.executescript(SCHEMA)

    def _move_cache_out_of_main(self) -> None:
        """Databases built before the split hold translations in `main`. Move
        them to `cache` once, then drop them from `main` -- left in place,
        `main` would shadow `cache` for every unqualified query.
        """
        for table in CACHE_TABLES:
            if self._has_table(table):
                with self.conn:
                    self.conn.execute(
                        f"INSERT OR IGNORE INTO cache.{table} SELECT * FROM main.{table}"
                    )
                    self.conn.execute(f"DROP TABLE main.{table}")
        with self.conn:
            for table in OBSOLETE_TABLES:
                self.conn.execute(f"DROP TABLE IF EXISTS main.{table}")

    def _has_table(self, table: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM main.sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone() is not None

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self.conn:
            yield self.conn

    # --- reviews -----------------------------------------------------------

    def upsert_reviews(self, rows: Iterable[dict]) -> int:
        """Load merged corpus rows. Idempotent, so rebuilds are safe."""
        sql = (
            f"INSERT OR REPLACE INTO reviews ({','.join(_REVIEW_COLUMNS)}) "
            f"VALUES ({','.join('?' * len(_REVIEW_COLUMNS))})"
        )
        n = 0
        with self.tx() as conn:
            batch: list[tuple] = []
            for row in rows:
                batch.append(tuple(row.get(c) for c in _REVIEW_COLUMNS))
                if len(batch) >= 2000:
                    conn.executemany(sql, batch)
                    n += len(batch)
                    batch.clear()
            if batch:
                conn.executemany(sql, batch)
                n += len(batch)
        return n

    def count(self, table: str) -> int:
        return self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def upsert_app_metadata(self, snaps: Iterable[dict]) -> int:
        sql = (
            "INSERT OR REPLACE INTO app_metadata "
            "(fetched_at, app_id, score, ratings, reviews, histogram_json, installs, version) "
            "VALUES (?,?,?,?,?,?,?,?)"
        )
        rows = [
            (
                s.get("fetched_at"), s.get("app_id"), s.get("score"),
                s.get("ratings"), s.get("reviews"),
                json.dumps(s.get("histogram")) if s.get("histogram") else None,
                s.get("installs"), s.get("version"),
            )
            for s in snaps
        ]
        with self.tx() as conn:
            conn.executemany(sql, rows)
        return len(rows)

    # --- streams -----------------------------------------------------------

    def stream(
        self,
        polarity: str,
        min_chars: int = 20,
        negative_max_score: int = 3,
        positive_min_score: int = 4,
        app_id: str | None = None,
    ) -> list[sqlite3.Row]:
        """One star-rating stream (the report's review totals), translations joined.

        `content_en` falls back to `content` so this is usable before
        `pv translate` has run; rows whose translation was dropped
        (non-Latin script) are excluded once translation exists.
        """
        if polarity == "negative":
            score_clause = "r.score <= ?"
            score_arg: int = negative_max_score
        elif polarity == "positive":
            score_clause = "r.score >= ?"
            score_arg = positive_min_score
        else:
            raise ValueError(f"unknown polarity {polarity!r}")

        sql = f"""
            SELECT r.review_id, r.content, r.score, r.thumbs_up, r.created_at,
                   r.app_version, r.lang,
                   COALESCE(t.content_en, r.content) AS content_en,
                   t.detected_lang
              FROM reviews r
              LEFT JOIN translations t ON t.review_id = r.review_id
             WHERE {score_clause}
               AND r.score > 0
               AND LENGTH(TRIM(r.content)) >= ?
               AND (t.review_id IS NULL OR t.content_en IS NOT NULL)
               {"AND r.app_id = ?" if app_id else ""}
             ORDER BY r.review_id
        """
        args: list = [score_arg, min_chars]
        if app_id:
            args.append(app_id)
        return self.conn.execute(sql, args).fetchall()

    def untranslated(self, min_chars: int = 20) -> list[sqlite3.Row]:
        """Reviews long enough to group that `pv translate` hasn't seen."""
        return self.conn.execute(
            """
            SELECT r.review_id, r.content
              FROM reviews r
              LEFT JOIN translations t ON t.review_id = r.review_id
             WHERE t.review_id IS NULL
               AND LENGTH(TRIM(r.content)) >= ?
             ORDER BY r.review_id
            """,
            (min_chars,),
        ).fetchall()

    def save_translations(self, rows: Iterable[Sequence]) -> int:
        """(review_id, detected_lang, confidence, content_en, model, translated_at)"""
        rows = list(rows)
        with self.tx() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO translations "
                "(review_id, detected_lang, confidence, content_en, model, translated_at) "
                "VALUES (?,?,?,?,?,?)",
                rows,
            )
        return len(rows)

    def translation_summary(self) -> list:
        return self.conn.execute(
            "SELECT detected_lang, COUNT(*) n, "
            "SUM(CASE WHEN content_en IS NULL THEN 1 ELSE 0 END) dropped "
            "FROM translations GROUP BY detected_lang ORDER BY n DESC"
        ).fetchall()

    def reviews_by_id(self, review_ids: Sequence[str]) -> list[sqlite3.Row]:
        """Fetch specific reviews, preserving the order given."""
        if not review_ids:
            return []
        q = ",".join("?" * len(review_ids))
        rows = {
            r["review_id"]: r
            for r in self.conn.execute(
                f"""
                SELECT r.review_id, r.content, r.score, r.created_at,
                       t.detected_lang, t.content_en
                  FROM reviews r
                  LEFT JOIN translations t ON t.review_id = r.review_id
                 WHERE r.review_id IN ({q})
                """,
                tuple(review_ids),
            )
        }
        return [rows[i] for i in review_ids if i in rows]
