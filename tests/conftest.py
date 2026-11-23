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

# #4270: the QA tooling moved to qa/ (the mypy set to scripts/). Tests (and the qa modules' own lazy bare imports,
# `from visual_ai_qa import ...`) still name them bare; this finder resolves each bare name to the ONE qa.<name>
# module object, so a monkeypatch on `qa_manifest` is seen by every importer whichever spelling it used.
_QA_BARE = frozenset(
    {
        "qa_manifest",
        "leak_token_sweep",
        "visual_qa",
        "visual_ai_qa",
        "visual_qa_verdict",
        "visual_qa_cli",
        "accuracy_audit",
        "comprehension_qa",
        "perf_trend",
        "pr_render_gate",
    }
)


class _QaAliasFinder:
    @classmethod
    def find_spec(cls, name, path=None, target=None):
        if name not in _QA_BARE:
            return None
        import importlib.util

        return importlib.util.spec_from_loader(name, cls)

    @staticmethod
    def create_module(spec):
        import importlib

        if _REPO not in sys.path:
            sys.path.insert(0, _REPO)
        return importlib.import_module("qa." + spec.name)

    @staticmethod
    def exec_module(module):
        return None


sys.meta_path.insert(0, _QaAliasFinder)

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
_AWS_CRED_KEYS = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_SECURITY_TOKEN",
    "AWS_PROFILE",
    # #6116: the credential FILES and the metadata service are credential sources too — stashed and restored with the
    # keys, so an `integration` test on a laptop (whose real credentials live in ~/.aws) still reaches them.
    "AWS_CONFIG_FILE",
    "AWS_SHARED_CREDENTIALS_FILE",
    "AWS_EC2_METADATA_DISABLED",
)
# #3917: the snapshot must happen ONCE, in the controller, BEFORE the fakes go on — and it must
# survive into xdist workers. A worker is a fresh process forked by the controller AFTER this
# module already faked the controller's environment, so a plain `os.environ.get(key)` snapshot
# taken in the worker captures `testing`, and "restoring" real credentials around an
# `integration` test restores the fake. The stash below is itself an environment variable, so
# workers inherit it; the controller writes it only when it is absent, so a worker never
# re-snapshots the fakes over it. `_UNSET_SENTINEL` keeps "the key was absent" distinct from
# "the key was empty".
_REAL_AWS_STASH_PREFIX = "LP_REAL_AWS_ENV__"
_UNSET_SENTINEL = "__unset__"
for _key in _AWS_CRED_KEYS:
    os.environ.setdefault(_REAL_AWS_STASH_PREFIX + _key, os.environ.get(_key) if os.environ.get(_key) is not None else _UNSET_SENTINEL)
