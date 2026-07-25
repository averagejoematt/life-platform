# HANDOVER — backlog paydown + Horizons/diary features + owner-decision blitz — 2026-07-25

> Instruction thread: continue the standing autonomous backlog paydown (`model:sonnet`/`model:opus`,
> skip `model:fable`), standing approval for ALL merges + deploys + Deploy-gate approvals; CDK deploys
> prepared for Matthew to run via `!`. Mid-session pivoted into an interactive **owner-decision blitz**
> (Matthew worked the whole owner-dependent backlog with ELI5/options/rec per item) + wired two social
> credentials + built the Horizons feature (S1+S3) end-to-end.

## What shipped (12 issues closed, all merged to main + deployed; main GREEN)

**Backlog paydown — 3 waves (worktree-implementers → combined-tree verify → merge → deploy_all):**
- **Wave 1:** **#1572** Video Diary journal template (PR #1732) · **#1569** widen the Third Wall (#1733) ·
  **#1379** Daily Fingerprint + `/data/wall/` (#1734).
- **Wave 2:** **#1377** the Wrong Feed (#1735) · **#1381** the Theme River `/story/theme-river/` (#1736).
- **Wave 3:** **#1393** Engagement Ladder (#1744) · **#1394** Cohort Strip (#1745, `COHORT#` grant CDK-deployed by Matthew).
- **#1544** closed (CI push-run stall — root-caused to the phantom concurrency queue, not billing; salt fix
  `60d6652c` verified; INCIDENT_LOG row present).

