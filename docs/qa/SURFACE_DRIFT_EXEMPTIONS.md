# Surface-Drift Exemptions Ledger (#1454)

> **Status:** log · **Verified:** 2026-07-18

The PR-time surface-drift gate (`scripts/surface_drift_gate.py`, run by
`.github/workflows/surface-drift.yml` on every PR touching a surface path)
blocks a PR that adds new QA-relevant surface without its registration:

| leg | new surface in the diff | required registration |
|-------|--------------------------|------------------------|
| page  | `site/**/*.html` (non-legacy) | entry (or `EXEMPT` reason) in `tests/qa_manifest.py` |
| route | site-api dispatcher route in `lambdas/web/site_api_lambda.py` | schema baseline in `tests/api_schemas/` (advisory until #1436 lands that directory; blocking automatically after) |
| cron  | EventBridge `Schedule.cron/rate/expression` under `cdk/stacks/` | a heartbeat/alarm change in the **same PR** (monitoring_stack touched, or an alarm-count increase in a changed stack file) |
| js    | `.js` under `site/` **outside** `site/assets/js/` | move it under `site/assets/js/` — the #1432 import gate covers that directory by construction |

## The contract

**Exemptions are dated ledger entries, never silent.** When a PR legitimately
adds surface that should NOT carry the standard registration (a deliberate
one-off, a surface covered by different machinery, a landing-order constraint),
it adds a line to the Entries section below — in the same PR the gate would
otherwise block. The entry is permanent, reviewable history: never delete a
line; if an exemption stops applying, remove the surface or land the
registration and leave the line as record (or supersede it with a dated note).

## Entry format

```
- YYYY-MM-DD | page|route|cron|js | <token> | <reason>
```

- `token` is matched **exact-or-prefix** against the finding key the gate
  prints: a page viewer path (`/x/y/`), a route path (`/api/x`), a cron key
  (`cdk/stacks/<file>.py:<schedule signature>` — the bare file path works as a
  prefix token), or a JS file path (`site/...`).
- Lines not matching the format are treated as prose and ignored by the parser
  (`surface_drift_gate.parse_exemptions`) — an entry that doesn't take effect
  is a malformed entry; run the gate locally to confirm it registers.

## Entries

- 2026-07-18 | js | site/sw.js | service worker must live at the site root for scope; already present pre-gate, parse-covered by the deploy-time node gate in deploy/sync_site_to_s3.sh
- 2026-07-19 | route | /api/character_receipt | #1373 progression receipts — new route ships in the same PR with a dated `_exemptions.json` capture-failed entry (route not deployed yet, no live shape to snapshot); post-deploy the driver runs deploy/capture_api_schemas.py, commits the real baseline, and drops the JSON exemption
- 2026-07-19 | route | /api/fulfillment_index | #1404 fulfillment index — new route ships with a dated `_exemptions.json` capture-failed entry (not deployed yet, no live shape); post-deploy the driver runs deploy/capture_api_schemas.py, commits the baseline, and drops the JSON exemption
