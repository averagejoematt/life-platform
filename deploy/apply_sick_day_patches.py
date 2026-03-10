#!/usr/bin/env python3
"""
apply_sick_day_patches.py — Apply sick day feature patches to Lambda files.

Run from project root:
  python3 deploy/apply_sick_day_patches.py

Patches applied:
  lambdas/daily_metrics_compute_lambda.py  — v1.0.0 → v1.1.0
  lambdas/anomaly_detector_lambda.py       — v2.1.0 → v2.2.0
  lambdas/freshness_checker_lambda.py      — sick day aware
  lambdas/daily_brief_lambda.py            — recovery brief
  mcp/registry.py                          — 3 new tools registered
"""

import os
import sys
import subprocess

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAMBDAS = os.path.join(PROJ, "lambdas")
MCP = os.path.join(PROJ, "mcp")


def patch_file(path, replacements, name):
    """Apply a list of (old, new) replacements to a file."""
    with open(path) as f:
        content = f.read()
    original = content
    for old, new in replacements:
        if old in content:
            content = content.replace(old, new, 1)
        else:
            print(f"  ⚠️  {name}: anchor not found — {repr(old[:60])}")
    if content != original:
        with open(path, "w") as f:
            f.write(content)
        print(f"  ✅ {name} patched")
    else:
        print(f"  ℹ️  {name} — no changes needed (already patched?)")


# ==============================================================================
# 1. daily_metrics_compute_lambda.py
# ==============================================================================

SICK_DAY_METRICS_BLOCK = '''
    # ── Sick day check ─────────────────────────────────────────────────────
    # If the target date is flagged as a sick/rest day, store a minimal record:
    #   - day_grade_letter = "sick" (not scored, excluded from trend charts)
    #   - Streak timers preserved from previous day (not broken, not advanced)
    #   - Anomaly alerts will be suppressed separately by anomaly_detector
    try:
        from sick_day_checker import check_sick_day as _check_sick
        _sick_rec = _check_sick(table, USER_ID, yesterday_str)
    except ImportError:
        _sick_rec = None

    if _sick_rec:
        _sick_reason = _sick_rec.get("reason") or "sick day"
        logger.info("Sick day flagged for %s (%s) — storing sick record", yesterday_str, _sick_reason)

        # Load previous day's computed_metrics to preserve streak values
        _dt_y = datetime.strptime(yesterday_str, "%Y-%m-%d")
        _prev_date = (_dt_y - timedelta(days=1)).strftime("%Y-%m-%d")
        _prev_cm = fetch_date("computed_metrics", _prev_date)
        _t0_streak  = int(float(_prev_cm.get("tier0_streak",  0))) if _prev_cm else 0
        _t01_streak = int(float(_prev_cm.get("tier01_streak", 0))) if _prev_cm else 0
        _vice_streaks = {k: int(float(v)) for k, v in _prev_cm.get("vice_streaks", {}).items()} if _prev_cm else {}

        _sick_item = {
            "pk":               USER_PREFIX + "computed_metrics",
            "sk":               "DATE#" + yesterday_str,
            "date":             yesterday_str,
            "day_grade_letter": "sick",
            "sick_day":         True,
            "sick_day_reason":  _sick_reason,
            "readiness_colour": "gray",
            "tier0_streak":     Decimal(str(_t0_streak)),
            "tier01_streak":    Decimal(str(_t01_streak)),
            "sleep_debt_7d_hrs": Decimal("0"),
            "computed_at":      datetime.now(timezone.utc).isoformat(),
            "algo_version":     ALGO_VERSION,
        }
        if _vice_streaks:
            _sick_item["vice_streaks"] = {k: Decimal(str(v)) for k, v in _vice_streaks.items()}

        table.put_item(Item=_sick_item)
        logger.info(
            "Sick day record stored for %s — streaks preserved (T0=%s T01=%s)",
            yesterday_str, _t0_streak, _t01_streak,
        )
        return {
            "statusCode":       200,
            "body":             f"Sick day {yesterday_str}: computed_metrics stored with grade='sick'",
            "day_grade_letter": "sick",
            "sick_day":         True,
            "tier0_streak":     _t0_streak,
            "tier01_streak":    _t01_streak,
        }

    profile = fetch_profile()'''

