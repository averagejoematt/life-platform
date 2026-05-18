#!/usr/bin/env python3
"""
patch_ascvd_risk.py — Add 10-year ASCVD risk score to existing labs records.

Implements the Pooled Cohort Equations (2013 ACC/AHA) to compute 10-year
atherosclerotic cardiovascular disease risk. Stores on each labs draw record.

Inputs pulled from labs biomarkers:
  - total_cholesterol (cholesterol_total)
  - HDL cholesterol (hdl)
  - systolic BP (manual input — not in current data sources)
  - diabetes (derived from HbA1c or glucose)
  - smoking status (from profile/manual)

Note: PCE validated for ages 40-79. Matthew is 36 at time of draws —
score is computed as a forward-looking reference but flagged as extrapolated.

Usage:
  python3 patch_ascvd_risk.py
"""

import boto3
import math
from decimal import Decimal
from datetime import datetime, timezone

TABLE_NAME = "life-platform"
REGION = "us-west-2"
PK = "USER#matthew#SOURCE#labs"

# ─────────────────────────────────────────────
# Pooled Cohort Equations Coefficients (2013)
# ─────────────────────────────────────────────

# White Males
_WM = {
    "ln_age":          12.344,
    "ln_tc":           11.853,
    "ln_hdl":          -7.990,
    "ln_sbp_treated":   1.797,
    "ln_sbp_untreated": 1.764,
    "smoking":          7.837,
    "diabetes":         0.658,
    "mean_coeff_sum":  61.18,
    "baseline_surv":    0.9144,
}

# African American Males
_AAM = {
    "ln_age":           2.469,
    "ln_tc":            0.302,
    "ln_hdl":          -0.307,
    "ln_sbp_treated":   1.916,
    "ln_sbp_untreated": 1.809,
    "smoking":          0.549,
    "diabetes":         0.645,
    "mean_coeff_sum":  19.54,
    "baseline_surv":    0.8954,
}

# White Females
_WF = {
    "ln_age":          -29.799,
    "ln_age_sq":         4.884,
    "ln_tc":           13.540,
    "ln_age_x_ln_tc":  -3.114,
    "ln_hdl":         -13.578,
    "ln_age_x_ln_hdl":  3.149,
    "ln_sbp_treated":   2.019,
    "ln_sbp_untreated": 1.957,
    "smoking":          7.574,
    "ln_age_x_smoking":-1.665,
    "diabetes":         0.661,
    "mean_coeff_sum": -29.18,
    "baseline_surv":    0.9665,
}

# African American Females
_AAF = {
    "ln_age":          17.114,
    "ln_tc":            0.940,
    "ln_hdl":         -18.920,
    "ln_age_x_ln_hdl":  4.475,
    "ln_sbp_treated":  29.291,
    "ln_age_x_ln_sbp_t": -6.432,
    "ln_sbp_untreated":27.820,
    "ln_age_x_ln_sbp_u": -6.087,
    "smoking":          0.691,
    "diabetes":         0.874,
    "mean_coeff_sum":  86.61,
    "baseline_surv":    0.9533,
}


