"""The report's pages: a hub with every area, and one page per role (§5).

Both are periodic overviews (D15): every count is for the reporting period,
set against "usual", the mean of the equal periods before it. Quotes come
from the period too, so a reader sees what was said this time, not the
standing medoid of a cluster spanning years.
"""

from __future__ import annotations

import re
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

    def spark(self, key: str, series: Series) -> str:
        name = f"spark-{_slug(key)}.svg"
        if name not in self.files:
            self.files[name] = svg.sparkline(series.spark(), series.change).encode("utf-8")
        # An explicit width: without one Confluence stretches it to the cell.
        return b.image(name, svg.spark_width(SPARK_PERIODS))

    def done(self, body: str) -> StoragePage:
        return StoragePage(body, [Attachment(n, d, "image/svg+xml") for n, d in self.files.items()])


# --- shared pieces -----------------------------------------------------------

LOZENGE = {"new": ("NEW", "Red"), "up": ("↑ UP", "Red"), "down": ("↓ DOWN", "Blue"),
           "steady": ("steady", "Grey"), "quiet": ("quiet", "Grey")}


def _change_cell(change: str) -> str:
    title, colour = LOZENGE[change]
    hl = b.RISING_TINT if change in ("up", "new") else b.POSITIVE_TINT if change == "down" else None
    return b.cell(b.status(title, colour), highlight=hl)


def _date(d: datetime) -> str:
    return f"{d:%b} {d.day}"


def _quote(q: Quote, limit: int = 220) -> str:
    text = q.text if len(q.text) <= limit else q.text[:limit - 1] + "…"
    meta = f"{STARS.get(q.score, '')} · {_date(q.created)}"
    if q.version:
        meta += f" · v{q.version}"
    if q.thumbs:
        meta += f" · {q.thumbs} 👍"
    return f"<em>“{b.esc(text)}”</em> {b.muted(b.esc(meta))}"


def _label(issue: Issue, quote: bool = True) -> str:
    out = f"<strong>{b.esc(issue.label)}</strong>"
    if not issue.curated:
        out += " " + b.muted("(auto-labelled)")
    if quote:
        recent = issue.recent_quotes(1)
        if recent:
            out += "<br />" + _quote(recent[0], 160)
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
        row += [str(i.now), _usual(i.usual), _change_cell(i.change),
                canvas.spark(f"{i.polarity[:3]}-{i.label}", i.series)]
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


def _kpi(big: str, caption: str, note: str, change: str = "steady") -> str:
    accent = {"up": b.RISING, "new": b.RISING, "down": b.POSITIVE}.get(change, b.INK)
    bg, border = {"up": (b.RISING_TINT, "#F2C6B0"), "new": (b.RISING_TINT, "#F2C6B0"),
                  "down": (b.POSITIVE_TINT, "#C9D6EE")}.get(change, (b.PANEL_BG, b.GRID))
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

    roles = "".join(f"<li>{b.page_link(t, tx.roles[r].name)} "
                    f"{b.muted(b.esc('· ' + ', '.join(tx.area_name(a) for a in tx.roles[r].areas)))}</li>"
                    for r, t in role_titles.items())
    intro = (f"<p>What Play Store reviewers said in <strong>{b.esc(p.label())}</strong>, "
             "by product area, against what is usual for this app. Built for review "
             "analysts; each team has its own page with only its areas:</p>"
             f"<ul>{roles}</ul>")
    header = b.section("two_equal", intro + b.details(_period_pairs(neg, pos, store, app_id)),
                       chart)

    # KPI tiles
    tiles = [_kpi(str(neg.total.now), f"negative reviews in {p.days} days",
                  _vs_usual(neg.total), neg.total.change)]
    moved = by_change(issues)
    if moved:
        top = moved[0]
        tiles.append(_kpi(f"{top.now}", f"{LOZENGE[top.change][0]}: {top.label}",
                          f"usual {_usual(top.usual)} per period · "
                          f"{len(moved)} issue{'s' if len(moved) != 1 else ''} changed",
                          top.change))
    else:
        tiles.append(_kpi("0", "issues changed", "every issue is within normal variation"))
    switching = next((o for o in neg.of_kind("outcome") if "switching" in o.label.lower()), None)
    if switching:
        tiles.append(_kpi(str(switching.now), "say they're switching banks",
                          _vs_usual(switching.series), switching.change))
    kpis = b.section("three_equal", *tiles[:3])

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

    likes_html = _likes(pos, c, None, "What users liked this period")
    body = b.layout(header, kpis,
                    b.section("single", changed_html + area_html + general_html + likes_html
                              + _method(neg) + _footer(neg, pos)))
    return c.done(body)


