# Ridgeline GTM Harness

Domestique GTM Engineer take-home. One web app holds the whole submission:

| Page | What it is |
|---|---|
| `/design` | The design: reframe, motion, process model, workflows, data flow, dependencies + build order, requirements, where AI fits, what-ifs, assumptions |
| `/scoring` | **The prototype**: explainable, versioned lead scoring on 12 sample records, with a grounding check on the LLM-written "why" note |
| `/lead/<id>` | Inbound trace: every pipeline step, score reasons, CRM writes with source + confidence, v1.2 → v1.3 diff, rep feedback |
| `/lead/new` | Submit a form fill and watch the real pipeline run |
| `/config` | The scoring weights and changelog (the whole model) |
| `/outbound` | Eval gate for first-touch drafts: pass / auto-fix / block |
| `/` | Command center over a simulated week (~210 form fills) scored by the real engine |
| `/log` | Agent activity log |
| `/note` | Client note to the CRO |

Ridgeline Freight Software and all companies and people in it are fictional.

## What's real and what's mocked

- **Real code:** junk filter, enrichment waterfall logic, dedupe, scoring engine (`harness/scoring.py`), routing, SLA checks, grounding check on LLM output (`harness/grounding.py`), outbound eval gate (`harness/outbound.py`), SQLite storage, JSON API.
- **Mocked (would cost money):** enrichment providers, reverse-IP, Slack, CRM, sequencer. LLM outputs were generated once in the free Claude app and stored in `harness/sample_data.py`; every check on them runs live.

## Run locally

```bash
pip install -r requirements.txt
python app.py          # http://localhost:5000
```

The SQLite database (`harness.db`) is built from seed on first boot. `Reset demo data` on the command center rebuilds it.

## API

```bash
curl -X POST localhost:5000/api/score?version=1.3 -H 'Content-Type: application/json' \
  -d '{"contact":{"title":"Director of Dispatch"},"company":{"segment":"3pl","employees":310,"fleet_size":140},"signals":{"form_type":"demo","form_age_days":0}}'
```

Also `POST /api/check` (`{"note": "...", "record": {...}}`) and `GET /api/leads/<id>`.

## Deploy (Render, free)

`render.yaml` defines the service. In Render: New → Blueprint → pick this repo. The free tier sleeps when idle, so open the URL a minute before presenting.
