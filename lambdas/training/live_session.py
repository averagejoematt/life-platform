"""live_session.py — the session-level half of the LIVE policy (#5861 L6): what the drafted session itself must respect
once the exercise library is `approved` (`selection_engine.mode() == "live"`). In shadow every function here returns its
input untouched, before reading anything (tests/test_no_live_change_5861_l6.py proves the served drafts byte-identical).

WHY IT EXISTS. The integrated engine was run over synthetic sample weeks (scripts/sample_weeks_5861.py) and inspected like a
coach would. Four things the selection engine cannot see — it ranks accessory slots, like for like — broke the session:

  1. EQUIPMENT AND PAIN ON EVERY EXPOSURE. The selection excludes an unavailable or pain-flagged movement from an accessory
     slot, but an ANCHOR is resolved by `program_structure` from its catalog list, and a slot with no eligible candidate
     falls back to the template's accessory: both could prescribe a machine the gym lacks or the press his pain note named.
     Here every exposure is checked against the library's home_gym availability (`selection_engine.availability`) and the
     #5806 pain class (`selection_engine.pain_exclusion`): an anchor takes the next member of its pattern that is available,
     pain-free and prescribable; an accessory takes the slot's first usable selection fallback; with neither the exposure is
     SKIPPED and said so — never an impossible or painful prescription, never a filler.
  2. ONE GRADED REDUCER. Today a red readiness tier (or an ACWR "high") drops EVERY accessory (`_autoreg_multiplier` 0.6).
     Both are HR-derived (Whoop recovery, Whoop strain), and HR is not effort evidence until a post-regime baseline exists
     (owner ruling); a red week stripped the aesthetic day to one press set and left every muscle under its MEV. Under live
     the fatigue model is the one reducer: readiness and ACWR are ONE vote among its independent strain signals (sleep, cardio
     load, weekly sets, strength trend, effort drift), and two or more take accessory sets off in steps, anchors held.
  3. THE 75-MINUTE CEILING ON THE ROUTINE AS WRITTEN. The prescription is fitted to the ceiling before the warm-up pass, which
     adds a "find the load" set to every movement with no recent load — so a session with new accessories ran ~80 minutes.
     Here the routine's own minutes (`session_shape.routine_minutes`, warm-ups as written) are fitted: accessories go,
     last-listed first; anchors never (the charter's rule, `trim_to_time`).
  4. ONE STORY. The rotation's pool lines ("rotated: X -> Y") describe the #5075 pools the live selection replaced; under live
     only the selection's own lines are kept, and every live change (a fatigue reduction, a skipped or swapped exposure, a
     time trim) is written into the rationale and onto the first lift's Hevy note.

Every rule here is a heuristic over existing owner rulings (75-minute ceiling, accessories first, anchors never cut, the pain
class, home_gym availability); none is a new number.
"""

from __future__ import annotations

import copy
from collections import Counter
from typing import Any

ISSUE = "#5861"
MODE_LIVE = "live"
MARK = "live_session"
"""The prescription key that says this draft ran the live session fit (absent in shadow, so every later hook is a no-op)."""
POOL_LINE_PREFIXES = ("rotated:", "held:")
GRADED_MARK = "live: one HR-derived vote"
"""The rationale words a live draft writes when readiness/ACWR reached the drop line; `routine_title.format_why_note` reads
them so the WHY line never says "deloading today" for a session the fatigue model only trimmed."""
SKILL_CEILING = 2  # the week grid's accessory ceiling (#4080); the four core anchor families resolve at the ruling's own


def is_live(rotation: dict[str, Any] | None) -> bool:
    return ((rotation or {}).get("selection") or {}).get("mode") == MODE_LIVE


# ── 1. equipment and pain on every exposure ──────────────────────────────────
STRESS_ORDER = {"low": 0, "moderate": 1, "high": 2}
JOINTS = ("shoulder", "elbow", "wrist", "spinal_load", "shear", "knee", "hip")  # #5861 FIX4: knee + hip (the pain map)
NOT_LIFTS = ("duration", "distance_duration", "short_distance_weight", "weight_duration", "floors_duration", "steps_duration")


