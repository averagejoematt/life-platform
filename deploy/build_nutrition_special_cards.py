"""build_nutrition_special_cards.py — the 20-day nutrition carousel (a SPECIAL, not a daily).

The first caller of `deploy/lib/special_cards.py`, and the worked example a new topic is
copied from: this file owns the DATA and the WORDS, the kit owns the drawing.

WHAT IT IS

An 8-card Instagram carousel reading the first 20 days of the cycle's MacroFactor logs —
the good, the bad and the ugly — drawn on the special-series plum ground so the set reads
apart from the dailies and the weeklies in a profile grid. It reads DynamoDB and writes
PNGs to a local folder. It stores nothing in S3, writes no DynamoDB row, and sends nothing.

THE NUMBERS

Every figure is computed here from the stored `macrofactor`, `withings` and
`COACH#nutrition_coach` records — there is no narrative layer and no model in this path.
The claims that are not plain measurements are labelled on the card itself: body
composition is Withings bioimpedance (a DXA is scheduled), the protein thresholds are the
SITE's own (`site_api_nutrition.lean_mass` publishes 2.08 g/kg lean as the target and
2.3 as the muscle-retention floor — imported as coefficients, not retyped as grams), and
the packaged-food share counts a NAMED list of products rather than a keyword rule.

NO CALORIE TARGET IS DRAWN. ADR-133's #3931 amendment refuses to publish a calorie target
whose implied deficit disagrees with the measured weight trend; a card is a publication
surface, so it reports intake and the trend it actually produced, never a prescription.

MICRONUTRIENT SUFFICIENCY IS DELIBERATELY ABSENT (owner ruling 2026-09-26). It is computed
from MacroFactor alone and cannot see the supplements ticked in Habitify — vitamin D on 17
of these 20 days, at 125 mcg against a 100 mcg target — so it reported deficiencies that
are not real. See #4244 and #4245. A number a footnote has to rescue does not go on a card.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import pathlib
import statistics as st
import sys
from collections import Counter, defaultdict
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

import boto3  # noqa: E402
from boto3.dynamodb.conditions import Key  # noqa: E402
from lib import special_cards as kit  # noqa: E402
from lib.special_cards import (  # noqa: E402
    DIM,
    NOTE_Y,
    REGION,
    TABLE,
    _day_label,
    anchored_note,
    b_closing,
    b_dots,
    b_fact,
    b_hero,
    b_lines,
    b_neutral_bars,
    b_numbered,
    b_plain_spark,
    b_quote,
    b_rule,
    b_section,
    b_spark,
    b_table,
    canvas,
    compose,
    footer,
)
from web import card_engine as ce  # noqa: E402

ENGINEERED_FOODS = {
    "Chocolate Brownie Protein Bar Gluten Free",
    "Complete Vanilla 20g Protein Greek Yogurt",
    "Big Stick Jalepeno Pepper Jack",
    "Cool Whip Lite",
    "Fruity Cereal Protein",
    "Food Line Proteins Noodles Beef",
    "Fiber Gummies",
    "Sugar Free Jello",
    "Protein Infused Water Blueberry Raspberry",
}

#: Whole fruit and vegetables, as logged. Same rule: named, not inferred.
PRODUCE_FOODS = {
    "Onion, White, Yellow or Red, Raw",
    "Red Bell Peppers, Cooked",
    "Banana, Fresh",
    "Blueberries, Fresh",
    "Blackberries, Fresh",
    "Raspberries, Fresh, Red",
    "Clementine, Fresh",
    "Pineapple, Fresh",
    "Honeycrisp Apple",
    "Spinach, Cooked From Fresh",
    "Broccoli Steamed",
    "Lettuce, Romaine or Cos",
    "Tomato Raw (Includes Cherry, Grape, Roma)",
    "Beets, Raw",
    "Corn on the Cob, Yellow, Cooked From Fresh",
    "Jalapeno Peppers, Cooked From Fresh",
    "Garlic, Fresh",
    "Ginger Root, Raw",
    "Salads Mixed Baby Greens",
    "Pickled Red Onions",
}

#: The protein thresholds are the SITE's own, not a second method invented here:
#: `site_api_nutrition.lean_mass` publishes `target_g_per_kg_lean` 2.08 and
#: `floor_g_per_kg_lean` 2.3 (Helms, muscle retention on a cut) against Withings lean
#: mass. Computed here from the same lean-mass figure so the card and the door agree.
PROTEIN_TARGET_PER_KG_LEAN = 2.08
PROTEIN_FLOOR_PER_KG_LEAN = 2.3

#: The nutrition coach's own words, read from the stored COACH# outputs — never generated
#: here. A card that quotes the staff has to quote what the staff actually said.
COACH_ID = "nutrition_coach"


#: Day 1 of the cycle. Imported rather than typed; the fallback keeps the script runnable
#: outside the repo's import path.
try:
    from common.constants import EXPERIMENT_START_DATE
except Exception:  # noqa: BLE001
    EXPERIMENT_START_DATE = "2026-09-06"

#: The card family's own serial, drawn top-left on every frame of the set.
TITLE = "NUTRITION"
SERIES_LABEL = "DAYS 1-20"


# ── data ─────────────────────────────────────────────────────────────────────
def _f(row, key, default=0.0):
    v = row.get(key)
    return float(v) if v is not None else default


def load(table, start: str, end: str) -> dict[str, Any]:
    """Every number the cards draw, computed once from the stored partitions."""

    def q(source):
        return sorted(
            table.query(
                KeyConditionExpression=Key("pk").eq(f"USER#matthew#SOURCE#{source}") & Key("sk").between(f"DATE#{start}", f"DATE#{end}")
            ).get("Items", []),
            key=lambda r: r["sk"],
        )

    days = q("macrofactor")
    weigh = q("withings")

    kcal = [_f(r, "total_calories_kcal") for r in days]
    pro = [_f(r, "total_protein_g") for r in days]
    fib = [_f(r, "total_fiber_g") for r in days]
    mic = [_f(r, "micronutrient_avg_pct") for r in days]
    sod = [_f(r, "total_sodium_mg") for r in days]

    suf: dict[str, list[float]] = defaultdict(list)
    for r in days:
        for k, v in (r.get("micronutrient_sufficiency") or {}).items():
            suf[k].append(float(v.get("pct", 0)))

    # Foods are counted in DAYS PRESENT, not entries: three jello cups in one evening is
    # one day of jello, and an entry count would quietly triple it.
    day_presence: Counter = Counter()
    protein_by_food: dict[str, float] = defaultdict(float)
    entries = 0
    by_hour = {"morning": [0.0, 0.0], "midday": [0.0, 0.0], "evening": [0.0, 0.0]}
    for r in days:
        log = r.get("food_log") or []
        entries += len(log)
        for name in {(e.get("food_name") or "").strip() for e in log} - {""}:
            day_presence[name] += 1
        for e in log:
            name = (e.get("food_name") or "").strip()
            p, c = float(e.get("protein_g") or 0), float(e.get("calories_kcal") or 0)
            if name:
                protein_by_food[name] += p
            try:
                hour = int(str(e.get("time") or "").split(":")[0])
            except ValueError:
                continue
            slot = "morning" if hour < 11 else ("midday" if hour < 16 else "evening")
            by_hour[slot][0] += p
            by_hour[slot][1] += c

    lbs = [(r["sk"][5:], float(r["weight_lbs"])) for r in weigh if r.get("weight_lbs")]
    fat = [(r["sk"][5:], float(r["fat_mass_lbs"])) for r in weigh if r.get("fat_mass_lbs")]
    lean = [(r["sk"][5:], float(r["fat_free_mass_lbs"])) for r in weigh if r.get("fat_free_mass_lbs")]

    # The weight series carries one slot per day with None where he did not weigh in, so
    # the sparkline BREAKS on a missed day instead of drawing a line through it.
    dates = [r["sk"][5:] for r in days]
    wmap = dict(lbs)
    weight_series = [wmap.get(d) for d in dates]

    total_protein = sum(v[0] for v in by_hour.values()) or 1.0
    weeks = [days[0:7], days[7:14], days[14:20]]

    # The engineered / produce split, from the named sets above.
    tk = ek = pk_ = 0.0
    tp = ep = 0.0
    eng_days = prod_days = 0
    for r in days:
        log = r.get("food_log") or []
        names = {(e.get("food_name") or "").strip() for e in log}
        eng_days += 1 if names & ENGINEERED_FOODS else 0
        prod_days += 1 if names & PRODUCE_FOODS else 0
        for e in log:
            name = (e.get("food_name") or "").strip()
            c, pr = float(e.get("calories_kcal") or 0), float(e.get("protein_g") or 0)
            tk += c
            tp += pr
            if name in ENGINEERED_FOODS:
                ek += c
                ep += pr
            elif name in PRODUCE_FOODS:
                pk_ += c

    def _week_shares(week_rows):
        wk_t = wk_e = wk_p = 0.0
        for r in week_rows:
            for e in r.get("food_log") or []:
                name = (e.get("food_name") or "").strip()
                c = float(e.get("calories_kcal") or 0)
                wk_t += c
                if name in ENGINEERED_FOODS:
                    wk_e += c
                elif name in PRODUCE_FOODS:
                    wk_p += c
        return (wk_e / wk_t * 100 if wk_t else 0.0, wk_p / wk_t * 100 if wk_t else 0.0)

    lean_kg = lean[-1][1] / 2.20462 if lean else None
    protein_target = lean_kg * PROTEIN_TARGET_PER_KG_LEAN if lean_kg else None
    protein_floor = lean_kg * PROTEIN_FLOOR_PER_KG_LEAN if lean_kg else None

    return {
        "eng_kcal_pct": ek / tk * 100 if tk else 0,
        "eng_protein_pct": ep / tp * 100 if tp else 0,
        "eng_days": eng_days,
        "prod_kcal_pct": pk_ / tk * 100 if tk else 0,
        "prod_days": prod_days,
        "eng_vs_produce": ek / pk_ if pk_ else None,
        "lean_kg": lean_kg,
        "protein_target": protein_target,
        "protein_floor": protein_floor,
        "protein_short": (protein_target - st.mean(pro)) if protein_target else None,
        "n_days": len(days),
        "dates": dates,
        "kcal": kcal,
        "kcal_mean": st.mean(kcal),
        "kcal_sd": st.pstdev(kcal),
        "kcal_min": min(kcal),
        "kcal_max": max(kcal),
        "kcal_cv": st.pstdev(kcal) / st.mean(kcal) * 100,
        "pro_mean": st.mean(pro),
        "pro_sd": st.pstdev(pro),
        "fib_mean": st.mean(fib),
        "fib_min": min(fib),
        "fib_max": max(fib),
        "fib_under20": sum(1 for x in fib if x < 20),
        "fib_over38": sum(1 for x in fib if x >= 38),
        "mic_mean": st.mean(mic),
        "sod_mean": st.mean(sod),
        "sod_over4000": sum(1 for x in sod if x > 4000),
        "sufficiency": {k: (st.mean(v), len(v)) for k, v in suf.items()},
        "dist100": sum(1 for r in days if _f(r, "protein_distribution_score") == 100),
        "single_meal_days": sum(1 for r in days if _f(r, "total_meals") <= 1),
        "entries": entries,
        "distinct_foods": len(day_presence),
        # Ties are broken by NAME, not by insertion order. `Counter.most_common` keeps the
        # order it first saw a key, which here comes from iterating a per-day set — so two
        # foods on 10 days each swapped places between two runs over identical data, and
        # the card changed without the data changing. A generator whose output depends on
        # the process that ran it cannot be re-rendered or checked.
        "top_foods": sorted(day_presence.items(), key=lambda kv: (-kv[1], kv[0]))[:5],
        "top_protein": sorted(protein_by_food.items(), key=lambda kv: (-kv[1], kv[0]))[:3],
        "protein_share": {k: v[0] / total_protein * 100 for k, v in by_hour.items()},
        "weight_series": weight_series,
        "weigh_ins": len(lbs),
        "weight_first": lbs[0][1] if lbs else None,
        "weight_last": lbs[-1][1] if lbs else None,
        "fat_delta": (fat[-1][1] - fat[0][1]) if len(fat) >= 2 else None,
        "lean_delta": (lean[-1][1] - lean[0][1]) if len(lean) >= 2 else None,
        "weeks": [
            {
                "label": lab,
                "n": len(w),
                "kcal": st.mean([_f(r, "total_calories_kcal") for r in w]),
                "pro": st.mean([_f(r, "total_protein_g") for r in w]),
                "fib": st.mean([_f(r, "total_fiber_g") for r in w]),
                "mic": st.mean([_f(r, "micronutrient_avg_pct") for r in w]),
                "packaged": _week_shares(w)[0],
            }
            for lab, w in zip(("WEEK 1", "WEEK 2", "WEEK 3"), weeks)
            if w
        ],
    }


def coach_lines(table, start: str, end: str) -> dict[str, Any]:
    """The nutrition coach's stored lines across the window, and what it kept returning to.

    Read through `recap_data.coach_line`, which is the daily card's own path: the line has
    already passed `audience_guard` at write time, and every quote carries the OUTPUT#
    record it came from. Nothing is generated here — a card that says "the coach said" and
    then writes the sentence itself is the exact failure ADR-104's grounding gate exists
    to stop.
    """
    from content import recap_data

    d0, d1 = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    found: list[tuple[str, str, str]] = []
    for i in range((d1 - d0).days + 1):
        day = (d0 + dt.timedelta(days=i)).isoformat()
        line, src, status = recap_data.coach_line(table, day, "", coach_order=[COACH_ID])
        if status == "ok" and line:
            found.append((day, line, src))

    theme = [f for f in found if "protein" in f[1].lower() or "dinner" in f[1].lower() or "46g" in f[1]]
    # Three quotes, spread across the window rather than clustered, deduped on their
    # opening words — the coach repeats its own phrasing and three near-identical
    # sentences would read as one sentence printed three times.
    picked: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for day, line, src in theme:
        key = " ".join(line.lower().split()[:4])
        if key in seen:
            continue
        seen.add(key)
        picked.append((day, line, src))
    if len(picked) > 3:
        picked = [picked[0], picked[len(picked) // 2], picked[-1]]
    return {"days_with_a_line": len(found), "days_on_theme": len(theme), "quotes": picked}


def _short(name: str, n: int = 26) -> str:
    """A food-database name, shortened for a card. MacroFactor's names are catalogue rows."""
    name = name.split(",")[0].strip()
    swap = {
        "Chocolate Brownie Protein Bar Gluten Free": "Protein bar",
        "Complete Vanilla 20g Protein Greek Yogurt": "Protein greek yogurt",
        "Chicken Breast Grilled Boneless Skinless": "Grilled chicken breast",
        "Beef Ground 90% Lean 10% Fat Raw": "90/10 ground beef",
        "Rice White Cooked Without Salt": "White rice",
        "Onion": "Raw onion",
    }
    name = swap.get(name, name)
    return name if len(name) <= n else name[: n - 1].rstrip() + "…"


