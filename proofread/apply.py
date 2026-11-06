"""Apply a proofread to a built report: copy its pages and attachments to a new
directory and correct them there (corrections format: report-2026-10-08.yaml).

    .venv/Scripts/python.exe -X utf8 proofread/apply.py proofread/report-2026-10-08.yaml

Writes out/report-proofread/; out/report is left as built. Every correction
must match somewhere, so a typo fails instead of passing silently.
"""
from __future__ import annotations

import re
import shutil
import sys
from html import escape, unescape
from pathlib import Path

import yaml

from product_view.render import svg

SRC, DST = Path("out/report"), Path("out/report-proofread")
PAGE = "page.storage.xhtml"
MUTED = '<span style="color: #596069;">'
NOTE = " Issue names and quotes were checked by hand on Oct 14, 2026."


def esc(text: str) -> str:
    return escape(text, quote=True)


def quote_re(text: str) -> str:
    """One rendered quote: the text (maybe shortened with …) and its muted meta."""
    return f'<em>“{re.escape(esc(text))}[^”]*”</em> {re.escape(MUTED)}[^<]*</span>'


def quote_html(text: str, meta: str) -> str:
    return f"<em>“{esc(text)}”</em> {MUTED}{esc(meta)}</span>"


def row_re(name: str) -> str:
    return rf"<tr><td><strong>{re.escape(esc(name))}</strong>.*?</tr>"


def section_re(name: str) -> str:
    """A role page's detail section: its heading up to the next one."""
    return (rf"<h3>{re.escape(esc(name))} <ac:structured-macro.*?"
            rf"(?=<h3>|<h2>|<p>{re.escape(MUTED)}\d+ more issue)")


def count_of(row: str) -> int:
    return int(re.search(r'<td style="text-align: right;">(\d+)</td>', row).group(1))


def insert_row(table_html: str, row: str) -> str:
    """Into a table's rows, before the first with a lower count."""
    n = count_of(row)
    for m in re.finditer(r"<tr><td>.*?</tr>", table_html):
        if count_of(m.group(0)) < n:
            return table_html[:m.start()] + row + table_html[m.start():]
    return table_html.replace("</tbody>", row + "</tbody>", 1)


class Pages:
    def __init__(self, root: Path) -> None:
        self.text = {p.parent.name: p.read_text(encoding="utf-8") for p in root.glob(f"*/{PAGE}")}
        self.hits: dict[str, int] = {}

    def sub(self, key: str, pattern: str, repl, flags: int = re.S, pages=None) -> None:
        for page in pages or self.text:
            new, n = re.subn(pattern, repl, self.text[page], flags=flags)
            self.text[page] = new
            self.hits[key] = self.hits.get(key, 0) + n


def remove(pages: Pages, name: str) -> None:
    pages.sub(f"remove {name}", row_re(name), "")
    pages.sub(f"remove {name}", section_re(name), "")


