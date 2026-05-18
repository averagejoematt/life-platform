#!/usr/bin/env python3
"""
Patch: Journal Phase 4 — Wire journal signals into daily brief + weekly digest.

Daily Brief:
  - Fetch yesterday's journal entries (morning + evening) from DynamoDB
  - Feed mood/stress/themes into the Haiku insight prompt
  - Add "Journal Pulse" section to HTML (mood, energy, stress, notable quote)

Weekly Digest:
  - New ex_journal() extractor for 7 days of entries
  - Add journal summary to Haiku board prompt data
  - Add Journal & Mood section to HTML with mood/energy/stress averages
  - Update Coach Maya's instructions to reference journal signals
  - Add Notion to footer source list
"""

import re

# ══════════════════════════════════════════════════════════════════════════════
# DAILY BRIEF PATCH
# ══════════════════════════════════════════════════════════════════════════════

def patch_daily_brief(code: str) -> str:
    # ── 1. Add journal fetch function after fetch_range ──
    journal_fetch_fn = '''

def fetch_journal_entries(date_str):
    """Fetch all journal entries for a date (morning, evening, stressor, etc.)."""
    try:
        r = table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={
                ":pk": "USER#matthew#SOURCE#notion",
                ":prefix": f"DATE#{date_str}#journal#"
            })
        return r.get("Items", [])
    except Exception as e:
        print(f"[WARN] fetch_journal_entries: {e}")
        return []


def extract_journal_signals(entries):
    """Extract mood, energy, stress, themes, notable_quote from enriched journal entries."""
    if not entries:
        return None

    mood_scores = []
    energy_scores = []
    stress_scores = []
    all_themes = []
    all_emotions = []
    notable_quote = None
    templates_found = []

    for entry in entries:
        entry = d2f(entry)
        template = entry.get("template", "")
        templates_found.append(template)

        # Enriched fields (from Haiku enrichment Lambda)
        m = entry.get("enriched_mood")
        e = entry.get("enriched_energy")
        s = entry.get("enriched_stress")
        if m is not None: mood_scores.append(float(m))
        if e is not None: energy_scores.append(float(e))
        if s is not None: stress_scores.append(float(s))

        themes = entry.get("enriched_themes") or []
        if isinstance(themes, list):
            all_themes.extend(themes)

        emotions = entry.get("enriched_emotions") or []
        if isinstance(emotions, list):
            all_emotions.extend(emotions)

        # Prefer evening notable_quote, fallback to morning
        q = entry.get("enriched_notable_quote")
        if q and (template.lower() == "evening" or notable_quote is None):
            notable_quote = str(q)

        # Fallback to structured scores if enriched not available
        if m is None:
            for field in ("morning_mood", "day_rating"):
                val = entry.get(field)
                if val is not None:
                    mood_scores.append(float(val))
                    break
        if e is None:
            for field in ("morning_energy", "energy_eod"):
                val = entry.get(field)
                if val is not None:
                    energy_scores.append(float(val))
                    break
        if s is None:
            val = entry.get("stress_level")
            if val is not None:
                stress_scores.append(float(val))

    return {
        "mood_avg": round(sum(mood_scores)/len(mood_scores), 1) if mood_scores else None,
        "energy_avg": round(sum(energy_scores)/len(energy_scores), 1) if energy_scores else None,
        "stress_avg": round(sum(stress_scores)/len(stress_scores), 1) if stress_scores else None,
        "themes": list(dict.fromkeys(all_themes))[:4],  # dedupe, keep order, max 4
        "emotions": list(dict.fromkeys(all_emotions))[:5],
        "notable_quote": notable_quote,
        "templates": templates_found,
    }
'''
    # Insert after the fetch_range function definition
    anchor = "def safe_float(rec, field):"
    code = code.replace(anchor, journal_fetch_fn + anchor)

    # ── 2. Add journal to gather_daily_data() ──
    old_gather_return = '''    return {
        "date": yesterday,
        "whoop":  whoop,
        "sleep":  sleep,
        "hrv":    {"hrv_7d": hrv_7d_avg, "hrv_30d": hrv_30d_avg,
                   "hrv_yesterday": safe_float(whoop, "hrv")},
        "tsb":    tsb,
        "recovery": safe_float(whoop, "recovery_score"),
        "strain":   safe_float(whoop, "strain"),
        "sleep_score":    safe_float(sleep, "sleep_score"),
        "sleep_duration": (safe_float(sleep, "total_sleep_seconds") or 0) / 3600 or None,
        "sleep_efficiency": safe_float(sleep, "sleep_efficiency"),
        "rhr": safe_float(whoop, "resting_heart_rate"),
        "anomaly": anomaly,
    }'''
    new_gather_return = '''    # Journal entries (morning + evening)
    journal_entries = fetch_journal_entries(yesterday)
    journal = extract_journal_signals(journal_entries)

    return {
        "date": yesterday,
        "whoop":  whoop,
        "sleep":  sleep,
        "hrv":    {"hrv_7d": hrv_7d_avg, "hrv_30d": hrv_30d_avg,
                   "hrv_yesterday": safe_float(whoop, "hrv")},
        "tsb":    tsb,
        "recovery": safe_float(whoop, "recovery_score"),
        "strain":   safe_float(whoop, "strain"),
        "sleep_score":    safe_float(sleep, "sleep_score"),
        "sleep_duration": (safe_float(sleep, "total_sleep_seconds") or 0) / 3600 or None,
        "sleep_efficiency": safe_float(sleep, "sleep_efficiency"),
        "rhr": safe_float(whoop, "resting_heart_rate"),
        "anomaly": anomaly,
        "journal": journal,
    }'''
    code = code.replace(old_gather_return, new_gather_return)

    # ── 3. Add journal data to Haiku insight prompt payload ──
    old_payload = '''    payload_data = {
        "date": clean.get("date"),
        "recovery_score": clean.get("recovery"),
        "sleep_score": clean.get("sleep_score"),
        "sleep_duration_hrs": round(clean.get("sleep_duration") or 0, 1),
        "sleep_efficiency": clean.get("sleep_efficiency"),
        "hrv_yesterday": clean["hrv"].get("hrv_yesterday"),
        "hrv_7d_avg": clean["hrv"].get("hrv_7d"),
        "hrv_30d_avg": clean["hrv"].get("hrv_30d"),
        "resting_hr": clean.get("rhr"),
        "strain_yesterday": clean.get("strain"),
        "tsb_form": clean.get("tsb"),
    }'''
    new_payload = '''    journal = clean.get("journal") or {}
    payload_data = {
        "date": clean.get("date"),
        "recovery_score": clean.get("recovery"),
        "sleep_score": clean.get("sleep_score"),
        "sleep_duration_hrs": round(clean.get("sleep_duration") or 0, 1),
        "sleep_efficiency": clean.get("sleep_efficiency"),
        "hrv_yesterday": clean["hrv"].get("hrv_yesterday"),
        "hrv_7d_avg": clean["hrv"].get("hrv_7d"),
        "hrv_30d_avg": clean["hrv"].get("hrv_30d"),
        "resting_hr": clean.get("rhr"),
        "strain_yesterday": clean.get("strain"),
        "tsb_form": clean.get("tsb"),
        "journal_mood": journal.get("mood_avg"),
        "journal_energy": journal.get("energy_avg"),
        "journal_stress": journal.get("stress_avg"),
        "journal_themes": journal.get("themes", []),
        "journal_emotions": journal.get("emotions", []),
    }'''
    code = code.replace(old_payload, new_payload)

    # ── 4. Add Journal Pulse section to HTML (between anomaly and insight) ──
    old_insight_box = '''    # Insight box
    insight_html = ""
    if insight:'''
    new_journal_and_insight = '''    # Journal Pulse section
    journal_html = ""
    journal = data.get("journal")
    if journal:
        mood_val = journal.get("mood_avg")
        energy_val = journal.get("energy_avg")
        stress_val = journal.get("stress_avg")

        def mood_emoji(val):
            if val is None: return "—", "#888"
            if val >= 4: return "😊", "#059669"
            if val >= 3: return "😐", "#d97706"
            return "😔", "#dc2626"

        def stress_emoji(val):
            if val is None: return "—", "#888"
            if val <= 2: return "😌", "#059669"
            if val <= 3: return "😐", "#d97706"
            return "😰", "#dc2626"

        mood_e, mood_c = mood_emoji(mood_val)
        energy_e, energy_c = mood_emoji(energy_val)
        stress_e, stress_c = stress_emoji(stress_val)

        def signal_cell(label, val, emoji, color):
            v = f"{val}/5" if val is not None else "—"
            return (f'<td style="text-align:center;padding:8px 10px;">'
                    f'<div style="font-size:18px;">{emoji}</div>'
                    f'<div style="font-size:16px;font-weight:700;color:{color};">{v}</div>'
                    f'<div style="font-size:10px;color:#9ca3af;margin-top:2px;">{label}</div>'
                    f'</td>')

        signals_row = (
            f'<table style="width:100%;border-collapse:collapse;">'
            f'<tr>{signal_cell("Mood", mood_val, mood_e, mood_c)}'
            f'{signal_cell("Energy", energy_val, energy_e, energy_c)}'
            f'{signal_cell("Stress", stress_val, stress_e, stress_c)}</tr>'
            f'</table>'
        )

        themes_html = ""
        if journal.get("themes"):
            chips = " ".join(
                f'<span style="display:inline-block;background:#f0f4ff;color:#4a6cf7;'
                f'font-size:10px;padding:2px 8px;border-radius:10px;margin:2px 2px;">{t}</span>'
                for t in journal["themes"][:4]
            )
            themes_html = f'<div style="margin-top:8px;text-align:center;">{chips}</div>'

        quote_html = ""
        if journal.get("notable_quote"):
            q = journal["notable_quote"]
            quote_html = (
                f'<div style="margin-top:10px;padding:8px 12px;border-left:3px solid #c7d2fe;'
                f'background:#f8f9ff;border-radius:0 6px 6px 0;">'
                f'<p style="font-size:12px;color:#4338ca;font-style:italic;margin:0;line-height:1.5;">'
                f'"{q}"</p></div>'
            )

        templates = journal.get("templates", [])
        template_label = " + ".join(dict.fromkeys(t.title() for t in templates)) if templates else "Journal"

        journal_html = (
            f'<div style="background:#faf5ff;border-left:3px solid #8b5cf6;'
            f'border-radius:0 8px 8px 0;padding:12px 16px;margin-top:16px;">'
            f'<p style="font-size:11px;font-weight:700;color:#6d28d9;margin:0 0 8px;'
            f'text-transform:uppercase;letter-spacing:0.5px;">📓 Journal Pulse · {template_label}</p>'
            f'{signals_row}'
            f'{themes_html}'
            f'{quote_html}'
            f'</div>'
        )

    # Insight box
    insight_html = ""
    if insight:'''
    code = code.replace(old_insight_box, new_journal_and_insight)

    # ── 5. Insert journal_html into HTML template (after anomaly, before insight) ──
    old_insight_placement = '      {anomaly_html}\n      {insight_html}'
    new_insight_placement = '      {anomaly_html}\n      {journal_html}\n      {insight_html}'
    code = code.replace(old_insight_placement, new_insight_placement)

    # ── 6. Add journal to gather log line ──
    old_log = '''    print(f"[INFO] Date: {data['date']} | recovery={data.get('recovery')} "
          f"| sleep={data.get('sleep_score')} | HRV 7d={data['hrv'].get('hrv_7d')} "
          f"| TSB={data.get('tsb')}")'''
    new_log = '''    j = data.get("journal") or {}
    print(f"[INFO] Date: {data['date']} | recovery={data.get('recovery')} "
          f"| sleep={data.get('sleep_score')} | HRV 7d={data['hrv'].get('hrv_7d')} "
          f"| TSB={data.get('tsb')} | journal_mood={j.get('mood_avg')} "
          f"| journal_stress={j.get('stress_avg')}")'''
    code = code.replace(old_log, new_log)

    # ── 7. Update footer to include Notion ──
    old_footer = "Life Platform · Yesterday: {date_str} · Whoop · Eight Sleep · Strava"
    new_footer = "Life Platform · Yesterday: {date_str} · Whoop · Eight Sleep · Strava · Notion Journal"
    code = code.replace(old_footer, new_footer)

    # ── 8. Update version comment ──
    code = code.replace(
        '"""\nDaily Brief Lambda — v1.0.0',
        '"""\nDaily Brief Lambda — v1.1.0 (Journal Phase 4)'
    )

    return code


