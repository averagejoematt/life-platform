"""tests/test_training_charter_derivation_5068.py — the charter derivation guard (#5068, ADR-164).

# premerge-gate: a repo-shape ratchet — sweeps lambdas/training, the critics, three MCP tool modules and the coaching skills for hand copies of charter-owned values against a shrink-only ledger

CHARTER PRIMITIVES 2 + 3 (docs/CHARTER.md). `config/training_charter.json` is the registry
of training targets; this is the derivation guard that proves consumers read it rather
than carrying a private copy, with the pre-existing copies pinned in the dated SHRINK-ONLY
ledger `ledgers/training_charter_residue.py` (seeded 2026-10-18 from this file's own census).

WHAT IS SWEPT: every `.py` under lambdas/training/, `lambdas/coach/critics*.py`,
`mcp/tools_plan.py`, `mcp/tools_health.py`, `mcp/tools_hevy_routine.py`, and the coaching
skills (`.claude/skills/daily-debrief/SKILL.md`, `.claude/skills/speak-to-coaches/SKILL.md`,
`.claude/skills/coach-session/SKILL.md` when present). The loader itself is in scope.

WHAT A HIT IS: a CODE line (comments and docstrings stripped — a mention is not a read;
`redline_changelog.py` is skipped whole as a dated history of PAST values) matching one of
the patterns in `_patterns()`, each keyed to the dotted charter path that owns the value. The numeric patterns are DERIVED from the charter
(`steps.floor` 12000 -> `12[,_]?000`), so when the owner re-versions a value the sweep
follows it and a stale literal is a hit the next day.

THE RATCHET: a `path::pattern` key with a live count above its ledger row, or with no row
at all, is a NEW hand copy — red, with the lines named. A row whose live count fell is a
STALE row — red too, naming the replacement line, so the ledger is always the truth and a
W1 lane that moves a read onto the charter deletes (or lowers) its row in the same PR. The
row COUNT may only go down from the seed (`SEEDED_ROW_COUNT`, pinned here a second time).

NOT SEEN, stated: a value computed at runtime from a different literal (a step floor
written as 12 * 1000), a copy in docs/ or tests/, and prose that names the number in words.
"""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import os
import pathlib
import re
import sys
import tokenize
from typing import Dict, List, Tuple

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))

from training import training_charter as tc  # noqa: E402

_ledger_spec = importlib.util.spec_from_file_location("training_charter_residue", _REPO / "ledgers" / "training_charter_residue.py")
_ledger = importlib.util.module_from_spec(_ledger_spec)
assert _ledger_spec.loader is not None
_ledger_spec.loader.exec_module(_ledger)

# The row count the ledger was born with. Pinned HERE as well as in the ledger so the two
# must move together, and only downward (charter primitive 3).
SEEDED_ROW_COUNT_AT_BIRTH = 10

SWEEP_DIRS = ("lambdas/training",)
# A dated history of the redlines' PAST values (every line names a superseded number by
# construction) — not a live read, so not a site a W1 lane could retire.
HISTORY_RECORDS = ("lambdas/training/redline_changelog.py",)
SWEEP_GLOBS = ("lambdas/coach/critics*.py",)
SWEEP_FILES = (
    "mcp/tools_plan.py",
    "mcp/tools_health.py",
    "mcp/tools_hevy_routine.py",
    ".claude/skills/daily-debrief/SKILL.md",
    ".claude/skills/speak-to-coaches/SKILL.md",
    ".claude/skills/coach-session/SKILL.md",  # swept when present
)


def _thousands(n: int) -> str:
    """12000 -> the regex for 12000 / 12,000 / 12_000 (and 12k)."""
    assert n % 1000 == 0, n
    return rf"\b{n // 1000}(?:[,_]?000|k)\b"