patch_file(
    os.path.join(LAMBDAS, "daily_metrics_compute_lambda.py"),
    [
        ("Daily Metrics Compute Lambda — v1.0.0",
         "Daily Metrics Compute Lambda — v1.1.0"),
        ("v1.0.0 — 2026-03-07",
         "v1.0.0 — 2026-03-07\nv1.1.0 — 2026-03-09: Sick day support — grade='sick', streaks preserved"),
        ('\n    profile = fetch_profile()\n    if not profile:\n        logger.error("No profile found — aborting")',
         SICK_DAY_METRICS_BLOCK + '\n    if not profile:\n        logger.error("No profile found — aborting")'),
    ],
    "daily_metrics_compute_lambda.py",
)


# ==============================================================================
# 2. anomaly_detector_lambda.py
# ==============================================================================

SICK_TRAVEL_BLOCK = '''    if travel_mode:
        print(f"[INFO] TRAVEL MODE: {travel_dest} -- anomaly alerts will be suppressed")

    # ── Sick day check (v2.2.0) ──
    try:
        from sick_day_checker import check_sick_day as _check_sick_anomaly
        _sick_rec_anomaly = _check_sick_anomaly(table, USER_ID, yesterday)
    except ImportError:
        _sick_rec_anomaly = None
    sick_mode   = _sick_rec_anomaly is not None
    sick_reason = (_sick_rec_anomaly or {}).get("reason") or "sick day"
    if sick_mode:
        print(f"[INFO] SICK MODE: {sick_reason} -- anomaly alerts will be suppressed")'''

SICK_BRANCH = '''    elif multi and travel_mode:
        source_count = len(set(f["source"] for f in flagged))
        severity = "travel_suppressed"
        hypothesis = (f"[TRAVEL] Currently in {travel_dest}. "
                      "Anomalies expected due to timezone shift, routine disruption, "
                      "and environmental change. Alert suppressed.")
        print(f"[INFO] Travel mode -- {len(flagged)} metrics flagged across "
              f"{source_count} sources, alert SUPPRESSED")

    elif multi and sick_mode:
        source_count = len(set(f["source"] for f in flagged))
        severity = "sick_suppressed"
        hypothesis = (
            f"[SICK DAY] {sick_reason}. Missing data and biometric drops are expected "
            "during illness — recovery score, HRV, habits, and nutrition will all look "
            "off. Anomaly alerts suppressed. Rest and recover."
        )
        print(f"[INFO] Sick mode -- {len(flagged)} metrics flagged across "
              f"{source_count} sources, alert SUPPRESSED")'''

patch_file(
    os.path.join(LAMBDAS, "anomaly_detector_lambda.py"),
    [
        ("Anomaly Detector Lambda — v2.1.0",
         "Anomaly Detector Lambda — v2.2.0"),
        ('"detector_version": "2.1.0"',
         '"detector_version": "2.2.0"'),
        ('    if travel_mode:\n        print(f"[INFO] TRAVEL MODE: {travel_dest} -- anomaly alerts will be suppressed")',
         SICK_TRAVEL_BLOCK),
        ('def write_anomaly_record(date_str, flagged, alert_sent, hypothesis, severity,\n                         travel_mode=False, travel_dest=None):',
         'def write_anomaly_record(date_str, flagged, alert_sent, hypothesis, severity,\n                         travel_mode=False, travel_dest=None,\n                         sick_mode=False, sick_reason=None):'),
        ('        "travel_mode":      travel_mode,\n        "travel_destination": travel_dest,',
         '        "travel_mode":      travel_mode,\n        "travel_destination": travel_dest,\n        "sick_mode":        sick_mode,\n        "sick_reason":      sick_reason,'),
        ('    write_anomaly_record(yesterday, flagged, alert_sent, hypothesis, severity,\n                         travel_mode=travel_mode, travel_dest=travel_dest)',
         '    write_anomaly_record(yesterday, flagged, alert_sent, hypothesis, severity,\n                         travel_mode=travel_mode, travel_dest=travel_dest,\n                         sick_mode=sick_mode, sick_reason=sick_reason if sick_mode else None)'),
        # Insert sick branch after travel branch
        ('''    elif multi and travel_mode:
        source_count = len(set(f["source"] for f in flagged))
        severity = "travel_suppressed"
        hypothesis = (f"[TRAVEL] Currently in {travel_dest}. "
                      "Anomalies expected due to timezone shift, routine disruption, "
                      "and environmental change. Alert suppressed.")
        print(f"[INFO] Travel mode -- {len(flagged)} metrics flagged across "
              f"{source_count} sources, alert SUPPRESSED")''',
         SICK_BRANCH),
    ],
    "anomaly_detector_lambda.py",
)


