# HANDOVER — the deploy-machinery block: three shipped, and the blocker they uncovered — 2026-07-31/08-01

> Instruction thread: take the #1890 wrap's deploy-machinery block — **#1911 → #1907 →
> #1908 as one wave** — because it compounds and taxes every change. Verify the build beat
> landed first. Explicitly NOT a Fable session (the banked `/fullreview` partial's delta
> review is due on/after 2026-08-02). Standing approval given in-session for merges, the
> deploy-gate approval, and the two ordered deploys.

## Shipped (all merged AND live-verified)

- **#1911** (PRs **#1915** + **#1916**) — the endpoint that auto-reverted two correct
  deploys is fixed, and a timed-out request can no longer revert one anyway. Split into two
  PRs on purpose: the IAM half reds the R8-ST6 Plan gate by design, so bundling would have
  reddened main for the zero-risk CI fixes too.
- **#1907** (PR **#1915**) — the superseded-skip now requires a real trigger-path diff
  before declaring itself replaced, names the superseding commit, and fails safe.
- **#1908** (PR **#1915**) — the doc gates moved out of the deploy pipeline into Docs CI,
  which now triggers on **both** halves of the doc↔source coupling.

## The measurement that overturned the issue's own hypothesis

#1911 proposed a cold site-api container. The origin says otherwise. 7 days, 12,386
invocations: p50 51ms, p99 2.16s, **max 14.93s**. Both incidents align to the second:

| | duration | InitDuration |
|---|---|---|
| 2026-07-29 ended 16:10:19.407 | **11,628 ms** | *absent* |
| 2026-07-30 ended 18:00:15.636 | **14,934 ms** | *absent* |

Each began within a second of the smoke's last `✅ /api/horizons`. **No cold start** — pure
handler cost: ~62 *sequential* CloudWatch calls (6 models × 2 windows × 2 metrics + 19
Lambdas × 2), stretching to 11–15s whenever one is throttled and boto3 backs off. Readers
rarely saw it (900s edge cache); the smoke cache-busts, so it always paid full price. That
is why it surfaced as a deploy-gate failure and not a user complaint. Fixed with
`GetMetricData` (≤500 queries per call → one round trip). Threads were considered and
**rejected on evidence** — #1527 showed per-thread boto3 Sessions regressed this fleet
3.6s → 12–16s under the GIL.

## What the class-level framing bought again

Every issue was filed as an instance and was really a class — the third session running:

| Issue | Reported | Actually found |
|---|---|---|
| #1911 | 1 slow endpoint | **12** unguarded `$(curl …)` sites, any of which kills the run |
| #1908 | "gate in ci-cd's lint job" | it is in `ci-lint.yml`, and docs-ci **already ran it** |
| #1908 | — | + docs-ci's drift gate had been **silently skipping** on a shallow clone |

**#1908's issue text would have made things worse if followed literally.** It proposed
deleting the ci-lint copy; that copy is load-bearing — it catches *code* pushes that
invalidate docs, which is exactly the recurring `PILLAR_COMPUTERS` drift. The fix was to
give docs-ci the code-side triggers *and then* remove the duplicate, so coverage moved
rather than disappeared.

