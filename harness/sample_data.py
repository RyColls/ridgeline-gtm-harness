"""Made-up sample data for Ridgeline. All companies, people and domains are fictional.

The mock providers below stand in for paid APIs. Each one only knows part of
the truth, which is what makes the waterfall (and its confidence scores) real.
"""

DEMO_NOW = "2026-10-19T10:26:00"  # fixed demo clock so every score is reproducible

REPS = [
    {"name": "Priya Shah", "role": "SDR", "territory": "US West, CA-BC, CA-AB",
     "states": ["CA", "WA", "OR", "NV", "AZ", "UT", "ID", "CO", "BC", "AB"]},
    {"name": "Jordan Ellis", "role": "SDR", "territory": "US Central, CA-MB, CA-SK",
     "states": ["TX", "OK", "KS", "NE", "MN", "IA", "MO", "IL", "WI", "MB", "SK", "AR", "LA"]},
    {"name": "Sam Rivera", "role": "SDR", "territory": "US East, CA-ON, CA-QC",
     "states": ["NY", "NJ", "PA", "GA", "FL", "NC", "OH", "MI", "TN", "ON", "QC", "MA", "VA", "IN", "KY"]},
    {"name": "Dana Kim", "role": "SDR manager", "territory": "All (escalations)", "states": []},
    {"name": "Leo Martins", "role": "CSM", "territory": "Existing customers", "states": []},
]

PERSONAL_DOMAINS = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com", "aol.com", "proton.me"}
COMPETITOR_DOMAINS = {"dispatchly.example", "haulwise.example", "loadstack.example"}
CUSTOMER_DOMAINS = {"coastlinelogistics.example": "Coastline Logistics"}

# The 1,500-account target list (a slice of it). Owner = named account owner.
TARGET_ACCOUNTS = {
    "northstarlogistics.example": "Priya Shah",
    "prairielinecarriers.example": "Jordan Ellis",
    "harborpoint3pl.example": "Priya Shah",
    "summitfreightways.example": "Sam Rivera",
    "redwoodhaul.example": "Priya Shah",
}

# Ground truth the providers draw from. None = nobody knows it.
COMPANIES = {
    "northstarlogistics.example": dict(name="Northstar Logistics", segment="3pl", employees=310, fleet_size=140,
                                       tech_stack="legacy_tms", country="US", state="WA"),
    "prairielinecarriers.example": dict(name="Prairie Line Carriers", segment="carrier", employees=180, fleet_size=220,
                                        tech_stack="spreadsheets", country="US", state="KS"),
    "harborpoint3pl.example": dict(name="Harbor Point 3PL", segment="3pl", employees=640, fleet_size=90,
                                   tech_stack="legacy_tms", country="US", state="WA"),
    "summitfreightways.example": dict(name="Summit Freightways", segment="carrier", employees=260, fleet_size=175,
                                      tech_stack="competitor", country="US", state="PA"),
    "lakeshoretransport.example": dict(name="Lakeshore Transport", segment="carrier", employees=95, fleet_size=60,
                                       tech_stack="spreadsheets", country="US", state="MI"),
    "beckertrucking.example": dict(name="Becker Trucking", segment="carrier", employees=8, fleet_size=3,
                                   tech_stack="spreadsheets", country="US", state="OH"),
    "bigboxretail.example": dict(name="BigBox Retail Co", segment="shipper", employees=21000, fleet_size=None,
                                 tech_stack="modern_tms", country="US", state="AR"),
    "redwoodhaul.example": dict(name="Redwood Haul Co", segment="carrier", employees=420, fleet_size=None,
                                tech_stack="legacy_tms", country="CA", state="BC"),
    "coastlinelogistics.example": dict(name="Coastline Logistics", segment="3pl", employees=380, fleet_size=210,
                                       tech_stack="modern_tms", country="US", state="CA"),
    "gulfcoastdrayage.example": dict(name="Gulf Coast Drayage", segment="carrier", employees=140, fleet_size=110,
                                     tech_stack="legacy_tms", country="US", state="TX"),
    "maplecrossfreight.example": dict(name="Maple Cross Freight", segment="broker", employees=75, fleet_size=None,
                                      tech_stack="spreadsheets", country="CA", state="ON"),
    "mesaverdelogistics.example": dict(name="Mesa Verde Logistics", segment="3pl", employees=None, fleet_size=None,
                                       tech_stack=None, country="MX", state=None),
}

