#!/usr/bin/env python3
"""
Patch: Demo Mode / Sanitize for Sharing (v2.2.3)

Adds profile-driven HTML sanitization so Matthew can generate a "demo" version
of the daily brief with sensitive data redacted — safe to share with coworkers/friends.

Trigger: invoke Lambda with {"demo_mode": true}

Components:
1. Section markers (<!-- S:name -->) in build_html for section-level hiding
2. sanitize_for_demo() function reads rules from profile["demo_mode_rules"]
3. Handler checks event["demo_mode"], applies sanitization, prefixes subject

Profile rules (DynamoDB, updatable without deploy):
- redact_patterns: list of words to replace with "[redacted]"
- replace_values: map of field names → replacement text (uses actual data values)
- hide_sections: list of section names to strip entirely
- subject_prefix: e.g. "[DEMO]"
"""

LAMBDA_FILE = "daily_brief_lambda.py"


# ── Section markers to add ──
# Each tuple: (unique_string_before, marker_open, unique_string_after, marker_close)
# For html += var patterns: wrap the append
# For inline sections: add markers around the block

SECTION_MARKERS = [
    # Scorecard
    {
        "find": """    html += '<div style="padding:12px 8px 4px;">'
    html += '<p style="font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:1px;margin:0 8px 6px;font-weight:600;">Yesterday\\'s Scorecard</p>'""",
        "replace": """    html += '<!-- S:scorecard -->'
    html += '<div style="padding:12px 8px 4px;">'
    html += '<p style="font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:1px;margin:0 8px 6px;font-weight:600;">Yesterday\\'s Scorecard</p>'""",
    },
    {
        "find": "    html += '</tr></table></div>'\n\n    # -- Readiness",
        "replace": "    html += '</tr></table></div>'\n    html += '<!-- /S:scorecard -->'\n\n    # -- Readiness",
    },
    # Readiness
    {
        "find": """    html += '<div style="background:' + rc["bg"] + ';border-top:2px solid""",
        "replace": """    html += '<!-- S:readiness -->'
    html += '<div style="background:' + rc["bg"] + ';border-top:2px solid""",
    },
    {
        "find": """    html += '</div>'\n\n    # -- Training Report""",
        "replace": """    html += '</div>'\n    html += '<!-- /S:readiness -->'\n\n    # -- Training Report""",
    },
    # Training Report: wrap html += tc
    {
        "find": "        html += tc\n\n    # -- Nutrition Report",
        "replace": "        html += '<!-- S:training -->' + tc + '<!-- /S:training -->'\n\n    # -- Nutrition Report",
    },
    # Nutrition Report: wrap html += nc
    {
        "find": "        html += nc\n\n    # -- Habits Deep-Dive",
        "replace": "        html += '<!-- S:nutrition -->' + nc + '<!-- /S:nutrition -->'\n\n    # -- Habits Deep-Dive",
    },
    # Habits: wrap html += hc
    {
        "find": "        html += hc\n\n    # -- CGM Spotlight",
        "replace": "        html += '<!-- S:habits -->' + hc + '<!-- /S:habits -->'\n\n    # -- CGM Spotlight",
    },
    # CGM: wrap html += gc2
    {
        "find": "        html += gc2\n\n    # -- Habit Streaks",
        "replace": "        html += '<!-- S:cgm -->' + gc2 + '<!-- /S:cgm -->'\n\n    # -- Habit Streaks",
    },
    # Weight Phase
    {
        "find": """            html += '<div style="background:#f0fdf4;border-left:3px solid #22c55e;""",
        "replace": """            html += '<!-- S:weight_phase -->'
            html += '<div style="background:#f0fdf4;border-left:3px solid #22c55e;""",
    },
    {
        "find": """            html += '<p style="font-size:10px;color:#6b7280;margin:6px 0 0;">Phase milestone: ' + str(p_proj) + '</p></div>'\n\n    # -- Today's Guidance""",
        "replace": """            html += '<p style="font-size:10px;color:#6b7280;margin:6px 0 0;">Phase milestone: ' + str(p_proj) + '</p></div>'
            html += '<!-- /S:weight_phase -->'\n\n    # -- Today's Guidance""",
    },
    # Guidance
    {
        "find": "    # -- Today's Guidance (v2.2: AI-generated smart guidance) ------------------\n    guidance_items",
        "replace": "    # -- Today's Guidance (v2.2: AI-generated smart guidance) ------------------\n    html += '<!-- S:guidance -->'\n    guidance_items",
    },
    {
        "find": """        html += '</div>'\n\n    # -- Journal Pulse""",
        "replace": """        html += '</div>'\n    html += '<!-- /S:guidance -->'\n\n    # -- Journal Pulse""",
    },
    # Journal Pulse
    {
        "find": """    if journal:\n        def mood_em""",
        "replace": """    if journal:\n        html += '<!-- S:journal_pulse -->'\n        def mood_em""",
    },
    {
        "find": """        html += '</div>'\n\n    # -- Journal Coach""",
        "replace": """        html += '</div>'\n        html += '<!-- /S:journal_pulse -->'\n\n    # -- Journal Coach""",
    },
    # Journal Coach
    {
        "find": """    if journal_coach_text:\n        parts = journal_coach_text.split""",
        "replace": """    if journal_coach_text:\n        html += '<!-- S:journal_coach -->'\n        parts = journal_coach_text.split""",
    },
    {
        "find": """        html += '</div>'\n\n    # -- Board of Directors""",
        "replace": """        html += '</div>'\n        html += '<!-- /S:journal_coach -->'\n\n    # -- Board of Directors""",
    },
    # Board of Directors
    {
        "find": """    if bod_insight:\n        html += '<div style="background:#f0f9ff;border-left:3px solid #0ea5e9;""",
        "replace": """    if bod_insight:\n        html += '<!-- S:bod -->'\n        html += '<div style="background:#f0f9ff;border-left:3px solid #0ea5e9;""",
    },
    {
        "find": """        html += '<p style="font-size:13px;color:#0c4a6e;line-height:1.6;margin:0;">' + bod_insight + '</p></div>'\n\n    # -- Anomaly""",
        "replace": """        html += '<p style="font-size:13px;color:#0c4a6e;line-height:1.6;margin:0;">' + bod_insight + '</p></div>'\n        html += '<!-- /S:bod -->'\n\n    # -- Anomaly""",
    },
]


