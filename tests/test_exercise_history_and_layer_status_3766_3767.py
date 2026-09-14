"""tests/test_exercise_history_and_layer_status_3766_3767.py — measured vs derived, told apart.

THE INCIDENT (2026-09-13)
  The coach was asked to program Leg Extension (Machine). The only exercise-level tool
  left in the registry read the DERIVED note-signal layer, which was dark; it answered
  `sessions_with_notes: 0, timeline: []` — a clean, confident zero — and the coach
  reported "no history" and prescribed no load. The raw partition held **twelve** logged
  sessions for that template since 2024-01-13, with working sets to 104 kg × 5.

  Two defects, one sentence apart:
    #3766  `get_exercise_history` was pruned in #884 on 30 days of telemetry from a BUILD
           period, while three live surfaces — including the description of the very tool
           that replaced it — still named it as a standard pre-flight pull.
    #3767  the notes tool reported a measured-looking zero over a layer that could not
           have produced anything, with the health signal that knew sitting one module
           away and read by nobody on a schedule.

  The owner's rule, verbatim: "empty should be indistinguishable from 'we couldn't look'
  only if it actually is."
"""

from __future__ import annotations

import os
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))

# mcp.config reads these at import (the same shape tests/test_mcp_list_available_tools.py uses).
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from mcp.core import LAYER_DARK, LAYER_DEGRADED, LAYER_OK, LAYER_UNKNOWN, derived_layer_status  # noqa: E402
from mcp.strength_helpers import extract_hevy_sessions  # noqa: E402

# One raw Hevy workout row in the live shape: sk carries #WORKOUT#, exercises at top.
_LEG_EXTENSION = {
    "sk": "DATE#2024-02-15#WORKOUT#abc",
    "date": "2024-02-15",
    "workout_name": "Legs",
    "exercises": [
        {
            "template_id": "75A4F6C4",
            "name": "Leg Extension (Machine)",
            "notes": "",
            "sets": [
                {"weight_kg": 104.3, "reps": 5, "set_type": "normal"},
                {"weight_kg": 95.2, "reps": 5, "set_type": "normal", "rpe": 8},
                {"weight_kg": 13.6, "reps": 10, "set_type": "warmup"},
            ],
        },
        {"template_id": "D04AC939", "name": "Squat (Barbell)", "notes": "felt strong", "sets": [{"weight_kg": 60, "reps": 5}]},
    ],
}


# ── #3766: the measured record is reachable, by id and by name ────────────────
def test_sessions_resolve_by_exact_template_id():
    """A template id is not a substring of any NAME — matching by name alone can never find it."""
    sessions = extract_hevy_sessions([_LEG_EXTENSION], "", template_id="75A4F6C4")
    assert len(sessions) == 1
    assert sessions[0]["exercise_name"] == "Leg Extension (Machine)"
    assert sessions[0]["template_id"] == "75A4F6C4"


def test_template_id_match_is_exact_not_fuzzy():
    """NEGATIVE CONTROL — a near-miss id must find nothing, never the wrong movement."""
    assert extract_hevy_sessions([_LEG_EXTENSION], "", template_id="75A4F6C5") == []


def test_a_name_still_matches_fuzzily():
    sessions = extract_hevy_sessions([_LEG_EXTENSION], "leg extension")
    assert len(sessions) == 1 and sessions[0]["template_id"] == "75A4F6C4"


def test_sets_carry_rpe_and_absent_rpe_stays_none():
    """ADR-104: most of the 2024 corpus predates RPE logging. Absent must not read as 0."""
    sets = extract_hevy_sessions([_LEG_EXTENSION], "", template_id="75A4F6C4")[0]["sets"]
    assert [s["rpe"] for s in sets] == [None, 8.0]  # warmup excluded by default
    assert all(s["weight_lbs"] > 0 for s in sets)


def test_the_exercise_note_travels_with_the_measured_sets():
    squat = extract_hevy_sessions([_LEG_EXTENSION], "squat")[0]
    assert squat["note_raw"] == "felt strong"
    assert extract_hevy_sessions([_LEG_EXTENSION], "", template_id="75A4F6C4")[0]["note_raw"] == ""


def test_warmups_are_excluded_by_default_and_included_on_request():
    assert extract_hevy_sessions([_LEG_EXTENSION], "", template_id="75A4F6C4")[0]["set_count"] == 2
    assert extract_hevy_sessions([_LEG_EXTENSION], "", template_id="75A4F6C4", include_warmups=True)[0]["set_count"] == 3


def test_the_tool_is_registered_and_wired():
    """#884 pruned it while three live surfaces still told the coach to call it."""
    from mcp.registry import TOOLS

    assert "get_exercise_history" in TOOLS, "the tool the coaching docs name as a pre-flight pull is not registered"
    assert callable(TOOLS["get_exercise_history"]["fn"])
    schema = TOOLS["get_exercise_history"]["schema"]["inputSchema"]["properties"]
    assert "template_id" in schema and "exercise_name" in schema
    assert schema.get("start_date", {}).get("description", "").find("all time") != -1, "a default lookback would re-create #3708"


