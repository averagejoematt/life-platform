"""#4270 — production tooling (deploy/, scripts/) must not import code from tests/.

tests/ should hold tests and fixtures. Deploy and CI tooling that reaches INTO tests/ (a sys.path insert of
tests/, or a subprocess/path reference to a tests/*.py module) couples the deploy path to the test tree, so
a test-only refactor can break a deploy. The modules deploy/ needed (the page registry and the leak-token
sweep core) now live in qa/ (qa/qa_manifest.py, qa/leak_token_sweep.py) with re-export shims left in tests/.

NOT DONE: deploy/ still reaches into tests/ — three deploy/ files sit in LEGACY below — so #4270's
"deploy/ no longer imports tests/" box stays open. Scope is top-level deploy/*.py and scripts/*.py only;
subdirectories are not swept (measured 2026-10-10: one hit, deploy/archive/patch_visual_qa_log_5xx.py, an
archived one-shot patch script).

This is a shrink-only ledger: LEGACY lists the files that still reach into tests/ (each moves in a later
slice of #4270). A NEW offender fails; a ledger entry that no longer offends also fails (delete it).
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
]

# Shrink-only: still reach into tests/ today (follow-up slices of #4270).
LEGACY = {
    "deploy/sensor_self_test.py",
    "deploy/sentinel_producer_census.py",
    "scripts/api_sweep_check.py",  # qa_manifest (shim-resolved)
    "deploy/capture_api_schemas.py",  # import accuracy_audit
    "scripts/design_sync_capture.py",  # visual_qa, qa_manifest
    "scripts/review_anchor_seal.py",  # tests/qa_manifest.py by path
    "scripts/fresh_eyes_discovery.py",  # visual_qa, visual_ai_qa
    "scripts/capture_kit_page_fixtures.py",
    "scripts/v4_build_sitemap.py",
    "scripts/gate_census_structural.py",
    "scripts/harvest_eval_fixtures.py",
    "scripts/diligence_verify.py",
    "scripts/qa_audit.py",  # path literals of tests/ helper files
    "scripts/mypy_disable_cost.py",  # runs tests/mypy_clean_set.py
    "scripts/generate_platform_model.py",  # reads tests/pair_contract_registry.py
    "scripts/surface_drift_gate.py",  # QA_MANIFEST path literal (loads the shim)
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
    new = sorted(found - LEGACY)
    stale = sorted(LEGACY - found)
    moved_back = sorted(set(MOVED_CLEAN) & found)
    assert (
        not new
    ), f"deploy/ or scripts/ module now reaches into tests/ (move the module to qa/ instead, leaving a re-export shim in tests/): {new}"
    assert not moved_back, f"already-moved files regressed to importing tests/: {moved_back}"
    assert not stale, f"LEGACY entries no longer reach into tests/ — delete them from the ledger: {stale}"
