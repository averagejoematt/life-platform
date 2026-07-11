# Re-Entry Protocol — Reusable Runbook

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-05-19

Last updated: 2026-05-19 (V2 audit operational sweep)

**Trigger:** Any planned or unplanned platform gap > 7 days.
**Source:** Synthesized from `Downloads/ajm_reentry_plan.md` (the 2026-05-02/03 re-entry from a 30-day move silence). Promoted to runbook 2026-05-03. Reinforced by the 2026-04-05→2026-05-19 Garmin OAuth outage (44 days; see INCIDENT_LOG.md).
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
For each source that's been flowing during the gap, run `get_daily_snapshot view=latest sources=['<source>']` and confirm latest date is ≤ 24h. Sources that historically held during gaps (per 2026-05-02 evidence): Whoop, Eight Sleep, Withings, Strava, Notion ingestion (the polling Lambdas keep firing).

### 2. Re-auth + force-pull stale OAuth sources

| Source | Re-auth path | Notes |
|---|---|---|
| Garmin | `setup/setup_garmin_browser_auth.py` (Playwright/Chromium MFA) | OAuth1 refresh has ~30d lifetime — disable EventBridge rule before any planned silence > 2 weeks to prevent rate-limit accumulation. After re-auth, **clear the `auth_breaker` marker** (see RUNBOOK "Garmin: 429" section). The 2026-04-05→05-19 outage was caused by this exact gap pattern. |
| Withings | `setup/fix_withings_oauth.py` | Similar pattern; same mitigation |
| Strava | OAuth via setup helper (manually re-auth via Strava developer console if needed) | Open app on phone first, force a sync |
| Whoop | OAuth refresh tokens long-lived | Less risky during gaps |
| Eight Sleep | `setup/setup_eightsleep_auth.py` | Password may have changed during gap |
| Dropbox | `setup/setup_dropbox_auth.py` | If MacroFactor pipeline silent for >2 weeks |

### 3. Backfill Apple Health (if HAE webhook went silent)
- iPhone → Health app → profile → Export All Health Data → wait for ZIP
- Drop ZIP into `datadrops/apple_health_drop/apple_health_export_<dropname>/` and unzip
- Run `python3 backfill/backfill_apple_health_export_v16.py datadrops/apple_health_drop/apple_health_export_<dropname>/export.xml --since YYYY-MM-DD` where `--since` is the last known good Apple Health date
- v16.1 source-priority dedup ensures no double-counting (TD-15/16, fixed in v6.8.3)

### 4. Lab data
- If a Function Health draw is pending: download PDFs + CSV, save to `s3://matthew-life-platform/raw/matthew/labs/<draw_date>/`
- Build the structured biomarker dict via the existing `backfill/draw_*.py` pattern
- Run the ingest script; verify via `get_labs view=results`

### 5. Verify
- `get_daily_snapshot view=latest` — every source ≤ 24h or flagged broken with a workaround
- `get_health view=dashboard` — readiness, training load, biomarkers fresh

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
- Lambda timeouts that cold-start poorly (e.g., `list_protocols`, `get_field_notes` per the 2026-05-02 evening session)
- Polling Lambdas where the upstream auth expired (Garmin, Withings)
- "Computed" tables (e.g., chronicling) that depend on upstream Lambdas — verify they're still being written

Manually re-run nightly warming jobs to refresh dashboards (invoke `life-platform-mcp-warmer` directly).

If WR-48 (Stale-Source Alerts) is live and a source still shows stale, the alarm should already have fired into your daily brief — re-check that channel.

---

## Day 2 midday — Capture new baseline (~15 min)

This anchors the new "Cycle" as a measurement reference for future "where am I now vs. when I came back" comparisons.

- Run `capture_baseline label='reentry_<YYYY_MM_DD>'` via MCP (uses `tool_capture_baseline` in `mcp/tools_memory.py`)
- Write a one-paragraph platform_memory entry under category `re_entry` documenting: the gap dates, what caused it, what got broken, how you came back. This is for future-you and future Claude.
- Add a Cycle marker to platform_memory:
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
- `get_health view=dashboard` — readiness, training load, biomarkers all fresh
- `get_habits view=dashboard` — today reflects reality (even if low — that's fine)
- `get_journal_entries start_date=<re-entry date>` — re-entry entry present and enriched
- `get_labs view=results` — new draw visible if applicable
- All ~125 MCP tools respond < 30s. Spot-check 10 representative tools.

---

## Day 3+ — Gradual ramp

- Re-add habits beyond Tier-0 only as you actually do them. Don't aspire on day 3 — observe what's real, then ratchet up.
- Run a 7-day re-entry challenge: `create_challenge name="7-Day Re-Entry: Essential Seven Only" duration_days=7`
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

- `docs/WR_47_48_ARCHITECTURE_SPEC.md` — Pause Mode + Stale-Source Alerts design
- `docs/audits/TD-19_DATE_PARTITION_AUDIT.md` — date-keying convention per Lambda (relevant for any backfill work)
- `docs/audits/TD-11_HABITIFY_API_AUDIT.md` — Habitify state taxonomy (informs the Tier-0 habit reset)
- `handovers/HANDOVER_v6.8.7.md` — what shipped 2026-05-03 (the re-entry session itself)
- `Downloads/ajm_reentry_plan.md` — the original 2026-05-02 plan this runbook was synthesized from
- `docs/INCIDENT_LOG.md` — Garmin OAuth outage entry (2026-04-05 → 2026-05-19) is the canonical example of "what breaks during gaps without active pause-mode discipline"

---

**Verified:** 2026-05-19 (V2 audit operational sweep)
