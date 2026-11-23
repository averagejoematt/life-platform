"""emails/nutrition_week.py — which days of the Nutrition Review's week are a whole day's food log, and their averages,
the long format's seven-day table and the subject that states them (#6245). Split out of `nutrition_review_lambda` (module-size ceiling, #1665); the lambda re-exports
every name, so its callers and tests address one module.

Owner ruling 2026-11-23: a partly imported or not-yet-arrived day is never averaged in as a full day's intake. The
arrival half is `common.food_log_state.arrival` — the Morning Brief's own determination (#6240) — and the row half is
`health.nutrition_logging` (stubs #5607, partial exports #5954). Pure: no table, no clock.
"""

from __future__ import annotations

from datetime import datetime

from common import food_log_state
from common.constants import PLAN_DAILY_PROTEIN_MIN_G
from health import calorie_target, nutrient_intake, nutrition_logging

# #6245: whether a day's row is a whole day's food log. Owner ruling 2026-11-23: a partly imported or not-yet-arrived
# day is never averaged in as a full day's intake (the 2026-11-22 subject averaged an 80 kcal Saturday in as intake).
DAY_COMPLETE = "complete"
#: Part of a day: the row was exported while its day was still being logged (`partial_at_export`, #5954), or no export
#: has landed since the day ended (`food_log_state.arrival` == not_arrived, the Morning Brief's own determination).
DAY_PARTIAL = "partial"
#: A summary-only row with no diary entries (#5607): a missing day, never intake.
DAY_NO_ENTRIES = "no_entries"


def day_completeness(date_str, rec, last_arrival_day):
    """`complete`, `partial` or `no_entries` for one MacroFactor row (#6245). An unknown arrival (no stamp, failed
    read) claims nothing: the row's own flags decide."""
    if nutrition_logging.is_stub(rec):
        return DAY_NO_ENTRIES
    if nutrition_logging.is_partial_export(rec) or food_log_state.arrival(date_str, last_arrival_day) == food_log_state.NOT_ARRIVED:
        return DAY_PARTIAL
    return DAY_COMPLETE


def last_arrival_of(data):
    """The Pacific day the newest MacroFactor export landed, from the gathered data (None = unknown)."""
    return ((data or {}).get("food_freshness") or {}).get("last_arrival_day")


AVERAGES_BASIS = (
    "summary averages count complete days only (complete_days); a day whose completeness is 'partial' was exported "
    "while still being logged or its export has not arrived, and 'no_entries' is a row with no diary entries: neither "
    "is a day's intake, and missing food data is never a missed meal"
)


#: #6245: how an incomplete day is named wherever it is shown — the log's state, never a behaviour.
DAY_STATE_WORDS = {DAY_PARTIAL: "partly imported", DAY_NO_ENTRIES: "no entries"}


#: The days a review covers (today-7 .. today-1).
WEEK_DAYS = 7


def review_subject(dates, summary):
    """The subject — both formats (#6245 is a bug fix, not a format). Its averages are `compute_weekly_summary`'s, over
    COMPLETE days only, and the count is said whenever the week has fewer than seven ("(5 complete days)"); a week with
    none says so instead of stating an intake.

    #2221: a week of records that carry no totals (the partial-record case, and the shape a stalled MacroFactor feed
    produces) leaves the averages None. `int(None)` raised here, BEFORE ses.send_email — losing the entire review rather
    than degrading. ADR-104: say the number is absent, never substitute a 0."""
    n = summary.get("complete_days")
    if n == 0:
        return f"Nutrition Review - {dates['this_end']} - no complete day of food data yet"
    avg_cal = summary.get("avg_calories")
    avg_pro = summary.get("avg_protein_g")
    cal_part = f"{int(avg_cal)} kcal" if avg_cal is not None else "calories not logged"
    pro_part = f"{int(avg_pro)}g protein" if avg_pro is not None else "protein not logged"
    count = f" ({n} complete day{'s' if n != 1 else ''})" if isinstance(n, int) and n < WEEK_DAYS else ""
    return f"Nutrition Review - {dates['this_end']} - {cal_part} - {pro_part}{count}"


