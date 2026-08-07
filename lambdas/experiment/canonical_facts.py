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

from datetime import date as _date_cls, timedelta as _timedelta_cls

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

# ── #2113: which facts a PRIOR CYCLE's record may still speak for ─────────────
#
# `computed_metrics` is EXPERIMENT_SCOPED in phase_taxonomy (ADR-077) — it is
# exactly the class the reset tombstones. But every consumer here reads it with a
# bare newest-first `Limit: 1`, so in the hours after a genesis (before that day's
# daily-metrics-compute has run) the "latest" record is the PREVIOUS cycle's, and
# `authoritative_facts_block` renders it as "Latest Whoop recovery: 59%" under a
# hard rule telling the narrator to state that exact value.
#
# The split below is the honest one, and it is a SPLIT rather than a blanket wipe
# because the two halves are different kinds of number:
#   * OBSERVED — a measurement of a body on a specific day. A pre-genesis one is
#     not this cycle's reading at any age (the #2104 rule, one surface over).
#   * CONFIGURED — a target or floor from the profile. It is not an observation of
#     anything, does not belong to a cycle, and withholding it would make the coach
#     unable to say what the target even is. It travels.
#
# The union is asserted against NUMERIC_FIELDS by tests/test_genesis_week_coach_vitals_2113.py,
# so a field added to FIELD_UNITS later cannot silently escape classification —
# guard the SET, not the instance.
OBSERVED_FIELDS = (
    "recovery_pct",
    "hrv_ms",
    "rhr_bpm",
    "protein_g_avg",
    "latest_weight",
    "weekly_rate_lbs",
    "weekly_rate_ci_low",
    "weekly_rate_ci_high",
)
CONFIGURED_FIELDS = ("protein_g_target", "protein_g_floor")

# Keys in the returned dict that are NOT facts about a metric — provenance and cycle
# context for a renderer, never a value a narrative may cite. Consumers that feed the
# dict to a grounding detector or a number allow-list must strip these.
#
# This exists because `as_of` used to be the only one and `field_notes_lambda` filtered
# it by literal. #2113 added two more and the literal did not know — the extra keys
# reached `hard_canonical_contradictions` as if they were metric readings and the
# canary suite went from catching a planted wrong-RHR to missing it. A truth pass must
# never get quieter as a side effect of a change made elsewhere, so the set is declared
# here, next to the fields it shadows, and consumers import it rather than restate it.
# #1968: `night_of` joins them. The observed vitals here are WAKE-DATE-KEYED (#1923),
# so `as_of` is the MORNING they were recorded against and the night they describe is
# `as_of - 1`. Every narrative surface was handed the values with no way to name the
# night, which is how "credits a 7.5-hour sleep" and "duration at 6.58 hours" got
# published for the same night with no date on either. Carrying the night HERE rather
# than deriving it per-renderer does two things at once: the renderer can label the
# figure, and — because `allowed_numbers()` json.dumps this dict — the night's digits
# are automatically in every caller's allow-list, so instructing a narrative to cite
# the date cannot make the number gate flag it as fabricated. Meta, never a metric.
META_FIELDS = ("as_of", "night_of", "facts_are_pre_genesis", "cycle_genesis")

# The wake-date→night offset, mirroring web.site_api_common.NIGHT_OF_OFFSET_DAYS and
# ai.grounded_generation.NIGHT_OF_OFFSET_DAYS. tests/test_night_scoped_vitals_1968.py
# asserts all three agree so the frame cannot fork across the three bundles.
NIGHT_OF_OFFSET_DAYS = 1


def numeric_facts(facts: dict) -> dict:
    """`facts` with the META_FIELDS removed — the metric→value view a grounding
    detector or a number allow-list should see."""
    return {k: v for k, v in (facts or {}).items() if k not in META_FIELDS}


def observed_facts(record) -> dict:
    """The AS-MEASURED metric→value view. The cycle rule is deliberately NOT applied.

    Two different questions get asked of a `computed_metrics` record and only one of
    them is about cycles:

      * "May a narrative present this as the current reading?" — that is
        `build_canonical_facts`, and after a reset the answer for a pre-genesis
        record is no, so the values are withheld.
      * "Does this text CONTRADICT the record it was written from?" — that is this
        function, and the cycle is irrelevant to it. A note claiming 25% recovery
        against a record holding 55% is wrong no matter which cycle the record
        belongs to.

    Collapsing the two would have made the field-note contradiction detector go dark
    for the days after every reset — the withheld facts leave nothing to contradict.
    A truth pass must never get quieter as a side effect of a change made elsewhere
    (ADR-104/105), so the detector keeps its own view.
    """
    record = record or {}
    return {k: _num(record.get(k)) for k in NUMERIC_FIELDS}