# ==============================================================================
# 3. freshness_checker_lambda.py
# ==============================================================================

FRESHNESS_SICK_INIT = '''def lambda_handler(event, context):
    table = dynamodb.Table(TABLE_NAME)
    now = datetime.now(timezone.utc)
    stale_threshold = now - timedelta(hours=STALE_HOURS)

    # ── Sick day check: suppress stale alerts if yesterday was a sick/rest day ──
    # Stale data on a sick day is expected — user is not tracking anything.
    yesterday_str = (now.date() - timedelta(days=1)).isoformat()
    _sick_suppress = False
    try:
        from sick_day_checker import check_sick_day as _check_fresh_sick
        _sick_fr = _check_fresh_sick(table, USER_ID, yesterday_str)
        if _sick_fr:
            _sick_suppress = True
            _sick_r = _sick_fr.get("reason") or "sick day"
            logger.info(
                "Sick day flagged for %s (%s) — freshness alerts suppressed",
                yesterday_str, _sick_r,
            )
    except ImportError:
        pass'''

FRESHNESS_SNS_WITH_SICK = '''    if stale_sources:
        stale_list = "\\n".join([f"  - {name}: {detail}" for name, detail in stale_sources])
        status_list = "\\n".join(source_status)

        if _sick_suppress:
            # Sick day — expected data gap, no alert needed
            logger.info(
                "Stale sources detected (%d) but suppressed — sick day (%s)",
                len(stale_sources), yesterday_str,
            )
        else:
            message = (
                f"⚠️ Life Platform: Stale Data Detected\\n\\n"
                f"The following sources have not updated in over {STALE_HOURS} hours:\\n\\n"
                f"{stale_list}\\n\\n"
                f"Full source status:\\n{status_list}\\n\\n"
                f"Checked at: {now.strftime('%Y-%m-%d %H:%M UTC')}"
            )
            try:
                sns.publish(
                    TopicArn=SNS_ARN,
                    Subject=f"⚠️ Life Platform: {len(stale_sources)} stale source(s)",
                    Message=message,
                )
                logger.info("Alert sent for %d stale source(s)", len(stale_sources))
            except Exception as e:
                logger.error("SNS publish failed: %s", e)'''

patch_file(
    os.path.join(LAMBDAS, "freshness_checker_lambda.py"),
    [
        ('def lambda_handler(event, context):\n    table = dynamodb.Table(TABLE_NAME)\n    now = datetime.now(timezone.utc)\n    stale_threshold = now - timedelta(hours=STALE_HOURS)',
         FRESHNESS_SICK_INIT),
        ('''    if stale_sources:
        stale_list = "\\n".join([f"  - {name}: {detail}" for name, detail in stale_sources])
        status_list = "\\n".join(source_status)
        message = (
            f"⚠️ Life Platform: Stale Data Detected\\n\\n"
            f"The following sources have not updated in over {STALE_HOURS} hours:\\n\\n"
            f"{stale_list}\\n\\n"
            f"Full source status:\\n{status_list}\\n\\n"
            f"Checked at: {now.strftime('%Y-%m-%d %H:%M UTC')}"
        )
        try:
            sns.publish(
                TopicArn=SNS_ARN,
                Subject=f"⚠️ Life Platform: {len(stale_sources)} stale source(s)",
                Message=message,
            )
            logger.info("Alert sent for %d stale source(s)", len(stale_sources))
        except Exception as e:
            logger.error("SNS publish failed: %s", e)''',
         FRESHNESS_SNS_WITH_SICK),
    ],
    "freshness_checker_lambda.py",
)


# ==============================================================================
# 4. daily_brief_lambda.py — insert sick day recovery brief
# ==============================================================================

