"""exercise_gates.py — the exercise library's per-movement gates, evaluated from MEASURED inputs (#5772, epic #5770).

`config/exercise_library.json` (#5769) DEFINES the gates; this module EVALUATES them. It is pure: no reads, no clock,
no writes. The weekly leg (`mcp/exercise_gates_leg.py`, on the Monday panel-grade run) does the reads and the store;
the selection engine (#5773) calls `evaluate_gates` / `movement_states` with the same inputs.

THE OWNER'S RULES (2026-11-11, epic #5770 and #5772's acceptance)

  * Measured inputs only: the 7-day mean bodyweight (Withings), the Hevy record (sessions, sets, RPE, notes), the run
    gate as the May tracker reads it, the private overlay's owner-set values. Nothing is inferred or remembered.
  * An unknown input reads LOCKED, and says so: `state: "locked"`, `input: "unknown"`, a `reason` naming what was not
    measured. There is no third state a consumer could mistake for a pass — `state == "unlocked"` is the ONLY open.
  * A bodyweight gate whose overlay value is null (the owner has not set it) is LOCKED with the reason
    "threshold not set by owner" (`input: "not_set"`).
  * A `clinical_cue` gate is a CUE, never a lock and never an intensity gate: it always evaluates `unlocked` with
    `input: "cue"` and rides the movement's `cues`; `movement_states` never lists it in `locked_by`.
  * Chain order: a chain gate opens only when every prerequisite movement met its logged standard AND that
    prerequisite's own chain / performance gates are open — logging step 3 without step 2 opens nothing.
  * The charter's `gated_movements` are READ (the run gate, the lower-leg-prep carve-out and its weight, the power-clean
    revisit weight), never copied here.

THE RESULT — `evaluate_gates(library, overlay, measured) -> {gate_id: row}`, each row:
  `kind`, `state` (`unlocked` | `locked`), `input` (`measured` | `unknown` | `not_set` | `cue`), `reason`,
  `value_seen` (what the evaluator read — owner-only: a bodyweight mean lives here and in the owner-only DDB row, NEVER in
  a log line), `unlock_condition` (the library's words), and for a gate judged per movement (`PER_MOVEMENT_KINDS`)
  `by_movement` {movement_id: {state, input, reason}} for the LOCKED carriers only, plus `carriers` / `carriers_locked`.

`measured` (every key optional; a missing or None value is an unread input):
  `as_of` 'YYYY-MM-DD' (the Sunday evaluated), `bodyweight` {`mean_lb`, `state`}, `hevy_workouts` (the per-workout Hevy rows, each
  with `date` or a `DATE#…` sk and `exercises[{template_id, sets[{reps, weight_kg, rpe, duration_sec, type}], notes}]`),
  `run_gate` (`mcp.phase_evaluator_leg.run_gate_read`), `charter` (`training_charter.load_charter()`).
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Optional

VERSION = "exercise-gates@0.1.0"

UNLOCKED, LOCKED = "unlocked", "locked"
STATES = (UNLOCKED, LOCKED)
MEASURED, UNKNOWN, NOT_SET, CUE = "measured", "unknown", "not_set", "cue"

# Gate kinds judged per carrier movement (the verdict depends on the movement, not just on him).
PER_MOVEMENT_KINDS = ("pain_flag_exclusion", "equipment_available", "owner_confirmation", "charter_gate")
# Kinds that make up a progression chain: a prerequisite movement carrying a locked one has not "met" its step.
CHAIN_KINDS = ("chain_prerequisite", "performance_threshold")
# Global gates (applies_to: all) and cues are not what a movement "unlocks" — the announce-once record ignores them.
_NOT_ANNOUNCED_KINDS = ("pain_flag_exclusion", "equipment_available", "clinical_cue")

# Platform-chosen windows (pending owner ruling, #5772): a chain step counts from the last 12 weeks of the Hevy record —
# a standard met years ago is not measured capability now. Pain uses the library's own 28-day window.
CHAIN_LOOKBACK_DAYS = 84
PAIN_WINDOW_DAYS = 28
PAIN_TRIAL_RPE_MAX = 6
KG_TO_LB = 2.20462

# A performance gate carried by no movement names the movement it measures (library v0.1 has one).
PERFORMANCE_SUBJECTS = {"perf_assisted_pull": "pull_up_assisted"}

UNKNOWN_SUFFIX = " (an unknown input reads as locked)"
THRESHOLD_NOT_SET = "threshold not set by owner"


# ── small pure helpers ───────────────────────────────────────────────────────────────────────────────────────────
def _day(s: str) -> _dt.date:
    """A calendar day 'YYYY-MM-DD' (never an instant)."""
    t = str(s)[:10]
    return _dt.date(int(t[0:4]), int(t[5:7]), int(t[8:10]))


def _shift(day: str, days: int) -> str:
    return (_day(day) + _dt.timedelta(days=days)).isoformat()


def _monday(day: str) -> str:
    d = _day(day)
    return (d - _dt.timedelta(days=d.weekday())).isoformat()


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _workout_day(w: dict[str, Any]) -> str:
    return str(w.get("date") or str(w.get("sk") or "")[5:15])[:10]


def _verdict(state: str, inp: str, reason: str, value_seen: Any = None) -> dict[str, Any]:
    return {"state": state, "input": inp, "reason": reason, "value_seen": value_seen}


def _unknown(reason: str) -> dict[str, Any]:
    return _verdict(LOCKED, UNKNOWN, reason + UNKNOWN_SUFFIX)


def _charter_path(charter: Optional[dict[str, Any]], path: str) -> Any:
    cur: Any = charter
    for part in str(path).split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _movements(library: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return library.get("movements") or {}


def carriers(library: dict[str, Any]) -> dict[str, list[str]]:
    """gate_id -> the movement ids that carry it (`applies_to: all` -> every movement)."""
    mv = _movements(library)
    out: dict[str, list[str]] = {gid: [] for gid in library.get("gates") or {}}
    for mid, e in mv.items():
        for gid in e.get("gates") or []:
            out.setdefault(gid, []).append(mid)
    for gid, g in (library.get("gates") or {}).items():
        if g.get("applies_to") == "all":
            out[gid] = sorted(mv)
    return {gid: sorted(set(v)) for gid, v in out.items()}


# ── the Hevy record, indexed once ─────────────────────────────────────────────────────────────────────────────────
def index_sessions(workouts: Optional[list[dict[str, Any]]]) -> Optional[dict[str, list[dict[str, Any]]]]:
    """template id (upper) -> [{date, name, sets (working sets only), pain}], oldest first. None = unread.

    `pain` is the #5800 note class (`training_notes_pain.pain_class`): only a `pain` note flags — `discomfort` and
    `form_or_equipment` are listed elsewhere and never lock a movement (owner ruling, #5806)."""
    if workouts is None:
        return None
    from training.training_notes_pain import PAIN, pain_class

    out: dict[str, list[dict[str, Any]]] = {}
    for w in workouts:
        day = _workout_day(w)
        if len(day) != 10:
            continue
        for ex in w.get("exercises") or []:
            tid = str(ex.get("template_id") or "").strip().upper()
            name = str(ex.get("name") or ex.get("title") or "")
            if not tid and not name:
                continue
            sets = [s for s in ex.get("sets") or [] if str(s.get("type") or s.get("set_type") or "normal").lower() != "warmup"]
            pain = pain_class(str(ex.get("notes") or "")) == PAIN
            out.setdefault(tid or "_untemplated", []).append({"date": day, "name": name, "sets": sets, "pain": pain})
    for rows in out.values():
        rows.sort(key=lambda r: r["date"])
    return out


def _tid(library: dict[str, Any], mid: str) -> str:
    return str((_movements(library).get(mid) or {}).get("template_id") or "").strip().upper()


def _title_words(library: dict[str, Any], mid: str) -> list[str]:
    """The library's `template_match.title_all` for a movement (#5772): every word must appear in the logged title."""
    rule = (_movements(library).get(mid) or {}).get("template_match") or {}
    return [str(w).lower() for w in rule.get("title_all") or [] if str(w).strip()]


def measurable(library: dict[str, Any], mid: str) -> bool:
    """Can the Hevy record say anything about this movement? A template id, or a title-match rule, is required."""
    return bool(_tid(library, mid) or _title_words(library, mid))


def sessions_for(library: dict[str, Any], index: dict[str, list[dict[str, Any]]], mid: str) -> list[dict[str, Any]]:
    """The movement's logged sessions: its template id's rows, plus — with a `template_match` rule (the KB deadlift has
    no standard Hevy template, #5810) — any logged exercise whose title carries every rule word. Oldest first."""
    tid = _tid(library, mid)
    rows = list(index.get(tid, [])) if tid else []
    words = _title_words(library, mid)
    if words:
        pats = [re.compile(r"\b" + re.escape(w) + r"s?\b", re.I) for w in words]
        seen = {id(r) for r in rows}
        for key, sess in index.items():
            if key == tid:
                continue
            rows += [r for r in sess if id(r) not in seen and all(p.search(r["name"]) for p in pats)]
    return sorted(rows, key=lambda r: r["date"])


# ── pain (the note classes) ───────────────────────────────────────────────────────────────────────────────────────
def pain_verdict(sessions: Optional[list[dict[str, Any]]], as_of: str, window_days: int = PAIN_WINDOW_DAYS) -> dict[str, Any]:
    """No `pain`-class note (#5800) on this movement in the window -> open. After a flag, one later session with a
    working set at RPE <= 6 and no pain class re-opens it (the library's unlock condition)."""
    if sessions is None:
        return _unknown("Hevy record unread — pain flags unknown")
    start = _shift(as_of, -(window_days - 1))
    window = [s for s in sessions if start <= s["date"] <= as_of]
    flags = [s["date"] for s in window if s["pain"]]
    if not flags:
        return _verdict(UNLOCKED, MEASURED, f"no pain flag on it in the last {window_days} days", {"pain_flags": 0})
    last = max(flags)
    for s in window:
        if s["date"] <= last or s["pain"]:
            continue
        if any((_num(x.get("rpe")) or 99) <= PAIN_TRIAL_RPE_MAX for x in s["sets"]):
            return _verdict(UNLOCKED, MEASURED, "a pain-free trial set at RPE <= 6 after the last flag", {"pain_flags": len(flags)})
    return _verdict(LOCKED, MEASURED, "pain flag in the window; no pain-free trial set at RPE <= 6 since", {"pain_flags": len(flags)})


# ── chain / performance standards ─────────────────────────────────────────────────────────────────────────────────
def _set_meets(s: dict[str, Any], std: dict[str, Any], bw_lb: Optional[float]) -> Optional[bool]:
    """True / False, or None when the set does not record what the standard needs (an unmeasured set, never a pass)."""
    reps, dur = _num(s.get("reps")), _num(s.get("duration_sec") or s.get("duration_seconds"))
    if "rpe_max" in std:
        rpe = _num(s.get("rpe"))
        if rpe is None or rpe > float(std["rpe_max"]):
            return False  # an unlogged RPE is not evidence (the charter's on-ramp rule)
    timed = (reps is None or reps <= 0) and dur is not None and dur > 0
    if timed:
        if "hang_seconds_min" not in std:
            return False
        return dur >= float(std["hang_seconds_min"])
    if reps is None or reps < float(std.get("reps_min") or 1):
        return False
    if "assistance_fraction_max" in std:
        kg = _num(s.get("weight_kg"))
        if kg is None or bw_lb is None or bw_lb <= 0:
            return None
        if kg * KG_TO_LB / bw_lb > float(std["assistance_fraction_max"]):
            return False
    if "eccentric_seconds_min" in std:
        if dur is None or dur <= 0:
            return None
        if dur / reps < float(std["eccentric_seconds_min"]):
            return False
    return True


def standard_verdict(
    sessions: Optional[list[dict[str, Any]]], std: dict[str, Any], as_of: str, bw_lb: Optional[float], label: str
) -> dict[str, Any]:
    """One prerequisite movement against its logged standard over `CHAIN_LOOKBACK_DAYS`."""
    if sessions is None:
        return _unknown(f"{label}: Hevy record unread")
    start = _shift(as_of, -(CHAIN_LOOKBACK_DAYS - 1))
    window = [s for s in sessions if start <= s["date"] <= as_of]
    need_sets = int(std.get("sets") or 1)
    qualifying, unmeasured = [], 0
    for s in window:
        marks = [_set_meets(x, std, bw_lb) for x in s["sets"]]
        if sum(1 for m in marks if m) >= need_sets:
            qualifying.append(s["date"])
        elif any(m is None for m in marks):
            unmeasured += 1
    need = max(int(std.get("sessions_min") or 1), int(std.get("prerequisite_sessions_min") or 1))
    weeks = len({_monday(d) for d in qualifying})
    seen = {"qualifying_sessions": len(qualifying), "weeks": weeks, "sessions_in_window": len(window)}
    if "flag_free_days" in std:
        pain = pain_verdict(sessions, as_of, int(std["flag_free_days"]))
        if pain["state"] != UNLOCKED:
            return {**pain, "reason": f"{label}: {pain['reason']}", "value_seen": seen}
    if len(qualifying) >= need and weeks >= int(std.get("span_weeks_min") or 1):
        return _verdict(UNLOCKED, MEASURED, f"{label}: standard met in {len(qualifying)} session(s)", seen)
    if unmeasured and len(qualifying) + unmeasured >= need:
        return {**_unknown(f"{label}: {unmeasured} session(s) do not record what the standard measures"), "value_seen": seen}
    return _verdict(LOCKED, MEASURED, f"{label}: standard not yet met ({len(qualifying)} of {need} sessions)", seen)


class _ChainCtx:
    """Memoised chain evaluation: a prerequisite counts only when its own chain gates are open (chain order)."""

    def __init__(self, library: dict[str, Any], index: Optional[dict[str, list[dict[str, Any]]]], as_of: str, bw_lb: Optional[float]):
        self.library, self.index, self.as_of, self.bw_lb = library, index, as_of, bw_lb
        self.gates = library.get("gates") or {}
        self.memo: dict[str, dict[str, Any]] = {}
        self.visiting: set[str] = set()

    def sessions(self, mid: str) -> Optional[list[dict[str, Any]]]:
        if self.index is None:
            return None
        return sessions_for(self.library, self.index, mid) if measurable(self.library, mid) else None

    def step_open(self, mid: str) -> tuple[bool, Optional[str]]:
        """Are the chain gates the prerequisite movement itself carries open? (False, first locked gate id) if not."""
        for gid in (_movements(self.library).get(mid) or {}).get("gates") or []:
            if (self.gates.get(gid) or {}).get("kind") in CHAIN_KINDS and self.gate(gid)["state"] != UNLOCKED:
                return False, gid
        return True, None

    def prerequisite(self, mid: str, std: dict[str, Any]) -> dict[str, Any]:
        if mid not in _movements(self.library):
            return _unknown(f"{mid}: not a library movement")
        if not measurable(self.library, mid):
            return _unknown(f"{mid}: no Hevy template or title rule, so its sessions cannot be measured")
        open_, blocker = self.step_open(mid)
        if not open_:
            reason = f"{mid}: its own step is still locked ({blocker}) — chain order"
            if self.gate(str(blocker))["input"] != MEASURED:
                return _unknown(reason + "; that step's input is unknown")
            return _verdict(LOCKED, MEASURED, reason)
        return standard_verdict(self.sessions(mid), std, self.as_of, self.bw_lb, mid)

    def gate(self, gid: str) -> dict[str, Any]:
        if gid in self.memo:
            return self.memo[gid]
        if gid in self.visiting:
            return _unknown(f"{gid}: the chain loops back on itself")
        self.visiting.add(gid)
        g = self.gates.get(gid) or {}
        std = g.get("standard") or {}
        if g.get("kind") == "performance_threshold":
            subject = g.get("subject") or PERFORMANCE_SUBJECTS.get(gid)
            prereqs = [subject] if subject else []
        else:
            prereqs = list(g.get("chain_prerequisites") or [])
        if not prereqs:
            out = _unknown(f"{gid}: names no movement to measure")
        else:
            per = {p: self.prerequisite(p, std) for p in prereqs}
            out = _combine(per)
        self.visiting.discard(gid)
        self.memo[gid] = out
        return out


def _combine(per: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Every prerequisite must be open. A locked one wins over an unknown one in the reason (it is the nearer fact)."""
    seen = {p: {"state": v["state"], "input": v["input"], "reason": v["reason"], **(v.get("value_seen") or {})} for p, v in per.items()}
    if all(v["state"] == UNLOCKED for v in per.values()):
        return _verdict(UNLOCKED, MEASURED, "every prerequisite met its standard", seen)
    measured_locks = [v for v in per.values() if v["state"] != UNLOCKED and v["input"] == MEASURED]
    first = measured_locks[0] if measured_locks else next(v for v in per.values() if v["state"] != UNLOCKED)
    return {**first, "value_seen": seen}


# ── the single-verdict kinds ──────────────────────────────────────────────────────────────────────────────────────
def bodyweight_verdict(gid: str, g: dict[str, Any], overlay: Optional[dict[str, Any]], measured: dict[str, Any]) -> dict[str, Any]:
    thr = g.get("threshold") or {}
    if thr.get("charter_ref"):
        value = _num(_charter_path(measured.get("charter"), thr["charter_ref"]))
        if value is None:
            row = ((overlay or {}).get("gates") or {}).get(gid) or {}
            value = _num(row.get("value"))
        if value is None:
            return _unknown(f"the charter's {thr['charter_ref']} unread")
    else:
        if not isinstance(overlay, dict):
            return _unknown("the private overlay is unread, so the threshold is unknown")
        row = (overlay.get("gates") or {}).get(gid)
        if not isinstance(row, dict):
            row = (overlay.get("gate_thresholds") or {}).get(gid)
        if not isinstance(row, dict) or row.get("value") is None:
            return _verdict(LOCKED, NOT_SET, THRESHOLD_NOT_SET)
        value = _num(row.get("value"))
        if value is None:
            return _unknown("the overlay's threshold is not a number")
    bw = measured.get("bodyweight") or {}
    mean = _num(bw.get("mean_lb"))
    if mean is None:
        return _unknown(f"7-day mean bodyweight not measured ({bw.get('state') or 'unread'})")
    seen = {"mean_lb_7d": round(mean, 1)}
    if mean <= value:
        return _verdict(UNLOCKED, MEASURED, "7-day mean bodyweight at or under the threshold", seen)
    return _verdict(LOCKED, MEASURED, "7-day mean bodyweight above the threshold", seen)


def running_verdict(measured: dict[str, Any]) -> dict[str, Any]:
    rg = measured.get("run_gate")
    if not isinstance(rg, dict):
        return _unknown("the run gate is unread")
    state = str(rg.get("gate_state") or "").lower()
    if state in ("", "unknown"):
        return _unknown(f"the run gate is unknown: {rg.get('reason') or 'no reading'}")
    seen = {"gate_state": state, "running_unlocked": bool(rg.get("running_unlocked"))}
    if state == "open" and rg.get("running_unlocked"):
        return _verdict(UNLOCKED, MEASURED, "the run gate is open and the on-ramp is complete", seen)
    return _verdict(LOCKED, MEASURED, f"the run gate reads {state}; continuous running waits on the on-ramp", seen)


# ── the per-movement kinds ────────────────────────────────────────────────────────────────────────────────────────
def equipment_verdict(library: dict[str, Any], overlay: Optional[dict[str, Any]], mid: str) -> dict[str, Any]:
    items = (library.get("gym_inventory") or {}).get("items") or {}
    learned = (overlay or {}).get("availability_learned") or {} if isinstance(overlay, dict) else {}
    unknown, unavailable = [], []
    for eid in (_movements(library).get(mid) or {}).get("equipment") or []:
        if ((learned.get(eid) or {}).get("home_gym") or {}).get("state") == "unavailable":
            unavailable.append(eid)
            continue
        state = ((items.get(eid) or {}).get("home_gym") or {}).get("state")
        if state == "unavailable":
            unavailable.append(eid)
        elif state != "available":
            unknown.append(eid)
    if unavailable:
        return _verdict(LOCKED, MEASURED, "equipment unavailable at home_gym: " + ", ".join(sorted(unavailable)))
    if unknown:
        return _unknown("equipment availability unknown at home_gym: " + ", ".join(sorted(unknown)))
    return _verdict(UNLOCKED, MEASURED, "every equipment id is available at home_gym")


def confirmation_verdict(overlay: Optional[dict[str, Any]], mid: str) -> dict[str, Any]:
    if not isinstance(overlay, dict):
        return _unknown("the private overlay is unread, so no technique confirmation can be read")
    confirmed = overlay.get("technique_confirmations") or {}
    if isinstance(confirmed, dict) and confirmed.get(mid):
        return _verdict(UNLOCKED, MEASURED, "technique confirmed by the owner")
    return _unknown("no technique confirmation on record")


def plyometric_verdict(measured: dict[str, Any], mid: str) -> dict[str, Any]:
    prep = _charter_path(measured.get("charter"), "gated_movements.lower_leg_prep")
    if not isinstance(prep, dict):
        return _unknown("the charter's lower_leg_prep is unread")
    if mid not in (prep.get("carve_out_catalog_keys") or []):
        return _verdict(LOCKED, MEASURED, "excluded by the charter's plyometric rule (not on its carve-out list)")
    from_lb = _num(prep.get("from_lb"))
    mean = _num((measured.get("bodyweight") or {}).get("mean_lb"))
    if from_lb is None or mean is None:
        return _unknown("the carve-out weight or the 7-day mean bodyweight is not measured")
    if mean <= from_lb:
        return _verdict(UNLOCKED, MEASURED, "on the charter's carve-out list, at or under its prep weight", {"mean_lb_7d": round(mean, 1)})
    return _verdict(LOCKED, MEASURED, "on the charter's carve-out list, above its prep weight", {"mean_lb_7d": round(mean, 1)})


def _per_movement(gid: str, g: dict[str, Any], library, overlay, measured, index, mid: str) -> dict[str, Any]:
    kind = g.get("kind")
    if kind == "pain_flag_exclusion":
        if index is None:
            return pain_verdict(None, measured.get("as_of") or "")
        if not measurable(library, mid):
            return _verdict(UNLOCKED, MEASURED, "no Hevy template, so no note can flag it")  # nothing logged = nothing flagged
        return pain_verdict(sessions_for(library, index, mid), measured.get("as_of") or "")
    if kind == "equipment_available":
        return equipment_verdict(library, overlay, mid)
    if kind == "owner_confirmation":
        return confirmation_verdict(overlay, mid)
    if kind == "charter_gate":
        if "running" in str(g.get("charter_ref") or ""):
            return running_verdict(measured)
        return plyometric_verdict(measured, mid)
    return _unknown(f"{gid}: kind {kind} has no per-movement evaluator")


def _aggregate(verdicts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    locked = {m: {k: v[k] for k in ("state", "input", "reason")} for m, v in sorted(verdicts.items()) if v["state"] != UNLOCKED}
    inputs = {v["input"] for v in verdicts.values()}
    return {
        "state": LOCKED if locked else UNLOCKED,
        "input": MEASURED if inputs <= {MEASURED} else UNKNOWN,
        "reason": f"{len(locked)} of {len(verdicts)} carrier(s) locked" if locked else "open for every carrier",
        "value_seen": None,
        "carriers": len(verdicts),
        "carriers_locked": len(locked),
        "by_movement": locked,
    }


# ── the entry point ───────────────────────────────────────────────────────────────────────────────────────────────
def evaluate_gates(library: dict[str, Any], overlay: Optional[dict[str, Any]], measured: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Pure. Every library gate -> its verdict (module docstring). Never raises on a missing input — it locks."""
    measured = measured or {}
    as_of = str(measured.get("as_of") or "")
    index = index_sessions(measured.get("hevy_workouts"))
    bw_lb = _num((measured.get("bodyweight") or {}).get("mean_lb"))
    chain = _ChainCtx(library, index, as_of, bw_lb)
    who = carriers(library)
    out: dict[str, dict[str, Any]] = {}
    for gid, g in sorted((library.get("gates") or {}).items()):
        kind = g.get("kind")
        if kind == "clinical_cue" or g.get("locks") is False:
            row = _verdict(UNLOCKED, CUE, "a cue, never a lock or an intensity gate")
            row["cue"] = g.get("cue")
        elif not as_of:
            row = _unknown("no evaluation date")
        elif kind == "bodyweight_threshold":
            row = bodyweight_verdict(gid, g, overlay, measured)
        elif kind in CHAIN_KINDS:
            row = dict(chain.gate(gid))
        elif kind in PER_MOVEMENT_KINDS and not (kind == "charter_gate" and "running" in str(g.get("charter_ref") or "")):
            row = _aggregate({m: _per_movement(gid, g, library, overlay, measured, index, m) for m in who.get(gid, [])})
        elif kind == "charter_gate":
            row = running_verdict(measured)
        else:
            row = _unknown(f"no evaluator for gate kind {kind}")
        row.update({"kind": kind, "unlock_condition": g.get("unlock_condition")})
        out[gid] = row
    return out


def _gate_state_for(gates: dict[str, dict[str, Any]], gid: str, mid: str) -> dict[str, Any]:
    row = gates.get(gid) or _unknown(f"{gid}: not evaluated")
    by = row.get("by_movement")
    if isinstance(by, dict):
        return by.get(mid) or {"state": UNLOCKED, "input": row.get("input"), "reason": "open for this movement"}
    return row


def movement_states(library: dict[str, Any], gates: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Every movement -> {state, own_gates_open, locked_by [gate ids], reasons, unlock_conditions, cues, gates}.

    `state` counts every locking gate (global ones too); `own_gates_open` only the gates the movement itself lists —
    the thing that is "unlocked" and announced. A clinical cue is never in `locked_by`. A `not_for_you_now` entry is
    locked with its own reason and unlock condition."""
    lib_gates = library.get("gates") or {}
    globals_ = [gid for gid, g in lib_gates.items() if g.get("applies_to") == "all"]
    out: dict[str, dict[str, Any]] = {}
    for mid, e in _movements(library).items():
        own = [gid for gid in e.get("gates") or [] if (lib_gates.get(gid) or {}).get("kind") != "clinical_cue"]
        cues = [lib_gates[gid].get("cue") for gid in e.get("gates") or [] if (lib_gates.get(gid) or {}).get("kind") == "clinical_cue"]
        locked_by, reasons, conditions = [], {}, {}
        own_open = True
        for gid in own + [g for g in globals_ if g not in own]:
            if (lib_gates.get(gid) or {}).get("kind") == "clinical_cue":
                continue
            v = _gate_state_for(gates, gid, mid)
            if v.get("state") != UNLOCKED:
                locked_by.append(gid)
                reasons[gid] = v.get("reason")
                conditions[gid] = (lib_gates.get(gid) or {}).get("unlock_condition")
                if gid in own and (lib_gates.get(gid) or {}).get("kind") not in _NOT_ANNOUNCED_KINDS:
                    own_open = False
        nfy = e.get("not_for_you_now")
        if isinstance(nfy, dict):
            locked_by.append("not_for_you_now")
            reasons["not_for_you_now"] = nfy.get("reason_code")
            conditions["not_for_you_now"] = nfy.get("unlock_condition")
        out[mid] = {
            "state": LOCKED if locked_by else UNLOCKED,
            "own_gates": [g for g in own if (lib_gates.get(g) or {}).get("kind") not in _NOT_ANNOUNCED_KINDS],
            "own_gates_open": own_open,
            "locked_by": locked_by,
            "reasons": reasons,
            "unlock_conditions": conditions,
            "cues": [c for c in cues if c],
        }
    return out


def gated_movements(states: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The movements an unlock can be announced for: those carrying at least one own (non-global, non-cue) gate."""
    return {m: s for m, s in states.items() if s["own_gates"]}


def newly_unlocked(previous: Optional[dict[str, Any]], current: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Movements whose own gates are open now and were NOT open in the previous evaluation's `movements`.

    No previous evaluation -> nothing is "new" (the first run is the baseline: what is already open is not news).
    Returns [{movement_id, gates}] — `gates` is the key half of the claim-once record (gate+movement)."""
    if not isinstance(previous, dict):
        return []
    out = []
    for mid, s in sorted(gated_movements(current).items()):
        before = previous.get(mid)
        if s["own_gates_open"] and isinstance(before, dict) and not before.get("own_gates_open"):
            out.append({"movement_id": mid, "gates": sorted(s["own_gates"])})
    return out


def state_counts(gates: dict[str, dict[str, Any]]) -> dict[str, int]:
    """{unlocked, locked, locked_unknown, locked_not_set, cue} — counts only (what a log line may carry)."""
    c = {"unlocked": 0, "locked": 0, "locked_unknown": 0, "locked_not_set": 0, "cue": 0}
    for row in gates.values():
        if row.get("input") == CUE:
            c["cue"] += 1
        elif row.get("state") == UNLOCKED:
            c["unlocked"] += 1
        else:
            c["locked"] += 1
            if row.get("input") == UNKNOWN:
                c["locked_unknown"] += 1
            elif row.get("input") == NOT_SET:
                c["locked_not_set"] += 1
    return c


def log_view(gates: dict[str, dict[str, Any]]) -> dict[str, str]:
    """gate id -> 'state/input' — the ONLY per-gate shape a log line carries (no value_seen, no reason text)."""
    return {gid: f"{row.get('state')}/{row.get('input')}" for gid, row in sorted(gates.items())}
