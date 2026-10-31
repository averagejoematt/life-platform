"""weekly_menu_feed.py — the code-built weekly menu as the two food emails consume it (#5103 box 4).

The Weekly Plate (Friday evening) and the Nutrition Review (Saturday morning) used to ask the model for next week's
meals and grocery list from a calorie target alone; the numbers in those sections were the model's. Now both emails
carry the menu `health.weekly_menu` builds by code over the week's food plan — every planned day after today, through
the coming Sunday — rendered twice:

- a CODE-BUILT HTML block (`html_block`) above the model's column: the days, their targets and what the anchors land
  at, each named miss, the coming week's grocery list and the food-quality line, with no model between the fitter and
  the page; and
- a prompt payload + note (`feed`, `PROMPT_NOTE`): the model writes prose AROUND the menu — it names the feedings and
  riffs on them, and never restates or recomputes a figure the block already prints.

The food plan is read the way the MCP menu read reads it (`mcp.tools_training_notes._weekly_menu`), minus the Hevy
record: the email bundles carry no `mcp/`, so the days are typed by the committed routines' dates (`food_panel`'s named
fallback), and the block says so. Owner-only data (the anchor foods, the fixed dinner) in an owner-only email.
Never raises: an unbuildable menu is named, a failed read is `menu_unreadable`, and the emails ship either way.
"""

from __future__ import annotations

import html as _html
import logging
from typing import Any, Callable, Mapping, Optional

from common.pacific_time import shift_day_key

from health import calorie_target, weekly_menu

logger = logging.getLogger(__name__)

VERSION = "weekly-menu-feed@1.0.0"
ISSUE = "#5103"
MENU_UNREADABLE = "menu_unreadable"
CALENDAR_BASIS = "committed routines' dates (the email bundle reads no Hevy record)"

# Plain text, no braces: the Nutrition Review's fallback prompt is `.format()`ed at call time.
PROMPT_NOTE = """## THE MENU AHEAD — BUILT BY CODE, NUMBERS ARE FINAL
`menu_ahead` in the payload is the week's menu built by code from his anchor foods over the platform's own calorie
and protein targets (health.weekly_menu). Its figures are printed above your column by code; they are not yours to
restate or recompute.
- When `menu_ahead.built` is true: your meal ideas / recipes riff ON these feedings and name them; your grocery list
  STARTS from `menu_ahead.grocery` (quote those lines, then add his staples); a day's named miss may be cited as a
  priority. Never print a different kcal, protein, fat, carbohydrate or fibre figure for a menu day or feeding than
  the menu gives — say "see the menu" instead of a number.
- When `menu_ahead.built` is false: say in one line that no code-built menu exists this week and why (`reason`), then
  plan as you would have before."""


def weeks_ahead(today: str) -> list[str]:
    """The ISO Mondays whose weeks hold a planned day after `today`: this week while a day of it remains, and the
    coming week. A Sunday has only the coming week; a Monday has both (the current week from Tuesday)."""
    monday = calorie_target.week_monday(today)
    out = [monday] if shift_day_key(monday, 6) > today else []
    out.append(shift_day_key(monday, 7))
    return out


def _committed(r: Any) -> bool:
    return getattr(r, "status", None) != "archived" and (
        bool(getattr(r, "hevy_routine_id", None)) or getattr(r, "status", None) == "active"
    )


def read_plan(week_start: str, *, table: Any, today: str) -> dict[str, Any]:
    """The week's food plan as the panel grade reads it (`mcp.panel_weekly_grade.read_food_plan`), without the Hevy
    record: the committed routines' dates type the days. A raise propagates to `read_menu`, which names it."""
    from training import disruption, food_panel
    from training.routine_repo import list_by_date_range

    from health import titration

    end = shift_day_key(week_start, 6)
    planned = [str(getattr(r, "target_date", "") or "")[:10] for r in list_by_date_range(week_start, end) if _committed(r)]
    return food_panel.build_food_plan(
        week_start,
        planned_dates=planned,
        disruption_records=disruption.load_records_failsoft(table),
        titration_reader=lambda week: titration.read_record(table, week),
        case_id=f"food::{week_start}",
        block_workouts=None,
        today=today,
    )


def read_menu(week_start: str, *, table: Any, today: str, plan_reader: Optional[Callable[..., Any]] = None) -> dict[str, Any]:
    """`weekly_menu.build` over `read_plan` with the owner-only priorities row; a failed read or build is a menu that
    says `menu_unreadable`, never a raise and never a remembered menu."""
    try:
        from training import lab_priorities

        plan = (plan_reader or read_plan)(week_start, table=table, today=today)
        if plan is None:
            return {
                "built": False,
                "reason_code": weekly_menu.NO_PLAN,
                "reason": "the week's food plan is unreadable",
                "week_start": week_start,
            }
        menu = weekly_menu.build(plan, priorities=lab_priorities.read_priorities(table))
        menu.setdefault("week_start", week_start)
        return menu
    except Exception as e:  # noqa: BLE001 — named on the email; the emails ship without a menu rather than not at all
        # the detail goes to the log; the page names the class only (an exception message can carry a request's
        # internals — the handler tests showed a boto3 auth error's text landing in the email)
        logger.warning("weekly menu feed: %s unbuildable (%s: %s)", week_start, type(e).__name__, str(e)[:200])
        return {
            "built": False,
            "reason_code": MENU_UNREADABLE,
            "reason": f"{type(e).__name__} while reading the week's plan or building the menu (see the log)",
            "week_start": week_start,
        }