_REAL_AWS_ENV = {
    key: (None if os.environ[_REAL_AWS_STASH_PREFIX + key] == _UNSET_SENTINEL else os.environ[_REAL_AWS_STASH_PREFIX + key])
    for key in _AWS_CRED_KEYS
}
_FAKE_AWS_ENV = {
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SESSION_TOKEN": "testing",
    "AWS_SECURITY_TOKEN": "testing",
    "AWS_DEFAULT_REGION": "us-west-2",
    "AWS_REGION": "us-west-2",
    # #6116 (incident 2026-11-16): a test that builds its subprocess env with EMPTY key variables does not get "no
    # credentials" — the CLI and boto3 treat an empty value as unset and fall back to ~/.aws (there, an admin profile).
    # Pointing the files at devnull and switching the metadata service off closes those fallbacks for the session and
    # every child that inherits its env.
    "AWS_CONFIG_FILE": os.devnull,
    "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
    "AWS_EC2_METADATA_DISABLED": "true",
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

# #6116 — THE TEST-SESSION MARKER AND THE SHIMS. A child that rebuilds its env without the AWS_* keys sheds the
# fakes above; it does not shed these. LP_TEST_SESSION is the explicit marker the deploy guard reads
# (deploy/lib/prod_write_guard.sh + its Python twin; PYTEST_CURRENT_TEST and a pytest ancestor process are the other
# two signals), and the guard's shims go first on PATH so an `aws` / `npx cdk deploy` run BY NAME from any test or
# script is refused unless the test declares its stub (LP_TEST_AWS_IS_STUB=<path of the stub executable>). The ONE
# opt-in for live AWS is `@pytest.mark.integration` (below), which restores the real credentials and nothing else:
# the shims still refuse a CLI call, and no live test uses the CLI.
_PROD_WRITE_GUARD_SHIMS = os.path.join(_REPO, "deploy", "lib", "prod_write_guard_bin")
os.environ["LP_TEST_SESSION"] = "1"
if os.environ.get("PATH", "").split(os.pathsep)[0] != _PROD_WRITE_GUARD_SHIMS:
    os.environ["PATH"] = _PROD_WRITE_GUARD_SHIMS + os.pathsep + os.environ.get("PATH", "")

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
    # #5947: the owner-only clinical vocabulary is channel-only too — synthetic terms here, one of
    # them multi-word (the screen matches a phrase across whitespace or a hyphen).
    "blocked_clinical_keywords": ["snorbleitis", "quibbled wumpus"],
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
# THAT AFFORDABILITY NUMBER HAS MOVED, AND THIS COMMENT NO LONGER CARRIES IT
# (#2924 filed it; #3608 box 4 removed the literal). The number that used to sit
# here — a test-count-and-seconds pair stamped 2026-08-21 — was exactly the thing
# the surrounding paragraph warns against: a measurement frozen into prose, where
# nothing re-measures it and nothing reds when it drifts. It also disagreed with
# `deploy/github_posture.json`'s stored `typical_seconds` by more than a minute,
# and both were wrong against the observed 13m57s–15m22s band #3678 measured.
#
# THE MEASUREMENT, not a number: the pre-merge lane emits its own wall-clock and
# `deploy/github_posture.json`'s `typical_seconds` is written from it. Read that
# field (and `measured_on`/`measured_from` beside it) for the current figure — do
# not quote it back into a comment. The posture still holds on ratio, not on any
# particular second: the lane is a fraction of its `timeout-minutes`, and
# `scripts/check_job_timeout_headroom.py` (#3678) is what grades that fraction.
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
# These were hand-listed (#4270 box 4 replaced the list with the `# premerge-gate:` marker
# below, read from each gate's own file). Unlike `*_behavior.py` no filename is shared, so
# the marker is the opt-in. What keeps the set honest is that it cannot rot silently —
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
# on the repo tree has no business running after the merge.** When you add one, add a
# `# premerge-gate: <reason>` line to its own file in the same PR.
# DERIVED FROM A MARKER, NOT HAND-LISTED (#4270 box 4). A structural gate joins the
# pre-merge lane by carrying, at the START OF A LINE anywhere in its own file:
#
#     # premerge-gate: <one-line reason it is a repo-shape ratchet>
#
# `scripts/premerge_derivation.discover_marked_premerge_files()` reads those markers
# (tests/premerge_derivation.py is the import shim); this set is the result, so the
# 216-name hand-list that conflicted in every concurrent lane is gone and a new gate's
# registration lives in the file that is the PR's own diff. The name stays because
# several guards read it (test_premerge_lane, test_restart_verify_gates_3477, the
# #2372 classification test). tests/test_premerge_extra_files_derivation_2372.py holds
# the marker contract, including the mutation controls. Classification of tree-sweeping
# files is unchanged: marked here, or named in _PREMERGE_TREE_SWEEP_EXCLUDED below.
import premerge_derivation as _premerge_derivation  # noqa: E402 - tests/ is on sys.path (cf. ci_shard)

_PREMERGE_EXTRA_FILES = frozenset(_premerge_derivation.discover_marked_premerge_files())

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
    # #3625: walks ONLY the synthetic tree it builds under tmp_path (os.walk over a 4-file
    # fixture) to prove the bundle zip is byte-reproducible — it never touches the repo,
    # so its covered population cannot change when the repo does. Not a repo-shape ratchet.
    "test_bundle_zip_reproducible_3625.py": "walks its own tmp_path fixture tree, never the repo — the bundle-reproducibility proof (#3625)",
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
    # #3731: tests/repo_scan_cache.py gained a disk-backed cache keyed on a tree-state
    # fingerprint (`os.walk`), so it now matches `_SWEEP_PATTERN` for the first time and
    # every test file below — which merely imports it to reuse a scan — was newly
    # discovered as a sweeper. None of the four has a population that grows or shrinks
    # with the tree: each real-tree assertion is a fixed "the gate still exits 0 on the
    # committed tree" check, the exact `test_mirror_parity.py` shape above (inherits a
    # sweep by import, asserts about one fixed thing, not a repo-shape ratchet). Their
    # ~50s-class real-tree assertions belong in the exhaustive post-merge run, not the
    # fast pre-merge gate.
    "test_doc_facts_ops_1957.py": (
        "27 synthetic-fixture behaviour tests over doc_facts_ops.py's predicates; "
        "test_gate_passes_on_the_repo is one fixed pass/fail check, not a growing population"
    ),
    "test_doc_facts_ops_2003.py": (
        "14 synthetic-fixture behaviour tests over doc_facts_ops.py's predicates; "
        "test_gate_passes_on_the_repo is one fixed pass/fail check, not a growing population"
    ),
    "test_wiki_checkers.py": (
        "43 synthetic-fixture / scratch-file behaviour tests over the wiki-checker scripts; "
        "its three real-tree readers (test_doc_facts_clean, test_verified_advisory_is_warn_only, "
        "test_wiki_index_coverage_and_headers) are each one fixed pass/fail check"
    ),
    "test_repo_scan_cache_3224.py": (
        "the shared cache's own test suite — 16 of 17 tests fake subprocess.run entirely; "
        "the one real call (test_g) checks a single fixed script (check_doc_index.py) exits 0, "
        "not a population that changes with the repo"
    ),
}


