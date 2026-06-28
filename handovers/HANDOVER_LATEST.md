# Handover — 2026-06-28 — Accuracy remediation **Phase 3 + 4b COMPLETE, DEPLOYED, live-verified**

The truth-audit remediation (5-phase program) is **done**. Phases 1, 2, 4a, 5 + HRV-unit shipped last session (#220–224); this session shipped the **Phase 3 core** (canonical record + coach grounding) and the **Phase 4b coherence tail**, deployed them, and live-verified. Matthew gave express in-session permission to run the deploys. `main` @ post-#227.

## Shipped this session
- **PR #226** — Phase 3 + 4b (merged + deployed).
- **PR #227** — ruff import-sort fix in `site_api_ai_lambda.py` (merged). **This file's import block had been red on main's ENFORCED ruff gate since #220** — a masked failure that silently skipped Unit Tests/Plan/Deploy on every main push. #226 surfaced it; #227 cleared it. *(Lesson: Phase 1 left main's lint red and nobody caught it — the CI-masking pattern again. Verify the main CI/CD run is actually green after a merge, not just the PR checks.)*

## Phase 3 (the structural "no contradictions" fix) — DEPLOYED, layer v91
Root cause of both HIGH coherence findings: the same fact derived by independent paths that drift. Fix = one computed record is the shared source; AI prose is grounded to it.

- **3b — canonical vitals + one-day whoop selection** (`daily_metrics_compute`, `daily_brief`, `ai_summaries`, `ingestion_validator`):
  `computed_metrics` now stores the chosen day's `recovery_pct`/`hrv_ms`/`rhr_bpm` + `protein_g_avg`/`target`/`floor` (units in field names). `daily_brief` + `ai_summaries` read ONE `primary_whoop` (today-if-finalized-recovery else yesterday) for the vitals block, recovery line, readiness, AND the narrative → no 30-vs-86 split. `ingestion_validator` gained 0-100 recovery / sane HRV·RHR·protein range guards (WARN tier).
  **Live-verified:** `computed_metrics/DATE#2026-06-27` → recovery_pct 30, hrv_ms 25.18, rhr_bpm 64, protein_g_avg 140.7, target 190, floor 170.
- **3a — coach shared facts + grounding** (`ai_expert_analyzer`):
  `_load_canonical_facts()` reads the latest `computed_metrics`; an AUTHORITATIVE FACTS block is injected into every coach's cached system prompt + the integrator (intake 140.7 labelled apart from target 190 / floor 170; HRV pinned ms). Nutrition coach reads the target from facts, not the hardcoded `190`. Post-gen `validate_ai_output(health_context=facts)` WARNs on >25% recovery/HRV/RHR/weight deviation + HRV-in-bpm.
  **Live-verified (regenerated all 8 + integrator):** integrator "protein stuck at 140", nutrition "locked at 140", labs "intake 140.7g against a 170g floor" (170 now correctly the FLOOR, not hallucinated intake), glucose no longer cites protein. `/api/coach_analysis` live: cites 140 + 170, **not 190** — the 140/170/190 contradiction is gone.

## Phase 4b (caption/state coherence) — DEPLOYED (site sync)
`site/assets/js/evidence.js`, `evidence.css`, `dispatches.js`. Four real findings fixed; the 5th ("/story/journal Nothing published") was a **verified false positive** (that tab is Matt's own blog — `blog.json` genuinely empty; the 3 posts are the chronicle, a different tab):
- **Paused supplements** dimmed + "paused" badge + reason (the `paused` flag was ignored; 3 paused mushroom-stack compounds showed as active).
- **Autonomic caption** "downshifting into recovery" now gated on HRV actually being up (was firing on high recovery alone).
- **Rate-tempo bars** relabel data-limited windows with their real span ("13-day") + drop identical windows (the 30/90-day bars were identical to the 12-day).
- **Chronicle week label** derived genesis-anchored (Prologue · Part I/II vs Week N) — `posts.json` shipped two "Week 1"; the raw `week` also collided the list-selection id → now id = unique post date, `week` kept for podcast lookup.
**Live-verified:** assets carry `supp--paused`, the span relabel, and `Prologue · Part`.

## Deploy record (Matthew authorized this session)
- Layer dance: `build_layer.sh` → `cdk deploy LifePlatformCore` published **layer v91** → redeployed `LifePlatformCompute LifePlatformEmail LifePlatformOperational` + `LifePlatformIngestion LifePlatformMcp`. **Fleet uniform: 70/70 consumers on v91** (the Plan layer-consistency gate needs uniformity — same lesson as the 2026-06-24 v89 stall; redeploying only Compute/Email/Operational leaves ingestion/MCP behind).
- `sync_site_to_s3.sh` for Phase 4b. CF invalidated.
- **`accuracy_audit.py --live`: 0 HIGH, all pages resolve, no impossible values.**

## Privacy cleanup
Deleted leaking at-rest chronicle records (not live — feed verified clean): `DATE#2026-04-07` (the one Matthew flagged) **and** `DATE#2026-03-10` (its Layne-Norton-fabricated-quote twin, tombstoned cycle-3; Matthew OK'd). **Left** `DATE#2026-03-03` + `DATE#2026-06-11` — "the Goggins cycle" is a willpower *metaphor*, not a fabricated quote (privacy_guard fail-closes on the bare surname; legitimate reference, nothing live). The deeper rescan checked more content fields than `purge_stale_chronicle_drafts.py` does — consider widening that script's `_CONTENT_FIELDS` + handling `status != "draft"` tombstoned records.

## Deliberately skipped (note)
- **Did NOT re-invoke `daily-brief`** (it re-sends Matthew's email; the 11am brief already went out, day-selection is unit-tested + the canonical record is verified). Next 11am brief validates the primary_whoop fix naturally.
- **Did NOT run the full 50-agent `/accuracy-review full`** — verified the specific 15 findings directly + `accuracy_audit --live` 0 HIGH. Run `/accuracy-review full` if you want the exhaustive milestone re-attestation.

## Post-deploy discovery (after the #228 docs commit) — ONE open follow-up
Greening the ruff gate (#227) **unmasked the gating Visual+AI-vision QA job**, which had been `skipped` on every main push since #220 (Lint red → everything downstream skipped). It now **runs and fails on ONE pre-existing bug:**

- **Home page (`/`) horizontal overflow at 390px — content exceeds viewport by 16px.** All 25 other pages pass (24 passed, 1 failed, 26 warnings) — *including every page Phase 4b changed*. This is a **v5-redesign-era bug** (`site/index.html`, #216/#217), NOT the accuracy work — it was masked behind the red lint. (The one earlier run where visual-QA executed, #217 `431ba4cd`, also failed on it.)
- **Impact:** reds the CI run (a "CI failed" email) but does **NOT** roll back deploys — `rollback`'s `needs` excludes visual-qa. All live accuracy work is safe.
- **Deferred to next session (Matthew's call), browser-verified.** Memory: `project_home_overflow_followup`. Don't blind-patch `overflow-x:hidden` (clips content) — reproduce at 390px (Chrome MCP / `tests/visual_qa.py --screenshot` / `/qa`), find the ~16px-too-wide element. Home CSS is external (no inline culprit in `index.html`).

## State (final)
`main` @ post-**#228** (Phase 3+4b **#226**, ruff-greener **#227**, docs **#228**). **Main CI: Lint ✓ Unit Tests ✓ Plan ✓ Deploy ✓** — the only red is visual-qa on the pre-existing Home overflow above. **0 open PRs.** New `tests/test_phase3_grounding.py`. CLAUDE.md layer ref reads **v91**; top Verified line dated 2026-06-28. Live build-fingerprint `f7369057` (deployed from worktree, content-identical to merged `3927e1a5`) — cosmetic. Memories: `project_truth_audit` (COMPLETE), `project_home_overflow_followup` (new, OPEN), `reference_ci_masking_and_creds`.

## Follow-up RESOLVED (continuation later 2026-06-28) — #230, main now fully green
The Home overflow is fixed, deployed, and verified. Matthew gave express deploy permission again for this continuation.
- **Real root cause** (bisected + browser-verified — NOT a content element / inline CSS): the decorative **`.hero::before` warm-bloom** (`site/assets/css/story.css`, `inset: -6% -4% auto -4%`) bleeds the glow ~4% (~15.6px) past each hero side; at full-width mobile the right bleed lands off-screen and pushes document width (16px @ 390px, 31px @ 768px). `body{overflow-x:hidden}` never contained it because `visual_qa._mobile_overflow` measures `document.documentElement.scrollWidth` (the `<html>` box).
- **Fix:** `overflow-x: clip` on `.hero` (one line). `clip` (not `overflow:hidden`) keeps `overflow-y: visible` so the bloom still bleeds DOWN into the arc; no scroll container / sticky side-effects. Visually lossless.
- **Diagnosis method worth remembering:** every hero *child* fit inside the viewport on `getBoundingClientRect` yet `scrollWidth` was still +16 — the tell that it's a pseudo-element / non-flow decorative box. Found it by bisecting (hide subtrees, re-measure) then reading `getComputedStyle('.hero','::before')` (width 421px, inset -15.6px).
- **Deploy + verify:** PR **#230** merged `5de962f0`; `bash deploy/sync_site_to_s3.sh` (CF invalidation `I8UJWG87NATYDNA0TEAWJN2QAC`); live `version.json` build `066e3656` (worktree commit, content-identical — cosmetic). Live overflow **0 at 360/390/414/768px**; `visual_qa.py --page /` → **1 passed**; re-ran the red `ci-cd.yml` run `28312156590` `--failed` → **Visual+AI QA success → entire run green**.
- A pure-CSS/site change triggers only the lightweight **"v4 site gate"** workflow (it passed), NOT the full `ci-cd.yml` (path-filtered to Python/Lambda/CDK) — that's why re-running the prior failed `ci-cd.yml` job was the way to officially green the gating visual-QA.
- Memory `project_home_overflow_followup` → **RESOLVED**.

## Next-session quick-start
1. Main is fully green and 0 open follow-ups. Optional: full 50-agent `/accuracy-review full` for exhaustive re-attestation (the 15 findings were verified directly; `accuracy_audit --live` = 0 HIGH).
