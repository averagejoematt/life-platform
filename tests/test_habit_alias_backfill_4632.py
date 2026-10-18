"""#4632 box 1 (#4644 Q26 "applied to the history too") — `scripts/habit_alias_backfill_4632.py`.

The stored rows here are the WRITER's own output: `habitify_lambda.transform` over the committed live
capture `tests/fixtures/habitify/habitify_2026-09-06_wire.json`, with the three post-#4921 fields
(`habit_id`, `aliases`, `status_channel`) stripped to reproduce the pre-#4921 row shape read read-only
from `DATE#2026-08-10` (entry keys: current_value, group, periodicity, scheduled_today, status,
target_value; 61 entries, 0 with habit_id). The archive payloads are the framework envelope
`{fetched_at, raw: {area_map, date, journal, moods, notes}}` read read-only from
`raw/matthew/habitify/2026/08/2026-08-10.json` (61 journal entries, 61 unique ids), with the wire
fixture's journal inside. Only Collagen, a public supplement habit (#4333), is renamed.

Run:  python3 -m pytest tests/test_habit_alias_backfill_4632.py -v
"""

import copy
import importlib.util
import json
import os
import sys
from decimal import Decimal

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

from ingestion import habitify_lambda  # noqa: E402
from ingestion.habitify_lambda import reset_identity_cache, transform  # noqa: E402

_SPEC = importlib.util.spec_from_file_location("habit_alias_backfill_4632", os.path.join(ROOT, "scripts", "habit_alias_backfill_4632.py"))
bf = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bf)

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "habitify", "habitify_2026-09-06_wire.json")
OLD, NEW, NEWER = "Collagen", "Collagen Peptides", "Collagen (Marine)"
D1, D2, D3, D4 = "2026-08-01", "2026-08-09", "2026-08-15", "2026-10-16"
POST_4921_FIELDS = ("habit_id", "aliases", "status_channel")


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(habitify_lambda, "pacific_today", lambda: "2026-10-17")  # every fixture day is CLOSED
    monkeypatch.setattr(habitify_lambda, "_ALIAS_GROUPS_CACHE", [])
    monkeypatch.setattr(habitify_lambda, "_CORRECTION_DATES", frozenset())
    reset_identity_cache()
    yield
    reset_identity_cache()


def _wire():
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)


def _renamed(wire, old, new):
    w = copy.deepcopy(wire)
    for e in w["journal"]:
        if e["name"] == old:
            e["name"] = new
    w["logs"][new] = w["logs"].pop(old)
    return w


def _archive(wire, day):
    """The framework envelope as it sits in S3 (shape read read-only from the 2026-08-10 object)."""
    raw = {"area_map": wire["area_map"], "date": day, "journal": wire["journal"], "moods": [], "notes": {}}
    return {"fetched_at": f"{day}T14:00:00+00:00", "raw": raw}


def _stored(wire, day, pre_4921=True):
    """The writer's row for `day`; pre-#4921 rows carried no id, aliases or channel."""
    row = transform({"date": day, "area_map": wire["area_map"], "journal": wire["journal"], "moods": [], "logs": wire["logs"]}, day)[0]
    row["sk"] = f"DATE#{day}"
    row["updated_at"] = f"{day}T14:05:00+00:00"
    if pre_4921:
        for hs in row["habit_statuses"].values():
            for f in POST_4921_FIELDS:
                hs.pop(f, None)
    return row


def _id_of(wire, name):
    return next(e["id"] for e in wire["journal"] if e["name"] == name)


def _history():
    """Three pre-#4921 days (a rename between D2 and D3) and one post-#4921 day under a third name."""
    w1, w2, w3 = _wire(), _renamed(_wire(), OLD, NEW), _renamed(_wire(), OLD, NEWER)
    rows = [_stored(w1, D1), _stored(w1, D2), _stored(w2, D3), _stored(w3, D4, pre_4921=False)]
    archive = {D1: _archive(w1, D1), D2: _archive(w1, D2), D3: _archive(w2, D3), D4: _archive(w3, D4)}
    return rows, archive, w1