def test_no_live_description_names_a_tool_the_prune_removed():
    """The regression that made the incident possible: a shipped description citing a ghost.

    `get_exercise_notes` told every caller that `get_exercise_history` was "a standard
    pre-flight pull" for eight weeks after #884 deleted it. The denominator here is the
    REMOVED set from the audit ledger rather than "any word shaped like a tool name" —
    an action verb inside a tool's own enum (`update_status`, `add_book`) is not a
    citation, and a guard that flags those would be turned off within a week.
    """
    import re

    from mcp.registry import TOOLS

    ledger = (REPO / "docs" / "MCP_TOOL_AUDIT.md").read_text()
    removed = set(re.findall(r"`((?:get|manage|log|list|save|update|find|search|create|delete|end|evaluate)_[a-z0-9_]{3,})`", ledger))
    removed -= set(TOOLS)  # anything later restored is not a ghost
    assert len(removed) > 20, f"the removal ledger parsed to only {len(removed)} names — the extractor has gone blind"

    offenders = []
    for tool, spec in TOOLS.items():
        blob = spec["schema"].get("description", "")
        for prop in (spec["schema"].get("inputSchema", {}).get("properties") or {}).values():
            blob += " " + str(prop.get("description", ""))
        for ghost in removed:
            if re.search(rf"\b{re.escape(ghost)}\b", blob):
                offenders.append(f"{tool} names `{ghost}`")
    assert not offenders, "live tool descriptions name tools that no longer exist: " + "; ".join(offenders)


# ── #3767: a derived layer states whether it could be read ────────────────────
def test_status_dark_when_the_producer_is_dark():
    status, reason = derived_layer_status({"checked": True, "extractor_dark": True, "noted_exercise_sessions": 15, "degraded": 15})
    assert status == LAYER_DARK
    assert "withheld" in reason


def test_status_unknown_when_the_health_check_itself_failed():
    status, reason = derived_layer_status({"checked": False, "error": "AccessDenied"})
    assert status == LAYER_UNKNOWN
    assert "AccessDenied" in reason


def test_status_unknown_when_there_is_no_health_signal_at_all():
    """A layer with no health function must not read as healthy by default."""
    assert derived_layer_status(None)[0] == LAYER_UNKNOWN
    assert derived_layer_status({})[0] == LAYER_UNKNOWN


def test_status_degraded_names_the_count():
    status, reason = derived_layer_status({"checked": True, "extractor_dark": False, "degraded": 3, "records_found": 10})
    assert status == LAYER_DEGRADED and "3 of 10" in reason


def test_status_ok_is_reachable():
    """NEGATIVE CONTROL — a contract that can only report trouble is not a contract."""
    status, reason = derived_layer_status({"checked": True, "extractor_dark": False, "degraded": 0, "records_found": 10})
    assert status == LAYER_OK and reason == ""


# ── The end-to-end shape of the tool that misled the coach ────────────────────
class _Table:
    def __init__(self, notes_rows, health):
        self._notes = notes_rows
        self._health = health

    def query(self, **kw):
        # The tool issues exactly one query once the template id is given directly
        # (the name-resolution query is skipped for an id-shaped argument).
        return {"Items": self._notes}


def _run(monkeypatch, notes_rows, health):
    import mcp.tools_training_notes as ttn

    monkeypatch.setattr(ttn, "table", _Table(notes_rows, health))
    monkeypatch.setattr("training.training_notes.training_notes_health", lambda *_a, **_k: health)
    return ttn.tool_get_exercise_notes({"template_id": "75A4F6C4", "lookback_days": 720})


def test_a_dark_layer_never_reports_a_measured_zero(monkeypatch):
    """THE regression. On 2026-09-13 this returned `sessions_with_notes: 0` while the
    same layer reported `extractor_dark: true, 15/15 degraded` in the same minute."""
    out = _run(
        monkeypatch, [], {"checked": True, "extractor_dark": True, "noted_exercise_sessions": 15, "degraded": 15, "lookback_days": 14}
    )

    assert out["layer_status"] == LAYER_DARK
    assert out["sessions_with_notes"] is None, "a dark layer reported a count — the exact shape that misled the coach"
    assert out["pain_flag_any"] is None, "a dark layer asserted the absence of pain flags"
    assert "timeline" not in out, "an empty timeline is a claim; a dark layer must not make it"
    assert "get_exercise_history" in out["measured_alternative"]


def test_a_healthy_empty_layer_still_reports_an_honest_zero(monkeypatch):
    """NEGATIVE CONTROL — 'he wrote no notes on this lift' is a real, reportable answer."""
    out = _run(monkeypatch, [], {"checked": True, "extractor_dark": False, "degraded": 0, "records_found": 5, "lookback_days": 14})

    assert out["layer_status"] == LAYER_OK
    assert out["sessions_with_notes"] == 0
    assert out["pain_flag_any"] is False
    assert out["timeline"] == []


def test_a_degraded_layer_returns_its_rows_and_says_so(monkeypatch):
    rows = [{"sk": "DATE#2026-09-09#WORKOUT#x", "date": "2026-09-09", "note_raw": "grip gave out", "signals": [], "degraded": True}]
    out = _run(monkeypatch, rows, {"checked": True, "extractor_dark": False, "degraded": 2, "records_found": 5, "lookback_days": 14})

    assert out["layer_status"] == LAYER_DEGRADED
    assert out["sessions_with_notes"] == 1
    assert "deterministic signals only" in out["layer_reason"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
