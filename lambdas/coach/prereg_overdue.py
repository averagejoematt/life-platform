"""coach/prereg_overdue.py — no pre-registered row sits ungraded past its due date unheard (#5518).

WHY THIS EXISTS

A pre-registration is a promise that every sealed bet is graded or voided on the record. In cycle 17 four of the
eighteen sealed rows were invisible to their graders: the two genesis hypotheses carried a wall-clock ``phase=pilot``
stamp the engine's loader filtered out, and the retired training seat's two sealed bets sat in a partition the
evaluator never queried. Both stayed ``pending`` for weeks past their due dates and nothing said so; a review found
them on day 56. The grader fixes are #5533 (b) and ``compute/sealed_hypotheses``. This module is the INSTRUMENT that
makes the class audible next time, whichever seam it comes through:

1. **Grader visibility of a sealed prediction, independent of the stamp** (``grader_visible``): the evaluator's
   partition scan admits a row the ADR-058 phase filter passes OR a sealed row of the current cycle
   (``pre_registered``, not tombstoned, filed no earlier than the day before genesis) — the same rule
   ``compute/sealed_hypotheses.grader_visible`` applies to hypotheses. Every earlier cycle's sealed rows carry the
   reset's tombstone and stay out.

2. **The overdue count** (``scan`` / ``emit``): every run of the coach-prediction-evaluator reads, phase-blind,
   every ``pre_registered`` PREDICTION# row in every grading partition (operational AND retired seats) and every
   hypothesis that carries a frozen ``test_spec`` (#530: every v2 hypothesis is a pre-registration), and counts the
   non-tombstoned rows still ``pending``/``confirming`` more than a grace past their due date. The count is emitted as
   ``PreRegisteredOverdue`` in the evaluator's existing ``LifePlatform/Predictions`` namespace; the alarm
   ``prereg-overdue`` (cdk/stacks/monitoring_prediction_alarms.py) fires at >= 1 for two consecutive daily periods,
   digest-routed.

   Due dates are the graders' own: a prediction's is ``prediction_windows.due_date`` (the scorecard's date); a
   conditional may legitimately wait for its antecedent until the evaluator's 2x-window expiry, so its horizon is
   that expiry. A hypothesis is due ``monitoring_window_days`` after it was written. The graces cover cadence, not
   tolerance for silence: the evaluator runs daily (3 days = two missed runs), the engine weekly and resolves an
   inconclusive row at most 7 days after its window (10 days). A row a working grader can see is decided, expired
   or archived inside those horizons, so a row past one is a row its grader cannot see or a grader that is not
   running — the exact failure. An owner evaluation hold (#5607) is deliberate and never counted.

   Missing data BREACHES: the scan raises rather than emit a comforting zero when a read fails, so a failed scan and a
   dead evaluator are both silence, and silence is heard. (grading-stalled also hears a dead evaluator; the overlap
   is accepted, as for commitments-ungraded.)

boto3-free at import, so the CDK stack imports the alarm's name, metric and window from here (the
``commitment_grading`` idiom) and the two cannot drift.
"""

from __future__ import annotations

from typing import Any, Iterable

from common.constants import EXPERIMENT_PHASE_CURRENT, EXPERIMENT_START_DATE
from common.pacific_time import parse_day_key, shift_day_key

from coach import evaluation_hold
from coach.prediction_grading import EXPIRY_MULTIPLIER
from coach.prediction_windows import due_date as prediction_due_date, effective_window_days

NAMESPACE = "LifePlatform/Predictions"
METRIC = "PreRegisteredOverdue"
ALARM_NAME = "prereg-overdue"
PERIOD_SECONDS = 86400
#: Two consecutive daily periods: the in-progress UTC day has no datapoint until the 18:00 UTC run, and missing data
#: breaches — one period would flap every morning (grading-stalled's guard, same reason).
ALARM_PERIODS = 2
PREDICTION_GRACE_DAYS = 3
HYPOTHESIS_GRACE_DAYS = 10
OPEN_STATUSES = ("pending", "confirming")


def _day(value: Any) -> str:
    return str(value or "")[:10]


