"""Tests for #2831 — the API-before-frontend pre-merge sequencing check.

site/** merges auto-deploy with no approval gate (#750); site-api's deploy is
a separate pipeline behind manual production approval. A PR that adds a new
`/api/...` route AND the site/ page that consumes it in the same PR has fired
this class >=5 times (docs/INCIDENT_LOG.md: 2026-07-09 #900 x2 rollbacks —
the canonical shape — 2026-07-12, 2026-07-19, 2026-07-23 #1704 "a recurrence
of the 2026-07-09 class", 2026-08-02 #2040) with only reflex-level fixes
every time.

The acceptance box for this issue is explicit: prove the check on a REPLAY of
one historical incident SHAPE. `test_replay_1704_broadcast_incident_*` below
reconstructs #1704 exactly — `/api/broadcast` added to ROUTES in the same PR
that adds a `site/` file fetching it — and asserts:
  1. undeclared, this check would have FAILED the PR pre-merge (the fix
     #1704 needed but didn't have);
  2. with a `pending_deploy_routes` entry declared (the #2050 pattern this
     issue generalizes), the same PR passes.
"""

import json
import os
import subprocess
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")

sys.path.insert(0, SCRIPTS_DIR)
import check_api_before_frontend as cabf  # noqa: E402

# ══════════════════════════════════════════════════════════════════════════
# 1. extract_declared_routes — pure AST parsing
# ══════════════════════════════════════════════════════════════════════════

_ROUTES_SOURCE_BASE = """
def handle_vitals(event):
    pass


def handle_journey(event):
    pass


ROUTES = {
    "/api/vitals": handle_vitals,
    "/api/journey": handle_journey,
}

_SIMPLE_ROUTES = {
    "/api/nudge": ({"POST"}, handle_vitals),
}
"""

_ROUTES_SOURCE_WITH_BROADCAST = """
def handle_vitals(event):
    pass


def handle_journey(event):
    pass


def handle_broadcast(event):
    pass


ROUTES = {
    "/api/vitals": handle_vitals,
    "/api/journey": handle_journey,
    "/api/broadcast": handle_broadcast,
}

_SIMPLE_ROUTES = {
    "/api/nudge": ({"POST"}, handle_vitals),
}
"""


def test_extract_declared_routes_reads_both_tables():
    routes = cabf.extract_declared_routes(_ROUTES_SOURCE_BASE)
    assert routes == {"/api/vitals", "/api/journey", "/api/nudge"}


def test_extract_declared_routes_empty_or_none_source():
    assert cabf.extract_declared_routes("") == set()
    assert cabf.extract_declared_routes(None) == set()
    assert cabf.extract_declared_routes("not valid python (((") == set()


def test_extract_declared_routes_finds_real_routes():
    """Regression-proof against the actual lambdas/web/site_api_lambda.py shape."""
    with open(os.path.join(REPO_ROOT, "lambdas", "web", "site_api_lambda.py"), encoding="utf-8") as f:
        source = f.read()
    routes = cabf.extract_declared_routes(source)
    assert "/api/vitals" in routes
    assert "/api/broadcast" in routes, "the #1704 route itself should be discoverable in the real file"
    assert "/api/replicate_certify" in routes, "_SIMPLE_ROUTES entries must be found too"


def test_diff_new_routes():
    added = cabf.diff_new_routes(_ROUTES_SOURCE_BASE, _ROUTES_SOURCE_WITH_BROADCAST)
    assert added == {"/api/broadcast"}


def test_diff_new_routes_brand_new_file_treats_base_as_empty():
    added = cabf.diff_new_routes(None, _ROUTES_SOURCE_WITH_BROADCAST)
    assert "/api/broadcast" in added


# ══════════════════════════════════════════════════════════════════════════
# 2. find_at_risk_routes — substring search over touched site/ files
# ══════════════════════════════════════════════════════════════════════════


def test_find_at_risk_routes_matches_referenced_route():
    site_files = {"site/assets/js/dispatches.js": "fetch('/api/broadcast').then(r => r.json())"}
    at_risk = cabf.find_at_risk_routes({"/api/broadcast", "/api/unrelated"}, site_files)
    assert at_risk == {"/api/broadcast"}


def test_find_at_risk_routes_empty_when_not_referenced():
    site_files = {"site/assets/js/other.js": "console.log('nothing here')"}
    assert cabf.find_at_risk_routes({"/api/broadcast"}, site_files) == set()


