"""SQLite store — everything derived from the raw JSONL archive.

Two files, split by what they cost to recreate:

- `reviews.db` — reviews, listing snapshots, runs, pain points. Rebuilt clean
  from the JSONL archive on every `pv run` / `pv db build`, so it only ever
  holds the current result and never accumulates stale runs.
- `cache.db` — translations (keyed by review_id) and segment vectors (keyed
  by review_id + position). Model output that costs ~25 minutes of CPU to
  recompute, so it survives the rebuild.
  It is ATTACHed as schema `cache`; SQLite resolves unqualified table names
  across attached databases, so queries join the two as if they were one.

JSONL stays the landing zone and is never touched here, so deleting either
database is never data loss. Clustering is where SQLite earns its place:
embeddings as BLOBs, run history, and per-cluster membership are all awkward
in flat files.

Anything a reader might want to sort a pain point table by is a real column
rather than a field inside a JSON blob, so `ORDER BY` serves the terminal view
and the future dashboard from identical data.
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

CREATE TABLE IF NOT EXISTS runs (
    run_id              TEXT PRIMARY KEY,
    started_at          TEXT,
    finished_at         TEXT,
    app_id              TEXT,
    polarity            TEXT,
    algorithm           TEXT,
    granularity         TEXT,
    seed                INTEGER,
    params_json         TEXT,
    stream_size         INTEGER,      -- reviews
    unit_count          INTEGER,      -- complaint units those reviews split into
    unclustered         INTEGER,      -- units in no pain point
    uncovered_reviews   INTEGER,      -- reviews with no unit in any pain point
    corpus_monthly_json TEXT          -- shared denominator for every series
);

CREATE TABLE IF NOT EXISTS pain_points (
    run_id              TEXT NOT NULL,
    pain_point_id       TEXT NOT NULL,
    polarity            TEXT,
    title               TEXT,
    message             TEXT,
    keywords_json       TEXT,
    canonical_review_id TEXT,
    canonical_text      TEXT,         -- the medoid unit: the part of that review that placed it here
    -- sortable columns
    size                INTEGER,      -- distinct reviews, not units
    unit_count          INTEGER,
    sole_share          REAL,         -- share of its reviews where it is the only pain point
    pct_of_stream       REAL,
    mean_score          REAL,
    pct_one_star        REAL,
    thumbs_up_total     INTEGER,
    cohesion            REAL,
    first_seen          TEXT,
    last_seen           TEXT,
    peak_month          TEXT,
    peak_count          INTEGER,
    count_90d           INTEGER,
    count_365d          INTEGER,
    impact              REAL,
    c_recency           REAL,
    c_severity          REAL,
    c_momentum          REAL,
    c_endorsement       REAL,
    monthly_counts_json TEXT,
    representative_json TEXT,       -- MMR-selected quotes, not the most central
    centroid            BLOB,
    PRIMARY KEY (run_id, pain_point_id)
);

-- One row per complaint unit, so a review can sit in several pain points (and
-- twice in one, if it makes the same point twice). `unit_text` is kept because
-- units are formed at cluster time: it is what traces a pain point to the
-- exact words that put a review in it.
CREATE TABLE IF NOT EXISTS pain_point_members (
    run_id        TEXT NOT NULL,
    pain_point_id TEXT NOT NULL,
    review_id     TEXT NOT NULL REFERENCES reviews(review_id),
    unit_seq      INTEGER NOT NULL,
    unit_text     TEXT,
    similarity    REAL,
    PRIMARY KEY (run_id, pain_point_id, review_id, unit_seq)
);
CREATE INDEX IF NOT EXISTS ix_members_review ON pain_point_members(review_id);
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

-- Fine segments of each review (embed/segment.py) with their vectors.
-- `splitter` is the rule version they were cut with; a review split under
-- another version is re-split and re-encoded by `pv embed`.
CREATE TABLE IF NOT EXISTS cache.segments (
    review_id TEXT NOT NULL,
    model     TEXT NOT NULL,
    seq       INTEGER NOT NULL,
    splitter  TEXT NOT NULL,
    text      TEXT NOT NULL,
    dim       INTEGER NOT NULL,
    vector    BLOB NOT NULL,
    PRIMARY KEY (review_id, model, seq)
);
"""

# Tables a pre-split reviews.db may still hold in `main`, moved to `cache`.
CACHE_TABLES = ("translations",)

# Held in `main` by old databases and no longer used anywhere: whole-review
# vectors, from before clustering moved to complaint units.
OBSOLETE_TABLES = ("embeddings",)

# The clustering-result tables, and a column each has only in its current
# shape. They are cheap to recreate -- every `pv cluster` rewrites them -- so
# an older shape is dropped and recreated rather than migrated column by
# column (members also changed primary key, which ALTER TABLE cannot do).
RESULT_TABLES = {
    "runs": "unit_count",
    "pain_points": "sole_share",
    "pain_point_members": "unit_seq",
}

