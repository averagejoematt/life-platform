/* cohort_math.js — #1820: direction-aware cohort percentile.

   /api/cohort_strip computes `matthew_percentile` as the share of the cohort
   STRICTLY BELOW Matthew's raw value, and ships `lower_is_better` alongside it
   (lambdas/web/site_api_social.py, handle_cohort_strip). For a higher-is-better
   metric that "% below" IS "% he's ahead of" — no flip needed. For a
   lower-is-better metric (the module's own documented example is resting heart
   rate) it is exactly backwards: a LOWER value is the better one, so the people
   below him are the ones who did BETTER, not worse — he is ahead of the people
   ABOVE him, i.e. `100 - matthew_percentile`.

   Pulled into its own tiny pure module (no DOM, no imports) so the arithmetic is
   unit-testable without loading all of cockpit.js (a self-executing page script —
   see tests/js/cohort_math.test.mjs). cockpit.js imports and calls this; it does
   not reimplement the flip inline. */

export function cohortAheadPercent(matthewPercentile, lowerIsBetter) {
  if (matthewPercentile == null) return null;
  return lowerIsBetter ? 100 - matthewPercentile : matthewPercentile;
}
