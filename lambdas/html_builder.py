"""
html_builder.py — Daily Brief HTML rendering engine.

Extracted from daily_brief_lambda.py (Phase 5 monolith extraction).
Pure rendering module — no AWS dependencies. All data pre-computed by caller.

Exports:
  build_html(...)        — main entry point, returns HTML string
  hrv_trend_str(...)     — HRV trend description for scorecard
  _section_error_html()  — graceful section error placeholder
"""

import json
import math
from datetime import datetime

try:
    from digest_utils import compute_confidence
    _HAS_CONFIDENCE = True
except ImportError:
    _HAS_CONFIDENCE = False
    def compute_confidence(**kw):
        return {"level": "MEDIUM", "reason": "digest_utils unavailable", "badge_html": ""}


# ==============================================================================
# INLINE UTILITIES (tiny — avoids import dependency on daily_brief_lambda)
# ==============================================================================

def safe_float(rec, field, default=None):
    if rec and field in rec:
        try: return float(rec[field])
        except Exception: return default
    return default

def d2f(obj):
    from decimal import Decimal
    if isinstance(obj, list):    return [d2f(i) for i in obj]
    if isinstance(obj, dict):    return {k: d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return float(obj)
    return obj

def avg(vals):
    v = [x for x in vals if x is not None]
    return round(sum(v)/len(v), 1) if v else None

def clamp(val, lo=0, hi=100):
    return max(lo, min(hi, val))

def fmt_num(val):
    if val is None:
        return "—"
    return "{:,}".format(round(val))

def get_current_phase(profile, current_weight_lbs):
    phases = profile.get("weight_loss_phases", [])
    for p in phases:
        if current_weight_lbs >= p.get("end_lbs", 0):
            return p
    return phases[-1] if phases else None


# ==============================================================================
# SECTION ERROR PLACEHOLDER
# ==============================================================================

def _section_error_html(section_name, error):
    """Render a graceful error placeholder when a section crashes."""
    print("[WARN] Section " + section_name + " failed: " + str(error))
    return ('<div style="background:#fef2f2;border-left:3px solid #fca5a5;'
            'border-radius:0 8px 8px 0;padding:8px 16px;margin:12px 16px 0;">'
            '<p style="font-size:11px;color:#991b1b;margin:0;">'
            '&#9888; ' + section_name + ' section unavailable</p></div>')


# ==============================================================================
# HRV TREND
# ==============================================================================

def hrv_trend_str(hrv_7d, hrv_30d):
    if not hrv_7d or not hrv_30d or hrv_30d == 0:
        return "no trend data"
    pct = round((hrv_7d / hrv_30d - 1) * 100)
    arrow = "+" if pct >= 0 else ""
    direction = "trending up" if pct >= 2 else "stable" if pct >= -2 else "trending down"
    return str(round(hrv_7d)) + "ms 7d avg (" + arrow + str(pct) + "% vs 30d, " + direction + ")"


# ==============================================================================
# HTML BUILDER
# ==============================================================================



# ==============================================================================
# S2-T1-10: WEEKLY HABIT REVIEW — helper functions
# Sunday-only section in the Daily Brief.
# ==============================================================================

def _compute_weekly_habit_review(habit_7d_records, profile):
    """Compute weekly habit review data from 7 days of habit_scores DDB records.

    Returns a dict with per-habit completion, streak patterns, and synergy health.
    Returns None if no records.
    """
    if not habit_7d_records:
        return None

    registry = profile.get("habit_registry", {})
    sorted_recs = sorted(habit_7d_records, key=lambda x: x.get("date", ""))

    daily = []
    all_missed = {}  # habit_name -> days_missed_count

    for rec in sorted_recs:
        t0_done  = int(rec.get("tier0_done", 0))
        t0_total = int(rec.get("tier0_total", 0))
        raw_pct  = rec.get("tier0_pct")
        t0_pct   = float(raw_pct) if raw_pct is not None else (t0_done / t0_total if t0_total else 0)
        missed   = rec.get("missed_tier0") or []
        perfect  = (t0_total > 0) and (t0_done == t0_total)
        date_str = rec.get("date", rec.get("sk", "").replace("DATE#", ""))
        daily.append({
            "date":    date_str,
            "t0_done": t0_done,
            "t0_total": t0_total,
            "t0_pct":  round(t0_pct, 3),
            "perfect": perfect,
            "missed":  missed,
        })
        for h in missed:
            all_missed[h] = all_missed.get(h, 0) + 1

    days = len(daily)
    if days == 0:
        return None

    perfect_days  = sum(1 for d in daily if d["perfect"])
    avg_t0_raw    = [d["t0_pct"] for d in daily]
    avg_t0_pct    = round(sum(avg_t0_raw) / len(avg_t0_raw), 3) if avg_t0_raw else 0

    # Per T0 habit breakdown
    t0_habits = []
    for name, meta in registry.items():
        if meta.get("status") == "active" and meta.get("tier", 2) == 0:
            days_missed = all_missed.get(name, 0)
            days_done   = days - days_missed
            t0_habits.append({
                "name":       name,
                "days_done":  days_done,
                "days_total": days,
                "pct":        round(days_done / days, 3) if days else 0,
            })
    t0_habits.sort(key=lambda x: -x["pct"])  # best first

    # T1 summary
    t1_vals = [float(r["tier1_pct"]) for r in sorted_recs if r.get("tier1_pct") is not None]
    avg_t1_pct = round(sum(t1_vals) / len(t1_vals), 3) if t1_vals else None

    # Synergy groups
    synergy_totals = {}
    for rec in sorted_recs:
        sg = rec.get("synergy_groups") or {}
        for group, pct in sg.items():
            synergy_totals.setdefault(group, []).append(float(pct))
    synergy_summary = {g: round(sum(v) / len(v), 2) for g, v in synergy_totals.items()}

    return {
        "days":        days,
        "daily":       daily,
        "perfect_days": perfect_days,
        "avg_t0_pct":  avg_t0_pct,
        "avg_t1_pct":  avg_t1_pct,
        "t0_habits":   t0_habits,
        "synergy":     synergy_summary,
    }


def _render_weekly_habit_review(whr):
    """Render the Sunday Weekly Habit Review section as an HTML string.

    Returns empty string if whr is None.
    """
    if not whr:
        return ""

    days        = whr.get("days", 7)
    perfect     = whr.get("perfect_days", 0)
    avg_t0      = whr.get("avg_t0_pct", 0)
    t0_habits   = whr.get("t0_habits", [])
    avg_t1      = whr.get("avg_t1_pct")
    synergy     = whr.get("synergy", {})
    daily       = whr.get("daily", [])

    # Overall completion colour
    t0_pct_int = int(avg_t0 * 100)
    if t0_pct_int >= 85:
        overall_col = "#22c55e"
        overall_label = "Strong week"
    elif t0_pct_int >= 65:
        overall_col = "#f59e0b"
        overall_label = "Mixed week"
    else:
        overall_col = "#ef4444"
        overall_label = "Needs attention"

    perfect_pct = int(perfect / days * 100) if days else 0

    # ── Daily mini-bars (Mon-Sun) ────────────────────────────────────────────
    bar_cells = ""
    DAY_ABBR = ["M", "T", "W", "T", "F", "S", "S"]
    for i, d in enumerate(daily):
        pct_bar = max(8, int(d["t0_pct"] * 60))
        bar_col = "#22c55e" if d["t0_pct"] >= 0.85 else "#f59e0b" if d["t0_pct"] >= 0.65 else "#ef4444"
        done_str = str(d["t0_done"]) + "/" + str(d["t0_total"])
        day_abbr = DAY_ABBR[i % 7]
        try:
            from datetime import datetime as _dt
            day_abbr = _dt.strptime(d["date"], "%Y-%m-%d").strftime("%a")[0]
        except Exception:
            pass
        crown = " &#9733;" if d["perfect"] else ""
        bar_cells += (
            '<td style="text-align:center;padding:0 2px;vertical-align:bottom;">'
            + '<div style="font-size:9px;color:' + bar_col + ';font-weight:700;margin-bottom:2px;">'
            + done_str + crown + '</div>'
            + '<div style="height:' + str(pct_bar) + 'px;background:' + bar_col
            + ';border-radius:3px 3px 0 0;min-width:24px;"></div>'
            + '<div style="font-size:8px;color:#94a3b8;margin-top:3px;">' + day_abbr + '</div>'
            + '</td>'
        )

    bars_html = (
        '<table style="width:100%;border-collapse:collapse;margin:12px 0 4px;">'
        '<tr style="vertical-align:bottom;">' + bar_cells + '</tr></table>'
    )

    # ── Per-habit breakdown rows ─────────────────────────────────────────────
    habit_rows = ""
    for h in t0_habits:
        p = int(h["pct"] * 100)
        col = "#22c55e" if p >= 85 else "#f59e0b" if p >= 65 else "#ef4444"
        bar_w = max(4, p)
        flag = " &#9888;" if p <= 50 else ""
        short_name = h["name"][:32] + ("…" if len(h["name"]) > 32 else "")
        habit_rows += (
            '<tr>'
            '<td style="padding:5px 8px 5px 12px;font-size:12px;color:#e2e8f0;width:55%;">'
            + short_name + flag + '</td>'
            '<td style="padding:5px 8px;width:45%;">'
            '<div style="display:flex;align-items:center;gap:6px;">'
            '<div style="flex:1;background:rgba(255,255,255,0.08);border-radius:3px;height:6px;">'
            '<div style="width:' + str(bar_w) + '%;height:6px;background:' + col
            + ';border-radius:3px;"></div></div>'
            '<span style="font-size:11px;font-weight:700;color:' + col + ';min-width:36px;text-align:right;">'
            + str(h["days_done"]) + '/' + str(h["days_total"]) + '</span>'
            '</div></td>'
            '</tr>'
        )

    # ── Synergy groups ───────────────────────────────────────────────────────
    synergy_html = ""
    if synergy:
        chips = ""
        for group, pct in sorted(synergy.items(), key=lambda x: -x[1]):
            p_int = int(pct * 100)
            col = "#22c55e" if p_int >= 75 else "#f59e0b" if p_int >= 50 else "#ef4444"
            chips += (
                '<span style="display:inline-block;background:rgba(255,255,255,0.06);'
                'border:1px solid ' + col + '40;border-radius:12px;'
                'padding:3px 10px;font-size:10px;color:' + col + ';margin:2px 3px 2px 0;font-weight:600;">'
                + group + ' ' + str(p_int) + '%</span>'
            )
        synergy_html = (
            '<div style="margin-top:8px;padding-top:8px;border-top:1px solid rgba(255,255,255,0.08);">'
            '<p style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:1px;margin:0 0 5px;">Synergy Stacks</p>'
            + chips + '</div>'
        )

    # ── T1 line ──────────────────────────────────────────────────────────────
    t1_html = ""
    if avg_t1 is not None:
        t1_pct_int = int(avg_t1 * 100)
        t1_col = "#22c55e" if t1_pct_int >= 75 else "#f59e0b" if t1_pct_int >= 50 else "#94a3b8"
        t1_html = (
            '<p style="font-size:11px;color:#64748b;margin:6px 0 0;">'
            'Tier 1 avg: <span style="color:' + t1_col + ';font-weight:700;">'
            + str(t1_pct_int) + '%</span></p>'
        )

    html = (
        '<!-- S2-T1-10: Weekly Habit Review (Sunday only) -->'
        '<div style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.1);'
        'border-radius:12px;padding:16px 20px;margin:0 0 20px;">'

        # Header row
        '<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:4px;">'
        '<div>'
        '<p style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:1.5px;margin:0 0 2px;">&#128197; Weekly Habit Review</p>'
        '<p style="font-size:24px;font-weight:800;color:' + overall_col + ';margin:0;line-height:1.1;">'
        + str(t0_pct_int) + '<span style="font-size:14px;">%</span> T0</p>'
        '<p style="font-size:11px;color:' + overall_col + ';margin:2px 0 0;">' + overall_label + '</p>'
        '</div>'
        '<div style="text-align:right;">'
        '<p style="font-size:10px;color:#64748b;margin:0 0 2px;">' + str(days) + '-day window</p>'
        '<p style="font-size:20px;font-weight:700;color:#e2e8f0;margin:0;">' + str(perfect) + '/' + str(days) + '</p>'
        '<p style="font-size:10px;color:#94a3b8;margin:2px 0 0;">perfect days (' + str(perfect_pct) + '%)</p>'
        '</div>'
        '</div>'

        # Daily bars
        + bars_html

        # Habit table
        + '<table style="width:100%;border-collapse:collapse;margin-top:8px;">'
        + '<tr><td colspan="2" style="padding:0 0 4px 12px;font-size:10px;color:#64748b;'
        + 'text-transform:uppercase;letter-spacing:1px;">T0 Habits</td></tr>'
        + habit_rows
        + '</table>'

        # T1 line
        + t1_html

        # Synergy
        + synergy_html

        + '</div>'
    )

    return html

def build_html(data, profile, day_grade_score, grade, component_scores, component_details,
               readiness_score, readiness_colour, tldr_guidance, bod_insight,
               training_nutrition, journal_coach_text, mvp_streak, full_streak, vice_streaks=None,
               character_sheet=None, brief_mode="standard", engagement_score=None,
               triggered_rewards=None, protocol_recs=None,
               compute_stale=False, compute_age_msg="",
               weekly_habit_review=None):
    """Build the full daily brief HTML email.

    triggered_rewards and protocol_recs are pre-computed by lambda_handler
    (extracted from _evaluate_rewards_brief / _get_protocol_recs_brief in output_writers.py).
    """

    date_str = data["date"]
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        day_label = dt.strftime("%A, %b %-d")
    except Exception:
        day_label = date_str

    # Defaults
    if triggered_rewards is None:
        triggered_rewards = []
    if protocol_recs is None:
        protocol_recs = []

    # Adaptive mode banner colour
    banner_color = "#1a1a2e"
    if brief_mode == "flourishing":
        banner_color = "#064e3b"
    elif brief_mode == "struggling":
        banner_color = "#1e1b4b"

    # --- Header ---
    html = ('<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Morning Brief — ' + day_label + '</title></head>'
            '<body style="margin:0;padding:0;background:#0f0f23;font-family:\'SF Pro Display\','
            '\'Segoe UI\',sans-serif;">'
            '<div style="max-width:640px;margin:0 auto;background:#1a1a2e;">')

    # --- Adaptive mode banner (if not standard) ---
    try:
        if brief_mode == "flourishing":
            html += ('<div style="background:linear-gradient(135deg,#065f46,#059669);'
                     'padding:8px 24px;text-align:center;">'
                     '<p style="color:#d1fae5;font-size:11px;margin:0;font-weight:600;">'
                     '&#127775; FLOURISHING MODE — You\'re on a roll. Keep the momentum.</p></div>')
        elif brief_mode == "struggling":
            html += ('<div style="background:linear-gradient(135deg,#3730a3,#4f46e5);'
                     'padding:8px 24px;text-align:center;">'
                     '<p style="color:#e0e7ff;font-size:11px;margin:0;font-weight:600;">'
                     '&#128147; SUPPORT MODE — Rough stretch. Small wins count. You\'ve got this.</p></div>')
    except Exception as _e:
        html += _section_error_html("Adaptive Mode Banner", _e)

    # --- Dark gradient header ---
    html += ('<div style="background:linear-gradient(135deg,' + banner_color + ',#16213e,#0f3460);'
             'padding:32px 24px 24px;border-bottom:1px solid #2d2d5e;">'
             '<div style="display:flex;justify-content:space-between;align-items:flex-start;">'
             '<div>')

    grade_color = {"A": "#22c55e", "B": "#84cc16", "C": "#f59e0b",
                   "D": "#f97316", "F": "#ef4444"}.get(grade, "#94a3b8")

    html += ('<p style="color:#94a3b8;font-size:12px;margin:0 0 4px;">MORNING BRIEF</p>'
             '<h1 style="color:#ffffff;font-size:28px;font-weight:700;margin:0 0 4px;">'
             + day_label + '</h1>')

    # TL;DR line
    tldr_text = (tldr_guidance or {}).get("tldr", "")
    if tldr_text:
        html += ('<p style="color:#cbd5e1;font-size:13px;margin:4px 0 0;font-style:italic;">'
                 + tldr_text + '</p>')

    html += '</div><div style="text-align:right;">'

    if day_grade_score is not None:
        html += ('<div style="background:rgba(255,255,255,0.08);border-radius:12px;'
                 'padding:12px 16px;text-align:center;">'
                 '<p style="color:#94a3b8;font-size:10px;margin:0 0 2px;font-weight:600;">DAY GRADE</p>'
                 '<p style="color:' + grade_color + ';font-size:36px;font-weight:800;margin:0;line-height:1;">'
                 + grade + '</p>'
                 '<p style="color:#94a3b8;font-size:11px;margin:2px 0 0;">' + str(day_grade_score) + '/100</p>'
                 '</div>')

    html += '</div></div>'

    # Travel banner
    travel = data.get("travel_active")
    if travel:
        dest = travel.get("destination", "Unknown")
        country = travel.get("country", "")
        tz = travel.get("timezone", "")
        tz_offset = travel.get("tz_offset", 0)
        direction = travel.get("direction", "")
        tz_str = (" (" + tz + (", UTC" + ("+" if tz_offset >= 0 else "") + str(int(tz_offset)) if tz else "") + ")") if tz else ""
        jet_note = ""
        if abs(tz_offset) >= 5:
            jet_note = (" &#128992; Jet lag protocol: " +
                        ("Morning sunlight ASAP, avoid melatonin until day 3." if direction == "east"
                         else "Bright light in evening, consider 0.5mg melatonin at destination bedtime."))
        loc_label = dest + (", " + country if country else "")
        html += ('<div style="background:rgba(99,102,241,0.2);border-left:3px solid #6366f1;'
                 'padding:8px 16px;margin-top:12px;border-radius:0 6px 6px 0;">'
                 '<p style="color:#a5b4fc;font-size:11px;margin:0;">'
                 '&#9992; TRAVELING: ' + loc_label + tz_str + jet_note + '</p></div>')

    try:
        pass  # travel already handled above
    except Exception as _e:
        html += _section_error_html("Travel", _e)

    html += '</div>'  # end header

    # --- Character Sheet Section ---
    try:
        if character_sheet:
            cs_level = character_sheet.get("character_level", 1)
            cs_tier = character_sheet.get("character_tier", "Foundation")
            cs_tier_emoji = character_sheet.get("character_tier_emoji", "🌱")
            cs_xp = character_sheet.get("character_xp", 0)
            cs_events = character_sheet.get("level_events", [])
            cs_effects = character_sheet.get("active_effects", [])

            tier_colors = {
                "Foundation": "#78716c", "Momentum": "#2563eb",
                "Discipline": "#7c3aed", "Mastery": "#d97706", "Elite": "#dc2626"
            }
            tier_bg = {"Foundation": "#1c1917", "Momentum": "#1e3a5f",
                       "Discipline": "#2e1065", "Mastery": "#451a03", "Elite": "#450a0a"}
            tc = tier_colors.get(cs_tier, "#78716c")
            tb = tier_bg.get(cs_tier, "#1c1917")

            html += ('<div style="background:' + tb + ';border-left:3px solid ' + tc + ';'
                     'padding:16px 24px;border-bottom:1px solid #2d2d5e;">'
                     '<!-- S:character_sheet -->'
                     '<div style="display:flex;justify-content:space-between;align-items:center;">'
                     '<div>'
                     '<p style="color:' + tc + ';font-size:10px;margin:0 0 2px;font-weight:700;letter-spacing:1px;">CHARACTER SHEET</p>'
                     '<p style="color:#e2e8f0;font-size:18px;font-weight:700;margin:0;">'
                     + cs_tier_emoji + ' Level ' + str(cs_level) + ' — ' + cs_tier + '</p>')

            # XP bar
            level_within_tier = ((cs_level - 1) % 20) + 1
            xp_pct = round((level_within_tier / 20) * 100)
            html += ('<div style="margin-top:6px;background:#374151;border-radius:4px;height:6px;width:200px;">'
                     '<div style="background:' + tc + ';border-radius:4px;height:6px;width:' + str(xp_pct) + '%;"></div></div>'
                     '<p style="color:#9ca3af;font-size:10px;margin:2px 0 0;">Level ' + str(level_within_tier) + '/20 in ' + cs_tier + ' tier · ' + str(cs_xp) + ' total XP</p>')

            html += '</div>'

            # Pillar bars
            pillar_names = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]
            pillar_emojis = {"sleep": "😴", "movement": "⚡", "nutrition": "🥗",
                             "metabolic": "🔥", "mind": "🧠", "relationships": "🤝", "consistency": "🏆"}
            html += '<div style="display:grid;grid-template-columns:repeat(7,1fr);gap:4px;text-align:center;">'
            for pn in pillar_names:
                pd = character_sheet.get("pillar_" + pn, {})
                pl = pd.get("level", 1) if pd else 1
                pt = pd.get("tier", "Foundation") if pd else "Foundation"
                pc = tier_colors.get(pt, "#78716c")
                pct_bar = round((pl / 100) * 100)
                html += ('<div>'
                         '<p style="color:#9ca3af;font-size:8px;margin:0;">' + pillar_emojis.get(pn, "•") + '</p>'
                         '<div style="background:#374151;border-radius:2px;height:32px;width:16px;margin:2px auto;position:relative;">'
                         '<div style="background:' + pc + ';border-radius:2px;height:' + str(pct_bar) + '%;width:100%;position:absolute;bottom:0;"></div></div>'
                         '<p style="color:#9ca3af;font-size:8px;margin:0;">' + str(pl) + '</p>'
                         '</div>')
            html += '</div></div>'

            # Level events
            if cs_events:
                html += '<div style="padding:8px 24px;background:rgba(0,0,0,0.2);">'
                for ev in cs_events:
                    ev_type = ev.get("type", "")
                    pillar = ev.get("pillar", "").capitalize()
                    old = ev.get("old_level") or ev.get("old_tier", "")
                    new = ev.get("new_level") or ev.get("new_tier", "")
                    if "character" in ev_type:
                        html += '<p style="color:#fbbf24;font-size:11px;margin:2px 0;">⭐ Character Level ' + str(old) + ' → ' + str(new) + '!</p>'
                    elif "tier" in ev_type:
                        html += '<p style="color:#a78bfa;font-size:11px;margin:2px 0;">🎖 ' + pillar + ' Tier: ' + str(old) + ' → ' + str(new) + '!</p>'
                    elif "up" in ev_type:
                        html += '<p style="color:#34d399;font-size:11px;margin:2px 0;">↑ ' + pillar + ' Level ' + str(old) + ' → ' + str(new) + '</p>'
                    else:
                        html += '<p style="color:#f87171;font-size:11px;margin:2px 0;">↓ ' + pillar + ' Level ' + str(old) + ' → ' + str(new) + '</p>'
                html += '</div>'

            # Active effects
            if cs_effects:
                html += '<div style="padding:4px 24px 8px;background:rgba(0,0,0,0.1);">'
                for eff in cs_effects:
                    eff_name = eff.get("name", "")
                    eff_emoji = eff.get("emoji", "✨")
                    eff_desc = eff.get("description", "")
                    eff_color = "#f87171" if "drag" in eff_name.lower() or "penalty" in eff_name.lower() else "#60a5fa"
                    html += '<span style="display:inline-block;background:rgba(0,0,0,0.3);border-radius:12px;padding:2px 8px;margin:2px;font-size:10px;color:' + eff_color + ';">' + eff_emoji + ' ' + eff_name + '</span>'
                html += '</div>'

            # Triggered rewards (pre-computed, passed in)
            if triggered_rewards:
                html += '<div style="padding:8px 24px;background:rgba(251,191,36,0.1);border-top:1px solid rgba(251,191,36,0.2);">'
                for rw in triggered_rewards:
                    html += ('<p style="color:#fbbf24;font-size:12px;margin:2px 0;font-weight:600;">'
                             '🎁 REWARD UNLOCKED: ' + str(rw.get("title", "")) + '</p>'
                             '<p style="color:#fde68a;font-size:11px;margin:0 0 4px;">' + str(rw.get("description", "")) + '</p>')
                html += '</div>'

            # Protocol recommendations (pre-computed, passed in)
            if protocol_recs:
                html += '<div style="padding:8px 24px 12px;background:rgba(0,0,0,0.15);border-top:1px solid #2d2d5e;">'
                html += '<p style="color:#94a3b8;font-size:10px;margin:0 0 4px;font-weight:700;">PROTOCOL RECOMMENDATIONS</p>'
                for rec in protocol_recs:
                    pillar_name = rec.get("pillar", "").capitalize()
                    dropped = rec.get("dropped", False)
                    arrow = "↓" if dropped else "⚠"
                    protos = rec.get("protocols", [])
                    html += '<p style="color:#f87171;font-size:11px;margin:2px 0;">' + arrow + ' ' + pillar_name + ':</p>'
                    for proto in protos:
                        if isinstance(proto, dict):
                            html += '<p style="color:#9ca3af;font-size:10px;margin:0 0 2px 12px;">• ' + str(proto.get("name", proto)) + '</p>'
                        else:
                            html += '<p style="color:#9ca3af;font-size:10px;margin:0 0 2px 12px;">• ' + str(proto) + '</p>'
                html += '</div>'

            html += '<!-- /S:character_sheet --></div>'

    except Exception as _e:
        html += _section_error_html("Character Sheet", _e)

    # --- Scorecard ---
    try:
        html += '<!-- S:scorecard -->'
        html += ('<div style="background:#16213e;padding:20px 24px;border-bottom:1px solid #2d2d5e;">'
                 '<p style="color:#64748b;font-size:10px;margin:0 0 12px;font-weight:700;letter-spacing:1px;">YESTERDAY\'S SCORECARD</p>'
                 '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;">')

        score_items = [
            ("Sleep", component_scores.get("sleep_quality"), "😴"),
            ("Recovery", component_scores.get("recovery"), "💚"),
            ("Nutrition", component_scores.get("nutrition"), "🥗"),
            ("Movement", component_scores.get("movement"), "⚡"),
            ("Habits", component_scores.get("habits_mvp"), "✅"),
            ("Glucose", component_scores.get("glucose"), "📊"),
            ("Hydration", component_scores.get("hydration"), "💧"),
            ("Journal", component_scores.get("journal"), "📓"),
        ]

        for label, score, emoji in score_items:
            if score is None:
                color = "#475569"
                score_txt = "—"
            elif score >= 80:
                color = "#22c55e"
                score_txt = str(score)
            elif score >= 60:
                color = "#f59e0b"
                score_txt = str(score)
            else:
                color = "#ef4444"
                score_txt = str(score)

            html += ('<div style="background:#1e293b;border-radius:8px;padding:10px;text-align:center;">'
                     '<p style="font-size:16px;margin:0;">' + emoji + '</p>'
                     '<p style="color:' + color + ';font-size:18px;font-weight:700;margin:2px 0;">' + score_txt + '</p>'
                     '<p style="color:#64748b;font-size:9px;margin:0;">' + label + '</p>'
                     '</div>')

        # Habit tier breakdown
        habits_detail = component_details.get("habits_mvp", {})
        t0_data = habits_detail.get("tier0", {})
        t1_data = habits_detail.get("tier1", {})
        if t0_data:
            t0_done = t0_data.get("done", 0)
            t0_total = t0_data.get("total", 0)
            t1_done = t1_data.get("done", 0) if t1_data else 0
            t1_total = t1_data.get("total", 0) if t1_data else 0
            html += ('<div style="grid-column:span 3;background:#1e293b;border-radius:8px;padding:8px 12px;">'
                     '<p style="color:#64748b;font-size:9px;margin:0 0 4px;">HABIT TIERS</p>'
                     '<p style="color:#e2e8f0;font-size:11px;margin:0;">'
                     'T0 (non-neg): ' + str(t0_done) + '/' + str(t0_total) +
                     ' &nbsp;·&nbsp; T1 (high): ' + str(t1_done) + '/' + str(t1_total) + '</p>')

            # Vice streak callout
            if vice_streaks:
                vice_parts = []
                for v_name, v_streak in vice_streaks.items():
                    if v_streak and v_streak > 0:
                        vice_parts.append(v_name + ": " + str(v_streak) + "d streak avoided")
                if vice_parts:
                    html += '<p style="color:#22c55e;font-size:10px;margin:4px 0 0;">🚫 ' + " · ".join(vice_parts) + '</p>'
            html += '</div>'

        html += '</div>'

        # Sleep architecture detail
        sleep = data.get("sleep") or {}
        sleep_dur = safe_float(sleep, "sleep_duration_hours")
        sleep_score_val = safe_float(sleep, "sleep_score")
        deep_pct = safe_float(sleep, "deep_pct")
        rem_pct = safe_float(sleep, "rem_pct")
        efficiency = safe_float(sleep, "sleep_efficiency_pct")

        if sleep_dur or sleep_score_val:
            html += '<div style="margin-top:10px;padding-top:10px;border-top:1px solid #2d2d5e;">'
            html += '<p style="color:#64748b;font-size:9px;margin:0 0 6px;font-weight:700;">SLEEP ARCHITECTURE</p>'
            html += '<div style="display:flex;gap:16px;flex-wrap:wrap;">'

            arch_items = [
                ("Duration", str(round(sleep_dur, 1)) + "h" if sleep_dur else "—", "#94a3b8"),
                ("Score", str(round(sleep_score_val)) if sleep_score_val else "—", "#60a5fa"),
                ("Efficiency", str(round(efficiency)) + "%" if efficiency else "—", "#a78bfa"),
                ("Deep", str(round(deep_pct)) + "%" if deep_pct else "—",
                 "#22c55e" if deep_pct and deep_pct >= 20 else "#f59e0b" if deep_pct else "#94a3b8"),
                ("REM", str(round(rem_pct)) + "%" if rem_pct else "—",
                 "#22c55e" if rem_pct and rem_pct >= 20 else "#f59e0b" if rem_pct else "#94a3b8"),
            ]
            for arch_label, arch_val, arch_color in arch_items:
                html += ('<div style="text-align:center;">'
                         '<p style="color:' + arch_color + ';font-size:14px;font-weight:700;margin:0;">' + arch_val + '</p>'
                         '<p style="color:#475569;font-size:9px;margin:0;">' + arch_label + '</p>'
                         '</div>')
            html += '</div></div>'

        # HRV trend
        try:
            trend_s = hrv_trend_str(data["hrv"].get("hrv_7d"), data["hrv"].get("hrv_30d"))
            hrv_val = safe_float(data.get("whoop"), "hrv")
            if hrv_val:
                html += ('<p style="color:#64748b;font-size:10px;margin:8px 0 0;">'
                         '📡 HRV: <span style="color:#94a3b8;">' + str(round(hrv_val)) + 'ms yesterday · ' + trend_s + '</span></p>')
        except Exception:
            pass

        html += '</div><!-- /S:scorecard -->'

    except Exception as _e:
        html += _section_error_html("Scorecard", _e)

    # --- Essential Seven Scorecard (BS-01) ---
    # Ava Moreau: 7 rows, habit name + status + streak, green/amber, mono streak, above the fold.
    # Sarah Chen: this is the surface. Before AI commentary.
    try:
        html += '<!-- S:essential_seven -->'
        habits_detail   = component_details.get("habits_mvp", {})
        tier_status     = habits_detail.get("tier_status", {})
        tier0_status    = tier_status.get(0, tier_status.get("0", {}))
        registry        = profile.get("habit_registry", {})

        tier0_names = [
            n for n, m in registry.items()
            if m.get("tier") == 0 and m.get("status") == "active"
        ]
        if not tier0_names:
            tier0_names = list(profile.get("mvp_habits", []))

        if tier0_names:
            html += (
                '<div style="background:#0f172a;padding:16px 24px;border-bottom:1px solid #2d2d5e;">'
                '<!-- essential_seven -->'
                '<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:10px;">'
                '<p style="color:#64748b;font-size:10px;margin:0;font-weight:700;letter-spacing:1px;">'
                'ESSENTIAL SEVEN</p>'
                '<p style="color:#f59e0b;font-size:10px;margin:0;font-family:\'JetBrains Mono\',monospace;">'
                + str(mvp_streak) + 'd streak</p>'
                '</div>'
            )
            for h_name in tier0_names:
                done = bool(tier0_status.get(h_name, False))
                # Ava: green = done, amber = miss. No red — amber signals attention, not failure.
                icon_html  = ('<span style="color:#22c55e;font-size:14px;">&#10003;</span>'
                              if done else
                              '<span style="color:#f59e0b;font-size:14px;">&#10005;</span>')
                name_color = '#e2e8f0' if done else '#94a3b8'
                html += (
                    '<div style="display:flex;align-items:center;justify-content:space-between;'
                    'padding:5px 0;border-bottom:1px solid #1e293b;">'
                    '<div style="display:flex;align-items:center;gap:10px;">'
                    + icon_html +
                    '<span style="color:' + name_color + ';font-size:12px;">'
                    + h_name + '</span>'
                    '</div>'
                    '</div>'
                )
            done_count = sum(1 for n in tier0_names if bool(tier0_status.get(n, False)))
            total_count = len(tier0_names)
            bar_pct     = round(done_count / total_count * 100) if total_count else 0
            bar_color   = '#22c55e' if done_count == total_count else '#f59e0b' if done_count >= total_count * 0.7 else '#ef4444'
            html += (
                '<div style="margin-top:8px;background:#1e293b;border-radius:4px;height:4px;">'
                '<div style="background:' + bar_color + ';border-radius:4px;height:4px;width:' + str(bar_pct) + '%;"></div>'
                '</div>'
                '<p style="color:#475569;font-size:9px;margin:4px 0 0;">'
                + str(done_count) + '/' + str(total_count) + ' complete</p>'
                '</div><!-- /essential_seven -->'
            )
        html += '<!-- /S:essential_seven -->'
    except Exception as _e:
        html += _section_error_html("Essential Seven", _e)

    try:
        pass  # dummy try block to close re-opened try (scorecard already closed above)
    except Exception as _e:
        html += _section_error_html("Scorecard", _e)

    # --- Readiness Signal ---
    try:
        html += '<!-- S:readiness -->'
        r_colors = {"green": "#22c55e", "yellow": "#f59e0b", "red": "#ef4444", "gray": "#64748b"}
        r_labels = {"green": "GO", "yellow": "MODERATE", "red": "EASY DAY", "gray": "NO DATA"}
        r_emojis = {"green": "🟢", "yellow": "🟡", "red": "🔴", "gray": "⚪"}
        r_recs = {
            "green": "System is ready. Hard training or high-focus work OK.",
            "yellow": "Moderate effort day. Zone 2 or moderate strength.",
            "red": "Recovery day. Walk, stretch, or easy Zone 2 only.",
            "gray": "No readiness data available.",
        }
        r_col = r_colors.get(readiness_colour, "#64748b")
        html += ('<div style="background:#1e293b;padding:16px 24px;border-bottom:1px solid #2d2d5e;">'
                 '<div style="display:flex;align-items:center;gap:12px;">'
                 '<div style="background:rgba(0,0,0,0.3);border-radius:50%;width:48px;height:48px;'
                 'display:flex;align-items:center;justify-content:center;font-size:24px;">'
                 + r_emojis.get(readiness_colour, "⚪") + '</div>'
                 '<div><p style="color:#94a3b8;font-size:10px;margin:0;font-weight:700;">READINESS SIGNAL</p>'
                 '<p style="color:' + r_col + ';font-size:20px;font-weight:700;margin:2px 0;">'
                 + r_labels.get(readiness_colour, "—") + '</p>'
                 '<p style="color:#64748b;font-size:11px;margin:0;">' + r_recs.get(readiness_colour, "") + '</p>'
                 '</div></div>')

        whoop = data.get("whoop") or {}
        recovery = safe_float(whoop, "recovery_score")
        strain = safe_float(whoop, "strain")
        rhr = safe_float(whoop, "resting_heart_rate")
        if recovery or strain or rhr:
            html += '<div style="margin-top:10px;display:flex;gap:16px;">'
            for r_label, r_val in [("Recovery", str(round(recovery)) + "%" if recovery else "—"),
                                   ("Strain", str(round(strain, 1)) if strain else "—"),
                                   ("RHR", str(round(rhr)) + " bpm" if rhr else "—")]:
                html += ('<div><p style="color:#e2e8f0;font-size:14px;font-weight:600;margin:0;">' + r_val + '</p>'
                         '<p style="color:#475569;font-size:9px;margin:0;">' + r_label + '</p></div>')
            html += '</div>'

        html += '</div><!-- /S:readiness -->'
    except Exception as _e:
        html += _section_error_html("Readiness", _e)

    # --- Training Report ---
    try:
        html += '<!-- S:training -->'
        html += ('<div style="background:#16213e;padding:20px 24px;border-bottom:1px solid #2d2d5e;">'
                 '<p style="color:#64748b;font-size:10px;margin:0 0 12px;font-weight:700;letter-spacing:1px;">TRAINING REPORT</p>')

        strava = data.get("strava") or {}
        activities = strava.get("activities", [])
        if activities:
            for act in activities:
                name = act.get("name", "Activity")
                sport = act.get("sport_type", "?")
                dur_min = round((act.get("moving_time_seconds") or 0) / 60)
                avg_hr_act = act.get("average_heartrate")
                dist = act.get("distance_miles")
                elev = act.get("elevation_gain_ft")

                html += ('<div style="background:#1e293b;border-radius:8px;padding:12px;margin-bottom:8px;">'
                         '<div style="display:flex;justify-content:space-between;">'
                         '<div><p style="color:#e2e8f0;font-size:14px;font-weight:600;margin:0;">' + name + '</p>'
                         '<p style="color:#64748b;font-size:11px;margin:2px 0;">' + sport + '</p></div>'
                         '<p style="color:#60a5fa;font-size:13px;font-weight:600;margin:0;">' + str(dur_min) + ' min</p>'
                         '</div>')

                stat_parts = []
                if dist:
                    stat_parts.append(str(round(dist, 1)) + " mi")
                if avg_hr_act:
                    stat_parts.append("avg HR " + str(round(avg_hr_act)))
                if elev:
                    stat_parts.append(str(round(elev)) + "ft gain")
                if stat_parts:
                    html += '<p style="color:#94a3b8;font-size:11px;margin:4px 0 0;">' + " · ".join(stat_parts) + '</p>'
                html += '</div>'

        elif data.get("garmin"):
            garmin = data.get("garmin")
            steps = safe_float(garmin, "steps")
            html += '<p style="color:#64748b;font-size:12px;margin:0;">No structured workouts. Steps: ' + fmt_num(steps) + '</p>'
        else:
            html += '<p style="color:#64748b;font-size:12px;margin:0;">No training data for yesterday.</p>'

        # MacroFactor workout detail
        mf_workouts = data.get("mf_workouts")
        if mf_workouts:
            workouts = mf_workouts.get("workouts", [])
            for w in workouts:
                w_name = w.get("workout_name", "Strength Session")
                exercises = w.get("exercises", [])
                total_vol = mf_workouts.get("total_volume_lbs")
                total_sets = mf_workouts.get("total_sets")

                html += ('<div style="background:#0f172a;border-radius:8px;padding:12px;margin-top:8px;">'
                         '<p style="color:#94a3b8;font-size:11px;font-weight:700;margin:0 0 8px;">💪 ' + w_name + '</p>')
                for ex in exercises[:8]:
                    ex_name = ex.get("exercise_name", "?")
                    sets_data = ex.get("sets", [])
                    set_strs = []
                    for s in sets_data:
                        reps = s.get("reps", 0)
                        weight_ex = s.get("weight_lbs", 0)
                        rir = s.get("rir")
                        st = str(reps)
                        if weight_ex:
                            st += "@" + str(round(float(weight_ex))) + "lb"
                        if rir is not None:
                            st += " RIR" + str(rir)
                        set_strs.append(st)
                    html += ('<p style="color:#64748b;font-size:10px;margin:0 0 2px;">'
                             '<span style="color:#94a3b8;">' + ex_name + '</span>: '
                             + ", ".join(set_strs) + '</p>')

                if total_vol:
                    html += ('<p style="color:#475569;font-size:9px;margin:6px 0 0;">'
                             'Volume: ' + fmt_num(total_vol) + ' lbs · ' + str(round(float(total_sets or 0))) + ' sets</p>')
                html += '</div>'

        # AI training/nutrition commentary
        training_text = (training_nutrition or {}).get("training", "")
        if training_text:
            html += ('<div style="background:#1e293b;border-left:3px solid #3b82f6;border-radius:0 8px 8px 0;'
                     'padding:10px 14px;margin-top:10px;">'
                     '<p style="color:#60a5fa;font-size:10px;margin:0 0 4px;font-weight:700;">COACH ANALYSIS</p>'
                     '<p style="color:#94a3b8;font-size:12px;margin:0;line-height:1.5;">' + training_text + '</p></div>')

        tsb = data.get("tsb")
        if tsb is not None:
            tsb_color = "#22c55e" if tsb > 5 else "#f59e0b" if tsb > -10 else "#ef4444"
            tsb_label = "Fresh" if tsb > 10 else "Optimal" if tsb > 0 else "Tired" if tsb > -20 else "Overreached"
            html += ('<p style="color:#475569;font-size:10px;margin:8px 0 0;">'
                     'TSB: <span style="color:' + tsb_color + ';">' + str(round(tsb, 1)) + ' (' + tsb_label + ')</span></p>')

        # BS-09: ACWR training load alert
        try:
            computed_metrics = data.get("computed_metrics") or {}
            acwr_val = computed_metrics.get("acwr")
            acwr_zone = str(computed_metrics.get("zone", ""))
            acwr_alert = computed_metrics.get("alert", False)
            acwr_reason = str(computed_metrics.get("alert_reason", ""))
            if acwr_val is not None:
                _av = float(acwr_val)
                acwr_color = ("#ef4444" if acwr_alert
                              else "#f59e0b" if _av > 1.3 or _av < 0.8
                              else "#22c55e")
                zone_label = acwr_zone.upper() if acwr_zone else ""
                html += ('<p style="color:#475569;font-size:10px;margin:4px 0 0;">'
                         'ACWR: <span style="color:' + acwr_color + ';font-weight:600;">'
                         + str(round(_av, 2))
                         + (' \u2014 ' + zone_label if zone_label else '')
                         + '</span></p>')
                if acwr_alert and acwr_reason:
                    html += ('<div style="background:#1c0a0a;border-left:3px solid #ef4444;'
                             'border-radius:0 6px 6px 0;padding:8px 12px;margin-top:8px;">'
                             '<p style="color:#f87171;font-size:11px;margin:0;font-weight:700;">'
                             '\u26a0\ufe0f TRAINING LOAD ALERT</p>'
                             '<p style="color:#fca5a5;font-size:11px;margin:2px 0 0;line-height:1.5;">'
                             + acwr_reason + '</p></div>')
        except Exception:
            pass

        html += '</div><!-- /S:training -->'
    except Exception as _e:
        html += _section_error_html("Training Report", _e)

    # --- Nutrition Report ---
    try:
        html += '<!-- S:nutrition -->'
        html += ('<div style="background:#1e293b;padding:20px 24px;border-bottom:1px solid #2d2d5e;">'
                 '<p style="color:#64748b;font-size:10px;margin:0 0 12px;font-weight:700;letter-spacing:1px;">NUTRITION REPORT</p>')

        mf = data.get("macrofactor") or {}
        cals = safe_float(mf, "total_calories_kcal")
        protein = safe_float(mf, "total_protein_g")
        fat = safe_float(mf, "total_fat_g")
        carbs = safe_float(mf, "total_carbs_g")
        fiber = safe_float(mf, "total_fiber_g")

        cal_target = profile.get("calorie_target", 1800)
        protein_target = profile.get("protein_target_g", 190)

        if cals is not None:
            cal_pct = round(cals / cal_target * 100) if cal_target else 0
            cal_color = "#22c55e" if 85 <= cal_pct <= 110 else "#f59e0b" if cal_pct <= 120 else "#ef4444"
            prot_pct = round(protein / protein_target * 100) if protein and protein_target else 0
            prot_color = "#22c55e" if prot_pct >= 95 else "#f59e0b" if prot_pct >= 75 else "#ef4444"

            html += '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:12px;">'
            macro_items = [
                ("Calories", fmt_num(cals), "/" + str(cal_target), cal_color),
                ("Protein", str(round(protein)) + "g" if protein else "—", "/" + str(protein_target) + "g", prot_color),
                ("Fat", str(round(fat)) + "g" if fat else "—", "", "#94a3b8"),
                ("Carbs", str(round(carbs)) + "g" if carbs else "—", "", "#94a3b8"),
            ]
            for m_label, m_val, m_target, m_color in macro_items:
                html += ('<div style="background:#16213e;border-radius:8px;padding:10px;text-align:center;">'
                         '<p style="color:' + m_color + ';font-size:16px;font-weight:700;margin:0;">' + m_val + '</p>'
                         '<p style="color:#475569;font-size:9px;margin:0;">' + m_label + m_target + '</p>'
                         '</div>')
            html += '</div>'

            if fiber:
                html += '<p style="color:#475569;font-size:10px;margin:0;">Fiber: ' + str(round(fiber)) + 'g</p>'
        else:
            html += '<p style="color:#64748b;font-size:12px;margin:0;">No nutrition data logged yesterday.</p>'

        nutrition_text = (training_nutrition or {}).get("nutrition", "")
        if nutrition_text:
            html += ('<div style="background:#16213e;border-left:3px solid #22c55e;border-radius:0 8px 8px 0;'
                     'padding:10px 14px;margin-top:10px;">'
                     '<p style="color:#4ade80;font-size:10px;margin:0 0 4px;font-weight:700;">NUTRITIONIST</p>'
                     '<p style="color:#94a3b8;font-size:12px;margin:0;line-height:1.5;">' + nutrition_text + '</p></div>')

        html += '</div><!-- /S:nutrition -->'
    except Exception as _e:
        html += _section_error_html("Nutrition Report", _e)

    # --- Habits Deep-Dive ---
    try:
        html += '<!-- S:habits -->'
        html += ('<div style="background:#16213e;padding:20px 24px;border-bottom:1px solid #2d2d5e;">'
                 '<p style="color:#64748b;font-size:10px;margin:0 0 12px;font-weight:700;letter-spacing:1px;">HABITS DEEP-DIVE</p>')

        habitify = data.get("habitify") or {}
        registry = profile.get("habit_registry", {})
        h_map = habitify.get("habits", {})

        if registry:
            # Tier 0 first
            for tier_label, tier_num, tier_color in [("TIER 0 — NON-NEGOTIABLE", 0, "#ef4444"),
                                                       ("TIER 1 — HIGH PRIORITY", 1, "#f59e0b"),
                                                       ("TIER 2 — GOOD TO DO", 2, "#64748b")]:
                tier_habits = [(n, m) for n, m in registry.items()
                               if m.get("tier", 2) == tier_num and m.get("status") == "active"]
                if not tier_habits:
                    continue
                html += '<p style="color:' + tier_color + ';font-size:9px;margin:8px 0 4px;font-weight:700;">' + tier_label + '</p>'
                for h_name, meta in sorted(tier_habits, key=lambda x: x[0]):
                    done = h_map.get(h_name, 0)
                    completed = done is not None and float(done) >= 1
                    icon = "✅" if completed else "❌"
                    why = meta.get("why_matthew", "")
                    html += ('<div style="display:flex;align-items:flex-start;gap:8px;margin-bottom:4px;">'
                             '<span style="font-size:12px;flex-shrink:0;">' + icon + '</span>'
                             '<div><p style="color:' + ("#e2e8f0" if completed else "#94a3b8") +
                             ';font-size:12px;margin:0;">' + h_name + '</p>')
                    if why and not completed:
                        html += '<p style="color:#475569;font-size:10px;margin:0;">' + why[:80] + '</p>'
                    html += '</div></div>'

            # Synergy alert
            synergy_misses = {}
            for h_name, meta in registry.items():
                if meta.get("status") != "active":
                    continue
                sg = meta.get("synergy_group")
                if not sg:
                    continue
                done = h_map.get(h_name, 0)
                if not (done is not None and float(done) >= 1):
                    synergy_misses.setdefault(sg, []).append(h_name)
            for sg, misses in synergy_misses.items():
                total = sum(1 for _, m in registry.items()
                            if m.get("synergy_group") == sg and m.get("status") == "active")
                if len(misses) >= total * 0.5 and total >= 3:
                    html += ('<p style="color:#f59e0b;font-size:10px;margin:6px 0 0;">'
                             '⚠ Synergy alert: ' + sg + ' stack mostly missed</p>')
        elif h_map:
            done_count = sum(1 for v in h_map.values() if v and float(v) >= 1)
            total_count = len(h_map)
            html += '<p style="color:#94a3b8;font-size:13px;margin:0;">' + str(done_count) + ' / ' + str(total_count) + ' habits completed</p>'
        else:
            html += '<p style="color:#64748b;font-size:12px;margin:0;">No habit data for yesterday.</p>'

        html += '</div><!-- /S:habits -->'
    except Exception as _e:
        html += _section_error_html("Habits Deep-Dive", _e)

    # --- Supplements ---
    try:
        html += '<div style="background:#1e293b;padding:16px 24px;border-bottom:1px solid #2d2d5e;">'
        html += '<p style="color:#64748b;font-size:10px;margin:0 0 8px;font-weight:700;letter-spacing:1px;">SUPPLEMENTS</p>'
        supps_today = data.get("supplements_today")
        if supps_today:
            supp_list = supps_today.get("supplements", [])
            if supp_list:
                by_timing = {}
                for s in supp_list:
                    t = s.get("timing", "other")
                    by_timing.setdefault(t, []).append(s)
                timing_labels = {"morning_fasted": "Morning (fasted)", "afternoon_with_food": "Afternoon (with food)",
                                 "evening_sleep": "Evening / Sleep"}
                for timing_key, timing_label in timing_labels.items():
                    if timing_key in by_timing:
                        html += '<p style="color:#64748b;font-size:9px;margin:4px 0 2px;font-weight:700;">' + timing_label.upper() + '</p>'
                        for s_item in by_timing[timing_key]:
                            name = s_item.get("name", "?")
                            dose = s_item.get("dose", "")
                            unit = s_item.get("unit", "")
                            dose_str = (" — " + str(dose) + " " + str(unit)).strip() if dose else ""
                            html += '<p style="color:#94a3b8;font-size:11px;margin:0;">• ' + name + dose_str + '</p>'
            else:
                html += '<p style="color:#475569;font-size:11px;margin:0;">No supplement data logged.</p>'
        else:
            html += '<p style="color:#475569;font-size:11px;margin:0;">No supplement data for yesterday.</p>'
        html += '</div>'
    except Exception as _e:
        html += _section_error_html("Supplements", _e)

    # --- CGM Spotlight ---
    try:
        html += '<!-- S:cgm -->'
        html += ('<div style="background:#16213e;padding:20px 24px;border-bottom:1px solid #2d2d5e;">'
                 '<p style="color:#64748b;font-size:10px;margin:0 0 12px;font-weight:700;letter-spacing:1px;">CGM SPOTLIGHT</p>')

        apple = data.get("apple") or {}
        glucose_avg = safe_float(apple, "blood_glucose_avg")
        glucose_tir = safe_float(apple, "blood_glucose_time_in_range_pct")
        glucose_std = safe_float(apple, "blood_glucose_std_dev")
        glucose_min = safe_float(apple, "blood_glucose_min")
        glucose_max = safe_float(apple, "blood_glucose_max")

        if glucose_avg is not None:
            tir_color = "#22c55e" if glucose_tir and glucose_tir >= 85 else "#f59e0b" if glucose_tir and glucose_tir >= 70 else "#ef4444"
            avg_color = "#22c55e" if glucose_avg < 100 else "#f59e0b" if glucose_avg < 120 else "#ef4444"

            html += '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;">'
            cgm_items = [
                ("Avg", str(round(glucose_avg)), "mg/dL", avg_color),
                ("TIR", str(round(glucose_tir)) + "%" if glucose_tir else "—", "70-140", tir_color),
                ("Fasting", str(round(glucose_min)) if glucose_min else "—", "overnight low", "#94a3b8"),
                ("Variability", str(round(glucose_std, 1)) if glucose_std else "—", "SD mg/dL",
                 "#22c55e" if glucose_std and glucose_std < 15 else "#f59e0b" if glucose_std and glucose_std < 25 else "#ef4444"),
            ]
            for cg_label, cg_val, cg_sub, cg_color in cgm_items:
                html += ('<div style="background:#1e293b;border-radius:8px;padding:10px;text-align:center;">'
                         '<p style="color:' + cg_color + ';font-size:18px;font-weight:700;margin:0;">' + cg_val + '</p>'
                         '<p style="color:#475569;font-size:9px;margin:0;">' + cg_label + '</p>'
                         '<p style="color:#334155;font-size:8px;margin:0;">' + cg_sub + '</p>'
                         '</div>')
            html += '</div>'

            if glucose_min and glucose_min < 72:
                html += ('<p style="color:#ef4444;font-size:11px;margin:8px 0 0;">'
                         '⚠ Hypoglycemia signal: overnight low ' + str(round(glucose_min)) + ' mg/dL</p>')

            # 7-day trend
            apple_7d = data.get("apple_7d") or []
            gl_7d = [safe_float(d, "blood_glucose_avg") for d in apple_7d if safe_float(d, "blood_glucose_avg")]
            if len(gl_7d) >= 3:
                trend_avg = avg(gl_7d)
                html += ('<p style="color:#475569;font-size:10px;margin:6px 0 0;">'
                         '7-day avg: <span style="color:#94a3b8;">' + str(round(trend_avg)) + ' mg/dL</span></p>')
        else:
            html += '<p style="color:#64748b;font-size:12px;margin:0;">No glucose data for yesterday.</p>'

        html += '</div><!-- /S:cgm -->'
    except Exception as _e:
        html += _section_error_html("CGM Spotlight", _e)

    # --- Gait & Mobility ---
    try:
        html += ('<div style="background:#1e293b;padding:16px 24px;border-bottom:1px solid #2d2d5e;">'
                 '<p style="color:#64748b;font-size:10px;margin:0 0 8px;font-weight:700;letter-spacing:1px;">GAIT &amp; MOBILITY</p>')

        apple = data.get("apple") or {}
        ws = safe_float(apple, "walking_speed_mph")
        sl = safe_float(apple, "walking_step_length_in")
        asym = safe_float(apple, "walking_asymmetry_pct")
        dbl = safe_float(apple, "walking_double_support_pct")

        if ws or sl:
            gait_items = []
            if ws:
                gait_items.append(("Speed", str(round(ws, 2)) + " mph",
                                   "#22c55e" if ws >= 3.0 else "#f59e0b" if ws >= 2.5 else "#ef4444"))
            if sl:
                gait_items.append(("Step Length", str(round(sl, 1)) + '"',
                                   "#22c55e" if sl >= 27 else "#f59e0b"))
            if asym:
                gait_items.append(("Asymmetry", str(round(asym, 1)) + "%",
                                   "#22c55e" if asym < 3 else "#f59e0b" if asym < 5 else "#ef4444"))
            if dbl:
                gait_items.append(("Double Support", str(round(dbl, 1)) + "%", "#94a3b8"))

            html += '<div style="display:flex;gap:16px;flex-wrap:wrap;">'
            for g_label, g_val, g_color in gait_items:
                html += ('<div style="text-align:center;">'
                         '<p style="color:' + g_color + ';font-size:14px;font-weight:700;margin:0;">' + g_val + '</p>'
                         '<p style="color:#475569;font-size:9px;margin:0;">' + g_label + '</p></div>')
            html += '</div>'
        else:
            html += '<p style="color:#64748b;font-size:11px;margin:0;">No gait data available.</p>'
        html += '</div>'
    except Exception as _e:
        html += _section_error_html("Gait & Mobility", _e)

    # --- Habit Streaks ---
    try:
        html += '<!-- S:habit_streaks -->'
        html += ('<div style="background:#16213e;padding:16px 24px;border-bottom:1px solid #2d2d5e;">'
                 '<p style="color:#64748b;font-size:10px;margin:0 0 8px;font-weight:700;letter-spacing:1px;">HABIT STREAKS</p>')

        if mvp_streak > 0 or full_streak > 0:
            html += '<div style="display:flex;gap:16px;">'
            if mvp_streak > 0:
                html += ('<div style="text-align:center;">'
                         '<p style="color:#f59e0b;font-size:24px;font-weight:700;margin:0;">' + str(mvp_streak) + '</p>'
                         '<p style="color:#475569;font-size:9px;margin:0;">T0 Streak (days)</p></div>')
            if full_streak > 0:
                html += ('<div style="text-align:center;">'
                         '<p style="color:#22c55e;font-size:24px;font-weight:700;margin:0;">' + str(full_streak) + '</p>'
                         '<p style="color:#475569;font-size:9px;margin:0;">T0+T1 Streak</p></div>')
            html += '</div>'
        else:
            html += '<p style="color:#475569;font-size:11px;margin:0;">No active streak. Start today.</p>'

        html += '</div><!-- /S:habit_streaks -->'
    except Exception as _e:
        html += _section_error_html("Habit Streaks", _e)

    # --- Weather ---
    try:
        html += '<!-- S:weather -->'
        weather = data.get("weather_yesterday") or data.get("weather_today")
        if weather:
            html += ('<div style="background:#1e293b;padding:16px 24px;border-bottom:1px solid #2d2d5e;">'
                     '<p style="color:#64748b;font-size:10px;margin:0 0 8px;font-weight:700;letter-spacing:1px;">WEATHER CONTEXT</p>')
            temp_hi = safe_float(weather, "temp_high_f")
            temp_lo = safe_float(weather, "temp_low_f")
            condition = weather.get("condition", "")
            precip = safe_float(weather, "precip_in")
            aqi = safe_float(weather, "aqi")
            sunrise = weather.get("sunrise_local", "")
            sunset = weather.get("sunset_local", "")

            html += '<div style="display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start;">'
            if temp_hi:
                html += ('<div><p style="color:#f59e0b;font-size:18px;font-weight:700;margin:0;">'
                         + str(round(temp_hi)) + '°/' + (str(round(temp_lo)) if temp_lo else "—") + '°F</p>'
                         '<p style="color:#475569;font-size:9px;margin:0;">Hi/Lo</p></div>')
            if condition:
                html += ('<div><p style="color:#94a3b8;font-size:13px;margin:0;">' + condition + '</p>'
                         '<p style="color:#475569;font-size:9px;margin:0;">Conditions</p></div>')
            if sunrise:
                html += ('<div><p style="color:#fbbf24;font-size:12px;margin:0;">' + sunrise[:5] + '</p>'
                         '<p style="color:#475569;font-size:9px;margin:0;">Sunrise</p></div>')
            if precip and precip > 0:
                html += ('<div><p style="color:#60a5fa;font-size:12px;margin:0;">' + str(round(precip, 2)) + '"</p>'
                         '<p style="color:#475569;font-size:9px;margin:0;">Precip</p></div>')
            if aqi:
                aqi_color = "#22c55e" if aqi < 50 else "#f59e0b" if aqi < 100 else "#ef4444"
                html += ('<div><p style="color:' + aqi_color + ';font-size:12px;margin:0;">' + str(round(aqi)) + '</p>'
                         '<p style="color:#475569;font-size:9px;margin:0;">AQI</p></div>')
            html += '</div></div>'
        html += '<!-- /S:weather -->'
    except Exception as _e:
        html += _section_error_html("Weather", _e)

    # --- Blood Pressure ---
    try:
        html += '<!-- S:blood_pressure -->'
        bp_data = data.get("bp_data")
        if bp_data:
            html += ('<div style="background:#16213e;padding:16px 24px;border-bottom:1px solid #2d2d5e;">'
                     '<p style="color:#64748b;font-size:10px;margin:0 0 8px;font-weight:700;letter-spacing:1px;">BLOOD PRESSURE</p>')
            sys_val = bp_data.get("systolic")
            dia_val = bp_data.get("diastolic")
            bp_class = bp_data.get("class", "")
            bp_color = bp_data.get("class_color", "#94a3b8")
            pulse_val = bp_data.get("pulse")
            readings = bp_data.get("readings", 1)

            html += ('<div style="display:flex;align-items:center;gap:16px;">'
                     '<div><p style="color:' + bp_color + ';font-size:22px;font-weight:700;margin:0;">'
                     + str(round(sys_val)) + '/' + str(round(dia_val)) + '</p>'
                     '<p style="color:#475569;font-size:9px;margin:0;">mmHg</p></div>')
            if bp_class:
                html += ('<div><p style="color:' + bp_color + ';font-size:13px;font-weight:600;margin:0;">'
                         + bp_class + '</p><p style="color:#475569;font-size:9px;margin:0;">AHA Class</p></div>')
            if pulse_val:
                html += ('<div><p style="color:#94a3b8;font-size:13px;margin:0;">'
                         + str(round(pulse_val)) + ' bpm</p><p style="color:#475569;font-size:9px;margin:0;">Pulse</p></div>')
            if readings > 1:
                html += ('<div><p style="color:#475569;font-size:11px;margin:0;">'
                         + str(readings) + ' readings avg</p></div>')
            html += '</div></div>'
        html += '<!-- /S:blood_pressure -->'
    except Exception as _e:
        html += _section_error_html("Blood Pressure", _e)

    # --- Task Load (Todoist) ---
    try:
        html += '<!-- S:task_load -->'
        todoist = data.get("todoist")
        if todoist:
            active = int(todoist.get("active_count", 0))
            overdue = int(todoist.get("overdue_count", 0))
            due_today = int(todoist.get("due_today_count", 0))
            completed = int(todoist.get("completed_count", 0))
            by_project = todoist.get("completions_by_project", {})

            # Cognitive load colour
            if overdue > 30:
                load_color = "#dc2626"; load_label = "HIGH"
            elif overdue > 15:
                load_color = "#d97706"; load_label = "ELEVATED"
            elif overdue > 5:
                load_color = "#eab308"; load_label = "MODERATE"
            else:
                load_color = "#059669"; load_label = "CLEAR"

            html += ('<div style="background:#16213e;padding:16px 24px;border-bottom:1px solid #2d2d5e;">'
                     '<p style="color:#64748b;font-size:10px;margin:0 0 10px;font-weight:700;letter-spacing:1px;">TASK LOAD</p>'
                     '<div style="display:flex;gap:20px;align-items:center;flex-wrap:wrap;">'
                     '<div><p style="color:#e2e8f0;font-size:20px;font-weight:700;margin:0;">'
                     + str(completed) + '</p><p style="color:#475569;font-size:9px;margin:0;">DONE YESTERDAY</p></div>'
                     '<div><p style="color:' + load_color + ';font-size:20px;font-weight:700;margin:0;">'
                     + str(overdue) + '</p><p style="color:#475569;font-size:9px;margin:0;">OVERDUE</p></div>'
                     '<div><p style="color:#94a3b8;font-size:20px;font-weight:700;margin:0;">'
                     + str(due_today) + '</p><p style="color:#475569;font-size:9px;margin:0;">DUE TODAY</p></div>'
                     '<div><p style="color:#94a3b8;font-size:20px;font-weight:700;margin:0;">'
                     + str(active) + '</p><p style="color:#475569;font-size:9px;margin:0;">ACTIVE</p></div>'
                     '<div style="margin-left:auto;"><p style="color:' + load_color + ';font-size:11px;font-weight:700;margin:0;">'
                     + load_label + '</p><p style="color:#475569;font-size:9px;margin:0;">LOAD SIGNAL</p></div>'
                     '</div>')

            if by_project:
                top_proj = sorted(by_project.items(), key=lambda x: x[1], reverse=True)[:3]
                if top_proj:
                    html += '<p style="color:#475569;font-size:10px;margin:8px 0 4px;">Yesterday — '
                    html += ' · '.join(f'<span style="color:#94a3b8;">{p}</span> {c}' for p, c in top_proj)
                    html += '</p>'

            html += '</div>'
        html += '<!-- /S:task_load -->'
    except Exception as _e:
        html += _section_error_html("Task Load", _e)

    # --- Weight Phase ---
    try:
        html += '<!-- S:weight_phase -->'
        html += ('<div style="background:#1e293b;padding:20px 24px;border-bottom:1px solid #2d2d5e;">'
                 '<p style="color:#64748b;font-size:10px;margin:0 0 12px;font-weight:700;letter-spacing:1px;">WEIGHT PHASE TRACKER</p>')

        latest_weight = data.get("latest_weight")
        week_ago_weight = data.get("week_ago_weight")

        if latest_weight:
            phase = get_current_phase(profile, latest_weight)
            phase_name = phase.get("name", "") if phase else ""
            phase_end = phase.get("end_lbs", 0) if phase else 0
            journey_start = profile.get("journey_start_weight_lbs", 302)
            goal_weight = profile.get("goal_weight_lbs", 185)

            # Progress bar
            total_to_lose = journey_start - goal_weight
            lost = journey_start - latest_weight
            pct_complete = max(0, min(100, round(lost / total_to_lose * 100))) if total_to_lose > 0 else 0

            html += ('<div style="display:flex;justify-content:space-between;margin-bottom:8px;">'
                     '<p style="color:#e2e8f0;font-size:20px;font-weight:700;margin:0;">'
                     + str(round(latest_weight, 1)) + ' lbs</p>')

            if week_ago_weight:
                delta = round(latest_weight - week_ago_weight, 1)
                delta_color = "#22c55e" if delta < 0 else "#ef4444" if delta > 0.5 else "#f59e0b"
                delta_str = ("−" if delta < 0 else "+") + str(abs(delta))
                html += ('<p style="color:' + delta_color + ';font-size:14px;font-weight:600;margin:0;">'
                         + delta_str + ' lbs vs 7d ago</p>')
            html += '</div>'

            html += ('<div style="background:#374151;border-radius:6px;height:8px;margin-bottom:6px;">'
                     '<div style="background:linear-gradient(90deg,#3b82f6,#8b5cf6);border-radius:6px;'
                     'height:8px;width:' + str(pct_complete) + '%;"></div></div>'
                     '<div style="display:flex;justify-content:space-between;">'
                     '<p style="color:#475569;font-size:9px;margin:0;">' + str(journey_start) + ' lbs start</p>'
                     '<p style="color:#60a5fa;font-size:9px;margin:0;">' + str(round(pct_complete)) + '% to goal</p>'
                     '<p style="color:#475569;font-size:9px;margin:0;">' + str(goal_weight) + ' lbs goal</p>'
                     '</div>')
            if phase_name:
                html += ('<p style="color:#94a3b8;font-size:11px;margin:8px 0 0;">'
                         'Phase: <strong>' + phase_name + '</strong>'
                         + (' · target ' + str(round(phase_end)) + ' lbs' if phase_end else '') + '</p>')
        else:
            html += '<p style="color:#64748b;font-size:12px;margin:0;">No weight data recorded recently.</p>'

        html += '</div><!-- /S:weight_phase -->'
    except Exception as _e:
        html += _section_error_html("Weight Phase", _e)

    # --- Guidance ---
    try:
        html += '<!-- S:guidance -->'
        guidance_items = (tldr_guidance or {}).get("guidance", [])
        if guidance_items:
            html += ('<div style="background:#16213e;padding:20px 24px;border-bottom:1px solid #2d2d5e;">'
                     '<p style="color:#64748b;font-size:10px;margin:0 0 12px;font-weight:700;letter-spacing:1px;">TODAY\'S GUIDANCE</p>')
            for item in guidance_items:
                html += ('<div style="background:#1e293b;border-radius:8px;padding:10px 14px;margin-bottom:8px;">'
                         '<p style="color:#e2e8f0;font-size:12px;margin:0;line-height:1.5;">' + item + '</p></div>')
            html += '</div>'
        html += '<!-- /S:guidance -->'
    except Exception as _e:
        html += _section_error_html("Guidance", _e)

    # --- Journal Pulse ---
    try:
        html += '<!-- S:journal_pulse -->'
        journal = data.get("journal") or {}
        if journal:
            mood = journal.get("mood_avg")
            energy = journal.get("energy_avg")
            stress = journal.get("stress_avg")
            themes = journal.get("themes", [])

            html += ('<div style="background:#1e293b;padding:20px 24px;border-bottom:1px solid #2d2d5e;">'
                     '<p style="color:#64748b;font-size:10px;margin:0 0 12px;font-weight:700;letter-spacing:1px;">JOURNAL PULSE</p>'
                     '<div style="display:flex;gap:16px;">')

            for j_label, j_val in [("Mood", mood), ("Energy", energy), ("Stress", stress)]:
                if j_val is not None:
                    j_color = "#22c55e" if j_val >= 4 else "#f59e0b" if j_val >= 3 else "#ef4444"
                    if j_label == "Stress":
                        j_color = "#ef4444" if j_val >= 4 else "#f59e0b" if j_val >= 3 else "#22c55e"
                    html += ('<div style="text-align:center;">'
                             '<p style="color:' + j_color + ';font-size:20px;font-weight:700;margin:0;">'
                             + str(round(j_val, 1)) + '/5</p>'
                             '<p style="color:#475569;font-size:9px;margin:0;">' + j_label + '</p></div>')
            html += '</div>'

            if themes:
                html += ('<p style="color:#64748b;font-size:10px;margin:8px 0 4px;">Themes:</p>'
                         '<p style="color:#94a3b8;font-size:11px;margin:0;">' + ', '.join(str(t) for t in themes[:5]) + '</p>')
            html += '</div>'
        html += '<!-- /S:journal_pulse -->'
    except Exception as _e:
        html += _section_error_html("Journal Pulse", _e)

    # --- Journal Coach ---
    try:
        html += '<!-- S:journal_coach -->'
        if journal_coach_text:
            parts = journal_coach_text.split(" || ")
            reflection = parts[0].strip() if parts else ""
            tactic = parts[1].strip() if len(parts) > 1 else ""
            html += ('<div style="background:#16213e;padding:20px 24px;border-bottom:1px solid #2d2d5e;">'
                     '<p style="color:#64748b;font-size:10px;margin:0 0 8px;font-weight:700;letter-spacing:1px;">JOURNAL COACH</p>')
            if reflection:
                html += ('<p style="color:#e2e8f0;font-size:13px;line-height:1.6;margin:0 0 8px;font-style:italic;">'
                         '"' + reflection + '"</p>')
            if tactic:
                html += ('<div style="background:#1e293b;border-left:3px solid #8b5cf6;border-radius:0 8px 8px 0;'
                         'padding:8px 12px;">'
                         '<p style="color:#a78bfa;font-size:10px;margin:0 0 2px;font-weight:700;">TODAY\'S TACTIC</p>'
                         '<p style="color:#94a3b8;font-size:12px;margin:0;">' + tactic + '</p></div>')
            html += '</div>'
        html += '<!-- /S:journal_coach -->'
    except Exception as _e:
        html += _section_error_html("Journal Coach", _e)

    # --- Board of Directors ---
    try:
        html += '<!-- S:bod -->'
        if bod_insight:
            # BS-05: confidence badge — daily brief BoD insight confidence from data volume
            # Henning: n = days since journey start (observation count proxy)
            try:
                from datetime import datetime as _dt
                _start = data.get("profile", profile).get("journey_start_date", "2026-04-01") if isinstance(data.get("profile", profile), dict) else profile.get("journey_start_date", "2026-04-01")
                _days = (_dt.utcnow().date() - _dt.strptime(_start, "%Y-%m-%d").date()).days
                _sources_active = sum(1 for s in ["whoop", "macrofactor", "habitify", "strava", "apple"] if data.get(s))
                _conf = compute_confidence(days_of_data=_days, sources=list(range(_sources_active)))
                _badge = _conf["badge_html"]
            except Exception:
                _badge = ""
            html += ('<div style="background:#1e293b;padding:20px 24px;border-bottom:1px solid #2d2d5e;">'
                     '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">'
                     '<p style="color:#64748b;font-size:10px;margin:0;font-weight:700;letter-spacing:1px;">BOARD OF DIRECTORS</p>'
                     + (_badge if _badge else '') +
                     '</div>'
                     '<div style="background:#16213e;border-left:3px solid #6366f1;border-radius:0 8px 8px 0;'
                     'padding:12px 16px;">'
                     '<p style="color:#c7d2fe;font-size:13px;line-height:1.6;margin:0;">' + bod_insight + '</p>'
                     '</div></div>')
        html += '<!-- /S:bod -->'
    except Exception as _e:
        html += _section_error_html("Board of Directors", _e)

    # --- Anomaly Alert ---
    try:
        html += '<!-- S:anomaly -->'
        anomaly = data.get("anomaly")
        if anomaly and anomaly.get("has_anomalies"):
            alerts = anomaly.get("alerts", [])
            if alerts:
                html += ('<div style="background:#1c0a0a;padding:16px 24px;border-bottom:1px solid #450a0a;">'
                         '<p style="color:#f87171;font-size:10px;margin:0 0 8px;font-weight:700;letter-spacing:1px;">⚠ ANOMALY ALERT</p>')
                for alert in alerts[:3]:
                    metric = alert.get("metric", "")
                    msg = alert.get("message", "")
                    html += ('<p style="color:#fca5a5;font-size:12px;margin:0 0 4px;">'
                             '<strong>' + metric + ':</strong> ' + msg + '</p>')
                html += '</div>'
        html += '<!-- /S:anomaly -->'
    except Exception as _e:
        html += _section_error_html("Anomaly Alert", _e)

    # --- S2-T1-10: Weekly Habit Review (Sunday only) ---
    try:
        if weekly_habit_review:
            html += _render_weekly_habit_review(weekly_habit_review)
    except Exception as _whr_e:
        html += _section_error_html("Weekly Habit Review", _whr_e)

    # --- Footer ---
    active_sources = []
    if data.get("whoop"):
        active_sources.append("Whoop")
    if data.get("strava"):
        active_sources.append("Strava")
    if data.get("macrofactor"):
        active_sources.append("MacroFactor")
    if data.get("apple"):
        active_sources.append("Apple Health")
    if data.get("habitify"):
        active_sources.append("Habitify")
    if data.get("garmin"):
        active_sources.append("Garmin")
    if data.get("journal"):
        active_sources.append("Notion")
    source_str = " &middot; ".join(active_sources) if active_sources else "No data sources"
    if compute_stale:
        html += '<div style="background:#fffbeb;padding:6px 24px;border-top:1px solid #fde68a;margin-top:8px;">'
        html += '<p style="color:#92400e;font-size:9px;margin:0;text-align:center;">'
        html += '&#9888;&#65039; Compute data ' + (compute_age_msg or 'unavailable') + ' &mdash; some metrics may be estimated or from a prior run.'
        html += '</p></div>'
    html += '<div style="background:#f8f8fc;padding:10px 24px;border-top:1px solid #e8e8f0;margin-top:12px;">'
    html += '<p style="color:#9ca3af;font-size:9px;margin:0;text-align:center;">Life Platform v2.36 &middot; ' + date_str + ' &middot; ' + source_str + '</p>'
    html += '<p style="color:#b0b0b0;font-size:8px;margin:4px 0 0;text-align:center;">&#9874;&#65039; Personal health tracking only &mdash; not medical advice. Consult a qualified healthcare professional before making changes to your diet, exercise, or supplement regimen.</p>'
    html += '</div>'
    html += '</div></body></html>'
    return html
