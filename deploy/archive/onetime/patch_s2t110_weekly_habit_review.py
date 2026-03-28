#!/usr/bin/env python3
"""
patch_s2t110_weekly_habit_review.py — S2-T1-10 Sunday Weekly Habit Review

Patches two files:
  1. lambdas/html_builder.py
     - Adds _compute_weekly_habit_review() helper function
     - Adds _render_weekly_habit_review() HTML renderer
     - Adds weekly_habit_review=None parameter to build_html()
     - Injects section into HTML after the Habits section

  2. lambdas/daily_brief_lambda.py
     - Adds Sunday detection in lambda_handler
     - Fetches 7-day habit_scores range on Sundays
     - Computes weekly_habit_review dict
     - Passes it to html_builder.build_html()

Run from project root:
    python3 deploy/patch_s2t110_weekly_habit_review.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

# ─────────────────────────────────────────────────────────────────────────────
# PART 1 — html_builder.py
# ─────────────────────────────────────────────────────────────────────────────

HTML_BUILDER = ROOT / "lambdas" / "html_builder.py"

WEEKLY_HABIT_HELPERS = '''

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

'''

# Anchor: insert helper functions just before build_html definition
BUILD_HTML_DEF = "def build_html(data, profile, day_grade_score, grade, component_scores, component_details,"

# New signature line (adds weekly_habit_review=None)
OLD_SIGNATURE_LINE = (
    "def build_html(data, profile, day_grade_score, grade, component_scores, component_details,\n"
    "               readiness_score, readiness_colour, tldr_guidance, bod_insight,\n"
    "               training_nutrition, journal_coach_text, mvp_streak, full_streak, vice_streaks=None,\n"
    "               character_sheet=None, brief_mode=\"standard\", engagement_score=None,\n"
    "               triggered_rewards=None, protocol_recs=None,\n"
    "               compute_stale=False, compute_age_msg=\"\"):"
)

NEW_SIGNATURE_LINE = (
    "def build_html(data, profile, day_grade_score, grade, component_scores, component_details,\n"
    "               readiness_score, readiness_colour, tldr_guidance, bod_insight,\n"
    "               training_nutrition, journal_coach_text, mvp_streak, full_streak, vice_streaks=None,\n"
    "               character_sheet=None, brief_mode=\"standard\", engagement_score=None,\n"
    "               triggered_rewards=None, protocol_recs=None,\n"
    "               compute_stale=False, compute_age_msg=\"\",\n"
    "               weekly_habit_review=None):"
)

# The anchor in the HTML body where we inject — after Section 6 (Habits Deep-Dive comment)
# We inject the weekly review right before the Habit Streaks section or after habits section.
# Anchor: the section marker comment for Habit Streaks (Section 9)
INJECT_ANCHOR = "    # --- Section 9: Habit Streaks ---"

INJECT_CONTENT = """    # --- S2-T1-10: Weekly Habit Review (Sunday only) ---
    try:
        if weekly_habit_review:
            html += _render_weekly_habit_review(weekly_habit_review)
    except Exception as _whr_e:
        html += _section_error_html("Weekly Habit Review", _whr_e)

    # --- Section 9: Habit Streaks ---"""


