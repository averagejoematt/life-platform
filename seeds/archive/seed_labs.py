#!/usr/bin/env python3
"""
seed_labs.py — Seed Function Health lab results into Life Platform DynamoDB.

Loads parsed biomarker data from 2 blood draws (2025-04-08, 2025-04-17) into
the `labs` source partition. Each draw date becomes one DynamoDB item.

Schema design:
  PK: USER#matthew#SOURCE#labs
  SK: DATE#YYYY-MM-DD

Each item contains:
  - draw_date: YYYY-MM-DD
  - lab_provider: "function_health"
  - lab_network: "quest_diagnostics"
  - specimen_id: Quest accession number
  - collection_date: YYYY-MM-DD
  - report_date: YYYY-MM-DD
  - biomarkers: dict of normalized biomarker objects
  - out_of_range: list of biomarker keys that are flagged
  - out_of_range_count: int
  - total_biomarkers: int
  - metadata: dict with patient info, clinician notes summary, biological age
  - updated_at: ISO timestamp

Each biomarker object:
  {
    "value": <number or string for qualitative>,
    "value_numeric": <float or None if qualitative>,
    "unit": "mg/dL",
    "ref_low": <float or None>,
    "ref_high": <float or None>,
    "ref_text": "<14" or "0.3-13.4" (original reference text),
    "flag": "normal" | "high" | "low" | "carrier" | "noncarrier",
    "category": "lipids" | "metabolic" | "thyroid" | ... ,
    "fh_category": "In Range" | "Out of Range" | "Other"
  }

Usage:
  pip install boto3
  python3 seed_labs.py
"""

import boto3
import json
from datetime import datetime, timezone
from decimal import Decimal

TABLE_NAME = "life-platform"
REGION = "us-west-2"
USER = "matthew"
SOURCE = "labs"
PK = f"USER#{USER}#SOURCE#{SOURCE}"

# ─────────────────────────────────────────────
# Helper to build biomarker entries
# ─────────────────────────────────────────────

def bm(value, unit, ref_text, flag="normal", category="uncategorized",
       fh_category="In Range", value_numeric=None, ref_low=None, ref_high=None):
    """Build a biomarker dict."""
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
        "fh_category": fh_category,
    }

    if value_numeric is not None:
        entry["value_numeric"] = Decimal(str(value_numeric))
    if ref_low is not None:
        entry["ref_low"] = Decimal(str(ref_low))
    if ref_high is not None:
        entry["ref_high"] = Decimal(str(ref_high))

    return entry


# ═══════════════════════════════════════════════
# DRAW 1: 2025-04-08  (specimen OZ554791E)
# Reported: 2025-04-28
# 33 biomarkers, 4 out of range
# ═══════════════════════════════════════════════

