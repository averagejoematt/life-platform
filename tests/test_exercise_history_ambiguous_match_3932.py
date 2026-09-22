"""tests/test_exercise_history_ambiguous_match_3932.py — a fuzzy name is not one movement.

THE BUG (#3932)
  `tool_get_exercise_history`'s fuzzy `exercise_name` match is a case-insensitive
  substring match over `extract_hevy_sessions`. `exercise_name="bench press"` matched
  BOTH "Bench Press (Barbell)" and "Bench Press (Incline Dumbbell)" — two different Hevy
  `template_id`s, two different movements — and folded both sets of sessions into one
  series. The reported `total_1rm_gain: -114.5 lb` was last-incline-1RM minus
  first-barbell-1RM: a number that describes neither bar.

  Fixture note: the raw-hevy-item shape (`sk` carrying `#WORKOUT#`, `exercises` at the
  item's top level, per-set `weight_kg`) is copied from the LIVE shape already proven in
  `tests/test_exercise_history_and_layer_status_3766_3767.py`'s `_LEG_EXTENSION` fixture
  — never invented, never pulled from a live Hevy call.
"""

from __future__ import annotations

import os
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import mcp.tools_strength as ts  # noqa: E402

# Two distinct movements that both contain the substring "bench press". Barbell bench
# rises across the two sessions (155 -> 185 lbs); incline dumbbell is logged once, much
# lighter and later — the exact shape that produced the bogus merged "-114.5 lb" figure
# when folded into the barbell series.
_BARBELL_SESSION_1 = {
    "sk": "DATE#2025-01-05#WORKOUT#w1",
    "date": "2025-01-05",
    "workout_name": "Push",
    "exercises": [
        {
            "template_id": "AAA11111",
            "name": "Bench Press (Barbell)",
            "notes": "",
            "sets": [{"weight_kg": 70.3, "reps": 5, "set_type": "normal"}],  # ~155 lbs
        }
    ],
}
_BARBELL_SESSION_2 = {
    "sk": "DATE#2025-03-10#WORKOUT#w2",
    "date": "2025-03-10",
    "workout_name": "Push",
    "exercises": [
        {
            "template_id": "AAA11111",
            "name": "Bench Press (Barbell)",
            "notes": "",
            "sets": [{"weight_kg": 83.9, "reps": 5, "set_type": "normal"}],  # ~185 lbs
        }
    ],
}
_INCLINE_DB_SESSION = {
    "sk": "DATE#2025-02-01#WORKOUT#w3",
    "date": "2025-02-01",
    "workout_name": "Push",
    "exercises": [
        {
            "template_id": "BBB22222",
            "name": "Bench Press (Incline Dumbbell)",
            "notes": "",
            "sets": [{"weight_kg": 27.2, "reps": 8, "set_type": "normal"}],  # ~60 lbs/side
        }
    ],
}

_ITEMS = [_BARBELL_SESSION_1, _INCLINE_DB_SESSION, _BARBELL_SESSION_2]


def _run(monkeypatch, args, items=_ITEMS):
    # #4032: the read seam moved. `_read_hevy_all_phases` (#4030) used to call
    # `query_source_range("hevy", …, include_pilot=…)`; it now delegates to
    # `mcp.core.query_source_cross_phase`, the ONE place the taxonomy-derived
    # `include_pilot` and the tombstone exclusion live. This patch is the same
    # stand-in it always was — it replaces the read, not the phase decision — and
    # `tools_strength` no longer imports `query_source_range` at all.
    monkeypatch.setattr(ts, "query_source_cross_phase", lambda *_a, **_k: items)
    return ts.tool_get_exercise_history(args)


# ── the specimen from the issue ────────────────────────────────────────────────
def test_ambiguous_fuzzy_match_returns_candidates_not_a_merged_series(monkeypatch):
    out = _run(monkeypatch, {"exercise_name": "bench press"})

    assert out["ambiguous"] is True
    assert "summary" not in out, "an ambiguous match must never carry a top-level merged summary"
    assert "total_1rm_gain" not in out

    tids = {c["template_id"] for c in out["candidates"]}
    assert tids == {"AAA11111", "BBB22222"}
    assert len(out["results"]) == 2


def test_each_candidate_series_is_scoped_to_its_own_template_id(monkeypatch):
    out = _run(monkeypatch, {"exercise_name": "bench press"})
    by_tid = {r["template_id"]: r for r in out["results"]}

    barbell = by_tid["AAA11111"]
    assert barbell["exercise_name"] == "Bench Press (Barbell)"
    assert barbell["n_sessions"] == 2
    # 155 -> 185 lbs: a real gain on ONE bar, not the bogus cross-movement delta.
    assert barbell["summary"]["total_1rm_gain"] is not None
    assert barbell["summary"]["total_1rm_gain"] > 0

    incline = by_tid["BBB22222"]
    assert incline["exercise_name"] == "Bench Press (Incline Dumbbell)"
    assert incline["n_sessions"] == 1
    # A single-session series' first and last 1RM are the same reading: zero gain,
    # not the bogus cross-movement delta a merged series would have reported.
    assert incline["summary"]["total_1rm_gain"] == 0.0

    # The negative case this bug produced: no series anywhere mixes template_ids.
    for series in (barbell, incline):
        assert all(s["template_id"] == series["template_id"] for s in series["sessions"])


def test_an_unambiguous_fuzzy_match_still_returns_one_series(monkeypatch):
    """NEGATIVE CONTROL — a name that resolves to exactly one template_id is unaffected."""
    out = _run(monkeypatch, {"exercise_name": "incline dumbbell"}, items=[_INCLINE_DB_SESSION])

    assert "ambiguous" not in out
    assert out["template_id"] == "BBB22222"
    assert out["summary"]["total_sessions"] == 1


def test_an_explicit_template_id_bypasses_the_ambiguity_check(monkeypatch):
    """A caller who already knows the template_id never needs the candidate list —
    extract_hevy_sessions has already scoped to one movement before this branch runs."""
    out = _run(monkeypatch, {"template_id": "AAA11111"})

    assert "ambiguous" not in out
    assert out["template_id"] == "AAA11111"
    assert out["n_sessions"] == 2
    assert all(s["template_id"] == "AAA11111" for s in out["sessions"])


# ── the registered description names the scoping behavior (acceptance box 4) ──
def test_registered_description_states_per_template_scoping():
    from mcp.registry import TOOLS

    desc = TOOLS["get_exercise_history"]["schema"]["description"]
    assert "template_id" in desc
    assert "ambiguous" in desc or "never" in desc.lower()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
