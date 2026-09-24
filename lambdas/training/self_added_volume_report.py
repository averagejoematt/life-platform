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
    the digest reuses its own query instead of issuing a second one."""
    threshold = int(next(t for t in owner_redlines.TRIPWIRES if t["id"] == "self_added_volume")["threshold_weeks"])
    return self_added_volume.evaluate(hevy_full, w1_end, threshold)


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
    return out
