"""
recovery_authoring.py — Stage 2: recovery-adaptive night-before authoring.

Routines are authored the night before; Matthew trains the next morning
(wake → car → gym) with ZERO platform interaction possible. So the routine in
his hand must be (a) authored only on complete data, and (b) self-adapting at
5am off a wrist-visible Whoop recovery band, with a safe default.

This module is the DETERMINISTIC CORE — pure functions, stdlib only, NO mcp.config
/ boto3 import, so it unit-tests without env vars or AWS. The I/O that gathers
volume / recovery / workout-history lives in tools_hevy_routine.py and feeds these
functions. Design brief: docs/SPEC_RECOVERY_ADAPTIVE_AUTHORING_2026-06-21.md.

Non-negotiables encoded here (brief §2):
  1. Author tier-agnostic — the routine carries GREEN/YELLOW/RED branches; the
     morning selects one. No single recovery_tier is baked into the prescription.
  2. Safe default — absent/ambiguous morning signal resolves to YELLOW.
  3. Subtract-only — GREEN is the authored ceiling; YELLOW/RED are defined
     subtractions; nothing lets him exceed the GREEN ceiling on the day.
  4. Freshness-gated — author only when volume/recovery/recent-workout inputs
     cover the latest ingested session (completeness, not max-date recency).
"""

from __future__ import annotations

from datetime import datetime, timedelta

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
    ]
    if training_context and training_context.get("reasons"):
        lines.append("Today: " + "; ".join(training_context["reasons"]) + ".")
    if inputs_current_through:
        lines.append(f"inputs_current_through: {inputs_current_through}")
    return "\n".join(lines)
