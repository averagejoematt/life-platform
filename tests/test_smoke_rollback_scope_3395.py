"""tests/test_smoke_rollback_scope_3395.py — #3395: the smoke leg's rollback
reachability scope (the smoke edition of the #3352 visual-QA scope check).

THE INCIDENT
------------
Live 2026-09-01 01:35Z (INCIDENT_LOG P3): site-deploy run 33459065966 failed ONE
smoke check — `/api/vitals` weight arbitration, a data-plane state served from
DynamoDB — and `rollback-site-on-failure` reverted PR #3392's innocent site
content, "successfully", without touching the actual disagreement. The deploy's
own visual QA had PASSED: #3352 had scoped only the visual leg, and a smoke FAIL
still fired the rollback unconditionally. A rollback whose scope cannot reach
its trigger is the silent-failure floor.

THE FIX SHAPE (mirrors #3352)
-----------------------------
Every smoke check DECLARES its surface at the call site (`SMOKE_SURFACE` =
site / api / infra in deploy/smoke_test_site.sh, recorded through the one
`smoke_record_fail` recorder in deploy/lib/smoke_verdict.sh), the script emits a
machine-readable verdict (`site_reachable` / `surfaces` / `summary`) to
$GITHUB_OUTPUT, and the rollback step declines when EITHER gate's verdict says
`false` — filing the #1447 issue instead of reverting.

Two proof styles here, deliberately:
  * FUNCTIONAL — the verdict lib is real bash sourced in a subprocess, driven
    through positive AND negative controls (the #2963 lesson: a vacuous negative
    control equals a passing one).
  * STRUCTURAL — text pins on the harness + workflow, same style as
    tests/test_site_deploy_workflow.py (CI's test job has no PyYAML).

The LIVE proof (acceptance box 3) is the `smoke_inject_failure=api` dispatch run
after merge — a fail-closed path with green unit tests can still be
non-functional (#3200), so the run id gets pasted onto the issue, not assumed.
"""

import os
import re
import subprocess

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SMOKE = os.path.join(_REPO, "deploy", "smoke_test_site.sh")
_LIB = os.path.join(_REPO, "deploy", "lib", "smoke_verdict.sh")
_SITE_DEPLOY = os.path.join(_REPO, ".github", "workflows", "site-deploy.yml")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ── FUNCTIONAL: drive the real lib in a bash subprocess ──────────────────────────


def _run_verdict(body, tmp_path):
    """Source the real lib, run `body` (record_fail calls), emit, and return
    (stdout, {output_key: value}) from a real $GITHUB_OUTPUT file."""
    out_file = tmp_path / "github_output"
    out_file.write_text("")
    script = f'set -euo pipefail\nFAIL=0\nsource "{_LIB}"\n{body}\nsmoke_emit_verdict\n'
    proc = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env={**os.environ, "GITHUB_OUTPUT": str(out_file)},
    )
    assert proc.returncode == 0, f"verdict lib errored: {proc.stderr}"
    outputs = dict(line.split("=", 1) for line in out_file.read_text().splitlines() if "=" in line)
    return proc.stdout, outputs


def test_zero_failures_emit_reachable_true(tmp_path):
    """No recorded failure → `true`: the gate may have died before recording, and
    the fail-safe is today's behaviour (rollback runs)."""
    _, outputs = _run_verdict("", tmp_path)
    assert outputs["site_reachable"] == "true"
    assert outputs["surfaces"] == ""


def test_a_site_only_failure_stays_reachable_the_rollback_still_runs(tmp_path):
    """The negative control that matters most: this change may only REMOVE a rollback
    we can prove futile — a site/** red must keep rolling back exactly as today."""
    _, outputs = _run_verdict('SMOKE_SURFACE=site\nsmoke_record_fail "Home: constellation hero"', tmp_path)
    assert outputs["site_reachable"] == "true"
    assert outputs["surfaces"] == "site:1"


def test_an_api_failure_emits_reachable_false(tmp_path):
    """The 2026-09-01 P3 shape: one data-plane red must decline the rollback."""
    stdout, outputs = _run_verdict('SMOKE_SURFACE=api\nsmoke_record_fail "/api/vitals: missing weight_lbs"', tmp_path)
    assert outputs["site_reachable"] == "false"
    assert outputs["surfaces"] == "api:1"
    assert "NOT site/**-reachable" in outputs["summary"]
    assert "/api/vitals" in stdout  # the human log names the failing check


