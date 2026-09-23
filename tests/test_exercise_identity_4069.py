"""tests/test_exercise_identity_4069.py — exercise identity is a template id, never a name substring.

THE ISSUE (#4069)
  `get_exercise_history` selected sets by a case-insensitive NAME substring, so "bench press"
  pulled "Bench Press (Barbell)" and "Incline Bench Press (Dumbbell)" into one '-120 lb' 1RM
  story, and `anchor_lift_strength_drop` (v0.3 redline) read that same path. #3932 already split
  an ambiguous NAME answer per template id; this closes the rest:

  - sets are selected and grouped by IDENTITY (`strength_helpers.exercise_identity`): the raw
    Hevy template id through the ONE confirmed alias registry (`config/hevy_template_aliases.json`,
    #3929 — no second table). A name is RESOLVED to identities first and the answer says which.
  - the anchor trend (`tools_plan._anchor_trend`) compares a lift only with its own identity — a
    variant switch starts a new series and can never read as a drop; a real same-variant drop
    still trips (mutation control).
  - the engine's tripwire input (`_worst_anchor`) reads the four CORE anchors only, as the redline
    says — a shoulder-press row is not one.

  Fixture shape: the live per-workout row (`sk` with `#WORKOUT#`, `exercises[]` at the top level
  with `template_id`/`name`/`notes`/`sets[]`, per-set `weight_kg` + `type`), read off
  `USER#matthew#SOURCE#hevy` on 2026-09-22. Template ids and titles are the LIVE ones:
  79D0BB3A Bench Press (Barbell), 07B38369 Incline Bench Press (Dumbbell), 878CD1D0 Shoulder
  Press (Dumbbell), 9237BAD1 Seated Shoulder Press (Machine), and the registry's own alias pair
  B5EFBF9C -> 21310F5F (Overhead / plain Triceps Extension (Cable)).
"""

from __future__ import annotations

import os
import pathlib
import sys
from unittest.mock import patch

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import mcp.tools_plan as tp  # noqa: E402
import mcp.tools_strength as ts  # noqa: E402
from mcp.strength_helpers import exercise_identity, extract_hevy_sessions, resolve_exercise_templates  # noqa: E402

LB = 1 / 2.2046226218


def _row(day: str, wid: str, exercises: list[dict]) -> dict:
    return {
        "pk": "USER#matthew#SOURCE#hevy",
        "sk": f"DATE#{day}#WORKOUT#{wid}",
        "date": day,
        "title": "Morning workout",
        "exercises": exercises,
    }


def _ex(tid: str, name: str, top_lbs: float, reps: int = 8) -> dict:
    return {
        "template_id": tid,
        "name": name,
        "notes": "",
        "sets": [
            {"type": "warmup", "weight_kg": round(top_lbs * 0.5 * LB, 3), "reps": 10},
            {"type": "normal", "weight_kg": round(top_lbs * LB, 3), "reps": reps},
        ],
    }


BARBELL = ("79D0BB3A", "Bench Press (Barbell)")
INCLINE_DB = ("07B38369", "Incline Bench Press (Dumbbell)")
DB_SP = ("878CD1D0", "Shoulder Press (Dumbbell)")
MACHINE_SP = ("9237BAD1", "Seated Shoulder Press (Machine)")
TRI_CANON = ("21310F5F", "Triceps Extension (Cable)")
TRI_ALIAS = ("B5EFBF9C", "Overhead Triceps Extension (Cable)")

# Barbell bench 185 -> 205 (a real gain); incline DB bench logged at 65-80 per hand in between.
_BENCH_ITEMS = [
    _row("2026-05-29", "a", [_ex(*BARBELL, 185), _ex(*INCLINE_DB, 80)]),
    _row("2026-09-07", "b", [_ex(*BARBELL, 185), _ex(*INCLINE_DB, 65)]),
    _row("2026-09-19", "c", [_ex(*BARBELL, 205), _ex(*INCLINE_DB, 80)]),
]


def _run(monkeypatch, args, items):
    monkeypatch.setattr(ts, "query_source_cross_phase", lambda *_a, **_k: items)
    return ts.tool_get_exercise_history(args)


