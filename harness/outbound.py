"""Outbound eval gate. Drafts are LLM-written (prompt first_touch v6, pasted from the free
Claude app); every check below is deterministic and runs live. Nothing reaches the outbox
without passing. Mechanical problems are auto-fixed; factual problems block for a human.
"""
from __future__ import annotations

import re

from .grounding import CITE, NUMBER, _get, _norm, _related_numbers, split_sentences

STORIES = {
    "coastline": {"customer": "Coastline Logistics", "segment": "3pl",
                  "text": "Coastline Logistics cut empty miles 12% and moved 9 dispatchers off spreadsheets in 90 days.",
                  "numbers": {"12", "9", "90"}},
    "ironwood": {"customer": "Ironwood Carriers", "segment": "carrier",
                 "text": "Ironwood Carriers reduced driver check calls 40% in the first quarter after go-live.",
                 "numbers": {"40"}},
}

BANNED = ["i hope this finds you well", "synergy", "circle back", "touch base", "revolutionize", "game-changer"]
PRICING = re.compile(r"(\$\d|pricing|per seat|per truck|discount)", re.I)
OPS_PERSONAS = {"dispatch_leader", "ops_exec", "individual"}
MAX_WORDS = 120

ACCOUNTS = {
    "harborpoint3pl.example": {"contact": {"name": "Elena Ruiz", "title": "VP Operations", "persona": "ops_exec"},
                               "company": {"name": "Harbor Point 3PL", "segment": "3pl", "state": "WA"},
                               "signals": {"job_posts": 3, "job_post_age_days": 5}, "tier": "A"},
    "prairielinecarriers.example": {"contact": {"name": "Dana Ortiz", "title": "VP Operations", "persona": "ops_exec"},
                                    "company": {"name": "Prairie Line Carriers", "segment": "carrier",
                                                "fleet_size": 220, "tech_stack": "spreadsheets"},
                                    "signals": {"pricing_visits_7d": 4}, "tier": "A"},
    "summitfreightways.example": {"contact": {"name": "Aisha Grant", "title": "Director of Dispatch",
                                              "persona": "dispatch_leader"},
                                  "company": {"name": "Summit Freightways", "segment": "carrier", "fleet_size": 175},
                                  "signals": {"pricing_visits_7d": 1}, "tier": "B"},
    "redwoodhaul.example": {"contact": {"name": "Carlos Mendez", "title": "Dispatch Manager",
                                        "persona": "dispatch_leader"},
                            "company": {"name": "Redwood Haul Co", "segment": "carrier", "employees": 420},
                            "signals": {"job_posts": 1, "job_post_age_days": 20}, "tier": "A"},
    "gulfcoastdrayage.example": {"contact": {"name": "Ben Ford", "title": "COO", "persona": "c_level"},
                                 "company": {"name": "Gulf Coast Drayage", "segment": "carrier", "fleet_size": 110},
                                 "signals": {"funding_age_days": 40}, "tier": "B"},
}

DRAFTS = [
    {"id": "d_701", "domain": "harborpoint3pl.example", "subject": "Your new dispatch roles",
     "body": "Hi Elena,\n\nSaw Harbor Point is hiring 3 dispatchers in the last week [signals.job_posts]. That usually "
             "means the load board is outgrowing the team.\n\nCoastline Logistics was in the same spot [story:coastline]. After moving "
             "dispatch onto Ridgeline they cut dispatch time 35% [story:coastline].\n\nWorth 20 minutes to compare notes?"
             "\n\nSam", "judge": {"claim": "cut dispatch time 35%", "verdict": "unsupported", "confidence": 0.94}},
    {"id": "d_702", "domain": "prairielinecarriers.example", "subject": "220 trucks on spreadsheets",
     "body": "Hi Dana,\n\nRunning 220 power units off spreadsheets and phone calls is a lot of tabs "
             "[company.fleet_size][company.tech_stack]. Ironwood Carriers had the same setup and reduced driver "
             "check calls 40% in their first quarter [story:ironwood].\n\nOpen to a short look at how they did it?"
             "\n\nJordan", "judge": {"claim": None, "verdict": "supported", "confidence": 0.91}},
    {"id": "d_703", "domain": "summitfreightways.example", "subject": "Dispatch at Summit",
     "body": "Hi {{first_name}},\n\nYou run 175 power units [company.fleet_size], which is right where most carriers "
             "start to feel their dispatch tool fight them. Coastline Logistics moved 9 dispatchers off spreadsheets "
             "in 90 days [story:coastline].\n\nWould a side-by-side be useful?\n\nSam",
     "judge": {"claim": None, "verdict": "supported", "confidence": 0.89}},
    {"id": "d_704", "domain": "redwoodhaul.example", "subject": "Dispatch hiring at Redwood",
     "body": "Hi Carlos,\n\nNoticed Redwood Haul has an open dispatch role [signals.job_posts]. Ironwood Carriers "
             "reduced driver check calls 40% after go-live, which bought their team back hours a week "
             "[story:ironwood]. Pricing starts at $45 per truck per month.\n\nWorth a quick compare?\n\nPriya",
     "judge": {"claim": None, "verdict": "supported", "confidence": 0.90}},
    {"id": "d_705", "domain": "gulfcoastdrayage.example", "subject": "Congrats on the Houston terminal",
     "body": "Hi Ben,\n\nCongrats on opening the new Houston terminal. With 110 power units [company.fleet_size] and "
             "fresh funding [signals.funding_age_days], this is usually when dispatch gets rebuilt.\n\nOpen to "
             "comparing notes?\n\nJordan", "judge": {"claim": "new Houston terminal", "verdict": "unsupported",
                                                    "confidence": 0.88}},
]

