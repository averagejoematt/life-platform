"""tests/test_fitness_tests_5078.py — the fitness test battery every block (#5078, epic #5051).

Owner direction 2026-10-18 (the elite-panel training review): a battery on a fixed cadence — a 6-minute walk
for distance, a 20-minute bike at RPE 6 for distance, a dead hang for time, the assistance an assisted pull-up
needs. Covered here: the charter protocol, the cadence (ok / due / overdue / missed, block-aligned), the
storage round trip (fixture = the DynamoDB wire: Decimal in, the store's own reader out), the trend direction
per test, the Hevy reader, the test-day draft placement and the absent path. No clock is read: every day is
passed in.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
from decimal import Decimal
from unittest.mock import patch

import pytest

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO))

from training import (
    fitness_tests as ft,  # noqa: E402
    training_charter as tc,  # noqa: E402
)

CATALOG = json.loads((_REPO / "config" / "movement_catalog.json").read_text())
MOVEMENTS = CATALOG["movements"]


@pytest.fixture(autouse=True)
def _public_charter_only(monkeypatch):
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    tc.reset_cache()
    yield
    tc.reset_cache()


class FakeTable:
    """The two calls the store makes, holding items as the DynamoDB wire does (Decimal, never float)."""

    def __init__(self):
        self.items: dict[tuple[str, str], dict] = {}

    def put_item(self, Item):
        assert not any(isinstance(v, float) for v in _leaves(Item)), "a float reached put_item — boto3 rejects it"
        self.items[(Item["pk"], Item["sk"])] = Item

    def query(self, KeyConditionExpression, ExpressionAttributeValues, **kw):
        pk = ExpressionAttributeValues[":pk"]
        if ":sk" in ExpressionAttributeValues:
            rows = [v for (p, s), v in self.items.items() if p == pk and s == ExpressionAttributeValues[":sk"]]
        else:
            rows = [v for (p, s), v in sorted(self.items.items()) if p == pk and s.startswith(ExpressionAttributeValues[":pfx"])]
        return {"Items": rows}


def _leaves(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from _leaves(v)
    elif isinstance(o, list):
        for v in o:
            yield from _leaves(v)
    else:
        yield o


# ── the charter protocol ──────────────────────────────────────────────────────────────────
def test_the_charter_names_each_test_with_a_machine_a_unit_and_a_better_direction():
    c = tc.load_charter()
    assert c["version"] == c["change_log"][-1]["version"]
    assert any("#5078" in e["by"] for e in c["change_log"])
    p = ft.protocol()
    spec = ft.tests_spec()
    assert len(spec) == len(p["battery"]) == 4
    for tid, row in spec.items():
        assert row["catalog_key"] in MOVEMENTS, f"{tid}: {row['catalog_key']} is not in the movement catalog"
        assert MOVEMENTS[row["catalog_key"]].get("hevy_template_id_hint"), f"{tid}: no Hevy template id"
        assert row["unit"] and row["better"] in ("higher", "lower") and row["protocol"]
    assert spec["assisted_pull_up"]["better"] == "lower"
    assert sorted(p["order"]) == sorted([*spec, "minimum_session"])


def test_the_test_day_is_the_lightest_role_and_never_a_lower_day():
    from training import program_structure as ps

    role = ft.test_day_role()
    tmpl = ps.SESSION_TEMPLATES[role]
    assert role not in ft.never_on_roles() and ps.role_id("Lower-heavy") in ft.never_on_roles()
    assert tmpl["archetype"] != "lower" and all(i != "heavy" for _p, i in tmpl["anchors"])
    assert len(tmpl["anchors"]) == min(len(t["anchors"]) for t in ps.SESSION_TEMPLATES.values())


# ── cadence ───────────────────────────────────────────────────────────────────────────────
POS_W3 = {"week": 3, "week_opened_on": "2026-10-05"}  # week 6 then opens 2026-10-26 at the earliest


@pytest.mark.parametrize(
    "today,state",
    [("2026-10-20", ft.OK), ("2026-10-26", ft.DUE), ("2026-11-01", ft.DUE), ("2026-11-02", ft.OVERDUE), ("2026-11-09", ft.MISSED)],
)
def test_the_due_week_closes_the_block_then_overdue_then_missed(today, state):
    got = ft.due(today, POS_W3, [])
    assert got["due_on"] == "2026-10-26" and got["due_program_week"] == 6 and got["basis"] == "block"
    assert got["state"] == state
    assert (got["prompt"] is None) == (state == ft.OK)


def test_a_battery_in_the_due_week_or_a_week_early_covers_it_and_the_next_block_is_due_next():
    for logged in ("2026-10-27", "2026-10-19"):
        got = ft.due("2026-10-28", POS_W3, [logged])
        assert got["state"] == ft.OK and got["due_program_week"] == 12 and got["due_on"] == "2026-12-07"
    assert ft.due("2026-10-28", POS_W3, ["2026-10-18"])["state"] == ft.DUE  # eight days early is the last block's


def test_a_missed_battery_stays_missed_into_the_next_block_until_one_is_logged():
    pos = {"week": 8, "week_opened_on": "2026-11-09"}
    got = ft.due("2026-11-12", pos, ["2026-09-30"])
    assert got["due_program_week"] == 6 and got["due_on"] == "2026-10-26" and got["state"] == ft.MISSED
    after = ft.due("2026-11-13", pos, ["2026-09-30", "2026-11-12"])
    assert after["state"] == ft.OK and after["due_program_week"] == 12


def test_without_a_position_the_calendar_places_the_due_week_and_with_nothing_it_is_unknown():
    cal = ft.due("2026-11-12", None, ["2026-10-01"])
    assert cal["basis"] == "calendar" and cal["due_on"] == "2026-11-12" and cal["state"] == ft.DUE
    none = ft.due("2026-11-12", None, [])
    assert none["state"] == ft.UNKNOWN and none["due_on"] is None and none["prompt"] is None


# ── storage round trip (the wire) ─────────────────────────────────────────────────────────
def test_a_battery_round_trips_through_the_wire_and_a_second_write_merges():
    t = FakeTable()
    rec = ft.build_battery_record(date="2026-10-27", results={"six_minute_walk": 610, "dead_hang": 41.5}, recorded_at="t1")
    ft.write_record(t, rec)
    stored = t.items[(ft.PK, "BATTERY#2026-10-27")]
    assert stored["pk"] == "USER#matthew#SOURCE#fitness_tests" and isinstance(stored["tests"]["dead_hang"]["value"], Decimal)
    assert stored["tier"] == "owner_only" and stored["charter_version"] == tc.charter_version()
    back = ft.load_records(t)
    merged = ft.build_battery_record(
        date="2026-10-27", results={"assisted_pull_up": 70}, notes={"assisted_pull_up": "machine 2"}, recorded_at="t2", existing=back[0]
    )
    ft.write_record(t, merged)
    (row,) = ft.load_records(t)
    assert set(row["tests"]) == {"six_minute_walk", "dead_hang", "assisted_pull_up"}
    assert row["tests"]["dead_hang"] == {"value": 41.5, "unit": "s", "protocol_version": "1", "source": "explicit"}
    assert row["tests"]["assisted_pull_up"]["notes"] == "machine 2"


@pytest.mark.parametrize(
    "kw,why",
    [
        ({"date": "2026-10-27", "results": {"plank": 60}}, "unknown test"),
        ({"date": "2026-10-27", "results": {"dead_hang": "long"}}, "must be a number"),
        ({"date": "2026-10-27", "results": {"dead_hang": -1}}, "zero or more"),
        ({"date": "27/10/2026", "results": {"dead_hang": 30}}, "YYYY-MM-DD"),
        ({"date": "2026-10-27", "results": {}}, "no results"),
    ],
)
def test_a_bad_result_is_refused_whole(kw, why):
    with pytest.raises(ValueError, match=why):
        ft.build_battery_record(recorded_at="t", **kw)


def test_the_mcp_action_writes_through_the_store_and_lists_the_trend(monkeypatch):
    from mcp import config as mcp_config, tools_fitness_tests as ftt

    t = FakeTable()
    monkeypatch.setattr(mcp_config, "table", t)
    monkeypatch.setattr("mcp.plan_hevy_windows._block_workouts", lambda day: [])
    out = ftt.action_log({"date": "2026-10-27", "results": {"bike_20min_rpe6": 8100}})
    assert out["wrote"] is True and out["sk"] == "BATTERY#2026-10-27"
    bad = ftt.action_log({"date": "2026-10-27", "test": "plank", "value": 3})
    assert bad["wrote"] is False and "unknown test" in bad["error"]
    view = ftt.action_list({"today": "2026-10-28"})
    assert view["trend"]["bike_20min_rpe6"]["latest"]["value"] == 8100.0 and view["trend"]["dead_hang"]["state"] == ft.ABSENT


def test_the_action_rides_get_exercise_notes(monkeypatch):
    from mcp import tools_training_notes as tn

    seen = []
    monkeypatch.setattr("mcp.tools_fitness_tests.action_log", lambda a: seen.append(("log", a)) or {"ok": 1})
    monkeypatch.setattr("mcp.tools_fitness_tests.action_list", lambda a: seen.append(("list", a)) or {"ok": 2})
    assert tn.tool_get_exercise_notes({"action": "fitness_test", "results": {}}) == {"ok": 1}
    assert tn.tool_get_exercise_notes({"action": "fitness_tests"}) == {"ok": 2}
    assert [k for k, _a in seen] == ["log", "list"]


# ── trend ─────────────────────────────────────────────────────────────────────────────────
def _batt(date, **tests):
    return {"date": date, "tests": {k: {"value": v, "unit": "u", "source": "explicit"} for k, v in tests.items()}}


def test_the_trend_reads_each_test_in_its_own_better_direction():
    b = ft.batteries(
        [_batt("2026-10-27", six_minute_walk=600, assisted_pull_up=70), _batt("2026-12-08", six_minute_walk=640, assisted_pull_up=60)]
    )
    tr = ft.trend(b)
    assert tr["six_minute_walk"]["delta"] == 40 and tr["six_minute_walk"]["direction"] == "better"
    assert tr["assisted_pull_up"]["delta"] == -10 and tr["assisted_pull_up"]["direction"] == "better"
    worse = ft.trend(ft.batteries([_batt("2026-10-27", assisted_pull_up=60), _batt("2026-12-08", assisted_pull_up=70)]))
    assert worse["assisted_pull_up"]["direction"] == "worse"
    assert tr["dead_hang"]["state"] == ft.ABSENT and tr["bike_20min_rpe6"]["state"] == ft.ABSENT
    first = ft.trend(ft.batteries([_batt("2026-10-27", dead_hang=30)]))
    assert first["dead_hang"]["direction"] == "first" and first["dead_hang"]["previous"] is None


# ── Hevy, the second reader ───────────────────────────────────────────────────────────────
def _ex(key, sets):
    return {"name": MOVEMENTS[key]["title"], "template_id": MOVEMENTS[key]["hevy_template_id_hint"], "sets": sets}


def _hevy_row(date, title, exercises):
    """The stored per-workout shape (hevy_common.normalize_workout): distance_m, duration_sec, weight_kg in Decimal."""
    return {"pk": "USER#matthew#SOURCE#hevy", "sk": f"DATE#{date}#WORKOUT#abc", "date": date, "title": title, "exercises": exercises}


def test_hevy_reads_a_titled_battery_and_ignores_an_ordinary_ride():
    battery = _hevy_row(
        "2026-10-27",
        "FITNESS TESTS — SHOULDERS+ARMS — W6 — 2026-10-27",
        [
            _ex("treadmill", [{"type": "normal", "duration_sec": Decimal("360"), "distance_m": Decimal("612")}]),
            _ex("dead_hang", [{"type": "warmup", "duration_sec": Decimal("90")}, {"type": "normal", "duration_sec": Decimal("38")}]),
            _ex(
                "pull_up_assisted",
                [{"type": "normal", "weight_kg": Decimal("31.75"), "reps": 5}, {"type": "normal", "weight_kg": Decimal("27.2"), "reps": 3}],
            ),
        ],
    )
    ride = _hevy_row(
        "2026-10-25", "Cardio", [_ex("cycling", [{"type": "normal", "duration_sec": Decimal("1200"), "distance_m": Decimal("8000")}])]
    )
    got = ft.from_hevy([battery, ride], MOVEMENTS)
    assert list(got) == ["2026-10-27"]
    t = got["2026-10-27"]
    assert t["six_minute_walk"]["value"] == 612.0 and t["dead_hang"]["value"] == 38.0  # the warm-up hang is not the test
    assert t["assisted_pull_up"]["value"] == 70.0  # 3 reps at less assistance is not 5 clean reps
    assert all(r["source"] == "hevy" for r in t.values())


def test_the_explicit_record_wins_over_hevy_per_test():
    hevy = {"2026-10-27": {"dead_hang": {"value": 38.0, "source": "hevy"}, "six_minute_walk": {"value": 612.0, "source": "hevy"}}}
    rec = ft.build_battery_record(date="2026-10-27", results={"dead_hang": 41}, recorded_at="t")
    (b,) = ft.batteries([rec], hevy)
    assert b["tests"]["dead_hang"]["value"] == 41.0 and b["tests"]["dead_hang"]["source"] == "explicit"
    assert b["tests"]["six_minute_walk"]["source"] == "hevy" and b["sources"] == ["explicit", "hevy"]


# ── the draft placement ───────────────────────────────────────────────────────────────────
def _entry(role, week):
    """A real ledger position (`session_sequence.preview` — the served week rule), as `next_session` serves it."""
    from training import session_sequence

    entry = next(e for e in session_sequence.preview(60, start_day="2026-10-19") if e["session_role"] == role and e["week"] == week)
    return {**entry, "source": "session_sequence"}


def _generate(entry, batteries):
    from training.routine_generator import GeneratorInputs, generate_routines

    with (
        patch("training.routine_generator._load_note_indexes", return_value=({}, {}, {}, {})),
        patch("training.routine_generator._schedule_entry_for_date", return_value=entry),
        patch("training.fitness_tests.load_records_failsoft", return_value=None),
    ):
        return generate_routines(
            GeneratorInputs(
                target_date=entry["date"], block_workouts=[], deload_records=[], disruption_records=[], fitness_batteries=batteries
            )
        )


def _ideal(rs):
    return next(r for r in rs if r.variant == "ideal")


def test_the_due_week_test_day_draft_carries_the_battery_on_its_minimum_session():
    from training import hevy_compiler, warmup_sets

    role = ft.test_day_role()
    ideal = _ideal(_generate(_entry(role, 6), []))
    keys = [b.movement_key for b in ideal.exercises]
    spec = ft.tests_spec()
    assert [k for k in keys if k in {r["catalog_key"] for r in spec.values()}] == [
        spec[s]["catalog_key"] for s in ft.protocol()["order"] if s in spec
    ]
    assert ideal.title.startswith(ft.BATTERY_TITLE) and len(ideal.notes) <= 150 and "Why:" in ideal.notes
    lifts = [b for b in ideal.exercises if b.rationale_tag.startswith("anchor:")]
    assert lifts and all(
        warmup_sets.working_set_count(b.sets) <= tc.charter_value("split.minimum_session.sets_per_movement") for b in lifts
    )
    assert not [b for b in ideal.exercises if b.rationale_tag.startswith("accessory")]
    fb = ideal.inputs_snapshot["fitness_battery"]
    assert fb["tests"] == [s for s in ft.protocol()["order"] if s in spec] and fb["charter_version"] == tc.charter_version()
    assert fb["unresolved"] == []
    body = hevy_compiler.to_create_body(ideal, lambda k: MOVEMENTS[k]["hevy_template_id_hint"])
    assert len(body["routine"]["exercises"]) == len(ideal.exercises)


def test_no_battery_on_a_lower_day_off_the_due_week_or_when_already_logged():
    role = ft.test_day_role()
    for entry, batts in (
        (_entry("lower_heavy", 6), []),
        (_entry(role, 5), []),
        (
            _entry(role, 6),
            [ft.build_battery_record(date=_entry(role, 6)["week_basis"]["week_opened_on"], results={"dead_hang": 40}, recorded_at="t")],
        ),
    ):
        ideal = _ideal(_generate(entry, batts))
        assert not ideal.title.startswith(ft.BATTERY_TITLE) and "fitness_battery" not in ideal.inputs_snapshot


def test_an_unreadable_record_serves_the_usual_session_and_says_so():
    ideal = _ideal(_generate(_entry(ft.test_day_role(), 6), None))
    assert not ideal.title.startswith(ft.BATTERY_TITLE)
    assert any("could not be read" in line for line in ideal.rationale)


def test_an_unresolved_minimum_session_serves_the_usual_session_and_never_a_guessed_shape(monkeypatch):
    real = tc.charter_value

    def no_minimum(dotted, default=None):
        return default if dotted.startswith("split.minimum_session") else real(dotted, default)

    monkeypatch.setattr(tc, "charter_value", no_minimum)
    with pytest.raises(ValueError):
        ft.minimum_shape()
    ideal = _ideal(_generate(_entry(ft.test_day_role(), 6), []))
    assert not ideal.title.startswith(ft.BATTERY_TITLE) and "fitness_battery" not in ideal.inputs_snapshot
    assert any("UNRESOLVED split.minimum_session" in line for line in ideal.rationale)


# ── the readers: absent path, May tracker, dead-man ──────────────────────────────────────
def test_the_may_tracker_section_is_absent_with_no_battery_and_measured_with_one():
    from training import may_tracker as mt

    absent = mt.fitness_section({"batteries": [], "due": {"state": ft.DUE}}, "2026-11-01")
    assert absent["state"] == "absent" and absent["due"]["state"] == ft.DUE
    b = ft.batteries([_batt("2026-10-27", dead_hang=40)])
    got = mt.fitness_section({"batteries": b, "due": None}, "2026-11-01")
    assert got["state"] == "measured" and got["value"]["dead_hang"]["latest"]["value"] == 40 and got["latest_date"] == "2026-10-27"
    before = mt.fitness_section({"batteries": b, "due": None}, "2026-10-25")
    assert before["state"] == "absent"  # a battery after the week's Sunday is not that week's
    assert mt.fitness_section(None, None, "ReadError: x")["state"] == "read_failed"


def test_the_dead_man_emits_missed_and_never_raises(monkeypatch, capsys):
    from mcp import tools_fitness_tests as ftt

    monkeypatch.setattr(ftt, "cadence", lambda today=None: {"state": ft.MISSED, "due_on": "2026-10-26", "basis": "block"})
    out = ftt.nightly_leg("2026-11-12")
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert (
        out["state"] == ft.MISSED
        and line[ftt.METRIC_NAME] == 1
        and line["_aws"]["CloudWatchMetrics"][0]["Namespace"] == ftt.METRIC_NAMESPACE
    )
    monkeypatch.setattr(ftt, "cadence", lambda today=None: {"state": ft.UNKNOWN})
    assert ftt.nightly_leg("2026-11-12")["state"] == ft.UNKNOWN and capsys.readouterr().out == ""

    def boom(today=None):
        raise RuntimeError("x")

    monkeypatch.setattr(ftt, "cadence", boom)
    assert ftt.nightly_leg("2026-11-12") == {"outcome": "failed", "error": "RuntimeError"}


def test_a_failed_record_read_claims_no_cadence_state(monkeypatch):
    from mcp import tools_fitness_tests as ftt

    def boom():
        raise RuntimeError("denied")

    monkeypatch.setattr(ftt, "_records", boom)
    monkeypatch.setattr("mcp.plan_hevy_windows._block_workouts", lambda day: [])
    view = ftt.read_view("2026-11-12")
    assert view["due"]["state"] == ft.UNKNOWN and view["reads"]["record"]["state"] == ft.READ_FAILED


def test_the_battery_partition_is_owner_only_and_cross_phase():
    from experiment import phase_taxonomy
    from privacy import field_tiers

    assert field_tiers.SOURCE_TIERS[ft.SOURCE] == field_tiers.TIER_OWNER_ONLY
    assert phase_taxonomy.SOURCE_CLASS[ft.SOURCE] == phase_taxonomy.CROSS_PHASE


def test_the_missed_alarm_reads_the_series_the_dead_man_emits():
    """The alarm in cdk/stacks/mcp_stack.py and the emitter's constants are one contract (#5078)."""
    import re

    from mcp import tools_fitness_tests as ftt

    src = (_REPO / "cdk" / "stacks" / "mcp_stack.py").read_text()
    m = re.search(
        r'"FitnessBatteryMissed",\s*alarm_name="fitness-battery-missed",(.*?)add_alarm_action\(cw_actions\.SnsAction\(local_digest_topic\)\)',
        src,
        re.S,
    )
    assert m, "the fitness-battery-missed alarm is gone from mcp_stack.py, or no longer routes to the digest"
    body = m.group(1)
    assert f'namespace="{ftt.METRIC_NAMESPACE}"' in body and f'metric_name="{ftt.METRIC_NAME}"' in body
    assert f"dimensions_map={ftt.METRIC_DIMENSIONS!r}".replace("'", '"') in body
    assert 'statistic="Maximum"' in body and "GREATER_THAN_OR_EQUAL_TO_THRESHOLD" in body and "NOT_BREACHING" in body
