# Handover — Session AO: the red-teamed plan, the treadmill fix, and the trailer that reached main (2026-09-20 10:14 → 2026-09-21 ~19:45 PT)

**Fable, autonomous, standing merge + deploy authority (fleet, MCP, site, CDK — tonight only).** The brief set
63 → ≤45. The honest number at wrap is **57 open in all / 54 outside the Roadmap milestone** — the target was not
met, and could not have been: most of what shipped closes on a next occurrence (a nightly, a monthly close, a
reset) or on the owner's morning rulings, and the night's flagship deliverable is, by design, an owner-gated
document. Gross: **7 closed on live proof + 2 auto-closed (#3980 #3993), 2 filed (#3984 #4008).** The owner sheet
was applied at boot one item at a time (six rulings; two changed the plan on disk — #3753 became a red-team, not a
flip, and #3918 box 4 became a $0 value read, not a paid backfill).

---

## The flagship: TRAINING_PROGRAM v0.2 (#3753 / #3755 / #3754)

The owner did not approve the redlines draft; he asked for "all the coach personas, a red team with the
literature, my historical data from last time, an updated full plan at 3 lb/wk". Five personas — a transformation
coach, an obesity-medicine physician, a performance dietitian, an S&C coach, and a person who lost 100 lb fast and
finally held it — ran independently and blind on one evidence packet compiled from the platform's own record.
Where they converged, independently: **3 lb/wk is defensible now at BMI 46.8 and must taper on a schedule; the
measured 1,533 kcal / 146 g protein is the biggest problem in the record — too LOW; loads must move; "2–3 lifting
sessions" was wrong for him; the deficit monitor's SUSTAINABLE at day 14 is not clearance; walking collapse is the
relapse prodrome; the landing is the plan.** Owner-private: `s3://…/config/coaching/TRAINING_PROGRAM.md` (v0.2;
v0.1 preserved beside it) and `TRAINING_PROGRAM_v0.2_redteam.md` (the packet, the five positions with citations
and dissent, the split table, the reusable prompt). Machine twin: `owner_redlines.py` **v2.0-proposed** (#3994) —
a scheduled rate, an energy floor, protein 200/180, 5–6 lifting days on a load wave, medical cover, nine named
tripwires the engine does not yet evaluate (it says so in every block) — `ACTIVE = False` until he approves.

## What shipped (21 PRs merged tonight, every one `Refs`, no trailers except the one below)

**Driver PRs:** #3987 (#3984, the merge treadmill) · #3988 + #3999 (#3625, `built_at` from the commit; dirtiness
scoped to the staged roots) · #3991 (#3715) · #3994 (#3753 redlines v2) · #4007 (#3005 fix-forward, **armed**).
**Lane PRs:** #3985 (#3761) · #3986 (#3770) · #3989 (#3918) · #3990 (#3755) · #3992 (#3915) · #3995 (#3671) ·
#3996 (#3601) · #3997 (#3931) · #3998 (#3754) · #4000 (#3900) · #4001 (#3982) · #4002 (#3972) · #4003 (#3621 boxes
1+3) · #4004 (#3599) · #4006 (#3620) · #4005 (#3621 box 4, **armed**). AN's #3983 merged at Step 0.

**Closed on live proof (7):** #3625 (0 `S3Key` lines after the deploy) · #3984 (5 of 5 post-fix merges carried zero
regenerables) · #3715 · #3770 · #3931 · #3772 · #3938.

## Deploys — every stack, and which tip each function runs

