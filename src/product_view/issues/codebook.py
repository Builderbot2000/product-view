"""The issue codebook: data/issues.db, kept across runs.

reviews.db is rebuilt on every run and cache.db holds only what can be
recomputed. The codebook is neither: an issue's identity is the point of it,
so it lives in its own file that `pv run` never deletes.

- `concepts`: every concept ever proposed, with its status. Live ones are
  the issues (kind `issue`) and general-sentiment groups (kind `general`).
  A live concept is frozen: its name and criterion never change (llm-trials.md,
  "frozen codebook"). Rejected candidates stay as the record of what was
  tried: `broad`, `joined` (same meaning as an earlier concept, named in
  `merged_into`) or `unselected` (lost the selection).
- `points`: what each review says, one row per point, from the distill step.
  Keyed by the distiller (model + prompt version), so a new model or prompt
  re-distills instead of mixing outputs.
- `distilled`: which reviews a distiller has read, including those that made
  no point, so they are not read again.
- `scores`: the raw agreement (0-1) of each point with each concept. Whether
  a score counts as a match is decided by whoever reads it (the threshold in
  config), not stored.
- `runs`: one row per side per `pv issues` run.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id       TEXT PRIMARY KEY,
    side         TEXT NOT NULL,          -- complaint | praise
    started_at   TEXT,
    finished_at  TEXT,
    model        TEXT,
    window_start TEXT,
    reviews      INTEGER,
    points       INTEGER,
    stats_json   TEXT
);

CREATE TABLE IF NOT EXISTS concepts (
    concept_id   TEXT PRIMARY KEY,
    side         TEXT NOT NULL,
    name         TEXT NOT NULL,
    criterion    TEXT NOT NULL,
    kind         TEXT NOT NULL,          -- issue | general
    area         TEXT,                   -- area id; issues only
    status       TEXT NOT NULL,          -- live | broad | joined | unselected
    merged_into  TEXT,                   -- for joined: the earlier concept it repeats
    parent       TEXT,                   -- a live issue whose matches contain most of this one's
    round        INTEGER,
    run_id       TEXT,
    created_at   TEXT,
    built_from   TEXT                    -- point ids it was named from (JSON)
);
CREATE INDEX IF NOT EXISTS ix_concepts_side ON concepts(side, status);

CREATE TABLE IF NOT EXISTS points (
    point_id   INTEGER PRIMARY KEY,
    review_id  TEXT NOT NULL,
    distiller  TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    side       TEXT NOT NULL,            -- complaint | praise
    quote      TEXT NOT NULL,            -- the reviewer's words
    exact      INTEGER NOT NULL,         -- 1 if the quote is found verbatim in the review
    bullet     TEXT NOT NULL,            -- a short neutral restatement
    UNIQUE (review_id, distiller, seq)
);
CREATE INDEX IF NOT EXISTS ix_points_review ON points(review_id);

CREATE TABLE IF NOT EXISTS distilled (
    review_id TEXT NOT NULL,
    distiller TEXT NOT NULL,
    PRIMARY KEY (review_id, distiller)
);

CREATE TABLE IF NOT EXISTS scores (
    concept_id TEXT NOT NULL,
    point_id   INTEGER NOT NULL,
    score      REAL NOT NULL,
    PRIMARY KEY (concept_id, point_id)
);
CREATE INDEX IF NOT EXISTS ix_scores_point ON scores(point_id);
"""

