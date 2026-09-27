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
import pathlib
import sys

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "deploy"))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

import doc_drift_verdict as _verdict  # noqa: E402 — #3984: the off-main predicate, imported not restated
import sync_doc_metadata as sync  # noqa: E402


def _assert_or_skip_off_main(field: str, actual) -> None:
    """#3984: every DISCOVERED field in PLATFORM_STATS is bot-owned (#3101) — a branch may not
    regenerate `lambdas/web/platform_counts.py`, so off main a stale literal is not this
    checkout's defect. Skip VISIBLY, naming both values; on main the equality is enforced."""
    literal = PLATFORM_STATS[field]
    if literal != actual and not _verdict._checked_out_ref_is_main():
        pytest.skip(f"#3984: {field} literal {literal} vs discovered {actual} — bot-owned (#3101), reconciled on main; main runs enforce")
    assert literal == actual, "run: python3 deploy/sync_doc_metadata.py --apply"


from web.site_api_common import PLATFORM_STATS  # noqa: E402


def test_mcp_tools_matches_registry():
    actual = sync._auto_discover_tool_count()
    assert actual is not None
    _assert_or_skip_off_main("mcp_tools", actual)


def test_adr_count_matches_decisions_doc():
    actual = sync._count_adrs()
    assert actual is not None
    _assert_or_skip_off_main("adrs", actual)


def test_test_count_matches_suite():
    """#4250: test_count is no longer a committed literal, so there is nothing to lag — in a
    checkout the reader derives it from tests/ live, and it must equal the sync's discoverer."""
    actual = sync._count_test_functions()
    assert actual is not None
    assert PLATFORM_STATS["test_count"] == actual


# ── #4250: the bundle stamp — the served test_count's only home in a deployed Lambda ──
import json  # noqa: E402

import build_bundle  # noqa: E402
from web import bundle_counts  # noqa: E402


def test_the_bundle_stamp_is_the_suite_count(tmp_path):
    build_bundle.stage_bundle_counts(str(tmp_path))
    stamp = json.loads((tmp_path / bundle_counts.BUNDLE_COUNTS_NAME).read_text(encoding="utf-8"))
    assert stamp == {"test_count": sync._count_test_functions()}, "the stamp and the sync disagree on what a test is"


def test_a_deployed_bundle_serves_the_stamp_not_a_recount(tmp_path):
    """A bundle root has no tests/ beside it; the stamp is the only source. A value the
    checkout could never produce proves the stamp — not a recount — is what is read."""
    root = tmp_path / "bundle"
    root.mkdir()
    (root / bundle_counts.BUNDLE_COUNTS_NAME).write_text('{"test_count": 7}', encoding="utf-8")
    assert bundle_counts.load_bundle_counts(str(root)) == {"test_count": 7}


@pytest.mark.parametrize("stamp", [None, "{not json", '{"test_count": 0}', '{"test_count": "24000"}', '{"test_count": true}', "[]"])
def test_no_valid_stamp_and_no_tests_dir_omits_the_key(tmp_path, stamp):
    """Absent beats remembered: with nothing to derive from, /api/platform_stats drops the key."""
    root = tmp_path / "bundle"
    root.mkdir()
    if stamp is not None:
        (root / bundle_counts.BUNDLE_COUNTS_NAME).write_text(stamp, encoding="utf-8")
    assert bundle_counts.load_bundle_counts(str(root)) == {}


def test_a_failed_count_stages_nothing_and_never_raises(tmp_path, capsys):
    empty_repo = tmp_path / "repo"
    (empty_repo / "lambdas" / "web").mkdir(parents=True)
    (empty_repo / "tests").mkdir()
    (empty_repo / "lambdas" / "web" / "bundle_counts.py").write_text(
        (pathlib.Path(_REPO) / "lambdas" / "web" / "bundle_counts.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    out = tmp_path / "out"
    out.mkdir()
    build_bundle.stage_bundle_counts(str(out), repo_root=str(empty_repo))
    assert not (out / bundle_counts.BUNDLE_COUNTS_NAME).exists()
    assert "not staged" in capsys.readouterr().err


def test_stage_tree_stamps_every_bundle():
    """The stamp rides the one staging path every deploy uses (#781) — not an optional extra."""
    import inspect

    assert "stage_bundle_counts(out_dir)" in inspect.getsource(build_bundle.stage_tree)


def test_lambda_count_matches_cdk():
    actual = sync._auto_discover_lambda_count()
    if actual is None:  # discoverer bails when stacks unreadable — nothing to pin
        return
    _assert_or_skip_off_main("lambdas", actual)


def test_alarm_count_matches_cdk():
    """#795: alarm_count is now AST-discovered from cdk/stacks/*.py, same as lambda_count —
    the doc-drift gate can finally catch it rotting instead of only catching a rewrite of
    itself. See sync._auto_discover_alarm_count docstring for the CDK-vs-live distinction."""
    actual = sync._auto_discover_alarm_count()
    assert actual is not None, "discoverer bailed (unreadable/suspiciously-low stack parse) — investigate before trusting a fallback"
    assert isinstance(actual, int) and actual > 0
    _assert_or_skip_off_main("alarms", actual)


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
    _assert_or_skip_off_main("cdk_stacks", actual)
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
    _assert_or_skip_off_main("alarms", facts["alarm_count"])
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
