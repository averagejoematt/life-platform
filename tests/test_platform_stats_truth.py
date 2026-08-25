"""tests/test_platform_stats_truth.py — the served credibility numbers can't rot.

Replays the 2026-07-01 finding: /api/platform_stats (rendered on the /method/
credibility pages — the exact surface a skeptic cross-checks against the public
repo) served a hand-edited dict claiming 303 tests vs ~1,290 actual, 138 MCP tools
vs 144, 65 ADRs vs 85. Honesty is the moat; the credibility page can't be the one
incoherent surface. deploy/sync_doc_metadata.py --apply rewrites the discoverable
fields; this test reds CI whenever the served literal drifts from the discoverers.
"""

import glob
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


def test_alarm_count_matches_cdk():
    """#795: alarm_count is now AST-discovered from cdk/stacks/*.py, same as lambda_count —
    the doc-drift gate can finally catch it rotting instead of only catching a rewrite of
    itself. See sync._auto_discover_alarm_count docstring for the CDK-vs-live distinction."""
    actual = sync._auto_discover_alarm_count()
    assert actual is not None, "discoverer bailed (unreadable/suspiciously-low stack parse) — investigate before trusting a fallback"
    assert isinstance(actual, int) and actual > 0
    assert PLATFORM_STATS["alarms"] == actual, "run: python3 deploy/sync_doc_metadata.py --apply"


def test_cdk_stacks_matches_glob():
    """#3143: cdk_stacks used to be a hand-maintained literal in PLATFORM_STATS and
    it drifted (8 vs the real 10, missing the #793 serve split + DIL-027 backup
    stack). Two independent checks, so a mutation survives even if the discoverer
    itself were broken:
      1. the served value matches sync's own discoverer (the wiring didn't rot);
      2. the served value matches a FRESH glob computed right here, independent of
         any sync_doc_metadata internals — proving PLATFORM_STATS["cdk_stacks"]
         is not just a hardcoded int that happens to equal the discoverer's output.
    """
    actual = sync._auto_discover_cdk_stack_count()
    assert actual is not None
    assert PLATFORM_STATS["cdk_stacks"] == actual, "run: python3 deploy/sync_doc_metadata.py --apply"
    stacks_dir = os.path.join(_REPO, "cdk", "stacks")
    fresh_glob_count = len(glob.glob(os.path.join(stacks_dir, "*_stack.py")))
    assert fresh_glob_count >= 5, "sanity: too few *_stack.py files found — check the glob path"
    assert PLATFORM_STATS["cdk_stacks"] == fresh_glob_count, (
        f"PLATFORM_STATS['cdk_stacks'] ({PLATFORM_STATS['cdk_stacks']}) does not match a live "
        f"glob of cdk/stacks/*_stack.py ({fresh_glob_count}) — it may have regressed to a planted literal"
    )


def test_alarms_and_sources_share_the_maintained_fact():
    """One number, one home — DISCOVERY-first (#1327).

    The old form compared PLATFORM_STATS against the raw PLATFORM_FACTS hand
    literals, so every alarm-count change needed a manual fallback-literal bump
    in sync_doc_metadata.py or main went red (`assert 69 == 67` on 2026-07-18,
    the third instance of the class in one week). The shared source of truth is
    the DISCOVERED value; the literal is only the fallback when discovery bails.
    """
    facts = sync._apply_auto_discovered(dict(sync.PLATFORM_FACTS))
    assert PLATFORM_STATS["alarms"] == facts["alarm_count"], "run: python3 deploy/sync_doc_metadata.py --apply"
    # data_sources has no auto-discoverer (the public count is curated) — the
    # literal comparison stands, and the fact moves ~never.
    assert PLATFORM_STATS["data_sources"] == facts["data_sources"]
    # Fallback hygiene: the hand literal only matters when discovery bails, but a
    # far-drifted fallback would then quietly resurrect an old number. ±5 keeps
    # it near truth without demanding a bump on every alarm PR (the exact class
    # that redded main).
    assert abs(sync.PLATFORM_FACTS["alarm_count"] - facts["alarm_count"]) <= 5, (
        f"PLATFORM_FACTS alarm_count fallback ({sync.PLATFORM_FACTS['alarm_count']}) has drifted "
        f">5 from discovery ({facts['alarm_count']}) — refresh the fallback literal"
    )
