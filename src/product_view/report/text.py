"""Words and small marks every page uses: dates, counts, quotes, lozenges, sentences.

Every page is a periodic overview (D15): each count is for the reporting
period, set against "usual", the mean of the equal periods before it. Quotes
come from the period too, so a reader sees what was said this time.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ..periods import MIN_CHANGE, SPARK_PERIODS, Period, Series
from . import blocks as b
from .data import Quote, TopicCounts

STARS = {1: "1★", 2: "2★", 3: "3★", 4: "4★", 5: "5★"}
LOZENGE = {"new": "NEW", "up": "↑ UP", "down": "↓ DOWN", "steady": "steady", "quiet": "quiet"}


def lozenge(change: str) -> str:
    t = b.tone(change)
    return b.status(LOZENGE[change], b.TONE[t][3] if t else "Grey")


def change_cell(change: str) -> str:
    t = b.tone(change)
    return b.cell(lozenge(change), highlight=b.TONE[t][1] if t else None)


def date(d: datetime) -> str:
    return f"{d:%b} {d.day}"


def period_ends(p: Period) -> list[str]:
    """The last day of each sparkline period, oldest first."""
    return [date(p.end - timedelta(days=p.days * k + 1)) for k in reversed(range(SPARK_PERIODS))]


def quote(q: Quote, limit: int = 220) -> str:
    text = q.text if len(q.text) <= limit else q.text[:limit - 1] + "…"
    meta = f"{STARS.get(q.score, '')} · {date(q.created)}"
    if q.version:
        meta += f" · v{q.version}"
    if q.thumbs:
        meta += f" · {q.thumbs} 👍"
    return f"<em>“{b.esc(text)}”</em> {b.muted(b.esc(meta))}"


def usual(x: float) -> str:
    return f"{x:.1f}" if x < 10 else f"{x:.0f}"


def vs_usual(series: Series, unit: str = "") -> str:
    word = {"up": "significantly up", "new": "new this period",
            "down": "significantly down"}.get(series.change, "within normal variation")
    return f"usual {usual(series.usual)}{unit} · {word}"


# --- the numbers, told in sentences ---------------------------------------------

def and_list(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def against(series: Series) -> str:
    """How a count sits against usual, in words. Only a significant change
    is called up or down; anything else just gives the usual for scale."""
    u = usual(series.usual)
    return {"up": f"well above the usual {u}", "new": "where there were none before",
            "down": f"well below the usual {u}"}.get(series.change, f"against a usual {u}")


def topic_name(topic: TopicCounts) -> str:
    return f"“{b.esc(topic.name)}”"


def brief(topic: TopicCounts) -> str:
    """A topic in a list: its name and its count against usual."""
    if topic.change == "new":
        return f"{topic_name(topic)} ({topic.now}, new)"
    return f"{topic_name(topic)} ({topic.now}, usually {usual(topic.usual)})"


def main_version(topic: TopicCounts) -> str:
    """'Most of them were on v4.66 (8 of 12). ' when one version dominates."""
    known = [(v, n) for v, n in topic.versions_now.most_common() if v != "unknown"]
    if not known or topic.now < MIN_CHANGE or known[0][1] * 2 <= topic.now:
        return ""
    v, n = known[0]
    return f"Most of them were on v{b.esc(v)} ({n} of {topic.now}). "
