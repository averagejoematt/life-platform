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
import re
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


# ── #5990: the retired walking heart-rate cap stays retired from the coach tree ─────────────
# #5916 (owner ruling 2026-11-13) retired the fixed walking heart-rate cap and target: easy aerobic work is the talk
# test plus RPE (`training.recent_aerobic.EASY_EFFORT_CUE`), heart rate is a measurement only. `coach.critics_aerobic`
# was out of that lane's reach and kept printing the cap in its swap reason. A cap is caught in either form a coach
# module could print it: a literal sentence shape, or the two retired legacy names / the retired grade key read into an
# f-string (whose literal parts alone, e.g. "HR avg ≤ ", carry no number).
_RETIRED_HR_NAMES = ("HR_CEILING_BPM", "HR_TARGET_BPM", "over_ceiling", "over_hr_ceiling")
_RETIRED_HR_SHAPES = {
    "a cap in bpm": re.compile(r"[≤<]=?\s*\d{2,3}(?:\.\d)?\s*[- ]?bpm", re.I),
    "a heart-rate cap": re.compile(r"(?:\bHR|heart[ -]rate)\s+(?:avg|average)?\s*[≤<]", re.I),
    "a heart-rate target": re.compile(r"bpm\s*\(?\s*target\b|\b\d{2,3}\s*(?:bpm\s+)?the target\b", re.I),
    "a grade against a ceiling": re.compile(r"over the (?:HR|heart[ -]rate) (?:ceiling|cap)|bpm walking line", re.I),
}


def _retired_hr_hits(text: str, rel: str) -> list[str]:
    out: list[str] = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Attribute) and node.attr in _RETIRED_HR_NAMES:
            out.append(f"{rel}:{node.lineno}: reads the retired `{node.attr}`")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if any(name in node.value for name in _RETIRED_HR_NAMES[2:]):
                out.append(f"{rel}:{node.lineno}: the retired grade key {node.value!r}")
            for shape, pat in _RETIRED_HR_SHAPES.items():
                m = pat.search(node.value)
                if m:
                    out.append(f"{rel}:{node.lineno}: {shape} — {m.group(0)!r}")
    return out


# premerge-gate: #5990 — sweeps lambdas/coach for the retired walking heart-rate cap; a coach string that prints it again must red before the merge.
def test_no_coach_module_states_the_retired_walking_heart_rate_cap():
    """Every offender across lambdas/coach, reported together. Mutation control: restore the pre-#5990 swap sentence in
    `coach/critics_aerobic.py` (`HR avg ≤ {recent_aerobic.HR_CEILING_BPM} bpm (target …)`) — this reds."""
    root = _REPO / "lambdas" / "coach"
    files = sorted(root.rglob("*.py"))
    assert len(files) >= 50, f"lambdas/coach has gone blind: {len(files)} modules"
    offenders: list[str] = []
    for path in files:
        offenders += _retired_hr_hits(path.read_text(encoding="utf-8"), str(path.relative_to(_REPO)))
    assert not offenders, "a coach module states the retired walking heart-rate cap:\n  " + "\n  ".join(offenders)
    # the detector itself reds on the retired sentence's shapes (its own must-fail control)
    retired = (
        'f"HR avg ≤ {recent_aerobic.HR_CEILING_BPM} bpm (target {recent_aerobic.HR_TARGET_BPM})."',
        '"swap to cycling, HR avg ≤ 120 bpm (target 105)"',
        'numbers["last_cardio_block_over_hr_ceiling"] = last["over_ceiling"]',
    )
    for src in retired:
        assert _retired_hr_hits(src, "<retired>"), src
    assert not _retired_hr_hits('"ran at 116.9 bpm avg — a measurement, never graded"', "<measured>")
