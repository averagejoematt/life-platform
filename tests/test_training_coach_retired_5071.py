"""tests/test_training_coach_retired_5071.py — the retired training coach stays retired (#5071 box 3).

#5071's third acceptance box: "The 'Personal Board' role-play text and the stale retired
training_coach config are removed." Three things went, and this file holds each one gone:

  1. ``config/coaches/training_coach.json`` — the retired seat's voice spec. Every voice-spec
     loader keys on a coach id that reaches it only for an operational (or chat, or lead)
     persona: the coach page 404s a retired persona before it loads a voice
     (``site_api_coach_profile.handle_coach``), the brief, memoir, quality gate and expert
     analyzer iterate ``OPERATIONAL_COACH_IDS`` / ``OPERATIONAL_SHORT_IDS``, and the public
     board maps the legacy ``training_coach`` id onto ``physical_coach`` before it renders.
     The retired byline itself is the ``config/personas.json`` entry (name, colour, emoji),
     which stays — ``persona_registry.RETIRED_COACH_IDS`` still pins it.
  2. ``ai_calls.call_training_coach_v2`` — the retired seat's daily-brief wrapper. The brief
     dropped it from its v2 roster at the ADR-153 merge; nothing called it.
  3. The "Personal Board" role-play framing in the coach-facing prompt trees. History (ADRs,
     reviews, docs/archive) keeps the phrase; the three trees that feed a live coaching
     conversation do not.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent

# The live surface: every tree whose Python ships in a bundle or runs as a deploy/CI step.
_LIVE_PY_TREES = ("lambdas", "mcp", "deploy", "scripts", "cdk", "qa")

# The three trees whose text reaches a coaching conversation (the issue's own Set query).
_ROLE_PLAY_TREES = (".claude/skills", "docs/coaching", "config/coaches")
_ROLE_PLAY_PHRASE = "personal board"

_RETIRED_FN = "call_training_coach_v2"


def test_the_retired_training_coach_voice_spec_is_gone():
    assert not (_REPO / "config" / "coaches" / "training_coach.json").exists()
    assert not (_REPO / "config" / "coaches" / "training_coach_stance.json").exists()


def test_the_retired_persona_points_at_no_voice_spec():
    """The registry entry stays (the published byline), but it must not name a file that
    no longer exists — a `voice_spec_ref` is a promise a loader can follow."""
    import json

    personas = json.loads((_REPO / "config" / "personas.json").read_text(encoding="utf-8"))["personas"]
    entry = personas["training_coach"]
    assert entry.get("retired") is True
    assert "voice_spec_ref" not in entry


# premerge-gate: #5071 box 3 — sweeps the live Python trees and the three coach-prompt trees; a re-added retired wrapper or role-play line must red before the merge.
def test_no_live_module_references_the_retired_wrapper_or_role_play_text():
    """Collect EVERY offender across both sweeps and report them together."""
    offenders: list[str] = []
    for tree in _LIVE_PY_TREES:
        root = _REPO / tree
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            if "node_modules" in path.parts or "cdk.out" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if _RETIRED_FN not in text:
                continue
            # AST-confirm a real reference (def, name, attribute, import) or a string literal.
            try:
                tree_ast = ast.parse(text)
            except SyntaxError:
                offenders.append(f"{path.relative_to(_REPO)}: unparseable and mentions {_RETIRED_FN}")
                continue
            for node in ast.walk(tree_ast):
                hit = (
                    (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == _RETIRED_FN)
                    or (isinstance(node, ast.Name) and node.id == _RETIRED_FN)
                    or (isinstance(node, ast.Attribute) and node.attr == _RETIRED_FN)
                    or (isinstance(node, ast.alias) and node.name == _RETIRED_FN)
                    or (isinstance(node, ast.Constant) and isinstance(node.value, str) and _RETIRED_FN in node.value)
                )
                if hit:
                    offenders.append(f"{path.relative_to(_REPO)}:{getattr(node, 'lineno', '?')}: {_RETIRED_FN}")
    for tree in _ROLE_PLAY_TREES:
        root = _REPO / tree
        if not root.is_dir():
            continue
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for n, line in enumerate(text.splitlines(), 1):
                if _ROLE_PLAY_PHRASE in line.lower():
                    offenders.append(f"{path.relative_to(_REPO)}:{n}: 'Personal Board' role-play text")
    assert not offenders, "retired training-coach surface still live:\n  " + "\n  ".join(offenders)


def test_the_brief_module_no_longer_exports_the_retired_wrapper():
    import sys

    lambdas = str(_REPO / "lambdas")
    if lambdas not in sys.path:
        sys.path.insert(0, lambdas)
    from ai import ai_calls

    assert not hasattr(ai_calls, _RETIRED_FN)
    # the operational seats are untouched
    assert callable(ai_calls.call_physical_coach_v2) and callable(ai_calls.call_sleep_coach_v2)
