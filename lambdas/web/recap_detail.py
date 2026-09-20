"""recap_detail.py — card 2 of 2: trained / ate / the rest, as one split (#3741).

Split out of `recap_layouts` when the panel pass pushed that module over the 1000-line
ceiling (#1665). Same public entrypoints — `recap_layouts.detail`, `.detail_plan`,
`.detail_bands`, `.detail_caption` and the `DETAIL_*` constants all still resolve there —
so no caller changed. The chrome (canvas, serial, footer, fact rows, the fillers) stays in
`recap_layouts` and is imported here; the band drawing and the plan live here.

THE SHAPE: a real band draws only when the day has it; an empty slot takes a filler that
names the absence; two blocks make a card, one does not.
"""

from __future__ import annotations

from web import card_engine as ce, recap_charts as ch
from web.recap_layouts import (
    DIM,
    FLOOR_Y,
    W_CONTENT,
    M,
    _canvas,
    _caption_tail,
    _fact_row,
    _footer,
    _serial,
    _session_label,
    _session_line,
    _sets_word,
    cap_caption,
    draw_filler,
    pick_fillers,
    short_exercise,
)

# ── E. DETAIL — the second card: trained / ate / the rest ─────────────────────
#: A real band draws only when the day has it; an empty slot takes a filler. Two blocks
#: make a card, one does not (#3741, the owner's brief: "a dual or three part split").
DETAIL_MIN_BANDS = 2
DETAIL_SLOTS = 3
#: Exercise rows the TRAINED band may list when all three slots share the frame.
DETAIL_EXERCISE_ROWS = {3: 4, 2: 8}
#: What a filler in each slot is standing in for — drawn on the filler's header line.
DETAIL_ABSENCE_NOTES = {"trained": "no training logged", "ate": "no food logged", "rest": "no sleep or habit data"}


def detail_bands(facts) -> list[str]:
    """Which of the three bands this day can honestly draw, in frame order."""
    bands: list[str] = []
    if facts.workouts or (facts.walk_miles is not None and facts.walk_miles >= 0.5):
        bands.append("trained")
    if facts.calories is not None or facts.protein_g is not None:
        bands.append("ate")
    if any(v is not None for v in (facts.sleep_hrs, facts.recovery_pct, facts.tier0_done, facts.steps, facts.water_oz)):
        bands.append("rest")
    return bands


def _band_header(draw, label: str, *, y: int, summary: str | None = None) -> int:
    """`TRAINED` left, the band's one number right — so the three-band rhythm reads at a glance."""
    draw.text((M, y), label.upper(), fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 22))
    if summary:
        draw.text((M + W_CONTENT, y - 2), summary, fill=ce.MUTED, font=ce.font(ce.FONT_MONO, 24), anchor="ra")
    return y + 40


def _band_trained(draw, facts, *, y: int, rows: int) -> int:
    w = facts.workouts[0] if facts.workouts else None
    summary = _sets_word(w.n_sets) if w else (f"{facts.walk_miles:.1f} mi walked" if facts.walk_miles else None)
    y = _band_header(draw, "trained", y=y, summary=summary)
    if w:
        title = _session_label(w.title)
        f = ch.fit_text(draw, title, font_name=ce.FONT_DISPLAY, max_size=72, min_size=40, width=W_CONTENT)
        draw.text((M, y), title, fill=ce.TEXT, font=f)
        y += 86
        draw.text((M, y), _session_line(w), fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 26))
        y += 46
        shown = w.detail[:rows]
        f_name = ce.font(ce.FONT_MONO, 26)
        for ex in shown:
            if y > FLOOR_Y - 40:
                break
            name = short_exercise(ex.name)
            right = f"{ex.n_sets} × {ex.reps}" if ex.reps else _sets_word(ex.n_sets)
            if ex.top_weight_lb:
                right += f"  ·  {ex.top_weight_lb:,.0f} lb"
            try:
                rw = draw.textlength(right, font=f_name)
            except Exception:  # noqa: BLE001
                rw = 220
            name_w = W_CONTENT - rw - 30
            try:
                while draw.textlength(name, font=f_name) > name_w and len(name) > 6:
                    name = name[:-2].rstrip() + "…"
            except Exception:  # noqa: BLE001
                pass
            draw.text((M, y), name, fill=ce.MUTED, font=f_name)
            draw.text((M + W_CONTENT, y), right, fill=ce.TEXT, font=f_name, anchor="ra")
            y += 38
        if len(w.detail) > len(shown):
            draw.text((M, y), f"+{len(w.detail) - len(shown)} more", fill=DIM, font=ce.font(ce.FONT_MONO, 22))
            y += 36
    if facts.walk_miles is not None and facts.walk_miles >= 0.5:
        draw.text((M, y), f"walked {facts.walk_miles:.1f} mi", fill=ce.MUTED, font=ce.font(ce.FONT_MONO, 26))
        y += 38
    return y


