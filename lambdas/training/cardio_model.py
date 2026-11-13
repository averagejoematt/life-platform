"""cardio_model.py — cardio on its own model (epic #5861, lane L4; the brief's §8). Pure: no I/O, no clock.

WHY THIS EXISTS

The exercise library rates every movement on a hypertrophy rubric, so all its cardio rows are D and nothing reads
them; the live menu (`cardio_menu`) picks the machine by rotation and leg-load rules, not by what the modality is FOR.
This module rates cardio on conditioning criteria, carries the intensity protocols as data, counts the daily walking
dose before any added cardio, and exposes the load cardio puts on lifting. It is not wired into live drafting.

WHAT IT PROVIDES

  * `MODALITIES`: the modality table, every criterion categorical (no point scores, no personal numbers):
    aerobic stimulus, intensity control, impact, lower-body interference, recovery demand, skill, how intensity is set.
  * `conditioning_rating(entry, movement_id)`: the `ratings.conditioning` basis for the exercise library (lane L1's
    contract `{tier, basis, evidence_confidence}`); None for a movement that is not a conditioning modality. It never
    reads the hypertrophy rows: cardio is not judged by the hypertrophy rubric.
  * `PROTOCOLS` + `protocol(name)`: easy recovery, moderate continuous, tempo/threshold, structured intervals,
    progressive endurance, incline/resistance progression. Intensity is RPE + talk test + level/incline/speed on a
    wrist-clock rule, never heart rate. `progress(name, state)`: duration, then frequency, then intensity.
  * `aerobic_plan(...)`: steps first. Daily walking is counted toward the week's aerobic dose before any added
    cardio; structured cardio is added only for a named purpose, never to fill a slot.
  * `cardio_load(...)`: the documented load interface the fatigue model (lane L3) reads.
  * `conditioning_session(request)`: the conditioning-day seam (a 4+1 split needs one): a request in, one session out.

HEART RATE (owner rulings, 2026-10): HR is not effort evidence until a post-2026-10-10 baseline exists, and no
cardio intensity is gated on HR. Nothing this module emits carries an HR target, cap or zone (`hr_target` is
always None, and tests/test_cardio_model_5861.py scans every emitted prescription for one).

EVIDENCE: every rating and rule here is practitioner consensus or a platform-chosen heuristic, labelled as such.
No citation was verified for this module, so none is claimed (`evidence_confidence: consensus`).
"""

from __future__ import annotations

import re
from typing import Any, Iterable

CARDIO_MODEL_VERSION = "cardio-model@0.1.0"

TIERS = ("S", "A", "B", "C", "D")
ORDINAL = {"none": 0, "low": 1, "moderate": 2, "high": 3}
EVIDENCE = "consensus"  # practitioner consensus: no citation verified through scripts/library_evidence_review.py

# ── the modality table (categorical; practitioner consensus) ──────────────────────────────────────────────────
# Each criterion is a category with a stated meaning, not a score:
#   aerobic_stimulus        how far the modality can take a typical adult into moderate-to-vigorous aerobic work
#                           (muscle mass involved, whether intensity can be held)
#   intensity_control       how finely and repeatably intensity can be set and progressed (levels, incline, watts)
#   impact                  ground-reaction / landing load per minute; it matters more at higher body mass
#   lower_body_interference how much the modality competes with lower-body lifting (eccentric and impact loading
#                           of the legs; concentric-dominant cycling is low)
#   recovery_demand         at a moderate dose
#   skill                   technique needed before intensity can be raised safely
_LEVELS = "level (resistance) + cadence"
GRADED = ("aerobic_stimulus", "intensity_control", "impact", "lower_body_interference", "recovery_demand", "skill")


def _m(label: str, equipment: tuple[str, ...], grades: str, expressed_as: str, joint_notes: str, **extra: Any) -> dict[str, Any]:
    """One modality row: `grades` is the six GRADED categories in order, space-separated (stimulus, control, impact,
    interference, recovery, skill). `extra`: menu_machine (the charter's machine key), uses_legs, has_levels,
    readiness_gate (a library gate that must be open)."""
    row: dict[str, Any] = {"label": label, "equipment": equipment, "expressed_as": expressed_as, "joint_notes": joint_notes}
    row.update(dict(zip(GRADED, grades.split())))
    return {"menu_machine": None, "uses_legs": True, "has_levels": False, "readiness_gate": None, **row, **extra}


