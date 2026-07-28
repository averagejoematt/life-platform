"""Resolve the MCP server's Lambda Function URL at runtime (SEC-02, #780).

The remote-MCP Function URL is the possession-based auth boundary (the repo is
public; committing the URL re-exposes it — the exact finding #780 fixed). So it
is NOT hardcoded in CDK env vars or docs anymore. Consumers that need to reach
the MCP endpoint (canary, qa-smoke) discover the live URL at runtime with
`lambda:GetFunctionUrlConfig` on the MCP function — self-healing across any
future URL rotation, nothing to re-commit or re-deploy.

An explicit `MCP_FUNCTION_URL` env var still wins if set (local/test override);
otherwise the URL is discovered once per warm container and cached.
"""

import logging
import os

logger = logging.getLogger()

MCP_FUNCTION_NAME = os.environ.get("MCP_FUNCTION_NAME", "life-platform-mcp")

_cached_url = None


def resolve_mcp_url():
    """Return the live MCP Function URL, or "" if it can't be resolved.

    Order: explicit env override → runtime discovery (cached) → "".
    Never raises — a discovery failure returns "" so the caller skips the MCP
    check gracefully (same contract the old empty-env-var path had).
    """
    global _cached_url

    env_override = os.environ.get("MCP_FUNCTION_URL", "")
    if env_override:
        return env_override

    if _cached_url is not None:
        return _cached_url

    try:
        import boto3

        client = boto3.client("lambda", region_name=os.environ.get("AWS_REGION", "us-west-2"))
        url = client.get_function_url_config(FunctionName=MCP_FUNCTION_NAME).get("FunctionUrl", "")
        _cached_url = url
        return url
    except Exception as e:  # pragma: no cover — network/IAM dependent
        logger.warning("resolve_mcp_url: could not discover MCP Function URL: %s", e)
        _cached_url = ""
        return ""
