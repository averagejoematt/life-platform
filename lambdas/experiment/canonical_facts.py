"""
canonical_facts.py — the ONE authoritative cross-cutting daily-facts schema.

The "30-vs-86 recovery split" and the "140/170/190 protein" confusion happened
because multiple places each built their own dict of the day's key numbers from
the `computed_metrics` record — and they could (and did) read different fields,
units, or roundings. This module is the single definition of WHAT the canonical
facts are, their UNITS, and how they're extracted from a `computed_metrics`
record. Every consumer — the coach-grounding reader (ai_expert_analyzer), the
Coherence Sentinel's facts check — builds the dict the same way, so the value a
coach is grounded on is exactly the value the Sentinel checks against.

`computed_metrics` is produced by daily_metrics_compute_lambda.store_computed_metrics
(Phase-3: the single computer of these). The field names here MUST match what it
writes — `tests/test_canonical_facts.py` asserts that contract so a producer-side
rename can't silently break grounding.

Pure (no boto3) — bundled with the lambdas/ asset, not the layer.
"""

from __future__ import annotations

# Canonical numeric facts + their UNITS (documented once, authoritatively). The unit
# notes are the contract: HRV is milliseconds (never bpm); protein avg/target/floor
# are three DISTINCT numbers (intake is the avg, NOT the target or floor).
FIELD_UNITS = {
    "recovery_pct": "percent (0-100), Whoop recovery",
    "hrv_ms": "milliseconds — NEVER bpm",
    "rhr_bpm": "bpm, resting heart rate",
    "protein_g_avg": "grams — actual 7-day average INTAKE (not the target/floor)",
    "protein_g_target": "grams — target (not intake)",
    "protein_g_floor": "grams — floor (not intake)",
    "latest_weight": "pounds",
    "weekly_rate_lbs": "pounds per week (signed)",
    "weekly_rate_ci_low": "pounds per week — low end of the 80% CI on the rate (#535)",
    "weekly_rate_ci_high": "pounds per week — high end of the 80% CI on the rate (#535)",
}
NUMERIC_FIELDS = tuple(FIELD_UNITS)


def _num(v):
    """One rounding rule for every fact: float→1dp, or None."""
    try:
        return round(float(v), 1) if v is not None else None
    except (TypeError, ValueError):
        return None


def build_canonical_facts(record) -> dict:
    """Extract the one authoritative facts dict from a `computed_metrics` record.

    `record` is the DDB item (Decimals already cast to float by the caller, or
    castable). Returns every NUMERIC_FIELD (float-1dp or None) plus `as_of` (the
    record's date). This is the single extraction every consumer shares."""
    record = record or {}
    facts = {k: _num(record.get(k)) for k in NUMERIC_FIELDS}
    facts["as_of"] = record.get("date") or record.get("as_of")
    return facts
