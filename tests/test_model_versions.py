"""
test_model_versions.py — PIPE-05: Assert Anthropic model IDs used in CDK stacks are valid.

Prevents deploying with deprecated or mistyped model IDs. Known-valid IDs are
maintained here. When Anthropic releases a new model, update VALID_MODEL_IDS
and update the CDK stack / constants.py together.

Known valid model IDs (as of 2026-03):
  claude-haiku-4-5-20251001   (fast/cheap — compute Lambdas, weekly-correlation)
  claude-opus-4-6             (most capable — hypothesis-engine)
  claude-sonnet-4-6           (balanced — daily-brief AI calls via ai_calls.py)
"""

import os
import re

CDK_DIR = os.path.join(os.path.dirname(__file__), "..", "cdk", "stacks")
LAMBDAS_DIR = os.path.join(os.path.dirname(__file__), "..", "lambdas")

# ── Add new model IDs here when Anthropic releases them ──────────────────────
VALID_MODEL_IDS = {
    "claude-haiku-4-5-20251001",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    # claude-3 family — still valid, used in some older references
    "claude-3-5-haiku-20241022",
    "claude-3-5-sonnet-20241022",
    "claude-3-opus-20240229",
}

# Pattern to find quoted model IDs in Python source
_MODEL_PATTERN = re.compile(r'"(claude-[a-z0-9\-\.]+)"')


def _find_model_ids(filepath: str) -> list[tuple[str, int, str]]:
    """Return [(model_id, line_number, context)] for all claude-* model IDs found."""
    results = []
    with open(filepath) as f:
        for lineno, line in enumerate(f, 1):
            for m in _MODEL_PATTERN.finditer(line):
                results.append((m.group(1), lineno, line.strip()))
    return results


def test_cdk_stacks_use_valid_model_ids():
    """All claude-* model IDs hardcoded in CDK stacks must be in VALID_MODEL_IDS."""
    for fname in os.listdir(CDK_DIR):
        if not fname.endswith(".py"):
            continue
        path = os.path.join(CDK_DIR, fname)
        for model_id, lineno, ctx in _find_model_ids(path):
            assert model_id in VALID_MODEL_IDS, (
                f"{fname}:{lineno}: Unknown model ID {model_id!r}\n"
                f"  Context: {ctx}\n"
                f"  If this is a new model, add it to VALID_MODEL_IDS in test_model_versions.py"
            )


def test_constants_model_default_is_valid():
    """The default AI_MODEL_HAIKU value in constants.py must be in VALID_MODEL_IDS."""
    constants_path = os.path.join(CDK_DIR, "constants.py")
    findings = _find_model_ids(constants_path)
    assert findings, "No claude-* model IDs found in constants.py — was AI_MODEL_HAIKU removed?"
    for model_id, lineno, ctx in findings:
        assert model_id in VALID_MODEL_IDS, (
            f"constants.py:{lineno}: Default model {model_id!r} is not in VALID_MODEL_IDS\n"
            f"  Update VALID_MODEL_IDS in test_model_versions.py when adding a new model."
        )