def is_sealed_prediction(item: dict, genesis: str = EXPERIMENT_START_DATE) -> bool:
    """A sealed PREDICTION# row of the cycle that starts on ``genesis`` (rule 1)."""
    if not item.get("pre_registered") or item.get("tombstone"):
        return False
    filed = _day(item.get("created_date"))
    return parse_day_key(filed) is not None and filed >= shift_day_key(genesis, -1)


def grader_visible(item: dict, genesis: str = EXPERIMENT_START_DATE) -> bool:
    """The evaluator's admission rule: the phase filter, or a sealed row of this cycle whatever its stamp."""
    phase = item.get("phase")
    return phase is None or phase == EXPERIMENT_PHASE_CURRENT or is_sealed_prediction(item, genesis)


def prediction_horizon(item: dict) -> str | None:
    """The last day a visible grader may leave this prediction open: its due date, or a conditional's 2x expiry."""
    spec = item.get("evaluation") or {}
    due = prediction_due_date(_day(item.get("created_date")), spec, item.get("subdomain", ""))
    if due and spec.get("type") == "conditional":
        window = effective_window_days(spec, item.get("subdomain", ""))
        due = shift_day_key(_day(item.get("created_date")), window * EXPIRY_MULTIPLIER)
    return due


def hypothesis_horizon(item: dict) -> str | None:
    written = _day(item.get("created_at"))
    if parse_day_key(written) is None:
        return None
    try:
        return shift_day_key(written, int(float(item.get("monitoring_window_days") or 0)))
    except (TypeError, ValueError):
        return None


def overdue(item: dict, kind: str, today: str) -> dict | None:
    """The member record when ``item`` is an open pre-registered row past horizon + grace, else None."""
    if item.get("tombstone") or item.get("status") not in OPEN_STATUSES or evaluation_hold.is_grading_held(item):
        return None
    if kind == "prediction":
        if not item.get("pre_registered"):
            return None
        horizon, grace = prediction_horizon(item), PREDICTION_GRACE_DAYS
    else:
        if not item.get("test_spec"):
            return None
        horizon, grace = hypothesis_horizon(item), HYPOTHESIS_GRACE_DAYS
    if not horizon or shift_day_key(horizon, grace) >= _day(today):
        return None
    return {
        "kind": kind,
        "pk": item.get("pk"),
        "sk": item.get("sk"),
        "status": item.get("status"),
        "phase": item.get("phase"),
        "due": horizon,
    }


def _query_all(table, pk: str, prefix: str) -> Iterable[dict]:
    """Phase-blind on purpose: an invisible row is the thing being counted. Raises on a failed read."""
    kwargs = {"KeyConditionExpression": "pk = :pk AND begins_with(sk, :p)", "ExpressionAttributeValues": {":pk": pk, ":p": prefix}}
    while True:
        resp = table.query(**kwargs)
        yield from resp.get("Items", [])
        if "LastEvaluatedKey" not in resp:
            return
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def scan(table, coach_ids: Iterable[str], hypotheses_pk: str, today: str) -> dict:
    """Every overdue pre-registered row across the grading partitions and the hypotheses partition."""
    members = [m for c in coach_ids for i in _query_all(table, f"COACH#{c}", "PREDICTION#") if (m := overdue(i, "prediction", today))]
    members += [m for i in _query_all(table, hypotheses_pk, "HYPOTHESIS#") if (m := overdue(i, "hypothesis", today))]
    return {"count": len(members), "members": members, "as_of": _day(today)}


def emit(cw, result: dict, logger) -> dict:
    """Put the count (every completed scan, a zero included) and log each member."""
    for m in result["members"]:
        logger.warning(
            "[#5518] pre-registered row overdue: %s %s/%s status=%s phase=%s due=%s",
            m["kind"],
            m["pk"],
            m["sk"],
            m["status"],
            m["phase"],
            m["due"],
        )
    cw.put_metric_data(Namespace=NAMESPACE, MetricData=[{"MetricName": METRIC, "Value": float(result["count"]), "Unit": "Count"}])
    return {"count": result["count"], "as_of": result["as_of"]}