draw_1_biomarkers = {
    # --- Liver / Digestive ---
    "ggt": bm(13, "U/L", "3-90", category="liver", ref_low=3, ref_high=90),
    "amylase": bm(18, "U/L", "21-101", flag="low", category="digestive",
                  fh_category="Out of Range", ref_low=21, ref_high=101),
    "lipase": bm(12, "U/L", "7-60", category="digestive", ref_low=7, ref_high=60),

    # --- Metabolic ---
    "leptin": bm(0.4, "ng/mL", "0.3-13.4", category="metabolic", ref_low=0.3, ref_high=13.4),
    "methylmalonic_acid": bm(76, "nmol/L", "55-335", category="metabolic", ref_low=55, ref_high=335),

    # --- Immune ---
    "rheumatoid_factor": bm("<10", "IU/mL", "<14", category="immune", ref_high=14),
    "ana_screen": bm("NEGATIVE", "", "NEGATIVE", category="immune", fh_category="Other"),

    # --- Thyroid ---
    "thyroglobulin_antibodies": bm(2, "IU/mL", "≤1", flag="high", category="thyroid",
                                    fh_category="Out of Range", ref_high=1),
    "thyroid_peroxidase_antibodies": bm(1, "IU/mL", "<9", category="thyroid", ref_high=9),

    # --- Cardiovascular ---
    "homocysteine": bm(9.5, "umol/L", "<11.4", category="cardiovascular", ref_high=11.4),

    # --- Hormones ---
    "fsh": bm(2.8, "mIU/mL", "1.4-12.8", category="hormones", ref_low=1.4, ref_high=12.8),
    "lh": bm(1.8, "mIU/mL", "1.5-9.3", category="hormones", ref_low=1.5, ref_high=9.3),
    "prolactin": bm(3.4, "ng/mL", "2.0-18.0", category="hormones", ref_low=2.0, ref_high=18.0),
    "estradiol": bm(16, "pg/mL", "≤39", category="hormones", ref_high=39),
    "shbg": bm(59, "nmol/L", "10-50", flag="high", category="hormones",
               fh_category="Out of Range", ref_low=10, ref_high=50),
    "dhea_sulfate": bm(223, "mcg/dL", "93-415", category="hormones", ref_low=93, ref_high=415),
    "testosterone_total": bm(577, "ng/dL", "250-1100", category="hormones", ref_low=250, ref_high=1100),
    "testosterone_free": bm(63.5, "pg/mL", "35.0-155.0", category="hormones", ref_low=35.0, ref_high=155.0),

    # --- Prostate ---
    "psa_total": bm(0.7, "ng/mL", "≤4.0", category="prostate", ref_high=4.0),
    "psa_free": bm(0.2, "ng/mL", "", category="prostate"),
    "psa_pct_free": bm(29, "%", ">25", category="prostate", ref_low=25),

    # --- Toxicology ---
    "lead_venous": bm("<1.0", "mcg/dL", "<3.5", category="toxicology", ref_high=3.5),

    # --- Minerals ---
    "zinc": bm(100, "mcg/dL", "60-130", category="minerals", ref_low=60, ref_high=130),

    # --- Omega Fatty Acids ---
    "omegacheck": bm(7.8, "% by wt", ">5.4", category="omega_fatty_acids", ref_low=5.4),
    "arachidonic_acid_epa_ratio": bm(8.1, "", "3.7-40.7", category="omega_fatty_acids",
                                      ref_low=3.7, ref_high=40.7),
    "omega6_omega3_ratio": bm(5.2, "", "3.7-14.4", category="omega_fatty_acids",
                               ref_low=3.7, ref_high=14.4),
    "omega3_total": bm(7.8, "% by wt", "", category="omega_fatty_acids"),
    "epa": bm(1.7, "% by wt", "0.2-2.3", category="omega_fatty_acids", ref_low=0.2, ref_high=2.3),
    "dpa": bm(2.1, "% by wt", "0.8-1.8", flag="high", category="omega_fatty_acids",
              fh_category="Out of Range", ref_low=0.8, ref_high=1.8),
    "dha": bm(3.9, "% by wt", "1.4-5.1", category="omega_fatty_acids", ref_low=1.4, ref_high=5.1),
    "omega6_total": bm(40.2, "% by wt", "", category="omega_fatty_acids"),
    "arachidonic_acid": bm(13.8, "% by wt", "8.6-15.6", category="omega_fatty_acids",
                            ref_low=8.6, ref_high=15.6),
    "linoleic_acid": bm(23.3, "% by wt", "18.6-29.5", category="omega_fatty_acids",
                         ref_low=18.6, ref_high=29.5),
}

draw_1_out_of_range = ["thyroglobulin_antibodies", "shbg", "amylase", "dpa"]

draw_1_item = {
    "pk": PK,
    "sk": "DATE#2025-04-08",
    "draw_date": "2025-04-08",
    "lab_provider": "function_health",
    "lab_network": "quest_diagnostics",
    "specimen_id": "OZ554791E",
    "collection_date": "2025-04-08",
    "report_date": "2025-04-28",
    "biomarkers": draw_1_biomarkers,
    "out_of_range": draw_1_out_of_range,
    "out_of_range_count": len(draw_1_out_of_range),
    "total_biomarkers": len(draw_1_biomarkers),
    "metadata": {
        "patient_name": "Matthew Walker",
        "patient_dob": "1989-02-07",
        "patient_sex": "Male",
        "patient_age_at_draw": 36,
        "ordering_physician": "Terri DeNeui, DNP",
        "fh_test_round": "Spring 2025 - Draw 1 of 2",
    },
    "updated_at": datetime.now(timezone.utc).isoformat(),
}


