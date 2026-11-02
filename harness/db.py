"""SQLite store. Rebuilt from seed on first boot (and on Render, every deploy), so the demo is
always clean. In production this is the trace/log store; the CRM stays the system of record.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from . import sample_data as D
from .outbound import evaluate_batch
from .pipeline import run_pipeline
from .synth import generate

DB_PATH = Path(os.environ.get("HARNESS_DB", Path(__file__).resolve().parent.parent / "harness.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
  id TEXT PRIMARY KEY, received_order INTEGER, name TEXT, company TEXT, source TEXT,
  tier TEXT, fit INTEGER, intent INTEGER, owner TEXT, sla_state TEXT, data TEXT
);
CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT, lead_id TEXT, rep TEXT, verdict TEXT, reason TEXT,
  score_version TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS agent_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, trace TEXT, agent TEXT, action TEXT,
  model_prompt TEXT, result TEXT, cost REAL, latency_s REAL
);
CREATE TABLE IF NOT EXISTS synth (id TEXT PRIMARY KEY, data TEXT);
CREATE TABLE IF NOT EXISTS outbound (id TEXT PRIMARY KEY, result TEXT, data TEXT);
"""

# When the rep first touched each sample lead (minutes after routing). Missing = not yet.
REP_TOUCH = {"L-1002": 3, "L-1005": 4, "L-1007": 9, "L-1012": 22}


def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init(force=False):
    if force and DB_PATH.exists():
        DB_PATH.unlink()
    fresh = not DB_PATH.exists()
    con = connect()
    con.executescript(SCHEMA)
    if fresh:
        seed(con)
    con.commit()
    con.close()


def _ts(minutes_ago):
    return (datetime.fromisoformat(D.DEMO_NOW) - timedelta(minutes=minutes_ago)).strftime("%H:%M:%S")


def insert_lead(con, r, order):
    res = r["result"] or {}
    con.execute("INSERT OR REPLACE INTO leads VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (r["id"], order, r["contact"].get("name"), (r["company"] or {}).get("name") or r["domain"],
                 r["form"].get("form_type"), res.get("tier", "Blocked"), res.get("fit"), res.get("intent"),
                 r["owner"], (r["sla"] or {}).get("state"), json.dumps(r, default=str)))


def log(con, ts, trace, agent, action, model, result, cost, latency):
    con.execute("INSERT INTO agent_log (ts,trace,agent,action,model_prompt,result,cost,latency_s) "
                "VALUES (?,?,?,?,?,?,?,?)", (ts, trace, agent, action, model, result, cost, latency))


def seed(con):
    for n, f in enumerate(D.SAMPLE_FORMS):
        r = run_pipeline(f, rr_index=n, rep_touch_min=REP_TOUCH.get(f["id"]), minutes_ago=f["minutes_ago"],
                         ai_note=D.AI_SUMMARIES.get(f["id"]))
        insert_lead(con, r, n)
        ts = _ts(f["minutes_ago"])
        tr = "tr_" + f["id"][-4:]
        for s in r["steps"]:
            if s["name"] == "Enrichment waterfall" and s["status"] != "SKIPPED":
                log(con, ts, tr, "Enrichment", s["detail"], "rules · waterfall v1.4", s["status"], s["cost"],
                    round(s["at_ms"] / 1000, 1))
            if s["name"].startswith("Write the"):
                log(con, ts, tr, "Score note", s["detail"], "claude-haiku · score_reasons v4", s["status"], 0.002, 1.3)
            if s["name"] == "Route":
                log(con, ts, tr, "Router", s["detail"], "rules · routing v1.2", s["status"], 0.0, 0.2)
            if s["name"] == "Junk filter" and s["status"] != "PASSED":
                log(con, ts, tr, "Junk filter", s["detail"], "rules · junk v1.0", s["status"], 0.0, 0.3)
            if s["name"] == "SLA check":
                log(con, _ts(f["minutes_ago"] - 15), tr, "SLA monitor", s["detail"], "rules · sla v1.0",
                    "ESCALATED", 0.0, 0.0)
    for e in evaluate_batch():
        con.execute("INSERT INTO outbound VALUES (?,?,?)", (e["id"], e["result"], json.dumps(e, default=str)))
        log(con, _ts(150), "tr_" + e["id"], "Outbound eval", f"{e['account']['company']['name']}: "
            + ("; ".join(d for c in e["checks"].values() if not c["ok"] for d in c["detail"]) or "all checks passed"),
            "rules + claude-sonnet · grounding_judge v3", e["result"], 0.006, 3.2)
    for row in generate():
        con.execute("INSERT INTO synth VALUES (?,?)", (row["id"], json.dumps(row)))
    fb = [("L-1003", "Priya Shah", "right", "Hiring signal was real, booked a discovery call", "1.3", 300),
          ("L-1005", "Sam Rivera", "right", "", "1.3", 20),
          ("L-1007", "Sam Rivera", "wrong", "Already in a competitor contract until 2028", "1.3", 45),
          ("S-0031", "Jordan Ellis", "wrong", "Content download only, not a buyer", "1.2", 9000),
          ("S-0057", "Jordan Ellis", "wrong", "Content download only, not a buyer", "1.2", 8800),
          ("S-0102", "Sam Rivera", "wrong", "Content download only, not a buyer", "1.2", 8600)]
    for lead, rep, v, why, ver, ago in fb:
        con.execute("INSERT INTO feedback (lead_id,rep,verdict,reason,score_version,created_at) VALUES (?,?,?,?,?,?)",
                    (lead, rep, v, why, ver, _ts(ago)))
