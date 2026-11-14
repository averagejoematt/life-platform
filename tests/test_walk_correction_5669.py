"""tests/test_walk_correction_5669.py — the owner's correction for the 2026-10-20 walk (#5669).

THE RULING (owner, 2026-11-09)

The 2026-10-20 outdoor walk counts at 55 minutes. It was dropped by the #4638 Strava tombstone and must
never count the 174-min WHOOP span. Vendor partitions hold vendor data only, so the ruling is a
`WALK_CORRECTION#2026-10-20` row in the owner-only `training_constraints` partition, and the walking layer
counts it as a labelled walk (`owner_correction`) — never blended into a device source.

THE FIXTURES are the wire: the WHOOP workout, habit row and Strava copy are the live rows PR #5698's
tests pin (field-projected), and the correction row is the exact item `scripts/write_walk_correction.py`
builds.

EACH TEST NAMES THE MUTATION THAT REDS IT; each claim has a negative control beside it.
"""

from __future__ import annotations

import importlib.util
import os
from decimal import Decimal
from pathlib import Path

for _k, _v in {
    "S3_BUCKET": "test-bucket",
    "TABLE_NAME": "life-platform",
    "USER_ID": "matthew",
    "AWS_DEFAULT_REGION": "us-west-2",
    "AWS_REGION": "us-west-2",
}.items():
    os.environ.setdefault(_k, _v)

import pytest  # noqa: E402
from training import (  # noqa: E402
    recent_aerobic as ra,
    walking_volume as wv,
)

DAY = "2026-10-20"
WHOOP_WALK = {
    "pk": "USER#matthew#SOURCE#whoop",
    "sk": "DATE#2026-10-20#WORKOUT#5f70ea18-0cf3-485c-8527-8c184b8423de",
    "date": DAY,
    "workout_id": "5f70ea18-0cf3-485c-8527-8c184b8423de",
    "sport_name": "walking",
    "start_time": "2026-10-20T23:09:23.734Z",
    "end_time": "2026-10-21T02:03:37.542Z",
    "zone_0_minutes": "113.03",
    "zone_1_minutes": "52.37",
    "zone_2_minutes": "5.72",
    "zone_3_minutes": "3.08",
    "zone_4_minutes": "0.03",
    "zone_5_minutes": "0",
}
HABIT_DAY = {
    "sk": "DATE#2026-10-20",
    "date": DAY,
    "habit_statuses": {"Walk Outdoor >2mi": {"aliases": ["Walk 5k"], "status": "completed"}, "Cold Shower": {"status": "failed"}},
}
OTHER_DAY_STRAVA = {
    "date": "2026-10-19",
    "activities": [{"sport_type": "Walk", "start_date": "2026-10-19T13:21:29Z", "moving_time_seconds": 2705, "elapsed_time_seconds": 2705}],
}


# A lifting session with no counted cardio: Hevy is READ (0 h), so the total's floor flag speaks only to the walk.
HEVY_LIFT = {
    "date": "2026-10-19",
    "start_time": "2026-10-19T17:00:00Z",
    "end_time": "2026-10-19T18:00:00Z",
    "exercises": [{"name": "Squat (Barbell)", "sets": [{"reps": 5, "weight_kg": 80}]}],
}


def _strava_walk_on_the_day(minutes: int) -> dict:
    """The 10-20 Strava copy as it was ingested, at `minutes` of moving time."""
    return {
        "date": DAY,
        "activities": [
            {
                "strava_id": "20669407754",
                "sport_type": "Walk",
                "device_name": "WHOOP",
                "start_date": "2026-10-20T23:09:23Z",
                "moving_time_seconds": minutes * 60,
                "elapsed_time_seconds": minutes * 60,
            }
        ],
    }


