"""The report's pages: a hub with every area, and one page per role (§5).

Both are periodic overviews (D15): every count is for the reporting period,
set against "usual", the mean of the equal periods before it. Quotes come
from the period too, so a reader sees what was said this time, not the
standing medoid of a cluster spanning years.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..publish.storage import Attachment, StoragePage
from ..store import Store
from . import blocks as b
from . import svg
from .issues import (MIN_CHANGE, OTHER, SIGNIFICANCE, SPARK_PERIODS, Issue, Quote,
                     Role, Series, Stream, Taxonomy, by_change, by_volume)

STARS = {1: "1★", 2: "2★", 3: "3★", 4: "4★", 5: "5★"}


@dataclass
class PageSpec:
    key: str             # output folder
    title: str
    page: StoragePage
    parent: str | None   # parent page's title; None for the root


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

    def dots(self, key: str, scores: list[int]) -> str:
        name = f"dots-{_slug(key)}.svg"
        self.files[name] = svg.dots(scores).encode("utf-8")
        return b.image(name, svg.dots_width(len(scores)))

    def done(self, body: str) -> StoragePage:
        return StoragePage(body, [Attachment(n, d, "image/svg+xml") for n, d in self.files.items()])


# --- shared pieces -----------------------------------------------------------

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


STAR_KEY = ("Each dot is one reviewer this period: "
            + " ".join(b.colour("●", svg.STAR_COLOURS[n]) + f" {n}★" for n in range(1, 6)))


def _quote(q: Quote, limit: int = 220) -> str:
    text = q.text if len(q.text) <= limit else q.text[:limit - 1] + "…"
    meta = f"{STARS.get(q.score, '')} · {_date(q.created)}"
    if q.version:
        meta += f" · v{q.version}"
    if q.thumbs:
        meta += f" · {q.thumbs} 👍"
    return f"<em>“{b.esc(text)}”</em> {b.muted(b.esc(meta))}"


TABLE_QUOTES = 2     # quotes under each issue in a table row
DETAIL_QUOTES = 8    # quotes per issue in a role page's "What users said"


def _label(issue: Issue, quote: bool = True) -> str:
    out = f"<strong>{b.esc(issue.label)}</strong>"
    if not issue.curated:
        out += " " + b.muted("(auto-labelled)")
    if quote:
        for q in issue.recent_quotes(TABLE_QUOTES):
            out += "<br />" + _quote(q, 160)
    return out


def _usual(x: float) -> str:
    return f"{x:.1f}" if x < 10 else f"{x:.0f}"


def _issue_rows(issues: list[Issue], canvas: Canvas, taxonomy: Taxonomy | None = None,
                quote: bool = True) -> list[list[str]]:
    rows = []
    for i in issues:
        row = [_label(i, quote)]
        if taxonomy is not None:
            row.append(b.esc(taxonomy.area_name(i.area)))
        row += [str(i.now), _usual(i.usual), _change_cell(i.change, i.polarity),
                canvas.spark(f"{i.polarity[:3]}-{i.label}", i.series, i.polarity)]
        rows.append(row)
    return rows


def _issue_table(issues: list[Issue], canvas: Canvas, taxonomy: Taxonomy | None = None,
                 first: str = "Issue", quote: bool = True) -> str:
    header = [first] + (["Area"] if taxonomy else []) + [
        "This period", "Usual", "Change", f"Last {SPARK_PERIODS} periods"]
    widths = [460] + ([150] if taxonomy else []) + [86, 70, 90, 140]
    numeric = {1, 2} if not taxonomy else {2, 3}
    return b.table(header, _issue_rows(issues, canvas, taxonomy, quote), widths, numeric)


def _shown(issues: list[Issue]) -> tuple[list[Issue], int]:
    """Issues worth a row: said this period, or usually are."""
    shown = [i for i in issues if i.now > 0 or i.usual >= 1]
    return by_volume(shown), len(issues) - len(shown)


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


def _period_pairs(neg: Stream, pos: Stream | None, store: Store, app_id: str) -> list:
    p = neg.period
    base_start = p.start - timedelta(days=p.days * p.baseline)
    base_end = p.start - timedelta(days=1)
    versions = ", ".join(f"{v} ({n})" for v, n in neg.versions_now.most_common(4))
    pairs = [
        ("Period", f"<strong>{b.esc(p.label())}</strong> ({p.days} days)"),
        ("Usual", f"mean of the {p.baseline} periods before it, "
                  f"{_date(base_start)} {base_start.year} – {_date(base_end)} {base_end.year}"),
        ("Reviews", f"{neg.total.now} negative (1–3★), usual {_usual(neg.total.usual)}"
                    + (f"; {pos.total.now} positive (4–5★), usual {_usual(pos.total.usual)}"
                       if pos else "")),
        ("App versions", b.esc(versions) + " " + b.muted("(negative reviews)")),
    ]
    meta = store.conn.execute(
        "SELECT * FROM app_metadata ORDER BY fetched_at DESC LIMIT 1").fetchone()
    if meta:
        pairs.append(("Store rating", f"★ {meta['score']:.2f} from {meta['ratings']:,} ratings "
                                      f"(latest version {b.esc(meta['version'] or '?')})"))
    pairs.append(("App", f"<code>{b.esc(app_id)}</code>"))
    return pairs


# --- summaries: the numbers below, told in sentences -----------------------------

def _span(neg: Stream) -> str:
    p = neg.period
    return f"between {_date(p.start)} and {_date(p.end - timedelta(days=1))}"


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
    """An issue in a list: its name and its count against usual."""
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


def _movers(issues: list[Issue], skip: Issue | None) -> str:
    """'Also rising: … Easing off: …' for the issues that changed."""
    moved = [i for i in by_change(issues) if i is not skip]
    up = [_brief(i) for i in moved if i.change in ("new", "up")][:3]
    down = [_brief(i) for i in moved if i.change == "down"][:3]
    out = ""
    if up:
        out += f"Also rising: {_and(up)}. "
    if down:
        out += f"Easing off: {_and(down)}. "
    return out


def _spotlight(issue: Issue) -> str:
    """The one issue to look at first, with a line of evidence."""
    recent = issue.recent_quotes(1)
    return (f"{_main_version(issue)}"
            + (f"One reviewer put it this way: {_quote(recent[0], 180)}" if recent else ""))


def _hub_summary(neg: Stream, pos: Stream | None, tx: Taxonomy,
                 area_rows: list[tuple[str, Series]]) -> str:
    issues = neg.of_kind("issue")
    t = neg.total
    first = (f"Here’s how the app did on the Play Store {_span(neg)}. "
             f"{_n(t.now, 'reviewer')} left a negative review (1–3★), {_against(t)}")
    if pos:
        first += f", and {pos.total.now} left a positive one (4–5★), {_against(pos.total)}"
    first += "."
    worse = t.change in ("up", "new") or (pos and pos.total.change == "down")
    better = t.change == "down" or (pos and pos.total.change in ("up", "new"))
    if worse and not better:
        first += " So, a rougher period than usual."
    elif better and not worse:
        first += " So, a better period than usual."
    paras = [first]

    # The headline: the area that rose most, else the busiest one.
    rising = sorted([r for r in area_rows if r[1].change in ("up", "new")],
                    key=lambda r: -(r[1].now - r[1].usual))
    lead_issue = None
    if rising or area_rows:
        a, s = (rising or area_rows)[0]
        in_area = [i for i in issues if i.area == a]
        lead_issue = next(iter(by_change([i for i in in_area if i.change in ("up", "new")])),
                          None) or next(iter(by_volume(in_area)), None)
        opener = "The biggest story is" if rising else "Nothing rose beyond normal variation; the busiest area is"
        text = (f"{opener} <strong>{b.esc(tx.area_name(a))}</strong>: "
                f"{_n(s.now, 'negative review')}, {_against(s)}.")
        if lead_issue:
            text += f" Leading it is {_brief(lead_issue)}."
        paras.append(text)
    others = _movers(issues, lead_issue)
    if others:
        paras.append(others.strip())

    switching = next((o for o in neg.of_kind("outcome") if "switching" in o.label.lower()), None)
    if switching and switching.now:
        paras.append(f"{_n(switching.now, 'reviewer')} said they’re switching banks, "
                     f"{_against(switching.series)}.")
    return "".join(f"<p>{p}</p>" for p in paras)


def _role_summary(neg: Stream, pos: Stream | None, tx: Taxonomy, role: Role,
                  issues: list[Issue], total: Series, hub_title: str) -> str:
    area_names = _and([tx.area_name(a) for a in role.areas])
    paras = [f"Here’s what Play Store reviewers said {_span(neg)} about "
             f"<strong>{b.esc(area_names)}</strong>, the "
             f"{'area' if len(role.areas) == 1 else 'areas'} you look after. "
             f"You got {_n(total.now, 'negative review')}, {_against(total)}, "
             f"out of {neg.total.now} across the whole app."]

    moved = [i for i in by_change(issues) if i.change in ("new", "up")]
    shown, _ = _shown(issues)
    top = moved[0] if moved else next(iter(shown), None)
    if top is None:
        paras.append("No one raised a problem in your areas this period.")
    else:
        if moved:
            lead = (f"The one to look at first is <strong>{_name(top)}</strong>: "
                    f"{_n(top.now, 'review')}, {_against(top.series)}. ")
        else:
            lead = ("Nothing in your areas rose beyond normal variation. The issue you "
                    f"heard most about is <strong>{_name(top)}</strong>: "
                    f"{_n(top.now, 'review')}, {_against(top.series)}. ")
        paras.append(lead + _spotlight(top))
        busiest = next(iter(shown), None)
        rest = _movers(issues, top)
        if moved and busiest is not None and busiest is not top and busiest.change not in ("new", "up"):
            rest += f"Your busiest issue overall is still {_brief(busiest)}. "
        if rest:
            paras.append(rest.strip())

    if pos:
        liked = by_volume([i for i in pos.issues if i.kind == "issue" and i.now
                           and set(i.areas) & set(role.areas)])
        if liked:
            paras.append(f"On the bright side, {_n(liked[0].now, 'reviewer')} praised "
                         f"{_name(liked[0])}.")
    paras.append(f"{b.muted('Trends and quotes for every issue are below. For the whole app, see ')}"
                 f"{b.page_link(hub_title, hub_title)}.")
    return "".join(f"<p>{p}</p>" for p in paras)


def _footer(neg: Stream, pos: Stream | None) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    runs = neg.run["run_id"] + (f" and {pos.run['run_id']}" if pos else "")
    return f"<p>{b.muted(b.esc(f'Generated by pv report at {stamp} from run {runs}.'))}</p>"


def _method(neg: Stream) -> str:
    p = neg.period
    return b.expand("Method: how these numbers are made", (
        "<ul>"
        f"<li><strong>Periods.</strong> This report covers {p.days} days ending on the day "
        "of the newest review fetched. <em>Usual</em> is the mean count over the "
        f"{p.baseline} periods of the same length before it. Sparklines show the last "
        f"{SPARK_PERIODS} periods, this one on the right, each on its own scale.</li>"
        "<li><strong>Change.</strong> Counts per period are small, so a ratio would call "
        "1 → 3 a tripling. Instead a count is <em>up</em> when it would be that high by "
        f"chance less than {SIGNIFICANCE:.0%} of the time at the usual rate (a Poisson "
        f"test), and <em>down</em> likewise; under {MIN_CHANGE} reviews is never a "
        "change. <em>New</em> means none in the earlier periods.</li>"
        "<li><strong>Issues</strong> come from clustering every review's sentences over "
        "the app's whole history, which keeps their definitions stable from period to "
        "period; the report only counts the period's share. Clusters describing the same "
        "problem are merged and each review counted once per issue, but one review can "
        "raise several issues, so issue counts add up to more than the review total.</li>"
        "<li><strong>Labels and areas</strong> are curated in <code>curation.yaml</code>; "
        "an issue no one has labelled yet keeps its extracted title (marked "
        "auto-labelled) and is filed by keyword. Quotes are verbatim; French reviews are "
        "machine-translated.</li>"
        "</ul>"))


# --- hub -----------------------------------------------------------------------

def _hub(store: Store, neg: Stream, pos: Stream | None, tx: Taxonomy, app_id: str,
         title: str, role_titles: dict[str, str]) -> StoragePage:
    c = Canvas()
    issues = neg.of_kind("issue")
    p = neg.period

    # area chart, busiest first
    area_ids = list(tx.areas) + ([OTHER] if any(i.area == OTHER for i in issues) else [])
    area_rows = []
    for a in area_ids:
        s = neg.area_series(a)
        if s.now or s.usual >= 0.5:
            area_rows.append((a, s))
    area_rows.sort(key=lambda r: (-r[1].now, -r[1].usual))
    chart = c.add("areas.svg", svg.area_bars(
        [{"name": tx.area_name(a), "now": s.now, "usual": s.usual, "change": s.change}
         for a, s in area_rows],
        "Negative reviews by area, this period",
        f"{p.label()} · bar = this period, tick = usual"), 620)
    ends = _period_ends(p)
    panels = [{"name": "Negative (1–3★)", "values": neg.total.spark(),
               "usual": neg.total.usual, "tone": b.tone(neg.total.change, "negative")}]
    if pos:
        panels.append({"name": "Positive (4–5★)", "values": pos.total.spark(),
                       "usual": pos.total.usual, "tone": b.tone(pos.total.change, "positive")})
    trend = c.add("trend.svg", svg.trend_panels(
        panels, ends, f"Reviews per period, last {SPARK_PERIODS}",
        f"{p.days}-day periods · dashed = usual · dot = this period"), 620)

    roles = "".join(f"<li>{b.page_link(t, tx.roles[r].name)} "
                    f"{b.muted(b.esc('· ' + ', '.join(tx.area_name(a) for a in tx.roles[r].areas)))}</li>"
                    for r, t in role_titles.items())
    intro = (_hub_summary(neg, pos, tx, area_rows)
             + "<p>Each team has its own page with only its areas:</p>"
             f"<ul>{roles}</ul>")
    # issues over time (sits under the trend, filling the right column)
    heat_rows = by_volume([i for i in issues if sum(i.series.spark())])[:20]
    heat_html = (c.add("heatmap.svg", svg.heatmap(
        [{"name": i.label, "values": i.series.spark()} for i in heat_rows], ends,
        f"Negative reviews per issue, last {SPARK_PERIODS} periods",
        "Busiest this period first · outlined column = this period"),
        620)) if heat_rows else ""

    # KPI tiles
    tiles = [_kpi(str(neg.total.now), f"negative reviews in {p.days} days",
                  _vs_usual(neg.total), neg.total.change, compact=True)]
    moved = by_change(issues)
    if moved:
        top = moved[0]
        tiles.append(_kpi(f"{top.now}", f"{LOZENGE[top.change]}: {top.label}",
                          f"usual {_usual(top.usual)} per period · "
                          f"{len(moved)} issue{'s' if len(moved) != 1 else ''} changed",
                          top.change, compact=True))
    else:
        tiles.append(_kpi("0", "issues changed", "every issue is within normal variation", compact=True))
    switching = next((o for o in neg.of_kind("outcome") if "switching" in o.label.lower()), None)
    if switching:
        tiles.append(_kpi(str(switching.now), "say they're switching banks",
                          _vs_usual(switching.series), switching.change, compact=True))

    header = b.section("two_equal",
                       intro + "".join(tiles[:3]) + b.details(_period_pairs(neg, pos, store, app_id)),
                       (heat_html + "<p />" if heat_html else "") + chart + "<p />" + trend)

    # what changed
    changed = by_change(issues + neg.of_kind("outcome"))
    changed_html = "<h2>What changed this period</h2>" + (
        f"<p>{b.muted('Issues whose count is significantly above or below usual (see Method). Everything else moved within normal variation.')}</p>"
        + _issue_table(changed, c, tx)
        if changed else b.info("<p>No issue moved beyond normal variation this period.</p>"))

    # by area
    area_html = "<h2>By area</h2>"
    for a, s in area_rows:
        in_area = [i for i in issues if i.area == a]
        shown, quiet = _shown(in_area)
        readers = [b.page_link(role_titles[r], tx.roles[r].name)
                   for r in role_titles if a in tx.roles[r].areas]
        area_html += (
            f"<h3>{b.esc(tx.area_name(a))} {b.muted(f'· {s.now} reviews, usual {_usual(s.usual)}')}</h3>"
            + (f"<p>{b.muted('Team page: ')}{' · '.join(readers)}</p>" if readers else "")
            + _issue_table(shown, c)
            + (f"<p>{b.muted(f'{quiet} more issue(s) had no reviews this period or before it.')}</p>"
               if quiet else ""))

    # general sentiment
    general = by_volume([i for i in neg.of_kind("outcome") + neg.of_kind("mood")
                         if i.now or i.usual >= 1])
    general_html = b.expand(
        f"General sentiment and outcomes this period ({len(general)} kinds)",
        f"<p>{b.muted('Reviews voicing frustration without a specific cause, or saying what the problems led them to do. Kept apart from the actionable issues above.')}</p>"
        + _issue_table(general, c, first="Sentiment")) if general else ""

    body = b.layout(header,
                    b.section("single", changed_html + area_html + _likes(pos, c) + general_html
                              + _method(neg) + _footer(neg, pos)))
    return c.done(body)


def _likes(pos: Stream | None, c: Canvas) -> str:
    if pos is None:
        return ""
    likes = [i for i in pos.issues if i.now or i.usual >= 1]
    if not likes:
        return ""
    return ("<h2>What users liked this period</h2>"
            f"<p>{b.muted(f'{pos.total.now} positive (4–5★) reviews in all.')}</p>"
            + _issue_table(by_volume(likes), c, first="Theme"))


# --- role pages ------------------------------------------------------------------

def _role(neg: Stream, pos: Stream | None, tx: Taxonomy, role: Role, hub_title: str) -> StoragePage:
    c = Canvas()
    p = neg.period
    issues = neg.in_areas(role.areas)
    total = Series(p)
    for i in issues:
        total.union(i.series)
    area_names = ", ".join(tx.area_name(a) for a in role.areas)

    intro = _role_summary(neg, pos, tx, role, issues, total, hub_title)
    pairs = [("Period", f"{b.esc(p.label())} ({p.days} days)"),
             ("Areas", b.esc(area_names)),
             ("Reviews", f"{total.now} in these areas, usual {_usual(total.usual)} "
                         f"{b.muted(f'(of {neg.total.now} negative reviews in all)')}")]
    header = b.section("single", intro + b.details(pairs))

    moved = by_change(issues)
    shown, quiet = _shown(issues)
    tiles = [_kpi(str(total.now), "reviews in your areas", _vs_usual(total), total.change)]
    if moved:
        top = moved[0]
        tiles.append(_kpi(str(top.now), f"{LOZENGE[top.change]}: {top.label}",
                          f"usual {_usual(top.usual)} · {len(moved)} changed", top.change))
    else:
        tiles.append(_kpi("0", "issues changed", "all within normal variation"))
    # The busiest issue, unless the change tile already shows it.
    lead = next((i for i in shown if not moved or i is not moved[0]), None)
    if lead:
        tiles.append(_kpi(str(lead.now), f"Most raised: {lead.label}",
                          f"usual {_usual(lead.usual)} per period"))
    kpis = b.section("three_equal", *tiles)

    summary = ("<h2>Your issues this period</h2>"
               f"<p>{b.muted('Busiest first. Details and this period’s quotes follow below.')}</p>"
               + _issue_table(shown, c, tx if len(role.areas) > 1 else None, quote=False))
    if "versions" in role.charts:
        summary += _versions_chart(shown, c)

    details = (f"<h2>What users said</h2><p>{b.muted(STAR_KEY)}</p>"
               + "".join(_said(i, c) for i in shown))
    if quiet:
        details += f"<p>{b.muted(f'{quiet} more issue(s) in these areas had no reviews recently.')}</p>"

    likes_html = ""
    if pos:
        liked = by_volume([i for i in pos.issues if i.kind == "issue" and i.now
                           and set(i.areas) & set(role.areas)])
        if liked:
            likes_html = ("<h2>What users praised</h2>"
                          f"<p>{b.muted(f'From the {pos.total.now} positive (4–5★) reviews this period.')}</p>"
                          + "".join(_said(i, c) for i in liked))
    body = b.layout(header, kpis, b.section("single", summary + details + likes_html
                                            + _method(neg) + _footer(neg, pos)))
    return c.done(body)


def _said(i: Issue, c: Canvas) -> str:
    """One issue in full: counts, versions, trend, and many of the period's quotes."""
    versions = ", ".join(f"{v} ({n})" for v, n in i.versions_now.most_common(4))
    facts = (f"{i.now} this period · usual {_usual(i.usual)} · {len(i.all_time):,} all time"
             + (f" · versions {versions}" if versions else ""))
    quotes = i.recent_quotes(DETAIL_QUOTES)
    if quotes:
        lead = (f"{_n(i.now, 'reviewer')} said this; "
                + ("here they all are:" if len(quotes) == i.now
                   else f"the {len(quotes)} most liked and newest:"))
        said = (f"<p>{c.dots(f'{i.polarity[:3]}-{i.label}', [q.score for q in i.quotes_now.values()])}</p>"
                f"<p>{b.muted(lead)}</p><ul>"
                + "".join(f"<li>{_quote(q)}</li>" for q in quotes) + "</ul>")
    else:
        said = f"<p>{b.muted('No reviews this period. Typical wording: ')}<em>“{b.esc(i.quote[:200])}”</em></p>"
    return (f"<h3>{b.esc(i.label)} {_lozenge(i.change, i.polarity)}</h3>"
            f"<p>{b.muted(b.esc(facts))}</p>"
            f"<p>{c.spark(f'{i.polarity[:3]}-{i.label}', i.series, i.polarity)}</p>" + said)


