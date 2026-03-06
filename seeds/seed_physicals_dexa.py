#!/usr/bin/env python3
"""
seed_physicals_dexa.py — Seed GP physical blood draws + DEXA scan into Life Platform DynamoDB.

Adds 5 GP blood draws (2019-2024) and 1 DEXA body composition scan to the platform.
Uses the same biomarker format as seed_labs.py for seamless trending across all draws.

Lab draws added:
  2019-05-01  One Medical / LabCorp (SE) — 35 biomarkers
  2020-10-20  One Medical / LabCorp (SE) — 35 biomarkers (from Excel)
  2021-10-20  One Medical / LabCorp (SE) — 34 biomarkers (from PDF, new draw)
  2022-06-01  One Medical / LabCorp (SE) — 33 biomarkers
  2024-06-01  One Medical / LabCorp (SE) — 45 biomarkers (added WBC diff)

DEXA scan added:
  2025-05-10  DexaFit Seattle — body composition + posture assessment

Schema:
  Labs:  PK=USER#matthew#SOURCE#labs  SK=DATE#YYYY-MM-DD
  DEXA:  PK=USER#matthew#SOURCE#dexa  SK=DATE#YYYY-MM-DD

Usage:
  python3 seed_physicals_dexa.py          # dry run
  python3 seed_physicals_dexa.py --write  # write to DynamoDB
"""

import boto3
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal

TABLE_NAME = "life-platform"
REGION = "us-west-2"
USER = "matthew"

LABS_PK = f"USER#{USER}#SOURCE#labs"
DEXA_PK = f"USER#{USER}#SOURCE#dexa"

NOW = datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────

def bm(value, unit, ref_text, flag="normal", category="uncategorized",
       value_numeric=None, ref_low=None, ref_high=None):
    """Build a biomarker dict matching seed_labs.py format."""
    if value_numeric is None:
        if isinstance(value, (int, float)):
            value_numeric = float(value)
        elif isinstance(value, str):
            cleaned = value.replace("<", "").replace(">", "").replace("≤", "").replace("≥", "")
            try:
                value_numeric = float(cleaned)
            except (ValueError, TypeError):
                value_numeric = None

    entry = {
        "value": value if isinstance(value, str) else Decimal(str(value)),
        "unit": unit,
        "ref_text": ref_text,
        "flag": flag,
        "category": category,
    }

    if value_numeric is not None:
        entry["value_numeric"] = Decimal(str(value_numeric))
    if ref_low is not None:
        entry["ref_low"] = Decimal(str(ref_low))
    if ref_high is not None:
        entry["ref_high"] = Decimal(str(ref_high))

    return entry


def build_draw_item(date, biomarkers, provider, lab_network, specimen_id=None,
                    report_date=None, physician=None, fasting=True):
    """Build a complete DynamoDB item for a blood draw."""
    out_of_range = [k for k, v in biomarkers.items() if v["flag"] in ("high", "low")]
    item = {
        "pk": LABS_PK,
        "sk": f"DATE#{date}",
        "draw_date": date,
        "lab_provider": provider,
        "lab_network": lab_network,
        "fasting": fasting,
        "biomarkers": biomarkers,
        "out_of_range": out_of_range,
        "out_of_range_count": len(out_of_range),
        "total_biomarkers": len(biomarkers),
        "updated_at": NOW,
    }
    if specimen_id:
        item["specimen_id"] = specimen_id
    if report_date:
        item["report_date"] = report_date
    if physician:
        item["physician"] = physician
    return item


# ═══════════════════════════════════════════════
# DRAW: 2019-05-01  — One Medical / LabCorp SE
# 35 biomarkers, 0 out of range
# ═══════════════════════════════════════════════

