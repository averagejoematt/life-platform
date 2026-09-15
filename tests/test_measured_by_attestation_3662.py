"""tests/test_measured_by_attestation_3662.py — #3662: `measured_by` is real, not a literal.

Four halves, four groups of tests:

1. `_row_to_session` reads an optional `measured_by` CSV/Excel column (a fixture row
   naming a measurer round-trips all the way to the written DDB item — a planted
   hard-coded literal REDS `test_lambda_handler_writes_the_csvs_named_measurer`).
2. A row with no `measured_by` column falls back to the stated `"unrecorded"`
   literal, never to a fabricated identity (ADR-104) and never to the old
   `"partner"` default.
3. `physical_overview` (the site-api serving path) now serves `measured_by` — it
   used to be read off the DDB item and then explicitly discarded.
4. When the latest and previous tape sessions carry different `measured_by`
   values, `physical_overview` surfaces that as a `measurer_changed` flag plus a
   rendered `measurer_change_note` — never silently presenting the delta as one
   instrument's reading.

`scripts/check_ingestion_hardcoded_literals.py` (wired by
`tests/test_ingestion_hardcoded_literal_guard_3662.py`) is the generalized AST
sweep for acceptance criterion 3; not duplicated here.
"""

import csv
import io
import json
import os
import sys
from decimal import Decimal

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "lambdas", "ingestion"))

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")

import measurements_ingestion_lambda as mi  # noqa: E402

# ──────────────────────────────────────────────────────────────────────────────
# Fakes (same shape as tests/test_macrofactor_ingestion_behavior.py's FakeTable/FakeS3)
# ──────────────────────────────────────────────────────────────────────────────


class FakeTable:
    def __init__(self, seed_items=None):
        self.items = {(it["pk"], it["sk"]): it for it in (seed_items or [])}
        self.puts = []

    def put_item(self, Item):  # noqa: N803
        self.puts.append(Item)
        self.items[(Item.get("pk"), Item.get("sk"))] = Item

    def get_item(self, Key):  # noqa: N803
        item = self.items.get((Key.get("pk"), Key.get("sk")))
        return {"Item": item} if item else {}

    def query(self, **kwargs):
        # only ever used here with Key("pk").eq(PK) & Key("sk").begins_with("DATE#")
        out = [v for (p, s), v in self.items.items() if p == mi.PK and s.startswith("DATE#")]
        return {"Items": [{"sk": it["sk"]} for it in out]}


class _Body:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return self._payload


class FakeS3:
    def __init__(self, payload=b""):
        self.payload = payload

    def get_object(self, Bucket, Key):  # noqa: N803
        return {"Body": _Body(self.payload)}


HEADERS = ["date", "waist_narrowest_in", "waist_navel_in", "measured_by", "notes"]


def csv_bytes(rows):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=HEADERS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({h: row.get(h, "") for h in HEADERS})
    return buf.getvalue().encode("utf-8")


def invoke(monkeypatch, payload, table=None):
    table = table or FakeTable()
    s3 = FakeS3(payload)
    monkeypatch.setattr(mi, "table", table)
    monkeypatch.setattr(mi, "s3", s3)
    response = mi.lambda_handler({"bucket": "test-bucket", "key": "imports/measurements/session.csv"}, None)
    return response, table


# ──────────────────────────────────────────────────────────────────────────────
# 1 + 2. The override + the correctness (ingestion)
# ──────────────────────────────────────────────────────────────────────────────


def test_row_to_session_reads_the_measured_by_column():
    row = {"date": "2026-09-06", "waist_narrowest_in": "49.0", "waist_navel_in": "55.5", "measured_by": "matthew (self)"}
    session = mi._row_to_session(row)
    assert session["measured_by"] == "matthew (self)"


def test_row_to_session_falls_back_to_unrecorded_not_partner():
    row = {"date": "2026-03-29", "waist_narrowest_in": "52.0", "waist_navel_in": "52.0"}
    session = mi._row_to_session(row)
    assert session["measured_by"] == "unrecorded"
    assert session["measured_by"] != "partner"


def test_lambda_handler_writes_the_csvs_named_measurer(monkeypatch):
    """The must-fail case: a fixture row naming a measurer round-trips to DDB.

    If `lambda_handler` ever goes back to hard-coding `"measured_by": "partner"`
    (the #3662 regression), this assertion breaks even though the CSV explicitly
    named a different, real measurer.
    """
    payload = csv_bytes([{"date": "2026-09-06", "waist_narrowest_in": "49.0", "waist_navel_in": "55.5", "measured_by": "matthew (self)"}])
    response, table = invoke(monkeypatch, payload)
    assert response["statusCode"] == 200
    item = table.items[(mi.PK, "DATE#2026-09-06")]
    assert item["measured_by"] == "matthew (self)"
    assert item["measured_by"] != "partner"


