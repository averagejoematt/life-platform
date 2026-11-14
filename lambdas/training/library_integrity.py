"""library_integrity.py — the exercise library's integrity rules (#5861 fix round 13, owner rulings 2026-11-14).

Pure over the library dict: no reads, no clock, no import of the loader. `exercise_library.validate` runs `problems(lib)`
on every build and in CI, so a library that breaks a rule here is refused. Four rules, each stated once.

1. LOGGABLE. A movement can be selected automatically only when the Hevy record can represent it: its own `template_id`,
   or a VERIFIED CANONICAL MAPPING (`logs_as`: it is logged under another member of its own canonical family, whose
   template holds no other exercise's history). Anything else is not selectable, whatever its other flags say
   (`unloggable`; `selection_engine.not_for_you_now` reads it).

2. AVAILABILITY. Every equipment id, and every movement, carries one of five EVIDENCE states for home_gym:
   `owner_confirmed`, `recent_inferred`, `historical_only`, `unknown`, `confirmed_unavailable` (`AVAILABILITY_EVIDENCE`).
   The engine's `state` follows from it and from nothing else (`EVIDENCE_STATE`): only owner-confirmed and
   recent-inferred equipment is `available`; a machine known only from old logs, or never logged, is `unknown` and is not
   served. A movement's evidence is the WORST of its equipment's. `recent_inferred` is a HEURISTIC: used by a movement
   logged within `RECENT_WINDOW_MONTHS` of the history's last workout. The basic classes (`BASIC_EQUIPMENT`) are
   inferred as a class from the same recent use and are never confirmed one by one.

3. FALLBACKS — THE ONE EQUIVALENCE RULE (`fallback_problems`). B is a fallback for A only when it serves the same
   training function in A's slot:
     purpose    the same category (hypertrophy, strength, conditioning, athletic, mobility, rehab/control, carry). One
                crossing is allowed: a strength lift may fall back to a hypertrophy lift that is itself strength-rated.
     function   the same named movement pattern, or a recognised substitute pattern (`SUBSTITUTE_PATTERNS`), or another
                member of the same canonical family. A movement whose pattern is not named is matched only on its
                declared function (trunk function, or function label). Conditioning modalities substitute for each other.
     stimulus   the same primary target muscle, the same job (compound or isolation), the same trunk function and, for
                mobility and rehab work, the same kind of work. A shared family label, or a shared muscle alone, is not
                equivalence.
   and B is valid in itself: equipment `available` at home_gym; no locking gate and no `not_for_you_now`; loggable; and
   suitable (skill no higher than A's, no joint rated two levels worse, no higher impact, not ballistic unless A is).
   Nothing is added to fill a list: a movement with no equivalent has NO fallbacks, and the served week drops the slot.

4. GATES. A readiness chain is acyclic and reachable (`gate_audit`): every chain gate names a prerequisite that is a
   library movement the Hevy record can measure (a template id or a title rule), that is not confirmed unavailable, and
   whose own chain steps lead — without ever returning to a gate already on the path — to an entry movement that carries
   no chain step. A standard uses only what a Hevy set records (`STANDARD_KEYS`). Every non-global gate is carried by a
   movement. Nothing here opens a gate: reachable means a path exists, not that it has been walked.
"""

from __future__ import annotations

from typing import Any, Optional

LOCATION = "home_gym"
LEVEL = {"low": 0, "moderate": 1, "high": 2}

# ── 1. loggable ──────────────────────────────────────────────────────────────
UNLOGGABLE_CODE = "needs_custom_hevy_template"


def log_template(entry: dict[str, Any]) -> Optional[str]:
    """The Hevy template id a set of this movement is logged under: its own, or its verified canonical mapping's. None =
    the Hevy record cannot represent it."""
    tid = entry.get("template_id") or (entry.get("logs_as") or {}).get("template_id")
    return str(tid).upper() if tid else None


def unloggable(entry: dict[str, Any]) -> Optional[str]:
    """Why this movement cannot be selected automatically (rule 1), or None when it is loggable."""
    if log_template(entry):
        return None
    return "no Hevy template id and no verified canonical mapping: the Hevy record cannot represent it"


