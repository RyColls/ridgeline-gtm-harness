"""Render the whole Flask app into one self-contained HTML page (hash-routed tabs) for
hosting as a claude.ai artifact. Every number comes from a fresh run of the real pipeline.

Usage:  python tools/freeze.py OUT_DIR
Writes OUT_DIR/index.html (artifact body: no <html>/<head>/<body> wrapper).
"""
from __future__ import annotations

import html
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp())
os.environ["HARNESS_DB"] = str(TMP / "freeze.db")
sys.path.insert(0, str(ROOT))

import app as A  # noqa: E402

PRESETS = [
    ("Good fit, demo, grounded note", dict(first="Jamie", last="Cole", email="jcole@gulfcoastdrayage.example",
     title="VP Operations", form_type="demo", asset="",
     ai_note="Gulf Coast Drayage is a carrier with 140 employees [company.segment][company.employees]. They had "
             "funding news recently [signals.funding_age_days]. Jamie runs operations and asked for a demo "
             "[contact.title][signals.form_type].")),
    ("Same lead, hallucinated note", dict(first="Jamie", last="Cole", email="j.cole@gulfcoastdrayage.example",
     title="VP Operations", form_type="demo", asset="",
     ai_note="Gulf Coast Drayage just raised a $40M Series B [signals.funding_age_days]. They run 500 trucks across "
             "Texas [company.fleet_size].")),
    ("Canadian broker, content download", dict(first="Priya", last="Natarajan",
     email="pnatarajan@maplecrossfreight.example", title="Dispatch Supervisor", form_type="content",
     asset="Driver HOS guide", ai_note="")),
    ("Outside US/Canada", dict(first="Alex", last="Morgan", email="amorgan@mesaverdelogistics.example",
     title="Director of Logistics", form_type="demo", asset="", ai_note="")),
    ("Competitor", dict(first="Chris", last="Bell", email="cbell@haulwise.example", title="Growth",
     form_type="content", asset="ROI calculator", ai_note="")),
]


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def route_to_hash(path):
    path = html.unescape(path)
    if path in ("/", ""):
        return "command"
    m = re.match(r"^/lead/(L-\d+)(#.*)?$", path)
    if m:
        return f"lead-{m.group(1)}"
    if path == "/lead/new":
        return "try"
    m = re.match(r"^/outbound/(d_\d+)$", path)
    if m:
        return "outbound-" + m.group(1).replace("_", "")
    m = re.match(r"^/log\?agent=(.+)$", path)
    if m:
        from urllib.parse import unquote_plus
        return "log-" + slug(unquote_plus(m.group(1)))
    simple = {"/design": "design", "/scoring": "scoring", "/config": "config", "/outbound": "outbound",
              "/log": "log", "/note": "note", "/start": "start", "/trace": "lead-L-1001"}
    return simple.get(path)


def rewrite_links(body):
    def href(m):
        h = route_to_hash(m.group(1))
        return f'href="#{h}"' if h else m.group(0)
    body = re.sub(r'href="(/[^"]*)"', href, body)

    def onclick(m):
        h = route_to_hash(m.group(1))
        return f"onclick=\"location.hash='{h}'\"" if h else m.group(0)
    return re.sub(r"onclick=\"location='([^']*)'\"", onclick, body)


def main_of(page):
    m = re.search(r'<main class="wrap">(.*)</main>', page, re.S)
    body = m.group(1)
    return re.sub(r'<div class="foot">.*?</div>', "", body, flags=re.S)


MERMAID_CFG = {
    "theme": "base",
    "flowchart": {"curve": "basis", "htmlLabels": True, "nodeSpacing": 30, "rankSpacing": 40},
    "themeVariables": {"fontFamily": "Open Sans, Arial, sans-serif", "fontSize": "15px", "primaryColor": "#ffffff",
                       "primaryBorderColor": "#3a3a3a", "primaryTextColor": "#232323", "lineColor": "#8e3a2c",
                       "clusterBkg": "#f7f6f2", "clusterBorder": "#ccc8bd", "edgeLabelBackground": "#ffffff",
                       "tertiaryColor": "#f7f6f2"},
}


def render_mermaid(body):
    import json
    cfg = TMP / "mm.json"
    cfg.write_text(json.dumps(MERMAID_CFG))
    n = [0]

    def one(m):
        n[0] += 1
        src, out = TMP / f"d{n[0]}.mmd", TMP / f"d{n[0]}.svg"
        src.write_text(html.unescape(m.group(1)))
        subprocess.run(["mmdc", "-i", str(src), "-o", str(out), "-c", str(cfg), "-b", "white", "-q"], check=True)
        svg = out.read_text()
        svg = re.sub(r"^<\?xml[^>]*>", "", svg).strip()
        svg = svg.replace(f'id="my-svg"', f'id="diagram-{n[0]}"').replace("#my-svg", f"#diagram-{n[0]}")
        return f'<div class="diagram">{svg}</div>'
    return re.sub(r'<pre class="mermaid">(.*?)</pre>', one, body, flags=re.S)


