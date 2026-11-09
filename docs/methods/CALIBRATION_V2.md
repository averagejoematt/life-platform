# Calibration v2 — three questions, three tests

**Status: ADOPTED 2026-11-09** (owner ruling). Every page and API that shows or serves a calibration verdict uses it.
**Owner requirement:** 2026-11-09 ("these are different questions and shouldn't share one arbitrary threshold").
**Code:** `lambdas/experiment/calibration_v2.py` (pure; `assess`), served by `lambdas/web/site_api_calibration_v2.py`.
It is a sibling of `calibration_core.py`, not an edit to it. v1's Brier, skill and reliability numbers, and its
open-source and JS copies, stay byte-identical. `site/assets/js/calibration-v2-core.js` is the browser port used by
/method/grade-your-coach/; shared vectors hold it to the Python exactly.
**Served:** `/api/calibration` → `assessment_v2` (per coach and per platform stratum, this season), with
`status: "adopted"` and `adopted: "2026-11-09"`. The same coach answers are on `/api/coach_team` (each huddle entry)
and the MCP track-record tool.
**Shown on:** /method/calibration/, /method/grade-your-coach/, /method/registry/ (`calibration_v2_*`) and the Coaching
Room build.

## The owner's ruling (2026-11-09)

> "I approve adopting the new calibration methodology. Preserve its three distinct questions: Can calibration be
> estimated across confidence levels? Is there statistically supported overconfidence or underconfidence at an
> observed confidence level? Does the coach outperform the same-call simple baseline? Keep the uncertainty ranges and
> multiple-testing correction. Never equate failure to detect a problem with proof of good calibration. Nutrition's
> result can be described as evidence of overconfidence for its 50%-confidence calls, but not as proof of poor
> calibration across confidence levels. No coach currently demonstrates a reliable advantage over the baseline.
> Update the public methodology accordingly. Do not modify thresholds to accommodate current coach outcomes."

No constant changed at adoption. The words changed in one way: an over- or under-confidence finding now names the
level it was found at (for example, "Over-confident at its 50% calls (12 of 43 came true, 95% CI 15%–44%; Holm-adjusted
p 0.0108) — a finding about calls at that confidence level, not about calibration across confidence levels.").

## Method history

| Version | In use | What it was |
|---|---|---|
| calibration-v1 | until 2026-11-09 | One label per forecaster from a fixed ±0.15 mean-gap trip, a Brier-skill gate and a one-band withhold rule. |
| calibration-v2 | from 2026-11-09 | The three questions below, each with its own test and interval. |

The v1 fields (`calibration`, `label`, `score`) are still computed and served for API compatibility. They are listed as
deprecated in `/api/calibration` → `calibration_method`, and no page renders them
(`tests/test_calibration_v1_labels_retired.py` guards that).

## The calls it counts

The same publication-eligible calls as every other public count (call publication method v2,
`common/prediction_publication.py`): private calls are dropped by the table before this code sees a row. Within that set,
the same season rows as the coach's record (`coach_record.decided_rows`): graded right or wrong, one resolution per call,
not under classification review. Platform strata (hypotheses, each forecast model) are assessed separately and never pooled.
`tests/test_calibration_v2_privacy.py` proves that journal, State of Mind, video-diary and private-call rows cannot change
any v2 output. Its mutation control is the same walk with the gate off, which does move the output.

## The three questions

Each answer carries `n`, an estimate, an interval and the method name. A label appears only when its test passes;
otherwise the wording is neutral. "Well-calibrated" is never a v2 output.

### 1. Can calibration across confidence levels be estimated?

A level is one of the ten stated-confidence bands the reliability curve already uses (0.5 and 0.55 are one level).

- **Every level** gets a plain statement: "calls stated at about 50% came true 10 of 44 (95% CI 12%–38%)" — exact
  (Clopper-Pearson) interval. This is a single-level comparison, and is named as one.
- **Across levels** is *estimable* only when at least **2 levels** each have a **usable** interval, and the rarer
  outcome occurs at least **20** times. Usable: the level's exact 95% interval is at most **0.5** wide for any hit
  count. That takes **17** calls: `min_level_n()` derives it from the 0.5, and a test pins it. 20 = 10 events per
  parameter (Peduzzi et al. 1996) × the 2 parameters of the fit.
