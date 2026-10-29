"""tests/test_check_pip_audit_5473.py — the layer manifests are scanned, and a scan that
cannot run is red (#5473).

The life-platform-pip-audit Lambda never scanned a layer manifest: python3.12 ships no pip,
every non-empty manifest errored, and the report read 0 vulnerabilities with no hard-fail
reason. CI skipped the manifests on the assumption the Lambda covered them. Pinned here:

  * scripts/check_pip_audit.py verdicts — CLEAN only when every pin came back scanned;
    a finding is VULNERABLE; pip-audit missing, non-JSON output, a non-zero exit with no
    finding, or zero dependencies is ERROR, and ERROR exits 1 like a finding.
  * NEGATIVE CONTROL: a fixture manifest pinned to `pillow==12.3.0` (the version the 41
    Dependabot advisories were filed against) makes `--layers` exit 1. pip-audit is stubbed
    with an advisory table shaped like its real JSON. The real run was watched on the lane
    and is recorded in the PR (39 advisories on pillow 12.3.0, exit 1).
  * The allowlist's `scope=` is honoured per manifest: the retired garth layer's dismissed
    certifi advisory (GHSA-6q48-6c7w-9gw2) is waived on lambdas/requirements/garmin.txt and
    nowhere else. The same bytes at another path red.
  * Wiring: layer-pip-audit.yml runs `--layers` on schedule, dispatch and PRs touching the
    manifests; ci-lint's blocking step runs `--resolve` on the dev + CDK manifests through
    the same parser.
  * The Lambda: a scan error is a hard_fail_reason, so the invocation raises after the
    artifact is written.

No network and no AWS: pip-audit is a fake runner, S3 is a recording fake.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import types

import pytest
import yaml

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "scripts"))
sys.path.insert(0, str(_REPO / "lambdas"))
os.environ.setdefault("S3_BUCKET", "test-bucket")

import check_pip_audit as pam  # noqa: E402
from operational import pip_audit_lambda as pa  # noqa: E402

# A pip-audit-shaped advisory table: (normalized name, version) -> vulns.
_ADVISORIES = {
    ("pillow", "12.3.0"): [
        {"id": "PYSEC-2026-4327", "aliases": ["GHSA-test-pillow-0001"], "fix_versions": ["13.0.0"]},
        {"id": "PYSEC-2026-4328", "aliases": [], "fix_versions": ["13.0.0"]},
    ],
    ("certifi", "2026.7.22"): [
        {"id": "PYSEC-2026-4320", "aliases": ["GHSA-6q48-6c7w-9gw2"], "fix_versions": ["2026.10.18"]},
        {"id": "PYSEC-2026-4320", "aliases": ["GHSA-6q48-6c7w-9gw2"], "fix_versions": ["2026.10.19"]},
    ],
}


def _fake_pip_audit(cmd):
    """Behaves like `pip-audit -r FILE --format json [--ignore-vuln ID]...` for exact pins:
    one dependency per pin, advisories from _ADVISORIES, an ignore matching id OR alias."""
    req = pathlib.Path(cmd[cmd.index("-r") + 1])
    ignore = {cmd[i + 1] for i, a in enumerate(cmd) if a == "--ignore-vuln"}
    deps = []
    for raw in req.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        name, _, version = line.partition("==")
        vulns = [v for v in _ADVISORIES.get((pam.normalize(name), version), []) if v["id"] not in ignore and not set(v["aliases"]) & ignore]
        deps.append({"name": pam.normalize(name), "version": version, "vulns": vulns})
    rc = 1 if any(d["vulns"] for d in deps) else 0
    return types.SimpleNamespace(returncode=rc, stdout=json.dumps({"dependencies": deps, "fixes": []}), stderr="")


def _proc(rc=0, stdout="", stderr=""):
    return types.SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)


# ── the allowlist parser ────────────────────────────────────────────────────────


def test_allowlist_parses_plain_and_scoped_entries_and_rejects_stray_tokens():
    entries = pam.parse_allowlist(
        "# header\n\nPYSEC-1  # global waiver\nGHSA-x  scope=a.txt,b.txt  # scoped\n   # indented comment\n",
    )
    assert [(e.vuln_id, e.scopes) for e in entries] == [("PYSEC-1", ()), ("GHSA-x", ("a.txt", "b.txt"))]
    assert pam.ignore_ids_for("a.txt", entries) == ["GHSA-x", "PYSEC-1"]
    assert pam.ignore_ids_for("requirements-dev.txt", entries) == ["PYSEC-1"]
    # The pre-#5473 bash parser glued a second token INTO the ID; this one refuses it.
    with pytest.raises(pam.AllowlistError, match="unexpected token"):
        pam.parse_allowlist("PYSEC-1 lambdas/requirements/garmin.txt\n")
    with pytest.raises(pam.AllowlistError, match="empty scope"):
        pam.parse_allowlist("PYSEC-1 scope=\n")


def test_real_allowlist_scopes_the_garth_certifi_waiver_to_garmin_only():
    entries = pam.parse_allowlist(pam.ALLOWLIST_PATH.read_text())
    assert pam.stale_scopes(entries) == [], "every scope= must name a manifest that exists"
    assert "GHSA-6q48-6c7w-9gw2" in pam.ignore_ids_for("lambdas/requirements/garmin.txt", entries)
    for other in ("requirements-dev.txt", "cdk/requirements.txt", "lambdas/requirements/pillow.txt"):
        assert "GHSA-6q48-6c7w-9gw2" not in pam.ignore_ids_for(other, entries), other


def test_a_scope_naming_no_manifest_is_a_usage_error(tmp_path, capsys):
    allow = tmp_path / "allow.txt"
    allow.write_text("GHSA-x scope=lambdas/requirements/nope.txt  # stale\n")
    assert pam.main(["--layers", "--allowlist", str(allow)], runner=_fake_pip_audit) == 2
    assert "names no manifest" in capsys.readouterr().out


# ── verdicts ────────────────────────────────────────────────────────────────────


def test_classify_every_red_shape_and_the_one_green_one():
    clean = json.dumps({"dependencies": [{"name": "pillow", "version": "13.0.0", "vulns": []}]})
    assert pam.classify("m", ["pillow"], _proc(0, clean), True, []).verdict == pam.CLEAN
    vuln = json.dumps({"dependencies": [{"name": "pillow", "version": "12.3.0", "vulns": [{"id": "X", "fix_versions": ["13"]}]}]})
    assert pam.classify("m", ["pillow"], _proc(1, vuln), True, []).verdict == pam.VULNERABLE
    # The Lambda's own failure, verbatim: pip-audit could not run pip, stdout empty.
    no_pip = _proc(1, "", "/var/lang/bin/python3.12: No module named pip")
    res = pam.classify("m", ["pillow"], no_pip, True, [])
    assert res.verdict == pam.ERROR and "No module named pip" in res.detail
    assert pam.classify("m", ["pillow"], _proc(2, clean), True, []).verdict == pam.ERROR, "non-zero exit, no finding"
    assert pam.classify("m", ["pillow"], _proc(0, json.dumps({"dependencies": []})), True, []).verdict == pam.ERROR, "0 deps"
    assert pam.classify("m", ["pillow"], _proc(0, json.dumps({"oops": 1})), True, []).verdict == pam.ERROR
    two = ["pillow", "lameenc"]
    assert pam.classify("m", two, _proc(0, clean), True, []).verdict == pam.ERROR, "a pin the scan did not return"
    skipped = json.dumps({"dependencies": [{"name": "pillow", "skip_reason": "could not resolve"}]})
    assert pam.classify("m", ["pillow"], _proc(0, skipped), True, []).verdict == pam.ERROR
    # Resolve mode keeps the pre-#5473 ci-lint semantics: a skipped transitive dep warns.
    mixed = json.dumps({"dependencies": [{"name": "pillow", "version": "13.0.0", "vulns": []}, {"name": "x", "skip_reason": "editable"}]})
    assert pam.classify("m", ["pillow"], _proc(0, mixed), False, []).verdict == pam.CLEAN


def test_a_runner_that_cannot_start_is_error_not_clean(tmp_path):
    m = tmp_path / "pillow.txt"
    m.write_text("pillow==13.0.0\n")

    def boom(cmd):
        raise FileNotFoundError("pip_audit")

    res = pam.scan_manifest(m, [], True, runner=boom)
    assert res.verdict == pam.ERROR and "did not run" in res.detail


def test_exact_pin_mode_queries_pins_and_resolves_nothing(tmp_path):
    m = tmp_path / "x.txt"
    cmd = pam.pip_audit_command(m, exact_pins=True, ignore_ids=["A"])
    assert "--disable-pip" in cmd and "--no-deps" in cmd and cmd[-2:] == ["--ignore-vuln", "A"]
    assert "--no-deps" not in pam.pip_audit_command(m, exact_pins=False, ignore_ids=[])


# ── the negative control and the live tree ──────────────────────────────────────


def test_NEGATIVE_CONTROL_a_vulnerable_pillow_pin_reds_the_layer_scan(tmp_path, capsys):
    reqs = tmp_path / "requirements"
    reqs.mkdir()
    (reqs / "pillow.txt").write_text("# fixture\npillow==12.3.0\n")
    (reqs / "infra.txt").write_text("# stdlib only\n")
    rc = pam.main(["--layers", "--requirements-dir", str(reqs)], runner=_fake_pip_audit)
    out = capsys.readouterr().out
    assert rc == 1
    assert "PYSEC-2026-4327" in out and "pillow==12.3.0" in out
    assert "::error title=Dependency vulnerability (blocking)::" in out
    assert "EMPTY" in out and "infra.txt" in out


def test_the_scan_that_cannot_run_reds_and_never_reads_zero_vulnerabilities(tmp_path, capsys):
    reqs = tmp_path / "requirements"
    reqs.mkdir()
    (reqs / "pillow.txt").write_text("pillow==13.0.0\n")
    rc = pam.main(["--layers", "--requirements-dir", str(reqs)], runner=lambda cmd: _proc(1, "", "No module named pip"))
    out = capsys.readouterr().out
    assert rc == 1
    assert "pip-audit could not scan (blocking)" in out
    assert "pip-audit clean" not in out and "0 red" not in out and "SCANNED" not in out


def test_the_live_tree_scans_all_three_layer_manifests_and_honours_the_scope(tmp_path, capsys, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert pam.main(["--layers"], runner=_fake_pip_audit) == 0
    out = capsys.readouterr().out
    for name, count in (("pillow", 1), ("lameenc", 1), ("garmin", 18)):
        line = next(ln for ln in out.splitlines() if f"lambdas/requirements/{name}.txt" in ln)
        assert line.startswith("SCANNED") and f"packages={count}" in line, line
    assert "allowlisted: GHSA-6q48-6c7w-9gw2" in out
    assert "lambdas/requirements/pillow.txt" in summary.read_text()
    # The same garmin bytes OUTSIDE the scoped path: the waiver does not travel.
    reqs = tmp_path / "requirements"
    reqs.mkdir()
    (reqs / "garmin.txt").write_text((_REPO / "lambdas" / "requirements" / "garmin.txt").read_text())
    assert pam.main(["--layers", "--requirements-dir", str(reqs)], runner=_fake_pip_audit) == 1
    assert "PYSEC-2026-4320" in capsys.readouterr().out


# ── wiring ──────────────────────────────────────────────────────────────────────


def _workflow(name):
    return yaml.safe_load((_REPO / ".github" / "workflows" / name).read_text())


def test_layer_workflow_runs_the_scan_on_schedule_dispatch_and_manifest_prs():
    wf = _workflow("layer-pip-audit.yml")
    on = wf.get("on", wf.get(True))  # PyYAML reads a bare `on:` key as True
    assert on["schedule"] and "workflow_dispatch" in on
    paths = on["pull_request"]["paths"]
    for p in (
        "lambdas/requirements/**",
        "deploy/build_lambda_layer.py",
        ".github/pip-audit-allowlist.txt",
        "scripts/check_pip_audit.py",
    ):
        assert p in paths, p
    steps = wf["jobs"]["audit"]["steps"]
    runs = [s.get("run", "") for s in steps]
    assert any("python3 scripts/check_pip_audit.py --layers" in r and "|" not in r for r in runs), "unpiped --layers scan"
    filer = next(s for s in steps if s.get("uses") == "./.github/actions/advisory-failure-issue")
    assert "pull_request" in filer["if"] and filer["with"]["workflow-slug"] == "layer-pip-audit"


def test_ci_lint_blocking_step_uses_the_same_parser_for_dev_and_cdk():
    steps = _workflow("ci-lint.yml")["jobs"]["lint"]["steps"]
    step = next(s for s in steps if str(s.get("name", "")).startswith("Dependency Security Scan"))
    assert "python3 scripts/check_pip_audit.py --resolve requirements-dev.txt cdk/requirements.txt" in step["run"]
    assert "--ignore-vuln" not in step["run"], "the allowlist is parsed in ONE place now"


# ── the Lambda: a scan error is a hard fail ─────────────────────────────────────


class _RecordingS3:
    def __init__(self):
        self.puts = []

    def put_object(self, **kw):
        self.puts.append(kw)


def _wire_lambda(monkeypatch, result, installed=True):
    s3 = _RecordingS3()
    monkeypatch.setattr(pa, "s3", s3)
    monkeypatch.setattr(pa, "ensure_pip_audit", lambda: installed)
    monkeypatch.setattr(pa, "list_requirements_files", lambda: ["config/requirements/pillow.txt"])
    monkeypatch.setattr(pa, "download_requirements", lambda key, path: True)
    monkeypatch.setattr(pa, "audit_requirements_file", lambda path, name: dict(result))
    monkeypatch.setattr(pa, "check_layer_manifest_coverage", lambda: [])
    monkeypatch.setattr(pa, "check_alerts_enabled", lambda: {"status": "skipped", "reason": "no token"})
    return s3


def test_lambda_scan_error_is_a_hard_fail_reason_and_raises_after_the_artifact(monkeypatch):
    err = {
        "lambda": "pillow",
        "vulnerabilities": [],
        "packages_checked": 1,
        "status": "error",
        "error_msg": "JSON parse failed. stdout=, stderr=/var/lang/bin/python3.12: No module named pip",
    }
    s3 = _wire_lambda(monkeypatch, err)
    with pytest.raises(RuntimeError, match="scan error on pillow"):
        pa.lambda_handler({"force": True}, None)
    artifact = json.loads(s3.puts[-1]["Body"])
    assert artifact["hard_fail_reasons"] and "No module named pip" in artifact["hard_fail_reasons"][0]


def test_lambda_clean_scan_still_returns_200(monkeypatch):
    s3 = _wire_lambda(monkeypatch, {"lambda": "pillow", "vulnerabilities": [], "packages_checked": 1, "status": "clean"})
    assert pa.lambda_handler({"force": True}, None)["statusCode"] == 200
    assert json.loads(s3.puts[-1]["Body"])["hard_fail_reasons"] == []


def test_lambda_without_pip_audit_raises_instead_of_returning_a_quiet_500(monkeypatch):
    _wire_lambda(monkeypatch, {}, installed=False)
    with pytest.raises(RuntimeError, match="pip-audit not available"):
        pa.lambda_handler({"force": True}, None)
