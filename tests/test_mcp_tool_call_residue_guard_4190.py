"""tests/test_mcp_tool_call_residue_guard_4190.py — #4190.

`/api/decisions` served a `log_decision` record (dated 2026-09-08, `source: mcp`)
whose `decision` field ended `…Foundation - Push - 3 - 11.</decision>\\n<parameter
name="followed">true`. That tail is the closing half of the CALLING MCP client's
own tool-call XML envelope, echoed back into the string argument it was
assembling by a client-side parsing bug, and the write door stored it verbatim.

THE GUARD IS CENTRAL, NOT A PER-TOOL SPRINKLE. `mcp/handler.py::handle_tools_call`
strips tool-call residue from every argument of every classified WRITE tool
(`mcp/audit.py::is_write_tool` — the SAME registry-derived classification the
#753 audit trail already uses) before the tool function ever runs. This guards
the SET by construction: a 27th write tool inherits the strip for free, it is
never a hand list to fall out of date, and the derivation below asserts that
set is real (non-vacuous) and covers every door the issue named.

MUTATION CONTROL (AC1's "guard off -> residue stored -> red"):
`test_without_the_guard_the_fixture_would_have_stored_residue` monkeypatches
the dispatch-level strip to a no-op and re-runs the EXACT SAME end-to-end
scenario as the green test above it — proving the green test is not vacuous:
remove the guard and it goes red on stored, leaked residue.
"""

from __future__ import annotations

import os

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

import pytest  # noqa: E402
from common.text_guards import has_tool_call_residue, strip_tool_call_residue  # noqa: E402

from mcp import (
    audit as mcp_audit,  # noqa: E402
    handler as h,  # noqa: E402
    tools_decisions as td,  # noqa: E402
)
from mcp.registry import TOOLS  # noqa: E402
from tests.reading_fakes import FakeTable  # noqa: E402

# The exact tail measured live on the 2026-09-08 log_decision record.
LIVE_RESIDUE_DECISION = 'Committed to Hevy as Foundation - Push - 3 - 11.</decision>\n<parameter name="followed">true'
LIVE_RESIDUE_CLEAN = "Committed to Hevy as Foundation - Push - 3 - 11."


# ── common.text_guards — the pure strip ─────────────────────────────────────


def test_strip_matches_the_live_fixture_exactly():
    assert strip_tool_call_residue(LIVE_RESIDUE_DECISION) == LIVE_RESIDUE_CLEAN


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("clean text, nothing to strip", "clean text, nothing to strip"),
        ("", ""),
        ("before</invoke>after", "before"),
        ("before<function_calls>after", "before"),
        ('before<invoke name="x">after', "before"),
        ("no angle brackets at all", "no angle brackets at all"),
    ],
)
def test_strip_is_a_truncation_not_a_rejection(raw, expected):
    assert strip_tool_call_residue(raw) == expected


def test_strip_is_idempotent():
    once = strip_tool_call_residue(LIVE_RESIDUE_DECISION)
    assert strip_tool_call_residue(once) == once


def test_strip_leaves_non_strings_untouched():
    for v in (None, 42, True, 3.5, ["a", "<invoke"], {"k": "<invoke"}):
        assert strip_tool_call_residue(v) is v


def test_has_tool_call_residue_true_only_when_present():
    assert has_tool_call_residue(LIVE_RESIDUE_DECISION) is True
    assert has_tool_call_residue("clean text") is False
    assert has_tool_call_residue(42) is False


# ── the derived door SET (guard the set, not the instance) ─────────────────


def test_write_tool_set_is_non_vacuous_and_covers_the_named_examples():
    write_tools = {name for name in TOOLS if mcp_audit.is_write_tool(name)}
    assert len(write_tools) >= 20, f"only {len(write_tools)} write tools derived — the classification probably broke"
    for named in ("log_decision", "write_platform_memory", "save_insight", "log_coach_correction"):
        assert named in write_tools, f"{named} (named in #4190) did not classify as a write tool"