MODALITIES: dict[str, dict[str, Any]] = {
    # stimulus control impact interference recovery skill
    "recumbent_bike": _m(
        "recumbent bike",
        ("stationary_bike",),
        "high high none low low low",
        _LEVELS,
        "seated with back support, no impact: the knee- and back-sparing choice",
        menu_machine="cycling",
        has_levels=True,
    ),
    "upright_bike": _m(
        "upright bike",
        ("stationary_bike",),
        "high high none low low low",
        _LEVELS,
        "no impact; saddle load and more hip flexion than the recumbent",
        has_levels=True,
    ),
    "treadmill_incline_walk": _m(
        "incline treadmill walk",
        ("treadmill",),
        "high high low low low low",
        "incline % + speed",
        "walking impact only; incline raises the work without running's landing load",
        menu_machine="treadmill",
    ),
    "elliptical": _m(
        "elliptical",
        ("elliptical",),
        "high high low low low low",
        _LEVELS,
        "feet never leave the pedals: weight-bearing without landing",
        menu_machine="elliptical",
        has_levels=True,
    ),
    "rower": _m(
        "rowing machine",
        ("rower",),
        "high high none moderate moderate moderate",
        "split pace + stroke rate (damper fixed)",
        "repeated hip and spinal flexion at the catch; technique fades into lumbar flexion when tired",
        menu_machine="rowing_machine",
    ),
    "air_bike": _m(
        "air bike",
        ("air_bike",),
        "high moderate none low moderate low",
        "watts / RPM (fan resistance rises with effort)",
        "no impact; arms share the work; suits intervals, harder to hold a steady easy pace",
        menu_machine="air_bike",
    ),
    "stair_climber": _m(
        "stair climber / stepmill",
        ("stair_climber",),
        "high high low moderate moderate low",
        "step rate level",
        "knee and hip load per step rises with body mass; concentric-dominant",
        has_levels=True,
    ),
    "ski_erg": _m(
        "SkiErg",
        ("ski_erg",),
        "moderate high none low moderate moderate",
        "split pace + stroke rate",
        "upper-body and trunk dominant; shoulder extension under load",
    ),
    "swimming": _m(
        "swimming", ("pool",), "high low none none low high", "pace per length + RPE", "unloaded; the stimulus depends on stroke skill"
    ),
    "deep_water_running": _m(
        "deep-water running", ("pool",), "moderate low none none low moderate", "cadence + RPE", "unloaded running pattern"
    ),
    "walking": _m(
        "walking (outdoor)",
        ("outdoor",),
        "moderate low low low low low",
        "pace + talk test",
        "the volume base; counted from steps before any added cardio",
    ),
    "hiking": _m(
        "hill walking / hiking",
        ("outdoor",),
        "moderate low moderate moderate moderate low",
        "grade + pace + RPE",
        "descents are eccentric knee loading",
    ),
    "rucking": _m(
        "loaded hiking / rucking",
        ("outdoor",),
        "moderate moderate moderate moderate moderate low",
        "pack load + grade + pace",
        "adds spinal and foot load on top of body mass",
    ),
    "backward_treadmill_walk": _m(
        "backward treadmill walk",
        ("treadmill",),
        "moderate high low low low moderate",
        "incline % + speed",
        "knee-friendly, quad-biased; slow speeds and a handrail first",
    ),
    "step_aerobics": _m(
        "low-impact step aerobics",
        ("plyo_box",),
        "moderate low low moderate low moderate",
        "step height + tempo",
        "low step heights; no jumping",
    ),
    "arm_ergometer": _m(
        "arm ergometer",
        ("arm_ergometer",),
        "low high none none low low",
        _LEVELS,
        "small muscle mass: the option when the legs cannot train",
        uses_legs=False,
        has_levels=True,
    ),
    "sled": _m(
        "sled push / drag",
        ("sled",),
        "high moderate none moderate moderate low",
        "sled load + distance",
        "concentric-only leg work: little soreness, real local quad fatigue",
    ),
    "kettlebell_swing": _m(
        "kettlebell swing intervals",
        ("kettlebell",),
        "moderate moderate none moderate moderate moderate",
        "bell load + reps per minute",
        "a hinge: posterior-chain fatigue overlaps the week's hinges",
    ),
    "battle_rope": _m(
        "battle rope",
        ("battle_rope",),
        "moderate moderate none none moderate low",
        "work:rest + RPE",
        "shoulder endurance; legs free",
        uses_legs=False,
    ),
    "running": _m(
        "running",
        ("treadmill",),
        "high high high high high moderate",
        "speed + incline",
        "landing load scales with body mass; gated by the run on-ramp",
        readiness_gate="charter_running",
    ),
    "jump_rope": _m(
        "jump rope",
        ("jump_rope",),
        "high low high moderate moderate moderate",
        "work:rest + RPE",
        "repeated landings: plyometric-gated",
        readiness_gate="charter_plyometric",
    ),
    "sprint_agility_drills": _m(
        "sprint / agility drills",
        ("outdoor",),
        "high low high high high high",
        "distance + work:rest",
        "athletic skill work, not an aerobic base: decelerations and cuts at body mass",
        readiness_gate="charter_running",
    ),
}

