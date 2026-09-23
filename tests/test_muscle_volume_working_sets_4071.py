"""tests/test_muscle_volume_working_sets_4071.py — per-muscle volume counted right, once.

THE BUG (#4071, owner-flagged 09-14, 09-15, 09-18, 09-19; misused again 09-22)
  `get_muscle_volume` — read by `plan_next_session` and, through the planner's
  `muscle_volume` block, by the `volume_ceiling` redline — was wrong four ways at once.
  Measured read-only against the live Hevy partition for 2026-09-15..09-21:

    old (origin/main)          Quads 10  Hamstrings 10  Chest 28  Triceps 32  Other 28   num_periods 0.9
    new (this module)          Quads  6  Hamstrings  7  Chest 12  Triceps 13  (cardio excluded, named)  1.0 week

  1. every set credited EVERY muscle in its keyword row at 1.0 (RDL -> Back+Ham+Glutes+Quads);
  2. warm-ups counted — the live rows carry `type`, the normalizer read `set_type`;
  3. keyword collisions ("Seated Leg Curl" -> Biceps via "curl");
  4. `(end - start).days` over an inclusive window: 7 days = 0.857 weeks.

THE FIXTURES ARE THE WIRE
  Rows are the live per-workout shape (`sk = DATE#…#WORKOUT#<uuid>`, sets with `type`,
  `weight_kg`, `reps` as the ingester writes them), fed through the real
  `normalize_hevy_items`. A fixture with a `set_type` key would have hidden defect 2 — the
  #4031 fixtures did exactly that.

THE DERIVATION GUARD
  `training.muscle_volume.working_sets_by_muscle` is the ONE per-muscle set computation.
  The AST guard below fails on any function in mcp/ or lambdas/training/ that both attributes
  an exercise to muscles and reads its sets, unless it is on the (reasoned) allowlist.
"""

from __future__ import annotations

import ast
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

from training import muscle_volume as mv  # noqa: E402

from mcp.strength_helpers import classify_exercise, normalize_hevy_items  # noqa: E402

PK = "USER#matthew#SOURCE#hevy"


def _set(kind: str = "normal", kg: float = 60.0, reps: int = 8, i: int = 0) -> dict:
    # Live key set, observed 2026-09-22 on all 623 sets since 2026-05-26.
    return {"type": kind, "weight_kg": kg, "reps": reps, "rpe": None, "distance_m": None, "duration_sec": None, "set_index": i}


def _ex(name: str, tid: str, n: int, warmups: int = 0) -> dict:
    sets = [_set("warmup", 20.0, 10, i) for i in range(warmups)] + [_set("normal", 60.0, 8, warmups + i) for i in range(n)]
    return {"template_id": tid, "name": name, "notes": "", "sets": sets}


def _row(date: str, uid: str, exercises: list[dict]) -> dict:
    return {"pk": PK, "sk": f"DATE#{date}#WORKOUT#{uid}", "date": date, "phase": "experiment", "exercises": exercises}


# The live 2026-09-17 leg day's shape, minus the hamstring movements: a QUAD-ONLY week.
_QUAD_ONLY_WEEK = [
    _row(
        "2026-09-17",
        "4c43e553-48c3-4a57-bb48-af833f38a3d6",
        [
            _ex("Leg Extension (Machine)", "75A4F6C4", 3),
            _ex("Linear Leg Press", "cb2d3813-d5b7-4c2e-a85e-6508c4a18d8b", 3, warmups=2),
        ],
    )
]


def _count(rows, start=None, end=None):
    return mv.working_sets_by_muscle(normalize_hevy_items(rows), start, end)


# ── Quads and Hamstrings are computed independently ──────────────────────────
def test_a_quad_only_week_reads_zero_hamstring_sets():
    out = _count(_QUAD_ONLY_WEEK)
    assert out["muscles"]["Quads"]["direct_sets"] == 6
    assert "Hamstrings" not in out["muscles"], out["muscles"]  # 0, not 6 — the old table credited 6


def test_a_hamstring_only_week_reads_zero_quad_sets():
    rows = [_row("2026-09-17", "u1", [_ex("Seated Leg Curl (Machine)", "11A123F3", 3), _ex("Romanian Deadlift (Barbell)", "2B4B7310", 4)])]
    out = _count(rows)
    assert out["muscles"]["Hamstrings"]["direct_sets"] == 7
    assert "Quads" not in out["muscles"]


