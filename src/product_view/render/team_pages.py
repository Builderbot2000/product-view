"""Team pages and member reports (report-design.md D20).

One page per team, the high-level view of every topic its members own, and
under it one report per member covering only their topics, all from one
template. Both sit under the overview page. The pieces (tiles, tables,
lozenges, sparklines, quotes) are the earlier pages' (pages.py), so the
new pages read the same way.

Copy is for readers who know the app and nothing about how the report is
made: no tool, pipeline or statistics terms.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..matrix import Member, Team
from ..store import Store
from . import blocks as b
from .issues import MIN_CHANGE, SIGNIFICANCE, SPARK_PERIODS, Issue, Series, by_change, by_volume
from .pages import (LOZENGE, Canvas, PageSpec, _and, _against, _brief, _change_cell, _date,
                    _kpi, _lozenge, _main_version, _n, _name, _quote, _slug, _usual, _vs_usual)
from .topics import TopicReport

MEMBER_QUOTES = 3        # quotes per topic in a member report (D20)
NO_TOPIC_EXAMPLES = 5    # examples under "Did not fit a topic"


def team_title(team: Team) -> str:
    return team.name


def member_title(team: Team, member: Member) -> str:
    # Titles are unique per Confluence space; a member may sit in two teams.
    return f"{member.name} · {team.name}"


def _owners(team: Team, topic_id: str) -> list[Member]:
    return [m for m in team.members if topic_id in m.topics]


def span(r: TopicReport) -> str:
    p = r.period
    return f"between {_date(p.start)} and {_date(p.end - timedelta(days=1))}"


def owner_links(team: Team):
    """An Owner column: the team members who own the topic, linked to their reports."""
    return "Owner", lambda tid: ", ".join(b.page_link(member_title(team, m), m.name)
                                          for m in _owners(team, tid))


def topic_table(r: TopicReport, ids: list[str], canvas: Canvas, column=None,
                quotes: int = 0) -> str:
    """A row per topic: name and description (and up to `quotes` of this
    period's quotes), an optional (header, cell function) column, then this
    period, usual, change and the trend."""
    rows = []
    for tid in ids:
        i = r.topics[tid]
        first = (f"<strong>{b.esc(i.label)}</strong><br />"
                 + b.muted(b.esc(r.matrix.topics[tid].description)))
        for q in i.recent_quotes(quotes):
            first += "<br />" + _quote(q, 160)
        row = [first] + ([column[1](tid)] if column else [])
        row += [str(i.now), _usual(i.usual), _change_cell(i.change, i.polarity),
                canvas.spark(f"topic-{tid}", i.series, i.polarity)]
        rows.append(row)
    header = ["Topic"] + ([column[0]] if column else []) + [
        "This period", "Usual", "Change", f"Last {SPARK_PERIODS} periods"]
    widths = [440] + ([170] if column else []) + [86, 70, 90, 140]
    numeric = {2, 3} if column else {1, 2}
    return b.table(header, rows, widths, numeric)


def ordered(r: TopicReport, ids) -> list[str]:
    """Busiest this period first, then by usual level; ties keep list order."""
    pos = {t: n for n, t in enumerate(ids)}
    return sorted(ids, key=lambda t: (-r.topics[t].now, -r.topics[t].usual, pos[t]))


def period_pairs(r: TopicReport, extra: list[tuple[str, str]]) -> list[tuple[str, str]]:
    p = r.period
    base_start = p.start - timedelta(days=p.days * p.baseline)
    base_end = p.start - timedelta(days=1)
    return [("Period", f"<strong>{b.esc(p.label())}</strong> ({p.days} days)"),
            ("Usual", f"the average of the {p.baseline} periods before it, "
                      f"{_date(base_start)} {base_start.year} – {_date(base_end)} {base_end.year}"),
            *extra,
            ("All complaints", f"{r.total.now} negative reviews (1–3★) across the app, "
                               f"usual {_usual(r.total.usual)}")]


def movers(issues: list[Issue], skip: Issue | None) -> str:
    moved = [i for i in by_change(issues) if i is not skip]
    up = [_brief(i) for i in moved if i.change in ("new", "up")][:3]
    down = [_brief(i) for i in moved if i.change == "down"][:3]
    out = ""
    if up:
        also = "Also rising" if skip is not None and skip.change in ("new", "up") else "Rising"
        out += f"{also}: {_and(up)}. "
    if down:
        out += f"Easing off: {_and(down)}. "
    return out.strip()


def lead_paragraph(issues: list[Issue], whose: str) -> tuple[str, Issue | None]:
    """The one topic to look at first, and a paragraph on it."""
    moved = [i for i in by_change(issues) if i.change in ("new", "up")]
    busiest = next(iter(by_volume([i for i in issues if i.now])), None)
    top = moved[0] if moved else busiest
    if top is None:
        return f"No one raised a problem with {whose} this period.", None
    if moved:
        text = (f"The one to look at first is <strong>{_name(top)}</strong>: "
                f"{_n(top.now, 'review')}, {_against(top.series)}. ")
    else:
        text = (f"Nothing in {whose} rose beyond normal variation. The topic you heard most "
                f"about is <strong>{_name(top)}</strong>: {_n(top.now, 'review')}, "
                f"{_against(top.series)}. ")
    recent = top.recent_quotes(1)
    text += _main_version(top) + (f"One reviewer put it this way: {_quote(recent[0], 180)}"
                                  if recent else "")
    return text, top


def _tiles(r: TopicReport, issues: list[Issue], mine: Series, caption: str) -> list[str]:
    tiles = [_kpi(str(mine.now), caption, _vs_usual(mine), mine.change)]
    moved = by_change(issues)
    if moved:
        top = moved[0]
        tiles.append(_kpi(str(top.now), f"{LOZENGE[top.change]}: {top.label}",
                          f"usual {_usual(top.usual)} · {_n(len(moved), 'topic')} changed",
                          top.change))
    else:
        tiles.append(_kpi("0", "topics changed", "all within normal variation"))
    return tiles


def _topic_detail(r: TopicReport, tid: str, canvas: Canvas) -> str:
    """One topic in full: change, counts, versions, trend and up to 3 quotes."""
    i = r.topics[tid]
    versions = ", ".join(f"{v} ({n})" for v, n in i.versions_now.most_common(4))
    facts = (f"{i.now} this period · usual {_usual(i.usual)}"
             + (f" · app versions {versions}" if versions else ""))
    quotes = i.recent_quotes(MEMBER_QUOTES)
    if quotes:
        lead = ("What they said:" if len(quotes) == i.now
                else f"{len(quotes)} of {i.now}, the clearest first:")
        said = (f"<p>{b.muted(lead)}</p><ul>"
                + "".join(f"<li>{_quote(q)}</li>" for q in quotes) + "</ul>")
    else:
        said = f"<p>{b.muted('No reviews on this topic this period.')}</p>"
    return (f"<h3>{b.esc(i.label)} {_lozenge(i.change, i.polarity)}</h3>"
            f"<p>{b.muted(b.esc(facts))}</p>"
            f"<p>{canvas.spark(f'topic-{tid}', i.series, i.polarity)}</p>" + said)


def no_topic(r: TopicReport, examples: int = NO_TOPIC_EXAMPLES) -> str:
    s = r.no_topic
    out = (f"<h2>Did not fit a topic: {_n(s.now, 'review')}</h2>"
           f"<p>{b.muted(f'Negative reviews this period that match none of the topics any team owns, across the whole app (usual {_usual(s.usual)}). Most are general complaints that name no feature, but a problem that keeps turning up here may need a topic of its own.')}</p>")
    shown = r.no_topic_now[:examples]
    if shown:
        out += ("<p>" + b.muted(f"The {len(shown)} most liked and newest:") + "</p><ul>"
                + "".join(f"<li>{_quote(q)}</li>" for q in shown) + "</ul>")
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
    text = f"Generated at {stamp} from run {r.run['run_id']}."
    if r.matrix.is_sample:
        text += " Teams, people and topics are sample content."
    return f"<p>{b.muted(b.esc(text))}</p>"


# --- team page -------------------------------------------------------------------

def team_page(r: TopicReport, team: Team, overview: str | None):
    c = Canvas()
    ids = list(team.topics)
    issues = r.of(ids)
    mine = r.union(ids)
    first = (f"Here’s what Play Store reviewers said {span(r)} about the "
             f"{_n(len(ids), 'topic')} <strong>{b.esc(team.name)}</strong> follows. "
             f"{_n(mine.now, 'negative review')} touched at least one of them, "
             f"{_against(mine)}, out of {r.total.now} across the whole app.")
    lead, top = lead_paragraph(issues, "your topics")
    paras = [first, lead]
    if others := movers(issues, top):
        paras.append(others)
    members = "".join(f"<li>{b.page_link(member_title(team, m), m.name)} "
                      f"{b.muted(b.esc('· ' + ', '.join(r.matrix.topics[t].name for t in m.topics)))}</li>"
                      for m in team.members)
    intro = ("".join(f"<p>{p}</p>" for p in paras)
             + "<p>Each member has a report with only their topics:</p>" + f"<ul>{members}</ul>")
    if overview:
        intro += f"<p>{b.muted('For the whole app, see ')}{b.page_link(overview, overview)}.</p>"
    pairs = period_pairs(r, [("Reviews", f"{mine.now} on these topics, usual {_usual(mine.usual)}")])

    tiles = _tiles(r, issues, mine, "reviews on your topics")
    tiles.append(_kpi(str(r.no_topic.now), "did not fit any topic",
                      f"across the app · usual {_usual(r.no_topic.usual)}"))
    table = ("<h2>Your topics this period</h2>"
             f"<p>{b.muted('Busiest first. Each member’s report has the quotes behind these numbers.')}</p>"
             + topic_table(r, ordered(r, ids), c, owner_links(team)))
    body = b.layout(b.section("single", intro + b.details(pairs)),
                    b.section("three_equal", *tiles),
                    b.section("single", table + no_topic(r) + method(r) + footer(r)))
    return c.done(body)


# --- member report ---------------------------------------------------------------

def member_page(r: TopicReport, team: Team, member: Member):
    c = Canvas()
    ids = list(member.topics)
    issues = r.of(ids)
    mine = r.union(ids)
    names = _and([r.matrix.topics[t].name for t in ids])
    first = (f"Here’s what Play Store reviewers said {span(r)} about "
             f"<strong>{b.esc(names)}</strong>, the {'topic' if len(ids) == 1 else 'topics'} "
             f"you own. {_n(mine.now, 'negative review')} touched "
             f"{'it' if len(ids) == 1 else 'at least one of them'}, {_against(mine)}, "
             f"out of {r.total.now} across the whole app.")
    lead, top = lead_paragraph(issues, "your topics")
    paras = [first, lead]
    if others := movers(issues, top):
        paras.append(others)
    paras.append(b.muted("Trends and quotes for each topic are below. For the whole team, see ")
                 + b.page_link(team_title(team), team.name) + ".")
    pairs = period_pairs(r, [("Your topics", b.esc(names)),
                              ("Reviews", f"{mine.now} on your topics, usual {_usual(mine.usual)}")])
    tiles = _tiles(r, issues, mine, "reviews on your topics")
    # Always three tiles, so every member report has the same shape.
    busiest = next((i for i in by_volume(issues) if i.now and i is not top), None)
    if busiest:
        tiles.append(_kpi(str(busiest.now), f"Also raised: {busiest.label}",
                          f"usual {_usual(busiest.usual)} per period"))
    else:
        tiles.append(_kpi("0", "other topics raised", "no other topic of yours had reviews"))
    order = ordered(r, ids)
    table = ("<h2>Your topics this period</h2>"
             f"<p>{b.muted('Busiest first. Details and this period’s quotes follow below.')}</p>"
             + topic_table(r, order, c))
    details = "<h2>What users said</h2>" + "".join(_topic_detail(r, t, c) for t in order)
    body = b.layout(b.section("single", "".join(f"<p>{p}</p>" for p in paras) + b.details(pairs)),
                    b.section("three_equal", *tiles),
                    b.section("single", table + details + method(r) + footer(r)))
    return c.done(body)


# --- all pages -------------------------------------------------------------------

def build_all(store: Store, r: TopicReport, overview: str, app_id: str) -> list[PageSpec]:
    """The overview, then each team page under it followed by its members'
    reports: the same templates for every team and member in the matrix."""
    from .overview import overview_page

    specs = [PageSpec("overview", overview, overview_page(store, r, overview, app_id), None)]
    for team in r.matrix.teams.values():
        title = team_title(team)
        specs.append(PageSpec(f"team-{team.id}", title, team_page(r, team, overview), overview))
        for m in team.members:
            specs.append(PageSpec(f"member-{team.id}-{_slug(m.name)}", member_title(team, m),
                                  member_page(r, team, m), title))
    return specs