# ══════════════════════════════════════════════════════════════════════════
# 3. evaluate() — the full decision
# ══════════════════════════════════════════════════════════════════════════


def test_evaluate_passes_when_only_lambdas_touched():
    result = cabf.evaluate(
        changed_files=["lambdas/web/site_api_lambda.py"],
        base_routes_source=_ROUTES_SOURCE_BASE,
        head_routes_source=_ROUTES_SOURCE_WITH_BROADCAST,
        site_file_contents={},
        registry={"sequenced_routes": [], "pending_deploy_routes": []},
    )
    assert result.ok


def test_evaluate_passes_when_only_site_touched():
    result = cabf.evaluate(
        changed_files=["site/story/broadcast/index.html"],
        base_routes_source=_ROUTES_SOURCE_BASE,
        head_routes_source=_ROUTES_SOURCE_WITH_BROADCAST,
        site_file_contents={"site/story/broadcast/index.html": "no fetch here"},
        registry={"sequenced_routes": [], "pending_deploy_routes": []},
    )
    assert result.ok


def test_evaluate_passes_when_no_new_route_added():
    result = cabf.evaluate(
        changed_files=["lambdas/web/site_api_lambda.py", "site/story/broadcast/index.html"],
        base_routes_source=_ROUTES_SOURCE_WITH_BROADCAST,
        head_routes_source=_ROUTES_SOURCE_WITH_BROADCAST,  # unchanged route table
        site_file_contents={"site/story/broadcast/index.html": "fetch('/api/broadcast')"},
        registry={"sequenced_routes": [], "pending_deploy_routes": []},
    )
    assert result.ok


def test_evaluate_passes_when_new_route_not_referenced_by_touched_site_file():
    result = cabf.evaluate(
        changed_files=["lambdas/web/site_api_lambda.py", "site/unrelated/index.html"],
        base_routes_source=_ROUTES_SOURCE_BASE,
        head_routes_source=_ROUTES_SOURCE_WITH_BROADCAST,
        site_file_contents={"site/unrelated/index.html": "nothing about broadcast here"},
        registry={"sequenced_routes": [], "pending_deploy_routes": []},
    )
    assert result.ok


# ══════════════════════════════════════════════════════════════════════════
# 4. THE REPLAY — reconstructing the #1704 incident shape (the acceptance box)
# ══════════════════════════════════════════════════════════════════════════

_DISPATCHES_JS_WITH_BROADCAST_FETCH = """
// site/assets/js/dispatches.js — the #1704 shape
const SECTIONS = {
  broadcast: {
    load: () => fetch('/api/broadcast').then(r => r.json()),
  },
};
"""


def test_replay_1704_broadcast_incident_undeclared_reds_the_check():
    """#1704 (2026-07-23): a single PR added `/api/broadcast` to ROUTES AND a
    site/ file fetching it, with nothing anywhere declaring the sequencing
    risk. This is exactly what shipped: site/** auto-deployed, hit 404
    against site-api (not yet deployed), and rolled back — the log's own
    words: "a recurrence of the 2026-07-09 API-before-frontend class".

    Had this check existed, it would have failed the PR pre-merge instead of
    letting CI discover the race live and auto-rollback the whole site.
    """
    result = cabf.evaluate(
        changed_files=["lambdas/web/site_api_lambda.py", "site/assets/js/dispatches.js"],
        base_routes_source=_ROUTES_SOURCE_BASE,
        head_routes_source=_ROUTES_SOURCE_WITH_BROADCAST,
        site_file_contents={"site/assets/js/dispatches.js": _DISPATCHES_JS_WITH_BROADCAST_FETCH},
        registry={"sequenced_routes": [], "pending_deploy_routes": []},
    )
    assert not result.ok, "the #1704 incident shape must fail the check when undeclared"
    assert result.undeclared_routes == {"/api/broadcast"}
    assert "/api/broadcast" in result.reason


def test_replay_1704_broadcast_incident_passes_with_pending_deploy_declaration():
    """The fix path: declaring the route in pending_deploy_routes (the #2050
    pattern this issue generalizes) lets the same PR pass — and that same
    registry entry is what tests/visual_qa.py + deploy/smoke_test_site.sh
    read to downgrade the resulting 404 to a warning instead of a rollback.
    """
    registry = {
        "sequenced_routes": [],
        "pending_deploy_routes": [
            {"route": "/api/broadcast", "pr": 1704, "date": "2026-07-23", "reason": "site-api deploy lags site auto-deploy"}
        ],
    }
    result = cabf.evaluate(
        changed_files=["lambdas/web/site_api_lambda.py", "site/assets/js/dispatches.js"],
        base_routes_source=_ROUTES_SOURCE_BASE,
        head_routes_source=_ROUTES_SOURCE_WITH_BROADCAST,
        site_file_contents={"site/assets/js/dispatches.js": _DISPATCHES_JS_WITH_BROADCAST_FETCH},
        registry=registry,
    )
    assert result.ok, result.reason


