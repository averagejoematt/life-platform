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

    top_kg = base_kg x (1 - discount) x ramp_pct(week)        to the NEAREST 5 lb (#4388)
    base_kg = band_e1rm_kg, or anchor_kg when novel-again      (#4388 — see the ruling below)
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
  * the discount reads the deep end of `detraining_discount_pct`. #4090 took 15 % (the
    deep end of the owner's 10–15 % band); the owner ruled 10 % on 2026-09-23 (#4107), and
    the redline now carries [10, 10], so the ramp and every other reader see one number.
  * #4388 RULING — THE BASE IS BAND e1RM. The redline key says `start_pct_of_band_e1rm`
    and `max_pct_of_band_e1rm_until_week_8`; §3's prose says "of the band-matched historical
    anchor". #4090 read the prose as the anchor SET's load and applied e1RM only as the cap,
    so the 2026-09-28 squat floor was 60 % x 88.45 kg (195 lb x 5 on 09-24) = 53.5 kg
    (118 lb) for 8–12 reps. The owner reported that as a defect (2026-09-27), and his own
    hand-authored 09-28 routine loaded squat, leg curl and calf at "60 % of band e1RM"
    (squat 135 lb against 103.19 kg). The redline is his machine-readable wording and his
    own authoring follows it, so the ramp's percentage is now a share of the band e1RM —
    the same number the cap is a share of, so the ramp reaches the cap exactly at week 6
    (60 + 5 x 5 = 85) instead of stopping short of it.
  * #4388 — THE NOVEL-AGAIN EXCEPTION IS UNCHANGED. When the detraining discount applies
    (an anchor >= `DETRAINING_ANCHOR_AGE_DAYS` older than block 1, or undated — the pattern
    is novel-again), the base stays the anchor SET's load, exactly the #4090/#4107
    arithmetic. An Epley e1RM extrapolated from a set months old (the 09-28 trap bar: 225 lb
    x 5 on 2025-11-07, 325 days before) is not his current capacity, and the owner's own
    09-28 draft held the trap bar at this engine floor (55.5 kg) as a re-grooving session.
    `ramp.base` names which base a row used ("band_e1rm" | "anchor_set").

Rounding (owner ruling 2026-09-28, #4388) is to the NEAREST 5-lb step in the pound he loads —
`rep_scheme.load_step_kg`, the ONE rounding helper; the generator, the planner and the chat
commit gate all read it through this function. 60 % x 103.19 kg = 136.5 lb -> 135 lb, the load
he wrote by hand, so a week can land up to 2.5 lb under its exact percentage — the owner's call,
replacing #4090's round-UP-to-0.5-kg (which read 62.0 kg = 136.7 lb and refused his 135). The
e1RM cap is rounded DOWN on the same grid, so rounding never crosses it.

Week 1 therefore reads 0.90 x 0.60 = 54 % of an old (novel-again) anchor SET's load; week 6
onward, 0.90 x 0.85 = 76.5 %. A this-cycle anchor takes no discount (#4107) and ramps on its
band e1RM (#4388): 60 % of e1RM in week 1, 85 % — the cap itself — from week 6. On the
anchor-set base the e1RM cap cannot bind below the fraction cap by construction; on the e1RM
base it binds only through rounding (the ramp rounds to the nearest step, the cap DOWN). It is kept as a
guard either way, and `cap_bound` says when it did.

#4408 — THE RAMP IS A RE-ENTRY; A THIS-CYCLE LOAD AT THIS BAND IS HELD, NOT RAMPED UNDER

The ramp exists to bring him back to a load after time away from it. On 2026-09-29 it drafted
the bench top set (4–6 @ RPE 7–8) at 145 lb — 60 % of a band e1RM of 239 lb — six days after he
benched 205 x 5 @ RPE 8 at the same bodyweight band, with no discount (the anchor was this
cycle's) and no layoff: nothing to re-enter from. The routine's own note says the opposite rule
("a load below one already achieved at this bodyweight band, with no layoff, is a bug"). One rule
now, `achieved_hold`:

    top_kg = max(ramp top_kg, the heaviest load he moved for >= the set's rep floor
                              at the CURRENT band, in THIS cycle, before the session)

  * "this cycle" is `anchor_discount`'s own line — a session the detraining discount would NOT
    apply to (< `DETRAINING_ANCHOR_AGE_DAYS` older than block 1). An older session is exactly what
    the ramp re-enters from, so it can never hold a load up.
  * "at the set's rep floor" (`min_reps_of` — the lowest rep_range_start/reps of the exercise's
    working sets): 205 x 5 holds a 4–6 top set at 205 lb; it does NOT hold an 8–12 set, because
    205 lb was never achieved for 8. The 2026-09-28 squat (8–12) holds at 135 lb x 10 from that
    day, the load the owner wrote by hand — not at 195 lb x 5. No load is extrapolated (ADR-105:
    an achieved load, not a formula); where nothing was achieved at the rep floor the ramp stands.
  * no hold under a layoff — `days_since_last_workout >= layoff_days` as the caller says OR as the
    record says (`_lifting_gap_days`: the cron hands the generator a constant 2), on a nearest-band fallback
    anchor (nothing at this band), or when the caller cannot say the reps (`min_reps` None — the
    ramp alone, the lower number, so a caller that knows less can never refuse a draft that knows
    more: #4149).
  * the achieved load is held EXACTLY (not re-rounded): it is a load he moved, and a rounding
    step under it is the defect. The e1RM cap is the ramp's guard, not a reason to prescribe
    under an achieved load; `ramp.hold` records the set, the date, the rep floor and the rule.

The generator (`_enforce_load_floors`, the block's sets), the planner (`annotate_prescription`,
the exposure's rep range) and the chat gate (`derive_load_floors`, the drafted sets) all pass
`min_reps` into `v03_floor`, so the three still read one number.

Back-offs stay −10 % of the top set (`full_body_session._apply_back_offs`); they are the
one sanctioned set under the top-set floor, and `back_off_floor_kg` records it so the
commit gate (`recovery_authoring.audit_prescription`) checks them against their own floor.

SCOPE: v0.3 sessions only. `full_body_session` passes `v03_floor` into
`routine_generator._enforce_load_floors`; the muscle-budget (v0.1/v0.2) path and an
inactive program never reach this module.

#4107 — THE ANCHOR, WHEN THE CURRENT BAND HAS NONE, AND WHEN IT IS DISCOUNTED

`v03_floor` is the ONE v0.3 load path: the generator (`full_body_session`), the planner
(`annotate_prescription`) and the chat commit gate (`hevy_prescription_gate.
derive_load_floors`, the `draft_custom` path) all call it, and nothing else calls
`ramp_floor` or `nearest_band_anchor` (tests/test_v03_nearest_band_anchor_4107.py holds
that by AST). Two additions over #4090:

  * NEAREST-BAND FALLBACK. At 315 lb (band 310–319) the three heavy anchors of block 1 —
    leg press, flat DB bench, machine row — have no session in the band at all, so the
    #3927 floor returned `no_band_matched_history` and the 09-24 session said "choose your
    own weight" on exactly the lifts that matter. When (and only when) the current band has
    no history, the anchor comes from the nearest band he HAS lifted in, picked by
    `band_reference.resolve_band` — the platform's one nearest-band rule — over this
    movement's own per-band session counts, and the best load inside that band is
    `routine_generator.band_matched_best` evaluated at that band. The row carries
    `anchor_band`, `anchor_date`, `anchor_band_distance_lb` and `fallback: "nearest_band"`.
    Widening is not capped at `band_reference.MAX_WIDENING` (a walking-VOLUME bound): the
    issue's rule is "the nearest band he has actually lifted in", so the bound is his own
    record, and the distance is stated on the row instead of being hidden by a refusal.
    "Bodyweight-adjusted" is the band SELECTION (nearest by bodyweight); the load itself is
    NOT scaled by a bodyweight ratio — there is no evidence base in this repo for scaling a
    machine or dumbbell load by bodyweight, and at a heavier current bodyweight the only
    direction such a scale could move is up, which §3 does not license. The ramp's 54 %
    week-1 share is the conservatism.
  * THE DISCOUNT HAS AN AGE. §3 says "after the 10–15 % detraining discount": a discount
    for detraining, so an anchor he set days ago is not detrained. It applies only when the
    anchor is at least `DETRAINING_ANCHOR_AGE_DAYS` (28) older than the program's block-1
    start (`program_structure.BLOCK_CALENDAR['block_1_start']`, 2026-09-24). Measured to
    the block start rather than to each session's date, so the decision is FIXED per anchor
    for the whole program: an age measured to the session date would flip an in-cycle anchor
    to discounted four weeks in and cut the load 10 % mid-ramp, against "Loads HOLD". 28 d
    is population-derived (ADR-105 rule 4): short-term training cessation of under ~4 weeks
    largely preserves maximal strength in trained lifters (Mujika & Padilla 2000, Sports Med
    30(2); McMaster et al. 2013, Sports Med 43(6)); the owner's own calibration of the
    10–15 % band came from a ~10-week layoff (`owner_redlines.load_anchoring.note`), well
    past it. Every anchor set in cycle 17 before block 1 (genesis 2026-09-06, 18 d earlier)
    sits inside the 28 d, so none is discounted.
"""

from __future__ import annotations

from typing import Any

from training.rep_scheme import load_step_kg

ISSUE = "#4090"
SECTION = "TRAINING_PROGRAM_v0.3.md §3 — 'Start at 60–65 % of the band-matched historical anchor after the 10–15 % detraining discount'"

# #4107 — the detraining discount applies to an anchor at least this many days older than
# block 1's start. Population-derived (ADR-105 rule 4): < ~4 weeks of cessation largely
# preserves maximal strength (Mujika & Padilla 2000; McMaster et al. 2013). See the module
# docstring for why the age is measured to the block start and not to the session date.
DETRAINING_ANCHOR_AGE_DAYS = 28

FALLBACK_NEAREST_BAND = "nearest_band"

# #4388: what the week's percentage is a share of. Band e1RM is the rule; the anchor set's own
# load is the novel-again exception (the detraining discount applies), unchanged from #4090.
BASE_BAND_E1RM = "band_e1rm"
BASE_ANCHOR_SET = "anchor_set"
_BASE_LABEL = {BASE_BAND_E1RM: "band e1RM", BASE_ANCHOR_SET: "band anchor set (novel-again: an old anchor's e1RM is not today's)"}


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
            "discount": "owner_redlines.REDLINES['load_anchoring']['detraining_discount_pct'] ("
            + str(anchoring.get("detraining_discount_provenance") or anchoring.get("provenance"))
            + ")",
            "section": SECTION,
        },
    }


def ramp_pct(week: int | None, p: dict[str, Any] | None = None) -> int:
    """The week's share of the ramp's base (band e1RM, or a novel-again anchor set — #4388), in whole percent. Week < 1 (or unknown) is week 1."""
    p = p or params()
    w = max(1, int(week or 1))
    return min(p["start_pct"] + p["step_pct_per_wk"] * (w - 1), p["cap_pct"])


def _floor_half_kg(kg: float) -> float:
    return int(kg * 2) / 2


def band_e1rm_kg(best_kg: float, reps: list[int] | None) -> float:
    """Epley e1RM of the anchor set. No reps recorded -> the load itself (the conservative read)."""
    r = max([int(x) for x in (reps or []) if x] or [0])
    return float(best_kg) * (1 + r / 30.0) if r > 0 else float(best_kg)


def min_reps_of(sets: list[Any] | None) -> int | None:
    """The lowest rep floor among an exercise's working sets (#4408), or None when none says one.

    Reads an IR `Set` / wire dict (`rep_range_start`, else `reps`) and a `program_structure`
    exposure set (`reps: [lo, hi]`). Warm-ups are not working sets and are skipped."""
    lows: list[int] = []
    for s in sets or []:
        get = s.get if isinstance(s, dict) else (lambda k, _s=s: getattr(_s, k, None))
        if str(get("type") or "normal").lower() == "warmup":
            continue
        lo = get("rep_range_start")
        if lo is None:
            reps = get("reps")
            lo = reps[0] if isinstance(reps, (list, tuple)) and reps else reps
        try:
            n = int(lo)
        except (TypeError, ValueError):
            continue
        if n > 0:
            lows.append(n)
    return min(lows) if lows else None


def achieved_hold(
    template_id: str | None,
    history_index: dict[str, list],
    weight_index: dict[str, float] | None,
    current_weight_lb: float | None,
    *,
    min_reps: int | None,
    as_of: str | None = None,
    tolerance_days: int | None = None,
    p: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """The heaviest load moved for >= `min_reps` at the current band this cycle, before `as_of` — or None (#4408)."""
    from training.band_reference import band_key
    from training.exercise_history import BODYWEIGHT_TOLERANCE_DAYS, nearest_bodyweight

    if not template_id or not current_weight_lb or not min_reps:
        return None
    p = p or params()
    band = band_key(float(current_weight_lb))
    tol = BODYWEIGHT_TOLERANCE_DAYS if tolerance_days is None else tolerance_days
    best: dict[str, Any] | None = None
    for s in (history_index or {}).get(template_id) or []:
        d = str(s.get("date") or "")
        if (as_of and d >= as_of) or anchor_discount(d, p)[1]["applies"]:
            continue
        lbs = nearest_bodyweight(d, weight_index, tol)
        if lbs is None or band_key(lbs) != band:
            continue
        for st in s.get("sets") or []:
            w, r = float(st.get("weight_kg") or 0), int(st.get("reps") or 0)
            if w > 0 and r >= int(min_reps) and (best is None or (w, d) > (best["weight_kg"], best["date"])):
                best = {"weight_kg": w, "reps": r, "date": d, "bodyweight_lb": round(float(lbs), 1), "band": band}
    return best


def block_1_start() -> str:
    """The program's block-1 start — the ONE date the anchor's age is measured to (#4107)."""
    from training import program_structure

    return str(program_structure.BLOCK_CALENDAR["block_1_start"])


def anchor_discount(anchor_date: str | None, p: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    """(discount %, the ruling) for one anchor (#4107).

    The deepest documented discount when the anchor is at least `DETRAINING_ANCHOR_AGE_DAYS`
    older than block 1's start; 0 when it is younger (a load set this cycle is not detrained,
    and discounting it would take the ramp twice). An anchor with no readable date is treated
    as old — the conservative read, and the #4090 behaviour."""
    from common.pacific_time import parse_day_key

    p = p or params()
    start = block_1_start()
    a, b = parse_day_key(str(anchor_date or "")[:10]), parse_day_key(start)
    age = (b - a).days if (a is not None and b is not None) else None
    applies = age is None or age >= DETRAINING_ANCHOR_AGE_DAYS
    pct = int(p["discount_pct"]) if applies else 0
    return pct, {
        "applies": applies,
        "discount_pct": pct,
        "anchor_date": anchor_date,
        "anchor_age_days_at_block_1": age,
        "threshold_days": DETRAINING_ANCHOR_AGE_DAYS,
        "measured_to": f"block 1 start {start}",
        "rule": (
            f"the {p['discount_pct']}% detraining discount applies to an anchor >= {DETRAINING_ANCHOR_AGE_DAYS} d older than "
            f"block 1 ({start}); younger anchors are this cycle's and are not detrained (#4107)"
        ),
        "threshold_provenance": (
            "population-derived (ADR-105 rule 4): < ~4 weeks of training cessation largely preserves maximal strength "
            "(Mujika & Padilla 2000, Sports Med 30(2); McMaster et al. 2013, Sports Med 43(6))"
        ),
    }


def ramp_floor(floor: dict[str, Any], week: int | None) -> dict[str, Any]:
    """A `prescription_floor` result, re-based onto the week's ramp. Pure; returns a copy.

    #4388: the week's percentage is of band e1RM, except for a novel-again anchor (the
    detraining discount applies), which keeps the anchor-set base — `ramp.base` says which.

    Recomputes from `best_kg` (the undiscounted band anchor), so a layoff discount the floor
    may already have taken is never applied twice. A floor without a band-matched anchor
    passes through unchanged — no anchor, no ramp, and the status says which absence.
    The detraining discount is `anchor_discount`'s: the deep end for an old anchor, 0 for
    one set this cycle (#4107)."""
    out = dict(floor or {})
    if out.get("status") != "ok" or not out.get("best_kg"):
        return out
    p = params()
    pct = ramp_pct(week, p)
    anchor = float(out["best_kg"])
    basis = out.get("basis") or {}
    discount, discount_ruling = anchor_discount(basis.get("date"), p)
    e1rm = band_e1rm_kg(anchor, basis.get("reps"))
    # #4388: the percentage is of band e1RM (the redline's wording and the owner's own 09-28
    # authoring); a novel-again anchor — one the detraining discount applies to — keeps the
    # anchor-set base, unchanged from #4090/#4107 (see the module docstring).
    base_kind = BASE_ANCHOR_SET if discount_ruling["applies"] else BASE_BAND_E1RM
    base = anchor if base_kind == BASE_ANCHOR_SET else e1rm
    discounted = base * (100 - discount) / 100.0
    raw = discounted * pct / 100.0
    cap_kg = e1rm * p["cap_pct"] / 100.0
    # #4388 owner ruling: NEAREST 5-lb step for the ramp, DOWN for the cap — one helper (rep_scheme)
    top = min(load_step_kg(raw), load_step_kg(cap_kg, down=True))
    out["floor_kg"] = top
    out["discount_pct"] = discount
    out["layoff_reason"] = None
    out["ramp"] = {
        "week": max(1, int(week or 1)),
        "ramp_pct": pct,
        "discount_pct": discount,
        "discount": discount_ruling,
        "anchor_kg": anchor,
        "band_e1rm_kg": round(e1rm, 3),
        "base": base_kind,
        "base_kg": round(base, 3),
        "discounted_base_kg": round(discounted, 3),
        "cap_kg": round(cap_kg, 3),
        "cap_bound": cap_kg < raw,
        "top_kg": top,
        "pct_of_anchor": round(100.0 * top / anchor, 1),
        "pct_of_band_e1rm": round(100.0 * top / e1rm, 1),
        "pct_of_discounted_base": round(100.0 * top / discounted, 1),
        "rule": (
            f"v0.3 §3 entry ramp: {pct}% of the {_BASE_LABEL[base_kind]} after a {discount}% detraining discount "
            f"(start {p['start_pct']}%, +{p['step_pct_per_wk']}%/wk to week {p['ramp_to_week']}, <= {p['cap_pct']}% of band e1RM, "
            f"then {p['then']})"
        ),
        "provenance": p["provenance"],
    }
    return out


def _per_band_sessions(
    template_id: str,
    history_index: dict[str, list],
    weight_index: dict[str, float] | None,
    as_of: str | None,
    tolerance_days: int | None,
) -> dict[str, dict[str, Any]]:
    """This movement's LOADED, weighed sessions per bodyweight band — the evidence
    `resolve_band` ranks. Same filters as `band_matched_best` (as_of, weigh-in tolerance, a
    top set above 0), so a band offered here is one `band_matched_best` can answer from."""
    from training.band_reference import band_key
    from training.exercise_history import BODYWEIGHT_TOLERANCE_DAYS, nearest_bodyweight

    tol = BODYWEIGHT_TOLERANCE_DAYS if tolerance_days is None else tolerance_days
    bands: dict[str, dict[str, Any]] = {}
    for s in (history_index or {}).get(template_id) or []:
        d = str(s.get("date") or "")
        if as_of and d >= as_of:
            continue
        if float(s.get("top_weight_kg") or 0) <= 0:
            continue
        lbs = nearest_bodyweight(d, weight_index, tol)
        if lbs is None:
            continue
        # `n_weighins` is the count `resolve_band` gates on (min 1 here: one session IS
        # history). `n_days` is 0 on purpose: resolve_band's first pass ranks by the
        # walking-VOLUME floor (21 effective days), which is not a load question — a band
        # with more sessions must never outrank a NEARER band with fewer.
        row = bands.setdefault(band_key(lbs), {"n_weighins": 0, "n_days": 0, "sessions": 0})
        row["n_weighins"] += 1
        row["sessions"] += 1
    return bands


def nearest_band_anchor(
    template_id: str | None,
    history_index: dict[str, list],
    weight_index: dict[str, float] | None,
    current_weight_lb: float | None,
    as_of: str | None = None,
    tolerance_days: int | None = None,
) -> dict[str, Any] | None:
    """The band anchor from the NEAREST band with history, or None (#4107).

    `band_reference.resolve_band` picks the band (nearest by bodyweight; ties to the heavier
    band, its own rule), widened as far as his record reaches; `band_matched_best` then
    answers inside that band, so the anchor is the same definition the in-band floor uses."""
    from training.band_reference import BAND_WIDTH_LB, band_key, band_low, resolve_band
    from training.routine_generator import band_matched_best

    if not template_id or not current_weight_lb:
        return None
    bands = _per_band_sessions(template_id, history_index, weight_index, as_of, tolerance_days)
    if not bands:
        return None
    target = band_low(band_key(float(current_weight_lb)))
    reach = max(abs(band_low(k) - target) // BAND_WIDTH_LB for k in bands)
    picked = resolve_band(float(current_weight_lb), bands, max_widening=max(1, int(reach)), min_weighins=1)
    if not picked or picked.get("exact"):
        return None
    anchor = band_matched_best(
        template_id, history_index, weight_index, float(band_low(picked["band"])), as_of=as_of, tolerance_days=tolerance_days
    )
    if anchor.get("status") != "ok":
        return None
    anchor["fallback"] = {
        "kind": FALLBACK_NEAREST_BAND,
        "band_requested": picked["band_requested"],
        "anchor_band": picked["band"],
        "anchor_band_distance_lb": picked["band_distance_lb"],
        "sessions_in_anchor_band": int(picked.get("sessions") or 0),
        "bands_with_history": sorted(bands, key=band_low),
        "resolver": "band_reference.resolve_band (nearest by bodyweight, ties to the heavier band), widened to his whole record",
        "load_scaling": "none — the load is the anchor band's best as lifted; bodyweight picks the band, it does not scale the load",
    }
    return anchor


def v03_floor(
    template_id: str | None,
    history_index: dict[str, list],
    weight_index: dict[str, float] | None,
    current_weight_lb: float | None,
    days_since_last_workout: int | None = None,
    layoff_days: int | None = None,
    as_of: str | None = None,
    tolerance_days: int | None = None,
    *,
    week: int | None,
    min_reps: int | None = None,
) -> dict[str, Any]:
    """THE v0.3 load for one movement (#4090 + #4107 + #4408): band anchor -> nearest-band
    fallback -> the week's ramp -> the achieved-load hold. Same leading signature as
    `routine_generator.prescription_floor`, so `_enforce_load_floors` takes either. The ramp
    re-bases from the undiscounted anchor and applies its own discount; the layoff arguments
    decide only whether the #4408 hold applies (a layoff is something to re-enter from).

    Every returned row names its anchor: `anchor_band`, `anchor_date`, and `fallback`
    (None when the current band answered, "nearest_band" when it did not)."""
    from training.routine_generator import prescription_floor

    floor = prescription_floor(
        template_id,
        history_index,
        weight_index,
        current_weight_lb,
        days_since_last_workout=None,
        as_of=as_of,
        tolerance_days=tolerance_days,
    )
    floor["fallback"] = None
    if floor.get("status") == "no_band_matched_history":
        near = nearest_band_anchor(template_id, history_index, weight_index, current_weight_lb, as_of=as_of, tolerance_days=tolerance_days)
        if near is not None:
            in_band = {k: floor.get(k) for k in ("sessions_in_band", "sessions_other_band", "sessions_unweighed")}
            floor.update({k: near[k] for k in ("best_kg", "basis", "status")})
            floor["floor_kg"] = float(near["best_kg"])
            floor["fallback"] = FALLBACK_NEAREST_BAND
            floor["fallback_detail"] = {**near["fallback"], "current_band_counts": in_band}
    ramped = ramp_floor(floor, week)
    _apply_hold(
        ramped,
        template_id,
        history_index,
        weight_index,
        current_weight_lb,
        days_since_last_workout,
        layoff_days,
        as_of,
        tolerance_days,
        min_reps,
    )
    basis = ramped.get("basis") or {}
    ramped["anchor_band"] = (ramped.get("fallback_detail") or {}).get("anchor_band") or (ramped.get("band") if basis else None)
    ramped["anchor_date"] = basis.get("date")
    return ramped


def _lifting_gap_days(history_index: dict[str, list], as_of: str | None) -> int | None:
    """Days from the last loaded session on record to `as_of` — the layoff read from the evidence,
    whatever a caller passes (the cron hands the generator a constant). None: nothing on record."""
    from common.pacific_time import parse_day_key

    latest = max(
        (str(s.get("date") or "") for ss in (history_index or {}).values() for s in ss or [] if str(s.get("date") or "") < (as_of or "~")),
        default="",
    )
    a, b = parse_day_key(str(as_of or "")), parse_day_key(latest)
    return (a - b).days if (a is not None and b is not None) else None


def _apply_hold(
    ramped: dict[str, Any],
    template_id: str | None,
    history_index: dict[str, list],
    weight_index: dict[str, float] | None,
    current_weight_lb: float | None,
    days_since_last_workout: int | None,
    layoff_days: int | None,
    as_of: str | None,
    tolerance_days: int | None,
    min_reps: int | None,
) -> None:
    """#4408, IN PLACE: raise a ramped floor to the achieved this-cycle load at this band (module docstring)."""
    r = ramped.get("ramp")
    if not r:
        return
    if ramped.get("fallback"):
        r["hold"] = {"applies": False, "achieved": None, "min_reps": min_reps, "reason": "nearest-band anchor: nothing lifted at this band"}
        return
    from training.routine_generator import LAYOFF_DAYS_DEFAULT

    threshold = LAYOFF_DAYS_DEFAULT if layoff_days is None else int(layoff_days)
    gap = _lifting_gap_days(history_index, as_of)
    layoff = any(d is not None and int(d) >= threshold for d in (days_since_last_workout, gap))
    hold = (
        None
        if layoff
        else achieved_hold(
            template_id, history_index, weight_index, current_weight_lb, min_reps=min_reps, as_of=as_of, tolerance_days=tolerance_days
        )
    )
    applies = hold is not None and float(hold["weight_kg"]) > float(ramped.get("floor_kg") or 0) + 1e-9
    r["hold"] = {
        "applies": applies,
        "achieved": hold,
        "min_reps": min_reps,
        "layoff": layoff,
        "layoff_evidence": {"caller_days_since_last_workout": days_since_last_workout, "record_gap_days": gap, "threshold_days": threshold},
        "ramp_top_kg": ramped.get("floor_kg"),
        "rule": (
            "a load already moved for the set's rep floor at this bodyweight band, this cycle, with no layoff, is never ramped "
            "under — the ramp applies only when there is something to re-enter from (#4408)"
        ),
    }
    if applies and hold:
        ramped["floor_kg"] = float(hold["weight_kg"])
        r["top_kg"] = ramped["floor_kg"]


def render_ramp_cue(floor: dict[str, Any]) -> str:
    """The reader-facing line for a ramped load. Factual: the load, the share, the anchor, the date."""
    from training.routine_generator import _fmt_load

    r = (floor or {}).get("ramp") or {}
    if not r or not floor.get("floor_kg"):
        return ""
    hold = r.get("hold") or {}
    if hold.get("applies"):
        a = hold["achieved"]
        return (
            f"Week {r['week']} load {_fmt_load(float(floor['floor_kg']))} — the load you already moved: {_fmt_load(float(a['weight_kg']))} "
            f"x {a['reps']} on {a['date']} at {a['bodyweight_lb']} lb, this band, no layoff. The entry ramp "
            f"({r['ramp_pct']}% = {_fmt_load(float(hold['ramp_top_kg']))}) is for re-entry and never goes under an achieved load. "
            "Down on the day if you must, never up."
        )
    basis = floor.get("basis") or {}
    reps = "/".join(str(x) for x in (basis.get("reps") or []))
    got = _fmt_load(float(basis.get("weight_kg") or r["anchor_kg"])) + (f" x {reps}" if reps else "")
    discount = (
        f"after the {r['discount_pct']}% detraining discount" if r.get("discount_pct") else "no detraining discount (a this-cycle anchor)"
    )
    where = f"at {basis.get('bodyweight_lb')} lb"
    fb = floor.get("fallback_detail") or {}
    if floor.get("fallback") == FALLBACK_NEAREST_BAND and fb:
        where += f", nearest band you have lifted in: {fb.get('anchor_band')} — none yet at {fb.get('band_requested')}"
    if r.get("base") == BASE_BAND_E1RM:
        share = f"{r['ramp_pct']}% of your band e1RM {_fmt_load(float(r['band_e1rm_kg']))}"
    else:
        share = f"{r['ramp_pct']}% of your band anchor"
    return (
        f"Week {r['week']} load {_fmt_load(float(floor['floor_kg']))} — {share} {discount} "
        f"(anchor {got} on {basis.get('date')} {where}; v0.3 §3). "
        "Down on the day if you must, never up."
    )


PROVENANCE_FIELDS = ("anchor_band", "anchor_date", "fallback", "fallback_detail")


def _provenance_fields(floor: dict[str, Any]) -> dict[str, Any]:
    """The anchor's provenance, copied onto every audit/planner row (#4107)."""
    return {k: (floor or {}).get(k) for k in PROVENANCE_FIELDS}


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
    writes into the routine — both go through `v03_floor` (#4107)."""
    from training.exercise_history import nearest_bodyweight

    current = nearest_bodyweight(target_date, weight_index)
    summary: dict[str, Any] = {"status": "applied" if current else "no_current_bodyweight", "week": week, "params": params()}
    summary["current_bodyweight_lb"] = round(float(current), 1) if current else None
    for e in rx.get("exposures") or []:
        key = e.get("movement_key")
        # #4409: a kept title-only in-block variant carries its wire template id on the exposure
        tid = (((catalog_movements or {}).get(key) or {}).get("hevy_template_id_hint") or e.get("template_id")) if key else None
        if not current:
            e["load"] = {"status": "no_current_bodyweight"}
            continue
        # the ONE v0.3 load path (#4107) — the generator and the chat gate call the same function
        ramped = v03_floor(tid, history_index, weight_index, current, as_of=target_date, week=week, min_reps=min_reps_of(e.get("sets")))
        load: dict[str, Any] = {"status": ramped.get("status"), "template_id": tid, "top_kg": None}
        load.update(_provenance_fields(ramped))
        if ramped.get("ramp"):
            top = float(ramped["floor_kg"])
            load.update({"top_kg": top, "ramp": ramped["ramp"], "basis": ramped.get("basis")})
            pct = next((s.get("pct_of_top") for s in e.get("sets") or [] if s.get("kind") == "back_off"), None)
            if pct is not None:
                load["back_off_kg"] = _floor_half_kg(top * pct / 100.0)
        e["load"] = load
    return summary