# library movement id -> modality (the rows on file today); anything else is read by title below
LIBRARY_MODALITY = {
    # #5861 L6 reconciled: ONE machine, two library rows. He rides the recumbent and logs it under Hevy's built-in "Cycling"
    # (the menu's knee-sparing recumbent, cardio_note.MACHINES serves `cycling`); L2's `recumbent_bike` is the account's
    # never-logged custom "Recumbent Bike" template for the same machine. Both name the one `recumbent_bike` modality; the
    # menu keeps writing `cycling` (the template his history is on), and the two rate apart only by his N=1 sustainability.
    "cycling": "recumbent_bike",
    "recumbent_bike": "recumbent_bike",
    "treadmill": "treadmill_incline_walk",
    "walking": "walking",
    "elliptical_trainer": "elliptical",
    "rowing_machine": "rower",
    "air_bike": "air_bike",
    "running": "running",
    "jump_rope": "jump_rope",
    "jump_rope_drill": "jump_rope",
    "sled_push": "sled",
    "sled_drag": "sled",
    "kettlebell_swing": "kettlebell_swing",
}
# (title pattern, modality), first match wins; applied only to a conditioning row (target `cardio` or category
# `conditioning`), so "Walking Lunge" or "Seated Row (Machine)" never read as cardio
_TITLE_MODALITY = (
    (r"backward|retro walk", "backward_treadmill_walk"),
    (r"ruck|weighted[- ]vest walk|loaded (hike|hiking|walk)", "rucking"),
    (r"\bhik(e|ing)\b|hill walk|trail walk", "hiking"),
    (r"stair|step ?mill", "stair_climber"),
    (r"ski ?erg", "ski_erg"),
    (r"deep[- ]water|aqua jog|pool run", "deep_water_running"),
    (r"\bswim", "swimming"),
    (r"arm (erg|ergometer|crank|bike)|upper[- ]body (erg|ergometer|bike)", "arm_ergometer"),
    (r"step aerobic|low[- ]impact step", "step_aerobics"),
    (r"air bike|assault bike|fan bike|echo bike", "air_bike"),
    (r"recumbent", "recumbent_bike"),
    (r"upright bike|spin bike|\bbike\b|cycling", "upright_bike"),
    (r"elliptical|cross[- ]trainer", "elliptical"),
    (r"rowing machine|^rower$|indoor row", "rower"),
    (r"incline walk|treadmill", "treadmill_incline_walk"),
    (r"^(outdoor |brisk )?walk(ing)?$", "walking"),
    (r"battle rope", "battle_rope"),
    (r"jump rope|skipping", "jump_rope"),
    (r"^running$|^run$|jog", "running"),
    (r"sprint|shuttle|5-10-5|shuffle|s runs|box drill|high knee|rachet|back ?pedal", "sprint_agility_drills"),
)

# PLATFORM-CHOSEN (heuristic): a modality he has done at least this many times is one he sustains. Read from the
# library's own `history.exposures`, never a clock.
ESTABLISHED_EXPOSURES = 10


def _modality_of(entry: dict[str, Any] | None, movement_id: str | None = None) -> str | None:
    if movement_id in LIBRARY_MODALITY:
        return LIBRARY_MODALITY[str(movement_id)]
    entry = entry or {}
    conditioning = (entry.get("target") or {}).get("primary") == "cardio" or entry.get("category") == "conditioning"
    if not conditioning:
        return None
    title = str(entry.get("title") or movement_id or "").strip().lower()
    for pattern, modality in _TITLE_MODALITY:
        if re.search(pattern, title):
            return modality
    return None


def _sustainability(exposures: Any) -> str:
    try:
        n = int(exposures or 0)
    except (TypeError, ValueError):
        n = 0
    return "established" if n >= ESTABLISHED_EXPOSURES else ("tried" if n > 0 else "untried")


def _base_tier(m: dict[str, Any]) -> tuple[str, str]:
    """The categorical rule (practitioner consensus, not a point score): stimulus and control decide the band, impact caps it."""
    stim, ctrl = m["aerobic_stimulus"], m["intensity_control"]
    if stim == "low":
        tier, why = "D", "low aerobic stimulus (small muscle mass or hard to hold an aerobic intensity)"
    elif stim == "high" and ctrl == "high":
        tier, why = "A", "high aerobic stimulus with fine, repeatable intensity control"
    elif "high" in (stim, ctrl) and "low" not in (stim, ctrl):
        tier, why = "B", f"{stim} aerobic stimulus, {ctrl} intensity control"
    else:
        tier, why = "C", f"{stim} aerobic stimulus, {ctrl} intensity control: hard to dose and progress"
    if m["impact"] == "high" and TIERS.index(tier) < TIERS.index("C"):
        tier, why = "C", why + "; capped at C: high impact (landing load scales with body mass)"
    return tier, why