def _band_ate(draw, facts, *, y: int) -> int:
    y = _band_header(draw, "ate", y=y, summary=f"{facts.calories:,.0f} kcal" if facts.calories is not None else None)
    if facts.calories is not None:
        hero = f"{facts.calories:,.0f}"
        hf = ce.font(ce.FONT_DISPLAY, 72)
        draw.text((M, y), hero, fill=ce.TEXT, font=hf)
        try:
            hw = draw.textlength(hero, font=hf)
        except Exception:  # noqa: BLE001
            hw = 200
        tail = "kcal" + (f"  ·  target {facts.cal_target:,.0f}" if facts.cal_target else "")
        over = facts.cal_target is not None and float(facts.calories) > float(facts.cal_target)
        draw.text((M + hw + 16, y + 36), tail, fill=ce.AMBER if over else ce.MUTED, font=ce.font(ce.FONT_MONO, 26))
        y += 92
    # The macro row: four quiet columns. Protein carries its target because protein is the
    # one macro the protocol sets a floor on; the others are what they were.
    cols = [
        ("protein", f"{facts.protein_g:.0f} g" if facts.protein_g is not None else None),
        ("carbs", f"{facts.carbs_g:.0f} g" if facts.carbs_g is not None else None),
        ("fat", f"{facts.fat_g:.0f} g" if facts.fat_g is not None else None),
        ("fiber", f"{facts.fiber_g:.0f} g" if facts.fiber_g is not None else None),
    ]
    cols = [(k, v) for k, v in cols if v]
    if cols:
        cw = W_CONTENT // 4
        for i, (label, value) in enumerate(cols):
            x = M + i * cw
            draw.text((x, y), label.upper(), fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 20))
            draw.text((x, y + 28), value, fill=ce.TEXT, font=ce.font(ce.FONT_MONO, 32))
        y += 76
    if facts.protein_g is not None and facts.protein_target_g:
        frac = float(facts.protein_g) / float(facts.protein_target_g)
        ch.draw_progress(draw, min(frac, 1.0), x=M, y=y, w=W_CONTENT, h=12, colour=ce.GREEN if frac >= 1 else ce.AMBER)
        y += 24
        draw.text(
            (M, y), f"protein {frac * 100:.0f}% of the {facts.protein_target_g:.0f} g target", fill=DIM, font=ce.font(ce.FONT_MONO, 20)
        )
        y += 34
    if facts.meals is not None:
        logged = f"{int(facts.meals)} meal{'s' if int(facts.meals) != 1 else ''}"
        if facts.snacks:
            logged += f" · {int(facts.snacks)} snack{'s' if int(facts.snacks) != 1 else ''}"
        draw.text((M, y), f"{logged} logged", fill=DIM, font=ce.font(ce.FONT_MONO, 20))
        y += 34
    return y


def _rest_tiles(facts) -> list[tuple[str, str, str | None]]:
    """(label, value, note) for the REST band, in priority order. Absent stays absent."""
    tiles: list[tuple[str, str, str | None]] = []
    if facts.sleep_hrs is not None:
        tiles.append(("sleep", f"{facts.sleep_hrs:.1f} h", f"score {facts.sleep_score:.0f}" if facts.sleep_score is not None else None))
    if facts.recovery_pct is not None:
        hrv = None
        if facts.hrv_ms is not None:
            base = getattr(facts, "hrv_30d", None)
            hrv = f"HRV {facts.hrv_ms:.0f} ms" + (f" · 30d {base:.0f}" if base else "")
        tiles.append(("recovery", f"{facts.recovery_pct:.0f}%", hrv))
    if facts.tier0_done is not None and facts.tier0_total:
        tiles.append(("habits", f"{int(facts.tier0_done)}/{int(facts.tier0_total)}", None))
    if facts.steps is not None:
        tiles.append(("steps", f"{facts.steps:,.0f}", None))
    if facts.water_oz is not None:
        tiles.append(("water", f"{facts.water_oz:.0f} oz", f"of {facts.water_target_oz:.0f}" if facts.water_target_oz else None))
    if facts.readiness is not None:
        tiles.append(("readiness", f"{facts.readiness:.0f}/100", None))
    return tiles[:6]


