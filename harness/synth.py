"""A simulated week of Ridgeline inbound (~210 form fills = 900/month), scored by the real engine
under v1.2 and v1.3. Seeded, so the numbers are the same on every boot. Rep response times and
enrichment hit rates are assumptions, stated on the dashboard.
"""
from __future__ import annotations

import random

from .scoring import load_config, score

SEGMENTS = [("3pl", 0.34), ("carrier", 0.40), ("broker", 0.14), ("shipper", 0.12)]
TECH = [("legacy_tms", 0.35), ("spreadsheets", 0.33), ("competitor", 0.17), ("modern_tms", 0.15)]
TITLES = [("Director of Dispatch", 0.14), ("VP Operations", 0.12), ("Operations Manager", 0.16), ("CEO", 0.06),
          ("Owner", 0.06), ("IT Manager", 0.08), ("Dispatcher", 0.18), ("Operations Analyst", 0.12),
          ("Marketing Coordinator", 0.08)]
SOURCES = [("demo", 0.17), ("pricing_signal", 0.06), ("content", 0.63), ("junk", 0.14)]
STATES = ["WA", "CA", "TX", "IL", "PA", "GA", "OH", "ON", "BC", "KS", "MI", "FL"]


def _pick(rng, items):
    r, acc = rng.random(), 0.0
    for v, w in items:
        acc += w
        if r <= acc:
            return v
    return items[-1][0]


def generate(n=210, seed=42):
    rng = random.Random(seed)
    v12, v13 = load_config("1.2"), load_config("1.3")
    rows = []
    for i in range(n):
        src = _pick(rng, SOURCES)
        if src == "junk":
            rows.append({"id": f"S-{i:04d}", "source": "junk", "tier12": "Junk", "tier13": "Junk"})
            continue
        emp = int(rng.lognormvariate(5.0, 1.1))
        fleet = max(1, int(emp * rng.uniform(0.2, 0.8))) if rng.random() < 0.9 else None
        known = {  # enrichment hit rates after the waterfall (assumption; baseline was 30%)
            "employees": rng.random() < 0.93, "segment": rng.random() < 0.95,
            "tech": rng.random() < 0.82, "fleet": rng.random() < 0.61,
        }
        rec = {
            "contact": {"title": _pick(rng, TITLES)},
            "company": {"segment": _pick(rng, SEGMENTS) if known["segment"] else None,
                        "employees": emp if known["employees"] else None,
                        "fleet_size": fleet if known["fleet"] else None,
                        "tech_stack": _pick(rng, TECH) if known["tech"] else None,
                        "country": "CA" if rng.random() < 0.15 else "US",
                        "is_target": rng.random() < 0.18},
            "signals": {"form_type": "demo" if src == "demo" else ("content" if src == "content" else None),
                        "form_age_days": 0, "asset": "Benchmark report" if src == "content" else None},
        }
        if src == "pricing_signal" or rng.random() < 0.12:
            rec["signals"]["pricing_visits_7d"] = rng.randint(1, 4)
            rec["signals"]["pricing_age_days"] = rng.uniform(0, 6)
        if rng.random() < 0.22:
            rec["signals"]["job_posts"] = rng.randint(1, 3)
            rec["signals"]["job_post_age_days"] = rng.uniform(1, 45)
        if rng.random() < 0.06:
            rec["signals"]["funding_age_days"] = rng.uniform(10, 300)
        a, b = score(rec, v12), score(rec, v13)
        # rep response (assumption): A alerts in Slack -> fast; B queue -> slower; reps sometimes sit on leads
        resp = None
        if b["tier"] == "A":
            resp = rng.choice([2, 3, 3, 4, 4, 5, 6, 8, 11, 14, 22])
        elif b["tier"] == "B":
            resp = rng.choice([12, 20, 26, 35, 41, 48, 55, 70, 95])
        rows.append({"id": f"S-{i:04d}", "source": src, "tier12": a["tier"], "tier13": b["tier"],
                     "fit": b["fit"], "intent": b["intent"], "resp_min": resp, "known": known,
                     "rep": rng.choice(["Priya Shah", "Jordan Ellis", "Sam Rivera"]) if resp else None,
                     "sla": b["sla_minutes"]})
    return rows


def summary(rows):
    real = [r for r in rows if r["source"] != "junk"]

    def sdr(t):
        return t in ("A", "B")
    by_src = {}
    for s in ("demo", "pricing_signal", "content"):
        rs = [r for r in real if r["source"] == s]
        by_src[s] = {"leads": len(rs), "a": sum(r["tier13"] == "A" for r in rs),
                     "b": sum(r["tier13"] == "B" for r in rs),
                     "sdr12": sum(sdr(r["tier12"]) for r in rs), "sdr13": sum(sdr(r["tier13"]) for r in rs)}
    tiers = {t: sum(r["tier13"] == t for r in real) for t in ("A", "B", "C", "Nurture", "DQ")}
    tiers12 = {t: sum(r["tier12"] == t for r in real) for t in ("A", "B", "C", "Nurture", "DQ")}
    resp = sorted(r["resp_min"] for r in real if r["tier13"] == "A" and r["resp_min"] is not None)
    median_a = resp[len(resp) // 2] if resp else None
    breaches = [r for r in real if r.get("sla") and r["resp_min"] and r["resp_min"] > r["sla"]]
    by_rep = {}
    for r in real:
        if r.get("rep"):
            d = by_rep.setdefault(r["rep"], {"assigned": 0, "breaches": 0, "resp": []})
            d["assigned"] += 1
            d["resp"].append(r["resp_min"])
            if r.get("sla") and r["resp_min"] > r["sla"]:
                d["breaches"] += 1
    for d in by_rep.values():
        d["median"] = sorted(d["resp"])[len(d["resp"]) // 2]
    cov = {k: round(100 * sum(r["known"][k] for r in real) / len(real)) for k in ("employees", "segment", "tech", "fleet")}
    return {"total": len(rows), "junk": len(rows) - len(real), "real": len(real), "by_source": by_src,
            "tiers": tiers, "tiers12": tiers12, "median_a_min": median_a, "breaches": len(breaches),
            "by_rep": by_rep, "coverage": cov,
            "sdr12": sum(sdr(r["tier12"]) for r in real), "sdr13": sum(sdr(r["tier13"]) for r in real)}
