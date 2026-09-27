"""tests/test_routine_endpoint.py — #1066: /api/routine fail-closed projection.

The cockpit's training-block lever reads this endpoint. The stored routine IR
(the Hevy write-loop's system of record) carries fields that must NEVER reach
the public surface — the title (force_title can carry user-authored free text),
notes (session cues + private notes), exercise names/loads/reps, rationale, and
inputs_snapshot (recovery/deficit internals). The projection is counts-only and
built field-by-field; these tests prove it, plus the selection rules (newest
on/before today, else nearest upcoming; floor/re_entry/archived never selected)
and the honest-empty / read-error shapes.

/api/session (E3, epic #4182 — owner ruling 2026-09-26 option (a)) lives in the same
module and is tested below the routine block: the served shape from a WIRE fixture (the
2026-09-27 nightly pre-draft as stored — movement keys, weight_kg, rep ranges), the
pick order (committed > role-matched draft > archetype-matched draft > only draft >
program), the program fallback, the absent states, and the privacy assertion that the
body carries EXACTLY the listed keys — the mutation "add `notes` to the serializer"
reds `test_session_body_carries_only_the_listed_keys`.

#4338: the two routes share ONE picker (`pick_todays_routine`) and both serve the pick's
`routine_ref`; the live 2026-09-27 two-draft state (an upper pre-draft stamped before the
#4312 Flex fix + an unstamped lower chat draft, sequence next = lower_volume) is the fixture
that proves they name the same routine.
"""

import json
import os
import sys
from datetime import datetime

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

from web import site_api_data as sad  # noqa: E402

# #2223: `datetime.now(sad.PT).strftime(...)` read ONCE at import time used to
# live here. site_api_protocols.routine() (lambdas/web/site_api_protocols.py:275)
# reads its own `datetime.now(PT)` again at CALL time — a plain module import,
# not `_g`-injected — so a CI run whose EXECUTION crosses Pacific midnight after
# this file's COLLECTION desynced the two ("assert -1 == 0" on days_out, CI run
# 31244919499). Fixed instant + freeze the handler's clock to match instead.
# Any date strictly between the past/future fixtures exercised below
# (2026-01-05 .. 2027-01-02) keeps the days_out sign assertions meaningful.
_TODAY = "2026-06-20"


class _FrozenDateTime(datetime):
    """datetime whose now() is pinned to _TODAY."""

    @classmethod
    def now(cls, tz=None):
        base = datetime.strptime(_TODAY, "%Y-%m-%d")
        return base.replace(tzinfo=tz) if tz else base


@pytest.fixture(autouse=True)
def _freeze_clock(monkeypatch):
    """Pin site_api_protocols's live clock to _TODAY so routine()'s own
    `datetime.now(PT)` agrees with this file's fixtures regardless of
    wall-clock time (#2223)."""
    monkeypatch.setattr(sad._protocols, "datetime", _FrozenDateTime)


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


# ═════════════════════════════════════════════════════════════════════════════
# /api/session — today's session as it will be lifted (E3, #4182)
# ═════════════════════════════════════════════════════════════════════════════

from training import session_sequence  # noqa: E402

_BLOCK_DAY = "2026-09-27"  # on/after program_structure.SESSION_SEQUENCE['block_start'] (2026-09-24)
_LIVE_HEVY_ID = "9764f978-0908-4547-a066-45deeba21749"


def _freeze(monkeypatch, day):
    """Pin the handler's clock to `day` (the autouse fixture pins _TODAY; the session
    tests need a day inside the v0.4 block)."""

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            base = datetime.strptime(day, "%Y-%m-%d")
            return base.replace(tzinfo=tz) if tz else base

    monkeypatch.setattr(sad._protocols, "datetime", _Frozen)


def _no_lifts(monkeypatch):
    """The Hevy record since the block start reads EMPTY → the sequence serves its first role."""
    monkeypatch.setattr(session_sequence, "load_block_workouts", lambda day: [])


def _set(kg, lo, hi):
    return {
        "weight_kg": kg,
        "custom_metric": None,
        "rep_range_start": lo,
        "rep_range_end": hi,
        "duration_seconds": None,
        "type": "normal",
        "distance_meters": None,
        "reps": None,
    }