def pytest_ignore_collect(collection_path, config):
    """#4252: a ci-test.yml shard leg (CI_TEST_SHARD=K/N) collects only its own test
    files. Unset everywhere else, so every other run collects exactly what it did.
    The partition contract lives in tests/ci_shard.py."""
    import ci_shard

    if ci_shard.excluded(str(collection_path), os.environ.get(ci_shard.SHARD_ENV, "")):
        return True
    return None


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
# THE CHECKOUT IS ONE SHARED FIXTURE — `serial` MUST MEAN ALONE  (#6024)
# ══════════════════════════════════════════════════════════════════════════════
# `serial` (pytest.ini, #3025) marks a test that MUTATES THE REAL CHECKOUT (plants a file
# under lambdas/, rewrites docs/PROPORTIONALITY.md, ...). The marker was only ever a
# convention for the invocation — `-m "not serial"` for the parallel pass, `-m serial`
# afterwards. A bare `pytest tests/ -n 8` runs those writers concurrently with every
# whole-tree scan, and `scripts/check_doc_facts.py` (test_doc_facts_ops_1957/2003
# `test_gate_passes_on_the_repo`, via tests/repo_scan_cache.py) reads docs/ + lambdas/ for
# 7-15 s: any writer that lands inside that window flips it red; it passes alone because
# nothing else is writing. Reproduced 2026-11-15: the two gate tests + the registered writers under
# `-n 8` failed in 1 of 3 runs for the gate tests (and the writers failed each other).
#
# The fix is at the cause: under xdist, every test takes a SHARED lock on a per-checkout lock
# file for its whole setup/call/teardown and a `serial` test takes it EXCLUSIVELY, so a
# serial test genuinely runs alone whatever the command line. A turnstile lock stops a
# stream of shared holders starving the exclusive waiter. Outside xdist (the second pass,
# a single-file run) the hook is a no-op: one process cannot race itself.
try:
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - non-POSIX
    _fcntl = None


