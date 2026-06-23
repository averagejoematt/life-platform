# Handover — 2026-06-23 (Sleep evidence page redesign — P0→P2 + correlation board)

Third page through the design-review → Claude-Code pipeline (Nutrition, Training, now Sleep). Spec: `docs/SPEC_SLEEP_PAGE_REDESIGN_2026-06-21.md` + `docs/specs/CLAUDE_CODE_PROMPT_SLEEP_PAGE_v1.md`. Spine: **flip retrospective → prospective** — the circadian forecast LEADS, last night demotes to evidence. 23 commits, one per P-item.

**Status: built + locally verified (dark + mobile-390px + the new LIGHT capture). NOT deployed (deploy is a STOP-AND-ASK).** Branch `sleep-page-redesign` is stacked on `training-page-redesign` (which is on `origin/main` + the live-but-unmerged training work) — the sleep chart-kit additions sit on top of training's, so it must NOT be branched off origin/main (would revert training's charts.js). PR is stacked (base = training-page-redesign).

## What shipped
- **Phase 0 (P0.1–P0.9):** forecast hero (0→100 gauge + 4 anchors + lever, two-voice, at-risk MUTED not red) · demote composite score, lead with its inputs · dual-device dumbbell ("agreement, not truth") · regularity + social-jet-lag (empty until a weekend) · stage composition (refuses <4) · environment temp-vs-deep (normalized, observation-only) · autonomic downshift state · declutter physiology · signatures (gauge + trend spine + two-voice).
- **Phase 1 (P1.1–P1.5):** recovery readout ("what sleep defends in a deficit", cross-link) · last-meal cross-link (reuse nutrition eating window) · how-rested / caffeine+alcohol (privacy-tiered) / light-exposure honest empty states.
- **Phase 2 (P2.1–P2.9):** the SELF-POLICING correlation board — new `/api/sleep_correlations` endpoint (compact Pearson + day-lag replica, site-api can't import mcp/), every card n + overlap-weeks + confidence, direction-only <2 weeks (no Pearson/chip), "likely noise" flags, A1–B3 cards, C1 sleep-vs-weight coefficient HARD-WITHHELD, + forecast self-grading placeholder.

## Honesty rails / gates
- C1 sleep-vs-weight coefficient is withheld server-side (`withhold=True`); SURFACING it is a STOP-AND-ASK (false-positive risk in the water-weight phase) — do not un-withhold without sign-off.
- caffeine/alcohol behavioural inputs: not captured (empty state); any public render is a STOP-AND-ASK (privacy).
- The board's gate (`_CORR_MIN_COEF_DAYS = 14`) is the feature — don't lower it.

## Architecture
- **API:** `lambdas/web/site_api_data.py` — `handle_sleep_correlations` (+ `_corr_card`/`_whoop_daily`/`_shift_date`/`_f` helpers); route registered in `site_api_lambda.py`. No DDB schema change.
- **Front-end:** `renderSleep` restructured to parts[], forecast-first. New chart-kit fn `dumbbell`; `stackedDayColumns` gained `minPoints`; `dualLineChart` gained `showGap`; reused `targetSpine`/`correlationChip`. `circadianForecast`/`sleepCorrelationBoard` are sleep-local.
- Local harness `/tmp/sleep_render.py` (route-mocks the 4 endpoints). Deploy: `bash deploy/deploy_site_api.sh /api/sleep_correlations` + `bash deploy/sync_site_to_s3.sh` once approved.
