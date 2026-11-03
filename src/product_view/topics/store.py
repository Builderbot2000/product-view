"""topics.db: every matching run, and what it matched, stored raw.

Kept across runs, like the archive: reviews.db is rebuilt clean on every
build, and cache.db holds model output that could be recomputed. Each run
re-matches its whole window, because self-training makes a unit's probability
depend on the other units beside it, so a run's rows stand on their own and
reports read the latest finished run. Counts, trends and "no topic" are
derived from the raw rows by the reader (report-design.md: store raw, let
the consumer derive).

- runs:    one row per run: when, the matrix and models, the window, totals.
- units:   every unit the run saw, how it was routed (sure | model | misc),
           its best topic and that topic's probability, its text and quote.
- matches: (unit, topic) pairs, and how each was decided (sure | model).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    status        TEXT NOT NULL,      -- running | done | failed
    matrix        TEXT,
    topic_hash    TEXT,
    chat_model    TEXT,
    embed_model   TEXT,
    window_start  TEXT,
    window_end    TEXT,
    reviews       INTEGER,
    units         INTEGER,
    sure          INTEGER,
    model         INTEGER,
    misc          INTEGER,
    calls         INTEGER,
    error         TEXT
);
CREATE TABLE IF NOT EXISTS units (
    run_id      TEXT NOT NULL,
    review_id   TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    route       TEXT NOT NULL,
    best_topic  TEXT,
    p1          REAL,
    text        TEXT,
    quote       TEXT,
    PRIMARY KEY (run_id, review_id, seq)
);
CREATE TABLE IF NOT EXISTS matches (
    run_id      TEXT NOT NULL,
    review_id   TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    topic_id    TEXT NOT NULL,
    how         TEXT NOT NULL,
    PRIMARY KEY (run_id, review_id, seq, topic_id)
);
CREATE INDEX IF NOT EXISTS ix_matches_topic ON matches(run_id, topic_id);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TopicStore:
    def __init__(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "TopicStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def start(self, run_id: str, **fields) -> None:
        cols = ["run_id", "started_at", "status", *fields]
        with self.conn:
            self.conn.execute(
                f"INSERT INTO runs ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                [run_id, now(), "running", *fields.values()])

    def finish(self, run_id: str, unit_rows: list[tuple], match_rows: list[tuple],
               **fields) -> None:
        """Write the run's rows and mark it done, in one transaction: a run
        that fails part way leaves no rows for a report to read."""
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self.conn:
            self.conn.executemany("INSERT INTO units VALUES (?,?,?,?,?,?,?,?)",
                                  [(run_id, *u) for u in unit_rows])
            self.conn.executemany("INSERT INTO matches VALUES (?,?,?,?,?)",
                                  [(run_id, *m) for m in match_rows])
            self.conn.execute(f"UPDATE runs SET status = 'done', finished_at = ?"
                              f"{', ' + sets if sets else ''} WHERE run_id = ?",
                              [now(), *fields.values(), run_id])

    def fail(self, run_id: str, error: str) -> None:
        with self.conn:
            self.conn.execute("UPDATE runs SET status = 'failed', finished_at = ?, error = ? "
                              "WHERE run_id = ?", (now(), error[:2000], run_id))

    def latest(self) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM runs WHERE status = 'done' "
                                 "ORDER BY started_at DESC, run_id DESC LIMIT 1").fetchone()

    def units(self, run_id: str) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM units WHERE run_id = ? ORDER BY review_id, seq",
                                 (run_id,)).fetchall()

    def matches(self, run_id: str) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM matches WHERE run_id = ? "
                                 "ORDER BY review_id, seq, topic_id", (run_id,)).fetchall()
