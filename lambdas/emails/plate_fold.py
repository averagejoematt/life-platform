"""emails/plate_fold.py — the Weekly Plate's useful, code-built part as a section of the Nutrition Review (#6176, item 2).

The Friday Plate and the Saturday Nutrition Review built the same menu from the same food log fifteen hours apart
(discovery 2026-11-21). While the outbound trial's ``PLATE_INTO_NUTRITION_REVIEW`` item is on, the Plate does not send
and the Review carries this section instead:

  * the foods he logged most often over the two weeks the Review already reads (counted by code, the Plate's
    "Greatest Hits" without the prose);
  * a pointer to the menu ahead, which the Review already prints (``weekly_menu_feed.html_block``) — not repeated.

What it deliberately leaves out: the Plate's model-written recipe riffs, wildcard and grocery list (a second model
call on the Saturday review is not part of the trial), and ANY calorie target — the owner has the target question
open (ruling 2026-11-22 section 10), so this section states none and says so in one neutral line.

PURE: no table, no clock, no AWS.
"""

from __future__ import annotations

import html as _html
from collections import Counter
from typing import Iterable, Mapping

#: Supplements are not food (the Plate's own filter, ``weekly_plate_lambda.extract_food_data``).
NOT_FOOD = ("supplement", "vitamin", "fish oil", "creatine", "magnesium")
TOP_N = 8

TARGET_NOTE = "The calorie target is under review, so this section states none."


def top_foods(day_rows: Iterable[Mapping], n: int = TOP_N) -> list[tuple[str, int]]:
    """The ``n`` most-logged food names across MacroFactor day rows (``food_log[].food_name``), most frequent first."""
    counter: Counter = Counter()
    display: dict[str, str] = {}
    for row in day_rows or ():
        for item in (row or {}).get("food_log") or []:
            name = str((item or {}).get("food_name") or "").strip()
            if not name or any(s in name.lower() for s in NOT_FOOD):
                continue
            key = name.lower()
            counter[key] += 1
            display.setdefault(key, name)
    return [(display[k], c) for k, c in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]


def html_section(foods: list[tuple[str, int]], *, menu_built: bool, accent: str = "#4cc9f0") -> str:
    """The section's HTML (the Review's dark card style). Always renders: an empty log says so."""
    esc = _html.escape
    if foods:
        items = "".join(
            f'<li style="margin:0 0 4px 0;">{esc(name)} <span style="color:#8b949e;">×{count}</span></li>' for name, count in foods
        )
        body = f'<ul style="margin:6px 0 0 0;padding-left:18px;">{items}</ul>'
    else:
        body = '<p style="margin:6px 0 0 0;">No food items were logged in the last 14 days, so there is nothing to count.</p>'
    menu = "The menu ahead is printed above." if menu_built else "No menu ahead was built this week."
    return (
        f'<div style="background:#16213e;border-radius:8px;padding:16px 20px;margin:16px 0;color:#e0e0e0;'
        f'border-left:3px solid {accent};font-size:14px;line-height:1.5;">'
        f'<div style="font-weight:700;color:{accent};">From the Weekly Plate</div>'
        f'<div style="color:#8b949e;font-size:12px;margin-top:2px;">Your most-logged foods, last 14 days. {esc(menu)} '
        f"{esc(TARGET_NOTE)}</div>"
        f"{body}</div>"
    )
