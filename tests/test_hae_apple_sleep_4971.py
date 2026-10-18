#!/usr/bin/env python3
"""tests/test_hae_apple_sleep_4971.py — Apple's own sleep record as `sleep_*_apple` fields (#4971).

The contracts, each a caller-visible fact about the stored apple_health day row:

  * only Apple-device sleep readings are stored — HealthKit also carries Whoop's and
    Eight Sleep's nights under `sleep_analysis` (seen live 2026-10-04/05), and those never
    reach a field; every attribute the writer touches is an `_apple` field or a base field;
  * the day frame (#3677/#3913): a night is filed under the UTC day of its wake;
  * absence (ADR-104): no reading -> no field, an unstaged night -> no stage fields;
  * re-sends: overlapping samples are a UNION, never a sum; a fuller night-summary re-send
    replaces a partial one, never adds to it;
  * no METRIC_TRUTH facet reads an Apple sleep field as truth;
  * every field has a field_tiers row and a docs/SCHEMA.md row.

FIXTURE PROVENANCE. The night-summary shape is HAE's aggregated `sleep_analysis` record
copied key-for-key from the live raw archive (raw/matthew/health_auto_export/2026/10/
05_45110e98b97b08a5.json, a WHOOP-sourced night — no watch night exists yet); the values
and the source are synthetic. The per-sample shape (`startDate`/`endDate`/`value`/`qty`)
is HAE's unaggregated export form, not yet seen live on this account.
"""

import json
import os
import re
import sys
from decimal import Decimal

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
if LAMBDAS not in sys.path:
    sys.path.insert(0, LAMBDAS)