def _rate(modality: str, exposures: Any = None, joint_tolerance: str = "normal") -> dict[str, Any]:
    m = MODALITIES[modality]
    tier, why = _base_tier(m)
    basis = [
        why,
        f"impact {m['impact']}",
        f"lower-body interference {m['lower_body_interference']}",
        f"recovery demand {m['recovery_demand']}",
    ]
    sustain = _sustainability(exposures)
    # #5861 FIX-PROGRAMMING (red team): the PUBLIC conditioning tier caps at A — a modality's quality, not one person's use.
    # N=1 sustainability (S for HIM: A-level, low impact, ESTABLISHED_EXPOSURES+ sessions of his own) rides the `n1` field
    # only, for the private / N=1 layer; it never moves the public tier or enters the public basis.
    n1 = {"sustainability": sustain, "tier": tier}
    if tier == "A" and m["impact"] in ("none", "low") and sustain == "established":
        n1 = {
            "sustainability": sustain,
            "tier": "S",
            "why": f"A-level, low impact, and a modality he sustains ({ESTABLISHED_EXPOSURES}+ sessions)",
        }
    if joint_tolerance == "low" and m["impact"] == "moderate":
        tier = TIERS[min(len(TIERS) - 1, TIERS.index(tier) + 1)]
        basis.append("one band down: moderate impact while joint tolerance is low")
    if m.get("readiness_gate"):
        basis.append(f"readiness-gated ({m['readiness_gate']}): never auto-programmed while the gate is closed")
    return {"tier": tier, "basis": basis, "evidence_confidence": EVIDENCE, "modality": modality, "n1": n1}


def conditioning_rating(entry: dict[str, Any] | None, movement_id: str | None = None) -> dict[str, Any] | None:
    """The `ratings.conditioning` basis for one library movement (lane L1's contract): `{tier, basis,
    evidence_confidence, modality}`, or None when the movement is not a conditioning modality (never forced into the
    objective). Reads the modality table and the row's own `history.exposures` (N=1 sustainability); never the
    `hypertrophy` rows: cardio is not judged by the hypertrophy rubric. S needs A-level stimulus and control, low
    impact AND a modality he sustains, so it stays rare."""
    modality = _modality_of(entry, movement_id)
    if modality is None:
        return None
    return _rate(modality, ((entry or {}).get("history") or {}).get("exposures"))


# ── protocols (data, not exercises) ──────────────────────────────────────────────────────────────────────────
# `kind` is the charter cardio_menu block whose RPE band, talk test and minutes the protocol reads at call time
# (no menu number is restated here). `domain`: easy | moderate | threshold | vigorous.
PROTOCOLS: dict[str, dict[str, Any]] = {
    "easy_recovery": {
        "label": "easy recovery aerobic",
        "kind": "easy",
        "walk_kind": "incline_treadmill_walk",
        "domain": "easy",
        "clock": "one level (or one speed and incline) the whole block",
        "frequency_cap": None,
        "priority": 1,
        "purpose": "recovery and volume; daily walking usually covers it",
    },
    "moderate_continuous": {
        "label": "moderate continuous",
        "kind": "easy",
        "walk_kind": "incline_treadmill_walk",
        "domain": "moderate",
        "rpe_rule": "the top of the easy band",
        "clock": "one level the whole block",
        "frequency_cap": None,
        "priority": 2,
        "purpose": "aerobic base above walking pace",
    },
    "progressive_endurance": {
        "label": "progressive endurance",
        "kind": "easy",
        "walk_kind": "incline_treadmill_walk",
        "domain": "easy",
        "clock": "one level; the duration is what progresses",
        "frequency_cap": None,
        "priority": 3,
        "duration_cap": "none_in_the_gym",
        "purpose": "a longer easy session (walk or hike); the gym block stays under its cap",
    },
    "incline_resistance_progression": {
        "label": "incline / resistance progression",
        "kind": "hills",
        "walk_kind": "hills",
        "domain": "threshold",
        "clock": "+1 every 2 min from T1, back down from T2 (cardio_menu.HILL_STEP_MINUTES)",
        "frequency_cap": "conditioning",
        "priority": 4,
        "purpose": "more work at the same talk test by grade or resistance, not speed",
    },
    "tempo_threshold": {
        "label": "tempo / threshold",
        "kind": "tempo",
        "walk_kind": None,
        "domain": "threshold",
        "clock": "one level over steady (cardio_menu.TEMPO_LEVEL_STEP), talk checks every 10 min",
        "frequency_cap": "conditioning",
        "priority": 5,
        "purpose": "the threshold domain walking does not reach",
    },
    "structured_intervals": {
        "label": "structured intervals",
        "kind": "intervals",
        "walk_kind": None,
        "domain": "vigorous",
        # OWNER RULING 2026-11-08 (#5428, re-grade #6): the hard minutes sit TWO levels over his steady level; the easy
        # minutes ARE the steady level; the escape is one level. hevy_note_grammar.INTERVAL_HARD_STEP reads it HERE.
        "levels": {"hard_over_steady": 2, "easy_over_steady": 0, "escape": 1},
        "clock": "N min at steady + 2 from min a, b, c; else steady (the menu's efforts and work:easy minutes)",
        "frequency_cap": "conditioning",
        "priority": 6,
        "intensity_step": None,
        "purpose": "the vigorous domain; never prioritised by default: needs a purpose and good recovery",
    },
}
MAX_INTENSITY_PROTOCOLS: tuple[str, ...] = ()  # no protocol prescribes all-out work; the hardest is RPE 8 on the hard minutes
PROGRESSION_ORDER = ("duration", "frequency", "intensity")
# PLATFORM-CHOSEN (heuristic): a duration step on the owner's 2/5/10-minute watch grid; the sessions held at a dose
# before a step reuse the menu's own `HELD_WALKS_FOR_STEP`; progression waits while fewer than this share of the
# prescribed sessions were done (a dose he is not doing is not one to raise).
DURATION_STEP_MIN = 5
ADHERENCE_FLOOR = 0.8
DOMAINS_BY_PROTOCOL = {name: p["domain"] for name, p in PROTOCOLS.items()}


