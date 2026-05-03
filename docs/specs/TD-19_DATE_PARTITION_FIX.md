# TD-19 — Cross-source date partition convention fix

**Severity:** HIGH (architectural)
**Status:** Design — implementation pending Matthew approval
**Discovered:** 2026-05-02 during HAE webhook verification
**Source handover:** `handovers/HANDOVER_v6.8.1.md` ("Critical Architectural Finding")

---

## Problem

DDB partition keys for daily-source data use the form `DATE#YYYY-MM-DD`. But sources disagree on what midnight that date is anchored to:

- **HAE Lambda (Apple Health webhook)** writes today's data at the **local-PT-midnight** partition. A workout at 9pm PT on May 2 lands at `DATE#2026-05-02`.
- **Withings** writes today's data at the **UTC-midnight** partition. The same 9pm PT workout (which is 04:00 UTC May 3) would land at `DATE#2026-05-03`.

The two can disagree on which calendar date a given event belongs to. Same wall-clock day → two different DDB partitions → daily intelligence aggregation will silently undercount whichever source is on the "wrong" partition for the question being asked.

### How it surfaced

While verifying the HAE webhook tonight, today's `apple_health` row at `DATE#2026-05-03` was missing from MCP queries, but the Lambda logs showed it had successfully written. Direct DDB query found the row at `DATE#2026-05-02` (PT-local midnight). The other sources had already advanced to `DATE#2026-05-03`.

### Why this matters more later than now

With one or two sources misaligned, daily aggregation just shows partial data — visible-but-tolerable. As more sources come online and the platform leans on cross-source correlation (e.g. correlating Apple Health step count with Whoop strain on the same day), the bug produces **systematically wrong correlations rather than visible missing-data warnings**. That's silent corruption of the intelligence layer, which is exactly the failure mode the platform is supposed to defend against.

---

## Decision

**Adopt UTC midnight as the platform-wide partition convention.**

### Why UTC

1. **Source-of-truth alignment.** Every wearable I'm aware of stores timestamps in UTC internally. The PT-local convention is something we *added* on the way in. UTC is what's already there.
2. **Travel and DST.** Matthew travels (per memory: travel log feature exists). PT-local partitions break across timezone changes — a "day" becomes 23 or 25 hours. UTC is rigid and doesn't care.
3. **Cross-source correlation correctness.** With UTC, two sources writing the same event will always land on the same partition. This is the actual goal.
4. **Reversibility.** UTC → PT presentation is a one-line conversion at read time. PT → UTC requires knowing which timezone the data was originally written from, which we don't reliably store.

### Why not PT-local

The argument for PT-local is "the user lives in PT, queries should match their lived day." But:
- This is a *presentation* concern, not a *storage* concern
- We already format datetimes for display at read time
- The presentation layer can apply PT-localization on the way out without affecting storage

### Cost of being wrong about this decision

Low. The migration is mechanical. If we pick UTC and later regret it, switching to PT-local is the same migration shape applied in reverse. No data is lost in either direction; only the partition key changes.

---

## Audit — which Lambdas use which convention?

**Action item before any fix-forward:** audit every Lambda's date-keying logic and produce a table.

Known so far (from this session):
- HAE Lambda (`health-auto-export-webhook`) → **PT-local** ❌ needs fix
- Withings → **UTC** ✅
- Apple Health backfill v16 (`backfill_apple_health_export_v16.py`) → unknown, **must check** — backfill convention should match live convention or backfills will create the same bug after the fact

Unknown — must check:
- Garmin
- Whoop
- Eight Sleep
- Strava
- Habitify
- Todoist
- Notion
- Weather
- MacroFactor
- Function Health (lab draws — likely fine, dates are explicitly the draw date, not "now")

**Audit method:** for each Lambda, grep for `datetime.now()`, `date.today()`, `pytz`, `zoneinfo`, `tz=`, `astimezone`, and the partition key construction. Document what convention it uses. Output: `docs/audits/TD-19_DATE_PARTITION_AUDIT.md` with a row per source.

Estimated audit time: 1–2 hours.

---

## Implementation plan

Phased, each phase independently shippable.

### Phase 1: Audit (no code changes)

Produce `docs/audits/TD-19_DATE_PARTITION_AUDIT.md`. Identify every Lambda and its current convention. No fixes yet.

**Acceptance:** the audit doc exists with a row per source, and the verdict for each is one of: ✅ UTC, ❌ PT-local needs fix, ⚪ N/A (event-anchored, not "now"-anchored).

### Phase 2: Fix-forward in misaligned Lambdas

For each Lambda flagged ❌, change the date-keying logic to UTC. Pattern:

```python
# Before (broken)
from datetime import datetime
date_key = datetime.now().strftime("%Y-%m-%d")  # implicit local TZ

# After (fixed)
from datetime import datetime, timezone
date_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
```

**Test pattern per Lambda:**
1. Unit test: mock `datetime.now()` at 9pm PT on May 2 (04:00 UTC May 3). Assert partition key is `2026-05-03`.
2. Integration: deploy to staging if it exists, OR test invoke with a known-time payload, verify DDB row lands at expected partition.

**Critically:** ship Phase 2 changes ONE LAMBDA AT A TIME, not as a batch. If something breaks, we want to isolate which source caused it. Use `deploy/deploy_lambda.sh` per memory conventions, 10s wait between.

### Phase 3: Historical data migration (the hard part)

Existing rows under wrong partitions need to move. Pattern per affected source:

1. Identify all `DATE#YYYY-MM-DD` items where partition was constructed PT-local
2. For each item, determine if its semantic date should change under UTC convention
3. Items written between local midnight and UTC midnight (i.e. 4–5 hours of data, depending on DST) need to migrate forward by 1 day
4. Write new item, delete old item, in the same DDB transaction

**This is where the risk concentrates.** Risks:
- Idempotency: backfill scripts must be re-runnable without doubling rows. Use conditional puts.
- Cost: large rewrites of historical data are DDB-expensive. Estimate write capacity needs before running.
- Data loss: a partial migration that's interrupted can leave rows in inconsistent states. Migration must be transactional per item.

**Recommendation:** write the migration script as a one-off in `backfill/`, dry-run with `--no-write` first, log every change, then commit only after spot-checking the dry-run output.

### Phase 4: Verification

After Phases 2 + 3 complete for all sources:
- Run `life-platform:get_daily_snapshot` for several known dates and confirm cross-source data converges on the same partition
- Compare a known travel day (from `get_travel_log`) before and after migration — pre-migration the day might span two partitions; post-migration it should be clean
- Spot-check the headline-finding date (2026-05-02, the discovery point) and confirm `apple_health` and `withings` data are both at the same partition

---

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Migration script doubles rows due to non-idempotent writes | HIGH | Dry-run + conditional puts + per-item transactions |
| New convention silently breaks an existing query path that assumed PT-local | MED | Phase 4 verification queries all known surfaces before declaring done |
| MCP tool consumers (Claude chat, site Lambdas) implicitly assume PT-local in date math | MED | Grep MCP and Lambda code for date-keying; treat hits as part of the audit |
| DDB write capacity exceeded during migration | LOW | Throttle migration; monitor `aws cloudwatch get-metric-statistics` for `WriteThrottleEvents` |
| User-facing date display becomes confusing if presentation layer not updated | LOW | Presentation layer continues to render PT-local; storage is UTC. Add a note in `ARCHITECTURE.md`. |

---

## Open questions for Matthew

1. **Confirm UTC over PT-local?** This is the load-bearing decision. If you pick PT-local instead, the rest of the plan flips but the shape is identical.
2. **Migration urgency?** Phase 1 (audit) is cheap and unlocks visibility. Phase 2 (fix-forward) stops new corruption. Phase 3 (historical migration) is the expensive one — do we need historical correctness now, or can we live with "everything from this date forward is UTC, prior is PT-local with a flag" as an interim?
3. **Per-source rollout vs all-at-once for Phase 2?** Recommendation is one-at-a-time. Confirm.
4. **Travel context.** Memory mentions a travel log. Should the migration treat `away`-period data differently? My initial read: no — UTC is UTC regardless of where you are.

---

## Test strategy summary

**Unit:** mock-time tests per Lambda for boundary cases (9pm PT, 11pm PT, midnight UTC, DST transition days).
**Integration:** test-invoke each Lambda with a known-time payload after Phase 2.
**End-to-end:** Phase 4 cross-source convergence checks.
**Regression:** run existing test suite — `python3 -m pytest tests/ -v` — after each Phase 2 deploy.

---

## Deploy notes

- One Lambda per deploy, 10s wait between (memory rule)
- Use `deploy/deploy_lambda.sh` (memory rule — auto-reads handler config; never hardcode zip names)
- Tag commits with `td-19/<phase>/<source>` for traceability
- After Phase 4 verification: archive this design doc to `docs/archive/` and update `docs/DECISIONS.md` with the convention choice as a permanent record

---

## Doc updates triggered by this work

On Phase 2 completion: `ARCHITECTURE.md`, `SCHEMA.md`, `DECISIONS.md`.
On Phase 3 completion: `CHANGELOG.md` (always), `RUNBOOK.md` (note the migration script).
On Phase 4 completion: archive this spec.
