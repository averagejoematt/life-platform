"""mcp/panel_weekly_grade.py — the weekly panel-rubric grade of the real committed plan (#5072).

`training.panel_judge.grade_committed_week` is pure: it takes the week's committed routines, the latest
constraint block and the stored history, and returns the grade. This module is its WIRING on the MCP
Lambda — the three readers and the one writer — so the job can run where the plan engine and the
routine repo already live:

  * routines    `training.routine_repo.list_by_date_range(week_start, week_end)`, kept when COMMITTED (pushed
                to Hevy or `active`, never archived) — the plan he actually got, not a pre-draft.
  * the block   `tool_plan_next_session` stage 1 for the week's last day — the same deterministic block the
                plan was drafted beside (fatigue signals, the steps ramp, the tripwires). Fail-soft: an
                unreadable block is named on the grade (`degraded`), never a fabricated one.
  * history     the earlier `PANEL#` rows, for the trend.
  * the food    `training.food_panel.build_food_plan(week_start)` (#5110): the week's resolved calorie targets
                (`health.calorie_target.resolve`, titration over charter, each day typed lifting/rest by the
                per-date calendar `training.training_calendar` (#5191) — the committed routines' dates when the Hevy
                record is unreadable) + the intended feedings + the week's titration record. Fail-soft: an
                unreadable food plan is named on the grade (`degraded`), the training grade still stands.
  * the menu    `health.weekly_menu.build(plan)` (#5110 box 4, owner ruling 2026-10-26 "Hold for the first built
                menu"): the food panel grades the COMMITTED MENU — the same deterministic fit of his anchor foods to
                the week's resolved days that `get_exercise_notes action='weekly_menu'` serves for that Monday —
                through `training.food_panel.on_menu` (`basis: menu`; `read_menu_plan`), so the row also shows the
                food-quality targets' hit or miss (#5105). A week whose menu is not built (no anchor table, a day
                refused, an unreadable fixed meal) is graded on the intended feedings and the food grade is `degraded`
                with the menu's reason code, never silently.
  * the write   ONE owner-only row, `USER#<id>#SOURCE#training_constraints / PANEL#<week_end>` (docs/SCHEMA.md):
                scores, letters, reasons, the controls' verdicts and the trend — never the plan itself.

THE SCHEDULE. `mcp.handler` dispatches `{"job": "panel_weekly_grade"}` to `lambda_entry`, so an EventBridge
rule with that constant input on `life-platform-mcp-warmer` is the whole schedule — the same idiom as the nightly
pre-draft. The rule `PanelWeeklyGrade` and its dead-man `panel-weekly-grade-missing` live in
`cdk/stacks/mcp_stack.py`; the expression is the `life-platform-mcp-warmer#PanelWeeklyGrade` row of
`config/schedules.json` — Monday 15:30Z (08:30 PDT / 07:30 PST Monday), so the default week is the Mon-Sun week
just finished. `JOB` below is the one declaration the stack must match (tests/test_panel_grade_schedule_5072.py).
The rule carries an implicit `AWS::Lambda::Permission`, so it lands by an owner-attended
`bash deploy/cdk_deploy.sh LifePlatformMcp`; until that apply the job runs only on demand.
Every run prints one EMF datapoint (`LifePlatform/HevyRoutine::PanelGradeOutcome{Job=panel_weekly_grade}`):
1 for a graded or honestly-empty week, 0 for a failure — the series the dead-man reads (7 empty daily buckets).
BUDGET: the judge spends under `charter_judge` (budget_guard band 1) through `bedrock_client.invoke_with_retry`;
at tier >= 1 the run still lands — code scores only, `degraded` with the pause named — and still emits the 1.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from mcp.nightly_predraft import METRIC_NAMESPACE

logger = logging.getLogger(__name__)

JOB: dict[str, Any] = {
    "name": "panel_weekly_grade",
    "event": {"job": "panel_weekly_grade"},
    # Pacific wall clock (config/schedules.json platform_timezone, ADR-165): Monday 08:30 PT, so "yesterday" is Sunday
    "schedule_key": "life-platform-mcp-warmer#PanelWeeklyGrade",
    "schedule_pt": "cron(30 8 ? * MON *)",
    "function": "life-platform-mcp-warmer",
    "metric_namespace": METRIC_NAMESPACE,
    "metric_name": "PanelGradeOutcome",
    "metric_dimension": {"Job": "panel_weekly_grade"},
    "deadman_alarm": "panel-weekly-grade-missing",
    # 7 consecutive empty daily buckets: a whole week with no honest outcome = the Monday run missed or failed
    "deadman_period_s": 86400,
    "deadman_periods": 7,
    "week_days": 7,
}
HONEST_STATUSES = ("graded", "no_plan")


def _committed(ir: Any) -> bool:
    return getattr(ir, "status", None) != "archived" and (
        bool(getattr(ir, "hevy_routine_id", None)) or getattr(ir, "status", None) == "active"
    )


def read_routines(week_start: str, week_end: str) -> list[dict[str, Any]]:
    from training.routine_repo import list_by_date_range

    return [asdict(ir) for ir in list_by_date_range(week_start, week_end) if _committed(ir)]


def read_constraint_block(week_end: str) -> dict[str, Any] | None:
    try:
        from mcp.tools_plan import tool_plan_next_session

        out = tool_plan_next_session({"target_date": week_end}) or {}
        block = out.get("constraint_block")
        return block if isinstance(block, dict) else None
    except Exception as e:  # noqa: BLE001 — the grade names the missing block; it never invents one
        logger.warning("panel weekly grade: constraint block unreadable (%s: %s)", type(e).__name__, str(e)[:200])
        return None


def _block_workouts_or_none(week_end: str) -> list[dict[str, Any]] | None:
    """The Hevy record through `week_end` for the per-date calendar (#5191); None on a failed read (the committed
    routines' dates then type the days, as before)."""
    try:
        from common.pacific_time import shift_day_key

        from mcp.plan_hevy_windows import _block_workouts

        return _block_workouts(shift_day_key(week_end, 1))
    except Exception as e:  # noqa: BLE001 — the routines' dates are the named fallback
        logger.warning("panel weekly grade: Hevy record unreadable for the calendar (%s: %s)", type(e).__name__, str(e)[:200])
        return None


def read_food_plan(week_start: str, routines: list[dict[str, Any]]) -> dict[str, Any] | None:
    try:
        from common.pacific_time import pacific_today, shift_day_key
        from health import titration
        from training import disruption, food_panel

        from mcp.config import table

        week_end = shift_day_key(week_start, JOB["week_days"] - 1)
        plan = food_panel.build_food_plan(
            week_start,
            planned_dates=[str(r.get("target_date") or "")[:10] for r in routines],
            disruption_records=disruption.load_records_failsoft(),  # #5215: no record = the full-day rubric
            titration_reader=lambda week: titration.read_record(table, week),
            case_id=f"food::{week_start}",
            block_workouts=_block_workouts_or_none(week_end),
            today=pacific_today(),
        )
        return plan  # the plain plan: the MCP menu read builds its menu over it; `run` lays the menu on (read_menu_plan)
    except Exception as e:  # noqa: BLE001 — the grade names the missing food plan; it never invents one
        logger.warning("panel weekly grade: food plan unreadable (%s: %s)", type(e).__name__, str(e)[:200])
        return None


def read_menu_plan(plan: dict[str, Any] | None, *, build: Any = None) -> dict[str, Any] | None:
    """#5110 box 4 + #5105: the plan the food panel grades — the week's menu built by code over `plan`
    (`health.weekly_menu.build`, laid over it by `food_panel.on_menu` -> `weekly_menu.food_plan`: the grams the anchors
    actually carry and the rows the food-quality check reads), stamped `basis: menu`; or, when no menu builds (no
    owner-only anchor table, a refused day, an unreadable fixed meal) or the build raises, the plan on its intended
    feedings stamped `basis: intended_feedings` with the menu's reason code — the food grade then says so (degraded) and
    the quality report says `not checked`, never a fabricated pass. `build(plan)` is injected in tests. None in, None out
    (the food plan was not read)."""
    if plan is None:
        return None
    from training import food_panel

    try:
        if build is None:
            from health import weekly_menu

            build = weekly_menu.build
        menu = build(plan)
        if not (menu or {}).get("built"):
            logger.warning(
                "panel weekly grade: no menu built (%s: %s)", (menu or {}).get("reason_code"), str((menu or {}).get("reason"))[:200]
            )
    except Exception as e:  # noqa: BLE001 — named on the grade (menu_unreadable); the intended feedings are graded
        logger.warning("panel weekly grade: menu unbuildable (%s: %s)", type(e).__name__, str(e)[:200])
        menu = {"built": False, "reason_code": "menu_unreadable"}
    return food_panel.on_menu(plan, menu)


def _menu_plan_or_plain(plan: dict[str, Any]) -> dict[str, Any]:
    """#5105's reader, on the ONE menu path (`read_menu_plan`): the menu-built plan when the menu builds, else the plain
    plan, untouched (the food panel then reports the food-quality targets as `not checked`)."""
    from training import food_panel

    out = read_menu_plan(plan) or plan
    return out if out.get("basis") == food_panel.BASIS_MENU else plan


def read_history() -> list[dict[str, Any]]:
    from boto3.dynamodb.conditions import Key
    from training.panel_judge import PANEL_SK_PREFIX

    from mcp.config import USER_PREFIX, table

    resp = table.query(
        KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}training_constraints") & Key("sk").begins_with(PANEL_SK_PREFIX),
        ProjectionExpression="week_end, overall_score, seat_scores",
    )
    return json.loads(json.dumps(resp.get("Items") or [], default=float))


