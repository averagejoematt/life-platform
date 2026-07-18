"""tests/test_numeric.py — Phase 4.2 shared numeric helpers."""

import os
import sys
from decimal import Decimal

from boto3.dynamodb.types import TypeSerializer

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

import numeric as n  # noqa: E402


def test_float_to_decimal():
    assert n.floats_to_decimal(3.14) == Decimal("3.14")


def test_dict_recursion():
    out = n.floats_to_decimal({"a": 1.5, "b": {"c": 2.5}})
    assert out["a"] == Decimal("1.5")
    assert out["b"]["c"] == Decimal("2.5")


def test_list_recursion():
    out = n.floats_to_decimal([1.0, [2.0, 3.0], {"x": 4.0}])
    assert out[0] == Decimal("1.0")
    assert out[1][0] == Decimal("2.0")
    assert out[2]["x"] == Decimal("4.0")


def test_bool_preserved():
    """Bool would coerce to 1/0 via Decimal — must preserve bool semantics."""
    assert n.floats_to_decimal(True) is True
    assert n.floats_to_decimal(False) is False
    assert n.floats_to_decimal({"flag": True})["flag"] is True


def test_int_unchanged():
    assert n.floats_to_decimal(42) == 42


def test_string_unchanged():
    assert n.floats_to_decimal("hello") == "hello"


# ── #1207: NaN/Inf → None guard (adopted from character_engine) ───────────────


def test_nan_inf_map_to_none():
    """NaN and +/-Inf must map to None — a non-finite float can never be written
    (boto3's TypeSerializer rejects Decimal('NaN')/Decimal('Infinity')). Before
    #1207 the canonical helper passed them through as Decimal('nan'), so this
    assertion fails against the pre-fix implementation."""
    out = n.floats_to_decimal({"x": float("nan"), "y": float("inf"), "z": float("-inf"), "ok": 1.5})
    assert out["x"] is None
    assert out["y"] is None
    assert out["z"] is None
    assert out["ok"] == Decimal("1.5")


def test_nan_inf_result_is_boto3_serializable():
    """The converted structure must survive boto3's TypeSerializer — the exact
    DDB write path that raised 'Infinity and NaN not supported' on the forks."""
    out = n.floats_to_decimal({"nan": float("nan"), "inf": float("inf"), "vals": [1.0, float("nan"), 2.5]})
    # Must NOT raise; None serializes to {"NULL": True}, finite Decimals to {"N": ...}.
    TypeSerializer().serialize(out)


def test_nan_inf_scalar_and_nested():
    """The guard applies at every recursion depth and for bare scalars."""
    assert n.floats_to_decimal(float("nan")) is None
    nested = n.floats_to_decimal({"a": {"b": [float("inf")]}})
    assert nested["a"]["b"][0] is None


# ── #1207: precision param subsumes the round(4)/round(6) local variants ───────


def test_precision_param_rounds():
    """precision rounds floats before conversion (character_engine round(4),
    coach round(6)); default None preserves the full str(float) repr."""
    assert n.floats_to_decimal(1.23456789, precision=4) == Decimal("1.2346")
    assert n.floats_to_decimal({"a": 1.23456789}, precision=6)["a"] == Decimal("1.234568")
    # Default (None) keeps existing-caller behavior byte-for-byte.
    assert n.floats_to_decimal(1.23456789) == Decimal(str(1.23456789))


def test_precision_still_guards_nan():
    """The NaN/Inf guard fires regardless of the precision argument."""
    assert n.floats_to_decimal(float("nan"), precision=4) is None
    assert n.floats_to_decimal(float("inf"), precision=6) is None


def test_precision_preserves_bool():
    assert n.floats_to_decimal(True, precision=4) is True


def test_decimals_to_float():
    assert n.decimals_to_float(Decimal("3.14")) == 3.14
    assert n.decimals_to_float({"a": Decimal("1.5")})["a"] == 1.5


def test_safe_float_default():
    assert n.safe_float(None) is None
    assert n.safe_float(None, default=0.0) == 0.0
    assert n.safe_float("not-a-number") is None
    assert n.safe_float("3.14") == 3.14
    assert n.safe_float(Decimal("2.5")) == 2.5


def test_shim_imports():
    """Every Lambda shim should re-export the canonical impl.

    NOTE: SIMP-2-migrated Lambdas removed from this list — the framework
    handles Decimal conversion internally; the shim is no longer needed there.
    Removed as migrated: todoist (v7.10), habitify (v7.11), withings (v7.12),
    strava (v7.12), eightsleep (v7.13), whoop (v7.13), garmin (v7.13)."""
    for module_name in ("macrofactor_lambda", "enrichment_lambda"):
        # Reset any prior import; we only need to confirm the symbol exists.
        sys.modules.pop(module_name, None)
        # We can't actually import these (they require boto3 + env), but we
        # can verify the file has the canonical-import marker.
        # P3.1: these handlers moved to lambdas/ingestion/
        path = os.path.join(ROOT, "lambdas", "ingestion", module_name + ".py")
        with open(path) as f:
            src = f.read()
        assert (
            "from numeric import floats_to_decimal" in src
        ), f"{module_name} missing the Phase 4.2 shim — should re-export from numeric module"
