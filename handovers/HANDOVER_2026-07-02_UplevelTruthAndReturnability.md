# HANDOVER — /uplevel driver + truth repair + returnability slices — 2026-07-01/02

> **The `/uplevel` session driver was built, then run three times: (1) the six-honesty-leaks truth repair, (2) "What the machine suspects" (the hypothesis engine's public surface), (3) three returnability slices. Eight PRs #305–#310 (+ the driver in #305), ALL MERGED; #305/#306/#307 DEPLOYED + LIVE-VERIFIED in-session (Matthew authorized deploys); #308/#309/#310 merged awaiting one `sync_site_to_s3.sh`** *(NB: a later session's deploys may already have shipped them — `curl /version.json` vs the merge SHAs to confirm before re-syncing).*

## 0. The driver — `.claude/commands/uplevel.md` (shipped in #305)

`/uplevel` = orient on the v5 brief → multi-agent Workflow survey (5 lane lenses + 2 fresh-eyes audience lenses, **every finding adversarially verified** — the ~50% FP filter) → rank against the north star → ship the flagship slice end-to-end in a worktree. `/uplevel <lane or idea>` skips the broad survey (directed mode). First survey: 42 agents, 35 verified findings. The living scoreboard + remaining board lives in memory `project_uplevel_driver_and_board`.

## 1. Truth repair — PR #305 (+ #306), DEPLOYED + LIVE-VERIFIED

Six verified honesty leaks on skeptic-facing surfaces, all fixed:

