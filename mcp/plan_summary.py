"""plan_summary.py — `plan_next_session(detail="summary")`: the compact view a coaching chat reads (#5803).

WHY. The full `plan_next_session` result is ~240–305 KB on a live stage-2 call (PR #5791 measured it:
`constraint_block` ~198 KB, `critics` ~86 KB, `coach_context` ~12 KB). It serialises in milliseconds, so the cost is
not latency: every call drops the whole payload into the chat's context, and a session makes several calls (stage 1,
stage 2, re-runs). The summary carries what the chat must say and decide on, and NAMES everything it leaves out.

WHAT IT IS. A projection of the FULL result, built after the tool has run and returned it. The tool body is unchanged:
stage 2 still stores its full critics record on the routine, and commit binding (`training.commit_binding`) and every
stored verdict read that stored record, never this response. The default stays `full`, so the nightly pre-draft, the
weekly panel grade and the coach packet, which call the tool in code, get exactly what they got before.

THE CONTRACT. `SUMMARY_KEYS` is the declared key set; every summary carries all of them (null where the stage has none).
`omitted` names each top-level key of the full result that the summary does not carry verbatim, with how to fetch it.
Lines the chat must SAY are carried verbatim, never shortened: the honesty lines, the reference's `must_say`, the
calibration items and the exercise-unlock lines. Everything else is bounded (`_TEXT_CAP`, `_LIST_CAP`). Pinned by
`tests/test_plan_summary_5803.py` (key set, size budget, the binding path).

If the projection itself raises, the caller gets the FULL result with `summary_error` named on it. A bug here must
never cost a stage-2 run its answer.
"""

from __future__ import annotations

import functools
import json
from typing import Any, Callable

DETAIL_FULL = "full"
DETAIL_SUMMARY = "summary"
DETAILS = (DETAIL_FULL, DETAIL_SUMMARY)

SUMMARY_KEYS = (
    "detail",
    "target_date",
    "stage",
    "how_to_use",
    "session",
    "red_team",
    "predraft",
    "walking",
    "tripwires",
    "honesty",
    "must_say",
    "week_commitments",
    "deload_recommendation",
    "calibration_due",
    "training_phase",
    "exercise_unlocks",
    "steps",
    "recent_aerobic",
    "rate_target",
    "nutrition_verdicts",
    "inputs_failed",
    "morning_note",
    "omitted",
    "_disclaimer",
)

# Full-result keys the summary carries VERBATIM; every other top-level key is named in `omitted`.
_VERBATIM = ("target_date", "calibration_due", "exercise_unlocks", "_disclaimer")
_TEXT_CAP = 300
_SHORT_CAP = 160  # a per-row detail line (a commitment row, a change, a tripped wire's action)
_LIST_CAP = 12
_SMALL_JSON = 300  # a session field whose JSON is at most this many characters rides as it is
# session fields carried elsewhere (`deload_recommendation`, `exercises`) or said by how_to_use (`how_to_draft`)
_SESSION_ELSEWHERE = ("deload_recommendation", "prescription", "how_to_draft")
# constraint_block keys `summarize` reads (each condensed into one of SUMMARY_KEYS)
_BLOCK_CONDENSED = (
    "session",
    "walking",
    "tripwires",
    "tripped",
    "unreadable_tripwires",
    "failed_read_tripwires",
    "not_yet_active_tripwires",
    "unevaluated_tripwires",
    "honesty",
    "reference",
    "week_commitments",
    "deload_recommendation",
    "steps_ramp",
    "recent_aerobic",
    "rate_target",
    "inputs",
    "morning_note",
)
VERDICT_KEYS = ("critic", "verdict", "shown_as", "reason", "overridden")  # on every compact verdict
_VERDICT_OPTIONAL = ("metric", "value", "field", "to", "sentence")

_STAGE_1_FETCH = "plan_next_session(target_date={d}, detail='full') — stage 1 reads only, safe to re-run"
_STAGE_2_FETCH = (
    "the stored record: manage_hevy_routine action=get routine_id={r} (routine.inputs_snapshot.critics, read-only); "
    "re-derived without writing: plan_next_session(routine_id={r}, target_date={d}, dry_run=true, detail='full')"
)

