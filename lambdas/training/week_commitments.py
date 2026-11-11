"""week_commitments.py — the charter concession ledger's WEEKLY commitments as hard stage-1 checks (#5774, epic #5770).

WHY THIS EXISTS

The charter's `concession_ledger` is what each school of the panel gets in return for what it concedes to the deadline.
Several of those returns are weekly promises about what the program SERVES — dan_john "carries and kettlebell work weekly",
athlean_x "corrective work, carries, single-leg work", nippard "stretch-position work, rotation", rp_israetel's shoulder
volume (the charter's `volume_priorities.sets_per_wk.side_rear_delts` band). Until #5774 nothing at stage 1 read the ledger
at week level: no kettlebell movement appeared in four weeks of Hevy history while the ledger promised one weekly. This
module is that check: one function (`evaluate`) over a draft's own rotation record (`inputs_snapshot.rotation`, what
`variant_rotation.plan` stamps — the whole program week's served accessories), one verdict per commitment, and a stage-1
verdict that FAILS when any blocking commitment is missed. A failed draft is refused at commit (`commit_refusal`, called
from `manage_hevy_routine commit`), and the stage-1 constraint block shows the verdict before a draft exists (`attach`).

BLOCK OR WARN (owner, 2026-11-11)

  * The current pools CAN fill it -> it BLOCKS now: carries, single-leg, corrective, rotation, the side/rear-delt band.
  * The current pools CANNOT fill it -> report-only until they can, the switch in code:
      - kettlebell — `week_floors.kettlebell_enforced`: BLOCK from the earlier of library approval or 2026-12-20 (owner
        ruling 2026-11-11), RE-DATED here on the draft's own day, so a draft stamped `warn` on 12-19 for 12-20 still fails;
      - stretch-position — measured only from the exercise library's `length_bias` (no stretch classifier is written
        here); report-only, because no existing check could be named to retire for it (the owner's complexity budget:
        a new blocking check retires or merges one). `COMMITMENTS[...]["enforce"]` is the one line that would arm it.
  * A floor whose every member a RECORDED gate excludes (`week_floors.family_floors`' refusal reasons — equipment off the
    charter's list, block 1's first phase serving the committed template) WARNS with the gate named: the pool cannot fill it.
  * A draft with no rotation record (a `draft_custom` departure, the tired-day floor) is `not_evaluated` — named, never a
    pass, and not refused: the week-level record is what this check reads.

WHAT EACH CHECK MERGES (the complexity budget — no second classifier for anything): carries and single-leg ARE
`week_floors.family_floors` (#5786, report-only until now); kettlebell IS `week_floors.kettlebell_weekly` and its
`kettlebell_enforced` switch; the side/rear-delt band IS `volume_floors.charter_band_rows`' row (#5311's
`session.volume_bands`); rotation IS the panel's `accessory_rotation_drafted` computation (`rotation_problem`, moved here
from `panel_rubric`, which imports it); corrective IS the panel's corrective classifier (`CORRECTIVE`, moved here likewise).

Pure apart from `commit_refusal`'s catalog and library reads. No clock: the day is always the caller's.
"""

from __future__ import annotations

import re
from typing import Any

from training import week_floors

ISSUE = "#5774"
ERROR_CODE = "WEEK_COMMITMENT"
BLOCK, WARN, MET, NOT_EVALUATED = "block", "warn", "met", "not_evaluated"

