"""#5199: the summary line survives an oversized result and names a missing leg explicitly."""

import json

from mcp.predraft_summary import SUMMARY_MARK, summary_line

KEYS = (
    "routine_id",
    "critics",
    "coach_context",
    "shadow",
    "may_tracker",
    "calibration",
    "titration",
    "fitness_battery",
    "charter_version",
)


def _parse(line):
    assert line.startswith(SUMMARY_MARK + " ")
    return json.loads(line[len(SUMMARY_MARK) + 1 :])


def _full():
    return {
        "job": "j",
        "outcome": "drafted",
        "routine_id": "r1",
        "routine_version": 2,
        "block_model": {"x": "y" * 100000},
        "critics": {"model_ran": True, "veto": None, "verdicts": [{"critic": "a", "verdict": "ok"}, {"critic": "b", "verdict": "ok"}]},
        "coach_context": {"context_version": "1", "charter_version": "1.18.0", "not_supplied": ["labs"], "text": "t" * 5000},
        "shadow": {"outcome": "recorded", "sk": "SHADOW#1"},
        "may_tracker": {"outcome": "written", "sk": "WEEK#1"},
        "calibration": {"outcome": "checked", "states": {"a": "ok"}, "deadman": []},
        "titration": {"outcome": "written", "week": "w", "action": "hold", "step_kcal": 0, "reason_code": "R"},
    }


def test_oversized_result_summary_carries_every_key():
    line = summary_line(_full(), "1.18.0")
    assert len(line) < 2100
    d = _parse(line)
    assert all(k in d for k in KEYS)
    assert d["routine_id"] == "r1" and d["critics"]["verdicts"] == {"ok": 2}
    assert d["coach_context"]["stamp"] == "coach-context@1"
    assert "labs" in d["coach_context"]["not_supplied"]
    assert d["shadow"] == {"status": "recorded", "key": "SHADOW#1"}
    assert d["titration"]["action"] == "hold" and d["charter_version"] == "1.18.0"


def test_missing_legs_are_explicit_absent():
    d = _parse(summary_line({"job": "j", "outcome": "failed", "error": "Boom"}, None))
    assert all(k in d for k in KEYS)
    for k in ("critics", "coach_context", "shadow", "may_tracker", "calibration", "titration"):
        assert d[k] == {"state": "absent"}
    assert d["charter_version"] is None and d["error"] == "Boom"