def _entry(key: str | None, ctx: dict[str, Any]) -> dict[str, Any] | None:
    lid = ctx["idx"]["to_lib"].get(str(key)) if key else None
    return (ctx["lib"].get("movements") or {}).get(lid) if lid else None


def _blocked(key: str | None, ctx: dict[str, Any], anchor: bool) -> tuple[str, str] | None:
    """(code, why) when `key` can't be prescribed today — `equipment` (home_gym), `pain` (a #5806 pain-class note) or, on an
    anchor, `discomfort` (two discomfort-class notes in 14 days: an accessory's own discomfort is the selection's call) —
    else None. A movement the library can't place is judged by nothing (the selection's own rule)."""
    from training import selection_engine as se

    if not key or key not in ctx["catalog"]:
        return ("catalog", "not in the movement catalog")
    entry = _entry(key, ctx)
    if entry is None:
        return None
    why = se.availability(entry, ctx["lib"], ctx["overlay"])
    if why:
        return ("equipment", why)
    why = se.pain_exclusion(entry, ctx["overlay"])
    from training.live_safety import blocked_pain_is_mild

    if why and not blocked_pain_is_mild(entry, ctx):  # #5861 FIX4: a mild (<= 3/10, not sharp) note keeps the lift, lighter
        return ("pain", why)
    if anchor and str(entry.get("template_id") or "").upper() in ctx["discomfort"]:
        return ("discomfort", "two discomfort-class notes on it inside 14 days (fatigue_model, heuristic)")
    return None


def _worst_joint(entry: dict[str, Any] | None) -> tuple[str, int] | None:
    stress = (entry or {}).get("joint_stress") or {}
    known = [(j, STRESS_ORDER[str(stress.get(j))]) for j in JOINTS if str(stress.get(j)) in STRESS_ORDER]
    return max(known, key=lambda x: x[1]) if known else None


def _anchor_candidates(e: dict[str, Any], ctx: dict[str, Any], role: str | None) -> list[str]:
    """The role's own pinned members for the pattern (`anchor_keys`), else the pattern's listed members (moderate members
    first on a moderate exposure), then every catalog movement of that anchor family, best strength-then-hypertrophy rating
    first — the order the anchor lists themselves encode."""
    from training import program_structure as ps

    a = ps.ANCHORS.get(str(e.get("pattern"))) or {}
    pinned = list(((ps.SESSION_TEMPLATES.get(str(role)) or {}).get("anchor_keys") or {}).get(str(e.get("pattern"))) or [])
    keys = list(a.get("moderate_catalog_keys") or []) if e.get("intensity") == "moderate" else []
    keys = pinned + keys + list(a.get("catalog_keys") or [])
    rank = {t: i for i, t in enumerate("SABCD")}

    def tier(k: str) -> tuple[int, int, str]:
        r = (_entry(k, ctx) or {}).get("ratings") or {}
        return (rank.get(str((r.get("strength") or {}).get("tier")), 9), rank.get(str((r.get("hypertrophy") or {}).get("tier")), 9), k)

    family = sorted((k for k, c in ctx["catalog"].items() if c.get("anchor_family") == e.get("pattern")), key=tier)
    return list(dict.fromkeys(keys + family))


def _slot_fallbacks(e: dict[str, Any], rotation: dict[str, Any]) -> list[str]:
    sel = (rotation.get("selection") or {}).get("slots") or []
    role = ((rotation.get("slots") or [{}])[0]).get("role")
    hit: dict[str, Any] = next((s for s in sel if s.get("role") == role and s.get("incumbent") == e.get("slot")), {})
    return [str(f["catalog_key"]) for f in hit.get("fallbacks") or [] if f.get("catalog_key")]


