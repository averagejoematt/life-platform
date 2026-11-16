"""tests/test_calibration_v2_privacy.py — calibration-v2 counts only publication-eligible calls (owner rulings 2026-11-03/05).

``assessment_v2`` on ``/api/calibration`` is computed over the same rows as every other public count of calls (call
publication method v2, ``common/prediction_publication.py``). Proof by the existing inference walks — tables that
differ ONLY in private rows — reading the v2 block itself:

  * ``tests/call_publication_route_walk.py``: private journal-derived coach calls, their learnings, corrections, voids
    and a private bet;
  * ``tests/journal_activity_route_walk.py --axis journal``: journal activity;
  * ``tests/journal_activity_route_walk.py --axis mind``: State of Mind check-ins, video-diary rows and a diary-day
    hypothesis with its graded calibration row.

Since the owner adopted v2 (2026-11-09) the same holds for the coach answers ``/api/coach_team`` carries in its huddle.
Every v2 output must be byte-identical across each walk's variants, and non-vacuous (calls are assessed). MUTATION
CONTROL: the call walk with ``--ungated`` (every call published) must MOVE the v2 block — so the equality is the
publication gate holding, not v2 ignoring its input. Every row is SYNTHETIC.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _walk(script: str, *args) -> dict:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tests" / script), *args],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _v2(out: dict):
    return json.loads(out["bodies"]["/api/calibration"])["body"].get("assessment_v2")


def _cal_body(out: dict) -> dict:
    return json.loads(out["bodies"]["/api/calibration"])["body"]


def _huddle_v2(out: dict) -> dict:
    """Owner ruling 2026-11-09: /api/coach_team carries each coach's calibration-v2 answers in its huddle."""
    body = json.loads(out["bodies"]["/api/coach_team"])["body"]
    return {h["persona_id"]: (h.get("calibration") or {}).get("assessment_v2") for h in body.get("huddle") or []}


CALL_NOW = "2026-11-07T20:00:00+00:00"
JOURNAL_NOW = "2026-11-03T20:00:00+00:00"


@pytest.fixture(scope="module")
def call_walks() -> dict:
    return {v: _walk("call_publication_route_walk.py", "--now", CALL_NOW, "--variant", v) for v in ("none", "many")}


@pytest.fixture(scope="module")
def call_ungated() -> dict:
    return {v: _walk("call_publication_route_walk.py", "--now", CALL_NOW, "--variant", v, "--ungated") for v in ("none", "some")}


@pytest.mark.parametrize("axis", ["journal", "mind"])
def test_journal_state_of_mind_and_diary_rows_cannot_move_v2(axis):
    runs = {
        v: _walk("journal_activity_route_walk.py", "--axis", axis, "--now", JOURNAL_NOW, "--variant", v) for v in ("none", "daily", "gaps")
    }
    blocks = {v: _v2(o) for v, o in runs.items()}
    assert blocks["none"] is not None and blocks["none"]["method_version"] == "calibration-v2"
    assert len({json.dumps(b, sort_keys=True) for b in blocks.values()}) == 1, axis
    huddles = {v: _huddle_v2(o) for v, o in runs.items()}
    assert len({json.dumps(h, sort_keys=True) for h in huddles.values()}) == 1, axis


def test_private_calls_cannot_move_v2(call_walks):
    none, many = _v2(call_walks["none"]), _v2(call_walks["many"])
    assert none is not None and none["method_version"] == "calibration-v2"
    assert json.dumps(none, sort_keys=True) == json.dumps(many, sort_keys=True)


def test_the_v2_walk_is_not_vacuous(call_walks):
    v2 = _v2(call_walks["none"])
    assert v2["strata"]["coaches"]["n"] > 0
    assert sum(c["n"] for c in v2["coaches"].values()) == v2["strata"]["coaches"]["n"]
    assert v2["scope"] == "season" and v2["status"] == "adopted" and v2["adopted"] == "2026-11-09"


def test_the_api_keeps_v1_fields_only_as_deprecated(call_walks):
    body = _cal_body(call_walks["none"])
    method = body["calibration_method"]
    assert method["status"] == "adopted" and method["authority"] == "assessment_v2"
    assert set(method["deprecated_fields"]["fields"]) == {"calibration", "label", "score"}
    # compatibility: the deprecated fields are still served where they always were
    assert all({"calibration", "label", "score"} <= set(c) for c in body["coaches"])
    assert {"calibration", "label"} <= set(body["platform"])


def test_private_calls_cannot_move_the_huddle_answers(call_walks):
    none, many = _huddle_v2(call_walks["none"]), _huddle_v2(call_walks["many"])
    assert any(v and v["n"] for v in none.values()), "non-vacuous: some coach is assessed in the huddle"
    assert json.dumps(none, sort_keys=True) == json.dumps(many, sort_keys=True)
    # the huddle carries the SAME answers /api/calibration serves for that coach
    v2 = _v2(call_walks["none"])
    for pid, ans in none.items():
        full = v2["coaches"].get(pid.removesuffix("_coach"))
        if ans and full:
            for q in ("estimability", "confidence_direction", "skill"):
                assert ans[q]["wording"] == full[q]["wording"], (pid, q)


def test_mutation_control_ungated_calls_move_v2(call_ungated):
    none, some = _v2(call_ungated["none"]), _v2(call_ungated["some"])
    assert json.dumps(none, sort_keys=True) != json.dumps(some, sort_keys=True)
    assert some["strata"]["coaches"]["n"] > none["strata"]["coaches"]["n"]
    assert json.dumps(_huddle_v2(call_ungated["none"]), sort_keys=True) != json.dumps(_huddle_v2(call_ungated["some"]), sort_keys=True)