# Columns `pv painpoints --sort` accepts. Whitelisted rather than interpolated
# freely: these go straight into an ORDER BY clause.
SORTABLE = (
    "impact", "size", "unit_count", "sole_share", "pct_of_stream", "mean_score", "pct_one_star",
    "thumbs_up_total", "cohesion", "first_seen", "last_seen", "peak_month",
    "peak_count", "count_90d", "count_365d",
    "c_recency", "c_severity", "c_momentum", "c_endorsement",
)

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
        self._migrate()

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

    def _migrate(self) -> None:
        """Recreate result tables left in an older shape.

        CREATE TABLE IF NOT EXISTS silently keeps an older table's shape, so a
        new column would otherwise fail at insert time on a database that
        predates it. Only the result tables change shape, and a clustering run
        rewrites them anyway, so they are dropped together -- a run split
        across two schemas would be worse than none.
        """
        stale = False
        for table, marker in RESULT_TABLES.items():
            have = {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})")}
            stale = stale or marker not in have
        if stale:
            with self.conn:
                for table in RESULT_TABLES:
                    self.conn.execute(f"DROP TABLE IF EXISTS main.{table}")
            self.conn.executescript(SCHEMA)

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
        """The reviews entering a clustering run, with translations joined.

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
        """Reviews long enough to cluster that `pv translate` hasn't seen."""
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

    # --- segments ----------------------------------------------------------

    def unsegmented(self, model: str, splitter: str) -> list:
        """Translated reviews with no segments for `model` under `splitter`.

        Joining through `translations` is what keeps dropped non-Latin reviews
        out of the pass without a second filter. A review split by an older
        rule version comes back here too, so changing the rules re-splits
        exactly what they affect.
        """
        return self.conn.execute(
            """
            SELECT r.review_id, COALESCE(t.content_en, r.content) AS content_en
              FROM reviews r
              JOIN translations t ON t.review_id = r.review_id
             WHERE t.content_en IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1 FROM segments s
                    WHERE s.review_id = r.review_id AND s.model = ?
                      AND s.splitter = ?)
             ORDER BY r.review_id
            """,
            (model, splitter),
        ).fetchall()

    def save_segments(
        self, model: str, splitter: str, dim: int,
        rows: Iterable[tuple[str, int, str, bytes]],
    ) -> int:
        """(review_id, seq, text, vector). Replaces each review's segments
        whole, so a re-split that yields fewer pieces leaves no stale tail."""
        rows = list(rows)
        with self.tx() as conn:
            conn.executemany(
                "DELETE FROM segments WHERE review_id = ? AND model = ?",
                [(rid, model) for rid in {r[0] for r in rows}],
            )
            conn.executemany(
                "INSERT INTO segments (review_id, model, seq, splitter, text, dim, vector) "
                "VALUES (?,?,?,?,?,?,?)",
                [(rid, model, seq, splitter, text, dim, blob)
                 for rid, seq, text, blob in rows],
            )
        return len(rows)

    def load_segments(
        self, model: str, review_ids: Sequence[str]
    ) -> dict[str, list[tuple[str, bytes]]]:
        """{review_id: [(text, vector), ...] in reading order}, chunked around
        SQLite's 999-variable limit."""
        out: dict[str, list[tuple[str, bytes]]] = {}
        for i in range(0, len(review_ids), 900):
            chunk = review_ids[i : i + 900]
            q = ",".join("?" * len(chunk))
            for rid, text, blob in self.conn.execute(
                f"SELECT review_id, text, vector FROM segments "
                f"WHERE model = ? AND review_id IN ({q}) ORDER BY review_id, seq",
                (model, *chunk),
            ):
                out.setdefault(rid, []).append((text, blob))
        return out

    def translation_summary(self) -> list:
        return self.conn.execute(
            "SELECT detected_lang, COUNT(*) n, "
            "SUM(CASE WHEN content_en IS NULL THEN 1 ELSE 0 END) dropped "
            "FROM translations GROUP BY detected_lang ORDER BY n DESC"
        ).fetchall()

    # --- runs and pain points ----------------------------------------------

    def save_run(self, run: dict) -> None:
        with self.tx() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO runs (run_id, started_at, finished_at, app_id, "
                "polarity, algorithm, granularity, seed, params_json, stream_size, "
                "unit_count, unclustered, uncovered_reviews, corpus_monthly_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run["run_id"], run.get("started_at"), run.get("finished_at"),
                    run.get("app_id"), run.get("polarity"), run.get("algorithm"),
                    run.get("granularity"), run.get("seed"),
                    json.dumps(run.get("params", {})),
                    run.get("stream_size"), run.get("unit_count"),
                    run.get("unclustered"), run.get("uncovered_reviews"),
                    json.dumps(run.get("corpus_monthly", {})),
                ),
            )

    def save_pain_points(self, run_id: str, rows: Iterable[dict]) -> int:
        cols = (
            "run_id", "pain_point_id", "polarity", "title", "message",
            "keywords_json", "canonical_review_id", "canonical_text", "size",
            "unit_count", "sole_share", "pct_of_stream",
            "mean_score", "pct_one_star", "thumbs_up_total", "cohesion",
            "first_seen", "last_seen", "peak_month", "peak_count",
            "count_90d", "count_365d", "impact", "c_recency", "c_severity",
            "c_momentum", "c_endorsement", "monthly_counts_json",
            "representative_json", "centroid",
        )
        rows = list(rows)
        with self.tx() as conn:
            conn.executemany(
                f"INSERT OR REPLACE INTO pain_points ({','.join(cols)}) "
                f"VALUES ({','.join('?' * len(cols))})",
                [tuple(r.get(c) for c in cols) for r in rows],
            )
        return len(rows)

    def save_members(self, rows: Iterable[tuple[str, str, str, int, str, float]]) -> int:
        """(run_id, pain_point_id, review_id, unit_seq, unit_text, similarity)"""
        rows = list(rows)
        with self.tx() as conn:
            conn.executemany(
                "INSERT INTO pain_point_members "
                "(run_id, pain_point_id, review_id, unit_seq, unit_text, similarity) "
                "VALUES (?,?,?,?,?,?)",
                rows,
            )
        return len(rows)

    def clear_polarity(self, polarity: str) -> int:
        """Drop every stored run for one stream, so a new clustering replaces
        the previous one instead of accumulating beside it."""
        with self.tx() as conn:
            conn.execute(
                "DELETE FROM pain_point_members WHERE run_id IN "
                "(SELECT run_id FROM runs WHERE polarity = ?)", (polarity,))
            conn.execute(
                "DELETE FROM pain_points WHERE run_id IN "
                "(SELECT run_id FROM runs WHERE polarity = ?)", (polarity,))
            return conn.execute(
                "DELETE FROM runs WHERE polarity = ?", (polarity,)).rowcount

    def clear_run(self, run_id: str) -> None:
        with self.tx() as conn:
            conn.execute("DELETE FROM pain_points WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM pain_point_members WHERE run_id = ?", (run_id,))

    def latest_run(self, polarity: str | None = None) -> sqlite3.Row | None:
        sql = "SELECT * FROM runs"
        args: tuple = ()
        if polarity:
            sql += " WHERE polarity = ?"
            args = (polarity,)
        sql += " ORDER BY started_at DESC LIMIT 1"
        return self.conn.execute(sql, args).fetchone()

    def pain_points(
        self, run_id: str, sort: str = "impact", desc: bool = True, limit: int = 20
    ) -> list[sqlite3.Row]:
        if sort not in SORTABLE:
            raise ValueError(f"unsortable column {sort!r}; choose from {', '.join(SORTABLE)}")
        return self.conn.execute(
            f"SELECT * FROM pain_points WHERE run_id = ? "
            f"ORDER BY {sort} {'DESC' if desc else 'ASC'} LIMIT ?",
            (run_id, limit),
        ).fetchall()

    def members(self, run_id: str, pain_point_id: str, limit: int = 5) -> list[sqlite3.Row]:
        """Most-central members. For the supporting quotes a reader should see,
        use `reviews_by_id` with the pain point's `representative_json` -- MMR
        picks span the range of phrasing, where these five are near-identical
        restatements of the medoid."""
        return self.conn.execute(
            """
            SELECT m.review_id, m.unit_seq, m.unit_text, m.similarity,
                   r.content, r.score, r.created_at, t.detected_lang, t.content_en
              FROM pain_point_members m
              JOIN reviews r ON r.review_id = m.review_id
              LEFT JOIN translations t ON t.review_id = m.review_id
             WHERE m.run_id = ? AND m.pain_point_id = ?
             ORDER BY m.similarity DESC LIMIT ?
            """,
            (run_id, pain_point_id, limit),
        ).fetchall()

    def unit_texts(
        self, run_id: str, pain_point_id: str, review_ids: Sequence[str]
    ) -> dict[str, str]:
        """{review_id: the words of that review that placed it in this pain
        point}. A review making the point twice keeps its more central unit."""
        if not review_ids:
            return {}
        q = ",".join("?" * len(review_ids))
        out: dict[str, str] = {}
        for rid, text in self.conn.execute(
            f"SELECT review_id, unit_text FROM pain_point_members "
            f"WHERE run_id = ? AND pain_point_id = ? AND review_id IN ({q}) "
            f"ORDER BY similarity ASC",
            (run_id, pain_point_id, *review_ids),
        ):
            out[rid] = text
        return out

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