def _replacement(
    e: dict[str, Any],
    code: str,
    ctx: dict[str, Any],
    rotation: dict[str, Any],
    taken: set[str],
    limit: tuple[str, int] | None = None,
    unilateral: bool = False,
) -> str | None:
    """The first usable replacement: for an anchor its pattern's members (`_anchor_candidates`) at the ceiling the anchor
    resolves at (the #4080 exemption for the four core families only); for an accessory the slot's selection fallbacks.
    After a PAIN or DISCOMFORT flag the replacement must load the flagged movement's worst joint strictly less (the library's
    joint-stress ratings) — another press with the same shoulder stress is not an answer to a shoulder pain note. `limit`
    (live_program: a joint flag, axial stacking) caps one joint below a stress level; `unilateral` prefers a unilateral member
    (a single-leg slot stays single-leg) before any other."""
    from training import program_conflicts

    anchor = e.get("kind") == "anchor"
    ruling = program_conflicts.ANCHOR_SKILL_CEILING_RULING
    exempt = anchor and e.get("pattern") in ruling["exempt_families"]
    ceiling = int(ruling["effective_ceiling"]) if exempt else ctx["ceiling"]
    worst = _worst_joint(_entry(e.get("movement_key"), ctx)) if code in ("pain", "discomfort") else limit
    if code == "pain":  # #5861 FIX4: the joint the pain NOTE names, when it names one the library rates
        from training.live_safety import pain_limit

        worst = pain_limit(_entry(e.get("movement_key"), ctx), ctx) or worst
    pool = _anchor_candidates(e, ctx, ctx.get("role")) if anchor else _slot_fallbacks(e, rotation)
    if not anchor:  # #5861 FIX3: then the library's same-pattern, same-muscle members (a banded curl for a garage leg curl)
        from training.live_balance import library_fallbacks

        pool = list(dict.fromkeys(pool + library_fallbacks(e, ctx)))
    if unilateral:
        uni = [k for k in pool if "unilateral" in (((_entry(k, ctx) or {}).get("objective_inputs") or {}).get("functional") or [])]
        pool = uni + [k for k in pool if k not in uni]
    for k in pool:
        c = ctx["catalog"].get(k) or {}
        if k in taken or int(c.get("skill_tier", 99)) > ceiling or c.get("hevy_type") in NOT_LIFTS:
            continue
        if worst and STRESS_ORDER.get(str(((_entry(k, ctx) or {}).get("joint_stress") or {}).get(worst[0])), 9) >= worst[1]:
            continue
        if _blocked(k, ctx, anchor) is None and _servable(k, ctx) is None:
            return k
    return None


def _servable(key: str, ctx: dict[str, Any]) -> str | None:
    """A REPLACEMENT must also be servable the way the selection serves one: no locking gate (fail-closed here — the swap
    never opens a gate the selection has not) and no `not_for_you_now`. The served movement itself is never re-judged on these."""
    from training import selection_engine as se

    entry = _entry(key, ctx)
    if entry is None:
        return None
    return ("gate locked" if se.locked_gates(entry, ctx["lib"]) else None) or se.not_for_you_now(entry)


def fit_exposures(rx: dict[str, Any], rotation: dict[str, Any], ctx: dict[str, Any]) -> list[str]:
    """IN PLACE on `rx["exposures"]`: every exposure the gym can't serve or his pain note names is swapped (module doc 1) or
    skipped. Returns the rationale lines. Sets, reps, rest and the slot are kept; only the movement changes."""
    lines: list[str] = []
    keep: list[dict[str, Any]] = []
    taken = {str(e.get("movement_key")) for e in rx["exposures"] if e.get("movement_key")}
    for e in rx["exposures"]:
        hit = _blocked(e.get("movement_key"), ctx, e.get("kind") == "anchor") if e.get("movement_key") else None
        if not hit:
            keep.append(e)
            continue
        code, why = hit
        old = e["movement_key"]
        new = _replacement(e, code, ctx, rotation, taken)
        name = (ctx["catalog"].get(old) or {}).get("title") or old
        if not new and code == "equipment":  # a vertical pull keeps a vertical pull (VERTICAL_PULL_FALLBACK, heuristic; fail-closed)
            from training import live_week

            new = live_week.vertical_pull_fallback(e, ctx, taken)
            why = f"{why}; no pulldown — the first servable vertical pull (VERTICAL_PULL_FALLBACK, heuristic)" if new else why
        if new:
            taken.add(new)
            keep.append(e | {"movement_key": new, "template_id": None, "live_swap": {"from": old, "code": code}})
            lines.append(f"swapped (live): {name} -> {(ctx['catalog'].get(new) or {}).get('title') or new} — {code}: {why}")
        elif code == "discomfort":
            keep.append(e)
            lines.append(f"kept (live): {name} — {why}, but no member loads its joints less; the fatigue model weighs it")
        else:
            lines.append(
                f"skipped (live): {name} — {code}: {why}; "
                + (
                    "no usable member of its pattern loads that joint less"
                    if code != "equipment"
                    else "no member of its pattern is available"
                )
                + " — nothing fills it"
            )
    rx["exposures"] = [{k: v for k, v in e.items() if not (k == "template_id" and v is None)} for e in keep]
    return lines


