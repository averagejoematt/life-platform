"""#2660 / #2664 — an argument the caller supplied must be applied or refused, never quietly replaced.

Two tools, one failure: a value arrives at the boundary, is silently turned into a
different value, and the answer is then narrated as if the original had been used.
Measured against the deployed `life-platform-mcp` Lambda on 2026-08-15, BEFORE the fix:

    get_insights   {"limit": -1}   -> 200  total 41, returned 40, truncated true
    get_insights   {"limit": 0}    -> 200  total 41, returned 41, truncated false
    get_insights   {"limit": 3}    -> 200  total 41, returned  3, truncated true   <- clean control

`limit=-1` is `matched[:-1]`: it drops a record and then labels the short list
"truncated", which is the word for a page — so the caller reads a silently lossy
result as a complete-but-paged one. `limit=0` is `int(args.get("limit") or 50)`:
zero is falsy, so a request for none returned all fifty.

    get_muscle_volume {"period": "bogus"} -> 200  analysis_period "month"

The enum is coerced, not rejected. A coerced enum is strictly worse than an error,
because nothing downstream can distinguish the answer from a right one.

THE FILED SCOPE WAS SMALLER THAN THE DEFECT. Probing `get_muscle_volume` for the
issue's third acceptance box ("no record outside the applied window is described as
in-window") surfaced a second, live wrong claim that has nothing to do with `period`:

    get_muscle_volume {"start_date": "2026-08-01", "end_date": "2026-08-15"}
      -> completeness.stale = true
         "…a more recent in-window session is ingested (2026-06-25).
           Volume may undercount the latest training — do not author off this read
           until it clears."

2026-06-25 is six weeks BEFORE the window opens. `assess_volume_completeness` tested
`latest_ingested <= end_date` and never `>= start_date`, so any window starting after
the last session took the in-window branch. Nothing was missing — there was simply no
August training. The tool raised an authoring gate against a true statement, and the
gate can never clear, because no session will ever appear inside a window that has
already passed.

GUARD THE SET, NOT THE INSTANCE. The enforcement is generic in
`mcp.handler._validate_tool_args`, driven by the registry's own `enum` / `minimum`
declarations plus a `_RESULT_COUNT_ARGS` floor, so the tests below derive their
subjects from the live registry rather than naming `get_insights` and hoping.

`count` is the deliberate NON-member of that floor, and it is tested as such:
`log_evening_intake`'s `count` is a measurement with a valid value of 0. A floor
applied by shape rather than by meaning would reject a truthful "zero last night" —
a validation guard inventing exactly the kind of silent wrongness it exists to stop.
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

from mcp.handler import _RESULT_COUNT_ARGS, _validate_tool_args  # noqa: E402
from mcp.registry import TOOLS  # noqa: E402
from mcp.strength_helpers import assess_volume_completeness  # noqa: E402


def _schema(tool: str) -> dict:
    return TOOLS[tool].get("schema", {}).get("inputSchema", {}) or {}


def _props(tool: str) -> dict:
    return _schema(tool).get("properties", {}) or {}


def _tools_with_arg(arg: str) -> list[str]:
    return sorted(name for name in TOOLS if arg in _props(name))


_PLACEHOLDER = {"string": "x", "integer": 1, "number": 1, "boolean": True, "array": [], "object": {}}


def _args(tool: str, **overrides) -> dict:
    """Minimal schema-valid arguments for `tool`, with `overrides` applied.

    Required fields must be filled or step 1 of `_validate_tool_args` short-circuits on
    "Missing required argument" and every assertion below tests the wrong thing. That is
    exactly how the first draft of this file produced 30 green-looking failures.
    """
    built: dict = {}
    for field in _schema(tool).get("required", []) or []:
        spec = _props(tool).get(field, {}) or {}
        if field in overrides:
            continue
        if spec.get("enum"):
            built[field] = spec["enum"][0]
        elif spec.get("type") == "string" and field.endswith("_date"):
            built[field] = "2026-08-01"
        else:
            built[field] = _PLACEHOLDER.get(spec.get("type"), "x")
    built.update(overrides)
    return built


# ── #2660: the result-count floor ────────────────────────────────────────────


def test_limit_class_args_exist_on_the_live_surface():
    """Vacuity guard: an empty derived set would make every test below pass trivially."""
    covered = {name: arg for arg in _RESULT_COUNT_ARGS for name in _tools_with_arg(arg)}
    assert len(covered) >= 10, f"only {len(covered)} tools carry a result-count arg — derivation broke"
    assert "get_insights" in covered, "the issue's own tool must be in the derived set"


@pytest.mark.parametrize("tool", _tools_with_arg("limit"))
@pytest.mark.parametrize("bad", [0, -1, -50])
def test_every_limit_arg_rejects_zero_or_fewer(tool, bad):
    """Not just get_insights — `limit` is declared on 11 tools and 9 declared no minimum."""
    err = _validate_tool_args(tool, _args(tool, limit=bad))
    assert err is not None, f"{tool} accepted limit={bad}"
    assert "at least 1" in err, f"{tool} rejected limit={bad} without naming the accepted range: {err!r}"


@pytest.mark.parametrize("tool", _tools_with_arg("limit"))
def test_a_valid_limit_still_passes(tool):
    """The control. A guard that rejects everything is not a guard."""
    assert _validate_tool_args(tool, _args(tool, limit=3)) is None


def test_count_is_not_floored_because_zero_is_a_truthful_measurement():
    """`log_evening_intake(count=0)` means 'none last night' — flooring it would fabricate a 1."""
    assert "count" not in _RESULT_COUNT_ARGS
    assert "count" in _props("log_evening_intake")
    assert _validate_tool_args("log_evening_intake", _args("log_evening_intake", count=0)) is None


def test_get_insights_zero_is_no_longer_swallowed_by_the_default():
    """`int(args.get("limit") or 50)` turned a supplied 0 into 50. The boundary now refuses it."""
    err = _validate_tool_args("get_insights", _args("get_insights", limit=0))
    assert err is not None and "at least 1" in err


def test_get_insights_declares_its_own_floor():
    """Declared in the schema as well as enforced generically — the interface should state it."""
    assert _props("get_insights")["limit"].get("minimum") == 1


# ── #2664: the enum boundary ─────────────────────────────────────────────────


def _tools_with_enums(exempt: bool | None = False) -> list[tuple[str, str, list]]:
    """Every (tool, arg, enum) in the live registry, split by the sanctioned opt-out.

    `exempt=False` → enforced args. `exempt=True` → args declaring `coerce_outside_enum`.
    `exempt=None` → all of them.
    """
    found = []
    for name in sorted(TOOLS):
        for arg, spec in sorted(_props(name).items()):
            if not (isinstance(spec, dict) and spec.get("enum")):
                continue
            if exempt is None or bool(spec.get("coerce_outside_enum")) is exempt:
                found.append((name, arg, spec["enum"]))
    return found


def test_the_enum_surface_is_the_size_the_defect_actually_was():
    """The issue named ONE argument. Vacuity guard + the record of the real scope."""
    declared = _tools_with_enums(exempt=None)
    assert len(declared) >= 25, f"only {len(declared)} declared enums — derivation broke"
    assert ("get_muscle_volume", "period", ["week", "month"]) in declared


@pytest.mark.parametrize("tool,arg,allowed", _tools_with_enums())
def test_every_declared_enum_rejects_a_value_outside_it(tool, arg, allowed):
    err = _validate_tool_args(tool, _args(tool, **{arg: "definitely-not-a-member"}))
    assert err is not None, f"{tool}.{arg} accepted a value outside {allowed}"
    assert str(allowed[0]) in err, f"{tool}.{arg} rejected without listing the accepted enum: {err!r}"


@pytest.mark.parametrize("tool,arg,allowed", _tools_with_enums())
def test_every_declared_enum_accepts_each_of_its_own_members(tool, arg, allowed):
    for value in allowed:
        assert _validate_tool_args(tool, _args(tool, **{arg: value})) is None, f"{tool}.{arg} rejected its own member {value!r}"


@pytest.mark.parametrize("tool,arg,allowed", _tools_with_enums())
def test_enum_matching_tolerates_the_case_and_spacing_the_tools_already_strip(tool, arg, allowed):
    """THE REGRESSION THIS GUARD COULD HAVE CAUSED.

    Eight tools (`get_nutrition`, `get_training`, `manage_sick_days`, `find_days`,
    `manage_reading`, …) resolve their view/action with `(args.get(x) or default).lower().strip()`,
    so `view=" Summary "` works on the deployed Lambda today. A strict boundary check
    would have started rejecting every one of those calls — a validation guard causing
    exactly the class of silent breakage it exists to prevent.
    """
    for value in allowed:
        if not isinstance(value, str):
            continue
        noisy = f"  {value.upper()}  "
        assert _validate_tool_args(tool, _args(tool, **{arg: noisy})) is None, f"{tool}.{arg} rejected {noisy!r}"


def test_the_opt_out_is_exactly_one_argument_and_it_still_coerces():
    """#1806 chose coercion over refusal for `mark_journal_quote.channel`, on the record.

    A bad channel must not discard an otherwise-good, taboo-clean quote mark, and the
    taboo string still never reaches DynamoDB — the tool's own allowlist collapses it
    before the write. The opt-out lives in the schema, not in a list inside handler.py,
    so a second one cannot be added invisibly: this test names the whole set.
    """
    assert _tools_with_enums(exempt=True) == [("mark_journal_quote", "channel", ["journal", "video_diary", "solo_recording"])]
    assert _validate_tool_args("mark_journal_quote", _args("mark_journal_quote", channel="not-a-channel")) is None


def test_a_non_exempt_sibling_argument_on_the_same_tool_is_still_enforced():
    """The opt-out is per-argument, not per-tool — `mark_journal_quote.action` still rejects."""
    err = _validate_tool_args("mark_journal_quote", _args("mark_journal_quote", action="obliterate"))
    assert err is not None and "mark" in err


# ── #2664 (widened): the in-window claim ─────────────────────────────────────


def test_a_session_before_the_window_is_not_called_in_window():
    """The live wrong claim: window 2026-08-01..08-15, newest session 2026-06-25."""
    result = assess_volume_completeness([], "2026-06-25", "2026-08-15", "2026-08-01")
    assert "in-window" not in result["note"], result["note"]
    assert result["stale"] is False, "an empty window with no sessions on file is not stale data"
    assert "2026-06-25" in result["note"], "the note must still say where the last session actually was"
    assert "do not author off this read" not in result["note"]


def test_the_real_night_before_undercount_still_fires():
    """The behaviour B2a added must survive: newest session in-window, aggregation behind it."""
    result = assess_volume_completeness(["2026-08-10"], "2026-08-14", "2026-08-15", "2026-08-01")
    assert result["stale"] is True
    assert "in-window session is ingested (2026-08-14)" in result["note"]
    assert "do not author off this read" in result["note"]


def test_an_in_window_aggregation_that_reached_the_high_water_mark_is_clean():
    result = assess_volume_completeness(["2026-08-14"], "2026-08-14", "2026-08-15", "2026-08-01")
    assert result["stale"] is False
    assert result["includes_latest"] is True


def test_a_session_newer_than_the_window_is_unchanged():
    """The >end branch is deliberately untouched — out of scope, and its conservatism is correct."""
    result = assess_volume_completeness(["2026-06-20"], "2026-08-14", "2026-06-30", "2026-06-01")
    assert result["stale"] is False
    assert result["includes_latest"] is True


def test_start_date_defaults_to_none_for_existing_callers():
    """Positional back-compat: the new argument is last and optional."""
    result = assess_volume_completeness([], "2026-06-25", "2026-08-15")
    assert result["latest_ingested"] == "2026-06-25"
