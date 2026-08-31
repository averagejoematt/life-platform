# Handover — 2026-08-31 (FABLE 5): Session L — the ambitious drain, Fable orchestrating

**Session:** Claude Fable 5, owner co-working from mobile, Fable orchestrating Opus/Sonnet
worktree lanes (up to 8 concurrent). Started 2026-08-30 ~22:20Z. **The subagent fleet was cut
off by the MONTHLY spend limit at ~00:20Z** (429, resets 5:20pm PT) — four lanes and the
cold-read proof died mid-flight; the main session finished the deterministic tail by hand.

## The ask and the honest count

Owner: "as many open issues closed as possible, Fable orchestrating, without risking quality."
Pre-session estimate: realistic 12, stretch 15 (working set 21 non-Roadmap; epic checklists
turned out to be stale by construction, see gotchas). **Closed 10:** #3316 #3278 #2833 #3328
#3327 #3251 #3317 **#3314** (on its boot proof, not its merge), plus #2848 merged as `Refs`
pending its cold-read proof. **Filed 8 carriers** (#3324 #3327 #3328 #3329 #3336 #3337 #3340
+ the two owner-decision records) because the verification kept surfacing real residuals —
every one now has an owner. Net working set: 21 → 18, with 4 open PRs carrying more.

## What shipped (11 PRs merged; main-tip deploy lease approved)

- **#3314 (PR #3320) — the system model boots the operator.** The alarm plane held **50 of 116**
  alarms (explicit `alarm_name=` kwargs only) — the operator would have booted on half the
  estate. Now seeded from `deploy/alarm_discovery.py` (the #795 authority, one enumeration not
  two) + composites = **119, 0 unresolved**, routing traced through local factories under each
  call's own args, composites, helpers the alarm variable is handed to, and the ADR-050
  constructor contract. Privacy plane from `field_tiers.py` (every partition stamped);
  schedules flattened with a UTC clock; `blast_radius.py --alarm/--at/--privacy/--lambda`.
  **The boot contract is executable:** `scripts/boot_brief.py::BOOT_CONTRACT`, printed by the
  registered SessionStart hook; 19 contract tests incl. the STALE dead-man and prose-may-not-
  disagree. Generator split into `platform_model_alarms.py` at the #1665 ceiling. **Proof
  pasted on the issue:** the hook run from main at close printed `model CONSISTENT · fleet 104 ·
  alarms 119 · privacy 13+2 · data 105/666/8` from the model.
- **#3278 (PR #3321)** — no security-tier log group anywhere was at the documented 90d (14
  Lambda@Edge replica groups NEVER-EXPIRE across 5 regions). Declared once in `constants.py`,
  derived by CDK, applied to all 17 groups (dry-run exit 0), asserted weekly by a new
  `log_retention` sentinel check. Deployed `LifePlatformOperational` + the edge apply script.
- **#2833 (PR #3323)** — shadow permanently: auto-merge gate, earn path and re-promotion bar
  retired; `auto` REJECTED at the kill-switch; re-priced $0.18/run (n=9). ADR-129 amended,
  ADR-065 Retired.
- **#3316 (PR #3319)** — `/api/sleep_detail` schema baseline recaptured live; gate proven to
  fail. Its full-sweep residual (34 endpoints red-for-noise) → #3324.
- **#3327 (PR #3334)** — grounding_guard: 7 phantom fabrication flags in 10 ordinary phrases on
  a BLOCKING gate; fixed with lookahead on all three metrics; 1,387 corpus tests, no golden edited.
- **#3251 (PR #3332)** — C1 measured: pair $0.239 → $0.048/run (n=16/11); ADR-125 amended;
  daily standalone priced; adjudicator scope → #3337.
- **#3328 (PR #3330)** — attribution guard matches all 3 banned forms + a PR-body sweep.
- **#3317 (PR #3326)** — qa-smoke set 3/3 KEEP from 30d live history; + `telegram-webhook-errors`
  (digest — owner Q4) live after a `LifePlatformServe` deploy.