def for_live_draft(
    rx: dict[str, Any],
    rotation: dict[str, Any] | None,
    inputs: Any,
    block_workouts: list[dict[str, Any]] | None,
    catalog_movements: dict[str, Any] | None = None,
    week: dict[str, Any] | None = None,
    set_cap: int | None = None,
) -> dict:
    """The draft path's live hook (`full_body_session._prescription`). In shadow: `rx` itself, nothing read. Never raises.
    Fix round 9's ONE pass, in order: the week's volume plan (`live_volume`: this morning's share, a short week's full-body
    composition), equipment and pain on every exposure, novelty (`live_load.mark_novelty`), the joint / stacking / lead-lift
    programming (`live_program.plan`), the systemic slump (`live_load.slump`), the fatigue model's one reducer, the set ceiling.
    `week`: the served day's week plan (`live_sequence.entry_week`, on the day entry); `set_cap` the session set ceiling."""
    if not is_live(rotation):
        return rx
    from training import fatigue_model, live_load, live_program, live_volume

    out = copy.deepcopy(rx)
    lines: list[str] = []
    ctx: dict[str, Any] | None = None
    hold_all = None
    plan_rows: dict[str, float] = {}
    lib: dict[str, Any] = {}
    catalog = catalog_movements or {}
    try:
        from training import selection_engine as se

        lib = se.load_library_failsoft() or {}
        target = str(getattr(inputs, "target_date", "") or "")
        sig: dict[str, Any] = fatigue_model.movement_signals(block_workouts, as_of=target) if block_workouts else {}
        n_hurt = fatigue_model.THRESHOLDS["discomfort_sessions"]["value"]
        from training import live_pain, live_safety

        hurts = {tid for tid, v in sig.items() if v.get("discomfort_sessions", 0) >= n_hurt} - live_pain.low_discomfort(block_workouts)
        light = {tid for tid, v in sig.items() if v.get("light_sessions", 0) + v.get("discomfort_sessions", 0) >= n_hurt} - hurts
        ctx = {
            "lib": lib,
            "catalog": catalog,
            "idx": se.key_index(lib, catalog),
            "overlay": se.load_overlay_failsoft(),
            "ceiling": SKILL_CEILING,
            "role": rx.get("session_role"),
            "discomfort": hurts,
            "light_discomfort": light,
            "target_date": target,
            "mild_pain": live_safety.mild_pain_tids(block_workouts),
            "pain_notes": live_safety.latest_notes(block_workouts),
        } | _week_ctx(week, inputs)
        mornings = int((week or {}).get("days") or 5)
        plan = live_volume.week_plan(catalog, lib, mornings)
        ctx["volume_plan"] = plan
        role_rows = [r for r in plan["rows"] if r["role"] == rx.get("session_role")]
        plan_rows = dict(live_volume._count(role_rows))
        lines += [str((week or {})["line"])] if (week or {}).get("line") else []
        lines += live_volume.apply(out, ctx, plan)
        lines += fit_exposures(out, rotation or {}, ctx)
        live_load.mark_novelty(out, ctx, block_workouts)
        lines += live_program.plan(out, rotation or {}, ctx, block_workouts, sig)
        lines += live_volume.pair_anchors(out, plan)
        tids = {str(catalog.get(str(e.get("movement_key")), {}).get("hevy_template_id_hint") or "").upper() for e in out["exposures"]}
        anchors = _anchor_tids(catalog)
        hist = live_load.history(block_workouts, (tids | anchors) - {""})
        slump = live_load.slump(hist, anchors, fatigue_model.in_deficit(getattr(inputs, "weights_by_day", None)), target)
        if slump:
            hold_all = "slump week, loads held"
            lines += [f"slump (live): {slump['declining']} of {slump['judged']} anchors declining together — every load held"]
            lines += live_load.slump_trim(out)
        _refit(out)
    except Exception as e:  # noqa: BLE001 — the live fit never blocks a draft
        lines.append(f"live session fit failed ({type(e).__name__}) — the prescription is unchanged")
        out = copy.deepcopy(rx)
        sig, hist = {}, {}
    before = [len(x["sets"]) for x in out["exposures"]]
    order = live_program.trim_order(surplus_first(catalog))
    out = fatigue_model.for_live_draft(out, rotation, inputs, block_workouts, trim_order=order)
    for x, n in zip(out["exposures"], before):
        if len(x["sets"]) < n:
            x["live_reduced"] = n - len(x["sets"])
    lines += live_volume.fit_sets(out, set_cap, catalog, lib)
    _refit(out)
    if ctx is not None:
        from training import live_rulings

        lines += live_rulings.evidence_line(out, ctx)
    trends = {tid: str(v.get("trend")) for tid, v in (sig or {}).items()}
    from training import live_balance, live_week

    skip = (ctx or {}).get("week_skip") or _week_ctx(week, inputs)["week_skip"]
    extra = {
        "aerobic": live_program.aerobic(inputs),
        "trends": trends,
        "symptom_tripwire": live_week.symptom_gate(
            getattr(inputs, "medical_stop_lines", None), block_workouts, getattr(inputs, "target_date", None)
        ),
        "conditioning_host": live_balance.conditioning_host(skip),
        "week_skip": list(skip),
        "hist": hist,
        "hold_all": hold_all,
        "layoff": (ctx or {}).get("layoff"),
        "plan_rows": plan_rows if ctx is not None else {},
    }
    from training import live_rulings

    rate = live_rulings.rate_line(inputs, out.get("fatigue"), out.get("session_role"))
    out[MARK] = {"issue": ISSUE, "lines": lines + ([rate] if rate else []), **extra}
    return out


