"""coach_json_schemas.py — output schemas for the four coach callers that still hand-parsed (#4276).

`coach_quality_gate` moved to structured outputs in #4464. This module does the same for the
other four coach-pipeline JSON calls: the state updater's extraction, the orchestrator's
generation brief, the ensemble digest, and the history summarizer's compression and stance.
Each schema goes to Bedrock as `output_config.format` through `ai.structured_json.call_json`,
which re-sends the request without the schema if Bedrock refuses it and logs that it did.

The schemas live in one sibling module rather than beside each prompt because
`coach_history_summarizer.py` sits at its #1665 module-size ceiling. What keeps each schema
and its prompt in step is a test, not proximity: `tests/test_coach_state_updater.py` checks
that every field a prompt asks for is a property here.

Two rules that Bedrock sets (see the #4464 PR's live check):
  * every object is closed (`additionalProperties: false` is the only accepted form);
  * so a map with free keys cannot be expressed. Where a prompt asked for one, the schema asks
    for a list of pairs instead, and `pairs_to_map` turns it back into the dict the consumers
    read. The ensemble's `positions`/`sides` take that route. A free map that code can derive
    (`confidence_state` in the compression and the ensemble summaries) is left out of the schema
    and filled from the stored CONFIDENCE# records, which is what the fallbacks already did.

Every key is required, and a value that may be absent is `anyOf [T, null]`, so the model has to
say "none" explicitly instead of leaving a field out.
"""

from __future__ import annotations

from typing import Any

_S: dict = {"type": "string"}
_I: dict = {"type": "integer"}
_B: dict = {"type": "boolean"}
_N: dict = {"type": "number"}
_STRS: dict = {"type": "array", "items": _S}


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def _list_of(props: dict) -> dict:
    return {"type": "array", "items": _obj(props)}


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


def pairs_to_map(value: Any, key: str, val: str) -> dict:
    """[{key: k, val: v}, ...] -> {k: v}. A dict (the schema-less fallback's shape) passes through."""
    if isinstance(value, dict):
        return value
    out: dict = {}
    for item in value if isinstance(value, list) else []:
        if isinstance(item, dict) and item.get(key):
            out[str(item[key])] = item.get(val)
    return out


# ── coach_state_updater: EXTRACTION_SYSTEM_PROMPT (coach_extraction_prompt.py) ────────────────
_DIRECTION = _nullable({"type": "string", "enum": ["up", "down"]})
EXTRACTION_OUTPUT_SCHEMA = _obj(
    {
        "themes": _STRS,
        "structural_fingerprint": _obj(
            {
                "opening_type": {
                    "type": "string",
                    "enum": [
                        "lead_with_data",
                        "reference_open_thread",
                        "callback_to_prediction",
                        "cross_coach_response",
                        "lead_with_environment_variable",
                        "lead_with_correction",
                        "lead_with_observation",
                        "other",
                    ],
                },
                "paragraph_count": _I,
                "uses_analogy": _B,
                "analogy_domain": _nullable(_S),
            }
        ),
        "threads_opened": _list_of(
            {
                "thread_slug": _S,
                "type": {"type": "string", "enum": ["observation", "prediction", "concern", "recommendation_pending"]},
                "summary": _S,
                "tags": _STRS,
            }
        ),
        "threads_referenced": _list_of({"topic": _S, "context": _S}),
        "predictions_made": _list_of(
            {
                "claim_natural": _S,
                "metric_hint": _nullable(_S),
                "direction": _DIRECTION,
                "timeframe_hint": _nullable(_S),
                "confidence_stated": _nullable(_S),
            }
        ),
        "commitments_made": _list_of(
            {
                "commitment_natural": _S,
                "action_check": _nullable(_S),
                "direction": _DIRECTION,
                "timeframe_hint": _nullable(_S),
                "public_ask": _S,
            }
        ),
        "decision_classes_used": {"type": "array", "items": {"type": "string", "enum": ["observational", "directional", "interventional"]}},
        "anti_pattern_violations": _STRS,
        "observatory_summary": _S,
        "key_recommendation": _S,
        "elena_quote": _nullable(_S),
        "public_summary": _S,
        "public_ask": _nullable(_S),
    }
)

# ── coach_derived_prose.RECONDENSE_SYSTEM_PROMPT (the state updater's corrective regen) ────────
RECONDENSE_OUTPUT_SCHEMA = _obj(
    {
        "observatory_summary": _nullable(_S),
        "key_recommendation": _nullable(_S),
        "elena_quote": _nullable(_S),
        "public_summary": _nullable(_S),
        "public_ask": _nullable(_S),
    }
)

