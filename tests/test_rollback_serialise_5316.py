"""tests/test_rollback_serialise_5316.py — a rollback can never move the fleet backwards past a newer good run (#5316).

THE INCIDENT, 2026-10-24: run 40086869374 (98877ab7e) failed `Smoke test` at 11:04:55Z. Its
auto-rollback ran 11:04:59–11:31:06Z, the next run's Deploy (d944d9521) succeeded inside that
window (11:05:46–11:16:16Z), and the rollback finished LAST: 62 of 113 functions ran older code
than main. The smoke failure itself was a transport timeout — qa-smoke ran 72 s, 76 s and 68 s
(the CLI's automatic retries) against the AWS CLI's 60 s default read timeout, and the step
exited 255 BEFORE deploy/lib/smoke_oracle_decision.py read a payload.

Four fixes, each held here in both directions:
  1. the rollback job shares the deploy job's concurrency group (they serialise);
  2. rollback_lambda.sh reverts a function only while it is live on THIS run's sha (exit 3 =
     SKIPPED_NEWER otherwise);
  3. only an oracle FAIL licenses the rollback (`smoke_verdict=failed_deploy_health`), and the
     invokes no longer carry the 60 s read timeout;
  4. deploy/check_fleet_drift.py reports any function off the expected deploy.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "deploy" / "lib"
WF = ROOT / ".github" / "workflows" / "ci-cd.yml"

THIS_RUN = "98877ab7e" + "0" * 31
NEWER_RUN = "d944d9521" + "1" * 31


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


oracle = _load("_smoke_oracle_5316", LIB / "smoke_oracle_decision.py")
cgr = _load("_canary_gate_retry_5316", LIB / "canary_gate_retry.py")
drift = _load("_check_fleet_drift_5316", ROOT / "deploy" / "check_fleet_drift.py")


def _jobs():
    return yaml.safe_load(WF.read_text(encoding="utf-8"))["jobs"]


# ── 3. only an oracle FAIL licenses the rollback ─────────────────────────────────────────
def test_only_an_all_FAIL_verdict_list_licenses_a_rollback():
    assert oracle.rollback_verdict(["FAIL"]) == "failed_deploy_health"
    assert oracle.rollback_verdict(["FAIL", "FAIL"]) == "failed_deploy_health"
    # the opposite direction: nothing the oracle did not itself decide may revert code
    for not_a_licence in ([], ["PARSE_ERROR"], ["FAIL", "PARSE_ERROR"], ["FAIL", cgr.INVOKE_ERROR], ["PASS"], [cgr.INVOKE_ERROR]):
        assert oracle.rollback_verdict(not_a_licence) is None, not_a_licence


def test_the_oracle_cli_writes_the_licence_on_FAIL_and_never_on_PARSE_ERROR(tmp_path):
    fail = tmp_path / "fail.json"
    fail.write_text(json.dumps({"statusCode": 200, "body": {"failed_deploy_health": 1}}), encoding="utf-8")
    garbage = tmp_path / "garbage.json"
    garbage.write_text("Read timeout on endpoint URL", encoding="utf-8")
    for payload, expect_licence in ((fail, True), (garbage, False)):
        out = tmp_path / f"out-{payload.stem}"
        proc = subprocess.run(
            [sys.executable, str(LIB / "smoke_oracle_decision.py"), str(payload), "Smoke test"],
            capture_output=True,
            text=True,
            env={**os.environ, "GITHUB_OUTPUT": str(out)},
        )
        assert proc.returncode == 1, proc.stdout  # both still fail the pipeline
        written = out.read_text(encoding="utf-8") if out.exists() else ""
        assert ("smoke_verdict=failed_deploy_health" in written) is expect_licence, (payload.name, written)


def test_a_canary_invoke_error_gates_but_is_not_an_oracle_FAIL(monkeypatch, tmp_path):
    seen = {}

    class Proc:
        returncode, stdout, stderr = 255, "", "Read timeout on endpoint URL"

    def fake_run(cmd, **_kw):
        seen["cmd"] = cmd
        return Proc()

    monkeypatch.setattr(cgr.subprocess, "run", fake_run)
    verdict, detail = cgr._aws_invoke("life-platform-canary", "us-west-2", tmp_path / "c.json", "Canary", ())(1)
    assert verdict == cgr.INVOKE_ERROR and cgr.is_gating(verdict) and "255" in detail
    assert oracle.rollback_verdict([verdict, verdict]) is None
    cmd = seen["cmd"]
    assert cmd[cmd.index("--cli-read-timeout") + 1] == "0", "the canary invoke still carries the CLI's 60 s read timeout"
    assert "--cli-connect-timeout" in cmd


def test_the_workflow_gates_the_rollback_on_the_oracle_verdict_and_drops_the_read_timeout():
    jobs = _jobs()
    smoke = jobs["smoke-test"]
    out = smoke["outputs"]["smoke_verdict"]
    assert "steps.smoke.outputs.smoke_verdict" in out and "steps.canary.outputs.smoke_verdict" in out
    ids = {s.get("id"): s for s in smoke["steps"] if isinstance(s, dict)}
    assert ids["smoke"]["name"] == "Run QA smoke test" and ids["canary"]["name"] == "Verify canary"
    invoke = ids["smoke"]["run"].split("--function-name life-platform-qa-smoke", 1)[1].split("/tmp/smoke.json", 1)[0]
    assert "--cli-read-timeout 0" in invoke and "--cli-connect-timeout" in invoke
    cond = jobs["rollback-on-smoke-failure"]["if"]
    assert "needs.smoke-test.outputs.smoke_verdict == 'failed_deploy_health'" in cond
    assert "needs.smoke-test.result == 'failure'" in cond and cond.strip().startswith("always()")


# ── 1. a rollback and a deploy serialise ─────────────────────────────────────────────────
def test_the_rollback_job_shares_the_deploy_jobs_concurrency_group_and_the_gate_does_not():
    jobs = _jobs()
    deploy, rollback = jobs["deploy"]["concurrency"], jobs["rollback-on-smoke-failure"].get("concurrency")
    assert rollback, "the rollback job has no concurrency group — it can overlap a newer deploy again (#5316)"
    assert rollback["group"] == deploy["group"] == "ci-cd-deploy-${{ github.ref }}"
    assert rollback["cancel-in-progress"] is False and deploy["cancel-in-progress"] is False
    # #2467: a job parked at an environment gate must never hold this slot.
    assert "concurrency" not in jobs["deploy-iam"]
    assert jobs["rollback-on-smoke-failure"]["environment"] == "ungated-deploy"


# ── 2. the rollback reverts only what this run still owns ────────────────────────────────
def test_owner_check_is_pure_and_names_each_outcome():
    assert drift.owner_check(THIS_RUN, [THIS_RUN])[0] == drift.OWNER_OK
    assert drift.owner_check(THIS_RUN[:9], [THIS_RUN])[0] == drift.OWNER_OK  # short sha = same commit
    code, msg = drift.owner_check(NEWER_RUN, [THIS_RUN])
    assert code == drift.OWNER_NEWER == 3 and "SKIPPED_NEWER" in msg
    assert drift.owner_check(None, [THIS_RUN])[0] == drift.OWNER_UNKNOWN


def _bundle(path: Path, sha: str | None):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("handler.py", "def lambda_handler(e, c):\n    return 1\n" * 20)
        if sha:
            zf.writestr("build_info.json", json.dumps({"git_sha": sha}))


def _fake_aws(tmp_path: Path, live_sha: str) -> dict:
    """A PATH-first `aws` that serves a live bundle stamped `live_sha` and logs every call."""
    live, prev, log = tmp_path / "live.zip", tmp_path / "prev.zip", tmp_path / "aws.log"
    _bundle(live, live_sha)
    _bundle(prev, "0ldc0de" + "2" * 33)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    aws = bindir / "aws"
    aws.write_text(
        f"""#!/bin/bash
