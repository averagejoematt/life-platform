"""tests/test_head_coverage_scheduled_consumer_2826.py — #2826.

`head_coverage()` (#2762) had no SCHEDULED consumer: it only ran inside a
session's `/wrap` gate, so an unattended merge (dependabot-automerge,
remediation automerge) whose push was swallowed had no detector until a human
happened to look. This file tests the fix: `main_head_coverage()`, the new
`--head-coverage-check` entry point wired into `deploy-wedge-watch.yml`'s
15-minute cron.

The naive wiring — "uncovered ⇒ page" — was tried and rejected LIVE in the
session that filed this: main's HEAD (8cbf075f) read `uncovered` for ci-cd.yml
(neither of its two changed files is in ci-cd.yml's `paths:` filter) but
`Docs CI` HAD run at that sha — an ORDINARY path-filter skip, not a swallowed
push. Two of the fixtures below are REAL API payloads captured for exactly
this commit and for PR #2916's head 392ce9c9c (which minted ZERO runs of any
workflow on 2026-08-20 — the genuine swallow), not inventions.
"""

import importlib.util
import os

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("cmg_2826", os.path.join(_REPO, "scripts", "check_main_green.py"))
cmg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cmg)

# ─────────────────────────────────────────────────────────────────────────
# ci_cd_push_paths() — parses ci-cd.yml's own `paths:` filter
# ─────────────────────────────────────────────────────────────────────────


def test_ci_cd_push_paths_finds_no_filter_on_the_real_file():
    """Against the actual checked-in workflow, not a fixture — this is the file
    `main_head_coverage()` reads live.

    #3378 (2026-09-01) REMOVED ci-cd.yml's `paths:` filter, so the live parse now
    legitimately returns []. The old assertion here named three patterns it expected to
    find; it is inverted rather than deleted, because the reason it existed still holds —
    this is the live read, and a silently-empty result used to be indistinguishable from a
    parse failure. It no longer is: the absence is pinned by
    tests/test_ci_main_push_coverage.py, which reds if anyone re-adds a filter.

    The consequence for THIS module is the load-bearing half. With no filter, the empty
    pattern list means every changed path is in scope (`path_matches_ci_filter` fails
    toward in-scope by design), so a zero-run HEAD on main is unambiguously a SWALLOW —
    `path-filter-skip` is now unreachable for ci-cd.yml on main. The classifier still
    implements that state and the tests below still cover it, driven by the frozen
    CI_PATHS frame rather than the live file: another workflow, or a future filter, can
    still produce one, and the recorded 8cbf075f incident must keep replaying under the
    filter it actually happened beneath.
    """
    with open(os.path.join(_REPO, ".github", "workflows", "ci-cd.yml")) as f:
        paths = cmg.ci_cd_push_paths(f.read())
    assert paths == [], f"ci-cd.yml re-acquired a push `paths:` filter: {paths} — see #3378"
    # An empty filter means "everything is in scope", never "nothing is".
    assert cmg.path_matches_ci_filter(["CLAUDE.md", "handovers/HANDOVER_LATEST.md"], paths) is True


def test_bare_on_key_is_handled_despite_pyyaml_yaml11_gotcha():
    """PyYAML's safe_load reads a bare `on:` as the boolean True, not the
    string "on" — the gotcha every other workflow-parsing script in this repo
    (gate_census.py, apply_branch_protection.py) already has to work around."""
    text = "name: x\non:\n  push:\n    paths:\n      - 'foo/**'\n"
    assert cmg.ci_cd_push_paths(text) == ["foo/**"]


def test_malformed_yaml_degrades_to_empty_not_an_exception():
    assert cmg.ci_cd_push_paths("not: [valid: yaml: at: all") == []


# ─────────────────────────────────────────────────────────────────────────
# path_matches_ci_filter() — the glob discriminator
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path,patterns,expected",
    [
        ("lambdas/ingestion/whoop.py", ["lambdas/**"], True),
        ("lambdas.py", ["lambdas/**"], False),  # ** requires the slash, not a prefix match
        ("mcp_server.py", ["mcp_server.py"], True),
        ("mcp_server_v2.py", ["mcp_server.py"], False),
        ("requirements-dev.txt", ["requirements*.txt"], True),
        (".github/workflows/ci-cd.yml", [".github/workflows/**"], True),
        ("CLAUDE.md", ["lambdas/**", "tests/**", ".github/workflows/**"], False),
        ("handovers/HANDOVER_LATEST.md", ["lambdas/**", "deploy/**"], False),
    ],
)
def test_path_matches_ci_filter_cases(path, patterns, expected):
    assert cmg.path_matches_ci_filter([path], patterns) is expected


def test_empty_filter_fails_toward_in_scope_never_toward_silent_skip():
    """An unreadable filter must never manufacture a false path-filter-skip —
    it has to fail toward treating the push as governed (swallowed if nothing
    ran), not toward silence."""
    assert cmg.path_matches_ci_filter(["anything.py"], []) is True


# ─────────────────────────────────────────────────────────────────────────
# classify_zero_run_head() — the state machine, real-payload replays
# ─────────────────────────────────────────────────────────────────────────

# Real payload: PR #2916's head 392ce9c9c001f8c71ed482b950a075707fa4547b —
# `gh api repos/.../actions/runs?head_sha=<full sha>` returned total_count: 0
# on 2026-08-20 (close/reopen did not fix it; only a new sha did — the genuine
# #2662 swallow). Changed file was tests/conftest.py (governed by `tests/**`),
# but that's irrelevant here: zero runs of ANYTHING is swallowed regardless of
# what the diff touches.
SWALLOWED_ALL_RUNS: list = []
SWALLOWED_CHANGED_PATHS = ["tests/conftest.py"]

