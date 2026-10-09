"""tests/test_notion_coowned_carry_4677.py — #4677.

The Notion journal writer rebuilds a row with a full-item put. Until #4677 it carried only
two hand-listed attribute families across that rebuild, so the deterministic vocal metrics
a third writer (``scripts/backfill_vocal_metrics.py``) had put on the same row were erased
the next time the page was edited in Notion and re-ingested. Nothing recomputes them.

The carried set now comes from ONE declaration — ``ingestion/journal_row_contract.py`` —
and these tests hold all three write paths to it: the same-key rewrite, the legacy-key →
stable-key move, and the single-entry-per-day rewrite.

Every row here is synthetic; no test reads or prints journal content.
"""

import os

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")

from decimal import Decimal  # noqa: E402

import ingestion.notion_lambda as nl  # noqa: E402
import pytest  # noqa: E402

DAY = "2026-09-20"
PAGE = "00000000-0000-4000-8000-0000000000aa"

# The seven attributes scripts/backfill_vocal_metrics.py writes (docs/SCHEMA.md, "Vocal
# metrics fields"). Spelled out here ON PURPOSE rather than derived from the contract: this
# is the behaviour the issue names, and a test that read the list from the code under test
# would agree with it by construction.
VOCAL = {
    "vocal_wpm": Decimal("141.2"),
    "vocal_mean_pause_s": Decimal("0.84"),
    "vocal_pauses_per_min": Decimal("6.1"),
    "vocal_fillers_per_min": Decimal("2.3"),
    "vocal_duration_s": Decimal("312.5"),
    "vocal_word_count": Decimal("735"),
    "vocal_metrics_computed_at": "2026-09-21T03:00:00+00:00",
}
ENRICHED = {"enriched_mood": Decimal("4"), "enriched_at": "2026-09-21T14:30:00+00:00", "defense_patterns": ["synthetic"]}


class FakeTable:
    """The slice of the DynamoDB Table API the ingester uses, over a dict keyed by sk."""

    def __init__(self, rows=()):
        self.rows = {r["sk"]: dict(r) for r in rows}

    def query(self, **kw):
        prefix = kw["KeyConditionExpression"]._values[1]._values[1]
        items = [dict(r) for sk, r in sorted(self.rows.items()) if sk.startswith(prefix)]
        wanted = [f.strip() for f in kw.get("ProjectionExpression", "").split(",") if f.strip()]
        if wanted:
            items = [{k: v for k, v in it.items() if k in wanted} for it in items]
        return {"Items": items}

    def get_item(self, Key, **kw):
        row = self.rows.get(Key["sk"])
        return {"Item": dict(row)} if row else {}

    def put_item(self, Item):
        self.rows[Item["sk"]] = dict(Item)

    def delete_item(self, Key):
        self.rows.pop(Key["sk"], None)


def _fresh(template_sk, page_id=PAGE, **extra):
    """An item as parse_page hands it to write_entries: vendor fields only."""
    item = {
        "date": DAY,
        "source": "notion",
        "template": template_sk,
        "notion_page_id": page_id,
        "notion_last_edited": "2026-10-04T08:00:00.000Z",
        "raw_text": "synthetic fixture body, edited",
    }
    item.update(extra)
    return item


def _stored(sk, page_id=PAGE, **extra):
    row = {
        "pk": nl.PK,
        "sk": sk,
        "date": DAY,
        "source": "notion",
        "notion_page_id": page_id,
        "notion_last_edited": "2026-09-20T18:00:00.000Z",
        "raw_text": "synthetic fixture body",
    }
    row.update(extra)
    return row


@pytest.fixture
def table(monkeypatch):
    fake = FakeTable()
    monkeypatch.setattr(nl, "table", fake)
    return fake


def _missing(row, expected):
    return sorted(k for k, v in expected.items() if row.get(k) != v)


def test_same_key_reingest_of_an_edited_recording_keeps_every_vocal_attribute(table):
    """The issue's reproduction: an edited page re-ingested under the SAME key, on both
    recording channels. One test that reports every offender."""
    lost = {}
    for template in ("Video Diary", "Solo Recording"):
        sk = nl.build_sk(DAY, template, PAGE)
        table.rows[sk] = _stored(sk, **VOCAL, **ENRICHED)

        assert nl.write_entries({DAY: [(template, _fresh(nl.TEMPLATE_SK[template]))]}) == 1

        row = table.rows[sk]
        assert row["raw_text"] == "synthetic fixture body, edited", "the rewrite itself did not land"
        missing = _missing(row, VOCAL) + _missing(row, ENRICHED)
        if missing:
            lost[template] = missing
    assert not lost, f"a same-key re-ingest erased attributes another pipeline wrote: {lost}"


def test_a_page_moving_to_its_stable_key_takes_its_vocal_attributes_with_it(table):
    """The re-key path: the stored row sits under a legacy positional key."""
    legacy = f"DATE#{DAY}#journal#video_diary#1"
    stable = nl.build_sk(DAY, "Video Diary", PAGE)
    table.rows[legacy] = _stored(legacy, **VOCAL, **ENRICHED)

    nl.write_entries({DAY: [("Video Diary", _fresh("video_diary"))]})

    assert legacy not in table.rows, "the legacy row should be removed once its attributes are carried"
    assert _missing(table.rows[stable], VOCAL) == []
    assert _missing(table.rows[stable], ENRICHED) == []


def test_single_entry_per_day_rewrite_keeps_coowned_attributes(table):
    """The other write path in the same file — Morning / Evening / Weekly, one row a day."""
    sk = nl.build_sk(DAY, "Morning")
    table.rows[sk] = _stored(sk, **VOCAL, **ENRICHED)

    assert nl.write_entries({DAY: [("Morning", _fresh("morning"))]}) == 1

    assert _missing(table.rows[sk], VOCAL) == []
    assert _missing(table.rows[sk], ENRICHED) == []


def test_a_freshly_fetched_vendor_field_is_never_overridden_by_a_stored_value(table):
    """Carrying is preservation, not merging: a key the fresh item already holds keeps the
    value Notion just sent, even under a carried family and even when the stored one differs."""
    sk = nl.build_sk(DAY, "Video Diary", PAGE)
    table.rows[sk] = _stored(sk, vocal_wpm=Decimal("141.2"), mood=Decimal("2"), extra_vendor_field="stale")

    nl.write_entries({DAY: [("Video Diary", _fresh("video_diary", vocal_wpm=Decimal("99"), mood=Decimal("5")))]})

    row = table.rows[sk]
    assert row["vocal_wpm"] == Decimal("99")
    assert row["mood"] == Decimal("5")
    assert "extra_vendor_field" not in row, "an undeclared stored attribute was carried — the carry must stay inside the declared families"


def test_a_row_that_cannot_be_read_is_not_rewritten(table):
    """A put after a failed read IS the erasure. The row keeps what it holds; the edit lands
    on a later run, when the stored row can be read and carried from. Both write paths."""

    def unreadable(Key, **kw):
        raise RuntimeError("synthetic read failure")

    table.get_item = unreadable
    rewritten = []
    for template in ("Video Diary", "Morning"):
        sk = nl.build_sk(DAY, template, PAGE)
        table.rows[sk] = _stored(sk, **VOCAL)

        written = nl.write_entries({DAY: [(template, _fresh(nl.TEMPLATE_SK[template]))]})

        if written or table.rows[sk]["raw_text"] != "synthetic fixture body" or _missing(table.rows[sk], VOCAL):
            rewritten.append(template)
    assert not rewritten, f"a row whose stored copy could not be read was rewritten anyway: {rewritten}"
