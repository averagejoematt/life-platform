"""Tests for #1859 — rollback-net residual gaps found in the 2026-07-27 firings
(follow-up to #1848, which seeded the rollback net and proved it with a real
98/99 clean-revert fire):

  1. us-east-1 revert support: `deploy/rollback_lambda.sh` hardcoded us-west-2
     for BOTH the S3 artifact fetch and the `aws lambda` calls. email-subscriber
     (the one us-east-1 function) was the 1 failed revert of 99 ("Lambda
     function not found"). Fix: resolve the Lambda-API region per function from
     ci/lambda_map.json; the S3 artifact bucket (matthew-life-platform) stays
     pinned to us-west-2 regardless — it's the bucket's real home region
     (verified via `aws s3api get-bucket-location`), not a per-function value.

  2. Push-triggered fleet deploys had NO rollback coverage: `deploy_matrix` is
     built by matching each changed file against ci/lambda_map.json's per-
     function source-path entries, so a push that only touches an unmapped
     shared module (the fleet_changed=true trigger) produces an EMPTY matrix
     even though deploy/deploy_fleet.sh actually redeployed (and re-seeded
     deploys/<fn>/previous.zip for, fc18f0c2) every mapped function. The CI
     auto-rollback job tallied 0/0/0 twice on 2026-07-27 (~01:37Z, ~02:27Z).
     Fix: when fleet_changed=true, the rollback job rebuilds its candidate
     list from ci/lambda_map.json (the same source deploy_fleet.sh iterates)
     instead of trusting deploy_matrix.

Both fixes must NOT regress the three-way tally semantics from #1848/5d36b4a9
(reverted / no-artifact / failed) — see test_lambda_map_regions.py for the
underlying region-parity contract these build on.
"""

import json
import os
import re
import subprocess

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ROLLBACK_SCRIPT = os.path.join(REPO_ROOT, "deploy", "rollback_lambda.sh")
LAMBDA_MAP_PATH = os.path.join(REPO_ROOT, "ci", "lambda_map.json")
CI_CD_WORKFLOW = os.path.join(REPO_ROOT, ".github", "workflows", "ci-cd.yml")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ══════════════════════════════════════════════════════════════════════════
# Gap 1: per-function region resolution in rollback_lambda.sh
# ══════════════════════════════════════════════════════════════════════════


def _resolve_region(function_name, lambda_map_path=LAMBDA_MAP_PATH):
    """Source rollback_lambda.sh (main-loop is guarded behind a
    BASH_SOURCE==0 check, #1859, specifically so it can be sourced like this)
    and call the real resolve_region() function — not a Python re-implementation
    that could silently diverge from the shipped logic."""
    script = f"""
set -euo pipefail
LAMBDA_MAP="{lambda_map_path}"
source "{ROLLBACK_SCRIPT}"
resolve_region "{function_name}"
"""
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, f"resolve_region() failed:\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
    return proc.stdout.strip()


def test_resolve_region_email_subscriber_is_us_east_1():
    """The exact function that failed the 2026-07-27 revert ('Lambda function
    not found') must now resolve to its real region."""
    assert _resolve_region("email-subscriber") == "us-east-1"


def test_resolve_region_defaults_to_us_west_2_for_unoverridden_function():
    assert _resolve_region("daily-brief") == "us-west-2"


def test_resolve_region_unmapped_function_defaults_to_us_west_2():
    assert _resolve_region("totally-unmapped-function-xyz") == "us-west-2"


def test_resolve_region_missing_map_file_defaults_to_us_west_2(tmp_path):
    missing = tmp_path / "does_not_exist.json"
    assert _resolve_region("email-subscriber", lambda_map_path=str(missing)) == "us-west-2"


def test_s3_calls_pinned_to_us_west_2_regardless_of_function_region():
    """The matthew-life-platform bucket is physically us-west-2 (confirmed via
    `aws s3api get-bucket-location`) no matter which region the FUNCTION runs
    in. Only the `aws lambda` calls may use the resolved per-function region —
    pointing the S3 read at a per-function region risks addressing a bucket
    name that doesn't (yet) exist in that region."""
    script = _read(ROLLBACK_SCRIPT)
    assert 'S3_REGION="us-west-2"' in script

    s3_calls = re.findall(r"aws s3 (?:ls|cp)[\s\S]*?--region \"\$\w+\"", script)
    assert len(s3_calls) >= 2, f"expected >=2 `aws s3` calls with --region in rollback_lambda.sh, found {len(s3_calls)}"
    for call in s3_calls:
        assert '--region "$S3_REGION"' in call, f"an `aws s3` call does not pin --region to $S3_REGION: {call!r}"