def patch_html_builder():
    src = HTML_BUILDER.read_text(encoding="utf-8")
    changed = False

    # 1. Guard: already patched?
    if "weekly_habit_review=None" in src:
        print("[INFO] html_builder.py: weekly_habit_review already present — skipping signature patch")
    else:
        if OLD_SIGNATURE_LINE not in src:
            print("[ERROR] html_builder.py: could not find build_html signature anchor")
            print("        Expected:\n" + OLD_SIGNATURE_LINE[:120])
            return False
        src = src.replace(OLD_SIGNATURE_LINE, NEW_SIGNATURE_LINE, 1)
        print("[OK]   html_builder.py: build_html signature updated")
        changed = True

    # 2. Insert helper functions before build_html
    if "_render_weekly_habit_review" in src:
        print("[INFO] html_builder.py: helpers already present — skipping helper insert")
    else:
        if BUILD_HTML_DEF not in src:
            print("[ERROR] html_builder.py: could not find build_html def for helper insert")
            return False
        src = src.replace(BUILD_HTML_DEF, WEEKLY_HABIT_HELPERS + BUILD_HTML_DEF, 1)
        print("[OK]   html_builder.py: weekly habit review helpers inserted")
        changed = True

    # 3. Inject section call into HTML body
    if "_render_weekly_habit_review(weekly_habit_review)" in src:
        print("[INFO] html_builder.py: section injection already present — skipping")
    else:
        if INJECT_ANCHOR not in src:
            print("[WARN] html_builder.py: Habit Streaks section anchor not found — appending near end of html assembly instead")
            # Fallback: inject before closing html assembly comment
            fallback_anchor = "    # --- Footer ---"
            if fallback_anchor in src:
                fallback_inject = (
                    "    # --- S2-T1-10: Weekly Habit Review (Sunday only) ---\n"
                    "    try:\n"
                    "        if weekly_habit_review:\n"
                    "            html += _render_weekly_habit_review(weekly_habit_review)\n"
                    "    except Exception as _whr_e:\n"
                    "        html += _section_error_html(\"Weekly Habit Review\", _whr_e)\n\n"
                    "    # --- Footer ---"
                )
                src = src.replace(fallback_anchor, fallback_inject, 1)
                print("[OK]   html_builder.py: section injection inserted (fallback anchor)")
                changed = True
            else:
                print("[ERROR] html_builder.py: no suitable injection anchor found")
                return False
        else:
            src = src.replace(INJECT_ANCHOR, INJECT_CONTENT, 1)
            print("[OK]   html_builder.py: weekly habit review section call injected")
            changed = True

    if changed:
        HTML_BUILDER.write_text(src, encoding="utf-8")
        print("[OK]   html_builder.py written")
    else:
        print("[INFO] html_builder.py: no changes needed")
    return True


# ─────────────────────────────────────────────────────────────────────────────
# PART 2 — daily_brief_lambda.py
# ─────────────────────────────────────────────────────────────────────────────

DAILY_BRIEF = ROOT / "lambdas" / "daily_brief_lambda.py"

# We need to:
# 1. After gathering habit_7d data (already fetched by daily-insight-compute path),
#    detect Sunday and build weekly_habit_review
# 2. Pass it to html_builder.build_html()

# Anchor 1: the line that calls _compute_deficit_ceiling_alert — this is near end of the
# "intelligence" block. We insert Sunday detection AFTER all IC signals, BEFORE build_ai_context_block.
# Actually, the cleanest anchor is the build_html call.

OLD_BUILD_HTML_CALL = (
    "    try:\n"
    "        html = html_builder.build_html(\n"
    "            data, profile, day_grade_score, grade, component_scores, component_details,\n"
    "            readiness_score, readiness_colour, tldr_guidance, bod_insight,\n"
    "            training_nutrition, journal_coach_text, mvp_streak, full_streak, vice_streaks,\n"
    "            character_sheet=character_sheet, brief_mode=brief_mode,\n"
    "            engagement_score=engagement_score,\n"
    "            triggered_rewards=triggered_rewards, protocol_recs=protocol_recs,\n"
    "            compute_stale=_compute_stale, compute_age_msg=_compute_age_msg)"
)

