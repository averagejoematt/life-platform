"""
chronicle_schema.py — the chronicle installment's guaranteed output shape (#1385
AC4, epic #1080).

Bedrock Structured Outputs (GA on Bedrock, same wire format as the direct API's
``output_config.format``) lets the model's output be constrained to a JSON schema
so the shape is schema-guaranteed rather than parse-and-pray. The chronicle's
installment envelope — title, the three stat-line numbers, and the markdown body —
is the fragile part today (a hand-rolled regex in ``parse_installment``); the
prose itself stays markdown, it just rides inside the ``body_markdown`` field so
the envelope can't come out malformed.

Structured-Outputs JSON-schema limits (per the claude-api reference): every object
needs ``additionalProperties: false`` + ``required``; string length / numeric-range
constraints are NOT supported, so the schema is types + required only.

The grounding gate (ADR-104) still runs on the serialized JSON text — every number
and date the model writes appears in that text exactly as in the markdown form, so
widening to structured output does not weaken the fabrication gate.
"""

# The response schema handed to Bedrock Structured Outputs (output_config.format).
INSTALLMENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        # Elena's editorial title for the week (the quoted first line today).
        "title": {"type": "string"},
        # The three numbers of the stat line: [Weight: X lbs | Week Grade: avg X | T0 Streak: X days]
        "weight_lbs": {"type": "number"},
        "week_grade": {"type": "number"},
        "t0_streak_days": {"type": "integer"},
        # The installment body — clean markdown prose (~1,200-1,800 words).
        "body_markdown": {"type": "string"},
    },
    "required": ["title", "weight_lbs", "week_grade", "t0_streak_days", "body_markdown"],
}

_TYPE_CHECKS = {
    "string": lambda v: isinstance(v, str),
    # bool is a subclass of int — exclude it so a stray True can't pass as a number.
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
}


def validate_installment(obj, schema: dict = INSTALLMENT_SCHEMA) -> list:
    """Deterministic ($0, no AI) validation of a structured installment object
    against `schema`. Returns a list of human-readable error strings — [] means the
    object satisfies the schema (all required keys present, correctly typed, and no
    extra keys when additionalProperties is false).

    This is the safety net that makes Structured Outputs load-bearing: even if a
    future model or a hand-built fallback produces the envelope, a malformed shape is
    caught here rather than silently mis-parsed downstream.
    """
    errors: list = []
    if not isinstance(obj, dict):
        return [f"expected object, got {type(obj).__name__}"]
    props = schema.get("properties", {})
    required = schema.get("required", [])
    for key in required:
        if key not in obj:
            errors.append(f"missing required field: {key!r}")
    for key, val in obj.items():
        if key not in props:
            if schema.get("additionalProperties") is False:
                errors.append(f"unexpected field: {key!r}")
            continue
        expected = props[key].get("type")
        check = _TYPE_CHECKS.get(expected)
        if check and not check(val):
            errors.append(f"field {key!r}: expected {expected}, got {type(val).__name__}")
    return errors


def parse_stats_line(stats_line: str) -> dict:
    """Extract the three stat numbers from the installment stat line
    ``[Weight: X lbs | Week Grade: avg X | T0 Streak: X days]``. Returns a dict with
    ``weight_lbs`` / ``week_grade`` / ``t0_streak_days`` (a key is absent — and thus
    fails the schema's `required` — when its number can't be found). This is the
    fragile parse; validating its output against INSTALLMENT_SCHEMA is what turns
    parse-and-pray into a caught error."""
    import re

    out: dict = {}
    text = stats_line or ""
    m = re.search(r"Weight:\s*([\d.]+)", text)
    if m:
        out["weight_lbs"] = float(m.group(1))
    m = re.search(r"Week Grade:\s*(?:avg\s*)?([\d.]+)", text)
    if m:
        out["week_grade"] = float(m.group(1))
    m = re.search(r"Streak:\s*(\d+)", text)
    if m:
        out["t0_streak_days"] = int(m.group(1))
    return out


def installment_from_stats(title: str, stats: dict, body_markdown: str) -> dict:
    """Assemble a schema-shaped installment dict from parsed pieces — the bridge for
    the fallback (non-structured) path so both paths produce the same validated
    envelope."""
    return {
        "title": title,
        "weight_lbs": stats.get("weight_lbs"),
        "week_grade": stats.get("week_grade"),
        "t0_streak_days": stats.get("t0_streak_days"),
        "body_markdown": body_markdown,
    }