# THE WIRE: routine ff7518cd… (VERSION#current) as stored on 2026-09-26 — the nightly
# pre-draft for 2026-09-27, stamped upper_heavy. Private fields carry markers.
_WIRE_DRAFT_IR = {
    "pk": "USER#matthew#ROUTINE#ff7518cdab4a1197f8e03e17d6458370",
    "sk": "VERSION#current",
    "routine_id": "ff7518cdab4a1197f8e03e17d6458370",
    "target_date": _BLOCK_DAY,
    "archetype": "upper",
    "variant": "ideal",
    "status": "draft",
    "title": "PRIVATE-FORCED-TITLE upper heavy",
    "notes": "PRIVATE-NOTE session cue",
    "rationale": ["PRIVATE-RATIONALE recovery amber"],
    "version": 3,
    "created_by": "cron",
    "source_action": "cron_generated",
    "hevy_routine_id": None,
    "hevy_pushed_at": None,
    "budget_used": {"upper_sets": 14},
    "inputs_snapshot": {
        "recovery_tier": "amber",
        "calendar": {"session_role": "upper_heavy", "label": "UPPER-HEAVY — week 1 · session 4 of 4, block 1"},
        "nightly_predraft": {"role": "primary", "session_role": "upper_heavy", "engine": "1.0.0"},
    },
    "exercises": [
        {
            "movement_key": "barbell_bench_press",
            "notes": "PRIVATE-EXERCISE-NOTE",
            "rest_seconds": 180,
            "sets": [_set(56, 4, 6), _set(50, 4, 6), _set(50, 4, 6)],
        },
        {"movement_key": "machine_row", "notes": None, "rest_seconds": 180, "sets": [_set(32, 4, 6), _set(28.5, 4, 6)]},
        {"movement_key": "machine_shoulder_press", "notes": None, "rest_seconds": 120, "sets": [_set(12.5, 6, 10)] * 3},
        {"movement_key": "lat_pulldown", "notes": None, "rest_seconds": 120, "sets": [_set(44, 6, 10)] * 2},
        {"movement_key": "cable_tricep_pushdown", "notes": None, "rest_seconds": 90, "sets": [_set(22, 8, 15)] * 2},
        {"movement_key": "db_curl", "notes": None, "rest_seconds": 90, "sets": [_set(7, 8, 15)] * 2},
    ],
    "branches": [],
}

_WIRE_DRAFT_INDEX = {
    "pk": "USER#matthew#SOURCE#routine_index",
    "sk": f"DATE#{_BLOCK_DAY}#ROUTINE#ff7518cdab4a1197f8e03e17d6458370",
    "routine_id": "ff7518cdab4a1197f8e03e17d6458370",
    "target_date": _BLOCK_DAY,
    "archetype": "upper",
    "variant": "ideal",
    "status": "draft",
    "hevy_routine_id": "",
}

_SESSION_KEYS = ("date", "state", "reason", "source", "kind", "session_role", "position_label", "routine_ref", "exercises", "as_of")
_EXERCISE_KEYS = ("name", "sets", "reps", "load_lbs", "loads_lbs")

_SESSION_PRIVATE_MARKERS = (
    "PRIVATE-FORCED-TITLE",
    "PRIVATE-NOTE",
    "PRIVATE-EXERCISE-NOTE",
    "PRIVATE-RATIONALE",
    "inputs_snapshot",
    "recovery_tier",
    "nightly_predraft",
    "budget_used",
    "hevy_routine_id",
    "hevy_pushed_at",
    _LIVE_HEVY_ID,
    "ff7518cdab4a1197f8e03e17d6458370",  # the routine id itself never leaves
    "weight_kg",
    "movement_key",
    "rest_seconds",
    "rpe",
)


def _draft_row(rid, archetype, role, target=_BLOCK_DAY, **ir_over):
    ir = dict(_WIRE_DRAFT_IR, routine_id=rid, pk=f"USER#matthew#ROUTINE#{rid}", archetype=archetype, target_date=target, **ir_over)
    ir["inputs_snapshot"] = dict(_WIRE_DRAFT_IR["inputs_snapshot"], calendar={"session_role": role} if role else {}, nightly_predraft={})
    idx = dict(_WIRE_DRAFT_INDEX, sk=f"DATE#{target}#ROUTINE#{rid}", routine_id=rid, archetype=archetype, target_date=target)
    return idx, ir


