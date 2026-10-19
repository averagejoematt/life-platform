"""panel_judge.py — the panel rubric's model half: a blinded judge for the criteria code cannot check (#5072).

`panel_rubric` scores every criterion a plan's own fields can prove (ADR-105). What remains — is the
exercise selection high-stimulus, is the conditioning placed to limit interference, does the plan read
like a time-bound transformation — is graded here, by ONE model call per plan with all eight seats in
it, on the training charter's AI seam (`charter_ai.system_blocks`, the charter block cached).

THE ANTI-GOODHART RULES (the owner's comment on #5072), each held by code or a test:

  * BLINDED. The judge reads `panel_rubric.blind_text(case)` — never the engine, its version, the
    plan's author or a routine id. The instructions below name no engine either.
  * A DIFFERENT TIER FROM THE PLANNER. The plan is built by the deterministic engine and red-teamed by
    the four critics on the WORKHORSE tier (`plan_critics`). The judge routes (`charter.judge`, the
    weekly grade; `charter.judge_gate`, the CI regression gate) resolve to the NARRATIVE tier, and every
    grade carries `tier_check` saying what each side resolved to — a same-model judge says so.
  * CALIBRATED AGAINST THE OWNER. Until the owner has graded `calibration.owner_graded_plans_required`
    plans by hand (`config/panel_rubric.json`), every grade says `calibrated: false`.
  * NEGATIVE CONTROLS, ALWAYS. The weekly grade judges the real plan AND the four controls
    `panel_rubric.negative_controls` makes of it, back-to-back inside one cache TTL; a control that
    passes the target makes the week's grade `degraded` — the rubric could not tell good from bad.
  * OUTCOMES OUTRANK THE RUBRIC. A tripped outcome tripwire (anchor strength, the loss rate, walking)
    on a plan the rubric passes reads `rubric_outranked`, never a clean A.

BUDGET. The weekly grade spends under `charter_judge` (band 1: an internal eval, pauses first); the CI
regression gate under `charter_judge_gate` (band 3 with the other operator-truth CI gates, pausing only at
the hard stop). A paused or failed judge leaves the CODE scores standing and marks the grade `degraded`
with the reason — never a fabricated score. Every call goes through `bedrock_client`, so a laptop run is
held by the dev-session cap (`ai.dev_session_cap`) as well.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from training import charter_ai, panel_rubric

logger = logging.getLogger(__name__)

WEEKLY_ROUTE = "charter.judge"
CI_ROUTE = "charter.judge_gate"
PLANNER_ROUTE = "plan_critics"  # the tier the plan's own red team runs on — the judge must not share it
# One weekly run = the real plan + every negative control, back-to-back (the cache register's calls_within_ttl).
WEEKLY_CALLS_PER_RUN = 1 + len(panel_rubric.CONTROL_MUTATIONS)
MAX_TOKENS = 2000
PANEL_SK_PREFIX = "PANEL#"

INSTRUCTIONS = (
    "PANEL RUBRIC JUDGE\n\n"
    "You grade ONE week of a training plan against a fixed rubric, as an eight-seat expert panel. Each seat is a "
    "school of training; the charter above names what each school concedes to the deadline and what it gets in "
    "return (concession_ledger). You see the plan only — not who or what wrote it — and you must not guess.\n\n"
    "Grade ONLY the criteria listed below; every other criterion was already scored from the plan's own fields. "
    "Score each 0-10 (10 = exemplary for this trainee under this charter, 9 = meets the bar, 7 = a visible gap, "
    "5 = half there, 0 = absent or contrary). Judge what the plan actually prescribes, not what it says about "
    "itself. Then, per seat, say whether the plan delivers what the seat was promised in return for its "
    "concession (concession_held) and give one short reason (why) naming the movement or line you judged from.\n\n"
    "Return JSON only, in the schema given. No preamble.\n\nCRITERIA TO GRADE\n"
)


# ── the request ───────────────────────────────────────────────────────────────────────────
def criteria_text(rubric: dict[str, Any]) -> str:
    rows = []
    for seat, crits in panel_rubric.judge_criteria(rubric).items():
        school = rubric["seats"][seat].get("school") or seat
        for c in crits:
            rows.append(f"- {seat}.{c['id']} ({school}): {c['text']}")
    return "\n".join(rows)


def response_schema(rubric: dict[str, Any]) -> dict[str, Any]:
    """A closed object: seat -> {scores: {criterion: int}, why, concession_held}. Small enough for Bedrock's grammar."""
    seats = {}
    for seat, crits in panel_rubric.judge_criteria(rubric).items():
        ids = [c["id"] for c in crits]
        seats[seat] = {
            "type": "object",
            "properties": {
                "scores": {
                    "type": "object",
                    "properties": {i: {"type": "integer"} for i in ids},
                    "required": ids,
                    "additionalProperties": False,
                },
                "why": {"type": "string"},
                "concession_held": {"type": "boolean"},
            },
            "required": ["scores", "why", "concession_held"],
            "additionalProperties": False,
        }
    return {"type": "object", "properties": seats, "required": sorted(seats), "additionalProperties": False}


