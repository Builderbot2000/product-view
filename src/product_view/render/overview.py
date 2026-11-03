"""The overview page: the whole app, every team and every topic (D20).

The top of the page tree and the analysts' view in one page: what the period
looked like across the app, what changed, then every team's topics with the
period's quotes behind each number, and the reviews that fit no topic. Each
team's section links to its team page, where the members' reports sit.
"""

from __future__ import annotations

from ..store import Store
from . import blocks as b
from . import svg
from .issues import SPARK_PERIODS, by_change, by_volume
from .pages import (LOZENGE, Canvas, _against, _brief, _kpi, _n, _period_ends, _usual,
                    _vs_usual)
from .team_pages import (footer, member_title, method, movers, no_topic, ordered, span,
                         team_title, topic_table)
from .topics import TopicReport

TABLE_QUOTES = 2          # quotes under each topic in the overview's tables
OVERVIEW_EXAMPLES = 10    # examples under "Did not fit a topic"
HEAT_ROWS = 20            # topics in the heatmap, busiest first


def _teams_of(r: TopicReport) -> dict[str, list[str]]:
    """topic id -> the names of the teams that follow it."""
    out: dict[str, list[str]] = {}
    for team in r.matrix.teams.values():
        for t in team.topics:
            out.setdefault(t, []).append(team.name)
    return out


def _summary(r: TopicReport, team_rows: list) -> str:
    t = r.total
    first = (f"Here’s how the app did on the Play Store {span(r)}. "
             f"{_n(t.now, 'reviewer')} left a negative review (1–3★), {_against(t)}.")
    if t.change in ("up", "new"):
        first += " So, a rougher period than usual."
    elif t.change == "down":
        first += " So, a better period than usual."
    paras = [first]

    # The headline: the team whose topics rose most, else the busiest team.
    rising = sorted([x for x in team_rows if x[1].change in ("up", "new")],
                    key=lambda x: -(x[1].now - x[1].usual))
    lead = None
    if rising or team_rows:
        team, s = (rising or team_rows)[0]
        issues = r.of(team.topics)
        lead = (next(iter(by_change([i for i in issues if i.change in ("up", "new")])), None)
                or next(iter(by_volume([i for i in issues if i.now])), None))
        opener = ("The biggest story is" if rising
                  else "Nothing rose beyond normal variation; the busiest team is")
        text = (f"{opener} <strong>{b.esc(team.name)}</strong>: "
                f"{_n(s.now, 'negative review')} on its topics, {_against(s)}.")
        if lead:
            text += f" Leading it is {_brief(lead)}."
        paras.append(text)
    if others := movers(list(r.topics.values()), lead):
        paras.append(others)
    paras.append(f"{_n(r.no_topic.now, 'review')} fit none of the topics, {_against(r.no_topic)}.")
    return "".join(f"<p>{p}</p>" for p in paras)


def _pairs(store: Store, r: TopicReport, app_id: str) -> list[tuple[str, str]]:
    from .team_pages import period_pairs

    versions = ", ".join(f"{v} ({n})" for v, n in r.versions_now.most_common(4))
    pairs = period_pairs(r, [("Topics", f"{len(r.topics)}, followed by "
                                        f"{_n(len(r.matrix.teams), 'team')}")])
    pairs.append(("App versions", b.esc(versions) + " " + b.muted("(negative reviews)")))
    meta = store.conn.execute(
        "SELECT * FROM app_metadata ORDER BY fetched_at DESC LIMIT 1").fetchone()
    if meta:
        pairs.append(("Store rating", f"★ {meta['score']:.2f} from {meta['ratings']:,} ratings "
                                      f"(latest version {b.esc(meta['version'] or '?')})"))
    pairs.append(("App", f"<code>{b.esc(app_id)}</code>"))
    return pairs


