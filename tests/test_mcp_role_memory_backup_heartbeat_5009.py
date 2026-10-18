"""tests/test_mcp_role_memory_backup_heartbeat_5009.py — #5009: the MCP role can read the
memory-backup heartbeat that `get_data_freshness` ages.

mcp/tools_labs.py runs operational.output_artifact_registry.check_all under the MCP
Lambda's role (role_policies_serve.mcp_server()). The s3:GetObject grant lived only on the
freshness-checker's role, so the MCP tool reported AccessDenied. The set, not the specimen:
EVERY registry key must be readable by the MCP role, and by exact key, never the prefix.
"""

from __future__ import annotations

import fnmatch
import sys
from pathlib import Path

import test_role_family_write_scope as family  # the stubbed role_policies* import (#2604-safe)

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))

from operational.output_artifact_registry import OUTPUT_ARTIFACTS  # noqa: E402


def _get_object_resources() -> list[str]:
    out: list[str] = []
    for s in family.policy_statements("mcp_server"):
        if "s3:GetObject" in getattr(s, "actions", []):
            out.extend(str(r) for r in getattr(s, "resources", []))
    assert out, "mcp_server() grants no s3:GetObject at all"
    return out


def test_every_output_artifact_key_is_readable_by_the_mcp_role():
    resources = _get_object_resources()
    missing = []
    for name, spec in OUTPUT_ARTIFACTS.items():
        arn_tail = f"{spec['bucket']}/{spec['key']}"
        if not any(fnmatch.fnmatch(f"arn:aws:s3:::{arn_tail}", r) for r in resources):
            missing.append(name)
    assert not missing, f"MCP role cannot GetObject the heartbeat of: {missing}"


def test_grant_is_the_exact_key_not_the_prefix():
    assert not any(r.rstrip("/").endswith("claude-memory-backup/*") for r in _get_object_resources())
