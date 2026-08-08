"""brief_weekly_habits.py — the Sunday Weekly Habit Review of the Daily Brief.

Compute + render, lifted out of `html_builder.py` (#1654 shape) so the module stays
inside its `tests/test_module_size_guard.py` baseline. Pure: no AWS, no wall clock
beyond the one `strptime` that turns a record's own date into a day initial.

`html_builder` re-exports both names — `daily_brief_lambda` imports
`_compute_weekly_habit_review` from there.
"""

from content.brief_format import esc, pct_int


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
        t0_done = int(rec.get("tier0_done", 0))
        t0_total = int(rec.get("tier0_total", 0))
        raw_pct = rec.get("tier0_pct")
        # ADR-104: a day on which NO tier-0 habit was applicable (every T0 habit scoped
        # `applicable_days: weekdays` on a weekend, say) carries no tier0_pct at all —
        # store_habit_scores strips the key because `t0["total"]` is falsy. That is an
        # unmeasured day, not a 0% day, and folding it in as 0.0 halves an honest week.
        if raw_pct is not None:
            t0_pct = float(raw_pct)
        elif t0_total:
            t0_pct = t0_done / t0_total
        else:
            t0_pct = None
        missed = rec.get("missed_tier0") or []
        perfect = (t0_total > 0) and (t0_done == t0_total)
        date_str = rec.get("date", rec.get("sk", "").replace("DATE#", ""))
        daily.append(
            {
                "date": date_str,
                "t0_done": t0_done,
                "t0_total": t0_total,
                "t0_pct": round(t0_pct, 3) if t0_pct is not None else None,
                "perfect": perfect,
                "missed": missed,
                # The habits actually evaluated that day. `tier0_applicable` is written by
                # store_habit_scores; older rows have only the count, so fall back to
                # "the day evaluated something" (tier0_total > 0).
                "applicable": list(rec.get("tier0_applicable") or []),
                "measured": bool(t0_total),
            }
        )
        for h in missed:
            all_missed[h] = all_missed.get(h, 0) + 1

    days = len(daily)
    if days == 0:
        return None

    perfect_days = sum(1 for d in daily if d["perfect"])
    # n is the number of MEASURED days; unmeasured days are excluded, not zeroed (ADR-105).
    avg_t0_raw = [d["t0_pct"] for d in daily if d["t0_pct"] is not None]
    avg_t0_pct = round(sum(avg_t0_raw) / len(avg_t0_raw), 3) if avg_t0_raw else None
    measured_days = len(avg_t0_raw)

    # Per T0 habit breakdown — the denominator is the number of days the habit was
    # actually evaluated, never the window length. scoring_engine.score_habits_registry
    # `continue`s past a habit that was not applicable, so it never reaches tier_status[0]
    # and never reaches missed_tier0 either; crediting that absence as "done" reported a
    # habit missed every day it applied at 4/7.
    t0_habits = []
    for name, meta in registry.items():
        if meta.get("status") == "active" and meta.get("tier", 2) == 0:
            applied = [d for d in daily if (name in d["applicable"] if d["applicable"] else d["measured"])]
            days_total = len(applied)
            days_done = sum(1 for d in applied if name not in d["missed"])
            t0_habits.append(
                {
                    "name": name,
                    "days_done": days_done,
                    "days_total": days_total,
                    "pct": round(days_done / days_total, 3) if days_total else 0,
                }
            )
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
        "days": days,
        "measured_days": measured_days,  # ADR-105: the n behind avg_t0_pct
        "daily": daily,
        "perfect_days": perfect_days,
        "avg_t0_pct": avg_t0_pct,
        "avg_t1_pct": avg_t1_pct,
        "t0_habits": t0_habits,
        "synergy": synergy_summary,
    }


