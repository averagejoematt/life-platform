# Re-Entry Protocol — Reusable Runbook

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-10-17 (every named script, Lambda, MCP tool and doc re-checked against the tree; stale tool names, the retired Garmin/Apple-XML paths and the dead links fixed — see the closing Verified line)

Last updated: 2026-10-17 (re-verification pass; day-by-day structure from the 2026-05-19 V2 audit sweep)

**Trigger:** Any planned or unplanned platform gap > 7 days.
**Source:** Synthesized from a local plan file (since removed) for the 2026-05-02/03 re-entry from a 30-day move silence. Promoted to runbook 2026-05-03. Reinforced by the 2026-04-05→2026-05-19 Garmin OAuth outage (44 days; see INCIDENT_LOG.md).
**Goal:** Every source flowing or explicitly known-broken with a workaround, by Day 2 evening. New baseline captured. Honest journal entry posted. Pause Mode → Re-Entry Day Template (WR-50) loaded once it ships.

---

## When this triggers

A gap > 7 days. Examples:
- Planned: travel, illness, focused work, deliberate platform-pause
- Unplanned: move, life event, energy crash

**Critical principle:** *Honest > Perfect.* This is recovery work, not crisis work. The platform exists for moments like this — to be the structure you come back to, not a tyrant you have to be perfect for.

---

## Day 0 — Declare the gap

If WR-47 (Pause Mode) is live by the time you read this:
- Use the Pause Mode UI to declare the gap explicitly.
- Site banner posts automatically. Scoring suppressed. Streak punishment frozen.
- Skip to "Day 1" below.

If WR-47 isn't live yet:
- Mentally mark today as "Day 0 — gap acknowledged."
- The work below covers what Pause Mode would automate.

---

## Day 1 morning — Connector sweep + lab refresh + HAE backfill (~90 min)

Goal: every source either flowing or explicitly known-broken with a plan.

### 1. Verify-only sources (no action)
For each source that's been flowing during the gap, run `get_daily_snapshot view=latest sources=['<source>']` (or `get_freshness_status` for every source at once) and confirm latest date is ≤ 24h. Sources that historically held during gaps (per 2026-05-02 evidence): Whoop, Eight Sleep, Withings, Strava, Notion ingestion (the polling Lambdas keep firing).

### 2. Re-auth + force-pull stale OAuth sources