_HOW_TO_USE = (
    "SUMMARY view (#5803). `omitted` names every full-result key left out and how to fetch it: fetch before quoting a "
    "number this view does not carry. Say every `must_say` line (verbatim in substance), every `calibration_due` item and "
    "each `exercise_unlocks` line; `honesty` is what the engine could not see, so never present a gap as clear. Quote a "
    "row's `weekday`, never compute one (#5274). "
)
_HOW_TO_USE_STAGE = {
    1: (
        "Stage 1: start from `session` (the next undone session) and `recent_aerobic.cardio_pick`; if `predraft.status` is "
        "`ready`, review that draft instead of building one. Then draft (manage_hevy_routine draft) and call again WITH "
        "routine_id: stage 2, the red team (#3752)."
    ),
    2: (
        "Stage 2: read `red_team.written` first; false means the verdicts were NOT stored (`red_team.next` says why), so run "
        "stage 2 again. A `veto` blocks commit: redraft, or re-run with veto_override={critic, owner_words} in his words. "
        "Commit binds to the STORED record (`red_team.binding`), never to this view."
    ),
}


def _cap(text: Any, n: int = _TEXT_CAP) -> Any:
    if not isinstance(text, str) or len(text) <= n:
        return text
    return text[: n - 1] + "…"


def _fields(src: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {k: _cap(src.get(k)) for k in keys if k in src}


def _pick(src: Any, keys: tuple[str, ...]) -> dict[str, Any] | None:
    """`_fields` of a value that may not be a dict (None then)."""
    return _fields(src, keys) if isinstance(src, dict) else None


def _small(v: Any) -> bool:
    if v is None or isinstance(v, (bool, int, float)):
        return True
    if isinstance(v, str):
        return len(v) <= _TEXT_CAP
    return len(json.dumps(v, default=str)) <= _SMALL_JSON


def _verdict(v: dict[str, Any], changes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """One critic's verdict, compact: the word, the metric and number it argued from, the reason, the override."""
    from coach import critics

    out = {
        "critic": v.get("critic"),
        "verdict": v.get("verdict"),
        "shown_as": critics.display_verdict(v, changes),  # what the Hevy note prints (a no-op change reads `flag`)
        "reason": _cap(v.get("reason")),
        "overridden": critics.is_overridden(v),
    }
    # the number it argued from, and the model's sentence — present only where the verdict carries one
    out.update({k: _cap(v[k]) for k in _VERDICT_OPTIONAL if v.get(k) is not None})
    return out


def _session(block: dict[str, Any]) -> dict[str, Any] | None:
    s = block.get("session")
    if not isinstance(s, dict):
        return None
    out = {k: v for k, v in s.items() if k not in _SESSION_ELSEWHERE and _small(v)}
    rx = s.get("prescription") if isinstance(s.get("prescription"), dict) else None
    if rx:
        out["exercises"] = [
            {**{k: e[k] for k in ("movement_key", "kind", "pattern") if e.get(k) is not None}, "sets": len(e.get("sets") or [])}
            for e in (rx.get("exposures") or [])
            if isinstance(e, dict)
        ]
    out["fields_omitted"] = sorted(k for k in s if k not in out and k not in ("deload_recommendation", "how_to_draft"))
    return out


def _red_team(crit: Any) -> dict[str, Any] | None:
    if not isinstance(crit, dict):
        return None
    changes = crit.get("changes") or []
    rt = _fields(
        crit,
        ("routine_id", "routine_version", "written", "verdict_state", "veto", "next", "model_ran", "model_paused_reason", "model_step"),
    )
    rt["verdicts"] = [_verdict(v, changes) for v in crit.get("verdicts") or [] if isinstance(v, dict)]
    rt["changes"] = [
        {**_fields(c, ("critic", "field", "to", "applied")), "reason": _cap(c.get("reason"), _SHORT_CAP)}
        for c in changes[:_LIST_CAP]
        if isinstance(c, dict)
    ]
    rt["changes_total"] = len(changes)
    rt["recheck"] = _pick(crit.get("recheck"), ("passed", "remaining_vetoes", "total_sets", "exercise_count", "hevy_precheck_errors"))
    rt["binding"] = crit.get("binding")  # the stored record's binding; commit reads the STORED record, never this view
    rt["owner_overrides"] = [_pick(o, ("critic", "applied", "owner_words")) for o in crit.get("owner_overrides") or []]
    rt["thread_written"] = (crit.get("thread") or {}).get("written") if isinstance(crit.get("thread"), dict) else None
    if "would_write" in crit:
        rt["would_write_count"] = len(crit.get("would_write") or [])
    return rt


def _predraft(pre: Any) -> dict[str, Any] | None:
    if not isinstance(pre, dict):
        return None
    out = {k: _cap(v) for k, v in pre.items() if k != "critics" and _small(v)}
    crit = pre.get("critics")
    if isinstance(crit, dict):
        # the pre-draft's own compact record (`nightly_predraft._critics_summary`): small by construction, carried whole
        out["critics"] = {k: _cap(v) for k, v in crit.items() if k != "verdicts"}
        out["critics"]["verdicts"] = [_pick(v, ("critic", "verdict")) for v in crit.get("verdicts") or [] if isinstance(v, dict)]
    return out


def _tripwires(block: dict[str, Any]) -> dict[str, Any]:
    rows = {t.get("id"): t for t in block.get("tripwires") or [] if isinstance(t, dict)}
    return {
        "tripped": [
            {
                "id": tid,
                "observed": _cap((rows.get(tid) or {}).get("observed")),
                "action": _cap((rows.get(tid) or {}).get("action_if_tripped"), _SHORT_CAP),
            }
            for tid in block.get("tripped") or []
        ],
        "unreadable": block.get("unreadable_tripwires") or [],
        "failed_read": block.get("failed_read_tripwires") or [],
        "not_yet_active": block.get("not_yet_active_tripwires") or [],
        "unevaluated_count": len(block.get("unevaluated_tripwires") or []),
    }


def _week_commitments(wc: Any) -> dict[str, Any] | None:
    if not isinstance(wc, dict):
        return None
    out = _fields(wc, ("verdict", "blocking", "warnings", "evaluated_from"))
    out["rows"] = [
        {**_fields(r, ("id", "verdict", "blocking")), "detail": _cap(r.get("detail"), _SHORT_CAP)}
        for r in wc.get("rows") or []
        if isinstance(r, dict)
    ]
    return out


def _deload(block: dict[str, Any]) -> dict[str, Any] | None:
    d = block.get("deload_recommendation") or (block.get("session") or {}).get("deload_recommendation")
    if not isinstance(d, dict):
        return None
    out = _fields(d, ("active", "reasons", "applied", "applied_on", "proposed_response", "triggers_unwired"))
    out["unread"] = ((d.get("event_signals") or {}).get("unread")) or []
    return out


def _steps(block: dict[str, Any]) -> dict[str, Any] | None:
    ramp = block.get("steps_ramp")
    if not isinstance(ramp, dict):
        return None
    out = _fields(ramp, ("steps_target_line", "state", "today_target", "floor", "held_by"))
    out["walk_to_close_gap"] = _pick(ramp.get("walk_to_close_gap"), ("state", "goal", "projected_steps", "gap", "walk_minutes", "line"))
    return out


def _recent_aerobic(ra: Any) -> dict[str, Any] | None:
    if not isinstance(ra, dict):
        return None
    out = _fields(ra, ("state", "cardio_pick"))
    rows = [r for r in ra.get("rows") or [] if isinstance(r, dict)]
    out["rows"] = [
        {
            **_fields(r, ("date", "weekday", "modality", "moving_min", "avg_hr")),
            "flags": sorted(k for k, v in (r.get("flags") or {}).items() if v),
        }
        for r in rows[-_LIST_CAP:]
    ]
    out["rows_total"] = len(rows)
    out["totals"] = _pick(ra.get("totals"), ("weight_bearing_hr_48h", "weight_bearing_hr_72h", "aerobic_hr_72h", "walks_over_75_min_48h"))
    return out


def _rate_target(rt: Any) -> dict[str, Any] | None:
    if not isinstance(rt, dict):
        return None
    out = _fields(rt, ("low_lb_wk", "high_lb_wk", "target_lb_wk", "target_pct_bw_wk", "cap_lb_wk", "owner_to_resolve"))
    out.update(_pick(rt.get("band"), ("floor_pct_bodyweight_per_wk", "ceiling_pct_bodyweight_per_wk")) or {})
    out["protein_gate_state"] = (rt.get("protein_gate") or {}).get("state")
    return out


def _nutrition(nc: Any) -> dict[str, Any] | None:
    if not isinstance(nc, dict):
        return None
    out = _fields(nc, ("veto", "model_ran", "model_paused_reason", "error"))
    out["verdicts"] = [_verdict(v) for v in nc.get("verdicts") or [] if isinstance(v, dict)]
    out["floor_misses"] = [_cap(m) for m in (nc.get("floor_misses") or [])[:_LIST_CAP]]
    return out


def _training_phase(tp: Any) -> dict[str, Any] | None:
    if not isinstance(tp, dict):
        return None
    out = {k: _cap(v) for k, v in tp.items() if k != "value"}
    val = tp.get("value")
    if isinstance(val, dict):
        out.update(_fields(val, ("phase", "phase_title", "since", "pending", "next_phase", "next_phase_title", "next_verdict")))
        out["closest_unmet_gate"] = _pick(val.get("closest_unmet_gate"), ("id", "verdict", "detail", "metric", "threshold"))
    return out


def _omitted(out: dict[str, Any], block: dict[str, Any]) -> dict[str, Any]:
    """Every full-result key this view does not carry verbatim -> which `fetch` brings it back."""
    d, rid = out.get("target_date"), (out.get("critics") or {}).get("routine_id")
    keys = {k: ("stage_2" if k == "critics" else "stage_1") for k in out if k not in _VERBATIM}
    fetch = {"stage_1": _STAGE_1_FETCH.format(d=d)}
    if "critics" in keys:
        fetch["stage_2"] = _STAGE_2_FETCH.format(r=rid, d=d)
    # the block keys this view reads nothing from (the rest are condensed into the summary's own keys)
    return {"keys": keys, "fetch": fetch, "constraint_block_not_condensed": sorted(k for k in block if k not in _BLOCK_CONDENSED)}


def summarize(out: dict[str, Any]) -> dict[str, Any]:
    """The declared compact view of one full `plan_next_session` result. Pure: reads `out`, writes nothing."""
    cb = out.get("constraint_block")
    block: dict[str, Any] = cb if isinstance(cb, dict) else {}
    walking = _pick(block.get("walking"), ("state", "now_hr_wk", "floor_hr_wk", "gap_hr_wk", "pct_of_floor"))
    stage = 2 if "critics" in out else 1
    summary = {
        "detail": DETAIL_SUMMARY,
        "target_date": out.get("target_date"),
        "stage": stage,
        "how_to_use": _HOW_TO_USE + _HOW_TO_USE_STAGE[stage],
        "session": _session(block),
        "red_team": _red_team(out.get("critics")),
        "predraft": _predraft(out.get("predraft")),
        "walking": walking,
        "tripwires": _tripwires(block),
        "honesty": list(block.get("honesty") or []),  # verbatim: the engine's own statement of what it cannot see
        "must_say": list((block.get("reference") or {}).get("must_say") or []),  # verbatim, required in the answer
        "week_commitments": _week_commitments(block.get("week_commitments")),
        "deload_recommendation": _deload(block),
        "calibration_due": out.get("calibration_due"),  # verbatim: said every day until logged (#5760)
        "training_phase": _training_phase(out.get("training_phase")),
        "exercise_unlocks": out.get("exercise_unlocks"),  # verbatim: announce-once (#5772), so never dropped here
        "steps": _steps(block),
        "recent_aerobic": _recent_aerobic(block.get("recent_aerobic")),
        "rate_target": _rate_target(block.get("rate_target")),
        "nutrition_verdicts": _nutrition(out.get("nutrition_critics")),
        "inputs_failed": {
            k: _cap((v or {}).get("error"), _SHORT_CAP)
            for k, v in (block.get("inputs") or {}).items()
            if (v or {}).get("state") == "read_failed"
        },
        "morning_note": block.get("morning_note"),
        "omitted": _omitted(out, block),
        "_disclaimer": out.get("_disclaimer"),
    }
    return summary


def detail_mode(fn: Callable[[dict[str, Any] | None], Any]) -> Callable[[dict[str, Any] | None], Any]:
    """`detail` on `plan_next_session`: refused BEFORE the tool runs when it is not one of `DETAILS` (a stage 2 must
    never write and then fail on its response shape); `full` (the default) is the result unchanged."""
    from mcp.utils import mcp_error

    @functools.wraps(fn)
    def wrapper(args: dict[str, Any] | None = None) -> Any:
        detail = (args or {}).get("detail") or DETAIL_FULL
        if detail not in DETAILS:
            return mcp_error(f"detail must be one of {list(DETAILS)}, got {detail!r}", error_code="INVALID_ARG")
        out = fn(args)
        if detail == DETAIL_FULL or not isinstance(out, dict) or "error" in out:
            return out
        try:
            return summarize(out)
        except Exception as e:  # noqa: BLE001 — the full answer is returned, the projection's failure named on it
            out["summary_error"] = f"{type(e).__name__}: {e}"[:200]
            return out

    return wrapper
