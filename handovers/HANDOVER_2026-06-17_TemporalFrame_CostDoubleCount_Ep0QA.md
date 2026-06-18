# HANDOVER — 2026-06-17 (PM) · Temporal-frame honesty · cost double-count · Episode 0 + podcast QA automation

> Long session. Everything here is **already deployed live** (deployed from the working
> tree as we went). **PR #150** brings `main` in sync — it's the single open PR and is
> **MERGEABLE**. #146 and #149 were closed (superseded by #150's black fix).

---

## 0. Deploy state — all live
| Area | Deployed | Notes |
|---|---|---|
| Temporal-frame APIs (`/api/vitals`,`/api/sleep_reconciliation`,`/api/circadian`) | ✅ `LifePlatformOperational` | additive `frame`/`night_of` |
| Cockpit + Evidence + charts (temporal regroup) | ✅ `sync_site_to_s3.sh` | live on `/now/`, `/evidence/` |
| Reserved concurrency (i15) | ✅ `LifePlatformIngestion`+`Operational` | quota raised to 100; `test_i15` now passes |
| Cost governor double-count fix | ✅ `deploy_and_verify life-platform-cost-governor` | projected $119→$73, tier 3→1 |
| Episode 0 + QA loop | ✅ `LifePlatformEmail` (×several) + bible → S3 `config/` | Episode 0 LIVE on `/story/panel` |

**Only undeployed bit:** the final QA-gate calibration (commit on #150) ships with the *next* `LifePlatformEmail` deploy — not urgent, the live Episode 0 already meets it.

## 1. Temporal-frame honesty (the original ask)
Sleep/recovery/HRV are wake-date-keyed ("last night → sets up today"); activity is same-day. Data layer was already correct; presentation under-told it. Fixed across all surfaces:
- **B** APIs: `frame`+`night_of` (additive). **A** Cockpit: past→present→future regroup (last-night readiness strip / today pillars / tonight's forecast) + relabeled deltas. **C** Evidence: last-night-vs-today framing + dated chart captions. **D** Story: chronicle prompt anchored to night-of.

## 2. Cost — the real tier-3 root cause (the big find)
`#144` (non-AI trailing projection) merged but the governor **still** false-tripped tier 3. RCA live: it **double-counted Bedrock** — `_non_ai_daily_series` excluded a service literally named `"Amazon Bedrock"`, but Bedrock bills as `"Claude Haiku 4.5 (Amazon Bedrock Edition)"` etc., so the filter matched nothing → Bedrock landed in BOTH the CE "non-AI" total AND the token estimate. Real spend **~$43 MTD** (CE by-service: Haiku $14.50 + Sonnet $10.11 + CW $5.68 + Secrets $4.33 + tax/CE), but it saw $68 → projected $119 → hard cutoff. **Fix:** group by SERVICE, drop any name containing "bedrock". Verified: projected $73, tier 1. **True steady-state ≈ $60/mo; AI ≈ $25/mo and is 100% product Bedrock calls — Claude Code dev is on the Max license, off-bill.** Tier should ease toward 0 as June's reset-inflated trailing-AI ages out.

## 3. Episode 0 — accuracy + craft
The wrong biography (grief / "moved to a city where he knew no one" / parent's illness — none true) was **hand-authored into `config/podcast_series_bible.json`** and the arc *mandated* a high→fall→trauma structure (the jarring ~1:50 cut). Rewrote `characters.matthew` (technical, curious, good at food/fitness, derails on disruption), the `episode0_arc` (Eli enters after the hook; setup via dialogue), the cold open, Eli owning the over-optimization risk, the series open-question close. Added durable **BIOGRAPHY** + **FLOW** guardrails. New: synchronized **transcript + chapters** on `/story/panel` (`wk0.transcript.json`).

## 4. Automated podcast QA (so future episodes self-enforce)
`coach_panel_podcast_lambda.py`: `_craft_check` (deterministic — consecutive-speaker ≤3, monologue >130w, **turn-0 hook exempt** ≤180w) + `_qa_review` (Haiku judge, **fail-open**; rubric: hook / friction / Eli-owns-risk / no-jump / closes-on-bet / **accuracy vs ground-truth**) + **re-roll loop** (`PANEL_QA_MAX_ATTEMPTS=3`, keep cleanest). Weekly path gets a craft re-roll before its editor/safety/HOLD flow. **Proven + calibrated live**: it caught real issues, and exposed two of its own bugs we then fixed — the judge thought "Dr. Eli Marsh" was invented (only had Matt's bio → now names Elena/Eli as established personas) and host/guest confusion. Thresholds calibrated (hook exempt; 4+ is the floor-hog, not 3).

## 5. Gotchas learned
- **Regen is slow now** (3× re-roll + Gemini): invoke with `--invocation-type Event` (async) — the AWS CLI's 60s read-timeout kills a sync invoke mid-run (the lambda's 900s timeout is fine; it completes server-side).
- Coach-panel reads budget tier via a **5-min cache** — after an SSM tier override, wait ~5 min or hit a cold container.
- `cdk deploy` must run from `cdk/` (relative `layer-build` asset path) and with `--require-approval never` (else it prepares a no-execute changeset).

## 6. Follow-ups
- **Merge #150** (single open, mergeable) → `main` reflects live.
- Next `LifePlatformEmail` deploy picks up the QA-gate calibration (optional; live Ep0 already meets it).
- Budget tier should self-ease to 0 over ~a week; if it doesn't, re-check the trailing-AI window.

**Verified:** 2026-06-17 PM. Full suite **1896 passed**, 1 pre-existing live-AWS failure (`test_i9_dlq_empty`, DLQ state).
