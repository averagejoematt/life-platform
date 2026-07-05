"""tests/test_food_delivery_reimport_479.py — #479 (B-6, epic #460).

A partial or re-ordered delivery CSV must not corrupt lifetime aggregates —
required before the Monarch feed reuses food_delivery_lambda's ingest path.
Exercises `ingest_food_delivery_rows` (the shared idempotent-fold core, not
just the S3-triggered lambda_handler wrapper) directly against an in-memory
fake DynamoDB table, so no real AWS/DynamoDB access happens.
"""

import csv
import os
import random
import sys
from decimal import Decimal

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "lambdas", "ingestion"))

import food_delivery_lambda as fd  # noqa: E402

PK = fd.PK


class FakeTable:
    """Minimal in-memory stand-in for the `life-platform` DynamoDB table —
    just enough of put_item/query/batch_writer to exercise the real fold
    logic without touching AWS."""

    def __init__(self):
        self.items = {}  # (pk, sk) -> item dict

    def put_item(self, Item):
        self.items[(Item["pk"], Item["sk"])] = dict(Item)

    def get_item(self, Key):
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item else {}

    def query(self, KeyConditionExpression=None, ExpressionAttributeValues=None, ExclusiveStartKey=None, **kw):
        pk = ExpressionAttributeValues[":pk"]
        results = [dict(v) for (p, _s), v in self.items.items() if p == pk]
        return {"Items": results}

    def batch_writer(self):
        return _FakeBatchWriter(self)


class _FakeBatchWriter:
    def __init__(self, table):
        self.table = table

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def put_item(self, Item):
        self.table.put_item(Item=Item)


def _phase_for_test(date_str):
    return "experiment"


def _rows(csv_text):
    return list(csv.DictReader(csv_text.splitlines()))


CSV_HEADER = "Date,Merchant,Category,Account,Original Statement,Notes,Amount,Tags,Owner\n"

# 6 real transactions across 3 days in July 2026:
#   07-01: 2 orders ($20 + $15 = $35)  -> not a binge day
#   07-03: 1 order  ($30)              -> not a binge day
#   07-05: 3 orders ($10 + $12 + $8 = $30) -> binge day (>=3)
# Total: 6 orders, $95.00
CSV_FULL = CSV_HEADER + (
    "2026-07-01,DOORDASH*RESTAURANT,Food Delivery,Chase Sapphire,DOORDASH*RESTAURANT SF CA,,-20.00,,Matthew\n"
    "2026-07-01,UBER *EATS,Food Delivery,Chase Sapphire,UBER *EATS HELP.UBER.COM,,-15.00,,Matthew\n"
    "2026-07-03,DOORDASH*PIZZA,Food Delivery,Chase Sapphire,DOORDASH*PIZZA SF CA,,-30.00,,Matthew\n"
    "2026-07-05,GRUBHUB,Food Delivery,Chase Sapphire,GRUBHUB SF CA,,-10.00,,Matthew\n"
    "2026-07-05,DOORDASH*TACOS,Food Delivery,Chase Sapphire,DOORDASH*TACOS SF CA,,-12.00,,Matthew\n"
    "2026-07-05,UBER *EATS,Food Delivery,Chase Sapphire,UBER *EATS HELP.UBER.COM,,-8.00,,Matthew\n"
)

# A truncated export containing only the first 3 rows of CSV_FULL (as if the
# statement was pulled mid-month, or the export got cut off).
CSV_PARTIAL = CSV_HEADER + (
    "2026-07-01,DOORDASH*RESTAURANT,Food Delivery,Chase Sapphire,DOORDASH*RESTAURANT SF CA,,-20.00,,Matthew\n"
    "2026-07-01,UBER *EATS,Food Delivery,Chase Sapphire,UBER *EATS HELP.UBER.COM,,-15.00,,Matthew\n"
    "2026-07-03,DOORDASH*PIZZA,Food Delivery,Chase Sapphire,DOORDASH*PIZZA SF CA,,-30.00,,Matthew\n"
)

# Two genuinely separate orders that happen to have identical content (same
# merchant, same amount, same day) — the natural key alone can't tell them
# apart, so the disambiguation suffix must keep both.
CSV_EXACT_DUPLICATES = CSV_HEADER + (
    "2026-07-10,DOORDASH*BURGER,Food Delivery,Chase Sapphire,DOORDASH*BURGER SF CA,,-18.00,,Matthew\n"
    "2026-07-10,DOORDASH*BURGER,Food Delivery,Chase Sapphire,DOORDASH*BURGER SF CA,,-18.00,,Matthew\n"
)