# Real payload: main's HEAD 8cbf075fb7dfacc8e53bd5964cea00ba95b2db54 —
# `gh api repos/.../actions/runs?head_sha=<full sha>` returned two runs
# (Docs CI: completed/success; Visual QA (standalone): in_progress), zero of
# them ci-cd.yml. `gh api repos/.../commits/<sha>` returned exactly
# CLAUDE.md + handovers/HANDOVER_LATEST.md.
SKIP_ALL_RUNS = [
    {"id": 32412461126, "name": "Docs CI", "status": "completed", "conclusion": "success"},
    {"id": 32415036516, "name": "Visual QA (standalone)", "status": "in_progress", "conclusion": None},
]
SKIP_CHANGED_PATHS = ["CLAUDE.md", "handovers/HANDOVER_LATEST.md"]

CI_PATHS = [
    "lambdas/**",
    "mcp/**",
    "mcp_server.py",
    "tests/**",
    "cdk/**",
    "ci/**",
    "config/**",
    ".github/workflows/**",
    "requirements*.txt",
    "pyproject.toml",
    ".flake8",
    "deploy/**",
]


def test_zero_runs_of_anything_is_swallowed_392ce9c9c_shape():
    v = cmg.classify_zero_run_head(SWALLOWED_ALL_RUNS, SWALLOWED_CHANGED_PATHS, CI_PATHS)
    assert v["state"] == cmg.ZR_SWALLOWED
    assert "no workflow run" in v["reason"]


def test_other_runs_but_out_of_scope_diff_is_path_filter_skip_8cbf075f_shape():
    v = cmg.classify_zero_run_head(SKIP_ALL_RUNS, SKIP_CHANGED_PATHS, CI_PATHS)
    assert v["state"] == cmg.ZR_PATH_FILTER_SKIP
    assert "Docs CI" in v["reason"]


def test_other_runs_and_in_scope_diff_is_a_partial_swallow():
    """Other workflow(s) ran, but the diff DOES touch ci-cd.yml's filter — it
    should have run too and did not. This is NOT the expected skip shape; it
    must still page."""
    v = cmg.classify_zero_run_head(SKIP_ALL_RUNS, ["lambdas/ingestion/whoop.py"], CI_PATHS)
    assert v["state"] == cmg.ZR_SWALLOWED


def test_unreadable_changed_paths_is_indeterminate_never_folded_into_either_verdict():
    v = cmg.classify_zero_run_head(SKIP_ALL_RUNS, None, CI_PATHS)
    assert v["state"] == cmg.ZR_INDETERMINATE


# ─────────────────────────────────────────────────────────────────────────
# main_head_coverage() — the CLI entry point, exit-code contract
# ─────────────────────────────────────────────────────────────────────────


class _FakeGh:
    """Dispatches on the `gh` argv the same way the real `_gh_json` is called,
    from a dict of canned responses keyed by a recognizable substring — and
    raises on anything NOT stubbed, so a test only passes if `main_head_coverage`
    made exactly the calls it claims to and no more (e.g. it must NOT fetch
    all-workflow runs when `head_coverage` already says `covered`)."""

    def __init__(self, responses: dict):
        self.responses = responses
        self.calls: list = []

    def __call__(self, args: list):
        self.calls.append(args)
        joined = " ".join(str(a) for a in args)
        for key, value in self.responses.items():
            if key in joined:
                if isinstance(value, Exception):
                    raise value
                return value
        raise AssertionError(f"unstubbed gh call in test: {args}")


HEAD = "b" * 40


def _run_list_response(head_sha_at=None):
    if head_sha_at is None:
        return [{"status": "completed", "conclusion": "success", "headSha": "a" * 40, "databaseId": 1, "createdAt": "2026-08-16T01:00:00Z"}]
    return [{"status": "completed", "conclusion": "success", "headSha": head_sha_at, "databaseId": 9, "createdAt": "x"}]


def test_covered_head_exits_0_without_fetching_all_workflow_runs(monkeypatch):
    gh = _FakeGh(
        {
            "run list": _run_list_response(head_sha_at=HEAD),
            "branches/main": {"commit": {"sha": HEAD}},
        }
    )
    monkeypatch.setattr(cmg, "_gh_json", gh)
    assert cmg.main_head_coverage() == 0
    # Only 2 calls: the ci-cd run list + the branch head. Never the
    # all-workflow / commits reads — those are unstubbed and would raise.
    assert len(gh.calls) == 2


def test_swallowed_push_replay_392ce9c9c_shape_exits_1(monkeypatch, capsys):
    gh = _FakeGh(
        {
            "run list": _run_list_response(),  # nothing at HEAD -> uncovered
            "branches/main": {"commit": {"sha": HEAD}},
            f"actions/runs?head_sha={HEAD}": {"workflow_runs": SWALLOWED_ALL_RUNS},
            f"commits/{HEAD}": {"files": [{"filename": p} for p in SWALLOWED_CHANGED_PATHS]},
        }
    )
    monkeypatch.setattr(cmg, "_gh_json", gh)
    assert cmg.main_head_coverage() == 1
    out = capsys.readouterr().out
    assert "SWALLOWED PUSH" in out


