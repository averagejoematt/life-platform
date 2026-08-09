"""#2368 — restart-day daily brief INSIGHT# writes must be idempotent.

The 2026-08-03 reset re-invoked the brief three times within a minute; each run
wrote the same 7 insights under a fresh wall-clock sk (INSIGHT#<ISO-ts>#daily_brief),
so readers saw 21 rows for one day. The fix keys daily-brief insight rows by
(date, digest_type, slug) — a same-day re-invocation overwrites the same keys.

Mutation proof: revert the slug-derived sk in write_insight (or drop the slugs in
extract_daily_brief_insights) and test_two_same_day_runs_write_identical_key_set
fails — the second run's keys diverge and the row count doubles.
"""

import importlib
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lambdas"))

insight_writer = importlib.import_module("content.insight_writer")


class FakeTable:
    """Minimal DynamoDB table double: a dict keyed by (pk, sk)."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict] = {}
        self.put_count = 0

    def put_item(self, Item: dict) -> None:  # noqa: N803 — boto3 signature
        self.put_count += 1
        self.rows[(Item["pk"], Item["sk"])] = Item


def _brief_fixture_kwargs() -> dict:
    """A fixed daily-brief AI output set: 7 insights (bod, tldr, 2 guidance, training, nutrition, journal)."""
    return {
        "bod_insight": "Sleep efficiency 71 percent — the wind-down routine was missed five of seven days.",
        "tldr_guidance": {
            "tldr": "Recovery is trending up; protein is the gap today.",
            "guidance": [
                "Hit 180g protein — front-load lunch with 50g.",
                "Zone 2 for 40 minutes, keep HR under 135.",
            ],
        },
        "training_nutrition": {
            "training": "Pull day as planned; ACWR is in the green band so full volume.",
            "nutrition": "Yesterday landed 140g protein against the 180g target — close the gap early.",
        },
        "journal_coach_text": "The evening entry shows the same Sunday dread pattern — name it before it names you.",
        "date": "2026-08-03",
        "component_scores": {"sleep": 71, "movement": 80},
    }


def _run_brief_write(table: FakeTable) -> tuple[int, int]:
    """One brief-Lambda insight pass. Returns (puts this run, insights extracted)."""
    insight_writer.init(table, "matthew")
    insights = insight_writer.extract_daily_brief_insights(**_brief_fixture_kwargs())
    before = table.put_count
    with mock.patch.object(insight_writer.time, "sleep"):  # skip the hot-partition delay
        written = insight_writer.write_insights_batch(insights)
    assert written == len(insights)
    return table.put_count - before, len(insights)


class TestDailyBriefInsightIdempotency(unittest.TestCase):
    def tearDown(self) -> None:
        insight_writer.init(None)  # reset module state for other tests

    def test_two_same_day_runs_write_identical_key_set(self) -> None:
        """Acceptance: two same-day brief runs write an identical key set — no duplicates."""
        table = FakeTable()

        # First invocation (17:40:51) and a restart-verification re-invocation
        # (17:41:23) — distinct wall clocks, as on 2026-08-03.
        with mock.patch.object(insight_writer, "_now_iso", return_value="2026-08-03T17:40:51.000Z"):
            puts_1, extracted = _run_brief_write(table)
        keys_after_first = set(table.rows)

        with mock.patch.object(insight_writer, "_now_iso", return_value="2026-08-03T17:41:23.000Z"):
            puts_2, _ = _run_brief_write(table)
        keys_after_second = set(table.rows)

        self.assertEqual(extracted, 7, "fixture should extract the full 7-insight brief set")
        # Put count == distinct key count, per invocation and across both.
        self.assertEqual(puts_1, len(keys_after_first))
        self.assertEqual(puts_2, len(keys_after_first))
        self.assertEqual(
            keys_after_second,
            keys_after_first,
            "a same-day re-invocation must overwrite the same keys, not mint new rows",
        )
        self.assertEqual(len(table.rows), 7, "readers of get_insights must see each insight once")

    def test_sk_is_derived_from_date_and_identity_not_wall_clock(self) -> None:
        """The stable key is (date, digest_type, slug); the timestamp lives in created_at only."""
        table = FakeTable()
        with mock.patch.object(insight_writer, "_now_iso", return_value="2026-08-03T17:40:51.000Z"):
            _run_brief_write(table)

        expected_sks = {
            "INSIGHT#2026-08-03#daily_brief#bod",
            "INSIGHT#2026-08-03#daily_brief#tldr",
            "INSIGHT#2026-08-03#daily_brief#guidance-0",
            "INSIGHT#2026-08-03#daily_brief#guidance-1",
            "INSIGHT#2026-08-03#daily_brief#training",
            "INSIGHT#2026-08-03#daily_brief#nutrition",
            "INSIGHT#2026-08-03#daily_brief#journal",
        }
        self.assertEqual({sk for _, sk in table.rows}, expected_sks)
        for row in table.rows.values():
            self.assertNotIn("17:40:51", row["sk"], "sk must not embed the invocation wall clock")
            self.assertEqual(row["created_at"], "2026-08-03T17:40:51.000Z")

    def test_slugless_writers_keep_the_legacy_timestamp_key(self) -> None:
        """Other digest Lambdas that pass no slug are unchanged (one row per invocation)."""
        table = FakeTable()
        insight_writer.init(table, "matthew")
        try:
            with mock.patch.object(insight_writer, "_now_iso", return_value="2026-08-03T09:00:00.000Z"):
                item = insight_writer.write_insight(
                    digest_type="weekly_digest",
                    insight_type="observation",
                    text="Weekly pattern: HRV dips every Sunday night before the Monday commute.",
                    date="2026-08-03",
                )
            assert item is not None
            self.assertEqual(item["sk"], "INSIGHT#2026-08-03T09:00:00.000Z#weekly_digest")
        finally:
            insight_writer.init(None)


if __name__ == "__main__":
    unittest.main()