# ── identity ──────────────────────────────────────────────────────────────────
def test_identity_is_the_template_id_through_the_alias_registry_never_the_name():
    amap = {"B5EFBF9C": "21310F5F"}
    assert exercise_identity("79d0bb3a", "Bench Press (Barbell)", amap) == "79D0BB3A"
    assert exercise_identity("B5EFBF9C", "anything at all", amap) == "21310F5F"
    # a shared substring is not a shared identity
    assert exercise_identity(*BARBELL, amap) != exercise_identity(*INCLINE_DB, amap)
    # an untagged title is its own bucket, never merged into a tagged one or another title
    assert exercise_identity("", "Bench Press (Barbell)") == "untagged:bench press (barbell)"
    assert exercise_identity("", "Bench Press") != exercise_identity("", "Bench Press (Barbell)")


def test_the_real_alias_registry_is_the_one_read():
    """The alias map is #3929's registry through adherence_calc — not a table of this PR's own."""
    amap, status = ts.template_alias_map()
    assert status["status"] == "read" and status["source"] == "config/hevy_template_aliases.json"
    assert amap.get("B5EFBF9C") == "21310F5F"


def test_a_name_resolves_to_template_ids_first():
    rows = resolve_exercise_templates(_BENCH_ITEMS, "bench press", {})
    assert {r["identity"] for r in rows} == {"79D0BB3A", "07B38369"}
    by = {r["identity"]: r for r in rows}
    assert by["79D0BB3A"]["titles"] == ["Bench Press (Barbell)"] and by["79D0BB3A"]["n_sessions"] == 3
    assert by["07B38369"]["titles"] == ["Incline Bench Press (Dumbbell)"]


# ── the specimen: barbell and incline-DB bench stay separate series ──────────
def test_barbell_and_incline_db_bench_are_separate_series(monkeypatch):
    out = _run(monkeypatch, {"exercise_name": "bench press"}, _BENCH_ITEMS)

    assert out["ambiguous"] is True and "summary" not in out
    resolved = {r["identity"] for r in out["searched"]["name_resolved_to"]}
    assert resolved == {"79D0BB3A", "07B38369"}, "the answer names which template ids the name matched"
    by = {r["identity"]: r for r in out["results"]}
    barbell, incline = by["79D0BB3A"], by["07B38369"]
    assert {s["template_id"] for s in barbell["sessions"]} == {"79D0BB3A"}
    assert {s["template_id"] for s in incline["sessions"]} == {"07B38369"}
    assert barbell["summary"]["best_weight_lbs"] == pytest.approx(205, abs=0.1)
    assert barbell["summary"]["total_1rm_gain"] > 0, "a merged series would have reported a fake loss"
    assert barbell["matched_templates"] == [
        {"identity": "79D0BB3A", "template_ids": ["79D0BB3A"], "titles": ["Bench Press (Barbell)"], "n_sessions": 3}
    ]


def test_barbell_bench_by_template_id_returns_no_incline_db_sets(monkeypatch):
    """The acceptance's live-proof shape, offline: pinning barbell bench carries no incline-DB set."""
    out = _run(monkeypatch, {"template_id": "79D0BB3A"}, _BENCH_ITEMS)
    assert "ambiguous" not in out
    assert out["n_sessions"] == 3
    assert all(s["template_id"] == "79D0BB3A" for s in out["sessions"])
    assert max(st["weight_lbs"] for s in out["sessions"] for st in s["sets"]) == pytest.approx(205, abs=0.1)
    assert out["searched"]["alias_registry"]["status"] == "read"


def test_a_confirmed_alias_pair_is_one_movement(monkeypatch):
    items = [
        _row("2026-09-07", "a", [_ex(*TRI_CANON, 40, reps=12)]),
        _row("2026-09-14", "b", [_ex(*TRI_ALIAS, 45, reps=12)]),
    ]
    out = _run(monkeypatch, {"template_id": "B5EFBF9C"}, items)
    assert out["n_sessions"] == 2 and out["identity"] == "21310F5F"
    assert out["matched_templates"][0]["template_ids"] == ["21310F5F", "B5EFBF9C"]
    # by name, the same pair is ONE candidate, not an ambiguous two
    out = _run(monkeypatch, {"exercise_name": "triceps extension"}, items)
    assert "ambiguous" not in out and out["n_sessions"] == 2


