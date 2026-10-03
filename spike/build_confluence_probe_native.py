"""Probe 2: Confluence-native storage format (macros, layouts, cell colours,
styled SVG). Publishes raw storage XHTML, bypassing pv's HTML converter, sets
the page to full width, and saves Confluence's rendered view HTML.

    python spike/build_confluence_probe_native.py SPACE_KEY out/probe2.view.html

Results are recorded in Project.md §0 "Still open"."""
import sys
from product_view.publish.confluence import Client, load_dotenv
from product_view.publish.storage import Attachment

TITLE = "PV probe 2: native macros"

SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="640" height="200" viewBox="0 0 640 200" font-family="Segoe UI, Helvetica, Arial, sans-serif">
<rect width="640" height="200" rx="10" fill="#ffffff" stroke="#e3e4e1"/>
<text x="20" y="32" font-size="15" font-weight="600" fill="#16191d">2FA verification, reviews per month</text>
<text x="20" y="52" font-size="12" fill="#596069">Jan 2025 to Sep 2026 · last 3 months highlighted</text>
<g transform="translate(20,175)">
""" + "".join(
    f'<rect x="{i*29}" y="{-v*3.5:.0f}" width="22" height="{v*3.5:.0f}" rx="2" fill="{"#b43c0a" if i >= 18 else "#a3a8ae"}"><title>{v}</title></rect>'
    for i, v in enumerate([15,5,10,5,11,13,23,11,5,2,5,6,1,7,9,6,8,5,12,29,11])
) + """
<text x="600" y="-108" font-size="12" font-weight="600" fill="#b43c0a" text-anchor="end">29: ties record</text>
</g></svg>"""

def macro(name, params=None, body=None, plain=None):
    p = "".join(f'<ac:parameter ac:name="{k}">{v}</ac:parameter>' for k, v in (params or {}).items())
    b = f"<ac:rich-text-body>{body}</ac:rich-text-body>" if body is not None else ""
    pb = f"<ac:plain-text-body><![CDATA[{plain}]]></ac:plain-text-body>" if plain is not None else ""
    return f'<ac:structured-macro ac:name="{name}">{p}{b}{pb}</ac:structured-macro>'

def status(title, colour):
    return macro("status", {"colour": colour, "title": title})

kpi = lambda big, small: f'<h1>{big}</h1><p><span style="color: rgb(89,96,105);">{small}</span></p>'

body = f"""
<ac:layout>
<ac:layout-section ac:type="single"><ac:layout-cell>
<p>P1 table of contents:</p>{macro("toc", {"maxLevel": "2"})}
<h2>P2 three-column layout with KPI tiles</h2>
</ac:layout-cell></ac:layout-section>
<ac:layout-section ac:type="three_equal">
<ac:layout-cell>{macro("panel", {"bgColor": "#F4F5F7", "borderColor": "#DFE1E6"}, kpi("13,030", "negative reviews analysed"))}</ac:layout-cell>
<ac:layout-cell>{macro("panel", {"bgColor": "#FFF4ED", "borderColor": "#FFD5BF"}, kpi("2.0×", "2FA verification pace vs last year"))}</ac:layout-cell>
<ac:layout-cell>{macro("panel", {"bgColor": "#F4F5F7"}, kpi("1,208", "say they are switching banks"))}</ac:layout-cell>
</ac:layout-section>
<ac:layout-section ac:type="two_right_sidebar">
<ac:layout-cell>
<h2>P3 styled SVG attachment, full cell width</h2>
<p><ac:image ac:width="640"><ri:attachment ri:filename="p2chart.svg" /></ac:image></p>
</ac:layout-cell>
<ac:layout-cell>
<h2>P4 status lozenges</h2>
<p>{status("Rising", "Red")} {status("New", "Blue")} {status("Steady", "Grey")} {status("Fading", "Green")} {status("Watch", "Yellow")} {status("Release 4.66", "Purple")}</p>
<h2>P5 info panels</h2>
{macro("info", body="<p>Info panel</p>")}{macro("note", body="<p>Note panel</p>")}{macro("warning", body="<p>Warning panel</p>")}{macro("tip", body="<p>Tip panel</p>")}
</ac:layout-cell>
</ac:layout-section>
<ac:layout-section ac:type="single"><ac:layout-cell>
<h2>P6 table with cell colours, column widths, wide layout</h2>
<table data-layout="full-width"><colgroup><col style="width: 40px;" /><col style="width: 320px;" /><col style="width: 90px;" /><col style="width: 90px;" /><col style="width: 120px;" /></colgroup>
<tbody>
<tr><th>#</th><th>Issue</th><th>Reviews</th><th>1★</th><th>Pace</th></tr>
<tr><td>1</td><td><strong>Support can’t resolve problems</strong><br /><em>“Customer service is of no help either”</em></td><td>795</td><td data-highlight-colour="#ffebe6">80%</td><td>{status("×0.9", "Grey")}</td></tr>
<tr><td>2</td><td><strong>2FA &amp; trusted-device verification</strong><br /><em>“Says it sends verification”</em></td><td>605</td><td data-highlight-colour="#fff0b3">67%</td><td data-highlight-colour="#ffebe6">{status("×2.0 ↑", "Red")}</td></tr>
</tbody></table>
<h2>P7 text colour and highlight</h2>
<p><span style="color: rgb(180,60,10);">Orange text</span> · <span style="background-color: rgb(255,240,179);">highlight via style</span> · <span data-highlight-colour="#fff0b3">highlight via data attr</span></p>
<h2>P8 excerpt (named) for reuse</h2>
{macro("excerpt", {"name": "kpis", "hidden": "false"}, "<p>This sentence is an excerpt named kpis.</p>")}
<h2>P9 anchor macro + anchor link</h2>
<p><ac:link ac:anchor="p2target"><ac:plain-text-link-body><![CDATA[Jump to target]]></ac:plain-text-link-body></ac:link></p>
<h2>P10 link to another page by title</h2>
<p><ac:link><ri:page ri:content-title="Product View: com.rbc.mobile.android" /><ac:plain-text-link-body><![CDATA[Open the preview page]]></ac:plain-text-link-body></ac:link></p>
<h2>P11 expand containing a table</h2>
{macro("expand", {"title": "Show 5 supporting quotes"}, "<table><tbody><tr><th>★</th><th>Quote</th></tr><tr><td>1</td><td>double authentication mandatory</td></tr></tbody></table>")}
<h2>P12 chart macro</h2>
{macro("chart", {"type": "line", "title": "Monthly reviews", "width": "600", "height": "250", "dataOrientation": "vertical"}, "<table><tbody><tr><th>Month</th><th>2FA</th><th>E-transfer</th></tr><tr><td>Jul</td><td>12</td><td>11</td></tr><tr><td>Aug</td><td>29</td><td>13</td></tr><tr><td>Sep</td><td>11</td><td>6</td></tr></tbody></table>")}
<h2>P13 date, emoticon, code macro</h2>
<p><time datetime="2026-09-29" /> <ac:emoticon ac:name="warning" /> <ac:emoticon ac:name="tick" /></p>
{macro("code", {"language": "yaml", "title": "run parameters"}, plain="strategy: leiden\nmin_cluster_size: 25")}
<h2>P14 page properties (details) macro</h2>
{macro("details", body="<table><tbody><tr><th>Run</th><td>2026-09-29</td></tr><tr><th>App version</th><td>4.67</td></tr></tbody></table>")}
<h2>P15 progress-bar-like table via cell colour</h2>
<p>{macro("anchor", {"": "p2target"})}Anchor target</p>
</ac:layout-cell></ac:layout-section>
</ac:layout>
"""

load_dotenv()
c = Client.from_env()
page, created = c.upsert_page(sys.argv[1], TITLE, body)
print("created" if created else "updated", c.page_url(page))
print(c.sync_attachments(page["id"], [Attachment("p2chart.svg", SVG.encode(), "image/svg+xml")]))
# full-width page appearance (content property used by the editor)
for key in ("content-appearance-published", "content-appearance-draft"):
    try:
        c._request("POST", f"/rest/api/content/{page['id']}/property", json_body={"key": key, "value": "full-width"})
        print("set", key)
    except Exception as e:
        print("property", key, str(e)[:160])
v = c._request("GET", f"/api/v2/pages/{page['id']}", params={"body-format": "view"})
open(sys.argv[2], "w", encoding="utf-8").write(v["body"]["view"]["value"])