def _anchor_tids(catalog: dict[str, Any]) -> set[str]:
    """The template ids of every anchor the five templates serve (the slump's anchors)."""
    from training import program_structure as ps

    out = set()
    for role in ps.SPLIT_ROLES:
        for e in ps.session_prescription_for_role(role, catalog_movements=catalog)["exposures"]:
            if e.get("kind") == "anchor":
                out.add(str((catalog.get(str(e.get("movement_key"))) or {}).get("hevy_template_id_hint") or "").upper())
    return out - {""}


def _week_ctx(week: dict[str, Any] | None, inputs: Any) -> dict[str, Any]:
    """The week plan's context keys: `short_week_host`, `week_skip` (the roles this week does not draft), `partner` (this
    session's full-body partners) and `week_mode`."""
    if week:
        return {
            "short_week_host": week.get("host"),
            "week_skip": tuple(week.get("skip") or ()),
            "partner": week.get("partner"),
            "week_mode": week.get("mode"),
        }
    return {"short_week_host": None, "week_skip": (), "partner": None}


def surplus_first(catalog: dict[str, Any]) -> Any:
    """The fatigue model's trim order: take sets first from the accessory whose muscle the program's week loads furthest above
    its MEV landmark (config/training_landmarks.json), ties last-listed first — a recovery trim never takes a muscle sitting at
    its minimum effective dose below it while the delts sit near MAV. Heuristic over existing data."""
    from training import block_model, live_volume, program_structure as ps, selection_engine as se

    marks = block_model.load_landmarks() or {}
    lib = se.load_library_failsoft() or {}

    def muscle(key: Any) -> str:
        c = live_volume.credits(live_volume.lib_entry(key, catalog, lib), key, catalog)
        return max(c, key=c.get) if c else "other"

    week: Counter = Counter()
    for role in ps.SPLIT_ROLES:
        for e in ps.session_prescription_for_role(role, catalog_movements=catalog)["exposures"]:
            week[muscle(e.get("movement_key"))] += len(e["sets"])

    def surplus(e: dict[str, Any]) -> float:
        m = muscle(e.get("movement_key"))
        return week[m] - float((marks.get(m) or {}).get("MEV") or week[m])

    def order(exposures: list[dict[str, Any]]) -> list[dict[str, Any]]:
        acc = [e for e in exposures if e.get("kind") == "accessory"]
        ranked = sorted(acc, key=lambda e: (-surplus(e), -acc.index(e)))
        return [e for e in ranked for _ in range(max(1, len(e.get("sets") or []) - 1))]

    return order


