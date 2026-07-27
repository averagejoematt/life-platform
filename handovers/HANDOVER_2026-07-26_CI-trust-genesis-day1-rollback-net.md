# HANDOVER — CI-trust repair + sweep-P3 paydown + genesis Day-1 + the rollback net's first real firings — 2026-07-26/27 (overnight-spanning session)

> Instruction thread: **solo fable session, owned main** — four workstreams in order:
> (1) Day-1 morning duties, (2) CI-trust repair (#1847/#1849/#1848 + the #1345 drill)
> BEFORE any merge wave, (3) the 21 open sweep-P3s delegated in clusters, (4) queue if
> headroom. Standing approval: all merges, Deploy-gate approvals, deploys incl.
> deploy_all; CDK via Matthew's `!`. The session started Sunday evening (genesis eve),
> the laptop slept overnight mid-queue, and it resumed into genesis morning — the wrap
> covers both halves.

## The headline: the record was wrong, twice, and the rollback net came alive

1. **The 07-26 "rollback non-fire" actually reverted 50 of 99 lambdas** (incl. MCP,
   withings-ingestion, chronicle, cost-governor). The wrap had read the FIRST interleaved
   per-function summary ("0 succeeded, 1 failed"); the job's final tally read **50/49**.
   The fleet ran mixed-version 00:12→01:33Z on genesis eve. Repaired same-hour by a full
   fleet redeploy once found; INCIDENT_LOG P2 correction row + memory
   `reference_rollback_partial_fires_mixed_fleet`.
2. **#1847+#1849 were ONE bug and the filed theory was wrong.** Runs died at the same
   test: #1796's `LastEvaluatedKey` pagination never terminates against a blanket
   MagicMock table — memory balloons (16GB observed) until the hosted runner OOM-kills
   ("runner has received a shutdown signal"). The 16s approval correlation was
   coincidence. Fix: DDB-shaped mock + 100-page hard bound (fc18f0c2). **Suite:
   45min+/never-completing → ~2.5 min (7,632 passed).** Durations budget note in
   TESTING.md. Memory `reference_magicmock_pagination_oom_runner_shutdown`.
3. **The seeded rollback net fired its FIRST true mass firing** (07-27 16:16Z):
   a deploy_all smoke FAIL → **98/99 clean reverts** through the #1848-seeded artifacts
   (1 fail: email-subscriber, us-east-1 — script region-hardcoded). Machinery perfect;
   the signal was another honest-check-wrong-threshold: qa-smoke's dashboard freshness
   used a 4h window against a 1x-daily (17:00 UTC brief) writer. Window fixed 4h→26h
   (b79469ff), fleet restored via deploy_all on tip — **final run: Deploy+Smoke+visual-QA
   all green, rollback skipped; all 24 live integration tests pass locally** (the run's
   I1/I2/I5 red = runner-side STS OIDC ETIMEDOUT, not the platform).

## What shipped — all merged AND live (fleet uniform on 3ef67571-era code, 17:05Z stamps)

**CI-trust (direct to main):** fc18f0c2 (OOM fix + fleet-deploy artifact seeding),
5d36b4a9 (rollback three-way tally + mixed-version warning), f64c75b0 (journal
featured-week PT-clock time bomb — failed every Sunday 17-24 PT on UTC runners),
39f01e88-class graces extended (dashboard-ahead + absent-character-sheet WARN in the
shared pre-start/Day-1 window), b79469ff (26h freshness), 964cf9cc (concurrency group
v2→v3 — the phantom stuck queue recurred), 82552827 (#1345 drill_smoke dispatch hook).
#1847/#1849 CLOSED; #1848 CLOSED (core proven; residuals → **#1859**).

**Sweep-P3 paydown: 21/21 closed** via 7 reconcile-ritual squash-merges (each round:
sync-literals-on-branch → linearize → merge; combined suite green every round):
- PR #1853 docket/dossier (#1798 pair-scoped keys, #1799 split pagination, #1800 PII
  screen, #1801 deterministic throttle) · PR #1852 journal/chronicle (#1803 cover sk,
  #1804 guard_version re-screen, #1805 tombstone redirects, #1806 channel enum) ·
  PR #1851 milestones (#1808 Mifflin-fallback disclosure, #1809 vacuous garmin zone-2
  extractor + SCHEMA.md truth, #1810 return-date honesty) · PR #1850 ops (#1816 region
  summary, #1817 STACK_FILE_REGION parity test) · PR #1855 privacy/AI (#1789 ADR-141 §4
  takeaway carve-out + deterministic screen; #1830 Horizons grounding gate) · PR #1856
  coach (#1791 correction cycle-provenance, #1792 observatory beta_param) · PR #1854 site
  (#1821 cohort cache TTL, #1823 theme-river wired into sync_site_to_s3, #1825 replicator
  permanent dedup). Plus **#1814** fixed directly (ADR-058 phase stamps on
  habit/day-grade writers, both copies; leaked 07-25/26 rows backfilled + re-stamped
  after the reverted brief clobbered them once).

**#1708 shipped (PR #1857) → epic #1686 CLOSED** — prescription reactions enrich the
journal via the existing #1577 sweep (channel provenance, no second pipeline) + a
deterministic reaction ledger calibrates future Horizons picks (counts/rates + n, no LLM
numbers, private-by-default, fail-closed publishability door with no caller yet).

**Genesis Day-1 (all verified live):** day_n=1/pre_start-gone flip ✓ · **real weigh-in
321.09 lbs superseded the 317.61 override honestly** (DDB profile + S3 configs + regenerated
constants + game-page/home rebakes; the FROZEN prereg deliberately keeps 317.61 — frozen
artifacts don't get rewritten, claims grade against real data) · restart_verify 11/13
(character sheet computes tomorrow; graced) · 17:00 brief SENT (the #1694 baseline-freshness
gate correctly flagged the reverted coach citing stale numbers — advisory; heals now the
fleet has 321.09) · milestone first sweep **baseline-quiet** (re-baselined ledger held; the
≤5-recipient warning is the standing owner task) · first nudge quiet-honest · ai_validator
fail-closed an empty coach output.

## Verified
Combined suite after every merge round; final tree 7,632 passed / 172s + black/ruff 6-dir
clean. deploy_all-4 (30286473574): Deploy ✓ Smoke ✓ visual-QA ✓ rollback skipped; 24/24
live integration tests pass locally (i3/i9/i13/i16 had been mixed-fleet symptoms). Fleet
LastModified uniform 16:57–17:05Z. CloudFront v4-redirects updated+published (function
LIVE-stage test returns 301) — but see the CDK item below.

## Gotchas (durable → memory, already written)
- Rollback per-function summaries interleave — read the JOB tally + sweep LastModified.
- "Runner shutdown signal" = check the LAST test printed for a mock-fed OOM before
  believing an event correlation.
- Freshness windows must encode the WRITER's cadence, not the checker's cron position
  (weight-null, dashboard-4h — same family, two firings).
- The concurrency-group phantom queue recurred (v3 salt now); a push supersedes any
  PENDING run — dispatch deploy_all only when nothing else will push, and expect a
  laptop sleep to freeze watchers mid-chain.
- The reverted brief's put_item clobbered backfilled phase stamps once — re-stamped;
  self-healing now #1814 code is fleet-wide.

## Wrap gates
**Build beat:** `2026-07-27-the-net-fires` (see beats.json).
**Docs:** TESTING.md (durations budget), INCIDENT_LOG.md (P2 correction + P3 first-firing
rows), docs/engines/CHARACTER.md (Day-1 baseline re-verify stamp), SCHEMA.md (via #1851),
DECISIONS.md (ADR-141 §4 amendment via #1855); wiki checkers green at commit.
**Decisions:** ADR-141 §4 amendment filed (in PR #1855) — no new ADR needed; the
freshness-window and rollback-tally changes are implementation posture, recorded in
INCIDENT_LOG + CONVENTIONS-adjacent memory.
**Main:** red — deploy_all-4's I1/I2/I5 job hit runner-side STS OIDC ETIMEDOUT (8 retries,
45 min); every deploy-bearing gate green and the same integration suite passes locally
24/24; production healthy + current.
**Incidents:** 2 rows added — (P2) the 07-26 partial-rollback record correction (50/99
reverted, mixed fleet ~1h20m); (P3) the net's first true mass firing (98/99 clean reverts
on the 4h-window false positive).
**Stash/hooks:** clean.
**Labels:** OK.

## Residual / next picks
- **Owner, one line each:** `bash deploy/cdk_deploy.sh LifePlatformWeb` (activates the
  `/journal/posts/week-*` redirect association — until then the 3 tombstone URLs still
  200; #1805 comment has detail) — not-work — owner-run CDK per standing rule.
- **#1858** IAM: cycle-read grant for read_cycle callers (digest logged AccessDenied,
  fail-softed correctly); needs role_policies + CDK deploy.
- **#1859** rollback-net residuals: us-east-1 revert + empty matrix on push-fleet runs.
- **#1345** left open for the owner's call: does the real 98/99 firing satisfy the drill
  AC, or should the quarterly ritual still run the synthetic (`drill_smoke=true` dispatch
  after a qa-smoke-only touch commit — hook is live)?
- Day-2 watches: first character sheet (computes tomorrow for today), first docket/dossier
  writes, first calibration write, youtube first capture, #1840 AC4 diary stamp, Wednesday
  remediation cron (Monday's 14:45Z never fired — GitHub schedule drift; shadow mode) —
  not-work — standing owner/next-session ritual.
- Queue if next session has headroom: diary-360 in order **#1841** → **#1842**/**#1843** →
  **#1844** → **#1845**/**#1846** (opus) · **#1396** calibration artifact (opus) ·
  **#1402** Broadcast (opus, gated on #1619 Phase-0 — check first) · **#1653** packaging
  (opus, LAST-merge-of-a-quiet-day, solo wave by design).
- Owner asks, no urgency: digest recipients 1→5-8 + reply_to (**#1623** note; the WARN
  fired live today) · **#1738** TTS listen · **#1571** AC4 phone test · **#1114** pick on
  PR #1768 · Dependabot **#1778**/**#1779**/**#1780** verdicts posted — not-work — each
  needs Matthew's coordinated step.
- Budget: tier 1 at session close (July temp ceiling $115; internal/dev AI paused) —
  not-work — governor behaving as designed, self-resolves 08-01.
