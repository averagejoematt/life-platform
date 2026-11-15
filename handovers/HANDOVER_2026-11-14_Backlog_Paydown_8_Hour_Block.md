# Handover — Backlog paydown, the 8-hour block: ten review and accuracy bugs fixed in parallel lanes, 12 PRs merged and deployed, six closed on live proof (2026-11-14)

## Driving instruction
The owner asked for "a fresh new sweep of our backlog, coordinate with other sessions, and make a plan for an autonomous session for the next 8 hours paying more issues down", then "go" on the plan, which carried five calls he accepted with it: merge the surge-baseline fix even though surge engages (ceiling $215 → $252 while it does); no DynamoDB backfill for state_of_matthew; the alarm-citation schedule's IAM goes to him as a draft PR, not deployed; exemption/hold for the emf census to 11-28 and the two rhythm checkpoints left to him; fold the nutrition epic #5094. Mid-block he offered the 2026-11-14 accuracy-review issues; this session took the engine-side three (#5952, #5954, #5955). Lanes were agreed with the peer sessions: training (life-platform-fe: lambdas/training/**, the #5858 conflict set incl. the gate-census files), v9 sprint (session-co-issue-paydown: www/**, site/privacy/, site_api_chapters.py, publish_snapshot*), review (life-platform-34: no paths; #5932 and mcp/handler.py held untouched as its blind control).

## What is COMPLETE (merged, deployed, verified live)
- **#5936** PR #5961 (e313b9d42) — the surge baseline ends before the reading under test. cost-governor redeployed 19:07Z; bundle carries `split_reading_and_baseline`. Closed.
- **#5930 + #5527** PR #5963 (07229169a) — status board pages to the end, derives rows from the registry, unique `apple_health:<field>` ids. Live /api/status 21:38Z: 0 duplicate ids, CGM 79d, Mindful 217d, hevy row, macrofactor_workouts as archive. Both closed.
- **#5955** PR #5964 (ee56f1697) — /api/presence reconciles against food rows at read time (cause: MacroFactor batch exports land after the 17:35Z presence compute). Live: present, last_log_date = newest food row. Closed.
- **#5954** PR #5962 (5559e1bbe) — `partial_at_export` rows labelled partial and kept out of headline, averages, floor count, micronutrients, Data room tiles, meal-timing anchor. Live (cache-busted): partial_days [2026-11-13], latest_date 2026-11-12. Closed.
- **#5952** PR #5960 (2c05f830f) + PR #5988 (ed0d41a24) — monthly_cost derived from the last closed month (~$220 for 2026-10); stack.json and the starter-slice cost note re-grounded. Live /api/platform_stats and /data/stack.json both ~$220. Closed.
- **#5094** folded: all 19 stories closed; rulings R1–R8 carried verbatim to #5907. Closed.

## Merged, live proof still owed (Refs, not Fixes)
- **#5931** PR #5965 (70d8f787f) — the writer's stage map renamed `phase_context`; `tag_record` overwrites a non-string `phase`. Proof: the Sun 19:30Z state-of-matthew run → `/api/state_of_matthew` `available: true`. The payload newly carries `phase_context` (day/week/stage — already public).
- **#5933** PR #5967 (1ac9a8134) — origin-idiom framings checked against the journey start; recap figures grounded against the installment text incl. `where_we_are_now`. Proof: the next weekly_priority and Wednesday chronicle.
- **#5934** PR #5958 (445dffa0f) — citations re-pointed; an alarm lit >14 d with no open `#N` now blocks wrap. The unattended schedule is draft PR **#5966** (OWNER-REQUIRED readonly-role grant); the paydown would not widen the remediation role's callers.
- **#5935** PR #5957 (c8cd41c58) — scheduled-workflow red tenure: the cron-freshness watcher files/refreshes one `auto-filed` tracker at 3 consecutive reds; `WF RED` lines at boot. It filed #5973–#5976 on its first run (each now carries a diagnosis). managed-where re-verified; emf-series-census held to 2026-11-28.
- **#5937** PR #5971 (8364da1f2) — CLAUDE.md CI/CD paragraph + format command corrected and gated by check_doc_facts; this wrap refreshes the status pointer (the last box).

## AWAITING THE OWNER
- **#5947 (P1)** — an owner-only clinical fact is live on a public surface (detail held privately). Takedown is his act.
- **#5949 (P1)** — Panel prologue speaks body-weight figures: re-cut, or rule historical weights allowed in audio.
- **PR #5966** — apply the readonly-role grant (#5934's schedule). **PR #5910** (#5513) and **#5897** (#5545, after #5858) as before.
- **#5935** — the two rhythm checkpoints (steps on PR #5957); the accuracy-review artifact landing ("land it" to the review session) resets accuracy-full.
- **#5974** — eval-harvest's role is KMS-denied on the table (IAM/key policy).

