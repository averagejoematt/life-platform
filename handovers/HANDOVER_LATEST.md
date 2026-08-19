# Handover — 2026-08-18 (evening, ~17:15 → ~19:00 PT): the plan's Wednesday was 15 hours away, and the gauge was measuring itself

**Session:** Opus, owner-directed (plan `boxes-close-and-the-ceiling-call.md`, model ceiling Opus —
no kernel builds; #2846/#2847 stay Fable-sequenced, every `model:fable` issue skipped). Boot was
**charter + model**, not a prose re-read. Third Opus session of 2026-08-18; the afternoon session's
wrap is archived as `HANDOVER_2026-08-18_unblock-publish-path.md`.

**Build beat:** `2026-08-18-the-number-that-was-measuring-the-wrong-thing` — merged, live, eligible.
**Docs:** `docs/CONVENTIONS.md` §9 (new gate-registry row for the `deploy/**` path-filter defect
class, then shortened to satisfy the 120-char pointer limit); `docs/audits/AI_COST_DRIFT_ATTRIBUTION_2026-08-18.md`
added. `sync_doc_metadata --apply` found everything else in sync; links/tombstones/index/ADR-index/doc-facts all green.
**Decisions:** none needed — flipping a frozen test assertion and widening a `paths:` filter are
implementation calls with their reasoning recorded inline and in #2881's closure comment.
**Main:** green (`bda59f73c`) — `check_main_green.py` exit 0.
**Incidents:** none — main was red 55m02s (`00:59:51Z` → `01:54:53Z`, two consecutive failed runs
from my own merge), which is under the >1h incident-class bar. Recorded here rather than omitted.
**Stash/hooks:** clean — `git stash list` empty, hook freshness 🟢.
**Closures:** #2881 commented (ADR-099 two-line contract). #2883 was closed **in error** by #2886's
merge and has been reopened with the cause recorded.
**Backlog:** Now live at 12 actionable; no stale `Later` issues. No promotion needed.
**Alarms:** 0 uncited — `check_alarm_citations.py` exit 0; the 8-alarm board is unchanged from the
afternoon session, exactly as 24h-period aggregates should be.
**CI warnings:** 1 — `test / Unit Tests` at **1443s vs the 1200s budget**. Already filed as **#2692**
(1247s when filed); recorded the worse measurement there rather than filing a duplicate, and took the
deliberate no-action call this session. Re-ran `--decoded`.

---

## The instruction that mattered most, and why it fired again

The owner built a date check into the prompt because the *previous* session inherited a Wednesday
that had not arrived. It fired again, in a subtler form. Boot was **Tuesday 17:17 PDT — which is
Wednesday 00:17 UTC.** UTC had rolled over seventeen minutes earlier, so a bare `date -u` says
"Wednesday" and the plan reads live.

It was not. Every Phase-0 cron sat **15–17 hours ahead**: #2669's chronicle (15:00Z), #2668's brief
(17:00Z), and both alarm self-clear predictions (whoop ~08:00 PT, qa-smoke-failures ~14:16Z). Phase 0
was unworkable, so it was re-sequenced rather than faked, and the fan-out plus the owner asks were
brought forward. The alarm board was confirmed byte-identical to the afternoon snapshot, which is
what a 24h-period aggregate *should* look like after seven hours.

**Reflex for the next cron-gated session:** print both clocks and compare against the cron's own
timezone. "Is it Wednesday?" is ambiguous here for about seven hours of every day.

## The September base — the plan's headline inverted under re-measurement

The plan carried *"there is no cheap option that preserves current behaviour,"* derived from
`ProjectedMonthlySpend = $180.25`. That projection is **spike-inflated and falling**: $239 (08-12) →
$171.72, with a $36 step at the 08-17 reset.

Measured from Cost Explorer instead:

| | |
|---|---|
| Daily unblended, 08-12 → 08-17 (6 complete days) | **$4.12/day**, sd $0.66, n=6 |
| Steady-state month | **$124** (95% CI $108–139) |
| The 08-09 → 08-11 spike | $8.85 + **$20.57** + $6.29 = $35.70 in three days |
| MTD split | **Bedrock $61.35 (55%)** · CloudWatch $19.87 (18%) · tax $9.45 · Secrets Manager $6.62 |

Tier bands recomputed by running `_tier_for` directly, not by hand:

| ceiling | steady state, no cut | after #2882 | August-like (w/ spike) |
|---|---|---|---|
| **$85 (auto-revert)** | tier 3 | tier 3 | tier 3 |
| $125 | tier 3 | tier 1 | tier 3 |
| **$150** | **tier 1** | **tier 0** | tier 3 |
| $180 | tier 0 | tier 0 | tier 2 |

**Corrected finding: there IS a cheap option.** $150 holds tier 1 — the platform's current normal —
with no cuts at all. What money above $150 buys is *spike headroom*, not steady-state behaviour.
Stated with its uncertainty: n=6, CI $108–139, and one of those six days is the reset.

## The 2.44x gauge was mostly measuring its own scope mismatch (#2883)

Verified in source rather than taken from the worker's report:

```
cost_governor_lambda.py:827   mtd = non_ai + ai      # ai carries _AI_SAFETY_BUFFER = 1.15 (:178)
cost_governor_lambda.py:771   AuthoritativeCostMTD = mtd
cost_governor_lambda.py:776   drift_ratio = mtd / self_reported_mtd   # Bedrock-ONLY, unbuffered
```

`CostMetricDriftRatio` divides **the whole AWS bill, padded 15%** by **AI spend only, unpadded**. Of
the $65.49 gap: **$39.62 scope mismatch, $9.29 the deliberate buffer, ~$11–17 genuine**. Real drift
is **≈1.3–1.4x, not 2.44x**. The genuine part is mostly cache-token *under-counting* (the app sees
21% of cache-write and 15% of cache-read tokens vs native `AWS/Bedrock`); prices verified correct,
stale `_PRICES` ruled out, the ADR-062 chokepoint clean. `named + unknown == bare` to the cent, so
`unknown` is a **tagging** gap, not missing money.

**Consequence: #2883 is a much weaker blocker on the September base than the plan assumed**, and the
base sizing should use `AuthoritativeCostMTD`/projection directly rather than deriving a whole-bill
figure from the AI-only metric.

## A 7/7-green PR red-mained twice

#2884 (`deploy/**` into ci-cd's `paths:` + a `bash -n` gate) merged green and broke main twice:

1. `test_push_trigger_globs_match_workflows` — `PUSH_TRIGGER_GLOBS` in `deploy/sentinel_github.py`
   is a sanctioned maintained literal mirroring the live filters. The derivation-guard primitive
   caught it exactly as designed.
2. `test_gate_registry_1349` — the CONVENTIONS §9 pointer cell was 147 chars against a 120 limit.
3. `test_matches_push_trigger_semantics` asserted `not _matches_push_trigger("deploy/…")`, citing
   "CONVENTIONS §deploy-from-main". That citation is a **misattribution** — §2 is about packaging
   the working tree rather than the wrong branch, and never argued `deploy/` should skip CI. The
   assertion had simply frozen the old filter state, so it was flipped with the reasoning inline.

**The durable lesson: green PR ≠ green main.** The PR lane (`Collect + deploy-critical + format`)
**deselects ~11,479 tests** that `test / Unit Tests` runs on push. That is now attached to #2692
alongside the 1443s measurement, because the deselection that keeps the PR lane fast is actively
leaking defects onto main.

**Proven live in the process:** #2881's acceptance box 1, which the PR could not demonstrate
pre-merge. Commit `34da61be0` touched only `deploy/` + `docs/` (the latter outside ci-cd's filter)
and minted a CI/CD run. And `Deploy` was observed **`skipped`** on both main runs — the deploy matrix
diffs only `lambdas/ mcp/ mcp_server.py` (`ci-cd.yml:614`), so widening `paths:` cannot strand an
approval-gate lease. Measured, not argued.

## Gotchas

- **A negated closing keyword still closes.** #2886's body said, in bold, *"This PR does NOT close
  #2883"* — written precisely to prevent closure. GitHub matched `close #2883` inside it and closed
  the issue on merge. The sentence written to prevent the closure caused it. Reopened by hand; a
  closed issue silently leaves the ranked backlog.
- **All three workers returned non-reports** ("I'll wait for the background poll") having pushed real
  work. Trap 7 held for the third session running — verify against the branch, never the report.
- **A `timeout:` above the 600000ms tool max is silently capped**, so a watcher sized for 21 minutes
  exits at 10 and reads exactly like a finished run. Re-read status after every loop.
- **One worker finding was rejected on verification:** the gate census's positional step-ids were
  reported as warranting their own issue. The census already documents the behaviour and *refuses*
  stale proofs rather than re-attaching them — it fails closed and loudly. Friction, not a defect.

## Residual / next picks

- **#2669** — the Wednesday chronicle box, fires 15:00Z on 08-19 (~08:00 PT). Unworked this session:
  the cron had not run. Run 3 of 3.
- **#2668** — the brief's IC-3 box, 17:00Z on 08-19; sample after ~17:10Z (the brief takes ~8 min and
  a 17:06Z check once missed it by 13 seconds). A clean run CLOSES it.
- **#2741** — box 5 only; needs `FailCount` at 0 **plus** `qa-smoke-failures` observed *transitioning*
  to OK, not the condition. Everything else on it is deployed and symbol-verified.
- **#2670** — PR **#2885 is green but deliberately NOT merged**: merging implies a
  `life-platform-qa-smoke` Lambda deploy, and without deploy consent that would strand an
  approval-gate lease. Its chronic reclassification was independently verified (8 of 8 invocations in
  48h warned drift, always the same two receipts; the cron is daily, so those are mostly post-deploy
  invocations — the conclusion is stronger than "nightly"). Acceptance boxes 2–3 need the 24h
  rolling-Maximum window to turn over.
- **#2883** — boxes 2–4 open. Highest leverage is fixing the ratio's **scope** before touching
  telemetry; box 3's alarm must wait for box 2 or it alarms on the artifact.
- **#2692** — the 1443s suite duration and the PR-lane/main-lane deselection gap.
- **#2882** — verified, green apart from a 9-test literal bump; merging implies a CDK deploy +
  site-api deploy. Owner decision.
- **#2836 / #2734** — the September base. `not-work — owner decision; a number is required and
  09-01 arrives by itself.`
- A Withings weigh-in. `not-work — owner action; no longer blocks deploys, gates only the supersede
  reflex.`

## Owner asks at hand-off (4)

1. **The September base number.** $150 buys tier 1 today and tier 0 after #2882; $85 auto-reverts to
   tier 3 (reader AI dark) on 09-01. Above $150 buys spike headroom only.
2. **Merge #2882?** Verified; implies `cdk_deploy.sh LifePlatformMonitoring` + the site-api deploy.
3. **Merge + deploy #2885?** Green and held; implies `deploy_lambda.sh life-platform-qa-smoke`.
4. **A Withings weigh-in** — newest row is still `DATE#2026-08-16`, `carried_from_cycle: 13`.
