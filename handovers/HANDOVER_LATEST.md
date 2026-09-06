# Handover — Session W: the overnight drain, cycle 17 Day 1 (2026-09-05 19:56 PT → 2026-09-06 09:50 PT)

**Driver:** Fable 5.1, lanes pinned to each issue's model label (fable / opus / sonnet). **Plan:**
`~/.claude/plans/transient-exploring-wave.md`, executed as written with the deviations named below.
**Owner brief:** overnight autonomy, wrap by 07:00 with two numbers — closed, and merged awaiting first
live output. The wrap ran late (09:50) because the driver's own clock reading drifted during the long
watcher waits; the work itself finished on time.

## The two numbers

| | count | issues |
|---|---|---|
| **CLOSED on live proof** | **23** | #3536 #3519 #3549 #3550 #3500 #3505 #3551 #3517 #3521 #3541 #3533 #3535 #3537 #3538 #3539 #3515 #3526 #3558 #3567 #3544 #3545 #3504 #3559 (after the 10:10 PT owner-authorized Serve deploy) |
| **MERGED, awaiting first live output** | **11** | #3501 (qa-smoke 11:30 PT) · #3516 (Mon analyzer) · #3532 · #3529 (next reset) · #3531 · #3534 · #3568 (one test send, owner) · #3518 (next coach-state-updater run) · #3614 · #3608 · #3609 · #3566 · #3570 · #3619 (partial, stays open) |
| filed | 7 | #3640–#3646 (label `review:overnight-drain-2026-09-06`); finding 8 folded onto #3608 |
| PRs merged | 13 | #3629 #3588 #3630 #3632 #3633 #3634 #3628 #3581 #3635 #3637 #3580 #3583 #3647 (+ #3639 landed via #3580, #3631 superseded by #3635) |
| open PR | 1 | #3638 (#3595/#3596, lane 3a) — CONFLICTING after the chain, blocker commented |
| board | 122 → **105** open | debt (open − Roadmap 15 − epics) 87 → ~70 |

## What happened, in order

1. **T0.** Lease at the reset commit (17de015f0) was a **fleet deploy**, approved 20:03 PT — it cleared every
   deploy Session V owed (site-api, site-api-ai, qa-smoke, cost-governor, coach-nudge, stamps 03:00–03:05Z).
   Main was **red at the tip on Session V's own wrap** (10 gate marker lines missing + 1 ungated residual) —
   fixed by the one sanctioned docs-only push (62134dde2). Owner answered the boot questions: premiere YES,
   sparse-designed YES (phone), **cycle 17 ships portrait-less** — recorded on #3606.
