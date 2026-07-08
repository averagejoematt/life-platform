# HANDOVER — high-value pay-down: 13 issues shipped end-to-end (entire Now milestone incl. #780 SEC-02), live alarms == code — 2026-07-07

> Instruction: "read memory and handover to put a plan together to efficiently pay down as
> much of the high value open issues in git as possible in this session. I authorize you to
> do edits, deploys, merges." Plan: 8 parallel worktree subagents (opus/sonnet) on 10 issues
> + driver-inline #809/#797; #780 excluded (needs Matthew at a laptop to re-paste the
> rotated MCP URL into the claude.ai connector — offer stands).

## What shipped (12 issues, PRs #848–#856; all MERGED + DEPLOYED + LIVE-VERIFIED)

- **#788+#807** (PR #855, Now) — /now/ static-rendered: baked `<noscript>` cockpit proof
  (level+tier, Body/Mind/Consistency, six pillar rows, as-of stamp) via new
  `scripts/v4_build_cockpit_proof.py`, wired into `sync_site_to_s3.sh`; JS-parity
  `_js_round()` (Python banker's rounding diverges at .5). First-visit level explainer,
  localStorage-dismissed. Live: `Character level 12 · Foundation` in the delivered HTML.
- **#789** (PR #850, Now) — home-page "Is he okay this week?" friends/family surface:
  deterministic plain-language read from the already-fetched /api/character +
  /api/journey (zero new calls, zero AI); ADR-104 absent states ("not measured this
  week"), post-reset refusal state, as-of stamp. Live on /.
- **#790** (PR #853, Now) — COST-01: 48 per-lambda ingestion-error alarms retired
  (`error_alarm=False` in compute+email stacks) per ADR-116; **premise correction: the
  audit's "no DLQ" count was stale — all 49 already had `dlq=local_dlq` in CDK AND live**
  (driver-verified live config). ~$4.80/mo off the fixed floor. alarm_count 113→65.
- **#809** (PR #856 + live ops) — the 113(65)-vs-122 live-vs-CDK gap CLOSED: driver audit
  found 9 orphan alarms (2026-05-25 pre-CDK script batch; table in the #809 comment).
  Dispositions: 5 async ops lambdas got `dlq=local_dlq` (ADR-116 pattern) + orphan alarms
  deleted; journal-enrichment already had DLQ → deleted; site-api-ai is SYNC → real CDK
  alarm `site-api-ai-errors` (≥3/hr); mcp `life-platform-recursive-loop` adopted in place
  (CFN upserts by name); redundant `mcp-canary-latency-15min` deleted. **Live count now
  exactly 67 == CDK 67.**
- **#811** (PR #852) — SEC-04: `wrap_untrusted_reader_text()` (ai_context.py; preamble +
  fence, tag-forgery stripped case-insensitively) at every prompt-construction site:
  /api/ask, /api/board_ask, board follow-ups, stored INTERACTION# episodic replay, weekly
  compression. Render-time wrapping so pre-fix stored records are covered. 10 new tests.
- **#799** (PR #854) — CI import gate `tests/test_lambda_map_imports.py` (deploy_critical):
  I7 = every mapped handler's un-guarded imports resolve inside the real build_bundle.py
  bundle; I8 = cdk_only annotations correlate with a real sibling dep. Only explicit
  ImportError catches count as guards (the I4 broad try/except would make it vacuous).
- **#794** (PR #849) — site-api dual ownership resolved: ground truth was that #781 already
  unified packaging; fixed the STORY (stale layer comments, ADR-112, deploy.md, CLAUDE.md)
  + `tests/test_deploy_bundle_paths.py` enforces both channels stay on build_bundle.py.
- **#798** (PR #848) — `.claude/commands/wrap.md` + `reconcile-branch.md` — the two
  most-repeated rituals as commands (this wrap used /wrap's steps).
- **#805+#806** (PR #851) — jargon/framing copy sweep: pillars introduced in plain
  language, co-movement/couplings/correlatively de-jargoned, "argues about it" → "offers
  different takes" across home + coaching/method shells AND their generators
  (v4_build_coaching/evidence — the shells are generator output, editing HTML alone drifts).
- **#797** (driver, wrap-time) — session state single-written: MEMORY.md Active Work
  archived 21 terminal entries to `project_shipped_archive.md`, CLAUDE.md status block
  shrunk to a pointer paragraph; wrap-time rule recorded in both.

## Deploys (authorized in-session)

`cdk deploy --all` exit 0 (all stacks UPDATE_COMPLETE; the 48+ alarm deletes + DLQ wiring
+ 2 new alarms + full-tree code asset fleet-wide incl. site-api with #852) ·
`sync_site_to_s3.sh` ×2 (second post-wrap so version.json == HEAD) · orphan-alarm CLI
deletes. Verified: smoke_test_site **67/67** · full suite **3901 passed** (only the 1
known live-AWS failure, test_ddb_key_contracts; i16 lives in the ignored integration
file) · /api/status 200 · live alarms 67 == synth 67 · /now/ noscript proof live ·
visual QA (see status block for final verdict).

## Gotchas (this session)

- **Agent-worktree edits can leak into the main tree** (macOS case-twin, known): #799's
  CONVENTIONS.md edit appeared staged in MY tree mid-merge-train. Preserved to scratchpad,
  cleaned, and the agent's own PR carried the same hunk — no loss. Check `git status`
  before every merge-train step when agents are live.
- **`gh pr merge` in a broken `&&` chain can still fire**: #851 got merged by a failed-
  looking chain (checkout aborted → later commands ran on the branch). Merged content was
  verified correct after the fact. Keep merge commands OUT of long chains.
- Three agents died mid-run on transient `Connection closed` API errors — `SendMessage`
  to the same agentId resumes them with worktree+context intact; all three finished.
- The empty-reconcile case: a copy-only PR merges main with 0 literal changes —
  `git commit -m reconcile` exits nonzero and kills the chain. Guard with
  `git diff --cached --quiet ||`.
- CFN adopts an existing same-name alarm silently (PutMetricAlarm upsert) — used
  deliberately for `life-platform-recursive-loop`.

## #780 SEC-02 — DONE this session (Matthew was at his laptop)

Rotated the MCP Function URL live (delete+recreate → new url-id; old host 403-dead, new
host enforces the Bearer boundary), Matthew re-pasted the new URL into the claude.ai
connector and reconnected (verified). PR #857: `lambdas/mcp_url.resolve_mcp_url()` — canary
+ qa-smoke now DISCOVER the URL at runtime via `lambda:GetFunctionUrlConfig` (both roles
granted, scoped to the MCP fn ARN), so no URL is committed and future rotations are
self-healing; CDK env vars + McpFunctionUrl CfnOutput removed; ARCHITECTURE/INFRASTRUCTURE/
OPERATOR_GUIDE + integration-test host + setup_waf.sh redacted. Deployed
LifePlatformOperational + LifePlatformMcp. **End-to-end proof: the i14 canary-MCP
integration test now PASSES** (live canary discovered the new URL, derived the Bearer,
reached the MCP endpoint). Gotcha: the #809 `life-platform-recursive-loop` alarm couldn't
be adopted by CFN while a live orphan of the same name existed — CFN early-validation
refuses ("already exists"); had to delete the live orphan, then CDK created it fresh (the
"CFN upserts by name" assumption is FALSE for change-set validation). Residual (durable
follow-up, not filed): the URL-possession auth model is the root weakness — either a real
per-request gate claude.ai can satisfy, or a CI check that fails on any committed
`*.lambda-url.*.on.aws` MCP host. Full detail in private memory
security-r22-mcp-token-exposure.

## Next picks (Now milestone is now EMPTY)

- **#804** static-render /coaching/ (the #855 cockpit-proof pattern now makes this
  mechanical) · **#803** chronicle cadence/gap · **#808** Haiku spend attribution (top AI
  line) · **#812/#813** fable AI items (golden-harness generalization; prediction-
  gradability triage — scorecard still 0-graded-ever).
- Older Matthew decisions: #417 re-stamp timing/format · Ingestion/HAE deploy call ·
  #740 edit pass · untracked docs/reviews/REVIEW_BUNDLE_2026-07-06.md (commit or delete).

Prior session archived at `handovers/HANDOVER_2026-07-06_mobile-bug-bash.md`.
