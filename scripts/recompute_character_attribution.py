"""scripts/recompute_character_attribution.py — which named change moves each number, in two layers (#6224, #6311, #6293).

Owner condition: "explicit separation of methodological changes" — he sees which public changes are the privacy fix and
which are the method revision. The private plan's per-row ``causes`` tag nearly every cause on every date, so they say
nothing about which change moved which number. Attribution is therefore in TWO layers:

LAYER 1 — the METHOD, on the PRIVATE (method-1) chain. Read from the private tool's own supported reader
``recompute_character_private_apply.ladder_states(path)`` (never re-implemented here): the chain's values after each
named step, cumulative, in the ladder's order. A date's level / XP / composite change is credited to the FIRST step whose
value differs from the step before (for ``replay_residual``: from the stored row, summarised with the private tool's own
``chain_state``). Attribution is ORDER-DEPENDENT: a different ladder order would credit differently. Two checks FAIL the
run: the control step (``tree_switch_residual``) must equal its predecessor on every date, and the last step must equal
the planned sheets (``planned_sheets``).

LAYER 2 — the PUBLIC delta (stored public → v3 public), split into
  ``privacy``      the public v3 projection of the STORED private rows, without the habit-timing fix (restraint inputs
                   removed, Mind and Relationships unscored in public, the food-delivery multiplier not applied);
  ``habit_timing`` the same with the public side's habit-order fix;
  ``method``       the remainder: the projection of the PLANNED private rows (the method revision, layer 1).
The three parts telescope, so they add up exactly; a residual line still reports any gap. A method-part public change on
a date where no ladder step changed the private chain on that date or earlier is UNATTRIBUTED and fails the run.

Events: each step's ``events`` say which step first removes or adds each per-pillar event of the private chain (the
"because of the method" table) — the privacy fix never touches the private rows.
"""

from __future__ import annotations

import statistics
from typing import Any, Optional

CONTROL = "tree_switch_residual"
FIRST_STEP = "replay_residual"
CHAIN = ("character_level", "character_xp", "composite")
PUBLIC_Q = ("character_level", "character_xp", "character_xp_debt", "composite")
PILLARS = ("sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency")
PROTECTED = ("sleep", "movement")  # owner: "Preserve legitimate previously served sleep and movement achievements"
PRIVATE_ONLY = ("mind",)  # Mind is not public under any method: its events are left out of the event table


def _moved(a: Any, b: Any) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) > 1e-9
    return a != b


def _delta(a: Any, b: Any) -> Optional[float]:
    return round(b - a, 4) if isinstance(a, (int, float)) and isinstance(b, (int, float)) else None


def _range(xs: list) -> Optional[list]:
    return [min(xs), round(statistics.median(xs), 4), max(xs)] if xs else None


# ── layer 1: the method on the private chain ─────────────────────────────────────────────────────────────────────────


def method_layer(states: dict, stored_states: dict, planned_states: dict) -> dict:
    """``states``: {cause: {date: state}} in ladder order (the reader); ``stored_states`` / ``planned_states``:
    {date: state} of the stored rows and the planned sheets (the same ``chain_state`` summary)."""
    order = list(states)
    dates = sorted(stored_states)
    first: dict = {q: {} for q in CHAIN}
    deltas: dict = {q: {} for q in CHAIN}
    changed_dates: dict = {}
    for d in dates:
        for q in CHAIN:
            prev = (stored_states.get(d) or {}).get(q)
            for cause in order:
                cur = ((states[cause].get(d)) or {}).get(q)
                if _moved(prev, cur):
                    first[q].setdefault(cause, 0)
                    first[q][cause] += 1
                    deltas[q].setdefault(cause, []).append(_delta(prev, cur))
                    break
                prev = cur
        prev_state = stored_states.get(d)
        for cause in order:
            cur_state = states[cause].get(d)
            if cur_state != prev_state:
                changed_dates.setdefault(d, []).append(cause)
            prev_state = cur_state
    i = order.index(CONTROL) if CONTROL in order else -1
    control_diff = [d for d in dates if i > 0 and states[order[i]].get(d) != states[order[i - 1]].get(d)]
    last_diff = [d for d in dates if order and states[order[-1]].get(d) != planned_states.get(d)]
    return {
        "order": order,
        "first_cause": {q: dict(sorted(v.items(), key=lambda kv: -kv[1])) for q, v in first.items()},
        "first_cause_range": {q: {c: _range([x for x in xs if x is not None]) for c, xs in v.items()} for q, v in deltas.items()},
        "control_differs": control_diff,
        "last_step_differs_from_plan": last_diff,
        "private_changed_dates": changed_dates,
    }