def test_path_filter_skip_replay_8cbf075f_shape_exits_0_silently(monkeypatch, capsys):
    gh = _FakeGh(
        {
            "run list": _run_list_response(),  # nothing at HEAD -> uncovered
            "branches/main": {"commit": {"sha": HEAD}},
            f"actions/runs?head_sha={HEAD}": {"workflow_runs": SKIP_ALL_RUNS},
            f"commits/{HEAD}": {"files": [{"filename": p} for p in SKIP_CHANGED_PATHS]},
        }
    )
    monkeypatch.setattr(cmg, "_gh_json", gh)
    # Replay under the filter this incident actually ran beneath (#3378 removed the live
    # one; main_head_coverage() reads it from disk, so it is pinned here, not stubbed away).
    monkeypatch.setattr(cmg, "ci_cd_push_paths", lambda _text: list(CI_PATHS))
    assert cmg.main_head_coverage() == 0
    out = capsys.readouterr().out
    assert "SWALLOWED" not in out
    assert "path-filter skip" in out


def test_execution_error_on_run_list_is_indeterminate_not_ok(monkeypatch):
    gh = _FakeGh({"run list": RuntimeError("gh timed out")})
    monkeypatch.setattr(cmg, "_gh_json", gh)
    assert cmg.main_head_coverage() == 2


def test_execution_error_on_all_workflow_runs_is_indeterminate_not_ok(monkeypatch):
    gh = _FakeGh(
        {
            "run list": _run_list_response(),
            "branches/main": {"commit": {"sha": HEAD}},
            f"actions/runs?head_sha={HEAD}": RuntimeError("API rate limited"),
        }
    )
    monkeypatch.setattr(cmg, "_gh_json", gh)
    assert cmg.main_head_coverage() == 2


def test_execution_error_never_prints_the_ok_glyph(monkeypatch, capsys):
    """The #2753 class this epic exists to close: an execution error must be
    visually and programmatically distinguishable from a clean 'OK' run."""
    gh = _FakeGh({"run list": RuntimeError("boom")})
    monkeypatch.setattr(cmg, "_gh_json", gh)
    cmg.main_head_coverage()
    out = capsys.readouterr().out
    assert "✅" not in out


def test_exit_codes_are_pairwise_distinct():
    """0 (ok) / 1 (confirmed swallow) / 2 (indeterminate) must never collide —
    a workflow step that only checks `!= 0` still needs the message, but a step
    that checks the code itself must never confuse 'broken check' with
    'confirmed incident'."""
    assert len({0, 1, 2}) == 3


# ── #2826 follow-up: the reconcile-commit false positive (2026-08-20) ──────────
#
# Found live, minutes after #2925 merged: `check_main_green.py --head-coverage-check`
# called main's HEAD a SWALLOWED PUSH and exited 1. The HEAD was a routine
# `chore(reconcile)` commit — pushed with GITHUB_TOKEN, which GitHub deliberately
# never dispatches workflows for (anti-recursion), AND touching
# lambdas/web/site_api_common.py, which IS in ci-cd.yml's paths: filter. So it hit
# the "partial swallow" branch. A reconcile commit follows EVERY merge, so the
# 15-minute cron would have paged forever — the exact false-positive-generator
# failure this issue's design was supposed to avoid.


def _ci_paths():
    """The RECORDED pre-#3378 filter, not the live file.

    These are replays of incidents that happened while ci-cd.yml carried a `paths:`
    filter (8cbf075f, PR #2916's head). #3378 removed that filter on 2026-09-01, so
    reading the live file would replay them under a frame they never ran in — and every
    path-filter-skip assertion below would flip to swallowed for a reason that has
    nothing to do with the behaviour under test. A replay runs under its own frame.
    """
    return list(CI_PATHS)


def test_reconcile_commit_by_bot_is_expected_not_swallowed():
    """The live false positive: bot push + zero runs + a diff that DOES hit the filter."""
    v = cmg.classify_zero_run_head(
        [], ["docs/TESTING.md", "lambdas/web/site_api_common.py"], _ci_paths(), committer_login="github-actions[bot]"
    )
    assert v["state"] == cmg.ZR_BOT_PUSH_NO_DISPATCH, v


def test_bot_push_check_precedes_every_other_branch():
    """It holds regardless of runs present or paths touched — a GITHUB_TOKEN push
    cannot dispatch, so no other signal can make it a swallow."""
    ci = _ci_paths()
    for runs, paths in (([], ["lambdas/x.py"]), ([{"name": "Docs CI"}], ["lambdas/x.py"]), ([], ["CLAUDE.md"])):
        v = cmg.classify_zero_run_head(runs, paths, ci, committer_login="github-actions[bot]")
        assert v["state"] == cmg.ZR_BOT_PUSH_NO_DISPATCH, (runs, paths, v)


def test_a_human_push_with_zero_runs_still_pages():
    """The regression guard: the fix must not mute a genuine swallow."""
    v = cmg.classify_zero_run_head([], ["lambdas/web/foo.py"], _ci_paths(), committer_login="averagejoematt")
    assert v["state"] == cmg.ZR_SWALLOWED, v


def test_omitting_committer_preserves_the_original_behaviour():
    """Back-compat: callers that pass no committer get exactly the pre-fix verdicts."""
    ci = _ci_paths()
    assert cmg.classify_zero_run_head([], ["lambdas/web/foo.py"], ci)["state"] == cmg.ZR_SWALLOWED
    assert cmg.classify_zero_run_head([{"name": "Docs CI"}], ["CLAUDE.md"], ci)["state"] == cmg.ZR_PATH_FILTER_SKIP


