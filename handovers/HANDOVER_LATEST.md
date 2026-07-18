# HANDOVER — Later-drain finish + human-gated queue cleared + cycle-8 reset to Sunday — 2026-07-18

> Instruction thread: "pay down EVERYTHING remaining that does NOT need my input, PROPERLY"
> (real fix + non-vacuous guard proven RED pre-fix, merged AND deployed + verified live), then
> Matthew unblocked the human-gated queue mid-session: approved all edits/merges/deploys,
> chose per-item dispositions, ran the live AWS deletes himself, and finished with "one more
> full reset" to Sunday 2026-07-19.

## Outcome — 8 issues shipped+deployed+verified, archive healed, cycle-8 reset live

**Code fan-out (3 worktree agents):**
- **#1251/#1252/#1244** (PR #1317, ONE coordinated site-ux slice): permanent "yesterday's
  read" scope on the cockpit daily line; "carried from prep" markers when a lever/supplement
  date predates genesis; self-hiding Home season-premiere beat off `/api/cycle_compare`
  (window_days 1–21, no new lambda). Site auto-deploy passed the gating visual-QA;
  `version.json` == merge SHA verified.
- **#1240** (PR #1318): split `site_api_data.py` 4,184 → ~2,740 lines — 14 handlers moved
  verbatim to `site_api_vitals`/`site_api_intelligence`; router parity 111→111 routes
  IDENTICAL (frozen into `tests/test_site_api_data_split.py`); `handle_cycle_compare` +
  `CYCLE_GENESES` deliberately stayed (restart tooling locates them by path). I independently
  smoke-imported the router pre-merge (circular-import check) and after `deploy_site_api.sh`
  verified **all 15 moved/kept endpoints 200 live**.
- **#1255** (PR #1316): chronicle gate `current_tier() >= 2` → `not allow("chronicle")`
  (cutoff now lives only in `_FEATURE_CUTOFF`); AST guard bans soft-tier hardcodes outside
  budget_guard/bedrock_client (scoped to exclude the legit Tier-3 hard-stop in
  bedrock_batch); wednesday-chronicle deployed.

**Human-gated queue (Matthew's dispositions, executed):**
- **#1227**: `cloudformation:DetectStackResourceDrift` added to the remediation role (PR
  #1359 + live `put-role-policy`, script-applied — NOT CDK, so no R8-ST6 Plan-red);
  `check_cfn_drift` now escalates all-stacks-AccessDenied `degraded → error` +
  `dead_capability` signal. Capability verified via `simulate-principal-policy` → `allowed`.
- **#916**: `lp_approval` remembered-browser cookie 30→90d (PR #1361) — the passcode-bypass
  window only; the 24h `lps_` session bearer deliberately untouched (revocation stays
  tight). MCP deployed from a clean origin/main worktree; boot verified (401 = healthy).
  If friction persists in cookieless connector contexts, the real fix is a refresh_token
  grant — flagged, not built.
- **#1257**: Matthew ran the 4 delete commands (both orphan EventBridge rules + targets);
  verified gone. Docstring half merged (PR #1362, `Refs` not `Fixes`): onboarding lambda now
  states CDK's `cron(5 17)`, guarded by `test_onboarding_schedule_docstring.py` (parses the
  CDK schedule — self-updating). The EventBridge-in-synth integration assertion remains open.
- **#1228**: Matthew deleted the dead us-west-2 `email-subscriber` twin + its orphan alarm;
  verified gone (pre-checked: no ESM/policy/FunctionURL — nothing invoked it).
- **#1265**: both chronicle lambdas deployed (the code merged prior session). The held
  `DATE#2026-07-14` draft with the phantom citation was **already reset-wiped**
  (`status=published, tombstone=true`) — nothing to regen. Fully closed.
- **#1114**: v2 portrait sketch round rendered (real rasterizer, signed recipes, frames
  injected via `layers["frame"]` — no shipped code touched) and published as a private
  artifact: https://claude.ai/code/artifact/98729e35-b124-4f2c-bcee-11015abd9b28
  (v1 vs v2a–d + stroke 1.6/1.15 A/B at 96px; my ranking v2c ▸ v2d ▸ v2b). **Matthew
  deferred the pick to a future session** — next step is his frame+stroke choice, then
  full-cast render through the ADR-106 gate.