- **Checkpoint 1 (22:56–23:03Z):** fleet 106 updated / 0 failed + `life-platform-mcp` + `life-platform-site-api`
  from `7c78aaec1` (postflight ancestry OK ×3). CDK `LifePlatformCompute` twice — `d65da1f1f` at 22:05Z (the
  #3625 measurement that failed on a dirty checkout, 32 `S3Key` lines) and `5c51af0ec` at 22:30Z (**0 lines**).
- `inter-coach-dialogue` from `17f41aef2` (00:38Z, #4000) + `backfill_coach_ensemble_phase_stamps.py --apply`
  (2 rows written, 77 cross-phase untouched).
- **Checkpoint 2 (01:39–01:49Z):** fleet 106/0 + MCP + site-api from `de634f585`; CDK `LifePlatformOperational`
  (01:41Z) and `LifePlatformServe` (01:49Z, `-- --require-approval never` — the new `ip-hash-salt` grants; the
  wrapper's first attempt exited 1 with no TTY). CDK-bundled `site-api-ai` reads `de634f58 · commit · dirty=false`.
- **Post-#4002 (02:02Z):** `life-platform-mcp` + `hevy-backfill` from `732e46659`. **So the fleet is split by two
  functions:** 104 on `de634f58`, MCP + hevy-backfill on `732e4665`, inter-coach-dialogue on `17f41aef2` — read
  `build_info.json` per function; every one says `built_at_source: commit`.
- **Attended:** Hevy template `39c60569…` created (`hevy_recreate_template.py --apply`, index 820 → 821, reads
  `calves`); `TRAINING_CONTEXT.md`, `PROGRESS_PHOTO_PROTOCOL.md`, `TRAINING_PROGRAM.md` (+ the v0.1 copy) and the
  red-team record uploaded to the owner-private home; the #3772 draft archived (`archived_local_only`).
- **Site:** no `site/**` merge tonight.

## Leases — 19 rejected by name, zero blanket
35525539152→d7bbecdd5 · 35528208686→b0487726b · 35528257051→ae0aa0d97 · 35532824199→1081b3fb1 · 35537546424→40fbaa446 ·
35538092643→9ff9f71c4 · 35540172268→39360c045 · 35540205924→d65da1f1f · 35541837756→255b78fa2 · 35541883498→5c51af0ec ·
35543133440→7c78aaec1 · 35543288831→9257341db · 35547330298→e134e00f7 · 35548265714→9616570c3 · 35548312052→17f41aef2 ·
35549643212→2ac9e29d1 · 35549686600→bd616dbaf · 35551325003→25fcbfaa6 · 35552303018→732e4665. The two armed PRs mint
one each when they merge — the next session rejects them by name.

## Found by measuring, not by reading

- **#3625 box 3 needed two PRs.** After #3988 the diff still read 32 `S3Key` lines: the main checkout carried the
  owner's modified `.claude/settings.local.json`, and `git status --porcelain` over the whole tree called that
  dirty → `built_at_source: clock`. #3999 scopes dirtiness to `lambdas mcp config deploy/build_bundle.py`. Then 0.
- **A `!` record in the counter file was ignored by `--check`** — printed, then dropped from the verdict; #3987's
  must-fail control found it. And `test_model_gate_pending_reconcile_3646` popped the runner's GITHUB_* env
  without restoring it, which is why the #3384 PR-exempt skip never fired on lane PRs.
- **The pr-checks full-suite check is NOT a required check** (only `Collect + deploy-critical + format` and
  gitleaks are) — auto-merge fired on PRs whose full suite was red on the treadmill.
- **The required job runs at its own wall-clock ceiling** (~14–17 min vs `timeout-minutes: 18`): CANCELLED with
  every step green on #3996 ×3, #4001 ×2, #4002 ×2, #4005 ×3, #4004/#3998 ×1 under concurrent lane load (#3678).
- **A lane's commit trailers reached main through a green PR.** The repo squashes with COMMIT_MESSAGES; #4000's
  commits carried the harness lines; the body check was clean; a depth-1 PR checkout cannot see branch commits.
  **Main's full suite has been red from `9257341db` (22:59Z).** #4007 records the sha (rewriting is forbidden),
  the commit-msg hook refuses the forms, pr-checks scans every PR commit's message (mutation-controlled).
- **My own #3984 hook re-created the counter conflict it was built to end:** "restore to HEAD" during a
  conflict-resolution commit reverted the counter the lane had just taken from main (#4005/#4006 went DIRTY after
  every reconcile). The fix — restore from `MERGE_HEAD` when a merge is in progress — rides on #4007 and is
  installed locally already.
- **The 532 un-extracted notes were 19** (the census on #3989's branch), all 2021–22 programme templates; the paid
  backfill is not worth running. The 2026-06-23 collision needs exactly ONE re-extraction to become two notes.
- **The nutrition door publishes no calorie target tonight** — #3931's impossibility check refuses at 52–54% of a
  3,223 kcal TDEE against the logged 1,533; the owner's §7.6 ruling implemented literally, reader-facing.
- **The cycle-16 prereg artifact is not gone** (PR #3884 said it was) and cycle 17's seal asserts 326.2 lb while
  the site has served 327.34 since 09-06 (#4004's read-only control). **411 archived rows stamp the cycle a reset
  OPENED, not closed** — two conventions (#4008).
- **The training-notes Haiku monthly cap (300) is reached** — 23 of 25 recent notes are `degraded: cap_exceeded`;
  the semantic pass has been dark most of the last 14 days (named on #3918, not this session's to fix).
- The routine-level Hevy note DOES render (owner screenshot); only the GET omits it. Memory corrected.

## Residual / next picks (every line cites)

- **Armed PRs:** #4005 (#3621 box 4 — the citation-network cron; its required job keeps hitting the 18-min ceiling,
  rerun once the full-suite job frees the workflow) · #4007 (#3005 fix-forward — main's full-suite red clears when it
  lands; whichever of the two merges second needs one more ratchet re-merge: total 671 / proven 120 on the merged tree).
  After #4007 merges: `bash scripts/install_hooks.sh` in every checkout.
- **Owner, morning:** #3753 approve/redline v0.2 (then a one-line `ACTIVE = True` PR) · #3918 "run the one" (the
  06-23 re-extraction) · #3761 box 1 (the 09-06 photo set) · #3599 amendment publish (attended) · #3945's register
  (0 posted by hand) · book DXA / labs / ECG (v0.2 §10) · the pharmacology conversation at month 3.
- **Nightly / next-occurrence:** #3900 (18:31Z — expect only the two pre-genesis rows) · #3915 box 4 · #3982 (the
  first newborn watched cron is #4005's) · #3563 · #3830 · #3712 · #3620 boxes 3–4 · #3601 (October close) · #3671
  (next reset) · #3621 boxes 2, 5 · #3972 (deployed; closes on a clean pre-flight).
- **Not started (design, not bug-fix):** #3436 (a design section) · #3754 boxes 3–4 · #3599 boxes 1–2 · #3615 · #3436.
- **Alarm board:** `qa-smoke-warnings` re-cited on its live cause (`data:orphan_routine_drafts`, cured by the #3772
  archive; EXPIRES 2026-09-22) — not-work — the 09-21 nightly clears it or files a new defect.
- **Worktrees:** every merged lane released; `issue-3621-citation-network-cron` and `issue-3005-trailer-fixforward`
  stay until their PRs merge; `issue-3982-newborn-cron-deadline`, `issue-3972-pain-lexicon-history`,
  `issue-3620-iphash-salt-prefix-deny` are merged and unreleased — not-work — `lane_worktree.py release` at the next boot.

**Build beat:** none — the red-teamed plan is owner-gated (v0.2 awaits his approval; #3753 stays open, `ACTIVE = False`), and a drain plus two structural fixes is not a beat.
**Docs:** `docs/CONVENTIONS.md` §1 (the content-addressed CDK asset sentence, #3988/#3999) and §4 + the reconciliation paragraph (the bot-owned invariant, #3987); `docs/coaching/README.md` + `PROGRESS_PHOTO_PROTOCOL.md` (#3985/#3990); `docs/SCHEMA.md` + ADR-094 (#3989); ADR-088 amendment (#3995); ADR-152 amendment (#3997); `docs/engines/HYPOTHESIS.md` re-verified (#4003); `docs/PROPORTIONALITY.md`'s phase-machinery row priced (#3996).
**Decisions:** ADR-094 (#3989, the occurrence key) · ADR-088 amendment (#3995) · ADR-152 amendment (#3997, the worked-set TDEE term) — no new standalone ADR.
**Main:** red — main's full suite has been red from `9257341db` (22:59Z) on `test_reachable_history_carries_no_trailer_since_ban`: PR #4000's squash carried a lane's attribution trailers (COMMIT_MESSAGES); **fix-forward #4007 is armed** (allowlist with the dated reason, hook refusal, PR-commit scan). Unit Tests on the tip are green apart from that one test; every deploy lease is rejected by name.
**Incidents:** none — the #4000 trailer red and the #4005/#4006 counter treadmill were both fix-forwarded inside the session (#4007) with a hook, a CI scan and tests; neither reached a reader surface.
**Stash/hooks:** clean — no stash; the installed pre-commit/commit-msg hooks are #4007's (ahead of main by design until it merges); `docs/alarm_citations.json` is the wrap commit's only dirty file.
**Closures:** #3625, #3984, #3715, #3770, #3931, #3772, #3938 commented (Outcome / Live proof / Residual each) · DoD: scanned=3 window=closed>=2026-09-21 hits=0 findings=0 dispositioned=0 mode=warn blocking=none (the three residual lines re-homed into the `not-work —` grammar before the sweep).
**Backlog:** 62 → 57 open (54 non-Roadmap); Now 20; 2 filed (#3984 closed the same night, #4008 on epic #3495 — its `## Stories` updated); hygiene: 1 violation (#4008 ↔ #3495 story list) fixed, 2 advisories (now_lane_coverage — a sonnet session finds no startable Now story; the #3540 grounding specimen, grandfathered).
**Alarms:** ✅ every lit alarm cites an OPEN issue or a dated self-clearing state — `qa-smoke-warnings` re-cited 02:1xZ on `data:orphan_routine_drafts` with `cause` + `cause_observed`, EXPIRES 2026-09-22 (check_alarm_citations green).
**CI warnings:** latest completed main run red on the #4000 trailer test (see Main); cron-freshness advisory: no open finding (#3980 self-closed 17:20Z).
**Ledger:** omitted — the only new standing machinery is the monthly citation-network cron (#4005, priced FREE on #3621 and still armed at wrap; its row lands with its first run) and the #3915 inverse-census wire-up (a line in an existing nightly, no new rent); `docs/PROPORTIONALITY.md` was regenerated by the reconcile bot after each merge (gate census 665 → 669 on main tonight).
