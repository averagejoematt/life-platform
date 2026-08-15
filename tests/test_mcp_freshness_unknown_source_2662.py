"""#2662 — a source name the freshness tool doesn't recognise must not read as "all fresh".

Measured against the deployed `life-platform-mcp` Lambda on 2026-08-15, BEFORE the fix:

    get_freshness_status {"sources": ["whoop", "not_a_real_source"]}
      -> {"status": "green", "fresh_count": 1, "stale_count": 0,
          "fresh_sources": [{"source": "whoop", ...}]}

`not_a_real_source` is absent from the answer entirely. The caller asked about two
sources, got a green verdict, and nothing in the response says one of them was never
looked at. A typo — or a source renamed in the registry — reads as "everything is
fresh", from the one tool whose entire job is answering "are we OK?".

This is the identical class the `_unreadable` helper in the same function was written
to close, and its docstring says so out loud:

    "A source we could not read is a NOT-OK answer, never a silent omission. Three
     paths used to exit without a trace … so asking about two sources with one
     unreadable answered `green, fresh_count: 1, stale_count: 0`."

That fix closed three paths inside the loop. The unknown-name path sits one line ABOVE
the loop — `keys = [s for s in requested if s in SOURCES]` — and was missed. Same
sentence, same wrong output, different line.

WHY REJECT RATHER THAN REPORT-AND-CONTINUE. A freshness verdict computed over "the
sources that happened to be spelled correctly" is not a partial answer, it is a wrong
one: `green` is a claim about a set, and the caller's set is not the set that was
checked. So the tool refuses and names the valid set, and separately every successful
response now states `evaluated_sources` — because a status over an unstated subset is
the shape that made this invisible in the first place.

THE VALID SET IS DERIVED. It comes from `ingestion.source_registry.mcp_sources()` — the
same registry the evaluation loop reads its thresholds from — so a source added or
renamed there is accepted or rejected correctly on the same commit. The issue asked for
exactly this ("derived from source_registry.py, not hand-listed"), and the tests below
derive their subjects the same way rather than naming `whoop` and hoping.
"""

from __future__ import annotations

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

import pytest  # noqa: E402
from ingestion.source_registry import mcp_sources  # noqa: E402

from mcp import tools_labs  # noqa: E402
from mcp.tools_labs import tool_get_freshness_status  # noqa: E402

VALID = sorted(mcp_sources())


class _EmptyTable:
    """Every partition reads empty. Hermetic — no AWS, and no dependence on what today's
    real data happens to look like. The name-validation boundary this file tests runs
    BEFORE any query, so the table only has to not be the thing under test."""

    def query(self, **_kwargs):
        return {"Items": []}


@pytest.fixture(autouse=True)
def _no_aws(monkeypatch):
    monkeypatch.setattr(tools_labs, "table", _EmptyTable())


def test_the_registry_is_the_source_of_truth_and_is_not_empty():
    """Vacuity guard: an empty valid set would make every rejection below trivially right."""
    assert len(VALID) >= 8, f"only {len(VALID)} mcp sources — registry derivation broke"
    assert "whoop" in VALID


@pytest.mark.parametrize(
    "bad",
    ["not_a_real_source", "Whoop", "whoop ", "wthings", "apple-health"],
    ids=["unknown", "wrong-case", "trailing-space", "typo", "wrong-separator"],
)
def test_an_unrecognised_source_is_refused_not_dropped(bad):
    result = tool_get_freshness_status({"sources": [bad]})
    assert result.get("status") != "green", f"{bad!r} produced a green verdict: {result}"
    assert "error" in result, f"{bad!r} was not refused: {result}"
    assert bad in result["error"], "the error must name the offending value"


def test_the_issues_own_case_no_longer_answers_green():
    """The exact live call from the issue: one good name, one bad."""
    result = tool_get_freshness_status({"sources": ["whoop", "not_a_real_source"]})
    assert "error" in result
    assert result.get("status") != "green"
    assert "fresh_count" not in result, "no freshness verdict may be published over a partly-unknown set"


def test_the_refusal_names_the_valid_set_and_it_comes_from_the_registry():
    """Acceptance box 1 — derived, not hand-listed."""
    result = tool_get_freshness_status({"sources": ["nope"]})
    suggestions = " ".join(result.get("suggestions", []))
    for src in VALID:
        assert src in suggestions, f"valid source {src!r} missing from the error's suggested set"


def test_an_empty_source_list_is_not_silently_read_as_all():
    """`if requested:` treated an explicit [] as 'unset' and checked all 12 sources."""
    result = tool_get_freshness_status({"sources": []})
    assert "error" in result, f"an explicitly empty list answered: {result}"


def test_a_bare_string_is_refused_rather_than_iterated_as_characters():
    """`[s for s in "whoop" if s in SOURCES]` yields [] — a green verdict over nothing.

    The MCP handler's type check catches this before the tool on the wire; the tool
    must not depend on being called only through that one path.
    """
    result = tool_get_freshness_status({"sources": "whoop"})
    assert "error" in result and "list" in result["error"]


# ── the controls: the guard must not have broken the working paths ───────────


def test_every_registered_source_is_still_accepted_by_name():
    """A guard that rejects valid input is worse than the bug it replaced."""
    result = tool_get_freshness_status({"sources": VALID})
    assert "error" not in result, result
    assert result["evaluated_sources"] == VALID


def test_omitting_sources_still_checks_them_all():
    result = tool_get_freshness_status({})
    assert "error" not in result
    assert sorted(result["evaluated_sources"]) == VALID


def test_every_response_states_the_set_its_verdict_covers():
    """Acceptance box 2. `status: green` over an unstated subset is what hid this bug."""
    for args in ({}, {"sources": ["whoop"]}, {"sources": VALID[:3]}):
        result = tool_get_freshness_status(args)
        assert "evaluated_sources" in result, f"{args} -> no evaluated_sources"
        assert result["evaluated_sources"], "the evaluated set must never be empty in a verdict"


def test_a_typod_source_never_returns_a_green_verdict():
    """Acceptance box 3, stated as the issue states it."""
    result = tool_get_freshness_status({"sources": ["whooop"]})
    assert result.get("status") != "green"
