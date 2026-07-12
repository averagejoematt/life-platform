"""tests/test_routine_endpoint.py — #1066: /api/routine fail-closed projection.

The cockpit's training-block lever reads this endpoint. The stored routine IR
(the Hevy write-loop's system of record) carries fields that must NEVER reach
the public surface — the title (force_title can carry user-authored free text),
notes (session cues + private notes), exercise names/loads/reps, rationale, and
inputs_snapshot (recovery/deficit internals). The projection is counts-only and
built field-by-field; these tests prove it, plus the selection rules (newest
on/before today, else nearest upcoming; floor/re_entry/archived never selected)
and the honest-empty / read-error shapes.
"""

import json
import os
import sys
from datetime import datetime

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

from web import site_api_data as sad  # noqa: E402

_TODAY = datetime.now(sad.PT).strftime("%Y-%m-%d")

_PHASE_STATE = {
    "phases": ["Foundation", "Build", "Forge", "Sustain"],
    "current": "Foundation",
    "current_started": "2026-06-16",
    "reset_epoch_date": "2026-06-16",
}

# The full stored IR — includes every field that must NOT reach the public surface.
_STORED_IR = {
    "pk": "USER#matthew#ROUTINE#r-abc123",
    "sk": "VERSION#current",
    "routine_id": "r-abc123",
    "target_date": _TODAY,
    "archetype": "push",
    "variant": "ideal",
    "title": "PRIVATE-FORCED-TITLE do not leak",
    "notes": "PRIVATE-NOTE shoulder tweak, went easy",
    "status": "active",
    "version": 3,
    "exercises": [
        {
            "movement_key": "bench_press",
            "notes": "PRIVATE-EXERCISE-NOTE",
            "sets": [{"type": "normal", "weight_kg": 60.0, "reps": 8}] * 3,
        },
        {"movement_key": "tmpl:12345", "sets": [{"type": "normal", "weight_kg": 20.0, "reps": 12}] * 2},
    ],
    "branches": [],
    "rationale": ["PRIVATE-RATIONALE recovery=red deload"],
    "inputs_snapshot": {"recovery_tier": "red", "deficit_state": "deep"},
    "budget_used": {"push_sets": 11},
    "hevy_routine_id": "hevy-xyz",
    "hevy_pushed_at": "2026-07-10T04:00:00+00:00",
}

_INDEX_ROW = {
    "pk": "USER#matthew#SOURCE#routine_index",
    "sk": f"DATE#{_TODAY}#ROUTINE#r-abc123",
    "routine_id": "r-abc123",
    "target_date": _TODAY,
    "archetype": "push",
    "variant": "ideal",
    "status": "active",
    "hevy_routine_id": "hevy-xyz",
}

# Markers that must never appear anywhere in the serialized public body.
_PRIVATE_MARKERS = (
    "PRIVATE-FORCED-TITLE",
    "PRIVATE-NOTE",
    "PRIVATE-EXERCISE-NOTE",
    "PRIVATE-RATIONALE",
    "bench_press",  # exercise names stay private — counts only
    "weight_kg",
    "recovery_tier",
    "inputs_snapshot",
    "hevy_routine_id",
    "hevy-xyz",
)


class _FakeTable:
    def __init__(self, index_rows, ir_items):
        self._rows = index_rows
        self._irs = ir_items  # routine_id -> stored IR item

    def query(self, **kwargs):
        # Endpoint queries the index newest-first.
        return {"Items": sorted(self._rows, key=lambda r: r["sk"], reverse=True)}

    def get_item(self, Key=None, **kwargs):
        for rid, item in self._irs.items():
            if Key and Key.get("pk") == f"USER#matthew#ROUTINE#{rid}":
                return {"Item": item}
        return {}


def _body(resp):
    return json.loads(resp["body"]) if isinstance(resp.get("body"), str) else resp["body"]


def _mount(monkeypatch, index_rows, ir_items, phase_state=_PHASE_STATE):
    monkeypatch.setattr(sad, "table", _FakeTable(index_rows, ir_items))
    monkeypatch.setattr(sad, "_load_phase_state", lambda: phase_state)
    monkeypatch.setattr(sad, "pre_start_meta", lambda: None)


def test_projection_is_fail_closed(monkeypatch):
    _mount(monkeypatch, [_INDEX_ROW], {"r-abc123": _STORED_IR})
    body = _body(sad.handle_routine())
    assert body["available"] is True
    assert body["block"] == {"phase": "Foundation", "phase_started": "2026-06-16"}
    rt = body["routine"]
    assert rt["archetype"] == "push"
    assert rt["variant"] == "ideal"
    assert rt["target_date"] == _TODAY
    assert rt["days_out"] == 0
    assert rt["exercise_count"] == 2
    assert rt["total_sets"] == 5
    assert rt["pushed"] is True
    # Nothing private leaks — anywhere in the payload.
    raw = json.dumps({k: v for k, v in body.items() if k != "_meta"})
    for marker in _PRIVATE_MARKERS:
        assert marker not in raw, f"private field/marker {marker!r} leaked to /api/routine"


