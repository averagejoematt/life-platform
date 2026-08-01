"""#1921 — the smoke oracle must not answer two questions with one verdict.

qa-smoke asks both "is the code that just shipped broken?" (DEPLOY_HEALTH) and
"is the published content honest right now?" (CONTENT_TRUTH). Only the first is
evidence about the deploy in flight and only the first is repaired by reverting
it, yet ci-cd wired the single combined verdict to fleet auto-rollback. Three
healthy fleets were reverted on content findings (2026-07-27: 98 functions on a
dashboard-freshness check; 2026-08-01 00:18Z: 100 functions on a reader_truth
finding about a defect that had been live for weeks).

What is asserted here:

  1. EXHAUSTIVENESS, DERIVED — every Check(...) construction site in the
     operational package is found by AST-walking the source and asserted to pass
     a partition. The set is read out of the code, never enumerated in this file:
     an enumerated list is exactly what #1917 showed silently goes stale (its
     derived registry found 7 fields that reading had missed).
  2. BOTH DIRECTIONS at the gate — a content_truth FAIL must NOT roll back, and
     a deploy_health FAIL still must. A one-sided test would pass just as
     happily against a gate that had been disabled outright.
  3. THE REAL INCIDENT, replayed with the LIVE payload shape recorded in
     CloudWatch on 2026-08-01, not a hand-built fixture that only proves the code
     does what its author wrote.
"""

import ast
import json
import os
import pathlib
import sys
import tempfile

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]

# qa_smoke_lambda reads these at import time (conftest supplies fake AWS creds).
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("EMAIL_RECIPIENT", "qa@example.com")
os.environ.setdefault("EMAIL_SENDER", "qa@example.com")

sys.path.insert(0, str(REPO / "lambdas"))
sys.path.insert(0, str(REPO / "deploy" / "lib"))

import qa_smoke_lambda as qa  # noqa: E402
import smoke_oracle_decision as sod  # noqa: E402

OPERATIONAL = REPO / "lambdas" / "operational"


# ---------------------------------------------------------------------------
# 1. Exhaustiveness — derived from the source, not enumerated here
# ---------------------------------------------------------------------------


