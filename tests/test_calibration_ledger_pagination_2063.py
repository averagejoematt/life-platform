"""tests/test_calibration_ledger_pagination_2063.py — the calibration ledger read
returns the WHOLE partition, not one page of it.

CONFIRMED regression this pins the fix for (#2063). After the #1978 reconcile wrote
its void backfill, `/api/calibration` served `voided.n = 971` where the ledger held
1,708 void rows, and the lifetime Brier denominator quietly shrank — the exact
class of silent-denominator regression #1893 exists to prevent, caused by #1893's
own correction landing.

The mechanism is NOT what "Limit=1500" suggests, and that is the whole lesson:

  * A DynamoDB query page is capped at **1MB of items read from the table**,
    whichever of {Limit, 1MB} comes first. The CALIB# ledger's ~1.1KB rows hit 1MB
    at ~977 rows — so the "Limit-1500" read was returning 977 of 1,731 rows.
    Raising Limit would not have moved it one row.
  * The 1MB cap is applied BEFORE `ProjectionExpression`, so trimming the row
    payload does not buy more rows per page either (measured against the live
    partition: projected to a single attribute, the page still stopped at 977).
  * The read is `ScanIndexForward=False` — newest-first — so the rows that fall
    off the end are the OLDEST. Those carry the earliest graded bets, which is why
    the career/lifetime pair counts shrank and not just the void tally.

Only following `LastEvaluatedKey` returns the ledger. These tests pin:

  1. the ledger fetch paginates — a >1,500-row partition served in pages comes
     back whole, and the OLDEST rows (last page) are present and scored;
  2. the coach PREDICTION# partitions deliberately do NOT paginate (they are
     217–372 projected rows each, one page with room to spare — paying a
     per-coach round trip would re-open the #1527 latency regression);
  3. pagination is bounded: a partition that never stops paging is cut off at
     `_MAX_QUERY_PAGES` and logged LOUD, rather than looping the Lambda to
     timeout — truncation may never again be silent;
  4. every page's query carries the SAME key condition/projection (only
     `ExclusiveStartKey` advances), so page 2+ cannot read a different shape.
"""

import json
import os
import sys

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

from fakes import FakeDdbTable  # noqa: E402
from web import site_api_coach as api  # noqa: E402

# The live 1MB-page boundary the bug fell off: ~977 CALIB# rows. Using the real
# measured number (not a round 1,500) keeps the fixture honest about the mechanism.
PAGE_SIZE = 977

# >1,500 rows, per the #2063 acceptance box. Split so the oldest rows land on a
# LATER page than the boundary — i.e. exactly where the old single fetch lost them.
VOIDS_PER_RESET = 900  # × 2 resets = 1,800 void rows
GRADED_OLD = 40  # the oldest graded bets — page 2, invisible before this fix


def _void(genesis, i):
    """One `voided_at_reset` row, the shape restart_pipeline.build_void_calib_item writes."""
    return {
        "pk": "USER#matthew#SOURCE#calibration",
        "sk": f"CALIB#{genesis}#void#prediction#{i:05d}",
        "record_type": "prediction_void",
        "outcome": "voided_at_reset",
        "reset_genesis": genesis,
        "stated_confidence": "medium",
    }


def _graded(i, resolved_at):
    """One graded hypothesis row — contributes a (confidence, outcome) Brier pair."""
    return {
        "pk": "USER#matthew#SOURCE#calibration",
        "sk": f"CALIB#{resolved_at}#hyp#{i:05d}",
        "record_type": "hypothesis_resolution",
        "outcome": "confirmed" if i % 2 == 0 else "refuted",
        "stated_confidence": "high",
        "resolved_at": resolved_at,
    }


def _ledger_rows():
    """A newest-first CALIB# ledger of >1,500 rows whose OLDEST slice is graded.

    Ordering matters: the handler reads ScanIndexForward=False, so index 0 is the
    newest row and the tail is the oldest. The graded rows sit in the tail, past
    PAGE_SIZE — the position from which the pre-#2063 read dropped them.
    """
    rows = [_void("2026-07-27", i) for i in range(VOIDS_PER_RESET)]
    rows += [_void("2026-07-13", i) for i in range(VOIDS_PER_RESET)]
    rows += [_graded(i, "2026-04-02") for i in range(GRADED_OLD)]
    return rows


LEDGER = _ledger_rows()
assert len(LEDGER) > 1500, "the #2063 acceptance box requires a >1,500-row fixture"
assert len(LEDGER) - GRADED_OLD > PAGE_SIZE, "the oldest graded rows must sit past the first page"


class PagingFake(FakeDdbTable):
    """A fake that paginates like DynamoDB: serves `page_size` items and hands back
    a LastEvaluatedKey until the partition is exhausted.

    `ledger_rows` backs the CALIB# partition; every other pk gets `coach_rows`
    (small enough to fit one page, like the live coach partitions)."""

    def __init__(self, ledger_rows, coach_rows=(), page_size=PAGE_SIZE):
        super().__init__()
        self.ledger_rows = list(ledger_rows)
        self.coach_rows = list(coach_rows)
        self.page_size = page_size
        self.pages_by_pk = {}

    def query(self, **kwargs):
        self.query_calls.append(kwargs)
        pk = kwargs["KeyConditionExpression"]._values[0]._values[1]
        rows = self.ledger_rows if pk.endswith("SOURCE#calibration") else self.coach_rows
        start = int(kwargs.get("ExclusiveStartKey", {}).get("_offset", 0))
        page = rows[start : start + self.page_size]
        self.pages_by_pk[pk] = self.pages_by_pk.get(pk, 0) + 1
        resp = {"Items": page}
        if start + self.page_size < len(rows):
            resp["LastEvaluatedKey"] = {"_offset": start + self.page_size}
        return resp