# ── the eight cards ──────────────────────────────────────────────────────────
SUB = "SEP 6 - SEP 25 2026  ·  MACROFACTOR"
TOTAL = 8


def _chrome(draw, i: int) -> None:
    kit.header(draw, i, TOTAL, SUB, title=TITLE, series=SERIES_LABEL)


def card_cover(d, i):
    img, draw = canvas()
    _chrome(draw, i)
    compose(
        [
            b_section(draw, "the good, the bad, the ugly", ce.TEXT),
            b_hero(draw, f"{d['kcal_mean']:,.0f}", size=150, suffix="kcal a day"),
            b_lines(draw, f"measured across {d['n_days']} days. every one of them logged.", size=28),
            b_rule(draw),
            b_fact(draw, "the good", f"{d['n_days']} of {d['n_days']} days logged · {d['pro_mean']:.0f} g protein a day"),
            b_fact(draw, "the bad", f"{d['kcal_min']:,.0f} to {d['kcal_max']:,.0f} kcal · a {d['kcal_cv']:.0f}% swing", colour=ce.AMBER),
            b_fact(draw, "the ugly", f"{d['protein_short']:.0f} g a day under my own protein target", colour=ce.AMBER),
        ],
        floor=1190,
    )
    anchored_note(draw, "swipe", "all three, with the numbers under them", y=NOTE_Y)
    footer(draw, f"{i} of {TOTAL}")
    return img