# ═══════════════════════════════════════════════
# DRAW 2: 2025-04-17  (specimen OZ587466E)
# Reported: 2025-05-10
# 74 biomarkers, 9 out of range
# ═══════════════════════════════════════════════

draw_2_biomarkers = {
    # --- Iron Panel ---
    "iron_total": bm(71, "mcg/dL", "50-180", category="iron", ref_low=50, ref_high=180),
    "tibc": bm(310, "mcg/dL", "250-425", category="iron", ref_low=250, ref_high=425),
    "iron_saturation": bm(23, "%", "20-48", category="iron", ref_low=20, ref_high=48),
    "ferritin": bm(272, "ng/mL", "38-380", category="iron", ref_low=38, ref_high=380),

    # --- Metabolic Panel ---
    "uric_acid": bm(4.8, "mg/dL", "4.0-8.0", category="metabolic", ref_low=4.0, ref_high=8.0),
    "glucose": bm(86, "mg/dL", "65-99", category="metabolic", ref_low=65, ref_high=99),
    "bun": bm(18, "mg/dL", "7-25", category="metabolic", ref_low=7, ref_high=25),
    "creatinine": bm(0.91, "mg/dL", "0.60-1.26", category="metabolic", ref_low=0.60, ref_high=1.26),
    "egfr": bm(112, "mL/min/1.73m2", "≥60", category="kidney", ref_low=60),
    "hba1c": bm(4.9, "%", "<5.7", category="metabolic", ref_high=5.7),
    "insulin": bm(2.5, "uIU/mL", "≤18.4", category="metabolic", ref_high=18.4),

    # --- Electrolytes ---
    "sodium": bm(140, "mmol/L", "135-146", category="electrolytes", ref_low=135, ref_high=146),
    "potassium": bm(4.7, "mmol/L", "3.5-5.3", category="electrolytes", ref_low=3.5, ref_high=5.3),
    "chloride": bm(105, "mmol/L", "98-110", category="electrolytes", ref_low=98, ref_high=110),
    "co2": bm(24, "mmol/L", "20-32", category="electrolytes", ref_low=20, ref_high=32),
    "calcium": bm(9.4, "mg/dL", "8.6-10.3", category="electrolytes", ref_low=8.6, ref_high=10.3),

    # --- Liver Panel ---
    "protein_total": bm(7.0, "g/dL", "6.1-8.1", category="liver", ref_low=6.1, ref_high=8.1),
    "albumin": bm(4.5, "g/dL", "3.6-5.1", category="liver", ref_low=3.6, ref_high=5.1),
    "globulin": bm(2.5, "g/dL", "1.9-3.7", category="liver", ref_low=1.9, ref_high=3.7),
    "ag_ratio": bm(1.8, "", "1.0-2.5", category="liver", ref_low=1.0, ref_high=2.5),
    "bilirubin_total": bm(0.7, "mg/dL", "0.2-1.2", category="liver", ref_low=0.2, ref_high=1.2),
    "alkaline_phosphatase": bm(55, "U/L", "36-130", category="liver", ref_low=36, ref_high=130),
    "ast": bm(30, "U/L", "10-40", category="liver", ref_low=10, ref_high=40),
    "alt": bm(31, "U/L", "9-46", category="liver", ref_low=9, ref_high=46),

    # --- Cardiovascular / Lipids ---
    "lpa": bm("<10", "nmol/L", "<75", category="cardiovascular", ref_high=75),
    "apob": bm(107, "mg/dL", "<90", flag="high", category="lipids",
               fh_category="Out of Range", ref_high=90),
    "cholesterol_total": bm(219, "mg/dL", "<200", flag="high", category="lipids",
                             fh_category="Out of Range", ref_high=200),
    "hdl": bm(72, "mg/dL", ">39", category="lipids", ref_low=39),
    "triglycerides": bm(46, "mg/dL", "<150", category="lipids", ref_high=150),
    "ldl_c": bm(133, "mg/dL", "<100", flag="high", category="lipids",
                fh_category="Out of Range", ref_high=100),
    "chol_hdl_ratio": bm(3.0, "", "<5.0", category="lipids", ref_high=5.0),
    "non_hdl_c": bm(147, "mg/dL", "<130", flag="high", category="lipids",
                     fh_category="Out of Range", ref_high=130),

    # --- Advanced Lipid Panel (NMR) ---
    "ldl_particle_number": bm(1787, "nmol/L", "<1138", flag="high", category="lipids_advanced",
                               fh_category="Out of Range", ref_high=1138),
    "ldl_small": bm(274, "nmol/L", "<142", flag="high", category="lipids_advanced",
                     fh_category="Out of Range", ref_high=142),
    "ldl_medium": bm(307, "nmol/L", "<215", flag="high", category="lipids_advanced",
                      fh_category="Out of Range", ref_high=215),
    "hdl_large": bm(6969, "nmol/L", ">6729", category="lipids_advanced", ref_low=6729),
    "ldl_pattern": bm("A", "", "Pattern A", category="lipids_advanced", fh_category="Other"),
    "ldl_peak_size": bm(223.1, "Angstrom", ">222.9", category="lipids_advanced", ref_low=222.9),

    # --- Inflammation ---
    "hs_crp": bm("<0.2", "mg/L", "<1.0", category="inflammation", ref_high=1.0),

    # --- Hormones ---
    "cortisol_total": bm(9.1, "mcg/dL", "4.6-20.6", category="hormones", ref_low=4.6, ref_high=20.6),

    # --- Thyroid ---
    "t4_free": bm(1.3, "ng/dL", "0.8-1.8", category="thyroid", ref_low=0.8, ref_high=1.8),
    "tsh": bm(1.52, "mIU/L", "0.40-4.50", category="thyroid", ref_low=0.40, ref_high=4.50),
    "t3_free": bm(2.5, "pg/mL", "2.3-4.2", category="thyroid", ref_low=2.3, ref_high=4.2),

    # --- Vitamins ---
    "vitamin_d_25oh": bm(117, "ng/mL", "30-100", flag="high", category="vitamins",
                          fh_category="Out of Range", ref_low=30, ref_high=100),

    # --- Minerals ---
    "magnesium_rbc": bm(5.6, "mg/dL", "4.0-6.4", category="minerals", ref_low=4.0, ref_high=6.4),

    # --- Kidney ---
    "albumin_urine": bm("<0.2", "mg/dL", "", category="kidney", fh_category="Other"),

    # --- Complete Blood Count ---
    "wbc": bm(3.4, "K/uL", "3.8-10.8", flag="low", category="cbc",
              fh_category="Out of Range", ref_low=3.8, ref_high=10.8),
    "rbc": bm(4.41, "M/uL", "4.20-5.80", category="cbc", ref_low=4.20, ref_high=5.80),
    "hemoglobin": bm(13.8, "g/dL", "13.2-17.1", category="cbc", ref_low=13.2, ref_high=17.1),
    "hematocrit": bm(41.4, "%", "38.5-50.0", category="cbc", ref_low=38.5, ref_high=50.0),
    "mcv": bm(93.9, "fL", "80.0-100.0", category="cbc", ref_low=80.0, ref_high=100.0),
    "mch": bm(31.3, "pg", "27.0-33.0", category="cbc", ref_low=27.0, ref_high=33.0),
    "mchc": bm(33.3, "g/dL", "32.0-36.0", category="cbc", ref_low=32.0, ref_high=36.0),
    "rdw": bm(12.6, "%", "11.0-15.0", category="cbc", ref_low=11.0, ref_high=15.0),
    "platelets": bm(209, "K/uL", "140-400", category="cbc", ref_low=140, ref_high=400),
    "mpv": bm(10.9, "fL", "7.5-12.5", category="cbc", ref_low=7.5, ref_high=12.5),

    # --- WBC Differential (absolute) ---
    "abs_neutrophils": bm(1989, "cells/uL", "1500-7800", category="cbc_differential",
                           ref_low=1500, ref_high=7800),
    "abs_lymphocytes": bm(1112, "cells/uL", "850-3900", category="cbc_differential",
                           ref_low=850, ref_high=3900),
    "abs_monocytes": bm(228, "cells/uL", "200-950", category="cbc_differential",
                         ref_low=200, ref_high=950),
    "abs_eosinophils": bm(41, "cells/uL", "15-500", category="cbc_differential",
                           ref_low=15, ref_high=500),
    "abs_basophils": bm(31, "cells/uL", "0-200", category="cbc_differential",
                         ref_low=0, ref_high=200),

    # --- WBC Differential (percentage) ---
    "neutrophils_pct": bm(58.5, "%", "", category="cbc_differential", fh_category="Other"),
    "lymphocytes_pct": bm(32.7, "%", "", category="cbc_differential", fh_category="Other"),
    "monocytes_pct": bm(6.7, "%", "", category="cbc_differential", fh_category="Other"),
    "eosinophils_pct": bm(1.2, "%", "", category="cbc_differential", fh_category="Other"),
    "basophils_pct": bm(0.9, "%", "", category="cbc_differential", fh_category="Other"),

    # --- Toxicology ---
    "mercury_blood": bm("<5", "mcg/L", "<11", category="toxicology", ref_high=11),

    # --- Blood Type ---
    "abo_group": bm("A", "", "", category="blood_type", fh_category="Other"),
    "rh_type": bm("Positive", "", "", category="blood_type", fh_category="Other"),

    # --- Genetics ---
    "lpa_aspirin_genotype": bm("Ile/Ile", "", "", flag="noncarrier", category="genetics",
                                fh_category="Other"),
    "9p21_rs10757278": bm("aa", "", "", flag="noncarrier", category="genetics",
                           fh_category="Other"),
    "9p21_rs1333049": bm("gg", "", "", flag="noncarrier", category="genetics",
                          fh_category="Other"),
    "4q25_rs2200733": bm("cc", "", "", flag="noncarrier", category="genetics",
                          fh_category="Other"),
    "4q25_rs10033464": bm("gt", "", "", flag="carrier", category="genetics",
                           fh_category="Other"),
}

