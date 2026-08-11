"""test_recall_journal_field_2569.py — the recall backfill reads the attribute the WRITER wrote.

#2569: `gather_journal` read `content` / `body` / `text`. No live journal row has ever
carried any of those three — `ingestion.notion_lambda.parse_page` writes `raw_text`
(always) and `body_text` (when the page body fetched). Every entry therefore failed the
`if not date or not text: continue` guard and semantic recall indexed **zero** journal
entries. Measured against live DynamoDB on 2026-08-11: 60 `#journal#` rows, all 60 with
`raw_text`, 53 with `body_text`, none with `content`/`body`/`text`; recall corpus 19
rows, 100% `kind=chronicle`.

`gather_coach_outputs` had the identical defect and a bigger blast radius: it read
`output_text`/`text` while `coach.coach_state_updater._write_output_record` writes
`content`. 851 live `OUTPUT#` rows, all carrying `content`, none carrying either guessed
name — zero coach docs in the corpus, consistent with the measurement above.

WHY IT SURVIVED, AND WHAT THESE TESTS DO DIFFERENTLY. A fixture written as
`{"content": "..."}` passes against the broken reader — the test and the bug shared the
same wrong guess. So nothing here hand-lists a field name at the read site:

  * the PARITY tests run a record through the real writer (`parse_page`,
    `_write_output_record`) and assert the gatherer extracts that writer's text. Rename a
    writer's attribute and these go red instead of a corpus silently emptying.
  * the LIVE-SHAPE test uses the verbatim attribute set of a real row (issue #2569).
  * the MUTATION test reverts `JOURNAL_TEXT_FIELDS` to the pre-fix guess and asserts the
    corpus comes back EMPTY — the failure mode reproduced on demand.

Hermetic — no AWS, no Bedrock, no network.

Run with:   python3 -m pytest tests/test_recall_journal_field_2569.py -v
"""

import importlib.util
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("S3_BUCKET", "")  # #476/X-7 archive is a no-op with no bucket
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from ai import semantic_recall as sr  # noqa: E402
from common import record_text  # noqa: E402
from ingestion import notion_lambda  # noqa: E402


