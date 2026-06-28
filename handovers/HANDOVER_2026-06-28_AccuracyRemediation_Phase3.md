# Handover — 2026-06-28 — Accuracy remediation, **Phase 3 + 4b to finish** (the grounding gate)

Pick this up in a FRESH session. The truth-audit remediation is a 5-phase program; **Phases 1, 2, 4a, 5 + the HRV-unit slice are DONE and largely DEPLOYED LIVE**. What remains is **Phase 3's core** (the number-grounding gate + coach shared-snapshot + the cross-day day-selection) and the **Phase 4b coherence-tail captions**. Matthew has authorized deploys ("do the deploys today" / "do it all today") — so build → merge → deploy → live-verify each, same as this session.

`main` @ latest (≈ `d099ad85+`). Layer **v90** live (`privacy_guard` + `weight_trend`). Plan file: `~/.claude/plans/soft-baking-toast.md`. Review: `docs/reviews/EDITORIAL_ACCURACY_REVIEW_2026-06-27.md`. Memory: `project_truth_audit`, `project_traffic_digest_measurement`, `feedback_squash_merge_drops_unpushed_commits`.

## Done this session (9 PRs: #217-224 + layer #222)
- **Phase 1 (privacy)** #220 — `lambdas/privacy_guard.py` (fail-closed real-name+vice gate), board_ask personas → fictional (patel/cole/driggs), chronicle publish gated, `deploy/purge_stale_chronicle_drafts.py` (ran --apply, 6 drafts deleted; 1 `changes_requested` 2026-04-07 still flagged for Matthew's manual review). **DEPLOYED + verified.**
- **Phase 2 (impossible numbers)** #221 — `lambdas/weight_trend.py` (one shared regression rate+projection); `daily_metrics_compute.compute_ctl_atl_tsb()` returns CTL/ATL clamped ≥0 + stores weekly_rate/rate_provisional/projected_goal_date; daily_brief + site_api READ them. **DEPLOYED + verified** (public_stats: ctl 543.3, weekly_rate −7.33, projection null).
- **Phase 4a (harness)** + **Phase 5 (CI gate)** #223 — 5 method-tier topics now `/method/` not `/data/` in `visual_qa.py`/`site_review_bindings.py`; `tests/accuracy_audit.py --live` (per-page resolve + impossible-value) is now a **gating CI step** in `.github/workflows/ci-cd.yml` visual-qa job. Merged, no deploy.
- **HRV-unit** #224 — field_notes key→`avg_hrv_ms` + prompt rule; `ai_output_validator` Check 13 (`_HRV_WRONG_UNIT_RE`, WARN). **DEPLOYED** (Compute). NB: the validator is a LAYER module — its guard activates on the **next layer rebuild** (i.e. when Phase 3 rebuilds the layer).

## REMAINING — Phase 3 core (the structural "no contradictions" fix)

### 3a. Coach number-grounding gate — kills protein 140/170/190 (HIGH)
**Problem:** the 8 coaches each call `gather_data_for_expert()` independently (`lambdas/intelligence/ai_expert_analyzer_lambda.py:725`); nutrition target hardcoded `190` (`:171`); Labs/Glucose coaches narrate "170g protein" — a number NOT in their data (hallucination). The integrator gets only prose (`generate_synthesis` ~955-1099).
**Fix:** (a) build ONE shared snapshot once and pass to all 8 + integrator (replace per-coach gather); read nutrition target from facts not `190`. (b) Add a **grounding gate** at the post-generation validate (`generate_and_cache` ~829-843): every number the coach cites must be in its snapshot (reuse `lambdas/er03_gate.py::er03_check(text, allowed_numbers=...)` — the exact mechanism panelcast uses; build allowed_numbers from the snapshot) → on violation, regenerate (≤2) or drop the claim. `ai_output_validator._check_hallucinated_metrics` already exists but only runs when `health_context` is passed — wire the snapshot in.