def test_the_live_week_no_longer_reads_quads_equal_to_hamstrings():
    """2026-09-17 as logged: RDL 4, Leg Press 3, Calf Press 3, Seated Leg Curl 3, Leg Extension 3."""
    rows = [
        _row(
            "2026-09-17",
            "4c43e553",
            [
                _ex("Romanian Deadlift (Barbell)", "2B4B7310", 4),
                _ex("Linear Leg Press", "cb2d3813-d5b7-4c2e-a85e-6508c4a18d8b", 3),
                _ex("Calf Press (Machine)", "91237BDD", 3),
                _ex("Seated Leg Curl (Machine)", "11A123F3", 3),
                _ex("Leg Extension (Machine)", "75A4F6C4", 3),
            ],
        )
    ]
    m = _count(rows)["muscles"]
    assert m["Quads"]["total_sets"] == 6.0  # leg press + leg extension
    assert m["Hamstrings"]["total_sets"] == 7.0  # RDL + leg curl
    assert m["Glutes"] == {"direct_sets": 0, "secondary_sets": 3.5, "total_sets": 3.5, "volume_lbs": 0.0}  # RDL 4x0.5 + LP 3x0.5
    assert m["Calves"]["total_sets"] == 3.0
    assert "Biceps" not in m  # "Seated Leg Curl" is not a curl


# ── warm-ups are excluded by the SET TYPE the live rows carry ────────────────
def test_warmups_are_excluded_by_the_live_type_field():
    out = _count(_QUAD_ONLY_WEEK)
    assert out["warmup_sets_excluded"] == 2
    assert out["working_sets_counted"] == 6


def test_the_normalizer_reads_type_and_still_reads_legacy_set_type():
    live = normalize_hevy_items([_row("2026-09-19", "u", [_ex("Bench Press (Barbell)", "79D0BB3A", 1, warmups=1)])])
    assert [s["set_type"] for s in live[0]["exercises"][0]["sets"]] == ["warmup", "normal"]
    legacy = normalize_hevy_items(
        [
            {
                "sk": "DATE#2025-01-01",
                "date": "2025-01-01",
                "workouts": [{"exercises": [{"name": "Bench", "sets": [{"set_type": "warmup"}]}]}],
            }
        ]
    )
    assert legacy[0]["exercises"][0]["sets"][0]["set_type"] == "warmup"


def test_failure_and_drop_sets_are_working_sets():
    assert mv.is_working_set({"set_type": "failure"}) and mv.is_working_set({"set_type": "dropset"})
    assert not mv.is_working_set({"set_type": "warmup"})


# ── one primary per set; a secondary only where named, at the stated fraction ─
def test_bench_is_one_chest_set_and_half_a_triceps_set():
    m = _count([_row("2026-09-19", "u", [_ex("Bench Press (Barbell)", "79D0BB3A", 5, warmups=2)])])["muscles"]
    assert m["Chest"]["direct_sets"] == 5 and m["Chest"]["total_sets"] == 5.0
    assert m["Triceps"]["direct_sets"] == 0 and m["Triceps"]["secondary_sets"] == 5 * mv.SECONDARY_FRACTION
    assert "Shoulders" not in m


def test_isolation_movements_name_no_secondary():
    for name in (
        "Leg Extension (Machine)",
        "Seated Leg Curl (Machine)",
        "Lateral Raise (Dumbbell)",
        "Cable Fly Crossovers",
        "Triceps Pushdown",
    ):
        assert mv.attribute_exercise(name)["secondary"] == {}, name


@pytest.mark.parametrize(
    "name,primary",
    [
        # Every resistance movement in the live 2026-05-26..09-22 vocabulary, by hand.
        ("Seated Leg Curl (Machine)", "Hamstrings"),
        ("Lat Pulldown - Close Grip (Cable)", "Back"),
        ("Straight Arm Lat Pulldown (Cable)", "Back"),
        ("Rear Delt Reverse Fly (Machine)", "Shoulders"),
        ("Face Pull", "Shoulders"),
        ("Lateral Raise (Dumbbell)", "Shoulders"),
        ("Front Raise (Dumbbell)", "Shoulders"),
        ("Calf Press (Machine)", "Calves"),
        ("Calf Press on Leg Press Machine", "Calves"),
        ("Romanian Deadlift (Barbell)", "Hamstrings"),
        ("Linear Leg Press", "Quads"),
        ("Squat (Barbell)", "Quads"),
        ("Step Up", "Quads"),
        ("Hip Thrust (Barbell)", "Glutes"),
        ("Glute Machine Kickback", "Glutes"),
        ("Rear Kick (Machine)", "Glutes"),
        ("Kettlebell Swing", "Glutes"),
        ("Hammer Curl (Dumbbell)", "Biceps"),
        ("EZ Bar Biceps Curl", "Biceps"),
        ("Overhead Triceps Extension (Cable)", "Triceps"),
        ("Tricep Pushdown", "Triceps"),
        ("Bench Press (Barbell)", "Chest"),
        ("Incline Bench Press (Dumbbell)", "Chest"),
        ("Chest Press (Machine)", "Chest"),
        ("Cable Fly Crossovers", "Chest"),
        ("Shoulder Press (Dumbbell)", "Shoulders"),
        ("Seated Overhead Press (Dumbbell)", "Shoulders"),
        ("Landmine Press", "Shoulders"),
        ("Dumbbell Row", "Back"),
        ("Landmine Row", "Back"),
        ("Seated Cable Row - V Grip (Cable)", "Back"),
        ("Shrug (Barbell)", "Back"),
        ("Kettlebell High Pull", "Shoulders"),
        ("Farmers Walk", "Core"),
        ("Suitcase Carry", "Core"),
        ("Cable Pallof Press", "Core"),
        ("Side Bend (Dumbbell)", "Core"),
        ("Narrow Grip Bench Press", "Chest"),  # "row" must not match mid-word
    ],
)
def test_the_taxonomy_names_the_right_primary(name, primary):
    assert mv.attribute_exercise(name)["primary"] == primary


