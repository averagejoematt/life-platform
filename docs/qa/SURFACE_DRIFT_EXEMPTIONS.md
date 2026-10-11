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
- 2026-09-26 | route | /api/page_feedback | #4182 POST-only write door (the two-question reader form) — there is no GET shape to snapshot; covered instead by the `write-path` entry in tests/api_schemas/_exemptions.json + deploy/capture_api_schemas.py WRITE_PATH_EXEMPT (the same disposition as every other capture door), with behaviour pinned in tests/test_page_feedback_4182.py
- 2026-09-27 | route | /api/morning_note | #4189 the morning note (GET served note / POST owner write) — new route ships in the same PR with a dated `_exemptions.json` capture-failed entry (route not deployed yet, no live GET shape to snapshot — the #1373 disposition); post-deploy the driver runs `deploy/capture_api_schemas.py --only /api/morning_note`, commits the real baseline, and drops the JSON exemption
- 2026-10-02 | cron | cdk/stacks/email_stack.py:events.Schedule.cron(minute='0', | #4546 (Monday 16:00 UTC rule) the Story Desk's Monday reply-desk questions — the rule targets the existing wednesday-chronicle lambda, whose DLQ + errors alarm already cover a failed invoke; a skipped Monday is a normal week by design (the questions are optional and never block generation), and the send-once STORYQ#W<n> marker records each send. A missed-send dead-man is part of #4539 (the season's dead-men). <!-- drift-ok: exemption-ledger token naming the new Monday rule, not a schedule claim for wednesday-chronicle -->
- 2026-10-03 | route | /api/edition | #4582 (epic #4580) the front page's one composed document — new read-only GET route ships in the same PR with a dated `_exemptions.json` capture-failed entry (route not deployed yet, no live GET shape to snapshot — the #1373 disposition); post-deploy the driver runs `deploy/capture_api_schemas.py --only /api/edition`, commits the real baseline, and drops the JSON exemption. Its block contract is pinned meanwhile against the live wire bodies in tests/test_site_api_routes.py
- 2026-10-04 | route | /api/owner_words | #4584 his own words from chat (MCP log_owner_note) or email (Story Desk replies), verbatim (GET, read-only) — new route ships in the same PR with a dated `_exemptions.json` capture-failed entry (route not deployed yet, no live GET shape to snapshot — the #1373 disposition); post-deploy the driver runs `deploy/capture_api_schemas.py --only /api/owner_words`, commits the real baseline, and drops the JSON exemption. Its payload contract is pinned meanwhile in tests/test_owner_words_4584.py and the edition fixture tests/fixtures/edition_wire_4582/owner_words.json
- 2026-10-04 | route | /api/calls | #4586 (epic #4580) every settled, checkable coach call, one page each — new read-only GET route ships in the same PR with a dated `_exemptions.json` capture-failed entry (route not deployed yet, no live GET shape to snapshot — the #1373 disposition); post-deploy the driver runs `deploy/capture_api_schemas.py --only /api/calls`, commits the real baseline, and drops the JSON exemption. Its contract is pinned meanwhile against the captured stored rows in tests/test_site_api_calls_4586.py
- 2026-10-04 | route | /api/coach_moves | #4648 (epic #4580) one day's coach lines by date for the preview day page (GET `?date=YYYY-MM-DD`, read-only, one GetItem) — new route ships in the same PR with a dated `_exemptions.json` capture-failed entry (route not deployed yet, no live GET shape to snapshot — the #1373 disposition); post-deploy the driver runs `deploy/capture_api_schemas.py --only /api/coach_moves`, commits the real baseline, and drops the JSON exemption. Its contract is pinned meanwhile in tests/test_site_api_coach_moves_4648.py
- 2026-10-04 | cron | cdk/stacks/email_stack.py:schedule="cron(0 | #4622 (Saturday 16:00 UTC, `habit-skip-review`) the weekly skipped-habits queue. Its absence signal is different machinery, not a new alarm: every run, empty week included, emits LifePlatform/Email::HabitSkipReviewRun (EMF), so the producer census (deploy/sentinel_producer_census.py, FIRST_DUE 2026-10-10) grades its Invocations on the weekly cadence, and tests/test_heartbeat_completeness.py carries its producer-census row. A swallowed AccessDenied is caught by the shared denial filter (monitoring_denial_alarms.WATCHED_LOG_GROUPS, changed in the same PR); a failed invoke goes to the shared DLQ. One owner email a week does not earn a dedicated alarm (docs/PROPORTIONALITY.md row). The token is the gate's prefix form (tokens cannot contain spaces). <!-- drift-ok: exemption-ledger token naming the new Saturday rule, not a schedule claim -->
