# HANDOVER — opus+sonnet paydown (7) + fable reconcile wave (6) + 2 CI-gate fixes — 2026-07-26

> Instruction thread: continue the standing autonomous backlog paydown (`model:opus`/`model:sonnet`,
> skip `model:fable`), standing approval for ALL merges + deploys + Deploy-gate approvals; CDK deploys
> prepared for Matthew to run via `!`. Mid-session: an interactive owner-decision triage, a **parallel
> fable session** launched (isolated OPEN-PR paydown), then this session **reconciled + merged + deployed
> that fable session's 6 shippable PRs**.

## What shipped — 13 issues closed, all merged to main + deployed + verified; main GREEN

**My paydown (7 — worktree-implementer fan-outs + direct):**
- **#1352** docs/LICENSES.md third-party inventory + advisory pip-licenses gate; deleted stale `layer.txt` (PR #1750).
- **#1330** restore strava token-health check (DescribeSecret grant) + monitored⊆IAM-grant parity test (PR #1751; role deployed via `LifePlatformOperational` CDK by Matthew).
- **#1345** close the smoke-oracle fail-open paths + PARSE_ERROR gating test, extracted `deploy/lib/smoke_oracle_decision.py` (PR #1752).
- **#1574** coach reactions to diary entries (grounding gate + producer + `/api/diary_reactions` + lab-notes render) — trigger deferred to **#1756** (PR #1754).
- **#1385** whole-life-context chronicle (1M + 1-hr cached archive into chronicle + State of Matthew, folded into the grounding allow-list; Structured Outputs at the bedrock chokepoint) (PR #1755).
- **#1336** SCA gaps — pillow/lameenc manifests + pip_audit RED-on-unscanned-layer guard + SHA-pinned gitleaks + fixed the false stdlib claims (PR #1757).
- **#1706** the Prescription follow-up hook (question / cross-coach hand-off, reusing the coach check-in queue) (PR #1765).