def menus_ahead(*, table: Any, today: str, read: Optional[Callable[[str], Mapping[str, Any]]] = None) -> dict[str, Any]:
    """The menus for every week of `weeks_ahead(today)`, each cut to the days after `today`. `read(week_start)` is
    injected in tests (default `read_menu`). The grocery list is the COMING week's (the Saturday shop); this week's
    remaining days were shopped for last Saturday and carry their feedings only."""
    read = read or (lambda week: read_menu(week, table=table, today=today))
    weeks = []
    for week in weeks_ahead(today):
        menu = dict(read(week) or {})
        days = [d for d in (menu.get("days") or []) if isinstance(d, dict) and str(d.get("date") or "") > today]
        weeks.append({"week_start": week, "menu": menu, "days": days, "shop": week > today})
    return {"version": VERSION, "issue": ISSUE, "tier": "owner_only", "today": today, "calendar_basis": CALENDAR_BASIS, "weeks": weeks}


def _day_lines(menu: Mapping[str, Any], days: list[dict[str, Any]]) -> list[str]:
    cut = dict(menu, days=days)
    out = weekly_menu.lines(cut)
    # `lines` appends the grocery and quality lines after the days; the days are the first len(days) lines
    return out[: len(days)]


def feed(ahead: Mapping[str, Any]) -> dict[str, Any]:
    """The prompt payload: `built` (any week built), one line per planned day ahead, the coming week's grocery lines,
    the quality line per built week, and each unbuilt week's reason. Templates over the code's numbers, no model."""
    days: list[str] = []
    grocery: list[str] = []
    quality: list[str] = []
    reasons: list[str] = []
    built = False
    for w in ahead.get("weeks") or []:
        menu = w.get("menu") or {}
        if not menu.get("built"):
            reasons.append(f"week of {w.get('week_start')}: {menu.get('reason_code')} — {menu.get('reason')}")
            continue
        built = True
        days.extend(_day_lines(menu, w.get("days") or []))
        if w.get("shop"):
            grocery.extend(weekly_menu.grocery_lines(menu))
        q = [ln for ln in (menu.get("lines") or []) if ln.startswith("Food quality:")]
        quality.extend(f"week of {w.get('week_start')} — {ln}" for ln in q)
    return {
        "version": VERSION,
        "built": built,
        "calendar_basis": ahead.get("calendar_basis"),
        "days": days,
        "grocery": grocery,
        "quality": quality,
        "reason": "; ".join(reasons) if reasons else None,
        "note": "numbers are final (code-built); write prose around them, never a different figure",
    }


def _esc(s: Any) -> str:
    return _html.escape(str(s), quote=False)


def html_block(fd: Mapping[str, Any], *, accent: str = "#f59e0b", title: str = "The menu ahead") -> str:
    """The code-built block the email prints above the model's column. Inline styles on the container only."""
    rows: list[str] = []
    if fd.get("built"):
        rows.extend(f"<div style='margin:0 0 6px;'>{_esc(ln)}</div>" for ln in fd.get("days") or [])
        if fd.get("grocery"):
            rows.append("<div style='margin:10px 0 4px;font-weight:600;color:#ffffff;'>The shop (coming week)</div>")
            rows.extend(f"<div style='margin:0 0 4px;'>{_esc(ln)}</div>" for ln in fd["grocery"])
        rows.extend(f"<div style='margin:8px 0 0;color:#9ca3af;'>{_esc(ln)}</div>" for ln in fd.get("quality") or [])
        if fd.get("reason"):
            rows.append(f"<div style='margin:8px 0 0;color:#9ca3af;'>Not built: {_esc(fd['reason'])}</div>")
    else:
        rows.append(f"<div>No code-built menu this week: {_esc(fd.get('reason') or 'no reason recorded')}.</div>")
    basis = _esc(fd.get("calendar_basis") or CALENDAR_BASIS)
    return (
        f'<div style="background:#16213e;border-left:3px solid {accent};border-radius:10px;padding:16px;margin-bottom:16px;'
        'font-size:13px;line-height:1.45;color:#e0e0e0;">'
        f"<div style='font-size:15px;font-weight:700;color:#ffffff;margin-bottom:8px;'>🧮 {_esc(title)}</div>"
        "<div style='color:#9ca3af;margin-bottom:8px;'>Built by code from your anchor foods over the platform's targets "
        f"(health.weekly_menu, {_esc(fd.get('version') or VERSION)}); the writer below riffs on it and prints no other figures. "
        f"Days typed by {basis}.</div>" + "".join(rows) + "</div>"
    )
