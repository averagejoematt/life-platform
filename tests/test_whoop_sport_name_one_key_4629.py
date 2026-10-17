"""#4629 boxes 2 and 3 — a Whoop workout row carries the vendor's own sport name, and each workout id
is filed under exactly ONE date key: the UTC day it started (#4644 Q11, consistent with #3913).

The fixture is the wire: ``tests/fixtures/upstream/whoop/workout_day_4629.json`` is the archived
``raw.workouts`` payload for the UTC-day fetch of 2026-09-30 (``raw_date_key('whoop', ...)``),
verbatim except the ids and user id. It carries the three shapes that matter:

  records[0]  walking (sport id 63 — the removed table called it "Hiking"), started 09-30 23:14Z,
              ends 10-01 01:02Z: the next day's fetch returns it too
  records[1]  stretching (id 128 — the table stored ``Sport_128``), a null score, started 00:40Z
              on 09-30 — 17:40 PT on 09-29, so a Pacific frame would file it a day early
  records[2]  weightlifting (id 45 — the table called it "Cross Training"), STARTED 09-29 23:03Z
              and returned by 09-30's fetch only because it overlaps the window

Mutation controls (run by hand, recorded in the PR): restoring the id-table lookup reds the
sport-name test; filing every returned workout under the fetch day, or keying in Pacific, reds the
one-key tests.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
for _k, _v in {
    "S3_BUCKET": "test-bucket",
    "TABLE_NAME": "life-platform",
    "USER_ID": "matthew",
    "AWS_DEFAULT_REGION": "us-west-2",
    "AWS_REGION": "us-west-2",
}.items():
    os.environ.setdefault(_k, _v)

from common.pacific_time import parse_iso_utc  # noqa: E402
from content import story_dossier  # noqa: E402
from ingestion import whoop_lambda  # noqa: E402

_FIXTURE = os.path.join(ROOT, "tests", "fixtures", "upstream", "whoop", "workout_day_4629.json")
_EMPTY = {"records": []}


def _wire() -> dict:
    with open(_FIXTURE) as fh:
        return json.load(fh)


def _raw(records: list) -> dict:
    return {"recovery": _EMPTY, "sleep": _EMPTY, "cycle": _EMPTY, "workouts": {"records": records, "next_token": None}}


def _filed(day: str, records: list) -> dict:
    """workout id -> the date key transform() files it under, for one day's fetch."""
    return {it["workout_id"]: it["date"] for it in whoop_lambda.transform(_raw(records), day) if "workout_id" in it}


# ── box 2: sport_name is the payload's own ───────────────────────────────────────────────────


def test_sport_name_is_the_vendors_label_on_the_real_wire():
    recs = _wire()["records"]
    got = [(f["sport_id"], f.get("sport_name"), f.get("vendor_sport_name")) for f in map(whoop_lambda._extract_workout, recs)]
    assert got == [
        (63, "walking", "walking"),  # the removed table: "Hiking"
        (128, "stretching", "stretching"),  # the removed table: "Sport_128"
        (45, "weightlifting", "weightlifting"),  # the removed table: "Cross Training"
    ]


def test_the_hand_written_sport_table_is_gone():
    assert not hasattr(whoop_lambda, "WHOOP_SPORT_NAMES")
    src = open(whoop_lambda.__file__).read()
    assert 'f"Sport_{' not in src, "a Sport_<id> fallback label is a guessed name (ADR-104)"


# ── box 3: one date key per workout id, the UTC start day ────────────────────────────────────


def test_a_fetch_files_only_the_workouts_that_started_on_its_utc_day():
    recs = _wire()["records"]
    filed = _filed(_wire()["fetch_day"], recs)
    assert filed == {recs[0]["id"]: "2026-09-30", recs[1]["id"]: "2026-09-30"}  # records[2] started 09-29
    assert recs[2]["id"] not in filed


def test_each_workout_id_lands_under_exactly_one_key_across_the_overlapping_fetches():
    """The vendor returns every workout that OVERLAPS a fetch window, so each day's fetch here is
    handed exactly the records overlapping [day T00:00Z, next T00:00Z) — the walk comes back from
    09-30 and 10-01, the lift from 09-29 and 09-30. Across all three, each id is filed once, under
    its UTC start day."""
    recs = _wire()["records"]
    keys: dict = {}
    returned: dict = {}
    for day in ("2026-09-29", "2026-09-30", "2026-10-01"):
        lo = datetime.fromisoformat(f"{day}T00:00:00+00:00")
        window = [r for r in recs if parse_iso_utc(r["start"]) < lo + timedelta(days=1) and parse_iso_utc(r["end"]) > lo]
        returned[day] = len(window)
        for wid, d in _filed(day, window).items():
            keys.setdefault(wid, []).append(d)
    assert returned == {"2026-09-29": 1, "2026-09-30": 3, "2026-10-01": 1}  # two ids come back twice
    assert keys == {
        recs[0]["id"]: ["2026-09-30"],  # crosses into 10-01, filed on its start day only
        recs[1]["id"]: ["2026-09-30"],  # 17:40 PT on 09-29 — the frame is UTC, not Pacific
        recs[2]["id"]: ["2026-09-29"],  # crosses into 09-30, filed on its start day only
    }