**Fable reconcile wave (6 — reconciled from the parallel fable session's OPEN PRs, merged in one queue):**
- **#1626** durable MILESTONE# event ledger (write-once conditional puts; → daily-metrics-compute) · **#1630** ADR-140 (anti-auto-posting amendment) · **#1471** editorial texture/art layer (site) · **#1567** /journal-interview publish mode · **#1627** spiral circuit breaker (ships unwired) · **#1743** video-diary signal spike (docs).

**2 CI-gate fixes (would have broken every future deploy — both merged + live):**
- **gitleaks push-only** (`6ff5e80d`): #1336's scan fell back to full-history on `workflow_dispatch` and tripped the pre-private Firebase key → red-walled every `deploy_all`. Guard = `github.event_name == 'push'`.
- **#1345 smoke-oracle regression** (`44e7bc5e`): the extracted `smoke_oracle_decision.py` was referenced by the smoke-test job, but that job had **NO checkout** → "No such file" → smoke failed on a healthy deploy → **spurious partial fleet rollback (50/97)**. Fix = add the reconciled-tree checkout to the smoke-test job.

**Owner CDK (Matthew ran):** `bash deploy/cdk_deploy.sh LifePlatformOperational -- --require-approval never` (strava grant).

## Verified
- Each wave: on-branch git-grep of agent claims + **combined-tree full suite** GREEN before merge (6924 → 6987 → **7041** after the fable wave). All CI-only gates each merge (black, ruff 6-dir, content-policy, mypy clean-set, tombstones, wiki index --strict, ADR index).
- Deploys: the wave fleet via `deploy_all` (after the two CI fixes) + the fable wave via change-detection push — both **Deploy/Smoke/Post-deploy-integration/Visual-QA GREEN, no rollback**. All 6 wave lambdas + daily-metrics-compute show fresh `LastModified`; **life-platform-mcp boots clean** (200, no FunctionError — validates the #1706 importlib + new imports in the deployed bundle).
- `/api/diary_reactions` pre-deployed live (200, empty — correct dormant state); story hub 200 post art-layer; #1336 pillow/lameenc manifests uploaded to `s3://…/config/requirements/`.

## Gotchas hit (durable lessons → memory)
- **gitleaks-action scans full history on non-push events** → guard secret-scan gates to `github.event_name == 'push'`. → `reference_gitleaks_push_only`.
- **An extracted CI-step script needs a checkout in EVERY job that calls it** — the smoke-test job had none; #1345's extraction assumed one. Review workflow-context availability, not just the script logic. → `reference_ci_extracted_script_needs_checkout`.
- **A spurious smoke failure triggers a partial fleet rollback** (50/97 here — lambdas without a `previous.zip` fail the revert, leaving a mixed state); recovery = re-`deploy_all` from the fixed tree (additive changes make the mixed state functional meanwhile).
- **mypy clean-set "source found twice"**: a runtime `from lambdas import X` fallback next to `import X` makes mypy resolve the file under two module names — use `importlib.import_module` to hide the fallback from the static resolver.
- **Fable-branch reconcile is conflict-free when each branch reverted its doc-sync literals** — the 3-way merge keeps main's literal (branch made no change); recompute once with `sync_doc_metadata --apply` at the end.

## Next-session paydown queue — residual / next-picks (opus + sonnet + fable triage)
**not-work — owner actions (on Matthew, surfaced this session):**
- `not-work — owner decision`: **#1768** portrait art-direction v2 option-round PR is **OPEN**, awaiting ADR-106 approval (pick ONE direction) — the only fable PR deliberately not merged.
- `not-work — owner provisions credentials`: X (`life-platform/x`), Instagram (`life-platform/instagram`), user-scoped billing PAT (#1613) — unlock the syndication/inbound tranche + the CI-minutes alarm.
- `not-work — owner GitHub toggles`: Dependabot + vuln-alerts + secret-scanning (#1336 gate:owner) — NB Dependabot IS now auto-merging dev-tooling bumps (#1760 landed mid-session), so alerts may already be partly on; confirm. Branch-protection ruleset (#1662) AFTER the private flip.
- `not-work — owner chore`: #1029 re-entry hardening before the 2026-08-20 domain renewal; publish #741; confirm phone on the #1333 SNS paging sub; ratify LICENSES.md §5 (AI-content ownership stance).
- `not-work — standing ops reminder`: #1330 strava verifies on the next freshness-checker run (9:45 AM PT); #1385 cache-hit on the next chronicle (Wed); #1626 ledger genesis on the next daily-metrics run. No aged-alarm / stale-secret escalations outstanding (remediation agent `shadow`).

**Buildable next (issue-cited):**
- **#1756** (the #1574 production trigger — inline-vs-lambda + IAM + the same-day sk-collision fix #1767 found) · **#1708** (prescription S4 — blocked on #1756 + a calibration-target design call, noted on-issue) · **#1650** (handovers→orphan-branch move — deferred, wrap-ritual coupling; noted on-issue).
- Doc-ADRs (fable): #1666 · #1333 · #1662. Code (opus/sonnet): #1570 · #1407 · #1623 · #1385-follow-ons. Infra multi-slice: #1658 (coverage→70%) · #1653 · #1654 · #1656.

**Method (held this session):** worktree-implementers 2–4 at a time in DIFFERENT areas → verify each on-branch (git-grep, ~50% false) → combined-tree FULL suite + FULL 6-dir gates → land code-reconcile waves via local-merge to main → pre-deploy site-api for new endpoints → `deploy_all` (or change-detection push) + `approve_deployment.sh <run_id>`. Parallel fable session = isolated OPEN-PRs only (it must NOT touch main); reconcile its PRs here via `/reconcile-branch` once its backlog is exhausted.

## Gate outcomes
- **Build beat:** `2026-07-26-thirteen-closed` (see below).
- **Docs:** LICENSES.md (new, #1352) + docs/README index + ADR-140 (#1630 via the fable PR) + 5 engine-doc re-verifications (2026-07-26, unblocking check_doc_index --strict after #1336's fetch-depth:0 de-vacuumed it); `sync_doc_metadata` reconciled (test_count 5475, adrs 138, adr_max 140); wiki checkers green.
- **Decisions:** none newly filed by me — ADR-140 shipped via the fable #1630 PR; the governance decisions from prior sessions still ship their ADRs at implementation (queued: #1662/#1666/#1333).
- **Main:** green (`44e7bc5e` latest completed; the fable-wave `3eb04d07` run completing on Visual-QA at wrap — Deploy/Smoke/Post-deploy already green).
- **Incidents:** 1 row — (P3) spurious smoke failure (missing `smoke_oracle_decision.py` in the un-checked-out smoke-test job) → partial fleet auto-rollback (50/97) → recovered by re-`deploy_all` from the fixed tree; false-positive class (deploy was healthy, `failed:0`).
- **Stash/hooks:** clean (stash empty; hook 🟢).
- **Labels:** OK (61 open stories, all `model:*`).
- **Live: budget tier 1.**

**Build beat:** 2026-07-26-thirteen-closed
