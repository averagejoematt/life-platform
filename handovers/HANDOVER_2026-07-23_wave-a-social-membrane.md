# HANDOVER — Wave A shipped: Social Membrane inbound + eng-excellence + coach-correction seeding — 2026-07-23

> Instruction thread: "read handover → clean-tree + budget-tier check → FIRST (before fan-out):
> (1) seed the coach-corrections ledger with last session's #1687 dry-run findings; (2) file the
> Coach Correction Loop LATER stories S5/S6/S7 under #1687. THEN pay down backlog — fan out
> worktree-implementers: Wave A (parallel independent) = Social Membrane #1671/#1672/#1673 +
> eng-excellence #1652/#1657; Wave B (big-bang, alone) = #1656 mypy / #1658 coverage / #1655 CI;
> #1620 outbound last; /plan #1686; gate:owner #1662/#1666/#1650 stop for sign-off." Working rules:
> VERIFY every agent finding by git-grepping the branch; full suite (no -x) before any merge; batch
> merges/deploys into ONE numbered ask; flag site/** auto-deploys; CDK deploys unpiped +
> `--require-approval never`. Mid-session Matthew: "a" (seed all 6 rows) · "yes accept it" (#1703
> F401 removal) · "i approve" + "yes run the ingestion cdk deploy, i approve all deploys" · answered
> #1686 sourcing = "3" (coach web-access) · approved #1709 + #1710 merges · "yes wrap".

## What shipped (all merged to main; deploy status per item)

**FIRST tasks:**
- **Coach-corrections ledger SEEDED** — 6 rows written to `USER#matthew#SOURCE#coach_corrections` via a one-off `write_correction` seed script (idempotent, fixed IDs), read back clean, all `status=open`: 4× `stale-baseline` ("315 lbs" + "Day 1" + two more of the 4-of-5 class), 1× `ungrounded-behavioral` ("you maintained your eating window today"), 1× `cross-coach-inconsistency` (protein 170g/190g). The qa_archive was wiped by the cycle-10 reset, so rows came from the epic #1687 body (Matthew confirmed "a" = all 6). This is the flywheel's first data.
- **Coach Correction Loop LATER stories filed** — **#1697** (S5 prompt-memory, opus) · **#1698** (S6 pattern-extraction→gate, fable) · **#1699** (S7 no-ungrounded-behavioral gate, sonnet), all Later under #1687.

**Wave A — 5 PRs merged + deployed:**
- **#1700 (#1652)** root-clutter ratchet guard — 19-dir allowlist + 7 support READMEs. Test/docs only, no deploy.
- **#1701 (#1673)** fail-closed auto-publish sensitivity gate (`broadcast_sensitivity_gate.py`, reuses `privacy_guard`; seam `sensitivity_status=="cleared"` via `gate.cleared_filter_expression()`). **DEPLOYED** LifePlatformIngestion (bedrock grant on youtube role).
- **#1702 (#1671)** post-enrichment → coach signals (`social_enrichment_lambda.py` + `social_signals.py`; membrane filter BEFORE Haiku; reuses journal `_ground_causal_hints`; consumers `ai_context`/daily-brief). **DEPLOYED** LifePlatformIngestion (new `social-enrichment` Lambda + role) + daily-brief.
- **#1703 (#1657)** retired blanket lint waivers — Matthew **accepted** the agent's judgment call to remove 17 dead F401 imports (overrode the "keep F401" instruction) after I verified tool count 69==69 + orphan/wiring tests green. Config only.
- **#1704 (#1672)** Broadcast feed `/story/broadcast/` + `/api/broadcast` (facade cards, 3 registries, seam reconciled to `"cleared"`). **DEPLOYED** site-api + site.

**Wave B (big-bang, one at a time):**
- **#1709 (#1656)** mypy-strict PARTIAL (Progresses, not Fixes) — clean-set 19→124 modules (`lambdas/`+`web/`), 7 of 14 disabled codes enforced, 9-module DIRTY denylist. Annotations-only (verified `Success: 0 issues, 124 files`). `mcp/` still out of scope. No deploy.
- **#1710 (#1658)** coverage-floor PARTIAL — floor 40→47 + **up-only ratchet guard** + 52 real behavioral tests (retry_utils/ai_output_validator/vacation_fund). 70% infeasible (61.5k-statement tree). No deploy.

**Also:** #1686 (Coach's Prescription) decomposed → **#1705–#1708** (S1–S4, Later); sourcing decision recorded = **coach web-access** (new capability, own ADR at implement time). Reconciles: `test_count` 4960→4991→4993→5045, `lambda_count` 96→97, endpoints 119→120.

## Verified
- Every agent finding git-grep-verified on-branch before merge (allowlist=19 dirs, seam literals, IAM grants, membrane-before-Haiku, mypy 124-file clean run, ratchet guard bites, behavioral tests real not theater).
- **Combined-tree full suite** (all 5 Wave-A branches merged locally + reconciled): **6551 passed / 0 failed**. Per-PR suites green.
- Deploys: LifePlatformIngestion UPDATE_COMPLETE (146s, drift clean — `social-enrichment` Active, bedrock grant on youtube role); site-api OK; `/api/broadcast` live 200; site smoke **217/0** after recovery.
- All Wave-A issues auto-closed by `Fixes #N`; #1656/#1658 correctly stay OPEN (partials).

## Gotchas hit
- **A new `/api/` endpoint + its consuming page in ONE PR races the on-merge site auto-deploy** — #1704's site deploy smoked `/api/broadcast` (404) before I could deploy site-api → auto-rollback. Recovered by deploying site-api then re-syncing. Prevention: API must be live AT merge time. Saved to memory ([[reference_api_before_frontend_autodeploy_race]]).
- **CI/CD workflow stuck pending, 0 jobs, ~25min** on the post-#1710 main head — matches the known billing/minutes silent-death (#1544): lighter workflows (CodeQL/Docs) ran on the same commit, the heavy CI/CD wouldn't dispatch. Cancel+rerun didn't unstick. **Owner action: check GitHub Actions minutes/billing.**
- **doc-sync reconcile can pull site/ regenerations into the working tree** — after a `sync_site_to_s3.sh`, the reconcile step showed regenerated `site/rss.xml`/`sitemap.xml`/coaching static fallbacks (live-data-derived, regenerate on every deploy). Do NOT commit them in a doc-sync reconcile — `git checkout -- site/` first, commit only the literal files.
- **CDK deploy classifier gate is per-command** — batch approval doesn't satisfy it; needs an explicit "run the deploy" ask, then run UNPIPED with `-- --require-approval never` ([[reference_cdk_deploy_classifier_and_approval]]).
- **A worktree-implementer died mid-response on an API connection error AGAIN** (#1672) — resumed via SendMessage from its transcript, no rework (same class as last session's #1688).

## Gate outcomes
- **Build beat:** `2026-07-23-broadcast-feed` (the site can now host Matthew's own posts, fail-closed by default).
- **Docs:** none beyond the auto-synced counters (test_count/lambda_count/endpoints via `sync_doc_metadata.py`, in the reconcile commits) — SCHEMA/PHASE_TAXONOMY updates for the ledger/gate shipped in-PR last session; no new canonical page invalidated this session. Wiki checkers green at wrap.
- **Decisions:** none needed as a repo ADR this session — the #1686 content-sourcing = coach-web-access decision is recorded on #1705/the epic and explicitly deferred to its own ADR at implement time (not yet governance-consequential in code); the #1703 F401 override was an owner call recorded on the PR.
- **Main:** see `check_main_green.py` — the latest CI/CD run is the stuck/orphaned one (GitHub couldn't dispatch it; billing/minutes). Offline combined-suite was 6551/0; both deployed stacks UPDATE_COMPLETE. `**Main:** red — CI/CD run orphaned by GitHub Actions dispatch stall (minutes/billing, #1544-class); no code cause, offline suite green.`
- **Incidents:** 1 row added to `docs/INCIDENT_LOG.md` — the #1704 site auto-rollback (P3, transient `/api/broadcast` 404 pre-API-deploy; recovered same session).
- **Stash/hooks:** clean — `git stash list` empty; hook freshness 🟢. Postflight `🔴 config drift: 1 lambda differs from CDK` is the standing parked-deploy advisory (not this session's deploys, which all completed UPDATE_COMPLETE); clears on the next full-fleet deploy / prod-gate approval.
- **Labels:** OK — `check_story_labels.py` green, 93 open stories all carry `model:*`.

## Residual / next-picks
- **Confirm the #1710 coverage floor on CI 3.12** once GitHub Actions recovers — floor 47 measured 51.55% on 3.14; if the post-merge 3.12 Unit Tests run reds, push a one-line floor drop (non-gating, low risk). (#1658)
- **#1655** CI-composition — the last Wave-B big-bang; edits `ci-cd.yml`, so land it only once CI is healthy (avoid stacking on the stuck run). (#1655)
- **#1620** outbound social links — runs the `v4_apply_chrome` HTML sweep; land AFTER any site/head sweep. (#1620)
- **gate:owner** — #1662 (branch-protection Option C), #1666 (proportionality ADR), #1650 (handovers disposition): code-complete then STOP for owner sign-off. (#1662/#1666/#1650)
- **#1656 mypy** remaining ratchet — `mcp/` + the 7 residual codes + `check_untyped_defs`/`warn_return_any` + the 9 DIRTY modules. (#1656)
- **#1686 open decisions** — which coach curates, cadence/placement/email, privacy routing (S1/S3/S4 blocked on these). `not-work — owner product decisions`.
- **Seed→apply the ledger** — the 6 seeded corrections are `status=open`; S5 (#1697) is the first consumer (prompt-memory injection). (#1697)
- **GitHub Actions minutes/billing** — CI/CD won't dispatch; `not-work — owner billing check`.
- **Activate YouTube ingestion** — provision `life-platform/youtube` `{"channel_id":"UC..."}` then flip registry `active_api:True` — unblocks the whole Social Membrane inbound path (enrichment/gate/feed are live but dormant). `not-work — owner secret provisioning`.
- **Pre-hygiene archive zip (135M)** on an old scratchpad — `not-work — owner file move`.

**Build beat:** 2026-07-23-broadcast-feed
