"""lambdas/emails/monthly_digest_render.py — the monthly coach's letter RENDERER,
split out of monthly_digest_lambda.py (#1654, module-size ratchet #1665).

This is the whole presentation layer of the letter and nothing else: the advisor
section-header classifier and ``build_html``, which turns the already-gathered
``(data, goals, commentary, windows)`` packet into the email's HTML. It is a pure
function of its arguments — no DynamoDB table, no SES/S3 client, no clock, no AI
call — which is exactly why it is the cohesive unit to lift out: the handler's
monkeypatchable module state (``table``/``ses``/``s3_client``/``datetime``/the
``_HAS_*`` flags) is untouched by the move, so no test patch point crosses the seam.

The two Zone-2 fallback constants move WITH the renderer because it is the only place
they are formatted for a reader; ``monthly_digest_lambda`` re-imports them (and both
functions) so every existing name on that module — ``build_html``,
``_is_section_header``, ``ZONE2_HR_LOW``, ``ZONE2_HR_HIGH`` — resolves exactly as
before. No public contract changed.

This module does NOT import monthly_digest_lambda, so there is no import cycle.
"""

from common.digest_utils import fmt

# Zone 2 HR constants — used as fallback when profile has no max_heart_rate
ZONE2_HR_LOW = 110
ZONE2_HR_HIGH = 129


