"""load_ramp.py — v0.3 §3's entry ramp: the load a v0.3 session actually prescribes (#4090).

WHY THIS EXISTS

#4064 made 2026-09-24 the first full-body HEAVY session of block 1, and every working set
in it went through the #3927 prescription floor — which, with no layoff, IS the best load
carried at the current bodyweight band. So week 1 of a program the owner approved as a
return from detraining prescribed a 100 % top set. v0.3 §3 (approved 2026-09-21) says
otherwise, in one sentence:

    "Start at 60–65 % of the band-matched historical anchor after the 10–15 % detraining
     discount; ramp ~5 %/wk to week 6; ≤ 85 % of band e1RM until week 8; then hold."

THE RULE, AS ARITHMETIC

    top_kg = anchor_kg x (1 - discount) x ramp_pct(week)      rounded UP to 0.5 kg
    top_kg <= cap_pct x band_e1rm_kg                           (the e1RM guard, rounded DOWN)
    ramp_pct(week) = min(start + step x (week - 1), cap_pct)   (held at cap_pct from then on)

  * `anchor_kg` is `routine_generator.band_matched_best` — the ONE definition of the band
    anchor (#3927), never re-derived here.
  * every number is read from `owner_redlines.REDLINES` (the machine twin of §3), so the
    provenance is the redline's: `lifting_sessions_per_wk.load_entry` (start / step /
    ramp_to_week / cap) and `load_anchoring.detraining_discount_pct`.
  * `start` is DERIVED, not picked: the ramp must reach the cap exactly at `ramp_to_week`,
    so start = cap - step x (ramp_to_week - 1) = 85 - 5 x 5 = 60. It is asserted to sit
    inside the declared 60–65 % — change any one number and the derivation either still
    lands in the band or refuses loudly.
  * the discount takes the DEEPEST end of the owner's 10–15 % band, the same end the #3927
    floor takes after a layoff: the anchor is a band-matched load from the 2024–25
    campaign, and "weeks since the last consistent block" (the owner's second axis) is
    not something the history index can measure — so the rule assumes the longer gap.
  * the redline key says `start_pct_of_band_e1rm`; §3's prose says the start is a share of
    the band-matched ANCHOR after the discount, and names e1RM only in the cap. This
    module follows the prose (the approved text) and applies e1RM only as the cap.

Rounding is UP to the 0.5 kg the history renders at, because the week's percentage is the
bottom of an approved band (60–65 %): rounding down would land week 1 under 60 %, which
§3 does not license. The e1RM cap is rounded DOWN, so rounding never crosses it.

Week 1 therefore reads 0.85 x 0.60 = 51 % of the anchor load; week 6 onward, 0.85 x 0.85
= 72.25 %. The e1RM cap (85 % of Epley e1RM from the anchor set) cannot bind below the
fraction cap by construction; it is kept as a guard, and `cap_bound` says when it did.

Back-offs stay −10 % of the top set (`full_body_session._apply_back_offs`); they are the
one sanctioned set under the top-set floor, and `back_off_floor_kg` records it so the
commit gate (`recovery_authoring.audit_prescription`) checks them against their own floor.

SCOPE: v0.3 sessions only. `full_body_session` passes `ramp_floor` into
`routine_generator._enforce_load_floors`; the muscle-budget (v0.1/v0.2) path and an
inactive program never reach this module.
"""

from __future__ import annotations

import math
from typing import Any

ISSUE = "#4090"
SECTION = "TRAINING_PROGRAM_v0.3.md §3 — 'Start at 60–65 % of the band-matched historical anchor after the 10–15 % detraining discount'"


def params() -> dict[str, Any]:
    """Every constant the ramp uses, read from `owner_redlines` — with provenance."""
    from training import owner_redlines

    lift = owner_redlines.REDLINES["lifting_sessions_per_wk"]
    entry = lift["load_entry"]
    anchoring = owner_redlines.REDLINES["load_anchoring"]
    lo, hi = entry["start_pct_of_band_e1rm"]
    step = int(entry["ramp_pct_per_wk"])
    to_week = int(entry["ramp_to_week"])
    cap = int(entry["max_pct_of_band_e1rm_until_week_8"])
    start = cap - step * (to_week - 1)
    if not lo <= start <= hi:
        raise ValueError(f"load ramp: derived start {start}% (cap {cap} - {step} x {to_week - 1}) is outside the redline's {lo}–{hi}%")
    _d_lo, d_deep = anchoring["detraining_discount_pct"]
    return {
        "start_pct": start,
        "start_pct_declared": [lo, hi],
        "step_pct_per_wk": step,
        "ramp_to_week": to_week,
        "cap_pct": cap,
        "then": entry.get("then"),
        "discount_pct": int(d_deep),
        "discount_pct_declared": list(anchoring["detraining_discount_pct"]),
        "provenance": {
            "load_entry": "owner_redlines.REDLINES['lifting_sessions_per_wk']['load_entry'] (" + str(lift.get("provenance")) + ")",
            "discount": "owner_redlines.REDLINES['load_anchoring']['detraining_discount_pct'] (" + str(anchoring.get("provenance")) + ")",
            "section": SECTION,
        },
    }


def ramp_pct(week: int | None, p: dict[str, Any] | None = None) -> int:
    """The week's share of the discounted anchor, in whole percent. Week < 1 (or unknown) is week 1."""
    p = p or params()
    w = max(1, int(week or 1))
    return min(p["start_pct"] + p["step_pct_per_wk"] * (w - 1), p["cap_pct"])


