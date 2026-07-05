# HANDOVER — opus batch #2: 13 issues → merged → layer v113→v114 → deployed + verified — 2026-07-05

> Second model:opus batch of the day. Ran AFTER opus batch #1
> (`handovers/HANDOVER_2026-07-05_opus_batch1.md`, 11 issues, layer v112→v113) and the HAE
> session, all of which were closed. A **concurrent session landed #478 (ADR-122) on main**
> mid-run; merged in. Matthew authorized all edits/merges/deploys up front, answered the 3
> product forks in-session, and twice said "keep going." Chose to WRAP (not chain a 3rd batch)
> because batch #3's centerpiece (#409) touches the AI chokepoint = another layer bump best done
> with fresh context.

## What shipped (13 issues, 10 parallel worktree agents, ADRs 114–121 pre-reserved)

**Distribution / share-cards (epics #338/#340)**
- **#595** the share-card engine — `lambdas/web/card_engine.py`, one code-drawn renderer; `og_image_lambda` re-exports its tokens/primitives so the 12 daily cards stay **byte-identical** (test-pinned). ADR-114.
- **#420** character card + linkable `/data/character/` (+ `og-character.png`, `share ↗`); computed stats only, proven byte-identical with/without an age field (privacy holds).
- **#405** per-chronicle share kit — `lambdas/chronicle_share_kit.py`; excerpt + honest-stats line + card URL + canonical URL, surfaced in the approval email + `generated/moments/share-kits/`.
- **#593** portraits travel — `lambdas/web/og_coach_cards.py` (thin `_Engine` adapter over the engine + shared `web/portrait_raster.render_recipe`), 40 committed portrait PNGs, coach OG cards / email byline PNG / episode-art script. Approved recipes only (ADR-106).
- **#399** Agent Activity feed — `/story/agents/` + `/api/agent_activity` (`lambdas/web/site_api_agents.py`), read-only render of `coherence-log`/`ai-canary-log`/`remediation-log` artifacts, privacy-gated, honest empty state.

**Harden / budget (epics #341/#344/#346)**
- **#402** DLQ escalation — ADR-115. Content-hash stable id `SYSTEM#dlq-ledger`, `ADD attempts :receive_count`, delete-only-after-confirmed-2xx, pages the existing `life-platform-alerts` SNS, time-budget drain replaces the 10-msg cap. Operational CDK + IAM (DDB + kms + sns).
- **#411** CloudWatch audit — ADR-116. Reconciled 136 live alarms vs 107 CDK; **deleted 18 orphans (136→118)** via `deploy/cloudwatch_retire_orphans.sh --apply`, **adopted 2** into Monitoring IaC. Deliberately KEPT the 48 per-lambda error alarms — only 2/49 lambdas route to a DLQ, so they're the sole failure signal (DLQ-wire-then-retire is the sanctioned follow-up). Audit doc: `docs/reviews/CLOUDWATCH_AUDIT_2026-07.md`.
- **#416**+**#418** — ADR-117. `@pytest.mark.deploy_critical` (11 files); CI `plan` now `needs: [lint, test-critical]` so an unrelated red no longer blacks out visual QA; site+layer rollback wiring rebuilt for the hashed-asset era. **Latent-bug fix: the Lambda auto-rollback `if` was missing `always()` → it had never fired.** Two ACs ("visual-QA runs on a red suite", "one rollback drill") await a live CI run — flagged in PR #688.

**Data honesty**
- **#508** Whoop-webhook spike — ADR-119, **KEEP POLLING** (id-only payload still needs a live token → worsens the rotation race `ReservedConcurrentExecutions=1` guards; no `cycle` webhook; no vendor DLQ). No prod change. Doc: `docs/reviews/WHOOP_WEBHOOK_SPIKE_2026-07.md`.
- **#489** Eight Sleep temp — ADR-118, **RETIRED** (v2 intervals 404s 4+ months; retired the fetch + MCP `get_sleep_environment_analysis` tool 144→143 + the /data/sleep env section; trends-payload reactivation lead recorded). Touched layer modules `ai_context`/`coach_stance`.
- **#507** State of Mind — **KEPT** (owner: "keep, I just need to start doing it"). ADR-121 + ADR-103 ledger flip. **Found a real bug: 8 consumers read an empty `state_of_mind` partition ingestion never writes** — data lands on `apple_health` as `som_*`. Fixed all read-side (character_engine, ai_context, daily brief, chronicle, site_api_data, tools_lifestyle, field-notes, ai-expert), honest empty states preserved, restart runbook added. Touches layer module `character_engine`.

**Infra**
- **#401** OIDC — ADR-120, **codify half only** (owner-approved codify-now/tighten-later). Roles + provider → `infra/iam/*.json` + `deploy/verify_oidc_iam.py` (0 drift, **0 live IAM mutation**). Tighten (`repo:*`→main-only) staged in `infra/iam/proposed/` + runbook, tracked as **#687**.

## Deploy record (one coordinated sequence)
1. `build_layer.sh` → `rm -rf cdk/cdk.out` → `cdk deploy LifePlatformCore` **published layer v114** → verified live → bumped `SHARED_LAYER_VERSION` 113→114.
2. Pushed main (closed all 10 PRs + 13 issues). **Push rebased over #478/ADR-122** which a concurrent session had landed.
3. `cdk deploy` Compute Email Mcp Operational Monitoring **Ingestion** (`--concurrency 3`) — all UPDATE_COMPLETE. Ingestion was **3 layer versions behind (111→114)** since the HAE session never redeployed it; diff was clean `[~]`-only.
4. `cloudwatch_retire_orphans.sh --apply` (20 deletes: 18 retire + 2 adopt-rename).
5. `deploy_site_api.sh` (also handled the layer re-attach) → `sync_site_to_s3.sh` (+ CF invalidation).
6. **Verify:** layer v114 attached · `version.json` build == HEAD `1576e52f` · smoke **67/67** · visual QA **33 pass / 1 FP / 10 transient warns** · MCP healthy (no import crash) · `/api/agent_activity` 200.

## Gotchas (durable ones saved to memory)
1. **macOS case-insensitive path twin** (`/Users/.../Documents/...` vs lowercase `documents`) let 3 parallel agents (#401/#399/#489) leak edits into the shared **main** tree, and left main checked out on an agent branch. The pushed PR branch is the source of truth; **preserve stranded main-tree work (an agent with no worktree commits + dirty main files) before cleaning.** → `reference_worktree_case_insensitive_pollution`.
2. **The pre-commit hook regenerates counter files but only stages ARCHITECTURE.md** — during a stacked-merge run it left `site_api_common.py` dirty and blocked the next merge. Disable the hook for the merge run, regenerate all counts once at the end with `sync_doc_metadata.py --apply`, re-enable.
3. **DECISIONS.md conflicts on every stacked merge** (each branch appends its ADR to the same region) — union-resolve (keep both, `---` between); regenerate counts at the end. `site_api_common.py` conflicts were count-lines except #411's real `alarms 56→109` fix (take theirs).
4. A concurrent session can push to main mid-batch (#478) — `git fetch` + merge origin/main in before your push; branch protection here allows a direct admin push (0 required reviews).

## State at close
- `main` clean == `origin/main` (`1576e52f`), all gates green, all 13 issues + PRs closed, worktrees pruned (only main + the pre-existing `uplevel-2026-07-01` remain).
- **GitHub Pages still enabled + public (carried from prior sessions, unactioned).**

## Next session (batch #3 — do fresh)
- **Cleanly doable:** **#408** (render/accuracy QA left onto site PRs — CI) · **#409** (batch-price the content AI — **touches `bedrock_client`/`ai_calls` = LAYER modules → plan another layer bump + full consumer redeploy**, and a batch-submit/poll path with a real-time deadline fallback) · motion trio **#588** (View Transitions) / **#590** (home cinematic) / **#591** (cockpit presence) — unblocked by batch #1's chart/uncertainty contract.
- **Need Matthew's input:** instrument-depth **#412/#415/#417/#421/#422/#475** — external endpoints, template↔movement map, or a real week of data; not cleanly closeable solo.
- **Attended:** **#395** MCP registry prune (destructive — removes tools through the AUDITED_AT ratchet).
- **Watched CI run:** **#687** OIDC trust-tighten (the risky half of #401).