def test_a_workout_with_no_start_stays_under_the_day_that_fetched_it():
    rec = dict(_wire()["records"][0], start=None)
    assert _filed("2026-10-01", [rec]) == {rec["id"]: "2026-10-01"}


def test_the_writer_frame_is_the_reconcilers_expected_key():
    """One frame, two users: the writer's filter and the reconciler's expected DATE# key are the
    same ``_utc_day``, so the store and the reconciliation can never disagree on a workout's day."""
    for rec in _wire()["records"]:
        day = whoop_lambda._utc_day(rec["start"])
        assert whoop_lambda.workout_files_under(rec, day)
        missing = whoop_lambda._records_missing_from_store([], [rec], {f"DATE#{day}#WORKOUT#{rec['id']}"}, [])
        assert missing == []


# ── consumers: both vocabularies read alike until the owner's relabel ────────────────────────


def _dossier_cardio(rows: list, monkeypatch) -> list:
    monkeypatch.setattr(story_dossier, "_rows", lambda table, source, start, end: rows if source == "whoop" else [])
    monkeypatch.setattr(story_dossier, "_days", lambda *a, **k: {})
    return story_dossier._training(None, {"start": "2026-09-28", "end": "2026-10-04"})["cardio_and_walks_whoop"]


def _row(rec: dict, day: str, sport_name: str | None, vendor: bool) -> dict:
    f = whoop_lambda._extract_workout(rec)
    if not vendor:  # a pre-#4629 row: the table label, no vendor field
        f.pop("vendor_sport_name", None)
        f["sport_name"] = sport_name
    f["average_heart_rate"] = f.get("average_heart_rate") or 100
    return {"sk": f"DATE#{day}#WORKOUT#{rec['id']}", "date": day, "workout_id": rec["id"], **f}


def test_story_dossier_filters_the_lift_and_the_stretch_in_both_vocabularies(monkeypatch):
    walk, stretch, lift = _wire()["records"]
    new = [_row(walk, "2026-09-30", None, True), _row(stretch, "2026-09-30", None, True), _row(lift, "2026-09-29", None, True)]
    old = [
        _row(walk, "2026-09-30", "Hiking", False),
        _row(stretch, "2026-09-30", "Sport_128", False),
        _row(lift, "2026-09-29", "Cross Training", False),
    ]
    assert [c["sport"] for c in _dossier_cardio(new, monkeypatch)] == ["walking"]
    assert [c["sport"] for c in _dossier_cardio(old, monkeypatch)] == ["Hiking"]  # history keeps its label until relabelled


# ── the dry-run history report (no write mode) ───────────────────────────────────────────────


def _report_module():
    spec = importlib.util.spec_from_file_location(
        "whoop_workout_history_4629", os.path.join(ROOT, "scripts", "whoop_workout_history_4629.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_history_report_counts_the_duplicate_keys_in_the_writers_frame():
    mod = _report_module()
    assert mod._utc_day is whoop_lambda._utc_day  # the report can never key differently from the writer
    walk, stretch, lift = _wire()["records"]

    def stored(rec, day, label):
        return {
            "sk": f"DATE#{day}#WORKOUT#{rec['id']}",
            "workout_id": rec["id"],
            "start_time": rec["start"],
            "sport_id": rec["sport_id"],
            "sport_name": label,
        }

    rows = [
        stored(walk, "2026-09-30", "Hiking"),
        stored(walk, "2026-10-01", "Hiking"),  # the pre-#4629 second copy
        stored(stretch, "2026-09-30", "Sport_128"),
        stored(lift, "2026-09-30", "Cross Training"),  # only copy, under the wrong day
        {"sk": "DATE#2026-09-30", "strain": 9},  # a day row is not a workout row
    ]
    assert mod.tally_keys(rows) == {
        "distinct_workout_ids": 3,
        "ids_under_two_or_more_keys": 1,
        "ids_with_no_row_on_start_day": 1,
        "ids_with_no_row_on_start_day_and_two_keys": 0,
        "rows_off_start_day": 1,
        "rows_without_start_time": 0,
        "workout_rows": 4,
    }

    by_wid, by_sport = mod.archive_labels({"2026-09-30": {"raw": {"workouts": _wire()}}})
    plan = mod.plan_relabel(rows, by_wid, by_sport)
    assert plan["label_changes"] == {"Hiking -> walking": 2, "Sport_128 -> stretching": 1, "Cross Training -> weightlifting": 1}
    assert plan["rows_relabel_from_archive"] == 4 and plan["rows_unresolved"] == 0


def test_history_report_refuses_to_run_without_dry_run_and_has_no_write_path(capsys):
    mod = _report_module()
    assert mod.main([]) == 2
    assert "no write mode" in capsys.readouterr().out
    body = open(os.path.join(ROOT, "scripts", "whoop_workout_history_4629.py")).read()
    for verb in ("put_item", "update_item", "delete_item", "batch_writer", "--apply"):
        assert verb not in body, f"the history report grew a write path ({verb}) — the removal and relabel are the owner's"