def _floor_half_kg(kg: float) -> float:
    return int(kg * 2) / 2


def _ceil_half_kg(kg: float) -> float:
    return math.ceil(round(kg * 2, 6)) / 2


def band_e1rm_kg(best_kg: float, reps: list[int] | None) -> float:
    """Epley e1RM of the anchor set. No reps recorded -> the load itself (the conservative read)."""
    r = max([int(x) for x in (reps or []) if x] or [0])
    return float(best_kg) * (1 + r / 30.0) if r > 0 else float(best_kg)


def ramp_floor(floor: dict[str, Any], week: int | None) -> dict[str, Any]:
    """A `prescription_floor` result, re-based onto the week's ramp. Pure; returns a copy.

    Recomputes from `best_kg` (the undiscounted band anchor), so a layoff discount the floor
    may already have taken is never applied twice. A floor without a band-matched anchor
    passes through unchanged — no anchor, no ramp, and the status says which absence."""
    out = dict(floor or {})
    if out.get("status") != "ok" or not out.get("best_kg"):
        return out
    p = params()
    pct = ramp_pct(week, p)
    anchor = float(out["best_kg"])
    basis = out.get("basis") or {}
    e1rm = band_e1rm_kg(anchor, basis.get("reps"))
    raw = anchor * (100 - p["discount_pct"]) / 100.0 * pct / 100.0
    cap_kg = e1rm * p["cap_pct"] / 100.0
    top = min(_ceil_half_kg(raw), _floor_half_kg(cap_kg))
    out["floor_kg"] = top
    out["discount_pct"] = p["discount_pct"]
    out["layoff_reason"] = None
    out["ramp"] = {
        "week": max(1, int(week or 1)),
        "ramp_pct": pct,
        "discount_pct": p["discount_pct"],
        "anchor_kg": anchor,
        "discounted_anchor_kg": round(anchor * (100 - p["discount_pct"]) / 100.0, 3),
        "band_e1rm_kg": round(e1rm, 3),
        "cap_kg": round(cap_kg, 3),
        "cap_bound": cap_kg < raw,
        "top_kg": top,
        "pct_of_anchor": round(100.0 * top / anchor, 1),
        "pct_of_discounted_anchor": round(100.0 * top / (anchor * (100 - p["discount_pct"]) / 100.0), 1),
        "rule": (
            f"v0.3 §3 entry ramp: {pct}% of the band anchor after the {p['discount_pct']}% detraining discount "
            f"(start {p['start_pct']}%, +{p['step_pct_per_wk']}%/wk to week {p['ramp_to_week']}, <= {p['cap_pct']}% of band e1RM, "
            f"then {p['then']})"
        ),
        "provenance": p["provenance"],
    }
    return out


def render_ramp_cue(floor: dict[str, Any]) -> str:
    """The reader-facing line for a ramped load. Factual: the load, the share, the anchor, the date."""
    from training.routine_generator import _fmt_load

    r = (floor or {}).get("ramp") or {}
    if not r or not floor.get("floor_kg"):
        return ""
    basis = floor.get("basis") or {}
    reps = "/".join(str(x) for x in (basis.get("reps") or []))
    got = _fmt_load(float(basis.get("weight_kg") or r["anchor_kg"])) + (f" x {reps}" if reps else "")
    return (
        f"Week {r['week']} load {_fmt_load(float(floor['floor_kg']))} — {r['ramp_pct']}% of your band anchor after the "
        f"{r['discount_pct']}% detraining discount (anchor {got} on {basis.get('date')} at {basis.get('bodyweight_lb')} lb; v0.3 §3). "
        "Down on the day if you must, never up."
    )


def annotate_prescription(
    rx: dict[str, Any],
    catalog_movements: dict[str, Any] | None,
    history_index: dict[str, list],
    weight_index: dict[str, float] | None,
    *,
    target_date: str,
    week: int | None,
) -> dict[str, Any]:
    """Stamp each exposure of a `program_structure` prescription with its ramped load, IN
    PLACE, and return a summary. The planner's read of the same numbers the generator
    writes into the routine — both go through `prescription_floor` then `ramp_floor`."""
    from training.exercise_history import nearest_bodyweight
    from training.routine_generator import prescription_floor

    current = nearest_bodyweight(target_date, weight_index)
    summary: dict[str, Any] = {"status": "applied" if current else "no_current_bodyweight", "week": week, "params": params()}
    summary["current_bodyweight_lb"] = round(float(current), 1) if current else None
    for e in rx.get("exposures") or []:
        key = e.get("movement_key")
        tid = ((catalog_movements or {}).get(key) or {}).get("hevy_template_id_hint") if key else None
        if not current:
            e["load"] = {"status": "no_current_bodyweight"}
            continue
        # the ramp re-bases from the undiscounted anchor, so the layoff arm of the floor is moot here
        floor = prescription_floor(tid, history_index, weight_index, current, days_since_last_workout=None, as_of=target_date)
        ramped = ramp_floor(floor, week)
        load: dict[str, Any] = {"status": ramped.get("status"), "template_id": tid, "top_kg": None}
        if ramped.get("ramp"):
            top = float(ramped["floor_kg"])
            load.update({"top_kg": top, "ramp": ramped["ramp"], "basis": ramped.get("basis")})
            pct = next((s.get("pct_of_top") for s in e.get("sets") or [] if s.get("kind") == "back_off"), None)
            if pct is not None:
                load["back_off_kg"] = _floor_half_kg(top * pct / 100.0)
        e["load"] = load
    return summary
