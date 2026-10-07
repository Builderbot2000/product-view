"""SVG charts, uploaded as page attachments (report-design.md D2, §4).

Attachments render as images, so: no web fonts (system stack only), no
hover, no CSS beyond presentation attributes. Every chart states its own
title and units in the image, because Confluence shows no caption.
"""

from __future__ import annotations

from html import escape

from .blocks import GRID, INK, MUTED, NEUTRAL, TONE, tone

FONT = "Segoe UI, Helvetica, Arial, sans-serif"
SPARK_BAR, SPARK_GAP, SPARK_H = 8, 3, 30


def spark_width(n: int) -> int:
    return n * (SPARK_BAR + SPARK_GAP) - SPARK_GAP


def _t(text: object) -> str:
    return escape(str(text), quote=True)


def _svg(w: int, h: int, inner: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}" font-family="{FONT}">{inner}</svg>')


def _text(x: float, y: float, s: str, size: int = 12, fill: str = MUTED,
          anchor: str = "start", weight: str = "normal") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" '
            f'text-anchor="{anchor}" font-weight="{weight}">{_t(s)}</text>')


def _accent(t: str | None) -> str:
    """The colour of a tone (blocks.tone), ink when there is no change."""
    return TONE[t][0] if t else INK


def sparkline(values: list[int], t: str | None) -> str:
    """One bar per period, oldest first, on the series' own scale. The last
    bar (this period) is dark, or in its tone's colour when it is a change."""
    w, h = spark_width(len(values)), SPARK_H
    peak = max(values, default=0) or 1
    out = [f'<line x1="0" y1="{h - 0.5}" x2="{w}" y2="{h - 0.5}" stroke="{GRID}"/>']
    for i, n in enumerate(values):
        if not n:
            continue
        bh = max((h - 2) * n / peak, 1.5)
        fill = _accent(t) if i == len(values) - 1 else NEUTRAL
        out.append(f'<rect x="{i * (SPARK_BAR + SPARK_GAP)}" y="{h - 1 - bh:.1f}" '
                   f'width="{SPARK_BAR}" height="{bh:.1f}" rx="1" fill="{fill}"/>')
    return _svg(w, h, "".join(out))


def area_bars(rows: list[dict], title: str, subtitle: str) -> str:
    """Reviews per area this period (bar) against the usual level (tick).

    rows: [{"name", "now", "usual", "change"}] of complaints, in the order given.
    """
    label_w, bar_w, row_h, top = 190, 300, 30, 52
    w, h = label_w + bar_w + 130, top + row_h * len(rows) + 26
    peak = max([r["now"] for r in rows] + [r["usual"] for r in rows] + [1])
    scale = bar_w / peak
    out = [_text(0, 18, title, 15, INK, weight="600"), _text(0, 38, subtitle, 12)]
    for k, r in enumerate(rows):
        y = top + k * row_h
        t = tone(r["change"])
        fill = _accent(t) if t else NEUTRAL
        out.append(_text(label_w - 10, y + 15, r["name"], 12, INK, "end"))
        if r["now"]:
            out.append(f'<rect x="{label_w}" y="{y + 3}" width="{r["now"] * scale:.1f}" '
                       f'height="16" rx="2" fill="{fill}"/>')
        ux = label_w + r["usual"] * scale
        out.append(f'<line x1="{ux:.1f}" y1="{y}" x2="{ux:.1f}" y2="{y + 22}" '
                   f'stroke="{INK}" stroke-width="2"/>')
        end = label_w + max(r["now"], r["usual"]) * scale + 8
        note = {"up": "  ↑ up", "new": "  new", "down": "  ↓ down"}.get(r["change"], "")
        out.append(_text(end, y + 15, f'{r["now"]}  (usual {r["usual"]:.0f}){note}', 11,
                         _accent(t) if note else MUTED,
                         weight="600" if note else "normal"))
    legend_y = h - 8
    out.append(f'<rect x="{label_w}" y="{legend_y - 9}" width="14" height="10" rx="2" fill="{NEUTRAL}"/>')
    out.append(_text(label_w + 20, legend_y, "this period", 11))
    out.append(f'<line x1="{label_w + 105}" y1="{legend_y - 11}" x2="{label_w + 105}" '
               f'y2="{legend_y + 1}" stroke="{INK}" stroke-width="2"/>')
    out.append(_text(label_w + 112, legend_y, "usual (mean of earlier periods)", 11))
    return _svg(w, h, "".join(out))


def _clip(name: str, n: int = 40) -> str:
    return name if len(name) <= n else name[:n - 1] + "…"


