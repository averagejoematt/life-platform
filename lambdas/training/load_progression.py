"""load_progression.py — the engine-authored double progression (#5052, epic #5050).

Before this module no code read the gain rule. Loads came from the entry ramp (`load_ramp`)
and the band-matched floor (`routine_generator.prescription_floor`), the chat path's loads
were written by a model, and the adherence grader read every set the owner raised himself
as a breach of the routine's RPE ceiling — 20 of 22 graded sessions came back
`as_prescribed: no`, mostly for beating the plan.

ONE RULE, READ FROM THE CHARTER. `config/training_charter.json` `progression.gain_rule` is
the owner's double-progression ruling (#4503 OD5), moved there from `owner_redlines` by this
issue; the effort ceilings are the charter's `effort_ceilings`. Nothing here hard-codes a
step size, an exposure count or an RPE number: every one is `charter_value(...)`.

Per movement, `next_prescription` returns `{next_load_kg, next_reps, basis, reason}`:

  * `re_entry`    — a layoff / re-entry is in force; the entry floor or ramp sets the load and
                    progression waits (the ramp is its own rule).
  * `hold`        — the rule has nothing to add (or a refusal — a deload the owner applied —
                    holds the load); the reason says how far the trigger is.
  * `floor_raise` — he carried a load above the engine's load, logged at or under the
                    effort ceiling (an overage within `overage_tolerance_rpe` is not a breach):
                    that load is the next FLOOR. A raised load above ceiling + tolerance is a
                    breach and is never a floor.
  * `step`        — the top set reached the top of the slot's rep range on the last
                    `consecutive_same_type_exposures` same-type exposures, each at or under the
                    ceiling (the RPE is a veto only, no tolerance; an unlogged RPE is not
                    evidence): one step — `step_pct` of the load in whole `step_lb` steps,
                    never less than one — reps back to the bottom of the range.

The load never goes DOWN here. `apply_to_sets` only raises working sets, so the floor's
subtract-only guarantee (#3927) holds; a back-off pass that runs after re-derives from the
raised top set.

THE CEILING (#5058). The charter states a band per class — compounds, and the last set of an
isolation movement — and the owner's experience tier picks the bands in force; the ceiling is
the band's HIGH end (`progression.ceiling_tier` in the charter says so): a compound is a movement whose
catalog entry names an `anchor_family`; anything else is an isolation movement, whose earlier
sets read the compounds band and whose LAST working set reads the isolation band.

Pure: inputs are values the caller already loaded; the only read is the charter (bundled,
cached, fail-soft). No boto3, no clock.
"""

from __future__ import annotations

from typing import Any, Iterable

from training.rep_scheme import LB_IN_KG
from training.training_charter import charter_value, charter_version

BASIS_FLOOR_RAISE = "floor_raise"
BASIS_HOLD = "hold"
BASIS_STEP = "step"
BASIS_RE_ENTRY = "re_entry"
BASES = (BASIS_FLOOR_RAISE, BASIS_HOLD, BASIS_STEP, BASIS_RE_ENTRY)

CLASS_COMPOUND = "compound"
CLASS_ISOLATION = "isolation"

LOAD_TOLERANCE_KG = 0.05
"""A float-compare guard only (Hevy stores kg to 2 dp; 185 lb is 83.9146... kg) — the same
guard `stall_detector.LOAD_TOLERANCE_KG` uses. Not a threshold."""

_WARMUP = {"warmup", "warm_up", "warm-up"}


# ── the charter reads ─────────────────────────────────────────────────────────────


def gain_rule() -> dict[str, Any]:
    """The charter's `progression.gain_rule` ({} when the charter cannot be read)."""
    return dict(charter_value("progression.gain_rule", {}) or {})


