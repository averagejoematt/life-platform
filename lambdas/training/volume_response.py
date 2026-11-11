"""volume_response.py — the block-end volume-response report (#5801): the dose beside the response, as a PROPOSAL.

The block retro grades the anchors' e1RM trend and #5762 records the progression basis each draft applied, but nothing
put the DOSE (weekly working sets per muscle) next to the RESPONSE (each lift's e1RM trend) — so each block's volume was
set without his own dose-response. This joins them, per muscle, and proposes next block's weekly sets from it.

ADVISORY, NEVER APPLIED. The output feeds the block design review (#5776); no writer reads it, no scheduled job runs it
(`scripts/training_block_retro.py volume-response`, an optional `/training-review` section). Loads and e1RMs are private
health numbers: the report is owner-only scratch output, never a repo file or a public surface.

NOTHING NEW IS COMPUTED. The sets are `muscle_volume.working_sets_by_muscle` (the one per-muscle count behind
`get_muscle_volume`); the trend is `plan_engine.anchor_e1rm_trend` over each lift's session e1RMs (the reader the May
tracker and the retro use); the noise line is the `anchor_lift_strength_drop` tripwire's own `threshold_pct` — the
platform's one statement of how big an e1RM move must be to count (`block_retro` grades `anchors` through it). The
proposal band is the owner's `sets_per_muscle_wk` range and its `volume_ceiling` top (`owner_redlines`).

HONESTY (ADR-104/105). n is one block and a handful of sessions per lift, so every label carries its n and the
caveat; the wording is "co-occurred with", never "caused". A move inside the noise line is `flat` and its proposal is
`insufficient evidence` (no change is proposed from it); so is a lift with too few sessions, a muscle whose lifts
disagree, and a muscle with no band. Pure: no clock, no I/O — the script hands the rows in.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

from training import muscle_volume, owner_redlines, plan_engine, program_structure

VERSION = "volume-response@1.0.0"
GAINING, FLAT, LOSING, MIXED, UNMEASURED = "gaining", "flat", "losing", "mixed", "unmeasured"
INSUFFICIENT = "insufficient evidence"
HOLD, STEP_DOWN = "hold", "step down"
#: Sets a `losing` response steps the proposal down by (never below the band's floor, never above the ceiling).
STEP_SETS = 2
CAVEAT = (
    "n = one block, a handful of sessions per lift: the e1RM change co-occurred with this dose; it does not show the dose "
    "caused it (sleep, energy deficit, deloads and variant switches move e1RM too). A change inside the noise line is not read."
)

# label -> the redline group that carries its band (`program_structure.REDLINE_MUSCLE_GROUPS`, keyed by catalog muscle)
_LABEL_KEY = {"Quads": "quadriceps", "Hamstrings": "hamstrings", "Glutes": "glutes", "Chest": "chest", "Back": "back"}
_LABEL_KEY.update({"Shoulders": "shoulders", "Biceps": "biceps", "Triceps": "triceps"})


def noise_pct() -> float:
    """The e1RM move (%) inside which nothing is read: the anchor tripwire's own threshold."""
    return float(next(t for t in owner_redlines.TRIPWIRES if t["id"] == "anchor_lift_strength_drop")["threshold_pct"])


def weekly_ceiling() -> int:
    """`volume_ceiling`'s sets-per-muscle-per-week top — the band's top, read from the redline, never re-typed."""
    return int(next(t for t in owner_redlines.TRIPWIRES if t["id"] == "volume_ceiling")["threshold"]["sets_per_muscle_wk"])


def band_for(label: str) -> Optional[list[int]]:
    """The owner's `sets_per_muscle_wk` range for a muscle label, or None when no redline group carries it."""
    for spec in program_structure.REDLINE_MUSCLE_GROUPS.values():
        if _LABEL_KEY.get(label) in spec["primary_muscles"]:
            return list(owner_redlines.REDLINES["lifting_sessions_per_wk"][spec["range_key"]])
    return None