def method_events(states: dict, stored_states: dict, served_keys: set) -> list:
    """Every private-chain event (Mind aside) that differs between the stored rows and the last step, with the FIRST step
    that removes or adds it and whether the public routes served it before."""
    order = list(states)
    rows = []

    def keys(state: Optional[dict]) -> set:
        return {
            (str(e.get("who")), str(e.get("type")), _norm(e.get("new")))
            for e in (state or {}).get("events") or []
            if str(e.get("who")) not in PRIVATE_ONLY
        }

    for d in sorted(stored_states):
        before, after = keys(stored_states.get(d)), keys(states[order[-1]].get(d)) if order else set()
        for kind, evs in (("REMOVED", before - after), ("ADDED", after - before)):
            for key in sorted(evs):
                prev, cause = before, None
                for c in order:
                    cur = keys(states[c].get(d))
                    if (key in prev) != (key in cur):
                        cause = c
                        break
                    prev = cur
                who, typ, new = key
                rows.append(
                    {
                        "date": d,
                        "who": who,
                        "event": typ,
                        "level": new,
                        "change": kind,
                        "first_cause": cause,
                        "served_before": (d, who, new) in served_keys,
                        "protected_pillar": who in PROTECTED,
                    }
                )
    return rows


def _norm(v: Any) -> Any:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return str(int(f)) if f == int(f) else str(round(f, 4))


# ── layer 2: the public delta, privacy vs method ─────────────────────────────────────────────────────────────────────


def public_layer(before: dict, parts: list, final: dict, private_changed_dates: dict) -> dict:
    """``before`` / ``final``: {date: {quantity: value}}; ``parts``: [(name, {date: {quantity: value}})] cumulative, the
    last part being ``method`` (= ``final``). Per part: dates moved and the delta range; the residual; the unattributed
    method-part changes (no ladder step changed the private chain on that date or before)."""
    per = {n: {q: [] for q in PUBLIC_Q} for n, _v in parts}
    moved = {n: {q: 0 for q in PUBLIC_Q} for n, _v in parts}
    residual: dict = {q: [] for q in PUBLIC_Q}
    unattributed = []
    changed_by = sorted(private_changed_dates)
    for d in sorted(final):
        for q in PUBLIC_Q:
            prev = (before.get(d) or {}).get(q)
            for name, vals in parts:
                cur = (vals.get(d) or {}).get(q)
                if _moved(prev, cur):
                    moved[name][q] += 1
                    dl = _delta(prev, cur)
                    if dl is not None:
                        per[name][q].append(dl)
                    if name == "method" and not any(x <= d for x in changed_by):
                        unattributed.append(f"{d} {q}")
                prev = cur
            if _moved(prev, (final.get(d) or {}).get(q)):
                residual[q].append(d)
    return {
        "parts": [n for n, _v in parts],
        "by_part": {n: {q: {"dates": moved[n][q], "range": _range(per[n][q])} for q in PUBLIC_Q} for n, _v in parts},
        "residual": {q: len(v) for q, v in residual.items() if v},
        "unattributed": unattributed,
    }


def quantities(view: Optional[dict], composite: Any) -> dict:
    v = view or {}

    def num(x: Any) -> Any:
        try:
            return None if x is None else round(float(x), 4)
        except (TypeError, ValueError):
            return None

    out = {q: num(v.get(q)) for q in ("character_level", "character_xp", "character_xp_debt")}
    out["composite"] = composite(view)
    return out


def _views(cli: Any, sheets: dict, char: dict) -> dict:
    out = {}
    for d, item in sheets.items():
        pub = (char.get(d) or {}).get("public")
        out[d] = quantities(cli.served_view(item, pub) if pub else None, cli.route_composite)
    return out


def public_attribution(cli: Any, snap: dict, config: dict, run_ts: str, plan_path: str, char: dict) -> dict:
    """Both layers and the method event table, for the public manifest (per-date detail stays in the private manifest)."""
    import backfill_public_variant_events as EV
    import recompute_character_private_apply as A
    import recompute_character_private_report as PR

    stored = snap["stored_sheets"]
    states = A.ladder_states(plan_path)
    stored_states = {d: PR.chain_state(item) for d, item in stored.items()}
    planned_states = {d: PR.chain_state(item) for d, item in A.planned_sheets(plan_path).items()}
    layer1 = method_layer(states, stored_states, planned_states)
    base = dict(snap, sheets=stored)
    before = {d: quantities(cli.served_view(item, None), cli.route_composite) for d, item in stored.items()}
    final = _views(cli, snap["sheets"], char)
    parts = [
        ("privacy", _views(cli, stored, cli.run_replays(base, config, run_ts, order_fix=False)[0])),
        ("habit_timing", _views(cli, stored, cli.run_replays(base, config, run_ts, order_fix=True)[0])),
        ("method", final),
    ]
    served = {(e["date"], e["who"], _norm(e["new"])) for e in EV.served_events([stored[d] for d in sorted(stored)], old_rule=True)}
    layer1["events"] = method_events(states, stored_states, served)
    layer2 = public_layer(before, parts, final, layer1.pop("private_changed_dates"))
    return {"method": layer1, "public": layer2}


def failures(att: dict) -> list:
    """Why the combined run fails (empty = it passes)."""
    m, p = att.get("method") or {}, att.get("public") or {}
    out = []
    if m.get("control_differs"):
        out.append(f"the control step {CONTROL} differs from its predecessor on {len(m['control_differs'])} date(s)")
    if m.get("last_step_differs_from_plan"):
        out.append(f"the last ladder step differs from the planned sheets on {len(m['last_step_differs_from_plan'])} date(s)")
    if p.get("unattributed"):
        out.append(f"{len(p['unattributed'])} public change(s) no ladder step produces")
    return out
