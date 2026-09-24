"""#4123 — a PR that adds an MCP tool can pass the required pre-merge job again.

Two contracts contradicted each other (PR #4119, 2026-09-23, `assert 84 == 85`):
`test_the_published_mcp_tool_count_matches_the_registry` asserted the bot-owned counter
in `lambdas/web/platform_counts.py` equals the registry's live TOOLS count, while the
#3984 hook restores that counter on every off-main commit — so no branch could ever carry
the value the test demanded. The ruling (the first of the issue's two options): the
pre-merge test compares against the registry count from the MERGE-BASE and treats
`published == registry − (tools added by this PR)` as pending-reconcile, the same off-main
`~` semantics the doc-literal check has had since #3984. The hook is untouched; the counter
keeps one writer (the reconcile job on main).

Properties, each with its can-it-fail control:

  1. the verdict table — success / pending-reconcile / failure — over (literal, discovered,
     merge-base discovered, ref), including the arm the skip-only shape lacks: a counter that
     matches NEITHER the registry NOR the merge-base is a failure off main too (hand-carried);
  2. `registry_tool_count` (text) agrees with `sync_doc_metadata._auto_discover_tool_count`
     (path) on the real registry — one discovery, two readers, no second number;
  3. the 84-vs-85 case reproduced through the REAL test as a subprocess: a synthetic tool
     appended to `mcp/registry.py`, ref pinned to a PR merge ref → SKIPPED naming #4123; the
     same tree pinned to `refs/heads/main` → FAILED (main runs still enforce). The reconcile
     writer sees the new count in the same window (property 2 on the mutated file).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

# #3025: this file rewrites the REAL mcp/registry.py for the subprocess case below and is
# registered in tests/test_suite_parallel_safety_3025.py::IN_TREE_WRITERS — serial, never
# alongside an rglob sweep under `pytest -n auto`.
pytestmark = pytest.mark.serial

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "deploy"))
import doc_drift_verdict as _verdict  # noqa: E402
import sync_doc_metadata as _sync  # noqa: E402

_REGISTRY = _REPO / "mcp" / "registry.py"
_STATUS_TEST = "tests/test_site_api_status_behavior.py"
_STATUS_CASE = "test_the_published_mcp_tool_count_matches_the_registry"


# ── 1. the verdict table ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "ref, literal, discovered, base, expected",
    [
        # equal everywhere → success, on every ref
        ("refs/heads/main", 84, 84, None, _verdict.VERDICT_SUCCESS),
        ("refs/pull/4119/merge", 84, 84, 84, _verdict.VERDICT_SUCCESS),
        # the #4119 shape: branch adds one tool, counter still equals main's registry → pending
        ("refs/pull/4119/merge", 84, 85, 84, _verdict.VERDICT_PENDING_RECONCILE),
        ("refs/heads/issue-4078-x", 84, 85, 84, _verdict.VERDICT_PENDING_RECONCILE),
        # a tool REMOVED on a branch is the same class
        ("refs/pull/1/merge", 84, 83, 84, _verdict.VERDICT_PENDING_RECONCILE),
        # shallow checkout, base unknowable → the #3984 skip, never a guess
        ("refs/pull/4119/merge", 84, 85, None, _verdict.VERDICT_PENDING_RECONCILE),
        # MUST-FAIL: same stale counter on main → failure (the strict half survives)
        ("refs/heads/main", 84, 85, 84, _verdict.VERDICT_FAILURE),
        ("refs/heads/main", 84, 85, None, _verdict.VERDICT_FAILURE),
        # MUST-FAIL: off main, counter matches neither the registry nor main's → hand-carried drift
        ("refs/pull/4119/merge", 83, 85, 84, _verdict.VERDICT_FAILURE),
        ("refs/pull/4119/merge", 85, 86, 84, _verdict.VERDICT_FAILURE),
    ],
)
def test_counter_verdict_table(monkeypatch, ref, literal, discovered, base, expected):
    monkeypatch.setenv("GITHUB_REF", ref)
    assert _verdict.bot_owned_counter_verdict(literal, discovered, base) == expected


def test_off_main_predicate_is_the_3984_one(monkeypatch):
    """The verdict reads the SAME ref predicate the doc-literal gate reads — a detached
    HEAD or an unanswerable git is MAIN (fail-closed to strict), not a free pass."""
    monkeypatch.delenv("GITHUB_REF", raising=False)
    monkeypatch.setattr(_verdict, "_checked_out_ref_is_main", lambda: True)
    assert _verdict.bot_owned_counter_verdict(84, 85, 84) == _verdict.VERDICT_FAILURE
    monkeypatch.setattr(_verdict, "_checked_out_ref_is_main", lambda: False)
    assert _verdict.bot_owned_counter_verdict(84, 85, 84) == _verdict.VERDICT_PENDING_RECONCILE


# ── 2. one discovery, two readers ───────────────────────────────────────────────────────


def test_text_discovery_agrees_with_the_writer_discovery():
    text_count = _verdict.registry_tool_count(_REGISTRY.read_text(encoding="utf-8"))
    path_count = _sync._auto_discover_tool_count()
    assert text_count is not None and path_count is not None
    assert text_count == path_count, "the pre-merge reader and the reconcile writer count the registry differently"


def test_text_discovery_returns_none_without_a_tools_dict_literal():
    assert _verdict.registry_tool_count("TOOLS = build()\n") is None
    assert _verdict.registry_tool_count("def f(:\n") is None
    assert _verdict.registry_tool_count('TOOLS = {\n    "a": {},\n    "b": {},\n}\n') == 2


def test_merge_base_text_is_none_when_git_cannot_answer(tmp_path):
    """A shallow CI checkout with no `origin/main` must yield None (→ the #3984 skip),
    never an exception and never a fabricated base."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    assert _verdict.merge_base_file_text("mcp/registry.py", cwd=str(tmp_path)) is None


# ── 3. the 84-vs-85 case through the REAL test ──────────────────────────────────────────

_SYNTHETIC_TOOL = (
    'TOOLS = {\n    "synthetic_tool_4123": {"description": "planted by tests/test_mcp_tool_count_pending_reconcile_4123.py",'
    ' "inputSchema": {"type": "object", "properties": {}}},\n'
)


def _run_status_case(ref: str) -> str:
    env = dict(os.environ, GITHUB_REF=ref)
    env.pop("GITHUB_EVENT_NAME", None)
    proc = subprocess.run(  # nosec B603 — fixed argv, our own test file
        [sys.executable, "-m", "pytest", _STATUS_TEST, "-k", _STATUS_CASE, "-q", "-rs", "-p", "no:cacheprovider"],
        cwd=str(_REPO),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    return proc.stdout + proc.stderr


@pytest.mark.skipif(
    _verdict.merge_base_file_text("mcp/registry.py", cwd=str(_REPO)) is None,
    reason="needs origin/main reachable to derive the merge-base registry count (shallow checkout)",
)
def test_a_synthetic_tool_on_a_branch_is_pending_reconcile_and_red_on_main():
    original = _REGISTRY.read_text(encoding="utf-8")
    assert original.count("TOOLS = {") == 1
    base_count = _verdict.registry_tool_count(original)
    mutated = original.replace("TOOLS = {\n", _SYNTHETIC_TOOL, 1)
    assert _verdict.registry_tool_count(mutated) == base_count + 1
    try:
        _REGISTRY.write_text(mutated, encoding="utf-8")
        # the reconcile writer reads the NEW count from the same tree — the counter it will
        # write on main after the merge is the registry's, not the branch's carried literal
        assert _sync._auto_discover_tool_count() == base_count + 1
        on_branch = _run_status_case("refs/pull/4119/merge")
        assert "1 skipped" in on_branch, on_branch
        assert "#4123" in on_branch, on_branch
        on_main = _run_status_case("refs/heads/main")
        assert "1 failed" in on_main, on_main
        # The PUBLISHED literal, not the branch registry's count: on a branch that itself adds a
        # tool (#4082) the two differ until the reconcile job runs on main, and this case is
        # about the synthetic tool, not the branch's own.
        import re

        literal = int(re.search(r'"mcp_tools":\s*(\d+)', (_REPO / "lambdas" / "web" / "platform_counts.py").read_text()).group(1))
        assert f"literal {literal} != registry {base_count + 1}" in on_main, on_main
    finally:
        _REGISTRY.write_text(original, encoding="utf-8")
    assert _REGISTRY.read_text(encoding="utf-8") == original