NEW_BUILD_HTML_CALL = (
    "    # ── S2-T1-10: Weekly Habit Review (Sunday only) ──────────────────────────────\n"
    "    _weekly_habit_review = None\n"
    "    try:\n"
    "        import calendar\n"
    "        _is_sunday = (datetime.now(timezone.utc).weekday() == 6)  # 6 = Sunday\n"
    "        if _is_sunday:\n"
    "            # Fetch 7-day habit_scores for the review\n"
    "            _whr_habit_7d = fetch_range(\n"
    "                \"habit_scores\",\n"
    "                (datetime.now(timezone.utc).date() - timedelta(days=7)).isoformat(),\n"
    "                yesterday,\n"
    "            )\n"
    "            if _whr_habit_7d:\n"
    "                from html_builder import _compute_weekly_habit_review\n"
    "                _weekly_habit_review = _compute_weekly_habit_review(_whr_habit_7d, profile)\n"
    "                print(\"[INFO] S2-T1-10: Weekly Habit Review computed for Sunday brief\")\n"
    "            else:\n"
    "                print(\"[WARN] S2-T1-10: No habit_scores data for weekly review\")\n"
    "    except Exception as _whr_err:\n"
    "        print(\"[WARN] S2-T1-10: Weekly habit review failed (non-fatal): \" + str(_whr_err))\n"
    "\n"
    "    try:\n"
    "        html = html_builder.build_html(\n"
    "            data, profile, day_grade_score, grade, component_scores, component_details,\n"
    "            readiness_score, readiness_colour, tldr_guidance, bod_insight,\n"
    "            training_nutrition, journal_coach_text, mvp_streak, full_streak, vice_streaks,\n"
    "            character_sheet=character_sheet, brief_mode=brief_mode,\n"
    "            engagement_score=engagement_score,\n"
    "            triggered_rewards=triggered_rewards, protocol_recs=protocol_recs,\n"
    "            compute_stale=_compute_stale, compute_age_msg=_compute_age_msg,\n"
    "            weekly_habit_review=_weekly_habit_review)"
)


def patch_daily_brief():
    src = DAILY_BRIEF.read_text(encoding="utf-8")
    changed = False

    if "_weekly_habit_review" in src:
        print("[INFO] daily_brief_lambda.py: S2-T1-10 already present — skipping")
        return True

    if OLD_BUILD_HTML_CALL not in src:
        print("[ERROR] daily_brief_lambda.py: could not find build_html call anchor")
        print("        Searched for:\n" + OLD_BUILD_HTML_CALL[:200])
        # Try a simpler anchor
        simple_anchor = "        html = html_builder.build_html("
        if simple_anchor in src:
            print("[INFO]  Attempting simpler anchor match...")
            # Find the full block
            idx = src.find(simple_anchor)
            block_end_marker = "            compute_stale=_compute_stale, compute_age_msg=_compute_age_msg)"
            if block_end_marker in src:
                old_block_start = src.rfind("    try:\n        html = html_builder.build_html(", 0, idx + 50)
                old_block = src[old_block_start : src.find(block_end_marker) + len(block_end_marker)]
                src = src.replace(old_block, NEW_BUILD_HTML_CALL, 1)
                print("[OK]   daily_brief_lambda.py: build_html call patched (simple anchor)")
                changed = True
            else:
                print("[ERROR] daily_brief_lambda.py: compute_age_msg marker not found either")
                return False
        else:
            return False
    else:
        src = src.replace(OLD_BUILD_HTML_CALL, NEW_BUILD_HTML_CALL, 1)
        print("[OK]   daily_brief_lambda.py: build_html call patched")
        changed = True

    if changed:
        DAILY_BRIEF.write_text(src, encoding="utf-8")
        print("[OK]   daily_brief_lambda.py written")
    return True


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("S2-T1-10: Weekly Habit Review patch")
    print("=" * 60)

    ok1 = patch_html_builder()
    ok2 = patch_daily_brief()

    if ok1 and ok2:
        print()
        print("[DONE] All patches applied successfully.")
        print()
        print("Next steps:")
        print("  1. Run: python3 -m pytest tests/ -x -q")
        print("  2. Deploy daily-brief Lambda:")
        print("     bash deploy/deploy_lambda.sh daily-brief")
        print("  3. Deploy MCP Lambda (html_builder is packaged with MCP):")
        print("     rm -f /tmp/mcp_deploy.zip && zip -j /tmp/mcp_deploy.zip mcp_server.py mcp_bridge.py && zip -r /tmp/mcp_deploy.zip mcp/ && zip -j /tmp/mcp_deploy.zip lambdas/digest_utils.py && aws lambda update-function-code --function-name life-platform-mcp --zip-file fileb:///tmp/mcp_deploy.zip --no-cli-pager > /dev/null && echo 'MCP deployed'")
        print()
        print("The Weekly Habit Review section will appear in Sunday's Daily Brief automatically.")
        print("Test it: invoke daily-brief Lambda with {\"date\": \"<last Sunday>\", \"force_sunday\": true}")
        sys.exit(0)
    else:
        print()
        print("[FAIL] One or more patches failed. Check output above.")
        sys.exit(1)
