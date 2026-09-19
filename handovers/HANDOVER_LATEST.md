# Handover — Session AL: the Fable drain — 25 closed, 10 filed, and the two reds the merge posture bought (2026-09-19 15:41Z → 23:1xZ)

**Driver:** Fable 5.1, autonomous drain. Owner brief: drive the DEBT COUNT (Now+Next+Later + the milestone-less epics = 84) as low
as it honestly goes; 40 the stretch, ~60–65 the plan's own honest landing; standing merge + deploy authority (CDK included);
auto-merge on the two REQUIRED checks only, deploy via `deploy_fleet.sh` from origin/main after each wave, REJECT every CI lease by
name; no `--deliver`. Plan: `~/.claude/plans/elegant-wobbling-beacon.md`. Owner answered the §2 sheet in-session (11 + 4 prompts).

**105 → 90 open, measured two ways (`search total_count` AND a paginated id-set, agreeing). 25 closed, 10 filed, net −15.**
Debt count 84 → 74 (Now 27 / Next 15 / Later 32; the 12 milestone-less epics were milestoned in Wave 0 and are inside those
numbers); Roadmap 21 → 16 (five retirements on the owner's word). **Owner-sheet closures 9** (3716 3771 2883 3042 + Roadmap 1677
1629 1570 1388 1407) · **engineering closures 16** (3614 3750 epic 3491 3731 3677 3692 3513 3877 3816 3769 3603 3543 3817 3717 3546 3608).
**22 PRs merged** (#3889–#3912 and #3921; #3913–#3920 are issues), **4 fleet-class deploys** (3 `deploy_fleet.sh`
runs, 106/106 each; 4 MCP deploys; four stacks redeployed by hand via `cdk_deploy.sh`: Email/Operational/Ingestion for #3890's SSM grant, Serve for #3895's salt
grant), 1 auto site-deploy with the visual gate GREEN (build 7058541), **15 leases REJECTED by name**, 0 approved. Short of 40 by
the plan's own arithmetic, not by a shortfall of work; the reason 60–65 was not reached either is the through-line below.

## The through-line

**The merge posture bought throughput and two self-inflicted reds, and every lane's second-round fix came from CI, not from
reading.** Auto-merge on the required lane let 21 PRs land in 8 hours; the full suite, running post-merge, caught what the lane
could not — twice (F's event-keyed tests, H's ratchet) — and both lanes fixed forward within the session. Nine of the fourteen
engineering closures needed a second CI round on the same PR (a grant the gate demanded, a user-agent string that matched the
secret-name shape, a census identity lost by editing a proven test, a frozen-clock guard, a size ceiling, a Pacific-day ratchet,
a conflicting model regeneration, a sync-owned literal the commit hook refuses). None of those was visible to the lane's targeted
tests; all were visible to the gate. That is the platform working, and it is also the reason a 45-minute lane is a 90-minute lane.

## What closed, and on what (engineering)

| # | Closed on |
|---|---|
| **3614** | the corpus-before-close rule run from merged main, firing on its founding incidents (3 `status: open` specimens) — then epic **3491** on its six closed stories |
| **3750** | the live footer (`instagram.com/averagejoematt`) + the owner's handle + the dated auto-posting rule on epic 3741 |
| **3731** | per-test table (six lockstep scanners cached cross-process; 49.6s → 0.22s) + the first post-merge Unit Tests reading, 1966s, n=1 stated |
| **3677** | the measurement reversed the premise: whoop's 2,249 straddling rows are ALL UTC-keyed, 0 Pacific — the "fix" would have minted phantom gaps; `MissingActivityCount{whoop}` 0 for 4 days incl. post-deploy |
| **3692** | registry 2453 → 2117 lines by extraction; `get_platform_state` listed over the real MCP transport (84 tools) and its summary equal to the page's artifact field-for-field |
| **3513 / 3877** | the row-side audit deployed (37 families); 120 rows backfilled (issue said 6); the third insights writer (MCP `save_insight`) found by the audit and stamped; the 18:31Z nightly reading zero for NUDGE# |
| **3816** | 15 changed re-extractions archived their prior + stamped `supersedes`, live; the 09-07 specimen declared unrecoverable |
| **3769** | `layer_status` on four readers, called live over the deployed server: a `count: 0` that says the layer was readable |
| **3603** | the calendar workflow's green run 35468600861 printing the carry-forward block under the rewritten instrument |
| **3543** | 353 → 0 sub-floor nodes on 64 pages; the visual gate green with the floor measured everywhere for the first time |
| **3817** | the 06-22 head record carrying two `progression` blocks with durations and an `rpe_caveat` joined to `DATE#2026-06-22`'s readiness row |
| **3717** | the deployed attestation record executed: 2021-04-12 → 2026-09-19, 30/45/60 min, on the owner's verbatim statement |

## Findings the work produced that the plan did not predict

