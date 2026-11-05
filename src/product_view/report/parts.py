"""Pieces the overview, team pages and member reports share: the page and its
charts, titles, tiles, the topic table, the opening paragraphs, and the method
and footer every page ends with.

Copy is for readers who know the app and nothing about how the report is
made: no tool, pipeline or statistics terms.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..matrix import Member, Team
from ..periods import MIN_CHANGE, SIGNIFICANCE, SPARK_PERIODS, Series
from ..publish.storage import Attachment, StoragePage
from . import blocks as b
from . import svg
from .data import TopicCounts, TopicReport, by_change, by_volume
from .text import (LOZENGE, against, and_list, brief, change_cell, date, main_version, plural,
                   quote, topic_name, usual)

NO_TOPIC_EXAMPLES = 5    # examples under "Did not fit a topic"


@dataclass
class PageSpec:
    key: str             # output folder
    title: str
    page: StoragePage
    parent: str | None   # parent page's title; None for the root


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "x"


class Canvas:
    """One page's attachments. Attachments are per page in Confluence, so
    each page carries its own copy of every chart it shows."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def add(self, name: str, svg_text: str, width: int | None = None) -> str:
        self.files[name] = svg_text.encode("utf-8")
        return b.image(name, width)

    def spark(self, key: str, series: Series) -> str:
        name = f"spark-{slug(key)}.svg"
        if name not in self.files:
            self.files[name] = svg.sparkline(series.spark(),
                                             b.tone(series.change)).encode("utf-8")
        # An explicit width: without one Confluence stretches it to the cell.
        return b.image(name, svg.spark_width(SPARK_PERIODS))

    def done(self, body: str) -> StoragePage:
        return StoragePage(body, [Attachment(n, d, "image/svg+xml") for n, d in self.files.items()])