def _load_backfill():
    """Import the deploy script by path (it is not an importable package)."""
    path = os.path.join(_REPO, "deploy", "backfill_recall_embeddings.py")
    spec = importlib.util.spec_from_file_location("backfill_recall_embeddings", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bf = _load_backfill()


class FakeTable:
    """Minimal `table.query(...)` stand-in — one page, no LastEvaluatedKey."""

    def __init__(self, items):
        self.items = items

    def query(self, **kwargs):
        return {"Items": list(self.items)}


# ── the live row shape (issue #2569, verbatim attribute set) ─────────────────
# A real 2023 entry: `raw_text` only, no `body_text` (pre-body-fetch), and none of
# `content` / `body` / `text`.
LIVE_JOURNAL_ROW = {
    "pk": "USER#matthew#SOURCE#notion",
    "sk": "DATE#2023-12-19#journal#journal#1",
    "created_at": "2023-12-19T08:02:00.000Z",
    "date": "2023-12-19",
    "defense_enriched_at": "2026-07-01T00:00:00+00:00",
    "enriched_alcohol": 0,
    "enriched_at": "2026-07-01T00:00:00+00:00",
    "enriched_emotional_depth": 3,
    "enriched_flow": 2,
    "enriched_sentiment": "neutral",
    "name": "Dec 19, 2023",
    "notion_last_edited": "2023-12-19T09:00:00.000Z",
    "notion_page_id": "abcdef01-2345-6789-abcd-ef0123456789",
    "phase": "pre_experiment",
    "raw_text": "[journal]\n\nSlept badly, ran anyway. Legs heavy the whole way.",
    "schema_version": "1.2.0",
    "source": "notion",
    "template": "journal",
    "updated_at": "2026-07-01T00:00:00+00:00",
}


def test_live_shaped_journal_row_produces_a_doc():
    """The real attribute set — not a `content`-bearing fixture — yields one corpus doc."""
    docs = bf.gather_journal(FakeTable([LIVE_JOURNAL_ROW]))
    assert len(docs) == 1, "a live-shaped journal row must produce exactly one doc"
    doc = docs[0]
    assert doc["kind"] == sr.KIND_JOURNAL
    assert doc["doc_date"] == "2023-12-19"
    assert doc["date"] == "2023-12-19#journal#journal#1"
    assert doc["artifact_sk"] == LIVE_JOURNAL_ROW["sk"]
    assert "ran anyway" in doc["text"], "the embedded text must be the row's own body"


def test_pre_fix_field_guess_indexes_nothing(monkeypatch):
    """MUTATION PROOF: revert to the pre-fix field names → the corpus comes back empty.

    This is the exact live behaviour #2569 measured. It is asserted here so the fix
    cannot be undone (or re-guessed at some other read site) without a red test.
    """
    monkeypatch.setattr(record_text, "JOURNAL_TEXT_FIELDS", ("content", "body", "text"))
    assert bf.gather_journal(FakeTable([LIVE_JOURNAL_ROW])) == []


def test_journal_writer_and_reader_agree():
    """PARITY: an item built by the real notion writer is readable by the real gatherer.

    `parse_page(page)` with no api_key is the body-fetch-less path — the shape of the
    older live rows. Nothing below names an attribute; the writer chooses them and the
    reader must find them.
    """
    page = {
        "id": "11112222-3333-4444-5555-666677778888",
        "created_time": "2026-08-05T15:30:00.000Z",
        "last_edited_time": "2026-08-05T16:00:00.000Z",
        "properties": {
            "Date": {"type": "date", "date": {"start": "2026-08-05"}},
            "Template": {"type": "select", "select": {"name": "Morning"}},
            "Energy": {"type": "number", "number": 7},
        },
    }
    parsed = notion_lambda.parse_page(page)
    assert parsed is not None, "fixture must parse — otherwise this test proves nothing"
    date_str, template, item = parsed
    item["pk"] = "USER#matthew#SOURCE#notion"
    item["sk"] = notion_lambda.build_sk(date_str, template, page["id"])
    assert "#journal#" in item["sk"]
    # The writer must not have produced any of the three names the broken reader guessed.
    assert not ({"content", "body", "text"} & set(item)), "writer produced a field the pre-fix reader guessed — re-read the issue"

    docs = bf.gather_journal(FakeTable([item]))
    assert len(docs) == 1, "the gatherer must read the attribute the writer just wrote"
    assert docs[0]["text"] == record_text.journal_text(item)
    assert docs[0]["doc_date"] == "2026-08-05"


def test_journal_body_text_wins_over_raw_text():
    """The writer's own precedence (`_archive_page_raw` archives body_text or raw_text):
    the human's free writing beats the template-label + property dump wrapper."""
    row = dict(LIVE_JOURNAL_ROW)
    row["body_text"] = "The free-writing body."
    assert bf.gather_journal(FakeTable([row]))[0]["text"] == "The free-writing body."


# ── the coach half of the same defect ───────────────────────────────────────


def _coach_output_item(output_text):
    """Build an OUTPUT# item through the REAL writer, capturing the put."""
    from coach import coach_state_updater as csu

    captured = {}

    def _capture(item):
        captured["item"] = item
        return True

    orig = csu._put_item
    csu._put_item = _capture
    try:
        csu._write_output_record("sleep_coach", "2026-08-05", "daily", output_text, {})
    finally:
        csu._put_item = orig
    return captured["item"]


def test_coach_writer_and_reader_agree():
    """PARITY, coach half: `gather_coach_outputs` reads what `_write_output_record` wrote.

    Pre-fix it read `output_text`/`text`; the writer has always written `content`, so all
    851 live OUTPUT# rows were skipped as empty.
    """
    text = "You slept 6h12m across the last three nights. That is the pattern, not the exception."
    item = _coach_output_item(text)
    assert not ({"output_text", "text"} & set(item)), "writer produced a field the pre-fix reader guessed"

    docs = bf.gather_coach_outputs(FakeTable([item]), ["sleep_coach"])
    assert len(docs) == 1, "the gatherer must read the attribute the writer just wrote"
    assert docs[0]["kind"] == sr.KIND_COACH
    assert docs[0]["text"] == text
    assert docs[0]["doc_date"] == "2026-08-05"


def test_pre_fix_coach_field_guess_indexes_nothing(monkeypatch):
    """MUTATION PROOF, coach half."""
    item = _coach_output_item("Some coach narrative that is long enough to matter.")
    monkeypatch.setattr(record_text, "COACH_OUTPUT_TEXT_FIELDS", ("output_text", "text"))
    assert bf.gather_coach_outputs(FakeTable([item]), ["sleep_coach"]) == []


def test_first_text_ignores_non_string_values():
    """A malformed attribute is ABSENT, not str()-coerced into "[]" as if it were prose."""
    assert record_text.first_text({"a": [], "b": 3, "c": "  real  "}, ("a", "b", "c")) == "real"
    assert record_text.first_text({"a": "   "}, ("a",)) == ""
