"""tests/test_mcp_tool_call_residue_guard_4190.py — #4190.

`/api/decisions` served a `log_decision` record (dated 2026-09-08, `source: mcp`)
whose `decision` field ended `…Foundation - Push - 3 - 11.</decision>\\n<parameter
name="followed">true`. That tail is the closing half of the CALLING MCP client's
own tool-call XML envelope, echoed back into the string argument it was
assembling by a client-side parsing bug, and the write door stored it verbatim.
The live row is `DECISION#2026-09-07T04:02:58.868Z`; `followed` is ABSENT on it —
the envelope swallowed the argument that followed.

THE DOOR REFUSES; IT NEVER TRIMS. The owner's ruling on #4190: a write door that
truncates the argument and stores the rest has rewritten the owner's words
without telling anyone (and has kept a row whose next argument was lost). So
`mcp/handler.py::handle_tools_call` REFUSES the call with a structured error
(`error_code == "TOOL_CALL_RESIDUE"`) that names the field and the fragment,
before schema validation, before the rate limiter charges it, before the audit
hook hashes it, and before the tool function runs. Nothing is written.

THE GUARD IS CENTRAL, NOT A PER-TOOL SPRINKLE. It runs ahead of every classified
WRITE tool (`mcp/audit.py::is_write_tool` — the SAME registry-derived
classification the #753 audit trail already uses). This guards the SET by
construction: a 27th write tool inherits the refusal for free, it is never a hand
list to fall out of date. The derivation below walks `mcp/registry.py::TOOLS`,
takes every write tool's free-text fields FROM ITS OWN inputSchema (string,
object, array-of-string), and drives each (door, field) through the REAL dispatch
path with the live specimen — asserting the refusal and that the tool function
was never entered.

MUTATION CONTROLS (the set test must be able to fail, and must name the door):
  * guard OFF -> the exact filed scenario stores the residue (the pre-fix defect,
    reproduced) — proves the green end-to-end test is not vacuous.
  * ONE door dropped from the write set -> the per-door assertion fails and its
    message names that door — proves the set test would catch a door that
    stopped being classified (a `plan_*`-style verb landing on a writer, say).
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

import pytest  # noqa: E402
from common.text_guards import (  # noqa: E402
    TOOL_CALL_ENVELOPE_RE,
    find_tool_call_residue,
    residue_fragments,
    strip_tool_call_residue,
)

from mcp import (
    audit as mcp_audit,  # noqa: E402
    handler as h,  # noqa: E402
    tools_decisions as td,  # noqa: E402
)
from mcp.registry import TOOLS  # noqa: E402
from tests.reading_fakes import FakeTable  # noqa: E402

# The exact tail measured live on the 2026-09-08 log_decision record (the wire).
LIVE_RESIDUE_DECISION = 'Committed to Hevy as Foundation - Push - 3 - 11.</decision>\n<parameter name="followed">true'
LIVE_RESIDUE_CLEAN = "Committed to Hevy as Foundation - Push - 3 - 11."
LIVE_FIRST_FRAGMENT = "</decision>"

# The owner's own words that a bare-`<` catch-all would have refused. A refuser
# that bounces these has rewritten his words by another route.
OWNERS_OWN_WORDS_WITH_ANGLE_BRACKETS = [
    "keep HR < 150 on the recumbent",
    "x<y for the whole block",
    "a <3 b, honestly",
    "5 < 6 > 4 is still true",
    "deficit < 500 kcal, protein > 200 g",
]

# The namespaced spelling of the Anthropic tool-call XML is assembled here rather
# than typed as a literal: a literal in this file reads as a real tool call to the
# tooling that edits it (#4190 lane, 2026-09-26 — the first write of this module
# was truncated at exactly that literal).
_NS = "antml:"

# Every tool-call-envelope shape the pattern set names: the Anthropic tool-call
# XML (plain and namespaced), other clients' tool_call/tool_use/tool_result
# envelopes, and the one closing tag on record.
ENVELOPE_SHAPES = [
    "</decision>",
    "<function_calls>",
    "</function_calls>",
    '<invoke name="log_decision">',
    "</invoke>",
    '<parameter name="followed">true',
    "</parameter>",
    "<function_results>",
    "</function_results>",
    f"<{_NS}function_calls>",
    f"</{_NS}function_calls>",
    f'<{_NS}invoke name="log_decision">',
    f"</{_NS}invoke>",
    f'<{_NS}parameter name="decision">',
    f"</{_NS}parameter>",
    f"<{_NS}function_results>",
    f"</{_NS}function_results>",
    "<tool_call>",
    "</tool_call>",
    '<tool_use id="x">',
    "</tool_use>",
    "<tool_result>",
    "</tool_result>",
]

# The per-argument generic shapes: the field-closer half of the specimen for ANY
# other string argument, and a bare opening tag. Residue in one argument string,
# never something the page sweep should fire on.
GENERIC_TAG_SHAPES = ["</note>", "</content>", "</override_reason>", "<decision>", "</summary >"]


# ── common.text_guards — the pattern set ────────────────────────────────────


def test_find_names_the_first_fragment_of_the_live_fixture():
    assert find_tool_call_residue(LIVE_RESIDUE_DECISION) == LIVE_FIRST_FRAGMENT


@pytest.mark.parametrize("shape", ENVELOPE_SHAPES)
def test_every_envelope_shape_is_residue_on_both_patterns(shape):
    text = f"his words {shape} more"
    assert TOOL_CALL_ENVELOPE_RE.search(text), f"envelope pattern missed {shape!r}"
    frag = find_tool_call_residue(text)
    assert frag is not None and shape.startswith(frag), f"residue pattern missed {shape!r} (found {frag!r})"


@pytest.mark.parametrize("shape", GENERIC_TAG_SHAPES)
def test_generic_field_tags_are_residue_for_an_argument_but_not_for_a_page(shape):
    text = f"his words {shape} more"
    assert find_tool_call_residue(text) is not None, f"per-argument pattern missed {shape!r}"
    assert not TOOL_CALL_ENVELOPE_RE.search(text), f"the page-sweep pattern must not fire on a generic tag {shape!r}"


def test_page_markup_is_not_an_envelope():
    """The leak-token sweep scans whole rendered pages; the envelope set must be
    silent on ordinary HTML or the daily sweep reds on every page."""
    assert not TOOL_CALL_ENVELOPE_RE.search("<div class='rd-card'><span>all good</span></div>")


@pytest.mark.parametrize("words", OWNERS_OWN_WORDS_WITH_ANGLE_BRACKETS)
def test_an_inequality_in_the_owners_words_is_not_residue(words):
    """No bare-`<` catch-all: the refuser must never bounce his own sentence."""
    assert find_tool_call_residue(words) is None
    assert strip_tool_call_residue(words) == words


def test_non_strings_never_carry_residue():
    for v in (None, 42, True, 3.5):
        assert find_tool_call_residue(v) is None
        assert strip_tool_call_residue(v) is v


def test_residue_fragments_walks_nested_structures_with_paths():
    args = {
        "category": "what_worked",
        "content": {"summary": LIVE_RESIDUE_DECISION, "nested": {"deep": "clean"}},
        "domains": ["clean", "x </note> y"],
        "n": 3,
    }
    assert residue_fragments(args) == [("content.summary", "</decision>"), ("domains[1]", "</note>")]
    assert residue_fragments({"decision": "Take a rest day."}) == []


# ── the serve-time strip (defence in depth; the door itself never trims) ───


def test_strip_matches_the_live_fixture_exactly_and_is_idempotent():
    once = strip_tool_call_residue(LIVE_RESIDUE_DECISION)
    assert once == LIVE_RESIDUE_CLEAN
    assert strip_tool_call_residue(once) == once


# ── the derived door SET (guard the set, not the instance) ─────────────────


def _free_text_fields(tool_name: str) -> list[tuple[str, str]]:
    """(field, kind) for every free-text-bearing field in the tool's OWN
    inputSchema: a string, an object (a dict of strings at runtime), or an array
    of strings. Derived from the registry, never hand-listed."""
    props = TOOLS[tool_name]["schema"].get("inputSchema", {}).get("properties", {})
    out = []
    for field, spec in props.items():
        kind = spec.get("type")
        if kind == "string":
            out.append((field, "string"))
        elif kind == "object":
            out.append((field, "object"))
        elif kind == "array" and (spec.get("items") or {}).get("type") == "string":
            out.append((field, "array"))
    return out


WRITE_TOOLS = sorted(name for name in TOOLS if mcp_audit.is_write_tool(name))
READ_TOOLS = sorted(name for name in TOOLS if not mcp_audit.is_write_tool(name))
DOOR_FIELDS = [(tool, field, kind) for tool in WRITE_TOOLS for field, kind in _free_text_fields(tool)]


def _fixture_for(kind: str):
    if kind == "object":
        return {"summary": LIVE_RESIDUE_DECISION}
    if kind == "array":
        return [LIVE_RESIDUE_DECISION]
    return LIVE_RESIDUE_DECISION


def _error_of(result: dict) -> dict:
    return json.loads(result["content"][0]["text"])


def test_write_tool_set_is_non_vacuous_and_covers_the_named_examples():
    assert len(WRITE_TOOLS) >= 20, f"only {len(WRITE_TOOLS)} write tools derived — the classification probably broke"
    for named in (
        "log_decision",
        "save_insight",
        "write_platform_memory",
        "log_field_note_response",
        "log_coach_correction",
        "log_evening_intake",
        "manage_diary_claims",
    ):
        assert named in WRITE_TOOLS, f"{named} (named in #4190) did not classify as a write tool"
        assert _free_text_fields(
            named
        ), f"{named}: no free-text field derived from its inputSchema — the derivation is wrong or the schema lost its strings"
    assert len(DOOR_FIELDS) >= 60, f"only {len(DOOR_FIELDS)} (door, field) pairs derived"


def _assert_door_refuses(tool: str, field: str, kind: str, monkeypatch) -> None:
    """The one assertion the set test and its mutation control share: drive the
    live specimen through the REAL dispatch path in `field` of `tool`; the door
    must refuse with a structured error naming both, and the tool function must
    never be entered."""
    entered = []
    monkeypatch.setitem(TOOLS[tool], "fn", lambda args: entered.append(args) or {"status": "should never run"})
    result = h.handle_tools_call({"name": tool, "arguments": {field: _fixture_for(kind)}})
    err = _error_of(result)
    assert err.get("error_code") == "TOOL_CALL_RESIDUE", f"{tool}.{field}: door did not refuse residue (got {err})"
    assert (
        field in err["error"] and LIVE_FIRST_FRAGMENT in err["error"]
    ), f"{tool}.{field}: refusal does not name the field and the fragment: {err['error']}"
    detail = json.loads(err["detail"])
    assert detail["tool"] == tool
    assert any(f["field"].split(".")[0].split("[")[0] == field and f["residue"] == LIVE_FIRST_FRAGMENT for f in detail["fields"])
    assert entered == [], f"{tool}.{field}: the tool function RAN — the refusal came after the write"


@pytest.mark.parametrize("tool,field,kind", DOOR_FIELDS, ids=[f"{t}.{f}" for t, f, _ in DOOR_FIELDS])
def test_every_free_text_field_of_every_write_door_refuses_the_live_residue(tool, field, kind, monkeypatch):
    """Guard the SET: every free-text field of every classified write tool, each
    derived from the registry's own inputSchema — not a hand-picked few."""
    _assert_door_refuses(tool, field, kind, monkeypatch)


