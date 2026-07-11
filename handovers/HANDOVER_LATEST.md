# HANDOVER — The Engineering Wiki program: 10 PRs, docs-as-code made AI-shutdown-proof, drift machinery live, adversarial panel graded 7.5/10 — 2026-07-10

> Instruction: "put a plan together to build out the wiki … graded 10/10 by a majority of
> engineers, CTOs, CPOs … the wiki and repo should be enough for if all of AI got powered
> down, human engineers would have everything they need … and think about deployment
> practices and session wraps going forward so the wiki stays accurate and avoids drift."
> Mid-session: "i approve you to do all merges and deploys this session, green light in
> advance" · "my assumption is the wiki ends up in github.com/…/wiki, no dependency on md
> files on my laptop" (answered: docs-as-code IN the repo on GitHub = zero laptop
> dependency + CI-gateable; the /wiki tab is a separate un-CI'd repo — a one-way mirror is
> available on request) · SSO migration approved (free) — console-enable still pending.

## What shipped (all merged + deployed, docs-ci green on every one)

**The corpus (7 program PRs):**
- **#923 wiki-1 repairs** — tombstone purge (retired layer #781 / WAF / stale counts /
  the inverted "NEVER deploy_lambda.sh for MCP" warnings / banned grep method) across 16
  live docs; `sync_doc_metadata` hardened (a RULES pattern matching NOTHING now fails
  `--check` — the silent-no-op class that let "133 tools" survive #395; 10 pre-existing
  broken rules repaired); RULES extended to 9 more docs; `secret_count` live-verified 9→21;
  DECISIONS index regenerated 57→119 rows via new `scripts/generate_adr_index.py`;
  DEPLOYMENT.md → superseded pointer shell.
- **#924 wiki-2 structure** — `docs/README.md` rebuilt as the wiki home (role paths +
  Diátaxis + 100% registry + the self-maintenance contract); 15 SPEC_* → `docs/specs/`,
  v4 quartet + V2 audit + dated artifacts → `docs/archive/` (51 files re-pointed;
  BACKLOG.md + docs/restart/ deliberately NOT moved — CDK/pipeline write there); status
  headers (`> **Status:** … · **Verified:**`) on all 39 canonical pages with honest dates.
- **#925 wiki-6** — `docs/SITE_AUTHORING.md` (add-a-page end-to-end: generators inventory,
  module-graph hashing trap, sw.js semantics, deploy+rollback); `site/DEPLOY.md` de-staled
  (described the pre-v4 site).
- **#926 wiki-4** — `docs/CONTINUITY.md` (the "AI powered down" keystone: 6→8 state
  surfaces, day-1 successor reading order); `scripts/export_platform_memory.py` (read-only,
  live dry-run 27 records/5 categories); 7 hard-won gotchas homed in CONVENTIONS §7.
- **#927 wiki-3** — `docs/AWS_ACCESS.md` (SSO primary + break-glass + OIDC role inventory);
  `docs/ACCOUNTS.md` (registrar = **NameCheap, averagejoematt.com expires 2026-08-20**;
  SES sends from mattsusername.com — also NameCheap); QUICKSTART cold-start rewrite;
  SECRETS_MAP reconciled to live (21 active, 9 previously undocumented secrets mapped).
- **#928 wiki-5** — SCHEMA.md Key-Family Catalog (every pk/sk family incl. STANCE#,
  ledger, coach, reading+GSIs; ~50 live Query(Limit=1) verifications); `docs/engines/`
  ×5 (SCORING/CHARACTER/READINESS/HYPOTHESIS/COACH_STANCE — formulas with file:line refs).
- **#929 wiki-7 machinery** — `scripts/check_doc_links.py` + `check_doc_tombstones.py`
  (+ `docs/_lint/tombstones.txt`) + `check_doc_index.py`; `.github/workflows/docs-ci.yml`
  (docs-only pushes previously ran NO pipeline); same gates in ci-cd Lint; wrap skill
  step (e) doc-sweep gate; PR-template Docs-impact checklist; CONVENTIONS §8 (the
  four-layer contract); `tests/test_wiki_checkers.py`.

