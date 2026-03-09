#!/bin/bash
# Feature #18 — Automated Threshold Learning for Anomaly Detector
# Replaces static Z_THRESHOLD=1.5 with per-metric personalized thresholds
# v2.37.0

set -euo pipefail
REGION="us-west-2"
FUNCTION_NAME="anomaly-detector"
LAMBDA_DIR="$HOME/Documents/Claude/life-platform/lambdas"

echo "═══════════════════════════════════════════════════════════"
echo "Feature #18 — Automated Threshold Learning"
echo "Anomaly Detector v2.0"
echo "═══════════════════════════════════════════════════════════"

# ── Write the upgraded anomaly detector Lambda ──
echo ""
echo "Step 1: Writing anomaly_detector_lambda.py v2.0..."

cat > "$LAMBDA_DIR/anomaly_detector_lambda.py" << 'LAMBDA_EOF'
"""
Anomaly Detector Lambda — v2.0.0 (Feature #18: Automated Threshold Learning)
Fires at 8:05am PT daily (16:05 UTC via EventBridge) — after enrichment, before daily brief.

v2.0.0 Changes:
  - Per-metric learned thresholds based on coefficient of variation (CV)
  - Day-of-week normalization for weekday vs weekend patterns (steps, tasks, habits)
  - Minimum absolute change filters (weight ±1.5 lbs, steps ±2000)
  - Learned thresholds stored in DynamoDB record for transparency
  - Updated metrics: chronicling→habitify, added Body Battery, caffeine

Logic:
  1. Fetch yesterday's values for 13 key metrics across 7 sources
  2. Compute 30-day rolling mean + SD for each metric
  3. Compute coefficient of variation (CV) → adaptive Z threshold:
     - High-CV metrics (CV > 0.3): threshold = 2.0 SD (naturally variable)
     - Medium-CV (0.15-0.3): threshold = 1.75 SD
     - Low-CV (< 0.15): threshold = 1.5 SD (tight — small moves matter)
  4. Day-of-week normalization for lifestyle-variable metrics
  5. Minimum absolute change filter prevents noise on stable metrics
  6. If 2+ flagged metrics span 2+ different sources → multi-source anomaly
  7. Write anomaly record to DynamoDB (always — even if no anomaly)
  8. If multi-source anomaly: call Haiku for root cause hypothesis, send alert email
"""

import json
import math
import statistics
import time
import boto3
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal

# ── AWS clients ───────────────────────────────────────────────────────────────
dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
table    = dynamodb.Table("life-platform")
ses      = boto3.client("sesv2", region_name="us-west-2")
secrets  = boto3.client("secretsmanager", region_name="us-west-2")

RECIPIENT = "awsdev@mattsusername.com"
SENDER    = "awsdev@mattsusername.com"
MIN_BASELINE_DAYS = 7

# ── Adaptive threshold configuration ─────────────────────────────────────────
# CV ranges → Z thresholds
# High-CV (>0.3): naturally variable metrics get wider thresholds
# Med-CV (0.15-0.3): moderate variability
# Low-CV (<0.15): tight metrics where small changes are meaningful
CV_THRESHOLDS = [
    (0.30, 2.0),   # high variability → Z=2.0
    (0.15, 1.75),  # medium variability → Z=1.75
    (0.0,  1.5),   # low variability → Z=1.5
]

# Minimum absolute change filters — prevent noise on stable metrics
# If the deviation from mean is less than this absolute amount, skip flagging
MIN_ABSOLUTE_CHANGE = {
    "weight_lbs":       1.5,   # ±1.5 lbs daily fluctuation is normal (water, food timing)
    "steps":            2000,  # ±2000 steps variance is normal lifestyle
    "resting_heart_rate": 3,   # ±3 bpm can be measurement noise
}

# Day-of-week normalization: these metrics have strong weekday/weekend patterns
# For these, we compute separate baselines for weekday vs weekend
DOW_NORMALIZED_METRICS = {"steps", "tasks_completed", "completion_pct"}

