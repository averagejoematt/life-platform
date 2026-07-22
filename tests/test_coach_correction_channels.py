"""test_coach_correction_channels.py — the two #1690 feedback channels (epic #1687 S3):
the MCP tool `log_coach_correction` and the email-reply parser. BOTH must land the SAME
class-tagged rows in the corrections ledger (#1689), resolving a pack #N via the shared
coach_correction_resolver, and REPORT (never drop) a malformed/unknown number (AC3).

Fully offline: the week's numbering is injected (no S3), DDB is a FakeDdbTable, and the
confirmation email is stubbed (no SES). Exercises the REAL coach_corrections.write_correction
so the persisted item_ref shape is pinned.
"""

import os
import sys

os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

import pytest  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402


def _entry(surface, variant, date, key):
    return {
        "surface": surface,
        "variant": variant,
        "date": date,
        "archived_at": f"{date}T12:00:00+00:00",
        "_key": key,
        "text": "archived text",
        "meta": {},
    }


_NUMBERED = [
    (1, _entry("chronicle", None, "2026-07-20", "generated/qa_archive/text/2026-07-20/chronicle--120000--aaaa1111.json")),
    (
        2,
        _entry(
            "coach_brief",
            "sleep_coach",
            "2026-07-20",
            "generated/qa_archive/text/2026-07-20/coach_brief--sleep_coach--120100--bbbb2222.json",
        ),
    ),
]


# ════════════════════════════════════════════════════════════════════════════
# Channel 1 — the MCP tool log_coach_correction
# ════════════════════════════════════════════════════════════════════════════
@pytest.fixture
def mcp_tool(monkeypatch):
    import mcp.tools_coach_corrections as tcc

    table = FakeDdbTable()
    monkeypatch.setattr(tcc, "_table_ref", table)
    # inject the week's numbering — resolve_number(raw_n) calls numbered_for_week()
    monkeypatch.setattr(tcc.ccr, "numbered_for_week", lambda **kw: list(_NUMBERED))
    return tcc, table


def test_mcp_tool_is_registered():
    """AC1 / wiring-coverage: the tool is wired into the registry. Scanned from source
    text (not imported) to stay robust to cross-test sys.path contamination — the live
    import + signature/orphan wiring is enforced by test_mcp_registry.py,
    test_mcp_orphan_tools.py, and test_mcp_tool_signature_convention.py."""
    registry_src = open(os.path.join(_REPO, "mcp", "registry.py"), encoding="utf-8").read()
    assert '"log_coach_correction": {' in registry_src
    assert '"fn": tool_log_coach_correction,' in registry_src
    assert "from mcp.tools_coach_corrections import tool_log_coach_correction" in registry_src


def test_mcp_tool_happy_path_writes_ledger_row(mcp_tool):
    tcc, table = mcp_tool
    res = tcc.tool_log_coach_correction({"item_number": 2, "correction": "the 315 lbs baseline is stale — 321.4 as of genesis"})
    assert res["status"] == "logged"
    assert res["item"] == {"number": 2, "surface": "coach_brief", "coach": "sleep_coach", "date": "2026-07-20"}
    assert res["error_class"] == "other"  # no override supplied
    # exactly one ledger row written, with the resolved item_ref
    assert len(table.puts) == 1
    item = table.puts[0]
    assert item["pk"] == "USER#matthew#SOURCE#coach_corrections"
    assert item["sk"].startswith("CORRECTION#")
    assert item["correction_text"].startswith("the 315 lbs baseline")
    assert item["item_ref"]["pack_number"] == 2
    assert item["item_ref"]["coach"] == "sleep_coach"
    assert item["item_ref"]["archive_key"].endswith("bbbb2222.json")
    assert res["correction_id"] == item["sk"]


def test_mcp_tool_class_override_valid(mcp_tool):
    tcc, table = mcp_tool
    res = tcc.tool_log_coach_correction({"item_number": 1, "correction": "wrong", "error_class": "stale-baseline"})
    assert res["error_class"] == "stale-baseline"
    assert "error_class_note" not in res
    assert table.puts[0]["error_class"] == "stale-baseline"