@pytest.mark.parametrize("name", ["Cycling", "Treadmill", "Walking", "Stretching", "Elliptical Trainer", "Rowing Machine"])
def test_cardio_and_mobility_carry_no_muscle_volume(name):
    a = mv.attribute_exercise(name)
    assert a["primary"] is None and a["matched"] == "non_resistance"


def test_an_unknown_movement_is_named_not_folded_into_a_muscle():
    out = _count([_row("2026-09-19", "u", [_ex("Hip Adduction (Machine)", "ABCD1234", 3)])])
    assert out["muscles"] == {}
    assert out["unattributed"] == [{"name": "Hip Adduction (Machine)", "template_id": "ABCD1234", "working_sets": 3}]


def test_classify_exercise_is_a_label_over_the_same_taxonomy():
    c = classify_exercise("Bench Press (Barbell)")
    assert c["muscle_groups"] == ["Chest", "Triceps"] and c["primary_muscle"] == "Chest"
    assert c["secondary_muscles"] == {"Triceps": mv.SECONDARY_FRACTION}


# ── whole-day window arithmetic ──────────────────────────────────────────────
def test_seven_inclusive_days_are_one_week():
    assert mv.window_days("2026-09-15", "2026-09-21") == 7
    assert mv.window_weeks("2026-09-15", "2026-09-21") == 1.0
    assert mv.window_weeks(mv.window_start("2026-09-21", 28), "2026-09-21") == 4.0
    assert mv.window_start("2026-09-21", 7) == "2026-09-15"


def test_an_inverted_or_unparseable_window_is_refused():
    with pytest.raises(ValueError):
        mv.window_days("2026-09-21", "2026-09-15")
    with pytest.raises(ValueError):
        mv.window_days("not-a-date", "2026-09-15")


def test_the_window_filter_is_inclusive_on_both_ends():
    rows = [_row(d, d, [_ex("Leg Extension (Machine)", "75A4F6C4", 1)]) for d in ("2026-09-14", "2026-09-15", "2026-09-21", "2026-09-22")]
    assert _count(rows, "2026-09-15", "2026-09-21")["muscles"]["Quads"]["direct_sets"] == 2


# ── the tool, end to end over a fake table ───────────────────────────────────
class _FakeTable:
    def __init__(self, rows):
        self.rows = rows

    def query(self, **kw):
        return {"Items": [r for r in self.rows if "#WORKOUT#" in r["sk"]] if "Limit" not in kw else [max(self.rows, key=lambda r: r["sk"])]}


@pytest.fixture
def tool(monkeypatch):
    import mcp.tools_strength as ts

    def _install(rows):
        monkeypatch.setattr(ts, "query_source_cross_phase", lambda src, s, e: [r for r in rows if s <= r["date"] <= e])
        monkeypatch.setattr(ts, "table", _FakeTable(rows))
        return ts.tool_get_muscle_volume

    return _install


def test_the_tool_reports_a_quad_only_week_as_zero_hamstrings(tool):
    out = tool(_QUAD_ONLY_WEEK)({"start_date": "2026-09-15", "end_date": "2026-09-21"})
    assert out["window_days"] == 7 and out["num_periods_analyzed"] == 1.0
    assert out["muscle_volume"]["Hamstrings"]["total_sets"] == 0.0
    assert out["muscle_volume"]["Hamstrings"]["volume_landmark_status"] == "below maintenance"
    assert out["muscle_volume"]["Quads"]["avg_sets_per_week"] == 6.0
    assert out["warmup_sets_excluded"] == 2
    assert out["method"]["source"].startswith("lambdas/training/muscle_volume.py::working_sets_by_muscle")


