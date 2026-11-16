"""tests/test_www_api_readiness.py — the v9 deploy waits for the Site API it reads (run 43124939822, 2026-11-12).

#5827 changed the Site API and the v9 build in one merge; the push-triggered root deploy built and smoke-tested
against the OLD Site API (its code deploy was held behind an owner-required IAM diff) and went red. These tests
hold deploy/www_api_readiness.py's decision, the workflow wiring that makes the deploy depend on it, and the
resume loop that re-dispatches a deferred deploy — with must-fail controls replaying the incident ordering.

The legacy site/** pipeline (site-deploy.yml) carries the same gate since the follow-up: the same module, the
same `check`, its own `deferred` job, resumed by the same web-deploy-resume.yml. The job-graph simulator below
replays the incident state through BOTH workflow files and shows which jobs would run.
"""

import json
import pathlib
import re
import subprocess

import pytest
import yaml

from deploy import www_api_readiness as war

_REPO = pathlib.Path(__file__).resolve().parent.parent
_WF = _REPO / ".github" / "workflows"
_V9 = _WF / "web-preview-deploy.yml"
_RESUME = _WF / "web-deploy-resume.yml"
_SITE = _WF / "site-deploy.yml"

# The incident's real commits: 4c072484b is #5827 (the commit the Site API owed); d15394b45 its parent — the
# newest commit the API could have carried at 00:07Z, every CI/CD run since 22:13Z having failed at Plan.
INCIDENT_OWED = "4c072484b37d2095a8584f42c87865f76f7807c5"
INCIDENT_LIVE = "d15394b45"


def _oracle(edges: set):
    """is_ancestor over a declared set of (ancestor, descendant) pairs — the incident without git."""

    def is_ancestor(a, b):
        return any(a.startswith(x) and b.startswith(y) for x, y in edges)

    return is_ancestor


def _load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def deploy_is_gated(doc: dict, deploy_job: str = "deploy") -> list:
    """Problems with a site workflow's readiness wiring ([] = the deploy waits for the Site API)."""
    jobs = doc.get("jobs") or {}
    out = []
    gate, deploy, deferred = jobs.get("api-readiness"), jobs.get(deploy_job) or {}, jobs.get("deferred")
    if not gate:
        return ["no api-readiness job"]
    steps = gate.get("steps") or []
    if not any("www_api_readiness.py check" in str(s.get("run", "")) for s in steps):
        out.append("api-readiness does not run deploy/www_api_readiness.py check")
    if not any((s.get("with") or {}).get("fetch-depth") == 0 for s in steps if "checkout" in str(s.get("uses", ""))):
        out.append("api-readiness checks out shallow — the owed commit cannot be derived")
    needs = deploy.get("needs") or []
    needs = [needs] if isinstance(needs, str) else needs
    if "api-readiness" not in needs:
        out.append("deploy does not need api-readiness (the pre-fix ordering)")
    if "needs.api-readiness.outputs.ready == 'true'" not in str(deploy.get("if", "")):
        out.append("deploy is not conditioned on ready == 'true'")
    if not deferred or "needs.api-readiness.outputs.ready != 'true'" not in str(deferred.get("if", "")):
        out.append("no deferred job on not-ready")
    return out


# ── the decision ─────────────────────────────────────────────────────────────────────────────
def test_incident_replay_is_not_ready():
    """Must-fail control: the 00:07Z state (live API behind #5827) defers instead of deploying."""
    state, reason = war.decide(INCIDENT_LIVE, INCIDENT_OWED, is_ancestor=_oracle({(INCIDENT_LIVE, INCIDENT_OWED[:9])}))
    assert state == war.NOT_READY, reason
    assert "BEHIND" in reason


def test_after_the_api_lands_it_is_ready():
    # 01:05Z: deploy_site_api.sh shipped a tree containing #5827 → same, or a descendant of the owed commit.
    assert war.decide(INCIDENT_OWED, INCIDENT_OWED, is_ancestor=_oracle(set()))[0] == war.READY
    descendant = "c9adc1b8a4d773aaa3083d13f4251d08ad7c28f9"
    assert war.decide(descendant, INCIDENT_OWED, is_ancestor=_oracle({(INCIDENT_OWED[:9], descendant[:9])}))[0] == war.READY


