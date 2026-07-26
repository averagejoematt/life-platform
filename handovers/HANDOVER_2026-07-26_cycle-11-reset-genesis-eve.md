# HANDOVER — cycle-11 reset day + genesis-eve sequence + billing sentinel (#1613) — 2026-07-26

> Instruction thread: **solo** reset-day session, this session OWNED main (merge + deploy own
> work); standing approval for ALL merges, Deploy-gate approvals, deploys incl. `deploy_all`.
> Workstream order from the driving prompt: (1) the ADR-077 platform reset FIRST (Matthew
> present for the dry-run review), (2) fable paydown, (3) quality sweep. (1) completed in full
> including the attended genesis-eve engagement sequence; (2) got #1613 (opportunistic — Matthew
> pasted the billing PAT mid-session) plus two sentinel-hygiene fixes off the sweep's first
> findings; (3) was **spun off by Matthew into a parallel read-only session** (reviewers file
> issues only, no main contention) — its findings land as issues, NOT in this handover.

## What shipped — cycle 11 live + 8 direct-to-main commits, all deployed, main GREEN

**The reset (ADR-077, one command + attended follow-ons):**
- `restart_pipeline.py --genesis 2026-07-27 --override-weight-lbs 317.61 --apply` — cycle 10→11,
  baseline 317.61 (honest last-known from 07-22; genesis is tomorrow, no weigh-in can exist).
  Census preflight 87/87 pk families; 59 phase-tagged; 332 tombstoned (12,343 scanned, 0 errors);
  ledger closed (cycle 10: 0 transactions) into LIFETIME#; RESET_LOG appended; SSM cycle=11.
- **Gates: rendered 93/93 · semantic 7/7 · truth loud-SKIP at budget tier 1** (honest). Zero
  rendered false-positives this cycle (contrast the cycle-10 small-gap class).
- **First reset over the 9 new coach-layer surfaces — classifications held:** MILESTONE#
  survived untouched (empty partition is correct — first sweep baselines via the
  `LEDGER#genesis`/`#windows` markers, never announces), journal_quotes + youtube kept
  (RAW_TIMESERIES), `ENSEMBLE#docket` in the wipe registry (honest 0), CONFIDENCE# tombstoned.
- Live after site sync + invalidation: `pre_start: true`, `days_until_start: 1`, start 317.6,
  honest nulls everywhere.

**Matthew's standing t-minus rule made structural (`62d50df5`):** "prequel chronicle articles
always roll t-minus genesis" — "The Night Before Everything" promoted into `PRELAUNCH_CALENDAR`
at `days_before=1` (the ONLY sanctioned carry mechanism; `--keep-chronicle` is a legacy override
that silently DISABLES calendar mode). Prose vetted date-agnostic first via new
`deploy/vet_night_before_leadin.py` (backup-first to /tmp + private S3, exactly-once edits,
idempotent — the restart_leadin_repair discipline): weekdays neutralized, "for the first time"
dropped, cycle-10 start-weight figure generalized (ADR-104).