def static_fixes(view, body):
    body = re.sub(r'<form class="inline" method="post"[^>]*>.*?</form>', "", body, flags=re.S)
    body = body.replace('<a class="btn" href="#try">Submit a test form fill</a>',
                        '<a class="btn red" href="#try">Try a scenario</a>')
    body = re.sub(r'<form method="post" action="/feedback/(L-\d+)">',
                  r'<form class="fb" data-lead="\1">', body)
    body = body.replace("Saved to SQLite.", "In the live app this saves to SQLite; here it stays in your browser.")
    body = body.replace("curl -X POST http://localhost/api/score", "curl -X POST https://&lt;harness-host&gt;/api/score")
    body = body.replace("Buttons are illustrative in this prototype; the outbox is mocked.",
                        "Buttons are illustrative; the outbox is mocked.")
    return body


def try_view(preset_ids):
    rows = "".join(
        f'<a class="scenario" href="#lead-{lid}"><b>{html.escape(label)}</b>'
        f'<span>{html.escape(f["first"])} {html.escape(f["last"])} · {html.escape(f["title"])} · '
        f'{html.escape(f["email"])}</span><span class="go">Open trace →</span></a>'
        for (label, f), lid in zip(PRESETS, preset_ids))
    return f"""
<div class="eyebrow">Prototype · live run</div>
<h1 class="page-title"><u>Try it</u>: run a scenario</h1>
<p class="lede">Each scenario below was submitted to the real pipeline: junk filter, enrichment waterfall (mocked providers),
dedupe, score v1.3, routing, CRM writeback and the grounding check on the LLM note. Open one to see its full trace.
In the hosted Python app the same form takes any input and saves the result to SQLite.</p>
<div class="scenarios">{rows}</div>
<div class="card mt"><h2>What to look for</h2>
<ul class="note" style="padding-left:18px;font-size:13px">
<li><b>Grounded vs hallucinated note:</b> same person, same score. The second note claims a $40M round and 500 trucks; neither is in the record, so the check blocks it and the rep sees template reasons.</li>
<li><b>Canadian broker:</b> Provider A misses Canadian brokers, so the waterfall falls through to Provider B, and fleet size stays unknown (scored 0, flagged).</li>
<li><b>Outside US/Canada:</b> disqualified before scoring matters; no owner.</li>
<li><b>Competitor:</b> stopped at the junk filter, $0 spent on enrichment.</li>
</ul></div>"""


def build(out_dir):
    c = A.app.test_client()
    preset_ids = []
    for _, f in PRESETS:
        r = c.post("/lead/new", data=f)
        preset_ids.append(r.location.rsplit("/", 1)[-1])

    con = A.db.connect()
    lead_ids = [r[0] for r in con.execute("SELECT id FROM leads ORDER BY received_order")]
    draft_ids = [r[0] for r in con.execute("SELECT id FROM outbound ORDER BY id")]
    agents = [r[0] for r in con.execute("SELECT DISTINCT agent FROM agent_log ORDER BY agent")]
    con.close()

    views = [("start", "/start"), ("command", "/"), ("design", "/design"), ("scoring", "/scoring"), ("config", "/config"),
             ("outbound", "/outbound"), ("log", "/log"), ("note", "/note")]
    views += [(f"lead-{i}", f"/lead/{i}") for i in lead_ids]
    views += [("outbound-" + d.replace("_", ""), f"/outbound/{d}") for d in draft_ids]
    from urllib.parse import quote_plus
    views += [("log-" + slug(a), f"/log?agent={quote_plus(a)}") for a in agents]

    sections = []
    for name, path in views:
        page = c.get(path).get_data(as_text=True)
        body = static_fixes(name, rewrite_links(main_of(page)))
        if name == "design":
            body = render_mermaid(body)
        sections.append(f'<section class="view" data-view="{name}" hidden>{body}</section>')
    sections.append(f'<section class="view" data-view="try" hidden>{try_view(preset_ids)}</section>')

    css = (ROOT / "static" / "style.css").read_text()
    shell = (ROOT / "tools" / "shell.html").read_text()
    out = shell.replace("/*CSS*/", css).replace("<!--VIEWS-->", "\n".join(sections))
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    (Path(out_dir) / "index.html").write_text(out)
    print(f"wrote {Path(out_dir) / 'index.html'}  ({len(out)//1024} KB, {len(sections)} views)")


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "dist"))