# --- Urinalysis (stored as nested object, same date) ---
draw_2_urinalysis = {
    "color": "Yellow",
    "appearance": "Clear",
    "specific_gravity": Decimal("1.027"),
    "ph": Decimal("6.0"),
    "glucose_urine": "Negative",
    "bilirubin_urine": "Negative",
    "ketones_urine": "Negative",
    "occult_blood": "Negative",
    "protein_urine": "Negative",
    "nitrite": "Negative",
    "leukocyte_esterase": "Negative",
    "bacteria": "None Seen",
    "wbc_urine": "0-2",
    "rbc_urine": "0-2",
    "epithelial_cells": "None Seen",
    "hyaline_casts": "None Seen",
}

draw_2_out_of_range = [
    "wbc", "vitamin_d_25oh", "apob", "ldl_particle_number",
    "ldl_small", "ldl_medium", "cholesterol_total", "ldl_c", "non_hdl_c"
]

draw_2_item = {
    "pk": PK,
    "sk": "DATE#2025-04-17",
    "draw_date": "2025-04-17",
    "lab_provider": "function_health",
    "lab_network": "quest_diagnostics",
    "specimen_id": "OZ587466E",
    "collection_date": "2025-04-17",
    "report_date": "2025-05-10",
    "biomarkers": draw_2_biomarkers,
    "out_of_range": draw_2_out_of_range,
    "out_of_range_count": len(draw_2_out_of_range),
    "total_biomarkers": len(draw_2_biomarkers),
    "urinalysis": draw_2_urinalysis,
    "metadata": {
        "patient_name": "Matthew Walker",
        "patient_dob": "1989-02-07",
        "patient_sex": "Male",
        "patient_age_at_draw": 36,
        "ordering_physician": "Terri DeNeui, DNP",
        "fh_test_round": "Spring 2025 - Draw 2 of 2",
        "biological_age_delta_years": Decimal("-9.6"),
        "fh_biological_age_note": "9.6 years younger than chronological age",
    },
    "clinician_summary": {
        "cardiovascular": "ApoB and LDL particles elevated. Consider dietary modifications, increase soluble fiber, reduce saturated fat. Retest in 3-6 months.",
        "thyroid": "Thyroglobulin antibodies mildly elevated (2 vs ≤1). TPO normal. Monitor — could indicate early autoimmune thyroid process. Thyroid function (TSH, T3, T4) all normal.",
        "immune": "WBC mildly low (3.4 vs 3.8). Can be normal variant, especially in lean/athletic individuals. No signs of infection or immune deficiency.",
        "vitamins": "Vitamin D elevated at 117 (goal 30-100). Consider reducing supplementation dose.",
        "hormones": "SHBG elevated (59 vs 10-50). Can reduce bioavailable testosterone. Often seen with low body fat or liver health optimization. Free T is normal so clinically insignificant currently.",
        "digestive": "Amylase mildly low (18 vs 21-101). Usually benign. No pancreatic concern with normal lipase.",
        "omega_fatty_acids": "OmegaCheck excellent at 7.8%. DPA slightly high — likely from fish oil supplementation. Omega-6/3 ratio excellent at 5.2.",
        "overall": "Excellent baseline. Primary action items: lipid optimization (ApoB/LDL-P) and vitamin D dose reduction. All other systems performing well.",
    },
    "updated_at": datetime.now(timezone.utc).isoformat(),
}