def _loggable_problems(mv: dict[str, dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for key, e in mv.items():
        la = e.get("logs_as")
        if la is not None:
            head = mv.get(str(la.get("movement_id")))
            if e.get("template_id"):
                out.append(f"movements.{key}: logs_as on a movement that has its own template_id")
            elif head is None or not head.get("template_id") or str(head["template_id"]) != str(la.get("template_id")):
                out.append(f"movements.{key}: logs_as must name a library movement and carry that movement's template_id")
            elif (e.get("canonical") or key) != (head.get("canonical") or la.get("movement_id")) or not la.get("why"):
                out.append(f"movements.{key}: logs_as is verified only inside one canonical family, with its reason")
        if unloggable(e) and (e.get("not_for_you_now") or {}).get("reason_code") != UNLOGGABLE_CODE:
            out.append(f"movements.{key}: not loggable, so it must be not_for_you_now ({UNLOGGABLE_CODE})")
        if not unloggable(e) and (e.get("not_for_you_now") or {}).get("reason_code") == UNLOGGABLE_CODE:
            out.append(f"movements.{key}: marked {UNLOGGABLE_CODE} but it is loggable")
    return out


# ── 2. availability ──────────────────────────────────────────────────────────
AVAILABILITY_EVIDENCE = ("owner_confirmed", "recent_inferred", "historical_only", "unknown", "confirmed_unavailable")
EVIDENCE_STATE = {
    "owner_confirmed": "available",
    "recent_inferred": "available",
    "historical_only": "unknown",
    "unknown": "unknown",
    "confirmed_unavailable": "unavailable",
}
_WORST_FIRST = ("confirmed_unavailable", "unknown", "historical_only", "recent_inferred", "owner_confirmed")
RECENT_WINDOW_MONTHS = 12
"""HEURISTIC (platform-proposed, #5861 fix round 13): equipment used by a movement logged in the last 12 months of the Hevy
history is very likely still there. One window, anchored on the history's own last workout, never on the wall clock."""
BASIC_EQUIPMENT = (
    "bodyweight",
    "barbell",
    "ez_bar",
    "dumbbell",
    "kettlebell",
    "weight_plate",
    "squat_rack",
    "bench_flat",
    "bench_adjustable",
    "cable_stack",
    "lat_pulldown_station",
    "pullup_bar",
    "resistance_band",
)
"""The basic classes: free weights, the benches and rack they need, the cable stations, the pull-up bar, bands and
bodyweight. Every commercial club has them, one is interchangeable with another (there is no machine-specific design to
confirm), and a wrong assumption costs a swap, not a session. They are inferred as a class and never confirmed one by one.
A named machine, a specialty bar or bench, and cardio kit are NOT basic: each is judged from its own logs."""


def worst_evidence(states: list[str]) -> str:
    """A movement's evidence: the worst of its equipment's (rule 2). No equipment listed is `unknown`."""
    return next((s for s in _WORST_FIRST if s in states), "unknown")


def _availability_problems(lib: dict[str, Any]) -> list[str]:
    out: list[str] = []
    items = (lib.get("gym_inventory") or {}).get("items") or {}
    for eid, row in items.items():
        st = (row or {}).get(LOCATION) or {}
        if st.get("evidence") not in AVAILABILITY_EVIDENCE:
            out.append(f"gym_inventory.{eid}: evidence {st.get('evidence')!r} is not one of the five states")
        elif st.get("state") != EVIDENCE_STATE[st["evidence"]]:
            out.append(f"gym_inventory.{eid}: state {st.get('state')!r} does not follow from evidence {st['evidence']!r}")
    for key, e in (lib.get("movements") or {}).items():
        av = (e.get("availability") or {}).get(LOCATION) or {}
        want = worst_evidence([str(((items.get(x) or {}).get(LOCATION) or {}).get("evidence")) for x in e.get("equipment") or []])
        if av.get("evidence") != want:
            out.append(f"movements.{key}: availability evidence {av.get('evidence')!r} is not the worst of its equipment ({want})")
        elif av.get("state") != EVIDENCE_STATE[want]:
            out.append(f"movements.{key}: availability state {av.get('state')!r} does not follow from evidence {want!r}")
    return out


# ── 3. fallbacks: the one equivalence rule ───────────────────────────────────
FALLBACK_REASONS = ("same_stimulus", "substitute_pattern", "same_function", "canonical_variant")
MAX_FALLBACKS = 3
SUBSTITUTE_PATTERNS: dict[frozenset[str], str] = {
    frozenset(
        ("press", "horizontal_press")
    ): "a press the pattern table does not name, for the same primary target, is that target's press",
    frozenset(("press", "vertical_press")): "a press the pattern table does not name, for the same primary target, is that target's press",
}
"""The recognised substitute patterns, each with its reason. Deliberately short: a row is not a fly for a press, a
lateral pull for a vertical one, or a single-joint lift for a compound."""
NOT_A_MUSCLE = ("other", "unknown", "full_body", "mobility", "cardio")
LOADED_CROSSING = ("strength", "hypertrophy")  # the one purpose crossing: a strength lift -> a strength-rated hypertrophy lift
PREP_CATEGORIES = ("mobility", "rehab_control")
JOINTS = ("spinal_load", "shear", "wrist", "elbow", "shoulder", "knee", "hip")
FALLBACK_CLAUSES = (
    "purpose",
    "function",
    "stimulus",
    "unavailable",
    "gated",
    "not_for_you_now",
    "unloggable",
    "skill",
    "joint_stress",
    "impact",
    "ballistic",
)


def locking_gates(lib: dict[str, Any], e: dict[str, Any]) -> list[str]:
    gates = lib.get("gates") or {}
    return [g for g in e.get("gates") or [] if (gates.get(g) or {}).get("locks")]


def _inputs(e: dict[str, Any]) -> dict[str, Any]:
    return e.get("objective_inputs") or {}


def _family(mv: dict[str, dict[str, Any]], key: str) -> str:
    return str((mv.get(key) or {}).get("canonical") or key)


def _ballistic(e: dict[str, Any]) -> bool:
    return (
        e.get("family") == "skill_athletic"
        or e.get("category") == "athletic"
        or e.get("pattern") == "olympic"
        or "power" in (_inputs(e).get("functional") or [])
    )


def _named(pattern: Any) -> bool:
    return bool(pattern) and pattern != "other"


def _function_match(a: dict[str, Any], b: dict[str, Any], same_family: bool) -> Optional[str]:
    """The fallback REASON when `b` does `a`'s movement function, else None (the `function` clause)."""
    pa, pb = a.get("pattern"), b.get("pattern")
    if a.get("category") == "conditioning":
        return "same_function" if _inputs(a).get("conditioning") and _inputs(b).get("conditioning") else None
    if _named(pa) and pa == pb:
        return "same_stimulus"
    if same_family:
        return "canonical_variant"
    if frozenset((str(pa), str(pb))) in SUBSTITUTE_PATTERNS:
        return "substitute_pattern"
    if not _named(pa) and not _named(pb):
        if a.get("trunk_function") and a.get("trunk_function") == b.get("trunk_function"):
            return "same_function"
        if a.get("functions") and sorted(a["functions"]) == sorted(b.get("functions") or []):
            return "same_function"
    return None


def _equivalence_breaks(a: dict[str, Any], b: dict[str, Any], same_family: bool) -> list[str]:
    out: list[str] = []
    ca, cb = a.get("category"), b.get("category")
    crossing = (ca, cb) == LOADED_CROSSING and ((b.get("ratings") or {}).get("strength") or {}).get("tier") is not None
    if ca != cb and not crossing:
        out.append("purpose")
    if _function_match(a, b, same_family) is None:
        out.append("function")
    ta, tb = (a.get("target") or {}).get("primary"), (b.get("target") or {}).get("primary")
    conditioning = ca == "conditioning"
    same_target = ta == tb and (ta not in NOT_A_MUSCLE or same_family or conditioning)
    same_work = a.get("job") == b.get("job") and a.get("trunk_function") == b.get("trunk_function")
    if ca in PREP_CATEGORIES and _inputs(a).get("mobility") != _inputs(b).get("mobility"):
        same_work = False
    if not (same_target and same_work):
        out.append("stimulus")
    return out


def _suitability_breaks(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    out: list[str] = []
    if LEVEL.get(str(b.get("skill_complexity")), 0) > LEVEL.get(str(a.get("skill_complexity")), 0):
        out.append("skill")
    ja, jb = a.get("joint_stress") or {}, b.get("joint_stress") or {}
    if any(j in LEVEL and i in LEVEL and LEVEL[j] - LEVEL[i] >= 2 for i, j in ((str(ja.get(x)), str(jb.get(x))) for x in JOINTS)):
        out.append("joint_stress")
    ia, ib = (_inputs(a).get("conditioning") or {}).get("impact"), (_inputs(b).get("conditioning") or {}).get("impact")
    if ia in LEVEL and ib in LEVEL and LEVEL[ib] > LEVEL[ia]:
        out.append("impact")
    if _ballistic(b) and not _ballistic(a):
        out.append("ballistic")
    return out


def fallback_problems(lib: dict[str, Any], key: str, fb: str) -> list[str]:
    """Every clause of THE rule (module doc 3, `FALLBACK_CLAUSES`) that `fb` breaks as a fallback for `key`. Empty = valid."""
    mv = lib.get("movements") or {}
    a, b = mv.get(key), mv.get(fb)
    if a is None or b is None or key == fb:
        return ["function"]
    out = _equivalence_breaks(a, b, _family(mv, key) == _family(mv, fb))
    if ((b.get("availability") or {}).get(LOCATION) or {}).get("state") != "available":
        out.append("unavailable")
    if locking_gates(lib, b):
        out.append("gated")
    if unloggable(b):
        out.append("unloggable")
    elif b.get("not_for_you_now"):
        out.append("not_for_you_now")
    return [c for c in FALLBACK_CLAUSES if c in out + _suitability_breaks(a, b)]


def fallback_candidates(lib: dict[str, Any], key: str) -> list[tuple[str, str]]:
    """Every valid fallback for `key` as (movement id, reason), ranked: the same named pattern first, then no equipment
    shared with `key` (a missing item must be a swap, not the same hole), then the same length bias, then the more
    familiar (history exposures). The builder keeps the first `MAX_FALLBACKS`; fewer, or none, is correct."""
    mv = lib.get("movements") or {}
    me = mv[key]
    my_eq = set(me.get("equipment") or [])
    ranked = []
    for k, e in mv.items():
        if k == key or fallback_problems(lib, key, k):
            continue
        reason = _function_match(me, e, _family(mv, key) == _family(mv, k)) or "same_function"
        shares = bool(set(e.get("equipment") or []) & my_eq)
        exposures = int(((e.get("history") or {}).get("exposures")) or 0)
        ranked.append(((reason != "same_stimulus", shares, e.get("length_bias") != me.get("length_bias"), -exposures, k), k, reason))
    return [(k, reason) for _, k, reason in sorted(ranked)]


def _fallback_errors(lib: dict[str, Any]) -> list[str]:
    out: list[str] = []
    mv = lib.get("movements") or {}
    for key, e in mv.items():
        fbs = e.get("fallbacks")
        if not isinstance(fbs, list) or len(fbs) > MAX_FALLBACKS:
            out.append(f"movements.{key}: fallbacks must be a list of at most {MAX_FALLBACKS} (an empty list is valid)")
            continue
        for fb in fbs:
            ref = fb.get("movement_id")
            if ref not in mv or ref == key:
                out.append(f"movements.{key}: fallback {ref!r} is not another library movement")
                continue
            if fb.get("reason") not in FALLBACK_REASONS:
                out.append(f"movements.{key}: fallback reason {fb.get('reason')!r}")
            broken = fallback_problems(lib, key, ref)
            if broken:
                out.append(f"movements.{key}: fallback {ref} breaks the equivalence rule ({', '.join(broken)})")
    return out


# ── 4. gates: acyclic, reachable, measurable ─────────────────────────────────
CHAIN_KINDS = ("chain_prerequisite", "performance_threshold")  # the kinds `exercise_gates` walks as a chain
STANDARD_KEYS = (
    "sets",
    "reps_min",
    "rpe_max",
    "sessions_min",
    "prerequisite_sessions_min",
    "span_weeks_min",
    "flag_free_days",
    "hang_seconds_min",
    "assistance_fraction_max",
)
"""What a logged Hevy set can show the evaluator (`exercise_gates._set_meets` / `standard_verdict`). A lowering tempo is
NOT here: no Hevy template type records reps and time on the same set, so a standard that needs both can never be met."""


def _chain_steps(lib: dict[str, Any], mid: str) -> list[str]:
    gates = lib.get("gates") or {}
    e = (lib.get("movements") or {}).get(mid) or {}
    return [g for g in e.get("gates") or [] if (gates.get(g) or {}).get("kind") in CHAIN_KINDS]


def _measurable(e: dict[str, Any]) -> bool:
    return bool(e.get("template_id") or (e.get("template_match") or {}).get("title_all"))


def _walk(lib: dict[str, Any], gid: str, path: tuple[str, ...], seen: dict[str, Any]) -> dict[str, Any]:
    """One gate's chain, depth first: its errors, its entry movements and what it still waits on (memoised per gate)."""
    if gid in path:
        return {"errors": [f"cycle: {' -> '.join(path[path.index(gid) :] + (gid,))}"], "entry": [], "waits": []}
    if gid in seen:
        return seen[gid]
    gates, mv = lib.get("gates") or {}, lib.get("movements") or {}
    g = gates.get(gid) or {}
    errors: list[str] = []
    entry: list[str] = []
    waits: list[str] = []
    if g.get("kind") == "chain_prerequisite" and not g.get("chain_prerequisites"):
        errors.append("a chain gate names no prerequisite movement")
    extra = sorted(set(g.get("standard") or {}) - set(STANDARD_KEYS))
    if extra:
        errors.append(f"the standard needs what no Hevy set records: {', '.join(extra)}")
    for p in g.get("chain_prerequisites") or []:
        e = mv.get(p)
        if e is None:
            errors.append(f"prerequisite {p} is not a library movement")
            continue
        if not _measurable(e):
            errors.append(f"prerequisite {p} has no Hevy template and no title rule: its sessions cannot be measured")
        ev = ((e.get("availability") or {}).get(LOCATION) or {}).get("evidence")
        if ev == "confirmed_unavailable":
            errors.append(f"prerequisite {p} needs equipment confirmed unavailable at {LOCATION}")
        elif EVIDENCE_STATE.get(str(ev)) != "available":
            waits.append(f"{p}: equipment {ev} at {LOCATION} (owner to confirm)")
        if unloggable(e):
            waits.append(f"{p}: no Hevy template yet (on the creation list)")
        waits += [f"{p}: locked by {x} ({gates[x].get('kind')})" for x in locking_gates(lib, e) if gates[x].get("kind") not in CHAIN_KINDS]
        steps = _chain_steps(lib, p)
        if not steps:
            entry.append(p)
        for step in steps:
            sub = _walk(lib, step, path + (gid,), seen)
            errors += [x if x.startswith("cycle") else f"{p} -> {step}: {x}" for x in sub["errors"]]
            entry += sub["entry"]
            waits += sub["waits"]
    out = {"errors": list(dict.fromkeys(errors)), "entry": sorted(set(entry)), "waits": list(dict.fromkeys(waits))}
    if not any(x.startswith("cycle") for x in errors):
        seen[gid] = out
    return out


def gate_audit(lib: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Per gate: kind, prerequisites, the movements that carry it, the entry movement(s) its chain starts from, the errors
    that make it unreachable (rule 4) and what it still waits on. `reachable_today` is the public reading: no error and
    nothing waited on (an owner-set threshold, a confirmation and the charter's own gates are owner inputs, reported by
    kind — a pure library read cannot see them)."""
    gates, mv = lib.get("gates") or {}, lib.get("movements") or {}
    carried: dict[str, list[str]] = {gid: [] for gid in gates}
    for key, e in mv.items():
        for gid in e.get("gates") or []:
            carried.setdefault(gid, []).append(key)
    out: dict[str, dict[str, Any]] = {}
    seen: dict[str, Any] = {}
    for gid, g in gates.items():
        chain = g.get("kind") in CHAIN_KINDS
        walk = _walk(lib, gid, (), seen) if chain else {"errors": [], "entry": [], "waits": []}
        errors = list(walk["errors"])
        if g.get("applies_to") != "all" and not carried.get(gid):
            errors.append("no movement carries this gate")
        out[gid] = {
            "kind": g.get("kind"),
            "prerequisites": list(g.get("chain_prerequisites") or []),
            "carriers": sorted(carried.get(gid) or []),
            "entry": walk["entry"],
            "errors": errors,
            "waits": walk["waits"],
            "reachable_today": (not errors and not walk["waits"]) if chain else None,
        }
    return out


def _gate_errors(lib: dict[str, Any]) -> list[str]:
    return [f"gates.{gid}: {err}" for gid, row in gate_audit(lib).items() for err in row["errors"]]


# ── the build-time check ─────────────────────────────────────────────────────
def problems(lib: dict[str, Any]) -> list[str]:
    """Every integrity violation in the library (rules 1-4), as readable strings. Empty = the library holds."""
    mv = lib.get("movements") or {}
    return _loggable_problems(mv) + _availability_problems(lib) + _fallback_errors(lib) + _gate_errors(lib)