@pytest.mark.parametrize("name", READ_TOOLS)
def test_read_tools_are_not_refused(name):
    """Residue in a READ tool's arguments can only affect what THIS call returns —
    never what gets persisted — so the write guard correctly leaves it alone."""
    assert h._refuse_tool_call_residue(name, {"probe_field": LIVE_RESIDUE_DECISION}) is None


def test_the_refusal_runs_before_schema_validation_and_the_rate_limiter(monkeypatch):
    """Ordering is the contract (hazard gate first): a refused call must not reach
    the SEC-3 validator (which would raise on the missing required field here) and
    must not be charged against the write rate limit."""
    charged = []
    monkeypatch.setattr(h, "_check_write_rate_limit", lambda name: charged.append(name) or None)
    result = h.handle_tools_call({"name": "save_insight", "arguments": {"insight": LIVE_RESIDUE_DECISION}})
    assert _error_of(result)["error_code"] == "TOOL_CALL_RESIDUE"
    assert charged == [], "a refused write was charged against the rate limit"


def test_the_refusal_never_modifies_the_callers_arguments():
    args = {"decision": LIVE_RESIDUE_DECISION, "followed": True}
    snapshot = dict(args)
    assert h._refuse_tool_call_residue("log_decision", args) is not None
    assert args == snapshot