draw_2019 = {
    # --- CBC ---
    "wbc": bm(5.5, "x10E3/uL", "3.4-10.8", category="cbc", ref_low=3.4, ref_high=10.8),
    "rbc": bm(4.77, "x10E6/uL", "4.14-5.80", category="cbc", ref_low=4.14, ref_high=5.80),
    "hemoglobin": bm(14.5, "g/dL", "13.0-17.7", category="cbc", ref_low=13.0, ref_high=17.7),
    "hematocrit": bm(42.5, "%", "37.5-51.0", category="cbc", ref_low=37.5, ref_high=51.0),
    "mcv": bm(89, "fL", "79-97", category="cbc", ref_low=79, ref_high=97),
    "mch": bm(30.4, "pg", "26.6-33.0", category="cbc", ref_low=26.6, ref_high=33.0),
    "mchc": bm(34.1, "g/dL", "31.5-35.7", category="cbc", ref_low=31.5, ref_high=35.7),
    "rdw": bm(13.5, "%", "12.3-15.4", category="cbc", ref_low=12.3, ref_high=15.4),
    "platelets": bm(250, "x10E3/uL", "150-379", category="cbc", ref_low=150, ref_high=379),
    # --- Thyroid ---
    "tsh": bm(3.4, "uIU/mL", "0.450-4.500", category="thyroid", ref_low=0.45, ref_high=4.5),
    # --- Lipids ---
    "cholesterol_total": bm(163, "mg/dL", "100-199", category="lipids", ref_low=100, ref_high=199),
    "triglycerides": bm(48, "mg/dL", "0-149", category="lipids", ref_low=0, ref_high=149),
    "hdl": bm(58, "mg/dL", ">39", category="lipids", ref_low=39),
    "vldl": bm(10, "mg/dL", "5-40", category="lipids", ref_low=5, ref_high=40),
    "ldl_c": bm(95, "mg/dL", "0-99", category="lipids", ref_low=0, ref_high=99),
    "chol_hdl_ratio": bm(2.8, "ratio", "0.0-5.0", category="lipids", ref_low=0, ref_high=5.0),
    # --- Metabolic (CMP) ---
    "glucose": bm(81, "mg/dL", "65-99", category="metabolic", ref_low=65, ref_high=99),
    "bun": bm(16, "mg/dL", "6-20", category="kidney", ref_low=6, ref_high=20),
    "creatinine": bm(1.04, "mg/dL", "0.76-1.27", category="kidney", ref_low=0.76, ref_high=1.27),
    "egfr": bm(96, "mL/min/1.73", ">59", category="kidney", ref_low=59),
    "bun_creatinine_ratio": bm(15, "", "9-20", category="kidney", ref_low=9, ref_high=20),
    "sodium": bm(142, "mmol/L", "134-144", category="electrolytes", ref_low=134, ref_high=144),
    "potassium": bm(4.3, "mmol/L", "3.5-5.2", category="electrolytes", ref_low=3.5, ref_high=5.2),
    "chloride": bm(103, "mmol/L", "96-106", category="electrolytes", ref_low=96, ref_high=106),
    "co2": bm(25, "mmol/L", "20-29", category="electrolytes", ref_low=20, ref_high=29),
    "calcium": bm(9.6, "mg/dL", "8.7-10.2", category="minerals", ref_low=8.7, ref_high=10.2),
    "protein_total": bm(7.2, "g/dL", "6.0-8.5", category="metabolic", ref_low=6.0, ref_high=8.5),
    "albumin": bm(4.6, "g/dL", "3.5-5.5", category="metabolic", ref_low=3.5, ref_high=5.5),
    "globulin": bm(2.6, "g/dL", "1.5-4.5", category="metabolic", ref_low=1.5, ref_high=4.5),
    "ag_ratio": bm(1.8, "", "1.2-2.2", category="metabolic", ref_low=1.2, ref_high=2.2),
    "bilirubin_total": bm(0.5, "mg/dL", "0.0-1.2", category="liver", ref_low=0, ref_high=1.2),
    "alkaline_phosphatase": bm(58, "IU/L", "39-117", category="liver", ref_low=39, ref_high=117),
    "ast": bm(20, "IU/L", "0-40", category="liver", ref_low=0, ref_high=40),
    "alt": bm(28, "IU/L", "0-44", category="liver", ref_low=0, ref_high=44),
    # --- Diabetes ---
    "hba1c": bm(5.2, "%", "4.8-5.6", category="diabetes", ref_low=4.8, ref_high=5.6),
}

draw_2019_item = build_draw_item(
    "2019-05-01", draw_2019,
    provider="one_medical", lab_network="labcorp",
    physician="Soriano, E", fasting=True,
)


# ═══════════════════════════════════════════════
# DRAW: 2020-10-20  — One Medical / LabCorp SE
# 35 biomarkers, 0 out of range
# ═══════════════════════════════════════════════

