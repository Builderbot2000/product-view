"""The team -> member -> topic matrix (report-design.md D18, D19).

`matrix.yaml` if present, else `matrix.sample.yaml`; `PV_MATRIX` overrides
both, so a cloud host can mount the real file as a secret. The real matrix
holds staff names and addresses and is never committed (.gitignore).

Loading validates the D19 rules and fails with every problem listed at once,
since the file is edited by hand (or by an assistant) and one round of fixes
should be enough. The hash covers only what changes the matching (topic ids,
names and descriptions), so moving a member between teams never re-matches.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

ENV_PATH = "PV_MATRIX"
REAL = Path("matrix.yaml")
SAMPLE = Path("matrix.sample.yaml")

_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class MatrixError(ValueError):
    pass


@dataclass(frozen=True)
class Topic:
    id: str
    name: str
    description: str


@dataclass(frozen=True)
class Member:
    name: str
    email: str
    topics: tuple[str, ...]


@dataclass(frozen=True)
class Team:
    id: str
    name: str
    mailing_list: str | None
    members: tuple[Member, ...]

    @property
    def topics(self) -> tuple[str, ...]:
        """Every topic a member owns, in first-listed order."""
        return tuple(dict.fromkeys(t for m in self.members for t in m.topics))


@dataclass(frozen=True)
class Matrix:
    path: Path
    topics: dict[str, Topic]
    teams: dict[str, Team]

    @property
    def is_sample(self) -> bool:
        return self.path.name == SAMPLE.name

    @property
    def topic_hash(self) -> str:
        """Changes when, and only when, the matching would change."""
        data = [[t.id, t.name, t.description] for t in self.topics.values()]
        return hashlib.sha256(json.dumps(data).encode()).hexdigest()[:12]


def default_path() -> Path:
    if env := os.environ.get(ENV_PATH):
        return Path(env)
    return REAL if REAL.exists() else SAMPLE


def load(path: str | Path | None = None) -> Matrix:
    import yaml

    path = Path(path) if path else default_path()
    if not path.exists():
        raise MatrixError(f"matrix file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    problems: list[str] = []
    if not isinstance(data, dict):
        raise MatrixError(f"{path}: top level must be a mapping with topics and teams")
    for key in sorted(set(data) - {"topics", "teams"}):
        problems.append(f"unknown top-level key {key!r} (expected topics, teams)")

    topics: dict[str, Topic] = {}
    for tid, t in (data.get("topics") or {}).items():
        tid = str(tid)
        if not _ID.match(tid):
            problems.append(f"topic id {tid!r}: use lowercase words joined by hyphens")
        if not isinstance(t, dict) or not t.get("name") or not t.get("description"):
            problems.append(f"topic {tid!r}: needs a name and a description")
            continue
        extra = set(t) - {"name", "description"}
        if extra:
            problems.append(f"topic {tid!r}: unknown key(s) {', '.join(sorted(extra))}")
        topics[tid] = Topic(tid, str(t["name"]).strip(), " ".join(str(t["description"]).split()))
    if not topics:
        problems.append("no topics")
    names = [t.name.lower() for t in topics.values()]
    for n in sorted({n for n in names if names.count(n) > 1}):
        problems.append(f"topic name {n!r} is used more than once")

    teams: dict[str, Team] = {}
    owned: set[str] = set()
    for team_id, t in (data.get("teams") or {}).items():
        team_id = str(team_id)
        where = f"team {team_id!r}"
        if not _ID.match(team_id):
            problems.append(f"{where}: use lowercase words joined by hyphens for the id")
        if not isinstance(t, dict) or not t.get("name"):
            problems.append(f"{where}: needs a name")
            continue
        extra = set(t) - {"name", "mailing_list", "members"}
        if extra:
            problems.append(f"{where}: unknown key(s) {', '.join(sorted(extra))}")
        mailing = t.get("mailing_list")
        if mailing and not _EMAIL.match(str(mailing)):
            problems.append(f"{where}: mailing_list {mailing!r} is not an email address")
        members: list[Member] = []
        for i, m in enumerate(t.get("members") or [], 1):
            mw = f"{where}, member {i}"
            if not isinstance(m, dict) or not m.get("name"):
                problems.append(f"{mw}: needs a name")
                continue
            mw = f"{where}, member {m['name']!r}"
            extra = set(m) - {"name", "email", "topics"}
            if extra:
                problems.append(f"{mw}: unknown key(s) {', '.join(sorted(extra))}")
            email = str(m.get("email") or "")
            if not _EMAIL.match(email):
                problems.append(f"{mw}: email {email!r} is not an email address")
            mtopics = [str(x) for x in (m.get("topics") or [])]
            if not mtopics:
                problems.append(f"{mw}: owns no topics")
            for x in mtopics:
                if x not in topics:
                    problems.append(f"{mw}: topic {x!r} is not under topics")
            dup = sorted({x for x in mtopics if mtopics.count(x) > 1})
            if dup:
                problems.append(f"{mw}: lists {', '.join(dup)} twice")
            owned |= set(mtopics)
            members.append(Member(str(m["name"]).strip(), email, tuple(dict.fromkeys(mtopics))))
        if not members:
            problems.append(f"{where}: has no members")
        mnames = [m.name.lower() for m in members]
        for n in sorted({n for n in mnames if mnames.count(n) > 1}):
            problems.append(f"{where}: member {n!r} is listed twice")
        teams[team_id] = Team(team_id, str(t["name"]).strip(), mailing or None, tuple(members))
    if not teams:
        problems.append("no teams")
    tnames = [t.name.lower() for t in teams.values()]
    for n in sorted({n for n in tnames if tnames.count(n) > 1}):
        problems.append(f"team name {n!r} is used more than once")
    for tid in topics:
        if tid not in owned:
            problems.append(f"topic {tid!r} has no owner: list it under a member")

    if problems:
        raise MatrixError(f"{path}: {len(problems)} problem(s):\n  " + "\n  ".join(problems))
    return Matrix(path, topics, teams)
