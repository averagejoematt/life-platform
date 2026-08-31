"""
tests/test_batch_feasibility_interactive_3372.py — the batch trip-wire's exclusion set (#3372).

`scripts/batch_feasibility.py` (the ADR-132 trip-wire) excludes `_INTERACTIVE`
producers from the batch-eligibility floor. #3372: deadline-critical CI/QA volume
(visual-ai-qa, reader-truth-qa, life-platform-qa-smoke, coach-quality-gate) was
counted toward the floor, so the wire read FEASIBLE on volume that cannot take
Batch's 24h SLA — a gating pipeline cannot wait 24h for a verdict.

Pins:
  1. The exclusion SET, by equality — adding or removing a caller class is a
     conscious decision here, never a silent drift (guard the set, not the
     instance).
  2. Each excluded string against its EMITTER, so a rename on the emitting side
     (which would silently re-include the volume under the new name) fails here:
     the CI labels against `bedrock_client.ATTRIBUTABLE_FEATURES`, the Lambda
     names against the CDK `function_name=` literals.

Run:  python3 -m pytest tests/test_batch_feasibility_interactive_3372.py -v
"""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

import batch_feasibility  # noqa: E402
from ai import bedrock_client  # noqa: E402

# The four real-time/interactive producers (AC of #409) + the four deadline-critical
# CI/QA gates (#3372). A new member lands by editing BOTH the script and this pin.
EXPECTED_INTERACTIVE = {
    "life-platform-site-api-ai",
    "life-platform-canary",
    "ai-quality-canary",
    "unknown",
    "visual-ai-qa",
    "reader-truth-qa",
    "life-platform-qa-smoke",
    "coach-quality-gate",
}

CI_LABELS = {"visual-ai-qa", "reader-truth-qa"}
LAMBDA_NAMES = {"life-platform-qa-smoke", "coach-quality-gate"}


def test_interactive_set_pinned_exactly():
    """Set equality, not membership of one instance — a new CI/QA caller class
    (or a removal) must be a conscious decision in both places."""
    assert batch_feasibility._INTERACTIVE == EXPECTED_INTERACTIVE, (
        "batch_feasibility._INTERACTIVE drifted from the pinned exclusion set. "
        "If a caller class was added/renamed, decide whether its volume can take "
        "Batch's 24h SLA (#3372/ADR-132) and update BOTH the script and this test."
    )


def test_ci_labels_match_attributable_features():
    """The CI gate rows exist under exactly these names because they are the
    allowlisted labels in bedrock_client.ATTRIBUTABLE_FEATURES — a rename there
    would re-include the volume here under the new name."""
    missing = CI_LABELS - set(bedrock_client.ATTRIBUTABLE_FEATURES)
    assert not missing, (
        f"{sorted(missing)} no longer allowlisted in bedrock_client.ATTRIBUTABLE_FEATURES — "
        "the exclusion in batch_feasibility._INTERACTIVE now matches nothing; "
        "update both sides together."
    )


def test_lambda_names_match_cdk_function_names():
    """The qa-smoke and coach-quality-gate rows carry the deployed Lambda function
    names (AWS_LAMBDA_FUNCTION_NAME always wins in feature_name()) — verify the
    strings against the CDK `function_name=` literals that mint those names."""
    cdk_dir = os.path.join(ROOT, "cdk", "stacks")
    source = ""
    for fname in os.listdir(cdk_dir):
        if fname.endswith(".py"):
            with open(os.path.join(cdk_dir, fname), encoding="utf-8") as f:
                source += f.read()
    for name in sorted(LAMBDA_NAMES):
        assert f'function_name="{name}"' in source, (
            f'no CDK stack defines function_name="{name}" — the Lambda was renamed or removed, '
            "so this batch_feasibility._INTERACTIVE entry excludes nothing; update both sides."
        )
