# Handover — 2026-06-21 (Strava walk-ingestion bug + DI-2 silent-gap detection)

Second thread of 2026-06-21 (the chronicle/podcast session is archived at
`HANDOVER_2026-06-21_ChroniclePodcast.md`). Driven by Matt: "Strava Walk activities are
silently missing from the platform." Investigated → root-caused → fixed → backfilled →
then built + deployed the monitoring that would have caught it. **PRs #180 + #184 merged
+ deployed + live-verified. `origin/main` @ `b519257d`.**

---

## 1. The bug — evening-PT walks silently dropped (PR #180, fixed + backfilled)

**Symptom.** Strava had 6 walks Jun 14–20; the platform had only 2 (Jun 14 + Jun 20).
`get_freshness_status` showed Strava GREEN the whole time.

**Root cause (NOT enrichment, NOT scope — verified against the live Strava API).**
`strava_lambda.fetch_day` fetched a **same-day UTC** window `[date 00:00Z, date+1 00:00Z)`
but keyed records by the activity's **local** date (`start_date_local`). At the day
boundary those clocks disagree: an evening-PT walk (≥17:00 PT) has a UTC start on the
*next* calendar day, so it fell just past the end of its own local day's window AND was
rejected by the `start_date_local[:10] != date_str` filter on the next day's window. It
fell through the crack both ways — silently (no exception, no log), and freshness stayed
green because midday Hevy `WeightTraining` kept the high-water mark advancing. This was a
long-standing latent bug; it only surfaced now because these particular walks were evening
walks. The model reproduced the DDB contents activity-for-activity (incl. why Jun 15 had no
record at all and Jun 16–19 held only their midday lifts).

**The 4 dropped IDs** (all evening, UTC date ≠ local date): `18936960658` (Jun 15 2.5mi),
`18951911155` (Jun 16 3.0mi), `18951831100` (Jun 16 0mi GPS-drop), `18978915387`
(Jun 18 2.86mi).

**Fix (PR #180).** Bracket the UTC fetch window by **±1 day** so it's a strict superset of
every instant that can map to `date_str` in any timezone; the existing `start_date_local`
filter then assigns each activity to exactly one local date — no gap, no double-count,
timezone-agnostic (correct even when traveling). No schema/read-path/framework change. The
per-activity HR enrichment stays gated by the filter so it isn't multiplied. + 2 regression
tests in `tests/test_ingestion_transforms.py`.

**Backfill.** After deploy, `aws lambda invoke ... {"date_override":"<d>"}` for Jun 15–19
(the hourly gap-filler treats a date with *any* record as "present", so partial Jun 16–19
records would never self-heal). Result: **5 distinct walks** now in-platform Jun 14–20. The
"6th" (the Jun 16 0mi GPS-drop, `18951831100`) is **intentionally** collapsed by the
ingestion `_dedup` into the real 3.0mi walk 17s away — by design, not a drop.

## 2. Why nobody noticed → DI-2 detection suite (PR #184, deployed + live)

**Key finding:** *every* freshness/health check reads **only DynamoDB** (`freshness_checker`,
`get_freshness_status` MCP tool, `qa_smoke`, ingest-liveness) → all see only the high-water
mark, blind to a gap behind it. Two complementary detectors added (**ADR-092**):

- **(A) Strava source-of-truth reconciliation** — daily `{"reconcile": true}` path *inside the
  existing strava lambda* (no new secret-access surface). Pulls a trailing 14d activity set
  from the Strava API, diffs vs the store (dedup-aware — same `strava_id` OR within 120s, so
  the GPS-drop twin isn't a false gap). → `LifePlatform/IngestReconciliation::MissingActivityCount{Source=strava}`
  → digest alarm `ingest-reconciliation-strava`. EventBridge `cron(20 17 * * ? *)` (10:20 PT).
  Reconcile failures return 200 (don't trip `ingestion-error-strava`); rotated refresh_token
  persisted. **This is the only thing that catches a deterministic silent drop** — a
  trailing-refresh would NOT have (the activity was never returned by any fetch).
- **(B) Interior-gap detection** — `freshness_checker` scans each **daily** source's trailing
  14d and flags dates missing *inside* the present span. `DAILY_SOURCES = {whoop, apple_health,
  eightsleep, habitify}`; sparse sources excluded so rest days don't false-fire. →
  `LifePlatform/Freshness::InteriorGapCount` (suppressed on sick days) → digest alarm
  `freshness-interior-gap`.

Pure-function cores are unit-tested: `tests/test_ingestion_transforms.py` (reconcile diff:
flags a drop, clean when present, no false-positive on GPS-drop twin) +
`tests/test_freshness_interior_gaps.py` (7 cases — interior flagged; trailing/leading/contiguous/
<2-date/out-of-window NOT flagged).

## 3. Deploy + live verification (all done)

- `deploy_lambda.sh strava-data-ingestion` + `deploy_lambda.sh life-platform-freshness-checker`
  (both with rollback artifacts).
- `cdk deploy LifePlatformMonitoring LifePlatformIngestion --require-approval never` — created
  the `StravaReconciliation` rule + its Lambda-invoke permission + both alarms. ⚠️ **The
  ingestion stack uses one shared `Code.from_asset("../lambdas")` bundle**, so this re-uploaded
  the current-`main` bundle to ALL ingestion functions (same handler code — a benign
  reconciliation; inherent to how the stack deploys, same caveat as the prior compute-stack note).
- **Live-verified:** reconcile invoke → `api 14 / stored 13 / missing 0`; freshness invoke →
  200, interior scan ran clean; both CloudWatch metrics emitting **0.0** datapoints; both alarms
  present + **OK**.

## 4. State + follow-ups

- `origin/main` @ `b519257d`; local `main` in sync. The earlier panelcast divergence resolved
  itself — those 2 commits live safely on `reconcile/panelcast-quality` (local + origin), ready
  to PR when Matt wants.
- Docs synced: **51 alarms** (was 49; `sync_doc_metadata.py` alarm_count bumped), ADR-092 added,
  this handover. Tools 135 / Lambdas 81 / layer unchanged (no new lambda or tool — DI-2 added an
  EventBridge rule + 2 alarms + reconcile/scan code paths).
- **Open follow-up (not done):** `get_freshness_status` MCP tool is still high-water-mark only —
  it would still report a mid-window hole as green. Reconciliation for other activity sources
  (Whoop/Garmin) generalizes but is a separate opt-in. Both noted in ADR-092 "Out of scope".
- Untracked local files (not mine, left alone): `deploy/_prologue_rewrite.py`,
  `deploy/_publish_week1.py`, the `docs/SPEC_*` + `docs/specs/*` Hevy/recovery spec drafts.