def _patterns() -> Dict[str, Tuple[str, re.Pattern[str]]]:
    """pattern id -> (owning charter path, compiled regex). Numbers come from the charter."""
    c = tc.load_charter()
    assert c["public_loaded"], "the public charter could not be read — the guard has no registry to derive from"
    band = c["governing_goal"]["rate_band_lb_per_wk"]
    floor, ceiling = band["floor"], band["ceiling"]
    rate_nums = "|".join(re.escape(str(x)) for x in sorted({floor, ceiling, 2.5}))  # 2.5: tools_health's pre-charter ACSM line
    seq = "|".join(re.escape(s) for s in c["split"]["sequence"])
    lift_lo, lift_hi = c["split"]["session_minutes"]["lifting"]
    anchors = c["rotation"]["anchors_fixed_weeks"]
    rotate = c["rotation"]["accessory_slots_rotate_every_weeks"]
    words = {3: "three", 6: "six"}
    return {
        "steps_floor": ("steps.floor", re.compile(_thousands(int(c["steps"]["floor"])))),
        "steps_target": ("steps.target", re.compile(_thousands(int(c["steps"]["target"])))),
        "rate_band": (
            "governing_goal.rate_band_lb_per_wk",
            re.compile(
                rf"(?:\b(?:{rate_nums})\s*(?:lbs?|lb)\s*(?:/|per|a)\s*(?:wk|week)s?\b)"
                rf"|(?:\"(?:target|cap|floor|ceiling)\":\s*(?:{rate_nums})\b)"
                rf"|(?:weekly_rate\s*[<>]=?\s*(?:{rate_nums})\b)"
            ),
        ),
        "session_minutes": (
            "split.session_minutes.lifting",
            re.compile(
                rf"\bsession_minutes(?:_ceiling)?\"?\s*(?:[:=]|\s)\s*(?:\[\s*\d+\s*,\s*\d+\s*\]|[1-9]\d\b)"
                rf"|\b{lift_lo}\s*[-–]\s*{lift_hi}\s*min"
            ),
        ),
        "anchor_block_weeks": (
            "rotation.anchors_fixed_weeks",
            re.compile(
                rf"\b(?:block_weeks|weeks_per_block|anchors_fixed_weeks)\"?\s*[:=]\s*{anchors}\b"
                rf"|\b(?:{anchors}|{words.get(anchors, anchors)})[- ]week\b",
                re.I,
            ),
        ),
        "accessory_rotation_weeks": (
            "rotation.accessory_slots_rotate_every_weeks",
            re.compile(rf"\b(?:{rotate}|{words.get(rotate, rotate)})[- ]week\b|\brotat\w*\b.{{0,40}}\bevery {rotate}\b", re.I),
        ),
        "sequence_names": ("split.sequence", re.compile(rf"\b(?:{seq})\b", re.I)),
        "scheduled_deload_week": ("deload.scheduled", re.compile(r"\b(?:at_program_week|every_nth_week)\"?\s*[:=]\s*\d+\b")),
    }


def _swept_files() -> List[pathlib.Path]:
    out: List[pathlib.Path] = []
    for d in SWEEP_DIRS:
        for root, _dirs, files in os.walk(_REPO / d):
            out.extend(pathlib.Path(root) / f for f in files if f.endswith(".py"))
    for g in SWEEP_GLOBS:
        out.extend(_REPO.glob(g))
    for f in SWEEP_FILES:
        if (_REPO / f).exists():
            out.append(_REPO / f)
    return sorted(p for p in set(out) if p.relative_to(_REPO).as_posix() not in HISTORY_RECORDS)