def test_diverged_is_not_ready_and_unknown_is_unverified():
    assert war.decide("aaaaaaaa1", "bbbbbbbb2", is_ancestor=_oracle(set()))[0] == war.NOT_READY
    assert war.decide(None, "bbbbbbbb2")[0] == war.UNVERIFIED  # no build_info.json on the live bundle
    assert war.decide("aaaaaaaa1", "bbbbbbbb2", is_ancestor=lambda a, b: None)[0] == war.UNVERIFIED


def test_owed_commit_is_the_dead_mans_derivation(monkeypatch):
    """Derivation guard: the function comes from ci/lambda_map.json and the owed commit from the SAME
    collect_owed_commits the stale-Lambda dead-man uses — never a hand-listed route or sha."""
    calls = {}
    fn, _region = war.site_api_function()
    assert fn == json.loads((_REPO / "ci" / "lambda_map.json").read_text())["lambdas"][war.SITE_API_HANDLER]["function"]

    def owed(path, only=None):
        calls["only"] = only
        return {fn: (INCIDENT_OWED, None, "x")}

    monkeypatch.setattr(war.check_deploy_deadman, "collect_owed_commits", owed)
    monkeypatch.setattr(war.check_deploy_deadman, "collect_deployed_shas", lambda fns: {fn: INCIDENT_LIVE})
    monkeypatch.setattr(war.bundle_ancestry, "git_is_ancestor", _oracle({(INCIDENT_LIVE, INCIDENT_OWED[:9])}))
    r = war.evaluate()
    assert calls["only"] == {fn}
    assert r["state"] == war.NOT_READY and r["owed_sha"] == INCIDENT_OWED and r["live_sha"] == INCIDENT_LIVE


def test_only_filter_matches_the_full_derivation():
    """The `only=` narrowing returns exactly the row the full dead-man derivation computes."""
    shallow = subprocess.run(["git", "rev-parse", "--is-shallow-repository"], cwd=_REPO, capture_output=True, text=True).stdout.strip()
    if shallow != "false":
        pytest.skip("needs full git history")
    import os

    cwd = os.getcwd()
    os.chdir(_REPO)
    try:
        fn, _ = war.site_api_function()
        full = war.check_deploy_deadman.collect_owed_commits("ci/lambda_map.json")
        one = war.check_deploy_deadman.collect_owed_commits("ci/lambda_map.json", only={fn})
    finally:
        os.chdir(cwd)
    assert set(one) == {fn} and one[fn] == full[fn]


def test_check_refuses_a_shallow_clone(monkeypatch, tmp_path):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.delenv("WWW_API_READINESS", raising=False)
    monkeypatch.setattr(war, "is_shallow", lambda: True)
    monkeypatch.setattr(war, "evaluate", lambda: pytest.fail("a shallow clone must not be evaluated"))
    assert war.cmd_check() == 1
    assert not out.exists() or "ready=true" not in out.read_text()


@pytest.mark.parametrize(
    "state,ready",
    [(war.READY, "true"), (war.UNVERIFIED, "true"), (war.NOT_READY, "false")],
)
def test_check_emits_ready(monkeypatch, tmp_path, state, ready):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.delenv("WWW_API_READINESS", raising=False)
    monkeypatch.setattr(war, "is_shallow", lambda: False)
    monkeypatch.setattr(war, "evaluate", lambda: {"function": "f", "state": state, "reason": "r", "live_sha": "", "owed_sha": ""})
    assert war.cmd_check() == 0
    assert f"ready={ready}" in out.read_text()


def test_break_glass_is_explicit(monkeypatch, tmp_path):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("WWW_API_READINESS", "skip")
    monkeypatch.setattr(war, "evaluate", lambda: pytest.fail("break-glass must not read the API"))
    assert war.cmd_check() == 0
    assert "ready=true" in out.read_text() and f"state={war.BREAK_GLASS}" in out.read_text()


# ── the workflow wiring (contract) ──────────────────────────────────────────────────────────────
def test_v9_deploy_waits_for_the_site_api():
    assert deploy_is_gated(_load(_V9)) == []


def test_old_ordering_is_caught():
    """Must-fail control: the pre-fix workflow — deploy with no needs/if — is reported, as is a lost fetch-depth."""
    doc = _load(_V9)
    doc["jobs"]["deploy"].pop("needs")
    doc["jobs"]["deploy"].pop("if")
    problems = deploy_is_gated(doc)
    assert any("pre-fix ordering" in p for p in problems) and any("ready == 'true'" in p for p in problems)
    doc = _load(_V9)
    for s in doc["jobs"]["api-readiness"]["steps"]:
        (s.get("with") or {}).pop("fetch-depth", None)
    assert any("shallow" in p for p in deploy_is_gated(doc))
    doc = _load(_V9)
    del doc["jobs"]["api-readiness"]
    assert deploy_is_gated(doc) == ["no api-readiness job"]


