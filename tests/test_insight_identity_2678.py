"""#2678 — every stored insight must carry a stable insight_id and a date_saved.

32 of 33 rows in the insights partition had both fields empty: three writers share
the partition, and `content/insight_writer.py` (the daily-brief/digest ledger writer)
stamped neither field, so its rows were unreferenceable by update_insight_outcome
and ageless to every staleness reader.

Two halves under test, matching the PR:
  1. Write path — insight_writer stamps both fields on every row, and insight_id is
     the sk minus its "INSIGHT#" prefix so the mcp reader's reconstruction
     (`sk = f"INSIGHT#{insight_id}"`) round-trips (fixture = the wire: we assert on
     the exact Item handed to put_item).
  2. Backfill — deploy/backfill_insight_identity.py classifies the existing archive
     (complete / backfill / unfixable), derives dates with the documented precedence,
     writes nothing in dry-run, and is idempotent under re-run.

Mutation proof: drop the insight_id/date_saved stamps from write_insight and the
write-path tests fail; make the backfill write in dry-run (or re-write complete rows)
and the backfill tests fail.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lambdas"))
sys.path.insert(0, str(_ROOT / "deploy"))

import backfill_insight_identity as backfill  # noqa: E402
from content import insight_writer  # noqa: E402

SK_PREFIX = "INSIGHT#"


# ──────────────────────────────────────────────────────────────────────────────
# Half 1 — the write path
# ──────────────────────────────────────────────────────────────────────────────


class PutCaptureTable:
    """Fixture = the wire: captures the exact Item dicts handed to put_item."""

    def __init__(self):
        self.items = []

    def put_item(self, Item):  # noqa: N803 — boto3 signature
        self.items.append(Item)


class TestWritePathStampsIdentity(unittest.TestCase):
    def setUp(self):
        self.table = PutCaptureTable()
        insight_writer.init(self.table, "matthew")

    def tearDown(self):
        insight_writer.init(None)

    def _assert_identity(self, item):
        """Acceptance: both fields non-empty, and the id round-trips to the sk."""
        self.assertTrue(str(item.get("insight_id", "")).strip(), f"empty insight_id on {item.get('sk')}")
        self.assertTrue(str(item.get("date_saved", "")).strip(), f"empty date_saved on {item.get('sk')}")
        # The mcp reader reconstructs sk = f"INSIGHT#{insight_id}" — the contract
        # that makes a row addressable by update_insight_outcome.
        self.assertEqual(SK_PREFIX + item["insight_id"], item["sk"])

    def test_slugged_write_carries_both_fields(self):
        item = insight_writer.write_insight(
            digest_type="daily_brief",
            insight_type="coaching",
            text="Sleep efficiency 71 percent — the wind-down routine was missed five of seven days.",
            date="2026-08-03",
            slug="bod",
        )
        self.assertIsNotNone(item)
        self._assert_identity(item)
        self.assertEqual(item["insight_id"], "2026-08-03#daily_brief#bod")
        self.assertEqual(item["date_saved"], "2026-08-03")
        # And the wire item — not just the return value — carries them.
        self._assert_identity(self.table.items[0])

    def test_legacy_slugless_write_carries_both_fields(self):
        with mock.patch.object(insight_writer, "_now_iso", return_value="2026-08-03T09:00:00.000Z"):
            item = insight_writer.write_insight(
                digest_type="weekly_digest",
                insight_type="observation",
                text="Weekly pattern: HRV dips every Sunday night before the Monday commute.",
                date="2026-08-03",
            )
        self.assertIsNotNone(item)
        self._assert_identity(item)
        self.assertEqual(item["insight_id"], "2026-08-03T09:00:00.000Z#weekly_digest")
        self.assertEqual(item["date_saved"], "2026-08-03")

    def test_every_daily_brief_insight_is_referenceable_and_aged(self):
        """The full 7-insight brief batch — the shape the 32 defective rows came from."""
        insights = insight_writer.extract_daily_brief_insights(
            bod_insight="Sleep efficiency 71 percent — the wind-down routine was missed five of seven days.",
            tldr_guidance={
                "tldr": "Recovery is trending up; protein is the gap today.",
                "guidance": ["Hit 180g protein — front-load lunch with 50g.", "Zone 2 for 40 minutes, keep HR under 135."],
            },
            training_nutrition={
                "training": "Pull day as planned; ACWR is in the green band so full volume.",
                "nutrition": "Yesterday landed 140g protein against the 180g target — close the gap early.",
            },
            journal_coach_text="The evening entry shows the same Sunday dread pattern — name it before it names you.",
            date="2026-08-03",
        )
        with mock.patch.object(insight_writer.time, "sleep"):
            written = insight_writer.write_insights_batch(insights)
        self.assertEqual(written, 7)
        self.assertEqual(len(self.table.items), 7)
        for item in self.table.items:
            self._assert_identity(item)


# ──────────────────────────────────────────────────────────────────────────────
# Half 2 — the backfill
# ──────────────────────────────────────────────────────────────────────────────


class QueryUpdateTable:
    """DDB double for the backfill wire: paginated query out, update_item in.

    update_item applies the (narrow) SET expression the script uses, so an
    apply-then-rerun sequence exercises real idempotency.
    """

    def __init__(self, rows):
        self.rows = {r["sk"]: dict(r) for r in rows}
        self.update_calls = []

    def query(self, **kwargs):
        assert "KeyConditionExpression" in kwargs, "backfill must query, not scan"
        return {"Items": [dict(r) for r in self.rows.values()]}

    def update_item(self, **kwargs):
        self.update_calls.append(kwargs)
        assert kwargs["UpdateExpression"] == "SET insight_id = :i, date_saved = :d", "backfill must touch ONLY the two identity fields"
        row = self.rows[kwargs["Key"]["sk"]]
        row["insight_id"] = kwargs["ExpressionAttributeValues"][":i"]
        row["date_saved"] = kwargs["ExpressionAttributeValues"][":d"]


PK = backfill.INSIGHTS_PK


def _corpus():
    return [
        # The one healthy row (mcp save_insight shape).
        {"pk": PK, "sk": "INSIGHT#2026-08-08T17:30:00", "insight_id": "2026-08-08T17:30:00", "date_saved": "2026-08-08", "text": "ok"},
        # insight_writer slugged row: id/date_saved absent, `date` present.
        {"pk": PK, "sk": "INSIGHT#2026-08-03#daily_brief#bod", "date": "2026-08-03", "created_at": "2026-08-03T17:40:51.000Z"},
        # insight_writer legacy row: empty-string fields, no `date`, created_at only.
        {
            "pk": PK,
            "sk": "INSIGHT#2026-07-11T09:00:00.000Z#weekly_digest",
            "insight_id": "",
            "date_saved": "",
            "created_at": "2026-07-11T09:00:00.000Z",
        },
        # No attributes at all — the date must come from the sk itself.
        {"pk": PK, "sk": "INSIGHT#2026-06-01T08:00:00#monthly_digest"},
        # Nothing derivable anywhere — reported, never written.
        {"pk": PK, "sk": "INSIGHT#mystery-row"},
    ]


class TestBackfillClassification(unittest.TestCase):
    def test_dry_run_classifies_and_writes_nothing(self):
        table = QueryUpdateTable(_corpus())
        report = backfill.run(table, apply=False)

        self.assertEqual(report["total"], 5)
        self.assertEqual(report["complete"], 1)
        self.assertEqual(len(report["backfill"]), 3)
        self.assertEqual([r["sk"] for r in report["unfixable"]], ["INSIGHT#mystery-row"])
        self.assertEqual(report["written"], 0)
        self.assertEqual(table.update_calls, [], "dry-run must not write")

    def test_date_precedence_date_attr_then_created_at_then_sk(self):
        table = QueryUpdateTable(_corpus())
        fixes = {f["sk"]: f for f in backfill.run(table, apply=False)["backfill"]}

        slugged = fixes["INSIGHT#2026-08-03#daily_brief#bod"]
        self.assertEqual((slugged["date_saved"], slugged["date_source"]), ("2026-08-03", "date"))
        legacy = fixes["INSIGHT#2026-07-11T09:00:00.000Z#weekly_digest"]
        self.assertEqual((legacy["date_saved"], legacy["date_source"]), ("2026-07-11", "created_at"))
        bare = fixes["INSIGHT#2026-06-01T08:00:00#monthly_digest"]
        self.assertEqual((bare["date_saved"], bare["date_source"]), ("2026-06-01", "sk"))

    def test_backfilled_id_is_the_sk_minus_prefix(self):
        """The id must satisfy the reader contract sk == INSIGHT#{insight_id}."""
        table = QueryUpdateTable(_corpus())
        for fix in backfill.run(table, apply=False)["backfill"]:
            self.assertEqual(SK_PREFIX + fix["insight_id"], fix["sk"])

    def test_apply_writes_then_rerun_is_a_no_op(self):
        table = QueryUpdateTable(_corpus())
        first = backfill.run(table, apply=True)
        self.assertEqual(first["written"], 3)
        self.assertEqual(len(table.update_calls), 3)

        second = backfill.run(table, apply=True)
        self.assertEqual(second["complete"], 4, "backfilled rows must classify complete on re-run")
        self.assertEqual(second["backfill"], [])
        self.assertEqual(second["written"], 0)
        self.assertEqual(len(table.update_calls), 3, "idempotent: a re-run performs zero writes")
        # The unfixable row is still reported — visible every run until tombstoned.
        self.assertEqual([r["sk"] for r in second["unfixable"]], ["INSIGHT#mystery-row"])

    def test_a_row_with_a_garbage_date_saved_is_repaired_not_trusted(self):
        """ADR-104: 'not-a-date' must not survive as an age; re-derive from created_at."""
        row = {"pk": PK, "sk": "INSIGHT#x", "insight_id": "x", "date_saved": "not-a-date", "created_at": "2026-05-05T01:02:03Z"}
        action, insight_id, date_saved, source = backfill.classify_row(row)
        self.assertEqual(action, "backfill")
        self.assertEqual(insight_id, "x")  # an existing non-empty id is kept
        self.assertEqual((date_saved, source), ("2026-05-05", "created_at"))


if __name__ == "__main__":
    unittest.main()
