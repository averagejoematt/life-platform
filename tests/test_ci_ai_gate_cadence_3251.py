"""#3251 (owner decision, option C1, 2026-08-30) — the AI CI gate cadence split is a pin,
not a comment.

Per-deploy copies (ci-cd.yml, site-deploy.yml) run the VISION gate only
(`--ai-qa --ai-qa-max-tier 1`); the PROSE judge (`--reader-truth`) runs in the daily
standalone (visual-qa.yml) on every fire unless the qa-level dial says lean/off.
Measured basis (LifePlatform/AI per-gate rows, n=16 deploy runs): reader_truth_qa
$0.193/run = 81% of the $0.239 pair, while the one recorded catch was the vision gate's.

Why a test: the decision first existed only as prose in issue comments (#3251's own
finding), and the workflow flags are hardcoded literals that a well-meaning "keep the
three copies in sync" edit would re-align in either direction. A `--reader-truth`
re-added to a deploy copy silently re-prices the gate ~5x; one dropped from the
standalone silently removes the platform's only CI prose truth-check. Both red here.
scripts/gate_census.py's entry for the per-deploy job is held to the workflow's actual
invocation for the same reason. Cadence is a workflow question; the budget band is not
touched by C1 — both gates stay in ADR-125's operator-truth placement (cutoff 3).
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows"
PER_DEPLOY = ("ci-cd.yml", "site-deploy.yml")
STANDALONE = "visual-qa.yml"
_INVOKE = re.compile(r"^\s*python3 tests/visual_qa\.py\b.*$", re.M)


def _invocations(name: str) -> list[str]:
    lines = _INVOKE.findall((WF / name).read_text(encoding="utf-8"))
    assert lines, f"{name}: no `python3 tests/visual_qa.py` invocation found"
    return [ln.strip() for ln in lines]


# #4589 (owner ruling, platform plan 2026-10-03 decision 4): ci-cd.yml's deploy-time copy runs the
# vision judge only when scripts/reader_surface.py says a reader surface changed. On SKIP it runs this
# exact deterministic-only invocation — the one sanctioned second line, and only behind RUN_AI=false.
_GATED_SKIP_INVOCATION = (
    'python3 tests/visual_qa.py --screenshot --ai-qa-skipped "${SKIP_REASON}"'  # #4652: the skip is recorded by the sweep
)


def _ai_invocations(name: str) -> list[str]:
    """The judge-running invocation(s): every sweep line except #4589's guarded SKIP line."""
    invs = _invocations(name)
    if name == "ci-cd.yml":
        text = (WF / name).read_text(encoding="utf-8")
        skip = [c for c in invs if c == _GATED_SKIP_INVOCATION]
        assert len(skip) == 1, f"{name}: expected exactly one #4589 SKIP invocation, got {skip}"
        guard = text.index('if [ "${RUN_AI}" = "false" ]; then')
        assert guard < text.index(_GATED_SKIP_INVOCATION + "\n"), f"{name}: the SKIP invocation is not behind the RUN_AI=false guard"
        invs = [c for c in invs if c != _GATED_SKIP_INVOCATION]
    return invs


def test_per_deploy_copies_run_the_vision_gate_only():
    for name in PER_DEPLOY:
        invs = _ai_invocations(name)
        assert len(invs) == 1, f"{name}: expected exactly one sweep invocation, got {invs}"
        (cmd,) = invs
        flags = cmd.split()
        assert (
            "--screenshot" in flags and "--ai-qa" in flags and "--ai-qa-max-tier 1" in cmd
        ), f"{name}: the deploy-time vision gate must keep the #1428 shape (--screenshot --ai-qa --ai-qa-max-tier 1): {cmd}"
        assert "--reader-truth" not in flags, (
            f"{name}: --reader-truth is back on a per-deploy copy — that reverses #3251's C1 decision "
            f"(~$0.19/run, 81% of the pair) without a recorded reversal: {cmd}"
        )


def test_daily_standalone_is_the_prose_judges_home():
    text = (WF / STANDALONE).read_text(encoding="utf-8")
    (cmd,) = _invocations(STANDALONE)
    assert "steps.cadence.outputs.reader_truth_flag" in cmd, f"{STANDALONE}: the sweep no longer passes the reader-truth flag: {cmd}"
    assert (
        'RT="--reader-truth"' in text
    ), f"{STANDALONE}: the cadence step no longer defaults --reader-truth ON — the only CI prose check went dark"
    cleared = text.count('RT=""')
    assert cleared == 3, (
        f"{STANDALONE}: RT is cleared in {cleared} branches; exactly three are sanctioned — qa-level off, lean, and "
        "#4589's reader-surface SKIP (owner ruling 2026-10-03) — a fourth silently removes the platform's only CI "
        "prose truth-check"
    )
    # The #4589 clear is the one that is conditional on a computed diff: it must sit inside the SKIP arm.
    assert 'case "$V" in *"(#4589): SKIP"*) RT=""' in text, f"{STANDALONE}: the third RT clear is not the #4589 SKIP arm"
    assert text.index('RT="--reader-truth"') < text.index('RT=""'), f"{STANDALONE}: the default must be set before any branch clears it"


def test_gate_census_records_the_live_per_deploy_command():
    census = (ROOT / "scripts" / "gate_census.py").read_text(encoding="utf-8")
    m = re.search(r'"ci::ci-cd\.yml::visual-qa::\d+": Proof\(.*?command="([^"]+)"', census, re.S)
    assert m, "the per-deploy visual-qa census entry vanished from scripts/gate_census.py"
    (live,) = _ai_invocations("ci-cd.yml")
    assert m.group(1) == live, f"gate census says {m.group(1)!r} but ci-cd.yml runs {live!r} — update the census with the workflow (#3251)"


def test_c1_changed_cadence_not_the_budget_band():
    from ai import budget_guard  # lambdas/ on sys.path via conftest

    assert set(budget_guard.CI_GATE_FEATURES) == {"reader_truth_qa", "visual_ai_qa"}
    for gate in budget_guard.CI_GATE_FEATURES:
        assert (
            budget_guard._FEATURE_CUTOFF[gate] == budget_guard._HARD_STOP_TIER
        ), f"{gate}: left the operator-truth placement — #3251 moved the prose judge's CADENCE, never its band (ADR-125)"
