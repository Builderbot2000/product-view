"""Pieces every report page shares: attachments, tiles, lozenges, quotes, sentences.

Every page is a periodic overview (D15): each count is for the reporting
period, set against "usual", the mean of the equal periods before it. Quotes
come from the period too, so a reader sees what was said this time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..publish.storage import Attachment, StoragePage
from . import blocks as b
from . import svg
from .issues import MIN_CHANGE, SPARK_PERIODS, Issue, Quote, Series

STARS = {1: "1★", 2: "2★", 3: "3★", 4: "4★", 5: "5★"}


@dataclass
class PageSpec:
    key: str             # output folder
    title: str
    page: StoragePage
    parent: str | None   # parent page's title; None for the root
    replaces: tuple[str, ...] = ()   # earlier titles of this page, renamed in place


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "x"


class Canvas:
    """One page's attachments. Attachments are per page in Confluence, so
    each page carries its own copy of every chart it shows."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def add(self, name: str, svg_text: str, width: int | None = None) -> str:
        self.files[name] = svg_text.encode("utf-8")
        return b.image(name, width)

    def spark(self, key: str, series: Series, polarity: str = "negative") -> str:
        name = f"spark-{_slug(key)}.svg"
        if name not in self.files:
            self.files[name] = svg.sparkline(series.spark(),
                                             b.tone(series.change, polarity)).encode("utf-8")
        # An explicit width: without one Confluence stretches it to the cell.
        return b.image(name, svg.spark_width(SPARK_PERIODS))

    def done(self, body: str) -> StoragePage:
        return StoragePage(body, [Attachment(n, d, "image/svg+xml") for n, d in self.files.items()])


LOZENGE = {"new": "NEW", "up": "↑ UP", "down": "↓ DOWN", "steady": "steady", "quiet": "quiet"}


def _lozenge(change: str, polarity: str) -> str:
    t = b.tone(change, polarity)
    return b.status(LOZENGE[change], b.TONE[t][3] if t else "Grey")


def _change_cell(change: str, polarity: str) -> str:
    t = b.tone(change, polarity)
    return b.cell(_lozenge(change, polarity), highlight=b.TONE[t][1] if t else None)


def _date(d: datetime) -> str:
    return f"{d:%b} {d.day}"


def _period_ends(p) -> list[str]:
    """The last day of each sparkline period, oldest first."""
    return [_date(p.end - timedelta(days=p.days * k + 1)) for k in reversed(range(SPARK_PERIODS))]


def _quote(q: Quote, limit: int = 220) -> str:
    text = q.text if len(q.text) <= limit else q.text[:limit - 1] + "…"
    meta = f"{STARS.get(q.score, '')} · {_date(q.created)}"
    if q.version:
        meta += f" · v{q.version}"
    if q.thumbs:
        meta += f" · {q.thumbs} 👍"
    return f"<em>“{b.esc(text)}”</em> {b.muted(b.esc(meta))}"


def _usual(x: float) -> str:
    return f"{x:.1f}" if x < 10 else f"{x:.0f}"


def _kpi(big: str, caption: str, note: str, change: str = "steady",
         compact: bool = False) -> str:
    """A tile for a complaint count: tinted by what its change means.
    Compact tiles are for stacking in a column: a smaller number, and the
    caption and note share a paragraph."""
    t = b.tone(change)
    accent, bg, border = b.TONE[t][:3] if t else (b.INK, b.PANEL_BG, b.GRID)
    if compact:
        return b.panel(f"<h2>{b.colour(b.esc(big), accent)}</h2>"
                       f"<p><strong>{b.esc(caption)}</strong><br />{b.muted(note)}</p>", bg, border)
    return b.panel(f"<h1>{b.colour(b.esc(big), accent)}</h1>"
                   f"<p><strong>{b.esc(caption)}</strong></p><p>{b.muted(note)}</p>", bg, border)


def _vs_usual(series: Series, unit: str = "") -> str:
    word = {"up": "significantly up", "new": "new this period",
            "down": "significantly down"}.get(series.change, "within normal variation")
    return f"usual {_usual(series.usual)}{unit} · {word}"


# --- the numbers, told in sentences ---------------------------------------------

def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _n(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _against(series: Series) -> str:
    """How a count sits against usual, in words. Only a significant change
    is called up or down; anything else just gives the usual for scale."""
    u = _usual(series.usual)
    return {"up": f"well above the usual {u}", "new": "where there were none before",
            "down": f"well below the usual {u}"}.get(series.change, f"against a usual {u}")


def _name(issue: Issue) -> str:
    return f"“{b.esc(issue.label)}”"


def _brief(issue: Issue) -> str:
    """A topic in a list: its name and its count against usual."""
    if issue.change == "new":
        return f"{_name(issue)} ({issue.now}, new)"
    return f"{_name(issue)} ({issue.now}, usually {_usual(issue.usual)})"


def _main_version(issue: Issue) -> str:
    """'Most of them were on v4.66 (8 of 12). ' when one version dominates."""
    known = [(v, n) for v, n in issue.versions_now.most_common() if v != "unknown"]
    if not known or issue.now < MIN_CHANGE or known[0][1] * 2 <= issue.now:
        return ""
    v, n = known[0]
    return f"Most of them were on v{b.esc(v)} ({n} of {issue.now}). "