def _txn_items(table, date_str=None):
    items = [v for (_p, s), v in table.items.items() if "#TXN#" in s]
    if date_str:
        items = [it for it in items if it["date"] == date_str]
    return items


def test_full_reimport_of_same_file_does_not_double_count():
    """Importing the exact same CSV twice must be a safe no-op."""
    table = FakeTable()
    fd.ingest_food_delivery_rows(table, _rows(CSV_FULL), "2026-07-06", phase_for=_phase_for_test)

    month_1 = dict(table.items[(PK, "MONTH#2026-07")])
    streak_1 = dict(table.items[(PK, "STREAK#current")])
    txn_count_1 = len(_txn_items(table))

    fd.ingest_food_delivery_rows(table, _rows(CSV_FULL), "2026-07-06", phase_for=_phase_for_test)

    month_2 = table.items[(PK, "MONTH#2026-07")]
    streak_2 = table.items[(PK, "STREAK#current")]
    txn_count_2 = len(_txn_items(table))

    assert txn_count_1 == txn_count_2 == 6
    assert month_1["order_count"] == month_2["order_count"] == 6
    assert month_1["total_spend"] == month_2["total_spend"] == Decimal("95.00")
    for key in ("last_order_date", "last_order_amount", "last_order_merchant", "streak_days", "streak_start", "longest_ever_streak"):
        assert streak_1[key] == streak_2[key]


def test_reordered_reimport_does_not_double_count():
    """A reordered copy of the same file (e.g. a re-export that sorted
    differently) must produce the identical canonical state — same txn keys,
    same aggregates — not a duplicated set of records."""
    table = FakeTable()
    fd.ingest_food_delivery_rows(table, _rows(CSV_FULL), "2026-07-06", phase_for=_phase_for_test)
    month_1 = dict(table.items[(PK, "MONTH#2026-07")])
    txn_keys_1 = sorted(s for (_p, s) in table.items if "#TXN#" in s)

    reordered = _rows(CSV_FULL)
    random.Random(42).shuffle(reordered)
    fd.ingest_food_delivery_rows(table, reordered, "2026-07-06", phase_for=_phase_for_test)

    month_2 = table.items[(PK, "MONTH#2026-07")]
    txn_keys_2 = sorted(s for (_p, s) in table.items if "#TXN#" in s)

    assert txn_keys_1 == txn_keys_2
    assert month_1["order_count"] == month_2["order_count"] == 6
    assert month_1["total_spend"] == month_2["total_spend"] == Decimal("95.00")


def test_partial_then_full_yields_correct_total():
    """A truncated/partial import followed by the full file must land on the
    correct final total — the partial import's dates get folded together
    with the full file's, not overwritten/lost."""
    table = FakeTable()
    fd.ingest_food_delivery_rows(table, _rows(CSV_PARTIAL), "2026-07-04", phase_for=_phase_for_test)

    partial_month = table.items[(PK, "MONTH#2026-07")]
    assert partial_month["order_count"] == 3
    assert partial_month["total_spend"] == Decimal("65.00")

    fd.ingest_food_delivery_rows(table, _rows(CSV_FULL), "2026-07-06", phase_for=_phase_for_test)

    final_month = table.items[(PK, "MONTH#2026-07")]
    assert final_month["order_count"] == 6
    assert final_month["total_spend"] == Decimal("95.00")
    assert len(_txn_items(table)) == 6

    streak = table.items[(PK, "STREAK#current")]
    assert streak["last_order_date"] == "2026-07-05"


def test_full_then_partial_does_not_regress_total():
    """Order shouldn't matter: the full file first, then a partial/older
    re-export second, must NOT roll the total backwards."""
    table = FakeTable()
    fd.ingest_food_delivery_rows(table, _rows(CSV_FULL), "2026-07-06", phase_for=_phase_for_test)
    fd.ingest_food_delivery_rows(table, _rows(CSV_PARTIAL), "2026-07-07", phase_for=_phase_for_test)

    final_month = table.items[(PK, "MONTH#2026-07")]
    assert final_month["order_count"] == 6
    assert final_month["total_spend"] == Decimal("95.00")
    assert len(_txn_items(table)) == 6

    streak = table.items[(PK, "STREAK#current")]
    assert streak["last_order_date"] == "2026-07-05"


