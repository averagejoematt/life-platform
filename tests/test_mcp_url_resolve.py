"""SEC-02 (#780): the MCP Function URL is discovered at runtime, never committed.

`lambdas/mcp_url.resolve_mcp_url()` is the shared resolver the canary and qa-smoke
lambdas use instead of a hardcoded `MCP_FUNCTION_URL` env var (the URL is the
possession-based auth boundary and the repo is public). These tests pin its
contract without any AWS access.
"""

import importlib
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAMBDAS = os.path.join(REPO, "lambdas")
if LAMBDAS not in sys.path:
    sys.path.insert(0, LAMBDAS)


def _fresh_module():
    """Reimport with a clean module-level cache each time."""
    sys.modules.pop("mcp_url", None)
    return importlib.import_module("mcp_url")


def test_env_override_wins(monkeypatch):
    monkeypatch.setenv("MCP_FUNCTION_URL", "https://override.example.on.aws/")
    m = _fresh_module()
    assert m.resolve_mcp_url() == "https://override.example.on.aws/"


def test_discovers_via_lambda_api_and_caches(monkeypatch):
    monkeypatch.delenv("MCP_FUNCTION_URL", raising=False)
    m = _fresh_module()

    calls = {"n": 0}

    class FakeLambda:
        def get_function_url_config(self, FunctionName):
            calls["n"] += 1
            assert FunctionName == "life-platform-mcp"
            return {"FunctionUrl": "https://discovered.example.on.aws/"}

    monkeypatch.setattr("boto3.client", lambda *a, **k: FakeLambda())
    assert m.resolve_mcp_url() == "https://discovered.example.on.aws/"
    # Second call is served from the warm-container cache — no second API hit.
    assert m.resolve_mcp_url() == "https://discovered.example.on.aws/"
    assert calls["n"] == 1


def test_discovery_failure_returns_empty_not_raise(monkeypatch):
    monkeypatch.delenv("MCP_FUNCTION_URL", raising=False)
    m = _fresh_module()

    def boom(*a, **k):
        raise RuntimeError("AccessDenied")

    monkeypatch.setattr("boto3.client", boom)
    # Never raises — a discovery failure returns "" so the caller skips gracefully.
    assert m.resolve_mcp_url() == ""


def test_url_not_hardcoded_in_repo_source():
    """The rotated live host must never be committed again in tracked source/docs.

    The old host is dead post-rotation; this guards against re-introducing ANY
    concrete `*.lambda-url.*.on.aws` MCP host in the resolver itself.
    """
    src = open(os.path.join(LAMBDAS, "mcp_url.py")).read()
    assert ".lambda-url." not in src, "mcp_url.py must not hardcode a Function URL host"