def card_good(d, i):
    img, draw = canvas()
    _chrome(draw, i)
    compose(
        [
            b_section(draw, "the good", ce.GREEN),
            b_dots(draw, d["n_days"], d["n_days"]),
            b_lines(
                draw, f"{d['n_days']} of {d['n_days']} days logged. {d['entries']} entries, {d['entries']/d['n_days']:.0f} a day.", size=26
            ),
            # `protein_distribution_score` is the share of MEALS clearing 30 g, not a statement
            # about the clock. Calling it a "spread score" here would read as a contradiction
            # of card 3's "62% after 4pm" — two true numbers that look like they disagree is
            # exactly how a reader stops believing both.
            b_fact(draw, "protein", f"{d['pro_mean']:.0f} g a day · every meal cleared 30 g on {d['dist100']} of {d['n_days']} days"),
            b_fact(
                draw, "the scale", f"{d['weight_first']:.1f} lb on day 1 · {d['weight_last']:.1f} on day {d['n_days']}", colour=ce.GREEN
            ),
            b_fact(
                draw,
                "down",
                f"{abs(d['weight_last'] - d['weight_first']):.1f} lb · {abs(d['fat_delta']):.1f} of it fat mass, {abs(d['lean_delta']):.1f} lean",
                colour=ce.GREEN,
            ),
            b_spark(draw, d["weight_series"], h=120, colour=ce.GREEN),
        ],
        floor=1180,
        max_gap=54,
        stretch_last=True,
    )
    anchored_note(draw, "n", f"{d['weigh_ins']} weigh-ins in {d['n_days']} days · bioimpedance, dxa pending", y=NOTE_Y)
    footer(draw, f"{i} of {TOTAL}")
    return img


