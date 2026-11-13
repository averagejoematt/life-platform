"""live_balance.py — the third red team's programming fixes (#5861 FIX3). LIVE only: every entry point is reached from a live
hook (`live_program.plan` / `annotate` / `cardio_fit` / `cardio_note` / `rate_line`, `live_session.for_live_draft` /
`_replacement`, `live_week.week_sets`), each of which returns before reading anything unless the draft ran the live session
fit (`live_session.MARK`, which exists only when the exercise library is `approved`) — or, for `template_resolver`, unless the
library is approved AND the owner set `kb_deadlift_template_id`. tests/test_no_live_change_5861_l6.py pins the served
proposed-mode drafts byte for byte.

WHY IT EXISTS. A third independent red team (2026-11-13) graded the integrated engine B- and named what an elite coach would
not sign in the GENERATED weeks. Each rule below answers one of its findings, measured on the generated weeks:

  1. ONE SPINE-LOADING DEFINITION (`spine_loading`), used by the stacking rule, the acceptance gates and the sample-week
     generator. The rule counted library spinal stress, the generator counted free-weight squat/hinge compounds (so a
     dumbbell reverse lunge read "axial" there and "low" here), and the stacking fix swapped a split squat for a reverse
     lunge that loads the spine the same — a label moved, not the fatigue (the data now rates the whole dumbbell-at-the-sides
     class low: `deploy/exercise_library_input_review.SPINE_AT_SIDES`).
  2. A REAL STACKING LIMIT AND THE KETTLEBELL SLOT (`kb_placement`, `place_kb`). Lower volume served RDL + back squat + the
     owner-pinned KB deadlift "kept light": three spine-loading lifts every week. The pinned slot is the movable one: its home
     (`kb_slot_role`, default the template's lower volume) keeps it unless that session already holds the limit, then it
     MOVES (`kb_slot_when_stacked`, default `move`, to `kb_slot_move_to`, default shoulders+arms) or is dropped (`drop`).
  3. PAIN THAT PERSISTS (`pain_assess`). A 6/10 sharp shoulder flag was routed around indefinitely. While a pain flag stands,
     the session carries one neutral line (`pain_assess_line`, on by default; "" turns it off): if it persists two sessions,
     get it assessed. No diagnosis, no number.
  4. VOLUME BY PRIORITY (`allocation_plan`, `allocate`). Delts sat at 18 (MAV 16) beside chest at its MEV. The week is
     allocated before it is drafted: every muscle over its MAV gives isolation sets (largest slot first, never under two
     sets) until it sits at MAV, and the freed sets go first to the priority muscles (`priority_muscles`, default chest,
     back, quadriceps, hamstrings — retention first) sitting at or under MEV + 1, one set per accessory slot.
  5. THE ADHERENCE DIP (`adherence_response`, `lighter_week`). Five of fourteen sessions done and the plan was a full week
     minus two sets. The default response is now fewer, shorter sessions focused on the anchors (`adherence_response`
     `short_week`: four mornings — shoulders+arms skipped, as in the short week — each fitted to ADHERENCE_DIP minutes, every
     accessory at two sets, anchors whole); the stricter keep-the-anchors week stays behind `behind_schedule_week`.
  6. THE LIBRARY FALLBACK (`library_fallbacks`). A garage week dropped the hamstring curl ("no member of its pattern is
     available") with a banded curl in the library: an accessory now searches the library's same-pattern, same-muscle members
     after its slot's ranked fallbacks.
  7. ONE EFFORT TARGET PER LIFT (`one_effort`, `effort_targets`). The first lift's note said "RPE 8–9 on big lifts" and then
     "RPE 6–7" for the same lift. When the first lift's own effort differs, the session line names the day only.
  8. CARDIO EQUIPMENT AND THE SHORT WEEK (`conditioning_host`, `cardio_machine`, `machine_label`). An equipment-limited week
     named a "Recumbent" with no recumbent; a short week under the shared cap had no conditioning host at all.
  9. THE OWNER'S OPEN DECISIONS AS SETTINGS, each with today's default: `kb_deadlift_template_id` (a custom "Kettlebell
     Deadlift" Hevy template, when he creates one, stops the KB pulls landing in the barbell Sumo Deadlift history),
     `body_fat_tier` (the rate band's starting rung; unknown today) and `rate_band_mode` (`advisory` text, or `structured` —
     the band recorded on the draft for a nutrition reader; nothing reads it back today).

Every number here is a labelled PLATFORM HEURISTIC (practitioner consensus at best), owner-adjustable; none is validated.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

ISSUE = "#5861"
HEURISTIC = "heuristic"
KB_SLOT_KEY = "kettlebell_swing"
"""The template slot the owner pinned (#5774): it serves the KB deadlift, then the swing (`kb_entry`)."""
KB_HOME = "lower_volume"
"""Where the program's templates place the kettlebell slot (`program_structure.SESSION_TEMPLATES`)."""
SETTINGS_DEFAULTS: dict[str, Any] = {
    "kb_slot_role": KB_HOME,
    "kb_slot_when_stacked": "move",
    "kb_slot_move_to": ["shoulders_arms", "upper_volume"],
    "kb_deadlift_template_id": None,
    "pain_assess_line": "Still hurts 2 sessions? Get it assessed.",
    "priority_muscles": ["chest", "back", "quadriceps", "hamstrings"],
    "adherence_response": "short_week",
    "body_fat_tier": None,
    "rate_band_mode": "advisory",
}
"""Library-carried settings (`programming_settings`), merged into `live_program.settings`. `kb_slot_role` is today's placement
(owner pin); `kb_slot_when_stacked` `move` | `drop`; `kb_deadlift_template_id` None = the owner-ruled Sumo Deadlift stand-in;
`kb_slot_move_to` the sessions it may move to, in order (under the shared cap the conditioning host is passed over: its minutes
are the aerobic block's); `pain_assess_line` "" turns the line off; `adherence_response` `short_week` (the default response to a dip) | `trim_sets`
(today's two sets off); `body_fat_tier` None = unknown; `rate_band_mode` `advisory` | `structured`."""
ALLOCATION: dict[str, dict[str, Any]] = {
    "over_mav_floor": {
        "value": 2,
        "label": HEURISTIC,
        "basis": "an isolation slot giving sets for an over-MAV muscle keeps at least two working sets (the slot keeps its stimulus)",
    },
    "priority_margin": {
        "value": 1,
        "label": HEURISTIC,
        "basis": "third red team (2026-11-13): a priority muscle 'at MEV' is at risk on any trimmed week; a muscle at or under "
        "MEV + 1 takes the freed sets first (retention of chest, back, quadriceps and hamstrings before any delt surplus)",
    },
    "add_per_slot": {"value": 1, "label": HEURISTIC, "basis": "one added set per accessory slot a week (no slot doubles)"},
}
ADHERENCE_DIP: dict[str, dict[str, Any]] = {
    "session_minutes": {
        "value": 60,
        "label": HEURISTIC,
        "basis": "after a dip (5+ of the fortnight's 10 planned sessions missed) a ~60-minute morning is easier to keep than a "
        "75-minute one; the anchors keep every set (strength is retained on the heavy work), the accessories carry the cut",
    },
    "accessory_sets": {"value": 2, "label": HEURISTIC, "basis": "every accessory at two working sets — the maintenance dose"},
}
HOST_ROLE = "shoulders_arms"


def _settings(lib: dict[str, Any] | None = None) -> dict[str, Any]:
    from training import live_program, selection_engine as se

    return live_program.settings(lib if lib is not None else se.load_library_failsoft())


def _entry(key: str | None, ctx: dict[str, Any]) -> dict[str, Any]:
    lid = ctx["idx"]["to_lib"].get(str(key)) if key else None
    return ((ctx["lib"].get("movements") or {}).get(lid) or {}) if lid else {}


# ── 1. one spine-loading definition ──────────────────────────────────────────
def spine_loading(entry: dict[str, Any] | None) -> bool:
    """THE spine-loading lift (one definition — the stacking rule, the gates and the sample-week generator read it): a
    squat- or hinge-pattern compound whose library spinal load is moderate or high. A carry is not one; a dumbbell lunge with
    the load at the sides is not one (its spinal load is low — `SPINE_AT_SIDES`)."""
    e = entry or {}
    spinal = str((e.get("joint_stress") or {}).get("spinal_load"))
    return e.get("pattern") in ("squat", "hinge") and e.get("job") == "compound" and spinal in ("moderate", "high")


# ── 2. the kettlebell slot's placement ───────────────────────────────────────
def _template_spine(role: str, catalog: dict[str, Any], lib: dict[str, Any]) -> int:
    """Spine-loading exposures the role's template serves, the kettlebell slot aside."""
    from training import program_structure as ps, selection_engine as se

    idx = se.key_index(lib, catalog)
    rx = ps.session_prescription_for_role(role, catalog_movements=catalog)
    mv = lib.get("movements") or {}
    return sum(
        1
        for e in rx["exposures"]
        if e.get("slot") != KB_SLOT_KEY and spine_loading(mv.get(idx["to_lib"].get(str(e.get("movement_key")))) or {})
    )


def kb_placement(lib: dict[str, Any], catalog: dict[str, Any], skipped: str | None = None) -> dict[str, Any]:
    """{home, host, why}: where the kettlebell slot serves this week. `home` is `kb_slot_role` (today's placement); when that
    session's template already holds STACK_RULE axial_per_session spine-loading lifts, the slot moves to `kb_slot_move_to`
    (`kb_slot_when_stacked` `move`, when that session has room and is drafted this week) or is dropped (`drop`, or no room).
    `skipped` is a role this week does not draft (the short week's)."""
    from training import live_program

    s = _settings(lib)
    cap = int(live_program.STACK_RULE["axial_per_session"]["value"])
    home = str(s["kb_slot_role"] or KB_HOME)
    if _template_spine(home, catalog, lib) < cap:
        return {"home": home, "host": home, "why": None}
    move_to = s["kb_slot_move_to"]
    targets = [str(t) for t in ([move_to] if isinstance(move_to, str) else (move_to or []))]
    busy = conditioning_host(skipped) if s.get("session_cap_includes_cardio") else None  # the shared cap's aerobic minutes
    why = f"{home} already holds {cap} spine-loading squat/hinge lifts (STACK_RULE, heuristic)"
    for to in targets if s["kb_slot_when_stacked"] == "move" else []:
        if to not in (skipped, busy, home) and _template_spine(to, catalog, lib) < cap:
            return {"home": home, "host": to, "why": why + f": the kettlebell slot moves to {to} (kb_slot_when_stacked=move)"}
    how = "kb_slot_when_stacked=drop" if s["kb_slot_when_stacked"] != "move" else "no move-to session is drafted with room"
    return {"home": home, "host": None, "why": why + f": the kettlebell slot is dropped this week ({how})"}


def place_kb(rx: dict[str, Any], ctx: dict[str, Any], workouts: Any) -> list[str]:
    """IN PLACE: the kettlebell slot leaves a session that is not its host this week and joins the host (`kb_placement`).
    The movement it serves follows `kb_entry` (the KB deadlift until two are logged, then the swing). Returns the lines."""
    from training import kb_entry, live_program as lp, program_structure as ps

    role = str(rx.get("session_role") or "")
    skipped = lp.SHORT_WEEK_SKIP if ctx.get("short_week_host") else None
    p = kb_placement(ctx["lib"], ctx["catalog"], skipped)
    lines: list[str] = []
    here = [e for e in rx["exposures"] if e.get("slot") == KB_SLOT_KEY]
    if here and role != p["host"]:
        rx["exposures"] = [e for e in rx["exposures"] if e.get("slot") != KB_SLOT_KEY]
        title = (ctx["catalog"].get(here[0].get("movement_key")) or {}).get("title") or here[0].get("movement_key")
        verb = f"moved (live): {title} -> {p['host']}" if p["host"] else f"dropped (live): {title}"
        lines.append(f"{verb} — {p['why'] or 'kb_slot_role=' + str(p['home'])}")
    if role == p["host"] and not any(e.get("slot") == KB_SLOT_KEY for e in rx["exposures"]):
        tmpl = ps.session_prescription_for_role(KB_HOME, catalog_movements=ctx["catalog"])
        slot = next((e for e in tmpl["exposures"] if e.get("slot") == KB_SLOT_KEY), None)
        if slot is not None:
            n = kb_exposures(workouts, ctx.get("target_date"), ctx["lib"])
            key = kb_entry.served(n)
            rx["exposures"].append(dict(slot, movement_key=key, live_added="kb_slot_moved"))
            title = (ctx["catalog"].get(key) or {}).get("title") or key
            lines.append(f"added (live): {title} — the kettlebell slot's host this week ({p['why'] or 'kb_slot_role'})")
    return lines


def kb_exposures(workouts: Any, before: str | None, lib: dict[str, Any] | None = None) -> int | None:
    """KB-deadlift entry exposures logged, under the stand-in template and the owner's custom one when set."""
    from training import kb_entry

    custom = _settings(lib).get("kb_deadlift_template_id")
    ids = (kb_entry.ENTRY_TEMPLATE_ID,) + ((str(custom).upper(),) if custom else ())
    return kb_entry.exposures(workouts, before, template_ids=ids)


def kb_note_line(lib: dict[str, Any] | None = None) -> str:
    """The implement line: the stand-in names its Hevy title; a custom template needs no explanation."""
    from training import live_week

    if _settings(lib).get("kb_deadlift_template_id"):
        return "KB deadlift — one kettlebell."
    return str(live_week.KB_SLOT["implement_line"]["value"])


def template_resolver(resolve: Any, lib: dict[str, Any] | None = None) -> Any:
    """The compiler's movement -> Hevy template resolver, with the KB deadlift written under `kb_deadlift_template_id` when
    the library is APPROVED and the owner set one; otherwise `resolve` itself (today's Sumo Deadlift stand-in, unchanged)."""
    from training import kb_entry, selection_engine as se

    lib = lib if lib is not None else se.load_library_failsoft()
    tid = _settings(lib).get("kb_deadlift_template_id") if se.mode(lib) == se.MODE_LIVE else None
    if not tid:
        return resolve

    def _resolve(movement_key: str) -> str:
        return str(tid) if movement_key == kb_entry.ENTRY else resolve(movement_key)

    return _resolve


# ── 3. pain that persists ────────────────────────────────────────────────────
def pain_assess(rx: dict[str, Any], ctx: dict[str, Any], flags: list[dict[str, Any]], workouts: Any) -> list[str]:
    """IN PLACE: while a PAIN flag stands, the session's first joint-flagged lift (else its first lift) carries
    `pain_assess_line` (`live_assess`) and the rationale says how many sessions logged it. Off when the setting is ""."""
    from training.training_notes_pain import pain_class

    line = str(_settings(ctx["lib"]).get("pain_assess_line") or "").strip()
    pains = [f for f in flags if f.get("source") == "pain"]
    if not line or not pains or not rx.get("exposures"):
        return []
    tids = {str(_entry_by_id(f["movement_id"], ctx).get("template_id") or "").upper() for f in pains}
    days = {
        str(w.get("date") or "")[:10]
        for w in workouts or []
        for x in w.get("exercises") or []
        if str(x.get("template_id") or "").upper() in tids and x.get("notes") and pain_class(str(x["notes"]))
    }
    hit = next(
        (
            e
            for e in rx["exposures"]
            if (e.get("live_swap") or {}).get("code") == "joint" or "flag" in str((e.get("live_load") or {}).get("why"))
        ),
        None,
    )
    (hit or rx["exposures"][0])["live_assess"] = line
    names = ", ".join(sorted(str(f.get("title")) for f in pains))
    return [f"pain (live): {names} — logged on {len(days)} session(s); the note says: {line} (pain_assess_line)"]


def _entry_by_id(mid: str, ctx: dict[str, Any]) -> dict[str, Any]:
    return (ctx["lib"].get("movements") or {}).get(mid) or {}


def assess_note(note: str, line: str) -> str:
    """The persistence line as the lift's last own line (never displacing the effort or a reason). Idempotent."""
    if not line or line in note.split("\n"):
        return note
    return f"{note}\n{line}".strip() if note else line


# ── 4. volume by priority ────────────────────────────────────────────────────
def _template_rows(catalog: dict[str, Any], lib: dict[str, Any]) -> list[dict[str, Any]]:
    """Every template exposure of the week: role, slot, kind, movement, sets, its landmark muscle, its secondaries."""
    from training import live_week, program_structure as ps, selection_engine as se

    idx = se.key_index(lib, catalog)
    rows = []
    for role in ps.SPLIT_ROLES:
        for e in ps.session_prescription_for_role(role, catalog_movements=catalog)["exposures"]:
            key = e.get("movement_key")
            prim = live_week.landmark_muscle(key, catalog, lib)
            entry = ((lib.get("movements") or {}).get(idx["to_lib"].get(str(key))) or {}) if key else {}
            secs = [live_week.LANDMARK_OF.get(str(s), str(s)) for s in (entry.get("target") or {}).get("secondary") or []]
            rows.append(
                {
                    "role": role,
                    "slot": e.get("slot"),
                    "kind": e.get("kind"),
                    "intensity": e.get("intensity"),
                    "key": key,
                    "sets": len(e.get("sets") or []),
                    "muscle": prim,
                    "secondary": [m for m in secs if m != prim],
                }
            )
    return rows


def _sum(rows: list[dict[str, Any]], deltas: dict[tuple[str, str], int]) -> Counter:
    out: Counter = Counter()
    for r in rows:
        n = r["sets"] + deltas.get((r["role"], str(r["slot"])), 0)
        out[r["muscle"]] += n
        for m in r["secondary"]:
            out[m] += n * 0.5
    return out


def allocation_plan(catalog: dict[str, Any], lib: dict[str, Any]) -> dict[str, Any]:
    """The week's set allocation (module doc 4), from the five templates: {deltas: {(role, slot): +/-n}, before, after,
    lines}. Pure over the catalog and the library; the same for every session of the week."""
    from training import block_model, selection_live

    rows = _template_rows(catalog, lib)
    marks = block_model.load_landmarks() or {}
    priority = [str(m) for m in _settings(lib).get("priority_muscles") or []]
    pinned = {sid.split(".", 1)[1] for sid in selection_live.SLOT_OBJECTIVES}
    floor = int(ALLOCATION["over_mav_floor"]["value"])
    deltas: dict[tuple[str, str], int] = {}
    freed = 0
    while True:  # 1. every muscle over its MAV gives isolation sets, the largest slot first, latest in the week on a tie
        week = _sum(rows, deltas)
        over = [r for r in rows if r["kind"] == "accessory" and r["slot"] not in pinned and r["intensity"] != "carry"]
        over = [r for r in over if r["muscle"] in marks and week[r["muscle"]] > float(marks[r["muscle"]]["MAV"])]
        over = [r for r in over if r["sets"] + deltas.get((r["role"], str(r["slot"])), 0) > floor]
        if not over:
            break
        r = max(over, key=lambda r: (r["sets"] + deltas.get((r["role"], str(r["slot"])), 0), rows.index(r)))
        deltas[(r["role"], str(r["slot"]))] = deltas.get((r["role"], str(r["slot"])), 0) - 1
        freed += 1
    margin = int(ALLOCATION["priority_margin"]["value"])
    for m in priority:  # 2. the freed sets go to the priority muscles at or under MEV + margin, one per accessory slot
        lm = marks.get(m) or {}
        for r in [r for r in rows if r["kind"] == "accessory" and r["muscle"] == m and r["slot"] not in pinned]:
            if freed <= 0 or not lm or _sum(rows, deltas)[m] > float(lm["MEV"]) + margin:
                break
            k = (r["role"], str(r["slot"]))
            if deltas.get(k, 0) < int(ALLOCATION["add_per_slot"]["value"]):
                deltas[k] = deltas.get(k, 0) + 1
                freed -= 1
    before, after = _sum(rows, {}), _sum(rows, deltas)
    lines = [
        f"{role}.{slot} {'+' if d > 0 else ''}{d} set(s)"
        for (role, slot), d in sorted(
            deltas.items(), key=lambda kv: (list(dict.fromkeys(r["role"] for r in rows)).index(kv[0][0]), kv[0][1])
        )
        if d
    ]
    return {"deltas": {k: v for k, v in deltas.items() if v}, "before": before, "after": after, "lines": lines}


def allocate(rx: dict[str, Any], ctx: dict[str, Any]) -> list[str]:
    """IN PLACE: this session's share of the week's allocation (`allocation_plan`): a slot's working sets go down (the last
    working set) or up (a copy of it). Returns the lines (the week's reason on each)."""
    from training import block_model

    plan_ = ctx.get("allocation") or allocation_plan(ctx["catalog"], ctx["lib"])
    ctx["allocation"] = plan_
    role = str(rx.get("session_role") or "")
    marks = block_model.load_landmarks() or {}
    lines = []
    for e in rx["exposures"]:
        d = plan_["deltas"].get((role, str(e.get("slot"))), 0)
        sets = e.get("sets") or []
        if not d or not sets:
            continue
        was = len(sets)
        for _ in range(abs(d)):
            if d > 0:
                sets.append(dict(sets[-1]))
            elif len(sets) > int(ALLOCATION["over_mav_floor"]["value"]):
                sets.pop()
        m = _muscle(e, ctx)
        lm = marks.get(m) or {}
        why = (
            f"{m} {plan_['before'][m]:g} > MAV {lm.get('MAV')} for the week"
            if d < 0
            else f"{m} at {plan_['before'][m]:g} (MEV {lm.get('MEV')}): a priority muscle takes the freed sets first"
        )
        title = (ctx["catalog"].get(e.get("movement_key")) or {}).get("title") or e.get("movement_key")
        lines.append(f"allocation (live): {title} {was} -> {len(sets)} sets — {why} (ALLOCATION, heuristic)")
    return lines


def _muscle(e: dict[str, Any], ctx: dict[str, Any]) -> str:
    from training import live_week

    return live_week.landmark_muscle(e.get("movement_key"), ctx["catalog"], ctx["lib"])


def allocated_week(catalog: dict[str, Any], lib: dict[str, Any]) -> Counter:
    """The program week's sets per landmark muscle AFTER the allocation (`live_week.week_sets` reads it)."""
    return Counter(allocation_plan(catalog, lib)["after"])


# ── 5. the adherence dip ─────────────────────────────────────────────────────
def adherence_response(workouts: Any, as_of: str, lib: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """{missed, planned, performed, mode} after a dip: `behind` (the keep-the-anchors week, `behind_schedule_week`) or `dip`
    (the default `adherence_response` `short_week`); None when adherence is fine, unread, or the response is `trim_sets`."""
    from training import live_week

    s = _settings(lib)
    monday = week_start(as_of)  # judged ONCE a week, as of its Monday: every morning of the week gets the same answer
    if s.get("behind_schedule_week"):
        got = live_week.behind_schedule(workouts, monday, lib)
        return {**got, "mode": "behind"} if got else None
    if s.get("adherence_response") != "short_week":
        return None
    got = live_week.behind_schedule(workouts, monday, lib, force=True)
    return {**got, "mode": "dip"} if got else None


def week_start(day: str) -> str:
    """The Monday of `day`'s calendar week (a dip read on Thursday would count Monday-Wednesday's own sessions and flip the
    answer mid-week); `day` itself when it does not parse."""
    from common.pacific_time import parse_day_key, shift_day_key

    d = parse_day_key(str(day)[:10])
    return shift_day_key(d.isoformat(), -d.weekday()) if d else day


def lighter_week(rx: dict[str, Any], ctx: dict[str, Any], dip: dict[str, Any] | None) -> list[str]:
    """IN PLACE, the default dip response: every anchor whole, every accessory (bar a pinned slot) at ADHERENCE_DIP
    accessory_sets, the routine fitted to its session_minutes (`live_session.fit_routine`); the trunk floor waits."""
    if not dip or dip.get("mode") != "dip":
        return []
    from training import selection_live

    role = str(rx.get("session_role") or "")
    pinned = {sid.split(".", 1)[1] for sid in selection_live.SLOT_OBJECTIVES if sid.startswith(f"{role}.")}
    n = int(ADHERENCE_DIP["accessory_sets"]["value"])
    off = 0
    for e in rx["exposures"]:
        if e.get("kind") == "accessory" and e.get("slot") not in pinned and e.get("intensity") != "carry":
            while len(e.get("sets") or []) > n:
                e["sets"].pop()
                off += 1
    ctx["behind"] = dip  # the trunk floor waits (live_program.trunk_floor)
    minutes = int(ADHERENCE_DIP["session_minutes"]["value"])
    rx.setdefault("live_session_cap", minutes)
    return [
        f"adherence dip (live): {dip['performed']} of {dip['planned']} planned sessions done in 14 days — a shorter week he can "
        f"keep: anchors whole, accessories at {n} sets ({off} off), ~{minutes} min (adherence_response=short_week, ADHERENCE_DIP, "
        "heuristic)"
    ]


# ── 6. the library fallback ──────────────────────────────────────────────────
def library_fallbacks(e: dict[str, Any], ctx: dict[str, Any]) -> list[str]:
    """An accessory's last resort after its slot's ranked fallbacks: the library's members of the same movement pattern
    whose landmark muscle is the slot's, best hypertrophy tier for that muscle first, then familiar first. Catalog-writable
    only (the generator can write it). Equipment, pain, gates and the joint limits are judged by the caller."""
    from training import live_week, selection_live

    if e.get("kind") != "accessory":
        return []
    cur = _entry(e.get("movement_key"), ctx) or _entry(e.get("slot"), ctx)
    pattern, muscle = cur.get("pattern"), _muscle(e, ctx)
    if not pattern or pattern in ("carry", "cardio", "other"):
        return []
    to_cat = {lid: k for k, lid in ctx["idx"]["to_lib"].items()}
    rank = {t: i for i, t in enumerate("SABCD")}
    out = []
    for lid, entry in sorted((ctx["lib"].get("movements") or {}).items()):
        key = to_cat.get(lid)
        if not key or entry.get("pattern") != pattern:
            continue
        if live_week.landmark_muscle(key, ctx["catalog"], ctx["lib"]) != muscle:
            continue
        tier = selection_live.objective_tier(entry, "hypertrophy", muscle)
        if tier is None:
            continue
        out.append((rank.get(str(tier), 9), -int((ctx["catalog"].get(key) or {}).get("sessions") or 0), key))
    return [k for *_r, k in sorted(out)]


# ── 7. one effort target per lift ────────────────────────────────────────────
_RULE_LINE = re.compile(r"^(?:Set 1|Top reps|One set|Other lifts|Dumbbells|Low energy)")


def effort_targets(note: str | None) -> list[str]:
    """The distinct effort TARGETS a lift's note states: the session line's band (exercise 1's day line) and each own line
    that is an effort line (`RPE a–b`, its last-set clause aside). A load rule's threshold ("Set 1: … at RPE 7 or less") is
    not a target. More than one = the note contradicts itself."""
    from training import hevy_note_grammar as g, session_block as sb

    block, own = sb.split(note)
    out = []
    eff = sb.session_effort(block) if block else None
    if eff:
        out.append(eff[len("RPE ") :])
    for line in own.split("\n"):
        m = g.EFFORT_RE.match(line.strip())
        if m and not _RULE_LINE.match(line.strip()):
            out.append(m.group("rpe"))
    for line in own.split("\n"):  # a carry's line 1: `RPE a–b · pick the load per hand`
        m = g.CARRY_LINE1_RE.match(line.strip())
        if m:
            out.append(m.group("rpe"))
    return list(dict.fromkeys(out))


def _day_line(head: str, own_effort: str) -> str:
    """The session line restated at exercise 1's own effort: `‹Day› · RPE ‹its band› on big lifts` (the note standard's
    grammar, `hevy_note_grammar.SESSION_LINE_RE`, kept) — the day's actual cap where exercise 1 is capped."""
    from training import hevy_note_grammar as g, session_block as sb

    m, e = sb.SESSION_LINE_RE.match(head), g.EFFORT_RE.match(own_effort.strip())
    if not m or not e:
        return head
    return f"{m.group('day')} · RPE {e.group('rpe')} on big lifts"


def one_effort(note: str | None) -> str:
    """Exercise 1's note with its session line restated at the lift's own effort when that effort says something else (a
    joint flag, the deload shape, a stall reset, the KB cap) — and the own line then printed once: one effort target per
    lift (third red team: "RPE 8–9 on big lifts" then "RPE 6–7" on the same lift). Any other note: unchanged."""
    from training import hevy_note_grammar as g, session_block as sb

    text = note or ""
    block, own = sb.split(text)
    eff = sb.session_effort(block) if block else None
    lines = [ln for ln in own.split("\n") if ln.strip()]
    if not eff or not lines or not g.EFFORT_RE.match(lines[0].strip()) or lines[0].strip() == eff:
        return text
    head, sep, rest = block.partition("\n")
    return sb._join(_day_line(head, lines[0]) + sep + rest, lines)


def why_effort(why: str, ir: Any) -> str:
    """The compiler's WHY block (`session_block.why_note_for`) with its session line restated at exercise 1's own effort when
    that says something else — LIVE drafts only (the prescription carries `live_session.MARK`); else `why`, unchanged. The
    compiler then prints exercise 1's effort once (`hevy_compiler._place_routine_note` dedupes the equal line)."""
    from training import hevy_note_grammar as g, live_session as ls, session_block as sb

    rx = (getattr(ir, "inputs_snapshot", None) or {}).get("session_prescription") or {}
    exercises = getattr(ir, "exercises", None) or []
    if ls.MARK not in rx or not exercises or not why:
        return why
    first = next((ln for ln in str(getattr(exercises[0], "notes", "") or "").split("\n") if ln.strip()), "")
    eff = sb.session_effort(why)
    if not eff or not g.EFFORT_RE.match(first.strip()) or first.strip() == eff:
        return why
    head, sep, rest = why.partition("\n")
    return _day_line(head, first) + sep + rest


# ── 8. cardio: the host, the machine, its name ───────────────────────────────
def conditioning_host(skipped: Any) -> str:
    """The session the shared cap puts hard conditioning on: shoulders+arms; in a week that skips it (the short week, the dip
    week), the session the menu places conditioning on instead — the one after the heavy lower day (owner ruling 2026-10-25
    on #5076). The third red team's short week had no conditioning at all under the shared cap."""
    from training import program_structure as ps

    if not skipped:
        return HOST_ROLE
    roles = [r for r in ps.SPLIT_ROLES if r != HOST_ROLE]
    return roles[(roles.index("lower_heavy") + 1) % len(roles)] if "lower_heavy" in roles else roles[-1]


def easy_gap(kind: str, live: dict[str, Any]) -> tuple[bool, list[str]]:
    """(keep, lines) for an EASY block when the week's steps do not cover the aerobic floor: the block stays only while the
    gap — the guideline floor less the walking credit less every block performed this week (since its Monday) — is at least
    CARDIO_ROOM's minimum block. Steps first, then only the structured minutes that close the gap (third red team: the
    conservative credit must not turn into an easy block every morning). A hard kind, or unread steps: (True, [])."""
    from training import cardio_model, live_program, live_week

    aer = live.get("aerobic") or {}
    if kind in live_program.HARD_KINDS or not aer or aer.get("volume_covered"):
        return True, []
    since, day = week_start(str(live.get("target_date") or "")), str(live.get("target_date") or "")
    done = sum(
        int(r.get("duration_sec") or 0) // 60
        for rows in (live.get("by_machine") or {}).values()
        for r in rows or []
        if since <= str(r.get("date") or "")[:10] < day
    )
    walk = int(aer.get("walking_min_per_wk") or 0)
    gap = int(cardio_model.WEEKLY_MODERATE_MIN[0]) - walk - done
    floor = int(live_week.CARDIO_ROOM["min_block"]["value"])
    if gap < floor:
        return False, [
            f"cardio (live): no easy block — steps (~{walk} moderate min/wk, conservatively credited) and {done} min of blocks this "
            f"week leave {max(gap, 0)} min of the weekly {cardio_model.WEEKLY_MODERATE_MIN[0]}: under a {floor}-min block (steps first)"
        ]
    return True, [
        f"cardio (live): easy block kept — the week is ~{gap} min short of {cardio_model.WEEKLY_MODERATE_MIN[0]} after ~{walk} min of steps and {done} min of blocks"
    ]


def min_block(kind: str, hard_min: int) -> int:
    """The shortest block worth serving under the shared cap: CARDIO_ROOM's minimum for an easy block (a stub is worthless),
    `hard_min` for a conditioning block (its intervals or tempo still fit)."""
    from training import live_program, live_week

    return hard_min if kind in live_program.HARD_KINDS else int(live_week.CARDIO_ROOM["min_block"]["value"])


def _unavailable(key: str, lib: dict[str, Any] | None) -> bool:
    from training import selection_engine as se

    entry = ((lib or {}).get("movements") or {}).get(key)
    return bool(entry) and bool(se.availability(entry, lib or {}, None))


def cardio_machine(menu: dict[str, Any], lib: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    """The menu's machine when the gym has it; else the first machine the menu runs this kind on that it has (treadmill,
    rower, bike, elliptical — `cardio_menu.fits_machine`); else unchanged (named). Live only (`live_program.cardio_fit`)."""
    from training import cardio_menu, cardio_note

    key = str(menu.get("machine") or "")
    if not key or not _unavailable(key, lib):
        return menu, []
    for alt in cardio_note.MACHINES:
        if alt != key and cardio_menu.fits_machine(str(menu["kind"]), alt) and not _unavailable(alt, lib):
            return {**menu, "machine": alt}, [f"cardio (live): {key} -> {alt} — the gym has no {key} (equipment, live)"]
    return menu, [f"cardio (live): {key} kept — no other machine the gym has runs {menu['kind']}"]


def recumbent_missing(lib: dict[str, Any] | None) -> bool:
    """The gym inventory marks a recumbent bike unavailable (an upright stationary bike may still be there)."""
    items = ((lib or {}).get("gym_inventory") or {}).get("items") or {}
    return str(((items.get("recumbent_bike") or {}).get("home_gym") or {}).get("state")) == "unavailable"


def machine_label(notes: str, lib: dict[str, Any] | None) -> str:
    """A `cycling` note names "Recumbent" (the owner's knee-sparing bike); where the gym has no recumbent it names "Bike"."""
    if not recumbent_missing(lib):
        return notes
    return "\n".join(("Bike" + ln[len("Recumbent") :]) if ln.startswith("Recumbent") else ln for ln in notes.split("\n"))


# ── 9. the rate band, by setting ─────────────────────────────────────────────
def rate_band(fatigue: dict[str, Any] | None, sleep_hours: Any, lib: dict[str, Any] | None = None) -> dict[str, Any]:
    """`health.rate_policy.propose_band` with the owner's `body_fat_tier` (None = unknown, today) and `rate_band_mode`."""
    from health import rate_policy

    s = _settings(lib)
    short = sleep_hours is not None and float(sleep_hours) < 6.5
    band = rate_policy.propose_band(
        body_fat_tier=s.get("body_fat_tier") or None, fatigue_level=(fatigue or {}).get("fatigue_level"), recovery_low=short or None
    )
    return {**band, "mode": str(s.get("rate_band_mode") or "advisory"), "body_fat_tier": s.get("body_fat_tier") or "unknown"}