def test_replay_1704_broadcast_incident_passes_with_sequenced_declaration():
    """The other declaration path: `sequenced_routes` ("the API is already
    deployed, no risk") also satisfies the check."""
    registry = {
        "sequenced_routes": [
            {"route": "/api/broadcast", "pr": 1704, "date": "2026-07-23", "reason": "site-api deployed manually ahead of merge"}
        ],
        "pending_deploy_routes": [],
    }
    result = cabf.evaluate(
        changed_files=["lambdas/web/site_api_lambda.py", "site/assets/js/dispatches.js"],
        base_routes_source=_ROUTES_SOURCE_BASE,
        head_routes_source=_ROUTES_SOURCE_WITH_BROADCAST,
        site_file_contents={"site/assets/js/dispatches.js": _DISPATCHES_JS_WITH_BROADCAST_FETCH},
        registry=registry,
    )
    assert result.ok, result.reason


# ══════════════════════════════════════════════════════════════════════════
# 5. Registry loading + the wired-up consumers
# ══════════════════════════════════════════════════════════════════════════


def test_load_registry_real_file_is_well_formed():
    registry = cabf.load_registry()
    assert isinstance(registry.get("sequenced_routes"), list)
    assert isinstance(registry.get("pending_deploy_routes"), list)


def test_load_registry_missing_file_is_fail_soft(tmp_path):
    registry = cabf.load_registry(str(tmp_path / "does_not_exist.json"))
    assert registry == {"sequenced_routes": [], "pending_deploy_routes": []}


def test_declared_routes_unions_both_buckets():
    registry = {
        "sequenced_routes": [{"route": "/api/a"}],
        "pending_deploy_routes": [{"route": "/api/b"}],
    }
    assert cabf.declared_routes(registry) == {"/api/a", "/api/b"}


def test_visual_qa_reads_the_same_registry_module():
    """tests/visual_qa.py must derive pending_deploy_apis from
    deploy/api_deploy_sequencing.json, not a bare hand-edited set literal —
    the exact drift #2050 could recur without this."""
    with open(os.path.join(REPO_ROOT, "tests", "visual_qa.py"), encoding="utf-8") as f:
        source = f.read()
    assert "api_deploy_sequencing.json" in source
    assert "pending_deploy_apis: set = set()" not in source, "the old hand-edited-per-incident literal should be gone"


def test_smoke_script_reads_the_same_registry():
    with open(os.path.join(REPO_ROOT, "deploy", "smoke_test_site.sh"), encoding="utf-8") as f:
        source = f.read()
    assert "api_deploy_sequencing.json" in source
    assert "pending_deploy_routes" in source


def test_pr_checks_workflow_wires_the_check():
    with open(os.path.join(REPO_ROOT, ".github", "workflows", "pr-checks.yml"), encoding="utf-8") as f:
        source = f.read()
    assert "check_api_before_frontend.py" in source
    # The existing required job's identity must survive untouched (its own
    # header warns: renaming `name:`, adding a `paths:` filter to the
    # pull_request trigger, or a job-level `if:` silently un-requires it).
    assert "name: Collect + deploy-critical + format" in source
    assert "name: PR checks" in source


# ══════════════════════════════════════════════════════════════════════════
# 6. CLI smoke test — the script runs end-to-end against the real repo
# ══════════════════════════════════════════════════════════════════════════


def test_cli_runs_against_real_repo_and_exits_zero_when_no_risk():
    """Smoke test of main(): against HEAD vs itself there is no diff, so no
    web+site overlap — the CLI must exit 0 without needing network or a real
    PR context."""
    proc = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS_DIR, "check_api_before_frontend.py"), "--base-ref", "HEAD", "--head-ref", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_registry_json_is_valid():
    with open(os.path.join(REPO_ROOT, "deploy", "api_deploy_sequencing.json"), encoding="utf-8") as f:
        data = json.load(f)
    assert "sequenced_routes" in data
    assert "pending_deploy_routes" in data