def test_lambda_api_calls_use_resolved_per_function_region():
    """The `aws lambda` calls inside rollback_one() (get-function-configuration
    x2, update-function-code, wait) must use the resolved per-function
    $REGION — never a bare hardcoded region string."""
    script = _read(ROLLBACK_SCRIPT)
    start = script.index("rollback_one() {")
    end = script.index("\n}\n", start)
    body = script[start:end]

    assert 'REGION=$(resolve_region "$FUNCTION_NAME")' in body, "rollback_one() must resolve a per-function region (#1859)"
    lambda_region_uses = body.count('--region "$REGION"')
    assert lambda_region_uses >= 4, f'expected >=4 `aws lambda ... --region "$REGION"` calls in rollback_one(), found {lambda_region_uses}'

    lambda_calls = re.findall(r"aws lambda [\s\S]*?--region \"\$\w+\"", body)
    assert lambda_calls, "expected `aws lambda` calls with --region in rollback_one()"
    for call in lambda_calls:
        assert '--region "$REGION"' in call, f"an `aws lambda` call does not use the resolved $REGION: {call!r}"


def test_lambda_map_email_subscriber_still_declares_us_east_1():
    """Guard against ci/lambda_map.json drifting back to missing the region
    override resolve_region() depends on."""
    with open(LAMBDA_MAP_PATH) as f:
        lambda_map = json.load(f)
    entry = lambda_map["lambdas"]["lambdas/web/email_subscriber_lambda.py"]
    assert entry["region"] == "us-east-1"
    assert entry["function"] == "email-subscriber"


def test_rollback_script_still_sourceable_and_guards_main():
    """The usage-check + rollback loop must be guarded behind the
    BASH_SOURCE==0 check so the script stays both a CLI tool and a sourceable
    unit-testing surface (#1859) — a regression here would break every test
    in this file with an early `exit 1` from the usage check."""
    script = _read(ROLLBACK_SCRIPT)
    assert 'if [ "${BASH_SOURCE[0]}" = "${0}" ]; then' in script
    # bash -n syntax check as a cheap smoke test of the guard's correctness.
    proc = subprocess.run(["bash", "-n", ROLLBACK_SCRIPT], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, f"bash -n failed:\n{proc.stderr}"


# ══════════════════════════════════════════════════════════════════════════
# Gap 2: fleet-aware rollback on push-triggered fleet deploys
# ══════════════════════════════════════════════════════════════════════════


def _rollback_job_body():
    text = _read(CI_CD_WORKFLOW)
    start = text.index("rollback-on-smoke-failure:")
    end = text.index("\n  notify-failure:")
    return text[start:end]


def test_rollback_job_depends_on_plan():
    """Needed so the job can read needs.plan.outputs.fleet_changed."""
    body = _rollback_job_body()
    assert "needs: [reconcile, plan, deploy, smoke-test]" in body


def test_rollback_step_reads_fleet_changed_output():
    body = _rollback_job_body()
    assert "needs.plan.outputs.fleet_changed" in body


def test_rollback_step_rebuilds_matrix_from_lambda_map_on_fleet_push():
    """The fallback query must walk ci/lambda_map.json's .lambdas the same way
    deploy_fleet.sh does (excluding not_deployed) and include both MCP
    functions, which deploy_fleet.sh always redeploys as part of a fleet run."""
    body = _rollback_job_body()
    assert ".lambdas | to_entries[]" in body
    assert "not_deployed" in body
    assert "life-platform-mcp-warmer" in body
    assert 'FLEET_CHANGED = "true"' in body or 'if [ "$FLEET_CHANGED" = "true" ]' in body


def test_standalone_mcp_rollback_skipped_when_fleet_fallback_used():
    """Avoid a redundant double-rollback attempt on life-platform-mcp: the
    standalone-MCP branch must be gated on the fleet fallback NOT having run
    (deploy_fleet.sh — and therefore the fallback list — always covers MCP)."""
    body = _rollback_job_body()
    assert 'if [ "$MCP_CHANGED" = "true" ] && [ "$FLEET_FALLBACK" = "false" ]' in body


def test_fleet_fallback_jq_query_produces_a_real_full_fleet_list():
    """Run the exact fallback jq expression from the workflow against the real
    ci/lambda_map.json (kept in sync with the workflow step by hand — the
    substring checks above catch drift on the query's shape) and confirm it
    yields a large, sane function list including the specific functions the
    2026-07-27 fires care about. A count > 50 mirrors the actual 98/99-function
    fleet fire (#1848) — this is not an arbitrary threshold."""
    jq_expr = (
        "[.lambdas | to_entries[] | select((.value.not_deployed // false) | not) | {function: .value.function}]"
        '\n                       + [{function:"life-platform-mcp"}, {function:"life-platform-mcp-warmer"}]'
        "\n                       | unique_by(.function)"
    )
    proc = subprocess.run(["jq", "-c", jq_expr, LAMBDA_MAP_PATH], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, f"fleet-fallback jq expression failed: {proc.stderr}"
    functions = json.loads(proc.stdout)
    assert len(functions) > 50, f"expected a large fleet-wide function list (mirrors the 98/99 fire), got {len(functions)}"
    names = {f["function"] for f in functions}
    assert "email-subscriber" in names
    assert "life-platform-mcp" in names
    assert "life-platform-mcp-warmer" in names


def test_fleet_fallback_query_text_matches_workflow_verbatim():
    """The jq expression exercised above must actually be the one shipped in
    the workflow — otherwise the previous test proves nothing about what CI
    runs."""
    body = _rollback_job_body()
    assert "select((.value.not_deployed // false) | not) | {function: .value.function}" in body
    assert "unique_by(.function)" in body
