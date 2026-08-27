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

# #3044: keep the unit suite hermetic — signed-unsubscribe-link minting resolves its
# HMAC key env-first (common.unsubscribe_token.get_unsub_secret). Without this, every
# sender test that builds a subscriber email would attempt a real Secrets Manager
# round-trip (with the fake creds below) and degrade to the /privacy/ fallback link.
os.environ.setdefault("UNSUB_TOKEN_SECRET", "test-unsub-signing-key")


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
# THAT AFFORDABILITY NUMBER HAS MOVED — re-measure it, never quote it (#2924,
# 2026-08-21): the whole `premerge` selection is now 8,813 tests in 155s locally,
# not the ~6,075-in-30s this comment block used to claim further down. Still ~26%
# of the 10-minute budget, so the posture holds; but the next person to add a slow
# file should measure, not trust a number a previous session stamped and left.
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
        "test_rate_limit_identity_1221.py",  # #1221: AST sweep — no handler may derive its own client identity
        "test_no_tool_attribution_3005.py",  # #3005: git ls-files sweep — no tracked file may instruct the banned trailer
        "test_no_private_markers_3043.py",  # #3043: git ls-files sweep — no tracked file may carry the PRIVATE marker
        "test_phase_context_coverage.py",  # the phase-context census
        "test_grounding_wiring_1967.py",  # the grounding-surface registry
        "test_privacy_tier_wiring_2803.py",  # #2803: the Tier-2 consumer registry — a new module touching an owner-only field must red BEFORE merge, not after
        # #2986: the derived-artifact registry. Verdict is pure repo shape — a new
        # generator writing a committed artifact must be classified BEFORE the merge,
        # and a guard placed in the wrong lane must red on the PR that placed it there.
        # Post-merge-only is the exact defect this registry was filed about.
        "test_derived_artifact_registry_2986.py",
        # #2846: enrollment by construction. Verdict is pure repo shape — a Lambda
        # constructed outside create_platform_lambda(), or landing with no deploy
        # registration and no alarm story, must red BEFORE the merge. Post-merge is
        # too late by construction: the next `cdk deploy` puts the unenrolled,
        # unwatched function in production.
        "test_enrollment_by_construction_2846.py",
        # #3042 (Phase D2): the public-claims registry. Verdict is repo shape + published
        # prose — a new page or generator restating a registered behavioural claim must be
        # registered BEFORE the merge. Post-merge is too late by construction: the site
        # auto-deploys on merge, so an unregistered stale claim is live before the red.
        "test_public_claims_registry_3042.py",
        "test_chat_behavioral_gate_2564.py",  # #2564: every build_grounder call site supplies available_logs
        "test_observatory_summary_grounding_2418.py",  # same registry, derived-prose surface (#2418)
        "test_coach_identity_drift_2757.py",  # #2757: AST sweep — no lambda module may hand-type a persona title/color map
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
        "test_site_api_namespace_guard_3002.py",  # #3002: one site-API metric namespace, no casing twins — repo-shape sweep, pre-merge
        "test_emf_namespace_ledger_2837.py",  # #2837: AST sweep of every metric emitter — a NEW namespace must join the ledger BEFORE merge, not after the bill
        "test_unsubscribe_token_3044.py",  # #3044: tree sweep — no lambdas/deploy module may reintroduce a plaintext-email unsubscribe link
        "test_operating_calendar_2832.py",  # #2832: calendar registry + set guard sweeps .claude/commands + docs/reviews — repo-shape, pre-merge
        "test_full_suite_premerge_3025.py",  # #3025: lane-parity contracts sweep two workflow files — repo-shape, pre-merge
        # #2986/#2838: the generic re-stamp rule, derived from sync_doc_metadata.RULES. Its
        # verdict is pure repo shape (0.5s), and the change that can break it — a new stamped
        # literal, or an edit to deploy/sync_doc_metadata.py — is exactly a PR's own diff, so
        # putting it post-merge would repeat this epic's own "model-guard-post-merge-only" fold.
        "test_doc_restamp_rule_2986.py",
        "test_budget_guard_fail_closed_2824.py",  # #2824: os.walk sweep — no lambdas/mcp module may re-declare FAIL_CLOSED_FEATURES; membership lives in budget_guard alone
        "test_csp_hardening_3048.py",  # #3048: site/ tree sweep — no non-legacy page may reintroduce an executable inline script; repo-shape, pre-merge
        "test_grant_enumeration_drift.py",  # #2824: consumer⊆granted across cdk/stacks + lambdas/ + .github/workflows + infra/iam — a new fail-closed consumer (or a role that drops a grant) must red BEFORE the merge, not after the channel is already stranded
        "test_no_hardcoded_feature_tier.py",
        "test_budget_guard_ladder.py",
        # #2818: the producer-cron mirror pair (cdk/stacks/compute_stack.py ↔
        # lambdas/operational/qa_check_outputs.py). Its verdict is pure repo shape —
        # a producer cron moving without its QA-window mirror must red BEFORE the
        # merge, not after the window has silently drifted a second time (#2670's
        # own fix seeded exactly that). Sweeps via check_doc_facts' helpers, which
        # are spec-loaded from scripts/ — invisible to premerge_derivation's
        # tests/-scoped helper detection, hence hand-listed here.
        "test_qa_window_derivation_2818.py",
        # #2813: the PT-day producer/gate contract sweep. Its verdict depends only
        # on repo shape — an os.walk(lambdas/) AST scan for any function accepting
        # a generation_date/day_n-shaped default with neither a @pt_day_contract
        # registration nor a written EXEMPT_PT_DAY_CANDIDATES reason. A new gate
        # that silently defaults to UTC (the #2675/#2812/#2815 defect class) must
        # red BEFORE the merge, not surface in production during the next PT
        # evening — the exact post-merge-only failure mode #2372 exists to stop.
        "test_pt_day_contract_sweep_2813.py",
        # #2847: the producer/consumer contract sweep — #2813's primitive generalised
        # past the day-frame agreement. Half its verdict is pure repo shape (the enrolled
        # floor, the enrollment ratchet, the PARTITION_WRITER_LEDGER against the #2845
        # model's write edges, the registry↔model agreement), and a NEW writer joining a
        # contracted shape must red on the PR that adds it — post-merge is how #2214's
        # dual-writer and #2804's dead-zone read both reached production. Reads fixed
        # files rather than sweeping the tree, so premerge_derivation cannot discover
        # it — hand-listed, same as #2813 above.
        "test_pair_contract_sweep_2847.py",
        # #2847 box 4: the must-agree SEAM guard — charter standing rule 3's fleet-wide
        # enforcement, the peer of #2844's rule-1 guard. Its whole premise is that the
        # birth of a must-agree pair is a decision made ON the PR that creates it; a red
        # arriving post-merge is the seam already shipped, which is exactly how #2804's
        # dead-zone read and #2214's dual writer both reached production. Builds the
        # #2845 model from source rather than sweeping the tree (~7s), so
        # premerge_derivation cannot discover it — hand-listed, same as the sweep above.
        "test_pair_seam_conformance_2847.py",
        # #3101: the doc-literal conflict surface. Its verdict is pure repo shape —
        # whether a discovered counter has grown a SECOND committed home, and whether
        # the single-writer plumbing (agent_commit refusal, hook stage pathspec,
        # reconcile whitelist) is still wired. Post-merge is too late by construction:
        # the whole point is that the surface must not reopen on the branch that
        # reopens it, and a red arriving after the merge is a red the next concurrent
        # PR pays for. Reads fixed files rather than sweeping, so premerge_derivation
        # cannot discover it — hand-listed, same as test_qa_window_derivation_2818.
        "test_doc_literal_conflict_surface_3101.py",
        # ── tree hygiene + safety sweeps ──────────────────────────────────────
        "test_lambdas_packaging_guard.py",  # ADR-146: no loose modules at the lambdas/ root
        "test_bundle_deploy_trigger_registry.py",  # #2920: every path build_bundle.py stages is a deploy trigger or a dated exemption
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
        # #2541: the starter template's forbidden-literal sweep. `oss/starter-slice/` is
        # built to be COPIED OUT and published, so a leaked owner name, account id or
        # bucket must red before the merge, not after — post-merge is already too late
        # for an artifact whose next step is someone else's `git push`.
        "test_starter_slice.py",
        # #2578: the gate census. Its verdict is a sweep of the whole repo tree (CI
        # workflows, guard entrypoints, registries, qa-smoke checks) and its floors
        # are blindness detectors — a derivation that returns [] must red BEFORE the
        # merge, not after, which is the entire point of this list.
        "test_gate_census_2578.py",
        # #3000: the census's OWN lane + visibility ratchet (epic #2578's fourth
        # acceptance box) — sibling to the entry above. Its verdict is pure repo shape
        # (the live gate count against a committed ceiling), so it belongs here for the
        # same reason as its sibling: post-merge is too late for a gate that entered
        # unverified.
        "test_gate_census_lane_3000.py",
        # #3220: what the census is allowed to COUNT. Third sibling of the two above,
        # and pre-merge for the same reason plus one of its own: it decides whether a
        # name-matched file has structural evidence it can enforce anything, so a
        # regression here silently moves the ratchet's denominator. Verdict is pure
        # repo shape (synthetic trees + one property assertion against the real tree),
        # measured at 0.16s.
        "test_gate_census_enforcement_3220.py",
        # #2632: the bundle-boot gate's WIRING. The gate itself is a pre-merge step and
        # a deploy-path step; this file is what stops the call site vanishing again, and
        # the removal it guards against is invisible in any diff that does not touch it.
        "test_bundle_boot_wiring_2632.py",
        "test_csp_native_embeds_1678.py",
        "test_archive_handover.py",  # a dated handover committed to main (#1650)
        # #2570: the CQ-01 pin guard stopped hand-listing the workflow files and now
        # derives its declaration surface from `git ls-files` (the Makefile's stale
        # black/ruff/mypy pins were invisible to the hand-list). That makes it a
        # repo-shape ratchet: a new file declaring a pin must be caught pre-merge.
        "test_ci_pin_consistency.py",
        # #2759: the npm leg of the same class — derives its workflow surface from
        # `git ls-files` exactly like the pip guard above, so a new workflow with a
        # bare `npm install -g` must red BEFORE the merge, not after.
        "test_npm_pin_consistency_2759.py",
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
        "test_fixture_frame_pairing_3222.py",  # #3222: the fixture half of the PT-day contract — repo-shape sweep of tests/ x lambdas/+mcp/, same lane as its two siblings below
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
        "test_utc_day_fleet_ratchet_2811.py",
        "test_site_chrome.py",
        "test_site_orphans.py",
        "test_site_partition_orphans.py",
        "test_tier0_streak_writer_2242.py",
        "test_timezone_discipline.py",
        "test_todoist_reader_writer_contract.py",
        "test_wayfinding.py",
        "test_wiring_coverage.py",
        "test_xfail_hygiene.py",
        # #2666: derives the MCP error-suggestion strings and the TOOLS dict by AST
        # sweep, and fails when a suggestion names a tool that is not registered —
        # a repo-shape ratchet whose verdict depends only on source, not on data.
        "test_mcp_suggestion_tool_names_2666.py",
        # #2698: sweeps lambdas/ mcp/ scripts/ for anything touching a follow partition —
        # a repo-shape ratchet whose verdict depends only on source (the consent guard).
        "test_follow_consent_state_2698.py",
        # #2653: sweeps lambdas/ docstrings and cdk/stacks/role_policies*.py to assert no
        # docstring names a secret no role grants — a repo-shape ratchet, source only.
        "test_docstring_secret_ids_2653.py",
        # #2898: sweeps `git ls-files` over lambdas/ cdk/ mcp/ scripts/ deploy/ tests/ and
        # site/ for a hand-typed copy of the budget ceiling. Its covered population is the
        # whole tracked tree and its forbidden VALUES are derived from the cost governor,
        # so both halves change size without anyone editing the file — a repo-shape
        # ratchet by construction, and it must red BEFORE the merge that adds the copy.
        "test_budget_ceiling_registry_2898.py",
        # the derivation guard itself — its own docstring/synthetic-fixture text
        # mentions the three sweep idioms, so it self-matches; it belongs pre-merge
        # regardless (it IS the structural gate this whole entry is about).
        "test_premerge_extra_files_derivation_2372.py",
        # #2692: PR #2884 merged 7/7 green on pr-checks.yml and red-mained main TWICE
        # on these two files — neither is caught by the #2372 tree-sweep derivation
        # above (discover_tree_sweeping_test_files() only matches os.walk(/.rglob(/
        # `git ls-files`), so nothing forced a classification decision. Both are
        # structural/derivation guards by the CHARTER's own primitives (registry +
        # derivation guard), just shaped differently than the tree-sweep detector:
        #   - test_drift_sentinel.py's test_push_trigger_globs_match_workflows()
        #     sweeps .github/workflows/ via os.listdir(), an idiom the #2372 pattern
        #     doesn't recognize — the exact PUSH_TRIGGER_GLOBS-vs-workflow-paths
        #     literal that drifted and reddened main.
        #   - test_gate_registry_1349.py reads ONE file (docs/CONVENTIONS.md) and
        #     checks it against a declared structure — not a tree sweep at all, but
        #     still a registry gate whose verdict depends only on repo state.
        # Both are cheap (102 tests / 0.31s measured) and cost nothing meaningful
        # against the lane's ten-minute budget. This is a deliberate, hand-added
        # pair, not a derivation-pattern widening: os.listdir( alone appears in 20
        # test files, most of them genuine behaviour suites, and sorting those is a
        # separate classification pass, not this fix.
        "test_drift_sentinel.py",
        "test_gate_registry_1349.py",
        # ── #2924: the sweep can live ONE IMPORT away ─────────────────────────
        # The pair above was hand-added because the #2372 detector reads only
        # tests/test_*.py source text. That blind spot had a second, larger half:
        # a guard whose sweep lives in a sibling HELPER module contains no sweep
        # idiom itself, only an import. `test_conformance_guard_2844.py` — the
        # charter conformance guard, the fleet-wide derivation-guard primitive
        # docs/CHARTER.md names — is exactly that shape (its sweep is in
        # tests/conformance_guard_lib.py). It landed 2026-08-17, was classified
        # nowhere, and ran POST-MERGE ONLY: the #2339 failure mode reproduced by
        # the derivation's own blind spot, while sitting in the 168-test command
        # every agent brief called a pre-merge check.
        #
        # premerge_derivation.py now sweeps tests/*.py for non-test helpers that
        # sweep (conformance_guard_lib, grounding_wiring, qa_manifest) and flags
        # any test file importing one, so this class joins BY CONSTRUCTION rather
        # than by another hand-addition. That found 22 unclassified files; the 20
        # below are registry/derivation gates whose covered population changes
        # when the registry does, measured together at 363 tests in 12.4s against
        # the lane's ten-minute budget. The other two are in the exclusion dict.
        "test_analyzer_gate_all_paths_2421.py",
        "test_behavioral_availability_2056.py",
        "test_compression_gate_2428.py",
        "test_conformance_guard_2844.py",
        "test_design_sync_capture.py",
        "test_field_notes_grounding.py",
        "test_hypothesis_prose_grounding_2420.py",
        "test_partial_gate_cluster_2430.py",
        "test_prereg_seal_1980.py",
        "test_qa_archive.py",
        "test_qa_audit.py",
        "test_qa_live_endpoint_coverage_2652.py",
        "test_qa_manifest.py",
        "test_reading_grounding_2425.py",
        "test_smoke_structural.py",
        "test_stance_behavioral_gate_2195.py",
        "test_traffic_green_report.py",
        "test_visual_ai_qa.py",
        "test_visual_qa_units.py",
        "test_webkit_weekly_qa.py",
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
    # #2924: both inherit qa_manifest's sweep by import, but each looks up exactly
    # ONE hardcoded page and asserts about that page alone — so unlike their 20
    # siblings above, their covered population CANNOT change when the registry
    # grows. That is precisely the property that makes a file a repo-shape ratchet,
    # and it is absent here. Behaviour suites in substance; post-merge is their job.
    "test_mirror_parity.py": (
        "imports qa_manifest.MANIFEST only to look up the single fixed /method/mirror/ "
        "entry (#1392); the rest is JS-vs-Python numeric-parity behaviour, not a sweep"
    ),
    "test_diary_shelf_1846.py": (
        "imports qa_manifest.MANIFEST only to assert the single fixed /story/diary/ page "
        "is registered (AC4 of #1846); the other 29 tests are diary-shelf behaviour"
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


# ══════════════════════════════════════════════════════════════════════════════
# PER-TEST DURATION WARNER  (#3025, folding #2692)
# ══════════════════════════════════════════════════════════════════════════════
# The total wall-clock budget (tests/test_duration_budget_ratchet.py) cannot
# distinguish "the suite grew a little" from "one test regressed badly" — the
# 180.85s test_add_book_dry_run_then_commit hid inside a 1394s total for weeks.
# This emits a `::warning` per test whose CALL phase crosses the bar, in every
# lane, so the wrap's standing-warning triage gate (#1966, e11) sees the next
# single-test regression the day it lands. A warning, not a failure: a slow but
# correct test must never red main; the ratchet owns the aggregate.
PER_TEST_WARN_SECONDS = 90.0
_SLOW_TESTS: list = []


def slow_test_warning_lines(slow, bar=PER_TEST_WARN_SECONDS):
    """Pure half, unit-tested in tests/test_full_suite_premerge_3025.py."""
    return [
        f"::warning title=Per-test duration (#3025)::{nodeid} took {dur:.1f}s "
        f"(bar {bar:.0f}s) — one test hiding inside the total budget; fix or justify it"
        for nodeid, dur in slow
        if dur >= bar
    ]


def pytest_runtest_logreport(report):
    if report.when == "call" and report.duration >= PER_TEST_WARN_SECONDS:
        _SLOW_TESTS.append((report.nodeid, report.duration))


def pytest_sessionfinish(session, exitstatus):
    for line in slow_test_warning_lines(_SLOW_TESTS):
        print(f"\n{line}")