def kpi(big: str, caption: str, note: str, change: str = "steady",
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


def changed_tile(moved: list[TopicCounts], compact: bool = False) -> str:
    """The topic that moved most, or a tile saying none did."""
    if not moved:
        return kpi("0", "topics changed", "all within normal variation", compact=compact)
    top = moved[0]
    return kpi(str(top.now), f"{LOZENGE[top.change]}: {top.name}",
               f"usual {usual(top.usual)} · {plural(len(moved), 'topic')} changed",
               top.change, compact=compact)


# --- titles and links --------------------------------------------------------------

def team_title(team: Team) -> str:
    return team.name


def member_title(team: Team, member: Member) -> str:
    # Titles are unique per Confluence space; a member may sit in two teams.
    return f"{member.name} · {team.name}"


def owner_links(team: Team):
    """An Owner column: the team members who own the topic, linked to their reports."""
    return "Owner", lambda tid: ", ".join(b.page_link(member_title(team, m), m.name)
                                          for m in team.members if tid in m.topics)


# --- the period and the topics -----------------------------------------------------

def span(r: TopicReport) -> str:
    p = r.period
    return f"between {date(p.start)} and {date(p.end - timedelta(days=1))}"


def period_pairs(r: TopicReport, extra: list[tuple[str, str]]) -> list[tuple[str, str]]:
    p = r.period
    base_start = p.start - timedelta(days=p.days * p.baseline)
    base_end = p.start - timedelta(days=1)
    return [("Period", f"<strong>{b.esc(p.label())}</strong> ({p.days} days)"),
            ("Usual", f"the average of the {p.baseline} periods before it, "
                      f"{date(base_start)} {base_start.year} – {date(base_end)} {base_end.year}"),
            *extra,
            ("All complaints", f"{r.total.now} negative reviews (1–3★) across the app, "
                               f"usual {usual(r.total.usual)}")]


def ordered(r: TopicReport, ids) -> list[str]:
    """Busiest this period first, then by usual level; ties keep list order."""
    pos = {t: n for n, t in enumerate(ids)}
    return sorted(ids, key=lambda t: (-r.topics[t].now, -r.topics[t].usual, pos[t]))


def topic_table(r: TopicReport, ids: list[str], canvas: Canvas, column=None,
                quotes: int = 0) -> str:
    """A row per topic: name and description (and up to `quotes` of this
    period's quotes), an optional (header, cell function) column, then this
    period, usual, change and the trend."""
    rows = []
    for tid in ids:
        t = r.topics[tid]
        first = (f"<strong>{b.esc(t.name)}</strong><br />"
                 + b.muted(b.esc(r.matrix.topics[tid].description)))
        for q in t.recent_quotes(quotes):
            first += "<br />" + quote(q, 160)
        row = [first] + ([column[1](tid)] if column else [])
        row += [str(t.now), usual(t.usual), change_cell(t.change),
                canvas.spark(f"topic-{tid}", t.series)]
        rows.append(row)
    header = ["Topic"] + ([column[0]] if column else []) + [
        "This period", "Usual", "Change", f"Last {SPARK_PERIODS} periods"]
    widths = [440] + ([170] if column else []) + [86, 70, 90, 140]
    numeric = {2, 3} if column else {1, 2}
    return b.table(header, rows, widths, numeric)


# --- opening paragraphs ------------------------------------------------------------

def movers(topics: list[TopicCounts], skip: TopicCounts | None) -> str:
    moved = [t for t in by_change(topics) if t is not skip]
    up = [brief(t) for t in moved if t.change in ("new", "up")][:3]
    down = [brief(t) for t in moved if t.change == "down"][:3]
    out = ""
    if up:
        also = "Also rising" if skip is not None and skip.change in ("new", "up") else "Rising"
        out += f"{also}: {and_list(up)}. "
    if down:
        out += f"Easing off: {and_list(down)}. "
    return out.strip()


def lead_paragraph(topics: list[TopicCounts], whose: str,
                   heard: str = "The topic you heard most about is"
                   ) -> tuple[str, TopicCounts | None]:
    """The one topic to look at first, and a paragraph on it."""
    moved = [t for t in by_change(topics) if t.change in ("new", "up")]
    busiest = next(iter(by_volume([t for t in topics if t.now])), None)
    top = moved[0] if moved else busiest
    if top is None:
        return f"No one raised a problem with {whose} this period.", None
    if moved:
        text = (f"The one to look at first is <strong>{topic_name(top)}</strong>: "
                f"{plural(top.now, 'review')}, {against(top.series)}. ")
    else:
        text = (f"Nothing in {whose} rose beyond normal variation. {heard} "
                f"<strong>{topic_name(top)}</strong>: {plural(top.now, 'review')}, "
                f"{against(top.series)}. ")
    recent = top.recent_quotes(1)
    text += main_version(top) + (f"One reviewer put it this way: {quote(recent[0], 180)}"
                                 if recent else "")
    return text, top


# --- closing sections --------------------------------------------------------------

def no_topic(r: TopicReport, examples: int = NO_TOPIC_EXAMPLES) -> str:
    s = r.no_topic
    out = (f"<h2>Did not fit a topic: {plural(s.now, 'review')}</h2>"
           f"<p>{b.muted(f'Negative reviews this period that match none of the topics any team owns, across the whole app (usual {usual(s.usual)}). Most are general complaints that name no feature, but a problem that keeps turning up here may need a topic of its own.')}</p>")
    shown = r.no_topic_now[:examples]
    if shown:
        out += ("<p>" + b.muted(f"The {len(shown)} most liked and newest:") + "</p><ul>"
                + "".join(f"<li>{quote(q)}</li>" for q in shown) + "</ul>")
    return out


def method(r: TopicReport) -> str:
    p = r.period
    months = round(p.days * p.baseline / 30.4)
    return b.expand("How these numbers are made", (
        "<p>These pages are built from the negative reviews (1 to 3 stars) people post about "
        "the app on the Google Play Store. Very short reviews (under "
        f"{r.min_chars} characters, such as “Bad”) are left out, reviews in French are "
        "translated into English automatically, and reviews in other alphabets, such as "
        "Arabic or Chinese, are not included.</p>"
        "<p>Each team decides which features of the app it follows, as a fixed list of topics "
        "with a short description each, and each team member owns some of them. A review "
        "often makes several separate complaints, so each review is split into them. Every "
        "complaint is then compared with the topic descriptions: one that clearly matches a "
        "single topic is counted under it straight away, one that matches nothing well is "
        "left out, and an AI language model reads the rest, with the whole review for "
        "context, and decides which of the closest topics it is about, if any. A review "
        "counts toward a topic when any of its complaints does, so one review can count "
        "toward several topics. The topic list never changes on its own, so a topic means the "
        "same thing from one report to the next. Reviews that fit no topic are counted "
        "separately, so problems missing from the list stay visible. The matching is "
        "automatic and can misplace a complaint, so the quotes under each topic are there to "
        "check it against.</p>"
        f"<p>Each report covers {p.days} days, ending on the date of the most recent review, "
        f"and every count is set against <em>usual</em>: the average for the {p.baseline} "
        f"periods of the same length before it, about {months} months in all. Most topics "
        "come up in only a few reviews a period, so small moves such as 1 review to 3 are "
        "usually just chance. A topic is marked <em>UP</em> only when its count is so far "
        "above usual that chance alone would explain it less than 1 time in "
        f"{round(1 / SIGNIFICANCE)}, and <em>DOWN</em> when it is as far below; a topic with "
        f"fewer than {MIN_CHANGE} reviews is never marked either way. <em>NEW</em> marks a "
        f"topic with at least {MIN_CHANGE} reviews this period and none in the {p.baseline} "
        "periods before it, and <em>STEADY</em> one within its normal range.</p>"
        f"<p>The small bar charts follow each topic over its last {SPARK_PERIODS} periods, "
        "oldest on the left. Each is scaled to its own tallest bar, so it shows whether a "
        "topic is growing or fading rather than how topics compare. Quotes are the part of "
        "the review that matched the topic, in the reviewer’s own words. The clearest "
        "matches come first, then the most liked and newest; very short ones only when "
        "there is nothing else. Each is followed by the "
        "star rating, the date, the app version when the store reports it, and how many "
        "people marked the review helpful (👍).</p>"))


def footer(r: TopicReport) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    text = f"Generated at {stamp}."
    if r.matrix.is_sample:
        text += " Teams, people and topics are sample content."
    return f"<p>{b.muted(b.esc(text))}</p>"
