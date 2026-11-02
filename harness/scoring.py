"""Explainable scoring engine.

Rules, not a model. Every point on a score comes from one named signal, which
points at one field in the record, so RevOps can answer "why did this change?"
by diffing two configs. Weights live in config/scoring_v*.json, versioned and
owned by RevOps; changing a weight is a config change, not a deploy.

score(record, config) -> {
    fit, intent, tier, sla_minutes, version,
    reasons: [{group, signal, field, evidence, points, status}],
    flags:   ["fleet size unknown", ...]
}
"""
from __future__ import annotations

import json
import re
from pathlib import Path

CONFIG_DIR = Path(__file__).parent / "config"

SEGMENT_LABEL = {"3pl": "3PL", "carrier": "Carrier", "broker": "Freight broker", "shipper": "Shipper (not ICP)"}
TECH_LABEL = {"legacy_tms": "Legacy TMS", "spreadsheets": "Spreadsheets + phone", "competitor": "Competitor customer",
              "modern_tms": "Modern TMS"}
PERSONA_LABEL = {"dispatch_leader": "Dispatch leader", "ops_exec": "Operations exec", "c_level": "C-level",
                 "it": "IT", "individual": "Individual contributor"}

# Title -> persona. Plain keyword rules, checked in order. Cheap and auditable.
PERSONA_RULES = [
    ("c_level", r"\b(ceo|coo|cfo|cto|president|owner|founder|chief)\b"),
    ("dispatch_leader", r"dispatch"),
    ("ops_exec", r"\b(vp|vice president|head|director|svp)\b.*\b(operations|ops|logistics|transportation|fleet)\b"),
    ("it", r"\b(it|information|systems|technology|cio)\b"),
]


def classify_persona(title: str | None) -> str | None:
    if not title:
        return None
    t = title.lower()
    for persona, pattern in PERSONA_RULES:
        if re.search(pattern, t):
            return persona
    return "individual"


def load_config(version: str = "1.3") -> dict:
    path = CONFIG_DIR / f"scoring_v{version.replace('.', '_')}.json"
    return json.loads(path.read_text())


def available_versions() -> list[str]:
    out = []
    for p in sorted(CONFIG_DIR.glob("scoring_v*.json")):
        out.append(json.loads(p.read_text())["version"])
    return out


def _get(record: dict, path: str):
    node = record
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _decay(points: float, age_days: float | None, half_life: float | None) -> float:
    if half_life is None or age_days is None:
        return points
    return points * 0.5 ** (age_days / half_life)


def _band(value, bands):
    for lo, hi, pts in bands:
        if lo <= value <= hi:
            return pts
    return 0


def _ago(days: float | None) -> str:
    if days is None:
        return ""
    if days < 1:
        return "today"
    if days < 45:
        d = round(days)
        return f"{d} day{'s' if d != 1 else ''} ago"
    m = round(days / 30)
    return f"{m} month{'s' if m != 1 else ''} ago"


