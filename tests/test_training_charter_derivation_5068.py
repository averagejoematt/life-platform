"""tests/test_training_charter_derivation_5068.py — the charter derivation guard (#5068, ADR-164).

# premerge-gate: a repo-shape ratchet — sweeps lambdas/training, the critics, four MCP tool modules, the nutrition API's rate line, config/user_goals.json and the coaching skills for hand copies of charter-owned values against a shrink-only ledger

CHARTER PRIMITIVES 2 + 3 (docs/CHARTER.md). `config/training_charter.json` is the registry
of training targets; this is the derivation guard that proves consumers read it rather
than carrying a private copy, with the pre-existing copies pinned in the dated SHRINK-ONLY
ledger `ledgers/training_charter_residue.py` (seeded 2026-10-18 from this file's own census).

WHAT IS SWEPT: every `.py` under lambdas/training/, `lambdas/coach/critics*.py`,
`mcp/tools_plan.py`, `mcp/tools_health.py`, `mcp/tools_hevy_routine.py`,
`mcp/tools_benchmark.py` (`RUN_GATE_LB`), `lambdas/web/site_api_nutrition.py`
(`_TARGET_RATE_LB_WK` — its copy is swept here; its charter READS are the privacy guard's),
`config/user_goals.json` (`daily_movement_target`), `docs/coaching/COACH_SESSION.md` (the
coach-session prompt — a skill, not documentation) and the coaching skills
(`.claude/skills/daily-debrief/SKILL.md`, `.claude/skills/speak-to-coaches/SKILL.md`,
`.claude/skills/coach-session/SKILL.md` when present). The loader itself is in scope. The
file set is the #5068 issue's `## Set` enumeration, less the members that cannot be swept
(below).

WHAT A HIT IS: a CODE line (comments and docstrings stripped — a mention is not a read;
`redline_changelog.py` is skipped whole as a dated history of PAST values) matching one of
the patterns in `_patterns()`, each keyed to the dotted charter path that owns the value.
The numeric patterns are DERIVED from the charter (`steps.floor` 12000 -> `12[,_]?000`;
the movement-gate weights from every `*_lb` leaf under `gated_movements`; the volume bands
from `volume_priorities.sets_per_wk`; the RPE ceilings from `effort_ceilings`), so when the
owner re-versions a value the sweep follows it and a stale literal is a hit the next day.

THE RATCHET: a `path::pattern` key with a live count above its ledger row, or with no row
at all, is a NEW hand copy — red, with the lines named. A row whose live count fell is a
STALE row — red too, naming the replacement line, so the ledger is always the truth and a
W1 lane that moves a read onto the charter deletes (or lowers) its row in the same PR. The
row COUNT may only go down from the seed (`SEEDED_ROW_COUNT`, pinned here a second time).

NOT SEEN, stated: a value computed at runtime from a different literal (a step floor
written as 12 * 1000); a copy in docs/ or tests/ (COACH_SESSION.md excepted, above); prose
that names the number in words; a pre-charter literal whose NUMBER differs from the charter
and carries no owning key (the redlines' `RPE 7–8` rep-scheme prose, the taper table's 3.25
/ 3.75 steps) — those fall to the W1 rewires, not to this sweep; a READ of a swept constant
at its use sites (`> RUN_GATE_LB`) — one copy, one row; and the `~/.claude/skills/synced/`
copy of coach-session, which lives outside the repo.
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
from typing import Any, Dict, Iterable, List, Set, Tuple

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))

from training import training_charter as tc  # noqa: E402

_ledger_spec = importlib.util.spec_from_file_location("training_charter_residue", _REPO / "ledgers" / "training_charter_residue.py")
_ledger = importlib.util.module_from_spec(_ledger_spec)
assert _ledger_spec.loader is not None
_ledger_spec.loader.exec_module(_ledger)

# The row count the ledger was born with. Pinned HERE as well as in the ledger so the two
# must move together, and only downward (charter primitive 3). Re-seeded once, in the same
# PR that created it, when review widened the sweep (three patterns, four files) — the
# ledger's own rule allows no raise after merge, so this was the only moment.
SEEDED_ROW_COUNT_AT_BIRTH = 21

SWEEP_DIRS = ("lambdas/training",)
# A dated history of the redlines' PAST values (every line names a superseded number by
# construction) — not a live read, so not a site a W1 lane could retire.
HISTORY_RECORDS = ("lambdas/training/redline_changelog.py",)
SWEEP_GLOBS = ("lambdas/coach/critics*.py",)
SWEEP_FILES = (
    "mcp/tools_plan.py",
    "mcp/tools_health.py",
    "mcp/tools_hevy_routine.py",
    "mcp/tools_benchmark.py",  # RUN_GATE_LB — a #5068 Set member
    "lambdas/web/site_api_nutrition.py",  # _TARGET_RATE_LB_WK — a #5068 / #5087 Set member (a published surface)
    "config/user_goals.json",  # daily_movement_target — a #5068 Set member (a second config carrying a steps target)
    "docs/coaching/COACH_SESSION.md",  # the coach-session prompt's run-gate line — a #5068 Set member
    ".claude/skills/daily-debrief/SKILL.md",
    ".claude/skills/speak-to-coaches/SKILL.md",
    ".claude/skills/coach-session/SKILL.md",  # swept when present
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """The guard derives from the bundled PUBLIC file only: no owner twin from the laptop's
    env and no live S3 probe (the review measured one GetObject per unisolated run)."""
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    tc.reset_cache()
    yield
    tc.reset_cache()


def _thousands(n: int) -> str:
    """12000 -> the regex for 12000 / 12,000 / 12_000 (and 12k)."""
    assert n % 1000 == 0, n
    return rf"\b{n // 1000}(?:[,_]?000|k)\b"


def _num_forms(x: Any) -> List[str]:
    """3.0 -> ['3.0', '3']; 3.5 -> ['3.5']; 240 -> ['240.0', '240'] — longest first for the alternation."""
    f = float(x)
    forms = {str(x)}
    if f.is_integer():
        forms.update({str(int(f)), f"{int(f)}.0"})
    return sorted((re.escape(s) for s in forms), key=len, reverse=True)


def _lb_leaves(node: Any) -> Set[int]:
    """Every integer under a key ending in `_lb` — the charter's gated weights."""
    out: Set[int] = set()
    if isinstance(node, dict):
        for k, v in node.items():
            if k.endswith("_lb") and isinstance(v, (int, float)) and not isinstance(v, bool):
                out.add(int(v))
            out |= _lb_leaves(v)
    elif isinstance(node, list):
        for v in node:
            out |= _lb_leaves(v)
    return out


