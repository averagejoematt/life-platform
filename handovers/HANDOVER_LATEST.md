# HANDOVER — The SS self-sustainability tail (SS-08/09/11) — 2026-06-30

The last documented backlog after the backend serial arc: three self-sustainability items —
counterweights to "fully automatic" content + a flat-day-still-shows-motion view. **Built, tested,
PR'd; deploys pending Matthew's merge.** With these the full backlog (serial phases 1–4 + SS tail) is
cleared; only genuinely-deferred items remain.

**3 items, 2 PRs:** SS-09 + SS-11 → **#280**; SS-08 → **#281**. (Plus #279 — the phase-4 wrap docs —
which this wrap stacks on.) ⚠️ I cannot self-merge (harness guardrail) — all await Matthew's merge.

---

## 1. What's built (low-fabrication across all three)

**SS-11 — editorial-image guardrail** (`lambdas/editorial_image.py`). A fail-closed quality/denylist gate
before an auto-picked Pexels cover ships:
- `_acceptable(photo)` — requires a usable landscape (≥1200×600, w>h) AND a description that reads as
  atmospheric texture; rejects people/face/text/brand via a **word-boundary** denylist (so "woman"
  doesn't trip on the "man" substring).
- `_search` scans candidates from the seed offset and ships the FIRST that clears the gate, or **NO
  image** if none qualify (a missing cover beats a wrong one).
- Bundled with `lambdas/` (chronicle + panelcast import it), NOT the layer → no layer dance.

**SS-09 — podcast format rotation** (`lambdas/emails/coach_panel_podcast_lambda.py`). `_episode_angle(week)`
picks one of 6 entry-point lenses deterministically by week, injected into the writer prompt so the show
doesn't feel formulaic by ep 26. The bet/Split/scoreboard scaffold (the show's identity) stays — only the
LENS the episode LEADS with rotates.

**SS-08 — monthly "what changed"** (`lambdas/compute/weekly_correlation_compute_lambda.py` +
`lambdas/web/site_api_data.py` + `site/assets/js/cockpit.js`). The `/now` cockpit's "Month" scope button
was a placeholder; SS-08 fills it with a real view so a flat day still shows monthly motion. **The
planner's key find: fill-in-the-blank, not greenfield** — the 90-day series + FDR correlations are
already computed in the weekly correlation lambda, so SS-08 piggybacks there (**zero new DDB queries, no
new lambda/schedule, no layer dance**):
- `compute_month_deltas` — trailing-30d vs prior-30d averages for 8 headline metrics, emitted ONLY when
  both halves have **≥10 real (non-None) days** (never zero-filled), higher-is-better-aware direction.
- `diff_newly_unlocked` — a **first-seen ledger** (`what_changed` partition: `STATE#first_seen` +
  `SNAPSHOT#current`): a correlation is stamped the first run it crosses FDR significance and surfaced
  only while that stamp is within 30 days → announced ONCE, a flickering pair never re-announced.
- `honest_null` when nothing moved → the front-end shows a calm "steady month", **never fake motion**.
- `handle_what_changed` + `/api/what_changed` (shaped-empty 200 pre-first-run); `renderMonth()` replaces
  the `showScopeSoon` stub. `what_changed` = `EXPERIMENT_SCOPED` in `phase_taxonomy.py` (a test enforces
  every writer is classified).

**Tests:** `tests/test_ss_tail.py` (11) + `tests/test_what_changed.py` (11); both + all related suites
green; ruff + black clean; cockpit.js valid.

## 2. Deploys — PENDING Matthew's merge (then I run them; `cdk diff` first)

- **SS-09 + SS-11 (#280) → `LifePlatformEmail`** — both files bundle there; diff = benign shared-bundle
  re-hash, no layer/IAM. Fail-soft/fail-closed, so no live behavior breaks if a cover or episode is
  skipped.
- **SS-08 (#281):** **`LifePlatformCompute`** (`weekly_correlation_compute_lambda.py` + `phase_taxonomy.py`
  — asset re-hash only, no IAM: table-wide PutItem already granted, no layer) + **site-api** via
  `deploy/deploy_site_api.sh /api/what_changed` + **front-end** via `sync_site_to_s3.sh`. **Bootstrap:**
  `aws lambda invoke --function-name life-platform-weekly-correlation-compute --payload '{"force":true}'`
  to populate `SNAPSHOT#current` immediately (it runs Sundays otherwise).

## 3. ✅ The full backlog is cleared

- Backend serial arc: phase 1 (coach stances) · 2 (coaches react to protocols) · 3 (Elena recaps) ·
  4 (historical windows) — all shipped + deployed live.
- SS tail: SS-08 · SS-09 · SS-11 — built + PR'd (this wrap).

## 4. ⚠️ OUTSTANDING — only genuinely-deferred items

- **SS-10 — coach-grounding frontier** (its own session by design): push fabrication from
  detect-and-email → block-and-regen at generation time; the known hard item + the `ai_calls.py`
  nutrition guardrail (rides the next layer rebuild).
- **PRE-13** — genome/lab publication granularity (deferred).
- **Watch:** the phase-3 spelled-number recap gap; labs_coach `grounding_flag` across weekly runs.
- **PR housekeeping:** #279 (phase-4 wrap), #280 (SS-09/11), #281 (SS-08) await Matthew's merge; I
  cannot self-merge. This wrap (`docs/ss-tail-wrap`) stacks on #279.