**The grading loop (3 PRs):** 5-persona adversarial panel (staff-eng cold-start, SRE,
CTO, security, CPO) scored 6.9 → **#932** fixed 24 verified defects (daily-brief is
17:00 UTC not 11 AM; MONITORING's 4 dead alarm names; RUNBOOK's dead-alarm ingestion
check; DR Scenario-5's false-security rotate loop; concurrency is 100 not 10; estate/
break-glass section with loud UNDOCUMENTED rows; ingestion count is 15 — ARCHITECTURE
was missing hevy, the grader had the outlier backwards) → re-grade → **#937** honesty
hotfix (my own fix claimed the repo was private; it is still PUBLIC — false security
assertion corrected) → **#938** round-2 residuals (the "aggregate ingestion alarm" is a
phantom — deliberately NO fleet alarm exists, detection = freshness+DLQ+canary; and
`deploy/setup_whoop_auth.py` EXISTS — in `deploy/`, not `setup/`).

**Deploys:** site-api ×2 (public `/api/platform_stats` now truthful: 64 tools / 94
Lambdas / 119 ADRs / 3029 tests / 21 secrets — every one was wrong this morning).

## Final graded scores (honest — no third-party re-score after #938's fixes)
Cold-start 7 · Correctness 6.7 · Coverage 7.8 · Navigability 8 · Operability 8 ·
Maintainability 8 · Continuity 7.3 → **≈7.5/10** (from 6.9). The gap to 9 is 3 owner
actions, not doc quality (below).

## Verified
All 5 wiki gates + `sync --check` green on main at `d4def416`; docs-ci success on every
merge; `tests/test_wiki_checkers.py` + sync/platform-stats truth tests pass (14 tests);
live-AWS cross-checks by graders (secrets 21/0, PITR ENABLED, CloudTrail logging, OIDC
roles, whois ×2, concurrency 100).

## Gotchas hit (durable ones → memory)
- GitHub's PR mergeability cache races a force-push — wait ~20s and retry, don't rebuild.
- The `--alarm-names` describe-alarms trap: nonexistent names are silently omitted →
  false "all-OK". Query by `--state-value ALARM` instead.
- Graders introduce-and-catch: 2 of my #932 fixes were themselves wrong (anticipatory
  "repo is private", "no whoop script"). Write docs to CURRENT truth, never intended
  truth; scripts live in `deploy/` AND `setup/` — search both.
- `.flake8` excludes `deploy/`; CI's flake8 only covers `lambdas/ mcp/`; black+ruff
  cover `scripts/ deploy/` — know which linter owns which dir.
- My header-inserter matched a bash `# comment` as an H1 in CHANGELOG (first real `# `
  heading was inside a fence at L1725).

## Matthew's queue (the entire remaining gap to 9/10)
1. **Flip the repo PRIVATE** — open HIGH finding; `docs/coaching/` biometrics are
   world-readable right now (DATA_GOVERNANCE + DR state this honestly).
2. **Fill the 2 estate rows in `docs/ACCOUNTS.md`** — password manager + estate access;
   MFA/2FA recovery-code locations. Until then documented bus-factor = 1.
3. **Enable IAM Identity Center** (console: IAM Identity Center → Enable, us-west-2 →
   Users → add `matthew`) — then I finish the SSO lane (permission set, assignment,
   `aws configure sso` verify; docs already written in AWS_ACCESS.md).
4. Decide the idle `life-platform/notion` secret (retire-candidate since 2026-03).
5. **averagejoematt.com renews 2026-08-20 at NameCheap** — nearest hard deadline.

## Residual queue (filed as issues)
#930 phase_taxonomy misses weight_episodes/training_reference (restart KeyError — real
bug found by the schema catalog) · #933 ADD_A_COACH.md · #934 alarm-NAME AST sync (kill
the MONITORING drift class permanently) · #935 whoop script housekeeping (move to
setup/) · #936 DR swap-back drill + measure the 30-min RTO claim. Prior gated items
unchanged: PRE-13, HN #741, /verify/ profile URLs, HAE straggler, #748, #916.

**Build beat:** wiki-program-2026-07-10
**Docs:** the program IS the docs — 10 PRs across ~60 pages; all five gates green at wrap.