def card_bad(d, i):
    img, draw = canvas()
    _chrome(draw, i)
    compose(
        [
            b_section(draw, "the bad", ce.AMBER),
            b_hero(draw, f"{d['kcal_min']:,.0f} – {d['kcal_max']:,.0f}", size=104, colour=ce.AMBER),
            b_lines(draw, "the range between my lowest and my highest day.", size=28),
            b_plain_spark(draw, d["kcal"], h=150),
            b_lines(draw, f"one point per day, against the {d['kcal_mean']:,.0f} average", size=20, colour=DIM),
            b_fact(draw, "day to day", f"a {d['kcal_cv']:.0f}% swing around that average", colour=ce.AMBER),
            b_fact(
                draw,
                "fiber",
                f"{d['fib_min']:.0f} g to {d['fib_max']:.0f} g · under 20 g on {d['fib_under20']} of {d['n_days']} days",
                colour=ce.AMBER,
            ),
            b_fact(
                draw,
                "when the protein lands",
                f"{d['protein_share']['evening']:.0f}% after 4pm · {d['protein_share']['morning']:.0f}% before 11am",
                colour=ce.AMBER,
            ),
        ],
        floor=1190,
        max_gap=44,
    )
    anchored_note(draw, "why", "a deficit that swings is one you cannot attribute", y=NOTE_Y)
    footer(draw, f"{i} of {TOTAL}")
    return img