SICK_BRIEF_BLOCK = '''    data = gather_daily_data(profile, yesterday)
    print("[INFO] Date: " + yesterday + " | sources: " +
          ", ".join(k for k in ["whoop", "sleep", "macrofactor", "habitify", "apple", "strava", "mf_workouts"] if data.get(k)))

    # ── Sick day check ─────────────────────────────────────────────────────
    # If today's subject date was a sick/rest day, send a brief recovery
    # summary instead of the full brief. Skip scoring, habits, and coaching.
    try:
        from sick_day_checker import check_sick_day as _check_sick_brief
        _sick_brief_rec = _check_sick_brief(table, USER_ID, yesterday)
    except ImportError:
        _sick_brief_rec = None

    if _sick_brief_rec:
        _sick_brief_reason = _sick_brief_rec.get("reason") or "sick day"
        print(f"[INFO] Sick day flagged for {yesterday} ({_sick_brief_reason}) — sending recovery brief")

        _sb_whoop      = fetch_date("whoop", yesterday)
        _sb_sleep_hrs  = safe_float(_sb_whoop, "sleep_duration_hours")
        _sb_recovery   = safe_float(_sb_whoop, "recovery_score")
        _sb_hrv        = safe_float(_sb_whoop, "hrv")

        _sb_sleep_line    = f"{_sb_sleep_hrs:.1f} hrs" if _sb_sleep_hrs else "—"
        _sb_recovery_line = f"{int(_sb_recovery)}%" if _sb_recovery else "—"
        _sb_hrv_line      = f"{int(_sb_hrv)} ms"   if _sb_hrv      else "—"

        try:
            _today_short = today.strftime("%a %b %-d")
        except Exception:
            _today_short = today.isoformat()

        _sb_reason_display = _sick_brief_reason.title()
        _sb_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f4f8;font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',sans-serif;">
  <div style="max-width:560px;margin:24px auto;background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
    <div style="background:#1a1a2e;padding:20px 24px 16px;">
      <p style="color:#8892b0;font-size:11px;margin:0 0 2px;text-transform:uppercase;letter-spacing:1px;">Daily Brief — Recovery Day</p>
      <h1 style="color:#fff;font-size:17px;font-weight:700;margin:0;">{_today_short}</h1>
    </div>
    <div style="background:#7c3aed;padding:14px 24px;">
      <p style="color:#fff;font-size:14px;font-weight:700;margin:0;">🤒 Rest &amp; Recovery — {_sb_reason_display}</p>
      <p style="color:#e9d5ff;font-size:12px;margin:4px 0 0;">No grades, no scores, no coaching today. Just recover.</p>
    </div>
    <div style="padding:20px 24px 8px;">
      <p style="font-size:11px;font-weight:700;color:#374151;text-transform:uppercase;letter-spacing:0.5px;margin:0 0 12px;">What Your Body Is Doing</p>
      <table style="width:100%;border-collapse:collapse;">
        <tr>
          <td style="padding:8px 0;font-size:13px;color:#6b7280;">Sleep last night</td>
          <td style="padding:8px 0;font-size:14px;font-weight:600;color:#1a1a2e;text-align:right;">{_sb_sleep_line}</td>
        </tr>
        <tr style="border-top:1px solid #f3f4f6;">
          <td style="padding:8px 0;font-size:13px;color:#6b7280;">Recovery score</td>
          <td style="padding:8px 0;font-size:14px;font-weight:600;color:#1a1a2e;text-align:right;">{_sb_recovery_line}</td>
        </tr>
        <tr style="border-top:1px solid #f3f4f6;">
          <td style="padding:8px 0;font-size:13px;color:#6b7280;">HRV</td>
          <td style="padding:8px 0;font-size:14px;font-weight:600;color:#1a1a2e;text-align:right;">{_sb_hrv_line}</td>
        </tr>
      </table>
    </div>
    <div style="padding:4px 24px 20px;">
      <div style="background:#f8f8fc;border-radius:8px;padding:14px 16px;border-left:3px solid #7c3aed;">
        <p style="font-size:14px;color:#1a1a2e;line-height:1.65;margin:0;">
          <strong>Today\'s only job:</strong> rest, hydrate, and let your immune system do its work.
          Habits, calories, and streaks are frozen — no progress lost for being sick.
          Your character sheet is paused. See you when you\'re back. 💜
        </p>
      </div>
    </div>
    <div style="background:#f8f8fc;padding:12px 24px;border-top:1px solid #e8e8f0;">
      <p style="color:#9ca3af;font-size:10px;margin:0;text-align:center;">Life Platform — Recovery Day Brief | {_sick_brief_reason}</p>
      <p style="color:#b0b0b0;font-size:8px;margin:4px 0 0;text-align:center;">&#9874;&#65039; Personal health tracking only &mdash; not medical advice.</p>
    </div>
  </div>
</body>
</html>"""

        _sb_subject = f"Recovery Day | {_today_short} | 🤒 Rest up — no scores today"
        ses.send_email(
            FromEmailAddress=SENDER,
            Destination={"ToAddresses": [RECIPIENT]},
            Content={"Simple": {
                "Subject": {"Data": _sb_subject, "Charset": "UTF-8"},
                "Body":    {"Html": {"Data": _sb_html, "Charset": "UTF-8"}},
            }},
        )
        print(f"[INFO] Recovery brief sent: {_sb_subject}")

        try:
            output_writers.write_buddy_json(
                {"date": yesterday, "whoop": _sb_whoop, "sick_day": True,
                 "sick_day_reason": _sick_brief_reason},
                profile, yesterday, character_sheet=None,
            )
        except Exception as _sbe:
            print(f"[WARN] write_buddy_json (sick) failed: {_sbe}")

        return {"statusCode": 200, "body": f"Recovery brief sent for {yesterday}"}

    # Deduplicate multi-device Strava activities'''