def _session_body(monkeypatch, rows, irs, day=_BLOCK_DAY, lifts=True):
    _freeze(monkeypatch, day)
    if lifts:
        _no_lifts(monkeypatch)
    monkeypatch.setattr(sad, "table", _FakeTable(rows, irs))
    resp = sad.handle_session()
    return resp, _body(resp)


def _public(body):
    return {k: v for k, v in body.items() if k != "_meta"}


def test_session_served_from_the_wire_draft(monkeypatch):
    """The 2026-09-27 pre-draft as stored → exactly what the page's loadRows reads:
    names from the catalog, sets, the rep range, the load in whole pounds."""
    resp, body = _session_body(monkeypatch, [_WIRE_DRAFT_INDEX], {_WIRE_DRAFT_IR["routine_id"]: _WIRE_DRAFT_IR})
    assert resp["statusCode"] == 200
    assert body["state"] == "served"
    assert body["source"] == "hevy-routine-draft"
    assert body["kind"] == "program"
    assert body["session_role"] == "upper_heavy"
    assert body["date"] == _BLOCK_DAY
    assert body["reason"] is None
    ex = body["exercises"]
    assert [e["name"] for e in ex] == [
        "Bench Press (Barbell)",
        "Seated Row (Machine)",
        "Seated Shoulder Press (Machine)",
        "Lat Pulldown (Cable)",
        "Triceps Pushdown",
        "Bicep Curl (Dumbbell)",
    ]
    bench = ex[0]
    assert bench["sets"] == 3
    assert bench["reps"] == "4–6"
    assert bench["load_lbs"] == 123  # 56 kg, the top set
    assert bench["loads_lbs"] == [123, 110, 110]  # top + two back-offs at −10 %
    assert ex[2] == {"name": "Seated Shoulder Press (Machine)", "sets": 3, "reps": "6–10", "load_lbs": 28, "loads_lbs": [28, 28, 28]}
    assert sum(e["sets"] for e in ex) == 14


def test_session_body_carries_only_the_listed_keys(monkeypatch):
    """THE privacy assertion (owner ruling option a): names + sets × reps + loads, and
    nothing else — exactly these keys, top-level and per exercise. Mutation control:
    add `"notes": ex.get("notes")` to `_exercise_row` in site_api_protocols.py and this
    fails on the exercise key set; add a top-level key to `_out` and it fails on the
    body key set. Private markers are ALSO swept so a leak through a value is caught."""
    _, body = _session_body(monkeypatch, [_WIRE_DRAFT_INDEX], {_WIRE_DRAFT_IR["routine_id"]: _WIRE_DRAFT_IR})
    assert tuple(sorted(_public(body))) == tuple(sorted(_SESSION_KEYS))
    assert body["exercises"], "the wire fixture must serve rows or this assertion is vacuous"
    for e in body["exercises"]:
        assert tuple(sorted(e)) == tuple(sorted(_EXERCISE_KEYS)), e
    raw = json.dumps(_public(body))
    for marker in _SESSION_PRIVATE_MARKERS:
        assert marker not in raw, f"private field/marker {marker!r} leaked to /api/session"
    # And the serializer's own declaration matches this test's — the two tuples are one contract.
    assert tuple(sad._protocols._SESSION_KEYS) == _SESSION_KEYS
    assert tuple(sad._protocols._EXERCISE_KEYS) == _EXERCISE_KEYS


def test_session_committed_routine_beats_a_draft_and_a_flex_is_a_complement(monkeypatch):
    """A routine pushed to Hevy for today is THE session (it is on his phone), whatever
    else is drafted; a Flex-folder routine is off-program — kind complement, no role."""
    d_idx, d_ir = _draft_row("d" * 32, "lower", "lower_heavy")
    c_idx, c_ir = _draft_row(
        "c" * 32, "flex", None, status="active", hevy_routine_id=_LIVE_HEVY_ID, hevy_pushed_at="2026-09-26T17:37:41+00:00"
    )
    c_ir["exercises"] = [
        {"movement_key": "tmpl:056a1c53-c778-4ace-bb18-6f72e81b6724", "sets": [{"type": "normal", "duration_seconds": 30}] * 3},
        {"movement_key": "tmpl:A2D838BD", "sets": [{"type": "normal", "reps": 10}] * 2},
    ]
    c_idx.update(status="active", hevy_routine_id=_LIVE_HEVY_ID)
    _, body = _session_body(monkeypatch, [d_idx, c_idx], {"d" * 32: d_ir, "c" * 32: c_ir})
    assert body["source"] == "hevy-routine"
    assert body["kind"] == "complement"
    assert body["session_role"] is None and body["position_label"] is None
    # tmpl:<id> keys resolve through the catalog's template-id hints (both id spellings)
    assert body["exercises"] == [
        {"name": "Suitcase Carry", "sets": 3, "reps": None, "load_lbs": None, "loads_lbs": None},
        {"name": "Cable Twist (Up to down)", "sets": 2, "reps": 10, "load_lbs": None, "loads_lbs": None},
    ]
    assert _LIVE_HEVY_ID not in json.dumps(_public(body))