# ─────────────────────────────────────────────────────────────────────────
# #4256 / ADR-158 — the deploy dead-man, the second scheduled consumer in
# deploy-wedge-watch.yml. Code ships on green with no approval gate, so the
# one question left is whether main's green runs reached AWS. The three run
# shapes marked REAL are the job lists of live CI/CD runs on main (read-only
# `gh api …/actions/runs/<id>/jobs`, 2026-09-28), trimmed to the fields read;
# the IAM-gate shapes are SYNTHETIC because the `Deploy IAM (production gate)`
# job only exists once this ADR merges.
# ─────────────────────────────────────────────────────────────────────────

_dm_spec = importlib.util.spec_from_file_location("deadman_4256", os.path.join(_REPO, "scripts", "check_deploy_deadman.py"))
dm = importlib.util.module_from_spec(_dm_spec)
_dm_spec.loader.exec_module(dm)

from datetime import datetime, timezone  # noqa: E402

_NOW = datetime(2026, 9, 28, 8, 0, 0, tzinfo=timezone.utc)


def _j(name, conclusion, completed_at="2026-09-28T01:50:00Z", status="completed", steps=None):
    return {"name": name, "status": status, "conclusion": conclusion, "completed_at": completed_at, "steps": steps or []}


# REAL — run 36366557551 (b2f3fbb1b): Plan green 01:50:00Z, Deploy success via the fleet step.
_FLEET_DEPLOYED = [
    _j("Plan deployments", "success", "2026-09-28T01:50:00Z"),
    _j(
        "Deploy",
        "success",
        "2026-09-28T02:02:35Z",
        steps=[
            {"name": "IAM gate verdict present (dead-man,", "conclusion": "success"},
            {"name": "Fleet deploy (shared module changed)", "conclusion": "success"},
            {"name": "Deploy Lambdas", "conclusion": "skipped"},
        ],
    ),
]
# REAL — run 36367108059 (536d8716e, a dependabot CDK-CLI bump): Plan green, Deploy skipped.
_NOTHING_OWED = [_j("Plan deployments", "success", "2026-09-28T01:58:25Z"), _j("Deploy", "skipped", "2026-09-28T01:58:26Z")]
# REAL — run 36357312147 (6e2584ff0): Plan green 23:14:30Z, Deploy `failure` — its approval
# record reads `rejected … session AP` (a superseded lease rejected under the OLD routing).
_REJECTED_LEASE = [_j("Plan deployments", "success", "2026-09-27T23:14:30Z"), _j("Deploy", "failure", "2026-09-27T23:15:27Z")]


def _run(rid, sha, created, event="push"):
    return {"id": rid, "head_sha": sha * 5, "created_at": created, "event": event}


def test_deadman_job_names_are_the_ones_ci_cd_yml_declares():
    """A rename in ci-cd.yml that is not mirrored here would make every run read as
    `in-flight` (no Plan job found) — pinned against the real file."""
    with open(os.path.join(_REPO, ".github", "workflows", "ci-cd.yml")) as f:
        wf = f.read()
    for name in (dm.PLAN_JOB, dm.DEPLOY_JOB, dm.DEPLOY_IAM_JOB):
        assert f"    name: {name}\n" in wf, name
    assert f"- name: {dm.FLEET_STEP_PREFIX} (" in wf  # #4255: the one deploy path keeps the prefix


def test_deadman_classifies_the_real_run_shapes():
    cases = {
        "fleet-deployed": (_FLEET_DEPLOYED, dm.DEPLOYED),
        "nothing-owed": (_NOTHING_OWED, dm.NOTHING),
        "rejected-lease": (_REJECTED_LEASE, dm.UNDEPLOYED),
    }
    wrong = {k: dm.classify_run(_run(1, "a", "2026-09-28T01:00:00Z"), jobs, _NOW)["state"] for k, (jobs, _) in cases.items()}
    assert wrong == {k: want for k, (_, want) in cases.items()}


def test_deadman_iam_gate_shapes():
    plan = _j("Plan deployments", "success", "2026-09-28T01:00:00Z")
    parked = dm.classify_run(
        _run(1, "a", "x"),
        [plan, _j("Deploy IAM (production gate)", None, None, status="waiting"), _j("Deploy", None, None, status="pending")],
        _NOW,
    )
    assert parked["state"] == dm.IN_FLIGHT and "production gate" in parked["reason"] and parked["age_hours"] == 7.0
    rejected = dm.classify_run(_run(2, "b", "x"), [plan, _j("Deploy IAM (production gate)", "failure"), _j("Deploy", "skipped")], _NOW)
    assert rejected["state"] == dm.UNDEPLOYED and "IAM gate" in rejected["reason"]
    iam_only = dm.classify_run(_run(3, "c", "x"), [plan, _j("Deploy IAM (production gate)", "success"), _j("Deploy", "skipped")], _NOW)
    assert iam_only["state"] == dm.NOTHING
    red = dm.classify_run(_run(4, "d", "x"), [_j("Plan deployments", "failure"), _j("Deploy", "skipped")], _NOW)
    assert red["state"] == dm.NOT_GREEN


def _walk(runs_and_jobs, hours=dm.DEADLINE_HOURS):
    jobs = {r["id"]: j for r, j in runs_and_jobs}
    return dm.verdict(dm.walk([r for r, _ in runs_and_jobs], lambda r: jobs[r["id"]], _NOW), hours)