def test_recommended_branch_counts_win(monkeypatch):
    """#417 2b: the recommended branch's own exercise list is what Hevy actually
    shows — its counts win over the routine-level list."""
    ir = dict(
        _STORED_IR,
        branches=[
            {"label": "easier", "recommended": False, "exercises": [{"sets": [{}] * 2}]},
            {"label": "as-written", "recommended": True, "exercises": [{"sets": [{}] * 4}, {"sets": [{}] * 4}, {"sets": [{}] * 4}]},
        ],
    )
    _mount(monkeypatch, [_INDEX_ROW], {"r-abc123": ir})
    rt = _body(sad.handle_routine())["routine"]
    assert rt["exercise_count"] == 3
    assert rt["total_sets"] == 12


def test_floor_re_entry_and_archived_never_selected(monkeypatch):
    rows = [
        dict(_INDEX_ROW, sk=f"DATE#{_TODAY}#ROUTINE#r-floor", routine_id="r-floor", variant="floor"),
        dict(_INDEX_ROW, sk=f"DATE#{_TODAY}#ROUTINE#r-re", routine_id="r-re", variant="re_entry"),
        dict(_INDEX_ROW, sk=f"DATE#{_TODAY}#ROUTINE#r-arch", routine_id="r-arch", status="archived"),
    ]
    _mount(monkeypatch, rows, {})
    body = _body(sad.handle_routine())
    assert body["available"] is False
    assert body["routine"] is None
    # The block is still registry truth even with nothing prescribed.
    assert body["block"]["phase"] == "Foundation"


def test_prefers_newest_on_or_before_today_else_upcoming(monkeypatch):
    past = dict(_INDEX_ROW, sk="DATE#2026-01-05#ROUTINE#r-old", routine_id="r-old", target_date="2026-01-05", archetype="pull")
    older = dict(_INDEX_ROW, sk="DATE#2026-01-02#ROUTINE#r-older", routine_id="r-older", target_date="2026-01-02")
    ir_old = dict(_STORED_IR, routine_id="r-old", target_date="2026-01-05", archetype="pull")
    _mount(monkeypatch, [past, older], {"r-old": ir_old})
    rt = _body(sad.handle_routine())["routine"]
    assert rt["archetype"] == "pull"
    assert rt["days_out"] < 0

    # Only future prescriptions → the NEAREST upcoming one is chosen.
    up_near = dict(_INDEX_ROW, sk="DATE#2027-01-02#ROUTINE#r-n", routine_id="r-n", target_date="2027-01-02")
    up_far = dict(_INDEX_ROW, sk="DATE#2027-01-09#ROUTINE#r-f", routine_id="r-f", target_date="2027-01-09")
    ir_near = dict(_STORED_IR, routine_id="r-n", target_date="2027-01-02")
    _mount(monkeypatch, [up_near, up_far], {"r-n": ir_near})
    rt = _body(sad.handle_routine())["routine"]
    assert rt["target_date"] == "2027-01-02"
    assert rt["days_out"] > 0


def test_honest_empty_when_nothing_prescribed(monkeypatch):
    _mount(monkeypatch, [], {})
    body = _body(sad.handle_routine())
    assert body["available"] is False
    assert body["routine"] is None
    assert body["block"]["phase"] == "Foundation"


def test_ir_read_failure_degrades_to_index_truth(monkeypatch):
    """VERSION#current unreadable → the index row still names the prescription;
    counts are honest nulls, never fabricated zeros."""

    class _IndexOnly(_FakeTable):
        def get_item(self, Key=None, **kwargs):
            raise RuntimeError("ddb down")

    monkeypatch.setattr(sad, "table", _IndexOnly([_INDEX_ROW], {}))
    monkeypatch.setattr(sad, "_load_phase_state", lambda: _PHASE_STATE)
    monkeypatch.setattr(sad, "pre_start_meta", lambda: None)
    body = _body(sad.handle_routine())
    rt = body["routine"]
    assert body["available"] is True
    assert rt["archetype"] == "push"
    assert rt["exercise_count"] is None
    assert rt["total_sets"] is None
    assert rt["pushed"] is False


def test_index_read_error_is_shaped(monkeypatch):
    class _Boom:
        def query(self, **kwargs):
            raise RuntimeError("ddb down")

        def get_item(self, Key=None, **kwargs):
            raise RuntimeError("ddb down")

    monkeypatch.setattr(sad, "table", _Boom())
    monkeypatch.setattr(sad, "_load_phase_state", lambda: _PHASE_STATE)
    monkeypatch.setattr(sad, "pre_start_meta", lambda: None)
    body = _body(sad.handle_routine())
    assert body["available"] is False
    assert body["routine"] is None


def test_phase_config_missing_still_shaped(monkeypatch):
    _mount(monkeypatch, [_INDEX_ROW], {"r-abc123": _STORED_IR}, phase_state={})
    body = _body(sad.handle_routine())
    assert body["block"] is None
    assert body["available"] is True  # the prescription stands on its own


def test_pre_start_flag_carried(monkeypatch):
    _mount(monkeypatch, [_INDEX_ROW], {"r-abc123": _STORED_IR})
    monkeypatch.setattr(sad, "pre_start_meta", lambda: {"pre_start": True, "days_until_start": 1, "start_date": "2027-01-01"})
    body = _body(sad.handle_routine())
    assert body["pre_start"] is True
    assert body["days_until_start"] == 1


def test_cache_headers_present(monkeypatch):
    _mount(monkeypatch, [_INDEX_ROW], {"r-abc123": _STORED_IR})
    resp = sad.handle_routine()
    assert resp["statusCode"] == 200
    assert "max-age=900" in resp["headers"]["Cache-Control"]
