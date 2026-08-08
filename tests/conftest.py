"""
tests/conftest.py — global pytest path setup.

Added 2026-05-25 (P3.1): when lambdas/ was reorganized into subpackages
(ingestion/, compute/, coach/, email/, web/, operational/, intelligence/),
existing tests that did `import whoop_lambda` directly broke. This conftest
adds each subpackage to sys.path so flat-name imports continue to work.

Tests that use the standard `sys.path.insert(0, "../lambdas")` pattern
get both the lambdas/ root (for shared-layer modules) AND each subpackage
visible. New tests can prefer `from ingestion.whoop_lambda import ...` but
legacy `import whoop_lambda` still resolves.
"""

import os
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LAMBDAS = os.path.join(_REPO, "lambdas")

# lambdas/ root — shared-layer modules + cross-pkg helpers (constants, retry_utils, etc.)
sys.path.insert(0, _LAMBDAS)

# Each subpackage — so flat-name handler imports work
for _sp in ("ingestion", "compute", "coach", "emails", "web", "operational", "intelligence"):
    _path = os.path.join(_LAMBDAS, _sp)
    if os.path.isdir(_path):
        sys.path.insert(0, _path)

# ADR-104: keep the unit suite hermetic — ai_output_validator's health_context
# autoload would otherwise perform a real DynamoDB read when local creds exist.
os.environ.setdefault("AI_VALIDATOR_AUTOLOAD", "off")

# #1178: keep the unit suite hermetic — the podcast zeitgeist fetch would
# otherwise hit live BBC RSS feeds from any test that drives _run_intro/_run_weekly.
# Tests that exercise the fetch itself set PANELCAST_ZEITGEIST=on and mock urlopen.
os.environ.setdefault("PANELCAST_ZEITGEIST", "off")


# #381: make the unit suite hermetic regardless of the developer's local
# ~/.aws profile. Several nominally-offline tests (e.g. tests/test_coaches_api.py)
# depend on real AWS calls *failing* so the code under test falls through to its
# offline/shaped-empty path — that's exactly what happens in CI, whose "Unit
# Tests" job never configures AWS credentials at all, so boto3 raises
# NoCredentialsError before any network call. On a developer machine with a
# real ~/.aws/credentials file, those same calls silently succeed against
# live AWS instead, producing real data and failing the offline assumption
# (four tests in test_coaches_api.py, 2026-07-03).
#
# Tests that intentionally exercise live AWS are marked `@pytest.mark.integration`
# (see pytest.ini) and are exempted below.
_REAL_AWS_ENV = {
    key: os.environ.get(key)
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_SECURITY_TOKEN", "AWS_PROFILE")
}
_FAKE_AWS_ENV = {
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SESSION_TOKEN": "testing",
    "AWS_SECURITY_TOKEN": "testing",
    "AWS_DEFAULT_REGION": "us-west-2",
    "AWS_REGION": "us-west-2",
}

# Force the fakes on at *import* time (i.e. collection), not just per-test setup.
# Several production modules build a boto3 client at their own module level
# (e.g. lambdas/web/site_api_coach.py: `_S3 = boto3.client("s3", ...)`), and those
# modules get imported the moment a test file does `from web import site_api_coach`
# during collection — before any per-test fixture has run. boto3 resolves and
# caches credentials on its shared default Session the first time any client is
# built, and that cache is NOT re-read from the environment afterward — so a
# per-test-only override would arrive too late for any module-level client that
# collection already constructed with real creds. Setting the fakes here, before
# pytest imports any test (or the production code it pulls in), keeps every
# module-level client hermetic too.
os.environ.pop("AWS_PROFILE", None)
os.environ.update(_FAKE_AWS_ENV)


@pytest.fixture(autouse=True)
def _hermetic_aws_credentials(request, monkeypatch):
    """Keep the unit suite hermetic (#381).

    Fake credentials are already active process-wide (see module-level override
    above), which is correct for the overwhelming majority of tests: any boto3
    call must fail with a ClientError/NoCredentials-style exception exactly as it
    does in CI, so code under test exercises the same offline fallback path
    regardless of the developer's local ~/.aws profile.

    Tests marked `@pytest.mark.integration` are the deliberate exception — they
    exist specifically to call live AWS. For those, restore the developer's real
    ambient credentials (if any) for the duration of the test. Restoring the env
    vars alone isn't enough: boto3 caches resolved credentials on its shared
    default Session the first time a client is built (which may have already
    happened with the fakes above, earlier in this same run), so also drop that
    cached session for the test to force a fresh credential resolution — and
    again on the way out, so the fakes are what the *next* (non-integration)
    test's first client build sees.
    """
    if request.node.get_closest_marker("integration") is None:
        yield
        return

    import boto3

    for key, value in _REAL_AWS_ENV.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    monkeypatch.setattr(boto3, "DEFAULT_SESSION", None)
    yield
    boto3.DEFAULT_SESSION = None


