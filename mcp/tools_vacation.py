"""
tools_vacation.py — `get_vacation_fund` MCP tool.

Thin wrapper over the shared `vacation_fund.compute_vacation_fund` (layer module).
Read-only: totals workout miles since the experiment start date and converts to a
USD vacation fund ($1/mile by default). See lambdas/vacation_fund.py for the math
and config (config/vacation_fund.json).
"""
from __future__ import annotations

from typing import Any

from mcp.utils import mcp_error


def tool_get_vacation_fund(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the vacation-fund total: miles since experiment start -> USD.

    Args (all optional):
      start_date: ISO YYYY-MM-DD (default: experiment start, 2026-06-01)
      end_date:   ISO YYYY-MM-DD (default: today, Pacific)
    """
    args = args or {}
    try:
        from vacation_fund import compute_vacation_fund
        return compute_vacation_fund(
            start_date=args.get("start_date"),
            end_date=args.get("end_date"),
        )
    except Exception as e:  # noqa: BLE001
        return mcp_error(f"vacation fund compute failed: {e}", error_code="INTERNAL")