# ══════════════════════════════════════════════════════════════════════════════
# WEEKLY DIGEST PATCH
# ══════════════════════════════════════════════════════════════════════════════

def patch_weekly_digest(code: str) -> str:

    # ── 1. Add ex_journal extractor after ex_chronicling ──
    journal_extractor = '''

def ex_journal(date_lists):
    """Extract journal signals from raw DynamoDB entries across a week of dates.

    date_lists: list of date strings to query (e.g. dates_back output).
    Returns aggregated mood/energy/stress with daily breakdown.
    """
    all_entries = []
    for d in date_lists:
        try:
            r = table.query(
                KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
                ExpressionAttributeValues={
                    ":pk": "USER#matthew#SOURCE#notion",
                    ":prefix": f"DATE#{d}#journal#"
                })
            all_entries.extend(r.get("Items", []))
        except Exception as e:
            print(f"[WARN] ex_journal {d}: {e}")

    if not all_entries:
        return None

    mood_scores, energy_scores, stress_scores = [], [], []
    all_themes, all_emotions, all_avoidance = [], [], []
    all_cognitive = []
    notable_quotes = []
    templates_count = {}
    daily_mood = {}  # date -> [scores]

    for entry in all_entries:
        entry = d2f(entry)
        template = str(entry.get("template", ""))
        templates_count[template] = templates_count.get(template, 0) + 1
        date = str(entry.get("date", ""))

        m = entry.get("enriched_mood")
        e = entry.get("enriched_energy")
        s = entry.get("enriched_stress")

        if m is not None:
            mood_scores.append(float(m))
            daily_mood.setdefault(date, []).append(float(m))
        if e is not None: energy_scores.append(float(e))
        if s is not None: stress_scores.append(float(s))

        # Fallback to structured scores
        if m is None:
            for field in ("morning_mood", "day_rating"):
                val = entry.get(field)
                if val is not None:
                    mood_scores.append(float(val))
                    daily_mood.setdefault(date, []).append(float(val))
                    break
        if e is None:
            for field in ("morning_energy", "energy_eod"):
                val = entry.get(field)
                if val is not None:
                    energy_scores.append(float(val))
                    break
        if s is None:
            val = entry.get("stress_level")
            if val is not None:
                stress_scores.append(float(val))

        for t in (entry.get("enriched_themes") or []):
            all_themes.append(str(t))
        for em in (entry.get("enriched_emotions") or []):
            all_emotions.append(str(em))
        for av in (entry.get("enriched_avoidance_flags") or []):
            all_avoidance.append(str(av))
        for cp in (entry.get("enriched_cognitive_patterns") or []):
            all_cognitive.append(str(cp))

        q = entry.get("enriched_notable_quote")
        if q:
            notable_quotes.append({"date": date, "template": template, "quote": str(q)})

    # Theme frequency
    theme_freq = {}
    for t in all_themes:
        theme_freq[t] = theme_freq.get(t, 0) + 1
    top_themes = sorted(theme_freq.items(), key=lambda x: -x[1])[:6]

    # Emotion frequency
    emotion_freq = {}
    for em in all_emotions:
        emotion_freq[em] = emotion_freq.get(em, 0) + 1
    top_emotions = sorted(emotion_freq.items(), key=lambda x: -x[1])[:6]

    # Best/worst mood days
    daily_mood_avg = {d: round(sum(v)/len(v), 1) for d, v in daily_mood.items() if v}
    best_day = max(daily_mood_avg.items(), key=lambda x: x[1], default=(None, None))
    worst_day = min(daily_mood_avg.items(), key=lambda x: x[1], default=(None, None))

    return {
        "mood_avg": avg(mood_scores),
        "energy_avg": avg(energy_scores),
        "stress_avg": avg(stress_scores),
        "entries": len(all_entries),
        "days_journaled": len(set(str(e.get("date","")) for e in all_entries)),
        "templates": templates_count,
        "top_themes": top_themes,
        "top_emotions": top_emotions,
        "avoidance_flags": list(dict.fromkeys(all_avoidance))[:5],
        "cognitive_patterns": list(dict.fromkeys(all_cognitive))[:5],
        "notable_quotes": notable_quotes[:3],
        "best_mood_day": {"date": best_day[0], "score": best_day[1]} if best_day[0] else None,
        "worst_mood_day": {"date": worst_day[0], "score": worst_day[1]} if worst_day[0] else None,
    }

'''
    anchor = "\n# ══════════════════════════════════════════════════════════════════════════════\n# TRAINING LOAD (Banister)"
    code = code.replace(anchor, journal_extractor + anchor)

    # ── 2. Add journal to gather_all() ──
    old_scorecard_line = '    scorecard = compute_scorecard(this, training_load)'
    new_scorecard_line = '''    # Journal data (queries directly — not in the source loop since SK is different)
    journal_this  = ex_journal(w1)
    journal_prior = ex_journal(w2)

    scorecard = compute_scorecard(this, training_load)'''
    code = code.replace(old_scorecard_line, new_scorecard_line)

    old_gather_return = '''    return {"this": this, "prior": prior, "training_load": training_load,
            "trends": trends, "sleep_debt": sleep_debt, "projection": projection,
            "scorecard": scorecard, "profile": profile,
            "open_insights": open_insights,
            "dates": {"this": w1, "prior": w2}}'''
    new_gather_return = '''    return {"this": this, "prior": prior, "training_load": training_load,
            "trends": trends, "sleep_debt": sleep_debt, "projection": projection,
            "scorecard": scorecard, "profile": profile,
            "open_insights": open_insights,
            "journal_this": journal_this, "journal_prior": journal_prior,
            "dates": {"this": w1, "prior": w2}}'''
    code = code.replace(old_gather_return, new_gather_return)

    # ── 3. Add journal data to Haiku prompt payload ──
    old_trim = '''    # Trim activities for token economy
    for wk in ("this","prior"):
        if pd.get(wk,{}).get("strava"):
            pd[wk]["strava"]["activities"] = pd[wk]["strava"].get("activities",[])[:5]'''
    new_trim = '''    # Trim activities for token economy
    for wk in ("this","prior"):
        if pd.get(wk,{}).get("strava"):
            pd[wk]["strava"]["activities"] = pd[wk]["strava"].get("activities",[])[:5]

    # Add journal data at top level for easy reference
    pd["journal_this_week"] = pd.pop("journal_this", None)
    pd["journal_prior_week"] = pd.pop("journal_prior", None)'''
    code = code.replace(old_trim, new_trim)

    # ── 4. Update Coach Maya's instructions in the board prompt ──
    old_maya = '''🧠 COACH MAYA RODRIGUEZ — BEHAVIOURAL PERFORMANCE
Domain: the gap between knowing and doing. Friction. Adherence patterns. The human behind the data.
Key question to answer: Not what happened — WHY. Where did Matthew underperform relative to his own standards, and what does the pattern suggest is the underlying cause? Look at P40 habit data for behavioural signals. This is the most important section. Be direct and human — speak to Matthew, not about him.'''
    new_maya = '''🧠 COACH MAYA RODRIGUEZ — BEHAVIOURAL PERFORMANCE
Domain: the gap between knowing and doing. Friction. Adherence patterns. The human behind the data.
Key question to answer: Not what happened — WHY. Where did Matthew underperform relative to his own standards, and what does the pattern suggest is the underlying cause? Look at P40 habit data AND journal data for behavioural signals — journal themes, avoidance flags, cognitive patterns, and mood trends reveal what the numbers cannot. Connect subjective journal signals with objective wearable data. This is the most important section. Be direct and human — speak to Matthew, not about him.'''
    code = code.replace(old_maya, new_maya)

    # ── 5. Add Journal & Mood section to HTML (after habits section, before recovery) ──
    old_recovery_section = '    recovery_section = section("Recovery & HRV","❤️", tbl(rec_rows)) if rec_rows else ""'
    new_journal_section = '''    # ── Journal & Mood ──
    jn_rows = ""
    jt = data.get("journal_this")
    jp = data.get("journal_prior")
    if jt:
        def mood_color(val, invert=False):
            if val is None: return "#888"
            if invert:
                return "#27ae60" if val <= 2 else "#e67e22" if val <= 3 else "#e74c3c"
            return "#e74c3c" if val < 3 else "#e67e22" if val < 4 else "#27ae60"

        mc = mood_color(jt.get("mood_avg"))
        ec = mood_color(jt.get("energy_avg"))
        sc = mood_color(jt.get("stress_avg"), invert=True)

        jn_rows += row("Avg Mood",
            f'<span style="color:{mc};font-weight:700;">{fmt(jt.get("mood_avg"))}/5</span>',
            delta_html(jt.get("mood_avg"), jp.get("mood_avg") if jp else None) if jp else "", highlight=True)
        jn_rows += row("Avg Energy",
            f'<span style="color:{ec};font-weight:700;">{fmt(jt.get("energy_avg"))}/5</span>',
            delta_html(jt.get("energy_avg"), jp.get("energy_avg") if jp else None) if jp else "")
        jn_rows += row("Avg Stress",
            f'<span style="color:{sc};font-weight:700;">{fmt(jt.get("stress_avg"))}/5</span>',
            delta_html(jt.get("stress_avg"), jp.get("stress_avg") if jp else None, invert=True) if jp else "")
        jn_rows += row("Entries / Days",
            f'{jt.get("entries", 0)} entries across {jt.get("days_journaled", 0)} days')

        if jt.get("top_themes"):
            theme_chips = " ".join(
                f'<span style="display:inline-block;background:#f0f4ff;color:#4a6cf7;'
                f'font-size:11px;padding:2px 8px;border-radius:10px;margin:2px;">{t} ({c})</span>'
                for t, c in jt["top_themes"][:5]
            )
            jn_rows += row("Top Themes", theme_chips)

        if jt.get("top_emotions"):
            emo_chips = " ".join(
                f'<span style="display:inline-block;background:#fef3c7;color:#92400e;'
                f'font-size:11px;padding:2px 8px;border-radius:10px;margin:2px;">{e} ({c})</span>'
                for e, c in jt["top_emotions"][:5]
            )
            jn_rows += row("Top Emotions", emo_chips)

        if jt.get("avoidance_flags"):
            av_items = ", ".join(jt["avoidance_flags"][:3])
            jn_rows += row("⚠ Avoidance Flags", f'<span style="color:#dc2626;">{av_items}</span>')

        if jt.get("cognitive_patterns"):
            cp_items = ", ".join(jt["cognitive_patterns"][:3])
            jn_rows += row("Cognitive Patterns", cp_items)

        if jt.get("best_mood_day") and jt["best_mood_day"].get("date"):
            jn_rows += row("😊 Best Mood Day",
                f'{jt["best_mood_day"]["date"]} ({jt["best_mood_day"]["score"]}/5)')
        if jt.get("worst_mood_day") and jt["worst_mood_day"].get("date"):
            jn_rows += row("😔 Worst Mood Day",
                f'{jt["worst_mood_day"]["date"]} ({jt["worst_mood_day"]["score"]}/5)')

        if jt.get("notable_quotes"):
            for nq in jt["notable_quotes"][:2]:
                jn_rows += row(f'📝 {nq["date"]}',
                    f'<span style="font-style:italic;color:#4338ca;">"{nq["quote"]}"</span>')

    journal_section = section("Journal & Mood","📓", tbl(jn_rows)) if jn_rows else ""

    recovery_section = section("Recovery & HRV","❤️", tbl(rec_rows)) if rec_rows else ""'''
    code = code.replace(old_recovery_section, new_journal_section)

    # ── 6. Insert journal_section into HTML template ──
    old_html_sections = '''      {habits_section}
      {recovery_section}'''
    new_html_sections = '''      {habits_section}
      {journal_section}
      {recovery_section}'''
    code = code.replace(old_html_sections, new_html_sections)

    # ── 7. Update footer to include Notion ──
    old_footer = "Life Platform v3 · Whoop · Eight Sleep · Withings · Strava · Hevy · MacroFactor · Todoist · Chronicling · AWS us-west-2"
    new_footer = "Life Platform v3 · Whoop · Eight Sleep · Withings · Strava · Hevy · MacroFactor · Todoist · Chronicling · Notion Journal · AWS us-west-2"
    code = code.replace(old_footer, new_footer)

    # ── 8. Update version ──
    code = code.replace(
        '"""\nWeekly Digest Lambda — v3.2.0',
        '"""\nWeekly Digest Lambda — v3.3.0 (Journal Phase 4)'
    )

    return code


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import os

    base = os.path.dirname(os.path.abspath(__file__))

    # Patch Daily Brief
    brief_path = os.path.join(base, "daily_brief_lambda.py")
    with open(brief_path, "r") as f:
        brief_code = f.read()
    patched_brief = patch_daily_brief(brief_code)
    with open(brief_path, "w") as f:
        f.write(patched_brief)
    print(f"✅ Patched daily_brief_lambda.py → v1.1.0")

    # Patch Weekly Digest
    digest_path = os.path.join(base, "weekly_digest_lambda.py")
    with open(digest_path, "r") as f:
        digest_code = f.read()
    patched_digest = patch_weekly_digest(digest_code)
    with open(digest_path, "w") as f:
        f.write(patched_digest)
    print(f"✅ Patched weekly_digest_lambda.py → v3.3.0")

    print("\nNext: run deploy_journal_phase4.sh to deploy both Lambdas")