def card_ugly(d, i):
    """The ugly, corrected (owner ruling 2026-09-26).

    The first draft put micronutrient sufficiency here and called a 1.5% vitamin D reading
    the worst thing in twenty days. That number is computed from MacroFactor alone, and the
    supplement channel it cannot see records vitamin D on 17 of those 20 days — #4244. The
    honest ugly is the one the platform CAN see from end to end: protein under its own
    published target every day for twenty days, with lean mass already moving.
    """
    img, draw = canvas()
    _chrome(draw, i)
    compose(
        [
            b_section(draw, "the ugly", ce.AMBER),
            b_hero(
                draw,
                f"{d['protein_short']:.0f} g",
                size=132,
                colour=ce.AMBER,
                suffix_lines=["short of target,", "every day"],
                suffix_size=32,
            ),
            b_fact(draw, "what i ate", f"{d['pro_mean']:.0f} g of protein a day across {d['n_days']} days"),
            b_fact(draw, "what the platform asks for", f"{d['protein_target']:.0f} g · 2.08 g per kg of lean mass", colour=ce.AMBER),
            b_fact(draw, "the muscle-retention floor", f"{d['protein_floor']:.0f} g · higher still, at 2.3 g per kg lean", colour=ce.AMBER),
            b_fact(draw, "and the scale agrees", f"lean mass is down {abs(d['lean_delta']):.1f} lb in {d['n_days']} days", colour=ce.AMBER),
            b_closing(draw, "you cannot out-train a protein target you miss every single day of a cut."),
        ],
        floor=1180,
        max_gap=42,
        stretch_last=True,
    )
    anchored_note(draw, "n", "lean mass by bioimpedance, not dxa · dxa at week 8", y=NOTE_Y)
    footer(draw, f"{i} of {TOTAL}")
    return img


