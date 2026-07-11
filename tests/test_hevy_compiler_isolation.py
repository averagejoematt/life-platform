"""tests/test_hevy_compiler_isolation.py — Hevy wire format must live in one file.

If a future agent inlines `exercise_template_id` somewhere else, a Hevy v2
spec change would require multi-file edits. This guard keeps Elena's
"API change touches one file" invariant honest.
"""

from __future__ import annotations

import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Modules permitted to know the Hevy wire schema. Everyone else is hands-off.
_ALLOWED_FILES = {
    os.path.join(ROOT, "lambdas", "hevy_compiler.py"),
    os.path.join(ROOT, "lambdas", "hevy_write_client.py"),
    # tests + the compiler-isolation test itself reference the key intentionally
    os.path.join(ROOT, "tests", "test_hevy_compiler.py"),
    os.path.join(ROOT, "tests", "test_hevy_compiler_isolation.py"),
    os.path.join(ROOT, "tests", "test_hevy_write_client.py"),
    os.path.join(ROOT, "tests", "test_adherence_calc.py"),
    os.path.join(ROOT, "tests", "test_hevy_adherence_wiring.py"),
    # #417 2b end-to-end restamp test asserts on the compiled wire body's
    # exercise_template_id to prove the recommended-branch push actually works.
    os.path.join(ROOT, "tests", "test_hevy_restamp.py"),
    os.path.join(ROOT, "tests", "test_tools_hevy_routine.py"),
    # adherence_calc reads template ids from Hevy responses — read-only, allowed.
    os.path.join(ROOT, "lambdas", "adherence_calc.py"),
    # MCP tool delegates to compiler; it only PASSES the IR through, doesn't
    # construct wire bodies. Still excluded from the scan because a key match
    # is acceptable in a docstring there.
    os.path.join(ROOT, "mcp", "tools_hevy_routine.py"),
    # Pre-existing read-side helper (SPEC_HEVY_AND_NUTRITION_BRIDGE 2026-05-25)
    # that normalizes inbound Hevy workout payloads — a different concern from
    # the routine-write schema this isolation rule guards. Grandfathered.
    os.path.join(ROOT, "lambdas", "hevy_common.py"),
    os.path.join(ROOT, "tests", "test_hevy_common.py"),
}

_KEY = "exercise_template_id"

# ".claude" — concurrent-agent worktrees under .claude/worktrees/ are full repo
# checkouts whose lambdas/hevy_compiler.py copies are NOT in _ALLOWED_FILES (the
# set holds absolute main-tree paths), so a live worktree redded the suite on
# main in 2 of 4 sessions (#953). "cdk.out" — synth output can land at repo root.
_SKIP_DIRS = {".git", ".claude", "__pycache__", "cdk", "cdk.out", "deploy", "docs", "site", "node_modules"}


def _iter_py_files():
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for fn in files:
            if fn.endswith(".py"):
                yield os.path.join(root, fn)


def test_exercise_template_id_only_in_allowed_files():
    offenders: list[str] = []
    for path in _iter_py_files():
        if path in _ALLOWED_FILES:
            continue
        with open(path, encoding="utf-8") as f:
            src = f.read()
        if re.search(rf'["\']?{_KEY}["\']?', src):
            offenders.append(os.path.relpath(path, ROOT))
    assert not offenders, (
        f"{_KEY} found outside the compiler/client. "
        f"Move Hevy schema knowledge into hevy_compiler.py. "
        f"Offenders:\n  - " + "\n  - ".join(offenders)
    )