def test_deadman_alarms_on_an_undeployed_green_run_newer_than_the_last_fleet_deploy():
    state = _walk(
        [
            (_run(3, "c", "2026-09-28T02:00:00Z"), _NOTHING_OWED),
            (_run(2, "b", "2026-09-27T23:00:00Z"), _REJECTED_LEASE),
            (_run(1, "a", "2026-09-27T20:00:00Z"), _FLEET_DEPLOYED),
        ]
    )
    assert [a["run_id"] for a in state["alarms"]] == [2]
    code, text = dm.render(state)
    assert code == dm.EXIT_ALARM and dm.RECOVERY in text


def test_deadman_a_newer_fleet_deploy_supersedes_an_older_failure():
    state = _walk([(_run(2, "b", "2026-09-28T02:00:00Z"), _FLEET_DEPLOYED), (_run(1, "a", "2026-09-27T23:00:00Z"), _REJECTED_LEASE)])
    assert state["alarms"] == [] and [r["run_id"] for r in state["rows"]] == [2], "the walk stops at the fleet deploy"
    assert dm.render(state)[0] == dm.EXIT_OK


def test_deadman_another_run_at_the_same_sha_settles_it():
    per_function = [_j("Plan deployments", "success"), _j("Deploy", "success", steps=[{"name": "Deploy Lambdas", "conclusion": "success"}])]
    state = _walk(
        [(_run(2, "a", "2026-09-28T03:00:00Z", "workflow_dispatch"), per_function), (_run(1, "a", "2026-09-28T01:00:00Z"), _REJECTED_LEASE)]
    )
    assert state["alarms"] == []


def test_deadman_waits_out_the_deadline_and_never_reads_unknown_age_as_fresh():
    young = [_j("Plan deployments", "success", "2026-09-28T07:00:00Z"), _j("Deploy", "failure")]
    assert _walk([(_run(1, "a", "2026-09-28T06:00:00Z"), young)])["alarms"] == []
    unknown = [_j("Plan deployments", "success", None), _j("Deploy", "failure")]
    assert [a["run_id"] for a in _walk([(_run(1, "a", "2026-09-28T06:00:00Z"), unknown)])["alarms"]] == [1]


def test_deadman_main_exit_codes_are_the_three_way_contract(monkeypatch, capsys):
    def boom():
        raise RuntimeError("HTTP 502")

    monkeypatch.setattr(dm, "collect", boom)
    assert dm.main([]) == dm.EXIT_INDETERMINATE
    assert "✅" not in capsys.readouterr().out, "an unreadable API must never print the OK glyph"
    runs = [_run(1, "a", "2026-09-27T23:00:00Z")]
    monkeypatch.setattr(dm, "collect", lambda: (runs, lambda r: _REJECTED_LEASE))
    assert dm.main(["--hours", "0.5"]) == dm.EXIT_ALARM
    monkeypatch.setattr(dm, "collect", lambda: (runs, lambda r: _FLEET_DEPLOYED))
    assert dm.main([]) == dm.EXIT_OK
    assert len({dm.EXIT_OK, dm.EXIT_ALARM, dm.EXIT_INDETERMINATE}) == 3


def test_deadman_alert_throttles_one_dispatch_per_episode(monkeypatch):
    calls = []
    state = {"alarms": [{"run_id": 7}], "rows": [], "hours": 4.0}
    marker = f"{dm.ALERT_MARKER_PREFIX}{dm.episode_key(state)}{dm.ALERT_MARKER_SUFFIX}"
    monkeypatch.setattr(dm, "_gh_api", lambda path: [{"number": 9, "body": f"x {marker}"}])
    monkeypatch.setattr(dm, "_gh", lambda args, stdin=None: calls.append(args) or "")
    assert dm.maybe_alert(state, "🛑 head", _NOW).startswith("alert-throttled")
    assert calls == []
    monkeypatch.setattr(dm, "_gh_api", lambda path: [])
    assert dm.maybe_alert(state, "🛑 head", _NOW).startswith("alert-fired")
    assert any(f"labels[]={dm.ALERT_LABEL}" in a for c in calls for a in c), "the tracking issue carries its one label"
    assert any(f"repos/{dm.REPO}/dispatches" in c for c in calls)


def test_deadman_is_wired_as_the_last_unskippable_step_of_the_watch():
    with open(os.path.join(_REPO, ".github", "workflows", "deploy-wedge-watch.yml")) as f:
        wf = f.read()
    steps = wf.split("\n      - ")
    last = steps[-1]
    assert last.startswith("name: Deploy dead-man"), "the dead-man must be the final step"
    assert "if: ${{ !cancelled() }}" in last
    assert "python3 scripts/check_deploy_deadman.py --alert" in last
    assert "continue-on-error" not in last and "|| true" not in last


# ─────────────────────────────────────────────────────────────────────────
# #4472 — plan's diff base is the LAST SUCCESSFUL DEPLOY, not GITHUB_SHA~1.
# The deploy job's concurrency group cancels an older pending run, so a `~1`
# base dropped the superseded run's merge forever (#4452's weekly-digest fix,
# 2026-09-29). Replay: A merges, its run is cancelled; B merges; B's plan must
# list A's files.
# ─────────────────────────────────────────────────────────────────────────

import re  # noqa: E402
import subprocess  # noqa: E402

_CANCELLED = [_j("Plan deployments", "success"), _j("Deploy", "cancelled")]
_IN_FLIGHT = [_j("Plan deployments", None, None, status="in_progress")]