def _check_call_sites():
    """Every Check(...) / check_cls(...) construction in the operational package.

    Derived by AST walk so a check added in a new module, or a new call site in
    an existing one, is picked up without anyone remembering to update a list.
    """
    sites = []
    for path in sorted(OPERATIONAL.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("Check", "check_cls"):
                sites.append((path.name, node.lineno, node.func.id, len(node.args), ast.unparse(node)))
    return sites


def test_ast_scan_finds_the_check_sites_at_all():
    """Guard the guard: a scan that silently finds nothing would pass everything."""
    sites = _check_call_sites()
    assert len(sites) >= 30, f"AST scan found only {len(sites)} Check() sites — the scan itself is broken"
    assert any(f == "qa_smoke_lambda.py" for f, *_ in sites)
    assert any(f == "weight_truth_qa.py" for f, *_ in sites)


def test_every_check_construction_supplies_a_partition():
    """No check may be built without deciding which question it answers."""
    unpartitioned = [(f, ln, src) for f, ln, _fn, nargs, src in _check_call_sites() if nargs != 3]
    assert not unpartitioned, "Check(...) built without a partition (#1921):\n" + "\n".join(
        f"  {f}:{ln}  {src[:100]}" for f, ln, src in unpartitioned
    )


def test_partition_is_required_and_validated_at_construction():
    """The constructor — not a convention — is what makes assignment mandatory."""
    with pytest.raises(TypeError):
        qa.Check("x", "cat")  # no partition at all
    with pytest.raises(ValueError):
        qa.Check("x", "cat", "some_new_bucket")  # not a real partition
    assert qa.Check("x", "cat", qa.CONTENT_TRUTH).partition in qa.PARTITIONS


def test_partition_vocabulary_is_exactly_two():
    """A third partition would need a deliberate decision about what gates."""
    assert qa.PARTITIONS == (qa.DEPLOY_HEALTH, qa.CONTENT_TRUTH)


# ---------------------------------------------------------------------------
# 2. The gate — both directions
# ---------------------------------------------------------------------------


def _qa_smoke_result(tmp_path, **body):
    """A qa-smoke invoke result in the real Lambda-proxy shape it returns."""
    body.setdefault("warned", 0)
    body.setdefault("paused", [])
    body.setdefault("emailed", True)
    path = tmp_path / "smoke.json"
    path.write_text(json.dumps({"statusCode": 200, "body": json.dumps(body)}))
    return str(path)


def test_content_truth_failure_does_not_gate_the_deploy():
    """The core re-routing: a content finding must not revert code."""
    with tempfile.TemporaryDirectory() as d:
        path = _qa_smoke_result(pathlib.Path(d), failed=2, failed_deploy_health=0, failed_content_truth=2)
        verdict, detail = sod.decide(path)
    assert verdict == "PASS", f"content-truth failure gated the deploy: {detail}"


def test_deploy_health_failure_still_gates_the_deploy():
    """The net must remain intact — this is the half that still rolls back."""
    with tempfile.TemporaryDirectory() as d:
        path = _qa_smoke_result(pathlib.Path(d), failed=1, failed_deploy_health=1, failed_content_truth=0)
        verdict, detail = sod.decide(path)
    assert verdict == "FAIL"
    assert "failed_deploy_health" in detail


def test_mixed_failure_gates_on_the_deploy_health_half():
    """A content finding alongside a real breakage must not mask the breakage."""
    with tempfile.TemporaryDirectory() as d:
        path = _qa_smoke_result(pathlib.Path(d), failed=5, failed_deploy_health=1, failed_content_truth=4)
        assert sod.decide(path)[0] == "FAIL"


def test_clean_run_passes():
    with tempfile.TemporaryDirectory() as d:
        path = _qa_smoke_result(pathlib.Path(d), failed=0, failed_deploy_health=0, failed_content_truth=0, emailed=False)
        assert sod.decide(path)[0] == "PASS"


def test_missing_partition_key_falls_back_to_the_total_conservatively():
    """An older qa-smoke zip, or the canary, must behave exactly as pre-#1921.

    The deploy job ships the new Lambda before the smoke job reads it, but the
    oracle must never fail OPEN on a payload that predates the split.
    """
    with tempfile.TemporaryDirectory() as d:
        path = _qa_smoke_result(pathlib.Path(d), failed=3)  # no partition keys at all
        verdict, detail = sod.decide(path)
    assert verdict == "FAIL"
    assert "failed=3" in detail


def test_canary_shape_is_untouched_by_the_split():
    """The canary has no partitions — every check it runs IS deploy health."""
    with tempfile.TemporaryDirectory() as d:
        path = pathlib.Path(d) / "canary.json"
        path.write_text(json.dumps({"statusCode": 500, "body": json.dumps({"all_pass": False})}))
        assert sod.decide(str(path), ["healthy"])[0] == "FAIL"


def test_content_truth_failures_are_announced_even_though_they_pass():
    """Re-routing, not muting: the CI surface must still shout about them."""
    with tempfile.TemporaryDirectory() as d:
        path = _qa_smoke_result(pathlib.Path(d), failed=2, failed_deploy_health=0, failed_content_truth=2)
        assert sod.content_truth_count(path) == 2
        assert sod.content_truth_count(_qa_smoke_result(pathlib.Path(d), failed=0, failed_deploy_health=0, failed_content_truth=0)) == 0


# ---------------------------------------------------------------------------
# 3. Replay the incident that motivated this — with the LIVE payload
# ---------------------------------------------------------------------------

# Recorded verbatim from CloudWatch Logs, log group /aws/lambda/life-platform-qa-smoke,
# 2026-08-01T00:18:20.351Z — the run whose FAIL tripped ci-cd run 30674330261's
# smoke-test job at 00:18:22Z and auto-reverted 100 Lambdas at 00:18:29Z. This was
# `reader_truth`'s FIRST execution after 26 consecutive days budget-paused (#1920),
# and it flagged a defect that had been live for weeks — nothing the deploy in
# flight had caused, and nothing reverting it could fix.
INCIDENT_20260801 = {
    "fail_log_lines": [
        "[QA] FAIL Reader Truth / reader_truth:verdict: 2 high truth finding(s) at Day 5: "
        "/api/vitals [impossible_number] weight_delta_30d is -4.8 lbs over 30 days, but the "
        "experiment is only on Day 5 (2026-07-27; /api/vitals [impossible_number] hrv_30d_avg "
        "and hrv_30d_n (5 readings) claim 30-day history on Day 5 of the current experi",
    ],
    "failed": 1,
}


def test_the_2026_08_01_rollback_does_not_fire_under_the_new_logic():
    """The incident, replayed. Same failure; no rollback."""
    # Every failing check that night was Reader Truth — content_truth to a check.
    assert all("Reader Truth" in line for line in INCIDENT_20260801["fail_log_lines"])

    with tempfile.TemporaryDirectory() as d:
        path = _qa_smoke_result(
            pathlib.Path(d),
            failed=INCIDENT_20260801["failed"],
            failed_deploy_health=0,
            failed_content_truth=INCIDENT_20260801["failed"],
        )
        verdict, _ = sod.decide(path)
        assert verdict == "PASS", "the 2026-08-01 incident would still revert 100 Lambdas"
        # ...and it is still shouted about, not swallowed.
        assert sod.content_truth_count(path) == 1


def test_the_same_incident_still_rolls_back_when_it_is_a_real_breakage():
    """Negative control for the replay: identical shape, deploy_health side."""
    with tempfile.TemporaryDirectory() as d:
        path = _qa_smoke_result(pathlib.Path(d), failed=1, failed_deploy_health=1, failed_content_truth=0)
        assert sod.decide(path)[0] == "FAIL"


# ---------------------------------------------------------------------------
# 4. The DR drill must still prove the net fires (#1345)
# ---------------------------------------------------------------------------


def test_dr_drill_check_is_deploy_health():
    """#1345's drill exists to fire the rollback for real — it must still gate."""
    src = (OPERATIONAL / "qa_smoke_lambda.py").read_text()
    tree = ast.parse(src)
    drill = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Check"
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "drill:synthetic"
    ]
    assert len(drill) == 1, "the #1345 synthetic-failure drill check went missing"
    assert (
        isinstance(drill[0].args[2], ast.Name) and drill[0].args[2].id == "DEPLOY_HEALTH"
    ), "the DR drill must be DEPLOY_HEALTH or it stops proving the rollback path fires"


# ---------------------------------------------------------------------------
# 5. #1920's execution receipt — a paused check must not look like a passing one
# ---------------------------------------------------------------------------


def test_paused_checks_are_reported_by_name():
    """`reader_truth` sat budget-paused for 26 days looking green (#1920).

    Check.pause() sets passed=True and printed nothing, so a skipped check and a
    passing check were byte-identical in every recorded signal — which is why its
    precision could not be measured after the fact. The oracle payload now names
    what did not run.
    """
    with tempfile.TemporaryDirectory() as d:
        path = _qa_smoke_result(
            pathlib.Path(d),
            failed=0,
            failed_deploy_health=0,
            failed_content_truth=0,
            paused=["reader_truth:verdict"],
        )
        with open(path) as f:
            body = json.loads(json.load(f)["body"])
        assert body["paused"] == ["reader_truth:verdict"]
        assert sod.decide(path)[0] == "PASS"  # a pause is still not a failure