@pytest.mark.parametrize("name", sorted(name for name in TOOLS if mcp_audit.is_write_tool(name)))
def test_every_write_tool_is_sanitized_by_the_dispatch_guard(name):
    """Guard the SET: every single classified write tool, not a hand-picked few."""
    cleaned = h._sanitize_write_arguments(name, {"probe_field": LIVE_RESIDUE_DECISION})
    assert cleaned["probe_field"] == LIVE_RESIDUE_CLEAN, f"{name}: dispatch guard did not strip residue"


@pytest.mark.parametrize("name", sorted(name for name in TOOLS if not mcp_audit.is_write_tool(name)))
def test_read_tools_are_left_untouched_by_the_write_guard(name):
    """Residue in a READ tool's arguments can only affect what THIS call returns —
    never what gets persisted — so the write guard correctly leaves it alone."""
    cleaned = h._sanitize_write_arguments(name, {"probe_field": LIVE_RESIDUE_DECISION})
    assert cleaned["probe_field"] == LIVE_RESIDUE_DECISION


def test_dispatch_guard_walks_nested_dicts_and_lists():
    """write_platform_memory's `content` is a dict, and several tools carry list-of-
    string fields (pillars, tags, domains) — the walk must not stop at the top level."""
    args = {
        "category": "what_worked",
        "content": {"summary": LIVE_RESIDUE_DECISION, "nested": {"deep": LIVE_RESIDUE_DECISION}},
        "domains": [LIVE_RESIDUE_DECISION],
    }
    cleaned = h._sanitize_write_arguments("write_platform_memory", args)
    assert cleaned["content"]["summary"] == LIVE_RESIDUE_CLEAN
    assert cleaned["content"]["nested"]["deep"] == LIVE_RESIDUE_CLEAN
    assert cleaned["domains"] == [LIVE_RESIDUE_CLEAN]


def test_clean_arguments_pass_through_unchanged_object_identity_not_required():
    """Non-vacuity's mirror: a call with NO residue must not be altered at all."""
    args = {"decision": "Take a rest day.", "followed": True, "pillars": ["sleep", "movement"]}
    cleaned = h._sanitize_write_arguments("log_decision", args)
    assert cleaned == args


# ── end-to-end: the exact filed scenario, through the real dispatch path ───


@pytest.fixture
def fake_table(monkeypatch):
    ft = FakeTable()
    monkeypatch.setattr(td, "_table_ref", ft)
    import mcp.config as cfg

    monkeypatch.setattr(cfg, "table", ft)
    return ft


def test_log_decision_end_to_end_strips_residue_via_real_dispatch(fake_table):
    result = h.handle_tools_call({"name": "log_decision", "arguments": {"decision": LIVE_RESIDUE_DECISION, "followed": True}})
    assert "error" not in result
    stored = next(v for v in fake_table.store.values() if "decision" in v)
    assert stored["decision"] == LIVE_RESIDUE_CLEAN
    assert not has_tool_call_residue(stored["decision"])


def test_without_the_guard_the_fixture_would_have_stored_residue(fake_table, monkeypatch):
    """Mutation control (AC1): disable ONLY the dispatch-level strip (identity
    passthrough) and re-run the exact same scenario as the green test above.
    This must go RED on stored residue — proving that test is not vacuously
    green, and documenting the exact pre-fix defect this issue was filed on."""
    monkeypatch.setattr(h, "strip_tool_call_residue", lambda text: text)
    h.handle_tools_call({"name": "log_decision", "arguments": {"decision": LIVE_RESIDUE_DECISION, "followed": True}})
    stored = next(v for v in fake_table.store.values() if "decision" in v)
    assert stored["decision"] == LIVE_RESIDUE_DECISION, "guard-off control did not reproduce the pre-fix leak"
    assert has_tool_call_residue(stored["decision"]), "guard-off control must actually carry residue — the point of a mutation control"