draw_2020 = {
    # --- CBC ---
    "wbc": bm(5.0, "x10E3/uL", "3.4-10.8", category="cbc", ref_low=3.4, ref_high=10.8),
    "rbc": bm(4.74, "x10E6/uL", "4.14-5.80", category="cbc", ref_low=4.14, ref_high=5.80),
    "hemoglobin": bm(14.1, "g/dL", "13.0-17.7", category="cbc", ref_low=13.0, ref_high=17.7),
    "hematocrit": bm(43.7, "%", "37.5-51.0", category="cbc", ref_low=37.5, ref_high=51.0),
    "mcv": bm(92, "fL", "79-97", category="cbc", ref_low=79, ref_high=97),
    "mch": bm(29.7, "pg", "26.6-33.0", category="cbc", ref_low=26.6, ref_high=33.0),
    "mchc": bm(32.3, "g/dL", "31.5-35.7", category="cbc", ref_low=31.5, ref_high=35.7),
    "rdw": bm(12.6, "%", "12.3-15.4", category="cbc", ref_low=12.3, ref_high=15.4),
    "platelets": bm(250, "x10E3/uL", "150-379", category="cbc", ref_low=150, ref_high=379),
    # --- Thyroid ---
    "tsh": bm(2.93, "uIU/mL", "0.450-4.500", category="thyroid", ref_low=0.45, ref_high=4.5),
    # --- Lipids ---
    "cholesterol_total": bm(151, "mg/dL", "100-199", category="lipids", ref_low=100, ref_high=199),
    "triglycerides": bm(88, "mg/dL", "0-149", category="lipids", ref_low=0, ref_high=149),
    "hdl": bm(62, "mg/dL", ">39", category="lipids", ref_low=39),
    "vldl": bm(16, "mg/dL", "5-40", category="lipids", ref_low=5, ref_high=40),
    "ldl_c": bm(73, "mg/dL", "0-99", category="lipids", ref_low=0, ref_high=99),
    "chol_hdl_ratio": bm(2.4, "ratio", "0.0-5.0", category="lipids", ref_low=0, ref_high=5.0),
    # --- Metabolic (CMP) ---
    "glucose": bm(81, "mg/dL", "65-99", category="metabolic", ref_low=65, ref_high=99),
    "bun": bm(19, "mg/dL", "6-20", category="kidney", ref_low=6, ref_high=20),
    "creatinine": bm(0.94, "mg/dL", "0.76-1.27", category="kidney", ref_low=0.76, ref_high=1.27),
    "egfr": bm(108, "mL/min/1.73", ">59", category="kidney", ref_low=59),
    "bun_creatinine_ratio": bm(20, "", "9-20", category="kidney", ref_low=9, ref_high=20),
    "sodium": bm(141, "mmol/L", "134-144", category="electrolytes", ref_low=134, ref_high=144),
    "potassium": bm(4.1, "mmol/L", "3.5-5.2", category="electrolytes", ref_low=3.5, ref_high=5.2),
    "chloride": bm(105, "mmol/L", "96-106", category="electrolytes", ref_low=96, ref_high=106),
    "co2": bm(24, "mmol/L", "20-29", category="electrolytes", ref_low=20, ref_high=29),
    "calcium": bm(9.4, "mg/dL", "8.7-10.2", category="minerals", ref_low=8.7, ref_high=10.2),
    "protein_total": bm(6.7, "g/dL", "6.0-8.5", category="metabolic", ref_low=6.0, ref_high=8.5),
    "albumin": bm(4.2, "g/dL", "3.5-5.5", category="metabolic", ref_low=3.5, ref_high=5.5),
    "globulin": bm(2.5, "g/dL", "1.5-4.5", category="metabolic", ref_low=1.5, ref_high=4.5),
    "ag_ratio": bm(1.7, "", "1.2-2.2", category="metabolic", ref_low=1.2, ref_high=2.2),
    "bilirubin_total": bm(0.5, "mg/dL", "0.0-1.2", category="liver", ref_low=0, ref_high=1.2),
    "alkaline_phosphatase": bm(66, "IU/L", "39-117", category="liver", ref_low=39, ref_high=117),
    "ast": bm(12, "IU/L", "0-40", category="liver", ref_low=0, ref_high=40),
    "alt": bm(12, "IU/L", "0-44", category="liver", ref_low=0, ref_high=44),
    # --- Diabetes ---
    "hba1c": bm(5.2, "%", "4.8-5.6", category="diabetes", ref_low=4.8, ref_high=5.6),
}

draw_2020_item = build_draw_item(
    "2020-10-20", draw_2020,
    provider="one_medical", lab_network="labcorp",
    physician="Soriano, E", fasting=True,
)


# ═══════════════════════════════════════════════
# DRAW: 2021-10-20  — One Medical / LabCorp SE
# From PDF Document-16691811-complete.pdf
# Specimen 29312917580, reported 2021-10-21
# 34 biomarkers, 2 out of range
# ═══════════════════════════════════════════════