def test_session_two_drafts_the_sequence_next_role_picks(monkeypatch):
    """Two ideal drafts for one day (the live 09-27 state: a cron upper_heavy + a chat lower):
    the one stamped with the sequence's NEXT role is the session. With no lifts since the
    block start the next role is the first role — lower_heavy — so the lower draft wins,
    and the position label comes from the ledger."""
    u_idx, u_ir = _draft_row("a" * 32, "upper", "upper_heavy")
    l_idx, l_ir = _draft_row("b" * 32, "lower", "lower_heavy")
    _, body = _session_body(monkeypatch, [u_idx, l_idx], {"a" * 32: u_ir, "b" * 32: l_ir})
    assert body["source"] == "hevy-routine-draft"
    assert body["session_role"] == "lower_heavy"
    assert body["position_label"] == "week 1 · session 1 of 4 · lower-heavy"
    # a chat draft with NO role stamp matches on archetype instead
    l_ir["inputs_snapshot"] = {"calendar": {}}
    _, body = _session_body(monkeypatch, [u_idx, l_idx], {"a" * 32: u_ir, "b" * 32: l_ir})
    assert body["source"] == "hevy-routine-draft"
    assert body["session_role"] is None  # unstamped: the role is not invented
    assert [e["name"] for e in body["exercises"]][0] == "Bench Press (Barbell)"  # the lower draft's (fixture) exercises


def test_session_two_drafts_neither_matching_serves_the_program(monkeypatch):
    """Two drafts, neither the next role nor its archetype → the program is the ONE answer to
    'what is next' (#4110); no draft is guessed."""
    a_idx, a_ir = _draft_row("a" * 32, "upper", "upper_heavy")
    b_idx, b_ir = _draft_row("b" * 32, "upper", "upper_volume")
    _, body = _session_body(monkeypatch, [a_idx, b_idx], {"a" * 32: a_ir, "b" * 32: b_ir})
    assert body["state"] == "served" and body["source"] == "program"
    assert body["session_role"] == "lower_heavy"


def test_session_falls_back_to_the_program_prescription(monkeypatch):
    """No routine for today → the program's prescription for the next undone session:
    names from the catalog, sets + the rep range from the exposure, loads honestly null
    (the program prescribes % of a top set, not pounds). Yesterday's draft is NOT today's."""
    y_idx, y_ir = _draft_row("y" * 32, "lower", "lower_heavy", target="2026-09-26")
    _, body = _session_body(monkeypatch, [y_idx], {"y" * 32: y_ir})
    assert body["state"] == "served"
    assert body["source"] == "program"
    assert body["kind"] == "program"
    assert body["session_role"] == "lower_heavy"
    assert body["position_label"] == "week 1 · session 1 of 4 · lower-heavy"
    ex = body["exercises"]
    assert ex[0]["name"] == "Squat (Barbell)"
    assert ex[0]["sets"] == 3 and ex[0]["reps"] == "4–6"  # 1 top set + 2 back-offs
    assert all(e["load_lbs"] is None and e["loads_lbs"] is None for e in ex)
    assert all(e["name"] for e in ex), ex
    assert tuple(sorted(_public(body))) == tuple(sorted(_SESSION_KEYS))
    for e in ex:
        assert tuple(sorted(e)) == tuple(sorted(_EXERCISE_KEYS))


def test_session_absent_before_the_block_start(monkeypatch):
    """The autouse clock (2026-06-20) is before the v0.4 block: nothing drafted, nothing
    prescribed → absent, with the reason, every key present, exercises empty."""
    monkeypatch.setattr(sad, "table", _FakeTable([], {}))
    _no_lifts(monkeypatch)
    body = _body(sad.handle_session())
    assert body["state"] == "absent"
    assert body["source"] is None and body["exercises"] == []
    assert "before the program's first session" in body["reason"]
    assert tuple(sorted(_public(body))) == tuple(sorted(_SESSION_KEYS))


