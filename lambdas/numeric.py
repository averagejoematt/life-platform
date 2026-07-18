"""
numeric.py — Phase 4.2 (2026-05-16): single source of truth for numeric
conversion between Python floats and DynamoDB Decimals.

Replaces the independent copies of `floats_to_decimal()` scattered across
ingestion + compute + coach + MCP Lambdas. Identical recursive shape,
divergent edge cases (NaN/Inf handling, rounding precision) — consolidating
eliminates the bug-fix-in-N-places risk.

Ships inside every function bundle (deploy/build_bundle.py, #781). Lambdas
that previously defined their own local helper import this instead:

    from numeric import floats_to_decimal

NaN/Inf handling (#1207): a non-finite float can NEVER be written to
DynamoDB — boto3's TypeSerializer raises "TypeError: Infinity and NaN not
supported" on a Decimal('NaN')/Decimal('Infinity'). The old local `_to_decimal`
copies disagreed: character_engine mapped NaN/Inf -> None while the plain
copies (and this module, pre-#1207) passed them through as Decimal('NaN'),
crashing the write. This module now adopts character_engine's proven
NaN/Inf -> None behavior for every caller.

The `precision` parameter subsumes the local variants that rounded before
converting (character_engine round(4), coach round(6)); default None keeps
the full str(float) representation for existing callers unchanged.

#1207 deleted every forked body (character_engine, hevy_common, compute/
scenario_explorer + forecast + hypothesis, intelligence/journal_analyzer +
challenge_generator, coach/* _float_to_decimal + _decimalize_dict,
mcp/tools_lifestyle, ingestion_framework, routine_ir, coach/voice_fidelity)
and repointed them here — some, e.g. compute/scenario_explorer, had been added
AFTER this module existed. The only remaining local `floats_to_decimal`
definitions are the `try: import / except ImportError: def` fallback shims in a
few ingestion Lambdas (dead under the one-bundle rule #781). Two genuinely
DIFFERENT helpers are intentionally NOT consolidated: the scalar coercers
(_scalar_to_decimal, _parse_decimal_field) and the int→Decimal /
key-stringifying / zero-fallback walkers (_dec, _deep_dec). See the D5 guard in
tests/test_ddb_patterns.py.
"""

from __future__ import annotations

import math
from decimal import Decimal


def floats_to_decimal(obj, precision=None):
    """Recursively convert floats to Decimal for DynamoDB compatibility.

    DynamoDB's boto3 layer rejects native Python floats. This helper walks
    a nested dict/list/scalar structure and converts every float to a
    Decimal (via str() to avoid float-binary repr surprises).

    NaN and +/-Inf map to None: boto3's TypeSerializer raises
    "TypeError: Infinity and NaN not supported" on Decimal('NaN'), so a
    non-finite float can never be persisted — None is the honest, writable
    sentinel (#1207, adopted from character_engine's battle-tested variant).

    precision: when set, floats are rounded to this many decimal places
    (round(value, precision)) before conversion. Default None preserves the
    full str(float) representation for existing callers.

    Bool is intentionally preserved (Decimal(True) would be 1, losing the
    bool semantics).
    """
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        if precision is not None:
            obj = round(obj, precision)
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: floats_to_decimal(v, precision) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [floats_to_decimal(v, precision) for v in obj]
    return obj


def decimals_to_float(obj):
    """Inverse: convert Decimals back to floats. Useful for JSON serialization
    of records read from DynamoDB."""
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: decimals_to_float(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [decimals_to_float(v) for v in obj]
    return obj


# #970 KEPT (deliberate): scalar-coercion contract (value, default), not digest_utils'
# record-field contract (rec, field, default) — different helper family.
def safe_float(value, default=None):
    """Coerce value to float, return default on None or unparseable input."""
    if value is None:
        return default
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