echo "$*" >> "{log}"
case "$1 $2" in
  "s3 ls") exit 0 ;;
  "s3 cp") cp "{prev}" "$4"; exit 0 ;;
  "lambda get-function") echo "file://{live}"; exit 0 ;;
  "lambda get-function-configuration") echo "2026-10-24T11:20:45Z"; exit 0 ;;
  "lambda update-function-code"|"lambda wait") exit 0 ;;
esac
exit 1
""",
        encoding="utf-8",
    )
    aws.chmod(aws.stat().st_mode | stat.S_IXUSR)
    return {"PATH": f"{bindir}:{os.environ['PATH']}", "log": log}


def _rollback_one(tmp_path, live_sha, expect):
    fake = _fake_aws(tmp_path, live_sha)
    env = {**os.environ, "PATH": fake["PATH"], "ROLLBACK_EXPECT_SHA": expect}
    proc = subprocess.run(
        ["bash", str(ROOT / "deploy" / "rollback_lambda.sh"), "daily-brief"], capture_output=True, text=True, env=env, timeout=120
    )
    return proc, fake["log"].read_text(encoding="utf-8")


def test_THE_INCIDENT_a_function_a_newer_deploy_owns_is_SKIPPED_NEWER_and_never_written(tmp_path):
    proc, calls = _rollback_one(tmp_path, NEWER_RUN, f"{THIS_RUN} {THIS_RUN}")
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "SKIPPED_NEWER" in proc.stdout
    assert "update-function-code" not in calls, "the rollback wrote over a newer deploy"


def test_MUST_FAIL_control_a_function_this_run_still_owns_IS_reverted(tmp_path):
    proc, calls = _rollback_one(tmp_path, THIS_RUN, f"{THIS_RUN},{'f' * 40}")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "update-function-code" in calls


def test_an_unreadable_live_sha_is_left_on_current_code(tmp_path):
    proc, calls = _rollback_one(tmp_path, None, THIS_RUN)
    assert proc.returncode == 3 and "update-function-code" not in calls


def test_the_fleet_rollback_tallies_skipped_newer_and_does_not_fail_on_it(tmp_path):
    fake = _fake_aws(tmp_path, NEWER_RUN)
    lm = tmp_path / "map.json"
    lm.write_text(
        json.dumps({"lambdas": {"a.py": {"function": "daily-brief"}, "b.py": {"function": "x", "not_deployed": True}}}), encoding="utf-8"
    )
    env = {**os.environ, "PATH": fake["PATH"], "ROLLBACK_EXPECT_SHA": THIS_RUN, "LAMBDA_MAP": str(lm)}
    proc = subprocess.run(["bash", str(ROOT / "deploy" / "rollback_fleet.sh")], capture_output=True, text=True, env=env, timeout=300)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "0 reverted, 0 no-artifact (left on current code), 3 skipped-newer" in proc.stdout  # daily-brief + both MCP
    assert "::warning::3 function(s) SKIPPED_NEWER" in proc.stdout
    assert "update-function-code" not in fake["log"].read_text(encoding="utf-8")


def test_the_workflow_hands_this_runs_shas_to_the_fleet_rollback():
    steps = {s.get("name"): s for s in _jobs()["rollback-on-smoke-failure"]["steps"]}
    step = steps["Rollback deployed Lambdas"]
    assert step["run"].strip() == "bash deploy/rollback_fleet.sh"
    assert "github.sha" in step["env"]["ROLLBACK_EXPECT_SHA"] and "needs.reconcile.outputs.build_sha" in step["env"]["ROLLBACK_EXPECT_SHA"]


# ── 4. the drift check ───────────────────────────────────────────────────────────────────
def test_compare_buckets_every_function_and_drift_exits_1():
    live = {"daily-brief": THIS_RUN, "life-platform-mcp": NEWER_RUN, "canary": None, "site-api": THIS_RUN[:9]}
    res = drift.compare(live, [THIS_RUN])
    assert res["on_expected"] == ["daily-brief", "site-api"]
    assert res["drifted"] == {"life-platform-mcp": NEWER_RUN}
    assert res["unverified"] == ["canary"]
    assert drift.verdict(res, [THIS_RUN]) == drift.EXIT_DRIFT
    text = drift.render(res, [THIS_RUN])
    assert "DRIFT: 1 function(s)" in text and "life-platform-mcp" in text and "UNVERIFIED: 1" in text


def test_a_uniform_fleet_is_clean_and_an_unreadable_one_is_never_clean():
    assert drift.verdict(drift.compare({"a": THIS_RUN, "b": THIS_RUN}, [THIS_RUN]), [THIS_RUN]) == drift.EXIT_OK
    assert drift.verdict(drift.compare({"a": THIS_RUN, "b": None}, [THIS_RUN]), [THIS_RUN]) == drift.EXIT_INDETERMINATE
    # no expected sha resolved: a histogram, never a fabricated drift list
    res = drift.compare({"a": THIS_RUN, "b": NEWER_RUN}, [])
    assert res["drifted"] == {} and drift.verdict(res, []) == drift.EXIT_INDETERMINATE


OLDER_RUN = "0ldc0de" + "2" * 33
LATER_MAIN = "6984087e0" + "3" * 31


def _history(a, b):
    """A fake git: OLDER_RUN -> NEWER_RUN -> LATER_MAIN on main; anything unknown is None."""
    order = [OLDER_RUN, NEWER_RUN, LATER_MAIN]
    if a in order and b in order:
        return order.index(a) <= order.index(b)
    return None


def test_deploy_base_mode_reads_a_later_main_deploy_as_ahead_and_the_incident_as_drift():
    # 2026-10-25: the attended fleet redeploy from 6984087e0 sits on top of CI's last deploy.
    res = drift.compare({"a": LATER_MAIN, "b": NEWER_RUN}, [NEWER_RUN], is_ancestor=_history)
    assert res["ahead"] == {"a": LATER_MAIN} and res["on_expected"] == ["b"] and not res["drifted"]
    assert drift.verdict(res, [NEWER_RUN]) == drift.EXIT_OK
    # 2026-10-24: the rollback put functions on code OLDER than the newest successful deploy.
    res = drift.compare({"daily-brief": OLDER_RUN, "mcp": NEWER_RUN}, [NEWER_RUN], is_ancestor=_history)
    assert res["drifted"] == {"daily-brief": OLDER_RUN} and drift.verdict(res, [NEWER_RUN]) == drift.EXIT_DRIFT
    # git cannot tell (shallow clone): never read as ahead
    res = drift.compare({"x": "abcdef1" + "4" * 33}, [NEWER_RUN], is_ancestor=_history)
    assert list(res["drifted"]) == ["x"]
    # the deploy-job mode (no ancestry) holds the exact sha: a descendant is still a mismatch there
    assert list(drift.compare({"a": LATER_MAIN}, [NEWER_RUN])["drifted"]) == ["a"]


def test_the_fleet_list_is_the_one_deploy_fleet_ships():
    fns = drift.fleet_functions()
    assert {"life-platform-mcp", "life-platform-mcp-warmer", "daily-brief"} <= set(fns)
    assert fns["email-subscriber"] == "us-east-1"
    rows = json.loads((ROOT / "ci" / "lambda_map.json").read_text(encoding="utf-8"))["lambdas"].values()
    assert not {r["function"] for r in rows if r.get("not_deployed")} & set(fns)


def test_main_with_fakes_reports_the_post_rollback_drift_against_the_deploy_base(tmp_path, monkeypatch, capsys):
    out = tmp_path / "gh_out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))

    def live(fns):
        return {fn: (NEWER_RUN if fn == "daily-brief" else THIS_RUN) for fn in fns}

    code = drift.main(["--expect-deploy-base"], collect_live=live, resolve_base=lambda: THIS_RUN, is_ancestor=lambda _a, _b: False)
    assert code == drift.EXIT_DRIFT
    printed = capsys.readouterr().out
    assert "daily-brief" in printed and "::error title=Fleet drift (#5316)::1 drifted" in printed
    assert out.read_text(encoding="utf-8").startswith("summary=1 drifted, 0 unverified")


def test_owner_check_cli_uses_the_injected_reader():
    assert drift.main(["--owner-check", "f", "--expect", THIS_RUN], read_one=lambda _f, _r: NEWER_RUN) == 3
    assert drift.main(["--owner-check", "f", "--expect", THIS_RUN], read_one=lambda _f, _r: THIS_RUN) == 0


def test_the_live_sha_read_goes_through_the_deadmans_ranged_reader(tmp_path):
    z = tmp_path / "b.zip"
    _bundle(z, THIS_RUN)
    assert drift.deadman.read_build_sha(f"file://{z}") == THIS_RUN
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("x.py", "")
    (tmp_path / "nofp.zip").write_bytes(buf.getvalue())
    assert drift.deadman.read_build_sha(f"file://{tmp_path / 'nofp.zip'}") is None


def test_the_workflow_runs_the_drift_check_after_the_fleet_deploy_and_after_the_rollback():
    jobs = _jobs()
    names = [s.get("name", "") for s in jobs["deploy"]["steps"]]
    fleet = next(i for i, n in enumerate(names) if n.startswith("Fleet deploy"))
    check = names.index("Fleet drift check (#5316)")
    assert check > fleet
    step = jobs["deploy"]["steps"][check]
    assert step.get("continue-on-error") is True and "check_fleet_drift.py --expect" in step["run"]
    rb = {s.get("name"): s for s in jobs["rollback-on-smoke-failure"]["steps"]}
    post = rb["Post-rollback fleet drift"]
    assert post["if"] == "always()" and "--expect-deploy-base" in post["run"] and post.get("continue-on-error") is True
    assert jobs["rollback-on-smoke-failure"]["permissions"]["actions"] == "read"