def test_mcp_tool_unknown_class_normalized_to_other(mcp_tool):
    tcc, table = mcp_tool
    res = tcc.tool_log_coach_correction({"item_number": 1, "correction": "wrong", "error_class": "totally-made-up"})
    assert res["error_class"] == "other"
    assert "error_class_note" in res  # reported, not rejected
    assert table.puts[0]["error_class"] == "other"
    assert table.puts[0]["error_class_raw"] == "totally-made-up"  # #1689 preserves the raw label


def test_mcp_tool_unknown_number_reported_not_written(mcp_tool):
    tcc, table = mcp_tool
    res = tcc.tool_log_coach_correction({"item_number": 9, "correction": "no such item"})
    assert "error" in res
    assert "no item #9" in res["error"]
    assert res["total_items"] == 2
    assert table.puts == []  # nothing written


def test_mcp_tool_requires_text_and_number(mcp_tool):
    tcc, table = mcp_tool
    assert "error" in tcc.tool_log_coach_correction({"item_number": 1})
    assert "error" in tcc.tool_log_coach_correction({"correction": "text but no number"})
    assert table.puts == []


# ════════════════════════════════════════════════════════════════════════════
# Channel 2 — the email-reply parser
# ════════════════════════════════════════════════════════════════════════════
@pytest.fixture
def email_parser(monkeypatch):
    import insight_email_parser_lambda as iep

    table = FakeDdbTable()
    monkeypatch.setattr(iep, "table", table)
    monkeypatch.setattr(iep.ccr, "numbered_for_week", lambda **kw: list(_NUMBERED))
    sent = {}
    monkeypatch.setattr(
        iep,
        "_send_correction_confirmation",
        lambda applied, unresolved, recipient, subject="": sent.update(
            {"applied": applied, "unresolved": unresolved, "recipient": recipient}
        ),
    )
    return iep, table, sent


def test_is_review_pack_reply():
    import insight_email_parser_lambda as iep

    assert iep._is_review_pack_reply("Re: 🗂️ Weekly AI Review Pack · Jul 14–Jul 20 · 12 generation(s)")
    assert not iep._is_review_pack_reply("Re: Daily Brief")
    assert not iep._is_review_pack_reply("")


def test_email_multi_line_lands_same_rows(email_parser):
    iep, table, sent = email_parser
    body = "#1 the chronicle title is wrong\n#2 the protein target should be 190g not 170g"
    out = iep.handle_review_pack_reply(body, "Re: Weekly AI Review Pack", "awsdev@mattsusername.com")
    assert len(out["applied"]) == 2
    assert out["unresolved"] == []
    assert len(table.puts) == 2
    # rows carry the SAME item_ref shape the MCP channel writes
    refs = {p["item_ref"]["pack_number"]: p["item_ref"] for p in table.puts}
    assert refs[1]["surface"] == "chronicle"
    assert refs[2]["coach"] == "sleep_coach"
    assert all(p["error_class"] == "other" for p in table.puts)  # email channel: default class
    assert sent["applied"] and sent["recipient"] == "awsdev@mattsusername.com"


def test_email_unknown_number_reported_not_dropped(email_parser):
    iep, table, sent = email_parser
    out = iep.handle_review_pack_reply("#9 there is no item nine", "Re: Weekly AI Review Pack", "awsdev@mattsusername.com")
    assert out["applied"] == []
    assert any("#9" in u and "no item #9" in u for u in out["unresolved"])
    assert table.puts == []


def test_email_malformed_line_reported_and_valid_still_lands(email_parser):
    iep, table, sent = email_parser
    body = "#notanumber please fix this\n#2 this one is valid"
    out = iep.handle_review_pack_reply(body, "Re: Weekly AI Review Pack", "awsdev@mattsusername.com")
    assert [a["n"] for a in out["applied"]] == [2]
    assert len(table.puts) == 1
    assert any("notanumber" in u for u in out["unresolved"])  # malformed reported


def test_email_no_correction_lines_reported(email_parser):
    iep, table, sent = email_parser
    out = iep.handle_review_pack_reply("thanks, looks good!", "Re: Weekly AI Review Pack", "awsdev@mattsusername.com")
    assert out["applied"] == []
    assert any("no '#N" in u for u in out["unresolved"])
    assert table.puts == []
