"""prediction_reason.py — a graded call's reason, in reader words (#4220, epic #4182).

THE DEFECT
----------
``/api/predictions`` served each call's ``outcome_notes`` exactly as the grader wrote it:
a serialized JSON object (``prediction_grading.build_outcome_notes``). The scorecard printed
that object verbatim as the reason line, e.g. ``{"actual_value": null, "reason":
"Insufficient data to determine trend for 'blood_glucose_avg'", ..., "grading_open":
true}``. Even the unwrapped ``reason`` is the grader's working, not a sentence:
``hrv_7day_avg trend=up (slope=0.2341), predicted=up``.

THE RULE
--------
``reason_words(record)`` returns ``(reason, graded_on_data)``:

  * ``reason`` is written from the STRUCTURED fields — the evaluation spec's ``type`` /
    ``metric`` / ``condition`` / ``threshold`` and the notes' ``actual_value`` — when the
    call's shape is one this module knows (directional, point, no-data, retired
    qualitative) and its metric has reader words. Otherwise it is the grader's own
    ``reason`` string, unwrapped, never re-worded by guesswork. No ``reason`` in the
    notes → ``None``: a reason is never invented where the grader wrote none.
  * ``graded_on_data`` — True for a confirmed/refuted verdict, False for a call that came
    back with no verdict (inconclusive/expired), None while nothing has come back
    (pending, observational). Named apart from the row's existing ``gradeable`` (#3046:
    "has a deterministic grading path at all"), which answers a different question.

Pure: no I/O, no clock. The one judgement it borrows from the grader is flatness — the
directional noise band lives in ``coach_prediction_evaluator`` (``DIRECTIONAL_NOISE_THRESHOLD``),
so a flat verdict is read from the grader's own "metric flat" marker rather than from a
second copy of the band.
"""

from __future__ import annotations

import json
import re
from typing import Any

from experiment.measurable_metrics import AGG_SUFFIXES, base_metric

#: Reader words for every base key in ``experiment.measurable_metrics.METRIC_SOURCES``
#: (tests/test_coaches_api.py pins the two key-sets equal).
METRIC_WORDS = {
    "hrv": "heart-rate variability",
    "recovery_score": "morning recovery score",
    "resting_heart_rate": "resting heart rate",
    "sleep_duration_hours": "sleep time",
    "sleep_score": "sleep score",
    "deep_pct": "deep-sleep share",
    "rem_pct": "REM-sleep share",
    "weight_lbs": "weight",
    "total_calories_kcal": "calories eaten",
    "total_protein_g": "protein eaten",
    "steps": "daily steps",
    "blood_glucose_avg": "average blood glucose",
    "blood_glucose_std_dev": "blood-glucose swings",
    "body_fat_pct": "body-fat percentage",
}

_SUFFIX_WORDS = {"_7day_avg": "7-day average", "_14day_avg": "14-day average", "_30day_avg": "30-day average"}
_DIRECTIONS = {"up": "up", "down": "down"}
_NO_VERDICT = ("inconclusive", "expired")


def metric_words(metric: Any) -> str | None:
    """'hrv_7day_avg' -> 'heart-rate variability (7-day average)'; None when unknown."""
    key = str(metric or "").strip()
    if not key:
        return None
    base = base_metric(key)
    words = METRIC_WORDS.get(base)
    if words is None:
        return None
    for suffix in AGG_SUFFIXES:
        if key != base and key.endswith(suffix):
            return f"{words} ({_SUFFIX_WORDS[suffix]})"
    return words