# ── end-to-end: the exact filed scenario, through the real dispatch path ───


@pytest.fixture
def fake_table(monkeypatch):
    ft = FakeTable()
    monkeypatch.setattr(td, "_table_ref", ft)
    import mcp.config as cfg

    monkeypatch.setattr(cfg, "table", ft)
    return ft


def test_log_decision_end_to_end_is_refused_and_nothing_is_stored(fake_table):
    result = h.handle_tools_call({"name": "log_decision", "arguments": {"decision": LIVE_RESIDUE_DECISION, "followed": True}})
    err = _error_of(result)
    assert err["error_code"] == "TOOL_CALL_RESIDUE"
    assert "decision" in err["error"] and LIVE_FIRST_FRAGMENT in err["error"]
    assert fake_table.store == {}, "a refused write must store NOTHING — not a trimmed row, not an idempotency claim"
    assert fake_table.put_calls == []


def test_a_clean_decision_in_the_owners_words_is_stored_verbatim(fake_table):
    """Non-vacuity's mirror, and the no-rewrite rule: a decision with no residue
    — including one carrying a real inequality — lands byte-for-byte."""
    words = "Take a rest day; keep HR < 150 if you walk."
    result = h.handle_tools_call({"name": "log_decision", "arguments": {"decision": words, "followed": True}})
    assert "error" not in _error_of(result)
    stored = next(v for v in fake_table.store.values() if "decision" in v)
    assert stored["decision"] == words


