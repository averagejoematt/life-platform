# HANDOVER — 2026-05-29 (Evening session)

**Previous handover:** `handovers/archive/HANDOVER_v8.0.0_2026-05-19.md`.
**This session covers:** Backlog spec items #2–#10 sweep + WAF removal + a 6-blocker CI bug-hunt.
**Latest HEAD on push:** `c62a731` (CI run #26673378064 inflight as of handover write).

---

## State of the world at handover

| Surface | Status |
|---|---|
| **Genesis** | 2026-05-30, baseline 304.62 lbs (provisional — Saturday re-anchor pending). |
| **Shared layer** | v62. No bump tonight. |
| **Budget tier** (SSM `/life-platform/budget-tier`) | 1 (coaches paused) when WAF was alive; should auto-flip to 0 at next hourly `cost_governor_lambda` run now that WAF spend is gone. |
| **Remediation mode** (SSM `/life-platform/remediation-mode`) | `auto`. |
| **WAF** | **DELETED.** `life-platform-amj-waf` detached from CloudFront + deleted. Subscribe rate-limit ported into the Lambda. |
| **email-subscriber** | Last CDK deploy 03:27 UTC with rate-limit code. Then a x-forwarded-for fix in `c62a731` is being deployed by CI via the now-region-aware deploy script. |
| **CI** | Was silently failing for ~6 weeks. Five blockers cleared tonight. Sixth (region-blindness) found post-deploy. |

---

## What I built tonight

### A. Backlog #2–10 sweep

| # | Outcome |
|---|---|
| #3 Cost/cache/SES audit | `docs/audits/COST_CACHE_SES_VERIFICATION_2026-05-29.md`. Real Bedrock MTD $4.27, daily-brief cache 0% read, SES opens 0 (Apple Mail Privacy). |
| #5 [VERIFY] sweep | `docs/audits/VERIFY_SWEEP_2026-05-29.md`. 3 PR1 bugs FIXED, IA fragmentation persists → #9 GO. |
| #4 Reserved concurrency | `deploy/stage_reserved_concurrency.sh` staged + gate-checked. Waits for AWS Support case 177921309700709 to approve 10→100. |
| #7 Email dark mode | 4 of 5 emails already had it. Added the missing `prefers-color-scheme: dark` block to the sick-brief template in `daily_brief_lambda.py`. |
| #2 TD-11 Phase 1 | Habitify ingestion now writes `habit_statuses` enum alongside legacy binary `habits`. 9 unit tests pass. |
| #6 WR-47 Pause Mode | **Deferred** (legitimately multi-session, schema dep). |
| #9 IA restructuring | `/achievements/`→`/character/`, `/data/`→`/platform/data/`, nav + sitemap pruned. |
| #8 Intelligence rebuild Phase 1 | New routes `/api/hypotheses` + `/api/intelligence_summary`. UI build deferred. |

### B. WAF removal saga

1. Built in-Lambda subscribe rate-limit (DDB atomic counter, 60 req / 5min / IP, fail-open).
2. Wrote `deploy/finish_waf_removal.sh` (detach + delete + preflight probe).
3. You ran the script based on my "preflight passed" signal. Preflight was bogus — it returned 400 from the old code path, not proof of new code.
4. WAF was deleted before the new rate-limit code was deployed → `/api/subscribe` unprotected for ~30 min.
5. New CI run pushed. Then hit 5 cascading CI failures before the deploy went through.
6. Deploy succeeded but updated the wrong region (us-west-2 twin instead of us-east-1 production). Fixed deploy_lambda.sh to be region-aware. Re-pushed.

**Lesson burned in:** "preflight passed" needs to be a positive proof of the new behavior (e.g., 61 rapid POSTs see a 429), not just "endpoint responds."

### C. TD-11 Phase 2 — the actual phantom-fail fix

The real consumer-side bug was that `completion_pct` counted today's `pending` habits as failures, making mid-day character scores read ~0%. Fixed at the source in `habitify_lambda.py:transform()` — `pending_count` excluded from denominator. Past-day records unchanged. Consumer code (streak calc, character engine) needs **no changes**. 12 unit tests pass. Backfill script written (`backfill/backfill_habitify_v2_schema.py`), not run.

### D. The CI bug-hunt — six blockers cleared

CI hadn't deployed cleanly in ~6 weeks. Cleared in order:

1. **IAM-secrets linter** — `KNOWN_SECRETS` missing `github-dispatch-token` from ADR-064.
2. **ARN convention drift** — dispatcher policy hardcoded `…/github-dispatch-token-*` (literal dash before wildcard) instead of using `_secret_arn()`. Linter regex stripped `*` but not `-`, so the extracted name didn't match KNOWN_SECRETS.
3. **Source-references linter** — sibling KNOWN_SECRETS in `test_secret_references.py` missing both `hevy` and `github-dispatch-token`.
4. **My own test pollution** — `test_habitify_status_resolution.py` stubbed `http_retry` in `sys.modules` unnecessarily, shadowing the real module when the full suite ran in alphabetical order.
5. **AWS CLI pagination** — `aws lambda list-layer-versions` paginates at 50 items; our layer is v62 → returned `62\n12` (the `LayerVersions[0].Version` per page). The CI layer-verify compared `"62"` against `"62\n12"` and flagged every consumer as mismatched. Hilarious error: `"daily-brief is on layer v62, expected v62"`. Fixed with `--no-paginate`.
6. **`deploy_lambda.sh` region-blindness** — hardcoded `REGION=us-west-2`. Production `email-subscriber` is in us-east-1, but a vestigial us-west-2 twin existed. CI was happily updating the twin while production stayed stale. CI's "success" was lying. Fixed with per-Lambda region in `lambda_map.json`, preflight that fails loud, and `tests/test_lambda_map_regions.py` R1/R2/R3 to close the bug class permanently.

---

## What still needs to happen

### Verification (post-CI)
- Confirm CI run #26673378064 deploys cleanly to us-east-1.
- Re-run the 65-POST smoke test:
  ```bash
  for i in $(seq 1 65); do curl -s -o /dev/null -w "%{http_code} " \
    -X POST -H "Content-Type: application/json" \
    -d '{"email":"smoke@gmail.com"}' \
    https://averagejoematt.com/api/subscribe; done; echo
  ```
  Expect ~60 `200`s then `429`s.

### Operator actions (agent can't do)
- **Saturday 2026-05-30**: weigh in, then re-run `python3 deploy/restart_pipeline.py --genesis 2026-05-30 --override-weight-lbs <real-weight> --apply` to lock the true Day-1 baseline.
- **AWS Support case 177921309700709**: check status. Once approved, `bash deploy/stage_reserved_concurrency.sh`.
- **PAT rotation reminder**: calendar item ~2026-08-27 (90d from current PAT creation).

### Pending engineering tasks (each its own future session)
- **#102** — Intelligence page tabbed UI (5 lazy-loaded panels). API plumbing is live.
- **#98** — WR-47 Phase 2 Pause Mode (multi-session). TD-11 Phase 2 dependency now clear.
- **#106** — Migrate subscriber-token HMAC off the Anthropic API key onto a dedicated `life-platform/subscriber-token-secret`. Security-relevant — AI-key rotation currently invalidates all subscriber tokens.
- **#108** — Port the x-forwarded-for fix to vote/follow/checkin/nudge/submit_finding in `site_api_social.py`. Same bug shape, allows vote-stuffing.
- **#90** — Sentinel-stub dead code in 18 Lambdas (safe + harmless; removal is cosmetic churn).
- **#101 backfill** — `python3 backfill/backfill_habitify_v2_schema.py --apply` to populate historical `habit_statuses` (≤60 days, ~60s runtime).

---

## Commits this session (oldest → newest)

| SHA | Subject |
|---|---|
| `b58f071` | sprint(spec): #3 #5 #4 #7 #2 #9 #8 — audits + IA cleanup + Habitify Phase 1 + Intel API plumbing |
| `a96f415` | fix(stats): correct stale PLATFORM_STATS + clear AnthropicAPIFailure findings |
| `4caab16` | sprint: TD-11 Phase 2 + WAF prep + subscribe rate-limit + ai_calls signatures |
| `f14ba0d` | fix(ci): IAM-secrets linter — register github-dispatch-token secret |
| `9bf93fd` | fix(ci): SR1 linter — register github-dispatch-token + hevy in source linter |
| `e11af98` | fix(ci): test_habitify_status_resolution polluted sys.modules with stub http_retry |
| `d6a30ce` | fix(ci): layer-verify paginated AWS CLI returns multi-line version |
| `3a0bfcb` | fix(deploy): deploy_lambda.sh region-aware via lambda_map.json per-entry region |
| `c62a731` | fix(subscribe): use x-forwarded-for as source_ip behind CloudFront |

---

## Operational notes worth remembering

- **AWS CLI paginates at 50 by default.** Any `--query` over a list returns one match per page → multi-line output. Always `--no-paginate` (or `--max-items`) when you expect a scalar.
- **CloudFront → Lambda Function URL source IP is the CloudFront edge IP, not the client.** Use `x-forwarded-for[0]` for any IP-based logic (rate-limit, audit, abuse detection).
- **Lambdas can have silent twins across regions.** Production `email-subscriber` is us-east-1 only — `tests/test_lambda_map_regions.py` enforces this going forward.
- **The remediation auto-merge gate is in `auto` mode.** PRs touching only the allowlist with ≤60 lines merge automatically. The production deploy approval gate still stands — auto-merge does not auto-deploy.

---

**Verified:** 2026-05-29 evening PT.
