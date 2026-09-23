"""
recovery_authoring.py — Stage 2: recovery-adaptive night-before authoring.

Routines are authored the night before; Matthew trains the next morning
(wake → car → gym) with ZERO platform interaction possible. So the routine in
his hand must be (a) authored only on complete data, and (b) self-adapting at
5am off a wrist-visible Whoop recovery band, with a safe default.

This module is the DETERMINISTIC CORE — pure functions, stdlib only, NO mcp.config
/ boto3 import, so it unit-tests without env vars or AWS. The I/O that gathers
volume / recovery / workout-history lives in tools_hevy_routine.py and feeds these
functions. Design brief: docs/specs/SPEC_RECOVERY_ADAPTIVE_AUTHORING_2026-06-21.md.

Non-negotiables encoded here (brief §2):
  1. Author tier-agnostic — the routine carries GREEN/YELLOW/RED branches; the
     morning selects one. No single recovery_tier is baked into the prescription.
  2. Safe default — absent/ambiguous morning signal resolves to YELLOW.
  3. Subtract-only — GREEN is the authored ceiling; YELLOW/RED are defined
     subtractions; nothing lets him exceed the GREEN ceiling on the day. And
     (#3927) nothing lets a prescription sit BELOW a load already achieved at
     this bodyweight band: subtract-only has a floor as well as a ceiling, and
     the athlete is never handed the job of triggering his own progression.
  4. Freshness-gated — author only when volume/recovery/recent-workout inputs
     cover the latest ingested session (completeness, not max-date recency).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

# #3927 — the rule has ONE wording, and it lives on the bundled side because the cron
# generator must carry it into every Lambda zip. This import keeps the module's purity
# contract: `training.routine_generator` pulls no boto3 and no mcp.config at import time
# (its S3/DDB clients are all lazily constructed inside functions), so this file still
# unit-tests with no env vars and no AWS. Two copies of a rule is how a rule drifts.
from training.routine_generator import SUBTRACT_ONLY_RULE  # noqa: F401  (re-exported: the skill doc + tests read it from here)

# ── Single source of truth: Whoop recovery bands + the rubric (brief §3) ──
# Branches key to Whoop's OWN thresholds because that's what's on his wrist at 5am.
BAND_THRESHOLDS = {"green_min": 67, "yellow_min": 34}  # green 67-100, yellow 34-66, red 1-33

# Base top-set RPE ceiling for a primary lift on a normal (yellow) day. GREEN adds
# the bonus (the ceiling); YELLOW is base; RED subtracts to a floor. Week-position /
# deficit / tissue caps can collapse GREEN down to base ("quality, not load").
RPE_BASE_YELLOW = 8
RPE_GREEN_BONUS = 1  # green ceiling = base + bonus, unless a cap applies
RPE_RED_SUBTRACT = 2  # red floor = base - subtract (or cut the top set entirely)

LOWER_OF_RULE = "use the lower of band/feel"
DEFAULT_NOTE = "no band → do YELLOW"

# Deficit states (from get_deficit_sustainability / recent nutrition).
DEEP_DEFICIT = "deep"
LATE_WEEK_STREAK = 5  # consecutive training days at/after which GREEN caps to quality
EARLY_RAMP_SESSIONS = 3  # novel-pattern sessions-into-block below which GREEN tendon-caps


# ──────────────────────────────────────────────────────────────────────────────
# Freshness / completeness gate (brief §5/E3 — the headline)
# ──────────────────────────────────────────────────────────────────────────────
def assess_authoring_freshness(volume_completeness, latest_recovery_date, target_date, recovery_max_age_days=2):
    """Is the platform state complete enough to author target_date's routine?

    Pure core for authoring_freshness_gate. Inputs:
      volume_completeness  — the dict from strength_helpers.assess_volume_completeness
                             (its `stale` flag is the muscle-volume completeness signal)
      latest_recovery_date — newest Whoop recovery DATE# ('YYYY-MM-DD' or None)
      target_date          — the day being authored ('YYYY-MM-DD')
      recovery_max_age_days— how old recovery may be (relative to target_date) before
                             it's a gap (default 2 — covers a night-before author)

    Returns {ok: bool, gaps: [{input, detail}]}. `ok` is False when ANY input lags
    the latest ingested session — the draft path must refuse to compile and surface
    the gaps so Claude refreshes/flags rather than authoring on stale data.
    """
    gaps = []

    if volume_completeness and volume_completeness.get("stale"):
        gaps.append(
            {
                "input": "muscle_volume",
                "detail": volume_completeness.get("note") or "Volume aggregation trails the latest ingested session.",
            }
        )

    if not latest_recovery_date:
        gaps.append({"input": "recovery", "detail": "No Whoop recovery on record — cannot anchor week-position baseline."})
    else:
        try:
            age = (datetime.strptime(target_date, "%Y-%m-%d").date() - datetime.strptime(latest_recovery_date, "%Y-%m-%d").date()).days
            if age > recovery_max_age_days:
                gaps.append(
                    {
                        "input": "recovery",
                        "detail": (
                            f"Latest recovery {latest_recovery_date} is {age}d before target — " f"stale beyond {recovery_max_age_days}d."
                        ),
                    }
                )
        except (ValueError, TypeError):
            gaps.append({"input": "recovery", "detail": f"Unparseable recovery date {latest_recovery_date!r}."})

    return {"ok": not gaps, "gaps": gaps}


# ──────────────────────────────────────────────────────────────────────────────
# Week-position / fuel / tissue context (brief §4)
# ──────────────────────────────────────────────────────────────────────────────
def _consecutive_days(workout_dates, target_date):
    """Streak length immediately before target_date (consecutive prior days trained)."""
    have = {d for d in (workout_dates or []) if d}
    try:
        cur = datetime.strptime(target_date, "%Y-%m-%d").date() - timedelta(days=1)
    except (ValueError, TypeError):
        return 0
    streak = 0
    while cur.isoformat() in have:
        streak += 1
        cur -= timedelta(days=1)
    return streak


def derive_training_context(workout_dates, deficit_state, target_date, tissue_ramp_sessions=None):
    """Where is he in the week / fuel / tissue ramp? Drives the GREEN ceiling + floors.

    Pure. The GREEN ceiling lowers to "quality, not load" when he's deep in a deficit
    OR late in a training streak OR early in a novel-pattern ramp (brief §4 / Marcus +
    Iris). `green_ceiling_quality` True means GREEN must NOT add load/RPE — it collapses
    to the YELLOW baseline (quality maintenance), preserving subtract-only on a
    motivated morning.
    """
    consecutive = _consecutive_days(workout_dates, target_date)
    deficit = (deficit_state or "moderate").lower()
    early_ramp = tissue_ramp_sessions is not None and tissue_ramp_sessions <= EARLY_RAMP_SESSIONS

    late_week = consecutive >= LATE_WEEK_STREAK
    deep_deficit = deficit == DEEP_DEFICIT
    green_ceiling_quality = late_week or deep_deficit or early_ramp

    reasons = []
    if late_week:
        reasons.append(f"day {consecutive + 1} of a streak — GREEN is quality, bias YELLOW/RED structure")
    if deep_deficit:
        reasons.append("deep deficit — GREEN is quality maintenance, not load")
    if early_ramp:
        reasons.append(f"early tissue ramp ({tissue_ramp_sessions} sessions in) — cap novel-pattern GREEN")

    return {
        "consecutive_days": consecutive,
        "deficit_state": deficit,
        "tissue_ramp_sessions": tissue_ramp_sessions,
        "late_week": late_week,
        "green_ceiling_quality": green_ceiling_quality,
        "reasons": reasons,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Branch construction (brief §3) — subtract-only ceiling
# ──────────────────────────────────────────────────────────────────────────────
def build_top_set_branches(base_rpe, training_context):
    """GREEN/YELLOW/RED top-set RPE branches for a primary lift. Subtract-only.

    YELLOW is the baseline (base_rpe). GREEN is the ceiling = base + bonus, UNLESS the
    week-position/deficit/tissue context collapses it to quality (== base). RED is the
    floor. Invariant (tested): green >= yellow >= red, and green never exceeds the
    authored ceiling (base + bonus).
    """
    quality = bool(training_context and training_context.get("green_ceiling_quality"))
    green_rpe = base_rpe if quality else base_rpe + RPE_GREEN_BONUS
    red_rpe = max(base_rpe - RPE_RED_SUBTRACT, 1)
    return {
        "green": {
            "rpe_cap": green_rpe,
            "cue": (f"top set RPE {green_rpe}" if not quality else f"top set RPE {green_rpe} (quality — hold load, sharpen execution)"),
        },
        "yellow": {"rpe_cap": base_rpe, "cue": f"top set RPE {base_rpe} (the plan)"},
        "red": {"rpe_cap": red_rpe, "cue": f"cut the top set — RPE {red_rpe} cap, or convert to technique"},
    }


def render_branch_block(branches):
    """Render a per-exercise branches dict into the standard one-liner cue.

    e.g. '🟢 top set RPE 9 · 🟡 top set RPE 8 (the plan) · 🔴 cut the top set … · use the lower of band/feel'
    """
    if not branches:
        return ""
    g = branches.get("green", {}).get("cue", "")
    y = branches.get("yellow", {}).get("cue", "")
    r = branches.get("red", {}).get("cue", "")
    return f"🟢 {g} · 🟡 {y} · 🔴 {r} · {LOWER_OF_RULE}"


def render_session_block(training_context, inputs_current_through=None):
    """The always-present session-level adaptive block written into routine.notes.

    This is the safe default and the rubric in one place: it states the bands, the
    YELLOW default, the lower-of-band/feel rule, and any week-position ceiling. Present
    on EVERY adaptive routine so the session self-adapts at 5am regardless of whether
    any per-exercise branch was detected (brief §5/E1,E2,E11).
    """
    gmin = BAND_THRESHOLDS["green_min"]
    ymin = BAND_THRESHOLDS["yellow_min"]
    lines = [
        "— ADAPT BY WAKE RECOVERY —",
        f"🟢 {gmin}-100: take the ceiling (top-set bonus, optional work ON, intervals if conditioning)",
        f"🟡 {ymin}-{gmin - 1}: the plan as written (DEFAULT — {DEFAULT_NOTE})",
        f"🔴 1-{ymin - 1}: floor — cut top sets, optional work OFF, Z2/mobility, or rest",
        f"Rule: {LOWER_OF_RULE} — feel can downgrade a branch, never upgrade it.",
        # #3927 — the rule on the wire, in the routine he is holding. The RPE branch
        # above adapts EFFORT; this line says the LOAD number is not a branch at all.
        f"Load: {SUBTRACT_ONLY_RULE}",
    ]
    if training_context and training_context.get("reasons"):
        lines.append("Today: " + "; ".join(training_context["reasons"]) + ".")
    if inputs_current_through:
        lines.append(f"inputs_current_through: {inputs_current_through}")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Subtract-only: the conditional-UP detector + the prescription auditor (#3927)
# ──────────────────────────────────────────────────────────────────────────────
# The specimen, verbatim off the wire (DDB `USER#matthew#ROUTINE#a5980a24…`,
# target 2026-09-19, incline_db_press):
#
#     "Ceiling RPE 9. If set 1 is <=7.5 go 80 - you had 80x8 on 09-11 leading with incline."
#
# The routine prescribed 75 lb and put the 80 he had ALREADY done behind a condition he
# had to evaluate himself, mid-set, at 5am. Three failures in one sentence: the number is
# below an achieved load; the progression is his job; and the note proves the platform
# knew. This detector is the structural guard against the sentence class, not the
# sentence — it fires on a condition marker and an ESCALATION in the same clause.
#
# What it must NOT fire on, also verbatim from the same live routines, because a
# subtract-only rule that eats its own down-branches is worse than no rule:
#     "Drop to 40x10 if set 1 exceeds it."        (a down-branch — the sanctioned form)
#     "HOLD 185x5 — do not add load."             ("add load", no condition: a prohibition)
#     "If set 3 is RPE9+, that's the session."    (a stop condition)
#
# Clauses split on SENTENCE boundaries (a period followed by space), never on a bare
# period: the live specimen contains "<=7.5", and splitting there tore the condition
# off its escalation and made the detector blind to the one sentence it exists for.
_CLAUSE_SPLIT = re.compile(r"(?<=[.!?])\s+|[\n·;]")

# A branch marker — the text makes the next thing CONDITIONAL on something he observes.
_CONDITION_MARKER = re.compile(
    r"\b(?:if|once|when|unless|provided)\b|\bgreen\s+only\b|\bperformance[- ]gated\b|\bgreen\b\s*[:,]",
    re.IGNORECASE,
)

# An escalation — the conditional's payload RAISES load or volume. Named individually so
# a finding can say which form it matched rather than just "matched".
_ESCALATIONS = [
    ("go_to_number", re.compile(r"\bgo\s+(?:up\s+|higher\s+|heavier\s+|to\s+)?\d+(?:\.\d+)?\s*(?:lb|lbs|kg)?\b", re.IGNORECASE)),
    ("go_up", re.compile(r"\bgo\s+(?:up|higher|heavier)\b", re.IGNORECASE)),
    ("climb", re.compile(r"\bclimb(?:s|ing|ed)?\b", re.IGNORECASE)),
    ("add_load", re.compile(r"\badd\s+(?:load|weight|\d+(?:\.\d+)?\s*(?:lb|lbs|kg))", re.IGNORECASE)),
    ("add_set", re.compile(r"\badd\s+(?:one\s+more|another|an?\s+extra|an?\s+additional)\s+set\b", re.IGNORECASE)),
    ("extra_set", re.compile(r"\b(?:a\s+|an\s+)?(?:2nd|second|3rd|third|4th|fourth|extra|additional)\s+set\b", re.IGNORECASE)),
    ("increase", re.compile(r"\b(?:increase|bump|jump|move)\s+(?:up|to|the\s+(?:load|weight))\b", re.IGNORECASE)),
    ("work_up_to", re.compile(r"\bwork\s+up\s+to\s+\d+", re.IGNORECASE)),
    ("toward_number", re.compile(r"\btowards?\s+\d+(?:\.\d+)?\s*(?:lb|lbs|kg)?\b", re.IGNORECASE)),
    ("progress_to", re.compile(r"\bprogress\s+to\s+\d+", re.IGNORECASE)),
]

# Self-contained: the condition and the escalation are the same phrase.
# Live: "65 only if set 1 was <=8 (GREEN)" — docs/coaching/routines/pull/foundation_pull_w4.md
_BARE_NUMBER_ONLY_IF = re.compile(r"\b\d+(?:\.\d+)?\s*(?:lb|lbs|kg)?\s+only\s+if\b", re.IGNORECASE)


def find_conditional_up(text):
    """Every conditional-UP clause in one block of prescription prose.

    Returns a list of {clause, pattern, match} — empty when the prose is clean. A list
    rather than a bool because a caller (and a failing test) has to be able to print the
    sentence, not just the verdict.
    """
    if not text:
        return []
    found = []
    for clause in _CLAUSE_SPLIT.split(str(text)):
        clause = clause.strip()
        if not clause:
            continue
        bare = _BARE_NUMBER_ONLY_IF.search(clause)
        if bare:
            found.append({"clause": clause, "pattern": "number_only_if", "match": bare.group(0)})
            continue
        if not _CONDITION_MARKER.search(clause):
            continue
        for name, rx in _ESCALATIONS:
            m = rx.search(clause)
            if m:
                found.append({"clause": clause, "pattern": name, "match": m.group(0)})
                break
    return found


def _sets_of(exercise):
    return (exercise.get("sets") if isinstance(exercise, dict) else getattr(exercise, "sets", None)) or []


def _field(obj, name, default=None):
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


# #4065 — a load equal to the floor must pass. A floor drawn from Hevy's stored kg
# (63.50300732) against a draft's lb->kg rounding (140 lb -> 63.5029) differs by 0.0001 kg,
# and a 1e-6 comparison refused a set AT the floor. 0.05 kg (~0.11 lb) absorbs any kg<->lb
# round trip and is an order of magnitude under the smallest real plate step (1.25 lb =
# 0.57 kg), so it cannot let a genuine under-prescription through.
LOAD_TOLERANCE_KG = 0.05


def _is_working(s):
    return str(_field(s, "type", "normal") or "normal").lower() != "warmup" and _field(s, "weight_kg") is not None


def _reps_of(s):
    for name in ("reps", "rep_range_end", "rep_range_start"):
        if _field(s, name) is not None:
            return int(_field(s, name))
    return None


def prescribed_back_offs(sets, floor_kg, scheme):
    """{set index: exemption} for the back-offs the program's OWN rep scheme prescribes (#4065).

    Derived from `training.rep_scheme` (parsed from the redline prose, never a hand list). The
    exemption holds only for the scheme's shape: the top set is the heaviest working set, its
    reps sit in the heavy-exposure range, it is itself at or above the floor, and each exempt
    set is one of the `back_offs` working sets IMMEDIATELY after it, at no less than the
    rounded −pct minimum. A set outside that window — an extra back-off, a deeper cut, a
    back-off off a sub-floor top — is not a prescribed back-off and meets the floor as before.
    Returns ({index: record}, {index: why_not}) — the second names why a set did NOT qualify.
    """
    from training.rep_scheme import back_off_min_kg

    if (scheme or {}).get("status") != "ok":
        return {}, {}
    working = [(i, float(_field(s, "weight_kg"))) for i, s in enumerate(sets) if _is_working(s)]
    if not working:
        return {}, {}
    top_kg = max(w for _, w in working)
    top_pos = next(p for p, (_, w) in enumerate(working) if w >= top_kg - LOAD_TOLERANCE_KG)
    top_i = working[top_pos][0]
    lo, hi = scheme["top_reps"]
    reps = _reps_of(sets[top_i])
    if reps is None or not lo <= reps <= hi:
        return {}, {i: f"top set {top_i + 1} is not a heavy exposure ({reps} reps, scheme {lo}-{hi})" for i, _ in working}
    if top_kg < float(floor_kg) - LOAD_TOLERANCE_KG:
        return {}, {i: f"top set {top_i + 1} is itself below the floor" for i, _ in working}
    min_kg = back_off_min_kg(top_kg, scheme)
    start = top_pos + int(scheme["top_sets"])
    window = working[start : start + int(scheme["back_offs"])]
    exempt, why = {}, {}
    for i, w in window:
        if w >= min_kg - LOAD_TOLERANCE_KG:
            exempt[i] = {"set": i + 1, "top_set": top_i + 1, "top_kg": top_kg, "min_kg": min_kg, "prescribed_kg": w}
        else:
            why[i] = f"deeper than the scheme's -{scheme['back_off_pct']:g} % back-off (min {min_kg:.2f}kg off a {top_kg:.2f}kg top)"
    for i, _ in working[start + int(scheme["back_offs"]) :]:
        why[i] = f"beyond the scheme's {scheme['back_offs']} back-off(s) after top set {top_i + 1}"
    return exempt, why


def audit_prescription(exercises, routine_notes="", floors=None, scheme=None):
    """Is this routine subtract-only? Deterministic, no model, no I/O.

    Two violation classes, both of them acceptance conditions of #3927:
      • `conditional_up` — prose that makes progression the athlete's job;
      • `below_floor`   — a prescribed load under `floors[movement_key]["floor_kg"]`,
                          the band-matched best from `training.routine_generator.
                          prescription_floor` — EXCEPT a back-off the program's own rep
                          scheme prescribes (#4065, `prescribed_back_offs`), which is
                          listed under `back_offs_exempted` instead of passed over.

    `floors` is optional, and its absence is reported (`floors_checked: False`) rather
    than passed over: an audit that could not see the floors is not a clean audit.
    `scheme` defaults to the ACTIVE program's (`training.rep_scheme.heavy_back_off_scheme`).
    """
    if scheme is None:
        from training.rep_scheme import heavy_back_off_scheme

        scheme = heavy_back_off_scheme()
    violations, exempted = [], []
    for hit in find_conditional_up(routine_notes):
        violations.append({"kind": "conditional_up", "where": "routine_notes", **hit})

    for ex in exercises or []:
        # IR vocabulary only. The Hevy wire's own key name stays inside the compiler
        # (tests/test_hevy_compiler_isolation.py) — this auditor runs on the IR, before
        # anything is compiled, which is the only place a refusal is still cheap.
        key = _field(ex, "movement_key") or "?"
        for hit in find_conditional_up(_field(ex, "notes", "")):
            violations.append({"kind": "conditional_up", "where": key, **hit})
        floor = (floors or {}).get(key) or {}
        floor_kg = floor.get("floor_kg")
        if not floor_kg:
            continue
        sets = list(_sets_of(ex))
        back_offs, why_not = prescribed_back_offs(sets, floor_kg, scheme)
        for i, s in enumerate(sets):
            if not _is_working(s):
                continue
            w = float(_field(s, "weight_kg"))
            if w >= float(floor_kg) - LOAD_TOLERANCE_KG:
                continue
            if i in back_offs:
                exempted.append({"where": key, "floor_kg": float(floor_kg), **back_offs[i]})
                continue
            note = f"; not a prescribed back-off: {why_not[i]}" if i in why_not else ""
            violations.append(
                {
                    "kind": "below_floor",
                    "where": key,
                    "set": i + 1,
                    "prescribed_kg": w,
                    "floor_kg": float(floor_kg),
                    "basis": floor.get("basis"),
                    "back_off_note": why_not.get(i),
                    "clause": f"set {i + 1} prescribes {w:.1f}kg against a floor of {float(floor_kg):.1f}kg ({floor.get('status')}){note}",
                }
            )
    return {
        "ok": not violations,
        "rule": SUBTRACT_ONLY_RULE,
        "floors_checked": bool(floors),
        "violations": violations,
        "back_offs_exempted": exempted,
        "back_off_scheme": {k: v for k, v in (scheme or {}).items() if k != "source_text"},
    }