def test_job_names_resume_reads_are_the_workflows():
    """Contract: resume classifies runs by job display name — each constant must be a real job name."""
    names = {j.get("name") for j in _load(_V9)["jobs"].values()}
    for const in (war.DEFERRED_JOB, war.DEPLOY_JOB, war.ROOT_SMOKE_JOB):
        assert const in names, const


def test_post_deploy_jobs_never_run_on_a_skipped_deploy():
    jobs = _load(_V9)["jobs"]
    for name in ("smoke", "visual-qa"):
        assert "needs.deploy.result == 'success'" in jobs[name]["if"], name
    rollback = jobs["rollback-v9-on-failure"]["if"]
    assert "needs.deploy.result == 'success'" in rollback  # a deferral syncs nothing, so it can never roll back


def test_resume_is_wired_to_every_api_deploy_path():
    doc = _load(_RESUME)
    on = doc.get(True) or doc.get("on")  # PyYAML reads the bare `on:` key as True
    ci_name = _load(_WF / "ci-cd.yml")["name"]
    assert ci_name in on["workflow_run"]["workflows"], "resume must fire when CI/CD (the fleet deploy) completes"
    assert on.get("schedule"), "the scheduled backstop/dead-man"
    assert doc["permissions"].get("actions") == "write"
    steps = doc["jobs"]["resume"]["steps"]
    assert any("www_api_readiness.py resume" in str(s.get("run", "")) for s in steps)
    assert any((s.get("with") or {}).get("fetch-depth") == 0 for s in steps if "checkout" in str(s.get("uses", "")))
    for script in ("deploy/deploy_site_api.sh", "deploy/deploy_fleet.sh"):
        assert 'www_api_readiness.py" resume' in (_REPO / script).read_text(), script
    assert war.WORKFLOW == _V9.name


# ── resume: which run is decisive ───────────────────────────────────────────────────────────────
def _run(i, status="completed", created="2026-11-12T00:07:23Z"):
    return {"id": i, "status": status, "created_at": created}


DEFERRED = [{"name": war.DEFERRED_JOB, "conclusion": "success"}, {"name": war.DEPLOY_JOB, "conclusion": "skipped"}]
DEPLOYED_ROOT = [{"name": war.DEPLOY_JOB, "conclusion": "success"}, {"name": war.ROOT_SMOKE_JOB, "conclusion": "failure"}]
DEPLOYED_PREVIEW = [{"name": war.DEPLOY_JOB, "conclusion": "success"}, {"name": war.ROOT_SMOKE_JOB, "conclusion": "skipped"}]


@pytest.mark.parametrize(
    "history,live_at_root,expect",
    [
        ([(1, DEFERRED)], True, ("deferred", 1)),
        ([(2, DEPLOYED_ROOT), (1, DEFERRED)], True, ("deployed", 2)),  # a later root deploy settles the deferral
        ([(2, DEPLOYED_PREVIEW), (1, DEFERRED)], True, ("deferred", 1)),  # a preview dispatch after the cut-over does not
        ([(2, DEPLOYED_PREVIEW), (1, DEFERRED)], False, ("deployed", 2)),
        ([(2, [{"name": war.DEFERRED_JOB, "conclusion": "failure"}])], True, ("deferred", 2)),  # SNS failed: still deferred
        ([(3, []), (1, DEFERRED)], True, ("deferred", 1)),  # a run that failed before deploying is not decisive
        ([], True, ("none", None)),
    ],
)
def test_outstanding_deferral(history, live_at_root, expect):
    runs = [_run(i) for i, _ in history]
    jobs = dict(history)
    kind, run = war.outstanding_deferral(runs, lambda r: jobs[r["id"]], live_at_root)
    assert (kind, run and run["id"]) == expect


def test_in_flight_run_is_left_alone():
    kind, run = war.outstanding_deferral([_run(9, status="in_progress"), _run(1)], lambda r: DEFERRED, True)
    assert kind == "in-flight" and run["id"] == 9