def protocol(name: str) -> dict[str, Any]:
    """One protocol resolved against the live charter menu (RPE band, talk words, minutes, interval set) — the menu's
    numbers are read through `cardio_menu`, never restated. `hr_target` is always None."""
    from training import cardio_menu

    p = PROTOCOLS[name]
    kind = p["kind"]
    band = cardio_menu.wire_band(kind) or (0, 0)
    if name == "moderate_continuous":
        band = (band[1], band[1])
    out = {
        **p,
        "name": name,
        "rpe": [int(band[0]), int(band[1])],
        "talk_test": cardio_menu.talk_word(kind),
        "minutes": cardio_menu.block_minutes(kind),
        "progression_order": list(PROGRESSION_ORDER),
        "hr_target": None,
    }
    if kind == "intervals":
        efforts, work, easy = cardio_menu.interval_set()
        out["interval_set"] = {"efforts": efforts, "work_min": work, "easy_min": easy}
    return out


def _frequency_cap(name: str) -> int | None:
    from training import cardio_menu

    return cardio_menu.conditioning_per_wk() if PROTOCOLS[name]["frequency_cap"] == "conditioning" else None


def _duration_cap(name: str) -> int | None:
    from training import cardio_menu

    return None if PROTOCOLS[name].get("duration_cap") == "none_in_the_gym" else cardio_menu.cardio_cap_minutes()


def _hold_reason(state: dict[str, Any]) -> tuple[str, str] | None:
    """(action, reason) when something other than the dose decides; None when progression may be considered."""
    from training import cardio_menu

    if state.get("symptoms"):
        return "stop_and_review", "symptoms during exercise: stop the block, no progression until they are reviewed"
    if state.get("tolerance") == "flag":
        return "hold_change_modality", "a joint or lower-leg flag: hold the dose on a lower-impact modality"
    if state.get("recovery") == "poor":
        return "step_back", "recovery is poor: one duration step back"
    adherence = state.get("adherence")
    if adherence is not None and float(adherence) < ADHERENCE_FLOOR:
        return "hold", f"done {float(adherence):.0%} of the prescribed sessions: make the current dose happen first"
    if state.get("rpe") is None:
        return "hold", "effort not logged: an unlogged RPE is not evidence (#5505)"
    if state.get("rpe") == "over":
        return "hold", "the logged RPE is over the band: hold until it sits inside"
    held = int(state.get("held_sessions") or 0)
    if held < cardio_menu.HELD_WALKS_FOR_STEP:
        return "hold", f"{held} session(s) at this dose; a step needs {cardio_menu.HELD_WALKS_FOR_STEP}"
    return None


def progress(name: str, state: dict[str, Any]) -> dict[str, Any]:
    """The next step for a protocol, by its stated rule: symptoms, tolerance, recovery and adherence decide first; then
    duration, then frequency, then intensity (one level, the menu's `cardio_progression` raise). `state`: `{minutes,
    sessions_per_wk, held_sessions, rpe: under|in|over|None, recovery: ok|poor, tolerance: ok|flag, symptoms: bool,
    adherence: 0..1|None}`. Structured intervals never step intensity on their own: the hard level rides the steady
    level. A proposal only: a dose above a charter value is flagged `owner_ruling_needed`."""
    minutes = int(state.get("minutes") or 0)
    per_wk = int(state.get("sessions_per_wk") or 0)
    out: dict[str, Any] = {"protocol": name, "minutes": minutes, "sessions_per_wk": per_wk, "hr_target": None}
    held = _hold_reason(state)
    if held:
        action, reason = held
        if action == "step_back":
            out["minutes"] = max(DURATION_STEP_MIN, minutes - DURATION_STEP_MIN)
        return {**out, "action": action, "reason": reason}
    dur_cap, freq_cap = _duration_cap(name), _frequency_cap(name)
    if dur_cap is None or minutes + DURATION_STEP_MIN <= dur_cap:
        return {**out, "action": "add_duration", "minutes": minutes + DURATION_STEP_MIN, "reason": "duration first"}
    if freq_cap is not None and per_wk < freq_cap:
        return {**out, "action": "add_session", "sessions_per_wk": per_wk + 1, "reason": "duration at its cap: frequency next"}
    if "intensity_step" in PROTOCOLS[name] and PROTOCOLS[name]["intensity_step"] is None:
        return {**out, "action": "hold", "reason": "intervals ride the steady level: the hard level rises when steady does"}
    return {**out, "action": "add_intensity", "level_step": 1, "reason": "duration and frequency at their caps: one level, same RPE"}


