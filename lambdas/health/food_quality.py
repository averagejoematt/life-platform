"""health/food_quality.py — the weekly menu's food-quality targets, read and checked in ONE place (#5105 N11, epic #5092).

WHY THIS EXISTS

The 2026-10-18 nutrition panel review named food-quality targets (the fibre floor, fatty fish a few times a week, the
lab-driven micronutrient priorities) that lived only in review prose: nothing in the planner held them. The charter's
`nutrition.food_quality` block now carries them, and this module is the ONE reader and the ONE check:

  * `health.weekly_menu` enforces them while it fits the week (fatty fish placed on spread days, fibre held as a floor)
    and attaches `check_week` over the fitted days as the menu's `quality` report;
  * `training.food_panel` runs the SAME `check_week` over a menu-built plan (`weekly_menu.food_plan` carries the rows).

WHERE EVERY NUMBER COMES FROM (none is restated here)

  * fibre: the ONE fibre floor, read through the block's `fibre_daily.floor_path` (`nutrition.floors.fibre.floor_g`);
  * fatty fish: `fatty_fish.servings_per_week` [low, high] — a platform default pending the owner's ruling (the charter
    labels it so);
  * micronutrient priorities: the owner-only clinical `PRIORITIES#current` row (`training.lab_priorities.from_rows`,
    #5111), passed in by the caller that already holds it. Free text, no number: the report carries it beside the
    week's servings of anchors whose `nutrient_tags` it names, and enforces nothing (no ruled target exists).

The quality tags are optional columns of the owner's anchor rows (`fatty_fish: true`, `nutrient_tags: [...]`); the
fibre per serving is the row's existing `fibre_g`. The repo is PUBLIC: no food, result or marker is named here.

NEVER SILENT: a missed target is a named line in `misses`; an unreadable target is a named line in `problems` and is
not enforced (never guessed).
"""

from __future__ import annotations

import re
from typing import Any, Callable, Iterable, Mapping, Optional

POLICY_PATH = "nutrition.food_quality"
FIBRE = "fibre_daily"
FISH = "fatty_fish_per_week"
PRIORITIES = "micronutrient_priorities"
MAX_TAG_CHARS = 40

CharterReader = Callable[[str], Any]


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _default_reader(dotted: str) -> Any:
    from training.training_charter import charter_value  # noqa: PLC0415 — lazy: import-safe offline

    return charter_value(dotted)


def policy(read: Optional[CharterReader] = None) -> dict[str, Any]:
    """`{fibre_floor_g, fibre_path, fish_range, problems}` from the charter's block. A target that cannot be read is
    None with a named line in `problems` (it is then not enforced)."""
    read = read or _default_reader
    raw = read(POLICY_PATH)
    block: Mapping[str, Any] = raw if isinstance(raw, dict) else {}
    problems: list[str] = [] if block else [f"the charter's {POLICY_PATH} block is missing"]
    raw_fib = block.get("fibre_daily")
    fib: Mapping[str, Any] = raw_fib if isinstance(raw_fib, dict) else {}
    path = str(fib.get("floor_path") or "")
    floor = _num(read(path)) if path else None
    if block and (floor is None or floor <= 0):
        problems.append(f"{FIBRE}: the fibre floor is unreadable ({path or 'no floor_path'})")
        floor = None
    raw_fish = block.get("fatty_fish")
    fish: Mapping[str, Any] = raw_fish if isinstance(raw_fish, dict) else {}
    rng = fish.get("servings_per_week")
    lo, hi = (_num(rng[0]), _num(rng[1])) if isinstance(rng, list) and len(rng) == 2 else (None, None)
    ok = lo is not None and hi is not None and lo.is_integer() and hi.is_integer() and 0 <= lo <= hi
    if block and not ok:
        problems.append(f"{FISH}: servings_per_week is unreadable ({rng!r})")
    return {
        "fibre_floor_g": floor,
        "fibre_path": path or None,
        "fish_range": (int(lo), int(hi)) if ok and lo is not None and hi is not None else None,
        "problems": problems,
    }


def tags(row: Mapping[str, Any]) -> dict[str, Any]:
    """An anchor row's optional quality tags: `fatty_fish` (only a literal true counts) and `nutrient_tags` (short
    lower-cased words, at most MAX_TAG_CHARS each)."""
    raw = row.get("nutrient_tags")
    words = raw if isinstance(raw, list) else []
    clean = sorted({str(w).strip().lower()[:MAX_TAG_CHARS] for w in words if isinstance(w, str) and str(w).strip()})
    return {"fatty_fish": row.get("fatty_fish") is True, "nutrient_tags": clean}


