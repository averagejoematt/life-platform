"""week_commitments.py — the charter concession ledger's WEEKLY commitments as hard stage-1 checks (#5774, epic #5770).

WHY THIS EXISTS

The charter's `concession_ledger` is what each school of the panel gets in return for what it concedes to the deadline.
Several of those returns are weekly promises about what the program SERVES — dan_john "carries and kettlebell work weekly",
athlean_x "corrective work, carries, single-leg work", nippard "stretch-position work, rotation", rp_israetel's shoulder
volume (the charter's `volume_priorities.sets_per_wk.side_rear_delts` band). Until #5774 nothing at stage 1 read the ledger
at week level: no kettlebell movement appeared in four weeks of Hevy history while the ledger promised one weekly. This
module is that check: one function (`evaluate`) over the program WEEK's served movements, one verdict per commitment, and
a stage-1 verdict that FAILS when any blocking commitment is missed. A failed draft is refused at commit (`commit_refusal`,
called from `manage_hevy_routine commit`), and the stage-1 constraint block carries the verdict (`attach`).

THE WEEK IS WHAT IS SERVED (owner ruling 2026-11-11, item 2). Each of the program week's five sessions is served by:
the draft in hand when it is that session's; else the routine he COMMITTED for that session this program week (a
`draft_custom` departure, the tired-day floor, or an engine draft — read from its IR exercises); else the engine's plan
(the rotation record's `variants_by_role` over `program_structure.session_prescription_for_role`). So a departure counts
toward AND against a commitment: a custom day that carries a carry satisfies it, a custom day that displaces the week's
only single-leg movement fails it. The program week is the session sequence's (`calendar.block`/`calendar.week`); a floor
draft, which carries no calendar, joins the week of the routines dated the same day.

BLOCK OR WARN (owner, 2026-11-11)

  * The current pools CAN fill it -> it BLOCKS now: carries, kettlebell's entry slot aside, single-leg, corrective,
    rotation, the side/rear-delt band.
  * Kettlebell — `week_floors.kettlebell_enforced`: WARN until the earlier of library approval or 2026-12-20, then BLOCK,
    dated on the draft's own day. The pools now serve one (`lower_volume.kettlebell_swing`, entered via two KB-deadlift
    exposures, `kb_entry`), so an engine week meets it; a week whose departures drop that day misses it.
  * Stretch-position — measured only from the exercise library's `length_bias`; report-only (no retirement named).
  * A floor whose every member a RECORDED gate excludes (equipment off the charter's list, block 1's first phase serving
    the committed template) WARNS with the gate named: the pool cannot fill it.
  * No week to read (no rotation record and no calendar to plan one from) is `not_evaluated` — named, never a pass.

WHAT EACH CHECK MERGES (the complexity budget — no second classifier for anything): carries and single-leg ARE
`week_floors.family_floors` (#5786); kettlebell IS `week_floors.kettlebell_weekly` and its `kettlebell_enforced` switch;
the side/rear-delt band IS `volume_floors.charter_band_rows`' row over `movement_counts` (#5311's `session.volume_bands`);
rotation IS the panel's `accessory_rotation_drafted` computation (`rotation_problem`, moved here from `panel_rubric`, which
imports it); corrective IS the panel's corrective classifier (`CORRECTIVE`, moved here likewise).

`evaluate` is pure. `attach` and `commit_refusal` read the week's routines (`routine_repo.list_by_date_range`, injectable)
and, at commit, the catalog and the library. No clock: the day is always the caller's.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from training import week_floors

ISSUE = "#5774"
ERROR_CODE = "WEEK_COMMITMENT"
BLOCK, WARN, MET, NOT_EVALUATED = "block", "warn", "met", "not_evaluated"

# The panel's corrective classifier (athlean_x's `corrective_work` criterion), moved here so the gate and the grade share it.
CORRECTIVE = re.compile(r"face pull|pallof|rear delt|reverse fly|external rotation|band pull|dead bug|bird dog|scap", re.I)
LENGTHENED = "lengthened"  # the exercise library's `length_bias` value for a movement loaded in the stretched position
BAND = "side_rear_delts"  # charter volume_priorities.sets_per_wk key
WEEK_WINDOW_DAYS = (10, 10)  # the routine read around the day: a program week spans at most ~9 Pacific days
TEMPLATE_PHASE = "block 1's first phase serves the template as written (#5075 step 0: the committed session)"

COMMITMENTS: list[dict[str, Any]] = [
    {
        "id": "carries",
        "seats": {"dan_john": "carries", "athlean_x": "carries"},
        "enforce": "now",
        "merges": "training/week_floors.py::family_floors (#5786, the carries floor — report-only until now)",
    },
    {
        "id": "kettlebell",
        "seats": {"dan_john": "kettlebell work weekly"},
        "enforce": "kettlebell ruling: the earlier of exercise-library approval or " + week_floors.KETTLEBELL_BLOCK_FROM,
        "merges": "training/week_floors.py::kettlebell_weekly + kettlebell_enforced (#5786's stamped verdict, now consumed)",
    },
    {
        "id": "single_leg",
        "seats": {"athlean_x": "single-leg work"},
        "enforce": "now",
        "merges": "training/week_floors.py::family_floors (#5786, the single_leg_progression floor — report-only until now)",
    },
    {
        "id": "corrective",
        "seats": {"athlean_x": "corrective work"},
        "enforce": "now",
        "merges": "training/panel_rubric.py::_CORRECTIVE (the corrective_work criterion's classifier, now CORRECTIVE here)",
    },
    {
        "id": "stretch_position",
        "seats": {"nippard": "stretch-position work"},
        "enforce": None,
        "merges": None,
        "report_only": "no existing check named to retire (complexity budget); measured from the exercise library's length_bias",
    },
    {
        "id": "rotation",
        "seats": {"nippard": "rotation"},
        "enforce": "now",
        "merges": "training/panel_rubric.py::rotation_problem (the accessory_rotation_drafted criterion, now here)",
    },
    {
        "id": "free_weight_compounds",
        "seats": {"dan_john": "a free-weight press, pull, squat and hinge weekly"},
        "enforce": "exercise-library approval (WARN while it is proposed: today's #5075 pools serve no free-weight pull)",
        "merges": "training/week_floors.py::free_weight_compounds (#5857, owner ruling 2026-11-12, board rec 4; anchors count)",
    },
    {
        "id": "side_rear_delt_band",
        "seats": {"rp_israetel": "rising volume on shoulders"},
        "band": "volume_priorities.sets_per_wk." + BAND,
        "enforce": "now",
        "merges": "training/volume_floors.py::charter_band_rows side_rear_delts row (#5311's session.volume_bands report)",
    },
]
"""One row per weekly commitment. `seats`: ledger seat -> the phrase of its `in_return` this row checks (a test holds every
phrase inside the charter's own ledger line, so nothing here is invented). `enforce`: when a miss blocks (None = never)."""


def ledger_line(seats: dict[str, str]) -> str:
    """The ledger lines a row answers to, READ from the charter (never copied): `dan_john: 'carries and kettlebell …'`."""
    from training.training_charter import charter_value

    ledger = charter_value("concession_ledger", {}) or {}
    return "; ".join(f"{s}: {str((ledger.get(s) or {}).get('in_return') or '?')!r}" for s in seats)


def rotation_problem(rot: Any) -> str | None:
    """#5759: why one draft's rotation record (`variant_rotation.plan`) is NOT on the charter cadence, or None when it is:
    the program week known, the rotation not refused, and past block 1's first phase every slot with another pool member
    serving a variant that differs from the phase before — except a hold owner ruling B accepts (#5856, 2026-11-12, amended:
    the held pick is the single servable member of the slot's S∪A pool; `rotation_holds` records it). Absence is not credit."""
    if not isinstance(rot, dict):
        return "no rotation record on the draft"
    pos = rot.get("position")
    if not pos:
        return "the program week was unknown, so the template served"
    if (rot.get("volume_check") or {}).get("unchanged") is False:
        return "the rotation was refused (the week's counts would move)"
    if int(pos.get("step") or 0) <= 0:
        return None  # block 1's first phase serves the template as written
    held = [str(s.get("slot_id")) for s in _held(rot) if not _sole_best(s) and not _live_hold(s)]
    return f"held at a phase boundary: {', '.join(held)}" if held else None


def _live_hold(slot: dict[str, Any]) -> bool:
    """#5861 L3 (owner 2026-11-12: accessory rotation is "for a reason", not a fixed cadence): a hold the LIVE selection
    recorded (`selection_engine._live` copies `rotation_decision` onto the slot — only an approved library writes it) is
    accepted with its reason; the shadow cadence check is unchanged because a shadow slot never carries the key."""
    return (slot.get("rotation_decision") or {}).get("action") == "hold"


def _held(rot: dict[str, Any]) -> list[dict[str, Any]]:
    """Past block 1's first phase: the unpinned slots with another pool member that serve the phase before's variant."""
    if int(((rot.get("position") or {}).get("step")) or 0) <= 0:
        return []
    return [
        s
        for s in rot.get("slots") or []
        if s.get("source") != "pinned" and len(s.get("pool") or []) >= 2 and s.get("variant") == s.get("previous")
    ]


def _sole_best(slot: dict[str, Any]) -> bool:
    """Owner ruling B on #5856 (2026-11-12), amended the same day (board rec 3): a held pick is accepted only when it is the
    SINGLE servable member of the slot's S∪A pool (`selection_engine.top_band.sa_members`). Two or more still rotate. When
    S∪A holds NO servable member this week (every one excluded or already served by another slot), the slot's own pool
    stands in for it: a single servable pool member is accepted, recorded the same way."""
    band = slot.get("top_band") or {}
    members = list(band.get("sa_members") or []) or list(band.get("members") or [])
    return members == [slot.get("variant")]


def rotation_holds(rot: Any) -> list[str]:
    """The holds ruling B accepted, recorded: `slot_id (tier X, the band's only member)`."""
    if not isinstance(rot, dict):
        return []
    return [
        f"{s.get('slot_id')} (tier {(s.get('top_band') or {}).get('tier')}, the only servable S/A member)"
        for s in _held(rot)
        if _sole_best(s)
    ]


# ── the week's served movements ─────────────────────────────────────────────────────────────────────────────────────
def _key_index(catalog: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, m in catalog.items():
        hint = str((m or {}).get("hevy_template_id_hint") or "").upper()
        if hint:
            out.setdefault(hint, k)
    return out


def routine_day(ir: Any, catalog: dict[str, Any]) -> list[tuple[str, int]]:
    """(catalog key, working sets) per exercise of one routine IR — a `tmpl:<id>` key (draft_custom's resolved template)
    maps back to the catalog key carrying that template id, so a custom day's farmer's walk counts as one."""
    from training.warmup_sets import working_set_count

    index = _key_index(catalog)
    out = []
    for b in getattr(ir, "exercises", None) or []:
        key = str(getattr(b, "movement_key", "") or "")
        if key.startswith("tmpl:"):
            key = index.get(key[5:].upper(), key)
        out.append((key, int(working_set_count(getattr(b, "sets", None)))))
    return out


def served_week(
    rotation: dict[str, Any] | None, catalog: dict[str, Any], days: dict[str, dict[str, Any]] | None = None, skill_ceiling: int = 2
) -> list[dict[str, Any]]:
    """Every movement the program week serves, `{key, sets, role, slot_id}`: a role in `days` by its routine's exercises,
    every other role by the engine's plan (the rotation's `variants_by_role`; none when there is no rotation record)."""
    from training import program_structure

    days = days or {}
    by_role = (rotation or {}).get("variants_by_role") or {}
    out: list[dict[str, Any]] = []
    for role in list(program_structure.SPLIT_ROLES) + [r for r in days if r not in program_structure.SPLIT_ROLES]:
        if role in days:
            src = days[role].get("source") or "routine"
            out += [{"key": k, "sets": n, "role": role, "slot_id": f"{role} [{src}]"} for k, n in days[role].get("keys") or []]
        elif isinstance(rotation, dict):
            rx = program_structure.session_prescription_for_role(
                role, catalog_movements=catalog, skill_ceiling=skill_ceiling, accessory_variants=by_role.get(role)
            )
            out += [
                {
                    "key": str(e["movement_key"]),
                    "sets": len(e["sets"]),
                    "role": role,
                    "slot_id": f"{role}.{e.get('slot') or e.get('pattern')}",
                }
                for e in rx["exposures"]
                if e.get("movement_key")
            ]
    return out


# ── the rows ──────────────────────────────────────────────────────────────────────────────────────────────────────
def _row(c: dict[str, Any], verdict: str, detail: str) -> dict[str, Any]:
    return {
        "id": c["id"],
        "seats": sorted(c["seats"]),
        "ledger": ledger_line(c["seats"]),
        "verdict": verdict,
        "blocking": verdict == BLOCK,
        "detail": detail,
    }


def _refusals(rotation: dict[str, Any] | None) -> list[dict[str, str]]:
    """The recorded gates: each slot's refused candidates, and block 1's first phase (the committed template, #5759)."""
    rot = rotation or {}
    out = [dict(e) for s in rot.get("slots") or [] for e in s.get("excluded") or []]
    for fl in rot.get("family_floors") or []:  # the stamp's own whole-week gates (a pinned movement off the equipment list)
        if not fl.get("met") and fl.get("gate") and not str(fl["gate"]).startswith("nothing in the week hosts"):
            out += [{"key": k, "reason": str(fl["gate"])} for k in week_floors.family_members(str(fl.get("family")))]
    if int((rot.get("position") or {}).get("step", -1) or 0) == 0 and rot.get("position"):
        out += [{"key": k, "reason": TEMPLATE_PHASE} for f in week_floors.WEEKLY_FAMILY_FLOORS for k in week_floors.family_members(f)]
    return out


def _floor(c: dict[str, Any], floors: list[dict[str, Any]], family: str) -> dict[str, Any]:
    fl = next(f for f in floors if f["family"] == family)
    if fl["met"]:
        return _row(c, MET, ", ".join(f"{s['title']} [{s['slot_id']}]" for s in fl["served"]))
    gate = str(fl.get("gate") or "")
    hosted = not gate or gate.startswith("nothing in the week hosts")
    return _row(
        c, BLOCK if hosted else WARN, f"no {family} member this week" + ("" if hosted else f" — a recorded gate excludes it: {gate}")
    )


def _kettlebell(
    c: dict[str, Any], served: list[dict[str, Any]], catalog: dict[str, Any], on: str | None, status: str | None
) -> dict[str, Any]:
    kb = week_floors.kettlebell_weekly(served, catalog, on=on, status=status)
    if kb["met"]:
        return _row(c, MET, ", ".join(f"{s['title']} [{s['slot_id']}]" for s in kb["served"]))
    why = week_floors.kettlebell_enforced(on, status)
    return _row(
        c,
        BLOCK if why else WARN,
        "no kettlebell movement this week — "
        + (f"stage 1 FAILS: {why}" if why else f"a warning until {week_floors.KETTLEBELL_BLOCK_FROM} or library approval"),
    )


def _title(key: str, catalog: dict[str, Any]) -> str:
    return str((catalog.get(key) or {}).get("title") or key.replace("_", " "))


def _corrective(c: dict[str, Any], served: list[dict[str, Any]], catalog: dict[str, Any]) -> dict[str, Any]:
    hits = sorted({_title(s["key"], catalog) for s in served if CORRECTIVE.search(_title(s["key"], catalog))})
    return _row(c, MET if hits else BLOCK, ", ".join(hits) if hits else "no corrective movement (face pull, rear delt, Pallof …)")


def _stretch(c: dict[str, Any], served: list[dict[str, Any]], lib: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance((lib or {}).get("movements"), dict):
        return _row(c, NOT_EVALUATED, f"no exercise library on this bundle to read length_bias from — report-only ({c['report_only']})")
    movements = lib["movements"]  # type: ignore[index]
    hits = sorted(
        {
            str((movements.get(s["key"]) or {}).get("title") or s["key"])
            for s in served
            if (movements.get(s["key"]) or {}).get("length_bias") == LENGTHENED
        }
    )
    return _row(
        c, MET if hits else WARN, ", ".join(hits) if hits else f"no lengthened-position movement — report-only ({c['report_only']})"
    )


def _band(c: dict[str, Any], served: list[dict[str, Any]], catalog: dict[str, Any]) -> dict[str, Any]:
    from training import volume_floors

    by_muscle: dict[str, int] = {}
    by_movement: dict[str, int] = {}
    for s in served:
        muscle = (catalog.get(s["key"]) or {}).get("primary_muscle") or "unresolved"
        by_muscle[muscle] = by_muscle.get(muscle, 0) + int(s["sets"])
        by_movement[s["key"]] = by_movement.get(s["key"], 0) + int(s["sets"])
    row = volume_floors.charter_band_rows(volume_floors.movement_counts(by_muscle, by_movement)).get(BAND)
    if not row:
        return _row(c, NOT_EVALUATED, f"no charter band {c['band']}")
    lo, hi = row["band"]
    inside = all(lo <= n <= hi for n in row["member_sets"])
    return _row(c, MET if inside else BLOCK, f"{row['member_sets']} sets a week against the charter band [{lo}, {hi}]")


def _free_weight(c: dict[str, Any], served: list[dict[str, Any]], lib: Any, catalog: dict[str, Any], status: str | None) -> dict[str, Any]:
    """Owner ruling 2026-11-12 (board rec 4): a free-weight compound press, pull, squat and hinge every program week, anchors
    counting. It BLOCKS once the exercise library is approved (the selection then fills the slots) and WARNS before."""
    if not isinstance((lib or {}).get("movements"), dict):
        return _row(c, NOT_EVALUATED, "no exercise library on this bundle to read job / pattern from")
    groups = week_floors.free_weight_compounds(served, lib, catalog)
    if status == week_floors.LIBRARY_APPROVED:  # #5861 L3: live only — the floor is a strength/competence floor
        groups = _with_bodyweight_pull(groups, served, lib, catalog)
    missing = [g for g, hits in groups.items() if not hits]
    if missing:
        armed = status == week_floors.LIBRARY_APPROVED
        tail = "" if armed else " — a warning until the exercise library is approved"
        return _row(c, BLOCK if armed else WARN, f"no free-weight compound {' / '.join(missing)} this week{tail}")
    return _row(c, MET, "; ".join(f"{g}: {', '.join(hits)}" for g, hits in groups.items()))


def _with_bodyweight_pull(groups: dict[str, list[str]], served: list[dict[str, Any]], lib: Any, catalog: dict[str, Any]) -> dict:
    """#5861 L3 (live only): a pull-up or chin-up (a bodyweight vertical-pull compound for the back, loadable with a belt)
    is a strength and competence pull — the free-weight floor's "pull" counts it. Before this, the library's
    `bodyweight` profile kept every pull-up out of the floor (engine audit 2026-11-12, §2e)."""
    out = {g: list(v) for g, v in groups.items()}
    for s in served:
        e = week_floors._library_entry(str(s.get("key") or ""), lib or {}, catalog)
        if not e or e.get("job") != "compound" or e.get("resistance_profile") != "bodyweight":
            continue
        if e.get("pattern") == "vertical_pull" and (e.get("target") or {}).get("primary") in week_floors.FREE_WEIGHT_TARGETS["pull"]:
            if str(e.get("title")) not in out["pull"]:
                out["pull"].append(str(e.get("title")))
    return out


def _rotation(c: dict[str, Any], rot: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(rot, dict):
        return _row(c, NOT_EVALUATED, "no rotation record for the week")
    why = rotation_problem(rot)
    holds = rotation_holds(rot)
    met = "on the charter cadence" + (f"; held by owner ruling B (#5856, 2026-11-12): {', '.join(holds)}" if holds else "")
    live = [
        f"{s.get('slot_id')} ({(s.get('rotation_decision') or {}).get('reason')})"
        for s in _held(rot)
        if _live_hold(s) and not _sole_best(s)
    ]
    met += f"; held for a reason (#5861, live): {', '.join(live)}" if live else ""
    return _row(c, BLOCK if why else MET, why or met)


def evaluate(
    rotation: Any,
    catalog: dict[str, Any] | None,
    *,
    on: str | None,
    library: Any = ...,
    days: dict[str, dict[str, Any]] | None = None,
    source: str = "the draft's rotation record",
) -> dict[str, Any]:
    """Every `COMMITMENTS` row over the program week (`served_week`: the routines in `days`, the plan for every other
    session) on day `on`, and the stage-1 verdict: `fail` when any row blocks, `pass` when none does, `not_evaluated`
    when there is no week to read. `library`: the exercise library (read from config when not given) — its `status` arms
    the kettlebell switch, its `length_bias` measures stretch."""
    rotation = rotation if isinstance(rotation, dict) else None
    by_id = {c["id"]: c for c in COMMITMENTS}
    if rotation is None or not catalog:
        why = "no movement catalog" if not catalog else "no rotation record to plan the week from (no calendar on the draft)"
        rows = [_row(c, NOT_EVALUATED, why) for c in COMMITMENTS]
        verdict = NOT_EVALUATED
    else:
        lib = week_floors.library() if library is ... else library
        status = week_floors.library_status(data=lib)
        served = served_week(rotation, catalog, days)
        floors = week_floors.family_floors(served, _refusals(rotation), catalog)
        rows = [
            _floor(by_id["carries"], floors, "carries"),
            _kettlebell(by_id["kettlebell"], served, catalog, on, status),
            _floor(by_id["single_leg"], floors, "single_leg_progression"),
            _corrective(by_id["corrective"], served, catalog),
            _stretch(by_id["stretch_position"], served, lib),
            _rotation(by_id["rotation"], rotation),
            _free_weight(by_id["free_weight_compounds"], served, lib, catalog, status),
            _band(by_id["side_rear_delt_band"], served, catalog),
        ]
        verdict = "fail" if any(r["blocking"] for r in rows) else "pass"
    return {
        "issue": ISSUE,
        "stage": 1,
        "on": on,
        "evaluated_from": source,
        "week_days": {r: d.get("source") for r, d in (days or {}).items()},
        "verdict": verdict,
        "blocking": [r["id"] for r in rows if r["blocking"]],
        "warnings": [r["id"] for r in rows if r["verdict"] in (WARN, NOT_EVALUATED)],
        "rows": rows,
        "lines": lines(rows),
    }


def lines(rows: list[dict[str, Any]]) -> list[str]:
    """One sentence per commitment not met: the ledger line named, then what the week lacks."""
    return [f"{r['verdict'].upper()} {r['id']} — {r['ledger']}: {r['detail']}" for r in rows if r["verdict"] != MET]


# ── the week's routines (I/O at the edges) ───────────────────────────────────────────────────────────────────────────
def _num(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _calendar(ir: Any) -> dict[str, Any]:
    snap = getattr(ir, "inputs_snapshot", None) or {}
    cal: dict[str, Any] = snap["calendar"] if isinstance(snap.get("calendar"), dict) else {}
    return {
        "block": _num(cal.get("block")),
        "week": _num(cal.get("week")),
        "session_role": cal.get("session_role") or snap.get("session_role"),
    }


def _kind(ir: Any) -> str:
    action = str(getattr(ir, "source_action", "") or "")
    if action == "draft_custom":
        return "draft_custom"
    return "floor" if str(getattr(ir, "variant", "") or "") == "floor" else "engine"


def week_days(ir: Any, routines: list[Any], catalog: dict[str, Any], week: tuple[int | None, int | None]) -> dict[str, dict[str, Any]]:
    """Per session role of program week `week` (block, week): the routine that serves it — `ir` (the draft in hand) for
    its own role, else the newest routine COMMITTED for that role this week — as `{keys, source}`. A floor draft (no
    calendar) belongs to the week of the routines dated the same day."""
    by_date: dict[str, tuple[int | None, int | None]] = {}
    for r in routines:
        cal = _calendar(r)
        if cal["week"] is not None:
            by_date.setdefault(str(getattr(r, "target_date", "")), (cal["block"], cal["week"]))

    def _week_of(r: Any) -> tuple[int | None, int | None]:
        cal = _calendar(r)
        return (cal["block"], cal["week"]) if cal["week"] is not None else by_date.get(str(getattr(r, "target_date", "")), (None, None))

    out: dict[str, dict[str, Any]] = {}
    committed = sorted(
        (r for r in routines if str(getattr(r, "status", "")) == "active" and _week_of(r) == week and _calendar(r)["session_role"]),
        key=lambda r: str(getattr(r, "hevy_pushed_at", None) or getattr(r, "created_at", None) or ""),
    )
    for r in committed:  # newest last, so it wins
        out[str(_calendar(r)["session_role"])] = {
            "keys": routine_day(r, catalog),
            "source": f"{_kind(r)} {str(getattr(r, 'routine_id', '?'))[:8]} {getattr(r, 'target_date', '')} committed",
        }
    role = _calendar(ir)["session_role"] if ir is not None else None
    if ir is not None and role and (_week_of(ir) in (week, (None, None))):
        out[str(role)] = {"keys": routine_day(ir, catalog), "source": f"{_kind(ir)} {str(getattr(ir, 'routine_id', '?'))[:8]} (this draft)"}
    return out


def _lister(start: str, end: str) -> list[Any]:
    from training import routine_repo

    return routine_repo.list_by_date_range(start, end)


def _week_of_rotation(rot: dict[str, Any] | None) -> tuple[int | None, int | None]:
    pos = (rot or {}).get("position") or {}
    return (_num(pos.get("block")), _num(pos.get("week")))


def rotation_for(ir: Any, routines: list[Any], catalog: dict[str, Any]) -> dict[str, Any] | None:
    """The week's rotation record: the draft's own, else one planned from its calendar (`variant_rotation.for_session`, no
    ledger read), else the record of a routine dated the same day (a floor draft carries neither)."""
    rot = (getattr(ir, "inputs_snapshot", None) or {}).get("rotation")
    if isinstance(rot, dict):
        return rot
    from training import variant_rotation

    for r in [ir] + [x for x in routines if str(getattr(x, "target_date", "")) == str(getattr(ir, "target_date", ""))]:
        cal = _calendar(r)
        if cal["week"] is not None and cal["block"] is not None:
            entry = {
                "week": cal["week"],
                "block": cal["block"],
                "session_role": cal["session_role"],
                "date": getattr(ir, "target_date", None),
            }
            return variant_rotation.for_session(entry, catalog, read=False)
        if isinstance((getattr(r, "inputs_snapshot", None) or {}).get("rotation"), dict):
            return r.inputs_snapshot["rotation"]
    return None


def _routines_around(day: str | None, lister: Callable[[str, str], list[Any]] | None) -> list[Any]:
    from common.pacific_time import shift_day_key

    if not day:
        return []
    return list((lister or _lister)(shift_day_key(day, -WEEK_WINDOW_DAYS[0]), shift_day_key(day, WEEK_WINDOW_DAYS[1])))


def attach(
    block: dict[str, Any], ir: Any, target_date: str, catalog: dict[str, Any] | None, lister: Callable[[str, str], list[Any]] | None = None
) -> None:
    """Stage 1 (`plan_next_session`): `constraint_block.week_commitments` over the program week — the draft in hand for its
    session, the routines committed this week for theirs, the plan for the rest — and, on a failure, the sentence on
    `honesty`. A failed routine read is named on the result; the week is then the plan (and the draft in hand)."""
    src = f"draft {getattr(ir, 'routine_id', '?')}" if ir is not None else "the planned session (constraint_block.session.rotation)"
    try:
        read_error = None
        try:
            routines = _routines_around(target_date, lister)
        except Exception as e:  # noqa: BLE001 — the week's routines are named unread, never assumed absent
            routines, read_error = [], f"{type(e).__name__}: {e}"[:200]
        rot = rotation_for(ir, routines, catalog or {}) if ir is not None else (block.get("session") or {}).get("rotation")
        week = (
            (_calendar(ir)["block"], _calendar(ir)["week"])
            if ir is not None and _calendar(ir)["week"] is not None
            else _week_of_rotation(rot)
        )
        out = evaluate(rot, catalog, on=target_date, days=week_days(ir, routines, catalog or {}, week), source=src)
        if read_error:
            out["routines_read_error"] = read_error
    except Exception as e:  # noqa: BLE001 — stage 1 must still answer; the failure is named, never a pass
        out = {"issue": ISSUE, "verdict": "read_failed", "error": f"{type(e).__name__}: {e}"[:300], "evaluated_from": src}
    block["week_commitments"] = out
    if out["verdict"] == "fail":
        block.setdefault("honesty", []).append(
            f"STAGE 1 FAILS on the concession ledger's weekly commitments ({', '.join(out['blocking'])}) — {src} is refused at commit (#5774)"
        )


def _catalog() -> dict[str, Any]:
    from training.routine_generator import _load_json  # the generator's own catalog read (local, else S3)

    return dict(_load_json("movement_catalog.json").get("movements") or {})


def commit_refusal(ir: Any, err: Any, lister: Callable[[str, str], list[Any]] | None = None) -> dict[str, Any] | None:
    """`manage_hevy_routine commit`: the refusal when the program week this draft serves into fails stage 1, else None —
    any draft (engine, `draft_custom`, floor), the week read with the routines already committed. `err` is the caller's
    error-envelope builder (message, error_code=..., suggestions=..., detail=...). Fails CLOSED: a week that cannot be
    read refuses, named."""
    day = getattr(ir, "target_date", None)
    read_error = None
    try:
        routines = [r for r in _routines_around(day, lister) if getattr(r, "routine_id", None) != getattr(ir, "routine_id", None)]
    except Exception as e:  # noqa: BLE001 — like the prescription gate's index read: named, the week is this draft + the plan
        routines, read_error = [], f"{type(e).__name__}: {e}"[:200]
    try:
        catalog = _catalog()
        rot = rotation_for(ir, routines, catalog)
        cal = _calendar(ir)
        week = (cal["block"], cal["week"]) if cal["week"] is not None else _week_of_rotation(rot)
        out = evaluate(rot, catalog, on=day, days=week_days(ir, routines, catalog, week), source=f"draft {getattr(ir, 'routine_id', '?')}")
        out["routines_read_error"] = read_error
    except Exception as e:  # noqa: BLE001 — fail CLOSED and legible: an unreadable week is never a passed one
        return err(
            f"Refusing to commit — the stage-1 week check (#5774) could not run: {type(e).__name__}: {e}"[:400], error_code=ERROR_CODE
        )
    if out["verdict"] != "fail":
        return None
    missed = [r for r in out["rows"] if r["blocking"]]
    return err(
        "Refusing to commit — stage 1 fails on the concession ledger's weekly commitments (#5774): " + " | ".join(lines(missed)),
        error_code=ERROR_CODE,
        suggestions=[
            "Re-draft so the program week serves the missing commitment — the engine's session, or a draft_custom day that carries it.",
            "The week is read from what is served: the routines committed this program week, this draft, and the plan for the rest.",
        ],
        detail=out,
    )
