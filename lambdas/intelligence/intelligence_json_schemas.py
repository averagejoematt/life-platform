"""intelligence_json_schemas.py — output schemas for intelligence_common's JSON-shaped model calls (#4276).

The schema goes to Bedrock as `output_config.format` through `ai.structured_json.call_json`,
which re-sends the request without it if Bedrock refuses the schema, and logs that it did.
It lives here, not beside its prompt, because `intelligence_common.py` sits at its #1665
module-size ceiling (the coach/coach_json_schemas.py precedent, #4494). What keeps it in step
with the prompt is tests/test_intelligence_common_behavior.py, which asserts it is sent.

Bedrock's rules (the #4464 live check): every object closed, every key required; a value the
prompt calls optional is `anyOf [T, null]`.
"""

from __future__ import annotations

from typing import Any

_S: dict[str, Any] = {"type": "string"}
_NULLABLE_S: dict[str, Any] = {"anyOf": [{"type": "string"}, {"type": "null"}]}


def _obj(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


# extract_thread_from_narrative's shape. Prediction identity and target dates are stamped in
# code (ADR-106), so the model is never asked for them; metric and timeframe are optional.
THREAD_SCHEMA: dict[str, Any] = _obj(
    {
        "position_summary": _S,
        "predictions": {
            "type": "array",
            "items": _obj(
                {
                    "text": _S,
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                    "metric": _NULLABLE_S,
                    "timeframe": _NULLABLE_S,
                }
            ),
        },
        "surprises": {"type": "array", "items": _S},
        "emotional_investment": {"type": "string", "enum": ["detached", "observing", "engaged", "invested", "concerned", "excited"]},
        "open_questions": {"type": "array", "items": _S},
    }
)