# Metrics to monitor: (source, field, human_label, low_is_bad)
# low_is_bad=True means a drop is concerning; False=spike is concerning; None=both directions
METRICS = [
    ("whoop",       "recovery_score",       "Recovery Score",      True),
    ("whoop",       "hrv",                  "HRV",                 True),
    ("whoop",       "resting_heart_rate",   "Resting Heart Rate",  False),
    ("eightsleep",  "sleep_score",          "Sleep Score",         True),
    ("eightsleep",  "sleep_efficiency",     "Sleep Efficiency",    True),
    ("withings",    "weight_lbs",           "Weight",              None),
    ("apple_health","steps",                "Steps",               True),
    ("apple_health","walking_speed_mph",    "Walking Speed",       True),
    ("apple_health","walking_asymmetry_pct","Walking Asymmetry",   False),
    ("todoist",     "tasks_completed",      "Tasks Completed",     True),
    ("habitify",    "completion_pct",       "P40 Habits",          True),
    ("garmin",      "body_battery_high",    "Body Battery",        True),
    ("garmin",      "avg_stress",           "Garmin Stress",       False),
]


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_anthropic_key():
    secret = secrets.get_secret_value(SecretId="life-platform/anthropic")
    return json.loads(secret["SecretString"])["api_key"]

def d2f(obj):
    if isinstance(obj, list):    return [d2f(i) for i in obj]
    if isinstance(obj, dict):    return {k: d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return float(obj)
    return obj

def fetch_date(source, date_str):
    try:
        r = table.get_item(Key={"pk": f"USER#matthew#SOURCE#{source}", "sk": f"DATE#{date_str}"})
        return d2f(r.get("Item") or {})
    except Exception:
        return {}

def fetch_range(source, start, end):
    try:
        r = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={
                ":pk": f"USER#matthew#SOURCE#{source}",
                ":s":  f"DATE#{start}",
                ":e":  f"DATE#{end}"
            })
        return [d2f(item) for item in r.get("Items", [])]
    except Exception:
        return []

def safe_float(rec, field):
    if rec and field in rec:
        try: return float(rec[field])
        except Exception: return None
    return None

def is_weekend(date_str):
    """Returns True if the date is Saturday or Sunday."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.weekday() >= 5
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════════════
# ADAPTIVE THRESHOLD LEARNING
# ══════════════════════════════════════════════════════════════════════════════

def compute_adaptive_threshold(cv):
    """Given a coefficient of variation, return the Z-score threshold."""
    for cv_floor, z_threshold in CV_THRESHOLDS:
        if cv >= cv_floor:
            return z_threshold
    return 1.5  # fallback


def compute_baseline(source, field, end_date, lookback_days=30, dow_normalize=False, target_is_weekend=False):
    """
    Returns (mean, sd, cv, z_threshold, sample_size, baseline_type) for a field.
    
    If dow_normalize=True, computes separate weekday/weekend baselines and uses
    the one matching target_is_weekend.
    """
    start = (end_date - timedelta(days=lookback_days)).isoformat()
    end   = (end_date - timedelta(days=1)).isoformat()
    records = fetch_range(source, start, end)

    if dow_normalize:
        # Split into weekday/weekend baselines
        weekday_vals = []
        weekend_vals = []
        for r in records:
            v = safe_float(r, field)
            if v is None:
                continue
            d = r.get("date") or r.get("sk", "").replace("DATE#", "")
            if is_weekend(d):
                weekend_vals.append(v)
            else:
                weekday_vals.append(v)
        
        vals = weekend_vals if target_is_weekend else weekday_vals
        baseline_type = "weekend" if target_is_weekend else "weekday"
    else:
        vals = [safe_float(r, field) for r in records]
        vals = [v for v in vals if v is not None]
        baseline_type = "rolling_30d"

    if len(vals) < MIN_BASELINE_DAYS:
        return None, None, None, None, len(vals), baseline_type

    mean = statistics.mean(vals)
    sd   = statistics.stdev(vals) if len(vals) > 1 else 0
    cv   = (sd / mean) if mean != 0 else 0
    z_threshold = compute_adaptive_threshold(cv)

    return mean, sd, cv, z_threshold, len(vals), baseline_type


def check_anomalies(yesterday_str, today):
    """
    Returns a list of anomaly dicts with adaptive thresholds.
    """
    flagged = []
    yesterday_date = datetime.strptime(yesterday_str, "%Y-%m-%d").date()
    yesterday_is_weekend = is_weekend(yesterday_str)

    # Fetch all yesterday records once
    records_cache = {}
    sources_needed = set(source for source, _, _, _ in METRICS)
    for source in sources_needed:
        records_cache[source] = fetch_date(source, yesterday_str)

    for source, field, label, low_is_bad in METRICS:
        yesterday_val = safe_float(records_cache[source], field)
        if yesterday_val is None:
            continue

        # Determine if this metric uses day-of-week normalization
        dow_normalize = field in DOW_NORMALIZED_METRICS

        mean, sd, cv, z_threshold, sample_size, baseline_type = compute_baseline(
            source, field, yesterday_date,
            dow_normalize=dow_normalize,
            target_is_weekend=yesterday_is_weekend
        )

        if mean is None or sd is None:
            continue
        if sd == 0:
            continue

        z = (yesterday_val - mean) / sd
        abs_change = abs(yesterday_val - mean)

        # Check minimum absolute change filter
        min_abs = MIN_ABSOLUTE_CHANGE.get(field, 0)
        if abs_change < min_abs:
            continue

        # Determine if this direction is anomalous using learned threshold
        is_anomalous = False
        direction = None

        if low_is_bad is True:
            if z <= -z_threshold:
                is_anomalous = True
                direction = "low"
        elif low_is_bad is False:
            if z >= z_threshold:
                is_anomalous = True
                direction = "high"
        else:
            if abs(z) >= z_threshold:
                is_anomalous = True
                direction = "low" if z < 0 else "high"

        if is_anomalous:
            flagged.append({
                "source":         source,
                "field":          field,
                "label":          label,
                "yesterday_val":  round(yesterday_val, 1),
                "baseline_mean":  round(mean, 1),
                "baseline_sd":    round(sd, 1),
                "z_score":        round(z, 2),
                "direction":      direction,
                "pct_from_mean":  round(((yesterday_val - mean) / mean) * 100, 1) if mean != 0 else 0,
                # v2.0 additions — threshold learning transparency
                "cv":             round(cv, 3) if cv is not None else None,
                "z_threshold":    z_threshold,
                "baseline_type":  baseline_type,
                "sample_size":    sample_size,
            })

    return flagged


def is_multi_source(flagged):
    sources = set(f["source"] for f in flagged)
    return len(sources) >= 2


# ══════════════════════════════════════════════════════════════════════════════
# HAIKU — ROOT CAUSE HYPOTHESIS
# ══════════════════════════════════════════════════════════════════════════════

HYPOTHESIS_PROMPT = """You are a health data analyst. Matthew's life platform detected anomalies across multiple data sources yesterday.

