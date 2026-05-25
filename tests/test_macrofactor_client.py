"""Unit tests for macrofactor_client — Firestore decoder + entry normalization.

No AWS, no MacroFactor calls. Synthetic Firestore payloads feed the decoder
and assert the produced shape matches the platform schema.

Tier 1 live-API tests are deliberately deferred — they need real credentials
and would fail if the unofficial endpoint changes. The parity diff (spec §3.8)
will be a separate one-shot script that compares Tier 1 vs Tier 2 output.
"""
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))


@pytest.fixture
def food_doc():
    """Synthetic Firestore food document for one day, mirroring real schema."""
    return {
        "name": "projects/sbs-diet-app/databases/(default)/documents/users/UID/food/2026-05-25",
        "fields": {
            "1716660000000000": {
                "mapValue": {"fields": {
                    "t":  {"stringValue": "Greek yogurt"},
                    "b":  {"stringValue": "Fage"},
                    "c":  {"stringValue": "120"},
                    "p":  {"stringValue": "18"},
                    "e":  {"stringValue": "9"},
                    "f":  {"stringValue": "0.5"},
                    "g":  {"stringValue": "170"},
                    "q":  {"stringValue": "1"},
                    "s":  {"stringValue": "container"},
                    "h":  {"stringValue": "8"},
                    "mi": {"stringValue": "30"},
                }}
            },
            "1716663600000000": {
                "mapValue": {"fields": {
                    "t":  {"stringValue": "Quaker Oatmeal"},
                    "c":  {"stringValue": "150"},
                    "p":  {"stringValue": "5"},
                    "h":  {"stringValue": "9"},
                    "mi": {"stringValue": "0"},
                    "deleted": {"booleanValue": True},  # soft-deleted
                }}
            },
        },
    }


def test_decode_value_string():
    from macrofactor_client import MacroFactorClient as MC
    assert MC._decode_value({"stringValue": "hello"}) == "hello"


def test_decode_value_integer():
    from macrofactor_client import MacroFactorClient as MC
    assert MC._decode_value({"integerValue": "42"}) == 42


def test_decode_value_double():
    from macrofactor_client import MacroFactorClient as MC
    assert MC._decode_value({"doubleValue": 3.14}) == 3.14


def test_decode_value_null():
    from macrofactor_client import MacroFactorClient as MC
    assert MC._decode_value({"nullValue": None}) is None


def test_decode_value_map():
    from macrofactor_client import MacroFactorClient as MC
    out = MC._decode_value({"mapValue": {"fields": {
        "a": {"stringValue": "x"},
        "b": {"integerValue": "5"},
    }}})
    assert out == {"a": "x", "b": 5}


def test_decode_value_array():
    from macrofactor_client import MacroFactorClient as MC
    out = MC._decode_value({"arrayValue": {"values": [
        {"stringValue": "x"}, {"stringValue": "y"},
    ]}})
    assert out == ["x", "y"]


def test_parse_document_empty():
    from macrofactor_client import MacroFactorClient as MC
    assert MC._parse_document({}) == {}
    assert MC._parse_document({"fields": {}}) == {}


def test_parse_document_full(food_doc):
    from macrofactor_client import MacroFactorClient as MC
    parsed = MC._parse_document(food_doc)
    assert "1716660000000000" in parsed
    assert "1716663600000000" in parsed
    assert parsed["1716660000000000"]["t"] == "Greek yogurt"
    assert parsed["1716660000000000"]["c"] == "120"  # still string per MF Android format


def test_normalize_food_entry_yogurt(food_doc):
    """Verify the field-code → platform-schema mapping."""
    from macrofactor_client import MacroFactorClient as MC, _normalize_food_entry
    parsed = MC._parse_document(food_doc)
    raw = parsed["1716660000000000"]
    entry = _normalize_food_entry("1716660000000000", raw, "2026-05-25")
    assert entry["food_name"] == "Greek yogurt"
    assert entry["brand"]     == "Fage"
    assert entry["calories"]  == 120.0
    assert entry["protein_g"] == 18.0
    assert entry["carbs_g"]   == 9.0
    assert entry["fat_g"]     == 0.5
    assert entry["grams"]     == 170.0
    assert entry["hour"]      == 8
    assert entry["minute"]    == 30
    assert entry["serving"]   == "container"
    assert "t" in entry["raw_fields"]


def test_normalize_food_entry_minimal_fields():
    """Entry with only title + calories — other macros should be None."""
    from macrofactor_client import _normalize_food_entry
    raw = {"t": "Bagel", "c": "300"}
    entry = _normalize_food_entry("xyz", raw, "2026-05-25")
    assert entry["food_name"] == "Bagel"
    assert entry["calories"] == 300.0
    assert entry["protein_g"] is None
    assert entry["fat_g"] is None


def test_normalize_food_entry_unnamed_fallback():
    """If no t or b field, food_name falls back to '(unnamed)'."""
    from macrofactor_client import _normalize_food_entry
    entry = _normalize_food_entry("abc", {"c": "50"}, "2026-05-25")
    assert entry["food_name"] == "(unnamed)"


def test_client_requires_credentials():
    from macrofactor_client import MacroFactorClient
    with pytest.raises(ValueError, match="email \\+ password"):
        MacroFactorClient("", "")
    with pytest.raises(ValueError):
        MacroFactorClient("email@example.com", "")


def test_client_uid_requires_signin():
    """Accessing .uid before sign_in raises an auth error."""
    from macrofactor_client import MacroFactorClient, MacroFactorAuthError
    c = MacroFactorClient("a@b.com", "pw")
    with pytest.raises(MacroFactorAuthError, match="not signed in"):
        _ = c.uid


def test_phase_pre_genesis():
    from macrofactor_puller_lambda import _phase_for_date
    assert _phase_for_date("2026-05-24") == "pilot"


def test_phase_post_genesis():
    from macrofactor_puller_lambda import _phase_for_date
    assert _phase_for_date("2026-05-25") == "experiment"
    assert _phase_for_date("2026-12-31") == "experiment"


def test_stable_entry_uid_is_deterministic():
    """Same date+entry_id+name should produce the same uid (for cross-tier dedupe)."""
    from macrofactor_puller_lambda import _stable_entry_uid
    a = _stable_entry_uid("2026-05-25", "1716660000000000", "Greek yogurt")
    b = _stable_entry_uid("2026-05-25", "1716660000000000", "Greek yogurt")
    c = _stable_entry_uid("2026-05-25", "1716660000000001", "Greek yogurt")
    assert a == b
    assert a != c
    assert a.startswith("mf:")
