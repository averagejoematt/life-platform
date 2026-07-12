# HANDOVER — The July-11 review remediated end-to-end: 18 PRs, 52 issues filed, 33 closed, reader-truth QA + one-command reset + /cockpit/ live — 2026-07-12 (genesis day)

> Instruction: Matthew's manual review (`~/Desktop/Review July 11th.md`, 41 items) +
> "plan to review, investigate, convert to issues, and do an efficient session to
> remediate all of them… create a /fullreview type skill… full autonomy" (edits,
> merges, deploys all authorized in-session).

## What ran

Genesis-day session (~06:00–17:00 UTC). The full elite loop: 5 investigation lanes
(Explore agents, live-verified) → 3 adversarial verifiers (finding-verifier) → issue-filer
(52 issues #1075–#1126, 9 epics, `review:2026-07-11` label) → 16 worktree-implementer
agents in 3 waves → serial merge queue (driver) → deploys + live verification. Plus two
unplanned inline fixes CI surfaced mid-train.

## What shipped (18 PRs #1127–#1144, ALL merged + deployed + live-verified)

**Epic R1 pre-start truth (#1075) COMPLETE:** #1127 homepage purpose reframe (thesis: life
satisfaction, weight = instrument; "the finish line" → "the first hard checkpoint"; north-star
doc updated) · #1132 tombstone/phase guards on 7 coach-route readers the #946 sweep missed
(the 1,581-kcal dispute, panel ledger, field notes, cycle digest, board-ask grounding) ·
#1133 honest-numbers guards (min-n + partial-today on steps/strain means — the "62 steps" was
an n=1 partial-day mean; genesis clamps on /api/vitals windows) · #1131 time-travel scrub
scoped to current cycle, genesis derived at runtime · #1128 discoveries relabeled "ongoing
protocols — carried across cycles" · #1136 chronicle prologue curated ("Empty Journal" +
"Body Votes First" retired — `curate_prelaunch_leadins.py --apply` RUN against prod, posts.json
now exactly 2 prologues) · #1130 multi-year labels on VO2max/Walking HR · **#1138 the flagship:
`build_experiment_phase_context()` mandatory in every AI narrative prompt builder** (coach,
SoM, chronicle, board, panelcast) with a coverage test. Plus 2 data repairs driver-run:
whoop DATE#2026-07-08 + habitify DATE#2026-07-09 re-tagged pilot (both poisoned by warm
lambdas stamping with stale constants AFTER the 07-10 tagger pass — new incident class).

**Epics R4+R5 design/IA:** #1137 six-issue design batch (glucose giant-"NO" → designed empty
state, vitals ladder, rd-tbl alignment, coach-card specialty-first headers, ~50-literal token
sweep + 2 genuinely-broken undefined tokens, ONE shared top-bar rule) · #1134 per-source
freshness row (all 13 sources, honest states) · #1135 footer standardization (canonical footer
on home/404/privacy/subscribe/confirm, apply-chrome now INSERTS) · #1139 "The Technology"
footer column + ledger unlisted + /story/agents/ orphan wired + standing orphan-audit test ·
**#1143 /now/ → /cockpit/ rename** — S3-first-then-CloudFront-function ordering executed
(function updated + published LIVE), 7 single-hop redirect assertions green, PWA start_url +
sw.js + sitemap SKIP_TOP handled; **key save: `redirects.map` had drifted from its generator
since v5 — regeneration would have reverted ~60 live redirects; the generator now carries the
v5 split and reproduces the live map byte-for-byte.**

**Epics R2+R3 process:** #1141 one-command reset (fix_prologue + prereg-seed + dedup folded as
post-verify hooks; publish stays attended; **new `restart_verify_semantic.py` gate — ran live,
7/7 pass, and its first real run CAUGHT the habitify poisoned row**; `dedup_source_records.py`
applied: 52 eightsleep UTC-rollover dupes deleted) · #1140 reader-truth QA (phase-aware Bedrock
pass — the check that was structurally missing: visual-AI QA was explicitly forbidden to judge
truth; now hooked post-deploy CI `--reader-truth` + nightly qa_smoke "Reader Truth" category,
budget-tier aware; Operational stack deployed for the role/timeout) · #1129 podcast
conversational-continuity gate (deterministic dangling-thread check post-drop, judge fail-closed,
HOLD instead of publish-best; the 3:53 prologue hole class) · #1142 + #1144 inline CI fixes (below).

