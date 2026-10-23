"""#4628 box 4 — `scripts/hae_additive_backfill_4628.py` rebuilds the five additive Apple Health
day fields from the raw webhook archive, through the writer's own functions.

The fixture is the wire: the 26 archived deliveries of the UTC day 2026-10-14 (see the fixture's
own `_provenance`), served here from an in-memory S3 under their REAL archived keys, so the
script's listing, leaf classification, reading-day bucketing and dedup all run on real data —
including the readings the phone re-sent across deliveries.
"""

import importlib.util
import io
import json
import os
import re
import sys
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if os.path.join(ROOT, "lambdas") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "lambdas"))
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from ingestion import (
    health_auto_export_additive as additive,  # noqa: E402
    health_auto_export_lambda as hae,  # noqa: E402
)
from ingestion.source_registry import raw_date_key  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "hae_additive_day_2026-10-14.json")
DAY = "2026-10-14"
BUCKET = "matthew-life-platform"
PK = "USER#matthew#SOURCE#apple_health"


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "hae_additive_backfill_4628", os.path.join(ROOT, "scripts", "hae_additive_backfill_4628.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load_script()


def _fixture():
    with open(FIXTURE) as fh:
        return json.load(fh)


class _NoSuchKey(Exception):
    pass


class _Exc:
    NoSuchKey = _NoSuchKey


class FakeS3:
    """list_objects_v2 + get_object over the fixture's real archived keys; put_object records
    (or, as the dry-run mutation control, refuses)."""

    exceptions = _Exc()

    def __init__(self, deliveries, refuse_put=False):
        t0 = datetime(2026, 10, 14, 0, 0, tzinfo=timezone.utc)
        self.objects = {d["archived_as"]: json.dumps(d["payload"]) for d in deliveries}
        self.modified = {d["archived_as"]: t0 + timedelta(minutes=i) for i, d in enumerate(deliveries)}
        self.refuse_put = refuse_put
        self.puts = []

    def list_objects_v2(self, Bucket=None, Prefix=None, ContinuationToken=None, **_):
        keys = sorted(k for k in self.objects if k.startswith(Prefix) and k in self.modified)
        return {"Contents": [{"Key": k, "LastModified": self.modified[k]} for k in keys], "IsTruncated": False}

    def get_object(self, Bucket=None, Key=None, **_):
        if Key not in self.objects:
            raise _NoSuchKey(Key)
        return {"Body": io.BytesIO(self.objects[Key].encode("utf-8"))}

    def put_object(self, Bucket=None, Key=None, Body=None, **_):
        if self.refuse_put:
            raise AssertionError(f"dry run must not write S3: {Key}")
        self.objects[Key] = Body
        self.puts.append(Key)
        return {}


class FakeTable:
    """A one-row store: query returns it; update_item applies a SET (or, as the dry-run mutation
    control, refuses)."""

    def __init__(self, rows, refuse_write=False):
        self.rows = {r["sk"]: dict(r) for r in rows}
        self.refuse_write = refuse_write
        self.updates = []

    def query(self, **_):
        return {"Items": [dict(r) for r in self.rows.values()]}

    def update_item(
        self, Key=None, UpdateExpression=None, ConditionExpression=None, ExpressionAttributeNames=None, ExpressionAttributeValues=None
    ):
        if self.refuse_write:
            raise AssertionError(f"dry run must not write DynamoDB: {Key}")
        assert ConditionExpression == "attribute_exists(sk)"
        assert Key["sk"] in self.rows, "the backfill must never create a row"
        self.updates.append((Key, UpdateExpression, ExpressionAttributeNames, ExpressionAttributeValues))
        for name_ph, val_ph in re.findall(r"(#[A-Za-z0-9]+) = (:[A-Za-z0-9]+)", UpdateExpression):
            self.rows[Key["sk"]][ExpressionAttributeNames[name_ph]] = ExpressionAttributeValues[val_ph]
        return {}


def _run(argv, s3, table):
    out = io.StringIO()
    with redirect_stdout(out):
        assert mod.main(argv, s3=s3, table=table, today=date(2026, 10, 17)) == 0
    text = out.getvalue()
    return text, json.loads(text[text.index("\n{") + 1 :])


def _write_path_values(deliveries):
    """What the LIVE writer stores after every delivery: `apply_archived_sums` against an empty
    archive, delivery by delivery — the expectation the backfill must reproduce."""
    s3 = FakeS3([])
    daily = {}
    for d in deliveries:
        daily = {}
        additive.apply_archived_sums(daily, d["payload"]["data"]["metrics"], hae.METRIC_MAP, hae.parse_date_str, s3, BUCKET)
    objects = {f: json.loads(s3.objects[raw_date_key("apple_health", DAY, sub=f"additive_{f}")]) for f in mod.FIELDS}
    return {f: additive.day_value(f, o["readings"], o["units"]) for f, o in objects.items()}


def test_replay_equals_the_write_path_and_the_independent_unique_timestamp_sum():
    """The script's replay of the archived deliveries gives, for all five fields, exactly what the
    live writer stores after the same deliveries — and an independent sum over unique reading
    timestamps straight from the fixture. The dedup is exercised: a naive steps sum is >1000 higher."""
    fx = _fixture()
    s3 = FakeS3(fx["deliveries"])
    keys = mod.archive_keys(s3, BUCKET, DAY, DAY, date(2026, 10, 17))
    assert [k for k, _, _ in keys] and all(k.startswith("raw/matthew/health_auto_export/2026/10/") for k, _, _ in keys)
    assert {d for _, d, _ in keys} == {"2026-10-14", "2026-10-15"}, "the key's day is the DELIVERY day; both days carry 10-14 readings"
    replayed, stats = mod.replay(mod.read_payloads(s3, BUCKET, keys, workers=2))
    assert stats["payloads_read"] == 26 and stats["max_delivery_lag_days"] == 1
    got = mod.day_values(replayed[DAY])

    independent = {}
    for d in fx["deliveries"]:
        for m in d["payload"]["data"]["metrics"]:
            independent.setdefault(hae.METRIC_MAP[m["name"]]["field"], {})
            for r in m["data"]:  # a re-delivered timestamp counts at its newest distinct quantity (#4628 revisions)
                versions = independent[hae.METRIC_MAP[m["name"]]["field"]].setdefault(r["date"], [])
                if r["qty"] not in versions:
                    versions.append(r["qty"])
    independent = {f: round(sum(v[-1] for v in tsv.values()), 2) for f, tsv in independent.items()}
    naive_steps = sum(
        r["qty"] for d in fx["deliveries"] for m in d["payload"]["data"]["metrics"] if m["name"] == "step_count" for r in m["data"]
    )
    assert naive_steps - independent["steps"] > 1000, "the fixture lost its re-sent readings — the dedup is no longer exercised"

    assert set(got) == set(mod.FIELDS)
    assert got == pytest.approx(independent, abs=0.011)
    assert got == pytest.approx(_write_path_values(fx["deliveries"]), abs=1e-9)
    assert got["steps"] > fx["stored_before_fix"]["steps"]


def test_dry_run_reports_the_diff_and_writes_nothing():
    """Default mode against the pre-fix stored row: the day is reported as differing with the
    per-field deltas, days outside the archive are counted, and NEITHER store is written (both
    doubles refuse a write)."""
    fx = _fixture()
    s3 = FakeS3(fx["deliveries"], refuse_put=True)
    table = FakeTable([{"sk": f"DATE#{DAY}", **{k: Decimal(str(v)) for k, v in fx["stored_before_fix"].items()}}], refuse_write=True)
    text, report = _run(["--since", "2026-10-13", "--until", "2026-10-15"], s3, table)
    assert report["mode"] == "dry-run"
    assert report["days_read"] == 3 and report["days_with_archive"] == 1 and report["days_no_archive"] == 2
    assert report["days_differs"] == 1 and report["days_to_write"] == 1
    steps = report["per_field"]["steps"]
    assert (
        steps["days_differing"] == 1
        and steps["days_stored_under"] == 1
        and steps["sum_delta"] == pytest.approx(13157.82 - 11525.99, abs=0.011)  # 13157.82: the live 10-14 archive object
    )
    assert report["per_field"]["basal_calories"]["sum_delta"] > 600
    assert "apply" not in report
    assert re.search(rf"^{DAY}\s+\d+d\s+differs\s+steps: 11525.99->1315\d(\.\d+)? \(\+16\d\d", text, re.M), text
    assert not s3.puts and not table.updates


def test_apply_writes_exactly_the_rebuilt_fields_and_is_idempotent():
    """--apply: one UpdateItem per differing day, conditioned on the row existing, SETting the five
    fields as Decimal + the writer's derived total + the SCHEMA stamp and nothing else; the five
    per-field archive objects land at the registry-resolved keys with the same shape the writer
    sums from. A second --apply writes nothing; a dry run afterwards shows no difference."""
    fx = _fixture()
    s3 = FakeS3(fx["deliveries"])
    stored = {"sk": f"DATE#{DAY}", "sleep_hours": Decimal("7.1"), **{k: Decimal(str(v)) for k, v in fx["stored_before_fix"].items()}}
    table = FakeTable([stored, {"sk": f"DATE#{DAY}#WORKOUT#abc", "steps": Decimal(1)}])
    _, report = _run(["--since", DAY, "--until", DAY, "--apply"], s3, table)
    assert report["apply"] == {"archive_objects_written": 5, "rows_written": 1, "rows_refused": 0}

    ((key, expr, names, values),) = table.updates
    assert key == {"pk": PK, "sk": f"DATE#{DAY}"}
    assert expr.startswith("SET ") and " REMOVE " not in expr and " ADD " not in expr
    written = {names[n]: values[v] for n, v in re.findall(r"(#[A-Za-z0-9]+) = (:[A-Za-z0-9]+)", expr)}
    assert set(written) == set(mod.FIELDS) | {mod.DERIVED, additive.PROVENANCE_FIELD}
    assert written[additive.PROVENANCE_FIELD] is True
    expected = _write_path_values(fx["deliveries"])
    for f in mod.FIELDS:
        assert isinstance(written[f], Decimal) and float(written[f]) == pytest.approx(expected[f], abs=1e-9), f
    assert float(written[mod.DERIVED]) == pytest.approx(expected["active_calories"] + expected["basal_calories"], abs=0.011)
    assert table.rows[f"DATE#{DAY}"]["sleep_hours"] == Decimal("7.1"), "an unrelated field is never touched"
    assert "steps" in table.rows[f"DATE#{DAY}#WORKOUT#abc"] and table.rows[f"DATE#{DAY}#WORKOUT#abc"]["steps"] == Decimal(1)

    for f in mod.FIELDS:
        obj = json.loads(s3.objects[raw_date_key("apple_health", DAY, sub=f"additive_{f}")])
        assert set(obj) - {"revisions"} == {"field", "date", "units", "readings"} and obj["field"] == f and obj["date"] == DAY
    # the fixture's same-second pair re-delivered two readings with a new quantity: both versions are kept
    steps_obj = json.loads(s3.objects[raw_date_key("apple_health", DAY, sub="additive_steps")])
    assert [q for _, q in steps_obj["revisions"]["Matt 17"]["2026-10-14 15:57:09 -0700"]] == [103.9283, 31.7674]
    assert sum(len(t) for t in json.loads(s3.objects[raw_date_key("apple_health", DAY, sub="additive_steps")])["readings"].values()) == 185

    _, again = _run(["--since", DAY, "--until", DAY, "--apply"], s3, table)
    assert again["apply"] == {"archive_objects_written": 0, "rows_written": 0, "rows_refused": 0}
    assert len(table.updates) == 1
    _, after = _run(["--since", DAY, "--until", DAY], s3, table)
    assert after["days_differs"] == 0 and after["days_same"] == 1 and after["days_to_write"] == 0


def test_a_day_with_archive_but_no_row_is_reported_and_never_created():
    fx = _fixture()
    s3 = FakeS3(fx["deliveries"])
    table = FakeTable([])
    _, report = _run(["--since", DAY, "--until", DAY, "--apply"], s3, table)
    assert report["days_no_row"] == 1 and report["days_to_write"] == 0
    assert report["apply"]["rows_written"] == 0 and not table.rows and not s3.puts