draw_2021 = {
    # --- CBC ---
    "wbc": bm(4.9, "x10E3/uL", "3.4-10.8", category="cbc", ref_low=3.4, ref_high=10.8),
    "rbc": bm(5.12, "x10E6/uL", "4.14-5.80", category="cbc", ref_low=4.14, ref_high=5.80),
    "hemoglobin": bm(15.4, "g/dL", "13.0-17.7", category="cbc", ref_low=13.0, ref_high=17.7),
    "hematocrit": bm(45.5, "%", "37.5-51.0", category="cbc", ref_low=37.5, ref_high=51.0),
    "mcv": bm(89, "fL", "79-97", category="cbc", ref_low=79, ref_high=97),
    "mch": bm(30.1, "pg", "26.6-33.0", category="cbc", ref_low=26.6, ref_high=33.0),
    "mchc": bm(33.8, "g/dL", "31.5-35.7", category="cbc", ref_low=31.5, ref_high=35.7),
    "rdw": bm(12.8, "%", "11.6-15.4", category="cbc", ref_low=11.6, ref_high=15.4),
    "platelets": bm(260, "x10E3/uL", "150-450", category="cbc", ref_low=150, ref_high=450),
    # --- Thyroid ---
    "tsh": bm(2.94, "uIU/mL", "0.450-4.500", category="thyroid", ref_low=0.45, ref_high=4.5),
    # --- Lipids ---
    "cholesterol_total": bm(212, "mg/dL", "100-199", flag="high", category="lipids", ref_low=100, ref_high=199),
    "triglycerides": bm(72, "mg/dL", "0-149", category="lipids", ref_low=0, ref_high=149),
    "hdl": bm(73, "mg/dL", ">39", category="lipids", ref_low=39),
    "vldl": bm(13, "mg/dL", "5-40", category="lipids", ref_low=5, ref_high=40),
    "ldl_c": bm(126, "mg/dL", "0-99", flag="high", category="lipids", ref_low=0, ref_high=99),
    # --- Metabolic (CMP) ---
    "glucose": bm(76, "mg/dL", "65-99", category="metabolic", ref_low=65, ref_high=99),
    "bun": bm(15, "mg/dL", "6-20", category="kidney", ref_low=6, ref_high=20),
    "creatinine": bm(0.93, "mg/dL", "0.76-1.27", category="kidney", ref_low=0.76, ref_high=1.27),
    "egfr": bm(108, "mL/min/1.73", ">59", category="kidney", ref_low=59),
    "bun_creatinine_ratio": bm(16, "", "9-20", category="kidney", ref_low=9, ref_high=20),
    "sodium": bm(141, "mmol/L", "134-144", category="electrolytes", ref_low=134, ref_high=144),
    "potassium": bm(4.3, "mmol/L", "3.5-5.2", category="electrolytes", ref_low=3.5, ref_high=5.2),
    "chloride": bm(101, "mmol/L", "96-106", category="electrolytes", ref_low=96, ref_high=106),
    "co2": bm(24, "mmol/L", "20-29", category="electrolytes", ref_low=20, ref_high=29),
    "calcium": bm(10.0, "mg/dL", "8.7-10.2", category="minerals", ref_low=8.7, ref_high=10.2),
    "protein_total": bm(7.7, "g/dL", "6.0-8.5", category="metabolic", ref_low=6.0, ref_high=8.5),
    "albumin": bm(4.8, "g/dL", "4.0-5.0", category="metabolic", ref_low=4.0, ref_high=5.0),
    "globulin": bm(2.9, "g/dL", "1.5-4.5", category="metabolic", ref_low=1.5, ref_high=4.5),
    "ag_ratio": bm(1.7, "", "1.2-2.2", category="metabolic", ref_low=1.2, ref_high=2.2),
    "bilirubin_total": bm(0.8, "mg/dL", "0.0-1.2", category="liver", ref_low=0, ref_high=1.2),
    "alkaline_phosphatase": bm(68, "IU/L", "44-121", category="liver", ref_low=44, ref_high=121),
    "ast": bm(21, "IU/L", "0-40", category="liver", ref_low=0, ref_high=40),
    "alt": bm(25, "IU/L", "0-44", category="liver", ref_low=0, ref_high=44),
    # --- Diabetes ---
    "hba1c": bm(5.0, "%", "4.8-5.6", category="diabetes", ref_low=4.8, ref_high=5.6),
}

draw_2021_item = build_draw_item(
    "2021-10-20", draw_2021,
    provider="one_medical", lab_network="labcorp",
    specimen_id="29312917580", report_date="2021-10-21",
    physician="Soriano, E", fasting=False,
)


# ═══════════════════════════════════════════════
# DRAW: 2022-06-01  — One Medical / LabCorp SE
# Specimen 15292500690, reported 2022-06-02
# 33 biomarkers, 2 out of range
# ═══════════════════════════════════════════════

