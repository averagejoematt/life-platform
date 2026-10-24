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

EVERY NUMERIC LEAF (#5175). Beside the eleven value-class patterns, `LEAF_PATTERNS` carries one pattern per charter
numeric leaf they do not own — the overage tolerance, the gain step, the lifting-day count, the stall rule, the cardio
doses, the disruption and calibration cadences, the panel bar, the wake-time rule — each keyed to its owning path, its
numbers filled from the charter at collection. The leaves are ENUMERATED FROM THE CHARTER
(`test_every_charter_numeric_leaf_has_a_pattern_or_a_stated_reason`), so a new numeric leaf reds until it gets a pattern
or a `NOT_APPLICABLE` row; that table is where every not-applicable reason is stated (each names the one reader and the
test that holds it), and a row covering nothing is red too. WORD FORMS: every pattern fills its numbers from ONE shared
map, `NUM_WORDS`, so `five lifting days` and `Two weeks of most sets` (the #5086 specimens) are hits like `5 lifting
days`; the word forms are matched next to the leaf's own noun or unit, in prose files and in code strings alike.

THE RATCHET: a `path::pattern` key with a live count above its ledger row, or with no row
at all, is a NEW hand copy — red, with the lines named. A row whose live count fell is a
STALE row — red too, naming the replacement line, so the ledger is always the truth and a
W1 lane that moves a read onto the charter deletes (or lowers) its row in the same PR. The
row COUNT may only go down from the seed (`SEEDED_ROW_COUNT`, pinned here a second time).

NOT SEEN, stated: a value computed at runtime from a different literal (a step floor
written as 12 * 1000); a copy in docs/ or tests/ (COACH_SESSION.md excepted, above); a
number in words that sits away from its noun or unit (the leaf patterns key a number to its noun: `five lifting days`
is seen, `five of them` is not); a number shared by a different quantity, so a pattern needs context (the
weeks-running and stall-RPE patterns require the ceiling / stall words on the line); a pre-charter literal whose NUMBER differs from the charter
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
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

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
    "mcp/tools_lifestyle.py",  # the movement-score step_target default — a #5056 Set member
    "mcp/tools_benchmark.py",  # RUN_GATE_LB — a #5068 Set member
    "lambdas/web/site_api_nutrition.py",  # _TARGET_RATE_LB_WK — a #5068 / #5087 Set member (a published surface)
    "config/user_goals.json",  # daily_movement_target — a #5068 Set member (a second config carrying a steps target)
    "docs/coaching/COACH_SESSION.md",  # the coach-session prompt's run-gate line — a #5068 Set member
    ".claude/skills/daily-debrief/SKILL.md",
    ".claude/skills/speak-to-coaches/SKILL.md",
    ".claude/skills/coach-session/SKILL.md",  # swept when present
    ".claude/skills/training-review/SKILL.md",  # #5079: the block retro reads its targets from the charter
    "lambdas/health/nutrient_intake.py",  # #5204: the fibre target in MICRONUTRIENT_TARGETS reads the charter floor
    "lambdas/emails/nutrition_review_lambda.py",  # #5204: the review footer renders the fibre floor from nutrient_intake, never a literal
    "lambdas/experiment/plan_facts.py",  # #5204: the plan's fibre figure reads the charter floor
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


# #5175: ONE number-to-word map for every pattern (the `rotation` map it replaces knew only 3 and 6). A charter
# integer with an entry here is matched in words as well as digits wherever its pattern names it.
NUM_WORDS: Dict[int, str] = {
    0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine",
    10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen", 16: "sixteen", 18: "eighteen",
    20: "twenty", 24: "twenty-four", 28: "twenty-eight", 30: "thirty", 40: "forty",
}  # fmt: skip
_TIMES_WORDS = {1: "once", 2: "twice"}

# #5175: a pattern per charter numeric leaf the eleven value-class patterns above do not own. Each entry is
# (regex templates, probe templates). A template names the NUMBER only through a slot, filled from the charter at
# collection time, so a re-versioned value moves the pattern with it:
#   {n}     the value in digits (and its float/int twin) or in words; a [lo, hi] range as `lo-hi` / `lo to hi` /
#           `lo or hi` (digits or words); a [k, k] band as k
#   {list}  the value as a JSON/Python list literal `[lo, hi]` (a copied key's value)
#   {pct}   a share 0 < v < 1 as a percent (`50 %`), or `half` for 0.5
#   {times} a count as `2x` / `2 times`, or `once` / `twice`
# The probes render each probe template with the digits AND (where NUM_WORDS has the number) the words, and every
# rendering must match — the positive control that this pattern still sees the copy it exists for.
LEAF_PATTERNS: Dict[str, Tuple[Tuple[str, ...], Tuple[str, ...]]] = {
    "split.lifting_days_per_wk": (
        (r"{n}[\s-]+lifting[\s-]+(?:days?|sessions?)\b", r"{n}[\s-]+day[\s-]+split\b", r"\blifting_days_per_wk\"?\s*[:=]\s*{n}"),
        ("{n} lifting days", "the {n}-day split", '"lifting_days_per_wk": {n}'),
    ),
    "split.frequency.each_major_muscle_per_wk": (
        (r"\b(?:each|every)\s+(?:major\s+)?muscle\s+(?:group\s+)?{times}", r"\beach_major_muscle_per_wk\"?\s*[:=]\s*{n}"),
        ("each major muscle {times} a week",),
    ),
    "split.frequency.delts_per_wk": (
        (r"\bdelts?\s+{times}", r"\bdelts_per_wk\"?\s*[:=]\s*{n}"),
        ("delts {times} a week",),
    ),
    "split.frequency.overhead_press_per_wk": (
        (r"\boverhead[\s_-]+press\s+{times}", r"\boverhead_press_per_wk\"?\s*[:=]\s*{n}"),
        ("overhead press {times} a week",),
    ),
    "split.session_minutes.cardio_block_max": (
        (
            r"\bcardio_block_max\"?\s*[:=]\s*{n}",
            r"{n}[\s-]*min(?:ute)?s?\s+(?:of\s+)?cardio\b",
            r"\bcardio\s+block\s+(?:of\s+|up\s+to\s+)?{n}[\s-]*min",
        ),
        ("a {n}-minute cardio block", "{n} min of cardio"),
    ),
    "split.session_minutes.stretching_max": (
        (
            r"\bstretching_max\"?\s*[:=]\s*{n}",
            r"{n}[\s-]*min(?:ute)?s?\s+(?:of\s+)?stretch",
            r"\bstretch\w*\s+(?:of\s+|up\s+to\s+)?{n}[\s-]*min",
        ),
        ("{n} minutes of stretching",),
    ),
    "split.minimum_session.minutes": (
        (r"{n}[\s-]*min(?:ute)?s?\s+minimum", r"\bminimum(?:\s+viable)?\s+session\s+(?:of\s+)?{n}[\s-]*min"),
        ("the {n}-minute minimum", "a minimum session of {n} min"),
    ),
    "split.minimum_session.sets_per_movement": (
        (r"\bsets_per_movement\"?\s*[:=]\s*{n}", r"{n}\s+sets\s+(?:per|a|each)\s+movement"),
        ("{n} sets per movement",),
    ),
    "split.minimum_session.max_movements": (
        (r"\bmax_movements\"?\s*[:=]\s*{n}", r"\b(?:at\s+most|up\s+to|max(?:imum)?(?:\s+of)?)\s+{n}\s+movements", r"{n}\s+movements\s+max"),
        ("at most {n} movements",),
    ),
    "split.minimum_session.est_minutes_per_set": (
        (r"\best_minutes_per_set\"?\s*[:=]\s*{n}", r"{n}\s*min(?:ute)?s?\s+(?:per|a|each)\s+set\b"),
        ("{n} minutes per set",),
    ),
    "steps.ramp.ramp_window_days": (
        (
            r"\bramp_window_days\"?\s*[:=]\s*{n}",
            r"{n}[\s-]+day\s+ramp",
            r"\bramp\w*\s+(?:over|from)\s+(?:the\s+)?(?:trailing\s+)?{n}\s+days",
        ),
        ("a {n}-day ramp", "the ramp over the trailing {n} days"),
    ),
    "cardio_menu.conditioning_sessions_per_wk": (
        (r"\bconditioning_sessions_per_wk\"?\s*[:=]\s*{n}", r"{n}\s+(?:hard\s+)?conditioning\s+sessions?", r"\bconditioning\s+{times}"),
        ("{n} conditioning sessions", "conditioning {times} a week"),
    ),
    "cardio_menu.blocks.easy.rpe": (
        (r"\beasy\b[^\n]{0,40}?\bRPE\s*{n}", r"\"easy\"\s*:\s*\{\s*\"rpe\"\s*:\s*{list}"),
        ("an easy block at RPE {n}",),
    ),
    "cardio_menu.blocks.tempo.rpe": (
        (r"\btempo\b[^\n]{0,40}?\bRPE\s*{n}", r"\"tempo\"\s*:\s*\{[^}\n]*\"rpe\"\s*:\s*{list}"),
        ("the tempo block at RPE {n}",),
    ),
    "cardio_menu.blocks.tempo.minutes": (
        (r"\btempo\b[^\n]{0,30}?{n}[\s-]*min", r"{n}[\s-]*min(?:ute)?s?\s+(?:of\s+)?tempo", r"\bhard\s+flat\s+{n}\b"),
        ("tempo for {n} min", "hard flat {n}"),
    ),
    "cardio_menu.blocks.hills.rpe": (
        (r"\bhills?\b[^\n]{0,40}?\bRPE\s*{n}", r"\"hills\"\s*:\s*\{\s*\"rpe\"\s*:\s*{list}"),
        ("hills at RPE {n}",),
    ),
    "cardio_menu.blocks.intervals.rpe_hard_minutes": (
        (r"\brpe_hard_minutes\"?\s*[:=]\s*{n}", r"\bRPE\s*{n}\s+on\s+the\s+hard"),
        ("RPE {n} on the hard minutes",),
    ),
    "cardio_menu.blocks.intervals.work_easy_minutes": (
        (r"\bwork_easy_minutes\"?\s*[:=]\s*{list}", r"{n}\s*(?:min\s*)?(?:on|hard|work)\s*[/,]\s*{n}\s*(?:min\s*)?(?:off|easy)"),
        ("{n} min hard / {n} min easy",),
    ),
    "cardio_menu.blocks.intervals.efforts": (
        (r"\befforts\"?\s*[:=]\s*{n}", r"{n}\s+(?:hard\s+)?(?:efforts|intervals|rounds\s+of\s+intervals)\b"),
        ("{n} hard efforts",),
    ),
    "cardio_menu.blocks.incline_treadmill_walk.rpe": (
        (r"\bincline\b[^\n]{0,40}?\bRPE\s*{n}", r"\bwalk\w*\b[^\n]{0,30}?\bRPE\s*{n}"),
        ("the incline walk at RPE {n}",),
    ),
    "cardio_menu.blocks.incline_treadmill_walk.starting_dose.incline_pct": (
        (r"{n}\s*%\s*(?:incline|grade)", r"\bincline\w*\s+(?:of\s+|at\s+)?{n}\s*%", r"\bincline_pct\"?\s*[:=]\s*{list}"),
        ("{n} % incline",),
    ),
    "cardio_menu.blocks.incline_treadmill_walk.starting_dose.mph": (
        (r"{n}\s*mph\b", r"\bmph\"?\s*[:=]\s*{list}"),
        ("at {n} mph",),
    ),
    "cardio_menu.blocks.incline_treadmill_walk.step.incline_pct": (
        (
            r"\+{n}\s*%\s*(?:incline|grade)",
            r"\bincline\s+(?:step|steps\s+up)\s+(?:of\s+|by\s+)?\+?{n}\s*%",
            r"\bincline_pct\"?\s*[:=]\s*{n}(?!\s*[,\]])",
        ),
        ("+{n} % incline",),
    ),
    "cardio_menu.blocks.incline_treadmill_walk.step.mph": (
        (r"\+{n}\s*mph\b", r"\bmph\"?\s*[:=]\s*{n}(?!\s*[,\]])"),
        ("+{n} mph",),
    ),
    "effort_ceilings.overage_tolerance_rpe": (
        (
            r"\boverage_tolerance_rpe\"?\s*[:=]\s*{n}",
            r"\bwithin\s+\+?{n}\s*(?:point\s+)?(?:of\s+)?RPE",
            r"\+{n}\s*RPE\s+(?:of|over|above|past)\s+the\s+ceiling",
            r"\+{n}\s*RPE\s+overage",
            r"{n}[\s-]+(?:RPE\s+)?point\s+(?:overage\s+)?tolerance",
        ),
        ("within +{n} RPE of the ceiling", "a +{n} RPE overage", '"overage_tolerance_rpe": {n}'),
    ),
    "effort_ceilings.ceiling_change_proposal.share_of_sets": (
        (r"\bshare_of_sets\"?\s*[:=]\s*{n}", r"\bmore\s+than\s+{pct}\s+of\s+(?:the\s+|his\s+)?sets"),
        ("more than {pct} of sets",),
    ),
    "effort_ceilings.ceiling_change_proposal.weeks_running": (
        (
            r"\bweeks_running\"?\s*[:=]\s*{n}",
            r"{n}\s+weeks?\s+of\s+(?:most|more\s+than)\b",
            r"\b(?:ceiling|sets)\b[^\n]{0,60}?{n}\s+(?:weeks?\s+running|consecutive\s+weeks|straight\s+weeks)\b",
            r"{n}\s+(?:weeks?\s+running|consecutive\s+weeks|straight\s+weeks)\b[^\n]{0,40}?\b(?:ceiling|sets)\b",
        ),
        ("a ceiling beaten on most sets {n} weeks running", "{n} weeks of most sets"),
    ),
    "progression.gain_rule.consecutive_same_type_exposures": (
        (
            r"\bconsecutive_same_type_exposures\"?\s*[:=]\s*{n}",
            r"{n}\s+(?:consecutive\s+)?(?:same[\s-]type\s+)?(?:top[\s-]of[\s-](?:the[\s-])?range\s+)?exposures",
        ),
        ("{n} consecutive same-type exposures", "{n} top-of-range exposures"),
    ),
    "progression.gain_rule.step_lb": (
        (
            r"\bstep_lb\"?\s*[:=]\s*{n}",
            r"\+{n}[\s-]*lbs?\b",
            r"{n}[\s-]*lbs?\s+(?:load\s+)?(?:step|jump|increment)s?\b",
            r"\bone\s+{n}[\s-]*lb\b",
        ),
        ("+{n} lb", "a {n}-lb step", '"step_lb": {n}'),
    ),
    "progression.gain_rule.step_pct": (
        (r"\bstep_pct\"?\s*[:=]\s*{n}", r"\+?{n}\s*%\s+(?:of\s+the\s+load|load|step|jump)"),
        ("+{n} % of the load",),
    ),
    "progression.stall_rule.consecutive_exposures": (
        (r"\bconsecutive_exposures\"?\s*[:=]\s*{n}", r"{n}\s+(?:consecutive\s+)?(?:same[\s-]type\s+)?exposures"),
        ("{n} consecutive exposures", "{n} exposures running"),
    ),
    "progression.stall_rule.max_rpe": (
        (
            r"\bmax_rpe\"?\s*[:=]\s*{n}",
            r"\b(?:stall\w*|step_due)\b[^\n]{0,80}?\bRPE\s*(?:{n}\s+or\s+(?:lower|less|under|below)|(?:<=|≤)\s*{n})",
            r"\bRPE\s*(?:{n}\s+or\s+(?:lower|less|under|below)|(?:<=|≤)\s*{n})[^\n]{0,80}?\b(?:stall\w*|step_due)\b",
        ),
        ("a stall: the same load at RPE {n} or lower", "each at RPE {n} or lower (the stall rule)", '"max_rpe": {n}'),
    ),
    "progression.stall_rule.rep_step_max": (
        (r"\brep_step_max\"?\s*[:=]\s*{n}", r"\bup\s+to\s+{n}\s+(?:more\s+|extra\s+)?reps", r"\+{n}\s+reps\b"),
        ("up to {n} more reps",),
    ),
    "disruption.templates.travel.sessions_per_wk": (
        (r"{n}\s+(?:short\s+)?sessions\s+(?:a|per)\s+(?:week|wk)", r"\"travel\"\s*:\s*\{\s*\"sessions_per_wk\"\s*:\s*{list}"),
        ("{n} short sessions a week",),
    ),
    "disruption.templates.busy.sessions_per_wk": (
        (r"{n}\s+(?:short\s+)?sessions\s+(?:a|per)\s+(?:week|wk)", r"\"busy\"\s*:\s*\{\s*\"sessions_per_wk\"\s*:\s*{list}"),
        ("{n} sessions a week",),
    ),
    "disruption.step_back_up.days": (
        (r"{n}[\s-]+day\s+step[\s-]+back", r"\bstep[\s-]+back[\s-]+up\b[^\n]{0,30}?{n}\s+days"),
        ("a {n}-day step back up",),
    ),
    "disruption.offer.travel_lead_days": (
        (r"\btravel_lead_days\"?\s*[:=]\s*{n}", r"{n}\s+days\s+(?:before|ahead\s+of)\s+(?:a\s+|the\s+)?(?:trip|travel)"),
        ("{n} days before a trip",),
    ),
    "disruption.offer.missed_session_days": (
        (r"\bmissed_session_days\"?\s*[:=]\s*{n}", r"{n}\s+days\s+(?:without|with\s+no)\s+(?:a\s+)?(?:session|lift)"),
        ("{n} days without a session",),
    ),
    "disruption.max_days": (
        (
            r"\bmax_days\"?\s*[:=]\s*{n}",
            r"{n}\s+days\s+(?:of\s+)?disruption",
            r"\bdisruption\b[^\n]{0,30}?(?:at\s+most|up\s+to|max(?:imum)?)\s+{n}\s+days",
        ),
        ("{n} days of disruption",),
    ),
    "calibration.tape_and_photos.every_weeks": (
        (
            r"\b(?:tape|photos?|measurements?)\b[^\n]{0,40}?\bevery\s+{n}\s+weeks",
            r"\bevery\s+{n}\s+weeks\b[^\n]{0,40}?\b(?:tape|photos?)\b",
        ),
        ("tape and photos every {n} weeks",),
    ),
    "calibration.tape_and_photos.dead_man_missed_cycles": (
        (r"\bdead_man_missed_cycles\"?\s*[:=]\s*{n}", r"{n}\s+missed\s+(?:cycles|tapes?|photo\s+days)"),
        ("{n} missed cycles",),
    ),
    "calibration.dexa.every_weeks_approx": (
        (r"\bevery_weeks_approx\"?\s*[:=]\s*{n}", r"\b(?:DEXA|DXA)\b[^\n]{0,40}?{n}\s+weeks", r"{n}\s+weeks\b[^\n]{0,20}?\b(?:DEXA|DXA)\b"),
        ("a DEXA about every {n} weeks",),
    ),
    "calibration.fitness_tests.every_weeks": (
        (
            r"\b(?:fitness[\s-]+tests?|battery)\b[^\n]{0,40}?\bevery\s+{n}\s+weeks",
            r"\bevery\s+{n}\s+weeks\b[^\n]{0,30}?\b(?:battery|fitness)\b",
        ),
        ("the fitness test battery every {n} weeks",),
    ),
    "calibration.block_retro.every_weeks": (
        (r"\bretro\b[^\n]{0,40}?\bevery\s+{n}\s+weeks", r"\bevery\s+{n}\s+weeks\b[^\n]{0,30}?\bretro\b"),
        ("the block retro every {n} weeks",),
    ),
    "calibration.block_retro.scorecard_rows": (
        (r"\bscorecard_rows\"?\s*[:=]\s*{n}", r"{n}[\s-]+row\s+(?:\w+\s+)?scorecard", r"\bscorecard\b[^\n]{0,30}?{n}\s+rows"),
        ("the {n}-row scorecard",),
    ),
    "panel_target.every_seat_at_least": (
        (r"\bevery_seat_at_least\"?\s*[:=]\s*{n}", r"\b(?:seat|panel)\w*\b[^\n]{0,40}?{n}\s*(?:/|of|out\s+of)\s*\d+"),
        ("every seat at least {n}/10",),
    ),
    "panel_target.out_of": (
        (r"\bout_of\"?\s*[:=]\s*{n}", r"\b(?:seat|panel)\w*\b[^\n]{0,40}?\d+\s*(?:/|out\s+of)\s*{n}\b"),
        ("every seat at least 9 out of {n}",),
    ),
    "sleep.wake_time.tolerance_minutes": (
        (r"\bwak\w*\b[^\n]{0,40}?(?:±|\+/-|\+-|within)\s*{n}\s*min", r"\btolerance_minutes\"?\s*[:=]\s*{n}"),
        ("a fixed wake time ±{n} min", "wake within {n} min of the anchor"),
    ),
    "sleep.wake_time.anchor_window_days": (
        (r"\bwak\w*\b[^\n]{0,60}?(?:trailing|last|past)\s+{n}\s+days", r"\banchor_window_days\"?\s*[:=]\s*{n}"),
        ("his median wake time over the trailing {n} days",),
    ),
    "sleep.wake_time.min_days_for_anchor": (
        (r"\bmin_days_for_anchor\"?\s*[:=]\s*{n}", r"{n}\s+(?:readable\s+)?days\s+(?:for|before)\s+(?:an\s+|the\s+)?anchor"),
        ("{n} readable days for an anchor",),
    ),
}

# #5175: the charter numeric leaves NO pattern here owns, each with its reason. A dotted PREFIX covers every leaf under
# it. The coverage test below fails on a leaf that is neither patterned nor listed, and on a row that covers nothing.
NOT_APPLICABLE: Dict[str, str] = {
    "gated_movements.running.walking_weeks": "the run gate's walking condition: read only by training.run_onramp; held equal to "
    "the owner_redlines run_gate_lb tissue clause by tests/test_run_onramp_5090.py",
    "gated_movements.running.walking_hours_per_wk": "as walking_weeks (training.run_onramp; tests/test_run_onramp_5090.py)",
    "gated_movements.running.onramp": "the Stage 4 level table and its spacing: read only by training.run_onramp, every expected "
    "number in tests/test_run_onramp_5090.py read from the charter; a table of small integers no prose pattern can key",
    "gated_movements.lower_leg_prep.prescription": "the prep doses: read only by training.run_onramp's prep placement "
    "(tests/test_run_onramp_5090.py); sets/reps/RPE of three accessories, the class effort_ceiling_rpe already sweeps in range form",
    "split.minimum_session.back_off_pct": "shares its number with the owner-fixed heavy scheme (program_structure.EXPOSURES: top "
    "set + 2 back-offs at -10 %, a pre-charter ruling with its own home, and its v0.4 freeze in program_v04), so neither a key nor "
    "a prose pattern can tell a copy from the scheme; read only by training.disruption.minimum_shape (tests/test_disruption_mode_5088.py)",
    "calibration.fitness_tests.early_days_credited": "the battery's due-week arithmetic: read only by training.fitness_tests "
    "(tests/test_fitness_tests_5078.py); no prose names it",
    "calibration.fitness_tests.grace_weeks": "as early_days_credited (training.fitness_tests; tests/test_fitness_tests_5078.py)",
    "calibration.fitness_tests.tests": "each test's protocol constants (durations, reps): the battery's own definition, read "
    "only by training.fitness_tests and printed from the charter by the protocol card (tests/test_fitness_tests_5078.py)",
    "phase_after_may.plan_prompt": "the post-deadline plan prompt's weeks (#5130): owner-only, read only by "
    "training.phase_after_may (tests/test_phase_after_may_5130.py); no swept file names them",
    "early_warning": "the relapse early-warning thresholds (#5121): read only by health.early_warning, outside this guard's "
    "swept set (the training consumers); every expected number in tests/test_relapse_early_warning_5121.py is read from the "
    "charter, and the owner's own failure_mode prose in config/user_goals.json names no swept pattern's noun",
    "nutrition": "outside this guard's swept set (the training consumers): every nutrition number has ONE reader with its own "
    "contract test — calories: health.calorie_target (tests/test_calorie_target_one_resolver_5095.py, which also sweeps "
    "lambdas/ mcp/ deploy/ scripts/ for a new 1,500 kcal literal); eating_window: health.eating_window "
    "(tests/test_eating_window_reads_5099.py, which also sweeps lambdas/ mcp/ for a typed window); protein: health.protein_engine "
    "(tests/test_protein_engine_5098.py, tests/test_one_protein_feeding_definition_5214.py); expenditure: "
    "health.expenditure_reconciler (tests/test_expenditure_reconciler_5097.py); titration: health.titration "
    "(tests/test_titration_engine_5096.py); training_day: tests/test_training_day_fuel_5101.py; labs: "
    "tests/test_lab_followup_5111.py; food_delivery: tests/test_food_delivery_upload_ritual_5006.py; maintenance_weeks + reverse_diet: "
    "health.maintenance_week (tests/test_maintenance_week_5107.py); travel_food: health.travel_food "
    "(tests/test_travel_food_kit_5104.py); floors: "
    "health.macro_floors (tests/test_macro_floors_5102.py) — the fibre floor alone is swept here (fibre_floor, #5204)",
}

# A pattern's owning path covers the leaves under it — except `gated_movements`, whose pattern is derived from the
# `*_lb` weights only, so it covers exactly those.
_COVERS_ONLY = {"gated_movements": lambda leaf: leaf.rsplit(".", 1)[-1].endswith("_lb")}


def _numeric_leaves(node: Any, path: str = "") -> List[Tuple[str, Any]]:
    """Every numeric leaf (int, float, or an all-numeric list) outside `_README` / `version` / `change_log`."""
    out: List[Tuple[str, Any]] = []
    if isinstance(node, bool):
        return out
    if isinstance(node, (int, float)):
        return [(path, node)]
    if isinstance(node, list):
        if node and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in node):
            return [(path, node)]
        for i, x in enumerate(node):
            out += _numeric_leaves(x, f"{path}[{i}]")
        return out
    if isinstance(node, dict):
        for k, v in node.items():
            if not path and k in ("_README", "version", "change_log"):
                continue
            out += _numeric_leaves(v, f"{path}.{k}" if path else k)
    return out


def _under(leaf: str, prefix: str) -> bool:
    return leaf == prefix or leaf.startswith(prefix + ".") or leaf.startswith(prefix + "[")


def _num_alt(x: Any) -> str:
    """One number: its digit forms (`_num_forms`) bounded so `15` never matches inside `150` or `1.5`, or its word."""
    x = abs(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else x
    digits = rf"(?<![\w.])(?:{'|'.join(_num_forms(x))})(?!\d|\.\d)"
    word = NUM_WORDS.get(int(x)) if float(x).is_integer() else None
    return rf"(?:{digits}|\b{word}\b)" if word else digits


def _slots(v: Any) -> Dict[str, str]:
    if isinstance(v, list):
        lo, hi = v
        n = _num_alt(lo) if lo == hi else rf"{_num_alt(lo)}\s*(?:[-–]|to|or)\s*{_num_alt(hi)}"
        lst = rf"\[\s*(?:{'|'.join(_num_forms(lo))})\s*,\s*(?:{'|'.join(_num_forms(hi))})\s*\]"
        return {"n": n, "list": lst, "pct": n, "times": n}
    n = _num_alt(v)
    pct = n
    if isinstance(v, float) and 0 < v < 1:
        p = round(v * 100)
        pct = rf"(?:{p}\s*%|{p}\s+percent" + (r"|half" if p == 50 else "") + ")"
    tw = _TIMES_WORDS.get(int(v)) if float(v).is_integer() else None
    times = rf"(?:{n}\s*(?:x|×|times)\b" + (rf"|\b{tw}\b" if tw else "") + ")"
    return {"n": n, "list": rf"(?<![\w.])(?:{'|'.join(_num_forms(abs(v)))})(?!\d|\.\d)", "pct": pct, "times": times}


def _fill(template: str, slots: Dict[str, str]) -> str:
    out = template
    for k, rx in slots.items():
        out = out.replace("{" + k + "}", rx)
    return out


def _probe_renderings(template: str, v: Any) -> List[str]:
    """A probe template rendered with the charter value in digits, and again in words where NUM_WORDS has it."""

    def digits(x: Any) -> str:
        x = abs(x)
        return str(int(x)) if float(x).is_integer() else str(x)

    def words(x: Any) -> Optional[str]:
        return NUM_WORDS.get(int(abs(x))) if float(x).is_integer() else None

    if isinstance(v, list):
        lo, hi = v
        d_n = digits(lo) if lo == hi else f"{digits(lo)}-{digits(hi)}"
        w_n = (words(lo) if lo == hi else (f"{words(lo)} to {words(hi)}" if words(lo) and words(hi) else None)) if words(lo) else None
        forms = [{"n": d_n, "list": f"[{digits(lo)}, {digits(hi)}]", "pct": d_n, "times": f"{d_n}x"}]
        if w_n:
            forms.append({"n": w_n, "list": f"[{digits(lo)}, {digits(hi)}]", "pct": w_n, "times": f"{w_n} times"})
    else:
        pct = f"{round(v * 100)}%" if isinstance(v, float) and 0 < v < 1 else digits(v)
        forms = [{"n": digits(v), "list": f"[{digits(v)}]", "pct": pct, "times": f"{digits(v)}x"}]
        if words(v):
            forms.append({"n": words(v), "list": f"[{digits(v)}]", "pct": pct, "times": _TIMES_WORDS.get(int(v), f"{words(v)} times")})
    out = []
    for f in forms:
        r = template
        for k, s in f.items():
            r = r.replace("{" + k + "}", s)
        if r not in out:
            out.append(r)
    return out


def _leaf_patterns(c: Dict[str, Any]) -> Dict[str, Tuple[str, re.Pattern[str]]]:
    """pattern id (= the owning leaf path) -> (owning path, compiled regex), the numbers filled from the charter."""
    out: Dict[str, Tuple[str, re.Pattern[str]]] = {}
    for path, (templates, _probes) in LEAF_PATTERNS.items():
        v = tc._get(c, path)
        if v is tc._MISSING:
            continue  # the coverage test names a dead row; a pattern for an absent leaf would be blind by construction
        slots = _slots(v)
        out[path] = (path, re.compile("|".join(f"(?:{_fill(t, slots)})" for t in templates), re.I))
    return out


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
    rpe_bands = _ranges(c["effort_ceilings"]["by_movement_class"].values())  # #5058: renamed from by_experience_tier
    words = NUM_WORDS
    return {
        "fibre_floor": (
            "nutrition.floors.fibre.floor_g",
            re.compile(
                r"\bdaily_fiber_min_g\"?\s*[:=]\s*\d"
                r"|\"fiber_g\"\s*:\s*\{\s*\"target\"\s*:\s*\d"
                r"|\b\d+(?:\.\d+)?\s*g(?:rams)?\s+(?:of\s+)?fib",  # ANY number in prose: a drifted '38g fiber' is caught too
                re.I,
            ),
        ),
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
            "effort_ceilings.by_movement_class",
            re.compile(
                rf"\b(?:top|compounds?|isolation|accessor\w*|effort)\w*_rpe\w*\"?\s*[:=]\s*(?:\[\s*\d|\d)"
                rf"|\bRPE\s*(?:{rpe_bands})\b"
                rf"|\bRPE\s*\d+(?:\.\d)?\s*[-–]\s*\d+(?:\.\d)?\b",
                re.I,
            ),
        ),
        **_leaf_patterns(c),
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
        "fibre_floor": [
            '"daily_fiber_min_g": 25,',
            '"fiber_g": {"target": 38, "label": "Fiber"},',
            "a 35 g fibre floor",
            "| 38g fiber |",
            "a 21.5 g of fibre target",
        ],
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
        "fibre_floor": ['"fiber_g": {"target": macro_floors.floor_g("fibre"), "label": "Fiber"},', 'out["daily_fiber_min_g"] = floor_g()'],
        "volume_band_sets": ['out["weekly_sets_by_muscle"] = f()', 'row.get("avg_sets_per_week")'],  # computed / read
    }
    pats = _patterns()
    leaf_ids = set(LEAF_PATTERNS)
    assert set(probes) == set(pats) - leaf_ids, "every value-class pattern carries a probe (the leaf patterns carry their own)"
    blind = [f"{pid}: {p!r}" for pid, (_o, rx) in pats.items() if pid in probes for p in probes[pid] if not rx.search(p)]
    assert not blind, f"patterns that no longer match their own probe: {blind}"
    loud = [f"{pid}: {p!r}" for pid, ps in negatives.items() for p in ps if pats[pid][1].search(p)]
    assert not loud, f"patterns matching a line they must not: {loud}"
    assert len(_swept_files()) >= 40, "the sweep covers (almost) nothing — a directory moved"
    assert {"mcp/tools_benchmark.py", "lambdas/web/site_api_nutrition.py"} <= {p.relative_to(_REPO).as_posix() for p in _swept_files()}


def test_every_charter_numeric_leaf_has_a_pattern_or_a_stated_reason():
    """#5175: the leaves are enumerated FROM THE CHARTER, not from a hand list, so a new numeric leaf reds here until it
    gets a pattern (LEAF_PATTERNS or a value-class pattern whose owner covers it) or a NOT_APPLICABLE reason. A leaf
    both patterned and excused, an excuse that covers nothing and a pattern for a leaf the charter no longer has are
    all named too, so neither table can rot."""
    c = tc.load_charter()
    leaves = [p for p, _v in _numeric_leaves({k: v for k, v in c.items() if k not in ("public_loaded", "private_loaded")})]
    owners = {o for o, _rx in _patterns().values()}

    def patterned(leaf: str) -> bool:
        return any(_under(leaf, o) and _COVERS_ONLY.get(o, lambda _l: True)(leaf) for o in owners)

    def excused(leaf: str) -> bool:
        return any(_under(leaf, na) for na in NOT_APPLICABLE)

    problems = [f"{leaf}: no pattern and no NOT_APPLICABLE reason" for leaf in leaves if not patterned(leaf) and not excused(leaf)]
    problems += [
        f"{leaf}: patterned AND excused — drop the NOT_APPLICABLE row" for leaf in leaves if patterned(leaf) and leaf in NOT_APPLICABLE
    ]
    problems += [f"NOT_APPLICABLE[{na!r}] covers no numeric leaf" for na in NOT_APPLICABLE if not any(_under(leaf, na) for leaf in leaves)]
    problems += [f"LEAF_PATTERNS[{p!r}] names a leaf the charter does not carry" for p in LEAF_PATTERNS if p not in leaves]
    assert not problems, "\n".join(problems)
    assert len(leaves) >= 65, f"only {len(leaves)} numeric leaves — the walk went blind"


def test_every_leaf_pattern_sees_its_copy_in_digits_and_in_words():
    """#5175 positive control: every probe, rendered with the charter's own number in digits AND in words (where the
    shared map has the word), is a hit for its leaf's pattern — and the two specimens the #5086 review removed by hand
    from the coach-session skill are hits for the leaves they copied."""
    c = tc.load_charter()
    pats = _patterns()
    blind = []
    for path, (_templates, probes) in LEAF_PATTERNS.items():
        v = tc._get(c, path)
        for probe in probes:
            for text in _probe_renderings(probe, v):
                if not pats[path][1].search(text):
                    blind.append(f"{path}: {text!r}")
    assert not blind, "leaf patterns that no longer match their own probe:\n" + "\n".join(blind)
    specimens = {
        "split.lifting_days_per_wk": "each session role of the five lifting days",
        "effort_ceilings.ceiling_change_proposal.weeks_running": "Two weeks of most sets above the ceiling",
        "effort_ceilings.overage_tolerance_rpe": "an overage within +1 RPE of the ceiling is not a breach",
        "progression.gain_rule.step_lb": "earn +5 lb next time",
    }
    missed = [f"{p}: {t!r}" for p, t in specimens.items() if not pats[p][1].search(t)]
    assert not missed, f"the named specimens are not hits: {missed}"
    # A number inside a bigger one is not a copy: `15` never matches in `150`, a `2` never in `2.5`.
    quiet = {
        "split.lifting_days_per_wk": ["15 lifting days", "2.5 lifting days"],
        "progression.gain_rule.step_lb": ["+50 lb", "+0.5 lb"],
        "steps.ramp.ramp_window_days": ["a 140-day ramp"],
    }
    loud = [f"{p}: {t!r}" for p, ts in quiet.items() for t in ts if pats[p][1].search(t)]
    assert not loud, f"leaf patterns matching a different number: {loud}"


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
