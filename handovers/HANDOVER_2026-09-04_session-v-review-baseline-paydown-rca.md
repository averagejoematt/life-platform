# Handover — 2026-09-04/05 (Fable 5.1 → Opus 5 → Fable 5.1): Session V — the review baseline, the batch paydown, the forensic RCA, the owner's pass, and one more reset

**Session:** three owner instructions in sequence. Fable, 17:00 PT: *"fable is back and we have 24
hours to use 100% of our allocation … closes as many issues open as possible … red team with
experts"* — owner calls: run `/review full` NOW, implement #3373, promote #1364's smallest slice,
tee both owner acts. Opus, 23:00 PT: *"manage yourself between now and 7am … pay down as many
open issues as you can that dont need my support, as long as they arent fable"*, escalated to
*"closer to going from 100+ issues back down to 30 with 70 closed … use red team and board
recommendations"*. Then, on the morning's Q&A about the review: *"do a deep forensic analysis on
the report, and then red team all of this … Part 1 root cause … Part 2 monitoring or self
healing … Part 3 a plan to get all areas to grade A … everything should be epics and stories …
if areas will materially increase the running cost of the platform - I do not want to do that
without detailed scrutiny."*

Session U proper (Architect ritual, 09-08, `~/.claude/plans/lovely-snacking-panda.md`) is
**untouched**. #3373 and #1364 were parked when the owner switched models (#3373's worktree
holds 22 dirty files, resumable).

## Part 1 — `/review full`, the NEW BASELINE (Fable, Day 0 of cycle 16)