def test_last_deployed_sha_skips_cancelled_failed_and_in_flight_runs():
    runs = [
        (_run(4, "d", "2026-09-29T18:00:00Z"), _IN_FLIGHT),  # B — this run, planning now
        (_run(3, "c", "2026-09-29T17:42:00Z"), _CANCELLED),  # A — superseded
        (_run(2, "b", "2026-09-29T17:00:00Z"), _REJECTED_LEASE),
        (_run(1, "a", "2026-09-29T16:00:00Z"), _FLEET_DEPLOYED),
    ]
    jobs = {r["id"]: j for r, j in runs}
    assert dm.last_deployed_sha([r for r, _ in runs], lambda r: jobs[r["id"]], _NOW) == "a" * 5
    assert dm.last_deployed_sha([r for r, _ in runs[:3]], lambda r: jobs[r["id"]], _NOW) is None, "no deploy in the window → None"


def test_deploy_base_mode_prints_only_the_sha_or_exits_indeterminate(monkeypatch, capsys):
    monkeypatch.setattr(dm, "collect", lambda: ([_run(1, "a", "2026-09-29T16:00:00Z")], lambda r: _FLEET_DEPLOYED))
    assert dm.main(["--deploy-base"]) == dm.EXIT_OK
    assert capsys.readouterr().out == "a" * 5 + "\n"
    monkeypatch.setattr(dm, "collect", lambda: ([_run(1, "a", "2026-09-29T16:00:00Z")], lambda r: _CANCELLED))
    assert dm.main(["--deploy-base"]) == dm.EXIT_INDETERMINATE
    assert capsys.readouterr().out == "", "no base → stdout empty, so plan deploys everything"

    def boom():
        raise RuntimeError("HTTP 502")

    monkeypatch.setattr(dm, "collect", boom)
    assert dm.main(["--deploy-base"]) == dm.EXIT_INDETERMINATE
    assert capsys.readouterr().out == ""


def _plan_changed_command() -> str:
    """The `CHANGED=$(git diff … HEAD -- lambdas/ mcp/ mcp_server.py` command in plan's
    non-deploy_all branch, read from the real ci-cd.yml."""
    with open(os.path.join(_REPO, ".github", "workflows", "ci-cd.yml")) as f:
        wf = f.read()
    step = wf.split("- name: Detect changes and build deploy plan", 1)[1].split("\n      - name:", 1)[0]
    m = re.search(r"CHANGED=\$\((git diff --name-only \S+ HEAD -- lambdas/ mcp/ mcp_server\.py)", step)
    assert m, "plan's CHANGED diff command not found"
    return m.group(1)


def test_superseded_run_a_rolls_into_run_b_plan(tmp_path):
    """A-cancelled → B-deploys: B's plan diff, executed as ci-cd.yml spells it, lists A's
    file. Mutation control: put the base back to "${GITHUB_SHA}~1" → A's file drops out."""
    repo = str(tmp_path)

    def git(*a):
        return subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True, text=True).stdout.strip()

    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    shas = {}
    for name, path in (
        ("base", "lambdas/emails/daily_brief_lambda.py"),
        ("A", "lambdas/emails/weekly_digest_lambda.py"),
        ("B", "mcp/tools_health.py"),
    ):
        os.makedirs(os.path.join(repo, os.path.dirname(path)), exist_ok=True)
        with open(os.path.join(repo, path), "w") as f:
            f.write(name)
        git("add", "-A")
        git("commit", "-qm", name)
        shas[name] = git("rev-parse", "HEAD")

    runs = [
        (_run(3, "x", "2026-09-29T18:00:00Z"), _IN_FLIGHT),
        (_run(2, "y", "2026-09-29T17:42:00Z"), _CANCELLED),
        (_run(1, "z", "2026-09-29T17:00:00Z"), _FLEET_DEPLOYED),
    ]
    runs[0][0]["head_sha"], runs[1][0]["head_sha"], runs[2][0]["head_sha"] = shas["B"], shas["A"], shas["base"]
    jobs = {r["id"]: j for r, j in runs}
    base = dm.last_deployed_sha([r for r, _ in runs], lambda r: jobs[r["id"]], _NOW)
    assert base == shas["base"]

    env = {**os.environ, "DEPLOY_BASE": base, "GITHUB_SHA": shas["B"]}
    out = subprocess.run(["bash", "-c", _plan_changed_command()], cwd=repo, env=env, check=True, capture_output=True, text=True).stdout
    changed = set(out.split())
    assert "lambdas/emails/weekly_digest_lambda.py" in changed, f"superseded run A's merge is missing from B's plan: {changed}"
    assert "mcp/tools_health.py" in changed


# #4472 box 2 — live Lambda older than its source on main (the nightly advisory).
_T = lambda s: datetime.fromisoformat(s).replace(tzinfo=timezone.utc)  # noqa: E731


def test_aws_last_modified_parses_to_an_aware_instant():
    assert dm._parse_aws_ts("2026-09-29T18:00:59.000+0000") == _T("2026-09-29T18:00:59")
    assert dm._parse_aws_ts(None) is None and dm._parse_aws_ts("garbage") is None


