"""coach_baseline.py — the coaches' record never appears alone (#4585, epic #4580).

THE RULE
--------
Every graded coach call is also scored by a rule that makes no forecast at all: **nothing
changes** — the metric stays where it was when the call was filed. The rule is graded on
the SAME call, by the SAME grader, against the SAME tolerance; only the prediction differs.

  * **Number call** (``point`` — "recovery will be about 61 tomorrow, ±1 SD"): the rule
    predicts the target-date reading equals the filed reading; it is right iff
    ``|graded reading − filed reading| <= the call's own frozen tolerance``.
  * **Direction call** (``directional``, and a threshold-less ``machine`` spec the grader
    re-routes to directional): the rule predicts FLAT; it is right iff the grader's own
    measured EWMA slope sits inside the grader's own noise band. No extra data is read —
    the slope rides on every graded direction call. A direction call cannot itself
    predict flat, so the coach and the rule are never both right on one.
  * **Yes/no bet** (``machine``/``conditional`` with a threshold, and a dispute-docket
    criterion): the rule answers "yes" iff the filed reading already meets the condition;
    it is right iff that answer matches the graded outcome.

**The filed reading** is the latest reading dated BEFORE the day the call was filed —
within ``FILED_GRACE_DAYS`` of that day, current experiment phase only. Strict on
purpose: a call is filed mid-morning Pacific, so the filing day's own nutrition total did
not yet exist, and the rule must never be handed a reading the coach did not have. Owner
ruling pending on the looser "on or before the filing day" variant (see the #4585 count
comment: it moves number calls from 18-of-34 to 21-of-35 for the rule).

THE RECORDS ARE SEPARATE
------------------------
Sealed day-one predictions, number calls, direction calls and yes/no bets are four
records. Each is tallied on its own and NO function here adds two of them together —
the rule's right-count on a direction call and on a number call are different questions.

WHEN IT IS SCORED
-----------------
At grading time (``stamp_at_grading`` from the evaluator, ``docket_stamp`` from the
docket resolver) the verdict is frozen on the PREDICTION# row as ``baseline``. Rows graded
before this shipped are back-filled by ``scripts/backfill_coach_baseline_4585.py``
(idempotent, dry-run by default). A graded row without ``baseline`` is ``not_yet_scored``
— never counted as unscorable, never as a miss. Until every graded row carries one, the
served sentence is the engine's existing skill score ("so far they do not beat a simple
guess"), with its n.

ADR-104/105: below ``MIN_N_FOR_RATE`` scored calls there is no percentage and no verdict;
a "better" is a two-sided exact sign test on the calls only one of the two got right.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Iterable

from common import stats_core
from common.constants import EXPERIMENT_START_DATE
from experiment import calibration_core
from experiment.measurable_metrics import METRIC_SOURCES

from coach import coach_record
from coach.prediction_point_grader import POINT_GRACE_DAYS, POINT_LOOKBACK_DAYS, evaluate_condition

logger = logging.getLogger(__name__)

RULE_ID = "nothing_changes"
RULE_VERSION = 1
RULE_WORDS = "a guess that nothing changes"

#: Never a percentage — and never a "better" — on fewer than this many scored calls.
MIN_N_FOR_RATE = 20
#: The sign test's two-sided threshold for "did better".
SIGNIFICANCE = 0.05
#: The filed reading may be at most this many days older than the day before filing —
#: the point grader's own grace for a missed reading.
FILED_GRACE_DAYS = POINT_GRACE_DAYS

#: The four records, in the order a sentence names them. Never summed.
RECORDS = ("number", "direction", "yes_no", "sealed")
RECORD_WORDS = {
    "number": "number calls",
    "direction": "direction calls",
    "yes_no": "yes/no bets",
    "sealed": "sealed day-one predictions",
}

# Why a graded call cannot be scored by the rule — served as counts, never hidden.
NO_FILED_READING = "no reading before the call was filed"
NO_GRADED_READING = "the grade carries no reading"
NO_RULE = "no rule for this kind of call"
NOT_GRADED = "the call was not graded right or wrong"
INCOMPLETE_SPEC = "the call's spec is incomplete"

_AGGREGATE_SUFFIXES = (("_30day_avg", 30), ("_14day_avg", 14), ("_7day_avg", 7))


# ── classification ──────────────────────────────────────────────────────────────────────


def rule_kind(spec: dict | None) -> str | None:
    """'number' | 'direction' | 'yes_no' for an evaluation spec, else None (qualitative)."""
    spec = spec or {}
    t = spec.get("type")
    if t == "point":
        return "number"
    if t == "directional":
        return "direction"
    if t in ("machine", "conditional"):
        # A threshold-less machine spec is graded as a direction call (#813 rescue).
        return "direction" if spec.get("threshold") is None else "yes_no"
    return None


def record_of(row: dict) -> str | None:
    """Which of the four records a graded PREDICTION# row belongs to."""
    if row.get("pre_registered"):
        return "sealed"
    if row.get("source") == "dispute_docket":
        return "yes_no"
    return rule_kind(row.get("evaluation"))