def test_day_level_fields_stay_correct_across_partial_then_full():
    """orders_that_day / is_binge_day must reflect the canonical per-day
    count, not just what happened to be in whichever file wrote the item —
    including for records written by an EARLIER, smaller import."""
    table = FakeTable()
    fd.ingest_food_delivery_rows(table, _rows(CSV_PARTIAL), "2026-07-04", phase_for=_phase_for_test)
    # At this point 07-01 has 2 orders written with orders_that_day=2 — correct already.
    jul1_before = _txn_items(table, "2026-07-01")
    assert all(it["orders_that_day"] == 2 for it in jul1_before)

    fd.ingest_food_delivery_rows(table, _rows(CSV_FULL), "2026-07-06", phase_for=_phase_for_test)

    jul1_after = _txn_items(table, "2026-07-01")
    jul5_after = _txn_items(table, "2026-07-05")
    assert len(jul1_after) == 2
    assert all(it["orders_that_day"] == 2 and it["is_binge_day"] is False for it in jul1_after)
    assert len(jul5_after) == 3
    assert all(it["orders_that_day"] == 3 and it["is_binge_day"] is True for it in jul5_after)


def test_exact_duplicate_rows_are_both_kept_and_reimport_is_idempotent():
    """Two genuinely separate orders with identical content (same merchant/
    amount/day) must both survive — the natural key alone collides, so the
    disambiguation suffix must keep them distinct. Re-importing the same
    file must not add a third."""
    table = FakeTable()
    fd.ingest_food_delivery_rows(table, _rows(CSV_EXACT_DUPLICATES), "2026-07-11", phase_for=_phase_for_test)

    dup_items = _txn_items(table, "2026-07-10")
    assert len(dup_items) == 2
    month = table.items[(PK, "MONTH#2026-07")]
    assert month["order_count"] == 2
    assert month["total_spend"] == Decimal("36.00")

    fd.ingest_food_delivery_rows(table, _rows(CSV_EXACT_DUPLICATES), "2026-07-11", phase_for=_phase_for_test)

    dup_items_2 = _txn_items(table, "2026-07-10")
    assert len(dup_items_2) == 2
    month_2 = table.items[(PK, "MONTH#2026-07")]
    assert month_2["order_count"] == 2
    assert month_2["total_spend"] == Decimal("36.00")


def test_year_aggregate_reflects_canonical_month_totals_after_partial_then_full():
    table = FakeTable()
    fd.ingest_food_delivery_rows(table, _rows(CSV_PARTIAL), "2026-07-04", phase_for=_phase_for_test)
    fd.ingest_food_delivery_rows(table, _rows(CSV_FULL), "2026-07-06", phase_for=_phase_for_test)

    year = table.items[(PK, "YEAR#2026")]
    assert year["order_count"] == 6
    assert year["total_spend"] == Decimal("95.00")


def test_lambda_handler_end_to_end_with_fake_s3_and_table(monkeypatch):
    """Smoke-test the S3-triggered wrapper still wires up correctly after the
    refactor: it should call the shared idempotent fold and write the
    freshness marker, without touching real AWS."""
    table = FakeTable()

    class _FakeDDBResource:
        def Table(self, name):
            return table

    fake_s3 = type("FakeS3", (), {})()
    fake_s3.get_object = lambda Bucket, Key: {"Body": type("B", (), {"read": lambda self: CSV_FULL.encode("utf-8")})()}

    monkeypatch.setattr(fd.boto3, "client", lambda *a, **k: fake_s3)
    monkeypatch.setattr(fd.boto3, "resource", lambda *a, **k: _FakeDDBResource())

    event = {"Records": [{"s3": {"bucket": {"name": "test-bucket"}, "object": {"key": "imports/food_delivery/q3.csv"}}}]}
    result = fd.lambda_handler(event, None)

    assert result["statusCode"] == 200
    month = table.items[(PK, "MONTH#2026-07")]
    assert month["order_count"] == 6

    freshness_keys = [s for (_p, s) in table.items if s.startswith("DATE#") and "#TXN#" not in s]
    assert len(freshness_keys) == 1
    freshness = table.items[(PK, freshness_keys[0])]
    assert freshness["records_imported"] == 6