17 rows graded from scratch with adversarial verifiers. **No A- survived**; 13 fell a notch, qs
rose C+→B-, 3 held. 116 findings → 99 CONFIRMED / 12 REFUTED (10% refutation vs the historic
~50% — recompute-first briefs). Artifacts `docs/reviews/FULLREVIEW_2026-09-05.md` +
`fullreview_grades_2026-09-05.json` reset both calendar clocks and discharged the #3245 hold.
The run died once at ~70 min on the 5-hour session window (17 agents + 2 lanes) and was
resumed from cache after the reset — see the memory entry. **Four rows independently found
the P1 of the night**: the chronicle 48h sweep had republished cycle 15's tombstoned Week-1
draft on Day 0 (#3485). Filed: 10 epics #3489–#3498 + 74 stories #3499–#3571.

Two things had to be fixed before the panel could fan out: main was red on a test that
phrase-matched `"170"` in the frozen prereg (fixed the TEST, never the hash-stamped artifact —
PR #3483, three red-team panels caught my first draft), and #3478 (Day-1 phantom weigh-in)
merged and deployed before 22:30 PT.

## Part 2 — the paydown (Opus, 23:00 → ~09:00 PT)

**28 closed. Board 116 → 91; non-fable 80 → 57. 12 PRs merged.** The honest ceiling was 71,
not 70-as-stretch: 80 non-fable open = 66 stories + 5 epics + 9 owner/date-gated. What moved
the number was CLASS-SIZED BATCH PRs (one PR closing 2–4 siblings sharing files and a
mechanism) chosen by a persona panel — which also found only THREE free closures in 66, so
do not plan a paydown around a free-closure haul. The Day-1 flip was verified live at 00:00
PT (`day_n 1, pre_start false, weighin_count 0`), the #3390 runlist executed (55 countdown
stamps, 2 orphan bets voided), the static Day-1 proof rebaked, #3512's archive notices
applied live.

**Four green PRs are still open, blocked ONLY on the gate-census chain** — #3580 (+8), #3581
(+2), #3583 (+1), #3588 (−2), 11 issues behind them. Each was VERDICT SUCCESS on its own head;
they conflict only on `BASELINE_TOTAL_GATES`. **Merge ONE, rebase the rest, full suite, repeat**
(~25 min/link). Two census movers merged to a silent DUPLICATE assignment earlier, not a
conflict — never merge two without a rebase between.

## Part 3 — the forensic RCA (Opus, morning)

`docs/reviews/FORENSIC_RCA_2026-09-05.md` + `.json` (PR #3591); page
https://claude.ai/code/artifact/7a89cfcc-24f3-4217-9357-aea29d4db057. Method: 4 forensic
analysts (lifecycle stage · guard integrity · session-workflow velocity · data lifecycle) → 6
red-team personas voting on all 26 proposed classes (none killed by ≥2) → 1 delivery
architect. Load-bearing counts re-checked against the tree before publishing.

**The 70 answer:** not a spike — ~5–6 confirmed findings per lens on every review since July;
this one ran 17 lenses (10 ungraded-from-scratch for 5 weeks, ~600 commits/fortnight, 12
resets) on Day 0 of a reset, 10h after a writer had undone the wipe, with anchors raised the
same day. The findings were not silent, they were **unread**: the workflow's instruments
measure the diff, the merge, the closing comment's shape and the count of gates; the defects
live in served bytes, IAM-denied writes (49 days), captions drifted from their number, crons
writing after a green snapshot. Measured: no pre-push hook and zero pytest in
`agent_commit.sh`; ~half of main since 08-22 by direct push; PR template line 19 = "targeted
pytest"; `closure_contract` warn-mode, median open→close 9h; 597 gates / 50 proven; 12 resets
in 55 days on machinery priced "a few times a quarter" (6 of 7 P1s).

**9 classes → 6 structural changes**, all FREE but one ≈$0.01/mo leg: ONE landing path (refuse
code direct-pushes, don't test them) · close on first live output (`Refs` not `Fixes` for
instrument PRs; one closure code armed block) · per-ENTRANT proof ratchet + `## Set` at
intake · the reset writer contract (three one-function fixes first) · derive-don't-detect ·
grade and prune on a clock. **Rent register:** accepted ≈$0.06/mo, ~$9/mo of proposals
rejected, retirements net negative. **What the panel changed about the framing:** "why
silent" → "why does nobody read what is already red"; "what would have stopped it" → "what
bounds time-to-detection"; "all A on an identical re-run" is incoherent (anchors extend
in-run; Day 0 ≠ Day 6; a zero-finding adversarial run has stopped looking) → replaced by:
next full, anchors frozen, run Day 0 AND Day 6, zero P1/P2, no lens < B+, none carried >28d,
instruments proven ≥ added, new rent < $1/mo. **Three owner decisions are named**: the reset
cadence (priced), keep-or-retire the commitment loop, route reader-audience alarms to a
channel you read.

**Filed:** epics #3592 (close on evidence) + #3593 (the review as an instrument); stories #3594–#3603 under #3489/#3490/#3493/#3592/#3593 (#3598 is the P1 — the three one-function reset fixes; #3601 is `gate:owner` — price and bound the reset cadence; #3600 is the only rent, ≈$0.01/mo with its demote trigger); #3528 AMENDED in place (refuse code direct-pushes, don't test them).

**Sequence (the report's "what to do first"):** #3501 (qa-smoke cause identity) BEFORE any new
nightly check → #3536 (per-entrant proof) BEFORE any new guard → `Refs` not `Fixes` + IAM-parity
role family BEFORE any new closure rule or alarm → the three reset one-function fixes (P1),
then the cadence decision with the monthly-close number in front of you → refuse code
direct-pushes in `agent_commit.sh`, replace PR template line 19 → clear the four standing
reds and pull one PROPORTIONALITY demote this month.

## Part 4 — the owner's pre-authorized pass (afternoon/evening PT)

The owner asked why the plan stopped at A-; a second panel (Opus, 5 gap analysts + a
relaxation model + an architect) answered: **cost is not the constraint** ($2.67/mo gross,
$1.37 net closes every rent-priced gap; two anchors price machinery as a NEGATIVE); the
distance is cycle length (11 cycles: 1,5,1,1,2,5,7,7,7,15,4 days; 30 days is the knee),
~22 owner acts (~6h44m), four taste verdicts, anchors that move in-run, and
'every'-quantified clauses whose sets nobody enumerated (538/597 gates unproven, 89 ISO-parse
sites). **Part 4 merged (b8ff4706e, PR #3605).** Filed: **#3606** (the ONE gate:owner
decisions issue, 22 items ordered by leverage) + stories **#3607–#3621** (folded into the
existing epics; no new epic).

Then: *"i give you blanket approval to do all autonomously for 1-22 … i pre-authorize
everything."* Done under that grant, each recorded on #3606:
- remediation role applied from `infra/iam/` (verifier CLEAN, 15/15) · orphan us-east-1 log
  group deleted · **cycle 16 PUBLISHED + SEALED** (`/experiments/prereg/genesis-2026-09-05.json`
  200, sha `a99fbb46…`; cycle-15 posts intact under the cycle-keyed archive) · tier-3 drill
  (both reader doors paused honestly; brief/`BudgetExceeded`/CI-pause legs NOT exercised —
  email invoke) · the five publicly readable reader-input objects rewritten without `email` +
  `ip_hash` and every prior version purged (the panel's "delete-protected" premise was wrong;
  the `email` field was worse than stated) · SES identity for averagejoematt.com created with
  custom MAIL FROM · urgent/paging topics verified confirmed.
- **Owner rulings 7–16 recorded** (#3606 + mirrored): 30-day minimum cycle · absence marker ·
  Dropbox IS a channel · protocols stay experiment-scoped ("reset should be brute force") ·
  Wednesday, one send · rebucket tap targets if the visual stays identical · light-theme QA
  nightly · commitment loop KEPT (owner names their own adherence as the cause) · urgent
  subscription confirmed · incident corpus moves to the repo after a privacy pass · item 18
  demotes: keep/keep/FIX (#3500)/keep-but-cheaper (**#3624** filed)/per-row at #3602.
- **Owner ran item 1 from a second session** (Operational UPDATE_COMPLETE, 24 Lambdas + the
  QaSmokeRole change) and the Route 53 batch (INSYNC; SES identity VERIFIED, DKIM SUCCESS;
  MAIL FROM converging). That session flagged that `build_bundle.py`'s zip is not
  byte-reproducible (three synths, three hashes) — a residual Code.S3Key diff after every
  deploy that reads as drift and is not. Worth a story. It also noted DKIM is the SOLE DMARC
  alignment carrier under `aspf=s` — recorded on #3568. **PR #3623 merged** (f0b003aae).
- **#3598 landed as PR #3622, MERGED 5eb516002** (Fable lane): all three legs — the wipe voids `draft` on what it
  tombstones; `experiment_stamp(as_of=)` derives phase/cycle from the write's date via
  `cycle_for_date`, SSM only post-genesis; `archive_one` keyed on (slug, cycle) under a
  `WORK_CONTRACT` (`run_step` reds input>0 ∧ acted==0, exit 75); 39 tests with run positive
  controls (22/39 fail on main); census 597 → 597; `Refs #3598` with the live proof named
  (next reset's log + the first countdown-window COACH# row carrying `phase=pilot`). Post-merge:
  the shared-bundle deploy. Worktree left locked for release after merge. **PR #3623** drops the
  applied #3562 entry from `_PENDING_PERMISSIONS_APPLY` (my item-2 apply had turned that live
  test red). Still in flight: the Day-1 supersede reflex (326.2 lb replaces the 324.64
  override; `Refs #3390`), and the ~88-row provenance reconcile script (#3511/#3513/#3514).
- **Blocked by the session classifier, owner runs from main:**
  `bash deploy/cdk_deploy.sh LifePlatformOperational -- --require-approval never` (item 1;
  also clears the IAM-gate red on main) ·
  `aws route53 change-resource-record-sets --hosted-zone-id Z063312432BPXQH9PVXAI --change-batch file://infra/dns/ses_averagejoematt_com.json` (item 17) ·
  ~~GitHub Settings → enable non-provider patterns + validity checks~~ — **NOT AVAILABLE on a
  user-owned repo** (the owner's screenshot shows only Push protection under Secret Protection;
  the REST PATCH returns 200 and changes nothing). The panel's 'free on a public repo' was wrong;
  the in-repo equivalent (custom gitleaks rules for the platform's bearer shapes, with positive
  controls) is folded into #3620. Also filed **#3625** (the deploy bundle is not
  byte-reproducible — every post-deploy diff reads as 24 phantom code changes).
- Not done by design: the GitHub org transfer (optional; high blast radius; free alternative)
  and the four taste verdicts + portrait approval (the owner's judgment by definition).

## Part 5 — "can we squeeze in one more reset please" (evening PT): cycle 16 → cycle 17, genesis 2026-09-06

Owner at ~18:50 PT: *"experiment start date as sunday september 6th … figure it out without creating
tech debt or more bugs, i just want to start tomorrow is all."* Flagged once that this closes cycle 16
at ONE day against the 30-day ruling made an hour earlier (#3601, not yet enforced); read as
"tomorrow is the true start". Cycle 16 was PUBLISHED + SEALED this afternoon, so closing it needs no
grandfather record. Pre-reset: the supersede lane was STOPPED (PR #3626 closed as superseded; its one
live write — PROFILE#v1 324.64 → 326.2 — stands and the reset overwrites it with the same 326.2
override; **worth re-landing from branch `issue-3390-supersede-baseline`: `deploy/supersede_baseline_editors_note.py`
+ 12 tests, the gate-driven replacement for the cycle-11 one-shot editor's note — `weight_truth_qa`
will demand a note on week-03 for any override→real gap > 1.5 lb**); the reconcile lane was told to
land its script + dry-run and NOT apply (the reset wipes the cycle-16 rows it targets) —
**PR #3627**: `deploy/reconcile_provenance_2026_09.py` (85 rows planned live: 77 #3514 CROSS_PHASE,
6 #3513 — the SAME defect recurring daily on `INSIGHT#`, 2 #3511; 22 tests; nothing applied) **plus a
one-line fix that matters for tomorrow: `countdown_gap_sweep.classify_item` called
`should_tombstone(item, mode)` WITHOUT `pk`, so ADR-153's CROSS_PHASE carve-out was inert and the next
`reconcile_countdown_gap.py --apply` would have tombstoned the coach `RELATIONSHIP#state` rows. MERGE
#3627 BEFORE the Day-1 runlist's reconcile.** Post-reset apply order is in the PR body
(`--disposition reset-durable --apply` first, the rest after tagger+wipe, then a 0-row re-plan). Dry run clean
(census preflight, all twelve doc gates). Applied:
`restart_pipeline.py --genesis 2026-09-06 --override-weight-lbs 326.2 --with-preregistration --sync-site --apply`.
This is the FIRST reset under #3622's writer contract (the wipe voids drafts; `WORK_CONTRACT` lines
in the log; cycle-keyed archive) — its log is #3598's live proof.

**How it went.** Run 1: steps 0–11 clean (`WORK_CONTRACT {"acted_count": 103, "input_count": 16789 …
"step": "restart_intelligence_wipe"}` — the contract printed, the deploy converged, the live surface
flipped to genesis 09-06 / baseline 326.2 / SSM cycle 17), then **the #3477 sweep ABORTED it** on
`tests/js/genesis_pt_2941.test.mjs` (Nov 5 = Day 61 for a 09-06 genesis, not 62) — exactly the class
it exists to catch, third specimen. Re-derived all nine instants by hand (never loosened; JS suite
377/377). Run 2 (`--skip-deploy`, bundle already converged): rendered · semantic · truth **8/8 PASS**,
site synced, then the seeder REFUSED to regenerate over cycle 16's frozen prereg (by design) →
`git mv` the pair to `_2026-09-05_cycle16` → seeded (16 predictions + 2 hypotheses, sha `bd225d24…`,
`plan_facts` present) → predict-the-week seeded (2026-W36, 2 subjects) → **published + sealed** the
same evening (`/experiments/prereg/genesis-2026-09-06.json` 200, hash matches) → `/method/game/`
rebaked. **Live at wrap:** `/api/journey` day_n 0 · pre_start true · start 326.2 · weighin_count 0.
Not sent by choice: the genesis-eve prereg lock email (`send_prereg_lock_email.py`, eve-only) — the
owner declined it at the last reset; not re-asked tonight.

**Day-1 runlist for 2026-09-06 (post-genesis, in this order):** (1) ~~merge PR #3627~~ **MERGED 1851a9c3d before wrap** — without it
`reconcile_countdown_gap.py --apply` tombstones the coach `RELATIONSHIP#state` rows; (2)
`python3 deploy/restart_verify.py`; (3) `reconcile_countdown_gap.py --apply` then
`reconcile_prereg_voids.py --apply` (that order); (4) `reconcile_provenance_2026_09.py --disposition
reset-durable --apply`, then `--apply`, then a 0-row re-plan; (5) the supersede reflex on the 09-06
weigh-in (this time with the editor's-note tool from branch `issue-3390-supersede-baseline`);
(6) `restart_integration_check.py --deep --synthetic --expect-cycle 17`; (7) read the 10:00 brief
as the owner would. The 30-day minimum (#3601) now has a real cycle to protect.

## Main went red twice more this morning — both opened, both separated

- **Unit Tests** (mine): the citation I added for the genesis-window COMPOSITE was rejected as
  "not declared" — the AST alarm-name discoverer only resolved `alarm_name=`, the #3503 class
  one layer up. **PR #3590**: a separate composite discoverer, universe = metric ∪ composite,
  positive control inside the same test so the census stays at 594.
- **Plan / IAM gate** (since #3573 merged at 23:56 PT, EVERY main run): the qa-smoke role's
  S3List statement was modified in place (+`ai-canary-log/*`), which the additive-only gate
  classifies as owner-required. **Owner act:** `bash deploy/cdk_deploy.sh LifePlatformOperational`
  from main. Nothing on the CI deploy path ships until then (manual `deploy_lambda.sh` still works).
- **Main also redded once on a FLAKE**: `test_wait_pr_green_swallow_3219::test_progress_line_says_how_many_attached_once_some_have` at 63ab2f189 — passes locally, green before and on rerun; the #3455 timing fix is incomplete (noted on #3493).
- Local-only false red: `test_every_alarm_read_states_its_alarm_types` scans the gitignored
  `cdk/_*_staging/` copies — noted on #3493.

## Owner acts owed (in order)

1. **Day-1 weigh-in → supersede reflex.** No weigh-in had landed by the 09:30 PT compute; the
   10:00 brief reasoned from the 324.64 override. Run it the moment the Withings row exists.
2. **Attended cycle-16 prereg publish + stamp** — cycle 16 is FROZEN but UNSEALED.
3. **`bash deploy/cdk_deploy.sh LifePlatformOperational`** (clears the IAM-gate red on main).
4. **`bash deploy/setup_remediation_role.sh`** (#3562 + #3503), then delete the role's entry from
   `_PENDING_PERMISSIONS_APPLY` in `tests/test_grant_enumeration_drift.py`.
5. `aws logs delete-log-group --region us-east-1 --log-group-name /aws/lambda/life-platform-site-api`.
6. The three decisions the RCA names (reset cadence · commitment loop · reader-alarm routing).

## Deploys still owed (merged, not shipped)
`site-api` (#3589's additive key) · `coach-nudge` + `qa-smoke` (#3569) · `qa-smoke` (#3540) ·
`site-api-ai` (#3560) · `cost-governor` + `site-api` (#3583, when merged). #3569's dead-man
will red its first nightly (a 2026-08-30 ledger row `attempting`, ages out 09-06).

## Gotchas hit this session
- **The 5h session window kills a panel + lanes at ~70 min**; resume the Workflow from cache,
  relaunch lanes INTO their worktree (memory).
- **The frozen prereg is hash-stamped**: fix the test, never the artifact (memory).
- **The gate census is the merge-train bottleneck**, not CI; and batched PRs trip
  `check_pr_closing_set.py`'s single-int branch-name parse (folded into #3493).
- **zsh does not word-split an unquoted `$VAR`** — a doc-gate loop "failed" with exit 2 (file
  not found) until `${=c}`; the gates were green.
- `agent_commit.sh` refuses `docs/reviews/*` as doc-sync literals — `ALLOW_DOC_LITERALS=1`.
- **Every enumerator of "the alarms" must state which alarm TYPES it sees** — live API and
  AST alike.

**Build beat:** none — the shipped work this session is review machinery, Day-1 honesty
fixes and a forensic report; no reader-facing feature merged AND deployed.
**Docs:** none needed — the session's documents (the RCA, its Part 4) landed in their own PRs; the wrap touched only this handover and the status block.
**Decisions:** none needed — the owner's rulings (30-day minimum cycle, commitment loop KEPT, Wednesday send, protocols brute-force reset, portrait-less cast) are recorded on #3606 / #3601 / #3621, not as ADRs.
**Main:** red — ea41f094's Unit Tests failed on this handover's own missing gate lines and one ungated residual bullet (this docs-only fix at Session W boot; the run at the fix sha is the verdict).
**Incidents:** none — the two red-mains are decoded in the section above (composite-alarm universe → PR #3590; the IAM gate → the owner's Operational deploy).
**Stash/hooks:** one stash found at Session W boot — `stash@{0} On main: wrapfiles` (2026-09-05 17:40 PT, CLAUDE.md + this handover, a superseded draft of the wrap that ea41f094 then committed); left in place, not dropped, for Session W's wrap to dispose after a diff; the pre-commit hook is in place (`.git/hooks/pre-commit`, executable).
**Closures:** #3511, #3513, #3514 addressed by PR #3627 (Refs — close on the live reconcile) · DoD: scanned=0 window=closed>=2026-09-06 hits=0 findings=0 dispositioned=0 mode=warn.
**Backlog:** Now 22 actionable; 79 free issues across Now/Next/Later are the Session W plan's pool; no promotion this session.
**Alarms:** ✅ every alarm in ALARM state >72h cites an incident row or issue (wrap_gates batch at Session W boot).
**CI warnings:** run 34004648301 sha 6dadafc0 concluded `cancelled` with no failing job — a genuine supersession; the IAM-gate red on #3573's role diff clears on the owner's `bash deploy/cdk_deploy.sh LifePlatformOperational`.
**Ledger:** none — no standing machinery shipped by the wrap itself; the RCA's rent register lives in `docs/reviews/FORENSIC_RCA_2026-09-05.md`.

## Residual / next picks
- The census chain: #3580 → #3581 → #3583 → #3588 (11 issues).
- #3390 (owner acts 1–2 close it), #3403/#2978 (~09-08), #2883 (owner), #3422/#3436/#3373/#3042 fable.
- Session U proper: 2026-09-08 (the #2849 reopen trigger), `~/.claude/plans/lovely-snacking-panda.md`.