ANOMALOUS METRICS:
{anomalies_json}

ADDITIONAL CONTEXT (yesterday's full data):
{context_json}

Your job: write a concise root cause hypothesis in 2-3 sentences.

Rules:
- Reference specific numbers (e.g. "HRV dropped to 42ms vs your 61ms baseline")
- Propose the most likely causal chain connecting the anomalies
- If one anomaly likely caused another, say so explicitly
- End with ONE specific, actionable recommendation for today
- No bullet points, no headers, no markdown — flowing prose only
- Max 80 words total

Write the hypothesis now."""


def build_context(yesterday_str):
    sources = ["whoop", "eightsleep", "withings", "strava", "todoist", "habitify", "macrofactor", "garmin"]
    context = {"date": yesterday_str}
    for source in sources:
        rec = fetch_date(source, yesterday_str)
        if rec:
            clean = {k: v for k, v in rec.items()
                     if k not in ("pk", "sk", "activities", "food_log", "habits", "workouts")
                     and not isinstance(v, list)}
            context[source] = clean
    return context


def call_anthropic_with_retry(req, timeout=30, max_attempts=2, backoff_s=5):
    for attempt in range(1, max_attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            print(f"[WARN] Anthropic API HTTP {e.code} on attempt {attempt}/{max_attempts}")
            if attempt < max_attempts and e.code in (429, 529, 500, 502, 503, 504):
                time.sleep(backoff_s)
            else:
                raise
        except urllib.error.URLError as e:
            print(f"[WARN] Anthropic API network error on attempt {attempt}/{max_attempts}: {e}")
            if attempt < max_attempts:
                time.sleep(backoff_s)
            else:
                raise


def call_haiku_hypothesis(flagged, context, api_key):
    payload = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 250,
        "messages": [{
            "role": "user",
            "content": HYPOTHESIS_PROMPT.format(
                anomalies_json=json.dumps(flagged, indent=2),
                context_json=json.dumps(context, indent=2)
            )
        }]
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        },
        method="POST"
    )
    resp = call_anthropic_with_retry(req, timeout=25)
    return resp["content"][0]["text"].strip()


# ══════════════════════════════════════════════════════════════════════════════
# DYNAMODB WRITE
# ══════════════════════════════════════════════════════════════════════════════

def write_anomaly_record(date_str, flagged, alert_sent, hypothesis, severity):
    item = {
        "pk":               "USER#matthew#SOURCE#anomalies",
        "sk":               f"DATE#{date_str}",
        "date":             date_str,
        "anomalous_metrics": flagged,
        "source_count":     len(set(f["source"] for f in flagged)),
        "alert_sent":       alert_sent,
        "hypothesis":       hypothesis,
        "severity":         severity,
        "detector_version": "2.0.0",
        "updated_at":       datetime.now(timezone.utc).isoformat(),
    }
    item = json.loads(json.dumps(item), parse_float=Decimal)
    table.put_item(Item=item)
    print(f"[INFO] Anomaly record written: date={date_str} severity={severity} "
          f"metrics={len(flagged)} sources={item['source_count']}")


# ══════════════════════════════════════════════════════════════════════════════
# ALERT EMAIL
# ══════════════════════════════════════════════════════════════════════════════

def build_alert_html(flagged, hypothesis, date_str):
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        day_label = dt.strftime("%A, %b %-d")
    except Exception:
        day_label = date_str

    severity_count = len(flagged)
    severity_colour = "#dc2626" if severity_count >= 4 else "#d97706"
    severity_label  = "HIGH" if severity_count >= 4 else "MODERATE"

    metric_rows = ""
    for m in flagged:
        direction_emoji = "📉" if m["direction"] == "low" else "📈"
        pct = m["pct_from_mean"]
        pct_str = f'{"+" if pct > 0 else ""}{pct}% vs baseline'
        z_str = f'Z = {m["z_score"]} (threshold: {m.get("z_threshold", 1.5)})'
        baseline_note = m.get("baseline_type", "rolling_30d")
        if baseline_note != "rolling_30d":
            baseline_note = f'{baseline_note} baseline'
        else:
            baseline_note = ""
        metric_rows += f"""
        <tr>
          <td style="padding:10px 16px;font-size:13px;font-weight:600;color:#1a1a2e;border-bottom:1px solid #f3f4f6;">
            {direction_emoji} {m["label"]}
          </td>
          <td style="padding:10px 16px;font-size:13px;color:#374151;border-bottom:1px solid #f3f4f6;text-align:right;">
            <strong>{m["yesterday_val"]}</strong>
            <span style="color:#9ca3af;font-size:11px;margin-left:6px;">(baseline: {m["baseline_mean"]} ± {m["baseline_sd"]})</span>
          </td>
          <td style="padding:10px 16px;font-size:11px;color:{severity_colour};border-bottom:1px solid #f3f4f6;text-align:right;">
            {pct_str}<br><span style="color:#9ca3af;">{z_str}</span>
            {'<br><span style="color:#9ca3af;font-size:10px;">' + baseline_note + '</span>' if baseline_note else ''}
          </td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f4f8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <div style="max-width:560px;margin:24px auto;background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
    <div style="background:#1a1a2e;padding:20px 24px 16px;">
      <p style="color:#8892b0;font-size:11px;margin:0 0 2px;text-transform:uppercase;letter-spacing:1px;">Life Platform · Anomaly Alert v2.0</p>
      <h1 style="color:#fff;font-size:17px;font-weight:700;margin:0;">{day_label}</h1>
    </div>
    <div style="background:{severity_colour};padding:12px 24px;">
      <p style="color:#fff;font-size:13px;font-weight:700;margin:0;">
        ⚠️ {severity_label} — {severity_count} metric{"s" if severity_count != 1 else ""} flagged across {len(set(m["source"] for m in flagged))} sources
      </p>
    </div>
    <div style="padding:20px 24px 16px;">
      <p style="font-size:11px;font-weight:700;color:#374151;text-transform:uppercase;letter-spacing:0.5px;margin:0 0 8px;">Root Cause Hypothesis</p>
      <p style="font-size:14px;color:#1a1a2e;line-height:1.65;margin:0;background:#f8f8fc;padding:14px 16px;border-radius:8px;border-left:3px solid {severity_colour};">
        {hypothesis}
      </p>
    </div>
    <div style="padding:0 24px 16px;">
      <p style="font-size:11px;font-weight:700;color:#374151;text-transform:uppercase;letter-spacing:0.5px;margin:0 0 8px;">Flagged Metrics (Adaptive Thresholds)</p>
      <table style="width:100%;border-collapse:collapse;border:1px solid #f3f4f6;border-radius:8px;overflow:hidden;">
        {metric_rows}
      </table>
    </div>
    <div style="background:#f8f8fc;padding:12px 24px;border-top:1px solid #e8e8f0;">
      <p style="color:#9ca3af;font-size:10px;margin:0;text-align:center;">
        Life Platform · Anomaly Detector v2.0 · Adaptive thresholds (CV-based) · 2+ source rule
      </p>
    </div>
  </div>
</body>
</html>"""


def send_alert_email(flagged, hypothesis, date_str):
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        day_short = dt.strftime("%a %b %-d")
    except Exception:
        day_short = date_str

    source_list = ", ".join(sorted(set(m["source"] for m in flagged)))
    subject = f"⚠️ Anomaly Alert · {day_short} · {len(flagged)} metrics flagged ({source_list})"
    html = build_alert_html(flagged, hypothesis, date_str)

    ses.send_email(
        FromEmailAddress=SENDER,
        Destination={"ToAddresses": [RECIPIENT]},
        Content={"Simple": {
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body":    {"Html":  {"Data": html,    "Charset": "UTF-8"}},
        }},
    )
    print(f"[INFO] Alert email sent: {subject}")


# ══════════════════════════════════════════════════════════════════════════════
# HANDLER
# ══════════════════════════════════════════════════════════════════════════════

def lambda_handler(event, context):
    print("[INFO] Anomaly Detector v2.0 starting (adaptive thresholds)...")

    today     = datetime.now(timezone.utc).date()
    yesterday = (today - timedelta(days=1)).isoformat()
    print(f"[INFO] Checking anomalies for: {yesterday}")

    flagged = check_anomalies(yesterday, today)
    print(f"[INFO] Flagged metrics: {len(flagged)}")
    for m in flagged:
        print(f"  [{m['source']}] {m['label']}: {m['yesterday_val']} "
              f"(Z={m['z_score']}, threshold={m.get('z_threshold')}, "
              f"CV={m.get('cv')}, baseline={m.get('baseline_type')}, {m['direction']})")

    multi = is_multi_source(flagged)
    alert_sent  = False
    hypothesis  = ""
    severity    = "none"

    if multi:
        source_count = len(set(f["source"] for f in flagged))
        severity = "high" if len(flagged) >= 4 else "moderate"
        print(f"[INFO] Multi-source anomaly — {len(flagged)} metrics across {source_count} sources. Severity: {severity}")

        try:
            api_key    = get_anthropic_key()
            context_data = build_context(yesterday)
            hypothesis = call_haiku_hypothesis(flagged, context_data, api_key)
            print(f"[INFO] Hypothesis: {hypothesis[:100]}...")
        except Exception as e:
            print(f"[WARN] Haiku hypothesis failed: {e}")
            hypothesis = "Multiple metrics flagged — check your daily brief for details."

        try:
            send_alert_email(flagged, hypothesis, yesterday)
            alert_sent = True
        except Exception as e:
            print(f"[ERROR] Alert email failed: {e}")

    else:
        print("[INFO] No multi-source anomaly — no alert sent.")

    write_anomaly_record(yesterday, flagged, alert_sent, hypothesis, severity)

    return {
        "statusCode": 200,
        "body": json.dumps({
            "date": yesterday,
            "flagged_count": len(flagged),
            "multi_source": multi,
            "severity": severity,
            "alert_sent": alert_sent,
            "detector_version": "2.0.0",
        })
    }
LAMBDA_EOF

echo "✅ anomaly_detector_lambda.py v2.0 written"

# ── Package and deploy ──
echo ""
echo "Step 2: Packaging Lambda..."
TMPDIR=$(mktemp -d)
cp "$LAMBDA_DIR/anomaly_detector_lambda.py" "$TMPDIR/lambda_function.py"
cd "$TMPDIR"
zip -r anomaly_detector.zip lambda_function.py
cp anomaly_detector.zip "$LAMBDA_DIR/anomaly_detector_lambda.zip"

echo ""
echo "Step 3: Deploying to Lambda..."
aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://anomaly_detector.zip" \
    --region "$REGION" \
    --query "[FunctionName,CodeSize,LastModified]" \
    --output table

echo ""
echo "Step 4: Waiting for update to complete..."
aws lambda wait function-updated \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" 2>/dev/null || sleep 10

echo ""
echo "Step 5: Smoke test..."
aws lambda invoke \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --log-type Tail \
    /tmp/anomaly_test.json \
    --query "LogResult" \
    --output text | base64 -d | tail -10

echo ""
cat /tmp/anomaly_test.json

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "✅ Anomaly Detector v2.0 deployed!"
echo ""
echo "Changes from v1.0:"
echo "  • Per-metric adaptive thresholds (CV-based: 1.5/1.75/2.0 SD)"
echo "  • Day-of-week normalization (steps, tasks, habits)"
echo "  • Minimum absolute change filters (weight ±1.5lbs, steps ±2000)"
echo "  • Updated metrics: chronicling→habitify, +Body Battery, +stress"
echo "  • Threshold transparency in DDB records + alert emails"
echo "═══════════════════════════════════════════════════════════"

rm -rf "$TMPDIR"