## Gotchas learned (each in memory)
- A new test FILE is a new gate in the census (ceiling 857; census files fenced while #5858 is open) — fold new tests into an existing proven test file. Two lanes hit it.
- Peer sessions in bypass mode hold this session's cross-session messages; three expired or waited for approval. Put cross-lane notes on the issue instead.
- A merge-loop's "all checks done" must wait for the main PR workflow to REGISTER — `assert_pr_green.py` caught two expected checks missing on #5988 while "PR checks" sat queued.
- A site deploy whose change touches site-API code defers itself until the site API serves that commit; it re-dispatches after the CI/CD deploy (stack.json landed ~40 min after merge).
- CloudFront holds `/api/nutrition_overview` up to 1 h — read live proofs cache-busted.

## Residual / next picks
- #5518 — Sun 2026-11-15 12:00 PT the hypothesis-engine writes the two genesis voids; verify both rows `expired_undecided`, then close (also clears `prereg-overdue`).
- #5931 — read `/api/state_of_matthew` after the Sun 19:30Z run; close on `available: true`.
- #5933 — close on the next weekly_priority + Wednesday chronicle passing the gates.
- #5575 — Mon 2026-11-16 weekly run closes it, with #5759, #5761, #5772 and likely #5505.
- #5802 — last box (one live stage-1 read) blocked by stage-1 latency #5813 (training lane).
- #5990 — Coaching Room: critics_aerobic.py still prints the retired cap (residual of #5916).
- #5973 — config-twin drift is training-lane artifacts; #5976 — PII sweep reds on two dark Coaching Room 404s.
- not-work — the wrap's memory backup (`aws s3 sync … claude-memory-backup/`) was not run: an S3 write is ask-first under the owner's global rules; run it attended.
- not-work — read the cost-governor's first run on the new code (~2026-11-15T01:00Z): expect `surge_threshold=1769 … recent_uniques=2603 surge_active=True`.

**Build beat:** none — a backlog paydown of ten engine and gate fixes; no single reader-visible story to narrate
**Docs:** `docs/alarm_citations.json` (qa-smoke-failures re-cited to #5939, new 2026-11-14 episode; qa-smoke-warnings gains its `cause`) · `CLAUDE.md` (status pointer) · CLAUDE.md CI/CD + format lines, `docs/MANAGED_WHERE_LEDGER.md`, `docs/OPERATING_CALENDAR.md` shipped in the lane PRs
**Decisions:** none needed — every call this block made was the owner's plan answer of 2026-11-14 recorded on the issues; no governance change
**Main:** green (ed0d41a2)
**Incidents:** none
**Stash/hooks:** clean · worktree-reap removed 140 merged lanes, released 14 locks; 1 dirty lane named and untouched (`sprint3/redact-labels`, the v9 sprint session's)
**Closures:** #5094, #5110, #5371, #5527, #5530, #5533, #5540, #5542, #5558, #5769, #5780, #5792, #5795, #5801, #5817, #5899, #5930, #5936, #5952, #5954, #5955 commented (Shipped + Outcome); #3759/#4772 (folded, not planned) lost `closure:live-proof` with a not-realized verdict · DoD: scanned=37 hits=5 — #5916 unhomed-residual homed on #5990 (the sweep still reads the original close-time verdict); #5899 post-close "Reopen if…" is the owner's week-10 regeneration condition, not a reopen; #5920, #5948, #5956 are the v9 sprint session's closes, verdicts theirs
**Backlog:** Now live at 12 (sonnet 2 · opus 12 · fable 1 startable); no promotion needed; Later sweep — no stale Later issues. Filed this session: #5990. Open 103 (95 at block start; +12 accuracy-review, +4 auto-filed trackers, +1 #5990)
**Alarms:** all lit alarms cited; qa-smoke-failures (single 19:32Z FAIL, self-clears ~2026-11-15T19:35Z) → #5939; prereg-overdue → #5518
**CI warnings:** 6 — 5 the intentional playwright skip (#3640), no action; 1 `test_grant_enumeration_drift.py::test_every_lambda_consumer_is_granted_its_channel` 92.7 s over the 90 s bar under a saturated runner day → #5514 (CI hygiene, per-test timeout)
**Ledger:** omitted — #5935's tenure pass and #5934's wrap block are legs inside existing gates (cron-freshness, check_alarm_citations), and `docs/PROPORTIONALITY.md` is fenced to the training lane while #5858 is open; its wrap-nightly row still says alarm-citations is "not a leg" (owed with #5966)
