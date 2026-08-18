# Handover — 2026-08-18 (afternoon, ~12:20 → ~14:30 PT): unblock the publish path, then take the LLM out of a blocking alarm

**Session:** Opus, owner-directed (plan `swirling-singing-crown`, model ceiling Opus — no kernel
builds; #2846/#2847 stay Fable-sequenced, every `model:fable` issue skipped). Boot was
**charter + model** (#2845), not a prose re-read. Second Opus session of 2026-08-18 — the
morning session's wrap is archived as `HANDOVER_2026-08-18_failure-that-looked-like-health.md`.

**Build beat:** `2026-08-18-the-reviewer-that-kept-changing-its-mind` — merged AND deployed, eligible.
**Docs:** CONVENTIONS §9 (new gate-registry row for the day-number-proxy defect class), INCIDENT_LOG
(amended the site-auto-rollback row's resolution — see Incidents). `sync_doc_metadata --apply` found
everything else in sync; links/tombstones/index/ADR-index all green.
**Decisions:** none needed — the two judgement calls (keying the carve-out on `/api/source_freshness`
rather than a `/api/vitals` self-report; declining the cross-nightly n-of-m counter) are
implementations of existing ADR-104/105 and are recorded in CONVENTIONS §9 and in the #2741 issue
comment rather than as new governance.
**Incidents:** none — no incident-class event this session. **Amended** the morning session's
2026-08-18 site-auto-rollback row: it claimed "not resolved — owner-gated on a Withings weigh-in",
which was wrong. It was resolved the same day by #2879 *without* a weigh-in. The missing Withings row
was the trigger; the day-number proxy was the defect.
**Main:** green — `check_main_green.py` exit 0. See "Main-green decode" below for HEAD's own run.
**Stash/hooks:** clean — `git stash list` empty, `session_postflight.py` hook freshness 🟢.
**Closures:** #2878 commented (full ADR-099 contract, `Outcome: realized`). The nine other issues
closed on 2026-08-18 belong to the morning session, which already wrapped them — not backfilled.
**Backlog:** Now live at 12 (6 actionable, well above the 3 floor) — no refill needed; `later_staleness`
clean, no stale `Later` issues, so no promote-or-close calls were owed.
**Alarms:** clean — every alarm red >72h cites an incident row or issue, and every one red >14d cites
a filed issue.
**CI warnings:** 1 — Unit Tests wall-clock 1297s vs the 1200s budget on green main `9e3659a1`.
Already filed as **#2692**; commented with the recurrence datapoint (1247s → 1297s, gap widened
47s → 97s) and made an explicit no-action call this session, since #2692's own bar is *measure before
raising it again*. Disclosed honestly that this session ADDED 12 tests, a marginal contribution.

---

## What drove the session

Two threads, in order. (1) The morning session's own wrap deploy auto-rolled-back and left the site
**un-publishable**: the vitals smoke check keyed its genesis carve-out on `day_n <= 1` instead of on
whether a weigh-in had happened, so every `site/**` merge deployed, failed smoke, and reverted. The
build beat was on `main` but not served. (2) The Opus headline #2741: a blocking alarm's FAIL boundary
was being decided by an LLM that disagreed with itself run-to-run about a string its own rubric
already exempts.

## Two of the plan's premises were wrong, and it mattered

1. **The plan assumed the session would be Wednesday 2026-08-19. It was Tuesday 2026-08-18.**
   So #2668's run 3 (the 08-19 17:00Z brief) and #2669's Wednesday chronicle box (the 08-19 15:00Z
   cron) were **not observable** and neither box moved. Both remain the next session's first checks.
2. **The Whoop owner-ask was already resolved.** The plan carried it as open ("no rows past 08-16").
   Measured: `IngestAuthHealthy` for whoop flipped **0.0 → 1.0 at ~08:00 PT on 08-18**, and DDB holds
   complete rows (29 fields each) for 08-16, 08-17 and 08-18 including workouts. **No #2085 latch-clear
   and no backfill were needed.** `ingest-auth-unhealthy-whoop` is still ALARM only because it is
   `Period 86400 / Eval 1 / Minimum` — a 24h lagging aggregate, structurally identical to the
   `qa-smoke-failures` lag the plan describes. It self-clears ~08-19 08:00 PT. It is not stuck.

## What shipped — 2 PRs merged AND deployed, 1 issue closed, 1 filed, 1 worker PR left open

### #2879 → closes #2878 — the publish path, unblocked (merged `0bffc1ec`, deployed)

`PRE_START = pre_start or day_n <= 1` was a proxy for "no weigh-in yet". The proxy expired on Day 2
while the condition it stood for was still true. The carve-out now reads the real predicate from
`/api/source_freshness` — `experiment.genesis` against withings' `last_update`. That endpoint is a
**different lambda module on an un-genesis-clamped query**, so the two sources must *agree*; that
independence is what keeps the check able to fail instead of becoming a green light wired to nothing.

**Mutation-proven both directions**, on the block extracted *verbatim* from the file (not a retyped
copy) against a mock origin — 7 cases: honest absence PASSes; **a weigh-in present in DDB but absent
from the payload FAILs**; a weigh-in on the genesis day FAILs; an absent withings row and a malformed
freshness payload both fail closed. An unverifiable absence is not a pass.

Live proof: run `32177220989` on `0bffc1e` — Deploy, Site smoke, **and** Visual/AI-QA all green,
auto-rollback skipped; `/version.json` == HEAD; `/story/build/beats.json` 113 → 114 with the morning
beat served. Matthew had **not** weighed in, so it is proven against the failing state, not around it.

Enumerated the other day-number proxies: `deploy/restart_verify_semantic.py` also uses `day_n <= 1`
and was **left alone deliberately** — it runs at reset time to assert the site *reflects* a fresh
genesis, where the day number is the thing being checked, not a stand-in for something else.

### #2880 → #2741 (merged `fcd78ceb`, deployed + symbol-verified) — issue stays OPEN

**Measured before retiring**, per #2613's bar, from `/aws/lambda/life-platform-qa-smoke` over the ten
days to 08-18, **at zero Bedrock cost** (logs already paid for — which matters while #2734 has
month-end above ceiling): a home-page `temporal_contradiction` in **25 of 60 runs (42%)**, spanning
Day 6 of cycle 13, the pre-start countdown, and Days 1–2 of cycle 14 — *every* phase, which is exactly
the claim the exempt clause makes. Severity flipped on byte-identical copy (20:36Z `med`, 22:17Z `high`).

Retired structurally, not with more prose: `DURABLE_DESIGN_COPY` is the registry (charter primitive 1);
`build_prompt` **renders the rubric's example list from that tuple** so the clause the model reads and
the clause code enforces cannot drift, asserted not assumed (primitive 2); `assess_prose` drops a
finding only when *every* quoted span is registered copy, printed, sitting alongside the #2613/#2780
drops. Scope pinned by the production record — the 22:17Z `high`, which also quotes two other
sentences, is pinned as **KEPT**.

Deployed and **symbol-verified in the live bundle** (`is_durable_design_copy` at line 224, the drop
call site at 642; function LastModified 21:01:18Z) — not inferred from a green run.

### #2881 filed — `deploy/**` is outside ci-cd's path filter

`deploy/smoke_test_site.sh` — the script that can revert the public site — merged with **no lint, no
tests, one Docs CI run**. It is a *legitimate* path-filter skip by config, which is what makes it
dangerous: indistinguishable from a swallowed push at a glance. Same class DEVOPS-01 (2026-06-30)
fixed for `cdk/ci/config` and missed here.

### #2882 (worker, #2876) — OPEN, deliberately not merged

The Sonnet worker delivered the right shape: a genuine **single dispatch exit point** (not the 27-call
sprinkle the charter forbids) plus an AST-derived guard proven to bite. Held on cost. See owner asks.

## Gotchas

- **The wire taught two things a retyped fixture would have missed.** The live model notes carry
  **U+2011 NON-BREAKING HYPHEN** in `Day‑1` while the rubric writes ASCII — a raw comparison would have
  matched nothing, forever, while hand-written tests passed and the check *looked* wired. And a real
  note quotes the bare fragment `'starts at'` alongside the whole string, which the first rule rejected;
  the suite went red on verbatim production text and forced containment in both directions.
- **Trap 1 avoided, and it bites via the test file.** `agent_commit.sh` refused the commit; the pinned
  `.venv-black` 26.3.1 then reformatted **only** the new test file. No unrelated drift.
- **Trap 2 decoded correctly, twice.** `0bffc1ec` earned exactly 1 run. That is a *legitimate*
  path-filter skip (`deploy/**` and `docs/**` are outside ci-cd's `paths:`), not a swallowed push —
  and the fact that the two are indistinguishable without hand-reading the filter is what became #2881.
- **A watcher exiting is not a run finishing.** The deploy watcher hit its 20-iteration cap and
  returned while the run was still `in_progress`. Re-watched rather than reading the exit as terminal.
- **The plan's cost figure for #2882 needed grounding, and the grounding changed the answer.** See below.

## Owner asks — 3 open

1. **#2882 needs a cost call before it merges.** Worst case is ~$26.40/mo, but CloudWatch custom
   metrics are **prorated hourly**, proven two ways from your own bill: July's `MetricMonitorUsage`
   quantity is a *fraction* (64.9, reconciling exactly to $16.46 after the 10-metric free tier), and
   165 route metrics are defined while only **80 were active in the last 3h**. Applying that measured
   48% active-rate gives **~$12–13/mo** realistic. Options: merge as-is; take the cheap
   EMF-property-only redesign (~$0, loses direct per-route graphing, needs the `TOP_ROUTES` dashboard
   touched); **merge the restructure and drop the metric** (recommended — the structural win is free
   and item 2 is a live squeeze); or close it. Note CloudWatch is *already* climbing: $24.50 in July,
   tracking ~$34/mo in August.
2. **#2734 / #2836 — the September base, due 09-01.** Live: AWS Budgets limit $85, MTD **$100.82**,
   forecast **$163.42**; tier currently 1. August's temporary $200 ceiling **auto-reverts 09-01 with no
   deploy**, at which point ~$163 against $85 is ~190% → **tier 3 hard cutoff, reader-facing AI dark**,
   on a date nobody is necessarily watching. Drivers measured: Bedrock ~$105/mo (Haiku $30.86 + Sonnet
   $30.35 in 18d), CloudWatch ~$34/mo, Secrets Manager ~$11/mo.
3. **A Withings weigh-in.** Still no in-cycle row (newest `DATE#2026-08-16`, `carried_from_cycle: 13`);
   baseline is still the 321.01 override. **No longer blocks deploys** — it only gates the supersede
   reflex in `project_monday_reset`. Matthew said he would double-check.

## Residual / next picks

- **#2668** — run 3 of 3 is the **08-19 17:00Z** brief; sample after ~17:10Z (the brief takes ~8 min).
  Clean run → close with the ADR-099 two-line verdict.
- **#2669** — the Wednesday chronicle box, after the **08-19 15:00Z** cron. One generation, <300s,
  a persisted issue, no duplicate-generation lines → close.
- **#2741** — box 5 only: one clean nightly against the now-deployed bundle, then observe
  `qa-smoke-failures` **transitioning** to OK (it is `Period 86400 / Maximum`, so up to 24h lag).
- **#2670** — now unblocked, #2741 having landed. Plan's measurements still hold; acceptance demands a
  planted failure observed driving OK→ALARM, not assumed.
- **#2881** — the `deploy/**` path-filter gap filed this session.
- **#2692** — Unit Tests wall-clock, now 1297s and still climbing.
- **#2820** — the Wednesday chronicle delivery dead-man; pairs with #2669.
- **not-work — verify `ingest-auth-unhealthy-whoop` clears ~08-19 08:00 PT** as the 24h `Minimum`
  window rolls past the last 0.0. A standing ops observation, not a backlog item.
