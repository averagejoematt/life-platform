# HANDOVER — Backlog blitz: 17 issues + 7 epics closed, 21 PRs, DR swap-back drilled, reset drill caught real lies — 2026-07-12 (genesis evening)

> Instruction: "maximize paying down as many open issues in this session as possible,
> preferably those most complex or technically more difficult as we are using the Fable
> model. I approve all merges and deploys."

## What ran

Genesis-evening session (~17:45–20:15 UTC), directly after the July-11 review remediation.
Three waves of worktree-implementer agents (8 + 4 + 3) over the entire unblocked backlog,
serial merge queue with per-merge doc-sync reconciliation, plus two driver lanes run in
parallel (the #936 DR drill and the #1094 reset drill).

## What shipped (21 PRs #1145–#1165, ALL merged + deployed + live-verified)

**Wave 1 (8):** #1145 reader-truth gate folded into restart verify (#1097) · #1146 habits
30-day genesis-clamped `days[]` + dot strip (#1107 — live: 59 habits, honestly 1 day) ·
#1147 cockpit hero instrument strip from ring()/sigil primitives, earned-glow honest
(#1106 — its render QA caught a real `Number(null)→0` fabricated-alert bug pre-commit) ·
#1148 supplements `hoped_outcome`/`measured_by` (#1116 — 18/21 annotated live, **values
await Matthew's review**, registry uploaded to S3 config/) · #1149 immersive coach bios:
authored trait scores (`lambdas/coach_traits.py`), `_voice_subset` prompt transparency,
live-record dossier (#1113) · #1150 /data/physical/ fluid-first + registry-derived cadence
chips (#1119) · #1151 chronicle audio: per-article date-keyed read-aloud join — **fixed a
live wrong-audio state** (both prologues played the same panel mp3), reset-unsafe `wk{N}`
keys, an unpublished-draft voicing risk, and a dead IAM permission; producer re-run
rendered `ep-2026-07-11.mp3` (#1121) · #1152 per-timeframe coach narratives: daily
one-liner (honest attribution to the brief, not a fake coach byline), Week lens finally
consumes `/api/state_of_matthew`, month rollup + `/api/month_rollup`, phase-context in all
integrator prompts (#1115).

**Wave 2 (4):** #1154 challenges why-now/measured-by grammar + `hoped_outcome` in the
generator (#1118) · #1155 build-log `why_it_mattered` layer — full 40-beat authoring pass,
field now required by the validator (#1120) · #1157 experiment justification contract
(why_now/priority/hoped_outcome/measurement/evidence_links; `why_now` wired to the
promotion trigger) (#1117) · #1158 Dr. Eli Marsh live at lead tier on by-coach + detail
route, honest "runs the program / files no stances" empty states (#1112).

**Wave 3 (3):** #1163 `/method/game/` — The Game, Explained, generated from the real
engine config with a byte-match + engine-fingerprint drift tripwire (#1124) · #1162
level-up drivers persisted at event fire (engine v1.6.1; read-time enrichment kept as the
honest fallback; sim harness invariants re-proven) (#1125) · #1164 `/data/badges/` badge
wall over /api/achievements + 6-badge catalog extension — live state: 0 of 40 earned,
glow discipline intact (#1126).

**Driver lanes:** **#936 DR swap-back drill + fix (PR #1153)** — PITR restore to isolated
table measured **4m32s**; `iam simulate-principal-policy` proved the documented Path A
(env-repoint-only) was broken as written (implicitDeny — roles scoped to the exact table
ARN); 7 hardcoded env literals + 4 stack literals would have partially reverted any
cutover; all table names now derive from `stacks/constants.py TABLE_NAME`, making the real
cutover ONE env-var-prefixed `cdk deploy --all` (~6 min measured from CI); **measured
Scenario-2 RTO ~15 min vs the asserted 30**; DR doc rewritten, drill table torn down.
**#1094 reset drill (PR #1161)** — dry-run pipeline vs synthetic genesis 2026-08-02 clean;
semantic verify 7/7; **the reader-truth gate's first full run correctly FAILED with real
findings**: the home waveform's static "every day, including the ones that dipped" over a
1-dot chart (fixed #1156/#1159) and the cockpit week/month scope caps (fixed #1160);
re-run confirmed cleared; pre-reset drill contract now a REQUIRED RUNBOOK step. Plus
inline fixes: #1165 binding-map entry for the head-coach page (redded the selfcheck),
#1159 story.js `dayN` redeclare hotfix.

**Epics closed (7):** R1 #1075, R2 #1076, R3 #1077, R4 #1078, R5 #1079, R7 #1081,
R9 #1083. R6 #1080 stays open on #1114 (Matthew art direction); R8 #1082 on #1123.

## Verification

Serial merge queue; doc-sync `--apply` reconciled per test-adding merge (test_count →
3585). Deploys: site-api ×6, MCP (deploy_mcp_split.sh), chronicle-podcast (+1 producer
invoke, 1 episode 0 errors), challenge-generator, ai-expert-analyzer,
character-sheet-compute, CDK LifePlatformEmail (70s), supplement registry → S3 config/.
Final `smoke_test_site.sh` **76/76**; live spot-checks: lead coach API (tier lead, stance
source none, 9 coaches), habits days[]=1, supplements 18/21, /method/game/ 200,
/data/badges/ 200 + 0/40 earned, phase-aware wave claim JS live. Post-genesis watch items
all green: 17:00 UTC coach generation phase-aware ("Day 1 baseline… no intervention claims
yet"), genesis weigh-in in /api/vitals (314 lbs, honest nulls), character v1.6.0 ran 18:30
UTC (level 1, XP 0, honest Day-1 state). Tree clean, zero open PRs, no stashes, worktrees
pruned.

## Gotchas / new reflexes

- **`node --check` misses `const` redeclaration inside function bodies** (V8 lazy parse) —
  my #1156 fix shipped a `SyntaxError` that only the deploy pipeline's full module parse
  caught (publish blocked pre-QA, fail-safe). Verify JS with a real `import()`, not
  `--check`. → memory `reference_node_check_lazy_parse`.
- **CloudFront caches an API 404 for 300s → the site smoke fails and auto-rolls-back even
  though the Lambda deploy was correct** (the #1158 eli_marsh route; two consecutive
  deploys failed on the same cached error). After deploying a NEW API route the smoke
  checks, invalidate its viewer path immediately. → memory `reference_cloudfront_404_cache_smoke`.
- **Env-repoint ≠ cutover** — least-privilege table-ARN scoping silently breaks any
  "just change TABLE_NAME" recovery story; now structurally fixed (#1153) and documented.
- **Byte-match drift guards interact across concurrent PRs** — #1164's registry addition
  changed #1163's generated page; the guard correctly demanded a regen at merge
  (`v4_build_game_explained.py` re-run in the rebase). Generator-owned pages: regen, don't
  hand-resolve.
- **Two agents ran banned `git stash` in the shared tree** (both self-recovered, stack
  verified empty at wrap) — the ban needs to stay loud in agent briefs.
- Budget tier was 1 all session (internal AI paused) — reader-truth full runs used the
  sanctioned tier-0 override, honest tier restored immediately after each.

## Next picks / residual

- **Matthew queue (everything left on Now is yours):** #1123 wk0 prologue regen + attended
  listen (the gate is in) · #1029 re-entry hardening (owner-gated) · #741 essay `[CONFIRM]`
  before HN · #1114 portrait art direction v2 (option rounds) — it alone holds epic #1080;
  #1123 alone holds epic #1082. **Review queue from this session:** the 18 supplement
  hoped_outcome/measured_by values (#1148) and the authored coach trait scores
  (`lambdas/coach_traits.py`, #1149/#1158) are drafted awaiting your edit; by-coach now
  lands on Marsh by default (deliberate lead-tier call — flag if unwanted).
- **Deferred with reason:** #916 (explicitly gated on observed /authorize re-entry
  friction — none observed yet) · #1017 (needs post-genesis real data at 390px).
- **Watch:** first persisted-drivers level-up event (next headline level-up, engine
  v1.6.1) · challenge generator's next Sunday 22:00 UTC run emits `hoped_outcome` ·
  Wednesday 15:40 UTC chronicle-podcast cron on the new date-keyed feed · Monday
  `restart_verify.py` (asserts post-genesis character) · Monday 16:00 UTC traffic digest.
- **Backlog:** Later epics #1000/#1001 (mobile IA/perf) · standing #936→done, #916/#748 ·
  older epics #342/#348/#717–#723 unchanged.

**Build beat:** 2026-07-12-the-machine-audited-its-own-story (see `site/story/build/beats.json`).

**Docs:** DISASTER_RECOVERY.md (Scenario-2 rewrite + drill row + measured RTO, Verified
2026-07-12) · RUNBOOK.md (pre-reset drill contract + drill record) · site pages carry
their own registries (SITE_MAP/sitemap regenerated by the builders in-PR); no other
canonical pages invalidated — engine change was version-bump-only (v1.6.1 drivers field,
SCHEMA untouched: drivers ride the existing event item), MCP tool count unchanged.
