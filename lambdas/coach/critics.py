"""critics.py — four adversarial reviewers holding DISJOINT evidence (#3752, epic #3742).

WHY THIS EXISTS

The debrief "board" was one model role-playing six personas in one pass. A single pass
cannot disagree with itself about evidence it was handed all at once. The owner's bar is a
genuine red team: *as if ten elite experts reviewed all of that data and aligned on
tomorrow's workout*. Critics that hold DIFFERENT data and must name a NUMBER can disagree;
a persona list cannot.

THE FOUR CRITICS AND WHAT EACH ONE HOLDS

  muscle_defense       anchor-lift strength trend + protein vs the floor
  joints_tendons       pain flags per movement, novelty (days since), the loaded-lifting streak
                       (rest-day ask) beside the active-day streak (context only, #4067)
  rate_advocate        the owner's redlines + which tripwires are CLEAR — argues for MORE
  blueprint_historian  the weight-band reference + the #3717 attestation, LABELLED

`test_the_four_packets_are_pairwise_disjoint` holds the packets apart: a metric name may
appear in ONE packet. That is the whole mechanism. Two critics reading the same number
agree by construction; two reading different numbers have to argue.

THE RULE THAT MAKES A CRITIC WORTH READING (#3851)

A critic that always objects is a critic nobody reads. So the model is BOUNDED by the
deterministic layer (ADR-105: computation before any LLM verdict):

  * every packet is first evaluated deterministically — redline violations and tripped
    tripwires are computed from the numbers, not asked for;
  * a deterministic `veto` stands whatever the model says; a deterministic `change` stands;
  * the model may ADD an objection only where the packet already carries a flag on the
    metric it cites — it can escalate one step (info → change, change → veto), never from
    nothing. On a clean packet — no flags — a model veto is DISCARDED and recorded as such.
    That is the negative control: feed a clean draft and no critic can invent an objection.

A veto blocks the Hevy commit (`veto_reason`). A change is APPLIED to the draft
(`apply_changes`) and the revised draft is re-checked deterministically (`recheck`) before
anyone reads a verdict off it.

THE OWNER OVERRIDE (#4076)

The owner may overrule ONE vetoing critic in his own words (`coach.critic_overrides`). The
verdict stays `veto` on the record and carries `owner_override`; `standing_vetoes` /
`veto_reason` stop counting it; every other verdict, veto or change, is untouched.

WHERE THE REDLINES COME FROM

Two sources, and the provenance rides on every flag:
  * `training.owner_redlines` (#3753) — ACTIVE since the owner approved v3 on 2026-09-21; its
    tripwires produce `change`, never `veto`, whenever `ACTIVE` is False (a plan may not be
    refused on a rule he has not signed);
  * the owner's private calibration doc, §4 "NEVER (regardless of motivation)" — his own
    words, edited by him, so these ARE vetoes. They are paraphrased here, not quoted: the
    doc is owner-private (#3043) and this file ships in a public repo.

This module is PURE. Every reader is injected by `mcp/tools_plan.py`; the only I/O it
knows about is the `invoke` callable handed to `run_critics`, which is the Bedrock
chokepoint (ADR-062) or a test double.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from training import owner_redlines, training_context_registry, training_streaks

CRITICS_VERSION = "critics@1.4.0"  # #4149: every numeric change computed in code; critic loads clamped to the subtract-only floor
CRITIC_IDS = ("muscle_defense", "joints_tendons", "rate_advocate", "blueprint_historian")
VERDICTS = ("approve", "change", "veto")
_SEVERITY = {"info": 0, "change": 1, "veto": 2}

HAIKU_MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 240  # one JSON object with one ≤200-char sentence; measured, not guessed: ~120 tok typical
BUDGET_FEATURE = "plan_critics"

# ── owner calibration doc §4 — paraphrased, cited by section, never quoted ──────────
# INTERPRETATION RECORDED (not a ruling): "cold" is read as "neither axial pattern trained in
# the last CALIBRATION_COLD_DAYS days"; "heavy" as a working set at or above AXIAL_HEAVY_LBS
# (a loaded bar). Both are assumptions this lane made to make the rule computable; the owner
# can tighten either without touching the critic logic.
NOVEL_AGAIN_DAYS = 28
# #4149 — THE DETERMINISM RULING. On 2026-09-23 the joints critic answered one signal
# (squat_barbell days_since_movement 98/99) three ways: sets 3->2, load -25 %, load -13 %; the
# model chose the number. A days-since signal now moves VOLUME, computed here, never LOAD: the
# v0.3 entry ramp (`load_ramp.v03_floor` — layoff discount x the week's ramp) already prices the
# layoff into the load and the commit gate holds that load as a floor, so a critic load cut on
# the same signal double-discounts and is uncommittable by construction (the -25 % run was
# refused at 36 kg against a 48 kg floor). INTERPRETATION RECORDED (not an owner ruling): a
# novel-again pattern's session 1 carries at most NOVEL_AGAIN_MAX_WORKING_SETS working sets
# (one of the model's own three answers, the only committable one). The owner can move the
# number without touching the logic.
NOVEL_AGAIN_MAX_WORKING_SETS = 2
CALIBRATION_COLD_DAYS = 14
AXIAL_HEAVY_LBS = 135.0
_AXIAL_SQUAT = ("squat", "front squat", "back squat", "hack squat", "leg press", "goblet")
_AXIAL_HINGE = ("deadlift", "rdl", "romanian", "good morning", "hip thrust", "rack pull", "trap bar", "clean", "snatch")
_FAILURE_WORDS = ("amrap", "to failure", "max out", "max-out", "1rm", "rep max")

CALIBRATION_REDLINES = {
    "failure_on_novel_session_1": "no max-out / to-failure work on session 1 of a novel-again pattern (owner calibration doc §4)",
    "two_heavy_axial_cold": "no two heavy axial patterns cold in one session (owner calibration doc §4)",
    "pain_flag_loaded": "a movement carrying a pain flag on a named site is substituted, not loaded (owner calibration doc §4; tripwire pain_flag_named_site)",
}

# The `change` grammar, MAX_ADDED_SETS, the lb/kg factor and the label live in `critics_apply`
# (#4149 extraction) and are re-exported here unchanged.
from coach.critics_apply import (  # noqa: E402,F401
    _LBS_PER_KG,
    CHANGE_FIELD_RE,
    FLOOR_TOLERANCE_KG,
    MAX_ADDED_SETS,
    _label,
    apply_changes,
)

# #4149: the advocate's escalation is a code-computed quantum, not a model-chosen total — one
# set per pass (INTERPRETATION RECORDED: the smallest step; MAX_ADDED_SETS stays the bound).
ADVOCATE_ADD_SETS = 1


# ── the draft, summarised the same way for every critic ───────────────────────────────
def draft_summary(ir: Any) -> dict[str, Any]:
    """What every critic sees of the plan — the SAME view, so the packets are the only
    thing that differs between them."""
    exercises = []
    for i, ex in enumerate(getattr(ir, "exercises", None) or []):
        sets = getattr(ex, "sets", None) or []
        working = [s for s in sets if (getattr(s, "type", "normal") or "normal") != "warmup"]
        weights = [float(s.weight_kg) * _LBS_PER_KG for s in working if getattr(s, "weight_kg", None) is not None]
        reps = [int(s.reps) for s in working if getattr(s, "reps", None) is not None]
        notes = (getattr(ex, "notes", "") or "").lower()
        label = _label(ex)
        exercises.append(
            {
                "idx": i,
                "movement_key": getattr(ex, "movement_key", ""),
                "label": label,
                "n_sets": len(sets),
                "n_working_sets": len(working),
                "top_weight_lbs": round(max(weights), 1) if weights else None,
                "top_reps": max(reps) if reps else None,
                "to_failure": any((getattr(s, "type", "") or "") == "failure" for s in sets) or any(w in notes for w in _FAILURE_WORDS),
                "axial": _axial_pattern(label) or _axial_pattern(getattr(ex, "movement_key", "")),
            }
        )
    return {
        "routine_id": getattr(ir, "routine_id", None),
        "target_date": getattr(ir, "target_date", None),
        "archetype": getattr(ir, "archetype", None),
        "total_sets": sum(e["n_sets"] for e in exercises),
        "exercises": exercises,
    }


def _axial_pattern(name: str) -> str | None:
    n = (name or "").lower().replace("_", " ")
    if any(k in n for k in _AXIAL_SQUAT):
        return "squat"
    if any(k in n for k in _AXIAL_HINGE):
        return "hinge"
    return None


# ── packets: one per critic, pairwise-disjoint metric names ───────────────────────────
def _flag(
    metric: str,
    severity: str,
    reason: str,
    *,
    provenance: str,
    field: str | None = None,
    to: Any = None,
    governed: bool = False,
) -> dict[str, Any]:
    """One packet flag. `field`/`to` are computed HERE, never by the model (#4149): on a
    `change` flag they are the change; on an `info` flag they are what a grounded model
    escalation applies. `governed` marks a signal a code rule already answers in full — the
    model may not escalate it at all, so its verdict cannot vary with the sample."""
    return {
        "metric": metric,
        "severity": severity,
        "reason": reason,
        "provenance": provenance,
        "field": field,
        "to": to,
        "governed": governed,
    }


# #4112: extracted to the cohesive sibling `critics_muscle_defense` (this module was at its
# size ceiling — docs/ENGINEERING_STANDARDS.md §2, the #2610/#2604 precedent). Behavior is
# unchanged; every caller still reads `critics.build_muscle_defense_packet`.
from coach.critics_muscle_defense import build_muscle_defense_packet  # noqa: E402,F401


def build_joints_packet(
    draft: dict[str, Any],
    *,
    pain_by_idx: dict[int, dict[str, Any]] | None,
    days_since_by_idx: dict[int, int | None] | None,
    active_day_streak: int | None,
    loaded_lifting_streak: int | None,
    pain_layer_status: str | None,
    dismissals: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Pain flags on the draft's movements, novelty, and where he is in the week.

    Carries the ONLY vetoes a critic can issue without the owner having signed #3753: the
    calibration doc's own §4 rules, which are his.

    `dismissals` (#4036) are the owner-dismissal records the caller read from
    `USER#matthew#SOURCE#training_constraints`. A flag instance he has dismissed does NOT
    produce the `pain_flag_loaded` veto — the §4 redline is his rule, and so is the
    dismissal; the packet still carries the flag and says who overrode it, because the
    critic must argue from what happened, not from a cleaned-up version of it. A note dated
    AFTER the dismissal re-arms the veto on its own (`training_context_registry`, one rule,
    shared with `plan_engine`)."""
    # #4067: TWO streaks, both named. The rest-day ask keys on the LOADED one alone — the old
    # single `consecutive_training_days` counted Engine (cardio-only) and walk days, read 16
    # against a loaded streak of 4 and asked for rest. The active streak is context, carried in
    # `numbers` and deliberately never flagged: a flag is the model's escalation handle.
    numbers: dict[str, Any] = {
        "active_day_streak": active_day_streak,
        "loaded_lifting_streak": loaded_lifting_streak,
        "pain_layer_status": pain_layer_status,
    }
    flags: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []
    unknown: list[str] = []
    layer_ok = pain_layer_status not in (None, "dark", "unknown")
    if active_day_streak is None:
        unknown.append("active_day_streak")
    streak_flag = training_streaks.loaded_streak_flag(loaded_lifting_streak)
    if loaded_lifting_streak is None:
        unknown.append("loaded_lifting_streak")
    elif streak_flag:
        # #4149: the upper-tail line is an escalation handle; if the model takes it, the cut is
        # the owner's own signed deload (`lifting_sessions_per_wk.deload.sets_pct`, loads held),
        # computed here — live, the model had picked 18, 14 and 2 total sets for one signal.
        esc = {} if streak_flag[0] != "info" else {"field": "session.total_sets", "to": _deload_total_sets(draft)}
        flags.append(_flag("loaded_lifting_streak", *streak_flag, provenance=training_streaks.CALIBRATION["provenance"], **esc))
    heavy_axial_cold: list[dict[str, Any]] = []
    dismissed_rows: list[dict[str, Any]] = []  # #4036 — every owner dismissal this packet met
    for ex in draft["exercises"]:
        i = ex["idx"]
        ds = (days_since_by_idx or {}).get(i, None)
        dk = f"days_since_movement[{i}]"
        numbers[dk] = ds
        novel = ds is None or ds >= NOVEL_AGAIN_DAYS
        if ds is None:
            flags.append(
                _flag(dk, "info", f"{ex['label']}: no performed history in the window — treated as novel-again", provenance="owner-history")
            )
        elif novel:
            flags.append(_novel_again_flag(ex, dk, ds))
        if novel and ex.get("to_failure"):
            violations.append(
                {
                    "redline": "failure_on_novel_session_1",
                    "metric": dk,
                    "reason": f"{ex['label']}: to-failure work on a novel-again pattern — {CALIBRATION_REDLINES['failure_on_novel_session_1']}",
                    "field": f"exercises[{i}].drop",
                    "to": True,
                }
            )
        pk = f"pain_flag[{i}]"
        pain = (pain_by_idx or {}).get(i)
        if not layer_ok or pain is None or pain.get("pain_flag_any") is None:
            numbers[pk] = None
            unknown.append(pk)
        else:
            numbers[pk] = bool(pain.get("pain_flag_any"))
            if pain.get("pain_flag_any"):
                dates = pain.get("pain_dates") or []
                # #4036: did the owner dismiss THIS instance, and does the dismissal still hold?
                res = training_context_registry.resolve_flag(movement=ex["label"], note_dates=dates, dismissals=dismissals)
                if res is not None:
                    dismissed_rows.append({**res, "idx": i})
                    numbers[f"pain_dismissed[{i}]"] = bool(res.get("dismissed"))
                if res is not None and res.get("dismissed"):
                    # No flag and no violation on a dismissed instance — deliberately. A `flags`
                    # entry here would be an escalation handle: `reconcile` lets the model raise
                    # info -> change on any metric the packet flags, so "carried but not objected
                    # to" has to mean carried OUTSIDE `flags` (see `owner_dismissals` below).
                    continue
                reason = f"{ex['label']}: pain flag on {', '.join(dates[-2:]) or 'a recent session'} — {CALIBRATION_REDLINES['pain_flag_loaded']}"
                if res is not None:
                    # A dismissal exists but does not hold: re-armed by a later note, or
                    # uncomparable because the flag carries no readable date. Either way the
                    # veto stands AND says why the override did not save it (#4036).
                    reason = f"{reason} [{res['detail']}]"
                violations.append(
                    {
                        "redline": "pain_flag_loaded",
                        "metric": pk,
                        "reason": reason,
                        "field": f"exercises[{i}].drop",
                        "to": True,
                    }
                )
        if ex.get("axial") and (ex.get("top_weight_lbs") or 0) >= AXIAL_HEAVY_LBS and (ds is None or ds >= CALIBRATION_COLD_DAYS):
            heavy_axial_cold.append(ex)
    patterns = {e["axial"] for e in heavy_axial_cold}
    numbers["heavy_axial_patterns_cold"] = len(patterns)
    if len(patterns) >= 2:
        second = heavy_axial_cold[-1]
        violations.append(
            {
                "redline": "two_heavy_axial_cold",
                "metric": "heavy_axial_patterns_cold",
                "reason": f"{' + '.join(e['label'] for e in heavy_axial_cold)}: {len(patterns)} heavy axial patterns cold in one session — {CALIBRATION_REDLINES['two_heavy_axial_cold']}",
                "field": f"exercises[{second['idx']}].weight_lbs",
                "to": round(AXIAL_HEAVY_LBS * 0.6, 1),
            }
        )
    if not layer_ok:
        flags.append(
            _flag(
                "pain_layer_status",
                "info",
                f"derived note layer status={pain_layer_status!r} — its silence is not evidence of no pain (#3768)",
                provenance="owner",
            )
        )
    return {
        "critic": "joints_tendons",
        "numbers": numbers,
        "flags": flags,
        "unknown": unknown,
        "violations": violations,
        # #4036 — carried on the packet so the verdict a human reads names the override and
        # its date. An empty list means no dismissal was in play, never that none exist.
        "owner_dismissals": dismissed_rows,
    }


def _deload_total_sets(draft: dict[str, Any]) -> int:
    """The session's total sets under the owner's signed deload cut (−30 % sets as of v3), >= 1."""
    pct = float(owner_redlines.REDLINES["lifting_sessions_per_wk"]["deload"]["sets_pct"])
    return max(1, int(round(int(draft.get("total_sets") or 0) * (1 + pct / 100.0))))


def _novel_again_flag(ex: dict[str, Any], dk: str, ds: int) -> dict[str, Any]:
    """The days-since rule, answered in code (#4149 — the ruling at NOVEL_AGAIN_MAX_WORKING_SETS).

    A LOADED movement last performed >= NOVEL_AGAIN_DAYS ago with more working sets than the cap
    draws a `change` to the cap; at or under the cap the rule is already met and the flag is
    `info`. Either way the flag is `governed`: the model cannot re-escalate it into a load cut
    or a different set count, so one (signal, value) gives one answer on every run."""
    cap = NOVEL_AGAIN_MAX_WORKING_SETS
    reason = f"{ex['label']}: last performed {ds} days ago — novel-again pattern, tendons lag muscle"
    loaded = ex.get("top_weight_lbs") is not None
    if loaded and (ex.get("n_working_sets") or 0) > cap:
        warmups = (ex.get("n_sets") or 0) - (ex.get("n_working_sets") or 0)
        return _flag(
            dk,
            "change",
            f"{reason}: {ex['n_working_sets']} -> {cap} working sets on session 1 (load stays the entry ramp's, never cut here)",
            provenance="owner-history",
            field=f"exercises[{ex['idx']}].set_count",
            to=warmups + cap,
            governed=True,
        )
    tail = f"; working sets already <= {cap}" if loaded else "; unloaded"
    return _flag(dk, "info", reason + tail, provenance="owner-history", governed=True)


def _walking_split_sentence(walking: dict[str, Any]) -> str:
    """The per-source split, inline in the critic's sentence: " (strava 6.04 + hevy 8.33)".

    #3930: a walking verdict the coach reads should never be a bare total again. A source that
    could not be read is named as such, and the total is declared a FLOOR, because "6.04 hr"
    from one readable source reads identically to "6.04 hr" from two — which is precisely how
    the Strava-only number passed for the week's volume.
    """
    sources = walking.get("sources")
    if not isinstance(sources, dict):
        return ""
    # the source names are taken from the layer's own breakdown, never hand-typed here:
    # a third walking source would join this sentence by existing (#2844 conformance guard)
    parts = []
    for name, row in sources.items():
        if not isinstance(row, dict):
            continue
        hours = row.get("hours")
        parts.append(f"{name} {hours}" if hours is not None else f"{name} {row.get('status', 'unreadable')}")
    if not parts:
        return ""
    tail = ", a FLOOR" if walking.get("total_is_floor") else ""
    return f" ({' + '.join(parts)}{tail})"


def build_rate_advocate_packet(
    draft: dict[str, Any],
    *,
    tripwires: list[dict[str, Any]] | None,
    walking: dict[str, Any] | None,
    rate_target: dict[str, Any] | None,
    current_rate_lb_wk: float | None,
    lifting_sessions_7d: int | None,
    rate_provisional: bool | None = None,
) -> dict[str, Any]:
    """The owner's redlines and which tripwires are CLEAR. This critic argues for MORE.

    Its deterministic layer never vetoes: an advocate is not a gate. Its `change` is bounded
    to adding sets, and only where every readable tripwire is clear. `current_rate_lb_wk` is
    THE loss rate (`mcp.shared_quantities`, #4068); a `rate_provisional` one argues nothing."""
    tw = tripwires or []
    clear = [t["id"] for t in tw if t.get("state") == "clear"]
    tripped = [t["id"] for t in tw if t.get("state") == "tripped"]
    # #4072: a tripwire whose input read FAILED is as unreadable as an absent one — the
    # advocate may not argue for more volume past either.
    unknown_tw = [t["id"] for t in tw if t.get("state") in ("unknown", "read_failed")]
    # #4098: a tripwire held by its own `not_before_week` is neither clear nor tripped — it is
    # counted and named, so "all clear" never silently means "all the ones that are armed".
    inactive = [t["id"] for t in tw if t.get("state") == "not_yet_active"]
    numbers: dict[str, Any] = {
        "tripwires_clear": len(clear),
        "tripwires_not_yet_active": len(inactive),
        "tripwires_tripped": len(tripped),
        "tripwires_unreadable": len(unknown_tw),
        "walking_gap_hr_wk": (walking or {}).get("gap_hr_wk"),
        "walking_pct_of_floor": (walking or {}).get("pct_of_floor"),
        # #3930: this critic's loudest sentence was built on a Strava-only walking read. It now
        # argues from the union and carries the split, so a source that could not be read lands
        # in `unknown` as None instead of silently contributing zero hours to the case.
        "walking_hr_wk_strava": (((walking or {}).get("sources") or {}).get("strava") or {}).get("hours"),
        "walking_hr_wk_hevy": (((walking or {}).get("sources") or {}).get("hevy") or {}).get("hours"),
        "rate_band_high_lb_wk": (rate_target or {}).get("high_lb_wk"),
        "rate_band_low_lb_wk": (rate_target or {}).get("low_lb_wk"),
        "current_rate_lb_wk": current_rate_lb_wk,
        "current_rate_provisional": rate_provisional,
        "lifting_sessions_7d": lifting_sessions_7d,
        "draft_total_sets": draft.get("total_sets"),
    }
    flags: list[dict[str, Any]] = []
    unknown: list[str] = [k for k, v in numbers.items() if v is None and k != "current_rate_provisional"]
    sessions_hi = owner_redlines.REDLINES["lifting_sessions_per_wk"]["high"]
    if tw and not tripped and not unknown_tw:
        flags.append(
            _flag(
                "tripwires_clear",
                "info",
                f"all {len(clear)} armed tripwires clear — nothing in the data argues for holding back"
                + (f" ({len(inactive)} not yet active: {', '.join(inactive)})" if inactive else ""),
                provenance="owner",
                # #4149: what a grounded escalation adds, computed here — never the model's total
                field="session.total_sets",
                to=int(draft.get("total_sets") or 0) + ADVOCATE_ADD_SETS,
            )
        )
    if tripped:
        flags.append(
            _flag(
                "tripwires_tripped",
                "info",
                f"{len(tripped)} tripped ({', '.join(tripped)}) — the case for more is closed on those",
                provenance="owner",
            )
        )
    w = walking or {}
    rt = rate_target or {}
    split = _walking_split_sentence(w)
    if w.get("state") == "below_floor":
        flags.append(
            _flag(
                "walking_gap_hr_wk",
                "info",
                f"walking {w.get('now_hr_wk')} hr/wk{split} vs the proven {w.get('floor_hr_wk')} hr/wk floor — "
                "the largest lever is not in this routine",
                provenance=w.get("provenance", "owner-history"),
            )
        )
    elif w.get("state") == "at_or_above_floor":
        # #3930: the floor being MET is an argument too, and it was unsayable while the read
        # was Strava-only — every week came back below floor and the advocate never had to
        # reason about a met one. Naming it stops "the largest gap on the board" from being
        # the standing verdict on a week he actually walked.
        flags.append(
            _flag(
                "walking_pct_of_floor",
                "info",
                f"walking {w.get('now_hr_wk')} hr/wk{split} is AT OR ABOVE the {w.get('floor_hr_wk')} hr/wk floor — "
                "the walking lever is not the gap this week; argue from something else",
                provenance=w.get("provenance", "owner-history"),
            )
        )
    hi = rt.get("high_lb_wk")
    # #4068: a provisional rate stays in `numbers` and is never flagged (a flag is an escalation handle).
    argued = None if rate_provisional else current_rate_lb_wk
    if argued is not None and hi is not None and argued < rt.get("low_lb_wk", 0):
        flags.append(
            _flag(
                "current_rate_lb_wk",
                "info",
                f"losing {current_rate_lb_wk} lb/wk, under the {rt.get('low_lb_wk')}-{hi} lb/wk band he set",
                provenance=rt.get("provenance", "owner"),
            )
        )
    elif argued is not None and hi is not None and argued > hi:
        flags.append(
            _flag(
                "current_rate_lb_wk",
                "info",
                f"losing {current_rate_lb_wk} lb/wk, ABOVE the {rt.get('low_lb_wk')}-{hi} lb/wk band he set — on rate the advocate has nothing to add",
                provenance=rt.get("provenance", "owner"),
            )
        )
    if lifting_sessions_7d is not None and lifting_sessions_7d >= sessions_hi:
        flags.append(
            _flag(
                "lifting_sessions_7d",
                "info",
                f"{lifting_sessions_7d} lifts in 7d already at the {sessions_hi}/wk redline — route the willingness to walking/Z2, not sets",
                provenance="owner",
            )
        )
    return {"critic": "rate_advocate", "numbers": numbers, "flags": flags, "unknown": unknown, "violations": []}


CONSISTENT_BLOCK_WEEKS = 2  # trailing weeks at >=2 lifts/wk before a lift counts as having a CURRENT baseline


def build_historian_packet(draft: dict[str, Any], *, reference: dict[str, Any] | None, weeks_in_block: int | None = None) -> dict[str, Any]:
    """The weight-band reference, and the #3717 attestation with its label welded on.

    The owner's load rule (#3753 `load_anchoring`) has TWO axes: (1) the matched bodyweight
    band says what his frame handled; (2) weeks since the last consistent block says what
    his connective tissue is ready for NOW. This critic holds both — `weeks_in_block` is the
    trailing count of weeks at >=2 lifts/wk, a different number from the joints critic's
    per-movement days-since. COLD (fewer than CONSISTENT_BLOCK_WEEKS) → a draft top above
    the band-matched best less the detraining discount is a `change`, down only. IN A BLOCK,
    or block length unknown → the band figure is DESCRIPTIVE: the calibration doc says once a
    lift has a current baseline, prescribe near it, and on 2026-09-19 the live band reference
    (2019-2024 window) held a 40 lb dumbbell row against an 80 lb row performed three days
    earlier — a cut to 36 lb would have been an invented objection (#3851).
    Attested volume is reported beside the measured figure, never added to it."""
    proven = (reference or {}).get("proven_target") or {}
    disc_lo, disc_hi = owner_redlines.REDLINES["load_anchoring"]["detraining_discount_pct"]
    cold = weeks_in_block is not None and weeks_in_block < CONSISTENT_BLOCK_WEEKS
    numbers: dict[str, Any] = {
        "weeks_in_current_block": weeks_in_block,
        "band": proven.get("band"),
        "band_distance_lb": proven.get("band_distance_lb"),
        "band_sets_wk": proven.get("sets_wk"),
        "band_walk_hr_wk": proven.get("walk_hr_wk"),
        "band_n_effective_days": proven.get("n_effective"),
        "band_volume_citable": proven.get("volume_citable"),
        "band_evidence_tier": proven.get("evidence_tier"),
        # LIVE SHAPE (2026-09-20): the prescription view's overlay carries HOURS PER WEEK
        # (`cardio_hr_wk_attested`, with _low/_high), not per-session minutes.
        "attested_cardio_hr_wk": (
            (proven.get("attested") or {}).get("cardio_hr_wk_attested") if isinstance(proven.get("attested"), dict) else None
        ),
        "attested_basis": "OWNER-ATTESTED, NOT MEASURED" if proven.get("attested") else None,
        "detraining_discount_pct": [disc_lo, disc_hi],
    }
    flags: list[dict[str, Any]] = []
    unknown: list[str] = []
    if weeks_in_block is None:
        unknown.append("weeks_in_current_block")
    if not proven:
        unknown.append("band")
        flags.append(
            _flag(
                "band",
                "info",
                "no weight-matched losing-phase reference — describe, never substitute the current band",
                provenance="owner-history",
            )
        )
        return {"critic": "blueprint_historian", "numbers": numbers, "flags": flags, "unknown": unknown, "violations": []}
    if proven.get("band_distance_lb"):
        flags.append(
            _flag(
                "band_distance_lb",
                "info",
                f"reference band {proven.get('band')} is {proven.get('band_distance_lb')} lb from his current weight — not a mirror",
                provenance="owner-history",
            )
        )
    if not proven.get("volume_citable"):
        flags.append(
            _flag(
                "band_volume_citable",
                "info",
                f"band {proven.get('band')} is BELOW the volume evidence floor (n_eff={proven.get('n_effective')}) — descriptive only, never a target",
                provenance="ADR-105",
            )
        )
    if proven.get("attested"):
        flags.append(
            _flag(
                "attested_cardio_hr_wk",
                "info",
                f"band carries an OWNER-ATTESTED overlay (~{numbers['attested_cardio_hr_wk']} hr/wk post-lift cardio, NOT MEASURED) — the measured figure is a floor (#3717)",
                provenance="owner-attested",
            )
        )
    top_by = proven.get("top_kg_by_movement") or {}
    norm_top = {_norm(k): v for k, v in top_by.items() if v is not None}
    for ex in draft["exercises"]:
        k = f"band_top_lbs[{ex['idx']}]"
        band_kg = _match_movement(ex["label"], ex.get("movement_key", ""), norm_top)
        if band_kg is None or ex.get("top_weight_lbs") is None:
            numbers[k] = None
            continue
        band_lbs = float(band_kg) * _LBS_PER_KG
        numbers[k] = round(band_lbs, 1)
        ceiling = band_lbs * (1 - disc_lo / 100.0)
        if ex["top_weight_lbs"] > ceiling + 0.5:
            if cold:
                flags.append(
                    _flag(
                        k,
                        "change",
                        f"{ex['label']}: draft top {ex['top_weight_lbs']} lb vs band-matched best {band_lbs:.0f} lb less the {disc_lo}% detraining "
                        f"discount = {ceiling:.0f} lb, and only {weeks_in_block} wk into a block — cold",
                        provenance="owner",
                        field=f"exercises[{ex['idx']}].weight_lbs",
                        to=round(ceiling, 1),
                    )
                )
            else:
                flags.append(
                    _flag(
                        k,
                        "info",
                        f"{ex['label']}: draft top {ex['top_weight_lbs']} lb vs band-matched best {band_lbs:.0f} lb (window {proven.get('window')}) — "
                        f"descriptive: {weeks_in_block if weeks_in_block is not None else 'unknown'} wk in the current block, a current baseline outranks the band",
                        provenance="owner",
                    )
                )
    return {"critic": "blueprint_historian", "numbers": numbers, "flags": flags, "unknown": unknown, "violations": []}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _match_movement(label: str, key: str, norm_top: dict[str, Any]) -> Any:
    for cand in (_norm(label), _norm(key)):
        if cand and cand in norm_top:
            return norm_top[cand]
    lab = _norm(label)
    for k, v in norm_top.items():
        if lab and (lab in k or k in lab):
            return v
    return None


# ── verdicts ──────────────────────────────────────────────────────────────────────────
def deterministic_verdict(packet: dict[str, Any]) -> dict[str, Any]:
    """The verdict the numbers alone support. Redline violation → veto; a `change`-grade
    flag → change; else approve. Owner-redline tripwires are `change` while #3753 is
    unsigned — a plan is not refused on a rule he has not signed."""
    if packet.get("violations"):
        v = packet["violations"][0]
        return {
            "verdict": "veto",
            "metric": v["metric"],
            "value": packet["numbers"].get(v["metric"]),
            "field": v.get("field"),
            "to": v.get("to"),
            "reason": v["reason"],
            "redline": v["redline"],
        }
    changes = [f for f in packet.get("flags", []) if f["severity"] == "change"]
    if changes:
        f = changes[0]
        return {
            "verdict": "change",
            "metric": f["metric"],
            "value": packet["numbers"].get(f["metric"]),
            "field": f.get("field"),
            "to": f.get("to"),
            "reason": f["reason"],
        }
    return {
        "verdict": "approve",
        "metric": None,
        "value": None,
        "field": None,
        "to": None,
        "reason": "nothing in this packet crosses a stated threshold",
    }


def _prompt(packet: dict[str, Any], draft: dict[str, Any]) -> dict[str, Any]:
    fields = "exercises[<idx>].weight_lbs | exercises[<idx>].set_count | exercises[<idx>].reps | exercises[<idx>].drop | session.total_sets"
    system = (
        f"You are the {packet['critic']} critic reviewing tomorrow's training session for one athlete. "
        "You hold ONLY the evidence packet below; other critics hold other evidence. Reply with exactly one JSON object: "
        '{"verdict": "approve"|"change"|"veto", "metric": <a key from numbers>, "value": <that number>, '
        f'"field": <one of {fields} or null>, "to": <number|true|null>, "sentence": <ONE sentence, max 200 characters>}}. '
        "Rules: `metric` MUST be a key in `numbers`. Object ONLY where a flag names the metric you cite; if no flag applies, approve. "
        "Never invent a threshold, never argue from evidence you were not given, and describe associations without causal wording."
    )
    user = json.dumps(
        {
            "draft": draft,
            "packet": {
                "numbers": packet["numbers"],
                "flags": packet["flags"],
                "unknown": packet["unknown"],
                "violations": packet.get("violations", []),
            },
        },
        default=str,
    )
    return {
        "model": HAIKU_MODEL,
        "max_tokens": MAX_TOKENS,
        "system": system,
        # #4149: pinned. The verdict's NUMBERS are computed in code regardless; this keeps the
        # objection and its sentence from varying with the sample as well.
        "temperature": 0,
        "messages": [{"role": "user", "content": user + "\nReturn the JSON object."}],
    }


def parse_model_verdict(resp: dict[str, Any]) -> dict[str, Any]:
    """The model's JSON object, or a named parse failure. Never a fabricated verdict."""
    if (resp or {}).get("stop_reason") == "max_tokens":
        # No retry: MAX_TOKENS and the packet are fixed, so the truncation is deterministic and a
        # retry bills again for the same cut. Recorded on the verdict; counted nowhere an operator
        # reads — the #3828 residual class (registered in tests/test_judge_verdict_retry_3688.py).
        return {"error": f"truncated at max_tokens={MAX_TOKENS}"}
    text = "".join(p.get("text", "") for p in (resp or {}).get("content", []) if p.get("type") == "text").strip()
    a, b = text.find("{"), text.rfind("}")
    if a == -1 or b <= a:
        return {"error": f"no JSON object in a {len(text)}-char response"}
    try:
        obj = json.loads(text[a : b + 1])  # noqa: E203
    except (ValueError, TypeError) as e:
        return {"error": f"json.loads failed: {type(e).__name__}"}
    if not isinstance(obj, dict) or obj.get("verdict") not in VERDICTS:
        return {"error": "verdict not in approve|change|veto"}
    sentence = str(obj.get("sentence") or "").strip()
    sentence = re.split(r"(?<=[.!?])\s", sentence)[0][:200]
    return {
        "verdict": obj["verdict"],
        "metric": obj.get("metric"),
        "value": obj.get("value"),
        "field": obj.get("field"),
        "to": obj.get("to"),
        "sentence": sentence,
    }


def reconcile(det: dict[str, Any], model: dict[str, Any] | None, packet: dict[str, Any]) -> dict[str, Any]:
    """Bound the model by the numbers. The deterministic verdict is a floor; the model may
    escalate ONE step and only on a metric the packet already flags."""
    out = dict(det)
    out["critic"] = packet["critic"]
    out["provenance"] = _provenance_for(packet, det.get("metric"))
    out["model"] = None
    out["discarded"] = None
    if not model:
        return out
    if model.get("error"):
        out["model"] = {"error": model["error"]}
        return out
    out["model"] = {k: model.get(k) for k in ("verdict", "metric", "value", "field", "to", "sentence")}
    if model.get("sentence"):
        out["sentence"] = model["sentence"]
    rank = {"approve": 0, "change": 1, "veto": 2}
    if rank[model["verdict"]] <= rank[det["verdict"]]:
        return out  # the model agrees or is milder — the floor holds
    flags = {f["metric"]: f for f in packet.get("flags", [])}
    violated = {v["metric"] for v in packet.get("violations", [])}
    metric = model.get("metric")
    if (metric not in flags and metric not in violated) or metric not in packet["numbers"]:
        out["discarded"] = f"model said {model['verdict']} on {metric!r}, which no flag in this packet names — objection discarded (#3851)"
        return out
    flag = flags.get(metric) or {}
    if flag.get("governed"):
        # #4149: a code rule already answers this signal in full; a model escalation here is how
        # one days-since value became three different changes on 2026-09-23.
        out["discarded"] = f"model said {model['verdict']} on {metric!r}, which a code rule governs — the rule's answer stands (#4149)"
        return out
    # grounded escalation: one step up from the floor, never more. The model chooses WHETHER to
    # object on a flagged metric; the field and number applied are the FLAG's, computed in code
    # (#4149) — a model-chosen number is recorded on `model`, never applied.
    target = "change" if det["verdict"] == "approve" else "veto"
    if model["verdict"] == "veto" and target == "change":
        out["discarded"] = f"model veto on {metric!r} downgraded to change — a veto needs a redline, and none is violated here"
    if model.get("field") or model.get("to") is not None:
        out["model_numbers_not_applied"] = f"{model.get('field')} -> {model.get('to')}: a model-chosen number is never applied (#4149)"
    code_field = flag.get("field")
    out.update(
        {
            "verdict": target,
            "metric": metric,
            "value": packet["numbers"].get(metric),
            "field": code_field or det.get("field"),
            "to": flag.get("to") if code_field else det.get("to"),
        }
    )
    out["reason"] = out.get("sentence") or out["reason"]
    out["provenance"] = _provenance_for(packet, metric)
    return out


def _provenance_for(packet: dict[str, Any], metric: str | None) -> str | None:
    for f in packet.get("flags", []):
        if f["metric"] == metric:
            return f.get("provenance")
    for v in packet.get("violations", []):
        if v["metric"] == metric:
            return "owner"
    return None


def run_critics(
    packets: dict[str, dict[str, Any]],
    draft: dict[str, Any],
    *,
    invoke: Callable[[dict[str, Any]], dict[str, Any]] | None,
    model_allowed: bool,
    model_paused_reason: str | None = None,
) -> list[dict[str, Any]]:
    """Four verdicts, one per packet, each a SEPARATE model call over its own packet.

    `invoke` is the Bedrock chokepoint (or a test double). With `model_allowed` False the
    deterministic layer alone decides and every verdict records why the model did not run —
    a paused critic is reported as paused, never as an approval."""
    out: list[dict[str, Any]] = []
    for cid in CRITIC_IDS:
        packet = packets[cid]
        det = deterministic_verdict(packet)
        model = None
        if model_allowed and invoke is not None:
            try:
                model = parse_model_verdict(invoke(_prompt(packet, draft)))
            except Exception as e:  # noqa: BLE001 — a model failure is recorded on the verdict, not raised past it
                model = {"error": f"{type(e).__name__}: {e}"[:200]}
        v = reconcile(det, model, packet)
        if not model_allowed:
            v["model"] = {"paused": model_paused_reason or "budget tier"}
        v["unknown"] = list(packet.get("unknown", []))
        out.append(v)
    return out


# ── applying changes and re-checking ──────────────────────────────────────────────────
# #4149: `apply_changes` + the floor clamp live in the cohesive sibling `critics_apply` (this
# module was nearing its size ceiling — the #4112 precedent). Every caller still reads
# `critics.apply_changes`.


def recheck(
    ir: Any,
    rebuild_packets: Callable[[dict[str, Any]], dict[str, dict[str, Any]]],
    *,
    overridden: Any = (),
) -> dict[str, Any]:
    """Re-run the DETERMINISTIC layer over the revised draft with the same evidence.

    `rebuild_packets(draft_summary)` is the caller's packet builder over the already-fetched
    evidence — no model, no I/O. Passes only when no packet still carries a violation that
    the owner has not overridden (#4076). An overridden critic's remaining veto is still
    LISTED, marked `owner_overridden`, never dropped from the record."""
    draft = draft_summary(ir)
    packets = rebuild_packets(draft)
    over = set(overridden or ())
    remaining = [
        deterministic_verdict(p) | {"critic": cid} | ({"owner_overridden": True} if cid in over else {})
        for cid, p in packets.items()
        if p.get("violations")
    ]
    return {
        "passed": not [r for r in remaining if not r.get("owner_overridden")],
        "remaining_vetoes": remaining,
        "total_sets": draft["total_sets"],
        "exercise_count": len(draft["exercises"]),
    }


# ── what rides on the routine ─────────────────────────────────────────────────────────
def is_overridden(v: dict[str, Any]) -> bool:
    """True when the owner overrode THIS verdict's veto (#4076). Only a veto can be."""
    return v.get("verdict") == "veto" and bool(v.get("owner_override"))


def standing_vetoes(verdicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The vetoes that still block: every `veto` the owner has not overridden."""
    return [v for v in verdicts or [] if v.get("verdict") == "veto" and not is_overridden(v)]


def veto_reason(ir: Any) -> str | None:
    """The reason a commit must refuse, or None. Read from the stored verdicts only.

    An owner-overridden veto (#4076) does not refuse; every other veto still does."""
    rec = ((getattr(ir, "inputs_snapshot", None) or {}).get("critics")) or {}
    vetoes = standing_vetoes(rec.get("verdicts", []))
    if not vetoes:
        return None
    return "; ".join(f"{v['critic']}: {v.get('reason')}" for v in vetoes)


_SHORT = {
    "muscle_defense": "muscle-defense",
    "joints_tendons": "joints/tendons",
    "rate_advocate": "rate-advocate",
    "blueprint_historian": "historian",
}

NOT_RED_TEAMED = "not run — this routine was NOT red-teamed (#3752: plan_next_session with routine_id first)"


def commit_status(ir: Any) -> str:
    """One line for the commit result: which critics ran and what each said, or that none did."""
    rec = ((getattr(ir, "inputs_snapshot", None) or {}).get("critics")) or {}
    verdicts = rec.get("verdicts") or []
    if not verdicts:
        return NOT_RED_TEAMED
    paused = " (model paused — deterministic layer only)" if rec.get("model_ran") is False else ""
    return f"{rec.get('engine', CRITICS_VERSION)}{paused}: " + ", ".join(
        f"{_SHORT.get(v['critic'], v['critic'])} {v['verdict']}" + (" (owner-overridden)" if is_overridden(v) else "") for v in verdicts
    )


def notes_block(ir: Any) -> str:
    """The critics' verdicts and the numbers they argued from, as lines for the Hevy notes."""
    rec = ((getattr(ir, "inputs_snapshot", None) or {}).get("critics")) or {}
    verdicts = rec.get("verdicts") or []
    if not verdicts:
        return ""
    lines = [f"RED TEAM ({rec.get('engine', CRITICS_VERSION)}, {len(verdicts)} critics, {rec.get('ran_at', '')[:10]}):"]
    for v in verdicts:
        num = f" {v['metric']}={_fmt(v.get('value'))}" if v.get("metric") else ""
        prov = f" [{v['provenance']}]" if v.get("provenance") else ""
        paused = " (model paused)" if isinstance(v.get("model"), dict) and v["model"].get("paused") else ""
        reason = (v.get("reason") or "").replace("\n", " ")
        over = " OVERRIDDEN BY OWNER" if is_overridden(v) else ""
        lines.append(f"- {_SHORT.get(v['critic'], v['critic'])} {v['verdict'].upper()}{over}{paused}:{num}{prov} {reason}"[:300])
    applied = [c for c in rec.get("changes", []) if c.get("applied")]
    if applied:
        lines.append("applied: " + "; ".join(f"{c['field']} -> {c['to']}" for c in applied))
    for c in rec.get("changes", []):
        if c.get("conflict"):
            lines.append(f"CONFLICT: {c['conflict']}"[:300])
    for o in rec.get("owner_overrides") or []:
        if o.get("applied"):
            words = " ".join(str(o.get("owner_words") or "").split())
            lines.append(f"owner override of {_SHORT.get(o['critic'], o['critic'])} ({str(o.get('at') or '')[:10]}): \"{words}\""[:300])
    return "\n".join(lines)


def with_notes_block(why_note: str, ir: Any) -> str:
    """#3938 (2026-09-20): no longer called at commit/dry_run — the block rides on exercises[0].notes
    via `_place_block_on_first_exercise` (Hevy has no routine-level notes field), and composing it
    here as well stacked it twice on that channel. Kept for callers that want the composed form."""
    block = notes_block(ir)
    return f"{why_note}\n\n{block}" if block and why_note else (block or why_note)


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.1f}"
    return str(v)


def thread_entry(ir: Any, *, today: str) -> dict[str, Any]:
    """The training coach thread row for tonight's verdicts — shaped like a thread entry so
    `get_coach_thread` renders it beside the analyzer's, keyed so it never overwrites one."""
    rec = ((getattr(ir, "inputs_snapshot", None) or {}).get("critics")) or {}
    verdicts = rec.get("verdicts") or []
    summary = "; ".join(
        f"{_SHORT.get(v['critic'], v['critic'])} {v['verdict']}" + (f" on {v['metric']}={_fmt(v.get('value'))}" if v.get("metric") else "")
        for v in verdicts
    )
    from experiment.phase_taxonomy import experiment_stamp_for  # #3900: tagger-blind pk, class-gated stamp

    return {
        **experiment_stamp_for("USER#matthew", f"SOURCE#coach_thread#training#{today}#critics"),
        "pk": "USER#matthew",
        "sk": f"SOURCE#coach_thread#training#{today}#critics",
        "coach_id": "training",
        "date": today,
        "generation_context": "plan_critics",
        "position_summary": f"Red team on routine {getattr(ir, 'routine_id', '?')} for {getattr(ir, 'target_date', '?')}: {summary}",
        "predictions": [],
        "surprises": [v.get("reason") for v in standing_vetoes(verdicts)],
        # #4076 — an overridden veto is not a surprise the coach carries forward; the owner's
        # words are, verbatim, beside the critic and signal he overrode.
        "owner_overrides": [
            {"critic": o["critic"], "signal": o.get("signal"), "owner_words": o.get("owner_words"), "at": o.get("at")}
            for o in rec.get("owner_overrides") or []
            if o.get("applied")
        ],
        "stance_changes": [
            f"{v['critic']}: {v.get('field')} -> {v.get('to')}" for v in verdicts if v.get("verdict") == "change" and v.get("field")
        ],
        "emotional_investment": "adversarial",
        "open_questions": [f"{v['critic']} could not read: {', '.join(v['unknown'])}" for v in verdicts if v.get("unknown")],
        "learning_log": [
            {
                "critic": v["critic"],
                "verdict": v["verdict"],
                "metric": v.get("metric"),
                "value": v.get("value"),
                "provenance": v.get("provenance"),
                "owner_overridden": is_overridden(v),
            }
            for v in verdicts
        ],
        "critics_engine": rec.get("engine", CRITICS_VERSION),
        "routine_id": getattr(ir, "routine_id", None),
    }
