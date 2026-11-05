"""The team page (report-design.md D20, revised 2026-11-04): a lead's overview
of their people.

Who needs to look at something this period (a row per member), the team's
trend, and every topic the team owns with one quote each. Nothing app-wide:
that is the overview's.
"""

from __future__ import annotations

from ..matrix import Team
from ..periods import SPARK_PERIODS
from ..publish.storage import StoragePage
from . import blocks as b
from . import svg
from .data import TopicReport, by_change, by_volume
from .parts import (Canvas, changed_tile, footer, kpi, lead_paragraph, member_title, method,
                    movers, ordered, owner_links, period_pairs, span, topic_table)
from .text import LOZENGE, against, brief, change_cell, period_ends, plural, usual, vs_usual


def _member_rows(r: TopicReport, team: Team) -> str:
    """A row per member: reviews on their topics against usual, and what to look at."""
    rows = []
    for m in team.members:
        topics = r.of(m.topics)
        mine = r.union(m.topics)
        moved = [t for t in by_change(topics) if t.change in ("new", "up", "down")]
        busiest = next(iter(by_volume([t for t in topics if t.now])), None)
        if moved:
            note = f"{LOZENGE[moved[0].change]}: {brief(moved[0])}"
        elif busiest:
            note = f"Most raised: {brief(busiest)}"
        else:
            note = b.muted("No reviews on their topics")
        rows.append([f"<strong>{b.page_link(member_title(team, m), m.name)}</strong><br />"
                     + b.muted(b.esc(", ".join(r.matrix.topics[t].name for t in m.topics))),
                     str(mine.now), usual(mine.usual), change_cell(mine.change), note])
    return b.table(["Member", "This period", "Usual", "Change", "To look at"], rows,
                   [330, 86, 70, 90, 330], {1, 2})


def team_page(r: TopicReport, team: Team, overview: str | None) -> StoragePage:
    c = Canvas()
    ids = list(team.topics)
    topics = r.of(ids)
    mine = r.union(ids)
    first = (f"Here’s what Play Store reviewers said {span(r)} about the "
             f"{plural(len(ids), 'topic')} <strong>{b.esc(team.name)}</strong> follows. "
             f"{plural(mine.now, 'negative review')} touched at least one of them, "
             f"{against(mine)}, out of {r.total.now} across the whole app.")
    lead, top = lead_paragraph(topics, "the team’s topics", "The busiest is")
    paras = [first, lead]
    if others := movers(topics, top):
        paras.append(others)
    intro = "".join(f"<p>{x}</p>" for x in paras)
    if overview:
        intro += f"<p>{b.muted('For the whole app, see ')}{b.page_link(overview, overview)}.</p>"
    pairs = period_pairs(r, [("Reviews", f"{mine.now} on the team’s topics, "
                                         f"usual {usual(mine.usual)}")])

    tiles = [kpi(str(mine.now), "reviews on the team’s topics", vs_usual(mine), mine.change),
             changed_tile(by_change(topics))]
    m, ms = sorted(((m, r.union(m.topics)) for m in team.members),
                   key=lambda x: (-x[1].now, -x[1].usual))[0]
    tiles.append(kpi(str(ms.now), f"Busiest: {m.name}",
                     f"usual {usual(ms.usual)} on their topics", ms.change))

    p = r.period
    trend = c.add(f"team-{team.id}-trend.svg", svg.trend_panels(
        [{"name": "The team’s topics", "values": mine.spark(), "usual": mine.usual,
          "tone": b.tone(mine.change)},
         {"name": "Whole app, for scale", "values": r.total.spark(), "usual": r.total.usual,
          "tone": b.tone(r.total.change)}],
        period_ends(p), f"Negative reviews per period, last {SPARK_PERIODS}",
        f"{p.days}-day periods · dashed = usual · dot = this period"), 620)
    people = ("<h2>Members this period</h2>"
              f"<p>{b.muted('Each member’s report has the reviews behind these numbers.')}</p>"
              + _member_rows(r, team))
    table = ("<h2>The team’s topics</h2>"
             f"<p>{b.muted('Busiest first, with the clearest quote for each.')}</p>"
             + topic_table(r, ordered(r, ids), c, owner_links(team), quotes=1))
    body = b.layout(b.section("single", intro + b.details(pairs) + trend),
                    b.section("three_equal", *tiles),
                    b.section("single", people + table + method(r) + footer(r)))
    return c.done(body)