os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("DYNAMODB_TABLE", "life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import health_auto_export_lambda as hae  # noqa: E402
from ingestion import health_auto_export_sleep as sleep  # noqa: E402
from ingestion.source_registry import METRIC_TRUTH, day_key_frame_for  # noqa: E402
from privacy.field_tiers import TIER_OWNER_ONLY, tier_of  # noqa: E402

PK = "USER#matthew#SOURCE#apple_health"
WATCH = "Matthew’s\u00a0Apple Watch"  # the live watch source string: curly apostrophe + NO-BREAK SPACE (#4969)
BASE_FIELDS = {"source", "date", "phase"}


def summary(source=WATCH, **over):
    """HAE's aggregated night record (live key set), synthetic values. Hours."""
    rec = {
        "asleep": 0,
        "awake": 0.4,
        "core": 3.9,
        "date": "2026-10-20 00:00:00 -0700",
        "deep": 1.1,
        "inBed": 8.2,
        "inBedEnd": "2026-10-20 06:40:00 -0700",
        "inBedStart": "2026-10-19 22:25:00 -0700",
        "rem": 1.6,
        "sleepEnd": "2026-10-20 06:30:00 -0700",
        "sleepStart": "2026-10-19 22:40:00 -0700",
        "source": source,
        "totalSleep": 6.6,
    }
    rec.update(over)
    return rec


def sample(stage, start, end, source=WATCH):
    return {"startDate": start, "endDate": end, "value": stage, "qty": 0, "source": source}


def payload(*records, units="hr"):
    return [{"name": "sleep_analysis", "units": units, "data": list(records)}]


class StatefulTable:
    """Applies the writer's SET / REMOVE to one in-memory item per key."""

    def __init__(self, items=None, get_error=None):
        self.items = {k: dict(v) for k, v in (items or {}).items()}
        self.updates = []
        self.get_error = get_error

    def get_item(self, Key=None, **kw):
        if self.get_error:
            raise self.get_error
        item = self.items.get(Key["sk"])
        return {"Item": dict(item)} if item else {}

    def update_item(self, Key=None, UpdateExpression="", ExpressionAttributeNames=None, ExpressionAttributeValues=None, **kw):
        self.updates.append({"Key": Key, "UpdateExpression": UpdateExpression, "names": dict(ExpressionAttributeNames)})
        item = self.items.setdefault(Key["sk"], {})
        names, values = ExpressionAttributeNames, ExpressionAttributeValues
        set_part, _, remove_part = UpdateExpression.partition(" REMOVE ")
        for clause in re.findall(r"(#\w+) = (if_not_exists\(#\w+, (:\w+)\)|:\w+)", set_part[4:]):
            attr, rhs, guarded = clause
            if guarded:
                item.setdefault(names[attr], values[guarded])
            else:
                item[names[attr]] = values[rhs]
        for ph in filter(None, (p.strip() for p in remove_part.split(","))):
            item.pop(names[ph], None)

    def row(self, day):
        return self.items.get(f"DATE#{day}", {})


def write(table, metrics):
    return sleep.write_apple_sleep(metrics, table, PK, hae.is_apple_device, phase_for_date=None)


# ── Source filter: Whoop / Eight Sleep never become Apple fields ──────────────


class TestOnlyAppleReadings:
    @pytest.mark.parametrize("src", ["WHOOP", "Eight Sleep", "", "Apple Watch|WHOOP"])
    def test_non_apple_or_blank_or_mixed_source_is_never_stored(self, src):
        table = StatefulTable()
        assert write(table, payload(summary(source=src))) == 0
        assert table.updates == []

    def test_writer_touches_only_apple_fields_and_base_fields(self):
        """Whoop's and Eight Sleep's fields on the same row are provably untouched."""
        whoop_es = {"sleep_duration_hours": Decimal("7.1"), "sleep_start": "x", "sleep_end": "y", "rem_hours": Decimal("1.2")}
        table = StatefulTable({"DATE#2026-10-20": dict(whoop_es)})
        write(table, payload(summary(), summary(source="WHOOP"), summary(source="Eight Sleep")))
        touched = set(table.updates[0]["names"].values())
        assert touched - BASE_FIELDS <= set(sleep.APPLE_SLEEP_FIELDS) | {sleep.RD_FIELD}
        assert all(f.endswith("_apple") for f in touched - BASE_FIELDS)
        row = table.row("2026-10-20")
        for k, v in whoop_es.items():
            assert row[k] == v
        assert "WHOOP" not in json.dumps(row[sleep.RD_FIELD], default=str)


# ── Day frame (#3677 keep-UTC ruling; #3913 Whoop's measured frame) ──────────


class TestDayFrame:
    def test_apple_health_partition_is_the_utc_frame(self):
        assert day_key_frame_for("apple_health") == "utc"

    def test_a_night_is_filed_under_the_morning_it_ends(self):
        """22:40 PDT 10-19 -> 06:30 PDT 10-20 is DATE#2026-10-20 — the wake date, the key
        Whoop files the same night under (onset after 17:00 PT lands on the UTC next day)."""
        assert list(sleep.entries_from_metrics(payload(summary()), hae.is_apple_device)) == ["2026-10-20"]

    def test_samples_of_one_session_share_the_wake_day_even_across_utc_midnight(self):
        """Samples before and after 00:00 UTC (17:00 PDT) of one session stay one night."""
        recs = [
            sample("Core", "2026-10-19 16:30:00 -0700", "2026-10-19 17:30:00 -0700"),
            sample("Deep", "2026-10-19 17:30:00 -0700", "2026-10-19 18:30:00 -0700"),
        ]
        assert list(sleep.entries_from_metrics(payload(*recs), hae.is_apple_device)) == ["2026-10-20"]

    def test_the_key_is_the_utc_day_of_the_wake_not_the_local_date(self):
        """A wake after 17:00 PDT is the next UTC day — the stated cost of the UTC frame."""
        rec = summary(sleepEnd="2026-10-20 18:10:00 -0700", inBedEnd="2026-10-20 18:10:00 -0700")
        assert list(sleep.entries_from_metrics(payload(rec), hae.is_apple_device)) == ["2026-10-21"]


# ── Absence (ADR-104) ────────────────────────────────────────────────────────


class TestAbsence:
    def test_no_sleep_metric_writes_nothing(self):
        table = StatefulTable()
        assert write(table, [{"name": "step_count", "units": "count", "data": []}]) == 0
        assert table.updates == []

    def test_unstaged_summary_carries_no_stage_fields_never_zero(self):
        table = StatefulTable()
        write(table, payload(summary(core=0, deep=0, rem=0, awake=0, asleep=6.6)))
        row = table.row("2026-10-20")
        for f in ("sleep_core_min_apple", "sleep_deep_min_apple", "sleep_rem_min_apple", "sleep_awake_min_apple"):
            assert f not in row
        assert row["sleep_unspecified_min_apple"] == Decimal("396.0")

    def test_staged_summary_keeps_a_reported_zero_stage(self):
        table = StatefulTable()
        write(table, payload(summary(deep=0)))
        assert table.row("2026-10-20")["sleep_deep_min_apple"] == Decimal("0.0")

    def test_a_stage_with_no_sample_is_absent(self):
        table = StatefulTable()
        write(table, payload(sample("Core", "2026-10-20 00:00:00 -0700", "2026-10-20 01:00:00 -0700")))
        row = table.row("2026-10-20")
        assert row["sleep_core_min_apple"] == Decimal("60.0")
        assert "sleep_deep_min_apple" not in row and "sleep_in_bed_hours_apple" not in row

    def test_summary_fields_and_capture_all(self):
        table = StatefulTable()
        write(table, payload(summary()))
        row = table.row("2026-10-20")
        assert row["sleep_total_hours_apple"] == Decimal("6.6")
        assert row["sleep_in_bed_hours_apple"] == Decimal("8.2")
        assert (row["sleep_core_min_apple"], row["sleep_deep_min_apple"], row["sleep_rem_min_apple"]) == (
            Decimal("234.0"),
            Decimal("66.0"),
            Decimal("96.0"),
        )
        assert row["sleep_awake_min_apple"] == Decimal("24.0")
        assert row["sleep_start_apple"] == "2026-10-19T22:40:00-07:00"
        assert row["sleep_end_apple"] == "2026-10-20T06:30:00-07:00"
        assert row["sleep_source_apple"] == WATCH
        assert row["sleep_record_kind_apple"] == "summary"
        (stored,) = row[sleep.RD_FIELD].values()
        assert set(summary()) - {"source"} <= set(stored)  # every vendor key kept


# ── Re-sends: the unique-sample rule, never a sum ────────────────────────────


class TestResends:
    def test_overlapping_sample_resend_is_a_union_not_a_sum(self):
        table = StatefulTable()
        first = [
            sample("Core", "2026-10-19 23:00:00 -0700", "2026-10-20 01:00:00 -0700"),
            sample("Deep", "2026-10-20 01:00:00 -0700", "2026-10-20 02:00:00 -0700"),
        ]
        write(table, payload(*first))
        # The next sync re-sends the deep sample, a shifted-boundary copy of it, and new readings.
        second = [
            sample("Deep", "2026-10-20 01:00:00 -0700", "2026-10-20 02:00:00 -0700"),
            sample("Deep", "2026-10-20 01:30:00 -0700", "2026-10-20 02:30:00 -0700"),
            sample("REM", "2026-10-20 02:30:00 -0700", "2026-10-20 03:00:00 -0700"),
        ]
        write(table, payload(*second))
        row = table.row("2026-10-20")
        assert row["sleep_core_min_apple"] == Decimal("120.0")  # kept from the first sync
        assert row["sleep_deep_min_apple"] == Decimal("90.0")  # 01:00-02:30 once; a sum would be 180
        assert row["sleep_rem_min_apple"] == Decimal("30.0")
        assert row["sleep_total_hours_apple"] == Decimal("4.0")  # 23:00-03:00
        assert row["sleep_start_apple"] == "2026-10-19T23:00:00-07:00"
        assert row["sleep_end_apple"] == "2026-10-20T03:00:00-07:00"
        assert len(row[sleep.RD_FIELD]) == 4  # the exact re-send stored once

    def test_identical_payload_twice_is_idempotent(self):
        table = StatefulTable()
        recs = [sample("Core", "2026-10-19 23:00:00 -0700", "2026-10-20 01:00:00 -0700")]
        write(table, payload(*recs))
        before = dict(table.row("2026-10-20"))
        write(table, payload(*recs))
        assert table.row("2026-10-20") == before

    @pytest.mark.parametrize("order", ["partial_first", "full_first"])
    def test_a_fuller_summary_resend_replaces_a_partial_one_in_either_order(self, order):
        partial = summary(totalSleep=2.2, core=1.0, deep=0.5, rem=0.7, sleepStart="2026-10-20 04:00:00 -0700")
        full = summary()
        table = StatefulTable()
        for rec in (partial, full) if order == "partial_first" else (full, partial):
            write(table, payload(rec))
        row = table.row("2026-10-20")
        assert row["sleep_total_hours_apple"] == Decimal("6.6")  # never 8.8
        assert row["sleep_core_min_apple"] == Decimal("234.0")

    def test_a_field_the_recomputed_night_drops_is_removed(self):
        """Summary night first (carries in-bed), then samples arrive with no in-bed: the
        finer record wins and the summary's in-bed value must not survive beside it."""
        table = StatefulTable()
        write(table, payload(summary()))
        write(table, payload(sample("Core", "2026-10-19 23:00:00 -0700", "2026-10-20 01:00:00 -0700")))
        row = table.row("2026-10-20")
        assert row["sleep_record_kind_apple"] == "samples"
        assert "sleep_in_bed_hours_apple" not in row

    def test_unreadable_stored_map_skips_the_night_rather_than_overwriting(self):
        table = StatefulTable(get_error=RuntimeError("throttled"))
        assert write(table, payload(summary())) == 0
        assert table.updates == []

    def test_minutes_units_are_converted(self):
        table = StatefulTable()
        rec = summary(totalSleep=396, inBed=492, core=234, deep=66, rem=96, awake=24)
        write(table, payload(rec, units="min"))
        assert table.row("2026-10-20")["sleep_total_hours_apple"] == Decimal("6.6")


# ── The handler routes sleep_analysis to the sleep writer ────────────────────


def test_handler_writes_apple_sleep(monkeypatch):
    table = StatefulTable()

    class _S3:
        def put_object(self, **kw):
            return {}

    monkeypatch.setattr(hae, "table", table)
    monkeypatch.setattr(hae, "s3_client", _S3())
    monkeypatch.setattr(hae, "get_api_key", lambda: "k")
    event = {"headers": {"authorization": "Bearer k"}, "body": json.dumps({"data": {"metrics": payload(summary()), "workouts": []}})}
    resp = hae.lambda_handler(event, None)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["apple_sleep_nights"] == 1
    assert table.row("2026-10-20")["sleep_total_hours_apple"] == Decimal("6.6")


# ── Never truth; tiered; documented ──────────────────────────────────────────


def test_no_metric_truth_facet_reads_an_apple_sleep_field():
    """The agreement study (#4974) reads these beside Whoop's — no resolver picks them."""
    ours = set(sleep.APPLE_SLEEP_FIELDS) | {sleep.RD_FIELD}
    for metric, facet in METRIC_TRUTH.items():
        assert not ours & set(facet["field_by_source"].values()), metric


def test_every_apple_sleep_field_is_tiered_owner_only():
    for f in (*sleep.APPLE_SLEEP_FIELDS, sleep.RD_FIELD):
        assert tier_of("apple_health", f) == TIER_OWNER_ONLY, f


def test_every_apple_sleep_field_has_a_schema_row():
    with open(os.path.join(ROOT, "docs", "SCHEMA.md"), encoding="utf-8") as fh:
        text = fh.read()
    missing = [f for f in (*sleep.APPLE_SLEEP_FIELDS, sleep.RD_FIELD) if f"| `{f}` |" not in text]
    assert not missing, missing