def test_an_infra_failure_emits_reachable_false(tmp_path):
    """Edge-config reds (CloudFront function 301s, CDK-owned CSP, sync-script cache
    stamps) — a site/** revert cannot republish any of them (#3352 deploy-script class)."""
    _, outputs = _run_verdict('SMOKE_SURFACE=infra\nsmoke_record_fail "CSP: live header drifted from source"', tmp_path)
    assert outputs["site_reachable"] == "false"
    assert outputs["surfaces"] == "infra:1"


def test_a_mixed_failure_declines_the_whole_rollback(tmp_path):
    """#3352's AND rule: one unreachable surface declines everything — a partial
    revert of a mixed failure is the worst of both. The summary names every surface
    so the human still sees the site/** half that stays theirs."""
    body = (
        'SMOKE_SURFACE=site\nsmoke_record_fail "Cockpit: data-bind targets"\n'
        'SMOKE_SURFACE=api\nsmoke_record_fail "/api/character: pillars missing"'
    )
    _, outputs = _run_verdict(body, tmp_path)
    assert outputs["site_reachable"] == "false"
    assert outputs["surfaces"] == "api:1,site:1"
    assert "1 of 2" in outputs["summary"]


def test_an_unknown_surface_records_as_site_the_negative_control(tmp_path):
    """Same rule as visual_qa_verdict.py: an unrecognised surface classifies as
    site/** — the rollback still runs. A silent widening of the decline set would
    convert a useful-but-blunt instrument into a dark one."""
    _, outputs = _run_verdict('SMOKE_SURFACE=bogus-future-class\nsmoke_record_fail "a check nobody thought about"', tmp_path)
    assert outputs["site_reachable"] == "true"
    assert outputs["surfaces"] == "site:1"


def test_a_bypassing_bare_fail_increment_stays_fail_safe_and_loud(tmp_path):
    """A future bare `FAIL=$((FAIL+1))` that skips the recorder must not flip the
    verdict to a decline — the unrecorded failure defaults toward rollback (today's
    behaviour) and the drift is printed out loud."""
    stdout, outputs = _run_verdict("FAIL=$((FAIL + 1))", tmp_path)
    assert outputs["site_reachable"] == "true"
    assert "bypassed" in stdout


def test_injection_rides_the_same_recorder_path(tmp_path):
    """The live-proof injection must classify through the SAME rule path as a real
    failure (mirrors #3352's `[INJECTED]` design) — proven by replaying the exact
    call the harness makes."""
    injected = re.search(r'smoke_record_fail "(\[INJECTED #3395[^"]*)"', _read(_SMOKE))
    assert injected, "the injection block must record through smoke_record_fail with an [INJECTED #3395 …] label"
    _, outputs = _run_verdict(f'SMOKE_SURFACE=api\nsmoke_record_fail "{injected.group(1)}"', tmp_path)
    assert outputs["site_reachable"] == "false"


# ── STRUCTURAL: the harness declares surfaces and cannot bypass the recorder ─────


def test_every_failure_path_goes_through_the_recorder():
    """Guard the SET, not the instance: the only bare `FAIL=$((FAIL…` increment
    allowed lives inside the lib's recorder itself. A new ❌ path added with a bare
    increment would be invisible to the scope verdict (fail-safe, but dark) — make
    it loud at PR time instead."""
    smoke = _read(_SMOKE)
    bare = [ln for ln in smoke.splitlines() if "FAIL=$((FAIL" in ln]
    assert not bare, f"bare FAIL increments bypass smoke_record_fail (#3395): {bare}"
    assert "smoke_record_fail" in smoke, "the harness must record failures through the lib"
    lib = _read(_LIB)
    incr = [ln for ln in lib.splitlines() if "FAIL=$((" in ln and not ln.strip().startswith("#")]
    assert len(incr) == 1, f"the lib must own exactly one FAIL increment, found: {incr}"


def test_the_harness_sources_the_lib_before_any_check():
    smoke = _read(_SMOKE)
    assert 'lib/smoke_verdict.sh"' in smoke, "smoke_test_site.sh must source deploy/lib/smoke_verdict.sh (#3395)"
    assert smoke.index("lib/smoke_verdict.sh") < smoke.index("check_status()"), "the lib must be sourced before the check helpers"


def test_every_declared_surface_is_a_known_class():
    """Acceptance box 1: every smoke check declares a surface class, and only the
    three classes exist — a typo'd surface would silently count as `site` (fail-safe
    but wrong), so catch it here at PR time."""
    declared = re.findall(r'^\s*SMOKE_SURFACE="?([a-z-]+)"?\s', _read(_SMOKE), re.MULTILINE)
    assert declared, "smoke_test_site.sh must declare SMOKE_SURFACE per section"
    assert set(declared) <= {"site", "api", "infra"}, f"unknown surface class declared: {sorted(set(declared))}"
    # The incident classes must actually be present — a harness that declares only
    # `site` everywhere would make this whole change vacuous.
    assert "api" in declared and "infra" in declared and "site" in declared