draw_2022 = {
    # --- CBC ---
    "wbc": bm(4.8, "x10E3/uL", "3.4-10.8", category="cbc", ref_low=3.4, ref_high=10.8),
    "rbc": bm(4.53, "x10E6/uL", "4.14-5.80", category="cbc", ref_low=4.14, ref_high=5.80),
    "hemoglobin": bm(13.6, "g/dL", "13.0-17.7", category="cbc", ref_low=13.0, ref_high=17.7),
    "hematocrit": bm(40.7, "%", "37.5-51.0", category="cbc", ref_low=37.5, ref_high=51.0),
    "mcv": bm(90, "fL", "79-97", category="cbc", ref_low=79, ref_high=97),
    "mch": bm(30.0, "pg", "26.6-33.0", category="cbc", ref_low=26.6, ref_high=33.0),
    "mchc": bm(33.4, "g/dL", "31.5-35.7", category="cbc", ref_low=31.5, ref_high=35.7),
    "rdw": bm(12.7, "%", "11.6-15.4", category="cbc", ref_low=11.6, ref_high=15.4),
    "platelets": bm(241, "x10E3/uL", "150-450", category="cbc", ref_low=150, ref_high=450),
    # --- Thyroid ---
    "tsh": bm(2.47, "uIU/mL", "0.450-4.500", category="thyroid", ref_low=0.45, ref_high=4.5),
    # --- Lipids ---
    "cholesterol_total": bm(201, "mg/dL", "100-199", flag="high", category="lipids", ref_low=100, ref_high=199),
    "triglycerides": bm(55, "mg/dL", "0-149", category="lipids", ref_low=0, ref_high=149),
    "hdl": bm(56, "mg/dL", ">39", category="lipids", ref_low=39),
    "vldl": bm(10, "mg/dL", "5-40", category="lipids", ref_low=5, ref_high=40),
    "ldl_c": bm(135, "mg/dL", "0-99", flag="high", category="lipids", ref_low=0, ref_high=99),
    # --- Metabolic (CMP) ---
    "glucose": bm(81, "mg/dL", "65-99", category="metabolic", ref_low=65, ref_high=99),
    "bun": bm(14, "mg/dL", "6-20", category="kidney", ref_low=6, ref_high=20),
    "creatinine": bm(0.84, "mg/dL", "0.76-1.27", category="kidney", ref_low=0.76, ref_high=1.27),
    "egfr": bm(118, "mL/min/1.73", ">59", category="kidney", ref_low=59),
    "bun_creatinine_ratio": bm(17, "", "9-20", category="kidney", ref_low=9, ref_high=20),
    "sodium": bm(141, "mmol/L", "134-144", category="electrolytes", ref_low=134, ref_high=144),
    "potassium": bm(4.5, "mmol/L", "3.5-5.2", category="electrolytes", ref_low=3.5, ref_high=5.2),
    "chloride": bm(102, "mmol/L", "96-106", category="electrolytes", ref_low=96, ref_high=106),
    "co2": bm(25, "mmol/L", "20-29", category="electrolytes", ref_low=20, ref_high=29),
    "calcium": bm(9.4, "mg/dL", "8.7-10.2", category="minerals", ref_low=8.7, ref_high=10.2),
    "protein_total": bm(6.8, "g/dL", "6.0-8.5", category="metabolic", ref_low=6.0, ref_high=8.5),
    "albumin": bm(4.4, "g/dL", "4.0-5.0", category="metabolic", ref_low=4.0, ref_high=5.0),
    "globulin": bm(2.4, "g/dL", "1.5-4.5", category="metabolic", ref_low=1.5, ref_high=4.5),
    "ag_ratio": bm(1.8, "", "1.2-2.2", category="metabolic", ref_low=1.2, ref_high=2.2),
    "bilirubin_total": bm(0.6, "mg/dL", "0.0-1.2", category="liver", ref_low=0, ref_high=1.2),
    "alkaline_phosphatase": bm(51, "IU/L", "44-121", category="liver", ref_low=44, ref_high=121),
    "ast": bm(12, "IU/L", "0-40", category="liver", ref_low=0, ref_high=40),
    "alt": bm(14, "IU/L", "0-44", category="liver", ref_low=0, ref_high=44),
}

draw_2022_item = build_draw_item(
    "2022-06-01", draw_2022,
    provider="one_medical", lab_network="labcorp",
    specimen_id="15292500690", report_date="2022-06-02",
    physician="Soriano, E", fasting=True,
)


# ═══════════════════════════════════════════════
# DRAW: 2024-06-01  — One Medical / LabCorp SE
# 45 biomarkers (added WBC differential), 2 out of range
# Date approximated from Excel header "June 2024"
# ═══════════════════════════════════════════════

