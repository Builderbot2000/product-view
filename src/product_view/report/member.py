"""The member report (report-design.md D20, revised 2026-11-04): a working page
on what users said about the member's own topics.

Per topic: the change, the count against usual and last period, app versions,
up to MEMBER_QUOTES quotes, and every review of the period in full behind an
expand.
"""

from __future__ import annotations

from dataclasses import replace

from ..matrix import Member, Team
from ..publish.storage import StoragePage
from . import blocks as b
from .data import TopicReport
from .parts import (Canvas, footer, lead_paragraph, method, movers, ordered, period_pairs, span,
                    team_title, topic_table)
from .text import against, and_list, lozenge, plural, quote, usual

MEMBER_QUOTES = 5        # quotes per topic in a member report


def _topic_detail(r: TopicReport, tid: str) -> str:
    """One topic's reviews: counts against usual and the period before, app
    versions, up to MEMBER_QUOTES quotes, and every review in full. The
    description and trend are in the table above, so not repeated here."""
    t = r.topics[tid]
    versions = ", ".join(f"{v} ({n})" for v, n in t.versions_now.most_common(4))
    facts = (f"{t.now} this period · {t.series.counts[1]} the period before · "
             f"usual {usual(t.usual)}" + (f" · app versions {versions}" if versions else ""))
    quotes = t.recent_quotes(MEMBER_QUOTES)
    if quotes:
        lead = ("What they said:" if len(quotes) == t.now
                else f"{len(quotes)} of {t.now}, the clearest first:")
        said = (f"<p>{b.muted(lead)}</p><ul>"
                + "".join(f"<li>{quote(q)}</li>" for q in quotes) + "</ul>")
        everyone = sorted(t.quotes_now.values(), key=lambda q: -q.created.timestamp())
        whole = [replace(q, text=q.full or q.text) for q in everyone]
        # Only when it adds something: reviews not quoted, or quotes cut from longer reviews.
        if len(everyone) > len(quotes) or any(q.full and q.full != q.text for q in quotes):
            label = ("The whole review" if len(everyone) == 1
                     else f"All {plural(t.now, 'review')} in full, newest first")
            said += b.expand(label,
                             "<ul>" + "".join(f"<li>{quote(q, 4000)}</li>" for q in whole)
                             + "</ul>")
    else:
        said = f"<p>{b.muted('No reviews on this topic this period.')}</p>"
    return (f"<h3>{b.esc(t.name)} {lozenge(t.change)}</h3>"
            f"<p>{b.muted(b.esc(facts))}</p>" + said)


def member_page(r: TopicReport, team: Team, member: Member) -> StoragePage:
    c = Canvas()
    ids = list(member.topics)
    topics = r.of(ids)
    mine = r.union(ids)
    # Topic names often contain "and", so each is bolded on its own to show where it ends.
    names = and_list([f"<strong>{b.esc(r.matrix.topics[t].name)}</strong>" for t in ids])
    first = (f"Here’s what Play Store reviewers said {span(r)} about "
             f"{names}, the {'topic' if len(ids) == 1 else 'topics'} "
             f"you own. {plural(mine.now, 'negative review')} touched "
             f"{'it' if len(ids) == 1 else 'at least one of them'}, {against(mine)}, "
             f"out of {r.total.now} across the whole app.")
    lead, top = lead_paragraph(topics, "your topics")
    paras = [first, lead]
    if others := movers(topics, top):
        paras.append(others)
    paras.append(b.muted("Each topic’s reviews follow, the clearest first, with every one in "
                         "full under each topic. For the whole team, see ")
                 + b.page_link(team_title(team), team.name) + ".")
    pairs = period_pairs(r, [("Your topics", "; ".join(b.esc(r.matrix.topics[t].name)
                                                       for t in ids)),
                              ("Reviews", f"{mine.now} on your topics, {mine.counts[1]} the "
                                          f"period before, usual {usual(mine.usual)}")])
    order = ordered(r, ids)
    table = "<h2>Your topics at a glance</h2>" + topic_table(r, order, c)
    details = "<h2>What users said</h2>" + "".join(_topic_detail(r, t) for t in order)
    body = b.layout(b.section("single", "".join(f"<p>{x}</p>" for x in paras) + b.details(pairs)
                              + table + details + method(r) + footer(r)))
    return c.done(body)