def move(pages: Pages, src: dict[str, str], m: dict) -> None:
    name, key = m["name"], f"move {m['name']}"
    # Hub: cut the row from the old area's table, insert it into the new one's.
    hub = pages.text["hub"]
    start = hub.index(f"<h3>{esc(m['from_area'])} ")
    row = re.compile(row_re(name), re.S).search(hub, start)
    hub = hub[:row.start()] + hub[row.end():]
    t0 = hub.index(f"<h3>{esc(m['to_area'])} ")
    t1 = hub.index("</table>", t0)
    pages.text["hub"] = hub[:t0] + insert_row(hub[t0:t1], row.group(0)) + hub[t1:]
    pages.hits[key] = 1
    # Role pages: copy the row (without its Area cell) and the detail section.
    source = src[m["source"]]
    full_row = re.search(row_re(name), source, re.S).group(0)
    bare_row = full_row.replace(f"<td>{esc(m['from_area'])}</td>", "", 1)
    section = re.search(section_re(name), source, re.S).group(0)
    for page in m.get("remove_from", []):
        pages.sub(key, row_re(name), "", pages=[page])
        pages.sub(key, section_re(name), "", pages=[page])
    for page in m.get("add_to", []):
        text = pages.text[page]
        t0 = text.index("Your issues this period")
        t1 = text.index("</table>", t0)
        table = insert_row(text[t0:t1], bare_row)
        text = text[:t0] + table + text[t1:]
        # The detail sections follow the table's order: go before the next row's.
        rows = re.findall(r"<tr><td><strong>(.*?)</strong>", table)
        after = rows[rows.index(esc(name)) + 1:]
        at = next((text.index(f"<h3>{r} ") for r in after if f"<h3>{r} " in text),
                  text.index("<h2>What users praised"))
        pages.text[page] = text[:at] + section + text[at:]
        for att in re.findall(r'ri:filename="([^"]+)"', bare_row + section):
            shutil.copy2(SRC / m["source"] / att, DST / page / att)
    for page in m.get("relabel_in", []):
        pages.sub(key, rf"({row_re(name)[:-6]}?)<td>{re.escape(esc(m['from_area']))}</td>",
                  rf"\1<td>{esc(m['to_area'])}</td>", pages=[page])


def drop(pages: Pages, text: str) -> None:
    q = quote_re(text)
    pages.sub(f"drop {text}", rf"<br />{q}", "")
    pages.sub(f"drop {text}", rf"<li>{q}</li>", "")
    for page, body in pages.text.items():
        if re.search(q, body):
            sys.exit(f"drop: {text!r} is still on {page} (in running text? use swap)")


def add(pages: Pages, a: dict) -> None:
    """Append to the issue's table cells and quote lists that lack it."""
    name, new = esc(a["issue"]), quote_html(a["text"], a["meta"])
    probe = f"“{esc(a['text'])}"
    key = f"add {a['issue']}: {a['text']}"

    def cell(m: re.Match) -> str:
        head, tail = m.group(1), m.group(2)
        return m.group(0) if probe in head else f"{head}<br />{new}{tail}"

    def section(m: re.Match) -> str:
        body = m.group(0)
        if probe in body or "<ul>" not in body:
            return body
        return body.replace("</ul>", f"<li>{new}</li></ul>", 1)

    # Only the hub's tables carry quotes; role pages quote in their detail sections.
    pages.sub(key, rf"(<tr><td><strong>{re.escape(name)}</strong>(?:(?!</td>).)*)(</td>)", cell,
              pages=["hub"])
    pages.sub(key, section_re(a["issue"]), section)


def fix_leads(pages: Pages) -> None:
    """Re-word each quote list's lead line to the quotes it now holds."""
    lead = re.compile(rf"({re.escape(MUTED)}(\d+) reviewers? said this; )(here they all are:|the (\d+) most liked and newest:)(</span></p><ul>(.*?)</ul>)", re.S)

    def fix(m: re.Match) -> str:
        n, shown = int(m.group(2)), m.group(6).count("<li>")
        was = int(m.group(4)) if m.group(4) else n
        if shown == was:
            return m.group(0)
        words = ("here they all are:" if shown == n else
                 "here is one of them:" if shown == 1 else f"here are {shown} of them:")
        return f"{m.group(1)}{words}{m.group(5)}"

    for page in pages.text:
        pages.text[page] = lead.sub(fix, pages.text[page])


def read_heatmap(text: str) -> tuple[list[dict], list[str], str, str]:
    """The rows, period labels, title and subtitle that svg.heatmap drew."""
    top, ch, cw = 66, 22, svg.HEAT_CELL
    texts = [(float(x), float(y), size, unescape(s)) for x, y, size, s in re.findall(
        r'<text x="([\d.]+)" y="([\d.]+)" font-size="(\d+)"[^>]*>([^<]*)</text>', text)]
    title, subtitle = texts[0][3], texts[1][3]
    labels = [t for t in texts if t[2] == "11" and t[0] == svg.HEAT_LABEL - 10]
    n = round((int(re.search(r'width="(\d+)"', text).group(1)) - svg.HEAT_LABEL - 10) / cw)
    periods = [""] * n
    rows = [{"name": s, "values": [0] * n} for _, _, _, s in labels]
    for x, y, size, s in texts[2:]:
        if size != "10":
            continue
        i = round((x - svg.HEAT_LABEL - cw / 2) / cw)
        if y < top:
            periods[i] = s
        else:
            rows[round((y - 15 - top) / ch)]["values"][i] = int(s)
    return rows, periods, title, subtitle


