"""tests/test_qa_skill_modes.py — #1449: the /qa skill is manifest-driven and mode-structured.

Guards (text-based on the command file, same style as the workflow-contract tests —
the skill is prose the agent executes, so the contract is what the prose names):

  1. All five #1449 modes exist — quick / tier1 / full / mobile / ai-review — plus
     the #1450 `audit` mode, each as a documented invocation of a real harness.
  2. Zero hand lists: every page/API set derives from tests/qa_manifest.py (#1426).
     The pre-#1449 skill hand-listed API endpoints (`- https://averagejoematt.com/api/...`)
     — exactly the drift class the manifest killed for pages. Banned outright.
  3. Each mode maps to the right underlying sweep flags (#1428/#1434 tiering —
     tier1 = the deploy-gate shape, mobile = the weekly WebKit shape).
  4. The skill surfaces the #1452 QA-depth dial (SSM /life-platform/qa-level) so a
     human running /qa sees the estate's current depth posture.

Proven RED against the pre-#1449 skill (no tier1/mobile/ai-review/audit modes,
hand-listed endpoints, no dial) before the rewrite.
"""

import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SKILL = os.path.join(_REPO, ".claude", "commands", "qa.md")


def _skill_text():
    assert os.path.exists(_SKILL), ".claude/commands/qa.md missing — the /qa skill is gone"
    with open(_SKILL, encoding="utf-8") as f:
        return f.read()


# ── 1. the mode structure ─────────────────────────────────────────────────────


def test_all_modes_documented():
    text = _skill_text()
    for mode in ("quick", "tier1", "full", "mobile", "ai-review", "audit"):
        assert re.search(rf"###.*`{re.escape(mode)}`", text), f"/qa mode `{mode}` not documented as a mode heading (#1449/#1450)"


def test_quick_is_the_default_mode():
    """#1449 AC: default mode preserves today's behavior — quick, the smoke sweep."""
    text = _skill_text()
    assert re.search(r"[Dd]efault.*`?quick`?", text), "quick is no longer the stated default mode"
    assert "deploy/smoke_test_site.sh" in text, "quick mode lost the smoke sweep"


# ── 2. zero hand lists — everything derives from the manifest ────────────────


def test_no_hand_listed_api_endpoints():
    """#1449 AC: all modes derive page/API sets from the A1 manifest. A literal
    bullet list of endpoint URLs is the exact pre-manifest drift class."""
    text = _skill_text()
    hand_rows = re.findall(r"^\s*-\s*`?https://averagejoematt\.com/api/\S+", text, flags=re.M)
    assert not hand_rows, f"hand-listed API endpoints in the /qa skill (derive from qa_manifest api_deps instead): {hand_rows}"


def test_no_hand_listed_page_paths_as_examples_of_state():
    """The endpoint set for the api mode must be derived, not enumerated."""
    text = _skill_text()
    assert "qa_manifest" in text, "the skill never references tests/qa_manifest.py — page/API sets must derive from THE registry (#1426)"
    assert "api_deps" in text, "the skill never derives endpoints from the manifest's api_deps facet"


# ── 3. mode → harness mapping ────────────────────────────────────────────────


def test_tier1_mode_is_the_deploy_gate_shape():
    text = _skill_text()
    assert "--max-tier 1" in text, "tier1 mode missing --max-tier 1 (deterministic sweep restricted to the flagship doors)"
    assert "--ai-qa-max-tier 1" in text, "tier1 mode missing --ai-qa-max-tier 1 (the #1428 deploy-gate AI shape)"


def test_mobile_mode_is_the_webkit_shape():
    text = _skill_text()
    assert "--browser webkit" in text, "mobile mode missing --browser webkit (#1434 — the iOS-Safari engine)"
    assert "--mobile" in text, "mobile mode missing --mobile (iPhone-class profile)"


def test_ai_review_and_full_modes_reach_the_ai_layer():
    text = _skill_text()
    assert "--ai-qa" in text, "no mode invokes the Claude/Bedrock vision layer (--ai-qa)"
    assert "tests/visual_qa.py" in text, "the skill never invokes the visual sweep harness"


def test_audit_mode_wires_the_coverage_audit():
    """#1450: /qa audit runs the repeatable coverage-map recompute."""
    text = _skill_text()
    assert "scripts/qa_audit.py" in text, "audit mode does not invoke scripts/qa_audit.py (#1450)"


# ── 4. the QA-depth dial surfaces in the skill ───────────────────────────────


def test_skill_surfaces_the_qa_level_dial():
    text = _skill_text()
    assert "/life-platform/qa-level" in text, "the skill never reads/reports the #1452 QA-depth dial"
    assert "standard" in text, "the skill doesn't state the fail-open default (standard) for an unreadable dial"