# ═══════════════════════════════════════════════
# Function Health metadata item (singleton)
# ═══════════════════════════════════════════════

fh_metadata_item = {
    "pk": PK,
    "sk": "PROVIDER#function_health#2025-spring",
    "provider": "function_health",
    "test_period": "Spring 2025",
    "total_biomarkers_tested": 119,
    "in_range_count": 86,
    "out_of_range_count": 14,
    "other_count": 19,
    "biological_age_delta_years": Decimal("-9.6"),
    "draw_dates": ["2025-04-08", "2025-04-17"],
    "food_recommendations": {
        "enjoy": [
            "Salmon", "Sardines", "Mackerel", "Walnuts", "Flaxseeds",
            "Chia seeds", "Oats", "Barley", "Lentils", "Beans",
            "Avocado", "Olive oil", "Almonds", "Berries", "Leafy greens",
            "Sweet potatoes", "Broccoli", "Brussels sprouts", "Garlic",
            "Turmeric", "Green tea", "Dark chocolate (70%+)"
        ],
        "avoid_or_limit": [
            "Processed meats", "Fried foods", "Refined carbohydrates",
            "Sugary beverages", "Excessive red meat", "Trans fats",
            "High-sodium processed foods", "Excessive alcohol"
        ],
        "focus_areas": {
            "soluble_fiber": "Increase to help lower LDL/ApoB — oats, barley, beans, lentils, psyllium husk",
            "omega3": "Maintain current intake — OmegaCheck 7.8% is excellent",
            "saturated_fat": "Moderate intake to help lipid profile",
        }
    },
    "supplement_recommendations": {
        "reduce": ["Vitamin D — currently 117 ng/mL, reduce dose or frequency"],
        "maintain": ["Fish oil / Omega-3 — excellent levels", "Magnesium — RBC level 5.6 is solid"],
        "consider": ["Plant sterols — may help with LDL reduction", "Psyllium husk — soluble fiber for ApoB"],
    },
    "updated_at": datetime.now(timezone.utc).isoformat(),
}