def effort_limits() -> dict[str, Any]:
    """The ceilings this module grades against, read from `effort_ceilings` through
    `training.effort_ceilings` (#5058: the owner's experience tier picks the class bands).

    `ceiling` is the HIGH end of the current tier's band (the charter's
    `experience_tier.ceiling_is`), `limit` = ceiling + the charter's `overage_tolerance_rpe` —
    the highest RPE that is NOT a breach. None when the charter is unreadable: absence is
    absence, never a default ceiling (ADR-105)."""
    from training import effort_ceilings as ec

    tol = ec.tolerance_rpe(charter_value)
    tier = ec.current_tier(charter_value)
    out: dict[str, Any] = {"tolerance_rpe": tol, "experience_tier": tier}
    for name, key in (("compound", ec.COMPOUNDS), ("last_isolation_set", ec.LAST_ISOLATION_SET)):
        ceiling = ec.ceiling(key, charter_value)
        out[name] = {
            "ceiling_rpe": ceiling,
            "limit_rpe": (ceiling + tol) if ceiling is not None and tol is not None else None,
            "source": f"effort_ceilings.experience_tier.{tier}.{key} (high end)",
        }
    return out


def movement_class(catalog_entry: dict[str, Any] | None) -> str:
    """compound | isolation — a catalog `anchor_family` is a compound pattern."""
    return CLASS_COMPOUND if (catalog_entry or {}).get("anchor_family") else CLASS_ISOLATION


def set_ceiling(cls: str, last_set: bool, limits: dict[str, Any] | None = None) -> dict[str, Any]:
    """The {ceiling_rpe, limit_rpe} one working set is graded against."""
    lim = limits if limits is not None else effort_limits()
    if cls == CLASS_ISOLATION and last_set and (lim.get("last_isolation_set") or {}).get("ceiling_rpe") is not None:
        return lim["last_isolation_set"]
    return lim.get("compound") or {"ceiling_rpe": None, "limit_rpe": None}


def grading_limits(cls: str, limits: dict[str, Any] | None = None) -> dict[str, Any]:
    """The shape `intensity_prescription.grade_sets(progression=...)` reads, minus the load."""
    lim = limits if limits is not None else effort_limits()
    return {
        "movement_class": cls,
        "limit_rpe": set_ceiling(cls, False, lim)["limit_rpe"],
        "last_set_limit_rpe": set_ceiling(cls, True, lim)["limit_rpe"] if cls == CLASS_ISOLATION else None,
    }


def rule_summary() -> dict[str, Any]:
    """`plan_engine.constraint_block['progression']`: the rule and the ceilings as read, stamped."""
    return {
        "gain_rule": gain_rule(),
        "self_raised_load": charter_value("progression.self_raised_load", {}) or {},
        "effort_limits": effort_limits(),
        "bases": list(BASES),
        "applied_by": "routine_generator draft path (after the floor, before warm-ups) and load_ramp.annotate_prescription",
        "charter_version": charter_version(),
    }


# ── helpers ───────────────────────────────────────────────────────────────────────


def _lb(kg: float) -> str:
    lb = float(kg) / LB_IN_KG
    return f"{lb:.0f} lb" if abs(lb - round(lb)) < 0.05 else f"{lb:.1f} lb"


def _num(v: Any) -> float | None:
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def _day(date: Any) -> str:
    """'2026-10-16' -> '10-16' (the reason string stays short)."""
    s = str(date or "")
    return s[5:10] if len(s) >= 10 else s


