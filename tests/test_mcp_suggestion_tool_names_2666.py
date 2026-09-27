"""#2666 — an MCP error suggestion must not name a tool that does not exist.

Every MCP tool error carries `suggestions`: the recovery actions Claude reads and
acts on without re-prompting Matthew. A suggestion that says "Call get_data_freshness"
when no such tool is registered does not degrade to a no-op — Claude follows it and
gets a *second*, unrelated failure ("Unknown tool"), so the first error's real cause
is buried under a fabricated one.

GUARD THE SET, NOT THE INSTANCE. The issue named one bad string. Deriving the set by
AST found **two** distinct dead names across four sites:

    mcp/utils.py:164  NO_DATA         "Call get_data_freshness to check when this source last updated."
    mcp/utils.py:175  SOURCE_UNAVAIL  "Call get_data_freshness to see which sources are current."
    mcp/utils.py:180  PARTIAL_DATA    "Call get_data_freshness to see if the source is fully ingested."
    mcp/utils.py:184  QUERY_TOO_BROAD "Use get_longitudinal_summary for multi-year overviews instead."

Neither is in `mcp/registry.py`'s TOOLS. `get_freshness_status` is the tool that
answers the first three; nothing answers the fourth, so it is replaced with a
suggestion naming a tool that exists.

HOW THE SET IS DERIVED — every input is read out of source, nothing is hand-listed:

  * suggestion strings  = the `_DEFAULTS` dict in `_default_suggestions` PLUS every
    `suggestions=` kwarg / third positional argument at every `mcp_error(...)` call
    site under `mcp/`. A new suggestion anywhere is covered the day it lands.
  * registered tools    = the keys of the TOOLS dict in `mcp/registry.py`.
  * tool-name verbs     = the first `_`-segment of every registered tool name, so
    `get_`, `list_`, `manage_`, `end_`… come from the registry, not from a literal.
  * schema arg names    = the union of every `inputSchema.properties` key. This is
    what keeps `start_date`/`end_date` out of the candidate set: `end_experiment`
    makes `end` a tool verb, so `end_date` looks exactly like a tool reference
    until you subtract the arguments. Hand-excluding those two would re-introduce
    the same blind spot one rename later.

The planted-bad-name test below is what makes this a guard and not a snapshot: it
proves the extractor actually catches a fabricated tool name in a fresh suggestion.
"""

from __future__ import annotations

import ast
import os
import pathlib
import re
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

REPO = pathlib.Path(_REPO)
MCP_DIR = REPO / "mcp"