def fix_charts(removed: list[str], renamed: dict[str, str]) -> int:
    """Carry removals and renames into the charts, whose labels are clipped
    to 40 characters. The heatmap is redrawn (rows go); the rest are relabelled."""
    clipped = {esc(svg._clip(old)): esc(svg._clip(new)) for old, new in renamed.items()}
    gone = {svg._clip(name) for name in removed}
    hits = 0
    for path in DST.glob("*/*.svg"):
        if path.name.startswith(("spark-", "dots-")):
            continue
        text = path.read_text(encoding="utf-8")
        if path.name == "heatmap.svg":
            rows, periods, title, subtitle = read_heatmap(text)
            if svg.heatmap(rows, periods, title, subtitle) != text:
                sys.exit(f"{path}: redrawing the heatmap does not reproduce it")
            rows = [r for r in rows if r["name"] not in gone]
            text = svg.heatmap(rows, periods, title, subtitle)
        for old, new in clipped.items():
            text, n = re.subn(rf'(text-anchor="end"[^>]*>){re.escape(old)}<', rf"\g<1>{new}<", text)
            hits += n
        path.write_text(text, encoding="utf-8")
    return hits


def main(corrections: Path) -> None:
    c = yaml.safe_load(corrections.read_text(encoding="utf-8"))
    if DST.exists():
        shutil.rmtree(DST)
    shutil.copytree(SRC, DST)
    src = Pages(SRC).text
    pages = Pages(DST)

    for name in c.get("remove", []):
        remove(pages, name)
    for m in c.get("move", []):
        move(pages, src, m)
    for text in c.get("drop", []):
        drop(pages, text)
    for s in c.get("swap", []):
        pages.sub(f"swap {s['from']}", quote_re(s["from"]), quote_html(s["to"], s["meta"]).replace("\\", "\\\\"))
    for a in c.get("add", []):
        add(pages, a)
    for old, new in c.get("rename", {}).items():
        key = f"rename {old}"
        pages.sub(key, rf"<strong>{re.escape(esc(old))}</strong> {re.escape(MUTED)}\(auto-labelled\)</span>",
                  f"<strong>{esc(new)}</strong>")
        pages.sub(key, re.escape(esc(old)), esc(new).replace("\\", "\\\\"))
    for r in c.get("replace", []):
        pages.sub(f"replace {r['from'][:60]}", re.escape(r["from"]), r["to"].replace("\\", "\\\\"))
    fix_leads(pages)
    pages.sub("plural", r"(?<![\d,])1 more issue\(s\)", "1 more issue")
    pages.sub("plural", r"more issue\(s\)", "more issues")
    pages.sub("plural", r"· 1 reviews,", "· 1 review,")
    pages.sub("note", r"Generated by pv report at [^<]*?\.(?=<)",
              esc(c["footer"]).replace("\\", "\\\\") + NOTE)
    if not fix_charts(c.get("remove", []), c.get("rename", {})):
        sys.exit("no chart label was renamed")

    missed = [k for k, n in pages.hits.items() if n == 0]
    if missed:
        sys.exit("no match for:\n  " + "\n  ".join(missed))
    left = [p for p, t in pages.text.items() if "(auto-labelled)</span>" in t]
    for page, text in pages.text.items():
        (DST / page / PAGE).write_text(text, encoding="utf-8")
    print(f"{len(pages.hits)} corrections applied -> {DST}")
    if left:
        print(f"still auto-labelled on: {', '.join(left)}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
