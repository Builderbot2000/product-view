"""`pv cycle`: one full cycle, then exit (docs/production-plan.md §0, step 7).

fetch -> db build -> translate -> match -> report -> publish. Email is
deferred until the delivery integration is settled, so a cycle ends at
publishing. The host's scheduler (cron, a Kubernetes CronJob, a cloud job
service) decides when cycles run; the image runs one and exits:

- exit 0 on success, 1 when a step fails, 3 when another cycle holds the lock;
- a one-line summary on stdout, and a row in topics.db's `cycles` table;
- one cycle at a time per data volume, by a lock file in the data directory.
  A lock older than STALE_HOURS is taken to be left by a crashed cycle;
- re-running in the same period is safe: pages are updated in place, as a
  new version.

Nothing is published unless every step before it succeeded, so a failed
cycle never leaves half a report.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("cycle")

LOCK = "pv-cycle.lock"
STALE_HOURS = 12
EXIT_FAILED, EXIT_LOCKED = 1, 3

CYCLES = """
CREATE TABLE IF NOT EXISTS cycles (
    cycle_id     TEXT PRIMARY KEY,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    status       TEXT NOT NULL,      -- running | done | failed
    step         TEXT,               -- the step running, or the one that failed
    match_run    TEXT,
    published    INTEGER,
    summary      TEXT
);
"""


class Locked(RuntimeError):
    pass


class Lock:
    """An exclusive lock file on the data volume."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def __enter__(self) -> "Lock":
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                age = (time.time() - self.path.stat().st_mtime) / 3600
                if age < STALE_HOURS:
                    raise Locked(f"another cycle is running (lock {self.path}, "
                                 f"{age * 60:.0f} min old: {self.path.read_text().strip()})")
                log.warning("removing a stale lock %s, %.0f hours old", self.path, age)
                self.path.unlink(missing_ok=True)
                continue
            with os.fdopen(fd, "w") as fh:
                fh.write(f"pid {os.getpid()} on {socket.gethostname()} since "
                         f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}\n")
            return self
        raise Locked(f"could not take the lock {self.path}")

    def __exit__(self, *exc: object) -> None:
        self.path.unlink(missing_ok=True)


def _record(db_path: Path, cycle_id: str, **fields) -> None:
    import sqlite3

    from .topics.store import now

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(CYCLES)
        with conn:
            if conn.execute("SELECT 1 FROM cycles WHERE cycle_id = ?", (cycle_id,)).fetchone():
                sets = ", ".join(f"{k} = ?" for k in fields)
                conn.execute(f"UPDATE cycles SET {sets} WHERE cycle_id = ?",
                             [*fields.values(), cycle_id])
            else:
                fields = {"started_at": now(), "status": "running", **fields}
                cols = ["cycle_id", *fields]
                conn.execute(f"INSERT INTO cycles ({','.join(cols)}) "
                             f"VALUES ({','.join('?' * len(cols))})", [cycle_id, *fields.values()])
    finally:
        conn.close()


def _review_count(args: argparse.Namespace) -> int:
    from .store import Store

    path = Path(args.data_dir) / "reviews.db"
    if not path.exists():
        return 0
    with Store(path) as store:
        return store.count("reviews")


def cmd_cycle(args: argparse.Namespace) -> int:
    from . import render
    from .cli import cmd_fetch
    from .commands import cmd_db_build, cmd_translate
    from .topics import load_matrix, run_match, topic_db
    from .topics.store import now

    data = Path(args.data_dir)
    data.mkdir(parents=True, exist_ok=True)
    cycle_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    db = topic_db(args)
    t0 = time.time()
    step = "lock"
    try:
        with Lock(data / LOCK):
            _record(db, cycle_id)
            matrix = load_matrix(args)     # a broken matrix fails before any fetching
            if matrix is None:
                raise RuntimeError("the matrix file has problems (listed above)")
            before = _review_count(args)

            def run(name: str, fn) -> None:
                nonlocal step
                step = name
                _record(db, cycle_id, step=name)
                print(f"\n== {name}", flush=True)
                if rc := fn(args):
                    raise RuntimeError(f"{name} exited with status {rc}")

            if args.fetch:
                args.resume = False        # a top-up, never a backfill
                args.full = False
                run("fetch", cmd_fetch)
            run("db build", cmd_db_build)
            run("translate", cmd_translate)
            new = _review_count(args) - before

            step = "match"
            _record(db, cycle_id, step=step)
            print("\n== match", flush=True)
            match_run = run_match(args, matrix)
            _record(db, cycle_id, match_run=match_run)

            step = "report"
            _record(db, cycle_id, step=step)
            print("\n== report", flush=True)
            built = render._team_pages(args)
            if isinstance(built, int):
                raise RuntimeError(f"report exited with status {built}")
            render.write(built, Path(args.out))
            published = 0
            if args.publish and args.space:
                step = "publish"
                _record(db, cycle_id, step=step)
                print("\n== publish", flush=True)
                if rc := render.publish(args, built):
                    raise RuntimeError(f"publish exited with status {rc}")
                published = len(built)
            where = (f"{published} pages published to {args.space}" if published
                     else f"{len(built)} pages written to {args.out}"
                          + ("" if not args.publish else " (not published: no confluence.space)"))
            summary = (f"pv cycle {cycle_id} ok in {(time.time() - t0) / 60:.1f} min: "
                       f"{new} new reviews, match run {match_run}, {where}")
            _record(db, cycle_id, status="done", step=None, finished_at=now(),
                    published=published, summary=summary)
    except Locked as exc:
        print(f"pv cycle: {exc}", file=sys.stderr)
        return EXIT_LOCKED
    except BaseException as exc:
        summary = f"pv cycle {cycle_id} FAILED at {step}: {type(exc).__name__}: {exc}"
        try:
            _record(db, cycle_id, status="failed", finished_at=now(), summary=summary[:2000])
        except Exception:          # the record is best effort; the exit status is what counts
            pass
        print(summary, flush=True)
        if not isinstance(exc, Exception):
            raise
        return EXIT_FAILED
    print(summary, flush=True)
    return 0


class JsonFormatter(logging.Formatter):
    """One JSON object per line, for log collectors (PV_LOG_JSON=1)."""

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({"time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
                           "level": record.levelname, "logger": record.name,
                           "message": record.getMessage()}, ensure_ascii=False)


def add_parser(sub, common, add_fetch_options) -> None:
    p = sub.add_parser("cycle", help="one full cycle: fetch, build, match, report, publish")
    common(p)
    add_fetch_options(p)
    p.add_argument("--fetch", action=argparse.BooleanOptionalAction, default=True,
                   help="top up the archive from the Play Store first (default: on)")
    p.add_argument("--publish", action=argparse.BooleanOptionalAction, default=True,
                   help="publish to Confluence when confluence.space is set (default: on)")
    p.add_argument("--matrix", help="matrix file")
    p.add_argument("--min-chars", type=int)
    p.add_argument("--out", default="out/report", help="output folder (default: out/report)")
    p.add_argument("--space", help="Confluence space key")
    p.add_argument("--parent-id", help="create the top page(s) under this page ID")
    p.set_defaults(func=cmd_cycle, title=None, app_name=None, period_days=None,
                   baseline_periods=None)
