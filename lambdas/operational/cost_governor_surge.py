"""lambdas/operational/cost_governor_surge.py — ADR-133's surge rule, derived (#3510).

EXTRACTED, NOT NEW (#1665/#2610). `cost_governor_lambda.py` sits against the 1,000-line
hard ceiling and the standing rule is extraction, never a baseline raise. This module is
the PURE half of the surge decision — the engage bar and the hysteretic engage/disengage
predicate. Everything that needs a CloudWatch or SNS client (reading the weekly baseline,
counting flips, emitting the metrics, sending the alerts) stays in the Lambda, where the
tests already monkeypatch those clients.

THE DEFECT THIS MODULE EXISTS FOR
─────────────────────────────────
ADR-133 sized `SURGE_UNIQUES_THRESHOLD = 900` as "~4x the median and ~3.1x the latest
reading" of a 165–288 uniques/week baseline, and closed with "revisit the threshold as
the baseline traffic grows — it is one env var." The baseline then grew 3–4x and NOTHING
carried that revisit: the weekly `UniqueVisitors7d` readings for 2026-07-01→09-05 were
972, 728, 803, 892, 973, 773, 838, 1011 — mean 873.75 — so 900 sat essentially at the
MEAN of the series it was supposed to be far above. A bar at the mean of a noisy series
flips on the noise: five engage/disengage edges in seven weeks, each an owner email and a
17% swing in the effective ceiling ($215→$252) and therefore in all three tier bands.

`surge_threshold_from_baseline` is the carrier the clause never had: the revisit happens
on every governor run instead of never, and
`tests/test_cost_governor.py::test_derived_threshold_exceeds_every_documented_baseline_reading`
is what keeps it true through the next 4x.
"""

from __future__ import annotations

import math
import os
import statistics

# 900 is now the FLOOR, not the rule — kept so a COLLAPSE in traffic can never make surge
# mode cheap to enter, and kept env-overridable (ADR-133's "one env var" property).
SURGE_UNIQUES_THRESHOLD = int(os.environ.get("SURGE_UNIQUES_THRESHOLD", "900"))
# The derived rule: engage at mean + K*SD of the trailing weekly baseline. K=3 puts the
# bar ~1.36x the mean at today's spread (873.75 + 3*104.4 = 1188), which is above every
# reading the platform has ever recorded (max 1011) and still an order of magnitude below
# the "single viral link" step ADR-133 defined surge for. SD is the SAMPLE SD, so a
# baseline that genuinely widens raises the bar with it.
SURGE_BASELINE_WEEKS = int(os.environ.get("SURGE_BASELINE_WEEKS", "8"))
SURGE_SIGMA_K = float(os.environ.get("SURGE_SIGMA_K", "3"))
# Fewer readings than this and the SD is not a measurement — fall back to the floor and
# SAY SO in the rule string, rather than deriving a threshold from two points.
SURGE_BASELINE_MIN_READINGS = 4
# Hysteresis: once engaged, surge holds until traffic drops below 0.8x the threshold.
# Without it a series oscillating one unique either side of the bar produces an unbounded
# number of edges — which is exactly what the SSM parameter history recorded.
SURGE_DISENGAGE_RATIO = 0.8
# Two flips in 30 days is itself the signal that the threshold is mis-set (#3510's own
# Outcome). At each edge the governor counts the trailing-30d flips from its own
# LifePlatform/Budget::SurgeFlip series and alerts on the same SNS topic the surge and
# tier alerts use when the count reaches this bar.
SURGE_FLIPS_30D_ALARM = 2


def surge_threshold_from_baseline(readings) -> tuple[int, str]:
    """(threshold, rule) — the engage bar derived from the trailing weekly baseline.

    PURE. Takes the weekly `UniqueVisitors7d` readings as a list so the RULE can be
    tested against the real recorded series without a CloudWatch client, and so the rule
    string that ships in the log line, the alert body and the budget-breakdown payload is
    the same string the test asserts on.

    The bar is ``mean + SURGE_SIGMA_K * SD`` (sample SD), floored at
    ``SURGE_UNIQUES_THRESHOLD``. Under ``SURGE_BASELINE_MIN_READINGS`` readings there is
    no SD to speak of, so the floor stands and the rule says which of the two produced the
    number — a threshold whose derivation is invisible is how 900 survived a 4x change in
    the baseline it was derived from.
    """
    vals = [float(v) for v in (readings or []) if v is not None]
    if len(vals) < SURGE_BASELINE_MIN_READINGS:
        return SURGE_UNIQUES_THRESHOLD, (
            f"floor {SURGE_UNIQUES_THRESHOLD} (only n={len(vals)} weekly readings, "
            f"under the n>={SURGE_BASELINE_MIN_READINGS} needed to derive an SD)"
        )
    mean = statistics.fmean(vals)
    sd = statistics.stdev(vals)
    derived = int(math.ceil(mean + SURGE_SIGMA_K * sd))
    threshold = max(SURGE_UNIQUES_THRESHOLD, derived)
    rule = (
        f"mean {mean:.1f} + {SURGE_SIGMA_K:g}*SD {sd:.1f} = {derived} "
        f"(n={len(vals)} weekly readings over {SURGE_BASELINE_WEEKS}w, floor {SURGE_UNIQUES_THRESHOLD})"
    )
    return threshold, rule


def engaged(recent_uniques, threshold: int | None, prev_surge_active: bool) -> bool:
    """Is surge mode ON, given this reading, the derived bar, and the previous state?

    `recent_uniques` is None when the metric has not been read yet (a transient
    CloudWatch error) — fails closed to NOT surging, never to surging.

    Hysteretic: engage at >= T, and once engaged HOLD until traffic falls below
    ``SURGE_DISENGAGE_RATIO * T``. The band is a hold, never an entry — it must not
    become a second, lower engage threshold from the off state.
    """
    if recent_uniques is None:
        return False
    bar = SURGE_UNIQUES_THRESHOLD if threshold is None else int(threshold)
    if prev_surge_active:
        return recent_uniques >= SURGE_DISENGAGE_RATIO * bar
    return recent_uniques >= bar