def _refit(rx: dict[str, Any]) -> None:
    from training.session_cues import exposure_cue
    from training.session_shape import session_minutes_estimate

    for e in rx["exposures"]:
        e["cue"] = exposure_cue(e["intensity"], e["sets"])
    rx["total_sets"] = sum(len(e["sets"]) for e in rx["exposures"])
    rx["session_minutes"] = session_minutes_estimate(rx["exposures"])


# ── 2. one graded reducer ────────────────────────────────────────────────────
def drop_accessories(autoreg: float, rx: dict[str, Any], rationale: list[str], drop_at: float) -> bool:
    """Shadow: today's rule exactly (`autoreg <= drop_at`, 0.6, drops every accessory). Live: never wholesale — the fatigue
    model's graded reduction already took its sets (module doc 2), and the HR-derived tier is one of its votes."""
    if MARK not in rx:
        return autoreg <= drop_at
    if autoreg <= drop_at:
        fat = rx.get("fatigue") or {}
        rationale.append(
            f"readiness/ACWR at the drop line (autoreg {autoreg:.2f}) — {GRADED_MARK} in the fatigue model, not a "
            f"wholesale accessory drop; the model reads {fat.get('state') or 'unknown'} and took {fat.get('sets_removed') or 0} "
            "accessory set(s), anchors held"
        )
    return False


# ── 3. the 75-minute ceiling on the routine as written ───────────────────────
def _unpair(blocks: list[Any], sid: Any) -> None:
    from training.program_structure import EXPOSURES

    for b in blocks:
        if sid is not None and getattr(b, "superset_id", None) == sid:
            b.superset_id = None
            if not getattr(b, "rest_seconds", None):
                b.rest_seconds = int(EXPOSURES["accessory"]["rest_seconds"])


def fit_routine(blocks: list[Any], rx: dict[str, Any], cap: int, movements: dict[str, Any], rationale: list[str], shape: dict) -> dict:
    """IN PLACE: under live, the ONE time fit (`live_volume.time_fit`) on the routine as written (warm-ups included). Returns the
    session shape (re-measured when anything went). Shadow: `shape`."""
    if MARK not in rx or shape.get("lifting_minutes") is None:
        return shape
    if shape["lifting_minutes"] > cap:
        from training import live_volume, program_structure, warmup_sets

        rx[MARK]["lines"] += live_volume.time_fit(blocks, rx, movements, int(cap))
        rationale[:] = [r for r in rationale if not r.startswith(f"OVER the {cap}-min lifting cap")]
        shape = program_structure.enforce_session_shape(blocks, movements) | {
            "working_sets": sum(warmup_sets.working_set_count(b.sets) for b in blocks)
        }
    rx[MARK]["summary"] = summary(blocks, rx, movements)
    rx[MARK]["contradictions"] = contradictions(blocks, rx)
    return shape


def _title(key: Any, movements: dict[str, Any]) -> str:
    return str((movements.get(str(key)) or {}).get("title") or key)