def lift_response(sessions: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """One lift's response over its e1RM series (cut to the latest session's identity — a variant switch is never a move).

    `sessions` is `mcp.strength_helpers.extract_hevy_sessions` shape, on or before the block end. The trend is
    `plan_engine.anchor_e1rm_trend`; `change_pct` is its recent median against its baseline median, signed.
    """
    sess = sorted(sessions, key=lambda s: str(s.get("date")))
    ident = str(sess[-1].get("identity") or "").upper() if sess else ""
    cut = [s for s in sess if str(s.get("identity") or "").upper() == ident]
    trend = plan_engine.anchor_e1rm_trend([s.get("best_1rm") for s in cut])
    out: dict[str, Any] = {"n_sessions": trend.get("n_sessions_e1rm", 0), "noise_pct": noise_pct()}
    base, recent = trend.get("baseline_median_e1rm_lb"), trend.get("recent_median_e1rm_lb")
    if not base or recent is None:
        return {**out, "label": UNMEASURED, "reason": trend.get("insufficient") or "no e1RM series"}
    change = round((float(recent) - float(base)) / float(base) * 100.0, 1)
    label = FLAT if abs(change) < out["noise_pct"] else (GAINING if change > 0 else LOSING)
    return {**out, "label": label, "change_pct": change, "baseline_e1rm_lb": base, "recent_e1rm_lb": recent}


def _muscle_label(labels: list[str]) -> str:
    measured = {x for x in labels if x != UNMEASURED}
    if not measured:
        return UNMEASURED
    return measured.pop() if len(measured) == 1 else MIXED


def propose(label_of: str, performed: float, band: Optional[list[int]], ceiling: int) -> dict[str, Any]:
    """Next block's weekly sets for one muscle, from its response label. The proposal is never applied."""
    if band is None:
        return {"status": INSUFFICIENT, "reason": "no sets_per_muscle_wk band carries this muscle"}
    if label_of in (FLAT, MIXED, UNMEASURED):
        why = {
            FLAT: "every measured lift moved inside the noise line",
            MIXED: "the muscle's lifts moved in different directions",
            UNMEASURED: "no lift with enough sessions to read a trend",
        }[label_of]
        return {"status": INSUFFICIENT, "reason": why}
    lo, hi = int(band[0]), int(ceiling)
    held = round(performed)
    if label_of == GAINING:
        return {"status": HOLD, "sets_per_wk": max(lo, min(hi, held)), "reason": "e1RM rose beyond noise at this dose; hold it"}
    return {
        "status": STEP_DOWN,
        "sets_per_wk": max(lo, min(hi, held - STEP_SETS)),
        "reason": f"e1RM fell beyond noise; {STEP_SETS} fewer sets",
    }


def _lifts_by_muscle(lifts: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by: dict[str, list[dict[str, Any]]] = {}
    for lift in lifts:
        primary = muscle_volume.attribute_exercise(str(lift.get("name") or ""), lift.get("template_id") or None)["primary"]
        if primary:
            by.setdefault(primary, []).append(
                {"name": lift.get("name"), "template_id": lift.get("template_id"), **lift_response(lift["sessions"])}
            )
    return by


def build_report(
    block_end: str,
    *,
    weeks: float,
    muscle_totals: Mapping[str, Mapping[str, Any]],
    lifts: Iterable[Mapping[str, Any]],
    progression: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """The report. `muscle_totals` is `working_sets_by_muscle(...)["muscles"]` over the block; `weeks` its inclusive length;
    `lifts` is [{name, template_id, sessions}] for each lift logged in the block; `progression` the #5762 block record."""
    by_muscle = _lifts_by_muscle(lifts)
    ceiling = weekly_ceiling()
    rows = []
    for muscle in muscle_volume.MUSCLES:
        sets = float((muscle_totals.get(muscle) or {}).get("total_sets") or 0)
        if not sets and muscle not in by_muscle:
            continue
        performed = round(sets / weeks, 1) if weeks else 0.0
        lifts_here = by_muscle.get(muscle, [])
        label = _muscle_label([x["label"] for x in lifts_here])
        rows.append(
            {
                "muscle": muscle,
                "performed_sets_per_wk": performed,
                "band": band_for(muscle),
                "lifts": lifts_here,
                "response": label,
                "n_lifts_measured": sum(1 for x in lifts_here if x["label"] != UNMEASURED),
                "proposal": propose(label, performed, band_for(muscle), ceiling),
            }
        )
    return {
        "version": VERSION,
        "block_end": block_end,
        "weeks": weeks,
        "ceiling_sets_per_muscle_wk": ceiling,
        "noise_pct": noise_pct(),
        "caveat": CAVEAT,
        "muscles": rows,
        "progression": dict(progression) if progression else None,
        "applied": False,
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    """The owner-only doc text. States n and the caveat on every row; says plainly that nothing is applied."""
    out = [
        f"# Volume response, block ending {report['block_end']} — ADVISORY, never applied",
        "",
        f"{report['caveat']} Noise line: {report['noise_pct']}% e1RM. Weekly ceiling: {report['ceiling_sets_per_muscle_wk']} sets/muscle.",
        "Feeds the block design review (#5776) as a proposal; the owner decides.",
        "",
    ]
    for r in report["muscles"]:
        p = r["proposal"]
        nxt = f"{p['sets_per_wk']} sets/wk ({p['status']})" if "sets_per_wk" in p else INSUFFICIENT
        out.append(
            f"## {r['muscle']}: {r['performed_sets_per_wk']} sets/wk performed; response {r['response']} (n = {r['n_lifts_measured']} lift(s))"
        )
        for x in r["lifts"]:
            move = f"{x['change_pct']:+}%" if "change_pct" in x else x.get("reason", "")
            out.append(f"- {x['name']}: {x['label']} {move} (n = {x['n_sessions']} sessions)")
        out.append(f"- Proposal: {nxt} — {p['reason']}")
        out.append("")
    prog = report.get("progression")
    if prog:
        out.append(
            f"Progression record (#5762): steps taken {prog.get('steps_taken')}, due {prog.get('step_due')}, stalls {prog.get('stalls')}."
        )
    return "\n".join(out).rstrip() + "\n"