def compute_ascvd_10yr(
    age: float,
    sex: str,           # "male" or "female"
    race: str,          # "white" or "african_american"
    total_cholesterol: float,
    hdl: float,
    systolic_bp: float,
    bp_treated: bool = False,
    is_diabetic: bool = False,
    is_smoker: bool = False,
) -> dict:
    """
    Compute 10-year ASCVD risk using Pooled Cohort Equations.

    Returns dict with risk_pct, risk_category, inputs, and caveats.
    """
    caveats = []
    if age < 40:
        caveats.append(f"Age {age} is below validated range (40-79). Score is extrapolated.")
    if age > 79:
        caveats.append(f"Age {age} is above validated range (40-79). Score is extrapolated.")

    ln_age = math.log(age)
    ln_tc = math.log(total_cholesterol)
    ln_hdl = math.log(hdl)
    ln_sbp = math.log(systolic_bp)

    smoking_val = 1.0 if is_smoker else 0.0
    diabetes_val = 1.0 if is_diabetic else 0.0

    if sex == "male":
        c = _WM if race == "white" else _AAM
        sbp_coeff = c["ln_sbp_treated"] if bp_treated else c["ln_sbp_untreated"]

        individual_sum = (
            c["ln_age"] * ln_age +
            c["ln_tc"] * ln_tc +
            c["ln_hdl"] * ln_hdl +
            sbp_coeff * ln_sbp +
            c["smoking"] * smoking_val +
            c["diabetes"] * diabetes_val
        )
    else:
        # Female equations have interaction terms
        if race == "white":
            c = _WF
            sbp_coeff = c["ln_sbp_treated"] if bp_treated else c["ln_sbp_untreated"]
            individual_sum = (
                c["ln_age"] * ln_age +
                c.get("ln_age_sq", 0) * ln_age ** 2 +
                c["ln_tc"] * ln_tc +
                c.get("ln_age_x_ln_tc", 0) * ln_age * ln_tc +
                c["ln_hdl"] * ln_hdl +
                c.get("ln_age_x_ln_hdl", 0) * ln_age * ln_hdl +
                sbp_coeff * ln_sbp +
                c["smoking"] * smoking_val +
                c.get("ln_age_x_smoking", 0) * ln_age * smoking_val +
                c["diabetes"] * diabetes_val
            )
        else:
            c = _AAF
            if bp_treated:
                sbp_term = c["ln_sbp_treated"] * ln_sbp + c.get("ln_age_x_ln_sbp_t", 0) * ln_age * ln_sbp
            else:
                sbp_term = c["ln_sbp_untreated"] * ln_sbp + c.get("ln_age_x_ln_sbp_u", 0) * ln_age * ln_sbp
            individual_sum = (
                c["ln_age"] * ln_age +
                c["ln_tc"] * ln_tc +
                c["ln_hdl"] * ln_hdl +
                c.get("ln_age_x_ln_hdl", 0) * ln_age * ln_hdl +
                sbp_term +
                c["smoking"] * smoking_val +
                c["diabetes"] * diabetes_val
            )

    risk_pct = round(
        (1.0 - c["baseline_surv"] ** math.exp(individual_sum - c["mean_coeff_sum"])) * 100,
        2
    )

    # Clamp to reasonable bounds
    risk_pct = max(0.01, min(risk_pct, 99.99))

    # Risk categories (ACC/AHA 2018 guidelines)
    if risk_pct < 5.0:
        category = "low"
    elif risk_pct < 7.5:
        category = "borderline"
    elif risk_pct < 20.0:
        category = "intermediate"
    else:
        category = "high"

    return {
        "ascvd_risk_10yr_pct": risk_pct,
        "risk_category": category,
        "inputs": {
            "age": age,
            "sex": sex,
            "race": race,
            "total_cholesterol_mg_dl": total_cholesterol,
            "hdl_mg_dl": hdl,
            "systolic_bp_mmhg": systolic_bp,
            "bp_treated": bp_treated,
            "is_diabetic": is_diabetic,
            "is_smoker": is_smoker,
        },
        "equation": "Pooled Cohort Equations (2013 ACC/AHA)",
        "caveats": caveats,
    }


# ─────────────────────────────────────────────
# Matthew's known inputs (from profile + labs)
# ─────────────────────────────────────────────

# BP not currently tracked — using clinically reasonable estimate for a
# 36-year-old male at 302 lbs with excellent metabolic markers (glucose 86,
# HbA1c 4.9, hs-CRP <0.2). Update when actual BP readings available.
MATTHEW_BP_ESTIMATE = 125  # mmHg systolic — conservative estimate
MATTHEW_RACE = "white"
MATTHEW_SEX = "male"
MATTHEW_DOB = "1989-02-07"
MATTHEW_BP_TREATED = False
MATTHEW_IS_SMOKER = False


def compute_age_at_date(dob_str: str, draw_date_str: str) -> float:
    """Compute age in years at a given date."""
    dob = datetime.strptime(dob_str, "%Y-%m-%d")
    draw = datetime.strptime(draw_date_str, "%Y-%m-%d")
    age = (draw - dob).days / 365.25
    return round(age, 1)


def is_diabetic_from_labs(biomarkers: dict) -> bool:
    """Derive diabetes status from HbA1c or fasting glucose."""
    hba1c = biomarkers.get("hba1c", {}).get("value_numeric")
    glucose = biomarkers.get("glucose", {}).get("value_numeric")
    if hba1c is not None and float(hba1c) >= 6.5:
        return True
    if glucose is not None and float(glucose) >= 126:
        return True
    return False