def trend_panels(panels: list[dict], periods: list[str], title: str, subtitle: str) -> str:
    """Small multiples, one line per panel, each on its own scale.

    panels: [{"name", "values" (oldest first), "usual", "tone"}]. The dashed
    line is usual; the last point, this period, is in its tone's colour.
    """
    pw, ph, gap, top, left = 250, 110, 44, 52, 28
    w, h = left + len(panels) * (pw + gap) - gap + 30, top + ph + 52
    out = [_text(0, 18, title, 15, INK, weight="600"), _text(0, 38, subtitle, 12)]
    n = len(periods)
    sx = pw / max(n - 1, 1)
    for k, p in enumerate(panels):
        x0, y0 = left + k * (pw + gap), top + 18
        vals = p["values"]
        peak = max(vals + [p["usual"], 1])

        def y(v: float) -> float:
            return y0 + ph - ph * v / peak

        out.append(_text(x0 - left, top + 4, p["name"], 12, INK, weight="600"))
        for v in (0, peak):
            out.append(f'<line x1="{x0}" y1="{y(v):.1f}" x2="{x0 + pw}" y2="{y(v):.1f}" '
                       f'stroke="{GRID}"/>')
            out.append(_text(x0 - 6, y(v) + 4, round(v), 10, MUTED, "end"))
        uy = y(p["usual"])
        out.append(f'<line x1="{x0}" y1="{uy:.1f}" x2="{x0 + pw}" y2="{uy:.1f}" '
                   f'stroke="{MUTED}" stroke-width="1.5" stroke-dasharray="4 3"/>')
        # Usual as an axis label, clear of the line; skipped when it would
        # collide with the 0 or peak label.
        if all(abs(uy - y(v)) >= 11 for v in (0, peak)):
            out.append(_text(x0 - 6, uy + 4, f'{p["usual"]:.0f}', 10, MUTED, "end"))
        pts = " ".join(f"{x0 + i * sx:.1f},{y(v):.1f}" for i, v in enumerate(vals))
        out.append(f'<polyline points="{pts}" fill="none" stroke="{MUTED}" stroke-width="2" '
                   f'stroke-linejoin="round" stroke-linecap="round"/>')
        lx, ly = x0 + (n - 1) * sx, y(vals[-1])
        out.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="5" fill="{_accent(p["tone"])}" '
                   f'stroke="#FFFFFF" stroke-width="2"/>')
        out.append(_text(lx + 9, ly + 4, vals[-1], 12, INK, weight="600"))
        for i in (0, n // 2, n - 1):
            out.append(_text(x0 + i * sx, y0 + ph + 18, periods[i], 10, MUTED,
                             "end" if i == n - 1 else "middle" if i else "start"))
    return _svg(w, h, "".join(out))


# Complaint counts, few to many: green (the "better" tone) through pale yellow
# to orange-red (the "worse" tone). Every cell prints its count, so the
# scale never relies on telling red from green.
SEQ = ["#3E8E55", "#7DB98A", "#BFDDB5", "#F1E6B8", "#F2B48C", "#DB7B4F", "#B43C0A"]
SEQ_LIGHT = {2, 3, 4}   # steps pale enough for ink text; white on the rest
EMPTY = "#F2F2EF"       # no reviews at all


HEAT_LABEL, HEAT_CELL = 270, 40


def heatmap_width(n: int) -> int:
    return HEAT_LABEL + n * HEAT_CELL + 10


def heatmap(rows: list[dict], periods: list[str], title: str, subtitle: str) -> str:
    """Issues by period: one cell per count, green for few reviews to red for many.

    rows: [{"name", "values" (oldest first)}]. One colour scale for the
    whole grid, so rows compare; the outlined last column is this period.
    """
    label_w, cw, ch, top = HEAT_LABEL, HEAT_CELL, 22, 66
    n = len(periods)
    w, h = heatmap_width(n), top + len(rows) * ch + 34
    # The scale tops out at the 95th percentile, so one spike doesn't turn
    # every other cell green; anything above it is full red.
    counts = sorted(v for r in rows for v in r["values"] if v) or [1]
    peak = counts[int(0.95 * (len(counts) - 1))]
    out = [_text(0, 18, title, 15, INK, weight="600"), _text(0, 38, subtitle, 12)]
    for i, lab in enumerate(periods):
        if i % 3 == 2 or i == n - 1:
            last = i == n - 1
            out.append(_text(label_w + i * cw + cw / 2, top - 8, lab, 10,
                             INK if last else MUTED, "middle", "600" if last else "normal"))
    for k, r in enumerate(rows):
        y = top + k * ch
        out.append(_text(label_w - 10, y + 15, _clip(r["name"]), 11, INK, "end"))
        for i, v in enumerate(r["values"]):
            # 1 review is the first step, the peak the last; 0 stays grey.
            step = min(len(SEQ) - 1, round((len(SEQ) - 1) * (v - 1) / max(peak - 1, 1))) if v else -1
            x = label_w + i * cw
            out.append(f'<rect x="{x + 1}" y="{y + 1}" width="{cw - 2}" height="{ch - 2}" '
                       f'rx="2" fill="{SEQ[step] if v else EMPTY}"/>')
            if v:
                out.append(_text(x + cw / 2, y + 15, v, 10,
                                 INK if step in SEQ_LIGHT else "#FFFFFF", "middle"))
    x = label_w + (n - 1) * cw
    out.append(f'<rect x="{x}" y="{top - 1}" width="{cw}" height="{len(rows) * ch + 2}" '
               f'fill="none" stroke="{INK}" stroke-width="1.5" rx="3"/>')
    ly = h - 10
    out.append(_text(label_w + 30, ly, "1", 11, anchor="end"))
    for i, c in enumerate(SEQ):
        out.append(f'<rect x="{label_w + 40 + i * 16}" y="{ly - 9}" width="14" height="10" '
                   f'rx="2" fill="{c}"/>')
    out.append(_text(label_w + 46 + len(SEQ) * 16, ly, f"{peak}+ reviews per period", 11))
    return _svg(w, h, "".join(out))


# One review per dot, coloured by its stars: orange (1★) through grey (3★)
# to green (5★), the same worse / better colours as a change.
STAR_COLOURS = {1: TONE["worse"][0], 2: "#DB7B4F", 3: NEUTRAL, 4: "#6DB07F",
                5: TONE["better"][0]}
DOT, DOT_GAP, DOTS_PER_ROW = 11, 4, 30


def dots(scores: list[int]) -> str:
    """A dot per reviewer, lowest stars first, wrapped in rows."""
    step = DOT + DOT_GAP
    out = []
    for k, s in enumerate(sorted(scores)):
        cx = (k % DOTS_PER_ROW) * step + DOT / 2 + 1
        cy = (k // DOTS_PER_ROW) * step + DOT / 2 + 1
        out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{DOT / 2}" '
                   f'fill="{STAR_COLOURS.get(s, NEUTRAL)}"/>')
    rows = -(-len(scores) // DOTS_PER_ROW)
    return _svg(dots_width(len(scores)), rows * step + 2, "".join(out))


def dots_width(n: int) -> int:
    return min(n, DOTS_PER_ROW) * (DOT + DOT_GAP) + 2


# Categorical, checked with the dataviz validator (light): blue, aqua,
# violet, then grey for every other version.
VERSION_COLOURS = ["#2A78D6", "#1BAF7A", "#4A3AA7"]


def version_width() -> int:
    return 270 + 320 + 50


def version_bars(rows: list[dict], versions: list[str], title: str, subtitle: str) -> str:
    """Each issue's reviews this period, split by app version.

    rows: [{"name", "counts": {version: n}}]; `versions` are the named ones,
    newest first, and anything else is "other". Counts sit in wide segments.
    """
    label_w, bar_w, row_h, top = 270, 320, 28, 66
    w, h = version_width(), top + row_h * len(rows) + 10
    colours = dict(zip(versions, VERSION_COLOURS))
    peak = max([sum(r["counts"].values()) for r in rows] + [1])
    scale = bar_w / peak
    out = [_text(0, 18, title, 15, INK, weight="600"), _text(0, 38, subtitle, 12)]
    x = label_w
    for v in versions + ["other"]:
        label = f"v{v}" if v != "other" else "other / unknown"
        out.append(f'<rect x="{x:.1f}" y="{49}" width="12" height="10" rx="2" '
                   f'fill="{colours.get(v, NEUTRAL)}"/>' + _text(x + 17, 58, label, 11))
        x += 17 + 6.5 * len(label) + 14
    for k, r in enumerate(rows):
        y = top + k * row_h
        out.append(_text(label_w - 10, y + 15, _clip(r["name"]), 11, INK, "end"))
        other = sum(n for v, n in r["counts"].items() if v not in colours)
        x = label_w
        for v, n in [(v, r["counts"].get(v, 0)) for v in versions] + [("other", other)]:
            if not n:
                continue
            sw = n * scale
            out.append(f'<rect x="{x:.1f}" y="{y + 3}" width="{max(sw - 2, 1):.1f}" '
                       f'height="18" rx="2" fill="{colours.get(v, NEUTRAL)}"/>')
            if sw >= 18:
                out.append(_text(x + sw / 2 - 1, y + 16, n, 10, "#FFFFFF", "middle", "600"))
            x += sw
        out.append(_text(x + 6, y + 16, sum(r["counts"].values()), 11, MUTED))
    return _svg(w, h, "".join(out))