def compute_weekly_summary(days):
    """The week's averages — over COMPLETE days only (#6245): a partly imported, not-yet-arrived or entry-less day
    is not a day's intake. `days_logged` stays the row count; `complete_days` is what every average covers. A day
    with no `completeness` key (a caller that predates #6245) counts as complete, as it always did."""
    if not days:
        return {}
    n = len(days)
    whole = [d for d in days if d.get("completeness", DAY_COMPLETE) == DAY_COMPLETE]

    def avg_field(field):
        vals = [d.get(field) for d in whole if d.get(field) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    return {
        "days_logged": n,
        "complete_days": len(whole),
        "avg_calories": avg_field("total_calories"),
        "avg_protein_g": avg_field("total_protein_g"),
        "avg_carbs_g": avg_field("total_carbs_g"),
        "avg_fat_g": avg_field("total_fat_g"),
        "avg_fiber_g": avg_field("total_fiber_g"),
        "avg_sodium_mg": avg_field("total_sodium_mg"),
        "avg_potassium_mg": avg_field("total_potassium_mg"),
        "avg_choline_mg": avg_field("total_choline_mg"),
        "avg_vitamin_d_mcg": avg_field("total_vitamin_d_mcg"),
        "avg_vitamin_k_mcg": avg_field("total_vitamin_k_mcg"),
        "avg_omega3_total_g": avg_field("total_omega3_total_g"),
        "avg_omega6_g": avg_field("total_omega6_g"),
        "avg_micronutrient_pct": avg_field("micronutrient_avg_pct"),
    }


# ADR-104 (#2221): a total the reader never logged is missing data, not a zero.
# `or 0` used to coerce every absent total, so a day with no food log rendered a
# real row reading "0 / 0g / 0%" — and, because 0 kcal clears `<= target * 1.05`,
# the calorie cell came out GREEN: an unlogged day read as a perfect deficit day.
# An absent value now renders as an em-dash in neutral grey: no number, and no
# green/amber/red verdict the module has not earned.
_ABSENT_CELL = "&mdash;"
_ABSENT_COLOR = "#6b7280"


def _graded_cell(value, color_of, fmt):
    """(colour, text) for one table cell. Absent -> em-dash, ungraded."""
    if value is None:
        return _ABSENT_COLOR, _ABSENT_CELL
    return color_of(value), fmt(value)


def _unconverted_note(days):
    """The footnote's honest tail (#4244): which TAKEN doses the Micro column could not count,
    DERIVED from the week's rows (health.nutrient_intake's `unconverted[]`), never hand-typed —
    a hand-typed list would drift the day the stack or the registry changes."""
    names = sorted({str(u.get("name")) for d in days for u in (d.get("supplements_unconverted") or []) if u.get("name")})
    absent = sum(1 for d in days if d.get("supplements_state") == "absent")
    parts = []
    if names:
        parts.append("not counted, no cited conversion: " + ", ".join(names))
    if absent:
        parts.append(f"{absent} day{'s' if absent != 1 else ''} with no supplement record = food only")
    return f" ({'; '.join(parts)})" if parts else ""


def _micro_column_scope(days):
    """(header scope, footnote basis) for the MICRO column, DERIVED from the week's rows (#4244).
    The join counts supplements only on days with a supplement record; a week with none is food
    only, and a header saying "food + supps" over it claims a channel nothing was counted from."""
    if any(d.get("supplements_state") in ("recorded", "scheduled_miss") for d in days):
        return "food + supps", "food + supplements taken that day"
    return "food only", "logged food (no supplement record this week)"


def build_summary_table(days, profile):
    if not days:
        return ""
    cal_target = calorie_target.target_kcal() or 0  # #5095; 0 = none resolved: every intake reads amber/red, never green
    protein_target = PLAN_DAILY_PROTEIN_MIN_G

    def _cal_color(v):
        return "#10b981" if v <= cal_target * 1.05 else "#f59e0b" if v <= cal_target * 1.2 else "#ef4444"

    def _pro_color(v):
        return "#10b981" if v >= protein_target * 0.85 else "#f59e0b" if v >= protein_target * 0.7 else "#ef4444"

    def _fib_color(v):
        return "#10b981" if v >= 30 else "#f59e0b" if v >= 20 else "#ef4444"

    def _mic_color(v):
        return "#10b981" if v >= 70 else "#f59e0b" if v >= 50 else "#ef4444"

    def _plain(_v):
        return "#e0e0e0"

    def _avg(_v):
        return "#4cc9f0"

    # (formatter, colour-for-a-day-row) per numeric column, in column order.
    columns = [
        (lambda v: f"{int(v)}", _cal_color),
        (lambda v: f"{int(v)}g", _pro_color),
        (lambda v: f"{int(v)}g", _plain),
        (lambda v: f"{int(v)}g", _plain),
        (lambda v: f"{v:.0f}g", _fib_color),
        (lambda v: f"{v:.0f}%", _mic_color),
    ]
    day_keys = ["total_calories", "total_protein_g", "total_carbs_g", "total_fat_g", "total_fiber_g", "micronutrient_avg_pct"]
    avg_keys = ["avg_calories", "avg_protein_g", "avg_carbs_g", "avg_fat_g", "avg_fiber_g", "avg_micronutrient_pct"]
    weights = ["600", "600", "400", "400", "400", "400"]

    def _ungraded(_v):
        return _ABSENT_COLOR

    rows = ""
    for d in days:
        try:
            day_name = datetime.strptime(d["date"], "%Y-%m-%d").strftime("%a %m/%d")
        except Exception:
            day_name = d["date"]
        # #6245: a partial or entry-less day is printed as what it is, in grey, and never graded or averaged
        whole = d.get("completeness", DAY_COMPLETE) == DAY_COMPLETE
        if not whole:
            day_name = f"{day_name} ({DAY_STATE_WORDS.get(d.get('completeness'), 'incomplete')})"
        cell_html = ""
        for key, (fmt, color), weight in zip(day_keys, columns, weights):
            c, t = _graded_cell(d.get(key), color if whole else _ungraded, fmt)
            cell_html += f'<td style="padding:8px;color:{c};font-size:13px;text-align:center;font-weight:{weight};">{t}</td>'
        rows += f"""<tr style="border-bottom:1px solid #2a2d4a;">
            <td style="padding:8px;color:#e0e0e0;font-size:13px;">{day_name}</td>{cell_html}
        </tr>"""

    # #2221: the AVG row is now DERIVED from compute_weekly_summary — the same
    # function that feeds the subject line — instead of a parallel
    # `sum(... or 0) / len(days)`. One unlogged day used to make the subject say
    # 1800 kcal while the table underneath it said 900. Two averages of the same
    # week cannot disagree if only one of them is computed.
    summary = compute_weekly_summary(days)
    avg_html = ""
    for key, (fmt, _color) in zip(avg_keys, columns):
        c, t = _graded_cell(summary.get(key), _avg, fmt)
        avg_html += f'<td style="padding:8px;color:{c};font-size:13px;text-align:center;font-weight:700;">{t}</td>'
    rows += f"""<tr style="border-top:2px solid #4cc9f0;background:#0f1127;">
        <td style="padding:8px;color:#4cc9f0;font-size:13px;font-weight:700;">AVG</td>{avg_html}
    </tr>"""

    excluded = len(days) - (summary.get("complete_days") or 0)
    avg_basis = (
        f" | AVG = {summary.get('complete_days') or 0} complete day{'s' if summary.get('complete_days') != 1 else ''}; "
        f"{excluded} incomplete day{'s' if excluded != 1 else ''} shown, not averaged"
        if excluded
        else ""
    )
    micro_scope, micro_basis = _micro_column_scope(days)
    fiber_target = nutrient_intake.MICRONUTRIENT_TARGETS["fiber_g"]["target"]
    fiber_txt = f"{fiber_target:g}g" if fiber_target else "—"  # ADR-104: an unknown floor reads unknown, never 0
    return f"""<table style="width:100%;border-collapse:collapse;background:#16213e;border-radius:8px;overflow:hidden;margin-bottom:20px;">
        <tr style="background:#0f1127;">
            <th style="padding:8px;color:#9ca3af;font-size:11px;text-align:left;">DAY</th>
            <th style="padding:8px;color:#9ca3af;font-size:11px;text-align:center;">KCAL</th>
            <th style="padding:8px;color:#9ca3af;font-size:11px;text-align:center;">PROTEIN</th>
            <th style="padding:8px;color:#9ca3af;font-size:11px;text-align:center;">CARBS</th>
            <th style="padding:8px;color:#9ca3af;font-size:11px;text-align:center;">FAT</th>
            <th style="padding:8px;color:#9ca3af;font-size:11px;text-align:center;">FIBER</th>
            <th style="padding:8px;color:#9ca3af;font-size:11px;text-align:center;">MICRO ({micro_scope})</th>
        </tr>
        {rows}
        <tr><td colspan="7" style="padding:4px 8px;color:#6b7280;font-size:10px;">
            Targets: {cal_target or "—"} kcal | {int(protein_target)}g protein | {fiber_txt} fiber | Micro = avg sufficiency % of {micro_basis}{_unconverted_note(days)}{avg_basis}
        </td></tr>
    </table>"""
