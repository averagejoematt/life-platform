"""compute_json_schemas.py — output schemas for the compute lambdas' JSON-shaped model calls (#4276).

Each schema goes to Bedrock as `output_config.format` through `ai.structured_json.call_json`,
which re-sends the request without it if Bedrock refuses the schema, and logs that it did.
They live here, not beside their prompts, because `hypothesis_engine_lambda.py` and
`daily_insight_compute_lambda.py` sit at their #1665 module-size ceilings (the
coach/coach_json_schemas.py precedent, #4494). What keeps a schema and its prompt in step is
the tests that send it (tests/test_hypothesis_engine_behavior.py,
tests/test_daily_insight_compute_behavior.py), not proximity.

Bedrock's rules (the #4464 live check): every object is closed (`additionalProperties: false`)
and every key is required; a value that may be absent is `anyOf [T, null]`.
"""

from __future__ import annotations

from typing import Any, Iterable

_S: dict[str, Any] = {"type": "string"}


def _obj(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def hypotheses_schema(spec_metrics: Iterable[str]) -> dict[str, Any]:
    """generate_hypotheses' JSON shape. The two metric slots are enums of the engine's
    SPEC_METRICS vocabulary (passed in — the vocabulary lives with the engine), so an
    out-of-vocabulary metric cannot be emitted; condition_threshold is nullable because
    median_split needs none."""
    metrics = sorted(spec_metrics)
    test_spec = _obj(
        {
            "condition_metric": {"type": "string", "enum": metrics},
            "condition_op": {"type": "string", "enum": [">=", "<=", "median_split"]},
            "condition_threshold": {"anyOf": [{"type": "number"}, {"type": "null"}]},
            "outcome_metric": {"type": "string", "enum": metrics},
            "direction": {"type": "string", "enum": ["higher", "lower"]},
            "min_effect": {"type": "number"},
            "lag_days": {"type": "integer"},
        }
    )
    hypothesis = _obj(
        {
            "hypothesis_id": _S,
            "hypothesis": _S,
            "domains": {"type": "array", "items": _S},
            "evidence": _S,
            "confirmation_criteria": _S,
            "test_spec": test_spec,
            "effect_size_observed": _S,
            "monitoring_window_days": {"type": "integer"},
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            "confidence_reason": _S,
            "actionable_if_confirmed": _S,
        }
    )
    return _obj({"hypotheses": {"type": "array", "items": hypothesis}})


_INTENTION_TYPES = [
    "sleep_timing",
    "food_logging",
    "protein_goal",
    "exercise",
    "walk",
    "meal_prep",
    "stress_management",
    "habit_completion",
    "hydration",
    "generic",
]

# IC-8's intention-evaluation shape. The prompt's array is wrapped in an object (a schema's
# root is an object); the caller still accepts a bare array from the schema-less fallback.
INTENTION_EVAL_SCHEMA: dict[str, Any] = _obj(
    {
        "evaluations": {
            "type": "array",
            "items": _obj(
                {
                    "type": {"type": "string", "enum": _INTENTION_TYPES},
                    "text": _S,
                    "executed": {"type": "boolean"},
                    "evidence": _S,
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                }
            ),
        }
    }
)