def test_stale_functions_replays_the_weekly_digest_incident():
    """#4452 merged 17:42Z; the live weekly-digest zip was 18:00:59Z from an older run's
    tree — here modelled as a zip older than the merge. Fresh, in-grace and absent shapes."""
    now = _T("2026-09-30T08:00:00")
    owed = {
        "weekly-digest": (_T("2026-09-29T17:42:00"), "lambdas/emails/weekly_digest_lambda.py changed"),
        "daily-brief": (_T("2026-09-29T17:42:00"), "a shared module / bundled config changed"),
        "coach-nudge": (_T("2026-09-30T07:30:00"), "lambdas/coach/coach_nudge.py changed"),  # inside the grace window
        "gone": (_T("2026-09-29T10:00:00"), "lambdas/x.py changed"),
    }
    live = {"weekly-digest": _T("2026-09-29T16:59:00"), "daily-brief": _T("2026-09-29T18:10:00"), "coach-nudge": _T("2026-09-29T01:00:00")}
    rows = dm.stale_functions(live, owed, now)
    assert [r["function"] for r in rows] == ["gone", "weekly-digest"]
    assert "not listed by AWS" in rows[0]["why"], "a mapped function AWS does not list is never read as fresh"
    code, text = dm.render_stale(rows)
    assert code == dm.EXIT_ALARM and dm.RECOVERY in text and "weekly-digest" in text
    assert dm.render_stale([])[0] == dm.EXIT_OK


def test_stale_lambdas_mode_is_indeterminate_when_aws_is_unreadable(monkeypatch, capsys):
    def boom():
        raise RuntimeError("ExpiredToken")

    monkeypatch.setattr(dm, "collect_last_modified", boom)
    assert dm.main(["--stale-lambdas"]) == dm.EXIT_INDETERMINATE
    assert "✅" not in capsys.readouterr().out


def test_stale_lambdas_is_wired_as_an_advisory_step_of_the_nightly_drift_workflow():
    with open(os.path.join(_REPO, ".github", "workflows", "config-drift.yml")) as f:
        wf = f.read()
    step = [s for s in wf.split("\n      - ") if "check_deploy_deadman.py --stale-lambdas" in s]
    assert len(step) == 1, "the stale-Lambda check must be one step of config-drift.yml"
    assert "if: always()" in step[0] and "continue-on-error: true" in step[0]


# #4472 box 2 (sha basis) — does the LIVE bundle's build_info.git_sha CONTAIN the commit the
# function owes? LastModified cannot tell which tree shipped: a superseded run deploying
# late stamps a fresh LastModified over old code (#2377's 2026-08-08 race).
import io as _io  # noqa: E402
import json as _json  # noqa: E402
import zipfile as _zipfile  # noqa: E402


def _bundle_zip(git_sha, members=400):
    """A bundle shaped like deploy/build_bundle.py's output: the tree at the zip root plus
    build_info.json carrying git_fingerprint()'s keys (live 2026-10-02: 104 of 104 mapped
    functions carried one)."""
    buf = _io.BytesIO()
    with _zipfile.ZipFile(buf, "w", _zipfile.ZIP_DEFLATED) as zf:
        for i in range(members):  # ~2.5 MB stored, the live bundle's order of size (CodeSize 2-5 MB)
            zf.writestr(f"common/mod_{i:04d}.py", "".join(f"X_{i}_{j} = {j * 7919 % 104729}\n" for j in range(400)), _zipfile.ZIP_STORED)
        if git_sha is not None:
            info = {
                "built_at": "2026-10-01T23:52:10Z",
                "built_at_source": "commit",
                "builder": "CI/CD Pipeline",
                "dirty": None,
                "dirty_scope": None,
                "git_sha": git_sha,
                "git_short_sha": git_sha[:8],
                "schema": 1,
            }
            zf.writestr("build_info.json", _json.dumps(info, sort_keys=True, indent=2) + "\n")
        zf.writestr("emails/weekly_digest_lambda.py", "def lambda_handler(e, c):\n    return 1\n")
    return buf.getvalue()


class _S3Ranged:
    """An in-memory presigned-URL server with S3's Range semantics (206 + Content-Range);
    `honour_range=False` answers 200 with the whole body and no Content-Range."""

    def __init__(self, body, honour_range=True):
        self.body, self.honour, self.served = body, honour_range, 0

    def __call__(self, req, timeout=None):
        rng = req.headers.get("Range") or req.get_header("Range")
        body, headers = self.body, {}
        if self.honour and rng:
            spec = rng.split("=", 1)[1]
            lo, hi = spec.split("-")
            n = len(self.body)
            start, end = (n - int(hi), n - 1) if lo == "" else (int(lo), min(int(hi), n - 1))
            start = max(0, start)
            body, headers = self.body[start : end + 1], {"Content-Range": f"bytes {start}-{end}/{n}"}
        self.served += len(body)

        class _Resp:
            def __init__(self):
                self.headers = headers

            def read(self):
                return body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return _Resp()


def test_build_sha_is_read_from_the_live_bundle_over_ranged_gets():
    sha = "612fe47d9" + "0" * 31
    blob = _bundle_zip(sha)
    server = _S3Ranged(blob)
    url = "https://awslambda-us-west-2-tasks.s3.us-west-2.amazonaws.com/snapshots/205930651321/weekly-digest-x?X-Amz-Signature=s"
    assert dm.read_build_sha(url, opener=server) == sha
    assert server.served < len(blob) / 2, "a ranged read, never the whole bundle"
    assert dm.read_build_sha(url, opener=_S3Ranged(blob, honour_range=False)) == sha, "a server ignoring Range still reads"
    assert dm.read_build_sha(url, opener=_S3Ranged(_bundle_zip(None))) is None, "no build_info.json → no fingerprint"