# ── steps first ──────────────────────────────────────────────────────────────────────────────────────────────
# HEURISTIC (practitioner consensus, labelled): about 100 steps a minute marks moderate-intensity walking for most
# adults; the first INCIDENTAL_STEPS of a day are treated as incidental living movement, not aerobic exercise. A walk
# with recorded minutes replaces the estimate. The weekly moderate range is the public-health guideline band.
STEPS_PER_MODERATE_MIN = 100
INCIDENTAL_STEPS = 5000
WEEKLY_MODERATE_MIN = (150, 300)
PURPOSES = ("intensity_domain", "fitness_test_progression", "conditioning_goal")


def _walking_dose(steps_by_day: dict[str, Any] | None, walk_minutes_by_day: dict[str, Any] | None = None) -> dict[str, Any]:
    days = sorted(set(steps_by_day or {}) | set(walk_minutes_by_day or {}))
    if not days:
        return {"days": 0, "moderate_min_per_wk": 0, "source": "none", "basis": ["no steps or walks read"]}
    total, recorded = 0.0, 0
    for d in days:
        walk = (walk_minutes_by_day or {}).get(d)
        if walk is not None:
            total += float(walk)
            recorded += 1
        else:
            total += max(0.0, float((steps_by_day or {}).get(d) or 0) - INCIDENTAL_STEPS) / STEPS_PER_MODERATE_MIN
    per_wk = round(total / len(days) * 7)
    source = "walk_minutes" if recorded == len(days) else ("steps_heuristic" if not recorded else "mixed")
    return {
        "days": len(days),
        "moderate_min_per_wk": per_wk,
        "source": source,
        "basis": [
            f"heuristic: steps over {INCIDENTAL_STEPS} a day at {STEPS_PER_MODERATE_MIN} steps a minute, unless a walk's minutes are recorded",
        ],
    }


def aerobic_plan(
    steps_by_day: dict[str, Any] | None,
    *,
    walk_minutes_by_day: dict[str, Any] | None = None,
    recent_protocols: Iterable[str] = (),
    purposes: Iterable[str] = (),
    recovery: str = "ok",
) -> dict[str, Any]:
    """Steps first. The week's walking dose (`_walking_dose`) is counted toward the aerobic volume BEFORE any added
    cardio; structured cardio is added only for a named purpose (`PURPOSES`): an intensity domain the week does not
    reach, a fitness-test progression, a conditioning goal. No purpose, no addition: cardio never fills a slot. Hard
    additions stay inside the menu's conditioning sessions a week and never land on poor recovery."""
    from training import cardio_menu

    unknown = [p for p in purposes if p not in PURPOSES]
    if unknown:
        raise ValueError(f"unknown purpose(s) {unknown}; known: {PURPOSES}")
    walking = _walking_dose(steps_by_day, walk_minutes_by_day)
    recent = list(recent_protocols)
    covered = {DOMAINS_BY_PROTOCOL[p] for p in recent if p in DOMAINS_BY_PROTOCOL}
    volume_ok = walking["moderate_min_per_wk"] >= WEEKLY_MODERATE_MIN[0]
    if volume_ok:
        covered |= {"easy", "moderate"}
    hard_room = max(
        0, cardio_menu.conditioning_per_wk() - sum(1 for p in recent if DOMAINS_BY_PROTOCOL.get(p) in ("threshold", "vigorous"))
    )
    additions: list[dict[str, Any]] = []
    declined: list[str] = []
    if not volume_ok:
        additions.append({"what": "walking", "purpose": "weekly_aerobic_volume", "why": "raise daily steps before any added cardio"})
    wanted: list[tuple[str, str]] = []
    for purpose in purposes:
        if purpose == "intensity_domain" and "threshold" not in covered:
            wanted.append(("tempo_threshold", purpose))
        elif purpose == "intensity_domain" and "vigorous" not in covered:
            wanted.append(("structured_intervals", purpose))
        elif purpose == "fitness_test_progression" and "threshold" not in covered:
            wanted.append(("tempo_threshold", purpose))
        elif purpose == "conditioning_goal":
            wanted += [
                (p, purpose) for p, d in (("tempo_threshold", "threshold"), ("structured_intervals", "vigorous")) if d not in covered
            ]
        else:
            declined.append(f"{purpose}: the week already reaches that domain")
    for name, purpose in wanted:
        if any(a.get("protocol") == name for a in additions):
            continue
        if recovery == "poor":
            declined.append(f"{name} for {purpose}: recovery is poor, no hard work added")
        elif hard_room <= 0:
            declined.append(f"{name} for {purpose}: the week's conditioning sessions are full")
        else:
            hard_room -= 1
            additions.append({"what": "structured_cardio", "protocol": name, "purpose": purpose, "why": PROTOCOLS[name]["purpose"]})
    if not list(purposes):
        declined.append("no purpose named: no structured cardio added to fill a slot")
    return {
        "version": CARDIO_MODEL_VERSION,
        "walking": walking,
        "weekly_target_min": list(WEEKLY_MODERATE_MIN),
        "volume_covered": volume_ok,
        "domains_covered": sorted(covered),
        "additions": additions,
        "declined": declined,
    }


