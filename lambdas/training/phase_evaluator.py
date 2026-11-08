"""training/phase_evaluator.py — the charter's phase gates, computed weekly (#5575, epic #5067). OWNER-ONLY.

`config/training_charter.json` `phases` (#5574) defines Foundation -> Build -> Forge -> Sustain: each later phase has
entry gates whose VALUES are references into the charter (`value_ref`, `gate_ref`, the `owner_twin:` alias), plus the
rules every transition shares (`every_transition`) and the advance rule (`advance`). This module reads that section
and computes each gate as `met / not_met / unknown` over measured inputs the caller hands in; the stage machine
(`training.stage_machine`, the primitive CS-4 can adopt) turns the verdict into a proposal and, at the next block
start, a transition. Pure — no clock, no I/O; the reads and the store are `mcp/phase_evaluator_leg.py`.

THE METRICS (one evaluator each; `SUPPORTED_METRICS` is the contract the charter is held to)

  weight_trend_7d_lb              the trailing 7-day mean weight (`health.milestone_ledger.trailing_weight_mean`:
                                  the 7 calendar days ending on the evaluation's Sunday, >= 3 weigh-ins, else no
                                  claim) at each weekly checkpoint, newest first. With `held_for` the gate must hold
                                  for `advance.consecutive_evaluations` checkpoints in a row (`stage_machine.held`).
  date                            the evaluation's Sunday against a charter date (`governing_goal.target_date`).
  gate_state                      the run gate as `training.run_onramp.gate_state` states it: `open` is met; closed,
                                  held, and a prep that is decided by weight are not met; a prep that only an unread
                                  input keeps shut (an unread strain flag, an unmeasured walking week) is unknown.
  performed_hevy_sessions_per_wk  performed Hevy sessions per completed Monday-Sunday week
                                  (`routine_title.count_distinct_performed`, no new counter): met when at least
                                  `weeks_meeting` of the last `of_last_weeks` weeks reach `min_sessions_per_wk`;
                                  not met when even the unmeasured weeks could not get there; else unknown.
  joint_or_lower_leg_pain_flags   a live (not dismissed) pain flag from the Hevy note layer in the last
                                  `pain_lookback_weeks` weeks — the flags the plan engine's `pain_flag_named_site`
                                  tripwire reads; none is met, any is not met, an unread note layer is unknown.

A gate whose reference does not resolve (the owner-only twin absent) is `unknown`, never met. The goal weight a
`owner_twin:` gate compares against is NEVER copied into a row: the gate carries `threshold_private: true` instead.

THE CONTRACT (`unsupported`). A phase, a gate, a metric, a comparator, a gate key or a reference the charter carries and
this module cannot evaluate is named — `tests/test_phase_evaluator_5575.py` fails the build on any of them, so the
charter can never grow a gate that silently reads as unknown forever.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Mapping, Optional, Sequence

from training import stage_machine as sm

PHASE_EVALUATOR_VERSION = "phase-evaluator@1.0.0"

# The owner-only values a gate may reference, by ALIAS (#5574): the alias, never the twin's key, sits in the public
# charter (the owner prompt block carries the whole public charter and must not name a private-twin key). The ONE map:
# tests/test_training_phases_charter_5574.py imports it from here.
OWNER_TWIN_REFS = {"owner_twin:goal_weight": "target_picture.weight_band_lb[1]"}

# ── the store: rows in the owner-only training_constraints partition (docs/SCHEMA.md) ───────────────────────────────
SOURCE = "training_constraints"
SK_EVAL = "PHASE#EVAL#"  # + <monday>: one row per evaluated Monday-Sunday week
SK_STATE = "PHASE#STATE"  # the one current-state row
SK_TRANSITION = "PHASE#TRANSITION#"  # + <effective_on>#<to>: one row per phase change

MET, NOT_MET, UNKNOWN = sm.MET, sm.NOT_MET, sm.UNKNOWN

GROUP_ENTRY, GROUP_ANY_OF, GROUP_EVERY = "entry_gates", "entry_gates_any_of", "every_transition"
GATE_KEYS = (GROUP_ENTRY, GROUP_ANY_OF)

# metric -> (the comparators its evaluator implements, the gate fields it needs)
SUPPORTED_METRICS: dict[str, tuple[frozenset, tuple[str, ...]]] = {
    "weight_trend_7d_lb": (frozenset({"<="}), ("value_ref",)),
    "date": (frozenset({">="}), ("value_ref",)),
    "gate_state": (frozenset({"=="}), ("gate_ref", "value")),
    "performed_hevy_sessions_per_wk": (frozenset({">="}), ("min_sessions_per_wk", "weeks_meeting", "of_last_weeks")),
    "joint_or_lower_leg_pain_flags": (frozenset({"none_in_window"}), ("pain_lookback_weeks",)),
}
# The gates a `gate_state` metric can read: the run gate, through `training.run_onramp.gate_state`.
SUPPORTED_GATE_REFS = {"gated_movements.running": ("open",)}
# The phases keys this module reads (or deliberately ignores as prose); a new key is a rule nobody evaluates.
KNOWN_PHASES_KEYS = frozenset({"_about", "ruling", "order", "evaluation", "advance", "every_transition", "definitions"})
KNOWN_DEFINITION_KEYS = frozenset({"title", "intent", "entry_gates", "entry_gates_any_of", "entry_note", "unlocks", "until_then"})
SUPPORTED_TAKES_EFFECT = ("next_block_start",)

_INDEX = re.compile(r"^(.*)\[(\d+)\]$")


# ── references ─────────────────────────────────────────────────────────────────────────────────────────────────────
def _walk(doc: Any, dotted: str) -> tuple[bool, Any]:
    cur = doc
    for part in dotted.split("."):
        m = _INDEX.match(part)
        key, idx = (m.group(1), int(m.group(2))) if m else (part, None)
        if not isinstance(cur, Mapping) or key not in cur:
            return False, None
        cur = cur[key]
        if idx is not None:
            if not isinstance(cur, list) or idx >= len(cur):
                return False, None
            cur = cur[idx]
    return True, cur


def resolve_ref(charter: Mapping[str, Any], ref: str) -> tuple[bool, Any, bool]:
    """(found, value, private) for a charter reference. `owner_twin:` aliases resolve through `OWNER_TWIN_REFS` in the
    MERGED charter (`training_charter.load_charter()`); `advance.*` resolves under `phases`. A null value is not found."""
    if ref.startswith("owner_twin:"):
        path = OWNER_TWIN_REFS.get(ref)
        if path is None:
            return False, None, True
        found, value = _walk(charter, path)
        return found and value is not None, value, True
    path = f"phases.{ref}" if ref.startswith("advance.") else ref
    found, value = _walk(charter, path)
    return found and value is not None, value, False


# ── the contract ───────────────────────────────────────────────────────────────────────────────────────────────────
def _gate_problems(where: str, gate: Mapping[str, Any]) -> list[str]:
    metric, comparator = gate.get("metric"), gate.get("comparator")
    if metric not in SUPPORTED_METRICS:
        return [f"{where}: metric {metric!r} has no evaluator (supported: {sorted(SUPPORTED_METRICS)})"]
    comparators, needs = SUPPORTED_METRICS[metric]
    out = [] if comparator in comparators else [f"{where}: comparator {comparator!r} is not implemented for {metric!r}"]
    out += [f"{where}: {metric!r} needs {k!r}" for k in needs if k not in gate]
    if metric == "gate_state":
        allowed = SUPPORTED_GATE_REFS.get(str(gate.get("gate_ref")))
        if allowed is None:
            out.append(f"{where}: gate_ref {gate.get('gate_ref')!r} has no reader (supported: {sorted(SUPPORTED_GATE_REFS)})")
        elif gate.get("value") not in allowed:
            out.append(f"{where}: gate_state value {gate.get('value')!r} is not one the reader states ({list(allowed)})")
    if "value_ref" in gate and str(gate["value_ref"]).startswith("owner_twin:") and gate["value_ref"] not in OWNER_TWIN_REFS:
        out.append(f"{where}: owner-only ref {gate['value_ref']!r} is not in OWNER_TWIN_REFS")
    held_for = gate.get("held_for")
    if held_for is not None and metric != "weight_trend_7d_lb":
        out.append(f"{where}: held_for on {metric!r} is not implemented (only a weekly series can be held)")
    return out


def unsupported(charter: Mapping[str, Any]) -> list[str]:
    """Every part of `charter['phases']` this evaluator cannot compute, named. Empty = fully supported."""
    ph = charter.get("phases")
    if not isinstance(ph, Mapping):
        return ["charter has no `phases` section"]
    out = [f"phases.{k}: a key the evaluator does not read" for k in sorted(set(ph) - KNOWN_PHASES_KEYS)]
    defs, order = ph.get("definitions") or {}, list(ph.get("order") or [])
    if not order:
        out.append("phases.order is empty")
    out += [f"phases.order names {p!r} with no definition" for p in order if p not in defs]
    out += [f"phases.definitions.{p}: not in phases.order, so never evaluated" for p in defs if p not in order]
    for i, pid in enumerate(order):
        d = defs.get(pid) or {}
        out += [f"phases.definitions.{pid}.{k}: a key the evaluator does not read" for k in sorted(set(d) - KNOWN_DEFINITION_KEYS)]
        groups = [k for k in GATE_KEYS if d.get(k)]
        if i > 0 and not groups:
            out.append(f"phases.definitions.{pid}: a later phase with no entry gate could never be proposed")
        if len(groups) > 1:
            out.append(f"phases.definitions.{pid}: carries both {GATE_KEYS} — the combination rule is undefined")
        for key in groups:
            for j, g in enumerate(d.get(key) or []):
                out += _gate_problems(f"phases.definitions.{pid}.{key}[{j}]", g)
    for rid, g in (ph.get("every_transition") or {}).items():
        out += _gate_problems(f"phases.every_transition.{rid}", g)
    adv = ph.get("advance") or {}
    if adv.get("takes_effect") not in SUPPORTED_TAKES_EFFECT:
        out.append(f"phases.advance.takes_effect {adv.get('takes_effect')!r} is not implemented ({SUPPORTED_TAKES_EFFECT})")
    if adv.get("regression") is not False:
        out.append("phases.advance.regression must be false: the stage machine never moves a phase backwards")
    n = adv.get("consecutive_evaluations")
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        out.append(f"phases.advance.consecutive_evaluations {n!r} is not a positive whole number")
    return out


# ── the gate evaluators (pure; `inputs` are the leg's measured reads) ─────────────────────────────────────────────────
def _result(gate: Mapping[str, Any], group: str, verdict: str, value: Any, detail: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": gate.get("id"),
        "group": group,
        "metric": gate.get("metric"),
        "comparator": gate.get("comparator"),
        "value": value,
        "verdict": verdict,
        "detail": detail,
        **extra,
    }


def _threshold(charter: Mapping[str, Any], gate: Mapping[str, Any]) -> tuple[Any, dict[str, Any]]:
    """(threshold or None, the fields the row carries about it). A private threshold is never carried."""
    ref = str(gate.get("value_ref"))
    found, value, private = resolve_ref(charter, ref)
    meta: dict[str, Any] = {"ref": ref}
    if private:
        meta["threshold_private"] = True
    elif found:
        meta["threshold"] = value
    return (value if found else None), meta


def _n_held(charter: Mapping[str, Any], gate: Mapping[str, Any]) -> int:
    ref = gate.get("held_for")
    if not ref:
        return 1
    found, value, _p = resolve_ref(charter, str(ref))
    return int(value) if found else 1


def _eval_weight(charter, gate, group, inputs) -> dict[str, Any]:
    thr, meta = _threshold(charter, gate)
    series = list(inputs.get("weight_trend_7d_lb") or [])
    n = _n_held(charter, gate)
    meta["held_for"] = n
    shown = [{k: c.get(k) for k in ("as_of", "mean_lbs", "n", "window_start", "window_end")} for c in series[:n]]
    if thr is None:
        why = "the owner-only twin is not loaded" if meta.get("threshold_private") else f"{meta['ref']} does not resolve"
        return _result(gate, group, UNKNOWN, shown, f"no threshold: {why} — unknown, never met", **meta)
    verdicts = [UNKNOWN if c.get("mean_lbs") is None else (MET if float(c["mean_lbs"]) <= float(thr) else NOT_MET) for c in series]
    verdict = sm.held(verdicts, n)
    for c, v in zip(shown, verdicts):
        c["verdict"] = v
    measured = sum(1 for v in verdicts[:n] if v != UNKNOWN)
    detail = f"7-day mean at or under the threshold on {sum(1 for v in verdicts[:n] if v == MET)} of {n} weekly checkpoints ({measured} measured)"
    return _result(gate, group, verdict, shown, detail, **meta)


def _eval_date(charter, gate, group, inputs) -> dict[str, Any]:
    thr, meta = _threshold(charter, gate)
    as_of = str(inputs.get("as_of") or "")
    if thr is None or not as_of:
        return _result(gate, group, UNKNOWN, as_of or None, "no date to compare", **meta)
    verdict = MET if as_of >= str(thr) else NOT_MET
    return _result(gate, group, verdict, as_of, f"the evaluation's Sunday {as_of} vs {meta.get('threshold', 'the date')}", **meta)


def run_gate_verdict(gs: Optional[Mapping[str, Any]]) -> tuple[str, str]:
    """(verdict, why) for a `run_onramp.gate_state` reading plus `walking_unknown`, the leg's flag for a walking week it
    could not measure."""
    if not gs:
        return UNKNOWN, "the run gate was not read"
    state = gs.get("gate_state")
    if state == "open":
        return MET, "the run gate is open"
    if state in (None, "unknown"):
        return UNKNOWN, str(gs.get("reason") or "the run gate is unknown")
    if state in ("closed", "held"):
        return NOT_MET, f"the run gate is {state}"
    # prep: decided by weight, or kept shut only by an input that was not read
    w, gate_lb = gs.get("weight_lb"), gs.get("gate_lb")
    if w is not None and gate_lb is not None and float(w) > float(gate_lb):
        return NOT_MET, "prep: above the gate weight"
    if gs.get("holds_read") is False or gs.get("walking_unknown"):
        return UNKNOWN, "prep, and an input it waits on was not read (strain flags or a walking week)"
    return NOT_MET, "prep: the walking weeks are not met"


def _eval_gate_state(charter, gate, group, inputs) -> dict[str, Any]:
    gs = inputs.get("run_gate")
    verdict, why = run_gate_verdict(gs)
    value = (
        None
        if not gs
        else {k: gs.get(k) for k in ("gate_state", "weight_date", "lb_to_gate", "walking_met", "walking_needed", "holds_read")}
    )
    return _result(gate, group, verdict, value, why, ref=gate.get("gate_ref"), threshold=gate.get("value"))


def _eval_consistency(charter, gate, group, inputs) -> dict[str, Any]:
    need, of_last = int(gate["min_sessions_per_wk"]), int(gate["of_last_weeks"])
    weeks_needed = int(gate["weeks_meeting"])
    weeks = list(inputs.get("sessions_by_week") or [])[:of_last]
    while len(weeks) < of_last:
        weeks.append({"week_start": None, "sessions": None})
    meeting = sum(1 for w in weeks if w.get("sessions") is not None and int(w["sessions"]) >= need)
    unmeasured = sum(1 for w in weeks if w.get("sessions") is None)
    if meeting >= weeks_needed:
        verdict = MET
    elif meeting + unmeasured < weeks_needed:
        verdict = NOT_MET
    else:
        verdict = UNKNOWN
    shown = [{"week_start": w.get("week_start"), "sessions": w.get("sessions")} for w in weeks]
    detail = f"{meeting} of the last {of_last} weeks at >= {need} performed sessions (need {weeks_needed}); {unmeasured} unmeasured"
    return _result(gate, group, verdict, shown, detail, threshold=need)


def _eval_pain(charter, gate, group, inputs) -> dict[str, Any]:
    pain = inputs.get("pain_flags")
    if not isinstance(pain, Mapping) or pain.get("live") is None:
        why = (pain or {}).get("error") if isinstance(pain, Mapping) else None
        return _result(
            gate, group, UNKNOWN, None, f"the pain-flag layer was not read{f' ({why})' if why else ''} — unknown, never pain-free"
        )
    live = list(pain.get("live") or [])
    value = {"window_start": pain.get("window_start"), "window_end": pain.get("window_end"), "live_flags": live}
    if live:
        return _result(gate, group, NOT_MET, value, f"{len(live)} live pain flag(s) in the window")
    return _result(gate, group, MET, value, "no live pain flag in the window")


_EVALUATORS: dict[str, Callable[..., dict[str, Any]]] = {
    "weight_trend_7d_lb": _eval_weight,
    "date": _eval_date,
    "gate_state": _eval_gate_state,
    "performed_hevy_sessions_per_wk": _eval_consistency,
    "joint_or_lower_leg_pain_flags": _eval_pain,
}


def evaluate_gate(charter: Mapping[str, Any], gate: Mapping[str, Any], group: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
    fn = _EVALUATORS.get(str(gate.get("metric")))
    if fn is None:  # the contract test keeps this unreachable for the live charter
        return _result(gate, group, UNKNOWN, None, f"no evaluator for metric {gate.get('metric')!r}")
    return fn(charter, gate, group, inputs)


# ── one week ────────────────────────────────────────────────────────────────────────────────────────────────────────
def phases(charter: Mapping[str, Any]) -> Mapping[str, Any]:
    return charter.get("phases") or {}


def order(charter: Mapping[str, Any]) -> list[str]:
    return list(phases(charter).get("order") or [])


def title_of(charter: Mapping[str, Any], pid: Optional[str]) -> Optional[str]:
    return ((phases(charter).get("definitions") or {}).get(pid) or {}).get("title") if pid else None


def phase_id_for_title(charter: Mapping[str, Any], title: Any) -> Optional[str]:
    for pid, d in (phases(charter).get("definitions") or {}).items():
        if str(d.get("title") or "").strip().lower() == str(title or "").strip().lower():
            return pid
    return None


def evaluate_next(charter: Mapping[str, Any], current: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
    """The gates between `current` and the next phase: `{next, gates, verdict, blocking_gate}`. At the last phase there
    is nothing to evaluate (`next` None, verdict None)."""
    ph = phases(charter)
    target = sm.next_stage(order(charter), current)
    if target is None:
        return {"next": None, "gates": [], "verdict": None, "blocking_gate": None}
    d = (ph.get("definitions") or {}).get(target) or {}
    entry = [evaluate_gate(charter, g, GROUP_ENTRY, inputs) for g in d.get(GROUP_ENTRY) or []]
    any_of = [evaluate_gate(charter, g, GROUP_ANY_OF, inputs) for g in d.get(GROUP_ANY_OF) or []]
    every = [evaluate_gate(charter, dict(g, id=rid), GROUP_EVERY, inputs) for rid, g in (ph.get("every_transition") or {}).items()]
    parts = [r["verdict"] for r in entry + every]
    if any_of:
        parts.append(sm.any_of(r["verdict"] for r in any_of))
    verdict = sm.all_of(parts)
    return {
        "next": target,
        "gates": entry + any_of + every,
        "verdict": verdict,
        "blocking_gate": blocking_gate(entry, any_of, every, verdict),
    }


def blocking_gate(entry: list, any_of: list, every: list, verdict: str) -> Optional[dict[str, Any]]:
    """THE one gate that stands between him and the next phase: the first not-met gate in charter order (entry gates,
    the any-of group as one gate, then the shared rules), else the first unknown one. None when the verdict is met."""
    if verdict == MET:
        return None
    units: list[dict[str, Any]] = [{"id": r["id"], "verdict": r["verdict"], "detail": r["detail"]} for r in entry]
    if any_of:
        v = sm.any_of(r["verdict"] for r in any_of)
        units.append({"id": " | ".join(str(r["id"]) for r in any_of), "verdict": v, "detail": "any one of these gates"})
    units += [{"id": r["id"], "verdict": r["verdict"], "detail": r["detail"]} for r in every]
    for want in (NOT_MET, UNKNOWN):
        hit = next((u for u in units if u["verdict"] == want), None)
        if hit:
            return hit
    return None


# ── the rows ────────────────────────────────────────────────────────────────────────────────────────────────────────
def pk(user_id: str = "matthew") -> str:
    return f"USER#{user_id}#SOURCE#{SOURCE}"


def eval_row(
    charter: Mapping[str, Any],
    *,
    week_start: str,
    week_end: str,
    state_before: Mapping[str, Any],
    evaluation: Mapping[str, Any],
    step: Mapping[str, Any],
    reads: Mapping[str, Any],
    evaluated_at: Optional[str] = None,
    user_id: str = "matthew",
) -> dict[str, Any]:
    """The week's EVAL row (owner-only; docs/SCHEMA.md `PHASE#EVAL#<monday>`)."""
    current = str(state_before.get("stage"))
    row: dict[str, Any] = {
        "pk": pk(user_id),
        "sk": SK_EVAL + week_start,
        "week_start": week_start,
        "week_end": week_end,
        "as_of": week_end,
        "phase": current,
        "phase_title": title_of(charter, current),
        "next_phase": evaluation.get("next"),
        "next_phase_title": title_of(charter, evaluation.get("next")),
        "gates": list(evaluation.get("gates") or []),
        "next_verdict": evaluation.get("verdict"),
        "blocking_gate": evaluation.get("blocking_gate"),
        "action": step.get("action"),
        "pending": (step.get("state") or {}).get("pending"),
        "phase_after": (step.get("state") or {}).get("stage"),
        "reads": dict(reads),
        "charter_version": charter.get("version"),
        "version": PHASE_EVALUATOR_VERSION,
        "stage_machine": sm.STAGE_MACHINE_VERSION,
        "tier": "owner_only",
    }
    if evaluated_at:
        row["evaluated_at"] = evaluated_at
    return row