def test_lambda_handler_missing_column_is_unrecorded_not_partner(monkeypatch):
    payload = csv_bytes([{"date": "2026-03-29", "waist_narrowest_in": "52.0", "waist_navel_in": "52.0"}])
    response, table = invoke(monkeypatch, payload)
    assert response["statusCode"] == 200
    item = table.items[(mi.PK, "DATE#2026-03-29")]
    assert item["measured_by"] == "unrecorded"
    assert item["measured_by"] != "partner"


def test_multi_row_csv_preserves_each_rows_own_measurer(monkeypatch):
    payload = csv_bytes(
        [
            {"date": "2026-03-29", "waist_narrowest_in": "49.5", "waist_navel_in": "52.0", "measured_by": "brittany"},
            {"date": "2026-09-06", "waist_narrowest_in": "49.0", "waist_navel_in": "55.5", "measured_by": "matthew (self)"},
        ]
    )
    response, table = invoke(monkeypatch, payload)
    assert response["statusCode"] == 200
    assert table.items[(mi.PK, "DATE#2026-03-29")]["measured_by"] == "brittany"
    assert table.items[(mi.PK, "DATE#2026-09-06")]["measured_by"] == "matthew (self)"


# ──────────────────────────────────────────────────────────────────────────────
# 3 + 4. The serving + the disclosure (site_api_physical.physical_overview)
# ──────────────────────────────────────────────────────────────────────────────


def _import_site_api_physical():
    if "web.site_api_physical" in sys.modules:
        del sys.modules["web.site_api_physical"]
    from web import site_api_physical as physical

    return physical


def _condition_strings(cond):
    """Recursively pull every string operand out of a boto3 Condition tree."""
    out = []
    values = getattr(cond, "_values", None)
    if not values:
        return out
    for v in values:
        if isinstance(v, str):
            out.append(v)
        elif hasattr(v, "_values"):
            out.extend(_condition_strings(v))
    return out


class _FakeQueryTable:
    """Enough of a DDB Table double to drive `physical_overview`'s tape-measurement
    branch — dexa/blood-pressure branches see empty results by construction."""

    def __init__(self, measurement_items):
        self._measurement_items = measurement_items

    def query(self, **kwargs):
        strings = _condition_strings(kwargs.get("KeyConditionExpression"))
        if any("measurements" in s for s in strings):
            return {"Items": list(self._measurement_items)}
        return {"Items": []}

    def get_item(self, Key):  # noqa: N803
        return {}


def _session(date, measured_by, waist_narrowest, session_number):
    return {
        "pk": "USER#matthew#SOURCE#measurements",
        "sk": f"DATE#{date}",
        "date": date,
        "unit": "in",
        "session_number": session_number,
        "measured_by": measured_by,
        "waist_narrowest_in": Decimal(str(waist_narrowest)),
        "waist_navel_in": Decimal("55.5"),
    }


def _call_physical_overview(measurement_items):
    physical = _import_site_api_physical()
    table = _FakeQueryTable(measurement_items)
    _g = {
        "table": table,
        "EXPERIMENT_START": "2026-09-06",
    }
    response = physical.physical_overview(_g=_g)
    return json.loads(response["body"])


def test_physical_overview_serves_measured_by():
    # descending order (ScanIndexForward=False) — latest first
    items = [_session("2026-09-06", "matthew (self)", 49.0, 2), _session("2026-03-29", "brittany", 49.5, 1)]
    resp = _call_physical_overview(items)
    tape = resp["tape_measurements"]
    assert tape["measured_by"] == "matthew (self)"


def test_physical_overview_flags_a_measurer_change_between_sessions():
    items = [_session("2026-09-06", "matthew (self)", 49.0, 2), _session("2026-03-29", "brittany", 49.5, 1)]
    resp = _call_physical_overview(items)
    tape = resp["tape_measurements"]
    assert tape["measurer_changed"] is True
    assert "matthew (self)" in tape["measurer_change_note"]
    assert "brittany" in tape["measurer_change_note"]
    assert tape["previous_session"]["measured_by"] == "brittany"


def test_physical_overview_does_not_flag_when_measurer_is_unchanged():
    items = [_session("2026-09-06", "brittany", 49.0, 2), _session("2026-03-29", "brittany", 49.5, 1)]
    resp = _call_physical_overview(items)
    tape = resp["tape_measurements"]
    assert tape["measurer_changed"] is False
    assert "measurer_change_note" not in tape


def test_physical_overview_single_session_carries_no_change_flag():
    items = [_session("2026-09-06", "matthew (self)", 49.0, 1)]
    resp = _call_physical_overview(items)
    tape = resp["tape_measurements"]
    assert tape["measured_by"] == "matthew (self)"
    assert "measurer_changed" not in tape
    assert "previous_session" not in tape