draw_2024 = {
    # --- CBC ---
    "wbc": bm(3.8, "x10E3/uL", "3.4-10.8", category="cbc", ref_low=3.4, ref_high=10.8),
    "rbc": bm(4.88, "x10E6/uL", "4.14-5.80", category="cbc", ref_low=4.14, ref_high=5.80),
    "hemoglobin": bm(14.9, "g/dL", "13.0-17.7", category="cbc", ref_low=13.0, ref_high=17.7),
    "hematocrit": bm(44.6, "%", "37.5-51.0", category="cbc", ref_low=37.5, ref_high=51.0),
    "mcv": bm(91, "fL", "79-97", category="cbc", ref_low=79, ref_high=97),
    "mch": bm(30.5, "pg", "26.6-33.0", category="cbc", ref_low=26.6, ref_high=33.0),
    "mchc": bm(33.4, "g/dL", "31.5-35.7", category="cbc", ref_low=31.5, ref_high=35.7),
    "rdw": bm(13.1, "%", "12.3-15.4", category="cbc", ref_low=12.3, ref_high=15.4),
    "platelets": bm(232, "x10E3/uL", "150-379", category="cbc", ref_low=150, ref_high=379),
    # --- WBC Differential (new in 2024) ---
    "neutrophils_pct": bm(50, "%", "", category="cbc_differential"),
    "lymphocytes_pct": bm(35, "%", "", category="cbc_differential"),
    "monocytes_pct": bm(10, "%", "", category="cbc_differential"),
    "eosinophils_pct": bm(4, "%", "", category="cbc_differential"),
    "basophils_pct": bm(1, "%", "", category="cbc_differential"),
    "immature_cells_pct": bm(0, "%", "", category="cbc_differential"),
    "neutrophils_abs": bm(1.9, "x10E3/uL", "1.4-7.0", category="cbc_differential", ref_low=1.4, ref_high=7.0),
    "lymphocytes_abs": bm(1.3, "x10E3/uL", "0.7-3.1", category="cbc_differential", ref_low=0.7, ref_high=3.1),
    "monocytes_abs": bm(0.4, "x10E3/uL", "0.1-0.9", category="cbc_differential", ref_low=0.1, ref_high=0.9),
    "eosinophils_abs": bm(0.2, "x10E3/uL", "0.0-0.4", category="cbc_differential", ref_low=0, ref_high=0.4),
    "basophils_abs": bm(0.0, "x10E3/uL", "0.0-0.2", category="cbc_differential", ref_low=0, ref_high=0.2),
    "immature_granulocytes_abs": bm(0.0, "x10E3/uL", "0.0-0.01", category="cbc_differential", ref_low=0, ref_high=0.01),
    # --- Thyroid ---
    "tsh": bm(2.54, "uIU/mL", "0.450-4.500", category="thyroid", ref_low=0.45, ref_high=4.5),
    # --- Lipids ---
    "cholesterol_total": bm(206, "mg/dL", "100-199", flag="high", category="lipids", ref_low=100, ref_high=199),
    "triglycerides": bm(96, "mg/dL", "0-149", category="lipids", ref_low=0, ref_high=149),
    "hdl": bm(65, "mg/dL", ">39", category="lipids", ref_low=39),
    "vldl": bm(17, "mg/dL", "5-40", category="lipids", ref_low=5, ref_high=40),
    "ldl_c": bm(124, "mg/dL", "0-99", flag="high", category="lipids", ref_low=0, ref_high=99),
    # --- Metabolic (CMP) ---
    "glucose": bm(93, "mg/dL", "65-99", category="metabolic", ref_low=65, ref_high=99),
    "bun": bm(15, "mg/dL", "6-20", category="kidney", ref_low=6, ref_high=20),
    "creatinine": bm(1.10, "mg/dL", "0.76-1.27", category="kidney", ref_low=0.76, ref_high=1.27),
    "egfr": bm(90, "mL/min/1.73", ">59", category="kidney", ref_low=59),
    "bun_creatinine_ratio": bm(14, "", "9-20", category="kidney", ref_low=9, ref_high=20),
    "sodium": bm(141, "mmol/L", "134-144", category="electrolytes", ref_low=134, ref_high=144),
    "potassium": bm(4.3, "mmol/L", "3.5-5.2", category="electrolytes", ref_low=3.5, ref_high=5.2),
    "chloride": bm(103, "mmol/L", "96-106", category="electrolytes", ref_low=96, ref_high=106),
    "co2": bm(26, "mmol/L", "20-29", category="electrolytes", ref_low=20, ref_high=29),
    "calcium": bm(9.6, "mg/dL", "8.7-10.2", category="minerals", ref_low=8.7, ref_high=10.2),
    "protein_total": bm(6.9, "g/dL", "6.0-8.5", category="metabolic", ref_low=6.0, ref_high=8.5),
    "albumin": bm(4.5, "g/dL", "3.5-5.5", category="metabolic", ref_low=3.5, ref_high=5.5),
    "globulin": bm(2.4, "g/dL", "1.5-4.5", category="metabolic", ref_low=1.5, ref_high=4.5),
    "bilirubin_total": bm(0.8, "mg/dL", "0.0-1.2", category="liver", ref_low=0, ref_high=1.2),
    "alkaline_phosphatase": bm(60, "IU/L", "39-117", category="liver", ref_low=39, ref_high=117),
    "ast": bm(19, "IU/L", "0-40", category="liver", ref_low=0, ref_high=40),
    "alt": bm(27, "IU/L", "0-44", category="liver", ref_low=0, ref_high=44),
    # --- Diabetes ---
    "hba1c": bm(5.1, "%", "4.8-5.6", category="diabetes", ref_low=4.8, ref_high=5.6),
}