def filed_day(row: dict) -> str | None:
    """The day a call was filed: the earlier of its effective date and its freeze instant
    (a sealed call's ``created_date`` is genesis, but it was frozen before Day 1)."""
    days = [str(row.get(k) or "")[:10] for k in ("created_date", "pre_registered_at")]
    days = [d for d in days if len(d) == 10 and d[4] == "-" and d[7] == "-"]
    return min(days) if days else None


def _day_before(day: str) -> str:
    return (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")


def _split_metric(metric: str) -> tuple[str, int | None]:
    for suffix, days in _AGGREGATE_SUFFIXES:
        if metric.endswith(suffix):
            return metric[: -len(suffix)], days
    return metric, None


# ── the rule's verdict (pure) ────────────────────────────────────────────────────────────


def filed_reading(series: Iterable[tuple[str, float]], metric: str, filed: str) -> tuple[float | None, str | None, str | None]:
    """(value, on_date, unscorable_reason) — the metric as it stood when the call was filed.

    ``series`` is the base metric's chronological ``(date, value)`` list. The anchor is the
    day BEFORE ``filed``; an aggregate key (``hrv_7day_avg``) is the mean of the last N
    readings on or before it, a raw key the latest reading within ``FILED_GRACE_DAYS``."""
    if not filed or not metric:
        return None, None, INCOMPLETE_SPEC
    anchor = _day_before(filed)
    _base, agg = _split_metric(metric)
    s = [(d, float(v)) for d, v in series or [] if d <= anchor and v is not None]
    if not s:
        return None, None, NO_FILED_READING
    if agg:
        vals = [v for _, v in s[-agg:]]
        return sum(vals) / len(vals), s[-1][0], None
    floor = (datetime.strptime(anchor, "%Y-%m-%d") - timedelta(days=FILED_GRACE_DAYS)).strftime("%Y-%m-%d")
    day, value = s[-1]
    if day < floor:
        return None, None, NO_FILED_READING
    return value, day, None


def verdict(kind: str | None, spec: dict, *, actual: Any = None, filed_value: Any = None, holds: Any = None, noise_band: float):
    """(right: bool | None, unscorable_reason | None) — the rule graded on one call.

    ``actual`` is the grader's own reading (number) or slope (direction); ``holds`` is the
    graded truth of a yes/no condition."""
    spec = spec or {}
    if kind == "direction":
        if actual is None:
            return None, NO_GRADED_READING
        return abs(float(actual)) <= float(noise_band), None
    if kind == "number":
        tol = spec.get("tolerance")
        if tol is None:
            return None, INCOMPLETE_SPEC
        if actual is None:
            return None, NO_GRADED_READING
        if filed_value is None:
            return None, NO_FILED_READING
        return abs(float(actual) - float(filed_value)) <= float(tol), None
    if kind == "yes_no":
        if filed_value is None:
            return None, NO_FILED_READING
        if holds is None or spec.get("threshold") is None:
            return None, INCOMPLETE_SPEC
        rule_says = evaluate_condition(float(filed_value), spec.get("condition"), float(spec.get("threshold")))
        if rule_says is None:
            return None, INCOMPLETE_SPEC
        return bool(rule_says) == bool(holds), None
    return None, NO_RULE


def _dec(v: Any) -> Decimal | None:
    if v is None:
        return None
    return Decimal(str(round(float(v), 4)))


def stamp(right: bool | None, reason: str | None = None, *, filed_value: Any = None, filed_on: str | None = None) -> dict:
    """The DynamoDB-safe ``baseline`` map frozen on a graded PREDICTION# row."""
    out: dict = {"rule": RULE_ID, "version": RULE_VERSION}
    if right is None:
        out["unscorable"] = reason or NO_RULE
    else:
        out["right"] = bool(right)
    if filed_value is not None:
        out["filed_value"] = _dec(filed_value)
    if filed_on:
        out["filed_on"] = filed_on
    return out


# ── grading-time stamping (the evaluator's and the docket's data path) ─────────────────


def _series_before(metric: str, filed: str, data_cache: dict, *, get_source_data, extract_metric_series):
    """The base metric's series up to the day before ``filed`` via the evaluator's own
    cached, phase-filtered read (this experiment only). None when the source returned NO
    rows at all over a lookback inside the experiment — a dark source or a failed read is
    not "no reading", so nothing is frozen and the back-fill retries it."""
    base, _agg = _split_metric(metric)
    source = METRIC_SOURCES.get(base)
    if not source:
        return []
    anchor = _day_before(filed)
    if anchor < EXPERIMENT_START_DATE:
        # The day before filing predates this experiment: the phase-filtered read can only
        # come back empty, and that emptiness is a fact, not a failed read.
        return []
    records = get_source_data(source, data_cache, anchor, lookback_days=POINT_LOOKBACK_DAYS)
    if not records:
        return None
    return extract_metric_series(records, base)


def stamp_at_grading(pred, spec, result, status, data_cache, get_source_data, extract_metric_series, noise_band):
    """The ``baseline`` map for a call the evaluator just graded, or None when it cannot be
    decided honestly yet (the read came back empty — the back-fill retries it later).
    ``get_source_data`` / ``extract_metric_series`` / ``noise_band`` are the evaluator's
    own (``coach_prediction_evaluator._BASELINE_IO``), so the rule reads the grader's data
    path and its noise band. Never raises: a grade is never lost to its comparison."""
    try:
        if status not in coach_record.GRADED_STATUSES:
            return stamp(None, NOT_GRADED)
        kind = rule_kind(spec)
        if kind is None:
            return stamp(None, NO_RULE)
        actual = (result or {}).get("actual_value")
        if kind == "direction":
            right, why = verdict(kind, spec, actual=actual, noise_band=noise_band)
            return stamp(right, why)
        filed = filed_day(pred)
        if not filed or not spec.get("metric"):
            return stamp(None, INCOMPLETE_SPEC)
        series = _series_before(
            spec["metric"], filed, data_cache, get_source_data=get_source_data, extract_metric_series=extract_metric_series
        )
        if series is None:
            return None
        fv, on, why = filed_reading(series, spec["metric"], filed)
        if fv is None:
            return stamp(None, why)
        right, why = verdict(kind, spec, actual=actual, filed_value=fv, holds=(status == "confirmed"), noise_band=noise_band)
        return stamp(right, why, filed_value=fv, filed_on=on)
    except Exception as exc:  # noqa: BLE001 — the grade stands; the comparison waits for the back-fill
        logger.warning("[coach_baseline] %s: %s", (pred or {}).get("prediction_id"), exc)
        return None


def docket_stamp(docket, holds, data_cache, get_source_data, extract_metric_series):
    """The ``baseline`` map for a resolved dispute docket — one answer for the question,
    stamped on BOTH coaches' rows (the rule is right on both or on neither)."""
    try:
        criterion = (docket or {}).get("criterion") or {}
        filed = str((docket or {}).get("opened_date") or "")[:10] or None
        metric = criterion.get("metric")
        if not filed or not metric:
            return stamp(None, INCOMPLETE_SPEC)
        series = _series_before(metric, filed, data_cache, get_source_data=get_source_data, extract_metric_series=extract_metric_series)
        if series is None:
            return None
        fv, on, why = filed_reading(series, metric, filed)
        if fv is None:
            return stamp(None, why)
        right, why = verdict("yes_no", criterion, filed_value=fv, holds=holds, noise_band=0.0)
        return stamp(right, why, filed_value=fv, filed_on=on)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[coach_baseline] docket %s: %s", (docket or {}).get("sk"), exc)
        return None


def write_stamp(table, pk: str, sk: str, baseline: dict | None, *, only_if_absent: bool = False) -> bool:
    """SET ``baseline`` on a graded PREDICTION# row. Nothing is written for a None stamp
    (never a NULL that would read as "scored"). ``only_if_absent`` is the back-fill's
    idempotence: a row that already carries a stamp is left exactly as it is. Returns
    whether a write landed; never raises (the grade beside it already stands)."""
    if not baseline or table is None:
        return False
    kwargs: dict = {
        "Key": {"pk": pk, "sk": sk},
        "UpdateExpression": "SET baseline = :baseline",
        "ExpressionAttributeValues": {":baseline": baseline},
        "ConditionExpression": "attribute_exists(pk)" + (" AND attribute_not_exists(baseline)" if only_if_absent else ""),
    }
    try:
        table.update_item(**kwargs)
        return True
    except Exception as exc:  # noqa: BLE001 — a refused condition is the idempotent no-op; anything else is logged
        logger.warning("[coach_baseline] stamp %s/%s not written: %s", pk, sk, exc)
        return False


# ── the served comparison ────────────────────────────────────────────────────────────────


def _empty_record() -> dict:
    return {
        "graded": 0,
        "coach_right": 0,
        "scored": 0,
        "coach_right_on_scored": 0,
        "rule_right": 0,
        "coach_only": 0,
        "rule_only": 0,
        "unscorable": 0,
        "unscorable_reasons": {},
        "not_yet_scored": 0,
    }


def _record_verdict(rec: dict) -> tuple[str, float | None]:
    if rec["not_yet_scored"]:
        return "not_yet_scored", None
    if rec["scored"] == 0:
        return "none_scored", None
    if rec["scored"] < MIN_N_FOR_RATE:
        return "too_few", None
    p = stats_core.exact_sign_test_p(rec["coach_only"], rec["rule_only"])
    if p is not None and p < SIGNIFICANCE:
        return ("coaches_better" if rec["coach_only"] > rec["rule_only"] else "rule_better"), p
    return "no_clear_difference", p


def _verdict_words(rec: dict) -> str:
    v, cr, rr = rec["verdict"], rec["coach_right_on_scored"], rec["rule_right"]
    if v == "coaches_better":
        return "the coaches did better"
    if v == "rule_better":
        return "the guess did better"
    lead = "the guess was right more often" if rr > cr else "the coaches were right more often" if cr > rr else "level"
    if v == "too_few":
        return f"{lead}, on too few calls to tell" if lead != "level" else "level, on too few calls to tell"
    return f"{lead}, but not by a clear margin" if lead != "level" else "level"


def _record_sentence(key: str, rec: dict) -> str:
    words = RECORD_WORDS[key]
    if rec["scored"] == 0:
        return f"{words.capitalize()}: none of the {rec['graded']} could be checked against {RULE_WORDS}."
    s = (
        f"{words.capitalize()}: on the {rec['scored']} a guess could also be checked against, the coaches were right "
        f"{_times(rec['coach_right_on_scored'])} and {RULE_WORDS} {_times(rec['rule_right'])} — {_verdict_words(rec)}."
    )
    if rec["unscorable"]:
        s += f" {rec['unscorable']} more could not be checked against the guess."
    return s


def _times(n: int) -> str:
    return "once" if n == 1 else f"{n} times"


def skill_sentence(n: int, skill: float | None) -> str:
    """The engine's existing skill score in plain words, with its n (the pre-back-fill line)."""
    if n == 0:
        return "No checked call yet, so nothing to compare with a simple guess."
    calls = "checked call" if n == 1 else "checked calls"
    if n < MIN_N_FOR_RATE or skill is None:
        return f"Too few checked calls yet ({n}) to compare them with a simple guess."
    if skill > 0:
        return f"Across {n} {calls}, so far they beat a simple guess."
    return f"Across {n} {calls}, so far they do not beat a simple guess."


def comparison_block(decided: Iterable[dict]) -> dict:
    """The served comparison over a set of DECIDED rows (``coach_record.decided_rows``):
    four separate records, the engine's skill score, and the one plain-words sentence."""
    rows = [r for r in decided or [] if coach_record.graded_status(r)]
    records = {k: _empty_record() for k in RECORDS}
    unclassified = 0
    for row in rows:
        key = record_of(row)
        if key is None:
            unclassified += 1
            continue
        rec = records[key]
        coach_right = coach_record.graded_status(row) == "confirmed"
        rec["graded"] += 1
        rec["coach_right"] += coach_right
        bl = row.get("baseline")
        if not isinstance(bl, dict) or bl.get("rule") != RULE_ID:
            rec["not_yet_scored"] += 1
            continue
        if bl.get("right") is None:
            rec["unscorable"] += 1
            reason = str(bl.get("unscorable") or NO_RULE)
            rec["unscorable_reasons"][reason] = rec["unscorable_reasons"].get(reason, 0) + 1
            continue
        rule_right = bool(bl["right"])
        rec["scored"] += 1
        rec["coach_right_on_scored"] += coach_right
        rec["rule_right"] += rule_right
        rec["coach_only"] += coach_right and not rule_right
        rec["rule_only"] += rule_right and not coach_right
    for rec in records.values():
        rec["verdict"], p = _record_verdict(rec)
        rec["sign_test_p"] = round(p, 4) if p is not None else None
        big = rec["scored"] >= MIN_N_FOR_RATE
        rec["coach_right_pct"] = round(100 * rec["coach_right_on_scored"] / rec["scored"], 1) if big else None
        rec["rule_right_pct"] = round(100 * rec["rule_right"] / rec["scored"], 1) if big else None
    skill = calibration_core.score_pairs(calibration_core.pairs_from_prediction_records(rows))
    n = len(rows)
    skill_line = skill_sentence(n, skill.get("brier_skill"))
    pending = sum(r["not_yet_scored"] for r in records.values())
    complete = n > 0 and pending == 0
    rule_lines = [_record_sentence(k, records[k]) for k in RECORDS if records[k]["graded"]]
    return {
        "rule": RULE_ID,
        "rule_words": RULE_WORDS,
        "rule_version": RULE_VERSION,
        "records": records,
        "unclassified": unclassified,
        "scored_complete": complete,
        "skill": {"n": n, "brier_skill": skill.get("brier_skill"), "sentence": skill_line},
        "rule_sentence": " ".join(rule_lines) if complete else None,
        # The ONE line a page prints beside a coach count: the rule's records once every
        # graded call is scored, the engine's skill score until then.
        "sentence": " ".join(rule_lines) if complete else skill_line,
        "min_n_for_rate": MIN_N_FOR_RATE,
        "method": (
            "Each graded call is also scored by a rule that predicts nothing changes — the metric stays at its last "
            "reading before the day the call was filed — graded by the same grader against the same tolerance. "
            "Number calls, direction calls, yes/no bets and sealed day-one predictions are separate records and are "
            "never added together. 'Did better' is a two-sided exact sign test (p < 0.05) on the calls only one of the "
            "two got right; calls that share a metric and a window are not independent, so it is optimistic. No "
            f"percentage or verdict below {MIN_N_FOR_RATE} scored calls."
        ),
    }


def comparison_from_rows(rows: Iterable[Any], *, genesis: str | None) -> dict:
    """``comparison_block`` over a coach partition's rows — the record's own decided set."""
    return comparison_block(coach_record.decided_rows(rows, genesis=genesis))


def for_coach(table: Any, coach_id: str, *, genesis: str | None) -> tuple[dict | None, dict | None]:
    """``(record, comparison)`` for one coach from ONE read of its PREDICTION# partition —
    the record and the comparison counted over the same decided rows. ``(None, None)``
    when the read failed: absence, never a zero record and never a comparison of nothing."""
    record, decided = coach_record.for_coach_with_rows(table, coach_id, genesis=genesis)
    if record is None:
        return None, None
    return record, comparison_block(decided)
