"""SVG charts, uploaded as page attachments (report-design.md D2, §4).

Attachments render as images, so: no web fonts (system stack only), no
hover, no CSS beyond presentation attributes. Every chart states its own
title and units in the image, because Confluence shows no caption.
"""

from __future__ import annotations

from html import escape

from .blocks import GRID, INK, MUTED, NEUTRAL, POSITIVE, RISING

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


def _accent(change: str) -> str:
    return RISING if change in ("up", "new") else POSITIVE if change == "down" else INK


def sparkline(values: list[int], change: str) -> str:
    """One bar per period, oldest first, on the series' own scale. The last
    bar (this period) is dark, or in the accent when it is a change."""
    w, h = spark_width(len(values)), SPARK_H
    peak = max(values, default=0) or 1
    out = [f'<line x1="0" y1="{h - 0.5}" x2="{w}" y2="{h - 0.5}" stroke="{GRID}"/>']
    for i, n in enumerate(values):
        if not n:
            continue
        bh = max((h - 2) * n / peak, 1.5)
        fill = _accent(change) if i == len(values) - 1 else NEUTRAL
        out.append(f'<rect x="{i * (SPARK_BAR + SPARK_GAP)}" y="{h - 1 - bh:.1f}" '
                   f'width="{SPARK_BAR}" height="{bh:.1f}" rx="1" fill="{fill}"/>')
    return _svg(w, h, "".join(out))


def area_bars(rows: list[dict], title: str, subtitle: str) -> str:
    """Reviews per area this period (bar) against the usual level (tick).

    rows: [{"name", "now", "usual", "change"}], drawn in the order given.
    """
    label_w, bar_w, row_h, top = 190, 300, 30, 52
    w, h = label_w + bar_w + 130, top + row_h * len(rows) + 26
    peak = max([r["now"] for r in rows] + [r["usual"] for r in rows] + [1])
    scale = bar_w / peak
    out = [_text(0, 18, title, 15, INK, weight="600"), _text(0, 38, subtitle, 12)]
    for k, r in enumerate(rows):
        y = top + k * row_h
        fill = _accent(r["change"]) if r["change"] in ("up", "new", "down") else NEUTRAL
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
                         _accent(r["change"]) if note else MUTED,
                         weight="600" if note else "normal"))
    legend_y = h - 8
    out.append(f'<rect x="{label_w}" y="{legend_y - 9}" width="14" height="10" rx="2" fill="{NEUTRAL}"/>')
    out.append(_text(label_w + 20, legend_y, "this period", 11))
    out.append(f'<line x1="{label_w + 105}" y1="{legend_y - 11}" x2="{label_w + 105}" '
               f'y2="{legend_y + 1}" stroke="{INK}" stroke-width="2"/>')
    out.append(_text(label_w + 112, legend_y, "usual (mean of earlier periods)", 11))
    return _svg(w, h, "".join(out))