def build_body(case: dict[str, Any], rubric: dict[str, Any], route: str, catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    """The Messages body for one plan: the cached charter block, the rubric instructions, the blinded plan."""
    return {
        "max_tokens": MAX_TOKENS,
        "temperature": 0,
        "system": charter_ai.system_blocks(route, INSTRUCTIONS + criteria_text(rubric)),
        "messages": [{"role": "user", "content": "PLAN UNDER REVIEW\n\n" + panel_rubric.blind_text(case, catalog)}],
    }


def parse_response(parsed: Any, rubric: dict[str, Any]) -> dict[str, Any]:
    """Seat -> {scores (clamped 0-10), why, concession_held}. A seat or criterion the reply lacks is left out
    (it reads `unscored` on the grade), never filled in."""
    out: dict[str, Any] = {}
    if not isinstance(parsed, dict):
        return out
    for seat, crits in panel_rubric.judge_criteria(rubric).items():
        row = parsed.get(seat)
        if not isinstance(row, dict):
            continue
        raw = row.get("scores")
        if not isinstance(raw, dict):
            raw = {}
        scores = {}
        for c in crits:
            v = raw.get(c["id"])
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                scores[c["id"]] = max(0.0, min(10.0, float(v)))
        held = row.get("concession_held")
        out[seat] = {"scores": scores, "why": str(row.get("why") or "")[:400], "concession_held": held if isinstance(held, bool) else None}
    return out


# ── the call ──────────────────────────────────────────────────────────────────────────────
def tier_check(route: str) -> dict[str, Any]:
    """What the judge and the planner's red team resolve to. `same_model` True is stated on every grade."""
    from ai import model_routing  # noqa: PLC0415

    judge_model, planner_model = model_routing.model_for(route), model_routing.model_for(PLANNER_ROUTE)
    return {"judge_model": judge_model, "planner_model": planner_model, "same_model": judge_model == planner_model}


def _bedrock_call(route: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    from ai import bedrock_client  # noqa: PLC0415 — lazy: the deterministic half imports without boto3

    model = getattr(charter_ai, charter_ai.CALLERS[route].model_var)
    return lambda body: bedrock_client.invoke_with_retry(body, model_name=model)


def _allowed(route: str) -> tuple[bool, str | None]:
    from ai import budget_guard  # noqa: PLC0415

    feature = charter_ai.CALLERS[route].feature
    try:
        if budget_guard.allow(feature):
            return True, None
        return False, f"paused by the budget guard ({feature} at tier {budget_guard.current_tier()})"
    except Exception as e:  # noqa: BLE001 — fail-open like every budget read; the judge then runs
        logger.warning("panel_judge: budget read failed (%s) — proceeding", type(e).__name__)
        return True, None


def judge(
    case: dict[str, Any],
    rubric: dict[str, Any],
    *,
    route: str = WEEKLY_ROUTE,
    call: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One judge call for one plan: {status, judged (seat -> scores), usage, reason}. Never raises.

    `call` is the transport (default: `bedrock_client.invoke_with_retry` on the route's model); tests and the
    gate's recorded mode pass a replay. Budget is checked here only for the real transport — a replay spends nothing."""
    from ai import structured_json  # noqa: PLC0415

    if call is None:
        ok, why = _allowed(route)
        if not ok:
            return {"status": "paused", "judged": None, "usage": {}, "reason": why}
    usage: dict[str, Any] = {}
    transport = call

    def _metered(body: dict[str, Any]) -> dict[str, Any]:
        resp = transport(body)
        usage.update((resp or {}).get("usage") or {})
        return resp

    try:
        if transport is None:  # inside the try: a missing boto3 / unknown route is an error status, never a raise
            transport = _bedrock_call(route)
        parsed = structured_json.call_json(_metered, build_body(case, rubric, route, catalog), response_schema(rubric), label="panel_judge")
    except Exception as e:  # noqa: BLE001 — a failed judge degrades the grade, it never fails the plan
        logger.warning("panel_judge: judge call failed (%s: %s)", type(e).__name__, str(e)[:200])
        return {"status": "error", "judged": None, "usage": usage, "reason": f"{type(e).__name__}: {str(e)[:200]}"}
    judged = parse_response(parsed, rubric)
    if not judged:
        return {"status": "unparsed", "judged": None, "usage": usage, "reason": "the judge's reply carried no gradeable seat"}
    return {"status": "ok", "judged": judged, "usage": usage, "reason": None}


def _cost(usage: dict[str, Any], route: str) -> float | None:
    if not usage:
        return None
    try:
        from ai import bedrock_client  # noqa: PLC0415

        return round(bedrock_client.estimate_cost_usd(usage, getattr(charter_ai, charter_ai.CALLERS[route].model_var)), 5)
    except Exception:  # noqa: BLE001 — a cost estimate is advisory
        return None


# ── the grade ─────────────────────────────────────────────────────────────────────────────
def calibration(rubric: dict[str, Any]) -> dict[str, Any]:
    cal = rubric.get("calibration") or {}
    n, need = len(cal.get("owner_grades") or []), int(cal.get("owner_graded_plans_required") or 0)
    return {"owner_graded_plans": n, "required": need, "calibrated": bool(need) and n >= need}


def grade_case(
    case: dict[str, Any],
    rubric: dict[str, Any],
    *,
    route: str = WEEKLY_ROUTE,
    call: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The full grade of one plan: the code pre-score, the judge, the combination, the outcome check."""
    code = panel_rubric.prescore(case, rubric, catalog)
    j = judge(case, rubric, route=route, call=call, catalog=catalog)
    graded = panel_rubric.combine(code, j["judged"], rubric)
    reasons = [f"judge {j['status']}: {j['reason']}"] if j["status"] != "ok" else []
    if j["status"] == "ok" and graded["unscored"]:
        reasons.append(f"judge left {len(graded['unscored'])} criteria unscored")
    disagree = panel_rubric.outcome_disagreement(case, graded)
    graded.update(
        case_id=case.get("case_id"),
        rubric_version=rubric.get("version"),
        judge={"status": j["status"], "route": route, "usage": j["usage"], "cost_usd": _cost(j["usage"], route)},
        degraded=bool(reasons) or graded["degraded"],
        degraded_reasons=reasons,
        rubric_outranked=disagree,
        tier_check=tier_check(route),
        calibration=calibration(rubric),
    )
    return graded


def failed_expectations(grade: dict[str, Any], expect_fail: list[str]) -> list[str]:
    """For a negative control: the `seat.criterion` it should have failed but did not (score at/above the seat floor)."""
    floor = float((grade.get("target") or {}).get("every_seat_at_least") or 0)
    missed = []
    for key in expect_fail:
        seat, _, crit = key.partition(".")
        score = (((grade["seats"].get(seat) or {}).get("criteria") or {}).get(crit) or {}).get("score")
        if score is None or score >= floor:
            missed.append(f"{key} scored {score!r}")
    if grade.get("target_met"):
        missed.append("the control met the panel target")
    return missed


def trend(current: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    """The change against the most recent earlier stored grade: overall and per seat."""
    prior = [h for h in history or [] if h.get("week_end") and h.get("week_end") < current.get("week_end", "")]
    if not prior:
        return {"previous": None, "weeks_graded": 0}
    prev = max(prior, key=lambda h: h["week_end"])
    seats = {s: round(v["score"] - float((prev.get("seat_scores") or {}).get(s, v["score"])), 2) for s, v in current["seats"].items()}
    return {
        "previous": prev["week_end"],
        "weeks_graded": len(prior),
        "overall_delta": round(current["overall"]["score"] - float(prev.get("overall_score") or 0), 2),
        "seat_delta": seats,
    }


def grade_committed_week(
    week_end: str,
    *,
    routines: list[dict[str, Any]],
    constraint_block: dict[str, Any] | None,
    rubric: dict[str, Any] | None = None,
    call: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    history: list[dict[str, Any]] | None = None,
    catalog: dict[str, Any] | None = None,
    week_start: str | None = None,
) -> dict[str, Any]:
    """The WEEKLY real-plan grade: the committed routines + the latest constraint block, then the four negative
    controls made from them — `WEEKLY_CALLS_PER_RUN` judge calls back-to-back. Readers are injected (the MCP
    side wires the routine repo, the plan engine and the PANEL# history), so this stays testable offline."""
    rubric = rubric or panel_rubric.load_rubric()
    if rubric is None:
        return {"week_end": week_end, "status": "no_rubric", "degraded": True, "degraded_reasons": ["config/panel_rubric.json unreadable"]}
    if not routines:
        return {"week_end": week_end, "status": "no_plan", "degraded": True, "degraded_reasons": ["no committed routine in the week"]}
    case = {
        "case_id": f"week::{week_end}",
        "week_start": week_start,
        "routines": routines,
        "constraint_block": dict(constraint_block or {}),
    }
    real = grade_case(case, rubric, route=WEEKLY_ROUTE, call=call, catalog=catalog)
    controls = []
    for c in panel_rubric.negative_controls(case):
        g = grade_case(c, rubric, route=WEEKLY_ROUTE, call=call, catalog=catalog)
        controls.append(
            {"control": c["case_id"].split("::")[-1], "target_met": g["target_met"], "missed": failed_expectations(g, c["expect_fail"])}
        )
    leaky = [c["control"] for c in controls if c["missed"]]
    if not constraint_block:
        real["degraded_reasons"].append("the constraint block was not read — the block-level criteria scored as absent")
    if leaky:
        real["degraded_reasons"].append(f"negative control(s) passed what they must fail: {leaky}")
    real.update(
        week_end=week_end,
        week_start=week_start,
        status="graded",
        routines_graded=len(routines),
        controls=controls,
        degraded=bool(real["degraded_reasons"]) or real["degraded"],
    )
    real["trend"] = trend(real, history or [])
    return real


def panel_item(grade: dict[str, Any], user_pk: str) -> dict[str, Any]:
    """The owner-only DDB row for one weekly grade (`<user_pk>#SOURCE#training_constraints / PANEL#<week_end>`).
    Scores, letters and reasons only — the plan itself is not copied (it stays on its ROUTINE# rows)."""
    return {
        "pk": f"{user_pk}#SOURCE#training_constraints",
        "sk": f"{PANEL_SK_PREFIX}{grade['week_end']}",
        "week_end": grade["week_end"],
        "week_start": grade.get("week_start"),
        "status": grade.get("status"),
        "overall_score": (grade.get("overall") or {}).get("score"),
        "overall_letter": (grade.get("overall") or {}).get("letter"),
        "target_met": grade.get("target_met"),
        "seat_scores": {s: v["score"] for s, v in (grade.get("seats") or {}).items()},
        "seats": grade.get("seats"),
        "degraded": grade.get("degraded"),
        "degraded_reasons": grade.get("degraded_reasons"),
        "rubric_outranked": grade.get("rubric_outranked"),
        "controls": grade.get("controls"),
        "trend": grade.get("trend"),
        "judge": grade.get("judge"),
        "tier_check": grade.get("tier_check"),
        "calibration": grade.get("calibration"),
        "rubric_version": grade.get("rubric_version"),
        "charter_version": charter_ai.training_charter.charter_version(),
    }