def _writer():
    path = Path(__file__).resolve().parent.parent / "scripts" / "write_walk_correction.py"
    spec = importlib.util.spec_from_file_location("write_walk_correction_5669", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


WRITER = _writer()
BASIS = "owner ruling 2026-11-09: the outdoor walk was 55 min of walking; the WHOOP auto-detect span (174 min) over-ran it"
ARGS = ["--date", DAY, "--minutes", "55", "--basis", BASIS, "--ruled-at", "2026-11-09", "--issue", "#5669"]
# The row exactly as the writer builds it (the read path gets Decimal back from DynamoDB, as here).
CORRECTION = WRITER.build_item(day=DAY, minutes=55, basis=BASIS, ruled_by="owner", ruled_at="2026-11-09", issue="#5669")


def _build(strava, corrections, start="2026-10-19", end=DAY):
    inputs = {"whoop": [WHOOP_WALK], "habitify": [HABIT_DAY]}
    if corrections is not wv.NOT_WIRED:
        inputs[wv.CORRECTION_INPUT] = corrections
    return wv.build(window_start=start, window_end=end, strava_items=strava, hevy_workouts=[HEVY_LIFT], completeness_inputs=inputs)


def _gaps(layer):
    return [(g["date"], g["signal"]) for g in layer["completeness"]["gaps"]]


# ── the weekly layer ──────────────────────────────────────────────────────────────────


def test_the_correction_counts_55_minutes_and_clears_the_10_20_gap():
    """Mutation controls: drop `c_counted` from `every` — reds on the total; drop the `resolve_gaps` call —
    reds on the gaps and the floor; drop the `by_source[CORRECTION_METHOD]` block — reds on the label."""
    layer = _build([OTHER_DAY_STRAVA], [CORRECTION])
    assert layer["total_hr"] == round((2705 + 55 * 60) / 3600.0, 2) == 1.67
    assert layer["by_modality"]["walking"] == 1.67
    assert _gaps(layer) == []
    assert layer["total_is_floor"] is False
    assert sorted((g["date"], g["resolved_by"]) for g in layer["completeness"]["resolved"]) == [
        (DAY, "owner_correction"),
        (DAY, "owner_correction"),
    ]
    block = layer["by_source"]["owner_correction"]
    assert block["method"] == "owner_correction" and block["hours"] == 0.92 and block["sessions"] == 1
    assert layer["by_source"]["strava"]["hours"] == 0.75  # never blended into the device source
    applied = layer["owner_corrections"]["applied"]
    assert applied == [
        {
            "date": DAY,
            "minutes": 55.0,
            "kind": "outdoor_walk",
            "method": "owner_correction",
            "basis": BASIS,
            "ruled_by": "owner",
            "ruled_at": "2026-11-09",
            "issue": "#5669",
        }
    ]
    assert any(h.startswith(DAY) and "owner_correction" in h and "55 min" in h for h in layer["honesty"])
    assert layer["version"] == "walking-volume@1.4.0"


def test_the_correction_never_counts_the_whoop_span():
    """The WHOOP auto-detect spans 174 min; only the ruled 55 count. Mutation control: count the gap's
    `span_minutes` instead of the row's `minutes` — reds."""
    layer = _build([], [CORRECTION])
    whoop_gap = next(g for g in layer["completeness"]["resolved"] if g["signal"] == "whoop_walk_workout")
    assert whoop_gap["span_minutes"] == 174.2
    assert layer["total_hr"] == 0.92


def test_negative_control_no_correction_the_gap_stays_a_floor():
    """The same week with no correction row (read, empty) and with the corrections not wired: the gap
    stands and the total is a floor. Mutation control: resolve gaps on any correction READ — reds."""
    for corrections in ([], wv.NOT_WIRED):
        layer = _build([OTHER_DAY_STRAVA], corrections)
        assert layer["total_hr"] == 0.75
        assert layer["total_is_floor"] is True
        assert _gaps(layer) == [(DAY, "walk_habit_completed"), (DAY, "whoop_walk_workout")]
        assert "owner_correction" not in layer["by_source"]
        assert not any("owner_correction" in h for h in layer["honesty"])
    assert _build([OTHER_DAY_STRAVA], [])["owner_corrections"]["status"] == "read"
    assert _build([OTHER_DAY_STRAVA], wv.NOT_WIRED)["owner_corrections"]["status"] == "not_checked"


def test_a_correction_beside_an_overlapping_counted_walk_is_a_conflict_never_110_minutes():
    """A counted 55-min walk on 10-20 plus the 55-min correction is ONE walk: 55 min, a conflict line,
    nothing added. Mutation control: drop the `same_day` branch in `apply_corrections` — reds (1.83 h)."""
    layer = _build([_strava_walk_on_the_day(55)], [CORRECTION])
    assert layer["total_hr"] == 0.92  # 55 min, not 110
    assert layer["owner_corrections"]["applied"] == []
    conflict = layer["owner_corrections"]["conflicts"]
    assert conflict == [{"date": DAY, "correction_minutes": 55.0, "counted_minutes": 55.0, "counted_sources": ["strava"], "issue": "#5669"}]
    assert any(h.startswith(f"{DAY}: CONFLICT") and "NOT added" in h for h in layer["honesty"])
    assert "owner_correction" not in layer["by_source"]


def test_negative_control_a_correction_on_a_day_with_no_counted_walk_is_added_not_a_conflict():
    """The counted walk on ANOTHER day (10-19) is no conflict for 10-20. Mutation control: judge conflicts
    over the whole window instead of the day — reds."""
    layer = _build([OTHER_DAY_STRAVA], [CORRECTION])
    assert layer["owner_corrections"]["conflicts"] == []
    assert not any("CONFLICT" in h for h in layer["honesty"])


def test_an_unreadable_correction_read_is_said_and_the_gap_stays():
    """Mutation control: treat a None read as an empty one — reds on the honesty line."""
    layer = _build([OTHER_DAY_STRAVA], None)
    assert layer["owner_corrections"]["status"] == "unreadable"
    assert any("could not be read" in h and "WALK_CORRECTION#" in h for h in layer["honesty"])
    assert layer["total_is_floor"] is True and layer["total_hr"] == 0.75
    # control: a readable empty partition says nothing
    assert not any("WALK_CORRECTION#" in h for h in _build([OTHER_DAY_STRAVA], [])["honesty"])


def test_a_correction_is_held_while_a_device_source_is_unread():
    """With Strava unread a counted walk on the day cannot be ruled out. Mutation control: drop the
    `sources_read` branch — reds (the correction is added over an unread Strava)."""
    layer = _build(None, [CORRECTION])
    assert layer["owner_corrections"]["applied"] == [] and layer["owner_corrections"]["held"][0]["date"] == DAY
    assert "owner_correction" not in layer["by_source"]
    assert _build([OTHER_DAY_STRAVA], [CORRECTION])["owner_corrections"]["held"] == []  # control


def test_a_malformed_or_foreign_row_is_never_counted():
    """A REQUEST# row in the same partition is ignored; a correction with a wrong kind or source is refused
    and named. Mutation control: drop the `source`/`kind` check — reds."""
    request = {"pk": wv.CORRECTION_PK, "sk": "REQUEST#2026-10-20#w#t#0", "date": DAY, "minutes": 55}
    wrong_kind = {**CORRECTION, "kind": "treadmill"}
    wrong_source = {**CORRECTION, "source": "strava"}
    for rows in ([request], [wrong_kind], [wrong_source]):
        layer = _build([OTHER_DAY_STRAVA], rows)
        assert layer["total_hr"] == 0.75 and layer["total_is_floor"] is True
    assert any("refused" in h for h in _build([OTHER_DAY_STRAVA], [wrong_kind])["honesty"])


def test_a_correction_outside_the_window_is_not_counted():
    layer = _build([], [CORRECTION], start="2026-10-12", end="2026-10-18")
    assert layer["owner_corrections"]["applied"] == [] and "owner_correction" not in layer["by_source"]
    assert layer["total_hr"] == 0.0


# ── the recent-aerobic block (the plan, the generator's z2 minutes) ───────────────────


def _block(strava, corrections):
    inputs = {"whoop": [WHOOP_WALK], "habitify": [HABIT_DAY], wv.CORRECTION_INPUT: corrections}
    return ra.build(target_date="2026-10-22", today="2026-10-25", strava_items=strava, hevy_workouts=[], completeness_inputs=inputs)


def _walk(day: str, hour_utc: int, minutes: int) -> dict:
    return {
        "date": day,
        "activities": [
            {
                "sport_type": "Walk",
                "start_date": f"{day}T{hour_utc:02d}:00:00Z",
                "moving_time_seconds": minutes * 60,
                "elapsed_time_seconds": minutes * 60,
            }
        ],
    }


def test_the_recent_aerobic_block_counts_the_correction_as_a_labelled_row():
    """Mutation control: drop `c_rows` from the block's rows — reds; drop `out["method"]` in `_public_row` — reds."""
    b = _block([_walk("2026-10-19", 15, 45)], [CORRECTION])
    row = next(r for r in b["rows"] if r["date"] == DAY)
    assert row["source"] == "owner_correction" and row["method"] == "owner_correction" and row["moving_min"] == 55.0
    assert row["start_utc"] is None and row["avg_hr"] is None
    assert b["completeness"]["gaps"] == [] and b["totals_are_floor"] is False
    assert b["totals"]["trailing_7d"]["hours"] == round((45 + 55) / 60.0, 2)
    assert ra.aerobic_minutes_7d(b) == round(round(100 / 60.0, 2) * 60.0, 1) == 100.2  # the block's hours rounding
    walks = b["totals"]["standalone_walks"]["trailing_7d"]["walks"]
    assert any(w["date"] == DAY and w["method"] == "owner_correction" for w in walks)
    assert b["version"] == "recent-aerobic@1.4.0"  # 1.4.0 (#5916): heart rate is a measurement with its basis, never graded


def test_negative_control_recent_aerobic_without_a_correction_is_unknown():
    b = _block([_walk("2026-10-19", 15, 45)], [])
    assert {g["date"] for g in b["completeness"]["gaps"]} == {DAY}
    assert ra.aerobic_minutes_7d(b) is None
    assert not any(r.get("method") for r in b["rows"])


def test_the_recent_aerobic_conflict_is_one_walk():
    b = _block([_strava_walk_on_the_day(55)], [CORRECTION])
    assert [r["source"] for r in b["rows"] if r["date"] == DAY] == ["strava"]
    assert b["owner_corrections"]["conflicts"][0]["date"] == DAY
    assert any("CONFLICT" in h for h in b["honesty"])


# ── the readers: every one #5698 wired gets the corrections through the shared read ──


def _reader(by_source):
    def read(source, start, end):
        return [r for r in by_source.get(source, []) if start <= str(r.get("date") or "")[:10] <= end]

    return read


SOURCES = {"strava": [_walk("2026-10-19", 15, 45)], "hevy": [HEVY_LIFT], "whoop": [WHOOP_WALK], "habitify": [HABIT_DAY]}


class _Table:
    """A table double that applies the correction query's string KeyConditionExpression, paginating one row a page."""

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def query(self, **kw):
        self.calls.append(kw)
        v = kw["ExpressionAttributeValues"]
        assert kw["KeyConditionExpression"] == "pk = :pk AND sk BETWEEN :lo AND :hi"
        hits = [r for r in self.rows if r["pk"] == v[":pk"] and v[":lo"] <= r["sk"] <= v[":hi"]]
        i = int(kw.get("ExclusiveStartKey", {}).get("i", 0))
        page = hits[i : i + 1]
        resp = {"Items": page}
        if i + 1 < len(hits):
            resp["LastEvaluatedKey"] = {"i": i + 1}
        return resp


def test_query_corrections_reads_the_window_pages_and_drops_tombstones():
    rows = [
        CORRECTION,
        {**CORRECTION, "sk": "WALK_CORRECTION#2026-10-21"},
        {**CORRECTION, "sk": "WALK_CORRECTION#2026-10-30"},
        {**CORRECTION, "sk": "WALK_CORRECTION#2026-10-19", "tombstone": True},
        {**CORRECTION, "pk": "USER#matthew#SOURCE#strava"},
    ]
    t = _Table(rows)
    got = wv.query_corrections(t, "2026-10-19", "2026-10-21")
    assert [r["sk"] for r in got] == ["WALK_CORRECTION#2026-10-20", "WALK_CORRECTION#2026-10-21"]
    assert len(t.calls) == 3  # paginated


@pytest.fixture
def corrections(monkeypatch):
    """Route the shared read's correction query to a table double holding the 10-20 row."""
    from mcp import shared_quantities as sq

    table = _Table([CORRECTION])
    monkeypatch.setattr(sq._core, "table", table)
    return table


def test_every_shared_reader_counts_the_correction(corrections, monkeypatch):
    """walking_layer, walking_layer_for_day, recent_aerobic_layer, z2_minutes_7d and weekly_walking_hours.
    Mutation control: drop the `_read_corrections` line from `_read_signals` — reds on every reader."""
    from mcp import shared_quantities as sq

    read = _reader(SOURCES)
    week = sq.walking_layer("2026-10-22", today="2026-10-25", read=read)
    assert week["owner_corrections"]["applied"][0]["date"] == DAY and week["total_is_floor"] is False
    assert week["total_hr"] == 1.67
    day = sq.walking_layer_for_day(DAY, today="2026-10-25", read=read, with_apple=False)
    assert day["by_source"]["owner_correction"]["hours"] == 0.92 and day["completeness"]["gaps"] == []
    block = sq.recent_aerobic_layer("2026-10-22", today="2026-10-25", read=read)
    assert any(r.get("method") == "owner_correction" for r in block["rows"])
    assert sq.z2_minutes_7d("2026-10-22", today="2026-10-25", read=read) == 100.2
    monkeypatch.setattr(sq._core, "query_source_range", read)
    assert sq.weekly_walking_hours("2026-10-22", today="2026-10-25") == 1.67


def test_negative_control_the_shared_readers_without_the_row(monkeypatch):
    """The same reads over an empty correction partition keep the 10-20 gap; a raising read is said."""
    from mcp import shared_quantities as sq

    read = _reader(SOURCES)
    monkeypatch.setattr(sq._core, "table", _Table([]))
    assert sq.walking_layer("2026-10-22", today="2026-10-25", read=read)["total_is_floor"] is True
    assert sq.z2_minutes_7d("2026-10-22", today="2026-10-25", read=read) is None

    class _Down:
        def query(self, **_kw):
            raise RuntimeError("ddb down")

    monkeypatch.setattr(sq._core, "table", _Down())
    layer = sq.walking_layer("2026-10-22", today="2026-10-25", read=read)
    assert layer["owner_corrections"]["status"] == "unreadable" and layer["total_is_floor"] is True


def test_the_routine_cron_counts_the_correction(monkeypatch):
    """Mutation control: drop the `_read_corrections` line from the cron's `_signals` — reds (None)."""
    from operational import hevy_routine_cron_lambda as cron
    from training import exercise_history

    monkeypatch.setattr(exercise_history, "_table", lambda: _Table([CORRECTION]))
    assert cron._z2_minutes_7d("2026-10-22", read=_reader(SOURCES)) == 100.2
    monkeypatch.setattr(exercise_history, "_table", lambda: _Table([]))
    assert cron._z2_minutes_7d("2026-10-22", read=_reader(SOURCES)) is None  # control: no row, the gap stands


# ── the writer ────────────────────────────────────────────────────────────────────────


class _Recording:
    def __init__(self):
        self.puts = []

    def put_item(self, **kw):
        self.puts.append(kw)


def test_the_writer_dry_run_writes_nothing(monkeypatch, capsys):
    """Mutation control: make `--apply` default True — reds (a put recorded)."""

    def _no_table():
        raise AssertionError("the dry run must not even build a table")

    monkeypatch.setattr(WRITER, "_table", _no_table)
    t = _Recording()
    assert WRITER.main(ARGS, table=t) == 0
    assert t.puts == []
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "WALK_CORRECTION#2026-10-20" in out and '"minutes": 55.0' in out


def test_negative_control_the_writer_apply_puts_one_conditional_row(capsys):
    t = _Recording()
    assert WRITER.main(ARGS + ["--apply"], table=t) == 0
    assert len(t.puts) == 1
    put = t.puts[0]
    assert put["ConditionExpression"] == "attribute_not_exists(sk)"
    item = put["Item"]
    assert item["pk"] == "USER#matthew#SOURCE#training_constraints" and item["sk"] == "WALK_CORRECTION#2026-10-20"
    assert item["minutes"] == Decimal("55") and item["source"] == "owner_correction" and item["kind"] == "outdoor_walk"
    assert item["ruled_by"] == "owner" and item["ruled_at"] == "2026-11-09" and item["issue"] == "#5669" and item["basis"] == BASIS
    assert "phase" not in item  # CROSS_PHASE: never stamped
    assert "stored:" in capsys.readouterr().out


def test_the_writer_refuses_an_existing_row_and_a_malformed_one(capsys):
    class _Exists:
        def put_item(self, **_kw):
            e = Exception("exists")
            e.response = {"Error": {"Code": "ConditionalCheckFailedException"}}
            raise e

    assert WRITER.main(ARGS + ["--apply"], table=_Exists()) == 1
    assert "already exists" in capsys.readouterr().out
    t = _Recording()
    assert (
        WRITER.main(["--date", DAY, "--minutes", "0", "--basis", "x", "--ruled-at", "2026-11-09", "--issue", "#5669", "--apply"], table=t)
        == 2
    )
    assert WRITER.main(ARGS[:1] + ["2026-13-40"] + ARGS[2:] + ["--apply"], table=t) == 2
    assert t.puts == []
