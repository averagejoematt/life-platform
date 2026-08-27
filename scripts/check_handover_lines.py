#!/usr/bin/env python3
"""scripts/check_handover_lines.py — every /wrap gate line is asserted, not remembered (#3006).

THE PROBLEM
  /wrap defines eleven gates and each ends in the same contract: the handover carries a
  marker line EITHER WAY ("silent omission is not an outcome"). Only three were backed by
  a script that reads an artifact; the other eight were prose. Measured over the 25
  handovers on `origin/session-archive` dated 2026-08-11 → 2026-08-22: 20 missing marker
  lines, ALL in four handovers — whole-wrap collapse, not gradual erosion. Three
  consecutive wraps on 2026-08-20 dropped the same core five lines. A check that cannot
  fail is a check that never ran (#2761's principle, applied one level up).

THE FIX
  This script asserts that every gate's marker line is present in the outgoing
  `handovers/HANDOVER_LATEST.md`, and exits 1 naming each missing one — generalising what
  check_proportionality_ledger.py already does for `**Ledger:**`.

  The expected markers are DERIVED FROM `.claude/skills/wrap/SKILL.md`, never hand-listed
  here: each wrap gate states its contract with the house phrase "carries one line
  (either way)" / "must carry one line", immediately followed by the backticked
  `**Marker:**` token. We parse exactly that. A hand-list would drift the moment a
  twelfth gate is added — the same failure one level up. A derivation that finds fewer
  than MIN_EXPECTED_MARKERS markers is itself an error (exit 2), so a wrap.md rewording
  cannot silently reduce this gate to a no-op (#1189 "no vacuous scans").

USAGE
  python3 scripts/check_handover_lines.py [HANDOVER_PATH] [--wrap WRAP_PATH]
    HANDOVER_PATH defaults to handovers/HANDOVER_LATEST.md;
    WRAP_PATH defaults to .claude/skills/wrap/SKILL.md (test hook).
  Exit 0: every derived marker line present. Exit 1: one or more missing (each named).
  Exit 2: the derivation itself regressed (wrap.md unreadable or too few markers found).
"""

import re
import sys
from pathlib import Path


def _skill_registry():
    """The ONE registry for Claude Code skills + agents (scripts/skill_registry.py)."""
    import importlib.util
    import os as _os

    _here = _os.path.dirname(_os.path.abspath(__file__))
    _cands = [_os.path.join(_here, "skill_registry.py"), _os.path.join(_here, "..", "scripts", "skill_registry.py")]
    for _p in _cands:
        if _os.path.isfile(_p):
            spec = importlib.util.spec_from_file_location("_skill_registry", _p)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise FileNotFoundError("scripts/skill_registry.py not found")


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HANDOVER = ROOT / "handovers" / "HANDOVER_LATEST.md"
DEFAULT_WRAP = _skill_registry().require_skill("wrap")

# Fewer derived markers than this means the wrap.md parse regressed, not that the wrap
# got simpler — eleven gates carry a marker line as of #3006 (see the file docstring).
MIN_EXPECTED_MARKERS = 8

# The house phrase every wrap gate uses to state its handover-line contract.
_CONTRACT_PHRASE = re.compile(r"(?:carry|carries)\s+one\s+line", re.I)
# The first backticked/bold marker token after the phrase, e.g. `**Alarms:**`.
_MARKER_TOKEN = re.compile(r"\*\*([^:*\n`]+):\*\*")
# How far past the phrase the token must appear (the templates sit right after it).
_WINDOW = 250

_STEP_HEADING = re.compile(r"^### \(([a-z0-9]+)\)", re.M)


def step_sections(wrap_text: str):
    """Yield (step_id, body) for each `### (x)` step in wrap.md."""
    matches = list(_STEP_HEADING.finditer(wrap_text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(wrap_text)
        yield m.group(1), wrap_text[m.start() : end]


def derive_markers(wrap_text: str) -> dict:
    """{marker_name: step_id} for every gate marker line wrap.md's steps declare.

    A marker is claimed wherever a step states the house contract phrase; the token that
    follows it is the required line. First claiming step wins (a marker restated by a
    later step — e.g. in an example — does not duplicate)."""
    markers: dict = {}
    for step_id, body in step_sections(wrap_text):
        for m in _CONTRACT_PHRASE.finditer(body):
            window = body[m.end() : m.end() + _WINDOW]
            token = _MARKER_TOKEN.search(window)
            if token:
                markers.setdefault(token.group(1).strip(), step_id)
    return markers


def marker_present(handover_text: str, name: str) -> bool:
    """True if the handover carries the marker as a line of record.

    Line-start (optionally after a list bullet), optional bold, case-insensitive —
    the same tolerance check_proportionality_ledger.py extends to `**Ledger:**`."""
    pat = re.compile(rf"^\s*(?:[-*]\s+)?\*{{0,2}}{re.escape(name)}\*{{0,2}}\s*:", re.I | re.M)
    return bool(pat.search(handover_text))


def evaluate(handover_text: str, markers: dict) -> tuple:
    """(ok, messages) — pure, so the mutation tests drive it directly."""
    messages = []
    missing = []
    for name in sorted(markers, key=lambda n: markers[n]):
        if marker_present(handover_text, name):
            messages.append(f"OK — `**{name}:**` present (step ({markers[name]}))")
        else:
            missing.append(name)
            messages.append(
                f"MISSING — `**{name}:**` (wrap step ({markers[name]})) has no line in the handover.\n"
                f"  Write the gate's outcome either way — silent omission is not an outcome (#3006)."
            )
    if missing:
        messages.append(f"FAIL — {len(missing)} of {len(markers)} gate lines missing: " + ", ".join(missing))
        return False, messages
    messages.append(f"OK — all {len(markers)} gate marker lines present.")
    return True, messages


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    wrap_path = DEFAULT_WRAP
    if "--wrap" in args:
        i = args.index("--wrap")
        try:
            wrap_path = Path(args[i + 1])
        except IndexError:
            print("--wrap requires a path")
            return 2
        del args[i : i + 2]
    handover_path = Path(args[0]) if args else DEFAULT_HANDOVER

    if not wrap_path.exists():
        print(f"ERROR — {wrap_path} not found; cannot derive the marker set.")
        return 2
    markers = derive_markers(wrap_path.read_text(encoding="utf-8"))
    if len(markers) < MIN_EXPECTED_MARKERS:
        print(
            f"ERROR — derived only {len(markers)} markers from {wrap_path} (expected ≥{MIN_EXPECTED_MARKERS}).\n"
            "  The wrap.md contract-phrase parse regressed — fix the derivation before trusting this gate\n"
            "  (a gate that derives an empty set passes everything: the #1189 vacuous-scan class)."
        )
        return 2
    if not handover_path.exists():
        print(f"ERROR — {handover_path} not found.")
        return 1

    ok, messages = evaluate(handover_path.read_text(encoding="utf-8"), markers)
    for m in messages:
        print(m)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
