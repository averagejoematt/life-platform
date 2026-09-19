"""tests/test_save_insight_phase_stamp_3513.py — the MCP save_insight writer stamps at the write site (#3513).

The third INSIGHT# writer. #3890 stamped `insight_writer` and the inbound email parser; the
row-side nightly audit then named three bare rows written by this tool on its first pass.
The property: every row this tool puts carries the class-gated stamp for its own Pacific day,
and the stamp cannot override what the item already carries.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "lambdas")):
    if p not in sys.path:
        sys.path.insert(0, p)
for k, v in (
    ("AWS_ACCESS_KEY_ID", "FAKE"),
    ("AWS_SECRET_ACCESS_KEY", "FAKE"),
    ("AWS_DEFAULT_REGION", "us-west-2"),
    ("S3_BUCKET", "test-bucket"),
    ("TABLE_NAME", "life-platform-test"),
    ("USER_ID", "matthew"),
):
    os.environ.setdefault(k, v)

from mcp import tools_lifestyle as tl  # noqa: E402


class _FakeTable:
    def __init__(self):
        self.items = []

    def put_item(self, Item):
        self.items.append(Item)


def _save(monkeypatch, text="Zone-2 after lifting kept HRV flat"):
    fake = _FakeTable()
    monkeypatch.setattr(tl, "table", fake)
    monkeypatch.setattr(tl._idem, "guard", lambda *a, **k: None)
    out = tl.tool_save_insight({"text": text, "tags": ["training"]})
    assert out["saved"] is True
    assert len(fake.items) == 1
    return fake.items[0]


def test_a_saved_insight_carries_the_write_time_phase_stamp(monkeypatch):
    item = _save(monkeypatch)
    assert item["pk"] == tl.INSIGHTS_PK
    assert item["sk"].startswith("INSIGHT#")
    assert "phase" in item, "the row-side audit would name this row the morning after it was written"
    assert item["phase"] in ("pilot", "experiment")


def test_the_stamp_never_overrides_what_the_item_carries(monkeypatch):
    item = _save(monkeypatch)
    # the fields the tool sets are intact after the merge — the stamp is spread FIRST
    assert item["status"] == "open"
    assert item["tags"] == ["training"]
    assert item["source"] == "chat"


def test_the_stamp_is_the_taxonomy_ruling_for_this_row(monkeypatch):
    from experiment.phase_taxonomy import experiment_stamp_for

    item = _save(monkeypatch)
    expected = experiment_stamp_for(tl.INSIGHTS_PK, item["sk"], as_of=item["date_saved"])
    for k, v in expected.items():
        assert item[k] == v