def summary(blocks: list[Any], rx: dict[str, Any], movements: dict[str, Any]) -> list[str]:
    """The 3-5 rationale lines that change what he does today, generated from the FINAL routine (fix round 9: the rest of the
    live lines stay on the record as `rx[MARK]["lines"]`, the debug view). Never a line about something the routine lacks."""
    mark = rx.get(MARK) or {}
    here = {b.movement_key for b in blocks}
    exp = {e.get("movement_key"): e for e in rx.get("exposures") or [] if e.get("movement_key") in here}
    out = [ln for ln in mark.get("lines") or [] if ln.startswith(("short week (live", "adherence dip week (live"))][:1]
    guard = [d for d in mark.get("load_guard") or [] if d["key"] in here]
    for mode, head in (("up", "heavier"), ("down", "lighter"), ("second", "RPE 7-8 (the second lift)")):
        names = [_title(d["key"], movements) + (f" ({d['why']})" if mode == "down" else "") for d in guard if d["mode"] == mode]
        if names:
            out.append(f"today: {head}: {', '.join(names)}")
    if mark.get("hold_all"):
        out.append(f"today: every load held — {mark['hold_all']}")
    back = [_title(k, movements) for k, e in exp.items() if e.get("live_first_back")]
    new = [_title(k, movements) for k, e in exp.items() if e.get("live_new")]
    if back:
        out.append(
            f"today: first session back after {((mark.get('layoff') or {}).get('gap_days')) or '10+'} days off — RPE 8, no step: {', '.join(back)}"
        )
    if new:
        out.append(f"today: new to you, RPE 7 once: {', '.join(new)}")
    out += _zero_by_design(blocks, rx, movements)
    gone = [ln for ln in mark.get("lines") or [] if ln.startswith(("skipped (live)", "swapped (live)"))]
    out += [ln.split(" — ")[0].replace(" (live)", "") for ln in gone][:1]
    fat = rx.get("fatigue") or {}
    if fat.get("state") in ("strained", "overreached") or fat.get("sets_removed"):
        out.append(f"today: recovery reads {fat.get('state')} — {fat.get('sets_removed') or 0} accessory set(s) off, anchors kept")
    return out[:5]


def _zero_by_design(blocks: list[Any], rx: dict[str, Any], movements: dict[str, Any]) -> list[str]:
    """Fix round 9 (F): a priority muscle the week's plan gives this morning that the pain rule took to ZERO is said plainly —
    never "held" (the eighth red team's garage + sharp shoulder: chest 0 while a line claimed 8)."""
    from training import live_settings, live_volume, selection_engine as se

    lib = se.load_library_failsoft() or {}
    plan = (rx.get(MARK) or {}).get("plan_rows") or {}
    prio = [str(m) for m in live_settings.settings(lib).get("priority_muscles") or []]
    final = live_volume.hard_sets(
        (live_volume.lib_entry(b.movement_key, movements, lib), 1, None, b.movement_key, movements) for b in blocks
    )
    pain = [ln for ln in (rx.get(MARK) or {}).get("lines") or [] if ln.startswith("skipped (live)") and (" pain" in ln or "flag" in ln)]
    out = []
    for m in prio:
        if plan.get(m) and not final.get(m) and pain:
            out.append(
                f"today: {m} 0 here by design — the pain rule took its pressing/squatting off and no lower-stress {m} "
                "option is available; it returns when the flag clears"
            )
    return out


def contradictions(blocks: list[Any], rx: dict[str, Any]) -> list[str]:
    """Where a lift's note says something its own rows or the live decision contradict (fix round 9, G): a heavier/lighter
    reason against the decision, a "find the load" over a written load, a layoff line on a lift of a familiar pattern.
    [] = consistent. (The low-energy line's cardio promise is fitted on the WHY block, `live_balance.why_effort`.)"""
    from training import hevy_note_grammar as g

    guard = {d["key"]: d for d in (rx.get(MARK) or {}).get("load_guard") or []}
    exp = {e.get("movement_key"): e for e in rx.get("exposures") or []}
    out = []
    for i, b in enumerate(blocks):
        note, d, e = str(getattr(b, "notes", "") or ""), guard.get(b.movement_key), exp.get(b.movement_key) or {}
        work = [s for s in b.sets or [] if str(getattr(s, "type", "") or "normal") != "warmup"]
        if d and d["mode"] == "up" and ("Lighter today" in note or "Same load" in note):
            out.append(f"{b.movement_key}: steps up but the note holds or lightens it")
        if d and d["mode"] == "down" and "Heavier" in note:
            out.append(f"{b.movement_key}: steps down but the note says heavier")
        if g.PICK_LOAD_OPEN_TAIL in note and work and all(getattr(s, "weight_kg", None) for s in work):
            out.append(f"{b.movement_key}: 'find the load' over a written load")
        if e.get("live_familiar") and not e.get("live_first_back") and ("first time in" in note or "session back after" in note):
            out.append(f"{b.movement_key}: a layoff line on a familiar pattern")
    return out