try:  # fail-soft, matching intelligence/weight_recency: a partial bundle must not
    from common import constants as _constants  # break canonical-fact assembly.
except Exception:  # noqa: BLE001
    _constants = None


def _num(v):
    """One rounding rule for every fact: float→1dp, or None."""
    try:
        return round(float(v), 1) if v is not None else None
    except (TypeError, ValueError):
        return None


def _resolve_genesis(genesis):
    """The current cycle's genesis date, read at CALL time (#2113).

    The import above binds the constants MODULE, never the value, so a re-anchor
    (or a test's monkeypatch) is picked up without a reload — the import-time
    frozen-globals trap this repo has been bitten by before.
    """
    if genesis is not None:
        return str(genesis)
    try:
        return str(_constants.EXPERIMENT_START_DATE)
    except Exception:  # noqa: BLE001 — see the fail-soft contract above
        return None


def _night_of(as_of):
    """The night a wake-date-keyed reading came from: `as_of - 1` (#1923/#1968).

    None for a missing or unparseable date — a fact set publishes no night rather
    than a guessed one, the same contract `web.site_api_common.night_of_for` uses.
    """
    try:
        d = _date_cls.fromisoformat(str(as_of)[:10])
    except (TypeError, ValueError):
        return None
    return (d - _timedelta_cls(days=NIGHT_OF_OFFSET_DAYS)).isoformat()


def _record_date(record):
    """The day a `computed_metrics` record describes: its `date`/`as_of`, else its sk."""
    d = record.get("date") or record.get("as_of")
    if d:
        return str(d)
    sk = str(record.get("sk") or "")
    return sk[len("DATE#") :][:10] if sk.startswith("DATE#") else None


def build_canonical_facts(record, genesis=None) -> dict:
    """Extract the one authoritative facts dict from a `computed_metrics` record.

    `record` is the DDB item (Decimals already cast to float by the caller, or
    castable). Returns every NUMERIC_FIELD (float-1dp or None) plus `as_of` (the
    record's date). This is the single extraction every consumer shares.

    #2113 — A PRE-GENESIS RECORD DOES NOT SPEAK FOR THIS CYCLE. On cycle 12's
    genesis the sleep and training coaches published "a recovery score of 59% ...
    and HRV of 42 ms" and "Day one of this experiment ... Your Whoop recovery came
    in at 59%, HRV at 42 ms" while /api/vitals served 44% and 35 ms. Nothing was
    stale by any age rule and no per-surface guard fired: the numbers were simply
    the 08-02 (pilot-phase) record, read by an unbounded newest-first query hours
    before the genesis day's own record existed.

    So when the record predates ``genesis``, every OBSERVED field is withheld —
    set to None, not annotated. That is deliberate and it is what makes the rule
    STRUCTURAL rather than advisory: the value never enters the fact set, so
    ``grounded_generation.allowed_numbers`` never allows it and a narrative that
    cites it anyway is caught as a fabricated number by the existing regen-once
    harness. A prompt instruction alone could not guarantee that (ADR-104/105).

    CONFIGURED fields (targets/floors) are not observations and travel unchanged.

    ``genesis`` defaults to the live ``EXPERIMENT_START_DATE`` (resolved at call
    time) so no caller can forget to arm it; pass it explicitly to pin a cycle.
    """
    record = record or {}
    facts = {k: _num(record.get(k)) for k in NUMERIC_FIELDS}
    as_of = _record_date(record)
    facts["as_of"] = as_of
    facts["night_of"] = _night_of(as_of)
    genesis = _resolve_genesis(genesis)
    # Lexicographic compare is exact for ISO dates and needs no parsing.
    pre_genesis = bool(as_of and genesis and as_of < genesis)
    if pre_genesis:
        for k in OBSERVED_FIELDS:
            facts[k] = None
    # The two cycle facts travel so a renderer can name the boundary it is
    # enforcing without a second lookup.
    facts["facts_are_pre_genesis"] = pre_genesis
    facts["cycle_genesis"] = genesis
    return facts
