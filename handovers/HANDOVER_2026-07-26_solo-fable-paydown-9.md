# HANDOVER — solo fable paydown (9) + post-merge review hardening + owner-unblock round — 2026-07-26

> Instruction thread: **solo** standing autonomous backlog paydown, `model:fable` ONLY, this
> session owns main (merge + deploy own work); standing approval for ALL merges, Deploy-gate
> approvals, and deploys incl. `deploy_all`; CDK deploys prepared for Matthew to run via `!`.
> Mid-session Matthew flagged the session driver had accidentally been Opus — the
> worktree-implementers were all genuinely fable (explicit `model: fable` override on every
> Agent call); only orchestration ran on Opus until the `/model` switch. Response: a full
> **3-reviewer post-merge audit** of the already-merged wave before approving the production
> gate. Session closed with an interactive **owner-decision unblock round** (Matthew answered
> the full gate:owner menu inline).

## What shipped — 9 fable stories closed, all merged + deployed + live-verified; main GREEN

**Wave 1 (4 worktree-implementers in parallel):**
- **#1628** window-validated process milestones — pure window fns (`return_after_gap` flagship, weight demoted to companion-only), through the MILESTONE# ledger + spiral breaker, uncertainty+n per ADR-105 (PR #1771).
- **#1481** conversational self-calibration — check-in answers move CONFIDENCE#/LEARNING# with `channel=conversation` provenance, bounded to one pseudo-observation; **ADR-141**; new MCP tool `log_coach_calibration` (PR #1770).
- **#1698** corrections pattern-extraction → gate-promotion PROPOSALS (deterministic clustering, proposal-only, review-pack surface) (PR #1769).
- **#1568** opt-in verbatim journal pull-quotes — consent-per-line, mark-time taboo gate, `/api/journal_quotes` + story-hub/home render; **ADR-142** (the shared three-tier journal privacy model) (PR #1772).

**Review-fix batch (`fc2293e5`, after the 3-reviewer audit — findings verified ~50% rule, then fixed + regression-tested):**
verbatim `answer_quote` structurally removed from summarizer/stance prompts (ADR-141 §4 — public-feeding LLM outputs had only numeric gates) · `/api/journal_quotes` serves only `grounding=verified` + the tool's `list` action re-verifies pendings · beverage-noun taboo widening · `marked_at` preserved on re-mark · calibration cap probe fail-closed · explicit `channel=conversation` filters on `/api/wrong` + `revision_signal` · **`LEDGER#genesis#windows` marker** (deploy-sequencing guard: a rule family added after genesis baselines once, never manufactures "news") · zone2 = per-day max(garmin, strava), never sum · breaker failure logs before suppressing · `RETURN_EMIT_WINDOW_DAYS` 14→45 (suppression was silently losing the flagship restart fact). Reviewer verdicts: 2× SAFE, 1× BLOCK whose premise (prod `LEDGER#genesis` exists) was **disproved against live DDB** — the guard was made structural anyway.

**Wave 2:**
- **#1483** allude-tier conversation references — `conversation_reference()` builds from sanctioned fields only (leakage structurally impossible); by-coach page + chronicle packet; tier 2 of ADR-142, no new ADR (PR #1773).
- **#1577** conversational capture → numeric signal — enrichment over checkin/reflection/field-note partitions, channel-tagged, **analysis-only v1** (Methods Registry fingerprinted), HYPO_CANDIDATE# provenance, dedup by content hash (PR #1774).
- **#1382** proactive coach nudges — deterministic triggers (nutrition-gap/ACWR/verdict-resolving), Haiku phrases only the payload, ≤1/day + quiet hours + tier≥2 silence, outcome-graded into Brier; **new CDK lambda `coach-nudge`** (LifePlatformEmail, Matthew ran the cdk_deploy via `!`) (PR #1775). Driver added the missed registry wiring (lambda_map, heartbeat COVERAGE exemption, typed handler).
- **Wave 3:** **#1386** Dispute Docket — machine-checkable criterion frozen at open, deterministic resolution reusing the evaluator, concession→loser's memory (grounding-enforced), `/api/coach_docket`, per-pair-per-topic throttle replaces the weekly cap (PR #1776) · **#1387** Coach Dossier — verbatim COACH# render behind a fail-closed privacy filter (reuses `find_mark_violations` + genotype patterns; conversation-channel excluded), `audit_coach_dossier` MCP tool (view/retract/correct via the #1689 corrections ledger, never mutates), honest zero-states (PR #1777).

**Owner-unblock round (Matthew answered inline):** **YouTube membrane LIVE** (api_key + channel_id `UCB4u65MnU5EV_BVPz2u-PsQ` in `life-platform/youtube`; ingestion invoked: 200, 7 dates, honest no_data) · **#1333 = Option B** (SNS→SMS for a named small alarm set; phone in SSM `/life-platform/paging-phone` SecureString; gate:owner removed) · **#1623 unblocked** (first recipient provisioned in `life-platform/digest`; gate:owner removed) · **#1666 approved** (gate:owner removed) · #1383 deferred to ~2026-08-26 · private-flip intent noted on #1662 · #1768 + #1622 parked by owner ("-").

