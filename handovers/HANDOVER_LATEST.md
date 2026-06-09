# HANDOVER — 2026-06-08 (Reset run · A-grade technical sweep · CDK orphan adoption → ∅ · inbox triage)

> A big operator day. The **Monday 2026-06-08 experiment reset is RUN** (genesis live,
> cycle 3). On top of it, a full **CTO/CIO-grade technical hardening sweep** landed,
> **every CLI-created Lambda orphan was adopted into CDK** (`list-functions ∖ CDK = ∅`),
> and a morning of alert emails was triaged to root cause and fixed/hardened.
> **15 PRs merged today (#55–#69).** `main == origin/main`; no open PRs; nothing pending.

> ✅ **State of the world:** all work is merged + deployed + verified. Production is
> healthy. The only "manual" step that ever remains for infra/config changes is a
> `cdk deploy <stack>` — and CI now flags exactly when that's needed (PR #69).

**Previous handover:** `handovers/HANDOVER_2026-06-07_PGSummitFrontDoor.md` (the PG summit / front-door work + the pre-reset design; its "pending" items — the reset and PRs #36/#39 — are all DONE now).

---

## 1. The experiment reset — RUN ✅

- **Genesis** re-anchored to **2026-06-08** (`lambdas/constants.py::EXPERIMENT_START_DATE`).
- **Baseline** = **311.62 lbs** (the real Monday Withings weigh-in; re-pointed from the earlier 306.25 placeholder in **PR #55**). Goal 185.
- SSM `/life-platform/experiment-cycle` = **3**.
- Pre-genesis days (≤ 2026-06-07) correctly read as Day 0 / ungraded. Compute pipeline healthy (character-sheet/daily-metrics/daily-insight/adaptive-mode all ran clean post-reset).
- The two held backend PRs are merged: **#36 (PG-04 native-SES welcome)** and **#39 (PG-10 public-AI hardening + 7 guard tests)**.

## 2. A-grade technical sweep (the "straight-A CTO inspection" pass) — PRs #58–#65

- **Enforced CI quality gates (ADR-080):** black + ruff (already on) **+ mypy tier-1** (budget/auth/inference core: `secret_cache`, `retry_utils`, `phase_filter`, `constants`, `bedrock_client` + broader clean set) **+ coverage regression floor** (`--cov-fail-under=8`; the ~9% offline baseline is by-design — handlers are integration-tested) **+ Lambda size gate** (`tests/test_lambda_size_gate.py`, no new `*_lambda.py` > 2000 lines; 3 grandfathered).
- **god-module split:** `ai_calls.py` 2412 → 1277, extracted `ai_context.py` + `ai_summaries.py` (`ai_calls` re-exports for back-compat). ~1000 F401 + 53 F841 removed and the rules enforced.
- **Governance/docs:** `.gitattributes`, `CONTRIBUTING.md`, root `SECURITY.md`, README CHANGELOG row, docstring pass on the big shared modules, layer **v76**.

## 3. CDK orphan adoption — orphan set → ∅ (ADR-081) — PRs #66, #67

Four CLI-created Lambdas were never in IaC. Now all adopted into CDK via `create_platform_lambda`, each with a **dedicated least-priv role**, shared layer (where used), DLQ, X-Ray, 30-day logs, error alarm, and a CDK-owned schedule preserving its live cadence:
- `ai-expert-analyzer`, `field-notes-generate`, `journal-analyzer` → `LifePlatformCompute`.
- `og-image-generator` (Pillow PNG/WebP share cards) → `LifePlatformOperational` (source was already at `lambdas/web/og_image_lambda.py`; pillow-layer attached, no shared layer — imports none).
- **`aws lambda list-functions ∖ CDK = ∅`.** Adoption was owner-run delete-and-recreate (stateless functions; same names/ARNs). Lambda count 73 → **77** CDK-defined.

## 4. Inbox triage → 3 fixes + 1 CI improvement — PRs #68, #69

The morning's alerts (1 DLQ failure + ~5 "CI/CD Run failed" + ~5 "QA: 1 failure") traced to **two transient root causes**, now fixed/hardened (**PR #68**):
- **og-image `/og` was broken since 2026-03-20** (real bug): `web_stack` handler `web.og_image_lambda.handler` but the Node `.mjs` lives at `lambdas/` root → `MODULE_NOT_FOUND`. Fixed handler → `og_image_lambda.handler`; also fixed a stale S3 key (`site/data/…` → `generated/public_stats.json`, ADR-046). `/og` now returns live-stat SVG (HTTP 200).
- **Whoop refresh-race** (the DLQ incident): EventBridge at-least-once double-delivery reused the single-use refresh token → HTTP 400 → DLQ. `whoop_lambda.authenticate()` now re-reads the secret fresh on a 400 and adopts a concurrently-rotated token instead of failing; only raises on a genuine 400.
- **qa-smoke "Day grade missing"** false positive: it validates *yesterday*, which on reset day is pre-genesis + ungraded. Now skips the grade check when the dashboard date precedes `EXPERIMENT_START_DATE`.

**CI improvement (PR #69):** CI deploys Lambda *code* only; config (handler/runtime/memory/timeout/env/layers) ships only via `cdk deploy`. The existing `cdk diff --all` saw the og-image drift but only as a buried warning. CI now emits a **loud `::warning title=Run: cdk deploy <stack>`** annotation for any merged Lambda **config** change (code/asset drift deliberately ignored — no false positives).

---

## Operator follow-ups
- **None blocking.** Everything merged + deployed + verified.
- **Reminder going forward:** if you merge a PR that changes a Lambda's *config* (not just code) — especially anything in `web_stack`/us-east-1 — CI now tells you the exact `cdk deploy <stack>` to run. CI does **not** auto-deploy `web_stack` (CloudFront — slow/risky by design).

## Known / deferred (genuinely gated, carried from the PG handover)
- **PG-04b** — `subscriber-onboarding` role needs an `s3:GetObject` grant for the day-2 bridge's dynamic cards (IAM/CDK change).
- **PG-07** (reader predict-the-week) — needs the D-05 prediction ledger producing verdicts (~Jun 17).
- **PG-13 / PG-14 productionization / PG-08/09/11/12** — see `HANDOVER_2026-06-07_PGSummitFrontDoor.md`.
- The qa-smoke "Day grade missing" naturally clears tomorrow (2026-06-09) once Day 1 completes + is graded; the genesis-aware check already silences it.

## Verify quickly
- `python3 -m pytest tests/ -q --ignore=tests/test_integration_aws.py` (offline suite green; the live `test_i13` freshness check is reset-day-sparse and CI-excluded).
- `curl -sI https://averagejoematt.com/og` → `200 image/svg+xml`.
- `aws sqs get-queue-attributes --queue-url …life-platform-ingestion-dlq --attribute-names ApproximateNumberOfMessages` → `0`.
- `bash deploy/smoke_test_site.sh` · `python3 tests/visual_qa.py`.
