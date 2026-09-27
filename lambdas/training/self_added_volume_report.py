"""#4111: the end-of-week self_added_volume report for the Sunday Weekly Digest.

Owner ruling 2026-09-23: "Just give me an end of week report or update — I don't think this
is anxiety, it's me wanting to do more." `report_only`: never a veto, never a mood question.
It reads the SAME `training.self_added_volume.evaluate` the plan_engine tripwire row reads, so
there is one computation and no second count. It lives here, not in the digest, to keep
`weekly_digest_lambda.py` inside its module-size baseline (#1665).
"""

from __future__ import annotations

from typing import Any, Callable

from training import owner_redlines, self_added_volume


def evaluate_for_digest(hevy_full: list[dict[str, Any]], w1_end: str) -> dict[str, Any]:
    """`hevy_full` already covers the window this needs: its worst-case start
    (`window_start(w1_end)`, a Sunday `w1_end`) lands exactly on the digest's `w4_start`, so
    the digest reuses its own query instead of issuing a second one.

    #4312: the rows are annotated with their routine archetype (one routine-index read) so an
    off-program complement (Flex) lands on its own line. If that read raises, the report still
    renders and `off_program_separation` says the line could not be separated — never a silent
    fold of Flex sets into "added beyond plan"."""
    from training.routine_title import annotate_with_routine_index

    threshold = int(next(t for t in owner_redlines.TRIPWIRES if t["id"] == "self_added_volume")["threshold_weeks"])
    start = self_added_volume.window_start(w1_end)
    try:
        rows = annotate_with_routine_index(hevy_full, start) if start else hevy_full
        separation: dict[str, Any] = {"state": "measured"}
    except Exception as e:  # noqa: BLE001 — the report renders; the line names why complements are not separated
        rows, separation = hevy_full, {"state": "read_failed", "error": f"{type(e).__name__}: {e}"}
    # `w1_end` is yesterday — a finished day: on a Monday run the week whose Sunday it is has ENDED and is the
    # latest complete week the report renders (#4111; before, it read as in progress and the report skipped it)
    return {**self_added_volume.evaluate(rows, w1_end, threshold, end_day_complete=True), "off_program_separation": separation}


def digest_rows(saw: dict[str, Any] | None, row: Callable[..., str], esc: Callable[[str], str]) -> str:
    """The most recent COMPLETE Mon–Sun week with a matched session: added sets or none.
    A standing report, not an alert gated on exceeding the prescription."""
    if not saw or not saw.get("weeks"):
        return ""
    wk = next((w for w in reversed(saw["weeks"]) if w.get("complete")), None)
    if not wk or not wk.get("sessions_matched"):
        return ""
    out = row(
        "Added Beyond Plan",
        f'{wk["added_sets"]} set(s) added ({wk["net_sets"]:+d} net) — week of {wk["week_start"]}',
        highlight=bool(wk["added_sets"]),
    )
    for a in wk.get("added", [])[:8]:
        rpe = f' @ RPE {a["max_rpe"]}' if a.get("max_rpe") is not None else ""
        out += row(f'↳ {esc(a["date"])} {esc(a["movement"])}', f'{a["programmed_sets"]} → {a["performed_sets"]} sets{rpe}')
    # #4312: the complements' own line — reported, never counted against the plan
    op = wk.get("off_program") or {}
    if op.get("sessions"):
        kinds = esc("/".join(op.get("archetypes") or []) or "off-program")
        out += row(
            "Off-Program Complements",
            f'{op["added_sets"]} set(s) added over {op["sessions"]} {kinds} session(s) — not counted against the plan',
        )
        for a in op.get("added", [])[:4]:
            out += row(
                f'↳ {esc(a["date"])} {esc(a["movement"])} ({esc(str(a.get("archetype") or ""))})',
                f'{a["programmed_sets"]} → {a["performed_sets"]} sets',
            )
    sep = saw.get("off_program_separation") or {}
    if sep.get("state") == "read_failed":
        out += row("↳ Off-program complements", f'not separated — routine index read failed ({esc(str(sep.get("error") or ""))})')
    return out
