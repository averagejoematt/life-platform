#!/usr/bin/env python3
"""tests/test_hae_protein_intraday_5187.py — the same-day protein feed for the breakfast nudge (#5187).

Contracts: HAE `protein` samples are captured per entry (time + grams) into `_rd_protein_hae`; a re-send with
jittered seconds and a re-drawn split overwrites, never adds; the daily field is never written; the nudge reads the
entries only when the MacroFactor day row is absent and keeps the absent-everything withhold.

FIXTURE PROVENANCE. The payload shape is copied key-for-key from the live raw archive
(raw/matthew/health_auto_export/2026/10/22_11*.json-class objects, read 2026-10-22): a metric `{name: "protein",
units: "g", data: [{date: "YYYY-MM-DD HH:MM:SS -0700", qty: <float>, source: <str>}]}`, two one-minute-apart
chunks per logged food. Values are synthetic; the source string is blank in the newest payloads, as live.
"""

import os
import sys
from datetime import datetime, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if os.path.join(ROOT, "lambdas") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "lambdas"))

os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("DYNAMODB_TABLE", "life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import health_auto_export_lambda as hae  # noqa: E402
from common.pacific_time import PACIFIC  # noqa: E402
from emails import protein_nudge_runner as runner  # noqa: E402
from health import protein_engine as pe  # noqa: E402
from ingestion import health_auto_export_protein as hp  # noqa: E402
from privacy.field_tiers import TIER_OWNER_ONLY, tier_of  # noqa: E402

DAY = "2026-10-22"
PK = "USER#matthew#SOURCE#apple_health"
TICK_UTC = datetime(2026, 10, 22, 17, 31, tzinfo=timezone.utc)  # 10:31 PT


def payload(*chunks, units="g", name="protein"):
    return [{"name": name, "units": units, "data": [{"date": d, "qty": q, "source": "MacroFactor"} for d, q in chunks]}]


class Table:
    def __init__(self):
        self.items = {}

    def get_item(self, Key, **_kw):
        it = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": dict(it)} if it else {}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeNames, ExpressionAttributeValues):
        it = self.items.setdefault((Key["pk"], Key["sk"]), dict(Key))
        if ":rd" not in ExpressionAttributeValues:  # the nudge ledger's settle
            it.update({ExpressionAttributeNames[f"#{v[1:]}"]: val for v, val in ExpressionAttributeValues.items()})
            return
        it[hp.RD_FIELD] = ExpressionAttributeValues[":rd"]
        it.setdefault("source", ExpressionAttributeValues[":src"])
        it.setdefault("date", ExpressionAttributeValues[":dt"])

    def put_item(self, Item, ConditionExpression=None):
        k = (Item["pk"], Item["sk"])
        if ConditionExpression and k in self.items:
            raise RuntimeError("ConditionalCheckFailedException")
        self.items[k] = dict(Item)


def write(table, metrics, now=TICK_UTC):
    return hp.write_hae_protein(metrics, table, hae.parse_date_str, lambda d: {"pk": PK, "sk": f"DATE#{d}"}, now=now)


def test_entries_are_captured_per_entry_with_time_and_grams():
    t = Table()
    assert write(t, payload(("2026-10-22 08:59:44 -0700", 11.2), ("2026-10-22 09:00:44 -0700", 3.8))) == 1
    rd = t.items[(PK, f"DATE#{DAY}")][hp.RD_FIELD]
    assert sorted(float(e["g"]) for e in rd.values()) == [3.8, 11.2]
    assert {e["t"][:19] for e in rd.values()} == {"2026-10-22T08:59:44", "2026-10-22T09:00:44"}
    assert all(e["seen_at"] == TICK_UTC.isoformat() and e["units_reported"] == "g" for e in rd.values())


def test_a_resend_with_jittered_seconds_and_a_redrawn_split_overwrites_never_adds():
    t = Table()
    write(t, payload(("2026-10-22 08:59:15 -0700", 4.0), ("2026-10-22 09:00:15 -0700", 11.0)))
    write(t, payload(("2026-10-22 08:59:49 -0700", 8.8), ("2026-10-22 09:00:49 -0700", 6.2)))
    rd = t.items[(PK, f"DATE#{DAY}")][hp.RD_FIELD]
    assert len(rd) == 2 and round(sum(e["g"] for e in rd.values()), 1) == 15.0
    # latest delivery wins: the stored grams are the second write's, not the first's
    assert sorted(float(e["g"]) for e in rd.values()) == [6.2, 8.8]


def test_the_daily_field_is_never_written_and_the_generic_path_still_skips_protein():
    t = Table()
    write(t, payload(("2026-10-22 12:47:38 -0700", 20.0)))
    row = t.items[(PK, f"DATE#{DAY}")]
    assert set(row) <= {"pk", "sk", hp.RD_FIELD, "source", "date"}
    assert "protein" in hae.SKIP_METRICS and "Protein" in hae.SKIP_METRICS


def test_unusable_readings_are_skipped_not_zeroed():
    t = Table()
    assert write(t, payload(("2026-10-22 09:00:00 -0700", 12.0), units="mg")) == 0
    assert write(t, payload(("not a date", 12.0), ("2026-10-22 09:00:00 -0700", None), ("2026-10-22 09:00:00 -0700", 9999))) == 0
    assert not t.items


def test_an_unreadable_stored_map_skips_the_day():
    class Broken(Table):
        def get_item(self, Key, **_kw):
            raise RuntimeError("throttled")

    assert write(Broken(), payload(("2026-10-22 09:00:00 -0700", 12.0))) == 0


def test_the_field_is_owner_only():
    assert tier_of("apple_health", hp.RD_FIELD) == TIER_OWNER_ONLY


# ── the reader ────────────────────────────────────────────────────────────────
def _seed(t, *chunks):
    write(t, payload(*chunks))


def test_hae_feeding_rows_filters_on_the_pacific_date_and_sorts():
    t = Table()
    _seed(t, ("2026-10-22 08:10:00 -0700", 30.0), ("2026-10-21 19:10:00 -0700", 50.0), ("2026-10-22 08:11:00 -0700", 20.0))
    rd = t.items[(PK, f"DATE#{DAY}")][hp.RD_FIELD]
    row = pe.hae_feeding_rows(rd, DAY)
    assert row["row_source"] == "hae_intraday" and [r["time"] for r in row["food_log"]] == ["08:10", "08:11"]
    assert pe.hae_feeding_rows(rd, "2026-10-23") is None and pe.hae_feeding_rows(None, DAY) is None


def _run(t, tier=0):
    sent = []
    return runner.run(t, sent.append, TICK_UTC, tier), sent, t.items.get((runner.LEDGER_PK, f"EVAL#{DAY}"))


def test_runner_on_track_from_the_intraday_entries():
    t = Table()
    threshold = pe._cv("feeding_threshold_g")
    _seed(t, ("2026-10-22 08:10:00 -0700", threshold / 2), ("2026-10-22 08:11:00 -0700", threshold / 2 + 1))
    out, sent, ev = _run(t)
    assert out["reason"] == "on_track" and not sent and ev["source"] == "hae_intraday" and ev["send"] is False


def test_runner_behind_logged_below_sends_from_the_intraday_entries():
    t = Table()
    _seed(t, ("2026-10-22 09:00:00 -0700", 8.0), ("2026-10-22 09:01:00 -0700", 7.0))
    out, sent, ev = _run(t)
    assert out["reason"] == "behind_logged_below" and len(sent) == 1 and ev["source"] == "hae_intraday"


def test_runner_nothing_anywhere_still_withholds_and_stamps_the_dead_man():
    out, sent, ev = _run(Table())
    assert out["reason"] == "no_same_day_log" and not sent and ev["source"] == "none"


def test_the_macrofactor_row_outranks_the_intraday_entries_when_present():
    t = Table()
    _seed(t, ("2026-10-22 09:00:00 -0700", 8.0))
    threshold = pe._cv("feeding_threshold_g")
    t.items[("USER#matthew#SOURCE#macrofactor", f"DATE#{DAY}")] = {
        "pk": "USER#matthew#SOURCE#macrofactor",
        "sk": f"DATE#{DAY}",
        "food_log": [{"time": "07:30", "protein_g": threshold + 5}],
    }
    out, sent, ev = _run(t)
    assert out["reason"] == "on_track" and ev["source"] == "macrofactor_day_row"


def test_pacific_morning_instant_is_the_same_utc_day():
    at = datetime(2026, 10, 22, 10, 10, tzinfo=PACIFIC).astimezone(timezone.utc)
    assert at.date().isoformat() == DAY