_SNAKE = re.compile(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b")


def _string_constants(node: ast.AST) -> list[tuple[int, str]]:
    return [(n.lineno, n.value) for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _registry() -> tuple[set[str], set[str], set[str]]:
    """(tool names, tool-name verbs, schema argument names) — all from registry.py."""
    tree = ast.parse((MCP_DIR / "registry.py").read_text())
    tools_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "TOOLS" for t in node.targets):
            tools_node = node.value
    assert tools_node is not None, "TOOLS dict not found in mcp/registry.py"

    names = {k.value for k in tools_node.keys if isinstance(k, ast.Constant)}
    assert len(names) > 50, f"registry parse looks wrong — only {len(names)} tools"

    args: set[str] = set()
    for value in tools_node.values:
        for sub in ast.walk(value):
            if not isinstance(sub, ast.Dict):
                continue
            for k, v in zip(sub.keys, sub.values):
                if isinstance(k, ast.Constant) and k.value == "properties" and isinstance(v, ast.Dict):
                    args |= {pk.value for pk in v.keys if isinstance(pk, ast.Constant)}
    assert "start_date" in args and "end_date" in args, "schema-argument extraction failed"

    return names, {n.split("_", 1)[0] for n in names}, args


# #4172: the one envelope builder outside mcp/ — `training.commit_binding` takes `mcp_error` in
# as `err` and calls it with `suggestions=`; its strings reach the caller like any other.
_ENVELOPE_BUILDERS = frozenset({"mcp_error", "err"})
_EXTRA_FILES = (REPO / "lambdas" / "training" / "commit_binding.py",)


def _error_source_files() -> list[pathlib.Path]:
    return sorted(MCP_DIR.rglob("*.py")) + list(_EXTRA_FILES)


def _binding_targets(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Assign):
        return [getattr(t, "id", "") for t in node.targets]
    if isinstance(node, ast.AnnAssign):
        return [getattr(node.target, "id", "")]
    return []


def _suggestion_strings() -> list[tuple[str, int, str]]:
    """Every string that can reach a caller as an MCP error `suggestions` entry."""
    found: list[tuple[str, int, str]] = []
    for path in _error_source_files():
        tree = ast.parse(path.read_text())
        rel = str(path.relative_to(REPO))
        for node in ast.walk(tree):
            if "_DEFAULT_SUGGESTIONS" in _binding_targets(node):
                found += [(rel, ln, s) for ln, s in _string_constants(node.value)]
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") in _ENVELOPE_BUILDERS:
                for kw in node.keywords:
                    if kw.arg == "suggestions":
                        found += [(rel, ln, s) for ln, s in _string_constants(kw.value)]
                if len(node.args) >= 3:
                    found += [(rel, ln, s) for ln, s in _string_constants(node.args[2])]
    return found


# ── #4172: a POLICY refusal is never told to retry ─────────────────────────────────────────
#
# The live specimen (2026-09-26 ~02:17Z): `manage_hevy_routine commit` refused a routine that
# had not passed stage 2 — error_code REDTEAM_BINDING, the right error, the right detail — and
# `suggestions` read ["Retry or check system status."], the transport fallback. A policy
# refusal answers the same call identically; an agent that reads only `suggestions` loops.
#
# THE SET, NOT THE INSTANCE. The kind lives on the code in `mcp.utils._ERROR_CODE_SPECS`, so
# "which codes are policy" is read from the registry, and "which codes are emitted" is read
# out of source — every `error_code=` constant at an envelope-builder call and every
# module-level `*_ERROR_CODE` name under mcp/ and commit_binding. A code that is emitted and
# not registered has no kind and no honest default, so it fails here the day it lands.

_RETRY_WORDS = re.compile(r"retry|try again|system status|temporar", re.I)


def _emitted_error_codes() -> dict[str, list[str]]:
    """code -> the source sites that emit it, read out of the AST."""
    sites: dict[str, list[str]] = {}
    for path in _error_source_files():
        tree = ast.parse(path.read_text())
        rel = str(path.relative_to(REPO))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") in _ENVELOPE_BUILDERS:
                for kw in node.keywords:
                    if kw.arg == "error_code" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        sites.setdefault(kw.value.value, []).append(f"{rel}:{node.lineno}")
                if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                    sites.setdefault(node.args[1].value, []).append(f"{rel}:{node.lineno}")
            for name in _binding_targets(node):
                if name.endswith("_ERROR_CODE") and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    sites.setdefault(node.value.value, []).append(f"{rel}:{node.lineno} ({name})")
    return sites


def policy_retry_violations(kinds: dict[str, str], defaults: dict[str, list[str]]) -> list[str]:
    """Every (policy code, suggestion) pair that tells the caller to retry. Pure — the mutation
    control below feeds it a flipped table and must see it red."""
    out = []
    for code, kind in sorted(kinds.items()):
        if kind != "policy":
            continue
        texts = defaults.get(code)
        if not texts:
            out.append(f"{code}: a policy code with NO default suggestions — the fallback would be the transport advice")
            continue
        out += [f"{code}: {t!r}" for t in texts if _RETRY_WORDS.search(t)]
    return out


def test_every_emitted_error_code_is_registered_with_a_kind():
    from mcp.utils import ERROR_CODES, ERROR_KINDS, ERROR_KINDS_VALID

    emitted = _emitted_error_codes()
    assert {"REDTEAM_BINDING", "SUBTRACT_ONLY_VIOLATION", "CRITIC_VETO", "TOOL_CALL_RESIDUE", "INTERNAL"} <= set(emitted), sorted(emitted)
    assert len(emitted) >= 15, f"only {len(emitted)} emitted codes found — extractor broke"
    unregistered = {c: s for c, s in emitted.items() if c not in ERROR_CODES}
    assert not unregistered, "error codes emitted with no registry entry (so no kind, no honest default):\n  " + "\n  ".join(
        f"{c} <- {', '.join(s)}" for c, s in sorted(unregistered.items())
    )
    assert set(ERROR_KINDS) == set(ERROR_CODES)
    bad_kind = {c: k for c, k in ERROR_KINDS.items() if k not in ERROR_KINDS_VALID}
    assert not bad_kind, bad_kind


def test_every_registered_code_has_default_suggestions():
    """The unregistered-code fallback is for codes NOT in the table; a registered code always has its own."""
    from mcp.utils import _DEFAULT_SUGGESTIONS, ERROR_CODES

    missing = sorted(set(ERROR_CODES) - set(_DEFAULT_SUGGESTIONS))
    assert not missing, f"registered codes with no default suggestions: {missing}"
    assert sorted(set(_DEFAULT_SUGGESTIONS) - set(ERROR_CODES)) == [], "defaults for a code nobody registered"


def test_no_policy_code_is_told_to_retry():
    from mcp.utils import _DEFAULT_SUGGESTIONS, ERROR_KINDS

    policy = sorted(c for c, k in ERROR_KINDS.items() if k == "policy")
    assert {"REDTEAM_BINDING", "SUBTRACT_ONLY_VIOLATION", "CRITIC_VETO", "TOOL_CALL_RESIDUE"} <= set(policy), policy
    violations = policy_retry_violations(ERROR_KINDS, _DEFAULT_SUGGESTIONS)
    assert not violations, "policy refusals told to retry:\n  " + "\n  ".join(violations)


def test_mutation_a_policy_code_told_to_retry_is_caught():
    """Flip ONE policy code's suggestion to the old transport line — the check must name it."""
    from mcp.utils import _DEFAULT_SUGGESTIONS, ERROR_KINDS

    flipped = {**_DEFAULT_SUGGESTIONS, "REDTEAM_BINDING": ["Retry or check system status."]}
    out = policy_retry_violations(ERROR_KINDS, flipped)
    assert out == ["REDTEAM_BINDING: 'Retry or check system status.'"], out
    # and a transport code saying so is not a violation — the rule is about the KIND
    assert policy_retry_violations(ERROR_KINDS, {**_DEFAULT_SUGGESTIONS, "INTERNAL": ["Retry."]}) == []
    # and a policy code with no defaults at all is caught too (it would fall to the fallback)
    emptied = {k: v for k, v in _DEFAULT_SUGGESTIONS.items() if k != "CRITIC_VETO"}
    assert any(o.startswith("CRITIC_VETO: a policy code with NO default") for o in policy_retry_violations(ERROR_KINDS, emptied))


def test_the_envelope_carries_the_kind_and_an_unregistered_code_is_not_told_to_retry():
    from mcp.utils import mcp_error

    assert mcp_error("x", "REDTEAM_BINDING")["kind"] == "policy"
    assert mcp_error("x", "INTERNAL")["kind"] == "transport"
    assert mcp_error("x", "MISSING_ARG")["kind"] == "argument"
    unknown = mcp_error("x", "NEVER_REGISTERED")
    assert unknown["kind"] == "unregistered"
    assert not any(_RETRY_WORDS.search(t) for t in unknown["suggestions"]), unknown
    assert "NEVER_REGISTERED" in unknown["suggestions"][0]


def _tool_references(text: str, verbs: set[str], schema_args: set[str]) -> set[str]:
    """snake_case tokens in `text` that read as a tool name (verb prefix, not an argument)."""
    return {tok for tok in _SNAKE.findall(text) if tok.split("_", 1)[0] in verbs and tok not in schema_args}


def test_suggestion_extraction_is_not_vacuous():
    """The extractor must actually find suggestion strings — an empty set passes everything."""
    suggestions = _suggestion_strings()
    assert len(suggestions) >= 20, f"only {len(suggestions)} suggestion strings found — extractor broke"
    assert any("Split the request into smaller date windows" in s for _, _, s in suggestions)


def test_every_tool_named_in_a_suggestion_is_registered():
    names, verbs, schema_args = _registry()
    offenders = []
    for rel, lineno, text in _suggestion_strings():
        for ref in sorted(_tool_references(text, verbs, schema_args)):
            if ref not in names:
                offenders.append(f"{rel}:{lineno} names '{ref}', not in registry — {text!r}")
    assert not offenders, "MCP suggestions point at tools that do not exist:\n  " + "\n  ".join(offenders)


@pytest.mark.parametrize(
    "planted,expected",
    [
        ("Call get_data_freshness to check when this source last updated.", "get_data_freshness"),
        ("Use get_longitudinal_summary for multi-year overviews instead.", "get_longitudinal_summary"),
        ("Try list_everything_ever for a full dump.", "list_everything_ever"),
    ],
)
def test_extractor_catches_a_planted_bad_name(planted, expected):
    """Proof the guard is live: a fabricated tool name in a suggestion is flagged."""
    names, verbs, schema_args = _registry()
    refs = _tool_references(planted, verbs, schema_args)
    assert expected in refs, f"extractor missed {expected!r} in {planted!r}"
    assert expected not in names


def test_argument_names_are_not_mistaken_for_tools():
    """`end_date` shares a prefix with `end_experiment`; subtracting schema args is what saves it."""
    names, verbs, schema_args = _registry()
    text = "Use YYYY-MM-DD format for both start_date and end_date."
    assert _tool_references(text, verbs, schema_args) == set()
    assert "end" in verbs, "precondition: `end_experiment` makes `end` a tool verb"


def test_suggested_tools_are_importable_at_runtime():
    """Not just present in the AST — actually wired into the live TOOLS dict."""
    from mcp.registry import TOOLS
    from mcp.utils import _default_suggestions

    names, verbs, schema_args = _registry()
    for code in ("NO_DATA", "SOURCE_UNAVAIL", "PARTIAL_DATA", "QUERY_TOO_BROAD", "DATE_RANGE", "INTERNAL", "RATE_LIMIT", "MISSING_ARG"):
        for text in _default_suggestions(code):
            for ref in _tool_references(text, verbs, schema_args):
                assert ref in TOOLS, f"{code} suggests '{ref}', absent from the live TOOLS dict"
