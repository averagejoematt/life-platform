# HANDOVER — 2026-06-05 (backlog burndown + features + a visual/AI test harness)

> **A long multi-thread session:** reconciled the backlog against live AWS, shipped several
> verified fixes/features to production, **caught + averted a KMS landmine**, fixed a **flagship
> Cockpit bug that 503'd ~16h/day**, and built a **Playwright + Claude-vision UI test harness**
> — which immediately found a real bug that's now fixed. 17 commits.

> 🔴 **READ FIRST — two things the next session MUST know:**
> 1. **Nothing is pushed.** `main` (local) is **17 commits ahead of `origin/main`**. CI has NOT
>    run on any of this. **First action: review + `git push`** (it'll re-deploy via CI, matching
>    what's already live — see below).
> 2. **Several Lambdas were deployed DIRECTLY** (`update-function-code`) from these *local* commits,
>    so **deployed code is ahead of `origin`** until you push. Deployed this session: **site-api**
>    (4× — Tier-3 empty states, `/api/source_freshness`, the Cockpit `/api/character` fix, the
>    coach-analysis fix; live sha `F2TBZgcS…`), **freshness-checker** (S-06), **anomaly-detector**
>    (L-01), **life-platform-mcp** (L-02), plus **site syncs** (pipeline page, Day-Grade Replay,
>    a11y, feed.xml). Rollback artifacts for the direct deploys are in `/tmp/*_ROLLBACK_*.zip`
>    (ephemeral — gone on reboot; the durable rollback is git).

**Previous handover:** `handovers/HANDOVER_2026-06-03_OperationsCost.md` (v4 live + ops/cost; ADR-074/075).
**No engine/schema/pipeline changes that alter data.** All work is read-side (site-api, site, QA, docs) plus two layer-module edits that ride the next layer rebuild.

---

## What shipped (by thread)

### 1. Backlog burndown (reconciled against live AWS)
Re-checked the data-blocked items against real CloudWatch/SES/SQS and closed the stale ones:
- **L-11** DLQ → 0 (drained). **D-03** AI-spend ranking captured (`coach-narrative-orchestrator`
  dominates at ~8M input tok/14d, ~8× the next). **N-01** alarms 4/5 cleared. **B-03** done.
- **D-01** finding: `daily-brief` writes prompt-cache it never reads (once/day vs 5-min TTL) — see S-07.
- **D-04** root cause: SES open-tracking simply **not enabled** (`TrackingOptions: null`), not Apple-Mail masking.
- Closed **L-01/L-02/L-05/L-06** (commits `0e41f11`); **L-10** verified a non-issue (historical comment).
- **Tier-0** (`d28423f`): corrected **CLAUDE.md tool count 140→133** — the docs were right; the
  `grep -c '"name":'` guidance over-counts (nested schema names). True source of truth is the AST
  count (`deploy/sync_doc_metadata.py`). Also dropped deprecated `utcnow()` in `html_builder.py` +
  `vacation_fund.py` (both **layer modules** — ships on next layer rebuild, not deployed for a P3).

### 2. S-06 — freshness SLO alarm de-noised (deployed) — `3bde46d`
`slo-source-freshness` was permanently ALARM. Fixed `freshness_checker_lambda.py` so
`StaleSourceCount` counts only **infra/pipeline** staleness (OAuth/API breakage = actionable);
**behavioral** sources (`measurements`, `food_delivery`) still show in the report but don't trip the
SLO. Also `todoist` 24h→48h (it reports the *prior* completed day, so 24h false-fired daily).
Zero new metrics/alarms (reuses the existing one). Verified live: StaleSourceCount 3→0.

### 3. "Pipeline status" Evidence dashboard (deployed) — `e039be9`
New read-only **`GET /api/source_freshness`** (`lambdas/web/site_api_data.py`) → per-source
fresh/stale/behavioral-stale/paused, querying each source's latest `DATE#` via
`begins_with("DATE#")` (sidesteps the `YEAR#` rollup) and phase-filtered like the rest of the site.
New Evidence topic **`/evidence/pipeline/`** (`scripts/v4_build_evidence.py` + `renderPipeline` in
`evidence.js`). Turns the freshness signal + the paused sources (ADR-074) into an honest reader
feature. Live, verified.

### 4. Cockpit `/api/character` 503'd ~16h/day + Day-Grade Replay (deployed) — `1de678b`
**Real flagship bug:** character-sheet compute writes the **prior day's** sheet daily at **16:30
UTC**, so the freshest record is routinely 1–2 days old — but `handle_character` only accepted
today/yesterday, so from 00:00 UTC until the 16:30 run it returned **503**, degrading the Cockpit's
level/pillars. Fixed to take the **latest available** `DATE#` record (+ its prior, for deltas).
**Day-Grade Replay:** each pillar now carries `score_delta`/`xp_earned` (record-over-record),
surfaced as a compact "score N ▲+X" chip in the existing cockpit pillar disclosure (stays within
the locked glanceable design). Also widened `test_i17` 2→3 days to match the compute cadence.

### 5. a11y (deployed) — `486d6ce`
Two **verified** WCAG-AA fails fixed (most audit a11y claims were false positives — skip-links
already work, constellation links already keyboard-accessible): `--ink-faint` contrast (dark
3.25→4.68, light 2.43→4.88) in `tokens.css`; constellation `<svg>` `role="img"`→`role="group"` so
its interactive pillar links are exposed to screen readers. (The waveform's `role="img"` is correct
— left alone.)

### 6. QA tooling
- **`deploy/smoke_test_site.sh` rewritten for v4** (`db079e4`) — it was pre-v4 and emitted **58
  false failures** (old v3 URLs that now 301, v3 chrome that's gone). Now 65/0; checks the real
  three-door structure + today's new endpoints, with a stale-copy guard. (Complements the qa-smoke
  *Lambda*, which covers data/output health.)
- **NEW: visual + AI-vision test harness** — see §7.

### 7. Visual + AI-vision UI test harness (NEW capability)
**The answer to "QA the rendered graphs" on a data-driven site where pixel-diff breaks daily.**
- **`tests/visual_qa.py`** — modernized the stale v3 Playwright harness for v4: real routes,
  inline-**SVG** checks (not Chart.js canvas), the **cockpit pillar interaction**, responsive
  overflow @390px, per-chart element crops; dropped the vestigial `cf-auth` (site is public).
- **`tests/visual_ai_qa.py`** — feeds each screenshot to **Claude via `bedrock_client.invoke()`**
  (Haiku, vision, ~$0.001/img) for a structured verdict. Validated both ways: a sparse-data state →
  correctly "ok"; a deliberately-broken render → "high" with specifics. Degrades cleanly (Bedrock
  error / budget tier-3 → AI-QA skipped, deterministic checks stand).
- **CI** — new **`visual-qa`** job in `.github/workflows/ci-cd.yml` (post-deploy, **ADVISORY**:
  `continue-on-error` + `|| true`). `playwright==1.58.0` pinned in `requirements-dev.txt`;
  `/qa full` updated. ADR-076.
- **It immediately found a real bug** → §8.

### 8. coach-analysis 400 (found by the harness, fixed, deployed) — `f823779`
The harness's **interaction layer** caught it: clicking 4 of 7 cockpit pillars
(`movement`/`metabolic`/`relationships`/`consistency`) → `/api/coach_analysis` **400 "Invalid
domain"** (the cockpit sends *character-pillar* names; the endpoint keyed on *coach-domain* names).
Fixed in `site_api_coach.py`: alias `movement→training`, `metabolic→glucose`; for the two pillars
with **no dedicated board coach** (`relationships`, `consistency`) return a graceful 200/`null` so
the cockpit fallback shows cleanly; genuinely-invalid domains still 400. Verified live: all 7 → 200;
harness re-run → Cockpit **PASS**.

### 9. KMS landmine — AVERTED (no change made) — `02d9cda`
The roadmap/audit said "remove orphan KMS grants from `role_policies.py`." **Verified against live
AWS first:** the ~32 remaining `KMS_KEY_ARN` grants reference **`444438d1` — the ENABLED DynamoDB
SSE-KMS key** (`life-platform-dynamodb`), NOT the deleted orphan S3 CMK (`5c50ca02`, already removed
2026-05-24). **Removing them would have locked every Lambda out of DynamoDB.** Recorded in BACKLOG
so it's never re-attempted. **Do not touch those grants.**

---

## ⚠️ Operator follow-ups (deliberately NOT auto-done)
1. **`git push`** the 17 commits (review first). CI will re-deploy, matching what's already live.
2. **Enable AI-QA in CI** — a scoped `bedrock:InvokeModel` grant is staged in
   `deploy/setup_github_oidc.sh` (`BedrockVisionQA` statement); it's a high-severity IAM change, so
   **operator-run** (`bash deploy/setup_github_oidc.sh`). Until applied, the `visual-qa` job runs
   the deterministic layer and AI-QA self-skips.
3. **Flip `visual-qa` advisory→gate** after ~1 week of tuning: remove `continue-on-error` + the
   `|| true` in the job (a FAIL — deterministic or AI-high — then blocks; rollback's `needs`
   excludes `visual-qa`, so advisory failures never trigger a rollback).
4. **`utcnow()` fix** (Tier-0) ships on the **next layer rebuild** (`html_builder`/`vacation_fund`
   are layer modules) — no urgency (P3).

## Known / deferred
- **S-07** (daily-brief cache waste, ~$0.02/mo) — diagnosed, deferred; touches the shared layer,
  root cause unconfirmed, not worth a layer redeploy. Do NOT blindly disable caching. (BACKLOG S-07.)
- **D-04** SES open-rate — needs a privacy decision (enable CNAME tracking) or accept unobservable.
- `relationships`/`consistency` pillars have **no board coach** by design (graceful null) — if you
  add coaches, extend `_coach_map` in `site_api_coach.py`.

**Verify quickly:** `bash deploy/smoke_test_site.sh` (65/0) · `python3 tests/visual_qa.py` (cockpit
now PASS) · `/api/source_freshness`, `/api/character`, `/api/coach_analysis?domain=movement` all 200.