def store(grade: dict[str, Any]) -> dict[str, Any]:
    from experiment.phase_taxonomy import experiment_stamp_for
    from training.panel_judge import panel_item

    from mcp.config import USER_ID, table

    item = panel_item(grade, f"USER#{USER_ID}")
    item.update(experiment_stamp_for(item["pk"], item["sk"]))
    item["graded_at"] = datetime.now(timezone.utc).isoformat()
    clean = json.loads(json.dumps(item, default=str), parse_float=Decimal)
    table.put_item(Item=clean)
    return {"written": True, "sk": item["sk"]}


def run(week_end: str | None = None) -> dict[str, Any]:
    """Grade the committed week ending `week_end` (default: yesterday, Pacific) and store it."""
    from common.pacific_time import pacific_today, shift_day_key
    from training import panel_judge

    end = week_end or shift_day_key(pacific_today(), -1)
    start = shift_day_key(end, -(JOB["week_days"] - 1))
    routines = read_routines(start, end)
    grade = panel_judge.grade_committed_week(
        end,
        week_start=start,
        routines=routines,
        constraint_block=read_constraint_block(end),
        history=read_history(),
        food_plan=read_menu_plan(read_food_plan(start, routines)),  # #5110 box 4: graded on the week's menu
    )
    grade["stored"] = store(grade) if grade.get("status") == "graded" else {"written": False, "reason": grade.get("status")}
    return grade