# The panel's corrective classifier (athlean_x's `corrective_work` criterion), moved here so the gate and the grade share it.
CORRECTIVE = re.compile(r"face pull|pallof|rear delt|reverse fly|external rotation|band pull|dead bug|bird dog|scap", re.I)
LENGTHENED = "lengthened"  # the exercise library's `length_bias` value for a movement loaded in the stretched position
BAND = "side_rear_delts"  # charter volume_priorities.sets_per_wk key

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
    serving a variant that differs from the phase before. Absence is not credit."""
    if not isinstance(rot, dict):
        return "no rotation record on the draft"
    pos = rot.get("position")
    if not pos:
        return "the program week was unknown, so the template served"
    if (rot.get("volume_check") or {}).get("unchanged") is False:
        return "the rotation was refused (the week's counts would move)"
    if int(pos.get("step") or 0) <= 0:
        return None  # block 1's first phase serves the template as written
    held = [
        str(s.get("slot_id"))
        for s in rot.get("slots") or []
        if s.get("source") != "pinned" and len(s.get("pool") or []) >= 2 and s.get("variant") == s.get("previous")
    ]
    return f"held at a phase boundary: {', '.join(held)}" if held else None


def week_keys(rot: dict[str, Any], catalog: dict[str, Any], skill_ceiling: int = 2) -> list[str]:
    """Every movement the program week serves under this rotation record — the five roles' prescriptions with the record's
    `variants_by_role` applied (a refused or unknown-week rotation carries none: the template serves)."""
    from training import program_structure

    by_role = rot.get("variants_by_role") or {}
    return [
        str(e["movement_key"])
        for role in program_structure.SPLIT_ROLES
        for e in program_structure.session_prescription_for_role(
            role, catalog_movements=catalog, skill_ceiling=skill_ceiling, accessory_variants=by_role.get(role)
        )["exposures"]
        if e.get("movement_key")
    ]


def _row(c: dict[str, Any], verdict: str, detail: str) -> dict[str, Any]:
    return {
        "id": c["id"],
        "seats": sorted(c["seats"]),
        "ledger": ledger_line(c["seats"]),
        "verdict": verdict,
        "blocking": verdict == BLOCK,
        "detail": detail,
    }


def _floor(c: dict[str, Any], rot: dict[str, Any], family: str) -> dict[str, Any]:
    fl = next((f for f in rot.get("family_floors") or [] if f.get("family") == family), None)
    if fl is None:
        return _row(c, NOT_EVALUATED, f"the rotation record carries no {family} floor (drafted before #5786)")
    if fl.get("met"):
        return _row(c, MET, ", ".join(f"{s.get('title')} [{s.get('slot_id')}]" for s in fl.get("served") or []))
    gate = str(fl.get("gate") or "")
    hosted = not gate or gate.startswith("nothing in the week hosts")
    return _row(
        c, BLOCK if hosted else WARN, f"no {family} member this week" + ("" if hosted else f" — a recorded gate excludes it: {gate}")
    )


def _kettlebell(c: dict[str, Any], rot: dict[str, Any], on: str | None, status: str | None) -> dict[str, Any]:
    kb = rot.get("kettlebell_weekly")
    if not isinstance(kb, dict):
        return _row(c, NOT_EVALUATED, "the rotation record carries no kettlebell verdict (drafted before #5786)")
    if kb.get("met"):
        return _row(c, MET, ", ".join(str(s.get("title")) for s in kb.get("served") or []))
    why = week_floors.kettlebell_enforced(on, status)  # re-dated on the draft's own day, never the stamp's
    return _row(
        c,
        BLOCK if why else WARN,
        "no kettlebell movement this week — "
        + (f"stage 1 FAILS: {why}" if why else f"a warning until {week_floors.KETTLEBELL_BLOCK_FROM} or library approval"),
    )


def _corrective(c: dict[str, Any], keys: list[str] | None, catalog: dict[str, Any]) -> dict[str, Any]:
    if keys is None:
        return _row(c, NOT_EVALUATED, "the movement catalog was not read")
    titles = [str((catalog.get(k) or {}).get("title") or k.replace("_", " ")) for k in keys]
    hits = sorted({t for t in titles if CORRECTIVE.search(t)})
    return _row(c, MET if hits else BLOCK, ", ".join(hits) if hits else "no corrective movement (face pull, rear delt, Pallof …)")


def _stretch(c: dict[str, Any], keys: list[str] | None, lib: dict[str, Any] | None) -> dict[str, Any]:
    if keys is None or not isinstance((lib or {}).get("movements"), dict):
        why = "the movement catalog was not read" if keys is None else "no exercise library on this bundle to read length_bias from"
        return _row(c, NOT_EVALUATED, f"{why} — report-only ({c['report_only']})")
    movements = lib["movements"]  # type: ignore[index]
    hits = sorted(
        {str((movements.get(k) or {}).get("title") or k) for k in keys if (movements.get(k) or {}).get("length_bias") == LENGTHENED}
    )
    return _row(
        c, MET if hits else WARN, ", ".join(hits) if hits else f"no lengthened-position movement — report-only ({c['report_only']})"
    )


def _band(c: dict[str, Any], rot: dict[str, Any], catalog: dict[str, Any] | None) -> dict[str, Any]:
    if not catalog:
        return _row(c, NOT_EVALUATED, "the movement catalog was not read")
    from training import variant_rotation

    row = variant_rotation.week_volume(catalog, rot.get("variants_by_role") or {})["bands"].get(BAND)
    if not row:
        return _row(c, NOT_EVALUATED, f"no charter band {c['band']}")
    lo, hi = row["band"]
    inside = all(lo <= n <= hi for n in row["member_sets"])
    return _row(c, MET if inside else BLOCK, f"{row['member_sets']} sets a week against the charter band [{lo}, {hi}]")


def _rotation(c: dict[str, Any], rot: dict[str, Any]) -> dict[str, Any]:
    why = rotation_problem(rot)
    return _row(c, BLOCK if why else MET, why or "on the charter cadence")


def evaluate(
    rotation: Any, catalog: dict[str, Any] | None, *, on: str | None, library: Any = ..., source: str = "the draft's rotation record"
) -> dict[str, Any]:
    """Every `COMMITMENTS` row over one rotation record on day `on`, and the stage-1 verdict: `fail` when any row blocks,
    `pass` when none does, `not_evaluated` when there is no rotation record to read. `library`: the exercise library
    (read from config when not given) — its `status` arms the kettlebell switch, its `length_bias` measures stretch."""
    by_id = {c["id"]: c for c in COMMITMENTS}
    if not isinstance(rotation, dict):
        rows = [_row(c, NOT_EVALUATED, "no rotation record — a draft_custom departure or the tired-day floor") for c in COMMITMENTS]
    else:
        lib = week_floors.library() if library is ... else library
        status = week_floors.library_status(data=lib)
        keys = week_keys(rotation, catalog) if catalog else None
        rows = [
            _floor(by_id["carries"], rotation, "carries"),
            _kettlebell(by_id["kettlebell"], rotation, on, status),
            _floor(by_id["single_leg"], rotation, "single_leg_progression"),
            _corrective(by_id["corrective"], keys, catalog or {}),
            _stretch(by_id["stretch_position"], keys, lib),
            _rotation(by_id["rotation"], rotation),
            _band(by_id["side_rear_delt_band"], rotation, catalog),
        ]
    blocking = [r["id"] for r in rows if r["blocking"]]
    verdict = NOT_EVALUATED if not isinstance(rotation, dict) else ("fail" if blocking else "pass")
    return {
        "issue": ISSUE,
        "stage": 1,
        "on": on,
        "evaluated_from": source,
        "verdict": verdict,
        "blocking": blocking,
        "warnings": [r["id"] for r in rows if r["verdict"] in (WARN, NOT_EVALUATED)],
        "rows": rows,
        "lines": lines(rows),
    }


def lines(rows: list[dict[str, Any]]) -> list[str]:
    """One sentence per commitment not met: the ledger line named, then what the week lacks."""
    return [f"{r['verdict'].upper()} {r['id']} — {r['ledger']}: {r['detail']}" for r in rows if r["verdict"] != MET]


def attach(block: dict[str, Any], ir: Any, target_date: str, catalog: dict[str, Any] | None) -> None:
    """Stage 1 (`plan_next_session`): `constraint_block.week_commitments` — the draft's own record when a routine is in
    hand, else the planned session's (`constraint_block.session.rotation`) — and, when it fails, the sentence on `honesty`."""
    if ir is not None:
        rot, src = (getattr(ir, "inputs_snapshot", None) or {}).get("rotation"), f"draft {getattr(ir, 'routine_id', '?')}"
    else:
        rot, src = (block.get("session") or {}).get("rotation"), "the planned session (constraint_block.session.rotation)"
    try:
        out = evaluate(rot, catalog, on=target_date, source=src)
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


def commit_refusal(ir: Any, err: Any) -> dict[str, Any] | None:
    """`manage_hevy_routine commit`: the refusal when the draft's week fails stage 1, else None. `err` is the caller's
    error-envelope builder (message, error_code=..., suggestions=..., detail=...)."""
    rot = (getattr(ir, "inputs_snapshot", None) or {}).get("rotation")
    if not isinstance(rot, dict):
        return None
    try:
        out = evaluate(rot, _catalog(), on=getattr(ir, "target_date", None), source=f"draft {getattr(ir, 'routine_id', '?')}")
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
            "Re-draft the session (manage_hevy_routine draft) so the program week serves the missing commitment, then commit that.",
            "A deliberate departure is a draft_custom with its departure_reason in the owner's words — it is recorded as one.",
        ],
        detail=out,
    )