**Genesis-eve engagement sequence (#1378, attended, ALL completed):** cycle-9 frozen prereg
archived in place → seeder --apply (16 predictions + 2 hypotheses frozen for 2026-07-27) →
"The Plan, On the Record" published (Prologue Part III) → public seal uploaded + **live hash
verified byte-for-byte** (`adece752…`) → predict-the-week vs frozen targets uploaded (calories +
steps, no weight subject) → **"Predictions lock tonight" email sent 1/1** (Matthew's explicit go).

**Bugs found & fixed on main (all deployed):**
- `774631fb` — **calibration post-reset resurrection P3** (flagged in #1481's review, confirmed
  in code): BOTH CONFIDENCE# write paths (conversation calibration + data-path evaluator) did
  get→inherit→full-item-put with no tombstone check — the first cycle-11 write would have
  resurrected wiped rows carrying cycle-10 Beta accumulators. Now tombstone-aware (fresh
  Beta(1,1); LEARNING# keeps history) + `experiment_stamp()` on both puts. 2 regression tests.
- `ac753774` — **live page-key collision** (the date tie the calendar promotion created): both
  genesis−1 posts computed seq 2 → both wrote `week-02/index.html`; the prereg publish silently
  overwrote "The Night Before Everything" live. seq/label now key on `(date, sk)` in parity
  across restart_leadin_pages + journal_post_ref + publish_to_journal closures; live re-rendered
  Part I/II/III distinct; regression tests both sides.
- `4e660ef6` — config-drift checker region-aware: `email-subscriber` (us-east-1, web_stack) read
  "NOT DEPLOYED" from the us-west-2 client in the sentinel sweep while Active + fresh. Live
  re-run: 0 drift items.
- `76a5afdd` — `sentinel_quota.py` extraction after #1613 pushed drift_sentinel.py to 1214 lines
  and redded the #1665 module-size guard on main (CI-only — Deploy/Smoke/QA were green, no
  rollback; extraction chosen over a baseline exception).

**#1613 CLOSED (`a2d39201`, Fixes) — the CI-minutes 70% warn is real now:** discovery beyond the
issue's premise — the legacy `/settings/billing/actions` endpoint is **410 Gone**, so the warn
could never have fired even correctly scoped. Rewritten to the enhanced-billing usage API
(month-filtered usageItems); `_gh_api_json` prefers `GH_BILLING_TOKEN` (posture-token pattern);
warn is visibility-aware (public-repo minutes free → reported + suppressed + auto-re-arms on a
private flip; paid overage always warns). PAT at Secrets Manager `life-platform/github-billing`
+ `GH_BILLING_TOKEN` repo secret (Matthew ran the classifier-blocked `gh secret set` via `!`).
**AC5 proven in-workflow same-day** via manual remediation dispatch: billing available=true,
11,842 real July minutes read through the token path, suppressed (public), run green.

## Verified
- Suite: targeted files at every commit + full CI; final `python3 scripts/check_main_green.py`
  ✅ GREEN at `76a5afdd`. Three fleet deploys landed green (a2cdb9ee approved, ac753774 approved,
  76a5afdd no-deploy run); site-deploy green; **no auto-rollback fired all session**.
- Live probes: MCP boots 75 tools with `log_coach_calibration` (bridge x-api-key probe);
  `/api/journey` pre-start state; journal Part I/II/III distinct pages + manifest; prereg seal
  hash matches; subscribe endpoint healthy (the sentinel's NOT-DEPLOYED was the checker bug).
- Sentinel drift triage: quota leg clean; `email-subscriber` false positive fixed; the two real
  residuals filed (#1781 CFN IAM-role drift across 7 stacks, #1782 push-run gap batch-push
  false positives).

## Gotchas hit (durable → memory)
- **`--keep-chronicle` bypasses the PRELAUNCH_CALENDAR entirely** (calendar_mode flips off) —
  "keeping" an article means PROMOTING it into the calendar + vetting prose date-agnostic, never
  the flag. → `project_monday_reset` (updated).
- **A date tie in the prologue arc is a page-KEY collision, not just a label wart** — seq drives
  `week-NN/index.html`; the later write silently replaces the earlier post. Structural fix
  landed; the tie is legal now.
- **The ci-cd concurrency group queues behind a run parked at the approval gate** — two
  unapproved pushes stacked "pending" 10+ min; cancelling the parked pre-deploy run (safe —
  nothing deployed yet) frees the queue. Distinct from the #1544 billing/phantom classes.
- **The module-size guard (#1665) reds main from a green local targeted-test run** — growing a
  >1200-line file needs the guard (or full suite) run locally; extraction is the sanctioned fix.

## Next-session queue
**Monday-morning duties (standing, not-work — ops reminders #1329):**
- `python3 deploy/restart_verify.py` post-genesis (deliberately not folded into the pipeline) +
  eyeball the countdown → Day 1 flip and the first Day-1 daily brief (17:00 UTC).
- First cron billing-sentinel run lands Monday (#1613 evidence comment carries the in-workflow
  proof already); first coach-nudge send + 2h grading, first docket open, first MILESTONE#
  baseline sweep, youtube first capture — all first-real-data watches (`not-work — standing
  ops reminders`, also under review by the parallel sweep session).
**Buildable (owner-cleared):** #1623 milestone digest (Now) · #1333 paging build (ADR + dedicated
SNS topic + SSM phone) · #1666 proportionality ADR (doc-only) · #1571 /vlog mode (Now) ·
#1425 QA epic (Now) · Dependabot triage (21 alerts, 16 high; 3 dependabot PRs open).
**Sub-agent fodder (their own model quotas):** #1781 · #1782 · #1029 · #741 · opus podcast chain
#1738–#1741 · #1653 packaging · #1650 handovers move · #1756 · #1396.
**Parallel sweep session (Matthew-launched, read-only):** will file issues from the ≥07-19
review — ingest + fix its P1/P2s next session (`not-work — arrives as issues`).
**Owner:** #1336 toggles pending · #1768/#1622 parked ("-") · #1383 deferred ~08-26 · #1029
before 2026-08-20 · LICENSES §5 (`not-work — owner actions`).

## Gate outcomes
- **Build beat:** `2026-07-26-cycle-11-reset-rolling-prologue`
- **Docs:** COST_TRACKER.md §GitHub billing rewritten (endpoint 410 → usage API, live figures);
  reset-pipeline docs auto-regenerated (restart_docs_update + sync_doc_metadata at every
  commit); CLAUDE.md genesis/cycle literals auto-synced. Wiki checkers green at wrap.
- **Decisions:** none needed — the calendar promotion is editorial curation under ADR-077's
  existing pre-launch-arc decision; #1613's warn semantics are recorded on the issue +
  COST_TRACKER (implementation posture, not architecture).
- **Main:** green (`76a5afdd`).
- **Incidents:** 1 row added — (P3) prereg publish overwrote "The Night Before Everything" at
  `week-02` via the date-tie seq collision (reader-facing ~40 min, fixed + re-rendered same
  session, no data loss). The `a2d39201` Unit-Tests red was CI-only (<1h, no rollback,
  production green throughout) — noted here, below the incident bar.
- **Stash/hooks:** clean.
- **Labels:** OK.
- **Live: budget tier 1** (unchanged all session).

**Build beat:** 2026-07-26-cycle-11-reset-rolling-prologue

## Residual / next picks

- Monday Day-1 verification checklist (restart_verify.py, flip, weigh-in supersedes override, brief, first cron billing run) — not-work — standing ops reminders, executes 2026-07-27 morning.
- `python3 deploy/rebaseline_milestone_ledger_1807.py --apply` — owner runs via `!` (dry-run reviewed 2026-07-26, 27 rungs) — closes #1807.
- CDK deploy LifePlatformCore/Email/Monitoring/Operational (paging topic #1333, milestone-digest #1623, paging alarms) + `deploy/wire_paging_phone.sh` — owner runs via `!`.
- `life-platform/digest` recipients secret — not-work — owner provisions to arm #1623.
- #1738 TTS pick — not-work — owner listens to the three parked renders.
- #1571 AC4 — not-work — owner's 5-minute voice-mode phone test.
