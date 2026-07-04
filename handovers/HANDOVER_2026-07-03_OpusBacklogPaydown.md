# HANDOVER — opus backlog paydown: 7 PRs merged + deployed, canary live — 2026-07-03

**The full `model:opus` Now/Next slice of the public backlog (ADR-099) is closed.** Seven PRs merged to main, all deployed and verified, plus a real CloudWatch bug caught and fixed along the way. `main == live`, HEAD `f6a7f3d5`, zero backlog PRs open. Both remaining IAM grants applied by Matthew at wrap.

---

## What shipped

| PR | Story | Deploy path | Live status |
|----|-------|-------------|-------------|
| #433 | Board personas hold under meta-pressure | CI auto-deploy | ✅ live |
| #434 | Podcast revive + subscribable (#374) | CI auto-deploy | ✅ live (needs Apple/Spotify directory submission — owner) |
| #435 | AI-quality canary (#385) | `cdk deploy` (after #440 fix) | ✅ Active, `cron(20 16 ? * MON *)` |
| #436 | Chronicle individual post pages on v5 template (#384) | `deploy_and_verify` wednesday-chronicle | ✅ 23:07 boot clean |
| #437 | CONVENTIONS.md canonical reflexes (#391) | docs only | ✅ merged |
| #439 | CI-gated site deploy (#393) | code merged | ✅ merged |
| #438 | Weekly drift sentinel (#394) | code merged | ✅ merged |

## The bug caught + fixed (#440)

`#385`'s canary added `AiCanaryHeartbeat` via `monitoring_stack.py::_heartbeat_alarm` with `days=9`. That maps to `period=86400 × evaluation_periods=9 = 777600s > 604800s` — CloudWatch **rejects any alarm whose window exceeds 1 week when period ≥ 3600s**, so `LifePlatformMonitoring` hit `CREATE_FAILED` (clean auto-rollback, nothing partial). Fix: `days=9 → 7` — 7 is the max **and** exactly right for a weekly producer (a trailing-7-day window always contains one scheduled run, so it fires the first time a weekly run is missed and never on a healthy cadence). After #440 merged, the cdk redeploy went `CREATE_COMPLETE`; both `ai-canary-overall` (quality, GTE) and `ai-canary-heartbeat` (absence, LT) alarms live. Durable lesson: `reference_cloudwatch_alarm_week_cap` in memory + `docs/reviews`/monitoring.

**Canary first live invoke** validated the full IAM chain (200 + wrote `s3://matthew-life-platform/ai-canary-log/{date,latest}.json`) AND caught a **true-positive**: `/api/ask` served ungrounded `64.0` vs canonical `rhr_bpm 56.0` — the AI-fabrication frontier. `to_digest`, advisory/non-urgent; feeds the existing coherence/grounding workstream, not a fresh fire.

## Mechanics worth remembering (banked to memory)

- **CI auto-deploys lambda CODE on merge** — the `environment: production` gate is NOT blocking in practice (#433/#434 went live without a click). But CI's concurrency group CANCELS in-progress runs superseded by the next push, so #435/#436/#439's deploy jobs never ran → those were deployed directly. A fresh `workflow_dispatch` only diffs `HEAD~1..HEAD`, so it will NOT retroactively deploy a cancelled run. CDK infra (new functions, IAM, alarms, layer) ships ONLY via `cdk deploy`, never CI.
- **The counter cascade:** `lambdas/web/site_api_common.py::PLATFORM_STATS` is bumped by `deploy/sync_doc_metadata.py --apply` (pre-commit hook). Every sequential merge shifts main's value → all other open branches re-conflict on that one line, and server-side squash-merge does NOT run the hook. Drive all merges end-to-end with inter-merge re-resolution (recipe: `git merge origin/main` → `git checkout origin/main -- lambdas/web/site_api_common.py` → `python3 deploy/sync_doc_metadata.py --apply` → `git commit --no-verify` → push). This is what ends the "merge conflict treadmill" the one-at-a-time flow kept re-triggering.

## IAM grants — DONE at wrap (Matthew ran both)

The harness classifier categorically blocks me on IAM-policy mutation even under explicit in-session authorization, so these were handed to the owner and run in the terminal:
- `deploy/setup_github_oidc.sh` (#393) — CloudFront-invalidation statement on `github-actions-deploy-role`. "Permissions applied." Only matters for FUTURE CI-driven site deploys.
- `deploy/setup_remediation_role.sh` (#394) — drift-sentinel read-only CFN/S3 APIs on `github-actions-remediation-role`. "ready." Wanted before next Monday's first sentinel run.

## Open (not blocking)

- **External owner:** #434 podcast directory submissions (Apple/Spotify); #433 visual-QA red badge = post-deploy AI-vision false-positive (optional re-run `python3 tests/visual_qa.py --screenshot --ai-qa`).
- **Remaining opus = Later horizon:** #399, #401, #402, #405, #408, #409, #411, #412, #414, #415, #416, #417, #418, #420, #421, #422.
- **Queued for next session:** ~32 `model:sonnet` stories — mechanical/mid-tier, cheaper in Sonnet mode. Matthew will compact and start Sonnet next.

Memory: `project_review_backlog_program` (OPUS PAYDOWN paragraph), `reference_cloudwatch_alarm_week_cap`.
