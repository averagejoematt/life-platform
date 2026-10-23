"""#5199: the summary line survives an oversized result and names a missing leg explicitly."""

import json

from training.coach_context import CONTEXT_VERSION

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
        "coach_context": {"context_version": CONTEXT_VERSION, "charter_version": "1.18.0", "not_supplied": ["labs"], "text": "t" * 5000},
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
    assert d["coach_context"]["stamp"] == CONTEXT_VERSION
    assert "labs" in d["coach_context"]["not_supplied"]
    assert d["shadow"] == {"status": "recorded", "key": "SHADOW#1"}
    assert d["titration"]["action"] == "hold" and d["charter_version"] == "1.18.0"


def test_missing_legs_are_explicit_absent():
    d = _parse(summary_line({"job": "j", "outcome": "failed", "error": "Boom"}, None))
    assert all(k in d for k in KEYS)
    for k in ("critics", "coach_context", "shadow", "may_tracker", "calibration", "titration"):
        assert d[k] == {"state": "absent"}
    assert d["charter_version"] is None and d["error"] == "Boom"


# ── #5247: the line against the REAL producers' shapes ─────────────────────────────────────
def _real_result(monkeypatch):
    """coach_context from `plan_helpers.coach_context_brief` and may_tracker from `write_latest` itself."""
    from test_may_tracker_coach_context_5200 import TARGET, _row, _Table, _wire

    from mcp import config, core, tools_may_tracker as tmt

    r = _wire(monkeypatch, _Table([_row()]))
    brief = r.coach_context_brief(TARGET)
    wrote = []

    class _Sink:
        def put_item(self, **kw):
            wrote.append(kw)

    monkeypatch.setattr(config, "table", _Sink())
    monkeypatch.setattr(core, "table", _Sink())
    monkeypatch.setattr(tmt, "compute_weeks", lambda monday, weeks=1: [_row()])
    leg = tmt.write_latest(TARGET)
    return {**_full(), "coach_context": brief, "may_tracker": leg, "calibration": {"outcome": "checked", "deadman": ["tape", "photos"]}}


def test_line_matches_the_real_producers(monkeypatch):
    res = _real_result(monkeypatch)
    assert res["may_tracker"]["outcome"] == "written" and "state" not in res["may_tracker"] and res["may_tracker"]["status"]
    d = _parse(summary_line(res, "1.18.0"))
    cc = d["coach_context"]
    assert cc["stamp"] == res["coach_context"]["context_version"] == CONTEXT_VERSION
    assert cc["stamp"].count("coach-context@") == 1
    assert isinstance(cc["not_supplied"], list) and "constraint_block" in cc["not_supplied"]
    assert isinstance(d["calibration"]["deadman"], list) and d["calibration"]["deadman"] == ["tape", "photos"]
    assert d["may_tracker"]["state"] == res["may_tracker"]["status"] and d["may_tracker"]["state"] is not None


def test_tracker_state_falls_back_to_state_key():
    d = _parse(summary_line({"may_tracker": {"outcome": "written", "sk": "W", "state": "x"}}))
    assert d["may_tracker"]["state"] == "x"


def test_the_predraft_states_why_it_carries_no_constraint_block(monkeypatch):
    from mcp import plan_helpers as ph

    res = _real_result(monkeypatch)
    reason = res["coach_context"]["not_supplied_reason"]
    assert reason["constraint_block"] == ph.BLOCK_NOT_READ_PREDRAFT
    assert reason["plan_packet"] == ph.PACKET_NOT_READ_PREDRAFT
