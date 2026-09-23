"""Stamp a stage-2 verdict + its #4066 binding onto an IR, for commit tests about OTHER contracts.

Since #4066 a commit refuses any routine that is not the one stage 2 verdicted. Tests that
exercise foldering, orphan recovery, the subtract-only gate etc. are not about that binding,
so they pass through it the only honest way: a verdict record carrying the PRODUCTION
`binding_for(ir)` over the very IR they commit. The binding itself is tested in
tests/test_commit_binding_and_back_offs_4065_4066.py.
"""

from __future__ import annotations

from typing import Any

from mcp.hevy_commit_binding import binding_for


def bind(ir: Any) -> Any:
    rec = {
        "engine": "critics@test",
        "ran_at": "2026-09-22T00:00:00+00:00",
        "verdicts": [{"critic": c, "verdict": "approve", "reason": "fixture"} for c in ("muscle_defense", "joints_tendons")],
        "changes": [],
    }
    ir.inputs_snapshot = {**(getattr(ir, "inputs_snapshot", None) or {}), "critics": rec}
    rec["binding"] = binding_for(ir)
    return ir