def _linear_repo(tmp_path, names):
    repo = str(tmp_path)

    def git(*a):
        return subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True, text=True).stdout.strip()

    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    shas = {}
    for name in names:
        with open(os.path.join(repo, name), "w") as f:
            f.write(name)
        git("add", "-A")
        git("commit", "-qm", name)
        shas[name] = git("rev-parse", "HEAD")
    git("checkout", "-q", "-b", "side", shas[names[0]])
    with open(os.path.join(repo, "side"), "w") as f:
        f.write("side")
    git("add", "-A")
    git("commit", "-qm", "side")
    shas["side"] = git("rev-parse", "HEAD")
    return repo, shas


def test_stale_by_build_sha_replays_a_superseded_runs_undeployed_merge(tmp_path):
    """base → A (weekly-digest fix; its run CANCELLED) → B (mcp change; its run deployed
    only B's diff). weekly-digest's live bundle is base's build — and its LastModified is
    NEWER than A, so the LastModified check reads it fresh; the sha basis does not."""
    dm._ensure_deploy_path()
    import bundle_ancestry

    repo, s = _linear_repo(tmp_path, ["base", "A", "B"])

    def oracle(a, b):
        return bundle_ancestry.git_is_ancestor(a, b, repo_root=repo)

    now = _T("2026-09-30T08:00:00")
    owed = {
        "weekly-digest": (s["A"], _T("2026-09-29T17:42:00"), "lambdas/emails/weekly_digest_lambda.py changed"),
        "life-platform-mcp": (s["B"], _T("2026-09-29T18:00:00"), "mcp/tools_health.py changed"),
        "daily-brief": (s["A"], _T("2026-09-29T17:42:00"), "a shared module / bundled config changed"),
        "laptop-lane": (s["A"], _T("2026-09-29T17:42:00"), "lambdas/x.py changed"),
        "pre-2377": (s["A"], _T("2026-09-29T17:42:00"), "lambdas/y.py changed"),
        "unfetched": (s["A"], _T("2026-09-29T17:42:00"), "lambdas/z.py changed"),
        "in-grace": (s["B"], _T("2026-09-30T07:30:00"), "lambdas/w.py changed"),
    }
    deployed = {
        "weekly-digest": s["base"],  # the superseded run's file never shipped
        "life-platform-mcp": s["B"],
        "daily-brief": s["B"],  # B contains A → fresh
        "laptop-lane": s["side"],  # diverged: a lane-branch deploy without A
        "pre-2377": None,  # no build_info.json → LastModified basis
        "unfetched": "f" * 40,  # a sha this checkout cannot resolve → LastModified basis
        "in-grace": s["base"],
    }
    lm = _T("2026-09-29T18:00:59")  # every function touched AFTER A merged — the race shape
    last_modified = {fn: lm for fn in owed}
    last_modified["unfetched"] = _T("2026-09-29T10:00:00")

    rows = dm.stale_by_build_sha(deployed, last_modified, owed, now, oracle)
    got = {r["function"]: r["why"] for r in rows}
    assert sorted(got) == ["laptop-lane", "unfetched", "weekly-digest"], got
    assert f"live build {s['base'][:8]} does not contain {s['A'][:8]} (behind)" in got["weekly-digest"]
    assert "(diverged)" in got["laptop-lane"]
    assert "LastModified basis: live build ffffffff not resolvable here" in got["unfetched"]
    lm_only = [r["function"] for r in dm.stale_functions(last_modified, {k: v[1:] for k, v in owed.items()}, now)]
    assert lm_only == ["unfetched"], "control: LastModified alone reads weekly-digest and laptop-lane fresh — the sha basis catches them"
    code, text = dm.render_stale(rows)
    assert code == dm.EXIT_ALARM and dm.RECOVERY in text and "weekly-digest" in text


def test_stale_lambdas_mode_reads_the_sha_basis_and_prints_its_coverage(monkeypatch, capsys):
    monkeypatch.setattr(
        dm, "collect_last_modified", lambda: {"weekly-digest": _T("2026-09-29T18:00:59"), "daily-brief": _T("2026-09-29T18:00:59")}
    )
    monkeypatch.setattr(
        dm,
        "collect_owed_commits",
        lambda: {
            "weekly-digest": ("a" * 40, _T("2026-09-29T17:42:00"), "w changed"),
            "daily-brief": ("a" * 40, _T("2026-09-29T17:42:00"), "d changed"),
        },
    )
    monkeypatch.setattr(dm, "mapped_regions", lambda: {"weekly-digest": "us-west-2", "daily-brief": "us-west-2"})
    monkeypatch.setattr(dm, "collect_deployed_shas", lambda fns: {"weekly-digest": "b" * 40, "daily-brief": None})
    seen = []

    def oracle(a, b):
        seen.append((a, b))
        return a == "b" * 40 and b == "a" * 40  # live b is an ANCESTOR of owed a → stale

    import bundle_ancestry

    monkeypatch.setattr(bundle_ancestry, "git_is_ancestor", oracle)
    assert dm.main(["--stale-lambdas"]) == dm.EXIT_ALARM
    out = capsys.readouterr().out
    assert "weekly-digest" in out and "bbbbbbbb does not contain aaaaaaaa" in out
    assert "basis: build_info.git_sha for 1 of 2 mapped functions; LastModified for 1: daily-brief" in out
    assert "judged: 2 of 2; 0 owe a commit inside the 2 h grace window" in out, "a pass must say how much it judged"