def test_session_absent_when_the_hevy_record_cannot_be_read(monkeypatch):
    """A Hevy read that RAISES is handed to the sequence as None → `sequence_unreadable`,
    no role → absent by name, never session 1 by default (ADR-104)."""
    _freeze(monkeypatch, _BLOCK_DAY)

    def _boom(day):
        raise RuntimeError("ddb down")

    monkeypatch.setattr(session_sequence, "load_block_workouts", _boom)
    monkeypatch.setattr(sad, "table", _FakeTable([], {}))
    body = _body(sad.handle_session())
    assert body["state"] == "absent"
    assert "could not be read" in body["reason"]


def test_session_index_read_error_still_serves_the_program(monkeypatch):
    """The routine index down → the program still answers (its record is a different read)."""

    class _Boom:
        def query(self, **kwargs):
            raise RuntimeError("ddb down")

        def get_item(self, Key=None, **kwargs):
            raise RuntimeError("ddb down")

    _freeze(monkeypatch, _BLOCK_DAY)
    _no_lifts(monkeypatch)
    monkeypatch.setattr(sad, "table", _Boom())
    body = _body(sad.handle_session())
    assert body["state"] == "served" and body["source"] == "program"


def test_session_floor_and_archived_never_selected(monkeypatch):
    f_idx, f_ir = _draft_row("f" * 32, "upper", "upper_heavy", variant="floor")
    f_idx["variant"] = "floor"
    a_idx, a_ir = _draft_row("e" * 32, "upper", "upper_heavy", status="archived")
    a_idx["status"] = "archived"
    _, body = _session_body(monkeypatch, [f_idx, a_idx], {"f" * 32: f_ir, "e" * 32: a_ir})
    assert body["source"] == "program"


def test_session_cache_headers_like_routine(monkeypatch):
    resp, _ = _session_body(monkeypatch, [_WIRE_DRAFT_INDEX], {_WIRE_DRAFT_IR["routine_id"]: _WIRE_DRAFT_IR})
    assert resp["statusCode"] == 200
    assert "max-age=900" in resp["headers"]["Cache-Control"]


# ═════════════════════════════════════════════════════════════════════════════
# #4338 — /api/routine and /api/session name the SAME routine (one picker)
# ═════════════════════════════════════════════════════════════════════════════

_LIVE_LOWER_ID = "6b31012523dfd24bc27d1d10d474f822"

# THE WIRE: routine 6b310125… (VERSION#current) as stored 2026-09-26 17:03Z — a chat
# `draft_custom` for 2026-09-27, archetype lower, NO role stamp (read-only DDB, 2026-09-27).
_WIRE_LOWER_IR = {
    "pk": f"USER#matthew#ROUTINE#{_LIVE_LOWER_ID}",
    "sk": "VERSION#current",
    "routine_id": _LIVE_LOWER_ID,
    "target_date": _BLOCK_DAY,
    "archetype": "lower",
    "variant": "ideal",
    "status": "draft",
    "created_by": "chat",
    "source_action": "draft_custom",
    "hevy_routine_id": None,
    "hevy_pushed_at": None,
    "exercises": [
        {"movement_key": "deadlift_trap_bar", "sets": [_set(55.5, 8, 12)] * 2},
        {"movement_key": "squat_barbell", "sets": [_set(53.5, 8, 12)] * 3},
        {"movement_key": "leg_curl", "sets": [_set(24.5, 8, 15)] * 2},
        {"movement_key": "calf_raise_machine", "sets": [_set(87.5, 8, 15)] * 2},
        {"movement_key": "machine_crunch", "sets": [_set(None, 8, 15)] * 2},
        {"movement_key": "treadmill", "sets": [{"type": "normal", "duration_seconds": 600}]},
    ],
    "branches": [],
}
_WIRE_LOWER_INDEX = dict(_WIRE_DRAFT_INDEX, sk=f"DATE#{_BLOCK_DAY}#ROUTINE#{_LIVE_LOWER_ID}", routine_id=_LIVE_LOWER_ID, archetype="lower")