def card_pattern(d, i):
    img, draw = canvas()
    _chrome(draw, i)
    compose(
        [
            b_section(draw, "what i actually eat", ce.TEXT),
            b_lines(draw, f"{d['distinct_foods']} different foods across {d['n_days']} days. five of them carried it.", size=26),
            b_neutral_bars(draw, [(_short(n), c) for n, c in d["top_foods"]], maximum=float(d["n_days"]), row_h=60),
            b_lines(draw, f"days present, out of {d['n_days']}", size=19, colour=DIM),
            b_rule(draw),
            b_fact(
                draw,
                "packaged protein products",
                f"{d['eng_kcal_pct']:.0f}% of my calories · on all {d['eng_days']} of {d['n_days']} days",
                colour=ce.AMBER,
            ),
            b_fact(
                draw,
                "fruit and vegetables",
                f"{d['prod_kcal_pct']:.0f}% of my calories · on {d['prod_days']} of {d['n_days']} days",
                colour=ce.AMBER,
            ),
            b_lines(
                draw,
                f"bars, jerky, jello and cool whip carried {d['eng_vs_produce']:.1f}x the calories that all the fruit and veg did.",
                size=25,
                colour=ce.AMBER,
            ),
        ],
        floor=1180,
        max_gap=34,
    )
    anchored_note(draw, "method", "a named list of products, not a computed category", y=NOTE_Y)
    footer(draw, f"{i} of {TOTAL}")
    return img


def card_coach(d, i):
    """The staff, quoted. Every line is a stored `COACH#nutrition_coach|OUTPUT#` record."""
    img, draw = canvas()
    _chrome(draw, i)
    c = d["coach"]
    quotes = c["quotes"][:3]
    blocks = [b_section(draw, "the coach has been saying it", ce.TEXT)]
    for day, line, _src in quotes:
        blocks.append(b_quote(draw, line, f"nutrition coach · {_day_label(day)}"))
    blocks.append(
        b_closing(
            draw,
            f"it raised protein or dinner on {c['days_on_theme']} of the {c['days_with_a_line']} days it had anything to say. i kept reading it and not changing it.",
            size=25,
        )
    )
    compose(blocks, floor=1180, max_gap=46, stretch_last=True)
    anchored_note(draw, "source", "stored coach records, quoted unedited", y=NOTE_Y)
    footer(draw, f"{i} of {TOTAL}")
    return img


