"""run_onramp.py — the run gate, the lower-leg prep and Stage 4, the run/walk on-ramp (#5090, epic #5067).

WHY THIS EXISTS

The owner ruled on 2026-10-18 that running is in the May plan. The run gate in
`owner_redlines.REDLINES['run_gate_lb']` names a "Stage 4" run/walk on-ramp that no code built, so
the gate could never open. His own record logs no run above the gate weight; running starts there
and scales down. This module is the gate, the prep before it and the on-ramp after it. Every number
is the training charter's (`gated_movements.running`, `gated_movements.lower_leg_prep`,
`cardio_menu.blocks.easy` / `run_walk`) read through `training_charter.charter_value()`.

WHAT IT DECIDES (pure: no I/O, no clock — every input is handed in)

  THE GATE — `gate_state(weight_lb, walking_weeks, pain_flags, stage4_done)`:
    closed   above the prep weight (`lower_leg_prep.from_lb`);
    prep     at or under the prep weight: calf + tibialis work and low-amplitude pogo hops on the
             lower days; the on-ramp waits for the gate weight AND the walking weeks;
    held     at or under the prep weight with a lower-leg strain flag (`training.steps_ramp`'s
             `strain_flag:` / `standing_constraint:` causes): the impact pauses — the pogo hops AND the
             run/walk (no run is placed) — and the on-ramp keeps its level, never losing it;
    open     at or under the gate weight, the walking weeks met, no hold: the on-ramp runs, and
             continuous running is unlocked once Stage 4 is completed (`stage4_done`);
    unknown  no weigh-in, or no charter — never read as closed or open (ADR-104).
  Every state carries its distance: lb to the prep and to the gate, walking weeks met / needed.

  THE WALKING WEEKS — `walking_weeks_status`: the newest consecutive completed weeks with at least
  `walking_hours_per_wk` of weight-bearing walking (the walking modality of `training.walking_volume`)
  and no lower-leg pain flag. A week whose hours or pain flags were not read breaks the run: an
  unread week is never a met week.

  THE PREP — `prep_exposures`: the charter's prescription on a lower day (the `split.sequence`
  names opening "lower", `cardio_menu.is_lower`), each item resolved to the first catalog key the
  generator may place (`movement_catalog.generator_eligible(..., prep_open=True)` — the carve-out
  from the plyometrics exclusion is the charter's list and nothing else).

  STAGE 4 — `stage_progress` over his logged run/walks (`performed_from_notes` reads the level, the
  RPE and a pain word off each treadmill/running note): two sessions at a level at or under the easy
  block's top RPE with no pain flag advance one level; a strain hold keeps him at his level (no session
  dated on or after the hold's start counts; an undated hold covers the whole record);
  `stage4_done` is the last level completed twice. `run_day_verdict` places a run: the gate open,
  under `max_runs_per_wk`, and not on a heavy lower day or the session either side of it in
  `split.sequence` (the day-level reading of "none within 24 h of a heavy lower session").
  `run_walk_block` is the block with its note; its minutes count toward the movement goal (a
  treadmill block, `cardio_menu.movement_minutes`).

Nothing here is medical: effort is by RPE and talk test.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Optional

from training import training_charter

RUN_ONRAMP_VERSION = "run-onramp@1.0.0"

CLOSED, PREP, HELD, OPEN, UNKNOWN = "closed", "prep", "held", "open", "unknown"
STATES = (CLOSED, PREP, HELD, OPEN, UNKNOWN)
HOLD_PREFIXES = ("strain_flag:", "standing_constraint:")
POGO_ITEM_WORD = "pogo"  # the prep item a strain hold pauses (the impact one); calf and tibialis work stay

_LEVEL_RE = re.compile(r"\b(?:L|level)\s*(\d+)\b", re.IGNORECASE)
_RPE_RE = re.compile(r"\bRPE\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
_RUN_WALK_RE = re.compile(r"\brun\s*/\s*walk\b|\brun-walk\b", re.IGNORECASE)


# ── the charter reads ─────────────────────────────────────────────────────────────────
def running() -> dict[str, Any]:
    return training_charter.charter_value("gated_movements.running", {}) or {}


def prep_cfg() -> dict[str, Any]:
    return training_charter.charter_value("gated_movements.lower_leg_prep", {}) or {}


def onramp() -> dict[str, Any]:
    return running().get("onramp") or {}


def history_from() -> Optional[str]:
    """The first day a run/walk session can exist (`onramp.history_from`): a Stage 4 reader reads back to it, so an
    early level never ages out of a rolling window."""
    v = onramp().get("history_from")
    return str(v)[:10] if v else None


def levels() -> list[dict[str, Any]]:
    out = []
    for lv in onramp().get("levels") or []:
        run, walk, rounds = int(lv["run_min"]), int(lv["walk_min"]), int(lv["rounds"])
        out.append({**lv, "total_min": (run + walk) * rounds})  # the last walk is the cool-down, inside the block
    return out


def easy_band() -> Optional[tuple[int, int]]:
    """The RPE band a run/walk is held to: the menu block the `run_walk` block names (`rpe_from`, the easy block)."""
    from training import cardio_menu  # noqa: PLC0415

    return cardio_menu.rpe_band(str(cardio_menu.block("run_walk").get("rpe_from") or "easy"))


def _num(v: Any) -> Optional[float]:
    try:
        return None if v is None or isinstance(v, bool) else float(v)
    except (TypeError, ValueError):
        return None


# ── the walking weeks ─────────────────────────────────────────────────────────────────
def walking_weeks_status(walking_weeks: Optional[Iterable[Mapping[str, Any]]]) -> dict[str, Any]:
    """`walking_weeks`: one row per completed week, `{week_start, hours, pain_flag}` (hours = the walking
    modality's hours; pain_flag None = not read). Counts the NEWEST consecutive weeks that meet the bar."""
    cfg = running()
    needed, bar = int(cfg.get("walking_weeks") or 0), _num(cfg.get("walking_hours_per_wk"))
    rows = sorted((dict(w) for w in walking_weeks or []), key=lambda w: str(w.get("week_start")), reverse=True)
    met, broken_by = 0, None
    verdicts = []
    for w in rows:
        hours = _num(w.get("hours"))
        if hours is None:
            v = "hours_not_read"
        elif bar is not None and hours < bar:
            v = "below_hours"
        elif w.get("pain_flag") is None:
            v = "pain_not_read"
        elif w.get("pain_flag"):
            v = "pain_flag"
        else:
            v = "met"
        verdicts.append({"week_start": w.get("week_start"), "hours": hours, "pain_flag": w.get("pain_flag"), "verdict": v})
        if broken_by is None:
            if v == "met":
                met += 1
            else:
                broken_by = v
    return {
        "met": met,
        "needed": needed,
        "hours_per_wk": bar,
        "satisfied": bool(needed) and met >= needed,
        "weeks_meeting_hours": sum(1 for v in verdicts if v["verdict"] in ("met", "pain_not_read", "pain_flag")),
        "broken_by": broken_by,
        "weeks": verdicts,
        "basis": cfg.get("walking_basis"),
    }


# ── the gate ──────────────────────────────────────────────────────────────────────────
def lower_leg_holds(source: Any) -> Optional[list[str]]:
    """The lower-leg hold causes from a `steps_ramp.compute` output (its `held_by`) or a list of causes.
    None = not read (never "no hold")."""
    if source is None:
        return None
    causes = source.get("held_by") if isinstance(source, Mapping) else source
    return [str(c) for c in causes or [] if str(c).startswith(HOLD_PREFIXES)]


def gate_state(
    weight_lb: Optional[float],
    walking_weeks: Optional[Iterable[Mapping[str, Any]]],
    pain_flags: Any,
    stage4_done: Optional[bool] = False,
    weight_date: Optional[str] = None,
) -> dict[str, Any]:
    """The run gate for one reading: state, distance and reason (see the module docstring). `weight_date` (#5314) is the
    day of the weigh-in `weight_lb` came from; it is carried so a line can say WHICH weight the distance is measured from."""
    cfg, prep = running(), prep_cfg()
    gate, prep_from = _num(cfg.get("gate_lb")), _num(prep.get("from_lb"))
    walk = walking_weeks_status(walking_weeks)
    holds = lower_leg_holds(pain_flags)
    w = _num(weight_lb)
    out: dict[str, Any] = {
        "version": RUN_ONRAMP_VERSION,
        "charter_version": training_charter.charter_version(),
        "weight_lb": w,
        "weight_date": str(weight_date) if weight_date else None,
        "gate_lb": gate,
        "prep_from_lb": prep_from,
        "lb_to_gate": None if w is None or gate is None else round(max(w - gate, 0.0), 1),
        "lb_to_prep": None if w is None or prep_from is None else round(max(w - prep_from, 0.0), 1),
        "walking": walk,
        "holds": holds,
        "holds_read": holds is not None,
        "stage4_done": bool(stage4_done),
        "running_unlocked": False,
        # the on-ramp's own preconditions (weight + walking weeks): a strain hold then HOLDS it at its level, never closes it
        "onramp_open": w is not None and gate is not None and w <= gate and walk["satisfied"],
    }
    if gate is None or prep_from is None:
        return {**out, "state": UNKNOWN, "reason": "the charter carries no running gate or prep weight"}
    if w is None:
        return {**out, "state": UNKNOWN, "reason": "no weigh-in: the gate distance is unknown, not closed"}
    walk_words = f"walking weeks {walk['met']}/{walk['needed']} at >= {walk['hours_per_wk']:g} h without a pain flag"
    if w > prep_from:
        return {
            **out,
            "state": CLOSED,
            "reason": f"{out['lb_to_prep']:g} lb to the lower-leg prep, {out['lb_to_gate']:g} lb to the on-ramp; {walk_words}",
        }
    if holds:
        return {
            **out,
            "state": HELD,
            "reason": f"a lower-leg strain flag pauses the pogo hops and the run/walk, the on-ramp keeps its level ({', '.join(holds)})",
        }
    if w > gate or not walk["satisfied"] or holds is None:
        missing = [f"{out['lb_to_gate']:g} lb to go"] if w > gate else []
        missing += [] if walk["satisfied"] else [walk_words]
        missing += ["the strain flags were not read: the on-ramp cannot open on an unread flag"] if holds is None else []
        return {**out, "state": PREP, "reason": "lower-leg prep on the lower days; the on-ramp waits: " + "; ".join(missing)}
    done = bool(stage4_done)
    reason = "Stage 4 completed: continuous running is unlocked" if done else "the run/walk on-ramp (Stage 4) runs"
    return {**out, "state": OPEN, "running_unlocked": done, "reason": reason}


def gate_line(gs: Optional[Mapping[str, Any]]) -> str:
    """One line for a coach prompt or the tracker: the state and its distance."""
    if not gs:
        return "Run gate: not read."
    wl, wd = gs.get("weight_lb"), gs.get("weight_date")
    # #5314: the distance is only comparable between surfaces when its weight and that weight's date are named
    at = f" (from {wl:g} lb{' on ' + str(wd) if wd else ', weigh-in undated'})" if wl is not None else ""
    return f"Run gate: {gs.get('state')} — {gs.get('reason')}{at}."


def rule_line() -> str:
    """The gate as the charter states it, for a context with no measured reading."""
    cfg, prep, ramp = running(), prep_cfg(), onramp()
    if cfg.get("gate_lb") is None:
        return "Run gate: the charter carries none."
    return (
        f"Run gate (charter; no measured reading supplied): the run/walk on-ramp opens at or under {cfg['gate_lb']:g} lb with "
        f"{cfg.get('walking_weeks')} consecutive weeks of >= {cfg.get('walking_hours_per_wk'):g} h walking and no lower-leg pain flag; "
        f"lower-leg prep from {prep.get('from_lb'):g} lb; max {ramp.get('max_runs_per_wk')} runs a week, none on a heavy lower day "
        "or the session either side of it."
    )


# ── the prep ──────────────────────────────────────────────────────────────────────────
def prep_exposures(
    gs: Mapping[str, Any],
    archetype: Any,
    catalog_movements: Optional[Mapping[str, Any]],
    *,
    skill_ceiling: int = 2,
    taken: Iterable[str] = (),
) -> dict[str, Any]:
    """The lower-leg prep for one session: `{placed, why, exposures}`. Lower days only, from the prep weight on;
    a strain hold drops the pogo hops (the calf and tibialis work stay)."""
    from training import cardio_menu  # noqa: PLC0415
    from training.movement_catalog import generator_eligible  # noqa: PLC0415

    state = gs.get("state")
    if state not in (PREP, HELD, OPEN):
        return {"placed": False, "why": f"run gate {state}: {gs.get('reason')}", "exposures": []}
    if not cardio_menu.is_lower(archetype):
        return {"placed": False, "why": "the prep rides the lower days", "exposures": []}
    used = set(taken)
    exposures, skipped = [], []
    for item in prep_cfg().get("prescription") or []:
        name = str(item.get("item"))
        if state == HELD and POGO_ITEM_WORD in name:
            skipped.append(f"{name} (held: {', '.join(gs.get('holds') or [])})")
            continue
        key = None
        for k in item.get("catalog_keys") or []:
            entry = (catalog_movements or {}).get(k)
            if entry and k not in used and generator_eligible(entry, skill_ceiling, key=k, prep_open=True):
                key = k
                break
        if item.get("catalog_keys") and key is None:
            skipped.append(f"{name} (no eligible catalog key)")
            continue
        if key:
            used.add(key)
        lo, hi = item.get("reps") or (None, None)
        rlo, rhi = item.get("rpe") or (None, None)
        cue = f"{name}: {item.get('sets')} x {lo}-{hi}, RPE {rlo}-{rhi}" + (f"; {item['cue']}" if item.get("cue") else "")
        why = f"lower-leg prep from {prep_cfg().get('from_lb')} lb, so the first run is not the first impact"
        exposures.append(
            {
                "kind": "prep",
                "item": name,
                "movement_key": key,
                "sets": [{"kind": "working", "reps": [lo, hi], "rpe": [rlo, rhi]} for _ in range(int(item.get("sets") or 0))],
                "cue": cue,
                "note": f"{cue}. Why: {why}.",
            }
        )
    return {"placed": bool(exposures), "why": "lower-leg prep", "exposures": exposures, "skipped": skipped}


def attach_prep(
    session: dict[str, Any],
    day: str,
    weight_lb: Optional[float],
    pain_flag_instances: Optional[list],
    catalog_movements: Optional[Mapping[str, Any]],
    skill_ceiling: int = 2,
) -> None:
    """The lower-leg prep on the session the plan serves (`session["lower_leg_prep"]`, `plan_engine._scheduled_session`).
    The pogo hops pause on `steps_ramp.lower_leg_holds`; owner dismissals are the steps ramp's read and are not applied
    here, so a dismissed flag still pauses the hops (the cautious side). The walking weeks are not read here: the prep
    needs only the weight; the on-ramp's full gate is the May tracker's reading."""
    from training import steps_ramp  # noqa: PLC0415

    gate = gate_state(weight_lb, None, steps_ramp.lower_leg_holds(day, pain_flag_instances))
    taken = {e.get("movement_key") for e in (session.get("prescription") or {}).get("exposures") or []}
    prep = prep_exposures(gate, session.get("archetype"), catalog_movements, skill_ceiling=skill_ceiling, taken=taken)
    session["lower_leg_prep"] = {**prep, "gate_state": gate["state"], "gate_reason": gate["reason"]}


# ── Stage 4 ───────────────────────────────────────────────────────────────────────────
def performed_from_notes(sessions: Optional[Iterable[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    """His logged run/walks from treadmill/running cardio-index sessions: `{date, level, rpe, pain_flag}` for
    every session whose note names a run/walk. The level and RPE come from his note ("run/walk L3 RPE 5");
    an unlogged RPE is None (not evidence for the advance rule); a pain word naming a lower-leg site flags it."""
    from training import steps_ramp  # noqa: PLC0415
    from training.training_notes import pain_lexicon_hit  # noqa: PLC0415

    out = []
    for s in sessions or []:
        note = str(s.get("note") or "")
        if not _RUN_WALK_RE.search(note):
            continue
        lv, rpe = _LEVEL_RE.search(note), _RPE_RE.search(note)
        out.append(
            {
                "date": str(s.get("date") or "")[:10],
                "level": int(lv.group(1)) if lv else None,
                "rpe": float(rpe.group(1)) if rpe else None,
                "pain_flag": bool(pain_lexicon_hit(note) and steps_ramp.is_lower_leg(note)),
            }
        )
    return sorted(out, key=lambda r: r["date"])


def stage_progress(
    performed: Optional[Iterable[Mapping[str, Any]]], holds: Optional[list[str]] = None, held_since: Optional[str] = None
) -> dict[str, Any]:
    """Where he is on the on-ramp. Sessions at another level than the current one are ignored; a session with a pain
    flag resets the count at the level. While `holds` stand, no session dated on or after `held_since` (the hold's
    first day) counts, so the level stays where the hold found it; with no `held_since` the hold is read as covering
    the whole record (the cautious side: nothing counts) — a caller passes the date to keep the earlier progress."""
    table = levels()
    rule = onramp().get("advance_rule") or {}
    need = int(rule.get("sessions_at_level") or 0)
    band = easy_band()
    rpe_max = band[1] if band else None
    if not table or not need or rpe_max is None:
        return {"state": UNKNOWN, "reason": "the charter carries no on-ramp table, advance rule or easy band"}
    last = int(table[-1]["level"])
    current, good, done = int(table[0]["level"]), 0, False
    held = bool(holds)
    for s in performed or []:
        if done or s.get("level") != current:
            continue
        if held and (not held_since or str(s.get("date") or "") >= held_since):
            continue
        if s.get("pain_flag"):
            good = 0
            continue
        rpe = _num(s.get("rpe"))
        if rpe is None or rpe > rpe_max:
            continue
        good += 1
        if good >= need:
            if current == last:
                done = True
            else:
                current, good = current + 1, 0
    spec = next(lv for lv in table if int(lv["level"]) == current)
    if done:
        reason = f"level {last} completed {need}x: Stage 4 is done"
    elif held:
        reason = f"held at level {current} while the flag stands (no advance): {', '.join(holds or [])}"
    else:
        reason = f"level {current}: {good}/{need} sessions at RPE <= {rpe_max} with no pain flag"
    return {
        "level": current,
        "last_level": last,
        "sessions_at_level": good,
        "needed": need,
        "rpe_max": rpe_max,
        "held": held,
        "stage4_done": done,
        "next": spec,
        "reason": reason,
    }


def _norm(name: Any) -> str:
    """A session name or role key compared by its letters: a `split.sequence` name and its role key are one session."""
    return re.sub(r"[^a-z]", "", str(name or "").lower())


def heavy_lower_names() -> set[str]:
    """The heavy lower sessions' names, lower-cased: the `split.sequence` names opening 'lower' that say 'heavy'."""
    seq = training_charter.charter_value("split.sequence", []) or []
    return {_norm(s) for s in seq if _norm(s).startswith("lower") and "heavy" in _norm(s)}


def _neighbours(archetype: Any) -> Optional[tuple[str, str]]:
    seq = [_norm(s) for s in training_charter.charter_value("split.sequence", []) or []]
    a = _norm(archetype)
    if a not in seq:
        return None
    i = seq.index(a)
    return seq[(i - 1) % len(seq)], seq[(i + 1) % len(seq)]


def run_day_verdict(
    archetype: Any, *, gate: Optional[Mapping[str, Any]], runs_this_week: int = 0, level: Optional[int] = None
) -> dict[str, Any]:
    """Whether today's session can carry a run/walk: `{eligible, why, block}`. `archetype` is the session's
    `split.sequence` name or its role key; a generic archetype ("lower") cannot be spaced, so it carries no run."""
    cfg = onramp()
    if not gate:
        return {"eligible": False, "why": "run gate not read"}
    if gate.get("state") == HELD:  # the same impact rule that pauses the pogo hops; the level is kept (stage_progress)
        return {"eligible": False, "why": "a lower-leg strain flag pauses the run/walk, as it pauses the pogo hops; the level is kept"}
    if gate.get("state") != OPEN:
        return {"eligible": False, "why": f"run gate {gate.get('state')}"}
    cap = int(cfg.get("max_runs_per_wk") or 0)
    if runs_this_week >= cap:
        return {"eligible": False, "why": f"the week's {cap} runs are done"}
    near = _neighbours(archetype)
    heavy = heavy_lower_names()
    if near is None:
        return {"eligible": False, "why": "not a session of the split: the spacing rule cannot be checked"}
    if _norm(archetype) in heavy:
        return {"eligible": False, "why": "a heavy lower day"}
    if near[0] in heavy:
        return {"eligible": False, "why": f"within {cfg.get('not_within_h_of_heavy_lower')} h after a heavy lower session"}
    if near[1] in heavy:
        return {"eligible": False, "why": f"within {cfg.get('not_within_h_of_heavy_lower')} h before a heavy lower session"}
    block = run_walk_block(level or int((levels() or [{"level": 1}])[0]["level"]))
    why = f"run {runs_this_week + 1} of {cap} this week"
    return {"eligible": block is not None, "why": why, "block": block}


def run_walk_block(level: int) -> Optional[dict[str, Any]]:
    """The run/walk block at `level`, with its note: line 1 the prescription (well under Hevy's session-note cut),
    line 2 its reason. None when the charter carries no such level."""
    from training import cardio_menu  # noqa: PLC0415

    spec = next((lv for lv in levels() if int(lv["level"]) == int(level)), None)
    band = easy_band()
    if spec is None or band is None:
        return None
    blk = cardio_menu.block("run_walk")
    talk = blk.get("talk_test") or ""
    run, walk, rounds, total = spec["run_min"], spec["walk_min"], spec["rounds"], spec["total_min"]
    shape = f"{rounds} x ({run} min run / {walk} min walk)" if walk else f"{run} min continuous"
    line1 = f"Treadmill run/walk L{level} · {total} min · {shape} · RPE <= {band[1]}, {talk}"
    need = (onramp().get("advance_rule") or {}).get("sessions_at_level")
    line2 = f"Why: Stage 4 level {level} of {levels()[-1]['level']}; {need} sessions at RPE <= {band[1]} with no pain move you up."
    return {
        "kind": "run_walk",
        "machine": blk.get("on") or "treadmill",
        "level": int(level),
        "run_min": run,
        "walk_min": walk,
        "rounds": rounds,
        "total_min": total,
        "rpe": list(band),
        "talk_test": talk,
        "note": f"{line1}\n{line2}",
        "movement_minutes": total,
        "charter_version": training_charter.charter_version(),
    }