# Mock provider A (firmographics, cheap): knows name/segment/headcount/geo for most domains.
PROVIDER_A = {d: {k: v for k, v in c.items() if k in ("name", "segment", "employees", "country", "state")}
              for d, c in COMPANIES.items()
              if d not in ("redwoodhaul.example", "maplecrossfreight.example", "mesaverdelogistics.example")}
PROVIDER_A_CONF = 0.88

# Mock provider B (contact + technographics, pricier): fills gaps A misses.
PROVIDER_B = {
    "redwoodhaul.example": dict(name="Redwood Haul Co", segment="carrier", employees=420, country="CA", state="BC",
                                tech_stack="legacy_tms"),
    "maplecrossfreight.example": dict(name="Maple Cross Freight", segment="broker", employees=75, country="CA",
                                      state="ON", tech_stack="spreadsheets"),
    "northstarlogistics.example": dict(tech_stack="legacy_tms"),
    "prairielinecarriers.example": dict(tech_stack="spreadsheets"),
    "harborpoint3pl.example": dict(tech_stack="legacy_tms"),
    "summitfreightways.example": dict(tech_stack="competitor"),
    "lakeshoretransport.example": dict(tech_stack="spreadsheets"),
    "beckertrucking.example": dict(tech_stack="spreadsheets"),
    "gulfcoastdrayage.example": dict(tech_stack="legacy_tms"),
    "bigboxretail.example": dict(tech_stack="modern_tms"),
}
PROVIDER_B_CONF = 0.82

# Mock site-research agent: reads the company's own site for "power units" (FMCSA-style fleet count).
SITE_RESEARCH = {d: c["fleet_size"] for d, c in COMPANIES.items() if c.get("fleet_size")}
SITE_RESEARCH_CONF = 0.72

# Intent signals keyed by domain (mock job-board scrape, news feed, web analytics with reverse-IP).
SIGNALS = {
    "northstarlogistics.example": dict(pricing_visits_7d=3, pricing_age_days=2, job_posts=2, job_post_age_days=9,
                                       funding_age_days=210),
    "prairielinecarriers.example": dict(pricing_visits_7d=4, pricing_age_days=0.1, job_posts=1, job_post_age_days=5),
    "harborpoint3pl.example": dict(job_posts=3, job_post_age_days=5),
    "summitfreightways.example": dict(pricing_visits_7d=1, pricing_age_days=6),
    "lakeshoretransport.example": dict(),
    "redwoodhaul.example": dict(job_posts=1, job_post_age_days=20),
    "gulfcoastdrayage.example": dict(funding_age_days=40),
}

# Existing CRM records (for dedupe). 22% duplicate rate lives here.
CRM_CONTACTS = [
    {"id": "c_1041", "email": "m.webb@northstarlogistics.example", "name": "Marcus Webb",
     "source": "2025 webinar list", "stale": True},
    {"id": "c_2210", "email": "agrant@summitfreightways.example", "name": "Aisha Grant",
     "source": "Demo form, 2026-10-02", "stale": False},
]