- When estimable, the estimate is the **logistic recalibration slope** (Cox 1958; 1 = confidence tracks outcomes) with
  a Wald 95% interval. Otherwise the answer is "calibration across confidence levels not estimable", with the reason.

The 0.5 width is lenient on purpose: this gate decides only whether an across-level number is reported. No label
depends on it.

### 2. Does the sample support over- or under-confidence?

- **Test:** at every level with a resolved call, an exact two-sided binomial test of the hits against the level's mean
  stated confidence. Mixed stated values inside one level make this conservative (a Poisson-binomial has less variance
  than the binomial with the same mean).
- **Multiplicity:** Holm across the levels tested, family-wise **α = 0.05** per forecaster.
- **Labels:** *over-confident* (calls came true less often than stated) when a level rejects in that direction;
  *under-confident* the other way; *mixed* when levels reject both ways. The words always name the level or levels
  that rejected ("over-confident at its 50% calls"). A finding at one level is never a statement about calibration
  across levels.
- **No rejection:** "consistent with stated confidence (not established)". When no level was large enough to reject
  even at its most extreme possible result, the answer is "insufficient evidence" instead — the test could not have
  fired.

### 3. Does the coach show skill against the baseline?

- **Baseline:** the rule the site already serves beside every count, `nothing_changes` (`coach/coach_baseline.py`):
  the metric stays at its last reading before the call was filed, graded by the same grader with the same tolerance.
  Chosen over the stratified base rate because it is an honest forecast made at filing time. A base rate is learned
  from the outcomes themselves, and Brier skill against it is driven by calibration-in-the-large: a coach who says 50%
  on every call scores below it whenever the hit rate differs from 50%. That mixes question 3 into question 2.
- **Same calls:** each comparison uses only calls the rule could also score. Unscorable and not-yet-scored calls are
  counted and shown.
- **Test:** an exact sign test on the calls only one of the two got right. The estimate is the difference in hit rate
  (coach minus rule) on those calls. Its interval is exact, conditional on the number of disagreements (Clopper-Pearson
  on the coach's share of them).
- **Records:** number, direction, yes/no and sealed calls stay separate records, as on the site. The intervals are
  Bonferroni-adjusted across the records a forecaster has.
- **Label:** *advantage over the guess* when the interval is wholly above 0; *the guess did better* when it is wholly
  below 0. Otherwise "no demonstrated advantage".
- Strata with no baseline (hypotheses, interval forecasts) answer "no baseline for this stratum".

## Caveats stated with every output

- Calls that share a metric and a window are not independent, so every p-value and interval here is optimistic.
- Nothing is tuned per forecaster. Every constant is in one block at the top of `calibration_v2.py`.

## Order of work

1. Read the v1 rule (`calibration_core.py` `CONCENTRATED_SHARE`, the gap verdict, the under_review hold, the pooled copy)
   and the rejected v3 proposal (one 43-per-band threshold for all three questions).
2. Fixed the constants and this note, and committed them (the first commit on `feat/calibration-method-v2`) before any
   v2 code ran on any data.
3. Implemented the tests on synthetic data only.
4. Only then computed per-coach v2 outputs from the live public API.

Disclosure: the author had already seen v1 labels and per-coach call counts (from the v3 proposal's table) before step 2.
No constant here is tied to a count, and none was revisited after step 4.

## What the results said at the ruling (`/api/calibration`, 2026-11-09 04:10 UTC)

These answers are a dated snapshot. They move whenever calls are graded or grades are corrected, so read the live
answers on `/api/calibration` or /method/calibration/. After that night's grade corrections, Nutrition had 7 decided
calls this season and read "insufficient evidence".

- **Nutrition** was over-confident at its 50% calls: 12 of 43 came true (95% CI 15%–44%; Holm-adjusted p 0.0108). That
  was evidence about its 50% calls only, not proof of poor calibration across confidence levels, which was not
  estimable for any coach yet.
- **Every other coach:** no level departed from its stated confidence ("consistent with stated confidence (not
  established)"), or there are too few calls for the test to fire ("insufficient evidence"). Neither is proof of good
  calibration.
- **Skill:** no coach showed a demonstrated advantage over the same-call guess that nothing changes.
- No constant was changed at adoption, and none will be changed to suit a coach's outcome.