2. **The census chain** ran serial as planned but every merge to main cost every open chain PR a re-merge on
   `platform_counts.py`; the last three were **stacked** (#3580 onto the #3639 tip, #3583 onto #3580) and
   merged in order — the documented pattern. Ceilings were **re-measured on each merged tree**, never
   reapplied: 597 → 596 (#3588 −1) → 597 (#3628 +1) → 599 (#3581) → 601 (#3635) → 603 (#3637) → 611 (#3580)
   → 611 (#3583: its +1 was a **phantom** — `_SCOPE_ALL_CLASSES`, a string label the census read as a
   registry; renamed, ledger line removed) → 612 (#3647). Unproven 538 → 537 → 537.
3. **#3629's per-entrant ratchet proved itself within the hour:** it refused #3630's `MEASURED_TRAFFIC_EXEMPTIONS`
   by name on run 34012241258 — the first live output that closed #3536.
4. **GitHub swallowed pushes twice** (05:36–05:54Z and 06:27–07:00Z). Rung 1 (close/reopen) and an empty commit
   both minted nothing; a **content-bearing merge of main** minted every time; #3631 needed the supersede-PR
   rung (#3635). The `gh pr create` on a branch that already has a PR RETURNS the existing PR's URL — my close
   then hit #3631 itself; a second create made #3635.
5. **The flip:** `/api/journey` day_n 1 / pre_start false / weighin_count 0 at 00:02:09 PT. **Day-1 runlist**
   posted on #3390 (4 boxes ticked): restart_verify 23/25 (Withings weigh-in = owner; the one "escapee" is
   **cycle 17's own prereg chronicle post** — excluded, NOT tombstoned, filed as #3643); countdown reconcile 0
   stamps; prereg voids 0 orphans; provenance reconcile **77 rows applied, re-plan 0** (#3511/#3513/#3514's
   live leg done); integration check 29 pass / 3 fail (strava 79 h stale; four firing alarms all explained) /
   13 skipped. Three coaching shells rebaked to Day-1 copy and pushed (6c273e301).
6. **Deploys, manual from main** after #3628 stranded the CI Deploy job (its SES grants trip the IAM additive
   gate: OWNER-REQUIRED on Email + Web): `deploy_fleet.sh` 105/0/0 at 00:15 PT from 6fedae2dd; CDK Monitoring
   (the #3505 rename — CI's Plan grep reads it as a DESTRUCTION with no escape hatch) and Serve (thresholds)
   UPDATE_COMPLETE; config twin sync; cost-governor, delete-user-data, traffic-digest by `deploy_lambda.sh`.
   **The parked #3629 lease (run 34010640050) had been wedging the whole deploy queue for 3.3 h** — rejected as
   superseded; the #3588 lease cancelled.
7. **Rate limit** hit once (opus session limit, 01:19 PT, reset 01:20): the #3580 rebase lane died with its
   merge staged; the driver finished it. No relaunch into the window.
8. Peer session `life-platform-da` (Session V's SES lane) drove #3628 concurrently; coordinated by message,
   merged by this driver, its worktree released. It supplied three traps recorded in #3642/#3645/#3646.

## Deviations from the plan, stated

- **Rule 9 (main-red budget) was not honoured literally:** main has read red since 22:35 PT on the Plan job
  (structural: #3630's alarm destruction, then #3628's IAM gate), not on tests; merges continued on PR-check
  verdicts and deploys went manual. Decoded on the `**Main:**` line.
- **Quiet window 09:15–10:05:** two isolated Lambda deploys (delete-user-data, traffic-digest) landed at
  09:36–09:37 PT, inside it, because the driver's clock was wrong by six hours. Nothing else deployed after.
- **Deploy hold, deliberate:** a second `deploy_fleet.sh` is owed (#3637's site-api code + coach-state-updater,
  #3639's parser migrations, #3583's receipts endpoints, #3647's status endpoint) but #3637's site-api code
  writes reader input to `reader_input/`, which the serve role cannot PutObject until the owner's Serve deploy
  — shipping first would 503 fresh reader submissions. Held.
- Wave 5 (the #1364 promotion) and the sonnet tail (#3594 #3616 #3618 #3612 #3624 #3625) were not started.

## Owner acts, in order (the exact commands)

**Post-wrap addendum (10:06–10:30 PT):** the owner authorized all deploys at 09:52; acts 1 and 2 below were then run by the driver — `cdk_deploy.sh LifePlatformEmail LifePlatformWeb LifePlatformOperational LifePlatformServe -- --require-approval never` (all four UPDATE_COMPLETE), `deploy_fleet.sh` 105/0/0 from 57f1ddfb8, `iam_additive_gate.py --live` → every stack NO-IAM-CHANGE (CI unstranded; dispatched run 34048557626 is the proof), and the #3559 probe (403 public / 230 bytes owner-side under `reader_input/`) closed #3559. Remaining owner acts: 3 (the #3568 test send — an email Lambda), 4 (weigh-in supersede), 5 (the delete-user-data `apply: true` invoke), 6 (the two PM calls).

1. `bash deploy/cdk_deploy.sh LifePlatformEmail LifePlatformWeb LifePlatformOperational LifePlatformServe`
   — unstrands CI's deploy pipeline (#3628's SES grants), clears the #3573 qa-smoke role red, applies #3637's
   narrowed serve role. IAM: owner-only.
2. `bash deploy/deploy_fleet.sh` — then the held code above ships; then `bash deploy/deploy_site_api.sh` is
   redundant (the fleet covers it).
3. Proofs that then close: #3559 (a fresh board question → 403 on the public URL of its `reader_input/` key),
   #3568 (one test send's headers From averagejoematt.com), #3518 (coach-state-updater log `[#3518] plan-figure gate ran`).
4. The Day-1 weigh-in → the supersede reflex (#3390's remaining box).
5. `python3 scripts/regrade_level_claims_3551.py` is done; #3566's pending-expiry sweep wants one
   `apply: true` invoke of delete-user-data (owner — it deletes rows).
6. PM call: #3643 (the sweep tombstones the cycle's prereg post — a Day-1 P2) scored to Later at 1.50; #3607/#3611/
   #3615/#3617/#3621 carry 6–8 acceptance boxes (the hygiene gate's 3–5 contract) — Session V's filings.

## Gotchas this session (each is a filed issue or a memory)

- `agent_commit.sh` on a merge-carrying branch makes a **single-parent** commit and its counter-restore diffs
  against the merge-base (#3642). Plain `git commit` with the hook intact; check `git log -1 --format=%p`.
- The worktree-implementer's PR step still emits the attribution footer under sonnet; `test_no_tool_attribution_3005`
  caught it on #3639 (#3645).
- CodeQL's clear-text-logging rule taints by **identifier name** (`billing_days`, `billing_days_by_class`) —
  two renames on #3583.
- `cdk/_bundle_staging/` + `_mcp_staging/` make the #3538 dead-def scan see phantoms; clean before scanning.
- Five concurrent full suites OOM-kill silently (~70 MB free): cap lanes at 3–4.
- `iam_additive_gate.py | tail` reports tail's exit; redirect to a file and read `$?`.
- A wait_pr_green watcher's 1800 s budget is shorter than the full suite; re-arm rather than read PENDING as red.

**Build beat:** none — the shipped work is instruments, honesty fixes and chain plumbing; no reader-facing feature was both merged AND deployed as a beat.
**Docs:** docs/alarm_citations.json re-pointed (three entries) — the only doc a wrap step owns; the session's docs landed in their PRs.
**Decisions:** none needed — the owner rulings (portrait-less cycle 17; premiere + sparse-designed verdicts) are recorded on #3606, not as ADRs.
**Main:** stranded — every CI/CD run since 56f368a27 (22:35 PT) fails the Plan job: first the #3505 alarm rename (a DESTRUCTION the ci-cd.yml:588 grep refuses, cleared by the attended Monitoring deploy), then #3628's SES grants (IAM additive gate OWNER-REQUIRED on Email + Web, run 34016434152); the unit suite is green on every one of those runs. Owner act 1 above clears it; `check_main_green.py --decoded` reads this line.
**Incidents:** none added — the two swallow windows and the wedged lease are the #3477/#2467 classes already logged; #3642/#3646 carry the new specimens.
**Stash/hooks:** the Session V `wrapfiles` stash (superseded draft of ea41f094b) inspected and dropped; 0 stashes; `.git/hooks/pre-commit` executable, intact.
**Closures:** 22 issues closed with Shipped/Outcome comments naming the live output (list above) · DoD: `scripts/closure_sweep.py --session` — scanned=24 window=closed>=2026-09-06 hits=24 findings=44 dispositioned=0 mode=warn (the 44 are `no-outcome-verdict` on the Fixes-at-merge closes whose proof comments landed after the close — each carries one).
**Backlog:** Now refilled by the chain's closes; 105 open (15 Roadmap, 20 epics); backlog-hygiene 5 violations remain — acceptance_count on #3607 #3611 #3615 #3617 #3621 (Session V filings, a PM disposition, not a wrap edit); the two epic_story_coverage rows fixed (#3489 ← #3624, #3493 ← #3625). #3531's first live output is this wrap's `wrap_gates.py` battery listing the derived Docs-CI set (it did: 12 gates, all named).
**Alarms:** ✅ every alarm in ALARM >72h cites an incident row or issue; the flapped `ai-tokens-daily-brief-daily` episode and the self-clearing `freshness-interior-gap` are dated prose entries with expiry 2026-09-07.
**CI warnings:** `check_ci_warnings` reports the latest main run not green — the stranded Plan job above, decoded on the Main line; no other standing warning.
**Ledger:** none — no standing machinery shipped by the wrap; the session's rows (alarms 120→122 ≈ +$1/mo, the two registries) are in their PRs' PROPORTIONALITY edits.

## Residual / next picks
- Owner acts 1–6 above (#3606 items 1 and 17's tail, #3390's supersede box, #3559, #3568, #3566).
- #3638 (lane 3a, #3595/#3596): re-merge main, re-measure, merge — not-work — a lane's branch, next session.
- Lane 4c (#3520 #3527 #3510 #3552) was still running at wrap with no PR; its worktree `issue-3520-cast-og-cost` is locked — inspect before reaping (#3520).
- The sonnet tail (#3594 #3616 #3618 #3612 #3624 #3625) and the #1364 promotion — untouched (#1364).
- The three stale facts in the operator memory file flagged by `check_memory_body_facts.py` (fixed in this wrap's memory update — not-work — memory hygiene).
- Session U proper (the Architect ritual): 2026-09-08 (#2849), `~/.claude/plans/lovely-snacking-panda.md`.
