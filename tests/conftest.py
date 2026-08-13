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

# ── #2370: neutral blocked-category vocabulary for the whole unit suite ────────
# The real vocabulary lives ONLY in the ER-06 non-committed channel (env
# CONTENT_FILTER_JSON / config/content_filter.local.json / private S3) — this
# repo is PUBLIC, so no test may carry the actual category names as literals.
# The suite runs against this NEUTRAL fixture vocabulary instead, injected at
# import time (same reasoning as the fake AWS creds above: channel consumers may
# resolve at collection). It is FORCED (not setdefault) so the unit suite is
# deterministic even when the real CI secret is present; the pre-existing value
# is preserved for the few tests that deliberately scan real artifacts with the
# real vocabulary (tests/test_public_surface_pii_guard.py).
# Term design: two long terms (>= 7 normalized chars — exercises the obfuscation
# fail-safe layer in site_api_common._scrub_blocked_terms) + one short term
# (< 7 — exercises the literal-pass-only residual).
import json as _json  # noqa: E402

REAL_CONTENT_FILTER_ENV = os.environ.get("CONTENT_FILTER_JSON")
NEUTRAL_CONTENT_FILTER = {
    "blocked_vices": ["No fizzlewick", "No grumbleflax"],
    "blocked_vice_keywords": ["fizzlewick", "grumbleflax", "zzq"],
}
os.environ["CONTENT_FILTER_JSON"] = _json.dumps(NEUTRAL_CONTENT_FILTER)


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
# `*_behavior.py` there is no filename or marker they share that a new one would inherit.
# What makes the hand-list safe is that it cannot rot silently —
# tests/test_premerge_lane.py asserts every path here exists and that the set only ever
# grows. The marker is the ONE selection mechanism both lanes name, so the workflow never
# needs a matching edit when this list changes.
#
# THE LIST STARTED AT FIVE AND THAT WAS DEMONSTRABLY TOO NARROW. Hours after the first
# five landed, #2339 red-mained main on `test_time_invariant_helpers_1964.py` — a ratchet
# of exactly this shape that nobody had thought to include. Deriving the real population
# (test files that sweep the source tree via `git ls-files`/`os.walk`, excluding the
# behaviour suite) found **20**. Eighteen of them are listed below; measured together they
# are **223 tests in 14.4s**, which is affordable against a lane budget of ten minutes.
#
# The two deliberately left out are `test_output_writers.py` (109 tests) and
# `test_diary_publish_1845.py` (63) — they sweep the tree but are behaviour suites in
# substance, not repo-shape ratchets, so they belong to the post-merge lane's job.
#
# The generalisable lesson, worth more than the list: **a guard whose verdict depends only
# on the repo tree has no business running after the merge.** When you add one, add it
# here in the same PR.
_PREMERGE_EXTRA_FILES = frozenset(
    {
        # ── size + type ceilings ──────────────────────────────────────────────
        "test_lambda_size_gate.py",  # ADR-080: *_lambda.py over 2,000 lines
        "test_module_size_guard.py",  # #1665: the 1,200-line ceiling + the BASELINE ratchet
        "test_mypy_clean_modules.py",  # tier-2 types (real only when mypy is installed — the lane installs it)
        "test_handler_type_hints.py",
        # ── registries a new module must join (none discoverable from the module) ──
        "test_phase_context_coverage.py",  # the phase-context census
        "test_grounding_wiring_1967.py",  # the grounding-surface registry
        "test_chat_behavioral_gate_2564.py",  # #2564: every build_grounder call site supplies available_logs
        "test_observatory_summary_grounding_2418.py",  # same registry, derived-prose surface (#2418)
        "test_api_schema_completeness.py",
        "test_vlog_mode_contract_1571.py",  # #1571: prose mode file <-> TEMPLATE_SK / date-key / abort semantics
        "test_og_card_coverage.py",
        "test_hae_datatype_liveness_468.py",
        "test_restart_pipeline_hooks.py",
        # ── one-idiom ratchets: the fork is invisible until someone edits one copy ──
        "test_time_invariant_helpers_1964.py",  # the #2339 red that widened this whole list
        "test_wallclock_globals_2223.py",  # 2026-08-10: #2472's own fix reddened main on this post-merge-only guard
        "test_singleton_tombstone_guards.py",  # 2026-08-10: Wave-2 call sites + Wave-3 exemptions split across PRs = main red between them
        "test_wallclock_fixture_bombs_2376.py",  # #2376: dated fixture + unfrozen handler clock (the #2354 midnight red)
        "test_raw_key_registry_guard.py",  # #2286: no hand-built raw/ S3 keys
        "test_no_hardcoded_feature_tier.py",
        "test_budget_guard_ladder.py",
        # ── tree hygiene + safety sweeps ──────────────────────────────────────
        "test_lambdas_packaging_guard.py",  # ADR-146: no loose modules at the lambdas/ root
        "test_root_clutter_guard.py",
        "test_no_conflict_markers.py",  # a merge marker reached main once already
        "test_no_dead_intelligence_functions.py",
        "test_hevy_compiler_isolation.py",
        "test_public_surface_pii_guard.py",  # privacy — the one most costly to catch late
        # #2587: the recall-corpus consent gate. Two of its assertions are pure repo-shape —
        # the writer set (every file calling `make_embedding_item` must also call the consent
        # gate) is a `os.walk` sweep, and the kind registries are derived from
        # `semantic_recall.KINDS` so a new corpus kind reds until someone classifies it. Both
        # are exactly the "invisible until someone adds a file" shape this list exists for,
        # and this one stands between a new kind/writer and an unreviewed privacy exposure.
        "test_recall_consent_2587.py",
        "test_coach_his_people_2488.py",  # #2488: the his-people sk must stay unreachable from the whole coach perimeter
        "test_leak_token_sweep.py",
        # #2578: the gate census. Its verdict is a sweep of the whole repo tree (CI
        # workflows, guard entrypoints, registries, qa-smoke checks) and its floors
        # are blindness detectors — a derivation that returns [] must red BEFORE the
        # merge, not after, which is the entire point of this list.
        "test_gate_census_2578.py",
        "test_csp_native_embeds_1678.py",
        "test_archive_handover.py",  # a dated handover committed to main (#1650)
        # #2570: the CQ-01 pin guard stopped hand-listing the workflow files and now
        # derives its declaration surface from `git ls-files` (the Makefile's stale
        # black/ruff/mypy pins were invisible to the hand-list). That makes it a
        # repo-shape ratchet: a new file declaring a pin must be caught pre-merge.
        "test_ci_pin_consistency.py",
        # ── #2372: the hand-list becomes a derivation — every file
        # tests/premerge_derivation.py finds below, classified in this same PR ──
        "test_blocked_vice_screen_set_2212.py",
        "test_board_lead_single_character.py",
        "test_cast_roster_consistency.py",
        "test_coach_ensemble_writer_phase_stamp_guard_2119.py",
        "test_coach_roster_set_guard_2334.py",
        "test_ddb_key_contracts.py",
        "test_ddb_patterns.py",
        "test_design_sync_bundle.py",
        "test_ensemble_digest_fallback_reader_set_2333.py",
        "test_experiment_surface_vice_screen_2240.py",
        "test_food_delivery_gate_2209.py",
        "test_food_delivery_gate_2233.py",
        "test_food_delivery_streak_freshness_2235.py",
        "test_gradability_liveness_cross_phase_2023.py",
        "test_intake_privacy_contract.py",
        "test_invoke_site_census_2390.py",
        "test_iso_week_pairing_2256.py",
        "test_lambda_handlers.py",
        "test_lambda_map_imports.py",
        "test_legacy_real_person_attributions_1905.py",
        "test_milestone_ledger_1626.py",
        "test_pacific_today_guard_2414.py",
        "test_pii_log_guard_2369.py",
        "test_qa_smoke_fault_isolation_2307.py",
        "test_secret_references.py",
        "test_ses_send_guard_set_2222.py",
        "test_site_chrome.py",
        "test_site_orphans.py",
        "test_site_partition_orphans.py",
        "test_tier0_streak_writer_2242.py",
        "test_timezone_discipline.py",
        "test_todoist_reader_writer_contract.py",
        "test_wayfinding.py",
        "test_wiring_coverage.py",
        "test_xfail_hygiene.py",
        # the derivation guard itself — its own docstring/synthetic-fixture text
        # mentions the three sweep idioms, so it self-matches; it belongs pre-merge
        # regardless (it IS the structural gate this whole entry is about).
        "test_premerge_extra_files_derivation_2372.py",
    }
)

# THE OTHER HALF OF THE #2372 DERIVATION — named, checked exclusions.
#
# tests/premerge_derivation.discover_tree_sweeping_test_files() is a SYNTACTIC
# detector: it flags any non-behaviour test_*.py file that sweeps a directory tree,
# regardless of WHY. Some of what it flags is a behaviour suite in substance, not a
# repo-shape ratchet — #2345 already made this call, in prose, for the two files
# below; this dict makes it a maintained, checked fact instead of a comment nobody
# re-reads. tests/test_premerge_extra_files_derivation_2372.py requires every name
# the detector returns to be in EITHER this dict or _PREMERGE_EXTRA_FILES above —
# so a new exclusion still has to be a deliberate, reasoned decision, not silence.
_PREMERGE_TREE_SWEEP_EXCLUDED = {
    "test_diary_publish_1845.py": (
        "behaviour suite over diary-publishing semantics (63 tests), not a repo-shape " "ratchet — #2345's own call, made explicit here"
    ),
}


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