def _version_key(v: str) -> tuple:
    return tuple(int(x) if x.isdigit() else 0 for x in v.split("."))


def _versions_chart(shown: list[Issue], c: Canvas) -> str:
    """This period's issues split by app version: the newest versions that
    carry the most reviews get a colour each, the rest are "other"."""
    rows = [i for i in shown if i.now]
    if not rows:
        return ""
    totals = Counter()
    for i in rows:
        totals.update(i.versions_now)
    named = sorted([v for v, _ in totals.most_common() if v != "unknown"][:len(svg.VERSION_COLOURS)],
                   key=_version_key, reverse=True)
    chart = svg.version_bars([{"name": i.label, "counts": dict(i.versions_now)} for i in rows],
                             named, "Reviews this period by app version",
                             "Each bar is one issue; a version that carries one issue is a likely regression")
    return "<h3>By app version</h3>" + c.add("versions.svg", chart, svg.version_width())


# --- all pages ---------------------------------------------------------------------

def build_all(store: Store, neg: Stream, pos: Stream | None, tx: Taxonomy, app_id: str,
              title: str | None = None, app_name: str | None = None) -> list[PageSpec]:
    hub_title = title or f"Product View @ {app_name or app_id}"
    role_titles = {r: role.name for r, role in tx.roles.items()}
    specs = [PageSpec("hub", hub_title,
                      _hub(store, neg, pos, tx, app_id, hub_title, role_titles), None)]
    for r, role in tx.roles.items():
        specs.append(PageSpec(f"role-{r}", role_titles[r],
                              _role(neg, pos, tx, role, hub_title), hub_title))
    return specs
