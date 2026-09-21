"""tests/test_pain_burst_census_3972.py — box 1 of #3972: the read-only census mode
(`deploy/backfill_training_notes.py --pain-burst-census`) that lists the coach_thread
`#pain` rows one backfill sweep wrote in a time window, with source note text and a
lexicon-hit explanation, so a human can post keep/dismiss counts on the issue.

Fake table supports ONLY `query` — no `put_item`/`delete_item` at all, so any write
attempt errors loudly rather than silently landing (the acceptance is "a read + a LIST,
never a write").
"""

import importlib.util
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))


def _matches(cond, item) -> bool:
    """Evaluate a real boto3 Key condition against a stored item (mirrors the pattern in
    tests/test_training_notes_occurrence_key_3918.py — evaluate the READER's own
    condition object, never a re-stated predicate)."""
    if cond is None:
        return True
    e = cond.get_expression()
    op, values = e["operator"], e["values"]
    if op in ("AND", "OR"):
        results = [_matches(v, item) for v in values]
        return all(results) if op == "AND" else any(results)
    attr = getattr(values[0], "name", None)
    got = item.get(attr, "")
    if op == "=":
        return got == values[1]
    if op == "BETWEEN":
        return values[1] <= got <= values[2]
    raise NotImplementedError(f"the fake does not implement {op!r}")


class _QueryOnlyTable:
    """No put_item/delete_item at all — any write attempt is an AttributeError."""

    def __init__(self, items):
        self.items = list(items)

    def query(self, KeyConditionExpression=None, ExclusiveStartKey=None, **_kw):  # noqa: N803
        rows = [it for it in self.items if _matches(KeyConditionExpression, it)]
        return {"Items": rows}


def _backfill_module():
    spec = importlib.util.spec_from_file_location("_bf3972", os.path.join(str(REPO), "deploy", "backfill_training_notes.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GRIP_TEXT = (
    'Training pain/discomfort note on Zercher Squat: "Also thick bar or heavy dB holds, plate pinch gripping, '
    'captains of crush gripper, rice digs". Surface at the next pre-flight; confirm or dismiss before loading that movement.'
)
PAIN_TEXT = (
    'Training pain/discomfort note on Deadlift: "sharp pain in the left knee". '
    "Surface at the next pre-flight; confirm or dismiss before loading that movement."
)

ROWS = [
    {
        "pk": "USER#matthew",
        "sk": "SOURCE#coach_thread#training_coach#2026-09-19T21:08:51Z#pain",
        "kind": "pain_flag",
        "text": GRIP_TEXT,
        "exercise": "Zercher Squat",
        "date": "2022-03-30",
        "created_at": "2026-09-19T21:08:51Z",
    },
    {
        "pk": "USER#matthew",
        "sk": "SOURCE#coach_thread#training_coach#2026-09-19T21:08:55Z#pain",
        "kind": "pain_flag",
        "text": PAIN_TEXT,
        "exercise": "Deadlift",
        "date": "2022-03-30",
        "created_at": "2026-09-19T21:08:55Z",
    },
    # Outside the window under test — must be excluded.
    {
        "pk": "USER#matthew",
        "sk": "SOURCE#coach_thread#training_coach#2026-09-19T20:00:00Z#pain",
        "kind": "pain_flag",
        "text": PAIN_TEXT,
        "exercise": "Deadlift",
        "date": "2022-03-30",
        "created_at": "2026-09-19T20:00:00Z",
    },
    # Same window, not a pain row — must be excluded.
    {
        "pk": "USER#matthew",
        "sk": "SOURCE#coach_thread#training_coach#2026-09-19T21:09:00Z#other",
        "kind": "something_else",
        "text": "n/a",
        "exercise": "Deadlift",
        "date": "2026-09-19",
        "created_at": "2026-09-19T21:09:00Z",
    },
]


def test_census_lists_only_pain_rows_in_the_window():
    bf = _backfill_module()
    table = _QueryOnlyTable(ROWS)
    rows = bf.pain_burst_census(table, "2026-09-19T21:00Z", "2026-09-19T21:10Z")
    assert [r["sk"] for r in rows] == [
        "SOURCE#coach_thread#training_coach#2026-09-19T21:08:51Z#pain",
        "SOURCE#coach_thread#training_coach#2026-09-19T21:08:55Z#pain",
    ]


def test_census_recovers_the_verbatim_note_and_explains_the_verdict():
    bf = _backfill_module()
    table = _QueryOnlyTable(ROWS)
    rows = bf.pain_burst_census(table, "2026-09-19T21:00Z", "2026-09-19T21:10Z")
    grip, pain = rows[0], rows[1]
    assert grip["note_text"] == "Also thick bar or heavy dB holds, plate pinch gripping, captains of crush gripper, rice digs"
    assert grip["pain_lexicon_hit_pre_3972"] is True  # "pinch" alone fired before the fix
    assert grip["pain_lexicon_hit_post_3972"] is False  # the #3972 grip-work control clears it
    assert grip["disposition"].startswith("dismiss")

    assert pain["note_text"] == "sharp pain in the left knee"
    assert pain["pain_lexicon_hit_pre_3972"] is True
    assert pain["pain_lexicon_hit_post_3972"] is True
    assert pain["disposition"].startswith("keep")


def test_census_never_writes(monkeypatch):
    bf = _backfill_module()
    table = _QueryOnlyTable(ROWS)
    # The fake has no put_item/delete_item at all; any attempted write is an AttributeError.
    bf.pain_burst_census(table, "2026-09-19T21:00Z", "2026-09-19T21:10Z")
    assert not hasattr(table, "puts")
    assert not hasattr(table, "deleted")
