"""
numeric.py — Phase 4.2 (2026-05-16): single source of truth for numeric
conversion between Python floats and DynamoDB Decimals.

Replaces 8 independent copies of `floats_to_decimal()` scattered across
ingestion + compute Lambdas. Identical recursive shape, occasionally
divergent edge cases — consolidating eliminates the bug-fix-in-N-places
risk.

Bundled into the shared layer via `deploy/build_layer.sh` MODULES list.
Lambdas that previously defined their own local helper can now do:

    from numeric import floats_to_decimal

The original local definitions are kept as backward-compat shims that
just re-export from this module, so callers don't need to change unless
they want the deduplication.
"""

from __future__ import annotations

from decimal import Decimal


def floats_to_decimal(obj):
    """Recursively convert floats to Decimal for DynamoDB compatibility.

    DynamoDB's boto3 layer rejects native Python floats. This helper walks
    a nested dict/list/scalar structure and converts every float to a
    Decimal (via str() to avoid float-binary repr surprises).

    Bool is intentionally preserved (Decimal(True) would be 1, losing the
    bool semantics).
    """
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: floats_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [floats_to_decimal(v) for v in obj]
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