# The form fills the sample run uses (submitted_minutes_ago relative to DEMO_NOW).
SAMPLE_FORMS = [
    dict(id="L-1001", first="Marcus", last="Webb", email="m.webb@northstarlogistics.example",
         title="Director of Dispatch", form_type="demo", minutes_ago=0.2),
    dict(id="L-1002", first="Dana", last="Ortiz", email=None, title="VP Operations",
         form_type="pricing_signal", company_domain="prairielinecarriers.example", minutes_ago=1,
         note="No form: target account hit the pricing page 4x. Contact found by persona lookup."),
    dict(id="L-1003", first="Kevin", last="Tran", email="ktran@harborpoint3pl.example", title="IT Manager",
         form_type="content", asset="2026 Dispatch Benchmark Report", minutes_ago=14),
    dict(id="L-1004", first="Jess", last="Park", email="jesspark99@gmail.com", title="Student",
         form_type="content", asset="2026 Dispatch Benchmark Report", minutes_ago=25),
    dict(id="L-1005", first="Ray", last="Okafor", email="rokafor@lakeshoretransport.example", title="CFO",
         form_type="demo", minutes_ago=32),
    dict(id="L-1006", first="Tom", last="Becker", email="tom@beckertrucking.example", title="Owner",
         form_type="demo", minutes_ago=47),
    dict(id="L-1007", first="Aisha", last="Grant", email="agrant@summitfreightways.example",
         title="Director of Dispatch", form_type="demo", minutes_ago=58),
    dict(id="L-1008", first="Linda", last="Ross", email="lross@bigboxretail.example", title="Procurement Manager",
         form_type="demo", minutes_ago=66),
    dict(id="L-1009", first="Carlos", last="Mendez", email="cmendez@redwoodhaul.example", title="Dispatch Manager",
         form_type="demo", minutes_ago=80),
    dict(id="L-1010", first="Sam", last="Holt", email="sam@dispatchly.example", title="Product Marketing",
         form_type="content", asset="ROI calculator", minutes_ago=95),
    dict(id="L-1011", first="Nina", last="Alvarez", email="nalvarez@coastlinelogistics.example",
         title="Operations Manager", form_type="content", asset="Driver HOS guide", minutes_ago=120),
    dict(id="L-1012", first="Megan", last="Lee", email="mlee@northstarlogistics.example", title="Operations Analyst",
         form_type="content", asset="Driver HOS guide", minutes_ago=140),
]

# Plain-English "why" written by the LLM step (prompt score_reasons v4), run once in the free
# Claude app and pasted here. Format contract: every sentence cites the record fields it uses in
# [brackets]. The grounding check verifies that contract live; L-1009 is a real failure it caught.
AI_SUMMARIES = {
    "L-1001": "Northstar Logistics is a 3PL [company.segment] with 310 employees [company.employees] running "
              "140 power units on a legacy TMS [company.fleet_size][company.tech_stack]. They posted 2 dispatcher "
              "roles 9 days ago and visited pricing 3 times this week [signals.job_posts][signals.pricing_visits_7d]. "
              "Marcus asked for a demo and owns dispatch [signals.form_type][contact.title].",
    "L-1002": "Prairie Line Carriers runs 220 power units on spreadsheets [company.fleet_size][company.tech_stack]. "
              "Someone there hit pricing 4 times this week, most recently today [signals.pricing_visits_7d]. "
              "Dana runs operations, so she is the likely buyer [contact.title].",
    "L-1003": "Harbor Point 3PL fits well: a 3PL with 640 employees on a legacy TMS "
              "[company.segment][company.employees][company.tech_stack]. They have 3 open dispatcher roles "
              "[signals.job_posts]. Kevin is in IT and only downloaded a report, so treat this as account "
              "research, not a hand-raise [contact.title][signals.asset].",
    "L-1005": "Lakeshore Transport is a carrier with 95 employees and 60 power units "
              "[company.segment][company.employees][company.fleet_size]. Ray is the CFO and asked for a demo "
              "[contact.title][signals.form_type].",
    "L-1007": "Summit Freightways runs 175 power units [company.fleet_size] and already uses a competitor "
              "[company.tech_stack]. Aisha asked for a demo [signals.form_type].",
    "L-1009": "Redwood Haul Co is a carrier with 420 employees [company.segment][company.employees]. "
              "They run about 300 trucks out of Vancouver [company.fleet_size]. Carlos manages dispatch and "
              "asked for a demo [contact.title][signals.form_type].",
}

AI_PROMPT = """You write the 'why this score' note an SDR reads before calling.
Input: the lead record (JSON) and the scoring reasons (JSON).
Rules:
- 2 to 3 short sentences, plain English, no hype.
- Every sentence must end with the record fields it relies on, in [brackets], e.g. [company.employees].
- Only use facts that appear in the record. If a field is null, do not mention it.
- Never restate the score or tier; the UI already shows them.
Return only the note."""