# get_coach_session_packet(2026-09-27).next_session after #4312 (the Flex no longer advances it).
_LIVE_NEXT = {"session_role": "lower_volume", "archetype": "lower", "position_label": "week 1 · session 4 of 4 · lower-volume"}


def _both_routes(monkeypatch, rows, irs, nxt=_LIVE_NEXT):
    _freeze(monkeypatch, _BLOCK_DAY)
    monkeypatch.setattr(sad._protocols, "_program_next", lambda day: (nxt, None))
    _mount(monkeypatch, rows, irs)
    return _body(sad.handle_routine()), _body(sad.handle_session())


def test_4338_live_two_drafts_both_routes_name_the_lower_draft(monkeypatch):
    """The live 2026-09-27 state: /api/routine served the UPPER pre-draft (newest index row)
    while /api/session served the LOWER draft (the sequence's next archetype). One picker →
    both name the lower draft, and both carry the same routine_ref. Mutation control: restore
    routine()'s own `next(r for r in rows if target_date <= today)` pick and this reds on the
    archetype (upper) and on the ref."""
    rows = [_WIRE_DRAFT_INDEX, _WIRE_LOWER_INDEX]  # the fake sorts newest-first: ff75… (upper) before 6b31…
    irs = {_WIRE_DRAFT_IR["routine_id"]: _WIRE_DRAFT_IR, _LIVE_LOWER_ID: _WIRE_LOWER_IR}
    rbody, sbody = _both_routes(monkeypatch, rows, irs)
    rt = rbody["routine"]
    assert rt["archetype"] == "lower", rt
    assert (rt["exercise_count"], rt["total_sets"], rt["days_out"]) == (6, 12, 0)
    assert sbody["source"] == "hevy-routine-draft"
    assert sum(e["sets"] for e in sbody["exercises"]) == rt["total_sets"]
    assert len(sbody["exercises"]) == rt["exercise_count"]
    assert sbody["exercises"][0]["name"] and "Trap" in sbody["exercises"][0]["name"]
    # THE agreement: one routine, one public handle, served by both routes
    ref = sad._protocols.routine_ref(_LIVE_LOWER_ID)
    assert rt["routine_ref"] == sbody["routine_ref"] == ref
    assert ref != sad._protocols.routine_ref(_WIRE_DRAFT_IR["routine_id"])
    # the handle is a digest — the platform routine id itself still never leaves either route
    for body in (rbody, sbody):
        assert _LIVE_LOWER_ID not in json.dumps(_public(body))


def test_4338_a_draft_the_picker_declines_is_never_named_by_routine(monkeypatch):
    """Two drafts, neither the sequence's next session → /api/session serves the program
    (routine_ref null); /api/routine must not name either declined draft — it falls back to the
    last prescription BEFORE today (yesterday's), never one of today's the session route passed over."""
    a_idx, a_ir = _draft_row("a" * 32, "upper", "upper_heavy")
    b_idx, b_ir = _draft_row("b" * 32, "upper", "upper_volume")
    y_idx, y_ir = _draft_row("y" * 32, "lower", "lower_heavy", target="2026-09-26")
    rbody, sbody = _both_routes(monkeypatch, [a_idx, b_idx, y_idx], {"a" * 32: a_ir, "b" * 32: b_ir, "y" * 32: y_ir})
    assert sbody["source"] == "program" and sbody["routine_ref"] is None
    rt = rbody["routine"]
    assert rt["target_date"] == "2026-09-26" and rt["days_out"] == -1
    assert rt["routine_ref"] == sad._protocols.routine_ref("y" * 32)


def test_4338_one_draft_needs_no_sequence_read(monkeypatch):
    """A single draft for today is the pick without consulting the sequence — /api/routine pays the
    Hevy read only when two drafts need it to decide."""
    _freeze(monkeypatch, _BLOCK_DAY)

    def _no_read(day):
        raise AssertionError("the sequence was read for a single draft")

    monkeypatch.setattr(sad._protocols, "_program_next", _no_read)
    _mount(monkeypatch, [_WIRE_LOWER_INDEX], {_LIVE_LOWER_ID: _WIRE_LOWER_IR})
    rt = _body(sad.handle_routine())["routine"]
    assert rt["archetype"] == "lower" and rt["routine_ref"] == sad._protocols.routine_ref(_LIVE_LOWER_ID)