def _notes(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
        except ValueError:
            return {"reason": text}
        return parsed if isinstance(parsed, dict) else {}
    return {"reason": text} if text else {}


#: A unit a reader expects beside the number (only where the metric carries one).
_UNITS = {"sleep_duration_hours": " hours", "weight_lbs": " lb", "total_calories_kcal": " kcal", "total_protein_g": " g"}

#: The grader's marker for a machine spec it graded as a direction (#813 rescue path).
_REROUTED = "[null-threshold machine spec re-routed to directional]"
_PREDICTED = re.compile(r"\bpredicted (up|down)\b")
#: #4541 — the count grader's reason (coach/prediction_count_grader.py): "counted sleep_duration_hours >= 7.5 on 3 of
#: 7 days 2026-09-06..2026-09-12 (claim: at least 5); ...". `actual_value` on such a row is a DAY COUNT.
_COUNTED = re.compile(
    r"^counted \S+ (?P<sym>>=|>|<=|<) (?P<thr>[\d.]+) on (?P<q>\d+) of (?P<n>\d+) days \S+ \(claim: (?P<bound>at least|at most) (?P<k>\d+)\)"
)
_SYM_WORDS = {">=": "at or above", ">": "above", "<=": "at or below", "<": "below"}


def _num(value: Any) -> str | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    text = f"{f:.1f}"
    return text[:-2] if text.endswith(".0") else text


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def graded_on_data(status: Any) -> bool | None:
    st = str(status or "").strip().lower()
    if st in ("confirmed", "refuted"):
        return True
    if st in _NO_VERDICT:
        return False
    return None


def reason_words(record: dict) -> tuple[str | None, bool | None]:
    """``(reason, graded_on_data)`` for one PREDICTION# record (see the module docstring)."""
    status = str(record.get("status") or "").strip().lower()
    flag = graded_on_data(status)
    notes = _notes(record.get("outcome_notes"))
    grader = str(notes.get("reason") or "").strip()
    if not grader:
        return None, flag  # ADR-104: no reason written -> none served

    spec = record.get("evaluation")
    ev: dict = spec if isinstance(spec, dict) else {}
    kind = str(ev.get("type") or "").strip().lower()
    rerouted = kind == "machine" and grader.startswith(_REROUTED)
    if rerouted:
        kind, grader = "directional", grader[len(_REROUTED) :].strip()
    words = metric_words(ev.get("metric"))
    actual = notes.get("actual_value")

    counted = _COUNTED.match(grader) if notes.get("graded_as") == "count" else None
    if counted and words and status in ("confirmed", "refuted"):
        unit = _UNITS.get(base_metric(str(ev.get("metric") or "")), "")
        bar = f"{_SYM_WORDS[counted.group('sym')]} {_num(counted.group('thr'))}{unit}"
        q, n, bound, k = counted.group("q"), counted.group("n"), counted.group("bound"), counted.group("k")
        return f"{_cap(words)} came in {bar} on {q} of {n} days — the call needed {bound} {k}", flag

    if status == "expired" and kind == "qualitative":
        return "retired ungraded — a call like this has no measurable test", flag
    if status in _NO_VERDICT and actual is None and words and kind in ("directional", "point"):
        return f"not gradable yet — not enough {words} data to read it", flag

    if words and status in ("confirmed", "refuted") and actual is not None:
        called = _DIRECTIONS.get(str(ev.get("condition") or "").strip().lower())
        if kind == "directional" and rerouted and not called:
            # A re-routed spec's condition is a comparison ('gt'), not a direction; the
            # called direction follows from the verdict and the observed slope.
            try:
                slope_up = float(actual) > 0
            except (TypeError, ValueError):
                slope_up = None
            if slope_up is not None and "metric flat" not in grader:
                called = ("up" if slope_up else "down") if status == "confirmed" else ("down" if slope_up else "up")
            elif "metric flat" in grader:
                # A flat verdict carries no slope sign to reason from; the grader's own
                # "predicted up|down" is the one place the called direction is written.
                m = _PREDICTED.search(grader)
                called = m.group(1) if m else None
        if kind == "directional" and called:
            if status == "refuted" and "metric flat" in grader:
                return f"{_cap(words)} held flat — the call was for it to go {called}", flag
            try:
                went = "up" if float(actual) > 0 else "down"
            except (TypeError, ValueError):
                went = None
            if went and status == "confirmed" and went == called:
                return f"{_cap(words)} went {went}, as called", flag
            if went and status == "refuted" and went != called:
                return f"{_cap(words)} went {went} — the call was for it to go {called}", flag
        if kind == "point":
            seen, want = _num(actual), _num(ev.get("threshold"))
            if seen and want:
                unit = _UNITS.get(base_metric(str(ev.get("metric") or "")), "")
                seen, want = f"{seen}{unit}", f"{want}{unit}"
                where = "within" if status == "confirmed" else "outside"
                return f"{_cap(words)} came in at {seen} against a call of {want} — {where} its usual day-to-day range", flag

    if status == "expired":
        return f"retired ungraded — {grader[:1].lower()}{grader[1:]}", flag
    if status == "inconclusive":
        return f"not gradable yet — {grader[:1].lower()}{grader[1:]}", flag
    return grader, flag