def test_the_tool_carries_7_and_28_day_trailing_windows(tool):
    rows = _QUAD_ONLY_WEEK + [_row("2026-08-30", "old", [_ex("Seated Leg Curl (Machine)", "11A123F3", 4)])]
    out = tool(rows)({"start_date": "2026-09-15", "end_date": "2026-09-21"})
    t7, t28 = out["trailing_windows"]["7d"], out["trailing_windows"]["28d"]
    assert (t7["start"], t7["weeks"]) == ("2026-09-15", 1.0)
    assert (t28["start"], t28["weeks"]) == ("2026-08-25", 4.0)
    assert t7["muscles"]["Hamstrings"]["total_sets"] == 0.0
    assert t28["muscles"]["Hamstrings"] == {"total_sets": 4.0, "direct_sets": 4, "sets_per_week": 1.0}
    # The analysis window's own provenance does not absorb the wider read.
    assert out["searched"]["workouts_read"] == 1
    assert out["searched"]["read_window"] == {"start": "2026-08-25", "end": "2026-09-21"}


def test_plan_next_session_asks_for_the_28_completed_days(monkeypatch):
    """The planner reads the tool — the SAME function — over target-28..target-1 (4.0 weeks)."""
    import mcp.tools_plan as tp
    import mcp.tools_strength as ts

    seen = {}

    def _spy(args):
        seen.update(args)
        return {"muscle_volume": {"Quads": {"avg_sets_per_week": 6.0, "total_sets": 24.0}}}

    monkeypatch.setattr(ts, "tool_get_muscle_volume", _spy)
    try:
        tp.tool_plan_next_session({"target_date": "2026-09-24"})
    except Exception:  # noqa: BLE001 — every other reader is unwired here; only the volume call matters
        pass
    assert seen == {"start_date": "2026-08-27", "end_date": "2026-09-23"}
    assert mv.window_weeks(seen["start_date"], seen["end_date"]) == 4.0
    assert tp._muscle_sets({"muscle_volume": {"Quads": {"avg_sets_per_week": 6.0, "total_sets": 24.0}}}) == {"Quads": 6.0}


# ── the derivation guard: ONE per-muscle computation ─────────────────────────
_ATTRIBUTION_CALLS = {"attribute_exercise", "classify_exercise", "muscle_override_for", "_classify_muscles"}

#: (file, function) -> why it is not a second per-muscle computation. Adding a row needs a reason.
_ALLOWED = {
    ("lambdas/training/muscle_volume.py", "working_sets_by_muscle"): "THE computation",
    ("mcp/tools_strength.py", "_summarize_exercise_sessions"): (
        "one MOVEMENT's history: labels the movement with its muscles and counts that movement's sets — never a per-muscle total"
    ),
}


def _calls_attribution(fn: ast.AST) -> bool:
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
            if name in _ATTRIBUTION_CALLS:
                return True
    return False


def _reads_sets(fn: ast.AST) -> bool:
    return any(
        (isinstance(n, ast.Constant) and n.value == "sets") or (isinstance(n, ast.Attribute) and n.attr == "sets") for n in ast.walk(fn)
    )


def _per_muscle_set_computations(source: str) -> list[str]:
    tree = ast.parse(source)
    return [
        fn.name
        for fn in ast.walk(tree)
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and _calls_attribution(fn) and _reads_sets(fn)
    ]


def test_no_second_per_muscle_set_computation_in_mcp_or_training():
    found = set()
    for root in ("mcp", "lambdas/training"):
        for path in sorted((REPO / root).rglob("*.py")):
            rel = path.relative_to(REPO).as_posix()
            for name in _per_muscle_set_computations(path.read_text()):
                found.add((rel, name))
    extra = found - set(_ALLOWED)
    assert not extra, f"a second per-muscle set computation exists — route it through training.muscle_volume: {sorted(extra)}"
    assert ("lambdas/training/muscle_volume.py", "working_sets_by_muscle") in found, "the guard no longer sees THE computation"


def test_the_guard_can_fail():
    """Mutation control: the pre-#4071 loop shape is caught."""
    old_shape = (
        "def tool(items):\n"
        "    out = {}\n"
        "    for ex in items:\n"
        "        for m in classify_exercise(ex['name'])['muscle_groups']:\n"
        "            out[m] = out.get(m, 0) + len(ex['sets'])\n"
        "    return out\n"
    )
    assert _per_muscle_set_computations(old_shape) == ["tool"]


def test_the_tool_and_the_planner_read_the_one_computation():
    ts_src = (REPO / "mcp/tools_strength.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(ts_src)) if isinstance(n, ast.FunctionDef) and n.name == "tool_get_muscle_volume")
    called = {n.func.id for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "working_sets_by_muscle" in called
    assert not (called & _ATTRIBUTION_CALLS), "the tool must not attribute sets itself"

    tp_src = (REPO / "mcp/tools_plan.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(tp_src)) if isinstance(n, ast.FunctionDef) and n.name == "tool_plan_next_session")
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    assert "tool_get_muscle_volume" in names
    assert not (names & _ATTRIBUTION_CALLS)
