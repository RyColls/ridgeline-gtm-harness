"""Ridgeline GTM Harness: design, prototype and client note in one app.

Run locally:  pip install -r requirements.txt && python app.py   ->  http://localhost:5000
"""
from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

from harness import db
from harness import sample_data as D
from harness.grounding import check_summary
from harness.outbound import render_body
from harness.pipeline import run_pipeline
from harness.scoring import available_versions, diff, load_config, score
from harness.synth import summary

app = Flask(__name__)
db.init()


@app.template_filter("pct")
def pct(v):
    return f"{v:.0%}" if v is not None else "—"


@app.template_filter("highlight")
def highlight(text, claim):
    from markupsafe import Markup, escape
    safe = str(escape(render_body(text or "")))
    if claim:
        c = str(escape(claim))
        safe = safe.replace(c, f'<mark class="bad">{c}</mark>')
    return Markup(safe)


@app.template_filter("clean")
def clean(v):
    return render_body(v or "")


def lead_rows():
    con = db.connect()
    rows = [dict(r) | {"data": json.loads(r["data"])} for r in
            con.execute("SELECT * FROM leads ORDER BY received_order")]
    con.close()
    return rows


def get_lead(lead_id):
    con = db.connect()
    r = con.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    fb = [dict(x) for x in con.execute("SELECT * FROM feedback WHERE lead_id=? ORDER BY id DESC", (lead_id,))]
    con.close()
    if not r:
        abort(404)
    return json.loads(r["data"]), fb


def synth_rows():
    con = db.connect()
    rows = [json.loads(r["data"]) for r in con.execute("SELECT data FROM synth")]
    con.close()
    return rows


@app.context_processor
def globals_():
    return {"nav": request.endpoint, "demo_now": datetime.fromisoformat(D.DEMO_NOW)}


# ---------------------------------------------------------------- pages
@app.route("/")
def command():
    s = summary(synth_rows())
    leads = lead_rows()
    con = db.connect()
    log = [dict(r) for r in con.execute("SELECT * FROM agent_log ORDER BY ts DESC LIMIT 8")]
    ob = Counter(r["result"] for r in con.execute("SELECT result FROM outbound"))
    con.close()
    breach = next((l for l in leads if l["sla_state"] == "BREACHED" and l["tier"] == "A"), None)
    return render_template("command.html", s=s, leads=leads, log=log, ob=ob, breach=breach)


@app.route("/start")
def start():
    return render_template("start.html", s=summary(synth_rows()))


@app.route("/design")
def design():
    s = summary(synth_rows())
    return render_template("design.html", s=s, cfg=load_config("1.3"))


@app.route("/scoring")
def scoring():
    leads = lead_rows()
    for l in leads:
        if l["data"].get("record"):
            d = diff(l["data"]["record"])
            l["old"] = d["old"]
    con = db.connect()
    fb = [dict(r) for r in con.execute("SELECT * FROM feedback ORDER BY id DESC")]
    con.close()
    s = summary(synth_rows())
    return render_template("scoring.html", leads=leads, fb=fb, s=s, cfg=load_config("1.3"))


@app.route("/lead/<lead_id>")
def lead(lead_id):
    r, fb = get_lead(lead_id)
    d = diff(r["record"]) if r.get("record") else None
    return render_template("lead.html", r=r, fb=fb, d=d, prompt=D.AI_PROMPT)


@app.route("/trace")
def trace_default():
    return redirect(url_for("lead", lead_id="L-1001"))