def patch_labs_records():
    """Add ASCVD risk score to existing labs records in DynamoDB."""
    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    table = dynamodb.Table(TABLE_NAME)

    # Query all labs records
    from boto3.dynamodb.conditions import Key
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(PK) & Key("sk").begins_with("DATE#")
    )
    items = resp.get("Items", [])

    print(f"Found {len(items)} labs draw records")

    for item in items:
        draw_date = item.get("draw_date")
        biomarkers = item.get("biomarkers", {})

        # Get required inputs
        tc_bm = biomarkers.get("cholesterol_total", {})
        hdl_bm = biomarkers.get("hdl", {})

        tc = tc_bm.get("value_numeric")
        hdl_val = hdl_bm.get("value_numeric")

        if tc is None or hdl_val is None:
            print(f"  {draw_date}: Skipping — missing total cholesterol or HDL")
            # Still store a placeholder
            table.update_item(
                Key={"pk": PK, "sk": item["sk"]},
                UpdateExpression="SET ascvd_risk_10yr_pct = :null_note, updated_at = :now",
                ExpressionAttributeValues={
                    ":null_note": "insufficient_data — missing total_cholesterol or HDL on this draw",
                    ":now": datetime.now(timezone.utc).isoformat(),
                },
            )
            continue

        age = compute_age_at_date(MATTHEW_DOB, draw_date)
        is_diabetic = is_diabetic_from_labs(biomarkers)

        result = compute_ascvd_10yr(
            age=age,
            sex=MATTHEW_SEX,
            race=MATTHEW_RACE,
            total_cholesterol=float(tc),
            hdl=float(hdl_val),
            systolic_bp=MATTHEW_BP_ESTIMATE,
            bp_treated=MATTHEW_BP_TREATED,
            is_diabetic=is_diabetic,
            is_smoker=MATTHEW_IS_SMOKER,
        )

        # Convert to Decimal for DynamoDB
        ascvd_pct = Decimal(str(result["ascvd_risk_10yr_pct"]))
        ascvd_inputs = {
            "age": Decimal(str(result["inputs"]["age"])),
            "sex": result["inputs"]["sex"],
            "race": result["inputs"]["race"],
            "total_cholesterol_mg_dl": Decimal(str(result["inputs"]["total_cholesterol_mg_dl"])),
            "hdl_mg_dl": Decimal(str(result["inputs"]["hdl_mg_dl"])),
            "systolic_bp_mmhg": Decimal(str(result["inputs"]["systolic_bp_mmhg"])),
            "systolic_bp_source": "estimate — no BP monitor data. Update with actual readings.",
            "bp_treated": result["inputs"]["bp_treated"],
            "is_diabetic": result["inputs"]["is_diabetic"],
            "is_smoker": result["inputs"]["is_smoker"],
        }

        table.update_item(
            Key={"pk": PK, "sk": item["sk"]},
            UpdateExpression=(
                "SET ascvd_risk_10yr_pct = :pct, "
                "ascvd_risk_category = :cat, "
                "ascvd_inputs = :inputs, "
                "ascvd_equation = :eq, "
                "ascvd_caveats = :cav, "
                "updated_at = :now"
            ),
            ExpressionAttributeValues={
                ":pct": ascvd_pct,
                ":cat": result["risk_category"],
                ":inputs": ascvd_inputs,
                ":eq": result["equation"],
                ":cav": result["caveats"],
                ":now": datetime.now(timezone.utc).isoformat(),
            },
        )

        print(f"  {draw_date}: ASCVD 10yr = {result['ascvd_risk_10yr_pct']}% ({result['risk_category']})")
        print(f"    Age: {age}, TC: {float(tc)}, HDL: {float(hdl_val)}, SBP: {MATTHEW_BP_ESTIMATE} (est)")
        print(f"    Diabetic: {is_diabetic}, Smoker: {MATTHEW_IS_SMOKER}")
        if result["caveats"]:
            for c in result["caveats"]:
                print(f"    ⚠️  {c}")

    print(f"\n{'='*50}")
    print("ASCVD risk scores patched on all eligible labs records.")
    print(f"NOTE: SBP uses estimate ({MATTHEW_BP_ESTIMATE} mmHg). Update when BP monitor data available.")


if __name__ == "__main__":
    patch_labs_records()
