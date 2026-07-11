# HANDOVER — 2026-06-17 · Cost telemetry + Hevy title renderer + email-noise RCA

> Long session: cost-governor honesty, AI cost telemetry, the Hevy `Phase-Type-N-Y`
> renderer, a full email-noise investigation, and a doc-accuracy sweep. Several PRs
> merged; **four are open awaiting review/merge + deploy (§Deploy ledger).**

---

## 0. Deploy ledger — what's where
| PR | What | Status | Deploy (Matt) |
|----|------|--------|---------------|
| #137 | cost-governor: project AI from trailing window | ✅ merged + **deployed** | done |
| #138 | cost-governor CE cadence 4h→8h | ✅ merged + **deployed** | done |
| #142 | **G1/G2** AI cost telemetry at the bedrock chokepoint + `ai-daily-spend-high` alarm | ✅ merged | layer + `cdk deploy --all` (pending) |
| #143 | **Hevy `Phase-Type-N-Y` renderer** (ADR-088) | ✅ merged | layer + cdk + MCP build + S3 config (RUNBOOK §ADR-088) |
| **#144** | project **non-AI** from a trailing window too (finishes governor honesty) | ⏳ OPEN | `deploy_and_verify.sh life-platform-cost-governor …` |
| **#145** | Hevy type via exact `hevy_routine_id` link (closes ADR-088 micro-decision) | ⏳ OPEN | layer + cdk |
| **#146** | **`black`-format 9 files** — fixes the ENFORCED CI format gate (main was red) | ⏳ OPEN | none (CI only) — **merge first** |
| **#147** | ai-expert timeout + G1 PutMetricData IAM gap + Garmin alarm→digest | ⏳ OPEN | `cdk deploy LifePlatformCompute LifePlatformMonitoring` |
| — | panelcast HOLD-path IAM (grants exist in code, undeployed) | n/a | `cdk deploy LifePlatformEmail` |

**Merge #146 first** — it un-reds `main`. Then #144/#145/#147 (each will re-run CI clean; #144 already black-patched).

---

## 1. Cost work
- **Governor was crying wolf** (projected ~$116, held a phantom tier-2 website-AI pause). #137 fixed the AI side (trailing window); **#144** finishes it — non-AI now also projects from a trailing window via one `_non_ai_daily_series` CE DAILY call (no extra CE cost), so the day-1 monthly-charge lump (Secrets/Route53/KMS, already banked in mtd) stops being extrapolated. Surfaces `non_ai_per_day`.
- **#142 (G1/G2):** `bedrock_client.invoke()` now meters token usage + `EstimatedCostUSD` per `LambdaFunction` (every AI call, all paths) + a dimensionless aggregate → `ai-daily-spend-high` alarm ($6/day). Removed the duplicate emit from `ai_calls`/`retry_utils`. **Caveat that bit us:** this needs `cloudwatch:PutMetricData` on every AI role → see #147.
- **`docs/archive/COST_FORECAST_2026-06.md`** — the one-pager (infra vs feature fees; steady-state ~$70/mo; lower/reduce/leave-alone; guardrails). June is a ~$90 outlier (reset + reviews + this work); self-corrects.
- **Secrets consolidation = NO-GO** (verified): the easy bundling is already done (`ingestion-keys`); the rest is rotating-OAuth (write-back contention) or actively-read (habitify per ADR-014, todoist via MCP, ai-keys ×14 lambdas). Log retention already 30d. Not worth the auth risk while under budget.

## 2. Hevy title renderer (ADR-088 — supersedes the 2026-05-31 ADR-067 amendment)
- N = performed workouts of this type since `current_started` (per-phase reset); Y = distinct performed since `reset_epoch_date` (deduped by `workout_uid`). Both honest. Type resolved WITHOUT parsing titles: sticker → **exact `hevy_routine_id`** (#145) → nearest-date. dry-run now renders the real title; `force_title` lockdown. Config `current_started`+`reset_epoch_date`=2026-06-16. Seed: next push `Foundation - Push - 2 - 2`, next pull `... Pull - 1 - 2`.

## 3. Email-noise RCA (the big investigation)
Inbox noise traced to **root causes, not volume**:
- **CI "Run failed" (~10, the bulk):** CI's **ENFORCED `black --check` gate** failed every push (9 unformatted files). **#146** fixes. *(Now documented in CLAUDE.md — run `black` before committing. CI pins black 25.9.0; `requirements-dev.txt` mismatches at 26.5.1 — flagged, not yet fixed.)*
- **DLQ repeating emails + 3 alarms:** `ai-expert-analyzer` **timed out at 120s** (8 experts × Bedrock call each), so its async EventBridge events exhausted retries into the ingestion DLQ. **#147** raises it to 600s; **DLQ purged live**. The 2 stuck messages were exactly those failed scheduled-events.
- **PutMetricData AccessDenied spam:** the #142 G1 regression — AI roles lacked `cloudwatch:PutMetricData`. **#147** grants it at the single `_compute_base(needs_ai_keys=True)` point (fixes ai-expert, field-notes, journal-analyzer, adaptive-mode… fleet-wide).
- **Budget alerts ×2:** expected June outlier.
- **Garmin (see §4).** **panelcast (see §5).**

## 4. Garmin RCA — re-auth is futile (you were right)
Logs prove **every server-side OAuth2 refresh is 429'd** (Garmin's 2026 anti-bot / datacenter-IP crackdown; browser auth from a home IP still works). A browser re-auth mints a ~1-day token that **can't be server-refreshed → dies within ~48h.** Unfixable short of a residential proxy (overkill). Core metrics (sleep/HRV/recovery) are covered by **Whoop + Eight Sleep** — Garmin is a best-effort second source for body-battery/stress/VO2max/steps. **#147 routes its auth alarm URGENT→digest.** **Don't re-auth expecting it to stick.** If you want a burst of Garmin-unique data, re-auth knowing it lapses in ~2 days.

## 5. Panelcast wk5 HOLD — correct, not a bug
Ran on **genesis Day-Zero (2026-06-14 reset)** with ~no data → the number-heavy "bet format" + Day-Zero hallucination guard + ER-03 number-gate + editor all correctly refused to fabricate a week-in-review → fail-closed HOLD ("too few clean turns after gate"). **Self-resolves** as cycle-4 data accrues (next Friday). Deferred (Matt's call, low value): a reset-aware data-sufficiency skip so it sits out gracefully post-reset instead of HOLD+alarm; + `_editor_review` tolerating slightly-malformed JSON. HOLD-path IAM (S3+SNS) exists in code → needs `cdk deploy LifePlatformEmail`.

## 6. Doc accuracy sweep (this session)
Audited docs/ + CLAUDE/README. Fixed: shared layer **v78/v76 → v85** (CLAUDE + ARCHITECTURE ×2), ADR count **78 → 88**, layer module count **30 → ~43**, added the **ENFORCED black-gate** to CLAUDE.md, refreshed the CLAUDE.md **Verified** line. (ARCHITECTURE line-3 counts are auto-maintained by `sync_doc_metadata` — left to the hook.)

**Verified:** 2026-06-17. Full suite **1884 passed** (2 pre-existing live-AWS integration failures: `test_i9_dlq_empty`, `test_i15_reserved_concurrency_guard`).