def working_sets(sets: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Loaded, non-warm-up sets (both wire spellings of the type field)."""
    out = []
    for s in sets or []:
        if str(s.get("type") or s.get("set_type") or "normal").strip().lower() in _WARMUP:
            continue
        if (_num(s.get("weight_kg")) or 0) <= 0 or (_num(s.get("reps")) or 0) <= 0:
            continue
        out.append(s)
    return out


def top_sets(session: dict[str, Any], cls: str, limits: dict[str, Any]) -> dict[str, Any]:
    """The heaviest load in one session and every working set carried at it, each with its ceiling."""
    work = working_sets(session.get("sets"))
    if not work:
        return {"load_kg": None, "sets": []}
    top = max(float(s["weight_kg"]) for s in work)
    rows = []
    for i, s in enumerate(work):
        if float(s["weight_kg"]) < top - LOAD_TOLERANCE_KG:
            continue
        c = set_ceiling(cls, i == len(work) - 1, limits)
        rows.append({"reps": int(_num(s.get("reps")) or 0), "rpe": _num(s.get("rpe")), **c})
    return {"load_kg": top, "sets": rows}


def step_kg(load_kg: float, rule: dict[str, Any]) -> float | None:
    """`step_pct` of the load in whole `step_lb` steps, never under one step (kg)."""
    step_lb, pct = _num(rule.get("step_lb")), _num(rule.get("step_pct")) or 0.0
    if not step_lb:
        return None
    load_lb = float(load_kg) / LB_IN_KG
    steps = max(1, int((load_lb * pct / 100.0) // step_lb))
    return steps * step_lb * LB_IN_KG


def _at_top(t: dict[str, Any], rep_hi: int) -> bool:
    """The exposure's top set reached the top of the range, at or under its ceiling (RPE logged)."""
    return any(
        r["reps"] >= rep_hi and r["rpe"] is not None and r["ceiling_rpe"] is not None and r["rpe"] <= r["ceiling_rpe"] for r in t["sets"]
    )


def _breach(t: dict[str, Any]) -> dict[str, Any] | None:
    """The first top-load set logged above ceiling + tolerance (or None)."""
    for r in t["sets"]:
        if r["rpe"] is not None and r["limit_rpe"] is not None and r["rpe"] > r["limit_rpe"]:
            return r
    return None


def _unlogged(t: dict[str, Any]) -> bool:
    return any(r["rpe"] is None for r in t["sets"])


def _same_type(
    sessions: list[dict[str, Any]] | None, exposure: str | None, rep_lo: int, cls: str, limits: dict[str, Any]
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """The exposures that count for this slot, most recent first.

    A session tagged with its exposure counts when the tag matches. An untagged one (the
    `exercise_history` index carries no slot) counts when its top load was moved for at
    least the slot's bottom reps — the #4408 hold's own test — so a heavy day's 5-rep
    top set never becomes a volume slot's floor."""
    out = []
    for s in sessions or []:
        if exposure and s.get("exposure") and s.get("exposure") != exposure:
            continue
        t = top_sets(s, cls, limits)
        if not t["load_kg"]:
            continue
        if not (exposure and s.get("exposure")) and not any(r["reps"] >= rep_lo for r in t["sets"]):
            continue
        out.append((s, t))
    return out


# ── the rule ──────────────────────────────────────────────────────────────────────


def next_prescription(
    sessions: list[dict[str, Any]] | None,
    *,
    current_kg: float | None,
    rep_range: tuple[int, int] | None,
    cls: str,
    exposure: str | None = None,
    re_entry_reason: str | None = None,
    hold_reason: str | None = None,
    rule: dict[str, Any] | None = None,
    limits: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The next load and rep target for ONE movement.

    `sessions`: that movement's performed sessions, MOST RECENT FIRST, each
    `{date, sets: [{weight_kg, reps, rpe, type?}], exposure?, prescribed_kg?}` — the
    `exercise_history` index shape; `exposure` (heavy / volume / ...) and the prescription
    are used when on file. `current_kg`: the load the engine already holds for this slot
    (the floor / ramp). `rep_range`: the slot's (bottom, top)."""
    rule = gain_rule() if rule is None else rule
    limits = effort_limits() if limits is None else limits
    out: dict[str, Any] = {
        "next_load_kg": current_kg,
        "next_reps": None,
        "basis": BASIS_HOLD,
        "reason": "",
        "movement_class": cls,
        "charter_version": charter_version(),
    }
    if re_entry_reason:
        out.update(basis=BASIS_RE_ENTRY, reason=f"re-entry: {re_entry_reason}; the entry load stands, progression resumes after it")
        return out
    if not rule or not rep_range:
        out["reason"] = "hold: no gain rule on the charter" if not rule else "hold: the slot names no rep range"
        return out
    rep_lo, rep_hi = int(rep_range[0]), int(rep_range[1])
    exposures = _same_type(sessions, exposure, rep_lo, cls, limits)
    if not exposures:
        out["reason"] = f"hold: no performed session of this movement for {rep_lo}+ reps on record"
        return out
    if hold_reason:
        out["reason"] = f"hold: {hold_reason}"
        return out

    cur = float(current_kg) if current_kg else 0.0
    last, last_top = exposures[0]
    load = float(last_top["load_kg"])
    need = int(rule.get("consecutive_same_type_exposures") or 0)
    run = exposures[:need] if need else []
    breach = _breach(last_top)

    if (
        need
        and len(run) == need
        and load >= cur - LOAD_TOLERANCE_KG
        and all(abs(float(t["load_kg"]) - load) <= LOAD_TOLERANCE_KG and _at_top(t, rep_hi) and not _breach(t) for _s, t in run)
    ):
        inc = step_kg(load, rule)
        if inc:
            ceiling = max(r["ceiling_rpe"] for _s, t in run for r in t["sets"] if r["ceiling_rpe"] is not None)
            days = " and ".join(_day(s.get("date")) for s, _t in reversed(run))
            out.update(
                next_load_kg=load + inc,
                next_reps=rep_lo,
                basis=BASIS_STEP,
                reason=f"+{_lb(inc)} to {_lb(load + inc)}: {need} top sets at the top of {rep_lo}-{rep_hi}, RPE <= {ceiling:g}, {days}; reps back to {rep_lo}",
            )
            return out

    if load > cur + LOAD_TOLERANCE_KG:
        if breach is not None:
            out["reason"] = (
                f"hold {_lb(cur) if cur else 'the floor'}: {_lb(load)} on {_day(last.get('date'))} was logged at RPE {breach['rpe']:g}, "
                f"above the {cls} ceiling RPE {breach['ceiling_rpe']:g} + {breach['limit_rpe'] - breach['ceiling_rpe']:g} — a breach, not a floor"
            )
            return out
        if _unlogged(last_top):
            out["reason"] = (
                f"hold: {_lb(load)} on {_day(last.get('date'))} has a set with no RPE logged — not evidence it sat under the ceiling"
            )
            return out
        mine = _num(last.get("prescribed_kg"))
        who = "you raised it" if mine is not None and load > mine + LOAD_TOLERANCE_KG else "you carried it"
        top_rpe = max(r["rpe"] for r in last_top["sets"])
        out.update(
            next_load_kg=load,
            basis=BASIS_FLOOR_RAISE,
            reason=f"floor {_lb(load)}: {who} on {_day(last.get('date'))} at RPE <= {top_rpe:g}, within the {cls} ceiling",
        )
        return out

    hits = 0
    for _s, t in exposures[: max(need, 1)]:
        if abs(float(t["load_kg"]) - load) <= LOAD_TOLERANCE_KG and _at_top(t, rep_hi) and not _breach(t):
            hits += 1
        else:
            break
    out["reason"] = f"hold {_lb(cur or load)}: {hits} of {need} top sets at the top of {rep_lo}-{rep_hi} at or under the ceiling"
    return out


def apply_to_sets(sets: list[Any], prog: dict[str, Any]) -> list[str]:
    """Write a `step` / `floor_raise` onto a block's working sets, IN PLACE — raise only, never lower.

    The rep RANGE is left as the slot wrote it; a step's "reps back to the bottom" is the
    reason line the note carries. IR `Set`s and dicts both work (the floor pass's own
    convention). Returns one line per change."""
    if prog.get("basis") not in (BASIS_STEP, BASIS_FLOOR_RAISE) or not prog.get("next_load_kg"):
        return []
    target = float(prog["next_load_kg"])
    lines: list[str] = []
    for i, s in enumerate(sets or []):
        get = s.get if isinstance(s, dict) else (lambda k, _s=s: getattr(_s, k, None))
        if str(get("type") or "normal").lower() in _WARMUP or get("distance_meters") or get("duration_seconds"):
            continue
        cur = _num(get("weight_kg"))
        if cur is None or cur < target - LOAD_TOLERANCE_KG:
            _put(s, "weight_kg", target)
            lines.append(f"set {i + 1}: {_lb(cur) if cur else 'no load'} -> {_lb(target)} ({prog['basis']})")
    return lines


def _put(s: Any, name: str, value: Any) -> None:
    if isinstance(s, dict):
        s[name] = value
    else:
        setattr(s, name, value)