def card_trend(d, i):
    img, draw = canvas()
    _chrome(draw, i)
    last = d["weeks"][-1]
    compose(
        [
            b_section(draw, "week over week", ce.TEXT),
            b_table(
                draw,
                # The fourth column WAS micronutrient sufficiency. It is food-only and the
                # supplement channel it cannot see covers three of its five nutrients
                # (#4244), so it is out of the deck entirely rather than printed with an
                # asterisk — a number a footnote has to rescue does not belong in a table.
                [(w["label"], f"{w['kcal']:,.0f}", f"{w['pro']:.0f} g", f"{w['fib']:.0f} g", f"{w['packaged']:.0f}%") for w in d["weeks"]],
                ("KCAL", "PROTEIN", "FIBER", "PACKAGED"),
                row_h=58,
            ),
            b_lines(draw, f"week {len(d['weeks'])} is {last['n']} days · day 21 closes it tonight.", size=22, colour=DIM),
            b_rule(draw),
            b_fact(draw, "what moved", f"protein up {last['pro'] - d['weeks'][0]['pro']:.0f} g a day since week 1", colour=ce.GREEN),
            b_fact(draw, "what did not", f"fiber is still swinging {d['fib_min']:.0f} g to {d['fib_max']:.0f} g", colour=ce.AMBER),
            b_fact(
                draw,
                "and week 2 is the tell",
                f"packaged food went {d['weeks'][0]['packaged']:.0f}% to {d['weeks'][1]['packaged']:.0f}% and back to {d['weeks'][2]['packaged']:.0f}%",
                colour=ce.AMBER,
            ),
        ],
        floor=1190,
        max_gap=52,
    )
    anchored_note(draw, "caveat", "three points is a direction, not a trend line", y=NOTE_Y)
    footer(draw, f"{i} of {TOTAL}")
    return img


def card_next(d, i):
    img, draw = canvas()
    _chrome(draw, i)
    compose(
        [
            b_section(draw, "what changes", ce.GREEN),
            b_numbered(
                draw,
                [
                    ("01", f"protein to {d['protein_target']:.0f} g. not on good days. every day."),
                    ("02", f"protein earlier. {d['protein_share']['morning']:.0f}% of it before 11am is not a distribution."),
                    ("03", "one real-food meal where a bar goes. the bar is not the problem; it is the default."),
                    ("04", f"a fiber floor, not a fiber average. {d['fib_min']:.0f} g to {d['fib_max']:.0f} g is a coin flip."),
                ],
            ),
            b_closing(
                draw,
                "and one fix to the instrument: my micronutrient score never counted the supplements i tick every day. filed, and fixed in public.",
                size=24,
                width=52,
            ),
        ],
        floor=1190,
        max_gap=86,
        stretch_last=True,
    )
    anchored_note(draw, "next", "week 4 gets graded on these four, in public", y=NOTE_Y)
    footer(draw, f"{i} of {TOTAL}")
    return img


CARDS = [card_cover, card_good, card_bad, card_ugly, card_pattern, card_coach, card_trend, card_next]


# ── caption ──────────────────────────────────────────────────────────────────
HASHTAGS = "#themeasuredlife #proofnotpromises #quantifiedself #weightlossjourney #buildinpublic #macrofactor"


def caption(d) -> str:
    c = d["coach"]
    return "\n".join(
        [
            "Three weeks of eating, logged. Here's how nutrition is actually going — the good, the bad and the ugly, "
            "every number straight out of MacroFactor.",
            "",
            f"THE GOOD: {d['n_days']} of {d['n_days']} days logged, {d['entries']} entries. {d['weight_first']:.1f} lb to "
            f"{d['weight_last']:.1f} — {abs(d['weight_last']-d['weight_first']):.1f} down in {d['n_days']} days, and by the "
            f"scale's own body-comp read {abs(d['fat_delta']):.1f} lb of that was fat.",
            "",
            f"THE BAD: I ate between {d['kcal_min']:,.0f} and {d['kcal_max']:,.0f} kcal — a {d['kcal_cv']:.0f}% swing day to day. "
            f"Fiber ran {d['fib_min']:.0f} g to {d['fib_max']:.0f} g. And {d['protein_share']['evening']:.0f}% of my protein "
            f"lands after 4pm, with {d['protein_share']['morning']:.0f}% before 11am.",
            "",
            f"THE UGLY: {d['pro_mean']:.0f} g of protein a day against my own {d['protein_target']:.0f} g target — "
            f"{d['protein_short']:.0f} g short, every day, for {d['n_days']} days. The muscle-retention floor is higher still at "
            f"{d['protein_floor']:.0f} g. Lean mass is already down {abs(d['lean_delta']):.1f} lb. And the food doing the work is "
            f"packaged: bars, jerky, jello and Cool Whip were {d['eng_kcal_pct']:.0f}% of my calories, on all "
            f"{d['eng_days']} days — {d['eng_vs_produce']:.1f}x what all the fruit and vegetables carried. Losing weight and "
            "eating well are not the same project.",
            "",
            f"My own nutrition coach raised protein or dinner on {c['days_on_theme']} of the {c['days_with_a_line']} days it had "
            "anything to say. I kept reading it and not changing it. Those quotes are on card 6, unedited.",
            "",
            "One more thing, because this is built in public: the micronutrient score on this platform is computed from "
            "MacroFactor alone, so it never counted the vitamin D, omega-3 and magnesium I tick off in Habitify every day. "
            "It was reporting deficiencies I don't have. Two issues are filed and the fix ships in public like everything else.",
            "",
            "No calorie target on these cards on purpose — the platform refuses to publish one when the model and the "
            "scale disagree. These are measurements, not a plan.",
            "",
            "averagejoematt.com",
            HASHTAGS,
        ]
    )