# ── coach_narrative_orchestrator: the generation brief (keys named in _build_user_message) ────
# The item shapes are the ones the live briefs carry (BRIEF#2026-09-30, read 2026-09-30).
# `computation_outputs` had free keys (`trends_relevant: {metric: note}`); it is a list of
# {metric, note} now. Nothing reads its inside as structure: the brief is prompt context.
BRIEF_OUTPUT_SCHEMA = _obj(
    {
        "coach_id": _S,
        "generation_brief": _obj(
            {
                "open_threads": _list_of({"id": _S, "summary": _S, "priority": _S, "action": _S}),
                "cross_coach_context": _list_of({"coach": _S, "position": _S, "your_position": _S, "action": _S, "influence_weight": _N}),
                "predictions_to_address": _list_of({"id": _S, "claim": _S, "status": _S, "decision_class": _S, "action": _S}),
                "narrative_beat": _S,
                "journey_phase": _S,
                "periodization_note": _S,
                "voice_guidance": _obj({"avoid_openings": _STRS, "suggested_opening": _S, "structural_note": _S}),
                "decision_class_ceiling": {"type": "string", "enum": ["observational", "directional", "interventional"]},
                "evidence_note": _S,
                "seasonal_flags": _STRS,
                "computation_outputs": _obj({"trends": _list_of({"metric": _S, "note": _S}), "warnings": _STRS}),
            }
        ),
    }
)

# ── coach_ensemble_digest: ENSEMBLE_SYSTEM_PROMPT ───────────────────────────────────────────
ENSEMBLE_OUTPUT_SCHEMA = _obj(
    {
        "coach_summaries": _list_of(
            {
                "coach_id": _S,
                "key_concerns": _STRS,
                "key_recommendations": _STRS,
                "predictions_active": _STRS,
                "wants_team_input_on": _STRS,
            }
        ),
        "active_disagreements": _list_of(
            {
                "topic": _S,
                "coaches": _STRS,
                "positions": _list_of({"coach_id": _S, "position": _S}),
                "status": _S,
                "data_needed_to_resolve": _S,
                "resolution_criterion": _nullable(
                    _obj(
                        {
                            "metric": _S,
                            "condition": {"type": "string", "enum": ["gt", "gte", "lt", "lte"]},
                            "threshold": _N,
                            "resolution_days": _I,
                            "sides": _list_of({"coach_id": _S, "holds": _B}),
                        }
                    )
                ),
            }
        ),
        "unanimous_flags": _STRS,
    }
)


def ensemble_to_dicts(digest: Any) -> Any:
    """Turn the schema's pair lists back into the `positions`/`sides` dicts the digest's readers use."""
    if not isinstance(digest, dict):
        return digest
    for d in digest.get("active_disagreements") or []:
        if not isinstance(d, dict):
            continue
        d["positions"] = pairs_to_map(d.get("positions"), "coach_id", "position")
        rc = d.get("resolution_criterion")
        if isinstance(rc, dict):
            rc["sides"] = pairs_to_map(rc.get("sides"), "coach_id", "holds")
    return digest


# ── coach_history_summarizer: COMPRESSION_SYSTEM_PROMPT and STANCE_SYSTEM_PROMPT ─────────────
# `confidence_state` (a free map) and `compressed_at` (overwritten by _finalize_compressed) are
# not asked of the model; _finalize_compressed derives the first from the CONFIDENCE# records.
COMPRESSION_OUTPUT_SCHEMA = _obj(
    {
        "coach_id": _S,
        "display_name": _S,
        "domain": _S,
        "summary": _S,
        "key_concerns": _STRS,
        "key_recommendations": _STRS,
        "active_threads": _list_of({"id": _S, "summary": _S}),
        "active_predictions": _list_of(
            {"id": _S, "claim": _S, "status": {"type": "string", "enum": ["pending", "confirming", "confirmed"]}}
        ),
        "recent_themes": _STRS,
        "positions_taken": _STRS,
        "corrections_made": _STRS,
        "relationship_notes": _S,
        "last_output_date": _S,
    }
)

STANCE_OUTPUT_SCHEMA = _obj(
    {
        "headline_read": _S,
        "focused_on_now": _STRS,
        "set_aside_for_now": _STRS,
        "stage": _obj({"label": _S, "rationale": _S}),
        "how_my_read_changed": _S,
        "confidence_note": _S,
        "evidence_basis": _STRS,
    }
)