SANITIZE_FUNCTION = '''

def sanitize_for_demo(html, data, profile):
    """Apply demo mode sanitization using profile-driven rules.
    
    Rules in profile["demo_mode_rules"]:
      redact_patterns: list of words → case-insensitive replace with "[redacted]"
      replace_values: dict mapping field names to replacement text
        Supported: weight_lbs, calories, protein, body_fat_pct
        Uses actual data values to find/replace all occurrences
      hide_sections: list of section names to strip entirely
        Available: scorecard, readiness, training, nutrition, habits, cgm,
                   weight_phase, guidance, journal_pulse, journal_coach, bod
      subject_prefix: string prepended to email subject (e.g. "[DEMO]")
    """
    import re
    rules = profile.get("demo_mode_rules", {})
    if not rules:
        return html

    # 1. Hide entire sections via comment markers
    for section in rules.get("hide_sections", []):
        pattern = r'<!-- S:' + re.escape(section) + r' -->.*?<!-- /S:' + re.escape(section) + r' -->'
        html = re.sub(pattern, '', html, flags=re.DOTALL)

    # 2. Replace specific data values with masked text
    rv = rules.get("replace_values", {})

    if "weight_lbs" in rv:
        mask = rv["weight_lbs"]
        # Replace actual weight values from data
        for w in [data.get("latest_weight"), data.get("week_ago_weight")]:
            if w:
                for fmt in [str(round(float(w), 1)), str(round(float(w)))]:
                    html = html.replace(fmt, mask)
        # Replace phase target weights
        for phase in profile.get("weight_loss_phases", []):
            for key in ["start_lbs", "end_lbs"]:
                v = phase.get(key)
                if v:
                    for fmt in [str(round(float(v), 1)), str(round(float(v)))]:
                        html = html.replace(fmt, mask)
        # Replace journey weights
        for key in ["goal_weight_lbs", "journey_start_weight_lbs"]:
            v = profile.get(key)
            if v:
                for fmt in [str(round(float(v), 1)), str(round(float(v)))]:
                    html = html.replace(fmt, mask)

    if "calories" in rv:
        mask = rv["calories"]
        mf = data.get("macrofactor") or {}
        cal = mf.get("total_calories_kcal")
        if cal:
            html = html.replace(str(round(float(cal))), mask)
        cal_target = profile.get("calorie_target")
        if cal_target:
            html = html.replace(str(round(float(cal_target))), mask)

    if "protein" in rv:
        mask = rv["protein"]
        mf = data.get("macrofactor") or {}
        prot = mf.get("total_protein_g")
        if prot:
            html = html.replace(str(round(float(prot))), mask)

    # 3. Redact text patterns (case-insensitive, word boundary)
    for pat in rules.get("redact_patterns", []):
        html = re.sub(r'(?i)\\b' + re.escape(pat) + r'(?:s|ed|ing)?\\b', '[redacted]', html)

    # 4. Add demo banner at top of email
    demo_banner = ('<div style="background:#fef3c7;border:2px solid #f59e0b;border-radius:8px;'
                   'padding:8px 16px;margin:0 16px 8px;text-align:center;">'
                   '<p style="font-size:11px;color:#92400e;margin:0;font-weight:700;">'
                   '&#128274; DEMO VERSION — Some data redacted for privacy</p></div>')
    # Insert after the header div closes (after the dark gradient header)
    header_end = '</div></div>'  # end of header section
    idx = html.find(header_end)
    if idx > 0:
        insert_at = idx + len(header_end)
        html = html[:insert_at] + demo_banner + html[insert_at:]

    return html

'''