# ── run ──────────────────────────────────────────────────────────────────────
def readme(start: str, end: str) -> str:
    return (
        "# Nutrition special — days 1-20\n\n"
        f"{len(CARDS)} cards, posted as ONE carousel in order (card-1of{len(CARDS)} first). Caption in `caption.txt`.\n\n"
        "Drawn on the special-series plum ground so the set reads apart from the dailies and the weeklies in grid "
        f"view. Every number is computed from the stored MacroFactor and Withings partitions for {start}..{end}. "
        "The coach quotes on card 6 are stored `COACH#nutrition_coach|OUTPUT#` records, read through the same path the "
        "daily card uses — nothing on these cards is generated. Nothing here posts itself.\n\n"
        "## The named product list (card 5)\n\n"
        "There is no 'processed' flag in the data, so the packaged share counts an explicit list of products rather "
        "than a keyword rule nobody could audit:\n\n"
        + "".join(f"- {n}\n" for n in sorted(ENGINEERED_FOODS))
        + "\nFruit and vegetables, counted the same way:\n\n"
        + "".join(f"- {n}\n" for n in sorted(PRODUCE_FOODS))
        + "\n## What is NOT on these cards\n\n"
        "Micronutrient sufficiency was the original card 4 and was cut on 2026-09-26. It is computed from MacroFactor "
        "alone and cannot see the supplements ticked in Habitify (vitamin D on 17 of these 20 days), so it reported "
        "deficiencies that are not real. See issues #4244 and #4245.\n"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="~/Desktop/averagejoematt-nutrition-20d")
    ap.add_argument("--start", default=EXPERIMENT_START_DATE)
    ap.add_argument("--end", default="2026-09-25")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--audit-ground", action="store_true", help="print the ground's contrast arithmetic and exit")
    args = ap.parse_args()

    if args.audit_ground:
        for k, v in kit.audit_ground().items():
            print(f"  {k:32} {v}")
        return 0

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    d = load(table, args.start, args.end)
    d["coach"] = coach_lines(table, args.start, args.end)
    if d["n_days"] < 14:
        sys.exit(f"refusing: only {d['n_days']} logged days in {args.start}..{args.end} — not a three-week read")
    if len(d["coach"]["quotes"]) < 2:
        # The coach card cannot be drawn from two quotes it does not have, and inventing
        # one is the thing this whole path refuses to do.
        sys.exit(f"refusing: only {len(d['coach']['quotes'])} stored coach lines in {args.start}..{args.end}")

    return kit.render_pack(
        CARDS,
        d,
        out=pathlib.Path(args.out).expanduser(),
        caption_text=caption(d),
        # Food names come from a partition with category rules, so they go through the
        # gate as items rather than as prose.
        gate_items=[("pattern", n) for n, _ in d["top_foods"]] + [("pattern", n) for n, _ in d["top_protein"]],
        gate_free_text=[q[1] for q in d["coach"]["quotes"]],
        readme=readme(args.start, args.end),
        force=args.force,
        context="nutrition-special",
    )


if __name__ == "__main__":
    raise SystemExit(main())
