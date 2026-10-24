"""tests/test_rhythm_channel_4972.py — the owner-only heart-rhythm event channel's
behaviour (#4972): ECG results, heart-rate notifications and the medication log land as
`RHYTHM#` rows in the clinical partition, de-duplicated, with day-1 absence semantics.

The payload shapes are the Health Auto Export vendor-documented JSON v2 shapes for the
`ecg`, `heartRateNotifications` and `medications` data types — NOT captured from the
webhook (no such payload has arrived yet, #4968). Names and values are placeholders.
"""

from __future__ import annotations

import json
import os
import sys
from decimal import Decimal

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (os.path.join(ROOT, "lambdas"), os.path.join(ROOT, "lambdas", "ingestion")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("DYNAMODB_TABLE", "life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from health import (
    clinical_facts,  # noqa: E402
    rhythm_channel as rc,  # noqa: E402
)

NOW = "2026-10-18T12:00:00+00:00"
PK = "USER#matthew#SOURCE#clinical"
WITHINGS_PK = "USER#matthew#SOURCE#withings"


class _CondFail(Exception):
    def __init__(self):
        super().__init__("conditional")
        self.response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class FakeTable:
    """An in-memory single table: put_item honours `attribute_not_exists(sk)`, query honours
    `begins_with(sk, :p)`, get_item is a key lookup. Records every write."""

    def __init__(self, items=()):
        self.items = {(i["pk"], i["sk"]): dict(i) for i in items}
        self.puts = []
        self.updates = []

    def put_item(self, Item, ConditionExpression=None):
        key = (Item["pk"], Item["sk"])
        if ConditionExpression == "attribute_not_exists(sk)" and key in self.items:
            raise _CondFail()
        self.puts.append(Item)
        self.items[key] = dict(Item)

    def update_item(self, **kwargs):
        self.updates.append(kwargs)
        return {}

    def get_item(self, Key, **_kw):
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item else {}

    def query(self, KeyConditionExpression, ExpressionAttributeValues, **_kw):
        pk = ExpressionAttributeValues[":pk"]
        prefix = ExpressionAttributeValues.get(":p", "")
        return {"Items": [dict(v) for (p, s), v in sorted(self.items.items()) if p == pk and s.startswith(prefix)]}


def ecg(start="2026-10-17 08:12:03 -0700", classification="classification_a", avg=71, source="Apple Watch"):
    return {
        "start": start,
        "end": start,
        "classification": classification,
        "severity": "none",
        "averageHeartRate": avg,
        "numberOfVoltageMeasurements": 3,
        "samplingFrequency": 512,
        "source": source,
        "voltageMeasurements": [{"date": start, "voltage": 0.0001, "units": "V"}],
    }


def notification(start="2026-10-17 03:00:00 -0700", threshold=120, hrs=(124, 131), **extra):
    n = {
        "start": start,
        "end": start,
        "threshold": threshold,
        "heartRate": [{"hr": h, "units": "count/min", "timestamp": {"start": start, "end": start}} for h in hrs],
    }
    n.update(extra)
    return n


def medication(name="medication_a", start="2026-10-17 07:30:00 -0700", dosage=1, form="tablet", status="Taken"):
    return {"displayText": name, "start": start, "end": start, "dosage": dosage, "form": form, "status": status, "isArchived": False}


# ── ECG ────────────────────────────────────────────────────────────────────────
def test_an_ecg_becomes_one_rhythm_row_with_its_fields():
    t = FakeTable()
    out = rc.ingest(t, {"ecg": [ecg()]}, now_iso=NOW)
    assert out["written"] == 1 and out["duplicates"] == 0
    (row,) = t.puts
    assert row["pk"] == PK
    assert row["sk"] == "RHYTHM#ECG#2026-10-17T08:12:03#apple-watch"
    assert row["rhythm_ecg_classification"] == "classification_a"
    assert row["rhythm_ecg_avg_hr_bpm"] == Decimal("71.0")
    assert row["rhythm_ecg_sample_start"] == "2026-10-17T08:12:03-07:00"
    assert row["rhythm_ecg_device"] == "Apple Watch"
    assert row["event_date"] == "2026-10-17" and row["channel"] == "rhythm" and row["source"] == "clinical"
    assert "cross_device_same_day" not in row
    assert "voltageMeasurements" not in json.dumps(row, default=str)


def test_a_redelivered_ecg_is_stored_once_and_never_clobbered():
    t = FakeTable()
    rc.ingest(t, {"ecg": [ecg()]}, now_iso=NOW)
    out = rc.ingest(t, {"ecg": [ecg(classification="classification_b")]}, now_iso=NOW)
    assert out["written"] == 0 and out["duplicates"] == 1
    assert len(t.puts) == 1 and t.puts[0]["rhythm_ecg_classification"] == "classification_a"


def test_an_ecg_the_owner_record_already_holds_is_stored_once():
    """The loader's `ECG#` row for the same recording (30 s apart, another device spelling)."""
    t = FakeTable([{"pk": PK, "sk": "ECG#2026-10-17T08:12:33#watch", "verdict": "x"}])
    out = rc.ingest(t, {"ecg": [ecg()]}, now_iso=NOW)
    assert out["written"] == 0 and out["duplicates"] == 1 and t.puts == []


def test_a_watch_ecg_on_a_withings_ecg_day_is_a_second_row_flagged_never_merged():
    withings = {
        "pk": WITHINGS_PK,
        "sk": "DATE#2026-10-17",
        "afib_result": Decimal("0"),
        "measurement_group_attribs": [{"timestamp": Decimal("1792240000"), "attrib": 0}],
    }
    t = FakeTable([withings])
    out = rc.ingest(t, {"ecg": [ecg()]}, now_iso=NOW)
    assert out["written"] == 1 and out["cross_device_same_day"] == 1
    assert t.puts[0]["cross_device_same_day"] is True
    # The Withings row is untouched — never merged into.
    assert t.items[(WITHINGS_PK, "DATE#2026-10-17")] == withings


def test_a_withings_ecg_mirrored_through_apple_health_at_its_own_timestamp_is_stored_once():
    # 2026-10-17 08:12:03 -0700 == 1792249923 UTC epoch
    withings = {
        "pk": WITHINGS_PK,
        "sk": "DATE#2026-10-17",
        "afib_result": Decimal("0"),
        "measurement_group_attribs": [{"timestamp": Decimal("1792249923"), "attrib": 0}],
    }
    t = FakeTable([withings])
    out = rc.ingest(t, {"ecg": [ecg(source="Withings")]}, now_iso=NOW)
    assert out["written"] == 0 and out["duplicates"] == 1


def test_a_zero_average_heart_rate_is_absence_not_a_zero():
    t = FakeTable()
    rc.ingest(t, {"ecg": [ecg(avg=0)]}, now_iso=NOW)
    assert "rhythm_ecg_avg_hr_bpm" not in t.puts[0]


def test_an_unreadable_ecg_is_skipped_not_guessed():
    t = FakeTable()
    out = rc.ingest(t, {"ecg": [ecg(classification=""), {"classification": "classification_a"}]}, now_iso=NOW)
    assert out["skipped"] == 2 and t.puts == []


# ── notifications ──────────────────────────────────────────────────────────────
def test_notification_kinds_named_and_inferred():
    t = FakeTable()
    payload = {
        "heartRateNotifications": [
            notification(),  # over threshold -> high (inferred)
            notification(start="2026-10-17 04:00:00 -0700", threshold=40, hrs=(38, 36)),  # -> low (inferred)
            {"start": "2026-10-17 05:00:00 -0700", "heartRateVariation": [{"hrv": 1}]},  # -> irregular (inferred)
            notification(start="2026-10-17 06:00:00 -0700", threshold=None, hrs=(), type="Hypertension Notification"),
        ]
    }
    out = rc.ingest(t, payload, now_iso=NOW)
    assert out["written"] == 4
    by_kind = {r["rhythm_notification_kind"]: r for r in t.puts}
    assert set(by_kind) == {"high", "low", "irregular", "hypertension"}
    assert by_kind["high"]["rhythm_notification_bpm"] == Decimal("131.0")
    assert by_kind["low"]["rhythm_notification_bpm"] == Decimal("36.0")
    assert by_kind["high"]["rhythm_notification_kind_inferred"] is True
    assert by_kind["hypertension"]["rhythm_notification_kind_inferred"] is False
    # No reading -> no bpm field, never a 0.
    assert "rhythm_notification_bpm" not in by_kind["irregular"]
    assert "rhythm_notification_bpm" not in by_kind["hypertension"]
    assert by_kind["high"]["sk"] == "RHYTHM#HRNOTIF#2026-10-17T03:00:00#high"


# ── medication log ─────────────────────────────────────────────────────────────
def test_a_medication_log_entry_is_owner_only_and_its_key_carries_no_name():
    t = FakeTable()
    out = rc.ingest(t, {"medications": [medication()]}, now_iso=NOW)
    assert out["written"] == 1
    (row,) = t.puts
    assert row["rhythm_med_name"] == "medication_a"
    assert row["rhythm_med_dose_text"] == "1 tablet"
    assert row["rhythm_med_status"] == "taken"
    assert row["sk"].startswith("RHYTHM#MEDLOG#2026-10-17T07:30:00#")
    assert "medication_a" not in row["sk"]


def test_the_returned_counts_carry_no_value():
    t = FakeTable()
    out = rc.ingest(t, {"medications": [medication()], "ecg": [ecg()], "heartRateNotifications": [notification()]}, now_iso=NOW)
    blob = json.dumps(out)
    for leak in ("medication_a", "classification_a", "tablet", "Apple Watch", "131"):
        assert leak not in blob


# ── absence + the writer's boundary ───────────────────────────────────────────
def test_no_event_no_row():
    t = FakeTable()
    assert not rc.has_channel_payload({"metrics": [], "workouts": []})
    out = rc.ingest(t, {"ecg": [], "heartRateNotifications": [], "medications": []}, now_iso=NOW)
    assert out["written"] == 0 and t.puts == [] and t.updates == []


def test_the_channel_writer_refuses_the_owner_record_families():
    t = FakeTable()
    for sk in ("ECG#2026-10-17T08:12:03#x", "MED#x", "GUIDANCE#current", "EVENT#2026-10-17#x"):
        with pytest.raises(ValueError):
            clinical_facts.put_channel_rows(t, [{"sk": sk}])
    assert t.puts == []


def test_the_coach_block_never_renders_the_channel():
    """The fact pack is #4977's ruling: the RHYTHM# rows are not a rendered family, on
    either channel."""
    t = FakeTable()
    rc.ingest(t, {"medications": [medication()], "ecg": [ecg()], "heartRateNotifications": [notification()]}, now_iso=NOW)
    rows = list(t.items.values()) + [{"pk": PK, "sk": "GUIDANCE#current", "rules": ["rule one"], "public_rules": ["rule one"]}]
    for published in (True, False):
        block = clinical_facts.render_clinical_block(rows, published=published)
        assert "rule one" in block
        for leak in ("medication_a", "classification_a", "RHYTHM#", "rhythm_"):
            assert leak not in block


def test_the_tier_registry_equals_the_producer_vocabulary():
    from privacy.field_tiers import FIELD_TIERS, TIER_OWNER_ONLY, strip_map

    assert {f for f, tier in FIELD_TIERS["clinical"].items() if tier == TIER_OWNER_ONLY} == set(rc.CHANNEL_FIELDS)
    assert strip_map()["clinical"] == frozenset(rc.CHANNEL_FIELDS)


# ── the webhook hunk ──────────────────────────────────────────────────────────
class _Ctx:
    aws_request_id = "test-4972"


def test_the_webhook_routes_the_events_to_the_channel_and_never_to_the_day_row(monkeypatch):
    import health_auto_export_lambda as hae

    t = FakeTable()
    monkeypatch.setattr(hae, "table", t)
    monkeypatch.setattr(hae, "get_api_key", lambda: "tok")
    monkeypatch.setattr(hae, "save_raw_payload", lambda payload, received=None: "raw/matthew/health_auto_export/test.json")
    payload = {"data": {"ecg": [ecg()], "heartRateNotifications": [notification()], "medications": [medication()]}}
    resp = hae.lambda_handler({"headers": {"authorization": "Bearer tok"}, "body": json.dumps(payload)}, _Ctx())
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["rhythm_channel"]["written"] == 3
    assert {p["pk"] for p in t.puts} == {PK}
    assert all(p["sk"].startswith("RHYTHM#") for p in t.puts)
    # Nothing reached the apple_health day row.
    assert t.updates == []
    assert "medication_a" not in resp["body"] and "classification_a" not in resp["body"]