| Source | Re-auth path | Notes |
|---|---|---|
| Garmin | **RETIRED (#4640, ADR-074 amendment 2026-10-11)** — no direct-API Lambda, the `life-platform/garmin` secret is in its deletion window, and Garmin data arrives through Strava. Nothing to re-auth. (`setup/setup_garmin_browser_auth.py` remains in the tree for revival only; the historical rule — disable the EventBridge rule before a silence > 2 weeks and clear the `auth_breaker` marker after re-auth, RUNBOOK "Garmin: 429" — is what the 2026-04-05→05-19 outage taught.) | Skip. |
| Withings | `setup/fix_withings_oauth.py` | Rate-limit accumulation on cron retries during silence — disable the EventBridge rule before a planned silence |
| Strava | OAuth via setup helper (manually re-auth via Strava developer console if needed) | Open app on phone first, force a sync |
| Whoop | OAuth refresh tokens long-lived; if it does die, `setup/setup_whoop_auth.py` | Less risky during gaps |
| Eight Sleep | `setup/setup_eightsleep_auth.py` | Password may have changed during gap |
| Dropbox | `setup/setup_dropbox_auth.py` | If MacroFactor pipeline silent for >2 weeks |

### 3. Apple Health (if the HAE webhook went silent)
- The Health Auto Export webhook (`health-auto-export-webhook`) is the **sole** `apple_health` writer. The export.xml import Lambda and its backfill script were retired 2026-07-04 (#474, ADR-103) — there is no manual XML path. See `docs/RUNBOOK.md` → Apple Health.
- Fix the cause, not the data: open the Health Auto Export app on the iPhone, confirm the automation is on **hourly** sync (not "since last run" — infrequent syncs drop Dietary Water/Caffeine), and force a sync. The webhook merges what it receives at reading level, so a catch-up push fills the gap.

### 4. Lab data
- If a draw is pending: save the PDF (and its markdown transcription) under `s3://matthew-life-platform/raw/matthew/labs/<draw_date>/` — the `raw_layout` facet of the labs entry in `lambdas/ingestion/source_registry.py` (hand-uploaded; no Lambda writes it)
- The structured biomarker record (DDB `SOURCE#labs`, shape in `docs/SCHEMA.md`) is written by an owner-attended session — the old `backfill/draw_*.py` scripts no longer exist in the tree, so nothing here is one command
- Verify via `get_labs view=results`

### 5. Verify
- `get_daily_snapshot view=latest` / `get_freshness_status` — every source ≤ 24h or flagged broken with a workaround
- `get_readiness_score` and `get_training` — readiness and training load fresh; `get_labs view=results` — biomarkers

---

## Day 1 afternoon — Re-Entry Journal Entry (NON-NEGOTIABLE)

This is the most important task of the re-entry. Cannot be skipped, cannot be delegated.

- Open Notion, create entry titled "Day N — Re-Entry" (or similar)
- Write what's actually true: what happened, what you avoided, what you noticed about not having the system, what surprised you (good or bad), what scares you about restarting
- Don't write for the AI. Don't write for an audience. Write the entry you'd write if no one was reading
- Verify the journal ingestion Lambda picks it up; manually run if needed (check `aws logs tail /aws/lambda/notion-journal-ingestion --since 30m`)

Why this matters: the AI coaches (Elena Voss, Paul Conti) need raw material to work with. Without it, next week's digest is a vacuum.

---

## Day 1 evening — Tier-0 habits only

**Critical principle:** *Don't lie to your data.* Pause what you're not doing, restart only what's real.

- Open Habitify
- Pause every habit you're not realistically doing this week
- Re-enable only the Essential Seven (Tier 0). The floor, not the ceiling.
- Log today's Tier-0 honestly — even if it's mostly zeros. The data gets to be true.
- (Once TD-11 ships, the Habitify ingestion Lambda will distinguish `pending` from `failed` natively — see `docs/audits/TD-11_HABITIFY_API_AUDIT.md`. Until then the live Lambda treats both as `0.0`.)

---

## Day 2 morning — Tech debt sweep (~90 min)

CloudWatch sweep:
- Any Lambdas in error state since the gap started? Spot-check via `aws cloudwatch get-metric-statistics --namespace AWS/Lambda --metric-name Errors`
- Did nightly warming jobs run during the gap? Check `/aws/lambda/life-platform-mcp-warmer`
- EventBridge rule integrity: `aws events list-rules --region us-west-2`

Common things that break during gaps:
- Lambda timeouts that cold-start poorly (e.g., `get_field_notes` per the 2026-05-02 evening session; `list_protocols` has since been removed)
- Polling Lambdas where the upstream auth expired (Withings, Strava, Dropbox)
- "Computed" tables (e.g., chronicling) that depend on upstream Lambdas — verify they're still being written

Manually re-run nightly warming jobs to refresh dashboards (invoke `life-platform-mcp-warmer` directly).

If WR-48 (Stale-Source Alerts) is live and a source still shows stale, the alarm should already have fired into your daily brief — re-check that channel.

---

## Day 2 midday — Capture new baseline (~15 min)

This anchors the new "Cycle" as a measurement reference for future "where am I now vs. when I came back" comparisons.

- Capture the baseline: `capture_baseline` was removed from the MCP surface (zero invocations, `docs/MCP_TOOL_AUDIT.md` batch 2), so record it by hand — `get_daily_snapshot view=summary date=<re-entry date>` plus `get_readiness_score`, and paste the key numbers into the platform_memory entry below
- Write a one-paragraph platform_memory entry (`write_platform_memory`; categories via `list_memory_categories`) under category `re_entry` documenting: the gap dates, what caused it, what got broken, how you came back. This is for future-you and future Claude.
- Add a Cycle marker to platform_memory (this is the *gap* marker, not an experiment restart — the experiment cycle counter is `get_experiment_cycle` / SSM `/life-platform/experiment-cycle`, and a gap re-entry never runs `restart_pipeline.py`; the owner ruled no further resets, #4037):
  - `CYCLE#<N>#<label>` where N is the new cycle number, label is the entry name
  - `start_date`, `end_date` (open-ended for current cycle), `summary`

The 2026-05-03 re-entry is logged at `MEMORY#re_entry#2026-05-03` and the cycle markers are at `CYCLE#1#launch`, `CYCLE#1.5#gap_move`, `CYCLE#2#reentry` — use those as templates for future re-entries.

---

## Day 2 afternoon — Narrative & UX

Decisions to make explicitly:

1. **Preserve the gap or reset data?** Strong recommendation: preserve. The gap IS the story. AJM's value is honest tracking. Erasing reality to look better is the first step toward a vanity dashboard.
2. **Public framing?** Recommendation: a single short post titled "On Coming Back" (or similar) — one paragraph, on the homepage, dated the re-entry date. Acknowledge the silence, name the re-entry. No dramatics. Vulnerability IS the brand.
3. **Soft re-launch?** Recommendation: yes — but as a narrative beat, not a data reset. The first daily brief of the new cycle is "Day 1 of Cycle N" without erasing prior cycle data.

If WR-50 (Re-Entry Day Template) is live, this auto-loads as a challenge in Habitify.

---

## Day 2 evening — Validation sweep

- `get_daily_snapshot view=latest` — every source within 24-48h or explicitly labeled
- `get_readiness_score` / `get_training` — readiness and training load fresh
- `get_habit_completion` — today reflects reality (even if low — that's fine)
- `get_date_range source=notion start_date=<re-entry date> end_date=<today>` — re-entry entry present and enriched
- `get_labs view=results` — new draw visible if applicable
- The MCP tools respond < 30s (the live count is `python3 scripts/boot_brief.py`). Spot-check 10 representative tools.

---

## Day 3+ — Gradual ramp

- Re-add habits beyond Tier-0 only as you actually do them. Don't aspire on day 3 — observe what's real, then ratchet up.
- Run a 7-day re-entry stretch by hand (the `create_challenge` MCP tool was removed, `docs/MCP_TOOL_AUDIT.md`): Essential Seven only, tracked with `get_habit_completion`
- After 7 days, measure honest completion rate. If <60%, the floor is too high — reduce. If >80%, ratchet up next week.
- Address the Todoist accumulation (likely 100+ overdue tasks): bulk-archive aggressively; most are pre-gap artifacts.

---

## What only Matthew can do (do not delegate)

Even when WR-47/48/49/50 are live, these stay manual:
- Re-auth steps that require physical phone interaction (Garmin Playwright flow, MacroFactor app login, Withings step-on-scale, Strava force-sync)
- The re-entry journal entry (Day 1 afternoon)
- Habitify pause/resume sweep
- Visual site walkthrough (Day 2 narrative phase)
- Todoist triage
- Anniversary / relationship items that surface as deferred during the gap

---

## Success criteria

By Day 2 evening:
1. Every source flowing or explicitly known-broken with a workaround.
2. New baseline captured + cycle marker written.
3. Honest journal entry posted, so Elena and Paul have something true to work with next digest.
4. Tier-0 habits started — not aspirational, just real.
5. Pause Mode (WR-47) declared closed (or, until WR-47 ships, mentally close the gap).
6. The site is coherent for any visitor who shows up.
7. You feel like AJM is yours again — not a debt, not a guilt object, just the thing that helps.

---

## See also

- Pause Mode + Stale-Source Alerts design: the spec file `docs/WR_47_48_ARCHITECTURE_SPEC.md` no longer exists (recoverable from git history, last present at `0650e3c3c~1`); ADR-051 in `docs/DECISIONS.md` carries the WR-48 decision. WR-48 is live (daily-brief "Data Status" banner, `get_freshness_status`); WR-47 Pause Mode is **not** shipped as a UI — only the `/life-platform/pause-mode` SSM parameter that some writers (e.g. `hevy_restamp_lambda`) honour
- `docs/audits/TD-19_DATE_PARTITION_AUDIT.md` — date-keying convention per Lambda (relevant for any backfill work)
- `docs/audits/TD-11_HABITIFY_API_AUDIT.md` — Habitify state taxonomy (informs the Tier-0 habit reset)
- The 2026-05-03 re-entry session's handover (v6.8.7) is no longer on `main` — the handover corpus moved to the `session-archive` branch (#1650)
- `docs/INCIDENT_LOG.md` — Garmin OAuth outage entry (2026-04-05 → 2026-05-19) is the canonical example of "what breaks during gaps without active pause-mode discipline"
- `docs/ACCOUNTS.md` / `docs/AWS_ACCESS.md` / `docs/NEW_MACHINE_BOOTSTRAP.md` + `scripts/check_reentry_hardening.py` — a *stolen or lost* laptop is a different, harder gap than the ones this runbook covers (data silence vs. losing the device itself); issue **#1029** (epic #1024) is the owner-gated hardening checklist for that scenario

---

**Verified:** 2026-10-17 — script paths (`setup/*`), Lambda names (`notion-journal-ingestion`, `life-platform-mcp-warmer`), the labs S3 prefix, every MCP tool name and the doc cross-references checked against the tree. **Not exercised:** the owner-only physical steps (phone re-auth flows, Notion journal entry, Habitify sweep) and the CloudWatch/EventBridge commands (generic AWS CLI, unchanged).