def test_the_pre_4921_rows_match_the_stored_shape_and_carry_no_id():
    rows, _, _ = _history()
    entry = next(iter(rows[0]["habit_statuses"].values()))
    assert set(entry) >= {"current_value", "periodicity", "scheduled_today", "status", "target_value"}
    assert not any(f in hs for hs in rows[0]["habit_statuses"].values() for f in POST_4921_FIELDS)
    assert isinstance(entry["current_value"], Decimal)


def test_every_pre_4921_entry_gains_its_vendor_id_from_the_days_archive():
    rows, archive, w1 = _history()
    counts, rewrites = bf.plan(rows, archive)
    n = len(w1["journal"])
    assert counts["entries_gaining_id"] == 3 * n
    assert counts["entries_with_id_already"] == n
    assert counts["entries_without_id"] == 0
    assert counts["days_archive_missing"] == 0
    first, _ = rewrites[f"DATE#{D1}"]
    assert all(hs["habit_id"] == _id_of(w1, name) for name, hs in first.items())
    assert first["Creatine"]["current_value"] == rows[0]["habit_statuses"]["Creatine"]["current_value"]


def test_a_rename_mid_history_yields_one_id_and_the_alias_chain_carries_forward():
    rows, archive, w1 = _history()
    counts, rewrites = bf.plan(rows, archive)
    cid = _id_of(w1, OLD)
    d1, d2, d3, d4 = (rewrites[f"DATE#{d}"][0] for d in (D1, D2, D3, D4))
    assert "aliases" not in d1[OLD] and "aliases" not in d2[OLD]  # the first name has nothing earlier
    assert d3[NEW]["habit_id"] == cid and d3[NEW]["aliases"] == [OLD]
    assert d4[NEWER]["habit_id"] == cid and d4[NEWER]["aliases"] == [OLD, NEW]
    assert "aliases" not in d3["Creatine"]  # a habit that was never renamed carries none
    assert counts["ids_with_more_than_one_name"] == 1
    assert counts["entries_gaining_aliases"] == 2
    assert counts["rows_to_rewrite"] == 4  # the post-#4921 row is rewritten for its aliases alone


def test_the_backfilled_rows_are_what_the_writer_derives_forward():
    """The ingest's own prior-day derivation over the back-filled D3 row stamps the same aliases on D4."""
    rows, archive, _ = _history()
    _, rewrites = bf.plan(rows, archive)
    d3 = dict(rows[2], habit_statuses=rewrites[f"DATE#{D3}"][0])
    reset_identity_cache(lambda _d: habitify_lambda.identity_from_record(d3))
    w3 = _renamed(_wire(), OLD, NEWER)
    live = transform({"date": D4, "area_map": w3["area_map"], "journal": w3["journal"], "moods": [], "logs": w3["logs"]}, D4)[0]
    assert live["habit_statuses"][NEWER]["aliases"] == rewrites[f"DATE#{D4}"][0][NEWER]["aliases"] == [OLD, NEW]


def test_a_second_pass_over_the_rewritten_rows_is_a_no_op():
    rows, archive, _ = _history()
    _, rewrites = bf.plan(rows, archive)
    rewritten = [dict(r, habit_statuses=rewrites.get(r["sk"], (r["habit_statuses"],))[0]) for r in rows]
    counts, again = bf.plan(rewritten, archive)
    assert again == {} and counts["rows_to_rewrite"] == 0
    assert counts["entries_gaining_id"] == 0 and counts["entries_gaining_aliases"] == 0


def test_a_day_whose_archive_is_missing_resolves_unambiguous_names_from_the_rest_of_the_archive():
    rows, archive, w1 = _history()
    archive[D2] = None
    counts, rewrites = bf.plan(rows, archive)
    assert counts["days_archive_missing"] == 1
    assert counts["entries_without_id"] == 0
    assert rewrites[f"DATE#{D2}"][0][OLD]["habit_id"] == _id_of(w1, OLD)