def _resume_env(monkeypatch, state, created):
    dispatched = []
    monkeypatch.setattr(war.www_owned_paths, "live_at_root", lambda: True)
    monkeypatch.setattr(war, "is_shallow", lambda: False)
    monkeypatch.setattr(war, "evaluate", lambda: {"function": "f", "state": state, "reason": "r", "live_sha": "", "owed_sha": ""})

    def gh(path):
        return {"workflow_runs": [_run(7, created=created)]} if path.endswith("per_page=30") else {"jobs": DEFERRED}

    monkeypatch.setattr(war, "_gh_json", gh)
    monkeypatch.setattr(war.subprocess, "run", lambda cmd, **kw: dispatched.append(cmd))
    return dispatched


def test_resume_dispatches_root_once_ready(monkeypatch):
    dispatched = _resume_env(monkeypatch, war.READY, "2026-11-12T00:07:23Z")
    assert war.cmd_resume(targets=(war.V9,)) == 0
    assert dispatched == [["gh", "workflow", "run", war.WORKFLOW, "--repo", war.GH_REPO, "--ref", "main", "-f", "target=root"]]


def test_resume_waits_while_not_ready(monkeypatch):
    from datetime import datetime, timezone

    dispatched = _resume_env(monkeypatch, war.NOT_READY, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    assert war.cmd_resume(targets=(war.V9,)) == 0 and dispatched == []


def test_resume_dead_man_reds_a_stale_deferral(monkeypatch):
    dispatched = _resume_env(monkeypatch, war.NOT_READY, "2026-01-01T00:00:00Z")
    assert war.cmd_resume(targets=(war.V9,)) == 1 and dispatched == []


# ── the legacy site/** pipeline (site-deploy.yml) — the same gate, the same module ─────────────────
_STATUS = {"always()": True, "!cancelled()": True, "cancelled()": False}


def _needs_of(job: dict) -> list:
    n = (job or {}).get("needs") or []
    return [n] if isinstance(n, str) else list(n)


def simulate(doc: dict, outputs: dict, failures: frozenset = frozenset()) -> dict:
    """job -> 'success' | 'failure' | 'skipped', evaluating each job's `if:` the way GitHub does for the
    shapes these workflows use. `outputs` = {(job, key): value}; jobs in `failures` fail when they run."""
    jobs = doc["jobs"]
    result: dict = {}

    def cond(name: str) -> bool:
        job, needs = jobs[name], _needs_of(jobs[name])
        expr = str(job.get("if", "")).strip()
        if not expr:  # GitHub's implicit success()
            return all(result[n] == "success" for n in needs)
        if not re.search(r"\b(always|cancelled|success|failure)\(", expr):
            expr = f"success() && ({expr})"
        for k, v in _STATUS.items():
            expr = expr.replace(k, repr(v))
        expr = expr.replace("success()", repr(all(result[n] == "success" for n in needs)))
        expr = expr.replace("failure()", repr(any(result[n] == "failure" for n in needs)))
        expr = re.sub(r"needs\.([\w-]+)\.result", lambda m: repr(result[m.group(1)]), expr)
        expr = re.sub(r"needs\.([\w-]+)\.outputs\.(\w+)", lambda m: repr(outputs.get((m.group(1), m.group(2)), "")), expr)
        expr = expr.replace("&&", " and ").replace("||", " or ")
        return bool(eval(expr, {"__builtins__": {}}))  # noqa: S307 - the workflow file's own expressions, test-only

    pending = list(jobs)
    while pending:
        for name in list(pending):
            if all(n in result for n in _needs_of(jobs[name])):
                result[name] = ("failure" if name in failures else "success") if cond(name) else "skipped"
                pending.remove(name)
    return result


#: deploy job · post-deploy gates · the rollback — per workflow
_SHAPES = {
    "site-deploy.yml": ("deploy-site", ("smoke", "visual-qa"), "rollback-site-on-failure"),
    "web-preview-deploy.yml": ("deploy", ("smoke", "visual-qa"), "rollback-v9-on-failure"),
}


def _incident_ready_output(monkeypatch, tmp_path) -> str:
    """Run the REAL `check` against the 00:07Z incident state; return what it wrote for `ready`."""
    out = tmp_path / "gh_out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.delenv("WWW_API_READINESS", raising=False)
    fn, _ = war.site_api_function()
    monkeypatch.setattr(war, "is_shallow", lambda: False)
    monkeypatch.setattr(war.check_deploy_deadman, "collect_owed_commits", lambda path, only=None: {fn: (INCIDENT_OWED, None, "x")})
    monkeypatch.setattr(war.check_deploy_deadman, "collect_deployed_shas", lambda fns: {fn: INCIDENT_LIVE})
    monkeypatch.setattr(war.bundle_ancestry, "git_is_ancestor", _oracle({(INCIDENT_LIVE, INCIDENT_OWED[:9])}))
    assert war.cmd_check() == 0
    return dict(line.split("=", 1) for line in out.read_text().splitlines())["ready"]


@pytest.mark.parametrize("wf", sorted(_SHAPES))
def test_incident_replay_defers_both_site_paths(monkeypatch, tmp_path, wf):
    """Incident replay: the 00:07Z state (live Site API behind #5827) through each workflow's job graph —
    the deferral runs; nothing deploys, nothing is judged, nothing rolls back."""
    ready = _incident_ready_output(monkeypatch, tmp_path)
    assert ready == "false"
    deploy, gates, rollback = _SHAPES[wf]
    r = simulate(_load(_WF / wf), {("api-readiness", "ready"): ready, ("deploy", "target"): "root"})
    for job in (deploy, *gates, rollback):
        assert r[job] == "skipped", f"{wf}: {job} would run against the old Site API — {r}"
    assert r.get("api-readiness") == "success" and r.get("deferred") == "success", r


def test_old_site_deploy_ordering_is_caught(monkeypatch, tmp_path):
    """Must-fail control: the pre-gate site-deploy.yml (deploy-site with no needs/if, no api-readiness, no
    deferred, smoke/visual on `superseded != 'true'` alone) DEPLOYS and SMOKES in the incident state — the
    shape that relied on api_deploy_sequencing.json alone. Both the contract and the simulator catch it."""
    doc = _load(_SITE)
    for job in ("api-readiness", "deferred"):
        del doc["jobs"][job]
    doc["jobs"]["deploy-site"].pop("needs")
    doc["jobs"]["deploy-site"].pop("if")
    for job in ("smoke", "visual-qa"):
        doc["jobs"][job]["if"] = "needs.deploy-site.outputs.superseded != 'true'"
    nd = doc["jobs"]["notify-deploy-failure"]
    nd["needs"], nd["if"] = "deploy-site", "always() && needs.deploy-site.result == 'failure'"
    assert deploy_is_gated(doc, "deploy-site") == ["no api-readiness job"]
    _incident_ready_output(monkeypatch, tmp_path)  # the gate WOULD say not ready — the old graph never asks
    r = simulate(doc, {("deploy-site", "superseded"): "false"}, failures=frozenset({"smoke"}))
    assert r["deploy-site"] == "success" and r["smoke"] == "failure", r  # the incident: synced, then red against the old API
    assert r["rollback-site-on-failure"] == "success"  # …and the rollback machinery engaged on an API-side red


def test_site_deploy_waits_for_the_site_api():
    doc = _load(_SITE)
    assert deploy_is_gated(doc, "deploy-site") == []
    deferred = doc["jobs"]["deferred"]["steps"]
    assert any("www_api_readiness.py notify-deferred --target site" in str(s.get("run", "")) for s in deferred)
    # The same module — never a second implementation inlined in the workflow.
    runs = [str(s.get("run", "")) for s in doc["jobs"]["api-readiness"]["steps"] if s.get("run")]
    assert runs == ["python3 deploy/www_api_readiness.py check"], runs


def test_site_deploy_old_contract_mutations_are_caught():
    doc = _load(_SITE)
    doc["jobs"]["deploy-site"].pop("needs")
    assert any("pre-fix ordering" in p for p in deploy_is_gated(doc, "deploy-site"))
    doc = _load(_SITE)
    doc["jobs"]["deploy-site"]["if"] = "!cancelled()"
    assert any("ready == 'true'" in p for p in deploy_is_gated(doc, "deploy-site"))
    doc = _load(_SITE)
    for s in doc["jobs"]["api-readiness"]["steps"]:
        (s.get("with") or {}).pop("fetch-depth", None)
    assert any("shallow" in p for p in deploy_is_gated(doc, "deploy-site"))


@pytest.mark.parametrize("wf", sorted(_SHAPES))
def test_a_real_failure_on_a_ready_run_still_rolls_back(wf):
    """Rollback semantics unchanged: ready → deploy → a smoke red → the rollback job runs (its own scope check
    then decides, as before). A deferral is not a failure: nothing to roll back, no deploy-failure page."""
    deploy, gates, rollback = _SHAPES[wf]
    outs = {("api-readiness", "ready"): "true", ("deploy-site", "superseded"): "false", ("deploy", "target"): "root"}
    r = simulate(_load(_WF / wf), outs, failures=frozenset({"smoke"}))
    assert r["deferred"] == "skipped" and r[deploy] == "success" and r[rollback] == "success", r
    r = simulate(_load(_WF / wf), outs)
    assert r[rollback] == "skipped", r
    if wf == "site-deploy.yml":
        assert r["notify-deploy-failure"] == "skipped"
        r = simulate(_load(_WF / wf), {("api-readiness", "ready"): "false"})
        assert r["notify-deploy-failure"] == "skipped" and r["rollback-site-on-failure"] == "skipped"
        r = simulate(_load(_WF / wf), {}, failures=frozenset({"api-readiness"}))  # the check itself errored
        assert r["deploy-site"] == "skipped" and r["notify-deploy-failure"] == "success", r


def test_site_job_names_resume_reads_are_the_workflows():
    """Contract: resume classifies site-deploy runs by job display name — each must be a real job name, and
    every target's workflow must exist."""
    names = {j.get("name") for j in _load(_SITE)["jobs"].values()}
    for const in (war.SITE_DEFERRED_JOB, war.SITE_DEPLOY_JOB, war.SITE_SMOKE_JOB):
        assert const in names, const
    assert war.SITE.workflow == _SITE.name
    for t in war.TARGETS.values():
        assert (_WF / t.workflow).exists(), t.workflow
        names = {j.get("name") for j in _load(_WF / t.workflow)["jobs"].values()}
        assert {t.deferred_job, t.deploy_job, t.smoke_job} <= names, t.key


def test_site_break_glass_is_dispatch_only():
    doc = _load(_SITE)
    on = doc.get(True) or doc.get("on")
    assert on["workflow_dispatch"]["inputs"]["api_readiness"]["options"] == ["enforce", "skip"]
    text = _SITE.read_text(encoding="utf-8")
    assert re.findall(r"WWW_API_READINESS:\s*(.+)", text) == ["${{ github.event.inputs.api_readiness }}"]


# ── resume across both targets ─────────────────────────────────────────────────────────────────
SITE_DEFERRED = [{"name": war.SITE_DEFERRED_JOB, "conclusion": "success"}, {"name": war.SITE_DEPLOY_JOB, "conclusion": "skipped"}]
SITE_DEPLOYED = [{"name": war.SITE_DEPLOY_JOB, "conclusion": "success"}, {"name": war.SITE_SMOKE_JOB, "conclusion": "success"}]
SITE_SUPERSEDED = [{"name": war.SITE_DEPLOY_JOB, "conclusion": "success"}, {"name": war.SITE_SMOKE_JOB, "conclusion": "skipped"}]


@pytest.mark.parametrize(
    "history,expect",
    [
        ([(1, SITE_DEFERRED)], ("deferred", 1)),
        ([(2, SITE_DEPLOYED), (1, SITE_DEFERRED)], ("deployed", 2)),
        ([(2, SITE_SUPERSEDED), (1, SITE_DEFERRED)], ("deferred", 1)),  # a superseded no-op deployed nothing
        ([(2, SITE_DEFERRED), (1, SITE_DEPLOYED)], ("deferred", 2)),
    ],
)
def test_site_outstanding_deferral(history, expect):
    runs = [_run(i) for i, _ in history]
    jobs = dict(history)
    for live_at_root in (True, False):  # the cut-over switch is v9's business, not the legacy pipeline's
        kind, run = war.outstanding_deferral(runs, lambda r: jobs[r["id"]], live_at_root, war.SITE)
        assert (kind, run and run["id"]) == expect


def test_the_dead_mans_clock_starts_at_the_first_deferral_of_the_streak():
    runs = [_run(4, created="2026-11-12T09:00:00Z"), _run(3, created="2026-11-12T05:00:00Z"), _run(2), _run(1)]
    jobs = {4: SITE_DEFERRED, 3: SITE_DEFERRED, 2: SITE_DEPLOYED, 1: SITE_DEFERRED}
    first = war.first_deferral_of_streak(runs, lambda r: jobs[r["id"]], True, war.SITE)
    assert first["id"] == 3  # not 4 (the clock would reset on every merge), not 1 (settled by run 2)


def _two_target_env(monkeypatch, state, deferred: dict, fail_list: str | None = None):
    """deferred = {workflow: created_at} for the workflows whose newest run is a deferral."""
    dispatched, evaluations = [], []
    monkeypatch.setattr(war.www_owned_paths, "live_at_root", lambda: True)
    monkeypatch.setattr(war, "is_shallow", lambda: False)

    def evaluate():
        evaluations.append(1)
        return {"function": "f", "state": state, "reason": "r", "live_sha": "", "owed_sha": ""}

    monkeypatch.setattr(war, "evaluate", evaluate)
    by_id = {}

    def gh(path):
        for i, wf in enumerate(sorted(war.TARGETS.values(), key=lambda t: t.key)):
            if f"workflows/{wf.workflow}/runs" in path:
                if wf.workflow == fail_list:
                    raise subprocess.CalledProcessError(1, "gh")
                if wf.workflow not in deferred:
                    return {"workflow_runs": []}
                rid = 100 + i
                by_id[rid] = [{"name": wf.deferred_job, "conclusion": "success"}]
                return {"workflow_runs": [_run(rid, created=deferred[wf.workflow])]}
        rid = int(path.split("/runs/")[1].split("/")[0])
        return {"jobs": by_id[rid]}

    monkeypatch.setattr(war, "_gh_json", gh)
    monkeypatch.setattr(war.subprocess, "run", lambda cmd, **kw: dispatched.append(cmd))
    return dispatched, evaluations


def test_resume_dispatches_both_deferred_paths_on_one_api_read(monkeypatch):
    """Incident replay, resume side: both paths deferred at 00:07Z; CI lands the API → ONE evaluate, TWO
    dispatches — the v9 root deploy and a plain site-deploy.yml re-run of main."""
    t = "2026-11-12T00:07:23Z"
    dispatched, evaluations = _two_target_env(monkeypatch, war.READY, {war.WORKFLOW: t, war.SITE_WORKFLOW: t})
    assert war.cmd_resume() == 0
    assert len(evaluations) == 1
    assert sorted(dispatched) == sorted(
        [
            ["gh", "workflow", "run", war.WORKFLOW, "--repo", war.GH_REPO, "--ref", "main", "-f", "target=root"],
            ["gh", "workflow", "run", war.SITE_WORKFLOW, "--repo", war.GH_REPO, "--ref", "main"],
        ]
    )


def test_resume_site_only(monkeypatch):
    dispatched, evaluations = _two_target_env(monkeypatch, war.READY, {war.SITE_WORKFLOW: "2026-11-12T00:07:23Z"})
    assert war.cmd_resume() == 0
    assert dispatched == [["gh", "workflow", "run", war.SITE_WORKFLOW, "--repo", war.GH_REPO, "--ref", "main"]]


def test_nothing_deferred_reads_no_api(monkeypatch):
    dispatched, evaluations = _two_target_env(monkeypatch, war.READY, {})
    assert war.cmd_resume() == 0 and dispatched == [] and evaluations == []


def test_stale_site_deferral_reds_the_resume_run(monkeypatch, capsys):
    dispatched, _ = _two_target_env(monkeypatch, war.NOT_READY, {war.SITE_WORKFLOW: "2026-01-01T00:00:00Z"})
    assert war.cmd_resume() == 1 and dispatched == []
    assert "gh workflow run site-deploy.yml --ref main -f api_readiness=skip" in capsys.readouterr().out


def test_one_targets_error_does_not_block_the_others_resume(monkeypatch):
    t = "2026-11-12T00:07:23Z"
    dispatched, _ = _two_target_env(monkeypatch, war.READY, {war.SITE_WORKFLOW: t}, fail_list=war.WORKFLOW)
    assert war.cmd_resume() == 1  # the v9 history read failed: red, so it is seen
    assert dispatched == [["gh", "workflow", "run", war.SITE_WORKFLOW, "--repo", war.GH_REPO, "--ref", "main"]]


def test_notify_deferred_names_the_target(monkeypatch, capsys):
    monkeypatch.delenv("SNS_TOPIC_ARN", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setenv("READINESS_REASON", "behind")
    assert war.main(["notify-deferred", "--target", "site"]) == 0
    assert "site/** deploy DEFERRED, not failed: behind" in capsys.readouterr().out
