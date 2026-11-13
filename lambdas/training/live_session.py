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
        if not new and code == "equipment":  # a trunk slot keeps direct trunk work (live_program.TRUNK_FALLBACK_ORDER, heuristic)
            from training import live_program, live_week

            new = live_program.trunk_fallback(e, ctx, taken)
            why = f"{why}; no same-function member — the nearest trunk job (TRUNK_FALLBACK_ORDER, heuristic)" if new else why
            if not new:  # a vertical pull keeps a vertical pull (live_week.VERTICAL_PULL_FALLBACK, heuristic; gates fail-closed)
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
    """The draft path's live hook (`full_body_session._prescription`): equipment and pain on every exposure, then the fatigue
    model (`fatigue_model.for_live_draft`, its one graded reduction). In shadow: `rx` itself, nothing read. Never raises.
    `week` (#5861 FIX5): the served day's week plan (`live_sequence.entry_week`, on the day entry) — its skipped roles, the
    host of the carry and trunk floor, this session's full-body partner; `set_cap` the week grid's session set ceiling."""
    if not is_live(rotation):
        return rx
    from training import fatigue_model, live_balance, live_program, live_rules, live_week

    out = copy.deepcopy(rx)
    lines: list[str] = []
    ctx: dict[str, Any] | None = None
    behind = None
    try:
        from training import selection_engine as se

        lib = se.load_library_failsoft() or {}
        catalog = catalog_movements or {}
        sig: dict[str, Any] = (
            fatigue_model.movement_signals(
                block_workouts,
                as_of=str(getattr(inputs, "target_date", "")),
                deficit=fatigue_model.in_deficit(getattr(inputs, "weights_by_day", None)),  # #5861 FIX7: held in a deficit = held
            )
            if block_workouts
            else {}
        )
        n_hurt = fatigue_model.THRESHOLDS["discomfort_sessions"]["value"]
        hurts = {tid for tid, v in sig.items() if v.get("discomfort_sessions", 0) >= n_hurt}
        from training import live_pain  # #5861 FIX7: discomfort at or under 2/10 keeps the lift (lighter), never swaps it out

        hurts -= live_pain.low_discomfort(block_workouts)
        light = {tid for tid, v in sig.items() if v.get("light_sessions", 0) + v.get("discomfort_sessions", 0) >= n_hurt} - hurts
        ctx = {
            "lib": lib,
            "catalog": catalog,
            "idx": se.key_index(lib, catalog),
            "overlay": se.load_overlay_failsoft(),
            "ceiling": SKILL_CEILING,
            "role": rx.get("session_role"),
            "discomfort": hurts,
            "light_discomfort": light,  # FIX5: a joint-located "sore" at the mild line — the joint rule keeps it, lighter
            "target_date": str(getattr(inputs, "target_date", "") or ""),
            "sick_days": getattr(inputs, "sick_days", None),  # #5861 FIX8: a declared illness opens the return week
        } | _week_ctx(week, inputs)
        from training import live_safety  # #5861 FIX4: the pain note's site and the mild line, read once

        ctx |= {"mild_pain": live_safety.mild_pain_tids(block_workouts), "pain_notes": live_safety.latest_notes(block_workouts)}
        lines += [str((week or {})["line"])] if (week or {}).get("line") else []
        lines += live_rules.full_body(out, ctx)  # FIX5: a short week's full-body day takes its partner's anchors (then fitted)
        lines += fit_exposures(out, rotation or {}, ctx)
        from training import live_progress  # #5861 FIX8: the first week back after 10+ days off runs at RPE 7-8, no steps

        back = live_progress.apply_return_week(out, ctx, block_workouts)  # before the plan: no stall reset in a return week
        lines += live_program.plan(out, rotation or {}, ctx, block_workouts, sig)  # joint pain, stacking, stalls, fatigue cost
        lines += back
        live_progress.cap_return(out, ctx, block_workouts)  # the plan's own additions (the carry, a slot) at the band too
        from training import live_stimulus  # #5861 FIX7: a fast cut with broad regression answers with volume, never load

        lines += live_stimulus.fast_cut(out, sig, inputs)
        lines += live_week.novel_start(out, ctx, block_workouts)  # a movement new to him never starts at 4-6 reps
        behind = live_balance.adherence_response(block_workouts, ctx["target_date"], lib)  # FIX3: a dip changes the week
        lines += live_week.keep_the_anchors(out, ctx, behind) + live_balance.lighter_week(out, ctx, behind)
        from training import live_rulings  # #5861 FIX6 ruling 3: AFTER the dip's lighter week, so it is never undone

        lines += live_rulings.arms_top_up(out, ctx, block_workouts) + live_rulings.arms_keep(out, ctx, block_workouts)
        _refit(out)
    except Exception as e:  # noqa: BLE001 — the live fit never blocks a draft
        lines.append(f"live session fit failed ({type(e).__name__}) — the prescription is unchanged")
        out = copy.deepcopy(rx)
        sig = {}
    before = [len(x["sets"]) for x in out["exposures"]]
    order = live_program.trim_order(surplus_first(catalog_movements or {}))  # high-fatigue work first, then surplus isolation
    if behind:  # the keep-the-anchors week IS the adherence answer: no further set trim for adherence on top of it
        order.adherence = lambda exposures: []
    out = fatigue_model.for_live_draft(out, rotation, inputs, block_workouts, trim_order=order)
    for x, n in zip(out["exposures"], before):
        if len(x["sets"]) < n:
            x["live_reduced"] = n - len(x["sets"])
    from training import live_shape  # #5861 FIX4: the kettlebell slot under strain (kb_slot_under_strain)

    strained = live_shape.kb_under_strain(out)
    if strained:  # #5861 FIX6: the slot dropped under strain (ruling 7) — its plan line "added ... host this week" goes with it
        lines = [ln for ln in lines if not (ln.startswith("added (live)") and "kettlebell slot" in ln)]
    lines += strained
    waits = live_rules.no_added_work(out)  # FIX5: nothing ADDED on a bad day — and the plan's "added" line for it goes
    gone = [str((catalog_movements or {}).get(k, {}).get("title") or k) for k in live_rules.waited(waits)]
    lines = [ln for ln in lines if not (ln.startswith("added (live)") and any(f": {t}" in ln for t in gone))] + waits
    if ctx is not None:
        try:  # the week's trunk-stability floor: purpose-driven, never on a strained day (live_program.trunk_floor)
            lines += live_program.trunk_floor(out, ctx, (out.get("fatigue") or {}).get("state"))
            _refit(out)
        except Exception as e:  # noqa: BLE001 — never blocks a draft
            lines.append(f"trunk floor failed ({type(e).__name__}) — nothing added")
    if ctx is not None:  # FIX7: every muscle with an MEV reaches it in HARD sets — after the trunk floor, never on a bad day
        from training import live_stimulus

        lines += live_stimulus.week_floor(out, ctx, block_workouts, set_cap)
        _refit(out)
    lines += live_rules.fit_set_cap(out, set_cap)  # FIX5: every live session within the session set ceiling (a crash before)
    _refit(out)
    from training import live_rulings  # #5861 FIX6 ruling 16: evidence confidence + data completeness, visible

    lines += live_rulings.evidence_line(out, ctx) if ctx is not None else []
    trends = {tid: str(v.get("trend")) for tid, v in (sig or {}).items()}
    extra = {
        "aerobic": live_program.aerobic(inputs),
        "trends": trends,
        # the medical stop line, read — and (FIX5) a symptom he logged on a Hevy note in the last fortnight
        "symptom_tripwire": live_week.symptom_gate(
            getattr(inputs, "medical_stop_lines", None), block_workouts, getattr(inputs, "target_date", None)
        ),
        "conditioning_host": live_balance.conditioning_host((ctx or {}).get("week_skip") or _week_ctx(week, inputs)["week_skip"]),
        "week_skip": list((ctx or {}).get("week_skip") or _week_ctx(week, inputs)["week_skip"]),  # FIX6: the time trim's week count
        "week_mode": (ctx or {}).get("week_mode"),  # FIX8: the arms floor's level in the time fit (`live_shape.precious`)
    }
    rate = live_rulings.rate_line(inputs, out.get("fatigue"), out.get("session_role"))  # FIX6 ruling 11: once a week, advisory
    band = live_balance.rate_band(out.get("fatigue"), getattr(inputs, "sleep_hours", None))  # FIX3: rate_band_mode=structured
    extra |= {"rate_band": band} if band["mode"] == "structured" else {}
    if rate:
        from training import live_stimulus

        rate += live_stimulus.rate_suffix(out)  # FIX7: the advisory line names the fast-cut answer
    out[MARK] = {"issue": ISSUE, "lines": lines + ([rate] if rate else []), **extra}
    from training import live_progress

    tids = {
        str((catalog_movements or {}).get(str(e.get("movement_key")), {}).get("hevy_template_id_hint") or "").upper()
        for e in out["exposures"]
    }
    out[MARK]["refs"] = live_progress.role_refs(block_workouts, tids - {""})  # FIX8: the load guard's role-keyed references
    return out