## Verified
- Combined-tree FULL suite at every merge point: 7134 → 7182 → 7236 → **7311** (final tree, 0 failures) + 6-dir black/ruff, content-policy, mypy clean-set (189 files), check_doc_index --strict, ADR index (140 records → ADR-142), sync_doc_metadata clean.
- **Three `deploy_all` runs GREEN** (Deploy/Smoke/Post-deploy/Visual-QA, no rollback) + Matthew's `cdk_deploy LifePlatformEmail` (coach-nudge infra) + two site-api pre-deploys + final site-deploy GREEN after two auto-rollback incidents (below).
- Live probes: `/api/journal_quotes` 200 honest-empty · `/api/coach_docket` 200 honest-empty (+ CloudFront viewer-path invalidation) · `/api/coach/{id}` carries `dossier` (all 8 keys) + `conversations` blocks · coaching page 200 · MCP boots (75 tools, no FunctionError) · `coach-nudge` fresh bundle code · youtube ingestion end-to-end 200.

## Gotchas hit (durable → memory)
- **The API-before-frontend race fires on ANY push of a merged branch with site/** JS + a new endpoint** — even when you plan to "batch the deploy later": the push itself triggers site-deploy. #1386's push → smoke 404 on `/api/coach_docket` → auto-rollback (readers unaffected). Pre-deploy site-api BEFORE pushing the merge, not before "the deploy". → `reference_api_before_frontend_autodeploy_race` (updated).
- **`curl` exit 28 (transient timeout) in site smoke reads as a failure → spurious auto-rollback**; recovery = `gh workflow run "Site deploy"` redispatch (workflow_dispatch supported). → `reference_site_smoke_transient_timeout_rollback` (new).
- **In-repo agent worktrees (`.worktrees/`) pollute filesystem-walking tests** (hevy-compiler isolation red on a healthy tree); `.worktrees/` now gitignored + agents briefed to use external paths. → `reference_inrepo_worktree_pollutes_scanners` (new).
- **A rule family added AFTER a write-once ledger's genesis needs its own baseline marker** — or the first sweep announces months-old states as news, uncorrectably (the `LEDGER#genesis#windows` pattern).
- Reviewer BLOCK verdicts need their premises checked against live state before acting (the "prod genesis exists" premise was false — `get-item` returned null).

## Next-session paydown queue — residual / next-picks
**Buildable next (owner-cleared this session):**
- **#1623** private milestone digest (Now) — recipients secret provisioned; data source = the #1628 MILESTONE# ledger.
- **#1333** paging channel (Next) — decision B recorded; build = ADR + dedicated SNS topic (NOT the alerts topic) + named alarm set + SMS sub from the SSM param.
- **#1666** proportionality ADR (Next) — approved, doc-only.
- **#1571** /vlog mode + format library (Now, fable) — untouched this session.
- Dependabot triage (21 vulns, 16 high) once Matthew flips the #1336 toggles.

**not-work — owner actions still pending:**
- `not-work — owner browser tasks`: #1336 security toggles + #1613 billing PAT (instructions delivered in-session; PAT to be pasted → store at `life-platform/github-billing`).
- `not-work — owner decision parked`: #1768 portrait direction ("-" this round) · #1622 posting-trial commitment ("-") · #1407/#1388/#1570/#1633/#1742/#1677/#1678 "discuss later".
- `not-work — owner chore`: #1029 re-entry hardening before 2026-08-20 · LICENSES.md §5 ratify · #741 publish gate (needs a survived bad week).
- `not-work — standing ops reminders (#1329)`: youtube captures its first video on the next upload (verify enrichment→gate→feed then) · first coach-nudge send + its 2h grading · first docket open (digest may propose criteria) · #1330 strava freshness green-run · no aged-alarm/stale-secret escalations outstanding (remediation agent `shadow`; digest-routed alarms clean at wrap).

**Method (held):** 2–4 fable worktree-implementers in DIFFERENT areas → on-branch git-grep verification (~50% false-positive rule held: 2 reviewer premises disproved) → combined-tree full suite + 6-dir gates → local merge waves → **post-merge 3-reviewer audit before the production gate when provenance is questioned** → pre-deploy site-api before ANY push carrying a new-endpoint consumer → `deploy_all` + `approve_deployment.sh`.

## Gate outcomes
- **Build beat:** `2026-07-26-nine-stories-coach-layer` (see beats.json).
- **Docs:** shipped-in-PR — ADR-141 + ADR-142 (+ index, 140 records), SCHEMA.md §Conversational Self-Calibration, Methods Registry entry (#1577) + regenerated `site/method/registry/`; wrap adds 2 INCIDENT_LOG rows; doc-sync literals reconciled at every merge (75 tools / 98 lambdas / test_count); wiki checkers green at wrap.
- **Decisions:** ADR-141 + ADR-142 filed (shipped via PRs #1770/#1772); no further governance decisions this session (owner decisions recorded on-issue, not ADR-class until built — #1333's ADR ships with its build).
- **Main:** green (`e3373196` — final `deploy_all` + site-deploy redispatch both success).
- **Incidents:** 2 rows added — (P3) #1386 API-before-frontend site auto-rollback (self-inflicted race, readers unaffected); (P4, false positive) transient curl-28 smoke timeout → site auto-rollback → redispatch green.
- **Stash/hooks:** clean (stash empty; hook 🟢).
- **Labels:** OK.
- **Live: budget tier 1** (unchanged).

**Build beat:** 2026-07-26-nine-stories-coach-layer
