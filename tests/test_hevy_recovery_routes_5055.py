"""#5055 — recovery strings route to what `draft` can actually do.

`draft` takes no exercise list and never reads Hevy's copy; keeping a deliberate departure
(an in-app edit, a load under its floor) is `draft_custom` + `departure_reason`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp"))

from utils import _DEFAULT_SUGGESTIONS  # noqa: E402


def _text(code):
    return " ".join(_DEFAULT_SUGGESTIONS[code])


def test_hevy_conflict_names_draft_custom_with_departure_reason():
    t = _text("HEVY_CONFLICT")
    assert "draft_custom" in t and "departure_reason" in t
    assert "draft from the current Hevy state" not in t


def test_field_fix_recoveries_offer_both_routes():
    for code in ("HEVY_PRECHECK_FAILED", "HEVY_BAD_REQUEST", "SUBTRACT_ONLY_VIOLATION", "UNRESOLVED_MOVEMENT"):
        t = _text(code)
        assert "draft_custom" in t and "departure_reason" in t, code


def test_unresolved_movement_names_template_id_for_stall_check():
    assert "template_id" in _text("UNRESOLVED_MOVEMENT")


def test_gate_suggestions_name_draft_custom():
    from hevy_prescription_gate import refusal_suggestions

    gate = {
        "verdict": "refuse",
        "audit": {
            "violations": [
                {"kind": "conditional_up", "where": "A", "clause": "if easy"},
                {"kind": "floor", "where": "B", "set": 1, "floor_kg": 50, "prescribed_kg": 40},
            ]
        },
    }
    out = refusal_suggestions(gate)
    assert sum("draft_custom + departure_reason" in s for s in out) == 2
