# The Time-Affluence Meter — a documented proxy

**Issue:** #1408 (epic #718, frontier review 2026-07-18 Epic C / C6) ·
**Code:** `lambdas/time_affluence.py` (pure math) + `lambdas/compute/hypothesis_engine_lambda.py::run_time_affluence_weekly` (weekly host) ·
**Partition:** `USER#matthew#SOURCE#time_affluence`

## Why this exists, and why it is a *proxy*

Time poverty carries a large, unemployment-scale wellbeing hit in the literature
(Whillans 2017). The platform measured **nothing** about it. The tools that could
have measured it directly — calendar integration — were retired (ADR-030), and
re-integrating a calendar is **explicitly out of scope** for this work.

So the Time-Affluence Meter does **not measure time affluence**. It is a **proxy**:
it triangulates three deterministic behavioural traces that *co-vary* with time
pressure, plus one weekly self-report anchor, into a single standardised weekly
index. It is labelled `"is_proxy": true` on every row it writes and it is called a
proxy everywhere it surfaces. Treat its number as a **hypothesis generator**, never
a validated score (per the frontier review's digital-phenotyping caveat).

## Construction

Everything is computed from **existing partitions** — no new ingestion. A "week" is
keyed by its closing **Sunday** (the day the probe is asked, framed "this week: …"),
and every day Mon–Sun folds into that week.

| Component | Source partition | Raw weekly signal | Orientation |
|---|---|---|---|
| `todoist_open_load` | `todoist` | mean daily open load (`active_count` + `overdue_count`) | **flipped** — more open load ⇒ *less* affluent |
| `evening_regularity` | `evening_ritual` | −(std-dev of the evening ritual's completion minute-of-day); needs ≥3 timestamped evenings | steadier evenings ⇒ more structured, unhurried time |
| `unscheduled_days` | `todoist` | fraction of observed days with `due_today_count == 0` | more obligation-free days ⇒ more discretionary time |
| `felt_time` (probe) | `time_affluence` (`DATE#`) | the weekly 1-item self-report, 0–4 | the self-report anchor, when answered |

**Standardisation (ADR-105 rule 4 — personal variance, no hand-set cutoffs).** Each
component is z-scored against **Matthew's own** values over the rolling window
(`PROXY_WINDOW_WEEKS = 12`). A component with fewer than `TRACE_MIN_WEEKS = 4`
observed weeks, or zero variance, is not calibratable honestly and **drops out of
every week's blend**. Open-load's z is negated so that, for every component,
**higher = more time-affluent**.

**The composite** is the mean of the *available* standardised components that week.
Coverage = present components ÷ 4. Below `COMPONENT_COVERAGE_FLOOR = 0.5` the week
emits **no score** (`state: "insufficient_signal"`) rather than a number the data
can't support.

## Absence is coverage-flagged, never zeroed (ADR-104)

This is the whole point of the story. A skipped weekly probe, or a trace with no
data that week, is a **coverage gap** — it drops from the blend and from `n`, and it
is **never scored 0**. Zeroing a missing self-report would fabricate a "time-poor"
reading out of silence.

This is the *measured-absence* branch of ADR-104 (like `fulfillment_index`: a sensor
gap shrinks the denominator), and the **opposite** of the character engine's
*behavioural* absence, where an unlogged habit legitimately scores 0. A self-report
you didn't give is not evidence of anything — so the probe is fully skippable, and an
unanswered Sunday simply means `n` doesn't accrue that week.

## The candidate edge (ADR-105 rule 1 — uncertainty + n on every claim)

The hypothesis is **edge-week time-affluence → next-week adherence** (adherence =
weekly mean of `habitify.completion_pct`). The weekly host builds lagged pairs and
tests, deterministically via `stats_core` (no LLM anywhere near the verdict):

- **lag 1 week** — the pre-registered hypothesis (this week's affluence predicting
  *next* week's adherence);
- **lag 0** — the contemporaneous control.

For each lag: Pearson `r`, raw `n`, autocorrelation-corrected effective `n_eff`
(AR(1)/Bartlett), a p-value computed on `n_eff`, and a 95% Fisher CI. The p-values
are then **BH-FDR-corrected across the lag family** (`p_fdr`). Below
`EDGE_MIN_N_EFF = 6` effective weeks a lag is tagged **`descriptive`** — reported
with its uncertainty but never asserted as an effect. This is genuinely honest for an
N=1 weekly series: for a long time it will read "descriptive, insufficient n," and it
says so.

Results persist to `EDGE#<sunday>`; the standardised weekly proxies persist to
`PROXY#<sunday>`. Both are recomputed from scratch each Sunday, so a verdict can move
in **either** direction as evidence accrues.

## Limitations (read these before trusting a number)

1. **It is a proxy, not a measurement.** No component observes time directly. A busy
   but *chosen* week (deep work you wanted) and a busy *imposed* week look similar to
   the open-load trace. The self-report anchor is the only component that knows the
   difference, and it is one 0–4 tap.
2. **Behavioural traces are fragile.** Evening-ritual regularity conflates "unhurried"
   with "habitual"; open-load conflates "obligated" with "engaged" (the review's
   Accomplishment-vs-load caveat). These are hypothesis inputs, not ground truth.
3. **Small n, always.** One data point per week. Even a full year is ~52 points; the
   edge test will read `descriptive` until effective n clears the floor, and the CI
   will be wide. That is reported, not hidden.
4. **Personal-relative, not absolute.** A z of +1 means "a more time-affluent week
   *for Matthew*," not any population claim. There is no normative scale here.
5. **No calendar (ADR-030).** The single most direct signal — scheduled vs. open
   hours — is deliberately absent. If a calendar source is ever re-added, the
   `unscheduled_days` trace should be replaced by a real free-hours measure and this
   proxy re-graded.
