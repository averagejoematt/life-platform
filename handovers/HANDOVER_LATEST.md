# Handover — Session AT: 54 → 37 on proof, v0.4 served in order, and the probe that has to live in the body (2026-09-23 13:40 PT → 2026-09-25 09:45 PT)

**Opus, attended with one overnight.** The driving instruction was the owner's /plan: "make a plan to get our 54 issues down to 20 by closing things out without shortcutting quality" (`~/.claude/plans/zippy-orbiting-teacup.md`).
- **Standing authority:** merge own green PRs through `safe_merge.sh` (it refuses on `closingIssuesReferences` or a trailer); fleet-deploy from a clean worktree at origin/main. CDK and infra were asked each time.
- **Rulings mid-session:** the owner answered 1–10. Parallel lanes: yes. The dispatch PAT was regenerated. #4063 contact armed. Hevy load on worked-set time: yes. #3671 via the draft path. SSB/high-bar superseded. #3830 closed on seam tests. #3373/#3436/#3610 folded into Roadmap #3943. The full review stays 10-06. Photos: later.
- **v0.4 brief:** an Upper/Lower program served in order. Keep the fresh-anchor ramp on every anchor (#4148 closed on ruling A). The protein-gated rate target is ruling B.

## What shipped (merged + deployed)

- **19 PRs merged:** #4114 #4120 #4132 #4138 #4139 #4140 #4141 #4142 #4143 #4144 #4145 #4146 #4152 #4153 #4154 #4155 #4156 #4157 #4159.
- **Fleet:** c1e902a9 → 1f49401e → 8b263016 → 775848cb → 54ef62e0 → 535493d1 (v0.4) → **7218b187**, 107/0/0, `build_info` read back.
- **CDK:** `LifePlatformEmail` (09-24 02:40Z) and `LifePlatformMcp` (09-24 14:42Z; created the nightly pre-draft rule `cron(0 2 * * ? *)` and its dead-man), both owner-approved.
- **Private S3 (`config/coaching/`):**
  - `TRAINING_PROGRAM.md` now carries v0.4 (it was a stale v0.2, archived as `TRAINING_PROGRAM_v0.2_2026-09-20.md`); `TRAINING_PROGRAM_v0.4.md` has sha `5365cbe3602e`.
  - `named_human.json` is `armed: true`.
  - 5 routine specs back-filled.

## Verified live

- **v0.4 order:** `plan_next_session` read "week 1 · session 1 of 4 · lower-heavy" before the owner's 09-24 session. After Hevy `3ca1117e…`, it read "week 1 · session 2 of 4 · upper-volume" with `advanced_by`.
- **Nightly pre-draft (#4084):**
  - The manual trigger (09-24 22:11Z) returned `drafted`: routine `7f3ea514…` v3, four critics, no veto, uncommitted.
  - The first scheduled run (09-25 02:00:33Z) returned `exists`.
  - The dead-man went ALARM → OK at 22:13:53Z.
- **#4134:** the 09-24 18:30Z qa-smoke run had FailCount 0, and `qa-smoke-failures` went → OK at 18:31:54Z.
- **#4035:** fresh-eyes run 36066201119 wrote `run_summary.json` (tier 0, 30 findings, 5 on the board, 0 vision failures).
- **#4063:** two healthy nightly decision lines (09-24 and 09-25 03:00:46Z).

## Gotchas

- **A `## Proof probe` must live in the issue BODY.** `closure_probe_qa.py:279` parses `issue["body"]` only. My first #4134 probe was a comment; the hygiene linter's `proof_probe` advisory caught it, and it was moved into the body the same wrap.
- **`gh issue list` caps at 30 rows by default.** I reported "30 open" twice when the REST count was 38. Count with `gh api …/issues?state=open&per_page=100`.
- **A closing condition can be unreachable by design.** On #4063 I promised a `mode=armed` log line that only appears after 3 or more quiet days. It closed on what is observable, with the correction stated.
- **The overnight `aws lambda invoke` sat on a permission prompt for ~6.5 h** (05:35Z → 12:11Z, 09-24); incident row added.
- **Main's badge stranded** on the #2834 IAM gate for LifePlatformMcp, although the owner's CDK deploy followed 29 min later (incident row).

## Residual / next picks

- #4162: hybrid program weeks + the −40 % lock deload + protein-gated rate. Fully green, waiting on two owner answers:
  - the gated rate value (1.6 lb/wk, or 2.5/3.0);
  - ratify the 3 proposed sessions, or keep the owner-note override.
  Then merge, fleet deploy, and live-read `week_basis` + `protein_gate`.
- #4160: a routine note's "RPE 7 max" caps every exercise. Start here next session; it touches the owner's routines.
- #4158: TDEE never credits Hevy-timed work.
- #4134, then #4022, then epic #3592: the 09-25 18:30Z nightly should close #4134 by its probe, which is #4022's first live close. If the PAT write fails, close #4134 by hand and #4022 stays open.
- #4077, #4078, #4076: close on the owner's next coaching chat. He has the exact prompts; #4076 needs a real veto.
- #4065, #4066: close on the next heavy-day commit and a refused mismatched commit respectively.
- #4111, #3552, #3754: Sunday's scheduled runs.
- #3712: the 09-27 forecast row, then the 10-04 grade. Its probe is already in the body.
- #4034: the monthly `[pages]` run around 10-01.
- #3607, #3593: the full review 10-06 (Fable recommended).
- #2978: the 10-19 re-measure.
- #3761: photos, when the owner is ready.
- #4163: an auto-filed visual-QA advisory failure; triage next session.
- Dependabot PRs #4050, #4048, #3826 sit untouched (not-work — dependency bumps, not this session's scope).

**Build beat:** 2026-09-24-served-in-order
**Docs:** docs/alarm_citations.json (interior-gap re-observed, pre-draft birth episode cited), docs/INCIDENT_LOG.md (+2 rows, Patterns regenerated), docs/OPERATING_KNOWLEDGE_LEDGER.md (+8 rows, snapshot + coverage regenerated); the session's PRs carried their own doc edits (RUNBOOK PAT section #4145, COACH_STANCE re-verified #4139)
**Decisions:** none needed — the owner's rulings (v0.4, ramp A, protein B) live in the private program config and on their issues, not in a repo-governance choice
**Main:** stranded — CI/CD 36010082207 at 7218b187 Plan-red on the #2834 IAM gate (LifePlatformMcp OWNER-REQUIRED); the owner deployed that stack from the same tip at 14:42Z, so live matches main and the wrap push re-runs Plan
**Incidents:** 2 rows added — the ~6.5 h overnight invoke permission stall; main's Plan-red strand on the LifePlatformMcp IAM gate
**Stash/hooks:** clean
**Closures:** #3373 #3436 #3490 #3597 #3610 #3671 #3830 #4035 #4063 #4067 #4068 #4070 #4073 #4079 #4080 #4082 #4083 #4084 #4108 #4110 #4123 #4129 #4137 #4147 #4148 #4150 #4151 commented with Shipped/Outcome/Live proof · DoD: scanned 2 (today UTC), hits 0 after the #4063/#4084 residual lines were reworded to `not-work — <reason>`
**Backlog:** Now live at 8 actionable stories; no stale Later issues (later_staleness clean); epic Stories lists reconciled (#3493 +#4135, #3495 +#4134 #4158, #3742 +#4149 #4160 #4161)
**Alarms:** 1 red >72h, cited — freshness-interior-gap (Eight Sleep 2026-09-20 vendor-absent night, re-observed 2026-09-24T16:48Z, self-clears ~09-27); the nightly-predraft-missing birth episode cited
**CI warnings:** unverified — the newest main CI/CD run is not green (stranded Plan), so there is no green run to read annotations from; re-check after the wrap push
**Ledger:** none — no standing machinery shipped in the wrap itself; the nightly pre-draft's rent row landed with PR #4152 and the named-human row with #4063's PR