def score(record: dict, config: dict | None = None) -> dict:
    cfg = config or load_config()
    reasons, flags = [], []

    def add(group, signal, field, evidence, points, status="ok"):
        reasons.append({"group": group, "signal": signal, "field": field, "evidence": evidence,
                        "points": int(round(points)), "status": status})

    # ---------------- fit ----------------
    f = cfg["fit"]
    disqualified = None

    country = _get(record, f["geo"]["field"])
    if country is not None and country not in f["geo"]["allowed"]:
        disqualified = f"Outside US/Canada ({country})"

    seg = _get(record, f["segment"]["field"])
    if seg is None:
        add("fit", f["segment"]["label"], f["segment"]["field"], "unknown", 0, "unknown")
        flags.append("segment unknown")
    else:
        add("fit", f["segment"]["label"], f["segment"]["field"], SEGMENT_LABEL.get(seg, seg),
            f["segment"]["points"].get(seg, 0))
        if seg in f["segment"].get("disqualify", []):
            disqualified = f"Not ICP: {SEGMENT_LABEL.get(seg, seg)}"

    emp = _get(record, f["employees"]["field"])
    if emp is None:
        add("fit", f["employees"]["label"], f["employees"]["field"], "unknown", 0, "unknown")
        flags.append("headcount unknown")
    else:
        add("fit", f["employees"]["label"], f["employees"]["field"], f"{emp:,} employees",
            _band(emp, f["employees"]["bands"]))

    fleet = _get(record, f["fleet"]["field"])
    if fleet is None:
        add("fit", f["fleet"]["label"], f["fleet"]["field"], "unknown", 0, "unknown")
        flags.append("fleet size unknown")
    else:
        add("fit", f["fleet"]["label"], f["fleet"]["field"], f"{fleet:,} power units", _band(fleet, f["fleet"]["bands"]))

    tech = _get(record, f["tech"]["field"])
    if tech is None:
        add("fit", f["tech"]["label"], f["tech"]["field"], "unknown", 0, "unknown")
        flags.append("tooling unknown")
    else:
        add("fit", f["tech"]["label"], f["tech"]["field"], TECH_LABEL.get(tech, tech), f["tech"]["points"].get(tech, 0))

    persona = _get(record, f["persona"]["field"]) or classify_persona(_get(record, "contact.title"))
    title = _get(record, "contact.title")
    if persona is None:
        add("fit", f["persona"]["label"], "contact.title", "unknown", 0, "unknown")
    else:
        add("fit", f["persona"]["label"], "contact.title", f"{title} ({PERSONA_LABEL.get(persona, persona)})",
            f["persona"]["points"].get(persona, 0))

    fit = min(f["cap"], sum(r["points"] for r in reasons if r["group"] == "fit"))

    # ---------------- intent ----------------
    i = cfg["intent"]
    s = record.get("signals", {})
    form = s.get("form_type")
    form_age = s.get("form_age_days")

    if form == "demo" and i.get("demo_request"):
        c = i["demo_request"]
        add("intent", c["label"], "signals.form_type", f"Demo form, {_ago(form_age)}",
            _decay(c["points"], form_age, c.get("half_life_days")))
    if form == "content" and i.get("content_download"):
        c = i["content_download"]
        asset = s.get("asset") or "content"
        add("intent", c["label"], "signals.asset", f"{asset}, {_ago(form_age)}",
            _decay(c["points"], form_age, c.get("half_life_days")))

    visits = s.get("pricing_visits_7d") or 0
    if visits and i.get("pricing_visits"):
        c = i["pricing_visits"]
        pts = min(c["max"], visits * c["points_per_visit"])
        add("intent", c["label"], "signals.pricing_visits_7d",
            f"{visits} visit{'s' if visits != 1 else ''} this week, last {_ago(s.get('pricing_age_days'))}",
            _decay(pts, s.get("pricing_age_days"), c.get("half_life_days")))

    posts = s.get("job_posts") or 0
    if posts and i.get("hiring"):
        c = i["hiring"]
        pts = min(c["max"], posts * c["points_per_post"])
        add("intent", c["label"], "signals.job_posts",
            f"{posts} open dispatcher role{'s' if posts != 1 else ''}, posted {_ago(s.get('job_post_age_days'))}",
            _decay(pts, s.get("job_post_age_days"), c.get("half_life_days")))

    fund_age = s.get("funding_age_days")
    if fund_age is not None and i.get("funding"):
        c = i["funding"]
        add("intent", c["label"], "signals.funding_age_days", f"Funding news {_ago(fund_age)}",
            _decay(c["points"], fund_age, c.get("half_life_days")))

    if _get(record, "company.is_target") and i.get("target_account"):
        c = i["target_account"]
        add("intent", c["label"], "company.is_target", "On the 1,500-account list", c["points"])

    intent = min(i["cap"], sum(r["points"] for r in reasons if r["group"] == "intent"))

    # ---------------- tier ----------------
    tier, sla, rule = "Nurture", None, "everything else"
    if disqualified:
        tier, rule = "DQ", disqualified
    else:
        for t in cfg["tiers"]:
            if fit < t.get("min_fit", 0):
                continue
            if intent < t.get("min_intent", 0):
                continue
            if t.get("requires") == "demo_request" and form != "demo":
                continue
            if f["persona"]["points"].get(persona, 0) < t.get("min_persona_points", 0):
                continue
            tier, sla, rule = t["tier"], t["sla_minutes"], t["desc"]
            break

    return {"version": cfg["version"], "fit": fit, "intent": intent, "tier": tier, "sla_minutes": sla,
            "tier_rule": rule, "reasons": reasons, "flags": flags}


def diff(record: dict, old: str = "1.2", new: str = "1.3") -> dict:
    """Explain a score change between two config versions, signal by signal."""
    a, b = score(record, load_config(old)), score(record, load_config(new))
    key = lambda r: (r["group"], r["signal"])
    av = {key(r): r["points"] for r in a["reasons"]}
    bv = {key(r): r["points"] for r in b["reasons"]}
    changes = []
    for k in list(dict.fromkeys(list(av) + list(bv))):
        if av.get(k, 0) != bv.get(k, 0):
            changes.append({"group": k[0], "signal": k[1], "old": av.get(k, 0), "new": bv.get(k, 0),
                            "delta": bv.get(k, 0) - av.get(k, 0)})
    return {"old": a, "new": b, "changes": changes}