_TREE_LOCK_HELD_ENV = "LIFE_PLATFORM_TREE_LOCK_HELD"


def _tree_lock_paths():
    import hashlib
    import tempfile

    tag = hashlib.sha256(os.path.dirname(os.path.abspath(__file__)).encode()).hexdigest()[:16]
    base = os.path.join(tempfile.gettempdir(), f"life-platform-tree-lock-{tag}")
    return base + ".turnstile", base + ".tree"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    # A test that shells out to `pytest` inherits PYTEST_XDIST_WORKER; if the child took the lock too it would
    # wait on its own parent (parent holds shared, child's serial test wants exclusive) — a deadlock found
    # in the first verification loop. The parent's hold already covers the child, so a nested run skips.
    if _fcntl is None or not os.environ.get("PYTEST_XDIST_WORKER") or os.environ.get(_TREE_LOCK_HELD_ENV):
        yield
        return
    exclusive = item.get_closest_marker("serial") is not None
    turnstile_path, tree_path = _tree_lock_paths()
    turnstile = os.open(turnstile_path, os.O_CREAT | os.O_RDWR)
    tree = os.open(tree_path, os.O_CREAT | os.O_RDWR)
    try:
        _fcntl.flock(turnstile, _fcntl.LOCK_EX)  # one entrant at a time; new entrants queue behind a waiting serial test
        try:
            _fcntl.flock(tree, _fcntl.LOCK_EX if exclusive else _fcntl.LOCK_SH)
        finally:
            if not exclusive:
                _fcntl.flock(turnstile, _fcntl.LOCK_UN)
        os.environ[_TREE_LOCK_HELD_ENV] = "1"
        yield
    finally:
        os.environ.pop(_TREE_LOCK_HELD_ENV, None)
        try:
            _fcntl.flock(tree, _fcntl.LOCK_UN)
            _fcntl.flock(turnstile, _fcntl.LOCK_UN)
        finally:
            os.close(tree)
            os.close(turnstile)


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


@pytest.fixture(autouse=True)
def _write_day_is_genesis_day(monkeypatch):
    """#3598: the provenance stamp derives phase + cycle from the WRITE'S DATE
    (experiment_stamp / tag_record's undated path read `phase_taxonomy._write_date`).
    Every writer test in this suite was written under the pre-#3598 assumption that
    a write is "the experiment", and a future-genesis reset (the sanctioned eve
    reset, #931) would otherwise turn all of them pilot for a day — and the #3477
    sweep runs CI's gates INSIDE the reset, so that day is reset day. So the suite's
    write day is GENESIS DAY unless a test says otherwise: pass `as_of=` (or re-pin
    `_write_date`) to exercise the countdown window — tests/test_reset_writer_contract_3598.py
    does, in both directions."""
    try:
        from common.constants import EXPERIMENT_START_DATE
        from experiment import phase_taxonomy
    except Exception:  # a test tree without the lambdas layer on its path
        yield
        return
    monkeypatch.setattr(phase_taxonomy, "_write_date", lambda: EXPERIMENT_START_DATE)
    yield