STORY_CITE = re.compile(r"\[story:([a-z]+)\]")


def _body_sentences(body):
    lines = [l.strip() for l in body.split("\n") if l.strip()]
    content = lines[1:-1]  # drop greeting and sign-off
    out = []
    for l in content:
        out.extend(split_sentences(l))
    return out


def _clean(text):
    return re.sub(r"[ \t]+([.,!?])", r"\1", STORY_CITE.sub("", CITE.sub("", text)))


def evaluate(draft: dict, batch: list[dict]) -> dict:
    acct = ACCOUNTS[draft["domain"]]
    body = draft["body"]
    checks = {}

    # 1 grounding: every factual sentence about the prospect cites a record field that exists
    g_problems = []
    for s in _body_sentences(body):
        if s.endswith("?") or PRICING.search(s):
            continue  # the ask, or pricing (persona check owns that)
        cites, stories = CITE.findall(s), STORY_CITE.findall(s)
        if not cites and not stories and not re.match(r"^(That|This|Which)\b", s):
            g_problems.append(f"Uncited claim: “{_clean(s).strip()}”")
        for c in cites:
            st, v = _get(acct, c)
            if st == "missing" or v is None:
                g_problems.append(f"{c} is not in the account record")
    checks["grounding"] = {"ok": not g_problems, "detail": g_problems or ["Every claim about the prospect cites a "
                                                                          "signal in the record."]}

    # 2 no invented facts: numbers must appear in the cited field or the cited customer story
    n_problems = []
    for s in _body_sentences(body):
        allowed = set()
        for c in CITE.findall(s):
            allowed |= _related_numbers(acct, c)
        for sid in STORY_CITE.findall(s):
            allowed |= STORIES.get(sid, {}).get("numbers", set())
        for n in NUMBER.findall(_clean(s).replace("%", " ")):
            if _norm(n) not in allowed and not PRICING.search(s) and not s.endswith("?"):
                src = (" / ".join(f"the {x} customer story" for x in STORY_CITE.findall(s))
                       or ", ".join(CITE.findall(s)) or "anything cited")
                n_problems.append(f"The number {n} is not in {src}")
    if draft.get("judge", {}).get("verdict") == "unsupported" and not n_problems:
        n_problems.append(f"LLM judge: “{draft['judge']['claim']}” unsupported "
                          f"(confidence {draft['judge']['confidence']})")
    checks["no_invented_facts"] = {"ok": not n_problems, "detail": n_problems or [
        "Every number traces to a field or a customer story."]}

    # 3 persona fit: ops personas get ops pain, never pricing in a first touch
    persona = acct["contact"]["persona"]
    p_problems = []
    if persona in OPS_PERSONAS and PRICING.search(body):
        p_problems.append(f"Pricing talk to an ops persona ({acct['contact']['title']}). Auto-fix: remove the sentence.")
    checks["persona_fit"] = {"ok": not p_problems, "fixable": bool(p_problems),
                             "detail": p_problems or [f"{acct['contact']['title']}: ops pain lead, no pricing."]}

    # 4 format
    words = len(_clean(body).split())
    f_problems = []
    if "{{" in body:
        f_problems.append("Unfilled merge field. Auto-fix: fill from the record.")
    if words > MAX_WORDS:
        f_problems.append(f"{words} words (max {MAX_WORDS}).")
    for b in BANNED:
        if b in body.lower():
            f_problems.append(f"Banned phrase: {b}")
    checks["format"] = {"ok": not f_problems, "fixable": all("Auto-fix" in p for p in f_problems) and bool(f_problems),
                        "detail": f_problems or [f"{words} words, no merge fields, no banned phrases."]}

    # 5 similarity to the rest of the batch (word trigram Jaccard)
    def grams(t):
        w = re.findall(r"[a-z']+", _clean(t).lower())
        return {tuple(w[i:i + 3]) for i in range(len(w) - 2)}
    mine = grams(body)
    sims = [len(mine & grams(o["body"])) / max(1, len(mine | grams(o["body"])))
            for o in batch if o["id"] != draft["id"]]
    top = max(sims) if sims else 0
    checks["similarity"] = {"ok": top < 0.30, "detail": [f"Closest other draft {top:.2f} (limit 0.30)."]}

    hard_fail = not checks["grounding"]["ok"] or not checks["no_invented_facts"]["ok"] or not checks["similarity"]["ok"]
    fixable = [k for k in ("persona_fit", "format") if not checks[k]["ok"]]
    if hard_fail:
        result = "BLOCKED"
    elif fixable and all(checks[k].get("fixable") for k in fixable):
        result = "FIXED"
    elif fixable:
        result = "BLOCKED"
    else:
        result = "PASS"
    return {"id": draft["id"], "account": acct, "draft": draft, "checks": checks, "result": result,
            "fixed_body": autofix(draft, acct) if result == "FIXED" else None}


def autofix(draft, acct):
    body = draft["body"].replace("{{first_name}}", acct["contact"]["name"].split()[0])
    if acct["contact"]["persona"] in OPS_PERSONAS:
        body = "\n".join(" ".join(s for s in re.split(r"(?<=[.!?])\s(?=[A-Z])", line) if not PRICING.search(s))
                         for line in body.split("\n"))
    return body


def render_body(text):
    """Strip citation markers for display."""
    return _clean(text)


def evaluate_batch():
    return [evaluate(d, DRAFTS) for d in DRAFTS]