def overview_page(store: Store, r: TopicReport, title: str, app_id: str):
    c = Canvas()
    p = r.period
    teams = list(r.matrix.teams.values())
    team_rows = sorted(((t, r.union(t.topics)) for t in teams),
                       key=lambda x: (-x[1].now, -x[1].usual))
    ends = _period_ends(p)

    chart = c.add("teams.svg", svg.area_bars(
        [{"name": t.name, "now": s.now, "usual": s.usual, "change": s.change}
         for t, s in team_rows],
        "Negative reviews on each team’s topics, this period",
        f"{p.label()} · bar = this period, tick = usual"), 620)
    trend = c.add("trend.svg", svg.trend_panels(
        [{"name": "Negative (1–3★)", "values": r.total.spark(), "usual": r.total.usual,
          "tone": b.tone(r.total.change)},
         {"name": "Fit no topic", "values": r.no_topic.spark(), "usual": r.no_topic.usual,
          "tone": b.tone(r.no_topic.change)}],
        ends, f"Reviews per period, last {SPARK_PERIODS}",
        f"{p.days}-day periods · dashed = usual · dot = this period"), 620)
    heat_rows = by_volume([i for i in r.topics.values() if sum(i.series.spark())])[:HEAT_ROWS]
    heat = (c.add("heatmap.svg", svg.heatmap(
        [{"name": i.label, "values": i.series.spark()} for i in heat_rows], ends,
        f"Negative reviews per topic, last {SPARK_PERIODS} periods",
        "Busiest this period first · outlined column = this period"), 620) + "<p />"
            if heat_rows else "")

    links = "".join(f"<li>{b.page_link(team_title(t), t.name)} "
                    f"{b.muted(b.esc('· ' + ', '.join(m.name for m in t.members)))}</li>"
                    for t in teams)
    intro = (_summary(r, team_rows)
             + "<p>Each team has its own page, with a report for each member under it:</p>"
             + f"<ul>{links}</ul>")

    tiles = [_kpi(str(r.total.now), f"negative reviews in {p.days} days", _vs_usual(r.total),
                  r.total.change, compact=True)]
    moved = by_change(list(r.topics.values()))
    if moved:
        top = moved[0]
        tiles.append(_kpi(str(top.now), f"{LOZENGE[top.change]}: {top.label}",
                          f"usual {_usual(top.usual)} · {_n(len(moved), 'topic')} changed",
                          top.change, compact=True))
    else:
        tiles.append(_kpi("0", "topics changed", "all within normal variation", compact=True))
    tiles.append(_kpi(str(r.no_topic.now), "fit no topic", _vs_usual(r.no_topic), compact=True))
    header = b.section("two_equal", intro + "".join(tiles) + b.details(_pairs(store, r, app_id)),
                       heat + chart + "<p />" + trend)

    teams_of = _teams_of(r)
    team_col = ("Team", lambda tid: b.esc(", ".join(teams_of.get(tid, []))))
    tid_of = {id(i): tid for tid, i in r.topics.items()}
    changed_ids = [tid_of[id(i)] for i in moved]
    changed = "<h2>What changed this period</h2>" + (
        f"<p>{b.muted('Topics whose count is well above or below usual (see How these numbers are made). Everything else moved within normal variation.')}</p>"
        + topic_table(r, changed_ids, c, team_col, TABLE_QUOTES)
        if changed_ids else b.info("<p>No topic moved beyond normal variation this period.</p>"))

    by_team = "<h2>By team</h2>"
    for team, s in team_rows:
        members = " · ".join(b.page_link(member_title(team, m), m.name) for m in team.members)
        by_team += (
            f"<h3>{b.esc(team.name)} {b.muted(f'· {s.now} reviews, usual {_usual(s.usual)}')}</h3>"
            f"<p>{b.muted('Team page: ')}{b.page_link(team_title(team), team.name)}"
            f"{b.muted(' · Members: ')}{members}</p>"
            + topic_table(r, ordered(r, team.topics), c, quotes=TABLE_QUOTES))

    body = b.layout(header, b.section("single", changed + by_team
                                      + no_topic(r, OVERVIEW_EXAMPLES) + method(r) + footer(r)))
    return c.done(body)
