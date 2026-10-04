"""tests/test_reader_surface_gate_4589.py — the two AI checks run only when a reader surface changed (#4589).

What is pinned:

  1. the surface is DERIVED — the site-API entry points' import closure reaches the
     modules a request executes, and stops short of a producer that only runs on a cron;
  2. the decision — a reader-page diff RUNS (the mutation control the issue asks for),
     a producer/docs-only diff SKIPS with a logged reason, and every uncertainty
     (no base, a non-ancestor base, a git error, an underivable surface) RUNS;
  3. the wiring — both CI homes of the AI judges consult the gate, the deterministic
     sweep is never gated, and the tier-3 pause still lives inside the judge.
"""

import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import reader_surface as rs  # noqa: E402


@pytest.fixture(scope="module")
def surface():
    return rs.reader_surface()


# ── 1. the derived surface ─────────────────────────────────────────────────────


def test_the_request_time_closure_reaches_what_a_request_executes(surface):
    rt = surface["request_time"]
    for path in rs.REQUEST_TIME_ENTRIES:
        assert path in rt
    # A module the API imports transitively, not listed anywhere by hand.
    assert "lambdas/web/site_api_common.py" in rt
    assert "lambdas/common/constants.py" in rt
    assert len(rt) > 50, f"the import walk stopped early: {len(rt)} modules"


def test_a_cron_only_producer_is_not_on_the_surface(surface):
    """The daily brief renders nothing at request time — its output lands on its next cron."""
    hits = rs.classify(["lambdas/emails/daily_brief_lambda.py", "docs/DECISIONS.md", "cdk/stacks/monitoring_stack.py"], surface)
    assert hits == [], hits


def test_the_judges_and_their_wiring_are_on_the_surface(surface):
    kinds = dict(
        rs.classify(["tests/visual_ai_qa.py", "lambdas/operational/reader_truth_qa.py", ".github/workflows/visual-qa.yml"], surface)
    )
    assert set(kinds) == {"tests/visual_ai_qa.py", "lambdas/operational/reader_truth_qa.py", ".github/workflows/visual-qa.yml"}


def test_a_missing_entry_point_fails_loudly_never_shrinks_the_surface():
    with pytest.raises(FileNotFoundError):
        rs.import_closure(["lambdas/web/no_such_handler.py"])


# ── 2. the decision ────────────────────────────────────────────────────────────


@pytest.fixture()
def fake_git(monkeypatch):
    """`decide()` with the git calls replaced: merge-base OK, diff returns `changed`."""
    state = {"changed": [], "ancestor": True}

    def _git(*args):
        assert args[0] == "diff"
        return "\n".join(state["changed"]) + "\n"

    real_run = subprocess.run

    def _run(cmd, *a, **k):
        if cmd[:3] == ["git", "merge-base", "--is-ancestor"]:
            if not state["ancestor"]:
                raise subprocess.CalledProcessError(1, cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(rs, "_git", _git)
    monkeypatch.setattr(rs.subprocess, "run", _run)
    return state


def test_a_reader_page_diff_runs_the_ai_checks(fake_git):
    """THE MUTATION CONTROL the issue names: a reader-page diff must still run them."""
    fake_git["changed"] = ["site/coaching/index.html", "docs/DECISIONS.md"]
    run, reason = rs.decide("abc123", "HEAD")
    assert run is True
    assert reason.startswith("RUN") and "site/coaching/index.html (site)" in reason


def test_a_site_api_handler_diff_runs_the_ai_checks(fake_git):
    fake_git["changed"] = ["lambdas/web/site_api_common.py"]
    run, reason = rs.decide("abc123", "HEAD")
    assert run is True and "request-time API" in reason


def test_a_producer_only_diff_skips_with_a_logged_reason(fake_git):
    fake_git["changed"] = ["lambdas/emails/daily_brief_lambda.py", "docs/DECISIONS.md", "cdk/stacks/monitoring_stack.py"]
    run, reason = rs.decide("abc123", "HEAD")
    assert run is False
    assert reason.startswith("SKIP") and "3 file(s) changed" in reason and "#4589" in reason
    assert "deterministic sweep still runs" in reason


def test_every_uncertainty_runs(fake_git, monkeypatch):
    assert rs.decide("", "HEAD")[0] is True
    fake_git["ancestor"] = False
    assert rs.decide("abc123", "HEAD")[0] is True
    fake_git["ancestor"] = True

    def _boom(*a):
        raise subprocess.CalledProcessError(128, ["git", "diff"])

    monkeypatch.setattr(rs, "_git", _boom)
    assert rs.decide("abc123", "HEAD")[0] is True


def test_an_underivable_surface_runs(fake_git, monkeypatch):
    fake_git["changed"] = ["docs/DECISIONS.md"]

    def _broken(*a, **k):
        raise FileNotFoundError("entry renamed")

    monkeypatch.setattr(rs, "reader_surface", _broken)
    run, reason = rs.decide("abc123", "HEAD")
    assert run is True and "could not be derived" in reason


def test_github_output_carries_the_verdict_and_the_reason(fake_git, tmp_path, monkeypatch):
    fake_git["changed"] = ["docs/DECISIONS.md"]
    out = tmp_path / "gh_out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert rs.main(["--base", "abc123", "--github-output"]) == 0
    text = out.read_text()
    assert "run_ai=false\n" in text and "reason=SKIP" in text


# ── 3. the wiring ──────────────────────────────────────────────────────────────


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def test_the_deploy_time_vision_gate_consults_the_reader_surface():
    wf = _read(".github/workflows/ci-cd.yml")
    assert 'scripts/reader_surface.py --base "${DEPLOY_BASE}" --github-output' in wf
    assert "deploy_base: ${{ steps.base.outputs.sha }}" in wf
    # RUN keeps the exact pre-#4589 judge invocation; SKIP keeps the deterministic sweep.
    assert "python3 tests/visual_qa.py --screenshot --ai-qa --ai-qa-max-tier 1" in wf
    assert 'if [ "${RUN_AI}" = "false" ]; then' in wf


def test_the_scheduled_judges_consult_the_reader_surface_per_judge_window():
    wf = _read(".github/workflows/visual-qa.yml")
    assert "scripts/reader_surface.py --since-hours 24" in wf, "the daily reader-truth pass is not gated"
    assert "scripts/reader_surface.py --since-hours 168" in wf, "the Sunday vision pass is not gated"
    assert 'if [ "${{ github.event_name }}" = "schedule" ] && [ "$LEVEL" = "standard" ]; then' in wf
    assert "fetch-depth: 0" in wf, "a depth-1 clone resolves no base, so the gate could never skip"


def test_the_tier_3_pause_still_lives_inside_the_judge():
    """The gate only decides whether --ai-qa is passed; the budget pause is the judge's own."""
    src = _read("tests/visual_ai_qa.py")
    assert "SKIPPED-BY-BUDGET" in src