**Feature builds (this session's back half):**
- **#1705 Horizons S1** (PR #1746) — weekly curation engine: pick model on the reading rail
  (`READING#HORIZON`/`PICK#<week>`), a categorized source **garden** (`lambdas/reading/horizons_garden.py`),
  a **fail-closed link-verification gate** (`horizons_verify.py`), MCP tools `curate_horizon`/`get_horizons`.
- **#1707 Horizons S3** (PR #1749) — the public **`/data/horizons/`** feed + the grounded, **budget-gated**
  (band-2) "why I sent it" retrospective (`horizons_retrospective.py`) through the #1673 sensitivity gate;
  new `GET /api/horizons`; MCP `archive_horizon`.
- **#1573 Whisper** (PR #1747) — solo local-Whisper transcription → the existing diary pipeline, `solo_recording` channel.
- **#1350 email purge** (PR #1748) — 18-month subscriber-email anonymize sweep + signed DATA_GOVERNANCE + a
  weekly EventBridge rule (`SubscriberRetentionSweep`, Mon 08:00 UTC — Matthew CDK-deployed `LifePlatformOperational`).

**Credentials wired (Social Membrane):** `life-platform/youtube` (channel_id `UCB4u65MnU5EV_BVPz2u-PsQ` — inbound
lambda live-invoked, feed reads clean) · `life-platform/bluesky` (handle + app password, `createSession`
validated 200 — staged; the #1676/#1629 consumers aren't built yet).

**Deliverables:** owner-decision worksheet artifact + the **#741 career-essay draft** ("Proof, Not Promises") artifact.

**~21 owner decisions recorded** on their issues (see the residual queue for the resulting build backlog).

## Verified
- Each wave: on-branch git-grep of agent claims + **combined-tree full suite** (no `-x`, `--ignore=test_integration_aws`)
  GREEN before merge — 6822 (w1) → 6840 (w2) → 6860 (w3) → **6924** (Horizons wave). All CI-only gates each merge
  (content-policy, `black`, ruff **6-dir**, mypy clean-set, doc-sync).
- Load-bearing ACs confirmed genuinely-asserting: #1379 byte-identical SVG; #1377 header==card count + graded-verdict
  sourcing (no AI-asserted wrongness); #1394 k-anonymity + stats-partition isolation test; #1705 fail-closed verify gate;
  #1707 budget-gating + grounded retrospective.
- Endpoints pre-deployed live before each site-page merge (autodeploy-race mitigation): `/api/fingerprint`, `/api/wall`,
  `/api/decisions`, `/api/wrong`, `/api/ladder_counts`, `/api/cohort_strip`, `/api/horizons` — all 200.
- Deploys: five `deploy_all` runs (Deploy/Smoke/Post-deploy/Visual-QA), plus Matthew's two CDK deploys (`LifePlatformServe`
  COHORT grant + `LifePlatformOperational` retention rule) — both verified live (grant on the role, rule `cron(0 8 ? * MON *)` ENABLED).

## Gotchas hit (durable lessons → memory)
- **CI ruff gate covers 6 dirs**, not `lambdas/ mcp/` — a narrow local run missed a `tests/` I001 → wave-2 `deploy_all`
  red at lint (caught pre-deploy, no bad ship). → memory `reference_ruff_full_dir_set`.
- **`gh pr merge` ships the branch, not your reconciled integration tree** — code reconcile fixes (CSS fs-ok, canary
  counts, registry classifications) made only on the integration branch are LOST on squash-merge. Land waves with a
  code-level reconcile via a **local merge / fast-forward to main** (auto-closes each PR). → memory
  `reference_gh_merge_takes_branch_not_integration_tree`.
- **Combined full-suite catches cross-cutting registry gaps individual agents miss** (targeted suites ≠ full): the
  Horizons wave surfaced 3 — a new scheduled lambda needing a heartbeat exemption (#1748), an unclassified MCP verb
  `archive` (#1749), a retired-term "shared layer" phrase (#1748). All fixed on the integration branch before merge.
- **Site-deploy `--delete` race**: an older site-only merge's deploy re-synced its tree last and removed the newer
  page (theme-river 404 window) — recovered via manual `sync_site_to_s3.sh` (see Incidents).

## Residual / next-picks (all issue-cited or `not-work`-tagged)
**Recorded build queue (approved this session, unbuilt — pick up next session):**
- Doc-ADRs (docs-only, sonnet): #1666 · #1352 · #1333 · #1662
- Code stories (sonnet/opus): #1330 · #1345 · #1570 · #1407 · #1623 · #1613 · #1336 · #1388
- Credential-gated builds (build code, dormant until owner keys land): #1631 (X) · #1632 (Instagram) ·
  #1676 + #1629 (Bluesky consumers — secret already staged) · #1678 + #1674 (embeds/CSP)
- Deferred (recorded): #1383 · #1396 · #1742

**`not-work` — owner actions (surfaced, on Matthew):**
- `not-work — owner provisions credentials`: X API keys (`life-platform/x`), Instagram Graph token
  (`life-platform/instagram`), a user-scoped billing PAT (for #1613).
- `not-work — owner GitHub toggles`: enable Dependabot + vuln-alerts + secret-scanning (#1336); apply the
  branch-protection ruleset (#1662) AFTER the private flip (it drops on the flip, #1319 class).
- `not-work — owner chore`: #1029 re-entry hardening before the 2026-08-20 domain renewal; #1243 podcast-audio regen;
  publish #741; confirm phone number on the #1333 SNS paging subscription.
- `not-work — owner decision`: the repo private-flip (ping for the post-flip checklist — metered minutes return + re-verify env protection).
- `not-work — standing ops reminder`: no aged-alarm / stale-secret escalations outstanding at wrap (remediation agent in `shadow`; SECRETS_ROTATION monitoring clean).

## Gate outcomes
- **Build beat:** `2026-07-25-horizons-live` (Horizons end-to-end — curate → public feed → grounded retrospective).
- **Docs:** DATA_GOVERNANCE (retention policy, #1350) + SCHEMA (diary channels + horizon pick shape) + DIARY_STUDIO_KIT
  updated by the shipping PRs; `sync_doc_metadata` reconciled (tools 72, endpoints 128, test_count 5359); doc checkers green.
- **Decisions:** none filed — the governance decisions made this session (license posture #1352, paging #1333,
  branch-protection #1662, embed-CSP #1678, complexity ledger #1666) are recorded on their issues and each ships its
  ADR at implementation time (all queued).
- **Main:** green (`270271ca` — the Horizons-wave deploy_all was completing at wrap; prior completed run `57c1365c` green, no red run).
- **Incidents:** 2 rows — (P4) wave-2 `deploy_all` lint-gate failure (ruff 6-dir scope gap, caught pre-deploy, fixed via
  the #1381 tail commit); (P4) theme-river 404 window from the older #1377 site-deploy `--delete` race, recovered via manual sync.
- **Stash/hooks:** clean.
- **Labels:** OK.
- **Live: budget tier 1.**

**Build beat:** 2026-07-25-horizons-live
