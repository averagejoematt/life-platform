# Handover — Depth restoration, autonomous night: the Journey and the Day live at the root, every chart answers, three pay-downs — 10 PRs merged, 9 root deploys, one rollback fixed within the hour (2026-11-02)

## Driving instruction
After the v9 launch (2026-11-01) the owner commissioned a parity audit (125 historical capabilities: A17 / B41 / C64 / D3), approved the Journey, One Day, Coaching Room and Laboratory prototypes as product directions (revision 2), sent seven prototype sections to keep verbatim, and decided: Journey at `/data/journey/` linked from the weight page · silhouette deferred · projected date off Start · date parameters on three read-only endpoints · coach lines only through the existing filters · nutrition as logged, missing ≠ zero · DEXA scan two shown missing · fluid in-place Day browsing with URL/history in sync (never navigation-only) · Journey visual-QA tier 1, Day pages tier 3 sampled · chapter progress bar retired, other retirements pending. Then: "yes you can do all the production work and merge … continue this plan … use opus/sonnet accordingly to conserve fable." Start stays frozen until his visual review. Fable ran out mid-wrap; the wrap finished on Opus.

## What is COMPLETE (merged, deployed, verified live)
- **M0 every chart answers + M1 the Journey layers 0–1** — PR #5580 (`69afaa072`) + #5582 (`e5ed127a8`, the phone label fix). #5578, #5579 closed with live proof.
- **Footer "sample content" chip** — PR #5588 (`227e967ff`). #5581 closed.
- **Coach names in disagreement verdicts** — PR #5587 (`cf4ad8050`); the build refuses a raw persona id. #5572 closed.
- **M3a date windows** on `/api/workouts`, `/api/sleep_detail`, `/api/nutrition_overview` — PR #5590 (`5a0eba3ad`), fleet deploy run 41396844099; `?date=` / `?from=&to=` (≤ 92 days, clamped, `window` echoed, 400 on a bad date, bare responses unchanged). #5584 closed.
- **M3b the Day object** — PR #5591 (`2e3fb3804`): `/data/day/<date>/` for all 57 days, readings against their own 7/30-day normals (computed at export), 14-day strip, scrubber, in-place swap with `pushState` + title + canonical in sync (proven on production: zero reloads, back/forward restore). #5585 closed.
- **M4 the Day's layers 2–3** — PR #5592 (`c6b5da702`): session set by set, night by two devices, recovery decomposed, food as logged with the platform's gap flag, engine score (absent shown as absent), coach lines, calls graded and open; every block has its in-place unavailable state. #5586 closed.
- **Chapter pages → their seven days** — PR #5594 (`fd0028536`). #5593 closed.
- **M2 the Journey layers 2–3** — PR #5589 (`c70d77a60`): the pace (the one published rate + 95% interval), the milestones ladder, the body (DEXA baseline, visceral gauge, "Missing: scan two", PhenoAge drivers, no chronological age anywhere), RHR + HRV in device eras, the coaches on the weight. #5583 closed. Root run 41415741597 green.
- All seven owner keep-verbatim sections are on production. Every root deploy ran smoke + visual + AI-vision QA; only the first (M1) rolled back.

## TESTED, merged, NOT run against production (owner-authorised acts only)
- none — everything merged this session is deployed and verified at the root.

## AWAITING THE OWNER
- **Start's visual review** (stabilization) — the new pages are reached from the data room, the weight page and chapter pages, not from `/`.
- **#5596** — the reader-truth smoke's HIGH finding on the Start portrait (Mind "2 entries in 57 days, the last on 9 Sep" vs Connection "the journal went quiet"); holds `qa-smoke-failures` / `qa-smoke-warnings`. Wording change on frozen Start, or a rulings-ledger false-positive call — his.
- **M2 lane's two judgement calls** (PR #5589 body): HRV is absent from the fixture build (adding it would push the v9 front-page reach to 13 > 12); rungs map to the chapter whose week contains the crossing (300 lb gets no chapter row because Week 8 is held) — the prototype used "latest chapter on or before"; one line to switch.
- The remaining proposed retirements (S09/A32, A07 deferred, A27, A30, M11) and the next restoration milestones (Coaching Room CR1–CR4, Laboratory L1–L4, Story HS1–HS3) — not started; his review first.