# ── #3620 (security ROW4): the suite gets a deterministic ip_hash salt ────────
# `web/site_api_social_engage._salted_ip_hash` reads `life-platform/ip-hash-salt`
# through common/secret_cache and returns None when it cannot — at which point
# every engagement door answers 503 and writes nothing. That fail-closed arm is
# the fix, not a defect, but it would otherwise short-circuit every pre-existing
# door test before it reached the behaviour it was written to pin (and in CI
# there is no Secrets Manager to read).
#
# So the suite pins a fixed salt. The fail-closed arm is NOT left unasserted:
# tests/test_ip_hash_salt_3620.py overrides this by patching `_get_secret` again
# inside the test, and asserts the None return AND a real handler's 503.
#
# `common.client_ip.salted_ip_hash` — the shared helper every OTHER ip_hash call
# site routes through (tests/test_ip_hash_salt_sweep_3620.py) — reads the SAME
# secret through its own `_get_secret` reference, patched here too so none of
# those doors' pre-existing tests start hitting a real (absent, in CI)
# Secrets Manager either.
@pytest.fixture(autouse=True)
def _ip_hash_salt_3620(monkeypatch):
    try:
        from web import site_api_social_engage as _engage
    except Exception:  # a test tree without the lambdas layer on its path
        yield
        return
    monkeypatch.setattr(_engage, "_get_secret", lambda secret_id, client: "conftest-ip-hash-salt")
    try:
        from common import client_ip as _client_ip

        monkeypatch.setattr(_client_ip, "_get_secret", lambda secret_id, client: "conftest-ip-hash-salt")
    except Exception:
        pass
    yield


# #6111: a Site API request reads the COMPLETE withheld graded record (web.publication_snapshot) from the table it reads.
# A unit test that drives the handler over a module-patched fake still leaves site_api_lambda.table as the real boto3
# handle; with the suite's fake credentials that read would leave the machine and fail (then the request is refused, 503).
# In the unit suite a REAL boto3 table therefore reads as empty — the record the test's own fake table does not hold — and
# each test starts with no snapshot held. A fake table is read for real (tests/test_publication_determinism_6111.py).
@pytest.fixture(autouse=True)
def _publication_snapshot_hermetic(monkeypatch):
    try:
        import boto3.resources.base as _b3res
        from web import publication_snapshot as _snap
    except Exception:  # a test tree without the lambdas layer on its path
        yield
        return
    _snap.reset()
    real = _snap._read_partition

    def _read(raw, pk):
        return [] if isinstance(raw, _b3res.ServiceResource) else real(raw, pk)

    monkeypatch.setattr(_snap, "_read_partition", _read)
    yield
    _snap.reset()


# #6199: the publish paths read every coach call to check text against the private ones, and fail CLOSED when they cannot
# (every text held). A unit test that drives a publish path still holds the module's REAL boto3 table; with the suite's
# fake credentials that read fails and every draft would hold. Same rule as the snapshot above: in the unit suite a REAL
# boto3 table reads as holding no calls; a fake table is read for real (tests/test_private_call_check_6199.py), and a
# test that wants the fail-closed path makes the read raise.
@pytest.fixture(autouse=True)
def _private_call_reads_hermetic_6199(monkeypatch):
    try:
        import boto3.resources.base as _b3res
        from content import private_call_check as _pcc
    except Exception:  # a test tree without the lambdas layer on its path
        yield
        return
    real = _pcc._read_rows

    def _read(table, pk, prefix):
        return [] if isinstance(table, _b3res.ServiceResource) else real(table, pk, prefix)

    monkeypatch.setattr(_pcc, "_read_rows", _read)
    # The Panel arms the check per run (emails.panelcast_desk.arm_private_calls); a run in one test must not leave it
    # armed — possibly with an unreadable fake table — for the next.
    for _name in ("emails.panelcast_desk", "panelcast_desk"):
        _mod = sys.modules.get(_name)
        if _mod is not None and hasattr(_mod, "_PRIVATE_CALLS"):
            monkeypatch.setattr(_mod, "_PRIVATE_CALLS", {"armed": False, "calls": None})
    yield


# #6176: the owner's two-week outbound-mail trial is committed ON until common.outbound_trial.TRIAL_ENDS_ON, after which
# the BASELINE behaviour returns by itself. The rest of the suite pins that baseline, so every test starts with the
# switchboard OFF (monkeypatch: restored after). The trial's own tests opt in explicitly (tests/test_outbound_trial_6176.py
# `trial_on`, and its pin reads the committed values captured at its import).
@pytest.fixture(autouse=True)
def _outbound_trial_baseline_off_6176(monkeypatch):
    try:
        from common import outbound_trial as _ot
    except Exception:  # a test tree without the lambdas layer on its path
        yield
        return
    for _item in list(_ot.TRIAL):
        monkeypatch.setitem(_ot.TRIAL, _item, False)
    monkeypatch.setattr(_ot, "TRIAL_ENDS_ON", None)
    yield