def test_the_substring_never_gates_a_set_directly():
    """Mutation control for the resolver: a set whose identity the name did not resolve to is never returned,
    and a name that resolves to nothing returns nothing — not the 'closest' sets."""
    assert extract_hevy_sessions(_BENCH_ITEMS, "shoulder press") == []
    sessions = extract_hevy_sessions(_BENCH_ITEMS, "incline bench")
    assert {s["identity"] for s in sessions} == {"07B38369"}


# ── the anchor trend: variant switch vs a real drop ──────────────────────────
def _sessions(tid_name, tops, start_day=1):
    return [
        {
            "date": f"2026-08-{start_day + i:02d}",
            "template_id": tid_name[0],
            "identity": tid_name[0],
            "exercise_name": tid_name[1],
            "best_weight": float(w),
        }
        for i, w in enumerate(tops)
    ]


def test_a_variant_switch_does_not_register_as_a_drop():
    """Machine shoulder press at 100 lb, then dumbbell at 45: the DB series is compared with itself."""
    mixed = _sessions(MACHINE_SP, [100, 100, 100]) + _sessions(DB_SP, [45, 45, 45], start_day=10)
    tr = tp._anchor_trend(mixed, "2026-08-20", 5.0)
    assert tr["identity"] == "878CD1D0"
    assert tr["excluded_other_identity_sessions"] == 3
    assert tr["drop_pct"] == 0.0 and tr["sessions_below"] == 0
    assert tr["trailing_best_lbs"] == 45.0


def test_a_real_same_variant_drop_still_trips():
    """MUTATION CONTROL: same identity, 75 -> 45 across the last two sessions — must read as a drop."""
    tr = tp._anchor_trend(_sessions(DB_SP, [75, 75, 75, 45, 45]), "2026-08-20", 5.0)
    assert tr["drop_pct"] == pytest.approx(40.0) and tr["sessions_below"] == 2
    assert "excluded_other_identity_sessions" not in tr


def test_the_variant_switch_through_the_tool_path(monkeypatch):
    """End to end over the wire shape: the draft's DB shoulder press reads only DB history."""
    items = [_row(f"2026-08-{d:02d}", f"m{d}", [_ex(*MACHINE_SP, 100)]) for d in (1, 3, 5)] + [
        _row(f"2026-09-{d:02d}", f"d{d}", [_ex(*DB_SP, 45)]) for d in (7, 11, 14)
    ]
    monkeypatch.setattr(ts, "query_source_cross_phase", lambda *_a, **_k: items)
    hist = ts.tool_get_exercise_history({"template_id": "878CD1D0", "start_date": "2026-03-01", "end_date": "2026-09-20"})
    tr = tp._anchor_trend(hist["sessions"], "2026-09-20", 5.0)
    assert hist["n_sessions"] == 3 and tr["drop_pct"] == 0.0


# ── the engine reads the four core anchors only ──────────────────────────────
def test_worst_anchor_reads_core_anchor_rows_only():
    evidence = {
        "exercises": [
            {"idx": 0, "label": "Shoulder Press (Dumbbell)", "drop_pct": 40.0, "sessions_below": 2},
            {"idx": 1, "label": "Bench Press (Barbell)", "drop_pct": 2.0, "sessions_below": 0, "anchor_family": "bench"},
        ]
    }
    assert tp._worst_anchor(evidence) == (2.0, 0)
    # mutation control: the same drop on a core-anchor row IS the worst
    evidence["exercises"][0]["anchor_family"] = "bench"
    assert tp._worst_anchor(evidence) == (40.0, 2)


def test_core_anchor_family_is_by_catalog_key_or_template_id_never_name():
    with patch("training.hevy_template_cache.peek_template_id", side_effect=lambda k: {"barbell_bench_press": "79D0BB3A"}.get(k)):
        ids = tp._core_anchor_identities()
    assert ids.get("79D0BB3A") == "bench"
    assert tp._core_anchor_family("barbell_bench_press", None, {}) == "bench"
    assert tp._core_anchor_family("tmpl:79D0BB3A", "79D0BB3A", ids) == "bench"
    # overhead press is an anchor, not a CORE anchor; the shoulder-press ids map to nothing
    assert tp._core_anchor_family("db_shoulder_press", "878CD1D0", ids) is None
    assert tp._core_anchor_family("machine_shoulder_press", "9237BAD1", ids) is None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
