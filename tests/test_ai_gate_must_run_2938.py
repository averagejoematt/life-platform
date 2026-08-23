"""#2938 — a requested AI gate that graded nothing is a FAILURE, not a warning.

THE OBSERVED DEFECT (2026-08-21, run 32509917798, job 96909117231 — the deploy-gating
`visual-qa` job on a real fleet deploy):

    ── AI-vision QA (Claude / Bedrock) — tier <= 1: 6/92 pages ──
      ⚠ AI-QA unavailable — could not import bedrock_client: No module named 'boto3'
    ── Reader-truth QA (phase-aware, Claude / Bedrock) ──
      ⚠ AI-QA unavailable — could not import bedrock_client: No module named 'boto3'
    ── Leak-token sweep (deterministic, #1448) ──
      ✅ 96 URL(s) checked (0 NOT checked), 0 finding(s)

**and the job concluded `success`.** `boto3` was never installed in ANY of the three
visual-qa workflow copies (`ci-cd.yml`, `site-deploy.yml`, `visual-qa.yml`), so both AI
gates had been structurally dark on the deploy path while `CLAUDE.md` and ADR-076
described them as gating since 2026-06-05 — "a deterministic FAIL or AI 'high' verdict
blocks the pipeline". Not a credentials problem: `permissions: id-token: write` is set
and the job configures OIDC; the import fails first.

THE MISSING DEPENDENCY IS THE TRIGGER; THE DEFECT IS `⚠` + exit 0. Installing boto3
alone would leave the identical silent pass one outage, one rename, one dependency
bump away. `run_sweep` returned `failed == 0`, reading page failures only, so an AI
status of "unavailable" had no effect on the exit code whatsoever.

WHAT IS AND IS NOT A FAILURE. `skipped_by_budget` is a designed, honest pause (ADR-125
tier 3, #1440/#1927) that already reports itself three ways and must stay a pause.
Everything else means the gate was asked for and graded nothing: `unavailable`
(dependency/import gone) and `no_surfaces` (reader-truth requested, no prose captured)
are both blindness, not health.

This compounds #1927, which moved these same two gates out of budget band 1 precisely
because they were "dark 26 of 30 days while still reporting green". That fixed the
budget cause. This is a second, structural cause with the same signature.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from visual_qa import requested_ai_gate_failures  # noqa: E402

UNAVAILABLE = {"status": "unavailable", "detail": "bedrock_client unavailable"}
PAUSED = {"status": "skipped_by_budget", "tier": 3}
OK = {"status": "ok"}


def _both(ai_status, rt_status, ai_requested=True, rt_requested=True):
    return requested_ai_gate_failures([("AI-vision QA", ai_requested, ai_status), ("Reader-truth QA", rt_requested, rt_status)])


def test_the_verbatim_production_shape_now_fails():
    """THE regression: both gates requested, both unavailable, job previously green."""
    failures = _both(UNAVAILABLE, UNAVAILABLE)
    assert len(failures) == 2, f"the exact production shape must fail both gates, got {failures}"
    assert all("bedrock_client unavailable" in f for f in failures)


def test_a_budget_pause_is_NOT_a_failure():
    """The one sanctioned non-run. Failing here would red the pipeline every time the
    platform deliberately conserves Bedrock spend at tier 3 — turning a designed pause
    into an outage, which is the opposite of what ADR-125 asks for."""
    assert _both(PAUSED, PAUSED) == []


def test_a_clean_run_is_not_a_failure():
    assert _both(OK, {"status": "ok", "findings": 0}) == []


def test_a_gate_that_was_not_requested_is_not_a_failure():
    """A deterministic-only sweep (no --ai-qa/--reader-truth) must stay green."""
    assert _both(None, None, ai_requested=False, rt_requested=False) == []


def test_no_surfaces_is_a_failure():
    """Reader-truth was asked for and found no prose to grade. 'Checked nothing'
    is not 'found nothing wrong'."""
    failures = _both(None, {"status": "no_surfaces"}, ai_requested=False)
    assert failures == ["Reader-truth QA: no_surfaces"]


def test_a_missing_status_dict_is_a_failure():
    """If the assessor returns nothing at all, that is the least trustworthy state of
    the lot — it must not read as a pass by omission."""
    failures = _both(None, None, rt_requested=False)
    assert failures == ["AI-vision QA: no status returned"]


def test_an_unknown_future_status_fails_closed():
    """A status nobody has taught this function about must fail, not pass. The
    sanctioned set is an allowlist for exactly this reason."""
    assert _both({"status": "some_new_state_2027"}, OK, rt_requested=True) == ["AI-vision QA: some_new_state_2027"]


def test_only_the_failing_gate_is_named():
    """Scope: one gate down must not implicate the other, or the operator cannot tell
    which half of the pass is real."""
    assert _both(UNAVAILABLE, OK) == ["AI-vision QA: bedrock_client unavailable"]
    assert _both(OK, UNAVAILABLE) == ["Reader-truth QA: bedrock_client unavailable"]


# ── the workflows must actually install the dependency ───────────────────────


def _workflow(name):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return open(os.path.join(root, ".github", "workflows", name)).read()


def test_every_visual_qa_copy_installs_boto3():
    """Guard the SET, not the instance. The gate is duplicated across three workflows
    and ALL THREE were missing boto3 — fixing one would leave the deploy path or the
    site path dark while the other looked fixed."""
    for name in ("ci-cd.yml", "site-deploy.yml", "visual-qa.yml"):
        text = _workflow(name)
        assert "ci_pins.py playwright boto3 botocore" in text, f"{name}'s visual-qa job does not install boto3 — its AI gates cannot run"


def test_boto3_is_pinned_through_ci_pins_not_a_literal():
    """CQ-01 (#2609): versions are READ from requirements-dev.txt, never copied into a
    workflow, or the pin drifts silently."""
    for name in ("ci-cd.yml", "site-deploy.yml", "visual-qa.yml"):
        text = _workflow(name)
        assert "pip install boto3==" not in text, f"{name} hardcodes a boto3 version instead of reading the pin"


def test_the_exit_code_actually_depends_on_this():
    """A helper nobody wires into the return value is the very shape this issue is
    about. Pins the call site by source inspection."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "tests", "visual_qa.py")).read()
    assert (
        "return failed == 0 and unevaluated == 0 and not ai_gate_failures" in src
    ), "run_sweep's return value ignores the AI-gate verdict — the fix is decorative"