def _ranges(pairs: Iterable[Any]) -> str:
    """[[14, 18], [8, 10]] -> `14\\s*[-–]\\s*18|8\\s*[-–]\\s*10` (deduplicated)."""
    return "|".join(sorted({rf"{int(lo)}\s*[-–]\s*{int(hi)}" for lo, hi in pairs}))


def _patterns() -> Dict[str, Tuple[str, re.Pattern[str]]]:
    """pattern id -> (owning charter path, compiled regex). Numbers come from the charter."""
    c = tc.load_charter()
    assert c["public_loaded"], "the public charter could not be read — the guard has no registry to derive from"
    band = c["governing_goal"]["rate_band_lb_per_wk"]
    floor, ceiling = band["floor"], band["ceiling"]
    # 2.5: tools_health's pre-charter ACSM line. Integer forms too: `_TARGET_RATE_LB_WK = 3` is a copy of 3.0.
    rate_nums = "|".join(f for x in sorted({floor, ceiling, 2.5}) for f in _num_forms(x))
    seq = "|".join(re.escape(s) for s in c["split"]["sequence"])
    lift_lo, lift_hi = c["split"]["session_minutes"]["lifting"]
    anchors = c["rotation"]["anchors_fixed_weeks"]
    rotate = c["rotation"]["accessory_slots_rotate_every_weeks"]
    gate_lb = "|".join(str(n) for n in sorted(_lb_leaves(c["gated_movements"])))
    volume_bands = _ranges(c["volume_priorities"]["sets_per_wk"].values())
    rpe_bands = _ranges(c["effort_ceilings"]["by_experience_tier"].values())
    words = {3: "three", 6: "six"}
    return {
        "steps_floor": (
            "steps.floor",
            re.compile(_thousands(int(c["steps"]["floor"])) + r'|"daily_movement_target"\s*:'),
        ),
        "steps_target": ("steps.target", re.compile(_thousands(int(c["steps"]["target"])))),
        "rate_band": (
            "governing_goal.rate_band_lb_per_wk",
            re.compile(
                rf"(?:\b(?:{rate_nums})\s*(?:lbs?|lb)\s*(?:/|per|a)\s*(?:wk|week)s?\b)"
                rf"|(?:\"(?:target|cap|floor|ceiling)\":\s*(?:{rate_nums})(?![.\d]))"
                rf"|(?:weekly_rate\s*[<>]=?\s*(?:{rate_nums})(?![.\d]))"
                rf"|(?:(?i:\b\w*rate_lb_wk\w*)\s*[:=]\s*(?:{rate_nums})(?![.\d]))"
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
        # A gate key set to a charter gate weight (`"conventional_pull_gate_lb": 275`, `"above_lb": 240`,
        # `RUN_GATE_LB = 240.0`); a gate's defining key opening its record (`"run_gate_lb": {`); or
        # prose on a code line that puts a charter weight and the word gate within 40 characters.
        "movement_gate_lb": (
            "gated_movements",
            re.compile(
                rf"\b(?:\w*gate_lb|\w*_until_lb|above_lb|revisit_at_lb|from_lb|deceleration_begins_lb)\"?\s*[:=]\s*(?:{gate_lb})(?:\.0)?(?![.\d])"
                rf"|\b(?:run_gate_lb|conventional_pull_gate_lb)\"\s*:"
                rf"|\bgate\w*\b[^\n]{{0,40}}?\b(?:{gate_lb})\s*lb\b"
                rf"|\b(?:{gate_lb})\s*lb\b[^\n]{{0,40}}?\bgate\w*",
                re.I,
            ),
        ),
        # A weekly-sets key assigned a band/number, a charter band written as `14–18 sets`, or a
        # per-muscle weekly volume (`~10 sets/muscle/wk`).
        "volume_band_sets": (
            "volume_priorities.sets_per_wk",
            re.compile(
                rf"\b(?:sets_per_wk|sets_per_week|weekly_sets|volume_priorities|mev_floors?)\w*\"?\s*[:=]\s*(?:\{{|\[\s*\d|\d)"
                rf"|\b(?:{volume_bands})\s*(?:hard\s+)?sets\b"
                rf"|\bsets\s*/\s*muscle\s*/\s*wk\b",
                re.I,
            ),
        ),
        # An effort-ceiling key (`"top_rpe": [7, 8]`, `compounds_rpe`, an isolation/accessory/effort
        # RPE) assigned a band/number, or an `RPE lo–hi` range prescribed on a code line (the charter's
        # bands and any pre-charter band alike — a range IS a ceiling).
        "effort_ceiling_rpe": (
            "effort_ceilings.by_experience_tier",
            re.compile(
                rf"\b(?:top|compounds?|isolation|accessor\w*|effort)\w*_rpe\w*\"?\s*[:=]\s*(?:\[\s*\d|\d)"
                rf"|\bRPE\s*(?:{rpe_bands})\b"
                rf"|\bRPE\s*\d+(?:\.\d)?\s*[-–]\s*\d+(?:\.\d)?\b",
                re.I,
            ),
        ),
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
    for a .py file; a skill's markdown or a config's JSON is swept whole."""
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
    """A regex that stopped matching anything would turn the guard green by going blind.
    Each pattern carries every shape it claims, so a narrowed branch is caught too."""
    probes = {
        "steps_floor": ["STEP_FLOOR = 12000  # steps", '"daily_movement_target": "3 miles"'],
        "steps_target": ["target 15,000 a day"],
        "rate_band": ['"target": 3.5,  # lb/wk', "_TARGET_RATE_LB_WK = 3", "weekly_rate > 2.5", "a 3 lb/week cut"],
        "session_minutes": ['"session_minutes": [55, 70],'],
        "anchor_block_weeks": ['"weeks_per_block": 6,'],
        "accessory_rotation_weeks": ["accessories rotate on a three-week cadence"],
        "sequence_names": ["the next session is Upper-heavy"],
        "scheduled_deload_week": ['"at_program_week": 6,'],
        "movement_gate_lb": [
            "RUN_GATE_LB = 240.0",
            '"conventional_pull_gate_lb": 275,',
            '"above_lb": 260,',
            '"run_gate_lb": {',
            'bits.append("Running stays parked until ~240 lb; the gate holds")',
            "Enforce the run gate (~240 lb) and the walking base",
        ],
        "volume_band_sets": ['"sets_per_wk": {"lats": [14, 18]},', "side delts at 14–18 sets a week", "~10 sets/muscle/wk"],
        "effort_ceiling_rpe": ['"top_rpe": [7, 8],', '"compounds_rpe": 9,', "one top set at RPE 7–8", "RPE 9-10 on the last set"],
    }
    negatives = {
        "rate_band": ['"cap": 3.75,', '"target": 3.25,'],  # pre-charter taper steps are not charter numbers
        "movement_gate_lb": ['"above_lb": 295,', "if current_weight > RUN_GATE_LB:"],  # not a gate weight; a read, not a copy
        "effort_ceiling_rpe": ['"standing_rpe_cap": 8,', '"rpe_max": 7'],  # a standing-constraint cap and a layoff cap, not the ceiling
        "volume_band_sets": ['out["weekly_sets_by_muscle"] = f()', 'row.get("avg_sets_per_week")'],  # computed / read
    }
    pats = _patterns()
    assert set(probes) == set(pats), "every pattern carries a probe"
    blind = [f"{pid}: {p!r}" for pid, (_o, rx) in pats.items() for p in probes[pid] if not rx.search(p)]
    assert not blind, f"patterns that no longer match their own probe: {blind}"
    loud = [f"{pid}: {p!r}" for pid, ps in negatives.items() for p in ps if pats[pid][1].search(p)]
    assert not loud, f"patterns matching a line they must not: {loud}"
    assert len(_swept_files()) >= 40, "the sweep covers (almost) nothing — a directory moved"
    assert {"mcp/tools_benchmark.py", "lambdas/web/site_api_nutrition.py"} <= {p.relative_to(_REPO).as_posix() for p in _swept_files()}


def test_the_public_charter_is_a_versioned_registry():
    data = json.loads((_REPO / "config" / "training_charter.json").read_text(encoding="utf-8"))
    assert re.fullmatch(r"\d+\.\d+\.\d+", data["version"]), data["version"]
    assert data["change_log"] and data["change_log"][-1]["version"] == data["version"]
    assert all({"version", "date", "what", "rule"} <= set(e) for e in data["change_log"])
    assert tc.charter_version() == data["version"]
    assert data["deload"] == {**data["deload"], "scheduled": False, "automatic": False, "owner_gated": True}
    assert data["split"]["sequence"] == ["Upper-heavy", "Lower-heavy", "Shoulders+arms", "Upper-volume", "Lower-volume"]
    assert (data["steps"]["floor"], data["steps"]["target"]) == (12000, 15000)
    assert _lb_leaves(data["gated_movements"]) == {240, 250, 260, 275}, "the four gated weights the sweep derives from"


if __name__ == "__main__":  # seed/refresh helper: prints the ledger body (no live probe)
    tc._from_s3 = lambda key: None  # type: ignore[assignment]
    os.environ.pop(tc.PRIVATE_ENV_VAR, None)
    counts, _lines = census()
    for k, v in sorted(counts.items()):
        print(f'    "{k}": {v},')
        if "--lines" in sys.argv:
            for ln in _lines[k]:
                print(f"        # {ln}")
    print(f"# rows: {len(counts)}", file=sys.stderr)
    pytest.main([__file__, "-q"]) if "--test" in sys.argv else None