def state_row(charter: Mapping[str, Any], state: Mapping[str, Any], *, updated_at: str, user_id: str = "matthew") -> dict[str, Any]:
    stage = str(state.get("stage"))
    return {
        "pk": pk(user_id),
        "sk": SK_STATE,
        "stage": stage,
        "title": title_of(charter, stage),
        "since": state.get("since"),
        "origin": state.get("origin"),
        "pending": state.get("pending"),
        "last_eval": state.get("last_eval"),
        "updated_at": updated_at,
        "version": PHASE_EVALUATOR_VERSION,
        "tier": "owner_only",
    }


def transition_row(
    charter: Mapping[str, Any], transition: Mapping[str, Any], *, recorded_at: str, user_id: str = "matthew"
) -> dict[str, Any]:
    return {
        "pk": pk(user_id),
        "sk": f"{SK_TRANSITION}{transition['effective_on']}#{transition['to']}",
        **dict(transition),
        "from_title": title_of(charter, transition.get("from")),
        "to_title": title_of(charter, transition.get("to")),
        "recorded_at": recorded_at,
        "version": PHASE_EVALUATOR_VERSION,
        "tier": "owner_only",
    }


def seed_state(charter: Mapping[str, Any], title_phase: Any, title_started: Any) -> dict[str, Any]:
    """The first STATE: the Hevy title's hand-set phase (`config/training_phases.json` `current`, ADR-067) when it names a
    charter phase, else the first phase in the order. `since` is that file's `current_started` (None when unknown)."""
    pid = phase_id_for_title(charter, title_phase) or (order(charter) or [None])[0]
    return {"stage": pid, "since": str(title_started)[:10] if title_started else None, "pending": None, "origin": sm.ORIGIN_SEED}


def weekly_checkpoints(week_end: str, n: int, shift: Callable[[str, int], str]) -> list[str]:
    """The `n` weekly checkpoint Sundays ending `week_end`, newest first."""
    return [shift(week_end, -7 * k) for k in range(max(1, int(n)))]


def max_lookback_weeks(charter: Mapping[str, Any]) -> int:
    """How many weeks back the reads must reach for every gate in the charter (weight checkpoints, consistency weeks,
    the pain window)."""
    ph = phases(charter)
    n = int((ph.get("advance") or {}).get("consecutive_evaluations") or 1)
    for g in (ph.get("every_transition") or {}).values():
        for k in ("of_last_weeks", "pain_lookback_weeks"):
            if isinstance(g.get(k), int):
                n = max(n, int(g[k]))
    return n


def every_transition_param(charter: Mapping[str, Any], metric: str, key: str, default: Any = None) -> Any:
    for g in (phases(charter).get("every_transition") or {}).values():
        if g.get("metric") == metric and key in g:
            return g[key]
    return default


def gate_summary(gates: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """{gate id: verdict} — the compact line the log and the tool lead with."""
    return {str(g.get("id")): str(g.get("verdict")) for g in gates}
