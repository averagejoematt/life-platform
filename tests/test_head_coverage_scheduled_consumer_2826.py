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