# ══════════════════════════════════════════════════════════════════════════════
# THE `premerge` MARKER  (#2258)
# ══════════════════════════════════════════════════════════════════════════════
# WHY. The pre-merge lane (pr-checks.yml) was a STRICT SUBSET of the post-merge
# lane (ci-test.yml): pre-merge ran `--collect-only` plus the `deploy_critical`
# marker subset, and ZERO `tests/*_behavior.py` tests carry that marker. So a PR
# could be green pre-merge and red main the moment it landed. That gap red-mained
# main THREE times in 24h on 2026-08-08 — once on an undeclared PyYAML dep, then
# twice on the same collision shape: one PR's coverage tranche pins current
# behaviour while a sibling PR's privacy gate turns that behaviour off. Each PR is
# genuinely green alone; only their union is red, and only the post-merge lane
# ever saw the union.
#
# The behaviour suite is what catches that class, and it is affordable: 34 files /
# ~4,600 tests / ~22s locally (measured 2026-08-08), against a lane that took 117s
# with a 10-minute timeout.
#
# DERIVED, NOT HAND-LISTED. Marking 34 files by hand would rot the moment someone
# adds the 35th. This hook keys on the filename, so a new `*_behavior.py` joins the
# pre-merge lane automatically — and `tests/test_premerge_lane.py` asserts both
# workflows reference this one marker, so the two lanes cannot drift apart again.
_PREMERGE_FILENAME_SUFFIX = "_behavior.py"

# THE THIRD SOURCE — the structural gates that only ever ran AFTER merge (2026-08-09).
#
# #2258 closed the *behaviour* half of the pre-merge gap. The other half stayed open:
# main went red four more times in one session, and every one was a repo-shape gate that
# no PR check runs — a module crossing a size ceiling, and a new module that has to join
# a registry nothing points at from the module itself. Each red cost 20–70 minutes of
# driver time, and each was knowable from the PR's own diff.
#
# These are hand-listed on purpose, and that is the honest weak point: unlike
# `*_behavior.py` there is no filename or marker these five share that a sixth would
# inherit. What makes the hand-list safe is that it cannot rot silently —
# tests/test_premerge_lane.py asserts every path here exists AND that the set covers
# every guard whose failure is a pure function of the repo tree (see
# `test_the_structural_gates_run_pre_merge`). Add to it whenever a new gate of that
# shape lands; the marker is the ONE selection mechanism both lanes name, so the
# workflow never needs a matching edit.
_PREMERGE_EXTRA_FILES = frozenset(
    {
        "test_lambda_size_gate.py",  # ADR-080: *_lambda.py over 2,000 lines
        "test_module_size_guard.py",  # #1665: the 1,200-line ceiling + the BASELINE ratchet
        "test_phase_context_coverage.py",  # the phase-context census a new module must join
        "test_grounding_wiring_1967.py",  # the grounding-surface registry, likewise
        "test_mypy_clean_modules.py",  # tier-2 types (real only when mypy is installed — the lane installs it)
    }
)


def pytest_collection_modifyitems(config, items):
    """Auto-apply `premerge` to the behaviour suite + deploy-critical + the structural gates.

    Three sources, one marker:
      - any test in a `tests/*_behavior.py` file (the union-breach detector),
      - any test already marked `deploy_critical` (ADR-117's deploy-gating subset),
        so the pre-merge lane is a strict SUPERSET of what it checked before rather
        than a swap, and
      - the `_PREMERGE_EXTRA_FILES` structural gates, whose verdict depends only on the
        repo tree and which previously ran nowhere until after a merge.
    """
    for item in items:
        name = os.path.basename(str(getattr(item, "fspath", "")))
        if name.endswith(_PREMERGE_FILENAME_SUFFIX) or name in _PREMERGE_EXTRA_FILES or item.get_closest_marker("deploy_critical"):
            item.add_marker(pytest.mark.premerge)
