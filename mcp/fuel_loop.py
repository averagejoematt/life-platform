"""fuel_loop.py — a tripped protein, fat or fibre floor rebuilds the menu, its grocery list and a Todoist prep task (#5792).

The `protein_floor_missed` tripwire's action reads "the next 7 days are a kitchen intervention (pre-portioned
protein)". Before this module nothing carried it out: plan_engine withheld the green block and that was all. This is the
action, executed — deterministic, no model call, so it runs at every budget tier.

HOST: a fail-soft leg on the nightly pre-draft (`mcp.nightly_predraft.lambda_entry`, EventBridge on
`life-platform-mcp-warmer`). That function already holds the Todoist secret (`rp.mcp_server()` grants
`life-platform/todoist` to the MCP server AND the warmer, TD-23), so NO new IAM. The leg never changes the pre-draft's
outcome or its dead-man.

THE ONE TRIGGER READER (`read_trigger`), over THE protein-gate window (`owner_redlines.protein_window`, the 7 completed
Pacific days ending yesterday):
  protein  the plan's own count (`mcp.tools_plan._protein_days_7d`, THE count, #4161), evaluated by
           `plan_engine.floor_days_state` — the evaluation plan_engine's `protein_floor_missed` row uses;
  fat      the days `health.macro_floors.evaluate_day` grades as missed (`met is False`; an unlogged or unreadable day
  fibre    is unknown, never a miss), through the SAME `floor_days_state`, so the count that trips is the tripwire's own
           `threshold_days`. No new threshold constant: a different count for fat and fibre is a charter key, by ruling.

ON A TRIGGER, AT MOST ONCE PER MACRO PER ISO WEEK: each fired macro takes a permanent claim on
`(macro, ISO week of today)` in the shared claim ledger (`mcp.idempotency`, scope `fuel_loop`). The macros whose claim
this run won get ONE menu and ONE Todoist task:
  * the menu is `health.weekly_menu.build` over the food plan (`mcp.panel_weekly_grade.read_food_plan`, the MCP menu
    read's own plan) cut to the intervention window (tomorrow and the six days after), one build per ISO week the window
    touches; the grocery list is the build's own (`weekly_menu.grocery_list`) and rides in `lines`;
  * a day the menu cannot fit is reported with each miss named (`weekly_menu`'s own `unfit_days`), never a silent no-op;
  * the task goes through `mcp.tools_todoist.create_todoist_task` (its claim-before-POST ledger), dated tomorrow, the
    menu and the shop in its description. A failed POST is named in the run result and the claims are RELEASED, so the
    next night retries rather than losing the week.
  A claim that degrades (the ledger could not be read or written) creates nothing: a nightly job that cannot prove it
  has not already acted would otherwise post a task every night (fail-closed, unlike the interactive tool's fail-open).

PRIVACY: the menu names his foods. They go ONLY into the Todoist task (his private space). The run result (the
CloudWatch log) carries dates, macros, day counts, codes and each unfit day's named misses — no food list.

DRY RUN (the post-deploy proof, read-only — no claim, no Todoist): from a checkout with read-only AWS credentials,
  python3 -c "import sys; sys.path[:0]=['lambdas','.']; import json; from mcp import fuel_loop as f; print(json.dumps(f.run(dry_run=True), indent=1, default=str))"
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Callable, Mapping, Optional, Sequence

from common.pacific_time import shift_day_key

logger = logging.getLogger(__name__)

ISSUE = "#5792"
SCOPE = "fuel_loop"  # the claim-ledger scope (USER#…#MCP_IDEMPOTENCY, sk `fuel_loop#<content key>`)
MACROS = ("protein", "fat", "fibre")
FLOOR_MACROS = ("fat", "fibre")  # graded per day by health.macro_floors (#5102)
# The tripwire's own action: "the next 7 days are a kitchen intervention" — the window the menu is built for.
INTERVENTION_DAYS = 7
DESCRIPTION_MAX = 15000  # under Todoist's task-description limit; the menu is clipped, never dropped

# outcomes
NO_TRIGGER = "no_trigger"
ALREADY_DONE = "already_done"
TASK_CREATED = "task_created"
TASK_FAILED = "task_failed"
LEDGER_UNAVAILABLE = "ledger_unavailable"
DRY_RUN = "dry_run"
FAILED = "failed"


def iso_week(day: str) -> str:
    """`YYYY-Www` of a `YYYY-MM-DD` day — the idempotency period."""
    y, w, _ = date.fromisoformat(day[:10]).isocalendar()
    return f"{y}-W{w:02d}"


def claim_key(macro: str, week: str) -> str:
    """The idempotency key: BOTH the macro and the ISO week (#5792 box 2)."""
    from mcp import idempotency

    return idempotency.content_key(SCOPE, macro, week)


# ── the one trigger reader ────────────────────────────────────────────────────────────────────────────────────
def _default_protein(today: str) -> tuple[Optional[int], Optional[int]]:
    from mcp.tools_plan import _protein_days_7d

    return _protein_days_7d(today)


def _default_rows(start: str, end: str) -> list[dict[str, Any]]:
    from mcp.core import query_source

    return list(query_source("macrofactor", start, end) or [])


def floor_day_counts(rows: Sequence[Mapping[str, Any]], window: Mapping[str, str]) -> dict[str, dict[str, Any]]:
    """`{fat|fibre: {missed, measured}}` over the window's MacroFactor day rows, each day graded by
    `macro_floors.evaluate_day`. `missed` is None when no day was measured (unknown, never 0 — ADR-104)."""
    from health import macro_floors

    out = {m: {"missed": 0, "measured": 0} for m in FLOOR_MACROS}
    seen: set[str] = set()
    for row in rows:
        day = str(row.get("date") or "")[:10]
        if not (window["start"] <= day <= window["end"]) or day in seen:
            continue
        seen.add(day)
        graded = macro_floors.evaluate_day(row)
        for m in FLOOR_MACROS:
            met = graded[m]["met"]
            if met is None:
                continue
            out[m]["measured"] += 1
            out[m]["missed"] += int(met is False)
    for c in out.values():
        if not c["measured"]:
            c["missed"] = None
    return out


def read_trigger(
    today: str,
    *,
    protein_reader: Optional[Callable[[str], tuple[Optional[int], Optional[int]]]] = None,
    rows_reader: Optional[Callable[[str, str], list[dict[str, Any]]]] = None,
) -> dict[str, Any]:
    """THE trigger: `{window, threshold_days, macros: {m: {state, missed, measured[, error]}}, fired}`. A failed read is
    `read_failed` with its class — never clear, never tripped."""
    from training import owner_redlines, plan_engine

    win = owner_redlines.protein_window(today, today)
    t = next(x for x in owner_redlines.engine_evaluated_tripwires() if x["id"] == "protein_floor_missed")
    macros: dict[str, dict[str, Any]] = {}
    try:
        missed, measured = (protein_reader or _default_protein)(today)
        macros["protein"] = {"state": plan_engine.floor_days_state(missed), "missed": missed, "measured": measured}
    except Exception as e:  # noqa: BLE001 — named, never clear
        macros["protein"] = {"state": "read_failed", "error": type(e).__name__}
    try:
        counts = floor_day_counts((rows_reader or _default_rows)(win["start"], win["end"]), win)
        for m, c in counts.items():
            macros[m] = {"state": plan_engine.floor_days_state(c["missed"]), **c}
    except Exception as e:  # noqa: BLE001 — named, never clear
        for m in FLOOR_MACROS:
            macros[m] = {"state": "read_failed", "error": type(e).__name__}
    fired = [m for m in MACROS if macros[m]["state"] == "tripped"]
    return {"window": win, "threshold_days": int(t["threshold_days"]), "macros": macros, "fired": fired}


# ── the menu for the intervention window ──────────────────────────────────────────────────────────────────────
def window_days(today: str) -> list[str]:
    return [shift_day_key(today, i) for i in range(1, INTERVENTION_DAYS + 1)]


def _default_plan(week_start: str) -> Optional[dict[str, Any]]:
    from mcp import panel_weekly_grade as pwg

    return pwg.read_food_plan(week_start, pwg.read_routines(week_start, shift_day_key(week_start, 6)))


def _default_build(plan: Mapping[str, Any]) -> dict[str, Any]:
    from health import weekly_menu
    from training import lab_priorities

    from mcp.config import table

    return weekly_menu.build(plan, priorities=lab_priorities.read_priorities(table))


def _week_menu(week: str, days: Sequence[str], plan_reader: Callable[..., Any], build: Callable[..., Any]) -> dict[str, Any]:
    """One ISO week's menu over its window days; a failed read or build is named (`menu_unreadable`), never raised."""
    try:
        plan = plan_reader(week)
        if plan is None:
            return {"week_start": week, "built": False, "reason_code": "no_plan", "reason": "the week's food plan is unreadable"}
        cut = dict(plan, days=[d for d in plan.get("days") or [] if isinstance(d, dict) and d.get("date") in days])
        if not cut["days"]:
            return {"week_start": week, "built": False, "reason_code": "no_plan", "reason": "the food plan carries no window day"}
        menu = dict(build(cut) or {})
        menu.setdefault("week_start", week)
        return menu
    except Exception as e:  # noqa: BLE001 — the task still lands, naming the menu it could not build
        logger.warning("[fuel_loop] menu for %s unbuildable (%s)", week, type(e).__name__)
        return {"week_start": week, "built": False, "reason_code": "menu_unreadable", "reason": f"{type(e).__name__} building the menu"}


def build_window_menu(
    today: str, *, plan_reader: Optional[Callable[..., Any]] = None, build: Optional[Callable[..., Any]] = None
) -> dict[str, Any]:
    """`weekly_menu.build` for the intervention window, one build per ISO week it touches. `unfit_days` is every window
    day the anchors cannot fit, each miss named (weekly_menu's own report); `weeks` keeps each menu whole (owner-only)."""
    from health import calorie_target

    days = window_days(today)
    weeks = sorted({calorie_target.week_monday(d) for d in days})
    menus = [_week_menu(w, days, plan_reader or _default_plan, build or _default_build) for w in weeks]
    unfit = [u for m in menus for u in m.get("unfit_days") or [] if u.get("date") in days]
    return {"days": days, "weeks": menus, "built": any(m.get("built") for m in menus), "unfit_days": unfit}


# ── the Todoist task ──────────────────────────────────────────────────────────────────────────────────────────
def _names(macros: Sequence[str]) -> str:
    return ", ".join(macros[:-1]) + (" and " if len(macros) > 1 else "") + macros[-1]


def task_args(today: str, macros: Sequence[str], trigger: Mapping[str, Any], menu: Mapping[str, Any]) -> dict[str, Any]:
    """The one task: content, the due date (tomorrow) and the menu + shop in the description (owner-only)."""
    tw = trigger["macros"]
    why = "; ".join(f"{m}: {tw[m].get('missed')} of {tw[m].get('measured')} logged days below the floor" for m in macros)
    out = [
        f"Fuel loop ({ISSUE}): the {_names(macros)} floor was missed on at least {trigger['threshold_days']} of the 7 days "
        f"{trigger['window']['start']}..{trigger['window']['end']} ({why}).",
        f"The next {INTERVENTION_DAYS} days are a kitchen intervention: shop the list below and pre-portion the protein.",
    ]
    for m in menu.get("weeks") or []:
        if not m.get("built"):
            out.append(f"Week of {m.get('week_start')}: no menu built — {m.get('reason_code')}: {m.get('reason')}")
            continue
        out.append(f"Week of {m.get('week_start')}:")
        out.extend(str(ln) for ln in m.get("lines") or [])
    if menu.get("unfit_days"):
        out.append(
            "Days the anchors cannot fit: " + "; ".join(f"{u['date']}: {', '.join(u.get('misses') or [])}" for u in menu["unfit_days"])
        )
    desc = "\n".join(out)
    if len(desc) > DESCRIPTION_MAX:
        desc = desc[: DESCRIPTION_MAX - 40] + "\n… (clipped; the full menu: weekly_menu)"
    return {
        "content": f"Kitchen intervention: shop + prep the menu ({_names(macros)} floor missed)",
        "due_date": shift_day_key(today, 1),
        "description": desc,
    }


def _default_create(args: dict[str, Any]) -> dict[str, Any]:
    from mcp.tools_todoist import create_todoist_task

    return create_todoist_task(args)


def _default_table() -> Any:
    from mcp.config import table

    return table


# ── the run ───────────────────────────────────────────────────────────────────────────────────────────────────
def _claim(table: Any, fired: Sequence[str], week: str) -> tuple[list[str], list[str], list[str]]:
    """(won, already claimed this week, degraded) — each fired macro's permanent claim on (macro, ISO week)."""
    from mcp import idempotency

    won: list[str] = []
    already: list[str] = []
    degraded: list[str] = []
    for m in fired:
        c = idempotency.claim(table, SCOPE, claim_key(m, week), payload={"macro": m, "iso_week": week, "task_id": ""})
        (degraded if c.get("degraded") else won if c["claimed"] else already).append(m)
    return won, already, degraded


def _release(table: Any, macros: Sequence[str], week: str) -> None:
    from mcp import idempotency

    for m in macros:
        idempotency.release(table, SCOPE, claim_key(m, week))


def _menu_report(menu: Mapping[str, Any]) -> dict[str, Any]:
    """The menu as the run result carries it: no food list (privacy), every unfit day with its misses named."""
    weeks = [{k: m.get(k) for k in ("week_start", "built", "reason_code", "fits_all")} for m in menu.get("weeks") or []]
    return {"built": menu.get("built"), "days": menu.get("days"), "weeks": weeks, "unfit_days": menu.get("unfit_days") or []}


def run(
    today: Optional[str] = None,
    *,
    dry_run: bool = False,
    protein_reader: Optional[Callable[..., Any]] = None,
    rows_reader: Optional[Callable[..., Any]] = None,
    plan_reader: Optional[Callable[..., Any]] = None,
    build: Optional[Callable[..., Any]] = None,
    create_task: Optional[Callable[[dict[str, Any]], dict[str, Any]]] = None,
    table: Any = None,
) -> dict[str, Any]:
    """One night's fuel loop. Every collaborator is injectable (tests); the defaults are the live readers and writer."""
    from common.pacific_time import pacific_today

    today = today or pacific_today()
    week = iso_week(today)
    trig = read_trigger(today, protein_reader=protein_reader, rows_reader=rows_reader)
    res: dict[str, Any] = {"issue": ISSUE, "today": today, "iso_week": week, "trigger": trig, "fired": trig["fired"]}
    if not trig["fired"]:
        return {**res, "outcome": NO_TRIGGER}
    if dry_run:
        return {**res, "outcome": DRY_RUN, "menu": _menu_report(build_window_menu(today, plan_reader=plan_reader, build=build))}
    table = table if table is not None else _default_table()
    won, already, degraded = _claim(table, trig["fired"], week)
    res.update(claimed=won, already_this_week=already, ledger_degraded=degraded)
    if not won:
        return {**res, "outcome": LEDGER_UNAVAILABLE if degraded else ALREADY_DONE}
    try:
        menu = build_window_menu(today, plan_reader=plan_reader, build=build)
        res["menu"] = _menu_report(menu)
        made = (create_task or _default_create)(task_args(today, won, trig, menu)) or {}
    except Exception as e:  # noqa: BLE001 — the claims go back so the next night retries; the failure is named
        _release(table, won, week)
        return {**res, "outcome": TASK_FAILED, "task": {"created": False, "error": f"{type(e).__name__}: {e}"[:200]}}
    if made.get("error") or not (made.get("task_id") or made.get("duplicate")):
        _release(table, won, week)
        return {**res, "outcome": TASK_FAILED, "task": {"created": False, "error": str(made.get("error") or "no task id returned")[:200]}}
    from mcp import idempotency

    for m in won:
        idempotency.record(table, SCOPE, claim_key(m, week), {"macro": m, "iso_week": week, "task_id": str(made.get("task_id") or "")})
    task = {"created": bool(made.get("created", True)), "task_id": made.get("task_id"), "due_date": shift_day_key(today, 1)}
    return {**res, "outcome": TASK_CREATED, "task": task}


def nightly_leg(today: Optional[str] = None) -> dict[str, Any]:
    """The fail-soft leg the nightly pre-draft calls. Never raises; never changes the pre-draft's outcome."""
    try:
        return run(today)
    except Exception as e:  # noqa: BLE001 — named on the run result
        logger.warning("[fuel_loop] nightly leg failed (%s)", type(e).__name__)
        return {"outcome": FAILED, "error": type(e).__name__}