# ── 4. one story ─────────────────────────────────────────────────────────────
def rotation_lines(rotation: dict[str, Any]) -> list[str]:
    """The rotation's rationale. Live: the #5075 pool lines for slots the selection served are dropped (they name movements
    the session does not serve); the selection's own lines say what serves and why. Shadow: unchanged."""
    lines = list(rotation.get("rationale") or [])
    if not is_live(rotation) or rotation.get("source") != "selection":
        return lines
    slots = rotation.get("slots") or []
    served = {s.get("slot_id") for s in slots if s.get("source") in ("selection", "ledger", "owner_approved")}
    lines = [ln for ln in lines if not (ln.startswith(POOL_LINE_PREFIXES) and any(f"[{sid}," in ln for sid in served))]
    # a phase the ledger already decided (its first draft, before the library was approved) keeps its movement until the next
    # phase: the selection's line then names what WILL serve, so it says what serves NOW
    picks = {s["slot_id"]: (s.get("pick") or {}).get("catalog_key") for s in (rotation.get("selection") or {}).get("slots") or []}
    kept = {s["slot_id"]: s["variant"] for s in slots if s.get("source") == "ledger" and s.get("variant") != picks.get(s.get("slot_id"))}
    return [
        (
            ln + f" — THIS phase serves {kept[sid]} (the rotation ledger: a phase's first draft decides it); the pick serves from the next"
            if ln.startswith("selection:") and (sid := next((k for k in kept if f" for {k} " in ln or ln.endswith(f" for {k}")), None))
            else ln
        )
        for ln in lines
    ]


def rationale_lines(rx: dict[str, Any]) -> list[str]:
    """The rationale's live lines: the 3-5 that change what he does (`summary`, from the final routine) and the fatigue model's
    decision; the rest of the live lines stay on the record (`rx[MARK]["lines"]`, the debug view). Shadow: []."""
    if MARK not in rx:
        return []
    out = list(rx[MARK].get("summary") or [])
    fat = rx.get("fatigue") or {}
    if fat:
        sig = ", ".join(fat.get("strain_signals") or []) or "none"
        out.append(
            f"fatigue (live): {fat.get('state')} — strain signals: {sig}; {fat.get('action')}"
            + (f" ({'; '.join(fat.get('reduce_reasons') or [])})" if fat.get("reduce_reasons") else "")
            + (f", {fat.get('sets_removed')} accessory set(s) off, anchors held" if fat.get("sets_removed") else "")
            + ("; a deload is RECOMMENDED — it applies only on your word" if (fat.get("deload") or {}).get("recommended") else "")
        )
    return out


def annotate_blocks(blocks: list[Any], rx: dict[str, Any]) -> None:
    """IN PLACE, live only: each lift the fatigue model took sets from says so on its own Hevy note, in the critic-change
    grammar (`session_block.applied_clause` — "2 sets today: recovery."). Matched by movement key (unique in a session).
    Shadow: nothing."""
    if MARK not in rx:
        return
    from training import live_program, session_block, warmup_sets

    live_program.annotate(blocks, rx)  # #5861 red team: the load guard's reason, the deload / joint-flag effort caps
    guarded = {d["key"] for d in rx[MARK].get("load_guard") or []}  # one reason per lift: the load line outranks the count
    cut = {e.get("movement_key") for e in rx.get("exposures") or [] if e.get("live_reduced") and e.get("kind") == "accessory"} - guarded
    for b in blocks:
        if b.movement_key in cut:
            clause = session_block.applied_clause("set_count", working_sets=warmup_sets.working_set_count(b.sets), reason="recovery")
            b.notes = session_block.add_reason(b.notes, clause)