def _likes(pos: Stream | None, c: Canvas, areas: tuple[str, ...] | None, heading: str) -> str:
    if pos is None:
        return ""
    likes = [i for i in pos.issues if i.now or i.usual >= 1]
    if areas is not None:
        likes = [i for i in likes if i.kind == "issue" and set(i.areas) & set(areas)]
    if not likes:
        return ""
    return b.expand(f"{heading} ({pos.total.now} positive reviews in all)",
                    _issue_table(by_volume(likes), c, first="Theme"))


# --- role pages ------------------------------------------------------------------

def _role(neg: Stream, pos: Stream | None, tx: Taxonomy, role: Role, hub_title: str) -> StoragePage:
    c = Canvas()
    p = neg.period
    issues = neg.in_areas(role.areas)
    total = Series(p)
    for i in issues:
        total.union(i.series)
    area_names = ", ".join(tx.area_name(a) for a in role.areas)

    intro = (f"<p>Negative Play Store reviews about <strong>{b.esc(area_names)}</strong> "
             f"in <strong>{b.esc(p.label())}</strong>, against the usual level. "
             f"{b.muted('Other areas are left out; the full picture is on ')}"
             f"{b.page_link(hub_title, hub_title)}.</p>")
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
        tiles.append(_kpi(str(top.now), f"{LOZENGE[top.change][0]}: {top.label}",
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

    details = "<h2>What users said</h2>"
    for i in shown:
        versions = ", ".join(f"{v} ({n})" for v, n in i.versions_now.most_common(4))
        facts = (f"{i.now} this period · usual {_usual(i.usual)} · {len(i.all_time):,} all time"
                 + (f" · versions {versions}" if versions else ""))
        quotes = i.recent_quotes(3)
        said = ("<ul>" + "".join(f"<li>{_quote(q)}</li>" for q in quotes) + "</ul>") if quotes \
            else f"<p>{b.muted('No reviews this period. Typical wording: ')}<em>“{b.esc(i.quote[:200])}”</em></p>"
        title, colour = LOZENGE[i.change]
        details += (f"<h3>{b.esc(i.label)} {b.status(title, colour)}</h3>"
                    f"<p>{b.muted(b.esc(facts))}</p>"
                    f"<p>{c.spark(f'neg-{i.label}', i.series)}</p>" + said)
    if quiet:
        details += f"<p>{b.muted(f'{quiet} more issue(s) in these areas had no reviews recently.')}</p>"

    likes_html = _likes(pos, c, role.areas, "What users liked in these areas")
    body = b.layout(header, kpis, b.section("single", summary + details + likes_html
                                            + _method(neg) + _footer(neg, pos)))
    return c.done(body)


# --- all pages ---------------------------------------------------------------------

def build_all(store: Store, neg: Stream, pos: Stream | None, tx: Taxonomy, app_id: str,
              title: str | None = None) -> list[PageSpec]:
    hub_title = title or f"Product View: {app_id}"
    role_titles = {r: f"Product View · {role.name}" for r, role in tx.roles.items()}
    specs = [PageSpec("hub", hub_title,
                      _hub(store, neg, pos, tx, app_id, hub_title, role_titles), None)]
    for r, role in tx.roles.items():
        specs.append(PageSpec(f"role-{r}", role_titles[r],
                              _role(neg, pos, tx, role, hub_title), hub_title))
    return specs
