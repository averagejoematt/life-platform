# HANDOVER — The SS self-sustainability tail (SS-08/09/11) — 2026-06-30

The last documented backlog after the backend serial arc: three self-sustainability items —
counterweights to "fully automatic" content + a flat-day-still-shows-motion view. **SHIPPED + DEPLOYED
LIVE + verified.** With these the full backlog (serial phases 1–4 + SS tail) is cleared and live; only
genuinely-deferred items remain.

**3 items, 2 PRs, all MERGED + DEPLOYED:** SS-09 + SS-11 → **#280**; SS-08 → **#281** (Matthew merged all
PRs — incl. the #279/#282 wrap docs — and authorized "work through them" for the deploys). 0 open PRs.

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

## 2. Deploys — DONE + LIVE-VERIFIED (each behind a `cdk diff`; Matthew authorized "work through them")

- **SS-09 + SS-11 (#280) → `LifePlatformEmail`** — both files bundle there; diff = benign shared-bundle
  re-hash, no layer/IAM. Fail-soft/fail-closed, so no live behavior breaks if a cover or episode is
  skipped. Passive — take effect on the next weekly panelcast / next chronicle-with-cover.
- **SS-08 (#281):** **`LifePlatformCompute`** (`weekly_correlation_compute_lambda.py` + `phase_taxonomy.py`
  — asset re-hash only, no IAM: table-wide PutItem already granted, no layer) + **site-api** via
  `deploy/deploy_site_api.sh /api/what_changed` (verified 200) + **front-end** via `sync_site_to_s3.sh`.
  **Bootstrapped:** `aws lambda invoke --function-name weekly-correlation-compute --payload
  '{"force":true}'` (NB: the real fn name is `weekly-correlation-compute`, NOT `life-platform-…`) →
  `SNAPSHOT#current` populated.
- **Verified live:** `/api/what_changed` serves `honest_null=False, deltas=[], newly_unlocked=1`.
  `deltas=[]` is correct + honest (genesis 2026-06-14 → the prior-30d half is empty, so NO fabricated
  month-over-month motion). The 1 unlock (`habit_pct↔day_grade`, ledger-stamped `2026-06-30`) proves the
  FDR rigor: the run logged "3 significant (|r|≥0.3)" but SS-08 surfaces only the **1 BH-FDR-significant**
  pair, not the loose-|r| heuristic. `main == live`, nothing left behind.

## 3. ✅ The full backlog is cleared + DEPLOYED

- Backend serial arc: phase 1 (coach stances) · 2 (coaches react to protocols) · 3 (Elena recaps) ·
  4 (historical windows) — all shipped + deployed live.
- SS tail: SS-08 · SS-09 · SS-11 — shipped + deployed live. **0 open PRs.**

## 4. ⚠️ OUTSTANDING — only genuinely-deferred items

- **SS-10 — coach-grounding frontier** (its own session by design): push fabrication from
  detect-and-email → block-and-regen at generation time; the known hard item + the `ai_calls.py`
  nutrition guardrail (rides the next layer rebuild).
- **PRE-13** — genome/lab publication granularity (deferred).
- **Watch:** the phase-3 spelled-number recap gap; labs_coach `grounding_flag` across weekly runs; the
  SS-08 month view stays delta-light until ~30 days post-genesis fill the prior-30d half (then real
  month-over-month deltas surface — expected, not a bug).
