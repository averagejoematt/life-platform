"""test_coach_corrections.py — the #1689 corrections-ledger contract.

Pins: the pure item-builder's shape (pk/sk/Decimal-safety/error-class normalization),
the writer/reader idiom (table passed in, mockable with FakeDdbTable), and the
status-transition guard. Fully offline — mirrors tests/test_eval_retention.py.
"""

import os
import sys
from datetime import datetime, timezone
from decimal import Decimal

os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import coach_corrections as cc  # noqa: E402
import pytest  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402


@pytest.fixture
def table():
    return FakeDdbTable()


# ── build_correction_item: pure, no AWS ─────────────────────────────────────
def test_build_correction_item_shape():
    item = cc.build_correction_item(
        {"surface": "coach_brief", "coach": "sleep_coach", "date": "2026-07-20", "pack_number": 3},
        "The 315 lbs baseline is stale — I'm 321.4 as of genesis.",
        "stale-baseline",
        now=datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc),
        correction_id="a1b2c3d4",
    )
    assert item["pk"] == "USER#matthew#SOURCE#coach_corrections"
    assert item["sk"] == "CORRECTION#2026-07-22#a1b2c3d4"
    assert item["correction_id"] == "a1b2c3d4"
    assert item["error_class"] == "stale-baseline"
    assert item["status"] == "open"
    assert item["created_at"] == "2026-07-22T12:00:00+00:00"
    assert item["correction_text"].startswith("The 315 lbs baseline")
    assert item["item_ref"]["coach"] == "sleep_coach"
    assert "error_class_raw" not in item


def test_build_correction_item_generates_id_and_now_when_omitted():
    item = cc.build_correction_item({"surface": "coach_brief"}, "text", "framing")
    assert item["sk"].startswith("CORRECTION#")
    prefix_len = len(cc.SK_PREFIX)
    date_part, id_part = item["sk"][prefix_len:].split("#")
    assert len(date_part) == 10  # YYYY-MM-DD
    assert len(id_part) == 8
    assert item["correction_id"] == id_part


@pytest.mark.parametrize("error_class", list(cc.ERROR_CLASSES))
def test_all_known_error_classes_pass_through_unchanged(error_class):
    item = cc.build_correction_item({}, "x", error_class)
    assert item["error_class"] == error_class
    assert "error_class_raw" not in item


def test_unknown_error_class_normalizes_to_other_without_dropping_it():
    item = cc.build_correction_item({}, "x", "some-brand-new-class-nobody-registered")
    assert item["error_class"] == "other"
    assert item["error_class_raw"] == "some-brand-new-class-nobody-registered"


def test_item_ref_numeric_fields_cast_to_decimal():
    item = cc.build_correction_item({"pack_number": 3.0, "confidence": 0.82}, "x", "checkable-metric")
    assert isinstance(item["item_ref"]["pack_number"], Decimal)
    assert isinstance(item["item_ref"]["confidence"], Decimal)
    assert item["item_ref"]["pack_number"] == Decimal("3.0")
    # No bare float ever reaches DDB attribute level
    assert not any(isinstance(v, float) for v in item["item_ref"].values())


def test_item_ref_none_becomes_empty_dict():
    item = cc.build_correction_item(None, "x", "other")
    assert item["item_ref"] == {}


def test_error_classes_tuple_has_other_fallback():
    assert "other" in cc.ERROR_CLASSES
    assert cc.ERROR_CLASSES == (
        "stale-baseline",
        "ungrounded-behavioral",
        "cross-coach-inconsistency",
        "framing",
        "checkable-metric",
        "hedged-safe",
        "defense-held",
        "other",
    )


# ── write_correction: mockable table ────────────────────────────────────────
def test_write_correction_puts_and_returns_sk(table):
    sk = cc.write_correction(
        table,
        {"surface": "coach_brief", "coach": "mind_coach"},
        "You didn't log an eating window today; I can't ground that claim.",
        "ungrounded-behavioral",
    )
    assert sk.startswith("CORRECTION#")
    assert len(table.puts) == 1
    assert table.puts[0]["sk"] == sk
    assert table.puts[0]["error_class"] == "ungrounded-behavioral"


def test_write_correction_raises_on_ddb_error():
    def _fail(*_a, **_kw):
        raise RuntimeError("simulated DDB outage")

    failing_table = FakeDdbTable(put_item_hook=_fail)
    with pytest.raises(RuntimeError):
        cc.write_correction(failing_table, {}, "x", "framing")


# ── get_correction / list_corrections / update_status ──────────────────────
def test_get_correction_round_trip(table):
    sk = cc.write_correction(table, {"surface": "x"}, "text", "framing")
    got = cc.get_correction(table, sk)
    assert got is not None
    assert got["sk"] == sk
    assert got["correction_text"] == "text"


def test_get_correction_missing_returns_none(table):
    assert cc.get_correction(table, "CORRECTION#2026-01-01#deadbeef") is None


def test_list_corrections_filters_by_status_and_error_class():
    rows = [
        cc.build_correction_item({}, "a", "stale-baseline", correction_id="aaaaaaaa"),
        cc.build_correction_item({}, "b", "framing", correction_id="bbbbbbbb"),
        {**cc.build_correction_item({}, "c", "stale-baseline", correction_id="cccccccc"), "status": "applied-to-gate"},
    ]
    t = FakeDdbTable(rows=rows)
    all_rows = cc.list_corrections(t)
    assert len(all_rows) == 3

    stale = cc.list_corrections(t, error_class="stale-baseline")
    assert {r["correction_id"] for r in stale} == {"aaaaaaaa", "cccccccc"}

    open_only = cc.list_corrections(t, status="open")
    assert {r["correction_id"] for r in open_only} == {"aaaaaaaa", "bbbbbbbb"}

    open_stale = cc.list_corrections(t, status="open", error_class="stale-baseline")
    assert [r["correction_id"] for r in open_stale] == ["aaaaaaaa"]


def test_list_corrections_respects_limit():
    rows = [cc.build_correction_item({}, str(i), "other", correction_id=f"{i:08d}") for i in range(5)]
    t = FakeDdbTable(rows=rows)
    assert len(cc.list_corrections(t, limit=2)) == 2
    assert len(cc.list_corrections(t, limit=100)) == 5


def test_list_corrections_queries_the_partition_key():
    t = FakeDdbTable(rows=[])
    cc.list_corrections(t)
    assert len(t.query_calls) == 1


def test_update_status_writes_expected_expression(table):
    sk = cc.write_correction(table, {}, "x", "framing")
    assert cc.update_status(table, sk, "applied-to-prompt") is True
    assert len(table.updates) == 1
    call = table.updates[0]
    assert call["Key"] == {"pk": cc.PK, "sk": sk}
    assert call["ExpressionAttributeValues"][":s"] == "applied-to-prompt"


def test_update_status_rejects_unknown_status(table):
    sk = cc.write_correction(table, {}, "x", "framing")
    with pytest.raises(ValueError):
        cc.update_status(table, sk, "resolved-forever")
    assert len(table.updates) == 0


@pytest.mark.parametrize("status", list(cc.STATUSES))
def test_all_known_statuses_accepted(table, status):
    sk = cc.write_correction(table, {}, "x", "framing")
    assert cc.update_status(table, sk, status) is True
