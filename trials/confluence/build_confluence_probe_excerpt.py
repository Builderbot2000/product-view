"""Probe 3: `excerpt-include` across pages (report-design.md D5).

Publishes a source page holding two named excerpts (a table with a status
lozenge, and an SVG attachment), and a target page that includes both. Then
reads the target's rendered view to see what came through.

    python trials/confluence/build_confluence_probe_excerpt.py SPACE_KEY out/probe3.view.html

The SVG excerpt is included twice: once as the renderer writes images today
(`ri:attachment` with no page, which means "this page"), and once with the
source page named inside the attachment reference. Results are recorded in
Project.md §0 "Still open"."""
import sys
from product_view.publish.confluence import Client, load_dotenv
from product_view.publish.storage import Attachment

SOURCE = "PV probe 3: excerpt source"
TARGET = "PV probe 3: excerpt target"

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="320" height="80">'
       '<rect width="320" height="80" fill="#b43c0a"/>'
       '<text x="16" y="48" font-size="20" fill="#ffffff">probe3 chart</text></svg>')

def macro(name, params=None, body=None):
    p = "".join(f'<ac:parameter ac:name="{k}">{v}</ac:parameter>' for k, v in (params or {}).items())
    b = f"<ac:rich-text-body>{body}</ac:rich-text-body>" if body is not None else ""
    return f'<ac:structured-macro ac:name="{name}">{p}{b}</ac:structured-macro>'

def include(name):
    return ('<ac:structured-macro ac:name="excerpt-include">'
            f'<ac:parameter ac:name="name">{name}</ac:parameter>'
            '<ac:parameter ac:name="nopanel">true</ac:parameter>'
            f'<ac:parameter ac:name=""><ac:link><ri:page ri:content-title="{SOURCE}" /></ac:link></ac:parameter>'
            '</ac:structured-macro>')

table = ('<table><tbody><tr><th>Topic</th><th>This period</th><th>Change</th></tr>'
         f'<tr><td>probe3-table-row</td><td>12</td><td>{macro("status", {"colour": "Red", "title": "Rising"})}</td></tr>'
         '</tbody></table>')
img_plain = '<p><ac:image ac:width="320"><ri:attachment ri:filename="probe3.svg" /></ac:image></p>'
img_named = ('<p><ac:image ac:width="320"><ri:attachment ri:filename="probe3.svg">'
             f'<ri:page ri:content-title="{SOURCE}" /></ri:attachment></ac:image></p>')

source = ("<h2>Source</h2>"
          + macro("excerpt", {"name": "table", "hidden": "false"}, table)
          + macro("excerpt", {"name": "chart-plain", "hidden": "false"}, img_plain)
          + macro("excerpt", {"name": "chart-named", "hidden": "false"}, img_named))
target = ("<h2>E1 table excerpt</h2>" + include("table")
          + "<h2>E2 chart, attachment with no page</h2>" + include("chart-plain")
          + "<h2>E3 chart, attachment naming the source page</h2>" + include("chart-named"))

def main(space, out):
    load_dotenv()
    c = Client.from_env()
    src, _ = c.upsert_page(space, SOURCE, source, message="probe 3")
    c.sync_attachments(src["id"], [Attachment("probe3.svg", SVG.encode(), "image/svg+xml")])
    tgt, _ = c.upsert_page(space, TARGET, target, message="probe 3")
    view = c._request("GET", f"/rest/api/content/{tgt['id']}", params={"expand": "body.view"})
    html = view["body"]["view"]["value"]
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print("source", c.page_url(src)); print("target", c.page_url(tgt))

if __name__ == "__main__":
    main(*sys.argv[1:3])