def test_the_incident_check_is_api_classed():
    """THE check that reverted PR #3392 (the /api/vitals weight arbitration, 'API
    data quality' section) must sit under an api declaration — the exact regression
    this issue exists to prevent."""
    smoke = _read(_SMOKE)
    section = smoke.index('echo "── API data quality')
    last_surface = re.findall(r'SMOKE_SURFACE="([a-z-]+)"', smoke[:section])
    assert last_surface and last_surface[-1] == "api", "the API data quality section must be api-classed (#3395)"


def test_the_verdict_is_emitted_before_the_failing_exit():
    """The verdict must be written before `exit 1`, or every failing run — the only
    case the verdict exists for — would emit nothing and roll back unconditionally."""
    smoke = _read(_SMOKE)
    assert "smoke_emit_verdict" in smoke
    assert smoke.rindex("smoke_emit_verdict") < smoke.rindex("[[ $FAIL -eq 0 ]] || exit 1")


def test_the_lib_emits_the_three_outputs_the_workflow_reads():
    lib = _read(_LIB)
    for key in ("site_reachable=", "surfaces=", "summary="):
        assert key in lib, f"smoke_verdict.sh must emit {key} to $GITHUB_OUTPUT"


# ── STRUCTURAL: the workflow wiring (same text-based style as test_site_deploy_workflow) ──


def _step_block(text, step_name):
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.strip().startswith("- name:") and step_name in ln)
    indent = len(lines[start]) - len(lines[start].lstrip())
    out = [lines[start]]
    for ln in lines[start + 1 :]:
        if ln.strip().startswith("- name:") and (len(ln) - len(ln.lstrip())) <= indent:
            break
        out.append(ln)
    return "\n".join(out)


def test_the_smoke_job_exports_the_scope_verdict():
    text = _read(_SITE_DEPLOY)
    smoke_job = text.split("\n  smoke:", 1)[1].split("\n  visual-qa:", 1)[0]
    for output in ("site_reachable: ${{ steps.smoke.outputs.site_reachable }}", "surfaces: ${{ steps.smoke.outputs.surfaces }}"):
        assert output in smoke_job, f"the smoke job must export {output} (#3395)"
    assert "id: smoke" in smoke_job, "the smoke step needs an id for its outputs to be addressable"


def test_the_rollback_declines_on_a_smoke_verdict_too():
    """The fix itself: the decline guard must read BOTH legs, and the declined path
    must exit before rollback_site.sh (which re-runs the sync — the P1 lesson)."""
    text = _read(_SITE_DEPLOY)
    step = _step_block(text, "Roll back site to previous build")
    assert "needs.smoke.outputs.site_reachable" in step, "the rollback must read the smoke scope verdict (#3395)"
    guard = step.index('SMOKE_REACHABLE:-}" = "false"')
    exit_early = step.index("exit 0", min(guard, step.index('SITE_REACHABLE:-}" = "false"')))
    rollback = step.index("bash deploy/rollback_site.sh")
    assert exit_early < rollback, "the declined path must exit BEFORE rollback_site.sh"
    # Only an explicit `false` declines — an absent verdict must roll back as today.
    assert '"${SMOKE_REACHABLE:-}" = "false"' in step, "the guard must compare against explicit 'false' (fail-safe direction)"


def test_only_a_workflow_dispatch_can_inject_a_smoke_failure():
    """Mirror of #3352's injection guard: `github.event.inputs.*` is empty on a push,
    so a merge can never inject — but only if that is the ONLY source of the env var."""
    text = _read(_SITE_DEPLOY)
    assert "smoke_inject_failure:" in text, "the #3395 live-proof dispatch input is missing"
    sources = re.findall(r"SMOKE_INJECT_SURFACE:\s*(.+)", text)
    assert sources, "the smoke job must receive the injection choice through SMOKE_INJECT_SURFACE"
    for src in sources:
        assert src.strip() == "${{ github.event.inputs.smoke_inject_failure }}", f"injection reachable from a non-dispatch source: {src}"
    push_block = text.split("  push:", 1)[1].split("  workflow_dispatch:", 1)[0]
    assert "smoke_inject_failure" not in push_block
    # The harness only honours the one declared class.
    assert '"${SMOKE_INJECT_SURFACE}" == "api"' in _read(_SMOKE), "the harness must gate injection to the declared 'api' class"