def _is_section_header(line: str) -> bool:
    """True for an advisor's section header line in the board commentary.

    Derived from the SHAPE the prompt asks for — a leading emoji followed by an
    upper-case name/title — rather than from a hardcoded six-emoji tuple (#1658).
    The prompt builds its headers from whichever members the S3 board config
    assigns to `monthly_digest`, each with their own emoji, so any advisor added
    to the board (or any emoji written without the exact VS16 variation selector)
    silently lost its heading and was rendered as ordinary body prose.
    """
    line = line.strip()
    if not line:
        return False
    # The six advisors of the shipped fallback prompt stay a fast path, so this can
    # only ever match MORE lines than the old tuple did, never fewer.
    if any(line.startswith(e) for e in ("🏋️", "🥗", "😴", "🩺", "🧠", "🎯")):
        return True
    if line[0].isascii():
        return False
    letters = [c for c in line if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


def build_html(data, goals, commentary, windows):
    cur = data["cur"]
    prior = data["prior"]
    tl = data["training_load"]
    data.get("profile", {})
    month = windows["month_label"]
    prior_month = windows["prior_label"]

    def delta(cur_val, prior_val, unit="", dec=1, invert=False):
        if cur_val is None or prior_val is None:
            return ""
        diff = round(cur_val - prior_val, dec)
        if diff == 0:
            return '<span style="color:#888;font-size:11px;"> →0</span>'
        better = (diff < 0) if invert else (diff > 0)
        color = "#27ae60" if better else "#e74c3c"
        arrow = "↑" if diff > 0 else "↓"
        return f'<span style="color:{color};font-size:11px;"> {arrow}{abs(diff)}{unit}</span>'

    def row(label, value, dlt="", highlight=False):
        bg = "#fff8e7" if highlight else "#ffffff"
        return (
            f'<tr style="background:{bg}">'
            f'<td style="padding:6px 12px;color:#666;font-size:13px;">{label}</td>'
            f'<td style="padding:6px 12px;font-size:13px;font-weight:600;">{value}{dlt}</td></tr>'
        )

    def section(title, emoji, content):
        return (
            f'<div style="margin-bottom:28px;">'
            f'<h2 style="font-size:15px;font-weight:700;color:#1a1a2e;margin:0 0 8px;'
            f'border-bottom:2px solid #e8e8f0;padding-bottom:6px;">{emoji} {title}</h2>'
            f"{content}</div>"
        )

    def tbl(rows):
        return f'<table style="width:100%;border-collapse:collapse;background:#fafafa;border-radius:8px;">{rows}</table>'

    # ── Parse commentary ──
    board_html = insight_html = ""
    in_insight = False
    for line in commentary.strip().split("\n"):
        if line.startswith("💡"):
            in_insight = True
            insight_html += f'<p style="font-size:13px;font-weight:700;color:#92400e;margin:0 0 6px;">{line}</p>'
        elif in_insight:
            if line.strip():
                insight_html += f'<p style="font-size:14px;color:#78350f;line-height:1.7;margin:0;">{line}</p>'
        elif _is_section_header(line):
            board_html += f'<p style="font-size:13px;font-weight:700;color:#1a1a2e;margin:16px 0 4px;">{line}</p>'
        elif line.strip():
            board_html += f'<p style="font-size:13px;color:#333;line-height:1.6;margin:0 0 8px;">{line}</p>'

    insight_box = (
        (
            f'<div style="background:#fffbeb;border:2px solid #f59e0b;border-radius:10px;'
            f'padding:16px 20px;margin-bottom:24px;">{insight_html}</div>'
        )
        if insight_html
        else ""
    )

    board_section = section(
        "Monthly Board of Advisors",
        "📋",
        f'<div style="background:#f0f4ff;border-left:4px solid #4a6cf7;padding:16px;border-radius:0 8px 8px 0;">' f"{board_html}</div>",
    )

    # ── Monthly scorecard ──
    def sc_pill(label, cur_val, prior_val, unit="%", invert=False, thresholds=(60, 80)):
        if cur_val is None:
            col, emoji = "#888", "⚫"
        else:
            lo, hi = thresholds
            if invert:
                col, emoji = ("#27ae60", "🟢") if cur_val <= lo else ("#e67e22", "🟡") if cur_val <= hi else ("#e74c3c", "🔴")
            else:
                col, emoji = ("#e74c3c", "🔴") if cur_val < lo else ("#e67e22", "🟡") if cur_val < hi else ("#27ae60", "🟢")
        dlt = delta(cur_val, prior_val, unit, invert=invert) if prior_val is not None else ""
        return (
            f'<div style="text-align:center;padding:10px 8px;flex:1;">'
            f'<div style="font-size:20px;">{emoji}</div>'
            f'<div style="font-size:15px;font-weight:700;color:{col};">'
            f"{fmt(cur_val, unit)}</div>"
            f'<div style="font-size:10px;color:#888;">{label}</div>'
            f'<div style="font-size:10px;">{dlt}</div>'
            f"</div>"
        )

    w_c = cur.get("whoop")
    w_p = prior.get("whoop") or {}
    s_c = cur.get("sleep")
    s_p = prior.get("sleep") or {}
    st_c = cur.get("strava")
    st_p = prior.get("strava") or {}
    ch_c = cur.get("chronicling")
    ch_p = prior.get("chronicling") or {}
    wi_c = cur.get("withings")
    wi_p = prior.get("withings") or {}

    scorecard_html = (
        f'<div style="background:#f8f9fc;border-radius:10px;padding:12px 4px;margin-bottom:24px;">'
        f'<p style="text-align:center;font-size:11px;color:#888;margin:0 0 8px;'
        f'text-transform:uppercase;letter-spacing:1px;">{month} — Month at a Glance</p>'
        f'<div style="display:flex;justify-content:space-around;flex-wrap:wrap;">'
        f'{sc_pill("Recovery", w_c["recovery_avg"] if w_c else None, w_p.get("recovery_avg"))}'
        f'{sc_pill("Sleep",    s_c["score_avg"] if s_c else None, s_p.get("score_avg"), thresholds=(65, 82))}'
        f'{sc_pill("HRV ms",   w_c["hrv_avg"] if w_c else None, w_p.get("hrv_avg"), unit="ms", thresholds=(45, 60))}'
        f'{sc_pill("Habits",   ch_c["score_avg"] if ch_c else None, ch_p.get("score_avg"), thresholds=(55, 75))}'
        f'{sc_pill("RHR bpm",  w_c["rhr_avg"] if w_c else None, w_p.get("rhr_avg"), unit=" bpm", invert=True, thresholds=(55, 65))}'
        f"</div></div>"
    )

    # ── Annual goals progress bar ──
    wt_goal = goals.get("weight", {})
    pct_done = wt_goal.get("pct_complete", 0)
    year_pct = goals.get("year_pct_elapsed", 0)
    w_bar = max(0, min(100, pct_done))
    y_bar = max(0, min(100, year_pct))
    goals_html = (
        '<div style="background:#f0fdf4;border:1px solid #86efac;border-radius:8px;padding:14px 18px;margin-bottom:24px;">'
        '<p style="font-size:12px;font-weight:700;color:#166534;margin:0 0 10px;'
        'text-transform:uppercase;letter-spacing:0.5px;">2026 Annual Goals Progress</p>'
        + (
            f'<div style="margin-bottom:8px;">'
            f'<div style="display:flex;justify-content:space-between;font-size:12px;color:#15803d;margin-bottom:3px;">'
            f'<span>⚖️ Weight Goal ({wt_goal.get("current_lbs", "—")} → {wt_goal.get("goal_lbs", "—")} lbs)</span>'
            f"<span>{pct_done}% done</span></div>"
            f'<div style="background:#dcfce7;border-radius:4px;height:8px;">'
            f'<div style="background:#22c55e;width:{w_bar}%;height:8px;border-radius:4px;"></div></div>'
            f"</div>"
            if wt_goal
            else ""
        )
        + f"<div>"
        f'<div style="display:flex;justify-content:space-between;font-size:12px;color:#15803d;margin-bottom:3px;">'
        f"<span>📅 Year elapsed</span><span>{year_pct}%</span></div>"
        f'<div style="background:#dcfce7;border-radius:4px;height:8px;">'
        f'<div style="background:#86efac;width:{y_bar}%;height:8px;border-radius:4px;"></div></div>'
        f"</div>" + "</div>"
    )

    # ── Training ──
    tr_rows = ""
    if st_c:
        tr_rows += row("Total Miles", fmt(st_c.get("total_miles"), " mi"), delta(st_c.get("total_miles"), st_p.get("total_miles"), " mi"))
        tr_rows += row(
            "Total Elevation",
            f'{st_c.get("total_elevation_feet", 0):,} ft',
            delta(st_c.get("total_elevation_feet"), st_p.get("total_elevation_feet"), " ft"),
        )
        tr_rows += row("Activities", str(st_c.get("activity_count", 0)), delta(st_c.get("activity_count"), st_p.get("activity_count")))
        z2 = st_c.get("zone2_minutes", 0)
        z2pct = st_c.get("zone2_pct", 0)
        z2_range = st_c.get("zone2_hr_range", f"{ZONE2_HR_LOW}–{ZONE2_HR_HIGH}")
        z2col = "#27ae60" if z2 >= 500 else "#e67e22" if z2 >= 200 else "#e74c3c"
        tr_rows += row(f"Zone 2 ({z2_range} bpm)", f'<span style="color:{z2col};font-weight:700;">{z2} min ({z2pct}% of cardio)</span>')
    # ADR-104 (#1658): the fitness verdict is only published when something was
    # actually measured. These rows used to render outside the `if st_c:` guard, so
    # a month with no recorded activity at all still published "CTL — 42-day
    # Fitness: 0.0" and "TSB — Current Form: 0.0 (Neutral)" — a confident verdict
    # computed over nothing. The 60-day load window is wider than the 30-day arm, so
    # the guard is "the load model saw something", not "this month had activity".
    tsb = tl.get("tsb", 0)
    if st_c or any(v for v in (tl or {}).values()):
        tcol = "#27ae60" if tsb >= 0 else "#e67e22" if tsb >= -15 else "#e74c3c"
        tr_rows += row("CTL — 42-day Fitness", fmt(tl.get("ctl")), highlight=True)
        tr_rows += row(
            "TSB — Current Form",
            f'<span style="color:{tcol};">{fmt(tl.get("tsb"))} ({"Fresh" if tsb >= 5 else "Neutral" if tsb >= -5 else "Fatigued"})</span>',
        )
    if cur.get("hevy"):
        h = cur["hevy"]
        hp = prior.get("hevy") or {}
        tr_rows += row("Strength Workouts", str(h.get("workout_count", 0)), delta(h.get("workout_count"), hp.get("workout_count")))
        if h.get("total_volume_lbs"):
            tr_rows += row(
                "Strength Volume",
                f'{h["total_volume_lbs"]:,} lbs',
                delta(h.get("total_volume_lbs"), hp.get("total_volume_lbs"), " lbs", dec=0),
            )
    training_section = section("Training — 30 Days", "🏃", tbl(tr_rows))

    # ── Recovery ──
    rec_rows = ""
    if w_c:
        rec_rows += row(
            "Avg Recovery", fmt(w_c.get("recovery_avg"), "%"), delta(w_c.get("recovery_avg"), w_p.get("recovery_avg"), "%"), highlight=True
        )
        rec_rows += row("Avg HRV", fmt(w_c.get("hrv_avg"), " ms"), delta(w_c.get("hrv_avg"), w_p.get("hrv_avg"), " ms"))
        rec_rows += row("HRV Range", f'{fmt(w_c.get("hrv_min"), " ms")} – {fmt(w_c.get("hrv_max"), " ms")}')
        rec_rows += row("Avg RHR", fmt(w_c.get("rhr_avg"), " bpm"), delta(w_c.get("rhr_avg"), w_p.get("rhr_avg"), " bpm", invert=True))
    recovery_section = section("Recovery & HRV", "❤️", tbl(rec_rows)) if rec_rows else ""

    # ── Sleep ──
    sl_rows = ""
    if s_c:
        sl_rows += row(
            "Avg Sleep Score", fmt(s_c.get("score_avg"), "%"), delta(s_c.get("score_avg"), s_p.get("score_avg"), "%"), highlight=True
        )
        sl_rows += row(
            "Avg Duration",
            fmt(s_c.get("duration_avg_hrs"), " hrs"),
            delta(s_c.get("duration_avg_hrs"), s_p.get("duration_avg_hrs"), " hrs"),
        )
        sl_rows += row(
            "Avg Efficiency", fmt(s_c.get("efficiency_avg"), "%"), delta(s_c.get("efficiency_avg"), s_p.get("efficiency_avg"), "%")
        )
        if s_c.get("rem_pct"):
            sl_rows += row("REM %", fmt(s_c["rem_pct"], "%"), delta(s_c.get("rem_pct"), s_p.get("rem_pct"), "%"))
        if s_c.get("deep_pct"):
            sl_rows += row("Deep %", fmt(s_c["deep_pct"], "%"), delta(s_c.get("deep_pct"), s_p.get("deep_pct"), "%"))
        sl_rows += row("Nights Tracked", str(s_c.get("nights", 0)))
    sleep_section = section("Sleep — 30 Days", "😴", tbl(sl_rows)) if sl_rows else ""

    # ── Weight ──
    wt_rows = ""
    if wi_c:
        wt_rows += row(
            "Month-End Weight",
            fmt(wi_c.get("weight_latest"), " lbs"),
            delta(wi_c.get("weight_latest"), wi_p.get("weight_latest"), " lbs", invert=True),
            highlight=True,
        )
        wt_rows += row(
            "Monthly Avg", fmt(wi_c.get("weight_avg"), " lbs"), delta(wi_c.get("weight_avg"), wi_p.get("weight_avg"), " lbs", invert=True)
        )
        wt_rows += row("Range", f'{fmt(wi_c.get("weight_min"), " lbs")} – {fmt(wi_c.get("weight_max"), " lbs")}')
        if wi_c.get("body_fat_avg"):
            wt_rows += row(
                "Body Fat %", fmt(wi_c["body_fat_avg"], "%"), delta(wi_c.get("body_fat_avg"), wi_p.get("body_fat_avg"), "%", invert=True)
            )
        wg = goals.get("weight", {})
        if wg:
            wt_rows += row(
                "Journey Progress", f'{wg.get("lost_lbs", "—")} lbs lost · {wg.get("pct_complete", "—")}% to goal', highlight=True
            )
    weight_section = section("Weight & Body Composition", "⚖️", tbl(wt_rows)) if wt_rows else ""

    # ── Nutrition ──
    nu_rows = ""
    m_c = cur.get("macrofactor")
    m_p = prior.get("macrofactor") or {}
    if m_c:
        nu_rows += row(
            "Avg Calories",
            fmt(m_c.get("calories_avg"), " kcal"),
            delta(m_c.get("calories_avg"), m_p.get("calories_avg"), " kcal", invert=True),
            highlight=True,
        )
        # An unmeasured rate renders as absence, not as "0%" / "None%" (#1658).
        nu_rows += row("Calorie Target Hit", fmt(m_c.get("calorie_hit_rate"), "%", dec=0))
        nu_rows += row("Avg Protein", fmt(m_c.get("protein_avg_g"), "g"), delta(m_c.get("protein_avg_g"), m_p.get("protein_avg_g"), "g"))
        nu_rows += row("Protein Target Hit", fmt(m_c.get("protein_hit_rate"), "%", dec=0))
        nu_rows += row("Days Logged", str(m_c.get("days_logged", 0)))
    else:
        nu_rows = '<tr><td colspan="2" style="padding:12px;color:#999;font-size:13px;font-style:italic;">MacroFactor pending — export CSV from app</td></tr>'
    nutrition_section = section("Nutrition — 30 Days", "🥗", tbl(nu_rows))

    # ── Habits ──
    hab_rows = ""
    if ch_c:
        scol = "#27ae60" if (ch_c.get("score_avg") or 0) >= 75 else "#e67e22" if (ch_c.get("score_avg") or 0) >= 55 else "#e74c3c"
        hab_rows += row(
            "Avg P40 Score",
            f'<span style="color:{scol};font-weight:700;">{fmt(ch_c.get("score_avg"), "%")}</span>',
            delta(ch_c.get("score_avg"), ch_p.get("score_avg"), "%"),
            highlight=True,
        )
        if ch_c.get("group_avgs"):
            for g, v in sorted(ch_c["group_avgs"].items(), key=lambda x: x[1] or 0):
                gcol = "#27ae60" if (v or 0) >= 75 else "#e67e22" if (v or 0) >= 55 else "#e74c3c"
                cp = ch_p.get("group_avgs", {}).get(g)
                hab_rows += row(f"↳ {g}", f'<span style="color:{gcol};">{fmt(v, "%")}</span>', delta(v, cp, "%") if cp is not None else "")
        if ch_c.get("best_group"):
            hab_rows += row("🏆 Best Group", ch_c["best_group"])
        if ch_c.get("worst_group"):
            hab_rows += row("⚠️ Weakest Group", ch_c["worst_group"])
    else:
        hab_rows = (
            '<tr><td colspan="2" style="padding:12px;color:#999;font-size:13px;font-style:italic;">Chronicling data not available</td></tr>'
        )
    habits_section = section("Habits & P40 — 30 Days", "🎯", tbl(hab_rows))

    # ── Character Sheet ──
    cs_c = cur.get("character_sheet")
    cs_p = prior.get("character_sheet") or {}
    cs_html = ""
    if cs_c:
        level = cs_c.get("character_level", 0)
        tier = cs_c.get("character_tier", "🔨 Foundation")
        xp = cs_c.get("character_xp", 0)
        xp_d = cs_c.get("xp_delta_30d", 0)
        p_level = cs_p.get("character_level")
        xp_str = f"+{int(xp_d)} XP" if xp_d >= 0 else f"{int(xp_d)} XP"
        xp_col = "#27ae60" if xp_d >= 0 else "#e74c3c"
        lvl_delta = delta(level, p_level) if p_level is not None else ""
        cs_rows = row(
            "Character Level",
            f'<span style="font-size:15px;font-weight:700;">Level {int(level)}</span> — {tier}',
            lvl_delta,
            highlight=True,
        )
        cs_rows += row("XP This Month", f'<span style="color:{xp_col};font-weight:700;">{xp_str}</span>')
        cs_rows += row("Total XP", f"{int(xp):,}")
        _PILLAR_EMOJI = {
            "sleep": "😴",
            "movement": "🏋️",
            "nutrition": "🥗",
            "metabolic": "📊",
            "mind": "🧠",
            "relationships": "💬",
            "consistency": "🎯",
        }
        for pname in ("sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"):
            pd = (cs_c.get("pillars") or {}).get(pname)
            if not pd:
                continue
            plvl = pd.get("level", 0)
            ptier = pd.get("tier", "")
            prev = (cs_p.get("pillars") or {}).get(pname, {}).get("level") if cs_p else None
            dlt = delta(plvl, prev) if prev is not None else ""
            emoji = _PILLAR_EMOJI.get(pname, "")
            cs_rows += row(f"{emoji} {(pname or "").capitalize()}", f"Level {int(plvl)} — {ptier}", dlt)
        cs_html = section("Character Sheet — 30 Days", "🎮", tbl(cs_rows))

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>@media (prefers-color-scheme: dark){{body{{background:#1a1a1f !important;color:#e5e5e5 !important}}div[style*="background:#fff"],div[style*="background:#fafafa"],div[style*="background:#f8f9fc"],table[style*="background:#fafafa"]{{background:#22222a !important;color:#e5e5e5 !important}}div[style*="background:#fffbeb"]{{background:#3a2f15 !important}}h1,h2,h3,h4{{color:#f5f5f5 !important}}td{{color:#d5d5d5 !important}}}}</style></head>
<body style="margin:0;padding:0;background:#f4f4f8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <div style="max-width:660px;margin:32px auto;background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 2px 16px rgba(0,0,0,0.09);">

    <div style="background:linear-gradient(135deg,#0f172a 0%,#1e3a5f 100%);padding:32px;">
      <p style="color:#94a3b8;font-size:11px;margin:0 0 4px;text-transform:uppercase;letter-spacing:2px;">Monthly Coach's Letter</p>
      <h1 style="color:#fff;font-size:26px;margin:0 0 4px;">{month}</h1>
      <p style="color:#64748b;font-size:12px;margin:0;">30-day review · Deltas vs {prior_month}</p>
    </div>

    <div style="padding:28px 32px;">
      {scorecard_html}
      {goals_html}
      {insight_box}
      {board_section}
      {training_section}
      {recovery_section}
      {sleep_section}
      {weight_section}
      {nutrition_section}
      {habits_section}
      {cs_html}
    </div>

    <div style="background:#f8f8fc;padding:16px 32px;border-top:1px solid #e8e8f0;">
      <p style="color:#999;font-size:11px;margin:0;">Life Platform Monthly · All sources · AWS us-west-2</p>
      <p style="color:#bbb;font-size:9px;margin:6px 0 0;">⚕️ Personal health tracking only — not medical advice. Consult a qualified healthcare professional before making changes to your diet, exercise, or supplement regimen.</p>
    </div>
  </div>
</body>
</html>"""
