"""
phase_filter.py — Default phase filter for the 2026-05-18 experiment restart.

Every read of platform DDB data passes through with_phase_filter() so that
phase=pilot records are hidden by default. Records without a phase attribute
(genome, profile, config, board, subscribers after untag) pass through.

Callers can pass include_pilot=True to bypass the filter for the rare
backward-looking case (e.g., historical research, audit, baseline diff).

Bundled into every function's deploy package (#781). Adds the filter to a boto3 Query/Scan
kwargs dict in-place-safe (returns a new dict if changes would be made,
otherwise returns the original).

v1.0.0 — 2026-05-23 (ADR-058)
"""

from constants import EXPERIMENT_PHASE_CURRENT

PHASE_FILTER_EXPRESSION = "(#phase = :phase_experiment OR attribute_not_exists(#phase))"
PHASE_FILTER_NAMES = {"#phase": "phase"}
PHASE_FILTER_VALUES = {":phase_experiment": EXPERIMENT_PHASE_CURRENT}


def singleton_visible(item) -> bool:
    """Item-level mirror of the query filter, for get_item reads (#946).

    Query paths hide wiped records via with_phase_filter, but get_item bypasses
    filters entirely — so every STATE#current-style singleton reader must apply
    this predicate, or a reset's tombstones keep serving the wiped cycle until
    the next writer run overwrites the record.

    Hidden when tombstone=true (the restart wipe, Interpretation B) or when a
    phase attribute exists and isn't the current experiment phase (identical
    semantics to PHASE_FILTER_EXPRESSION). Items with no phase attribute
    (config, profile, genome) pass through, matching the query filter.
    """
    if not item:
        return False
    if item.get("tombstone"):
        return False
    phase = item.get("phase")
    return phase is None or phase == EXPERIMENT_PHASE_CURRENT


def with_phase_filter(kwargs: dict, include_pilot: bool = False) -> dict:
    """Add phase filter to a boto3 Query/Scan kwargs dict.

    If include_pilot is True, returns kwargs unchanged. Otherwise merges
    the phase filter into FilterExpression / ExpressionAttributeNames /
    ExpressionAttributeValues, preserving any existing entries.
    """
    if include_pilot:
        return kwargs
    out = dict(kwargs)
    existing_filter = out.get("FilterExpression")
    if existing_filter:
        out["FilterExpression"] = f"({existing_filter}) AND {PHASE_FILTER_EXPRESSION}"
    else:
        out["FilterExpression"] = PHASE_FILTER_EXPRESSION
    names = dict(out.get("ExpressionAttributeNames") or {})
    names.update(PHASE_FILTER_NAMES)
    out["ExpressionAttributeNames"] = names
    values = dict(out.get("ExpressionAttributeValues") or {})
    values.update(PHASE_FILTER_VALUES)
    out["ExpressionAttributeValues"] = values
    return out