def day_rows(days: Iterable[Mapping[str, Any]], by_id: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The fitted menu days reduced to what the quality check reads: `{date, fibre_g, fatty_fish_servings,
    tag_servings}` (+ `fixed_meals` on a day with a fixed feeding, #5103) — ids and grams only, no food label (the food
    panel's plan carries these rows)."""
    out = []
    for d in days:
        if not d.get("feedings"):
            continue
        fish = 0.0
        tagged: dict[str, float] = {}
        for f in d["feedings"]:
            for i in f.get("items") or []:
                a = by_id.get(i.get("item")) or {}
                n = _num(i.get("servings")) or 0.0
                if a.get("fatty_fish"):
                    fish += n
                for t in a.get("nutrient_tags") or []:
                    tagged[t] = tagged.get(t, 0.0) + n
        row = {
            "date": d.get("date"),
            "fibre_g": _num((d.get("totals") or {}).get("fibre_g")),
            "fatty_fish_servings": fish,
            "tag_servings": dict(sorted(tagged.items())),
        }
        fixed = [_fixed_row(f) for f in d["feedings"] if isinstance(f.get("fixed"), dict)]
        if fixed:
            row["fixed_meals"] = fixed  # #5103: the day's fixed feedings, in the day's fibre above (an unknown fibre as none)
        out.append(row)
    return out


def _fixed_row(f: Mapping[str, Any]) -> dict[str, Any]:
    """A fixed feeding (the meal-service dinner, #5103) as the quality row carries it: its id, slot and label values;
    `fibre_g` None when its label table carries no fibre."""
    fx = f["fixed"]
    return {
        "id": fx.get("id"),
        "slot": f.get("slot"),
        **{m: _num(f.get(m)) for m in ("kcal", "protein_g", "carb_g", "fat_g")},
        "fibre_g": _num(f.get("fibre_g")) if fx.get("fibre_known") else None,
    }


def _priorities(priorities: Optional[Mapping[str, Any]], rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    text = str((priorities or {}).get("text") or "").strip()
    if not text:
        return {"available": False, "line": "no lab-driven priorities row (owner-only clinical PRIORITIES#current): nothing is weighted"}
    week: dict[str, float] = {}
    for r in rows:
        for t, n in (r.get("tag_servings") or {}).items():
            week[t] = week.get(t, 0.0) + float(n)
    named = {t: round(n, 2) for t, n in sorted(week.items()) if re.search(rf"\b{re.escape(t)}\b", text, re.IGNORECASE)}
    return {
        "available": True,
        "text": text,
        "source": (priorities or {}).get("source"),
        "updated_at": (priorities or {}).get("updated_at"),
        "tagged_servings": named,
        "line": "lab-driven priorities carried; servings of the anchors tagged with a priority it names: "
        + (", ".join(f"{t} {n:g}" for t, n in named.items()) or "none in the week"),
    }


def check_week(
    rows: Iterable[Mapping[str, Any]], pol: Mapping[str, Any], priorities: Optional[Mapping[str, Any]] = None, fish_note: str = ""
) -> dict[str, Any]:
    """The week's quality targets over `day_rows`: each target met or missed, every miss a named line, every
    unreadable target a named problem. `met` is True only when every readable target is met and none is unreadable.
    `fish_note` is the caller's reason a fatty-fish count is short (e.g. no anchor tagged), appended to that miss."""
    rows = [r for r in rows if isinstance(r, dict)]
    misses: list[str] = []
    out: dict[str, Any] = {"problems": list(pol.get("problems") or [])}
    floor = pol.get("fibre_floor_g")
    if floor is not None:
        short = [r for r in rows if r.get("fibre_g") is None or float(r["fibre_g"]) < float(floor)]
        under = [f"{r['date']} {r['fibre_g']!r} g" for r in short]
        out[FIBRE] = {
            "floor_g": floor,
            "floor_path": pol.get("fibre_path"),
            "days": len(rows),
            "met": not under and bool(rows),
            "under": under,
            "under_dates": [r["date"] for r in short],
        }
        if under or not rows:
            misses.append(f"{FIBRE}: {len(under)} of {len(rows)} day(s) under the {float(floor):g} g fibre floor ({'; '.join(under[:7])})")
    rng = pol.get("fish_range")
    if rng is not None:
        n = round(sum(float(r.get("fatty_fish_servings") or 0) for r in rows), 2)
        days = [r["date"] for r in rows if (r.get("fatty_fish_servings") or 0) > 0]
        met = rng[0] <= n <= rng[1]
        out[FISH] = {"servings": n, "range": list(rng), "days": days, "met": met}
        if not met:
            side = f"under {rng[0]}" if n < rng[0] else f"over {rng[1]}"
            why = f" ({fish_note})" if fish_note and n < rng[0] else ""
            misses.append(f"{FISH}: {n:g} serving(s) {side} (target {rng[0]}-{rng[1]} a week){why}")
    out[PRIORITIES] = _priorities(priorities, rows)
    out["rows"] = rows
    out["misses"] = misses
    out["met"] = not misses and not out["problems"]
    return out
