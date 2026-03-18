"""
life-platform MCP Server — thin entry point.
The actual implementation lives in the mcp/ package.
Handler: mcp_server.lambda_handler (unchanged from original).

Why the explicit def instead of `from mcp.handler import lambda_handler`:
  CI linters (test_lambda_handlers I6, test_cdk_handler_consistency H4) require
  a def lambda_handler to be present in the entry-point file so static analysis
  can confirm the handler contract without importing mcp dependencies.
"""
from mcp.handler import lambda_handler as _handler


def lambda_handler(event, context):
    """MCP server Lambda entry point — delegates to mcp.handler."""
    try:
        return _handler(event, context)
    except Exception:
        raise
