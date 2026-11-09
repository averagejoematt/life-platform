"""calibration_v2.py — calibration-v2: three questions, three tests (owner requirement 2026-11-09).

The owner, verbatim: "a statistically defensible approach that distinguishes: Whether calibration can be estimated at
all. Whether the sample supports a claim of overconfidence or underconfidence. Whether a coach demonstrates forecasting
skill relative to the baseline. These are different questions and shouldn't share one arbitrary threshold."

This module answers each with its own evidence test and its own uncertainty statement (``docs/methods/CALIBRATION_V2.md``).
It is DARK and ADDITIVE: served beside the v1 fields on ``/api/calibration`` as ``assessment_v2``; no v1 field or label
reads from it. Pure and deterministic, stdlib only.

THE CONSTANTS BELOW WERE FIXED BEFORE ANY PER-COACH OUTPUT WAS COMPUTED (see the methods note's "order of work"). None
is chosen by which forecaster it flips; each is a convention or is derived from one.
"""

from __future__ import annotations

# ── the method, pre-declared ─────────────────────────────────────────────────────────────
METHOD_VERSION = "calibration-v2"

#: Family-wise error rate for EACH question, per forecaster. 0.05 is the convention, and it is the threshold the site's
#: existing comparison with the simple guess already uses (``coach.coach_baseline.SIGNIFICANCE``).
ALPHA = 0.05

#: A confidence LEVEL is one of the ten equal stated-confidence bands the reliability curve already serves
#: (``stats_core.reliability_bins(n_bins=10)``): 0.5 and 0.55 are one level, 0.5 and 0.6 are two.
LEVEL_BINS = 10

#: A level's interval is USABLE when its exact (Clopper-Pearson) 95% interval is at most this wide whatever the hit
#: count — i.e. it rules out at least half the probability scale. Deliberately lenient: this gate decides only whether
#: an across-level estimate is REPORTED; no label rides on it (labels come from the tests below, whose error rate is
#: ALPHA). The minimum level size is DERIVED from it (``min_level_n()``), never typed.
USABLE_CI_WIDTH = 0.5

#: An across-level estimate needs at least two levels (a slope needs two distinct stated confidences).
MIN_LEVELS = 2

#: The across-level estimate is a 2-parameter logistic recalibration (Cox 1958). Events-per-parameter >= 10 (Peduzzi et
#: al. 1996) is the conventional floor for a logistic fit whose interval can be trusted, so the rarer outcome must occur
#: at least EVENTS_PER_PARAMETER * 2 times.
EVENTS_PER_PARAMETER = 10
RECALIBRATION_PARAMETERS = 2

#: The skill baseline: the rule the site already scores every coach call against (``coach.coach_baseline.RULE_ID``).
SKILL_BASELINE = "nothing_changes"
#: The comparison's separate records, never added together (``coach.coach_baseline.RECORDS``).
SKILL_RECORDS = ("number", "direction", "yes_no", "sealed")