def _week_ctx(week: dict[str, Any] | None, inputs: Any) -> dict[str, Any]:
    """The week plan's context keys (#5861 FIX5): `short_week_host`, `week_skip` (the roles this week does not draft) and
    `partner` (this session's full-body partner). Without a plan, the generator's old `short_week` attribute (a host role)
    still reads as a shoulders+arms skip."""
    from training.live_program import SHORT_WEEK_SKIP

    if week:
        return {
            "short_week_host": week.get("host"),
            "week_skip": tuple(week.get("skip") or ()),
            "partner": week.get("partner"),
            "week_mode": week.get("mode"),  # #5861 FIX6: short (fewer mornings) or the dip's own mode — the arms top-up's target
        }
    host = getattr(inputs, "short_week", None)
    return {"short_week_host": host, "week_skip": (SHORT_WEEK_SKIP,) if host else (), "partner": None}


def surplus_first(catalog: dict[str, Any]) -> Any:
    """The fatigue model's trim order: take sets first from the accessory whose muscle the program's week loads furthest above
    its MEV landmark (config/training_landmarks.json), ties last-listed first — a recovery trim never takes a muscle sitting at
    its minimum effective dose (the crunch, the calves) below it while the delts sit near MAV. Heuristic over existing data."""
    from collections import Counter

    from training import block_model, live_week, program_structure as ps, selection_engine as se

    marks = block_model.load_landmarks() or {}
    lib = se.load_library_failsoft()

    def muscle(key: Any) -> str:  # a catalog `other` (the kettlebell slot) reads the library's target (second red team)
        m = (catalog.get(key or "") or {}).get("primary_muscle")
        return live_week.landmark_muscle(key, catalog, lib) if m in (None, "other") else str(m)

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
        return [e for e in ranked for _ in range(max(1, len(e.get("sets") or []) - 1))]  # drain the top surplus first

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
    """IN PLACE: under live, drop accessory blocks, last-listed first, until the routine's minutes as written (warm-ups
    included) fit `cap`; anchors never. Returns the session shape (re-measured when anything went). Shadow: `shape`."""
    if MARK not in rx or shape.get("lifting_minutes") is None:
        return shape
    from training import live_week

    cap = min(int(cap), int(rx.get("live_session_cap") or cap))  # a behind-schedule session's ~45 min (live option)
    shape = live_week.make_cardio_room(blocks, rx, movements, cap, shape)  # shared cap: lifting gives sets for an aerobic block
    from training import live_shape  # #5861 FIX4: drop, don't shave — no accessory left at one working set

    singles = live_shape.no_single_sets(blocks, movements)
    if singles:
        from training import program_structure as _ps, warmup_sets as _ws

        shape = _ps.enforce_session_shape(blocks, movements) | {"working_sets": sum(_ws.working_set_count(b.sets) for b in blocks)}
        rx[MARK]["lines"].append(f"dropped (live): {', '.join(singles)} — one working set left: drop, don't shave (live_shape)")
    if shape["lifting_minutes"] <= cap:
        return shape
    from training import program_structure
    from training.session_shape import routine_minutes

    before, dropped = shape["lifting_minutes"], []
    trimmed = live_week.trim_sets_for_time(blocks, rx, movements, cap)  # second red team: sets before exercises
    gone = Counter(trimmed)  # #5861 FIX4: what the drop order counts as off (the trimmed sets + every dropped accessory)
    guests = live_shape.trim_anchor_backoffs(blocks, rx, movements, cap, guests=True)  # FIX8: a full-body day's guest back-offs
    fixed = live_week._fixed(rx)
    while routine_minutes(blocks, movements)["lifting_minutes"] > cap:
        idx = live_shape.next_drop(blocks, movements, gone, fixed, rx)  # FIX4: largest surplus over MEV first
        if idx is None:
            break
        # FIX8: before a kept slot (a floor's, the only ab work) or a priority muscle's last sets under MEV go, the back-offs
        if str(blocks[idx].movement_key) in fixed or live_shape.precious(blocks[idx], movements, gone, rx):
            guests += live_shape.trim_anchor_backoffs(blocks, rx, movements, cap, guests=False)
            if routine_minutes(blocks, movements)["lifting_minutes"] <= cap:
                break
        cut = blocks.pop(idx)
        _unpair(blocks, getattr(cut, "superset_id", None))
        dropped.append((movements.get(cut.movement_key) or {}).get("title") or cut.movement_key)
    dropped += live_shape.no_single_sets(blocks, movements)
    anchors = live_shape.trim_anchor_backoffs(blocks, rx, movements, cap, guests=False)  # FIX8: the ceiling holds, always
    from training import warmup_sets

    new = program_structure.enforce_session_shape(blocks, movements) | {
        "working_sets": sum(warmup_sets.working_set_count(b.sets) for b in blocks)
    }
    how = [", ".join(f"{n} {m}" for m, n in sorted(trimmed.items())) + " set(s) off (surplus over MEV first)"] if trimmed else []
    how += (  # FIX8: before "dropped …", which ends the line's list of whole exercises
        [f"anchor back-offs off: {', '.join(f'{n} {k}' for k, n in Counter(guests + anchors).items())} (TIME_FIT)"]
        if guests + anchors
        else []
    )
    how += [f"dropped {', '.join(dropped)}"] if dropped else []
    line = f"time (live): ~{before} min as written (warm-ups included) > the {cap}-min lifting cap — {'; '.join(how)} -> ~{new['lifting_minutes']} min"
    rx[MARK]["lines"].append(line)  # `rationale_lines` writes it
    rationale[:] = [r for r in rationale if not r.startswith(f"OVER the {cap}-min lifting cap")]
    return new


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
    """The live fit's lines and the fatigue model's decision, for the rationale. Shadow: []."""
    if MARK not in rx:
        return []
    out = list(rx[MARK]["lines"])
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