patch_file(
    os.path.join(LAMBDAS, "daily_brief_lambda.py"),
    [
        ('    data = gather_daily_data(profile, yesterday)\n    print("[INFO] Date: " + yesterday + " | sources: " +\n          ", ".join(k for k in ["whoop", "sleep", "macrofactor", "habitify", "apple", "strava", "mf_workouts"] if data.get(k)))\n\n    # Deduplicate multi-device Strava activities',
         SICK_BRIEF_BLOCK),
    ],
    "daily_brief_lambda.py",
)


# ==============================================================================
# 5. mcp/registry.py — restore from git + add sick day tool entries
# ==============================================================================

print("\n5. Patching mcp/registry.py...")
try:
    subprocess.run(
        ["git", "checkout", "HEAD", "--", "mcp/registry.py"],
        cwd=PROJ, check=True, capture_output=True
    )
    print("  ✅ Restored from git HEAD")
except subprocess.CalledProcessError as e:
    print(f"  ⚠️  git restore failed: {e.stderr.decode()}")

registry_path = os.path.join(MCP, "registry.py")
with open(registry_path) as f:
    reg = f.read()

changed = False

if "from mcp.tools_sick_days" not in reg:
    reg = reg.replace(
        "from mcp.tools_hypotheses import *\n\nTOOLS = {",
        "from mcp.tools_hypotheses import *\nfrom mcp.tools_sick_days import *\n\nTOOLS = {"
    )
    changed = True
    print("  ✅ Import added")

if '"log_sick_day"' not in reg:
    sick_tools = '''
    "log_sick_day": {
        "fn": tool_log_sick_day,
        "schema": {
            "name": "log_sick_day",
            "description": (
                "Flag one or more dates as sick or rest days. When flagged: Character Sheet EMA frozen, "
                "day grade = \'sick\', habit/streak timers preserved (not broken), anomaly alerts suppressed, "
                "freshness alerts skipped, Daily Brief shows recovery banner."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "date":   {"type": "string", "description": "Single date YYYY-MM-DD."},
                    "dates":  {"type": "array", "items": {"type": "string"},
                               "description": "Multiple dates YYYY-MM-DD."},
                    "reason": {"type": "string", "description": "Optional reason (flu, injury, etc)."},
                },
                "required": [],
            },
        },
    },
    "get_sick_days": {
        "fn": tool_get_sick_days,
        "schema": {
            "name": "get_sick_days",
            "description": "List sick/rest days within a date range. Shows date, reason, when logged.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start YYYY-MM-DD (default 90d ago)."},
                    "end_date":   {"type": "string", "description": "End YYYY-MM-DD (default today)."},
                },
                "required": [],
            },
        },
    },
    "clear_sick_day": {
        "fn": tool_clear_sick_day,
        "schema": {
            "name": "clear_sick_day",
            "description": "Remove a sick day flag (use if logged in error).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date to un-flag YYYY-MM-DD."},
                },
                "required": ["date"],
            },
        },
    },
}
'''
    reg = reg.rstrip()
    if reg.endswith("\n}"):
        reg = reg[:-1] + sick_tools
    elif reg.endswith("}"):
        reg = reg[:-1] + sick_tools
    changed = True
    print("  ✅ Tool entries added")

if changed:
    with open(registry_path, "w") as f:
        f.write(reg)
    print("  ✅ mcp/registry.py written")
else:
    print("  ℹ️  mcp/registry.py already patched")


# ==============================================================================
# Done
# ==============================================================================

print("""
✅ All patches applied.

Next steps:
  bash deploy/sick_days_retroactive.sh     # flag Mar 8-9 in DDB
  bash deploy/sick_days_deploy.sh          # build layer + deploy all stacks

Or if you want to just build layer + deploy manually:
  bash deploy/build_layer.sh
  cd cdk && cdk deploy --all --require-approval never
""")