1. **Correlations `p 1.000 · FDR ✓`** — serving layer's `float(... or 1)` coerced the stored rounded-to-zero p=0.0 to 1.0; strength label said "weak" on r=0.843. Faithful p (`None` when absent), |r|-derived strength, featured-filter fixed; front-end renders `<0.001` / `—`, collapses the n<5 zero-row wall. `tests/test_correlations_serving.py`.
2. **Field notes "zero minutes"** — the gatherer read per-activity fields off Strava DAY rollups; the published W26 note publicly called it "a data entry issue I should flag". Reads `total_moving_time_seconds` + `activity_count`. **Then the regenerated note flagged ITSELF ("20 nights of sleep in one week") → second bug, same class: whoop `DATE#<day>#WORKOUT#<uuid>` sub-records counted as nights → `_query_day_records` filters all six week-gathers to exact day keys (#306).** W26 regenerated twice; final live note reads "7 complete nights". Regen recipe: `REMOVE ai_generated_at` on the WEEK# record, then invoke `{"manual_week": "2026-WNN"}` — **no force flag exists**.
3. **Home hero** — hardcoded "this is week one" fired in week 3; stale weight paired with a live day-counter. Copy derives from `week_n`/`weighin_span_days`; `/api/journey` serves `last_weighin_date`; a calm quiet-stretch line off `/api/presence` (muted, fail-quiet).
4. **Pipeline board** — strava/macrofactor dropped by 483ecb11, hevy never listed (added to freshness_checker + BEHAVIORAL_SOURCES too), food_delivery threshold drifted 90d vs 14d. `tests/test_freshness_board_mirror.py` pins board == checker.
5. **Protein dual truth** — /data/ hardcoded 190 and called it the "floor" while coaches grade the canonical 170 floor. `nutrition_overview` serves `protein_floor_g` + floor-graded hit pct from the SAME profile keys as `daily_metrics_compute`; every front-end "floor" word grades the floor. `tests/test_protein_contract.py`.
6. **PLATFORM_STATS provably stale** (303 tests vs ~1,290 actual; 138 tools vs 144; 65 ADRs vs 85) — `deploy/sync_doc_metadata.py --apply` now REWRITES the discoverable fields in `site_api_common.py` (judgment fields untouched); `tests/test_platform_stats_truth.py` reds CI on drift. **⚠️ The pre-commit hook runs this sync but leaves `site_api_common.py` UNSTAGED — `git add` it or the drift test reds main after adding tests (bit once, amended).**

**Deploy method for the two bundled lambdas** (`field-notes-generate`, `life-platform-freshness-checker`): the playbook's surgical zip of `lambdas/` with `_ASSET_EXCLUDES` + `update-function-code`, verified **file-list-identical to the live CDK asset** before shipping (size delta = compression only). Postflight fleet-consistent; smoke 66/66.

## 2. "What the machine suspects" — PR #307, DEPLOYED + LIVE-VERIFIED

The hypothesis engine (weekly Sundays; falsifiable bets with a pending→confirming→confirmed/refuted lifecycle + numeric-citation verdicts) had ZERO public surface — `/api/hypotheses` + `/api/intelligence_summary` unfetched by any page; discoveries showed static config templates. Now: live bet cards on `/protocols/discoveries` (domain-pair title, status badge — **ember earned by `confirmed` only, `refuted` muted never red** — verdict trail once graded, founding evidence behind a details toggle, "N earlier bets expired undecided" honesty line, template fallback for empty windows: 30-day hard expiry / post-reset); "open bets" fig + cross-link on `/method/intelligence`. Server: `handle_hypotheses` now serves `last_checked`/`last_evidence`. Cold-start-aware (state-derived copy, self-retires when the first grades land). `tests/test_hypotheses_serving.py`. **WATCH: first live grades land Sunday ~Jul 5 — the decided-state UI is mock-proven only; glance at the page after the Sunday run.**

## 3. Returnability slices — PRs #308/#309/#310, MERGED

- **#308 "since your last visit"** (cockpit): `/api/changes-since` (v3-era, zero non-legacy callers) ported into the cockpit's fire-and-forget self-hiding idiom. ≥12h localStorage gap (legacy `amj_last_visit` key reused), stamp advances only after a successful read, silent on first visit/failure/empty/time-travel. **The `ts` param is EPOCH SECONDS.** Verified over the live API with a seeded 4-day stamp (HRV 39→50 climbing · sleep 8.2→7.4 declining — honest both ways).
- **#309 waveform time-travel** (home): scored bars are anchors into `/now/?date=` (aria-labeled, keyboard-focusable; no-data days stay spans; `role=img`→`group`). Click-through proven: genesis bar → dated sheet → "Read Week 1" chronicle link.
- **#310 chronicle-listen cycle-safe join**: `podcastEpisode()` read the SEASON-1 feed by bare week number → current Week 5 would have inherited a May episode. Now the panelcast feed + a ±14-day date window; Week 1's silently-missing listen link surfaced (`wk1.wav`). **The zombie season-1 `chronicle-podcast` weekly cron was flagged here → retired by a later session (#312).**

## Durable lessons (this session)

- **The AI accusing its own pipeline is a bug CLASS**: any gatherer doing `len(items)` over a DDB partition with sub-records (whoop WORKOUT#, etc.) or reading per-activity fields off day rollups will make a coach/note "flag" phantom data errors publicly. Grep for other `len(_query_source(...))` consumers before trusting counts.
- **Playwright route-handler trap**: `page.route` handlers get `(route, request)` positionally — a keyword-default second param gets clobbered by the Request object. Use `def handler(route, _request=None, _mock=x)`.
- **Local render-QA**: `service_workers="block"` + `wait_until="domcontentloaded"` (networkidle hangs on the SW-era pages); proxy `/api/*` to live for realistic data, or route-mock for state you can't reproduce (the decided-hypothesis UI).
- Verified-fix loop works: the #305 drift test fired on its own PR's new tests twice and the sync corrected it both times.

## State at wrap (2026-07-02 ~11:00 PT)

`main` == #310 merged, 0 open PRs from these sessions; live = #305/#306/#307 deployed + verified (site-api, site, both lambdas, W26 regenerated); #308/#309/#310 awaited one site sync (check whether a later session's deploy already carried them). Memory `project_uplevel_driver_and_board` is the running scoreboard — later sessions have already continued the board (#311 chart parity, #312 zombie-cron retirement per its updates).