**#1266 archive heal (option C, Matthew-approved):** re-derived every tombstoned record's
true cycle from its CONTENT date (SK-embedded) against `CYCLE_GENESES` — **8,427 rows
re-stamped, verify re-scan = 0 mismatched** (now `{1:5218, 2:546, 3:443, 4:2212, 5:2417,
6:489}`); 198 pre-cycle-1 pilot rows left untouched (option A), 2,243 undateable singletons
left. **Near-miss:** the first dry-run inferred dates from `tombstoned_at` (the RESET time)
— would have re-corrupted 8k rows toward the reset dates; caught in dry-run, zero writes.
NEVER use tombstoned_at/last_updated for generation inference.

**Cycle-8 reset (Matthew: "one more full reset", Sunday genesis):**
`restart_pipeline.py --genesis 2026-07-19 --override-weight-lbs 315.65 --sync-site --apply`
— all hard gates PASS (rendered 40/40 clean vs old genesis, semantic, AI reader-truth). SSM
cycle=8, `CYCLE_GENESES` += 8, RESET_LOG appended, site synced + pre-start countdown owns
the surface until Sunday. Regenerated files committed from main (`37e09f04`), rebased over
the concurrent session's wrap. Backfill ran BEFORE the reset so the healed stamps rode
through under the merged #1266 `if_not_exists` protection — ordering that mattered.

**Un-red main (#1416):** #1317's `.carry-tag { font-size: 0.82em }` passed the gating
visual-QA but redded Unit Tests via `test_css_tokens` (a unit guard, not a render check).
Fixed with the sibling `/* fs-ok: reason */` sanction (value unchanged → pixel-identical).
Verified the exact CI invocation locally: 5,388 passed. Lesson → memory
`reference_css_token_guard_vs_visual_qa`.

## Gotchas hit (durable ones also in memory)
- **Concurrent sessions on the shared tree**: an `/sdlc-review` + `/frontier-plan` session
  ran in parallel; my `git add -A` swept its in-progress review file into PR #1359
  (harmless — its own PR #1360 superseded), and `gh pr merge` from the main tree kept
  failing branch-delete while worktrees held the branches. Reflex: worktree-per-change,
  scoped `git add`, and `git worktree remove` before branch delete.
- **CI logs unavailable** (`--log-failed` empty, artifact quota) — reproduced the Unit
  Tests red locally instead; on a stale checkout the two `test_count` literal tests +
  the cosmetic DLQ I9 fail too — reproduce on true `origin/main` HEAD to separate real
  reds from lag/noise.

## Residual / next picks
- **Sunday+ (post-genesis):** `python3 deploy/restart_verify.py` (asserts post-genesis
  state; deliberately not folded into the pipeline).
- **Attended prereg (dry-run-review posture):** `deploy/seed_genesis_preregistration.py
  --apply` then review + `deploy/publish_genesis_preregistration.py` for cycle 8.
- **#1114**: Matthew picks frame (v2c/v2d/v2b/keep) + stroke (1.6/1.15) from the artifact →
  full-cast render, recipes + parity manifest, ADR-106 gate.
- **#1257 remainder**: the read-only integration assertion (every ENABLED EventBridge rule
  targeting a life-platform lambda appears in synthesized CDK) — now that the orphans are
  deleted it can land green.
- **#1243 / #748 / #1187 / #1029**: still Matthew-gated (podcast audio re-narration,
  fulfillment story timing, music bed, re-entry checklist).
- The frontier-plan backlog (#1363–#1415, 52 issues) from the concurrent session is
  untouched by this one — its handover: `HANDOVER_2026-07-18_FrontierPlan.md`.
- Ingestion DLQ still holds the 1 Withings-transient msg (cosmetic integration-check red).

**Build beat:** `2026-07-18-later-finish-cycle8` (distilled per checklist — merged +
deployed + verified only).
**Docs:** RESET_LOG/SCHEMA/CHANGELOG/CLAUDE.md regenerated by the reset pipeline's own
doc-sync (committed `37e09f04`); ARCHITECTURE.md rows updated in PR #1318; no other pages
invalidated — the session's fixes were self-documenting (guards + docstrings in-tree).

Prior session (same day): `handovers/HANDOVER_2026-07-18_FrontierPlan.md`.
