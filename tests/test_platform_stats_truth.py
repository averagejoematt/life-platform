"""tests/test_platform_stats_truth.py — the served credibility numbers can't rot.

Replays the 2026-07-01 finding: /api/platform_stats (rendered on the /method/
credibility pages — the exact surface a skeptic cross-checks against the public
repo) served a hand-edited dict claiming 303 tests vs ~1,290 actual, 138 MCP tools
vs 144, 65 ADRs vs 85. Honesty is the moat; the credibility page can't be the one
incoherent surface. deploy/sync_doc_metadata.py --apply rewrites the discoverable
fields; this test reds CI whenever the served literal drifts from the discoverers.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "deploy"))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

import sync_doc_metadata as sync  # noqa: E402
from web.site_api_common import PLATFORM_STATS  # noqa: E402


def test_mcp_tools_matches_registry():
    actual = sync._auto_discover_tool_count()
    assert actual is not None
    assert PLATFORM_STATS["mcp_tools"] == actual, "run: python3 deploy/sync_doc_metadata.py --apply"


def test_adr_count_matches_decisions_doc():
    actual = sync._count_adrs()
    assert actual is not None
    assert PLATFORM_STATS["adrs"] == actual, "run: python3 deploy/sync_doc_metadata.py --apply"


def test_test_count_matches_suite():
    actual = sync._count_test_functions()
    assert actual is not None
    assert PLATFORM_STATS["test_count"] == actual, "run: python3 deploy/sync_doc_metadata.py --apply"


def test_lambda_count_matches_cdk():
    actual = sync._auto_discover_lambda_count()
    if actual is None:  # discoverer bails when stacks unreadable — nothing to pin
        return
    assert PLATFORM_STATS["lambdas"] == actual, "run: python3 deploy/sync_doc_metadata.py --apply"


def test_alarms_and_sources_share_the_maintained_fact():
    """One number, one home: the maintained PLATFORM_FACTS values are the source."""
    assert PLATFORM_STATS["alarms"] == sync.PLATFORM_FACTS["alarm_count"]
    assert PLATFORM_STATS["data_sources"] == sync.PLATFORM_FACTS["data_sources"]