# #6195: the target-neutral nutrition consistency switchboard. Every item ships OFF; when one is switched on, the rest
# of the suite still pins the OFF (baseline) output, so every test starts with the switchboard OFF (monkeypatch:
# restored after). tests/test_nutrition_consistency_6195.py opts in per item and pins the committed values itself.
@pytest.fixture(autouse=True)
def _nutrition_consistency_baseline_off_6195(monkeypatch):
    try:
        from common import nutrition_consistency as _nc
    except Exception:  # a test tree without the lambdas layer on its path
        yield
        return
    for _item in list(_nc.SWITCHES):
        monkeypatch.setitem(_nc.SWITCHES, _item, False)
    yield


# #6193: second editions of published chapters are committed LIVE (owner ruling 2026-11-22; nothing renders until an
# edition is approved by hash). The rest of the suite pins the pre-#6193 baseline, so every test starts with the switch
# OFF (monkeypatch: restored after). tests/test_chapter_editions_6193.py opts in explicitly and pins the committed value
# from a capture at its import.
@pytest.fixture(autouse=True)
def _chapter_editions_baseline_off_6193(monkeypatch):
    try:
        from content import chapter_editions as _ce
    except Exception:  # a test tree without the lambdas layer on its path
        yield
        return
    monkeypatch.setattr(_ce, "LIVE", False)
    yield


# Owner ruling 2026-11-11 (item 2): the plan root's private part lives OFF the repo — on a developer's machine at
# ~/.config/life-platform/user_goals_private.json (common.user_goals). A test must never read the owner's real private
# part, so the suite points the loader at a path that does not exist; a test that needs a private part writes a
# SYNTHETIC one to tmp_path and sets the variable itself.
@pytest.fixture(autouse=True)
def _goals_private_part_is_synthetic(monkeypatch, tmp_path_factory):
    monkeypatch.setenv("LIFE_PLATFORM_GOALS_PRIVATE_PATH", str(tmp_path_factory.getbasetemp() / "no-goals-private-part.json"))
    yield


# #5861 (owner approval 2026-11-14): config/exercise_library.json is APPROVED, so the generator serves the live engine. A test
# that pins the PRE-approval generator (dated golden IRs, v0.3/v0.4 template behaviour, the shadow rotation wording) runs on the
# library's ROLLBACK copy — status proposed, approved_on removed, nothing else changed — so it keeps guarding the rollback path
# (setting the status back to proposed serves exactly that generator). Opt in with
# `@pytest.mark.usefixtures("exercise_library_rollback")`. Every library read goes through `exercise_library.load_library`
# (the selection engine's cached `load_library_failsoft` reads it first; the cache is cleared on both sides) or
# `week_floors.library`.
def _exercise_library_rollback_copy() -> dict:
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "exercise_library.json")
    with open(path, encoding="utf-8") as f:
        lib = _json.load(f)
    lib["status"] = "proposed"
    lib.pop("approved_on", None)
    return lib


@pytest.fixture
def exercise_library_rollback(monkeypatch):
    import copy

    from training import exercise_library as _xl, selection_engine as _se, week_floors as _wf

    lib = _exercise_library_rollback_copy()
    assert _se.mode(lib) == _se.MODE_SHADOW
    monkeypatch.setattr(_xl, "load_library", lambda path=None: copy.deepcopy(lib))
    monkeypatch.setattr(_wf, "library", lambda path=None: copy.deepcopy(lib))
    _se._LIB_CACHE.clear()
    yield lib
    _se._LIB_CACHE.clear()
