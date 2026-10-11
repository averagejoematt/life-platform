"""#4270 - production tooling must not import code from tests/.

tests/ should hold tests and fixtures. Tooling that reaches INTO tests/ (a sys.path insert of tests/, a
subprocess/path reference to a tests/*.py module, `from tests.` ) couples the deploy path and the CI workflows
to the test tree, so a test-only refactor can break a deploy or a gate. The QA tooling now lives in qa/
(qa_manifest, leak_token_sweep, visual_qa, visual_ai_qa, visual_qa_verdict, visual_qa_cli, accuracy_audit,
comprehension_qa, perf_trend, pr_render_gate) and the mypy clean set in scripts/mypy_clean_set.py. tests/ keeps
a bare-name re-export shim for each (SHIMS below) so test modules that `import visual_qa` keep working - and the
shim files themselves are the only tests/ non-test modules that may be named.

Scope: top-level deploy/*.py and scripts/*.py (sys.path / path-literal patterns), plus a workflow / lambdas /
qa / cdk sweep for any `tests/<non-test>.py` invocation or `from tests.` import. Subdirectories of deploy/ and
scripts/ are not swept (deploy/archive holds archived one-shot patch scripts).

Two ledgers, both shrink-only (a NEW offender fails; a ledger row that no longer offends also fails):
  * EXEMPT - consumers that read a TEST-OWNED artefact on purpose (a registry that is itself the test's
    subject, a fixture generator). Moving the artefact would move the test; the row states why.
  * LEGACY - tooling still in tests/ that a later slice of #4270 moves to qa/ (each row names the module).
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Files that already moved off tests/ and MUST stay off it.
MOVED_CLEAN = [
    "deploy/restart_verify_rendered.py",
    "deploy/build_bundle.py",
    "deploy/sync_doc_metadata.py",
    "deploy/restart_integration_check.py",
    "deploy/capture_api_schemas.py",
    "scripts/api_sweep_check.py",
    "scripts/design_sync_capture.py",
    "scripts/fresh_eyes_discovery.py",
    "scripts/mypy_disable_cost.py",
    "scripts/review_anchor_seal.py",
    "scripts/surface_drift_gate.py",
    "scripts/v4_build_sitemap.py",
]

# Bare-name re-export shims left in tests/ for test modules that `import <name>` (the ONLY non-test tests/ modules
# this refactor leaves behind for the moved tooling). No workflow, deploy script or lambda may name them.
SHIMS = {
    "tests/qa_manifest.py",
    "tests/leak_token_sweep.py",
    "tests/visual_qa.py",
    "tests/visual_ai_qa.py",
    "tests/visual_qa_verdict.py",
    "tests/visual_qa_cli.py",
    "tests/accuracy_audit.py",
    "tests/comprehension_qa.py",
    "tests/perf_trend.py",
    "tests/pr_render_gate.py",
    "tests/mypy_clean_set.py",  # also the CLI path .claude/settings.json's permission entry names (owner edit)
}

# Deliberate: the consumer reads an artefact that is a TEST's own subject; relocating it relocates the test.
EXEMPT = {
    "deploy/sensor_self_test.py": "reads the COVERAGE registry out of tests/test_heartbeat_completeness.py",
    "deploy/sentinel_producer_census.py": "reads scheduled_lambda_cadences() out of tests/test_heartbeat_completeness.py",
    "scripts/diligence_verify.py": "imports the canonical PRIVATE-marker predicate from tests/test_no_private_markers_3043.py",
    "scripts/generate_platform_model.py": "AST-reads tests/pair_contract_registry.py (the pair-seam test registry)",
    "scripts/qa_audit.py": "reads the TEXT of tests/site_review_bindings.py to prove it derives from the manifest (CONSUMER_CONTRACT)",
    "scripts/capture_kit_page_fixtures.py": "writes tests/fixtures/kit_pages_4586 and imports tests/kit_page_gate.py",
}

# Shrink-only: tooling still in tests/ that a follow-up slice of #4270 moves out.
LEGACY = {
    "scripts/gate_census_structural.py",  # tests/premerge_derivation.py (the pr-checks premerge-lane story)
    "scripts/harvest_eval_fixtures.py",  # tests/golden_surface_eval.py (the golden-brief eval-harness slice -> qa/eval)
}

_PATTERNS = [
    re.compile(r"sys\.path\.(insert|append)\(.*[\"']tests[\"']"),
    re.compile(r"[\"']tests[\"']\s*,\s*[\"'](?!test_)[\w]+\.py[\"']"),
    re.compile(r"/\s*[\"']tests[\"']\s*/\s*[\"'](?!test_)[\w]+\.py[\"']"),
    re.compile(r"^QA_MANIFEST\s*=\s*[\"']tests/"),
    re.compile(r"sys\.path\.(insert|append)\(\s*\w*\s*,?\s*tests_dir"),
    re.compile(r"^for _p in .*[\"']tests[\"']"),
]


def _offenders() -> set:
    out = set()
    for sub in ("deploy", "scripts"):
        for p in (ROOT / sub).glob("*.py"):
            rel = p.relative_to(ROOT).as_posix()
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                s = line.strip()
                if s.startswith("#"):
                    continue
                if any(pat.search(s) for pat in _PATTERNS):
                    out.add(rel)
                    break
    return out


def test_no_new_deploy_or_scripts_module_reaches_into_tests():
    found = _offenders()
    allowed = LEGACY | set(EXEMPT)
    new = sorted(found - allowed)
    stale = sorted(allowed - found)
    moved_back = sorted(set(MOVED_CLEAN) & found)
    assert (
        not new
    ), f"deploy/ or scripts/ module now reaches into tests/ (move the module to qa/ instead, leaving a bare-name re-export shim in tests/ if tests import it): {new}"
    assert not moved_back, f"already-moved files regressed to importing tests/: {moved_back}"
    assert not stale, f"LEGACY / EXEMPT entries no longer reach into tests/ — delete them from the ledger: {stale}"


_TESTS_NONTEST = re.compile(r"\btests/(?!test_)(?!fixtures/)(?!js/)(?!api_schemas/)([A-Za-z0-9_]+\.py)\b")
_FROM_TESTS = re.compile(r"^\s*(from tests[. ]|import tests\b)", re.M)


def _invocations_outside_tests() -> list:
    """Workflow run-lines, lambdas, qa/ and cdk code that name a tests/<non-test>.py module or import `tests`."""
    hits = []
    roots = [(ROOT / ".github" / "workflows", "*.yml"), (ROOT / "lambdas", "**/*.py"), (ROOT / "qa", "*.py"), (ROOT / "cdk", "**/*.py")]
    for base, pat in roots:
        for p in sorted(base.glob(pat)):
            rel = p.relative_to(ROOT).as_posix()
            text = p.read_text(encoding="utf-8", errors="replace")
            if _FROM_TESTS.search(text):
                hits.append(f"{rel}: imports from tests")
            for line in text.splitlines():
                s = line.strip()
                if s.startswith("#"):
                    continue
                if rel.endswith(".yml") and not re.search(r"\b(python3?|pytest|bash|sh|run:)\b", s):
                    continue
                m = _TESTS_NONTEST.search(s)
                if m and f"tests/{m.group(1)}" in SHIMS:
                    hits.append(f"{rel}: names the shim tests/{m.group(1)}")
                    break
    return hits


def test_no_workflow_lambda_or_qa_module_names_a_tests_shim_or_imports_tests():
    """A workflow run-line / lambda / qa module that names tests/visual_qa.py (a shim) or does `from tests.` is the
    coupling #4270 removes - the real path is qa/<name>.py (scripts/mypy_clean_set.py for the mypy set)."""
    hits = _invocations_outside_tests()
    assert not hits, f"these reach through tests/ to a moved module: {hits}"


def test_every_shim_is_a_thin_alias_for_its_real_module():
    """A shim carries no logic of its own: it loads the real file and aliases itself to it."""
    for rel in sorted(SHIMS):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "sys.modules[__name__] = _mod" in text, f"{rel} is not a pure alias shim"
        assert len(text.splitlines()) < 45, f"{rel} grew logic - a shim must stay a re-export"