# ── the load interface (lane L3's fatigue model reads it) ─────────────────────────────────────────────────────
# HEURISTIC: session-RPE load (minutes x RPE, arbitrary units) is the practitioner-consensus internal-load measure; the
# lower-body share weights it by the modality's interference category (none 0, low 1/3, moderate 2/3, high 1: an
# ordinal weighting, not a measured ratio). Walking is reported apart at an assumed RPE of WALK_RPE.
WALK_RPE = 3
HARD_RPE = 7


def cardio_load(sessions: Iterable[dict[str, Any]], *, steps_by_day: dict[str, Any] | None = None) -> dict[str, Any]:
    """The load a window's cardio puts on recovery and on lower-body lifting. Each session: `{modality | movement_id,
    minutes, rpe?, protocol?}`; an unlogged RPE reads the protocol's band midpoint (`rpe_source: protocol_band`), and
    with neither the minutes are counted apart (`unknown_effort_minutes`), never guessed. Returns arbitrary units:
    `session_rpe_au` (minutes x RPE), `lower_body_au` (the same weighted by lower-body interference), `impact_minutes`
    (moderate or high impact), `hard_minutes` (RPE >= HARD_RPE), `walking` (steps first, `_walking_dose`, with its own
    `walking_au`). Heart rate is never read."""
    total = srpe = lower = 0.0
    impact = hard = unknown = 0.0
    rows = []
    for s in sessions or []:
        modality = s.get("modality") if s.get("modality") in MODALITIES else _modality_of(s.get("entry"), s.get("movement_id"))
        minutes = float(s.get("minutes") or 0)
        rpe, source = s.get("rpe"), "logged"
        if rpe is None and s.get("protocol") in PROTOCOLS:
            lo, hi = protocol(str(s["protocol"]))["rpe"]
            rpe, source = (lo + hi) / 2, "protocol_band"
        m = MODALITIES.get(str(modality)) or {}
        weight = ORDINAL.get(m.get("lower_body_interference", "moderate"), 2) / 3
        total += minutes
        impact += minutes if m.get("impact") in ("moderate", "high") else 0
        if rpe is None:
            unknown += minutes
            rows.append({"modality": modality, "minutes": minutes, "rpe": None, "rpe_source": None})
            continue
        srpe += minutes * float(rpe)
        lower += minutes * float(rpe) * weight
        hard += minutes if float(rpe) >= HARD_RPE else 0
        rows.append({"modality": modality, "minutes": minutes, "rpe": float(rpe), "rpe_source": source})
    walking = _walking_dose(steps_by_day) if steps_by_day else None
    if walking:
        walking["walking_au"] = round(walking["moderate_min_per_wk"] / 7 * walking["days"] * WALK_RPE)
    return {
        "version": CARDIO_MODEL_VERSION,
        "minutes": round(total),
        "session_rpe_au": round(srpe),
        "lower_body_au": round(lower),
        "impact_minutes": round(impact),
        "hard_minutes": round(hard),
        "unknown_effort_minutes": round(unknown),
        "walking": walking,
        "by_session": rows,
        "hr_used": False,
        "basis": ["heuristic: session-RPE load; lower-body share by the interference category; walking apart at RPE 3"],
    }


# ── the conditioning-day seam ─────────────────────────────────────────────────────────────────────────────────
TREADMILL_WALKS = ("treadmill_incline_walk", "backward_treadmill_walk")
# the machines the live menu already serves; "outdoor" (walking, hiking, rucking, drills) is opted into by the request
DEFAULT_EQUIPMENT = ("stationary_bike", "treadmill", "elliptical", "rower")


def _excluded(key: str, m: dict[str, Any], name: str, req: dict[str, Any], equipment: set[str]) -> str | None:
    if m["equipment"] and not set(m["equipment"]) & equipment:
        return f"needs {' or '.join(m['equipment'])}, not available"
    if m.get("readiness_gate") and m["readiness_gate"] not in set(req.get("gates_open") or ()):
        return f"readiness-gated ({m['readiness_gate']} is closed)"
    if req.get("legs_available") is False and m["uses_legs"]:
        return "the legs are not available today"
    if req.get("joint_tolerance") == "low" and m["impact"] == "high":
        return "high impact while joint tolerance is low"
    if key in TREADMILL_WALKS and PROTOCOLS[name]["walk_kind"] is None:
        return f"the menu runs {PROTOCOLS[name]['kind']} off the treadmill (cardio_menu.blocks.{PROTOCOLS[name]['kind']}.machines)"
    if name == "structured_intervals" and m["intensity_control"] == "low":
        return "intervals need a repeatable intensity setting"
    if name == "incline_resistance_progression" and not (m["has_levels"] or "incline" in m["expressed_as"] or "load" in m["expressed_as"]):
        return "no grade or resistance to progress"
    return None