def _render_weekly_habit_review(whr):
    """Render the Sunday Weekly Habit Review section as an HTML string.

    Returns empty string if whr is None.
    """
    if not whr:
        return ""

    days = whr.get("days", 7)
    perfect = whr.get("perfect_days", 0)
    avg_t0 = whr.get("avg_t0_pct", 0)
    measured_days = whr.get("measured_days")
    t0_habits = whr.get("t0_habits", [])
    avg_t1 = whr.get("avg_t1_pct")
    synergy = whr.get("synergy", {})
    daily = whr.get("daily", [])

    # Overall completion colour. Percentages ROUND — int() truncates, and the float the
    # compute layer produces lands just under (0.29 * 100 == 28.999999999999996), so every
    # figure in this section was systematically a point low.
    if avg_t0 is None:
        t0_pct_int = None
        t0_pct_str = "—"
        overall_col = "#94a3b8"
        overall_label = "No measured days"
    else:
        t0_pct_int = pct_int(avg_t0)
        t0_pct_str = str(t0_pct_int)
        if t0_pct_int >= 85:
            overall_col = "#22c55e"
            overall_label = "Strong week"
        elif t0_pct_int >= 65:
            overall_col = "#f59e0b"
            overall_label = "Mixed week"
        else:
            overall_col = "#ef4444"
            overall_label = "Needs attention"

    perfect_pct = pct_int(perfect / days) if days else 0

    # ── Daily mini-bars (Mon-Sun) ────────────────────────────────────────────
    bar_cells = ""
    DAY_ABBR = ["M", "T", "W", "T", "F", "S", "S"]
    for i, d in enumerate(daily):
        d_pct = d.get("t0_pct")
        if d_pct is None:  # nothing was applicable that day — a grey stub, not a red 0
            pct_bar = 8
            bar_col = "#475569"
            done_str = "—"
        else:
            pct_bar = max(8, int(d_pct * 60))
            bar_col = "#22c55e" if d_pct >= 0.85 else "#f59e0b" if d_pct >= 0.65 else "#ef4444"
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
            + '<div style="font-size:9px;color:'
            + bar_col
            + ';font-weight:700;margin-bottom:2px;">'
            + done_str
            + crown
            + "</div>"
            + '<div style="height:'
            + str(pct_bar)
            + "px;background:"
            + bar_col
            + ';border-radius:3px 3px 0 0;min-width:24px;"></div>'
            + '<div style="font-size:8px;color:#94a3b8;margin-top:3px;">'
            + day_abbr
            + "</div>"
            + "</td>"
        )

    bars_html = (
        '<table style="width:100%;border-collapse:collapse;margin:12px 0 4px;">'
        '<tr style="vertical-align:bottom;">' + bar_cells + "</tr></table>"
    )

    # ── Per-habit breakdown rows ─────────────────────────────────────────────
    habit_rows = ""
    for h in t0_habits:
        p = pct_int(h["pct"])
        col = "#22c55e" if p >= 85 else "#f59e0b" if p >= 65 else "#ef4444"
        bar_w = max(4, p)
        flag = " &#9888;" if p <= 50 else ""
        # Habit names come from the S3-hosted habit_registry config: an ampersand or an
        # angle bracket silently corrupted the row.
        short_name = esc(h["name"][:32]) + ("…" if len(h["name"]) > 32 else "")
        habit_rows += (
            "<tr>"
            '<td style="padding:5px 8px 5px 12px;font-size:12px;color:#e2e8f0;width:55%;">' + short_name + flag + "</td>"
            '<td style="padding:5px 8px;width:45%;">'
            '<div style="display:flex;align-items:center;gap:6px;">'
            '<div style="flex:1;background:rgba(255,255,255,0.08);border-radius:3px;height:6px;">'
            '<div style="width:' + str(bar_w) + "%;height:6px;background:" + col + ';border-radius:3px;"></div></div>'
            '<span style="font-size:11px;font-weight:700;color:'
            + col
            + ';min-width:36px;text-align:right;">'
            + str(h["days_done"])
            + "/"
            + str(h["days_total"])
            + "</span>"
            "</div></td>"
            "</tr>"
        )

    # ── Synergy groups ───────────────────────────────────────────────────────
    synergy_html = ""
    if synergy:
        chips = ""
        for group, pct in sorted(synergy.items(), key=lambda x: -x[1]):
            p_int = pct_int(pct)
            col = "#22c55e" if p_int >= 75 else "#f59e0b" if p_int >= 50 else "#ef4444"
            chips += (
                '<span style="display:inline-block;background:rgba(255,255,255,0.06);'
                "border:1px solid " + col + "40;border-radius:12px;"
                "padding:3px 10px;font-size:10px;color:"
                + col
                + ';margin:2px 3px 2px 0;font-weight:600;">'
                + esc(group)
                + " "
                + str(p_int)
                + "%</span>"
            )
        synergy_html = (
            '<div style="margin-top:8px;padding-top:8px;border-top:1px solid rgba(255,255,255,0.08);">'
            '<p style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:1px;margin:0 0 5px;">Synergy Stacks</p>'
            + chips
            + "</div>"
        )

    # ── T1 line ──────────────────────────────────────────────────────────────
    t1_html = ""
    if avg_t1 is not None:
        t1_pct_int = pct_int(avg_t1)
        t1_col = "#22c55e" if t1_pct_int >= 75 else "#f59e0b" if t1_pct_int >= 50 else "#94a3b8"
        t1_html = (
            '<p style="font-size:11px;color:#64748b;margin:6px 0 0;">'
            'Tier 1 avg: <span style="color:' + t1_col + ';font-weight:700;">' + str(t1_pct_int) + "%</span></p>"
        )

    # ADR-105: when the window contains unmeasured days, the mean ships its own n.
    n_note = ""
    if measured_days is not None and measured_days != days:
        n_note = " (n=" + str(measured_days) + " measured)"

    html = (
        "<!-- S2-T1-10: Weekly Habit Review (Sunday only) -->"
        '<div style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.1);'
        'border-radius:12px;padding:16px 20px;margin:0 0 20px;">'
        # Header row
        '<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:4px;">'
        "<div>"
        '<p style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:1.5px;margin:0 0 2px;">&#128197; Weekly Habit Review</p>'
        '<p style="font-size:24px;font-weight:800;color:'
        + overall_col
        + ';margin:0;line-height:1.1;">'
        + t0_pct_str
        + '<span style="font-size:14px;">%</span> T0</p>'
        '<p style="font-size:11px;color:' + overall_col + ';margin:2px 0 0;">' + overall_label + n_note + "</p>"
        "</div>"
        '<div style="text-align:right;">'
        '<p style="font-size:10px;color:#64748b;margin:0 0 2px;">' + str(days) + "-day window</p>"
        '<p style="font-size:20px;font-weight:700;color:#e2e8f0;margin:0;">' + str(perfect) + "/" + str(days) + "</p>"
        '<p style="font-size:10px;color:#94a3b8;margin:2px 0 0;">perfect days (' + str(perfect_pct) + "%)</p>"
        "</div>"
        "</div>"
        # Daily bars
        + bars_html
        # Habit table
        + '<table style="width:100%;border-collapse:collapse;margin-top:8px;">'
        + '<tr><td colspan="2" style="padding:0 0 4px 12px;font-size:10px;color:#64748b;'
        + 'text-transform:uppercase;letter-spacing:1px;">T0 Habits</td></tr>'
        + habit_rows
        + "</table>"
        # T1 line
        + t1_html
        # Synergy
        + synergy_html + "</div>"
    )

    return html