def test_a_name_that_ever_mapped_to_two_ids_is_never_stamped():
    rows, archive, w1 = _history()
    other = next(e for e in archive[D3]["raw"]["journal"] if e["name"] == "Creatine")
    other["id"] = "00000000-0000-4000-8000-000000000000"  # the same display name under a second vendor id
    archive[D2] = None  # D2 must fall back to the archive-wide map for that name
    counts, rewrites = bf.plan(rows, archive)
    assert counts["ambiguous_names"] == 1
    assert counts["entries_without_id"] == 1
    assert "habit_id" not in rewrites[f"DATE#{D2}"][0]["Creatine"]
    assert rewrites[f"DATE#{D1}"][0]["Creatine"]["habit_id"] == _id_of(w1, "Creatine")  # the day's own archive still decides


def test_a_gap_marker_row_without_statuses_is_counted_and_untouched():
    rows, archive, _ = _history()
    rows.append({"sk": "DATE#2026-08-05", "absent": True})
    counts, rewrites = bf.plan(rows, archive)
    assert counts["rows_without_statuses"] == 1 and counts["stored_day_rows"] == 5
    assert "DATE#2026-08-05" not in rewrites


class _Table:
    def __init__(self, fail_sks=()):
        self.calls, self.fail_sks = [], set(fail_sks)

    def update_item(self, **kw):
        from botocore.exceptions import ClientError

        self.calls.append(kw)
        if kw["Key"]["sk"] in self.fail_sks:
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "UpdateItem")


def test_apply_rewrites_only_the_planned_rows_conditioned_on_the_updated_at_it_read():
    rows, archive, _ = _history()
    _, rewrites = bf.plan(rows, archive)
    table = _Table(fail_sks={f"DATE#{D3}"})
    out = bf.apply_rewrites(table, "USER#matthew#SOURCE#habitify", rewrites)
    assert out == {"rows_written": 3, "rows_skipped_changed_underneath": 1}
    assert len(table.calls) == 4
    call = next(c for c in table.calls if c["Key"]["sk"] == f"DATE#{D1}")
    assert call["ConditionExpression"] == "attribute_exists(sk) AND updated_at = :u"
    assert call["ExpressionAttributeValues"][":u"] == rows[0]["updated_at"]
    assert call["UpdateExpression"] == "SET #f = :m" and call["ExpressionAttributeNames"] == {"#f": "habit_statuses"}
    assert isinstance(call["ExpressionAttributeValues"][":m"]["Creatine"]["current_value"], Decimal)


def test_a_float_anywhere_in_the_rewrite_is_refused_before_the_call():
    rows, archive, _ = _history()
    _, rewrites = bf.plan(rows, archive)
    rewrites[f"DATE#{D1}"][0]["Creatine"]["current_value"] = 1.0
    with pytest.raises(TypeError, match="float"):
        bf.apply_rewrites(_Table(), "USER#matthew#SOURCE#habitify", rewrites)


def test_the_dry_run_report_is_counts_only_and_writes_nothing(monkeypatch, capsys):
    rows, archive, w1 = _history()
    table = _Table()

    class _S3:
        class exceptions:
            class NoSuchKey(Exception):
                pass

        def get_object(self, Bucket, Key):
            day = Key.rsplit("/", 1)[-1][: len("2026-01-01")]
            if day not in archive:
                raise _S3.exceptions.NoSuchKey()
            return {"Body": type("B", (), {"read": staticmethod(lambda: json.dumps(archive[day]).encode())})()}

    monkeypatch.setattr(bf, "_read_store", lambda *_a: rows)
    monkeypatch.setattr(bf, "_read_archive", lambda s3, bucket, days: {d: archive.get(d) for d in days})
    import boto3

    monkeypatch.setattr(boto3, "resource", lambda *a, **k: type("R", (), {"Table": staticmethod(lambda _n: table)})())
    monkeypatch.setattr(boto3, "client", lambda *a, **k: _S3())
    assert bf.main(["--start", D1, "--end", D4]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["mode"] == "dry-run" and report["rows_to_rewrite"] == 4
    assert table.calls == []
    text = json.dumps(report)
    for name in [e["name"] for e in w1["journal"]] + [NEW, NEWER, _id_of(w1, OLD)]:
        assert name not in text  # no habit names, no vendor ids
    assert "2026-08-09" not in text.replace(D1, "").replace(D4, "")  # only the range bounds are dates