def _band_rest(draw, facts, *, y: int) -> int:
    summary = f"slept {facts.sleep_hrs:.1f} h" if facts.sleep_hrs is not None else None
    y = _band_header(draw, "the rest", y=y, summary=summary)
    tiles = _rest_tiles(facts)
    if tiles:
        cw = W_CONTENT // 3
        row_h = 104
        # A second row of tiles only if it clears the floor; the first three are the ones
        # that matter (sleep, recovery, habits) and the rest go to the caption.
        if y + 2 * row_h > FLOOR_Y - 20:
            tiles = tiles[:3]
        for i, (label, value, note) in enumerate(tiles):
            x = M + (i % 3) * cw
            ty = y + (i // 3) * row_h
            draw.text((x, ty), label.upper(), fill=ce.GREEN, font=ce.font(ce.FONT_MONO_BOLD, 20))
            draw.text((x, ty + 28), value, fill=ce.TEXT, font=ce.font(ce.FONT_MONO, 34))
            if note:
                # Under the value, at a size a phone can read — never a 13 px aside.
                draw.text((x, ty + 72), note, fill=DIM, font=ce.font(ce.FONT_MONO, 22))
        y += row_h * ((len(tiles) + 2) // 3) + 4
    if facts.missed_tier0:
        y = _fact_row(draw, "not checked in", " · ".join(facts.missed_tier0[:2]), y=y, colour=ce.AMBER, size=24)
    if facts.journaled:
        y = _fact_row(draw, "journal", "wrote it down", y=y, size=24)
    return y


def detail_plan(facts, weight_series=None, grade_series=None) -> list[tuple[str, str | None]]:
    """The slots card 2 will draw: (block, absence_note). Real bands first, fillers after.

    A day with all three bands has no fillers. A day missing one takes one filler in its
    place, labelled with what it replaces. A day with nothing real still gets a card if
    two fillers can draw — the arc and the road are true on a day nothing was logged —
    and the notes on both say so.
    """
    real = detail_bands(facts)
    plan: list[tuple[str, str | None]] = [(b, None) for b in real]
    missing = [b for b in ("trained", "ate", "rest") if b not in real]
    ctx = {"weight_series": weight_series or [], "grade_series": grade_series or []}
    for name, slot in zip(pick_fillers(facts, ctx, DETAIL_SLOTS - len(real)), missing):
        plan.append((name, DETAIL_ABSENCE_NOTES[slot]))
    return plan


def detail(facts, *, date_label: str, weight_series=None, grade_series=None):
    """The second card of the day. Raises when fewer than two blocks can be drawn."""
    plan = detail_plan(facts, weight_series, grade_series)
    if len(plan) < DETAIL_MIN_BANDS:
        raise ValueError(f"detail layout needs {DETAIL_MIN_BANDS} blocks; this day has {plan}")
    ctx = {"weight_series": weight_series or [], "grade_series": grade_series or []}
    img, draw = _canvas()
    y = _serial(draw, facts, date_label)
    draw.text((M + W_CONTENT, 148), "2 OF 2  ·  THE DETAIL", fill=DIM, font=ce.font(ce.FONT_MONO, 22), anchor="ra")
    rows = DETAIL_EXERCISE_ROWS.get(len(plan), 5)
    for i, (block, note) in enumerate(plan):
        if i:
            draw.rectangle([M, y, M + W_CONTENT, y + 2], fill=ce.BORDER)
            y += 30
        if block == "trained":
            y = _band_trained(draw, facts, y=y, rows=rows)
        elif block == "ate":
            y = _band_ate(draw, facts, y=y)
        elif block == "rest":
            y = _band_rest(draw, facts, y=y)
        else:
            y = draw_filler(draw, block, facts, ctx, y=y, note=note)
        y += 14
    _footer(draw)
    return img


def detail_caption(facts, *, day_label: str) -> str:
    """The words beside the second card — the same rule as the first: assembled, never generated."""
    head = " · ".join(x for x in (day_label, "the experiment", "the detail") if x)
    bits: list[str] = []
    if facts.workouts:
        w = facts.workouts[0]
        bit = f"Trained: {_session_label(w.title)}, {w.n_sets} sets"
        if w.volume_lbs and w.volume_lbs > 0:
            bit += f", {w.volume_lbs:,.0f} lb moved"
        bits.append(bit + ".")
    if facts.calories is not None:
        bit = f"Ate: {facts.calories:,.0f} kcal"
        if facts.protein_g is not None:
            bit += f", {facts.protein_g:.0f} g protein"
        bits.append(bit + ".")
    rest: list[str] = []
    if facts.sleep_hrs is not None:
        rest.append(f"slept {facts.sleep_hrs:.1f} h")
    if facts.recovery_pct is not None:
        rest.append(f"recovery {facts.recovery_pct:.0f}%")
    if facts.tier0_done is not None and facts.tier0_total:
        rest.append(f"habits {int(facts.tier0_done)}/{int(facts.tier0_total)}")
    if rest:
        bits.append((", ".join(rest) + ".").capitalize())
    return cap_caption((head + "\n" + " ".join(bits) + "\n" + _caption_tail(facts)).strip())