**Also:** `/fullreview` skill authored (`.claude/commands/fullreview.md`) — expert-panel graded
review driver, seeded mode takes a manual-review file and applies the understand-spirit →
root-cause → generalize → A/B-classify → regression-guard discipline. DLQ cleared (the queued
Withings message — delete went through this time). Build beat: `2026-07-12-the-site-learned-what-day-it-is`.

## Verification

Serial merge queue, doc-sync `--apply` reconciled per test-adding batch (test_count → 3430+).
Deploys: site auto-deploy green (final run carries everything), `deploy_site_api.sh` ×3,
**fleet ×2 (95 fns, 0 failed)**, CDK LifePlatformOperational, coach-panel-podcast, CloudFront
v4-redirects function published. Live checks all green: dispute null, discoveries carried_over,
vo2 scope multi_year, steps honest-null, 13-source sync line, "first hard checkpoint" hero,
/now/→/cockpit/ 301 single-hop, posts.json = 2 curated prologues, semantic verify 7/7.
`smoke_test_site.sh` 74/74. Worktrees/branches cleaned.

## Gotchas / new reflexes (all encoded in code or memory)

- **Adversarial verification killed 4 confident wrong fixes** (~25% of load-bearing claims):
  portrait "clock" = the deliberate 96px sigil-frame (art direction, not a bug — moved to #1114);
  coach-header swap fights the sitewide eyebrow convention (shipped deliberately scoped);
  time-travel floor + prelaunch calendar were designed; folding `restart_verify.py` into the
  reset would red every reset (it's a post-genesis check).
- **Warm lambdas can re-poison phase tags after a reset** — ingestion re-wrote rows with stale
  constants AFTER the tagger pass (whoop 07-08, habitify 07-09). The semantic verify's
  zero-pre-genesis-experiment-rows assertion is the standing guard.
- **The QA stack was phase-blind by design** — visual-AI QA's prompt forbade truth judgments;
  the smoke test demanded weight on a pre-weigh-in morning (fixed: Day ≤ 1 window). Reader-truth
  QA is the structural answer.
- **CI wiki drift gate false-drifts under a shallow clone** (#1142): `git log -1` per file in a
  fetch-depth:2 checkout returns HEAD's date → every engine doc "drifts" the day after its
  Verified stamp. Lint job now full-history + the checker skips loudly when shallow.
- **The 2000-line god-module gate works** (#1144): #1122 pushed the podcast lambda to 2022
  lines; split `panelcast_qa.py` out rather than grandfathering.
- **`redirects.map` generator drift** — regenerating without the v5 split would have clobbered
  ~60 live redirects. The generator is now the source of truth again (byte-for-byte).

## Next picks / residual

- **Matthew queue:** genesis weigh-in + the Sunday `restart_pipeline.py --apply` re-run (now
  carries the semantic gate; prereg seed/publish per the new printed steps — publish stays
  attended) · wk0 prologue regen + spot-listen (#1123, the gate is in) · essay `[CONFIRM]`
  draft-marker before any HN submission (#741) · #1029 (owner-gated).
- **Post-genesis watch:** first coach-narrative generation with the phase block (~17:00 UTC — the
  stale "Day 1 baseline" sleep-coach OUTPUT# self-replaces; verify it cites Day 1/cycle 5
  correctly) · first v1.6.0 character run ~17:35 UTC · first nightly qa_smoke with Reader Truth
  (18:30 UTC — watch for Haiku false positives, rails are in `lambdas/reader_truth_qa.py`) ·
  Monday 16:00 UTC traffic digest travel-watch section.
- **Open backlog (review epics):** R6 coach experience #1080 (#1112–#1115: head coach in
  by-coach, immersive bios, portrait art direction v2 — needs Matthew option rounds, per-timeframe
  narratives) · R7 protocol/story depth #1081 (#1116–#1121) · R9 gamification #1083 (Later) ·
  R4 residue #1106/#1107 (cockpit instrument strip, habits 30-day dot strip) · R2.3/R3.3
  (#1094/#1097 — reset drill + reader-truth in restart verify) · #1017/#916/#936/#748 + Later epics.
- Doc-debt: ~20 historical `docs/**` `/now/` references (harmless, historical); API.md re-verify
  pass still owed (pre-existing).

**Build beat:** 2026-07-12-the-site-learned-what-day-it-is (see `site/story/build/beats.json`).

**Docs:** CLAUDE.md v4-site section now says /cockpit/ (#1143 sweep); RUNBOOK restart section
rewritten to the one-command contract (#1141); COACH_STANCE.md re-verified post-#1138;
SITE_MAP_AND_INTENT.md updated (#1139). Doc-sync literals reconciled; wiki gates green at wrap.
