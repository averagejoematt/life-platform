"""
labs_coaching.py — Biomarker coaching rules for daily brief AI context.

Reads latest lab results from DynamoDB and generates coaching deltas
for out-of-range biomarkers. Injected into daily brief prompts so
AI coaching references actual lab data.

Used by: daily_brief_lambda.py (import, not standalone)
"""

import json
import logging
from decimal import Decimal

logger = logging.getLogger(__name__)


def _float(val):
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


# Coaching rules: biomarker → threshold → coaching delta
# Each rule: (biomarker_key, condition_fn, coaching_text)
COACHING_RULES = [
    ("ferritin", lambda v: v < 40,
     "Low ferritin ({val} ng/mL) — may limit oxygen carry and HRV recovery. Consider iron bisglycinate 25mg + Vitamin C. Recheck in 6 weeks."),
    ("vitamin_d", lambda v: v < 30,
     "Vitamin D low ({val} ng/mL) — suboptimal for immune function and mood. Supplement D3 4000-5000 IU daily with fat-containing meal."),
    ("hs_crp", lambda v: v > 3.0,
     "hs-CRP elevated ({val} mg/L) — systemic inflammation marker. Prioritize anti-inflammatory protocol: omega-3, turmeric, reduce processed food, check sleep quality."),
    ("hba1c", lambda v: v > 5.6,
     "HbA1c above optimal ({val}%) — 90-day glucose average suggests prediabetic territory. CGM data + carb timing should be priority."),
    ("fasting_insulin", lambda v: v > 10,
     "Fasting insulin elevated ({val} uIU/mL) — insulin resistance signal. Prioritize Zone 2 exercise, reduce refined carbs, consider berberine."),
    ("apob", lambda v: v > 90,
     "ApoB elevated ({val} mg/dL) — cardiovascular risk marker. Attia recommendation: target <80 mg/dL. Consider dietary changes or statin discussion."),
    ("testosterone_total", lambda v: v < 400,
     "Testosterone low-normal ({val} ng/dL) — may affect energy, recovery, mood. Prioritize sleep, resistance training, stress management. Recheck in 3 months."),
    ("tsh", lambda v: v > 2.5,
     "TSH above optimal ({val} mIU/L) — thyroid may be struggling. Prioritize selenium, iodine, stress reduction. Recheck in 6 weeks."),
]


def build_labs_coaching_context(table, user_prefix):
    """Read latest lab results and generate coaching deltas.

    Returns a string to inject into daily brief prompts, or empty string if no actionable findings.
    """
    try:
        from boto3.dynamodb.conditions import Key
        # Read latest labs — try the clinical.json S3 approach used by handle_labs
        labs_pk = f"{user_prefix}labs"
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(labs_pk),
            ScanIndexForward=False,
            Limit=20,
        )
        items = resp.get("Items", [])
        if not items:
            return ""

        # Build biomarker lookup from all lab items
        biomarkers = {}
        for item in items:
            # Try common field patterns
            for key in item:
                if key in ("pk", "sk", "date", "source", "ingested_at"):
                    continue
                val = _float(item[key])
                if val is not None:
                    # Normalize key to lowercase
                    biomarkers[key.lower().replace(" ", "_")] = val

        # Apply coaching rules
        coaching_lines = []
        for bm_key, condition_fn, template in COACHING_RULES:
            val = biomarkers.get(bm_key)
            if val is not None:
                try:
                    if condition_fn(val):
                        coaching_lines.append(template.format(val=val))
                except Exception:
                    pass

        if not coaching_lines:
            return ""

        result = "LABS COACHING (from most recent bloodwork):\n" + "\n".join(f"- {line}" for line in coaching_lines[:4])
        logger.info(f"Labs coaching: {len(coaching_lines)} actionable biomarkers")
        return result

    except Exception as e:
        logger.warning(f"Labs coaching failed (non-fatal): {e}")
        return ""