draw_2024_item = build_draw_item(
    "2024-06-01", draw_2024,
    provider="one_medical", lab_network="labcorp",
    physician="Soriano, E", fasting=True,
)


# ═══════════════════════════════════════════════
# DEXA SCAN: 2025-05-10  — DexaFit Seattle
# ═══════════════════════════════════════════════

dexa_item = {
    "pk": DEXA_PK,
    "sk": "DATE#2025-05-10",
    "scan_date": "2025-05-10",
    "provider": "dexafit_seattle",
    "provider_address": "111 W. John St. Suite 203A, Seattle WA 98119",
    "scan_type": "dexa",
    "updated_at": NOW,

    # --- Body Composition ---
    "body_composition": {
        "weight_lb": Decimal("190.2"),
        "body_fat_pct": Decimal("15.6"),
        "fat_mass_lb": Decimal("29.8"),
        "lean_mass_lb": Decimal("150.3"),
        "android_fat_pct": Decimal("22.1"),
        "gynoid_fat_pct": Decimal("19.6"),
        "ag_ratio": Decimal("1.13"),
        "visceral_fat_lb": Decimal("0.5"),
        "visceral_fat_g": Decimal("230"),
        "bmd_t_score": Decimal("1.4"),
    },

    # --- Posture Assessment (Kinetisense 3D) ---
    "posture": {
        "method": "kinetisense_3d",
        "capture_1": {
            "frontal": {
                "head_tilt_deg": Decimal("0.3"), "head_tilt_dir": "left",
                "shoulder_tilt_deg": Decimal("0.3"), "shoulder_tilt_dir": "left",
                "spine_tilt_deg": Decimal("0.4"), "spine_tilt_dir": "left",
                "hip_tilt_deg": Decimal("1.91"), "hip_tilt_dir": "right",
                "knee_tilt_deg": Decimal("1.0"), "knee_tilt_dir": "left",
                "ankle_tilt_deg": Decimal("1.1"), "ankle_tilt_dir": "right",
            },
            "sagittal": {
                "head_forward_in": Decimal("0.0"),
                "shoulder_forward_in": Decimal("2.4"),
                "spine_forward_in": Decimal("2.0"),
                "hip_forward_in": Decimal("2.8"),
                "knee_forward_in": Decimal("1.5"),
            },
            "transverse": {
                "shoulder_rotation_deg": Decimal("7.9"), "shoulder_rotation_dir": "left",
                "hip_rotation_deg": Decimal("8.0"), "hip_rotation_dir": "left",
                "knee_rotation_deg": Decimal("5.2"), "knee_rotation_dir": "left",
                "ankle_rotation_deg": Decimal("10.8"), "ankle_rotation_dir": "left",
            },
        },
        "capture_2": {
            "frontal": {
                "head_tilt_deg": Decimal("1.2"), "head_tilt_dir": "left",
                "shoulder_tilt_deg": Decimal("1.8"), "shoulder_tilt_dir": "left",
                "spine_tilt_deg": Decimal("0.4"), "spine_tilt_dir": "left",
                "hip_tilt_deg": Decimal("1.91"), "hip_tilt_dir": "right",
                "knee_tilt_deg": Decimal("0.5"), "knee_tilt_dir": "right",
                "ankle_tilt_deg": Decimal("1.3"), "ankle_tilt_dir": "right",
            },
            "sagittal": {
                "head_forward_in": Decimal("-0.6"),
                "shoulder_forward_in": Decimal("2.2"),
                "spine_forward_in": Decimal("1.7"),
                "hip_forward_in": Decimal("2.6"),
                "knee_forward_in": Decimal("1.4"),
            },
            "transverse": {
                "shoulder_rotation_deg": Decimal("9.9"), "shoulder_rotation_dir": "left",
                "hip_rotation_deg": Decimal("8.0"), "hip_rotation_dir": "left",
                "knee_rotation_deg": Decimal("5.2"), "knee_rotation_dir": "left",
                "ankle_rotation_deg": Decimal("10.9"), "ankle_rotation_dir": "left",
            },
        },
    },

    # --- Interpretations ---
    "interpretations": {
        "strengths": [
            "Leaner than 85% of men same age",
            "Low visceral fat — elite category for heart/liver health and insulin sensitivity",
            "Exceptional lean mass retention post-120lb weight loss",
            "Bone mineral density T-score 1.4 — excellent longevity profile",
        ],
        "areas_for_focus": [
            "Android-to-gynoid fat ratio 1.13 — slightly elevated (target 1.0 or lower)",
            "Mild limb asymmetry (common, manageable)",
            "Consistent left-side rotation from shoulders to ankles — muscular asymmetry",
            "Right hip tilt 1.91 deg — anterior pelvic tilt or glute deactivation",
            "Forward shoulder posture 2.2-2.4in — possible upper-cross syndrome",
        ],
        "goals_6mo": {
            "body_fat_target_pct": "12-13",
            "fat_loss_target_lb": "5-7",
            "ag_ratio_target": "1.0 or lower",
            "lean_mass": "maintain or grow",
        },
        "training_recs": [
            "Strength training 4-5x/week with progressive overload",
            "Focus posterior chain, glutes, core, anti-rotation",
            "Zone 2 cardio 3x/week",
            "1x/week metabolic conditioning",
        ],
        "nutrition_recs": {
            "protein_g_day": "150-180",
            "deficit_kcal": "400-500",
            "strategy": "Moderate-carb, low-sugar, anti-inflammatory",
        },
    },
}