# ── mutation controls ──────────────────────────────────────────────────────


def test_mutation_guard_off_reproduces_the_pre_fix_leak(fake_table, monkeypatch):
    """Disable ONLY the dispatch-level refuser (identity: every call proceeds) and
    re-run the exact filed scenario. The residue is STORED — the pre-fix defect,
    reproduced — proving the green end-to-end test above is not vacuous."""
    monkeypatch.setattr(h, "_refuse_tool_call_residue", lambda name, arguments: None)
    h.handle_tools_call({"name": "log_decision", "arguments": {"decision": LIVE_RESIDUE_DECISION, "followed": True}})
    stored = next(v for v in fake_table.store.values() if "decision" in v)
    assert stored["decision"] == LIVE_RESIDUE_DECISION, "guard-off control did not reproduce the pre-fix leak"
    assert (
        find_tool_call_residue(stored["decision"]) == LIVE_FIRST_FRAGMENT
    ), "guard-off control must actually carry residue — the point of a mutation control"


def test_mutation_one_door_dropped_from_the_set_fails_and_names_it(monkeypatch):
    """Remove ONE door from the write set (classify log_decision as a read) and the
    per-door assertion the set test runs must fail AND name that door. This is
    what would fire the day a writer lands under a read verb."""
    real = mcp_audit.is_write_tool
    monkeypatch.setattr(mcp_audit, "is_write_tool", lambda name: False if name == "log_decision" else real(name))
    with pytest.raises(AssertionError, match=r"log_decision\.decision: door did not refuse residue"):
        _assert_door_refuses("log_decision", "decision", "string", monkeypatch)
