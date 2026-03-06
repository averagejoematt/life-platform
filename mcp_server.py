"""
life-platform MCP Server — thin entry point.
The actual implementation lives in the mcp/ package.
Handler: mcp_server.lambda_handler (unchanged from original).
"""
from mcp.handler import lambda_handler  # noqa: F401