### 3b. Cross-day day-selection — kills recovery 30 vs 86 (HIGH)
**Problem:** `daily_brief_lambda.py` picks the whoop record inconsistently — the vitals block uses `data.get("whoop") or data.get("whoop_today")` (`~1943`), the recovery line prefers `whoop_today or whoop_yest` (`996-998`), and the AI narrative uses `data["whoop"]` (yesterday) via `ai_summaries.py:40`. Same page → two recoveries.
**Fix:** define ONE `primary_whoop` = the most recent whoop record that has a finalized `recovery_score`, set `data["whoop"]` = it before the AI call, and use it for the vitals block too. (gather sets `whoop`=yesterday `whoop_today`=today at `daily_brief_lambda.py:371,559`.) Best landed as part of widening the canonical `computed_metrics` record to hold the chosen-day vitals (recovery/HRV/RHR with units), which both the numbers and the narrative read — the Phase-3 canonical-record pattern Phase 2 started.

### 3c. (Strongest, optional) widen the canonical record
Phase 2 already made `daily_metrics_compute` the single computer of ctl/atl/weekly_rate/projection (stored in `computed_metrics`, read by daily_brief + site_api). Extend it to also hold the chosen-day vitals + protein avg+target **with units in the field names** (`hrv_ms`, `protein_g`), and migrate the coach snapshot + chronicle + field_notes to read it. Backfill the cycle. This is what makes 3a/3b structural rather than local.

## REMAINING — Phase 4b coherence captions (MEDIUM, mostly site/build/prompt)
From the review's medium tier: captions that contradict their own chart (evidence.js autonomic "both lines rising = recovery" on a low-recovery day, `site/assets/js/evidence.js` ~1822); identical "30-day/90-day" rate bars when only ~13 days exist (label honestly); `/story/journal/` "Nothing published" while the feed has posts (`dispatches.js`); paused supplements shown active; chronicle week-numbering (two "week 1"). Each re-checked against its data; re-run `/accuracy-review` after.

## Deploy mechanics (learned this session — reuse exactly)
- **Layer dance** (if you touch any layer module — er03_gate, ai_output_validator, weight_trend, privacy_guard, OR add a new one): `bash deploy/build_layer.sh` → bump `cdk/stacks/constants.py:SHARED_LAYER_VERSION` (90→91) → `cd cdk && npx cdk deploy LifePlatformCore` (publishes v91) → redeploy consumers `LifePlatformCompute LifePlatformEmail LifePlatformOperational`. New layer modules MUST also be added to `deploy/build_layer.sh` MODULES **and** `ci/lambda_map.json` shared_layer.modules (the `test_lv4` gate). Verify consumers attach the new version (`aws lambda get-function-configuration ... Layers`).
- **Non-layer lambda change** (e.g. ai_expert_analyzer, daily_brief code, field_notes): just `cdk deploy` its stack (ai_expert_analyzer + field_notes = `LifePlatformCompute`; daily_brief + chronicle = `LifePlatformEmail`; site-api + site-api-ai = `LifePlatformOperational`). cdk re-bundles the shared `Code.from_asset("../lambdas")` (benign).
- **Verify**: `python3 tests/accuracy_audit.py --live` (0 HIGH); regenerate public_stats by invoking `daily-metrics-compute` then `daily-brief` (the latter re-sends Matthew's brief email — fine); for coaches, invoke `ai-expert-analyzer` then `curl /api/coaches` / `/api/coach_team`. Re-run the full truth-audit workflow (`/accuracy-review full`) at the end → all 15 verified findings should clear.
- `worktree-v5-coherence-redesign` worktree; `gh pr merge` errors "main already used by worktree" are cosmetic (merge succeeds). Full suite creds-blanked must stay green; the doc-sync pre-commit hook auto-stamps counts.

## Residual notes
- board_ask persona KEY "norton" remains (its NAME is fictional Webb; the key is a JSON property, low risk) — rename to "webb" if doing a board_ask pass.
- CTL/ATL magnitude is kJ-scale (543/1316) — NOT front-end-rendered (training page uses /api/training_overview), so the clamp≥0 is sufficient; don't chase normalization.