def _ranked(name: str, req: dict[str, Any]) -> tuple[list[tuple[tuple[Any, ...], str, dict[str, Any]]], dict[str, str]]:
    equipment = set(req.get("equipment") or DEFAULT_EQUIPMENT)
    history = req.get("history") or {}
    spare_legs = bool(req.get("after_heavy_lower")) or req.get("joint_tolerance") == "low"
    ranked, excluded = [], {}
    for key, m in MODALITIES.items():
        why = _excluded(key, m, name, req, equipment)
        if why:
            excluded[key] = why
            continue
        rating = _rate(key, history.get(key), str(req.get("joint_tolerance") or "normal"))
        # legs to spare (the day after heavy lower, or low joint tolerance): the leg cost decides before the tier, so a
        # top-rated weight-bearing modality never beats a seated one on a day the legs need sparing
        sort = (
            ORDINAL[m["lower_body_interference"]] + ORDINAL[m["impact"]] if spare_legs else 0,
            TIERS.index(rating["tier"]),
            -int(history.get(key) or 0),
            key,
        )
        ranked.append((sort, key, rating))
    ranked.sort(key=lambda r: r[0])
    return ranked, excluded


def _clock_rule(p: dict[str, Any], modality: str, minutes: int, steady: int | None, incline: float | None) -> dict[str, Any]:
    """The wrist-clock rule (owner, 2026-10-25): one line on the 2/5/10-minute grid, at most three levels, built by the
    live note grammar (`cardio_note.clock_shape`, `wrist_clock.render`) so his own shapes parse back."""
    from training import cardio_menu, cardio_note, wrist_clock

    m = MODALITIES[modality]
    walk = modality in TREADMILL_WALKS
    kind = p["walk_kind"] if walk and p.get("walk_kind") else p["kind"]
    if not (m["has_levels"] or walk):
        dose: dict[str, Any] = {}
    elif walk:
        start = (cardio_menu.block("incline_treadmill_walk").get("starting_dose") or {}).get("incline_pct") or [0]
        dose = {"incline_pct": incline if incline is not None else float(start[0])}
    else:
        level = None if steady is None else steady + (cardio_menu.TEMPO_LEVEL_STEP if kind == "tempo" else 0)
        dose = {"level": level, "steady": steady}
    clauses, unit, check = cardio_note.clock_shape(kind, minutes, dose, walk=walk)
    rendered = (
        wrist_clock.render([c for c in clauses if "start" in c], unit) if dose and (dose.get("level") or dose.get("incline_pct")) else None
    )
    if rendered is None and kind == "intervals" and check:
        rendered, check = check, None  # no level to name: the phone line ("2 min hard from min 6, 10, …; else easy")
    rule = rendered or f"{minutes} min, {p['talk_test']}"
    return {"rule": rule, "phone_line": check, "set_by": m["expressed_as"]}


def conditioning_session(request: dict[str, Any]) -> dict[str, Any]:
    """The conditioning-day seam: a session request in, one session out (a 4+1 split needs a conditioning day; nothing
    live calls this). `request`: `{protocol, minutes_available?, equipment?, joint_tolerance: normal|low,
    legs_available?, after_heavy_lower?, history: {modality: sessions}, steady_level?, incline_pct?, gates_open?,
    progression_state?}`. The modality is the best-rated one that is possible today (equipment, gates, legs, joint
    tolerance), lower-body interference first when the legs need sparing; with none possible the answer says so rather
    than prescribe the impossible. Intensity is RPE + talk test + a wrist-clock rule; `hr_target` is always None."""
    name = str(request.get("protocol") or "")
    if name not in PROTOCOLS:
        raise ValueError(f"unknown protocol {name!r}; known: {sorted(PROTOCOLS)}")
    p = protocol(name)
    ranked, excluded = _ranked(name, request)
    base = {"version": CARDIO_MODEL_VERSION, "protocol": name, "hr_target": None, "excluded": excluded}
    if not ranked:
        return {**base, "modality": None, "why": [f"no available modality serves {p['label']} today"]}
    _sort, modality, rating = ranked[0]
    available = request.get("minutes_available")
    minutes = min(int(available), int(p["minutes"])) if available else int(p["minutes"])
    clock = _clock_rule(p, modality, minutes, request.get("steady_level"), request.get("incline_pct"))
    out = {
        **base,
        "modality": modality,
        "label": MODALITIES[modality]["label"],
        "minutes": minutes,
        "intensity": {"rpe": p["rpe"], "talk_test": p["talk_test"], "expressed_as": MODALITIES[modality]["expressed_as"]},
        "clock": clock,
        "rating": rating,
        "alternatives": [k for _s, k, _r in ranked[1:4]],
        "why": [p["purpose"], f"{MODALITIES[modality]['label']}: {rating['tier']} for conditioning ({rating['basis'][0]})"],
    }
    if request.get("progression_state"):
        out["next"] = progress(name, {**request["progression_state"], "minutes": minutes})
    return out
