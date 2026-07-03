# HANDOVER — 2026-06-16 (AM) · Cockpit circadian tile + cost investigation / governor fix

> Short session after the 2026-06-15 fix-sprint. Shipped the cockpit "tonight's
> forecast" tile (#136, live), then a cost investigation triggered by an AWS
> ">$75 forecast" email. **Headline: the platform is NOT actually over budget**
> — the cost-governor was crying wolf and had auto-paused website AI. Fix +
> trim opened as **#137 + #138 (both OPEN, deploys pending — §0).**

**Prior:** `handovers/HANDOVER_2026-06-15_EliteReviewFixSprint.md` (six PRs #129–#134 from the elite review).

---

## 0. Deploy ledger — ⚠️ TWO PENDING
| PR | Change | Deploy | Status |
|----|--------|--------|--------|
| #136 | Cockpit `/now/` "tonight's forecast" circadian tile | site (`sync_site_to_s3.sh`) | ✅ merged + deployed + live-verified |
| **#137** | **cost-governor: project AI from trailing 7-day window (not lumpy MTD avg)** | **`deploy_and_verify.sh life-platform-cost-governor`** | ⏳ **OPEN/merged? — DEPLOY PENDING** |
| **#138** | cost-governor poll cadence 4h→8h (CE self-cost) | **`cd cdk && npx cdk deploy LifePlatformOperational`** | ⏳ **OPEN — DEPLOY PENDING** |

```bash
# #137 — the real fix (un-pauses website AI)
bash deploy/deploy_and_verify.sh life-platform-cost-governor lambdas/operational/cost_governor_lambda.py
# #138 — CE cadence
cd cdk && npx cdk deploy LifePlatformOperational
# Optional: immediately clear the phantom tier-2 pause (governor will keep it at 0 once #137 is live)
aws ssm put-parameter --name /life-platform/budget-tier --value 0 --type String --overwrite
```

---

## 1. Cost investigation — the answer
**AWS forecast >$75 was mostly transient volume, not a structural blowout.** True steady-state run-rate ≈ **$60/mo** (under the $75 ceiling). Inflated this month by early-June one-time AI (cycle-4 reset + podcast generation) + a heavy dev day; regresses next month.

**Where the money goes** (Cost Explorer settled, half-month → ~/mo): Bedrock Haiku ~$22 + Sonnet ~$9 = **AI ~$29/mo steady** (trailing-7d token truth; the CE-settled $41 was early-month-skewed); CloudWatch ~$9 (50 alarms = $5 + metrics + logs); Secrets ~$7.6 (**almost all = 18 secrets × $0.40 storage**); CE API ~$4.6; tax ~$7; misc ~$3. Lambda ≈ $0.

**The real defect (the user-facing symptom):** the cost-governor projected **$115/mo** and escalated to **tier 2 → paused `/api/ask` + `/api/board_ask`** on a phantom. Root cause: `ai_daily = MTD-AI-total / active-days`, skewed high by lumpy early-month one-time AI (its own `_decide_tier` docstring names this failure mode). Why tier 2 not 3: `_decide_tier` caps projected-tier at `actual_mtd_tier + 1`.

## 2. What shipped
- **#136 — cockpit circadian tile.** `renderSleep`-style async fetch of `/api/circadian` rendered as a "tonight's forecast" strip after the boardline (score/100 + meter, category, prescription, weakest anchor). Fail-quiet (hidden if endpoint errors / `available:false`); present-tense only (hidden in week/journey scope + time-travel). Live-verified on `/now/`.
- **#137 — governor recalibration (real fix).** AI run-rate now from a **trailing 7-day window** (`_ai_cost(now-7d, now)/trailing_days`), clamped to month_start. Extracted pure `_project_month_end()` helper + 3 unit tests. **Safe by construction:** only reduces false escalation; the actual-mtd cap + EARLY_MONTH_DAYS guard + tier-3 hard-stop are untouched. Once deployed → projection ~$60 → tier de-escalates → website AI un-pauses.
- **#138 — CE cadence 4h→8h.** Halves the governor's own ~$4.6/mo Cost Explorer polling. No enforcement loss.

## 3. Verification discipline (dropped 3 plan items on inspection)
- **Tier 3 (cut AI frequency/quality): dropped** — data proved spend isn't high; would've degraded the product for a non-problem.
- **Alarm prune: dropped** — the 6 `ingest-consecutive-failures` alarms are NOT redundant with `ingest-auth-unhealthy` (#131): they catch **hard failures** (counter increments) vs **graceful-skip silent deaths**. Complementary; removing them would reopen the Whoop-49-failure gap to save $0.60/mo.
- **Prompt-caching re-enable: off the table** — D-01 (cross-region Bedrock defeats it; `us.` prefix mandatory).

## 4. Still available, NOT pursued (Matt's call, not urgent — under budget)
- **Secrets consolidation (~$2–3/mo):** bundle rarely-rotated secrets (18→~10) per the `ingestion-keys` pattern. Real lever but can break ingestion auth if rushed — deserves its own carefully-verified PR. Only worth it for margin.
- **Tier-2 AI model-tiering** (weekly/monthly/partner Sonnet→Haiku, ~$2–4/mo): also unnecessary while under budget.

## 5. Verified
#136 live on `/now/` (tile markup + renderCircadian in deployed JS; `/api/circadian` returns real data). #137/#138 unit-verified + `cdk synth` passes; full suite **1860 passed**. Budget tier still **2** until #137 deploys (then expect de-escalation to 0). Plan file: `~/.claude/plans/lively-swimming-rocket.md` (cost plan).

**Verified:** 2026-06-16 (AM).