# ═══════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════

ALL_ITEMS = [
    ("labs", "2019-05-01", draw_2019_item),
    ("labs", "2020-10-20", draw_2020_item),
    ("labs", "2021-10-20", draw_2021_item),
    ("labs", "2022-06-01", draw_2022_item),
    ("labs", "2024-06-01", draw_2024_item),
    ("dexa", "2025-05-10", dexa_item),
]


def decimal_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def main():
    write_mode = "--write" in sys.argv

    print("=" * 60)
    print("Life Platform — Physicals + DEXA Seed Script")
    print("=" * 60)
    print(f"Mode: {'WRITE' if write_mode else 'DRY RUN'}")
    print(f"Table: {TABLE_NAME} ({REGION})")
    print(f"Items to write: {len(ALL_ITEMS)}")
    print()

    for source, date, item in ALL_ITEMS:
        n_bio = item.get("total_biomarkers", 0)
        n_oor = item.get("out_of_range_count", 0)
        provider = item.get("lab_provider") or item.get("provider", "")

        if source == "labs":
            print(f"  [{source}] {date}  |  {provider}  |  {n_bio} biomarkers, {n_oor} out of range")
            if n_oor > 0:
                for k in item["out_of_range"]:
                    b = item["biomarkers"][k]
                    print(f"           > {k}: {b['value']} ({b['flag']}, ref {b['ref_text']})")
        elif source == "dexa":
            bc = item["body_composition"]
            print(f"  [{source}] {date}  |  {provider}")
            print(f"           Weight: {bc['weight_lb']} lb  |  BF: {bc['body_fat_pct']}%  |  Lean: {bc['lean_mass_lb']} lb")
            print(f"           BMD T-score: {bc['bmd_t_score']}  |  VAT: {bc['visceral_fat_g']}g  |  A/G: {bc['ag_ratio']}")

        import json as _j
        raw = _j.dumps(item, default=decimal_default)
        size_kb = len(raw.encode("utf-8")) / 1024
        print(f"           Item size: {size_kb:.1f} KB")
        print()

    if not write_mode:
        print("DRY RUN — no data written. Run with --write to seed DynamoDB.")
        return

    ddb = boto3.resource("dynamodb", region_name=REGION)
    table = ddb.Table(TABLE_NAME)

    for source, date, item in ALL_ITEMS:
        print(f"  Writing {source}/{date}... ", end="", flush=True)
        table.put_item(Item=item)
        print("done")

    print()
    print(f"Done! {len(ALL_ITEMS)} items written to {TABLE_NAME}.")
    print()
    print("Verification:")
    print(f'  aws dynamodb query --table-name {TABLE_NAME} --key-condition-expression "pk = :pk" \\')
    print(f'    --expression-attribute-values \'{{"pk": {{"S": "{LABS_PK}"}}}}\' \\')
    print(f'    --select COUNT --region {REGION}')
    print()
    print(f'  aws dynamodb get-item --table-name {TABLE_NAME} \\')
    print(f'    --key \'{{"pk": {{"S": "{DEXA_PK}"}}, "sk": {{"S": "DATE#2025-05-10"}}}}\' \\')
    print(f'    --projection-expression "scan_date, body_composition.body_fat_pct" \\')
    print(f'    --region {REGION}')


if __name__ == "__main__":
    main()
