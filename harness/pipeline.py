"""The inbound spine: one form fill (or one pricing-page signal) in, one routed CRM record out.

Each step returns a trace row: what went in, what happened, what came out,
how long it took and what it cost. Timings and costs are simulated; the logic
is real and is the same code the app runs on a new form fill.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from . import sample_data as D
from .grounding import check_summary, template_note
from .scoring import SEGMENT_LABEL, TECH_LABEL, classify_persona, score

CONFIDENT = 0.70
COST = {"cache": 0.0, "provider_a": 0.08, "provider_b": 0.15, "site_research": 0.03, "email_verify": 0.01}
LATENCY = {"cache": 40, "provider_a": 800, "provider_b": 1600, "site_research": 2400, "email_verify": 300}

# 30-day enrichment cache: domains Ridgeline already paid to enrich recently.
CACHE = {"summitfreightways.example": dict(name="Summit Freightways", segment="carrier", employees=260,
                                           country="US", state="PA", tech_stack="competitor", fleet_size=175)}


def _domain(email: str | None) -> str | None:
    return email.split("@", 1)[1].lower() if email and "@" in email else None


class Run:
    def __init__(self):
        self.t = 0
        self.cost = 0.0
        self.steps = []

    def step(self, name, status, detail, ms=0, cost=0.0, inp=None, out=None):
        self.t += ms
        self.cost += cost
        self.steps.append({"name": name, "status": status, "detail": detail, "at_ms": self.t,
                           "cost": round(cost, 2), "input": inp, "output": out})


def junk_filter(email, title, domain):
    if domain in D.COMPETITOR_DOMAINS:
        return "BLOCKED", "Competitor domain. Not routed, logged for Marketing."
    if domain in D.CUSTOMER_DOMAINS:
        return "DIVERTED", f"Existing customer ({D.CUSTOMER_DOMAINS[domain]}). Goes to the CSM, not an SDR."
    if domain in D.PERSONAL_DOMAINS or (title or "").lower() in {"student", "test", "n/a"}:
        return "NURTURE", "Personal email or student. Nurture sequence only, never an SDR."
    return "PASSED", "Work email, not a competitor, not an existing customer."


def enrich(domain):
    """Waterfall per field: cache -> provider A -> provider B -> site research. Stop at first confident hit."""
    fields = ["name", "segment", "employees", "fleet_size", "tech_stack", "country", "state"]
    company, prov = {k: None for k in fields}, {}
    tried = []
    acc = {"ms": 0, "cost": 0.0}

    def spend(k):
        acc["ms"] += LATENCY[k]
        acc["cost"] += COST[k]

    def fill(src, data, conf):
        hit = 0
        for k in fields:
            if company[k] is None and data.get(k) is not None and conf >= CONFIDENT:
                company[k] = data[k]
                prov[f"company.{k}"] = {"source": src, "confidence": conf}
                hit += 1
        return hit

    def missing():
        return [k for k in fields if company[k] is None]

    if domain in CACHE:
        n = fill("Cache (30-day)", CACHE[domain], 0.95)
        tried.append(f"cache hit ({n} fields)")
    else:
        tried.append("cache miss")
    spend("cache")
    if missing() and domain:
        a = D.PROVIDER_A.get(domain)
        spend("provider_a")
        n = fill("Provider A", a or {}, D.PROVIDER_A_CONF)
        tried.append(f"Provider A {'hit, ' + str(n) + ' fields' if n else 'miss'}")
    if [k for k in missing() if k != "fleet_size"] and domain:
        b = D.PROVIDER_B.get(domain)
        spend("provider_b")
        n = fill("Provider B", b or {}, D.PROVIDER_B_CONF)
        tried.append(f"Provider B {'hit, ' + str(n) + ' fields' if n else 'miss'}")
    if company["fleet_size"] is None and domain:
        spend("site_research")
        f = D.SITE_RESEARCH.get(domain)
        if f:
            company["fleet_size"] = f
            prov["company.fleet_size"] = {"source": "Site research agent", "confidence": D.SITE_RESEARCH_CONF}
            tried.append(f"site research found {f} power units")
        else:
            tried.append("site research found no fleet count")
    got = len([k for k in fields if company[k] is not None])
    return company, prov, tried, got, len(fields), acc["ms"], round(acc["cost"], 2)


def route(result, company, contact, domain, rr_index):
    """Rules, first match wins. Returns (owner, rule, action)."""
    tier = result["tier"]
    if tier == "DQ":
        return None, "Rule 0: disqualified", "No owner. Logged, excluded from SDR queues."
    if domain in D.TARGET_ACCOUNTS and tier in ("A", "B"):
        o = D.TARGET_ACCOUNTS[domain]
        return o, "Rule 1: named target account, existing owner", f"Assign to {o}, Slack DM with reasons."
    if tier in ("A", "B"):
        state = company.get("state")
        for r in D.REPS:
            if r["role"] == "SDR" and state in r["states"]:
                return r["name"], f"Rule 2: territory ({state})", f"Assign to {r['name']}, Slack DM with reasons."
        sdrs = [r["name"] for r in D.REPS if r["role"] == "SDR"]
        o = sdrs[rr_index % len(sdrs)]
        return o, "Rule 3: round robin (no territory match)", f"Assign to {o}."
    if tier == "C":
        return "Marketing nurture", "Rule 4: Tier C", "Nurture sequence. Re-scored nightly; promoted if it crosses B."
    return "Marketing nurture", "Rule 5: Nurture", "Newsletter only."


def run_pipeline(form: dict, rr_index: int = 0, rep_touch_min: float | None = None,
                 minutes_ago: float = 0.0, ai_note: str | None = None) -> dict:
    run = Run()
    email = form.get("email")
    domain = _domain(email) or form.get("company_domain")
    key = hashlib.sha1(f"{form.get('id')}|{email or domain}".encode()).hexdigest()[:10]
    is_signal = form.get("form_type") == "pricing_signal"

    run.step("Webhook received" if not is_signal else "Signal received", "DONE",
             (f"Idempotency key {key}. No duplicate submission in the last 24 hours." if not is_signal else
              f"Target account {domain} hit /pricing {D.SIGNALS.get(domain, {}).get('pricing_visits_7d', 0)}x this week "
              "(reverse-IP, web analytics). Hybrid play: treat it like a hand-raise."),
             ms=100, inp={"form_type": form.get("form_type"), "email": email, "domain": domain})

    # --- junk filter
    status, why = junk_filter(email, form.get("title"), domain)
    run.step("Junk filter", status, why, ms=300)
    contact = {"name": f"{form.get('first', '')} {form.get('last', '')}".strip(), "title": form.get("title"),
               "email": email, "persona": classify_persona(form.get("title"))}
    if status in ("BLOCKED",):
        return _finish(run, form, contact, {}, {}, None, None, None, None, minutes_ago, domain, status)

    # --- persona lookup for signal-only (no person yet)
    prov = {}
    if is_signal:
        contact["email"] = f"d.ortiz@{domain}"
        run.step("Find the buyer", "FOUND", "No form, so look up the most likely buyer at the account: "
                 "Provider B contact search for Ops / Dispatch leaders. Email verified.",
                 ms=LATENCY["provider_b"] + LATENCY["email_verify"], cost=COST["provider_b"] + COST["email_verify"])
        prov["contact.email"] = {"source": "Provider B + verify", "confidence": 0.91}
    elif email and status == "PASSED":
        run.step("Verify email", "VALID", "Work email verified (mock verifier).",
                 ms=LATENCY["email_verify"], cost=COST["email_verify"])
        prov["contact.email"] = {"source": "Form + verify", "confidence": 0.97}

    # --- enrichment (skip paid lookups for personal email: nothing to find, money wasted)
    if status == "NURTURE" and (domain in D.PERSONAL_DOMAINS):
        company = {"name": None, "segment": None, "employees": None, "fleet_size": None, "tech_stack": None,
                   "country": None, "state": None}
        run.step("Enrichment waterfall", "SKIPPED", "Personal domain: nothing to enrich, $0 spent.", ms=0)
    else:
        company, p2, tried, got, total, ms, spent = enrich(domain)
        prov.update(p2)
        run.step("Enrichment waterfall", f"{got} OF {total} FIELDS", (lambda x: x[:1].upper() + x[1:])("; ".join(tried)) +
                 f". Cost ${spent:.2f}.", ms=ms, cost=spent)

    sig = dict(D.SIGNALS.get(domain, {}))
    sig["form_type"] = "demo" if form.get("form_type") == "demo" else (
        "content" if form.get("form_type") == "content" else None)
    sig["form_age_days"] = minutes_ago / 1440
    if form.get("asset"):
        sig["asset"] = form["asset"]
    company["is_target"] = domain in D.TARGET_ACCOUNTS
    record = {"contact": contact, "company": company, "signals": sig}

    # --- score
    result = score(record)
    if status == "NURTURE":
        result = dict(result, tier="Nurture", tier_rule="Junk filter: nurture only", sla_minutes=None)
    elif status == "DIVERTED":
        result = dict(result, tier="Customer", tier_rule="Existing customer", sla_minutes=None)
    run.step("Score", f"TIER {result['tier'].upper()}",
             f"Rules engine v{result['version']}: fit {result['fit']}, intent {result['intent']}. "
             f"Tier rule: {result['tier_rule']}." + (f" Flags: {', '.join(result['flags'])}." if result['flags'] else ""),
             ms=180)

    # --- dedupe
    existing = next((c for c in D.CRM_CONTACTS if email and c["email"] == email), None)
    acct = company.get("name") or domain
    if existing:
        dd = (f"Matched contact {existing['id']} by email ({existing['source']}). Merged into one record; "
              f"newest form wins for intent fields, enriched fields win for firmographics.")
        dstat = "1 MERGE"
    else:
        dd = f"No existing contact. Matched to account {acct} by domain." if domain else "No domain to match."
        dstat = "NEW"
    run.step("Dedupe and account match", dstat, dd, ms=120)

    # --- route
    if status == "DIVERTED":
        owner, rule, action = "Leo Martins", "Rule 0b: existing customer", "Assign to CSM. Not an SDR lead."
    else:
        owner, rule, action = route(result, company, contact, domain, rr_index)
    run.step("Route", "ASSIGNED" if owner else "NO OWNER", f"{rule}. {action}", ms=150)

    # --- AI note + check
    note = None
    if ai_note:
        chk = check_summary(ai_note, record)
        note = {"text": ai_note, "check": chk,
                "shown": ai_note if chk["status"] == "pass" else template_note(result)}
        run.step("Write the 'why' note (LLM)", "PASSED CHECK" if chk["status"] == "pass" else "BLOCKED",
                 "LLM writes 2-3 sentences citing fields; grounding check verified every claim." if chk["status"] == "pass"
                 else "Grounding check failed: " + "; ".join(p for s in chk["sentences"] for p in s["problems"]) +
                      ". Rep sees the template reasons instead.", ms=1300)
    elif result["tier"] in ("A", "B"):
        note = {"text": None, "check": None, "shown": template_note(result)}

    run.step("CRM writeback and rep alert", "DONE",
             "Contact, account, score, reasons, sources and owner written to the CRM (system of record). " +
             (f"Slack DM to {owner} with the reasons and a link to this trace." if result["tier"] in ("A", "B") else
              "No rep alert."), ms=400)

    return _finish(run, form, contact, company, prov, result, owner, rule, note, minutes_ago, domain, status,
                   rep_touch_min, record)


def _finish(run, form, contact, company, prov, result, owner, rule, note, minutes_ago, domain, status,
            rep_touch_min=None, record=None):
    sla = None
    if result and result.get("sla_minutes"):
        limit = result["sla_minutes"]
        if rep_touch_min is not None and rep_touch_min <= limit:
            sla = {"state": "MET", "detail": f"Rep logged a call {rep_touch_min:g} min after routing (SLA {limit} min)."}
        elif minutes_ago > limit:
            sla = {"state": "BREACHED", "detail": f"No rep activity within {limit} min. Escalated to Dana Kim "
                                                   f"(SDR manager); {minutes_ago - limit:.0f} min overdue."}
            run.steps.append({"name": "SLA check", "status": "ESCALATED", "detail": sla["detail"],
                              "at_ms": limit * 60000, "cost": 0, "input": None, "output": None})
        else:
            left = limit - minutes_ago
            sla = {"state": "RUNNING", "detail": f"{left:.0f} of {limit} min left before escalation."}
    now = datetime.fromisoformat(D.DEMO_NOW)
    crm = []
    if result:
        for path, label in (("contact.email", "Email"), ("company.employees", "Headcount"),
                            ("company.fleet_size", "Fleet size"), ("company.segment", "Segment"),
                            ("company.tech_stack", "Tooling")):
            sec, k = path.split(".")
            val = (contact if sec == "contact" else company).get(k)
            val = SEGMENT_LABEL.get(val, TECH_LABEL.get(val, val)) if isinstance(val, str) else val
            p = prov.get(path, {})
            crm.append({"field": label, "value": val if val is not None else "unknown",
                        "source": p.get("source", "—"), "confidence": p.get("confidence")})
        crm.append({"field": "Lead tier", "value": result["tier"], "source": f"Score v{result['version']}",
                    "confidence": None})
        crm.append({"field": "Owner", "value": owner or "—", "source": "Routing v1.2", "confidence": None})
    return {
        "id": form.get("id"), "form": form, "contact": contact, "company": company, "domain": domain,
        "record": record, "provenance": prov, "result": result, "owner": owner, "route_rule": rule,
        "note": note, "steps": run.steps, "total_ms": run.t, "cost": round(run.cost, 2), "sla": sla,
        "crm": crm, "junk": status,
        "received_at": (now - timedelta(minutes=minutes_ago)).strftime("%-I:%M %p"),
    }