**The silent skip is the more valuable find.** `check_doc_index.py` skips the #973
engine-doc drift gate on a shallow clone, and docs-ci checked out at depth 1 — so it had
been running `--strict` with its drift half disabled, reporting a green it never earned.
Now `fetch-depth: 0`, with a test that proves the skip path is real rather than asserting a
knob nobody verified. It caught real drift on its very first run (PR #1916's date literals).

## Gotchas hit

- **`set -e` + `$(curl …)` is the whole #1911 mechanism.** On exit 28 the substitution
  fails and the script dies *before* the check's own error branch — hence no ❌ row, no URL,
  and a bare `exit code 28` read as a bad deploy. The guard is **derived** (AST-style scan
  for any `$(curl …)`), not enumerated, and was negative-tested by injecting a new call site.
- **The doc-sync stamp is UTC, so "same-day commit+merge" has a 17:00 PDT deadline.** I
  committed at 17:05 PDT — already 2026-08-01 to the gate — and reddened both main and PR
  #1916 with 8 stale date literals. `sync_doc_metadata.py:1182` uses
  `datetime.now(timezone.utc)`. The prior handover's rule is necessary but not sufficient;
  this is the sharper form.
- **YAML anchors do not work in GitHub Actions.** Caught before push; would have broken the
  docs-ci trigger outright. The two `paths:` lists are duplicated by hand with a test
  asserting they match.
- **`command curl` bypasses shell-function stubs.** Used it for recursion safety; it
  defeated every unit test (rc=6, real DNS). Plain `curl` is correct — the function name is
  already distinct.
- **A qa-smoke failure unrelated to deploy health reverted 100 Lambdas** — the #1911 pattern
  recurring on a *different* oracle (see #1917 below).

## Verified

- **Full suite 8,165 passed**; the one failure is `test_i16_recent_ingest_records_exist`
  (`Found: ['whoop@2026-07-31']`) — the exact signature its own docstring calls out as
  low-logging-activity, **not a code regression**, and CI excludes that file.
- **Deployed bytes inspected, not inferred**: downloaded the live site-api zip —
  `_batch_daily` and `cw.get_metric_data` present, old serial `_sum` helper gone.
- **Deploy order held**: IAM policy 6:02:30 → function 6:02:40. `cloudwatch:GetMetricData`
  confirmed live on `SiteApiLambdaRole`.
- `/api/inference_receipt` → 200 with `today_in == month_in == 5921`, which is exactly right
  on Aug 1 and validates the new `_split` arithmetic. Also confirms the **ADR-133 ceiling
  reverted $115 → $85** on schedule.
- `smoke_test_site.sh --quick` end-to-end against live: **186 passed, 0 failed** (twice).
- Every guard negative-tested: reverting the supersede fix fails 5 tests including both
  incident cases; injecting a bare `$(curl …)` fails the derived scan.
- **Honest caveat:** the 0.22–0.36s latency (vs 1.49–1.66s) is **partly confounded** — UTC
  rolled into August so `month_start` is hours old. The un-confounded proof is the
  call-count contract, not the stopwatch. And `smoke_test_site.sh` runs **only** from
  `site-deploy.yml`, so the #1911 smoke fix has not yet executed in production CI; that
  awaits the next `site/**` merge.

**Build beat:** `2026-08-01-the-gate-that-was-never-running`
**Docs:** `docs/CONVENTIONS.md` §4 — the doc/wiki gates' new home, the `fetch-depth: 0`
requirement, and the hand-duplicated path lists; gate-order line corrected (doc-drift removed).
**Decisions:** none needed — #1908's option-1 choice is a CI-placement call recorded in the
files it changes; no architecture/data/deploy-posture change beyond what ADR-099/103/104 cover.
**Main:** red — `check_main_green.py` reads **`e8d0ce43` FAILURE**: that run's Smoke Test
failed on the **pre-existing** qa-smoke reader_truth defect (#1917, which pre-dated the
deploy by ~48 min), and auto-rollback fired. The newer run on `7408e326` has every gate
green (Lint, Unit Tests, Deploy-critical, Plan) but sits `waiting` because I deliberately
did **not** approve its deploy — approving while reader_truth is red would roll back over
the #1911 fix. Both reds clear when #1917 lands; neither is a regression from this session.
**Incidents:** 1 row — the 2026-08-01 auto-rollback of 100 Lambdas on a pre-existing
qa-smoke reader-truth failure.
**Stash/hooks:** clean
**Closures:** #1911, #1907, #1908 commented with ADR-099 outcome verdicts
**Backlog:** Now live at 10 actionable; #1917 filed P1.

## Residual / next picks

1. **#1917 — the live blocker, take it first.** `/api/vitals` publishes `hrv_30d_avg`
   (n=5) and `weight_delta_30d` labelled "30d" on **Day 5**. It fails qa-smoke's
   reader_truth check, and qa-smoke is ci-cd's smoke oracle — so **every merge currently
   deploys, fails smoke, and auto-rolls-back**. The issue separates the two real questions
   (is the *number* wrong or only the *label*? weight legitimately survives a reset under
   ADR-077; HRV does not) rather than assuming a fix. Recurs on every cycle restart, so a
   date-independent fix beats a one-off.
2. **Approve the stranded deploy on `7408e326` — but only AFTER #1917.** `not-work — an
   ops step, sequenced.` It ships nothing new (site-api code + IAM already live via the
   manual deploys; only the `test_count` literal remains) and would roll back over the
   #1911 fix if approved while reader_truth is red.
3. **#1909** — `/api/status` reports "627% of budget" against a hardcoded `budget = 15.0`.
   The **$115 → $85 revert has now happened** (confirmed live: `budget_ceiling_usd: 85.0`,
   tier 0), so this can finally be verified across the real boundary rather than predicted.
4. **#1904, #1892, #1893, #1896, #1897** — the rest of epic #1890.
5. **Fable delta review due on/after 2026-08-02** — `not-work — a scheduling constraint.`
   Do not let another model finish the banked `/fullreview` partial (14/17 lenses).
6. **Worktree prune** — `not-work — housekeeping, no issue warranted.` Still ~130, many
   stale and in-repo under `.claude/worktrees/`.
7. **Standing alarms (#1329 checklist)** — `not-work — checked, nothing outstanding.` No
   digest-routed freshness alarm or manual-rotation secret reminder is aging; next
   MCP-bridge key rotation is 2026-10-05.
8. **Owner-gated, unchanged** — `not-work — owner decisions, not session-startable:` OSS
   publish one-liner, vocal backfill, #1738 / #1571 / #1114, Dependabot.