def emf_line(status: str) -> str:
    dims = JOB["metric_dimension"]
    return json.dumps(
        {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": METRIC_NAMESPACE,
                        "Dimensions": [sorted(dims)],
                        "Metrics": [{"Name": JOB["metric_name"], "Unit": "Count"}],
                    }
                ],
            },
            **dims,
            JOB["metric_name"]: 1 if status in HONEST_STATUSES else 0,
            "Status": status,
        }
    )


def lambda_entry(event: dict[str, Any]) -> dict[str, Any]:
    """The scheduled/on-demand entry. Never raises: a failure is logged by class and emits the datapoint at 0."""
    try:
        result = run((event or {}).get("week_end"))
    except Exception as e:  # noqa: BLE001 — reported by name; the dead-man reads the 0
        logger.exception("panel weekly grade failed")
        result = {"job": JOB["name"], "status": "failed", "error": f"{type(e).__name__}: {e}"[:300]}
    print(emf_line(result.get("status") or "failed"))
    summary = {k: result.get(k) for k in ("week_end", "status", "overall", "target_met", "degraded", "degraded_reasons", "stored")}
    food = result.get("food") or {}
    summary["food"] = {k: food.get(k) for k in ("overall", "target_met", "degraded_reasons", "basis", "menu")} if food else None
    logger.info("PANEL_WEEKLY_GRADE %s", json.dumps(summary, default=str)[:4000])
    return {"statusCode": 200, "body": json.dumps(summary, default=str), "headers": {"Content-Type": "application/json"}}