## Gotchas learned (each in memory)
- A fixed mobile viewBox scaled into a phone column shrinks SVG text below the visual sweep's 11 px floor → rollback; pass the container width as the viewBox, and measure effective text before a root deploy (`reference_a_phone_chart_viewbox_must_follow_the_container`; class tracker #5597).
- A rollback after a www merge restores only the previous build's paths — new pages keep serving beside reverted ones (a mixed root) until the next green run.
- `scripts/publish_snapshot.py` sits at the module-size guard; new mappers go in their own modules (`publish_snapshot_journey.py`, `publish_snapshot_day.py`).
- A live build rewrites `www/owned_paths.json` + `www/reach.json`; always re-export the fixture and rebuild before committing.
- axe cannot be injected under the live CSP; measure it in a `bypass_csp` context only. Playwright taps during smooth scroll miss.
- An Opus lane agent went silent mid-merge for 2.5 h (conflicts resolved, nothing committed); took the merge over by hand. The commit-msg hook requires a Conventional Commit subject even on merge commits (`chore(merge): …`).

## Residual / next picks
- #5597 — the www render gate measures effective SVG text (class tracker for the M1 rollback).
- #5596 — the Start-portrait reader-truth finding (owner's call; Start frozen).
- #5577 — the restoration epic: next milestones (CR/L/HS/DM) need the owner's review of tonight's pages first.
- #5573 — the parallel session's open item: `program_structure.py` still names `romanian_deadlift_*` (held for stabilization); lateral-raise/triceps questions unanswered.
- not-work — the owner's five-reader review of the launched site is his (2026-11-01 ruling).

**Build beat:** 2026-11-02-the-depth-came-back
**Docs:** `docs/INCIDENT_LOG.md` (+1 P3 row, Patterns regenerated) · `docs/alarm_citations.json` (qa-smoke-failures / -warnings re-cited to #5596) · `docs/OPERATING_KNOWLEDGE_LEDGER.md` (+6 rows, snapshot + counters) · `docs/API.md` (the day window, in #5590) · `www/README.md` (the Journey and Day objects)
**Decisions:** none needed — every rule shipped tonight is an owner decision of 2026-11-02 recorded on epic #5577 and its stories; no governance change
**Main:** green (c70d77a6)
**Incidents:** 1 row added — the Journey's first root deploy rolled back on a 9.1 px SVG label (P3, loud; class tracker #5597)
**Stash/hooks:** clean · worktree-reap removed 11 merged lanes; no dirty lane
**Closures:** #5578, #5579, #5581, #5572, #5584, #5585, #5586, #5593, #5583 commented (Shipped + Live proof + Outcome realized) · DoD: scanned=11 hits=0
**Backlog:** Now live at 10 (sonnet 4 · opus 10 · fable 2 startable); filed this session #5577 (epic), #5583–#5586, #5593, #5596, #5597; no promotion needed
**Alarms:** qa-smoke-failures / qa-smoke-warnings re-cited to #5596 (new episode 2026-11-02 06:19Z, reader_truth on the Start portrait); the failures citation names `reader_truth:verdict` while the latest run reads `-` because the daily-period alarm still holds the 06:19Z bucket — decoded, it clears at the first clean daily evaluation; calibration-deadman (#3759) and chronicle-delivery-heartbeat (#4531) unchanged
**CI warnings:** 5 — all the same intentional skip ("SKIPPED in CI — no playwright/chromium installed here", #3640); no action
**Ledger:** none — no standing machinery shipped (the web gate's new chart-answers check is a check inside the existing gate)