**1. The widened audit's first night found the real Set, and half of it was noise by construction.** #3890 replaced a hand list with
`pk_census` + `classify()`; the 18:31Z nightly reported 194 unstamped rows across 17 of 37 families. Split by tagger reach (read-only,
19:33Z): **35 rows on 4 tagger-BLIND families** (PERSONA 19, bare-USER coach_thread 14, COACH#commitments 1, NARRATIVE 1) are real
and filed as #3900; **159 on 13 SOURCE# families** are tagger-reachable in-cycle rows the reset stamps anyway. #3901 split the leg so
the chronic WARN names only blind or pre-genesis rows — a gate nobody can clear trains the reader to skip it (#3851). The alarm
citation was re-pointed to #3900, never dropped while the leg still warned.

**2. Three acceptance boxes were unsatisfiable as written, and each was recorded rather than paid by a look-alike.** 3654 box 4 wants
a dispatched red site-deploy showing the rollback's coverage line — but every injectable failure surface is one the #3652 scope check
DECLINES before the rollback script runs. 3646 box 2 ("next 3 merges green") failed 1 of 3 on the SYSTEM-MODEL gate, a second
bot-owned artifact outside #3896's partition. 3620 box 1 wants `pii_surface_guard` on a schedule — deploy/ is never bundled, so a
qa_smoke leg is impossible; only `ci-cd.yml` can host it. All three stay open, partial, with the member named.

**3. The fullreview-delta was INVALID by the rubric's own two tests, and the calendar carries the dated hold instead of a silent
lapse.** The change surface since the 09-05 baseline is 896 files across every area (>70% of the panel qualifies), and #3904
rewrote the instrument the same afternoon (frozen anchors, the 28-day cap, calibration controls). PR #3910 re-anchors the clock to
2026-09-26 with the reason verbatim; the next fullreview run is a NEW BASELINE. The owner's headroom answer (<50% used) would have
allowed it; the rubric did not.

**4. A backfill without `--since` walked the whole corpus — my omission, not the lane's.** Intending the 40 stored heads under the
1.0.0 → 1.1.0 version bump, `backfill_training_notes.py --apply` also CREATED the ~515 historically-absent note records #3918 had
reserved for an owner call (568 rows written, 53 versioned with priors archived; on the order of 500 short Haiku calls, under the
ceiling). Additive, versioned, readable — recorded on #3918 as a driver act, not claimed as the box's payment.

**5. The owner's 09-18 question on 3717 was stale: the record had been active since 09-08.** Today's statement EXTENDED it to the whole
Hevy window (first stored `DATE#` 2021-04-12 → the statement date). Reading the code before asking would have made it a one-word
confirm rather than a three-value question.

**6. `deploy/agent_commit.sh` silently reverts `lambdas/web/platform_counts.py` to the merge-base on every run** — even when the
branch legitimately carries the sync output (#3891, #3895 both hit it; the file must be committed with a plain `git commit` after
`sync_doc_metadata.py --apply`, hook intact). And `git checkout -- <file>` after a mutation restores HEAD, eating the uncommitted
edit beside it — the #3888 sweep lesson, one file wide, and I did it once before re-applying.

**7. Filed member counts were low again, in both directions.** 3513: 6 filed, 120 reconciled. 3543: 8 pages filed, 10 measured. 3620:
2 hash doors filed, 6 salted. 3677: a "fix" filed, 0 to fix. 3608: `typical_seconds: 90` stored, 1026 measured.

## Deploys and leases

- `deploy_fleet.sh` from origin/main at `2ce05e84e` (17:08Z), `ae53b679f` (20:08Z), `a7c39b102` (20:58Z) — each 106 updated / 0
  skipped / 0 failed, each verified by unzipping named functions and grepping the changed symbol (the row audit, both writer stamps,
  M's facet, the salted hash, the OAuth leg, the versioned note write, the attestation record — executed, not read).
- MCP via `deploy_lambda.sh` at 53e43517, ae53b679, f1e5113b, 9878f42c — each with the ancestry postflight.
- CDK by hand, `--require-approval never`: Email + Operational + Ingestion (the `ExperimentCycleRead` grant the pre-merge gate
  demanded, verified live on two roles), Serve (`IpHashSalt`, verified live). The first CDK attempt exited 1 on the no-TTY IAM
  prompt — the flag is the fix, and the wrapper's own usage line names it.
- Site: one auto site-deploy for #3907, `Visual + AI-vision QA: success`, rollback skipped.
- **15 leases rejected by name**, each with the prose the green-reader consumes; 0 approved; one persistent steward for the whole
  session (a leftover monitor from a prior session was stopped as a duplicate).

## Owner asks

- **3770** (calf-press template, in the Hevy app) · **1738** (TTS by ear) · **1571** (the S3 kit re-upload) — left open on the
  owner's own answers today.
- **3654 box 4** — choose: a `site-shell` injection surface (a real revert lever) or an attended `rollback_site.sh` run, and reword
  the box.
- **3918** — the duplicate-template key collision (the backfill half is done, by my omission).
- The 8 `gate:owner` items the sheet did not reach (3753 3755 3606 2978 …) and the 5 `acceptance_count` violations (3607 3611
  3615 3617 3621), untouched by instruction.
- **3741** — 0 cards posted; the owner intends to post the set in a parallel session (prompt handed over in-chat); box 4 re-measures
  after; boxes 1–2 become satisfiable 2026-09-22.

## Residual / next picks

- **3608 closed post-wrap** on its live CI outputs (the `lane-wallclock` notice at 977s on run 35471979963; the parity step on main's run 35471328402) — `python3 deploy/write_lane_posture.py --measure` joins the wrap ritual — not-work — a `/wrap` skill line for the next wrap.
- **#3900** — the 4 tagger-blind families; the next nightly's line (`35 row(s) across 4 of 37`) is its baseline.
- **#3646** — the system-model gate's `pending-reconcile` verdict (box 2's remaining member).
- **#3654** — box 4 (owner's choice above). **#3620** — box 1's `ci-cd.yml` host.
- **#3913–#3920** — the eight filed from lane findings (whoop's frame facet, the evening-nudge false negative, the 3,185-row inverse
  leg, the orphan guard's import blindness, the inert `integration` marker under xdist, the note-key collision, the calendar's exit-4
  arm, four more `DERIVED_LAYERS` readers).
- **#3897** — 18 serious contrast nodes on `/data/habits/` at 390px light (lane P's find; `site/**`).
- **#3678** — `check_job_timeout_headroom.py` red on main: pr-checks' Collect lane needs 20.74 min vs 18 (lane G measured it).
- The two `unvalidated-merge-closure` sweep hits (69f31b05e → #1921, d681aecc6 → #3715) predate this session — not-work — the
  #3863 class, owned by whoever dispositions `DISPOSITIONED_MERGE_TEXT`.
- **122 worktrees** — not-work — the `/worktree` inventory ritual; every lane worktree this session was released after merge.

---

**Build beat:** 2026-09-19-the-floor-on-every-page — "The 11px floor is now measured on every page" (PR #3907; merged, deployed,
build 7058541 served with the visual gate green).
**Docs:** `docs/PROPORTIONALITY.md` (+2 rows this wrap: #3603, #3546; +1 by #3895: #3620) · `docs/INCIDENT_LOG.md` (+1 row,
Patterns regenerated) · `docs/alarm_citations.json` (qa-smoke-warnings re-cited to #3900, #3901) · `docs/OPERATING_CALENDAR.md`
(regenerated for the hold, #3910) · `docs/CONVENTIONS.md` §4b/§4c (#3906, #3896) · `docs/SCHEMA.md` (the ARCHIVE#/`supersedes`
shape, #3899) · `docs/audits/TD-19_DATE_PARTITION_AUDIT.md` (§ 2026-09-19, #3894) · `docs/MCP_TOOL_CATALOG.md` (regenerated,
#3891/#3902) · `docs/ARCHITECTURE.md` (the salt secret; the 50-module count) · `site/story/build/beats.json` (+1). Doc-impact
sweep: nothing load-bearing was retired except `scripts/deploy.command` (tombstoned in #3908, pending).
**Decisions:** none needed — every call applied an existing ADR or the rubric's own text (ADR-099 closures, 103/144 ledger rows,
104 honest numbers, 133 ceiling untouched); the merge posture was the owner's per-session brief, not a standing change; the
delta hold is the calendar's own sanctioned shape (#3250 precedent).
**Main:** red — the tip's full suite carried F's event-keyed tests (#3896) and H's ratchet (#3902) until #3911/#3912 merged at
21:38Z/20:55Z; the first push run after #3911 is the one to read (decoded; `check_main_green.py --decoded`).
**Incidents:** 1 row added — the merge posture's two self-inflicted full-suite reds (~2h, no reader impact).
**Stash/hooks:** clean — `git stash list` empty; hook freshness 🟢.
**Closures:** 3716, 3771, 2883, 3042, 1677, 1629, 1570, 1388, 1407, 3614, 3750, 3491, 3731, 3677, 3692, 3513, 3877, 3816, 3769,
3603, 3543, 3817, 3717, 3546, 3608 commented, each with an ADR-099 `**Outcome:**` verdict and, on the instrument issues, a `**Live proof:**`
instant · DoD: `closure_sweep.py --session` scanned 31, hits 0, findings 0 (after one round of rewording four verdicts whose
residuals lacked a carrier — the same treadmill as AK, three rounds fewer).
**Backlog:** Now live at 3 (floor 3; fable lane 3 startable, opus 4, sonnet 1); no stale Later issues; `now_liveness` not firing.
**Alarms:** 0 uncited — every alarm red >72h cites an open issue; `qa-smoke-warnings`' chronic clause re-cited to #3900 with the
dated reason; `check_alarm_citations.py` ✅.
**CI warnings:** unverified at the gate run — the latest completed main run was not green (the F/H reds above); the next green
run's annotations are the next wrap's triage.
**Ledger:** #3603 and #3546 rows added; #3620's row landed in #3895.