def _code_lines(path: pathlib.Path) -> List[Tuple[int, str]]:
    """(lineno, text) with comments cut and docstrings / bare string statements dropped —
    for a .py file; a skill's markdown is swept whole."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if path.suffix != ".py":
        return list(enumerate(lines, 1))
    cut = list(lines)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                row, col = tok.start
                cut[row - 1] = cut[row - 1][:col]
    except (tokenize.TokenError, SyntaxError):
        pass
    skip: set[int] = set()
    try:
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                skip.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    except SyntaxError:
        pass
    return [(n, line) for n, line in enumerate(cut, 1) if n not in skip]


def census() -> Tuple[Dict[str, int], Dict[str, List[str]]]:
    """`path::pattern` -> matching-line count, plus the lines themselves for the report."""
    counts: Dict[str, int] = {}
    lines: Dict[str, List[str]] = {}
    pats = _patterns()
    for path in _swept_files():
        rel = path.relative_to(_REPO).as_posix()
        for n, line in _code_lines(path):
            for pid, (_owner, rx) in pats.items():
                if rx.search(line):
                    key = f"{rel}::{pid}"
                    counts[key] = counts.get(key, 0) + 1
                    lines.setdefault(key, []).append(f"{rel}:{n}: {line.strip()[:120]}")
    return counts, lines


def _owner_of(key: str) -> str:
    return _patterns()[key.rsplit("::", 1)[1]][0]


def test_every_hand_copy_of_a_charter_value_is_a_ledgered_site_and_every_row_is_live():
    live, lines = census()
    ledger = _ledger.TRAINING_CHARTER_RESIDUE
    problems: List[str] = []
    for key, n in sorted(live.items()):
        pinned = ledger.get(key)
        if pinned is None:
            problems.append(
                f"NEW hand copy of `{_owner_of(key)}` — read it through training_charter.charter_value():\n    " + "\n    ".join(lines[key])
            )
        elif n > pinned:
            problems.append(
                f"{key}: {n} lines, ledger says {pinned} — a new copy of `{_owner_of(key)}` was added:\n    " + "\n    ".join(lines[key])
            )
        elif n < pinned:
            problems.append(f'{key}: {n} lines, ledger says {pinned} — a site was retired: lower the row to `"{key}": {n},`')
    for key, pinned in sorted(ledger.items()):
        if key not in live:
            problems.append(f"{key}: ledger row {pinned} but the sweep finds 0 lines — delete the row (shrink-only)")
    assert not problems, "\n\n".join(problems)


def test_the_ledger_only_shrinks():
    ledger = _ledger.TRAINING_CHARTER_RESIDUE
    assert _ledger.SEEDED_ROW_COUNT == SEEDED_ROW_COUNT_AT_BIRTH, "the seed count is pinned in both files and moves only downward together"
    assert (
        len(ledger) <= _ledger.SEEDED_ROW_COUNT
    ), f"{len(ledger)} rows > the {_ledger.SEEDED_ROW_COUNT} seeded — a row was ADDED to legalise a new hand copy"
    assert all(isinstance(v, int) and v > 0 for v in ledger.values()), "every row is a positive line count"
    assert all(k.rsplit("::", 1)[1] in _patterns() for k in ledger), "every row names a pattern this sweep still runs"


def test_every_pattern_has_a_positive_control():
    """A regex that stopped matching anything would turn the guard green by going blind."""
    probes = {
        "steps_floor": "STEP_FLOOR = 12000  # steps",
        "steps_target": "target 15,000 a day",
        "rate_band": '"target": 3.5,  # lb/wk',
        "session_minutes": '"session_minutes": [55, 70],',
        "anchor_block_weeks": '"weeks_per_block": 6,',
        "accessory_rotation_weeks": "accessories rotate on a three-week cadence",
        "sequence_names": "the next session is Upper-heavy",
        "scheduled_deload_week": '"at_program_week": 6,',
    }
    pats = _patterns()
    assert set(probes) == set(pats), "every pattern carries a probe"
    blind = [pid for pid, (_o, rx) in pats.items() if not rx.search(probes[pid])]
    assert not blind, f"patterns that no longer match their own probe: {blind}"
    assert len(_swept_files()) >= 40, "the sweep covers (almost) nothing — a directory moved"


def test_the_public_charter_is_a_versioned_registry():
    data = json.loads((_REPO / "config" / "training_charter.json").read_text(encoding="utf-8"))
    assert re.fullmatch(r"\d+\.\d+\.\d+", data["version"]), data["version"]
    assert data["change_log"] and data["change_log"][-1]["version"] == data["version"]
    assert all({"version", "date", "what", "rule"} <= set(e) for e in data["change_log"])
    assert tc.charter_version() == data["version"]
    assert data["deload"] == {**data["deload"], "scheduled": False, "automatic": False, "owner_gated": True}
    assert data["split"]["sequence"] == ["Upper-heavy", "Lower-heavy", "Shoulders+arms", "Upper-volume", "Lower-volume"]
    assert (data["steps"]["floor"], data["steps"]["target"]) == (12000, 15000)


if __name__ == "__main__":  # seed/refresh helper: prints the ledger body
    counts, _ = census()
    for k, v in sorted(counts.items()):
        print(f'    "{k}": {v},')
    print(f"# rows: {len(counts)}", file=sys.stderr)
    pytest.main([__file__, "-q"]) if "--test" in sys.argv else None