@app.route("/lead/new", methods=["GET", "POST"])
def lead_new():
    if request.method == "GET":
        return render_template("new.html", domains=sorted(D.COMPANIES), forms=D.SAMPLE_FORMS)
    f = request.form
    con = db.connect()
    n = con.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
    lead_id = f"L-{1001 + n}"
    while con.execute("SELECT 1 FROM leads WHERE id=?", (lead_id,)).fetchone():
        n += 1
        lead_id = f"L-{1001 + n}"
    email = (f.get("email") or "").strip().lower()
    form = {"id": lead_id, "first": f.get("first", "").strip(), "last": f.get("last", "").strip(),
            "email": email, "title": f.get("title", "").strip(), "form_type": f.get("form_type", "demo"),
            "asset": f.get("asset") or None}
    note = (f.get("ai_note") or "").strip() or None
    r = run_pipeline(form, rr_index=n, minutes_ago=0, ai_note=note)
    db.insert_lead(con, r, 100 + n)
    ts = datetime.fromisoformat(D.DEMO_NOW).strftime("%H:%M:%S")
    tier = (r["result"] or {}).get("tier", "Blocked")
    db.log(con, ts, "tr_" + lead_id[-4:], "Router", f"Live form fill from {email}: tier {tier}, owner {r['owner']}",
           "rules · routing v1.2", tier, r["cost"], round(r["total_ms"] / 1000, 1))
    con.commit()
    con.close()
    return redirect(url_for("lead", lead_id=lead_id))


@app.route("/feedback/<lead_id>", methods=["POST"])
def feedback(lead_id):
    r, _ = get_lead(lead_id)
    con = db.connect()
    con.execute("INSERT INTO feedback (lead_id,rep,verdict,reason,score_version,created_at) VALUES (?,?,?,?,?,?)",
                (lead_id, request.form.get("rep") or r.get("owner") or "Rep", request.form["verdict"],
                 request.form.get("reason", ""), (r.get("result") or {}).get("version", "1.3"),
                 datetime.fromisoformat(D.DEMO_NOW).strftime("%H:%M:%S")))
    con.commit()
    con.close()
    return redirect(url_for("lead", lead_id=lead_id) + "#feedback")


@app.route("/config")
def config():
    versions = [load_config(v) for v in available_versions()]
    return render_template("config.html", versions=versions)


@app.route("/outbound")
@app.route("/outbound/<draft_id>")
def outbound(draft_id=None):
    con = db.connect()
    rows = [json.loads(r["data"]) for r in con.execute("SELECT data FROM outbound ORDER BY id")]
    con.close()
    sel = next((x for x in rows if x["id"] == draft_id), None) or next(
        (x for x in rows if x["result"] == "BLOCKED"), rows[0])
    counts = Counter(x["result"] for x in rows)
    return render_template("outbound.html", rows=rows, sel=sel, counts=counts)


@app.route("/log")
def agent_log():
    agent = request.args.get("agent")
    con = db.connect()
    q = "SELECT * FROM agent_log" + (" WHERE agent=?" if agent else "") + " ORDER BY ts DESC, id DESC"
    rows = [dict(r) for r in con.execute(q, (agent,) if agent else ())]
    agents = [r[0] for r in con.execute("SELECT DISTINCT agent FROM agent_log ORDER BY agent")]
    con.close()
    return render_template("log.html", rows=rows, agents=agents, agent=agent)


@app.route("/note")
def note():
    return render_template("note.html", s=summary(synth_rows()))


@app.route("/reset", methods=["POST"])
def reset():
    db.init(force=True)
    return redirect(request.referrer or url_for("command"))


# ---------------------------------------------------------------- API
@app.route("/api/score", methods=["POST"])
def api_score():
    """POST a record (contact/company/signals) and get the score with reasons. ?version=1.2 to compare."""
    rec = request.get_json(force=True)
    return jsonify(score(rec, load_config(request.args.get("version", "1.3"))))


@app.route("/api/check", methods=["POST"])
def api_check():
    body = request.get_json(force=True)
    return jsonify(check_summary(body["note"], body["record"]))


@app.route("/api/leads/<lead_id>")
def api_lead(lead_id):
    r, fb = get_lead(lead_id)
    return jsonify(r | {"feedback": fb})


@app.route("/healthz")
def healthz():
    return {"ok": True}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
