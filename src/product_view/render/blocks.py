"""Confluence storage-format building blocks (report-design.md §3).

Every helper returns a string of well-formed storage XHTML. Text goes through
`esc`; anything passed as `body` is already storage format and is trusted.
Only elements probe 2 confirmed are used; see §3 for what Confluence strips.
"""

from __future__ import annotations

from html import escape

# Visual language, report-design.md §4. A change is coloured by what it means
# for the app (`tone`): worse is orange, better is green, and praise thinning
# out is blue, milder than a complaint rising.
INK = "#16191D"
MUTED = "#596069"
GRID = "#E3E4E1"
NEUTRAL = "#A3A8AE"
WORSE, WORSE_TINT, WORSE_BORDER = "#B43C0A", "#FBEAE2", "#F2C6B0"
BETTER, BETTER_TINT, BETTER_BORDER = "#1F7A3A", "#E4F2E7", "#BCDCC4"
FADING, FADING_TINT, FADING_BORDER = "#2B5FB8", "#E9EFF9", "#C9D6EE"
PANEL_BG = "#F7F7F5"

TONE = {"worse": (WORSE, WORSE_TINT, WORSE_BORDER, "Red"),
        "better": (BETTER, BETTER_TINT, BETTER_BORDER, "Green"),
        "fading": (FADING, FADING_TINT, FADING_BORDER, "Blue")}


def tone(change: str, polarity: str = "negative") -> str | None:
    """worse | better | fading, or None for no change. More complaints is
    worse and fewer is better; more praise is better and less is fading."""
    if change in ("up", "new"):
        return "worse" if polarity == "negative" else "better"
    if change == "down":
        return "better" if polarity == "negative" else "fading"
    return None


def esc(text: object) -> str:
    return escape(str(text), quote=True)


def cdata(text: str) -> str:
    return "<![CDATA[" + text.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def macro(name: str, params: dict | None = None, body: str | None = None,
          plain: str | None = None) -> str:
    p = "".join(f'<ac:parameter ac:name="{esc(k)}">{esc(v)}</ac:parameter>'
                for k, v in (params or {}).items())
    b = f"<ac:rich-text-body>{body}</ac:rich-text-body>" if body is not None else ""
    pb = f"<ac:plain-text-body>{cdata(plain)}</ac:plain-text-body>" if plain is not None else ""
    return f'<ac:structured-macro ac:name="{esc(name)}">{p}{b}{pb}</ac:structured-macro>'


def status(title: str, colour: str = "Grey") -> str:
    """Lozenge. colour: Grey, Red, Yellow, Green, Blue, Purple."""
    return macro("status", {"colour": colour, "title": title})


def panel(body: str, bg: str = PANEL_BG, border: str = GRID) -> str:
    return macro("panel", {"bgColor": bg, "borderColor": border}, body)


def expand(title: str, body: str) -> str:
    return macro("expand", {"title": title}, body)


def info(body: str, kind: str = "info") -> str:
    """kind: info, note, warning, tip."""
    return macro(kind, body=body)


def excerpt(name: str, body: str) -> str:
    return macro("excerpt", {"name": name, "hidden": "false"}, body)


def anchor(name: str) -> str:
    return macro("anchor", {"": name})


def anchor_link(name: str, text: str) -> str:
    return (f'<ac:link ac:anchor="{esc(name)}">'
            f"<ac:plain-text-link-body>{cdata(text)}</ac:plain-text-link-body></ac:link>")


def page_link(title: str, text: str) -> str:
    return (f'<ac:link><ri:page ri:content-title="{esc(title)}" />'
            f"<ac:plain-text-link-body>{cdata(text)}</ac:plain-text-link-body></ac:link>")


def image(filename: str, width: int | None = None) -> str:
    w = f' ac:width="{width}"' if width else ""
    return f'<ac:image{w}><ri:attachment ri:filename="{esc(filename)}" /></ac:image>'


def colour(text: str, rgb: str) -> str:
    return f'<span style="color: {rgb};">{text}</span>'


def muted(text: str) -> str:
    return colour(text, MUTED)


def section(kind: str, *cells: str) -> str:
    """One layout row. kind: single, two_equal, two_right_sidebar,
    two_left_sidebar, three_equal, three_with_sidebars."""
    inner = "".join(f"<ac:layout-cell>{c}</ac:layout-cell>" for c in cells)
    return f'<ac:layout-section ac:type="{kind}">{inner}</ac:layout-section>'


def layout(*sections: str) -> str:
    # Once a layout is used, the whole body must sit inside it (§3).
    return "<ac:layout>" + "".join(sections) + "</ac:layout>"


def cell(content: str, tag: str = "td", highlight: str | None = None,
         align: str | None = None) -> str:
    attrs = ""
    if highlight:
        attrs += f' data-highlight-colour="{highlight}"'
    if align:
        attrs += f' style="text-align: {align};"'
    return f"<{tag}{attrs}>{content}</{tag}>"


def table(header: list[str], rows: list[list[str]], widths: list[int] | None = None,
          numeric: set[int] | frozenset = frozenset()) -> str:
    """`rows` hold ready-made cells (from `cell`) or plain storage strings.
    `numeric` column indexes are right-aligned."""
    cols = ""
    if widths:
        cols = "<colgroup>" + "".join(f'<col style="width: {w}px;" />' for w in widths) + "</colgroup>"
    head = "<tr>" + "".join(
        cell(h, "th", align="right" if i in numeric else None) for i, h in enumerate(header)
    ) + "</tr>"
    body = ""
    for row in rows:
        body += "<tr>" + "".join(
            c if c.startswith("<td") else cell(c, align="right" if i in numeric else None)
            for i, c in enumerate(row)
        ) + "</tr>"
    return f'<table data-layout="full-width">{cols}<tbody>{head}{body}</tbody></table>'


def details(pairs: list[tuple[str, str]]) -> str:
    rows = "".join(f"<tr><th>{esc(k)}</th><td>{v}</td></tr>" for k, v in pairs)
    return macro("details", body=f"<table><tbody>{rows}</tbody></table>")