def _body(resp):
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])


class TestLedgerReadReturnsTheWholePartition:
    def test_voided_count_is_the_full_ledger_not_one_page(self, monkeypatch):
        """The headline #2063 regression: voided.n must be the census, not a page."""
        fake = PagingFake(LEDGER)
        monkeypatch.setattr(api, "table", fake)
        voided = _body(api.handle_calibration({}))["voided"]

        expected = sum(1 for r in LEDGER if r.get("outcome") == "voided_at_reset")
        assert voided["n"] == expected == VOIDS_PER_RESET * 2
        # ...and it is strictly more than one page could ever have carried.
        assert voided["n"] > PAGE_SIZE

    def test_by_reset_matches_the_ledger_census(self, monkeypatch):
        """Every reset's void tally, not just the resets inside the first page."""
        fake = PagingFake(LEDGER)
        monkeypatch.setattr(api, "table", fake)
        by_reset = _body(api.handle_calibration({}))["voided"]["by_reset"]

        census = {}
        for r in LEDGER:
            if r.get("outcome") == "voided_at_reset":
                g = r["reset_genesis"]
                census[g] = census.get(g, 0) + 1
        assert by_reset == census
        # The older reset lives entirely past the page boundary — before #2063 it read short.
        assert by_reset["2026-07-13"] == VOIDS_PER_RESET

    def test_oldest_graded_rows_survive_into_the_career_pairs(self, monkeypatch):
        """The quiet half of the bug: the displaced rows were the oldest GRADED bets,
        so the lifetime Brier denominator shrank. They must be scored."""
        fake = PagingFake(LEDGER)
        monkeypatch.setattr(api, "table", fake)
        body = _body(api.handle_calibration({}))

        assert body["hypotheses"]["lifetime"]["n"] == GRADED_OLD
        assert body["platform"]["lifetime"]["n"] >= GRADED_OLD
        # They are pre-genesis, so they belong to career only — season stays honest.
        assert body["hypotheses"]["n"] == 0

    def test_single_page_read_would_have_lost_them(self, monkeypatch):
        """The fixture actually reproduces the bug — a non-paginated read of the same
        partition drops the oldest rows. Without this, the tests above could pass on
        a fixture that never truncated in the first place."""
        fake = PagingFake(LEDGER)
        monkeypatch.setattr(api, "table", fake)
        one_page = api._query_partition("USER#matthew#SOURCE#calibration", "CALIB#")
        full = api._query_partition("USER#matthew#SOURCE#calibration", "CALIB#", paginate=True)

        assert len(one_page) == PAGE_SIZE < len(full) == len(LEDGER)
        assert not any(r["record_type"] == "hypothesis_resolution" for r in one_page)
        assert sum(1 for r in full if r["record_type"] == "hypothesis_resolution") == GRADED_OLD


class TestPaginationIsScopedAndBounded:
    def test_coach_partitions_still_take_exactly_one_query_each(self, monkeypatch):
        """#1527's latency trade is preserved: only the CROSS_PHASE ledger — the one
        partition that never resets and only accretes — pays the extra round trip."""
        fake = PagingFake(LEDGER, coach_rows=[])
        monkeypatch.setattr(api, "table", fake)
        api.handle_calibration({})

        coach_pages = {pk: n for pk, n in fake.pages_by_pk.items() if pk.startswith("COACH#")}
        assert len(coach_pages) == 8
        assert set(coach_pages.values()) == {1}, coach_pages
        assert fake.pages_by_pk["USER#matthew#SOURCE#calibration"] == 2

    def test_prediction_fetch_does_not_paginate(self, monkeypatch):
        fake = FakeDdbTable(query_hook=lambda table, **kw: {"Items": [], "LastEvaluatedKey": {"_offset": 1}})
        monkeypatch.setattr(api, "table", fake)
        api._fetch_prediction_partition("COACH#sleep_coach")
        assert len(fake.query_calls) == 1

    def test_runaway_pagination_is_capped_and_logged_loud(self, monkeypatch, caplog):
        """A partition that never stops paging must be cut off, not loop to timeout —
        and the cut must be LOUD. Silent truncation is the failure #2063 ends."""
        never_ends = FakeDdbTable(query_hook=lambda table, **kw: {"Items": [{"sk": "CALIB#x"}], "LastEvaluatedKey": {"_offset": 1}})
        monkeypatch.setattr(api, "table", never_ends)
        with caplog.at_level("ERROR"):
            out = api._query_partition("USER#matthew#SOURCE#calibration", "CALIB#", paginate=True)

        assert len(never_ends.query_calls) == api._MAX_QUERY_PAGES
        assert len(out) == api._MAX_QUERY_PAGES
        assert "TRUNCATED" in caplog.text

    def test_every_page_repeats_the_same_query_shape(self, monkeypatch):
        """Only ExclusiveStartKey advances — page 2 cannot silently read a different
        key condition, projection, or sort direction than page 1."""
        fake = PagingFake(LEDGER)
        monkeypatch.setattr(api, "table", fake)
        api._query_partition("USER#matthew#SOURCE#calibration", "CALIB#", paginate=True)

        assert len(fake.query_calls) == 2
        first, second = fake.query_calls
        assert "ExclusiveStartKey" not in first
        assert second["ExclusiveStartKey"] == {"_offset": PAGE_SIZE}
        assert {k: v for k, v in second.items() if k != "ExclusiveStartKey"} == first
        assert first["ScanIndexForward"] is False and first["Limit"] == 1500
