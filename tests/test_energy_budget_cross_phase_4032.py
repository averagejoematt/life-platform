"""tests/test_energy_budget_cross_phase_4032.py — the calorie target stepped at every genesis.

THE BUG (#4032, found by #4030's consumer audit)
  Two energy-budget readers pulled their inputs through the plain `query_source(...)`
  default, i.e. `include_pilot=False`, i.e. the ADR-058 phase filter:

    * `mcp/tools_health.py::_get_energy_expenditure` — `hevy_7d`/`hevy_30d` into
      `tdee_core.exercise_energy`, plus its `strava`, `withings` and `macrofactor` reads;
    * `mcp/tools_nutrition.py::_hevy_workouts` — the same worked-set input to the ADR-152
      energy budget, plus `_trend_check`/`_energy_budget`'s `withings` and `strava` reads.

  The restart tagger stamps every pre-genesis row `phase=pilot` (ADR-077), so every one of
  those trailing windows truncated at the current genesis. `phase_taxonomy.classify` rules
  all four partitions **raw_timeseries** — kept forever, genesis-ANCHORED on read (the
  caller's DATE window bounds recency), never HIDDEN — and
  `phase_filter.source_reads_cross_phase(source)` already returned True for each. No read
  asked it. On the morning after a restart the 30-day term collapses to one day of
  training and `exercise_energy` under-reports the worked-set input to the TDEE and the
  published calorie target for a month afterwards — exactly the loss #3931 added that term
  to prevent, re-introduced silently, on a schedule.

  Measured live 2026-09-21 (genesis 2026-09-06, 16 days back), 30d window 2026-08-23..09-21:
  hevy 15 -> 16 rows, strava 16 -> 18, macrofactor 14 -> 20, withings 9 -> 13; the 30d
  worked-set input 234 -> 257 sets and `tdee_30d_avg` 2776 -> 2812 kcal.

THE FIXTURE IS THE WIRE
  `_FakeTable` is patched into `mcp.core` (never over `query_source`/`_read_hevy_all_phases`),
  so every assertion runs through the real `query_source` -> `_apply_phase_filter` path and
  the fake applies the real FilterExpression string `mcp.core` mints, with DynamoDB's own
  semantics (an item with no `phase` attribute passes). Row shapes are copied from the live
  partitions read on 2026-09-21, never invented.

THE FIXTURE IS A DAY-AFTER-GENESIS (acceptance box 4)
  The phase boundary sits at 2026-09-17 — INSIDE the 7-day window as well as the 30-day one
  — because that is the failure mode the issue names: the error is a function of
  days-since-genesis and is TOTAL on the morning after a restart, not proportional to how
  small it happens to look on the calendar day the fix shipped.
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

import mcp.core as core  # noqa: E402
import mcp.tools_health as th  # noqa: E402
import mcp.tools_nutrition as tn  # noqa: E402

END = "2026-09-20"  # the tool's end_date; d7_start = 2026-09-14, d30_start = 2026-08-22
GENESIS = "2026-09-17"  # the fixture's cycle boundary — inside BOTH windows

PROFILE = {
    "pk": "USER#matthew",
    "sk": "PROFILE#v1",
    "height_inches": 69,
    "date_of_birth": "1989-01-15",
    "biological_sex": "male",
}


def _phase(date: str) -> str:
    return "experiment" if date >= GENESIS else "pilot"


def _hevy_workout(date: str, uid: str, n_sets: int) -> dict:
    """A per-workout Hevy row in the live wire shape (`DATE#…#WORKOUT#<uuid>`)."""
    return {
        "pk": "USER#matthew#SOURCE#hevy",
        "sk": f"DATE#{date}#WORKOUT#{uid}",
        "date": date,
        "phase": _phase(date),
        "source": "hevy",
        "source_workout_id": uid,
        "title": "Push",
        "duration_sec": 3600,
        "exercises": [
            {
                "template_id": "79D0BB3A",
                "name": "Bench Press (Barbell)",
                "sets": [{"weight_kg": 60.0, "reps": 8, "set_type": "normal"} for _ in range(n_sets)],
            }
        ],
    }


def _hevy_legacy_aggregate(date: str, n_sets: int) -> dict:
    """The superseded generation: a legacy daily aggregate, tombstoned in place 2026-05-26.

    Shape copied from the live row `DATE#2025-11-07` — `workouts[].exercises[].sets[]`, no
    top-level `exercises`, `tombstone=true`. All 421 of them carry a date that a per-workout
    row also covers, and `strength_helpers.normalize_hevy_items` parses BOTH shapes.
    """
    return {
        "pk": "USER#matthew#SOURCE#hevy",
        "sk": f"DATE#{date}",
        "date": date,
        "phase": _phase(date),
        "source": "hevy",
        "tombstone": True,
        "tombstoned_at": "2026-05-26T00:16:57.567204+00:00",
        "tombstoned_reason": "legacy_daily_aggregate_superseded_by_per_workout",
        "total_sets": float(n_sets),
        "workouts_count": 1.0,
        "workouts": [
            {
                "title": "Push",
                "duration_minutes": 60.0,
                "exercises": [
                    {
                        "name": "Bench Press (Barbell)",
                        "sets": [{"set_type": "normal", "set_index": float(i), "reps": 8.0, "weight_lbs": 135.0} for i in range(n_sets)],
                    }
                ],
            }
        ],
    }


def _strava_day(date: str, moving_s: int) -> dict:
    return {
        "pk": "USER#matthew#SOURCE#strava",
        "sk": f"DATE#{date}",
        "date": date,
        "phase": _phase(date),
        "source": "strava",
        "total_moving_time_seconds": moving_s,
        "total_kilojoules": 0,
        "activities": [{"sport_type": "Walk", "moving_time_seconds": moving_s}],
    }


def _withings_day(date: str, lbs: float) -> dict:
    return {
        "pk": "USER#matthew#SOURCE#withings",
        "sk": f"DATE#{date}",
        "date": date,
        "phase": _phase(date),
        "source": "withings",
        "weight_lbs": lbs,
    }


def _macrofactor_day(date: str, kcal: float) -> dict:
    return {
        "pk": "USER#matthew#SOURCE#macrofactor",
        "sk": f"DATE#{date}",
        "date": date,
        "phase": _phase(date),
        "source": "macrofactor",
        "total_calories_kcal": kcal,
        "total_protein_g": 150.0,
        "total_fiber_g": 25.0,
        "food_log": [{"time": "12:00", "food_name": "lunch", "calories_kcal": kcal, "protein_g": 150.0}],
    }


# ── the store ─────────────────────────────────────────────────────────────────
# Hevy: one pre-genesis workout inside the 7d window, one outside it but inside 30d, one
# current-cycle workout, one far-past row the WINDOW (not the phase tag) must exclude, and
# the tombstoned legacy duplicate of the 09-16 session.
_HEVY = [
    _hevy_workout("2026-05-01", "aaaaaaaa-0000-0000-0000-000000000001", 11),  # outside every window
    _hevy_workout("2026-08-28", "bbbbbbbb-0000-0000-0000-000000000002", 5),  # 30d only, phase=pilot
    _hevy_workout("2026-09-16", "cccccccc-0000-0000-0000-000000000003", 7),  # 7d AND 30d, phase=pilot
    _hevy_legacy_aggregate("2026-09-16", 7),  # the superseded duplicate of that same session
    _hevy_workout("2026-09-19", "dddddddd-0000-0000-0000-000000000004", 3),  # phase=experiment
]
_STRAVA = [
    _strava_day("2026-08-28", 1800),
    _strava_day("2026-09-16", 1800),
    _strava_day("2026-09-19", 1800),
]
_WITHINGS = [
    _withings_day("2026-09-07", 320.0),
    _withings_day("2026-09-16", 316.0),
    _withings_day("2026-09-19", 315.0),
]
# 14 consecutive MacroFactor days spanning the boundary — enough for the deficit tool's
# >=7-day floor, and the phase flips inside the window exactly as it does live.
_MACROFACTOR = [_macrofactor_day(f"2026-09-{day:02d}", 1800.0) for day in range(7, 21)]

_ROWS = _HEVY + _STRAVA + _WITHINGS + _MACROFACTOR

_PHASE_FILTER_EXPRESSION = "(#phase = :phase_experiment OR attribute_not_exists(#phase))"


def _eval_key_condition(cond, item) -> bool:
    """Evaluate a real boto3 Key condition tree against one item."""
    expr = cond.get_expression()
    op = expr["operator"]
    vals = expr["values"]
    if op == "AND":
        return _eval_key_condition(vals[0], item) and _eval_key_condition(vals[1], item)
    attr = vals[0].name
    actual = str(item.get(attr, ""))
    if op == "=":
        return actual == vals[1]
    if op == "BETWEEN":
        return vals[1] <= actual <= vals[2]
    if op == "begins_with":
        return actual.startswith(vals[1])
    raise AssertionError(f"fake table: unhandled key operator {op!r} — the fixture must be the wire")


class _FakeTable:
    """DynamoDB Query/GetItem semantics for exactly the shapes `mcp.core` builds."""

    def __init__(self, rows):
        self.rows = rows
        self.filters_by_pk: list = []

    def get_item(self, Key):  # noqa: N803 — boto3's own parameter name
        if Key == {"pk": PROFILE["pk"], "sk": PROFILE["sk"]}:
            return {"Item": PROFILE}
        return {}

    def query(self, **kwargs):
        rows = [r for r in self.rows if _eval_key_condition(kwargs["KeyConditionExpression"], r)]
        fe = kwargs.get("FilterExpression")
        pk = kwargs["KeyConditionExpression"].get_expression()["values"][0].get_expression()["values"][1]
        self.filters_by_pk.append((pk, fe))
        if fe is not None:
            # The only FilterExpression mcp.core mints on this path. Asserted rather than
            # pattern-matched so a future edit to the expression cannot make this fake
            # silently permissive.
            assert fe == _PHASE_FILTER_EXPRESSION, f"unexpected FilterExpression {fe!r}"
            field = kwargs["ExpressionAttributeNames"]["#phase"]
            wanted = kwargs["ExpressionAttributeValues"][":phase_experiment"]
            # DynamoDB: an item with no `phase` attribute passes attribute_not_exists.
            rows = [r for r in rows if field not in r or r[field] == wanted]
        return {"Items": rows}


@pytest.fixture
def wired(monkeypatch):
    fake = _FakeTable(_ROWS)
    monkeypatch.setattr(core, "table", fake)
    monkeypatch.setattr(core, "_PROFILE_CACHE", None)
    yield fake
    core._PROFILE_CACHE = None


@pytest.fixture
def hevy_seen(monkeypatch):
    """Every `hevy_workouts` list handed to the ADR-152 exercise term, in call order.

    Spying on the ONE method entry point rather than on a read helper is deliberate: what
    matters is what the published number was computed from, not what some helper returned.
    """
    from health import tdee as tdee_core

    real = tdee_core.exercise_energy
    seen: list = []

    def _spy(strava_items, weight_kg, hevy_workouts=None):
        seen.append(list(hevy_workouts or []))
        return real(strava_items, weight_kg, hevy_workouts)

    monkeypatch.setattr(tdee_core, "exercise_energy", _spy)
    return seen


def _sets(rows) -> int:
    from health import tdee as tdee_core

    return tdee_core.worked_set_seconds(rows)["sets"]


# ── caller 1: mcp/tools_health.py::_get_energy_expenditure ────────────────────
def test_the_worked_set_input_reaches_across_the_genesis_in_both_windows(wired, hevy_seen):
    """The day-after-genesis case: the pre-genesis sessions are IN, in the 7d term too."""
    out = th._get_energy_expenditure({"end_date": END})
    assert "error" not in out, out

    d7_hevy, d30_hevy = hevy_seen[0], hevy_seen[1]
    assert sorted(r["date"] for r in d7_hevy) == ["2026-09-16", "2026-09-19"]
    assert sorted(r["date"] for r in d30_hevy) == ["2026-08-28", "2026-09-16", "2026-09-19"]
    # 7 pre-genesis sets + 3 current; and 5 more from the 08-28 session in the 30d window.
    assert _sets(d7_hevy) == 10
    assert _sets(d30_hevy) == 15
    assert out["calorie_target"]["inputs"]["lifting"]["sets"] == 10
    assert out["calorie_target_30d_basis"]["inputs"]["lifting"]["sets"] == 15


def test_the_published_tdee_and_calorie_target_are_computed_across_phases(wired):
    """The numbers the owner reads — stated here as literals so a regression is loud."""
    out = th._get_energy_expenditure({"end_date": END})

    # The weigh-in the tool anchors to is itself pre-genesis in this fixture.
    assert out["current_weight_lbs"] == 315.0
    assert out["current_weight_date"] == "2026-09-19"
    assert out["exercise_kcal_7d_daily_avg"] == 136
    assert out["exercise_kcal_30d_daily_avg"] == 48
    assert out["tdee_7d_avg"] == 2477
    assert out["tdee_30d_avg"] == 2389
    assert out["calorie_target_based_on_30d"] == 1889

    # The 7d target is REFUSED here, and that is the fix working rather than a wobble: with
    # three weigh-ins visible instead of one, `implied_deficit_vs_measured_weight_trend`
    # finally has the >=7 trend days it needs to run at all, and it disagrees. The filtered
    # arm published a number precisely because it could not see enough of the record to
    # check it (see the mutation control below).
    assert out["calorie_target_based_on_7d"] is None
    assert out["calorie_target_published"] is False
    assert out["calorie_target_basis"].startswith("refused: model_and_trend_disagree")
    assert out["calorie_target_check"]["trend_days"] == 12


def test_every_partition_this_tool_reads_is_read_unfiltered(wired):
    """All four are raw_timeseries, so NONE of these reads may carry the ADR-058 filter."""
    th._get_energy_expenditure({"end_date": END})
    assert wired.filters_by_pk, "the tool never reached the table"
    filtered = [pk for pk, fe in wired.filters_by_pk if fe is not None]
    assert filtered == [], f"these partitions were still phase-filtered: {sorted(set(filtered))}"
    assert {pk.rsplit("#", 1)[-1] for pk, _ in wired.filters_by_pk} == {"hevy", "strava", "withings", "macrofactor"}


def test_the_answer_states_the_phases_and_the_window_it_read(wired):
    out = th._get_energy_expenditure({"end_date": END})
    scope = out["phase_scope"]

    assert "source_reads_cross_phase" in scope["phase_filter"]
    src = scope["sources"]
    assert src[f"hevy_7d[2026-09-14..{END}]"] == {"rows": 2, "phases": ["experiment", "pilot"]}
    assert src[f"hevy_30d[2026-08-22..{END}]"] == {"rows": 3, "phases": ["experiment", "pilot"]}
    assert src[f"strava_30d[2026-08-22..{END}]"]["phases"] == ["experiment", "pilot"]
    assert src[f"withings_trend_14d[2026-09-06..{END}]"]["phases"] == ["experiment", "pilot"]
    assert src[f"macrofactor_7d[2026-09-14..{END}]"]["rows"] == 7


def test_the_superseded_legacy_aggregate_never_reaches_the_exercise_term(wired, hevy_seen):
    """Lifting the filter must not double-count the 2026-05-26 superseded generation."""
    th._get_energy_expenditure({"end_date": END})
    for rows in hevy_seen:
        assert not any(r.get("tombstone") for r in rows), "a tombstoned legacy aggregate reached exercise_energy"
        # One row per real session — the legacy duplicate covers the same 2026-09-16 date.
        assert [r["date"] for r in rows].count("2026-09-16") == 1

    # Honesty about the size of this guard TODAY: `worked_set_seconds` reads
    # `w["exercises"]`, which the legacy shape does not carry (its sets live under
    # `workouts[].exercises[]`), so a leaked aggregate would currently contribute 0 sets
    # rather than 7. The exclusion is a contract, not a measured double-count on THIS
    # path — `normalize_hevy_items` (the strength tools' parser) does read both shapes,
    # which is where it bit in #4030.
    from health import tdee as tdee_core

    assert tdee_core.worked_set_seconds([_hevy_legacy_aggregate("2026-09-16", 7)])["sets"] == 0


def test_the_date_window_still_bounds_the_answer(wired, hevy_seen):
    """Cross-phase is not unbounded: the DATE window is what bounds recency (#2109).

    The 2026-05-01 session is `phase=pilot` and 4+ months old; it must stay out of both
    windows, and the 08-28 one must stay out of the 7-day window.
    """
    th._get_energy_expenditure({"end_date": END})
    d7_hevy, d30_hevy = hevy_seen[0], hevy_seen[1]
    assert "2026-05-01" not in {r["date"] for r in d7_hevy} | {r["date"] for r in d30_hevy}
    assert "2026-08-28" not in {r["date"] for r in d7_hevy}
    assert "2026-08-28" in {r["date"] for r in d30_hevy}


def test_an_explicit_earlier_end_date_is_honoured(wired, hevy_seen):
    """A historical end_date reads that window, not today's — and still crosses phases."""
    out = th._get_energy_expenditure({"end_date": "2026-09-17"})
    assert out["window"]["d7_start"] == "2026-09-11"
    assert sorted(r["date"] for r in hevy_seen[0]) == ["2026-09-16"]
    assert sorted(r["date"] for r in hevy_seen[1]) == ["2026-08-28", "2026-09-16"]


# ── caller 2: mcp/tools_nutrition.py — the ADR-152 energy budget ──────────────
def test_the_nutrition_worked_set_input_reads_both_cycles(wired):
    rows = tn._hevy_workouts("2026-09-14", END)
    assert sorted(r["date"] for r in rows) == ["2026-09-16", "2026-09-19"]
    assert {r["phase"] for r in rows} == {"pilot", "experiment"}
    assert not any(r.get("tombstone") for r in rows)
    assert _sets(rows) == 10


def test_the_nutrition_energy_budget_publishes_the_cross_phase_target(wired, hevy_seen):
    """`_energy_budget` is the ADR-152 definition the macros view and the deficit tool share."""
    budget = tn._energy_budget(END)
    assert budget is not None

    assert budget["inputs"]["lifting"]["sets"] == 10
    assert budget["inputs"]["weight_lbs"] == 315.0
    assert budget["tdee"] == 2477
    assert budget["target"] == 1977  # tdee - the ADR-152 default 500 kcal deficit
    assert sorted(r["date"] for r in hevy_seen[0]) == ["2026-09-16", "2026-09-19"]


def test_the_nutrition_reads_carry_no_phase_filter_either(wired):
    wired.filters_by_pk.clear()
    tn._energy_budget(END, intake_avg=1800.0)
    assert wired.filters_by_pk, "the budget never reached the table"
    assert [pk for pk, fe in wired.filters_by_pk if fe is not None] == []
    # withings (the weigh-in AND the trend check), strava, hevy — every one of them.
    assert {pk.rsplit("#", 1)[-1] for pk, _ in wired.filters_by_pk} == {"withings", "strava", "hevy"}


def test_the_deficit_tool_publishes_a_cross_phase_tdee_and_says_so(wired):
    out = tn.tool_get_deficit_sustainability({"end_date": END, "days": 14})
    assert "error" not in out, out

    assert out["deficit"]["estimated_tdee"] == 2477
    assert out["deficit"]["avg_intake_kcal"] == 1800
    assert out["deficit"]["tdee_method"] == "mifflin_bmr_plus_worked_set_exercise"
    scope = out["phase_scope"]["sources"]
    assert scope[f"macrofactor[2026-09-07..{END}]"] == {"rows": 14, "phases": ["experiment", "pilot"]}
    assert scope[f"hevy[2026-09-07..{END}]"]["phases"] == ["experiment", "pilot"]


# ── MUTATION CONTROL ──────────────────────────────────────────────────────────
def test_mutation_restoring_the_phase_filter_reproduces_the_bug(wired, hevy_seen, monkeypatch):
    """Force the one derived decision back to False and the pre-genesis record vanishes.

    `source_reads_cross_phase` is what `mcp.core.query_source_cross_phase` turns on, so
    forcing it False reproduces the pre-#4032 `query_source("hevy", …)` default exactly —
    for every source at once, which is the point: the defect was never Hevy-specific.
    """
    import experiment.phase_filter as pf

    monkeypatch.setattr(pf, "source_reads_cross_phase", lambda *_a, **_k: False)
    out = th._get_energy_expenditure({"end_date": END})

    # Both windows collapse to the cycle's AGE — one workout, three sets.
    assert sorted(r["date"] for r in hevy_seen[0]) == ["2026-09-19"], "mutation did not bite"
    assert sorted(r["date"] for r in hevy_seen[1]) == ["2026-09-19"]
    assert out["calorie_target"]["inputs"]["lifting"]["sets"] == 3
    assert out["calorie_target_30d_basis"]["inputs"]["lifting"]["sets"] == 3

    # …and the published numbers move with it. These are the "before" figures: a TDEE 71
    # kcal/day low on the 7d window and 33 low on the 30d, off 3 sets instead of 10/15.
    assert out["exercise_kcal_7d_daily_avg"] == 65
    assert out["exercise_kcal_30d_daily_avg"] == 15
    assert out["tdee_7d_avg"] == 2406
    assert out["tdee_30d_avg"] == 2356
    assert out["calorie_target_based_on_30d"] == 1856

    # The sharpest edge of the defect: with only one weigh-in visible the impossibility
    # check has no trend to judge against, so it PUBLISHES 1906 kcal/day as "unverified"
    # rather than refusing. The truncation did not just move the number — it disarmed the
    # guard that would have caught it.
    assert out["calorie_target_based_on_7d"] == 1906
    assert out["calorie_target_published"] is True
    assert out["calorie_target_basis"] == "published_unverified_no_measured_weight_trend"

    # The filter really is back on the wire, on every partition.
    assert [pk for pk, fe in wired.filters_by_pk if fe is None] == []


def test_mutation_also_reproduces_it_through_the_nutrition_caller(wired, monkeypatch):
    import experiment.phase_filter as pf

    monkeypatch.setattr(pf, "source_reads_cross_phase", lambda *_a, **_k: False)

    assert [r["date"] for r in tn._hevy_workouts("2026-09-14", END)] == ["2026-09-19"]
    budget = tn._energy_budget(END)
    assert budget["inputs"]["lifting"]["sets"] == 3
    assert budget["tdee"] == 2406
    assert budget["target"] == 1906

    # And the deficit tool stops answering at all — its >=7-day MacroFactor floor is the
    # one place the truncation surfaces as an error instead of as a confident number.
    assert tn.tool_get_deficit_sustainability({"end_date": END, "days": 14})["error"].startswith(
        "Need \u22657 days of MacroFactor data. Found 4"
    )


# ── the derivation is derived, not asserted ───────────────────────────────────
def test_the_cross_phase_decision_comes_from_the_taxonomy_for_all_four_sources():
    """If the taxonomy ever reclassifies one of these, the reads follow it — no edit here."""
    from experiment import phase_taxonomy
    from experiment.phase_filter import source_reads_cross_phase

    for source in ("hevy", "strava", "macrofactor", "withings"):
        assert phase_taxonomy.classify(f"USER#matthew#SOURCE#{source}") == phase_taxonomy.RAW_TIMESERIES
        assert source_reads_cross_phase(source) is True


def test_the_one_hevy_read_path_is_shared_not_duplicated():
    """#4030's helper and #4032's callers must be ONE read path, not two.

    AST, not a substring sweep: `_hevy_workouts`'s own docstring names the call it
    replaced, and a text match cannot tell that from a live call site.
    """
    import ast
    import inspect

    import mcp.tools_strength as ts

    assert "query_source_cross_phase" in inspect.getsource(
        ts._read_hevy_all_phases
    ), "the Hevy helper stopped delegating to the shared read"

    _FILTERED_READERS = {"query_source", "query_source_range", "parallel_query_sources"}

    def _filtered_calls(tree) -> list:
        return [
            ast.unparse(node)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FILTERED_READERS
        ]

    # tools_health: this issue's scope is `_get_energy_expenditure` alone. Its siblings in
    # the module (`_get_hydration_score`, the readiness/recovery views…) still read through
    # the phase-filtered default, and one of them reads `computed_metrics`, which is
    # EXPERIMENT_SCOPED and MUST keep the filter — so a module-wide assertion here would be
    # wrong, not merely broad. Named as a residual in the PR rather than swept silently.
    energy_fn = next(
        node
        for node in ast.parse(inspect.getsource(th)).body
        if isinstance(node, ast.FunctionDef) and node.name == "_get_energy_expenditure"
    )
    assert _filtered_calls(energy_fn) == [], f"_get_energy_expenditure re-opened a phase-filtered read: {_filtered_calls(energy_fn)}"

    # tools_nutrition: every read in the module is raw_timeseries (acceptance box 1 —
    # enumerated, not spot-fixed), so the whole module is held.
    offenders = _filtered_calls(ast.parse(inspect.getsource(tn)))
    assert offenders == [], f"mcp.tools_nutrition re-opened a phase-filtered read path: {offenders}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