PREFIX = {"complaint": "C", "praise": "P"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Codebook:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Shared by the distill threads; every write goes through tx(), which locks.
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self._lock = threading.RLock()
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Codebook":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock, self.conn:
            yield self.conn

    # --- points --------------------------------------------------------------

    def undistilled(self, review_ids: Iterable[str], distiller: str) -> list[str]:
        done = {r[0] for r in self.conn.execute(
            "SELECT review_id FROM distilled WHERE distiller = ?", (distiller,))}
        return [r for r in review_ids if r not in done]

    def save_points(self, review_id: str, distiller: str, points: list[dict]) -> None:
        with self.tx() as c:
            c.executemany(
                "INSERT OR REPLACE INTO points (review_id, distiller, seq, side, quote, exact, bullet) "
                "VALUES (?,?,?,?,?,?,?)",
                [(review_id, distiller, p["seq"], p["side"], p["quote"], int(p["exact"]), p["bullet"])
                 for p in points])
            c.execute("INSERT OR REPLACE INTO distilled VALUES (?,?)", (review_id, distiller))

    def points(self, side: str, distiller: str, review_ids: set[str]) -> list[sqlite3.Row]:
        rows = self.conn.execute(
            "SELECT * FROM points WHERE side = ? AND distiller = ? ORDER BY review_id, seq",
            (side, distiller)).fetchall()
        return [r for r in rows if r["review_id"] in review_ids]

    # --- concepts ------------------------------------------------------------

    def concepts(self, side: str, status: str | None = "live") -> list[sqlite3.Row]:
        sql = "SELECT * FROM concepts WHERE side = ?" + (" AND status = ?" if status else "")
        return self.conn.execute(sql + " ORDER BY concept_id",
                                 (side, status) if status else (side,)).fetchall()

    def next_id(self, side: str) -> str:
        (n,) = self.conn.execute("SELECT COUNT(*) FROM concepts WHERE side = ?", (side,)).fetchone()
        return f"{PREFIX[side]}{n + 1:03d}"

    def add_concept(self, side: str, c: dict, run_id: str) -> str:
        cid = self.next_id(side)
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO concepts (concept_id, side, name, criterion, kind, area, status, merged_into, "
                "parent, round, run_id, created_at, built_from) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, side, c["name"], c["criterion"], c["kind"], c.get("area"), c["status"],
                 c.get("merged_into"), None, c.get("round"), run_id, now(),
                 json.dumps(c.get("built_from", []))))
        return cid

    def set_parents(self, parents: dict[str, str | None]) -> None:
        with self.tx() as c:
            c.executemany("UPDATE concepts SET parent = ? WHERE concept_id = ?",
                          [(p, cid) for cid, p in parents.items()])

    # --- scores --------------------------------------------------------------

    def scored(self, concept_id: str) -> dict[int, float]:
        return {r[0]: r[1] for r in self.conn.execute(
            "SELECT point_id, score FROM scores WHERE concept_id = ?", (concept_id,))}

    def save_scores(self, concept_id: str, scores: dict[int, float]) -> None:
        with self.tx() as c:
            c.executemany("INSERT OR REPLACE INTO scores VALUES (?,?,?)",
                          [(concept_id, pid, s) for pid, s in scores.items()])

    def members(self, side: str, threshold: float) -> list[sqlite3.Row]:
        """Every (live concept, point) match at or above the threshold, closest first."""
        return self.conn.execute(
            """SELECT c.concept_id, p.point_id, p.review_id, p.quote, p.bullet, s.score
                 FROM scores s
                 JOIN concepts c ON c.concept_id = s.concept_id
                 JOIN points p ON p.point_id = s.point_id
                WHERE c.side = ? AND c.status = 'live' AND s.score >= ?
                ORDER BY c.concept_id, s.score DESC, p.review_id, p.seq""",
            (side, threshold)).fetchall()

    # --- runs ----------------------------------------------------------------

    def save_run(self, run: dict) -> None:
        with self.tx() as c:
            c.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?,?)",
                      (run["run_id"], run["side"], run["started_at"], run.get("finished_at"),
                       run["model"], run["window_start"], run["reviews"], run["points"],
                       json.dumps(run.get("stats", {}))))

    def latest_run(self, side: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM runs WHERE side = ? AND finished_at IS NOT NULL "
            "ORDER BY started_at DESC LIMIT 1", (side,)).fetchone()