# ═══════════════════════════════════════════════
# Write to DynamoDB
# ═══════════════════════════════════════════════

def write_items():
    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    table = dynamodb.Table(TABLE_NAME)

    items = [
        ("Draw 1 (2025-04-08)", draw_1_item),
        ("Draw 2 (2025-04-17)", draw_2_item),
        ("FH metadata (Spring 2025)", fh_metadata_item),
    ]

    for label, item in items:
        print(f"Writing: {label} ...")
        print(f"  PK: {item['pk']}")
        print(f"  SK: {item['sk']}")
        if "biomarkers" in item:
            print(f"  Biomarkers: {len(item['biomarkers'])}")
            print(f"  Out of range: {item.get('out_of_range_count', 'N/A')}")
        table.put_item(Item=item)
        print(f"  ✓ Written successfully")

    print(f"\n{'='*50}")
    print(f"Labs seed complete!")
    print(f"  Draw 1: {len(draw_1_biomarkers)} biomarkers ({len(draw_1_out_of_range)} out of range)")
    print(f"  Draw 2: {len(draw_2_biomarkers)} biomarkers ({len(draw_2_out_of_range)} out of range)")
    print(f"  Total unique biomarkers: {len(set(list(draw_1_biomarkers.keys()) + list(draw_2_biomarkers.keys())))}")
    print(f"  Provider metadata: Function Health Spring 2025")
    print(f"  DynamoDB items written: {len(items)}")


if __name__ == "__main__":
    write_items()