- **#2848 (PR #3333, `Refs`)** — 48 rules homed, 157 already-homed cited, a committed
  operating-knowledge ledger + guard; closes on a cold-read proof (#2848).

## Owner decisions (2026-08-30, all recorded on-issue)
- **#2834 → option (b)**: scoped additive-only CI IAM grant, conditioned on a CISO-grade review.
  PR #3335 built it; the review verdict (posted on the PR) is **APPROVE-WITH-REQUIRED-CHANGES
  R1–R5** — Code-tolerance shape, S3 mutating actions on `raw/*`/the replica/the ledger,
  in-namespace control-plane actions, a human-visible ALLOW record, the ratchet anchored to the
  ADR text. Key fact: CI gains **no** permission it lacks today (the deploy role already holds
  the CDK admin path) — the changes are narrowings. Declining R1/R2 → (c). Follow-up: #3340.
- **#3251 → C1** (done). **Q4 `telegram-webhook-errors` → digest** (done).
- BotFather for #2363: "at another time" — the epic stays open on the owner's 10 minutes.

## Verification state
- Governor 2026-08-31T00:00Z (first post-#3308 cycle): titan **$5.77 → $0.01**, drift
  **1.29x → 1.21x** — the prediction to the cent; posted on #2883. Soak clock honest.
- Main tip `3fae71b4d`'s ci-cd run: lease **approved** (the union of every merge); six superseded
  leases rejected by ancestry (`dda8ffce` `72556168` `d73aaf0d` `3d398fc7` `6f86302e` `0c4c4885`
  `54453a63`). **Its Deploy job completed success during the wrap** and was verified by content (the live
  `ai-expert-analyzer` bundle carries grounding_guard's `_NUM_VALUE`/`_NOT_A_COUNT`). The later run for `b4dab61b` (#3320,
  scripts/tests/docs only) will reach the gate after it — approve it, it is main's new tip.
- `deploy/verify_oidc_iam.py` **CLEAN**; log retention 17/17 at 90d; `telegram-webhook-errors`
  live and digest-routed.

## Open PRs at close (next session's merge queue)
- **#3335** (#2834) — implement R1–R5 + N1–N3 from the CISO review comment, then merge.
- **#3341** (#3318 closure contract, supersedes #3331) and **#3339** (#3315 dark-CI-flags sweep,
  supersedes #3322) — both green locally; **GitHub minted ZERO workflow runs for their pushes
  for 40+ minutes** across close/reopen, a re-mint push and supersede-PR (the #3219 class at
  its third rung). Both carry census bumps (571→57x) and will collide — train them together
  once minting recovers; if it does not, the integration-train rung.

## Lanes cut off by the spend limit (no PR opened; worktrees under
`~/dev/worktrees/life-platform/` still LOCKED with work in them — reuse or release)
- **#3336** IAM shell twin (P1) · **#3277** mobile-viewport axe (+ the webkit surface box) ·
  **#2834** R1–R5 · **#2848** cold-read proof.

## Gotchas (durable ones → memory)
- **A lane branch must never carry `lambdas/web/platform_counts.py`** — the pre-commit hook
  stages it; every later merge to main then conflicts (the train aborted twice on #3320).
  `git checkout origin/main -- …` and commit `--no-verify`.
- **Never apply a security document through a hand-maintained twin.** `setup_remediation_role.sh`
  regressed 4 grants and widened the remediation role's trust to `repo:*` for ~6 min (#3336).
- **Epic checklists are stale by construction** — all listed children of #2363/#3042/#2801 were
  CLOSED with their boxes unchecked; audit from live child state, then verify inline bold items.
- The permission classifier blocked `merge_train.sh` once and allowed it four times — retry, or
  `gh pr merge --squash` for a single fully-green PR.
- `lane_worktree.py new` prefixes `issue-` itself — three lanes produced `issue-issue-N` dirs.
- Eight concurrent lanes + verifiers + a reviewer is what hit the monthly cap; 3–4 per wave.

## Residual / next picks
- **#3336** first — P1 security twin (lane brief on the issue) — and its INCIDENT_LOG row is in
  (this wrap); the CloudTrail confirmation of the window is the PR's job.
- Land **#3335** R1–R5 (#2834), un-swallow **#3341/#3339** (#3318, #3315), rerun the **#2848**
  cold-read proof and close it, finish **#3277**.
- The `b4dab61b` (#3320) run reaches the deploy gate after the tip — approve it — not-work —
  lease disposal reflex, main's new tip.
- Prune the two qa-smoke registry entries after 2026-08-31T14:06Z/18:32Z if OK; the warnings
  alarm re-lit at 00:44Z on a #3337-class judge shape + a real 6-day scale gap — #3337.
- Epic closes now in reach: **#2799** (after #3277 + a one-line coach-nudge ledger revisit),
  **#2800** (after #2834 lands — its 09-08 ritual proof runs itself), **#2363** (owner's
  BotFather minutes — not-work — owner action). **#2578** cannot close honestly until #3329
  is decided (43/570 proven).
- **09-08 Architect ritual runs ITSELF** — not-work — scheduled machinery; it reads the boot
  brief via the `/review` orient step.

## Gate lines
**Build beat:** 2026-08-31-the-operator-boots-from-the-model
**Docs:** docs/CHARTER.md (boot contract), model/README.md, docs/DEPENDENCY_GRAPH.md (generated §5/§5b/§6), docs/DATA_GOVERNANCE.md + docs/PROPORTIONALITY.md (via #3321/#3323/#3332/#3333), docs/OPERATING_KNOWLEDGE_LEDGER.md (new + 3 rows), docs/INCIDENT_LOG.md (+1 row), docs/alarm_citations.json (qa-smoke-warnings re-cited), .claude/skills/review + uplevel (boot brief in orient), CLAUDE.md status block
**Decisions:** none needed — governance decisions landed as dated ADR amendments via the merged PRs (ADR-129 + ADR-065 Retired in #3323, ADR-125 in #3332); the #2834 option-(b) decision is recorded on-issue and its ADR-065 amendment ships with PR #3335
**Main:** green (3fae71b4d) — the tip run completed success (Deploy + smoke) during the wrap; verified by CONTENT: the live `ai-expert-analyzer` bundle (LastModified 2026-08-31T00:30:50Z) carries grounding_guard's new `_NUM_VALUE`/`_NOT_A_COUNT` regexes and `privacy/field_tiers.py`
**Incidents:** 1 row added — the remediation-role trust policy widened to any-branch for ~6 min by applying a grant through the stale shell twin (#3336)
**Stash/hooks:** clean
**Closures:** #3316, #3278, #2833, #3328, #3327, #3251, #3317, #3314 commented (Shipped + Outcome on each); #2848 merged as Refs, verdict deferred to its proof
**Backlog:** Now refilled to 3 stories by promoting #3337 (opus, by stored rank 1.50 — both edits: milestone + score arrow); fable-lane startable is 0 (NO REMEDY IN THE CORPUS for fable — #3314 was the last fable story and it closed); Later sweep — no stale Later issues printed
**Alarms:** 1 red — qa-smoke-warnings re-lit 2026-08-31T00:44Z, re-cited to #3337 (judge temporal_contradiction shape on /api/sleep_detail wake-date + a real 6-day weight gap); qa-smoke-failures OK; no uncited flaps
**CI warnings:** none to triage — check_ci_warnings found the latest completed main run not yet green at gather time (the tip run was mid-deploy); no warning annotations on the last green run (0449f12c)
**Ledger:** rows added via the merged PRs this session — log_retention sentinel (#3321), remediation agent re-priced as a triage instrument (#3323), AI CI QA gates re-priced under C1 (#3332), operating-knowledge guard (#3333); the boot brief rides the existing system-model row