def patch():
    with open(LAMBDA_FILE, "r") as f:
        code = f.read()

    # ── Fix 1: Add section markers in build_html ──
    applied = 0
    for marker in SECTION_MARKERS:
        if marker["find"] in code:
            code = code.replace(marker["find"], marker["replace"], 1)
            applied += 1
        else:
            # Try to find a close match for debugging
            short = marker["find"][:60].replace("\n", "\\n")
            print(f"[WARN] Marker not found: {short}...")
    print(f"[OK] Fix 1: {applied}/{len(SECTION_MARKERS)} section markers added")

    # ── Fix 2: Add sanitize_for_demo function (before HANDLER section) ──
    handler_marker = "# ==============================================================================\n# HANDLER"
    if handler_marker not in code:
        print("[ERROR] Could not find HANDLER section")
        return False
    code = code.replace(handler_marker, SANITIZE_FUNCTION + "\n" + handler_marker)
    print("[OK] Fix 2: sanitize_for_demo() function added")

    # ── Fix 3: Modify handler to support demo_mode ──
    old_handler_start = '    print("[INFO] Daily Brief v2.2 starting...")'
    new_handler_start = '''    demo_mode = event.get("demo_mode", False)
    print("[INFO] Daily Brief v2.2 starting..." + (" [DEMO MODE]" if demo_mode else ""))'''
    if old_handler_start in code:
        code = code.replace(old_handler_start, new_handler_start)
        print("[OK] Fix 3a: demo_mode flag parsing added")
    else:
        print("[WARN] Could not find handler start line")

    # Don't store day grade in demo mode
    old_store = '''    if day_grade_score is not None:
        store_day_grade(yesterday, day_grade_score, grade, component_scores,
                        profile.get("day_grade_weights", {}),
                        profile.get("day_grade_algorithm_version", "1.1"))'''
    new_store = '''    if day_grade_score is not None and not demo_mode:
        store_day_grade(yesterday, day_grade_score, grade, component_scores,
                        profile.get("day_grade_weights", {}),
                        profile.get("day_grade_algorithm_version", "1.1"))'''
    if old_store in code:
        code = code.replace(old_store, new_store)
        print("[OK] Fix 3b: skip day_grade store in demo mode")
    else:
        print("[WARN] Could not find store_day_grade block — may need manual check")

    # Apply sanitization before sending
    old_send = """    ses.send_email(
        FromEmailAddress=SENDER,
        Destination={"ToAddresses": [RECIPIENT]},
        Content={"Simple": {
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body":    {"Html": {"Data": html, "Charset": "UTF-8"}},
        }},
    )
    print("[INFO] Sent: " + subject)
    return {"statusCode": 200, "body": "Daily brief v2.2 sent: " + subject}"""

    new_send = """    # Demo mode: sanitize HTML and prefix subject
    if demo_mode:
        html = sanitize_for_demo(html, data, profile)
        prefix = (profile.get("demo_mode_rules") or {}).get("subject_prefix", "[DEMO]")
        subject = prefix + " " + subject
        print("[INFO] Demo mode: sanitization applied")

    ses.send_email(
        FromEmailAddress=SENDER,
        Destination={"ToAddresses": [RECIPIENT]},
        Content={"Simple": {
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body":    {"Html": {"Data": html, "Charset": "UTF-8"}},
        }},
    )
    print("[INFO] Sent: " + subject)
    return {"statusCode": 200, "body": "Daily brief v2.2 sent: " + subject}"""

    if old_send in code:
        code = code.replace(old_send, new_send)
        print("[OK] Fix 3c: demo mode sanitization + subject prefix before send")
    else:
        print("[ERROR] Could not find ses.send_email block")
        return False

    # ── Update version ──
    code = code.replace(
        "Daily Brief Lambda — v2.2.2 (Day Grade Fix + Activity Dedup)",
        "Daily Brief Lambda — v2.2.3 (+ Demo Mode)"
    )
    print("[OK] Version header updated to v2.2.3")

    with open(LAMBDA_FILE, "w") as f:
        f.write(code)

    print("\n[DONE] Patch applied. Run deploy_daily_brief_v223.sh to deploy.")
    return True


if __name__ == "__main__":
    patch()
