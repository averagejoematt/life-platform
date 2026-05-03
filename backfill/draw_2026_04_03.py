"""
draw_2026_04_03.py — Structured biomarker data for Function Health draw on 2026-04-03.

Hand-extracted from the source PDFs by careful reading. Mirrors the existing schema
in DDB (USER#matthew#SOURCE#labs / DATE#YYYY-MM-DD).

Panel sources:
  - Standard panel:  Lab Results of Record.pdf  (35 pages, reported 04/18/2026)
  - NfL panel:       Lab Results of Record (4).pdf  (27 pages, reported 04/11/2026)
  - Galleri panel:   Lab Results of Record (3).pdf  (11 pages, corrected 04/24/2026)

Key reference values (validated against Supplement_Protocol_2026-05_v2.md):
  - INSULIN: 14.3 uIU/mL (was 2.5)
  - TESTOSTERONE TOTAL: 361 ng/dL (was 577)
  - OMEGA-3 INDEX (EPA+DPA+DHA): 3.3% (was 7.8%)
  - APOLIPOPROTEIN B: 116 mg/dL (was 107)
  - GGT: 31 U/L (was 22 in narrative — the protocol's "22 → 31" predates 2025 GGT lab; 13.0 is what's in PDF for 2025)
"""

DRAW_DATE = "2026-04-03"
COLLECTION_TIMESTAMP_UTC = "2026-04-03T18:00:00Z"  # 11:00 AM PDT
PROVIDER = "function_health"
LAB_NETWORK = "quest_diagnostics"
PHYSICIAN = "Joshua A Emdur, DO"
FASTING = True
ACCESSION = "OZ793118F"

# Each biomarker:
#   value:          raw value as printed (string for "<0.10" or "NEGATIVE")
#   value_numeric:  parsed numeric (None for strings)
#   unit:           units string
#   ref_text:       reference range as printed
#   flag:           "high" | "low" | "normal"
#   category:       grouping for queries
#   panel:          which panel this came from
#   previous_value: from inline historical column when present (None otherwise)
#   previous_date:  YYYY-MM-DD of the previous value
BIOMARKERS = {

    # ──────── IRON, TIBC, FERRITIN PANEL ────────
    "iron_total": {
        "value": 179, "value_numeric": 179, "unit": "mcg/dL", "ref_text": "50-180",
        "flag": "normal", "category": "iron_metabolism", "panel": "iron_tibc_ferritin",
        "previous_value": 71.0, "previous_date": "2025-04-17",
    },
    "iron_binding_capacity": {
        "value": 413, "value_numeric": 413, "unit": "mcg/dL", "ref_text": "250-425 (calc)",
        "flag": "normal", "category": "iron_metabolism", "panel": "iron_tibc_ferritin",
        "previous_value": 310.0, "previous_date": "2025-04-17",
    },
    "iron_saturation_pct": {
        "value": 43, "value_numeric": 43, "unit": "%", "ref_text": "20-48 (calc)",
        "flag": "normal", "category": "iron_metabolism", "panel": "iron_tibc_ferritin",
        "previous_value": 23.0, "previous_date": "2025-04-17",
    },
    "ferritin": {
        "value": 279, "value_numeric": 279, "unit": "ng/mL", "ref_text": "38-380",
        "flag": "normal", "category": "iron_metabolism", "panel": "iron_tibc_ferritin",
        "previous_value": 272.0, "previous_date": "2025-04-17",
    },

    # ──────── LIPID PANEL, STANDARD ────────
    "cholesterol_total": {
        "value": 243, "value_numeric": 243, "unit": "mg/dL", "ref_text": "<200",
        "flag": "high", "category": "lipids", "panel": "lipid_standard",
        "previous_value": None, "previous_date": None,
    },
    "hdl": {
        "value": 58, "value_numeric": 58, "unit": "mg/dL", "ref_text": ">= 40",
        "flag": "normal", "category": "lipids", "panel": "lipid_standard",
        "previous_value": None, "previous_date": None,
    },
    "triglycerides": {
        "value": 105, "value_numeric": 105, "unit": "mg/dL", "ref_text": "<150",
        "flag": "normal", "category": "lipids", "panel": "lipid_standard",
        "previous_value": None, "previous_date": None,
    },
    "ldl_c": {
        "value": 163, "value_numeric": 163, "unit": "mg/dL", "ref_text": "<100 (calc, Martin-Hopkins)",
        "flag": "high", "category": "lipids", "panel": "lipid_standard",
        "previous_value": None, "previous_date": None,
    },
    "chol_hdl_ratio": {
        "value": 4.2, "value_numeric": 4.2, "unit": "ratio", "ref_text": "<5.0 (calc)",
        "flag": "normal", "category": "lipids", "panel": "lipid_standard",
        "previous_value": None, "previous_date": None,
    },
    "non_hdl_c": {
        "value": 185, "value_numeric": 185, "unit": "mg/dL", "ref_text": "<130 (calc)",
        "flag": "high", "category": "lipids", "panel": "lipid_standard",
        "previous_value": None, "previous_date": None,
    },

    # ──────── GGT ────────
    "ggt": {
        "value": 31, "value_numeric": 31, "unit": "U/L", "ref_text": "3-90",
        "flag": "normal", "category": "liver", "panel": "ggt",
        "previous_value": 13.0, "previous_date": "2025-04-08",
    },

    # ──────── URIC ACID ────────
    "uric_acid": {
        "value": 6.8, "value_numeric": 6.8, "unit": "mg/dL", "ref_text": "4.0-8.0",
        "flag": "normal", "category": "metabolic", "panel": "uric_acid",
        "previous_value": 4.8, "previous_date": "2025-04-17",
    },

    # ──────── COMPREHENSIVE METABOLIC PANEL ────────
    "glucose": {
        "value": 91, "value_numeric": 91, "unit": "mg/dL", "ref_text": "65-99 (fasting)",
        "flag": "normal", "category": "metabolic", "panel": "cmp",
        "previous_value": 86.0, "previous_date": "2025-04-17",
    },
    "bun": {
        "value": 15, "value_numeric": 15, "unit": "mg/dL", "ref_text": "7-25",
        "flag": "normal", "category": "kidney", "panel": "cmp",
        "previous_value": 18.0, "previous_date": "2025-04-17",
    },
    "creatinine": {
        "value": 1.03, "value_numeric": 1.03, "unit": "mg/dL", "ref_text": "0.60-1.26",
        "flag": "normal", "category": "kidney", "panel": "cmp",
        "previous_value": 0.91, "previous_date": "2025-04-17",
    },
    "egfr": {
        "value": 96, "value_numeric": 96, "unit": "mL/min/1.73m2", "ref_text": ">= 60",
        "flag": "normal", "category": "kidney", "panel": "cmp",
        "previous_value": 112.0, "previous_date": "2025-04-17",
    },
    "sodium": {
        "value": 138, "value_numeric": 138, "unit": "mmol/L", "ref_text": "135-146",
        "flag": "normal", "category": "electrolytes", "panel": "cmp",
        "previous_value": 140.0, "previous_date": "2025-04-17",
    },
    "potassium": {
        "value": 4.3, "value_numeric": 4.3, "unit": "mmol/L", "ref_text": "3.5-5.3",
        "flag": "normal", "category": "electrolytes", "panel": "cmp",
        "previous_value": 4.7, "previous_date": "2025-04-17",
    },
    "chloride": {
        "value": 102, "value_numeric": 102, "unit": "mmol/L", "ref_text": "98-110",
        "flag": "normal", "category": "electrolytes", "panel": "cmp",
        "previous_value": 105.0, "previous_date": "2025-04-17",
    },
    "carbon_dioxide": {
        "value": 26, "value_numeric": 26, "unit": "mmol/L", "ref_text": "20-32",
        "flag": "normal", "category": "electrolytes", "panel": "cmp",
        "previous_value": 24.0, "previous_date": "2025-04-17",
    },
    "calcium": {
        "value": 9.8, "value_numeric": 9.8, "unit": "mg/dL", "ref_text": "8.6-10.3",
        "flag": "normal", "category": "minerals", "panel": "cmp",
        "previous_value": 9.4, "previous_date": "2025-04-17",
    },
    "protein_total": {
        "value": 7.6, "value_numeric": 7.6, "unit": "g/dL", "ref_text": "6.1-8.1",
        "flag": "normal", "category": "metabolic", "panel": "cmp",
        "previous_value": 7.0, "previous_date": "2025-04-17",
    },
    "albumin": {
        "value": 4.9, "value_numeric": 4.9, "unit": "g/dL", "ref_text": "3.6-5.1",
        "flag": "normal", "category": "metabolic", "panel": "cmp",
        "previous_value": 4.5, "previous_date": "2025-04-17",
    },
    "globulin": {
        "value": 2.7, "value_numeric": 2.7, "unit": "g/dL", "ref_text": "1.9-3.7 (calc)",
        "flag": "normal", "category": "metabolic", "panel": "cmp",
        "previous_value": 2.5, "previous_date": "2025-04-17",
    },
    "albumin_globulin_ratio": {
        "value": 1.8, "value_numeric": 1.8, "unit": "ratio", "ref_text": "1.0-2.5 (calc)",
        "flag": "normal", "category": "metabolic", "panel": "cmp",
        "previous_value": 1.8, "previous_date": "2025-04-17",
    },
    "bilirubin_total": {
        "value": 0.9, "value_numeric": 0.9, "unit": "mg/dL", "ref_text": "0.2-1.2",
        "flag": "normal", "category": "liver", "panel": "cmp",
        "previous_value": 0.7, "previous_date": "2025-04-17",
    },
    "alkaline_phosphatase": {
        "value": 64, "value_numeric": 64, "unit": "U/L", "ref_text": "36-130",
        "flag": "normal", "category": "liver", "panel": "cmp",
        "previous_value": 55.0, "previous_date": "2025-04-17",
    },
    "ast": {
        "value": 24, "value_numeric": 24, "unit": "U/L", "ref_text": "10-40",
        "flag": "normal", "category": "liver", "panel": "cmp",
        "previous_value": 30.0, "previous_date": "2025-04-17",
    },
    "alt": {
        "value": 35, "value_numeric": 35, "unit": "U/L", "ref_text": "9-46",
        "flag": "normal", "category": "liver", "panel": "cmp",
        "previous_value": 31.0, "previous_date": "2025-04-17",
    },

    # ──────── LIPOPROTEIN(a) ────────
    "lipoprotein_a": {
        "value": 16, "value_numeric": 16, "unit": "nmol/L", "ref_text": "<75 (optimal)",
        "flag": "normal", "category": "lipids", "panel": "lipoprotein_a",
        "previous_value": None, "previous_date": None,
    },

    # ──────── ALBUMIN, RANDOM URINE (microalbuminuria) ────────
    "albumin_urine": {
        "value": "<0.2", "value_numeric": None, "unit": "mg/dL", "ref_text": "Not established",
        "flag": "normal", "category": "kidney", "panel": "albumin_urine",
        "previous_value": None, "previous_date": None,
    },

    # ──────── MAGNESIUM, RBC ────────
    "magnesium_rbc": {
        "value": 5.9, "value_numeric": 5.9, "unit": "mg/dL", "ref_text": "4.0-6.4",
        "flag": "normal", "category": "minerals", "panel": "magnesium_rbc",
        "previous_value": 5.6, "previous_date": "2025-04-17",
    },

    # ──────── OMEGACHECK (Comprehensive Fatty Acid Panel) ────────
    # KEY VALUE: omega_3_index = 3.3 (was 7.8) — referenced in supplement protocol
    "omega_3_index": {
        "value": 3.3, "value_numeric": 3.3, "unit": "% by wt", "ref_text": ">5.4 (omegacheck EPA+DPA+DHA)",
        "flag": "low", "category": "fatty_acids", "panel": "omegacheck",
        "previous_value": 7.8, "previous_date": "2025-04-08",
    },
    "arachidonic_epa_ratio": {
        "value": 17.4, "value_numeric": 17.4, "unit": "ratio", "ref_text": "3.7-40.7",
        "flag": "normal", "category": "fatty_acids", "panel": "omegacheck",
        "previous_value": 8.1, "previous_date": "2025-04-08",
    },
    "omega_6_omega_3_ratio": {
        "value": 12.8, "value_numeric": 12.8, "unit": "ratio", "ref_text": "3.7-14.4",
        "flag": "normal", "category": "fatty_acids", "panel": "omegacheck",
        "previous_value": 5.2, "previous_date": "2025-04-08",
    },
    "omega_3_total_pct": {
        "value": 3.3, "value_numeric": 3.3, "unit": "% by wt", "ref_text": "(no defined range)",
        "flag": "normal", "category": "fatty_acids", "panel": "omegacheck",
        "previous_value": 7.8, "previous_date": "2025-04-08",
    },
    "epa": {
        "value": 0.5, "value_numeric": 0.5, "unit": "% by wt", "ref_text": "0.2-2.3",
        "flag": "normal", "category": "fatty_acids", "panel": "omegacheck",
        "previous_value": 1.7, "previous_date": "2025-04-08",
    },
    "dpa": {
        "value": 0.8, "value_numeric": 0.8, "unit": "% by wt", "ref_text": "0.8-1.8",
        "flag": "normal", "category": "fatty_acids", "panel": "omegacheck",
        "previous_value": 2.1, "previous_date": "2025-04-08",  # was flagged H in 2025
    },
    "dha": {
        "value": 1.9, "value_numeric": 1.9, "unit": "% by wt", "ref_text": "1.4-5.1",
        "flag": "normal", "category": "fatty_acids", "panel": "omegacheck",
        "previous_value": 3.9, "previous_date": "2025-04-08",
    },
    "omega_6_total_pct": {
        "value": 41.8, "value_numeric": 41.8, "unit": "% by wt", "ref_text": "(no defined range)",
        "flag": "normal", "category": "fatty_acids", "panel": "omegacheck",
        "previous_value": 40.2, "previous_date": "2025-04-08",
    },
    "arachidonic_acid": {
        "value": 9.4, "value_numeric": 9.4, "unit": "% by wt", "ref_text": "8.6-15.6",
        "flag": "normal", "category": "fatty_acids", "panel": "omegacheck",
        "previous_value": 13.8, "previous_date": "2025-04-08",
    },
    "linoleic_acid": {
        "value": 24.5, "value_numeric": 24.5, "unit": "% by wt", "ref_text": "18.6-29.5",
        "flag": "normal", "category": "fatty_acids", "panel": "omegacheck",
        "previous_value": 23.3, "previous_date": "2025-04-08",
    },

    # ──────── LEPTIN ────────
    "leptin": {
        "value": 16.8, "value_numeric": 16.8, "unit": "ng/mL",
        "ref_text": "Adult Lean (BMI 18-25) Males 0.3-13.4; BMI 25-30 Males 1.8-19.9",
        "flag": "normal", "category": "metabolic", "panel": "leptin",
        "previous_value": 0.4, "previous_date": "2025-04-08",  # huge change worth noting
    },

    # ──────── METHYLMALONIC ACID (B12 functional marker) ────────
    "methylmalonic_acid": {
        "value": 122, "value_numeric": 122, "unit": "nmol/L", "ref_text": "55-335",
        "flag": "normal", "category": "vitamins", "panel": "methylmalonic_acid",
        "previous_value": 76.0, "previous_date": "2025-04-08",
    },

    # ──────── URINALYSIS, COMPLETE (qualitative — keep key fields) ────────
    "urine_color": {
        "value": "YELLOW", "value_numeric": None, "unit": "", "ref_text": "YELLOW",
        "flag": "normal", "category": "urinalysis", "panel": "urinalysis",
        "previous_value": None, "previous_date": None,
    },
    "urine_appearance": {
        "value": "CLEAR", "value_numeric": None, "unit": "", "ref_text": "CLEAR",
        "flag": "normal", "category": "urinalysis", "panel": "urinalysis",
        "previous_value": None, "previous_date": None,
    },
    "urine_specific_gravity": {
        "value": 1.005, "value_numeric": 1.005, "unit": "", "ref_text": "1.001-1.035",
        "flag": "normal", "category": "urinalysis", "panel": "urinalysis",
        "previous_value": 1.012, "previous_date": "2025-04-17",
    },
    "urine_ph": {
        "value": 7.0, "value_numeric": 7.0, "unit": "", "ref_text": "5.0-8.0",
        "flag": "normal", "category": "urinalysis", "panel": "urinalysis",
        "previous_value": 6.0, "previous_date": "2025-04-17",
    },
    "urine_glucose": {
        "value": "NEGATIVE", "value_numeric": None, "unit": "", "ref_text": "NEGATIVE",
        "flag": "normal", "category": "urinalysis", "panel": "urinalysis",
        "previous_value": None, "previous_date": None,
    },
    "urine_protein": {
        "value": "NEGATIVE", "value_numeric": None, "unit": "", "ref_text": "NEGATIVE",
        "flag": "normal", "category": "urinalysis", "panel": "urinalysis",
        "previous_value": None, "previous_date": None,
    },
    "urine_ketones": {
        "value": "NEGATIVE", "value_numeric": None, "unit": "", "ref_text": "NEGATIVE",
        "flag": "normal", "category": "urinalysis", "panel": "urinalysis",
        "previous_value": None, "previous_date": None,
    },
    "urine_blood": {
        "value": "NEGATIVE", "value_numeric": None, "unit": "", "ref_text": "NEGATIVE",
        "flag": "normal", "category": "urinalysis", "panel": "urinalysis",
        "previous_value": None, "previous_date": None,
    },

    # ──────── CBC ────────
    "wbc": {
        "value": 3.9, "value_numeric": 3.9, "unit": "Thousand/uL", "ref_text": "3.8-10.8",
        "flag": "normal", "category": "cbc", "panel": "cbc",
        "previous_value": 3.4, "previous_date": "2025-04-17",  # was flagged L in 2025
    },
    "rbc": {
        "value": 5.04, "value_numeric": 5.04, "unit": "Million/uL", "ref_text": "4.20-5.80",
        "flag": "normal", "category": "cbc", "panel": "cbc",
        "previous_value": 4.41, "previous_date": "2025-04-17",
    },
    "hemoglobin": {
        "value": 15.1, "value_numeric": 15.1, "unit": "g/dL", "ref_text": "13.2-17.1",
        "flag": "normal", "category": "cbc", "panel": "cbc",
        "previous_value": 13.8, "previous_date": "2025-04-17",
    },
    "hematocrit": {
        "value": 44.3, "value_numeric": 44.3, "unit": "%", "ref_text": "39.4-51.1",
        "flag": "normal", "category": "cbc", "panel": "cbc",
        "previous_value": 41.4, "previous_date": "2025-04-17",
    },
    "mcv": {
        "value": 87.9, "value_numeric": 87.9, "unit": "fL", "ref_text": "81.4-101.7",
        "flag": "normal", "category": "cbc", "panel": "cbc",
        "previous_value": 93.9, "previous_date": "2025-04-17",
    },
    "mch": {
        "value": 30.0, "value_numeric": 30.0, "unit": "pg", "ref_text": "27.0-33.0",
        "flag": "normal", "category": "cbc", "panel": "cbc",
        "previous_value": 31.3, "previous_date": "2025-04-17",
    },
    "mchc": {
        "value": 34.1, "value_numeric": 34.1, "unit": "g/dL", "ref_text": "31.6-35.4",
        "flag": "normal", "category": "cbc", "panel": "cbc",
        "previous_value": 33.3, "previous_date": "2025-04-17",
    },
    "rdw": {
        "value": 12.8, "value_numeric": 12.8, "unit": "%", "ref_text": "11.0-15.0",
        "flag": "normal", "category": "cbc", "panel": "cbc",
        "previous_value": 12.6, "previous_date": "2025-04-17",
    },
    "platelet_count": {
        "value": 256, "value_numeric": 256, "unit": "Thousand/uL", "ref_text": "140-400",
        "flag": "normal", "category": "cbc", "panel": "cbc",
        "previous_value": 209.0, "previous_date": "2025-04-17",
    },
    "mpv": {
        "value": 9.7, "value_numeric": 9.7, "unit": "fL", "ref_text": "7.5-12.5",
        "flag": "normal", "category": "cbc", "panel": "cbc",
        "previous_value": 10.9, "previous_date": "2025-04-17",
    },
    "absolute_neutrophils": {
        "value": 2087, "value_numeric": 2087, "unit": "cells/uL", "ref_text": "1500-7800",
        "flag": "normal", "category": "cbc", "panel": "cbc",
        "previous_value": 1989.0, "previous_date": "2025-04-17",
    },
    "absolute_lymphocytes": {
        "value": 1307, "value_numeric": 1307, "unit": "cells/uL", "ref_text": "850-3900",
        "flag": "normal", "category": "cbc", "panel": "cbc",
        "previous_value": 1112.0, "previous_date": "2025-04-17",
    },
    "absolute_monocytes": {
        "value": 394, "value_numeric": 394, "unit": "cells/uL", "ref_text": "200-950",
        "flag": "normal", "category": "cbc", "panel": "cbc",
        "previous_value": 228.0, "previous_date": "2025-04-17",
    },
    "absolute_eosinophils": {
        "value": 62, "value_numeric": 62, "unit": "cells/uL", "ref_text": "15-500",
        "flag": "normal", "category": "cbc", "panel": "cbc",
        "previous_value": 41.0, "previous_date": "2025-04-17",
    },
    "absolute_basophils": {
        "value": 51, "value_numeric": 51, "unit": "cells/uL", "ref_text": "0-200",
        "flag": "normal", "category": "cbc", "panel": "cbc",
        "previous_value": 31.0, "previous_date": "2025-04-17",
    },

    # ──────── RHEUMATOID FACTOR ────────
    "rheumatoid_factor": {
        "value": "<10", "value_numeric": 10, "unit": "IU/mL", "ref_text": "<14",
        "flag": "normal", "category": "autoimmune", "panel": "rheumatoid_factor",
        "previous_value": None, "previous_date": None,
    },

    # ──────── HS CRP (KEY) ────────
    "crp_hs": {
        "value": 1.4, "value_numeric": 1.4, "unit": "mg/L", "ref_text": "<1.0 (optimal)",
        "flag": "high", "category": "inflammation", "panel": "hs_crp",
        "previous_value": None, "previous_date": None,
    },

    # ──────── ANA SCREEN ────────
    "ana_screen": {
        "value": "NEGATIVE", "value_numeric": None, "unit": "", "ref_text": "NEGATIVE",
        "flag": "normal", "category": "autoimmune", "panel": "ana_screen",
        "previous_value": None, "previous_date": None,
    },

    # ──────── THYROID ANTIBODIES ────────
    "thyroglobulin_antibodies": {
        "value": "<2", "value_numeric": 2, "unit": "IU/mL", "ref_text": "<= 2",
        "flag": "normal", "category": "thyroid", "panel": "thyroid_antibodies",
        "previous_value": None, "previous_date": None,
    },
    "thyroid_peroxidase_antibodies": {
        "value": "<1", "value_numeric": 1, "unit": "IU/mL", "ref_text": "<9",
        "flag": "normal", "category": "thyroid", "panel": "thyroid_antibodies",
        "previous_value": None, "previous_date": None,
    },

    # ──────── HOMOCYSTEINE ────────
    "homocysteine": {
        "value": 9.2, "value_numeric": 9.2, "unit": "umol/L", "ref_text": "<= 13.5",
        "flag": "normal", "category": "metabolic", "panel": "homocysteine",
        "previous_value": 9.5, "previous_date": "2025-04-08",
    },

    # ──────── HORMONES ────────
    "cortisol_total": {
        "value": 10.8, "value_numeric": 10.8, "unit": "mcg/dL",
        "ref_text": "8AM 4.0-22.0; 4PM 3.0-17.0",
        "flag": "normal", "category": "hormones", "panel": "cortisol",
        "previous_value": None, "previous_date": None,
    },
    "dhea_sulfate": {
        "value": 317, "value_numeric": 317, "unit": "mcg/dL", "ref_text": "93-415",
        "flag": "normal", "category": "hormones", "panel": "dhea_sulfate",
        "previous_value": 223.0, "previous_date": "2025-04-08",
    },
    "fsh": {
        "value": 1.9, "value_numeric": 1.9, "unit": "mIU/mL", "ref_text": "1.4-12.8",
        "flag": "normal", "category": "hormones", "panel": "fsh",
        "previous_value": 2.8, "previous_date": "2025-04-08",
    },
    "insulin_fasting": {
        "value": 14.3, "value_numeric": 14.3, "unit": "uIU/mL", "ref_text": "<= 18.4 (optimal)",
        "flag": "normal", "category": "metabolic", "panel": "insulin",
        "previous_value": 2.5, "previous_date": "2025-04-17",
    },
    "lh": {
        "value": 1.7, "value_numeric": 1.7, "unit": "mIU/mL", "ref_text": "1.5-9.3",
        "flag": "normal", "category": "hormones", "panel": "lh",
        "previous_value": 1.8, "previous_date": "2025-04-08",
    },
    "prolactin": {
        "value": 8.3, "value_numeric": 8.3, "unit": "ng/mL", "ref_text": "2.0-18.0",
        "flag": "normal", "category": "hormones", "panel": "prolactin",
        "previous_value": 3.4, "previous_date": "2025-04-08",
    },
    "t4_free": {
        "value": 1.5, "value_numeric": 1.5, "unit": "ng/dL", "ref_text": "0.8-1.8",
        "flag": "normal", "category": "thyroid", "panel": "t4_free",
        "previous_value": 1.3, "previous_date": "2025-04-17",
    },
    "tsh": {
        "value": 2.35, "value_numeric": 2.35, "unit": "mIU/L", "ref_text": "0.40-4.50",
        "flag": "normal", "category": "thyroid", "panel": "tsh",
        "previous_value": 1.52, "previous_date": "2025-04-17",
    },
    "estradiol": {
        "value": 32, "value_numeric": 32, "unit": "pg/mL", "ref_text": "<= 39",
        "flag": "normal", "category": "hormones", "panel": "estradiol",
        "previous_value": 16.0, "previous_date": "2025-04-08",
    },
    "shbg": {
        "value": 21, "value_numeric": 21, "unit": "nmol/L", "ref_text": "10-50",
        "flag": "normal", "category": "hormones", "panel": "shbg",
        "previous_value": 59.0, "previous_date": "2025-04-08",  # 2025 was flagged H
    },
    "t3_free": {
        "value": 3.5, "value_numeric": 3.5, "unit": "pg/mL", "ref_text": "2.3-4.2",
        "flag": "normal", "category": "thyroid", "panel": "t3_free",
        "previous_value": 2.5, "previous_date": "2025-04-17",
    },
    "vitamin_d_25oh": {
        "value": 28, "value_numeric": 28, "unit": "ng/mL", "ref_text": "30-100 (optimal >=30)",
        "flag": "low", "category": "vitamins", "panel": "vitamin_d",
        "previous_value": 117.0, "previous_date": "2025-04-17",  # 2025 was flagged H
    },
    "psa_total": {
        "value": 1.1, "value_numeric": 1.1, "unit": "ng/mL", "ref_text": "<= 4.0",
        "flag": "normal", "category": "prostate", "panel": "psa",
        "previous_value": 0.7, "previous_date": "2025-04-08",
    },
    "psa_free": {
        "value": 0.3, "value_numeric": 0.3, "unit": "ng/mL", "ref_text": "(no defined range)",
        "flag": "normal", "category": "prostate", "panel": "psa",
        "previous_value": 0.2, "previous_date": "2025-04-08",
    },
    "psa_pct_free": {
        "value": 27, "value_numeric": 27, "unit": "%", "ref_text": ">25 (calc)",
        "flag": "normal", "category": "prostate", "panel": "psa",
        "previous_value": 29.0, "previous_date": "2025-04-08",
    },
    "amylase": {
        "value": 18, "value_numeric": 18, "unit": "U/L", "ref_text": "21-101",
        "flag": "low", "category": "pancreas", "panel": "amylase",
        "previous_value": 18.0, "previous_date": "2025-04-08",  # was also low in 2025
    },
    "hba1c": {
        "value": 5.0, "value_numeric": 5.0, "unit": "%", "ref_text": "<5.7",
        "flag": "normal", "category": "metabolic", "panel": "hba1c",
        "previous_value": 4.9, "previous_date": "2025-04-17",
    },
    "lipase": {
        "value": 7, "value_numeric": 7, "unit": "U/L", "ref_text": "7-60",
        "flag": "normal", "category": "pancreas", "panel": "lipase",
        "previous_value": 12.0, "previous_date": "2025-04-08",
    },
    "apob": {
        "value": 116, "value_numeric": 116, "unit": "mg/dL", "ref_text": "<90 (optimal)",
        "flag": "high", "category": "lipids", "panel": "apolipoprotein_b",
        "previous_value": 107.0, "previous_date": "2025-04-17",  # 2025 was also H
    },

    # ──────── HEAVY METALS ────────
    "mercury_blood": {
        "value": "<4", "value_numeric": 4, "unit": "mcg/L", "ref_text": "<= 10",
        "flag": "normal", "category": "heavy_metals", "panel": "mercury",
        "previous_value": None, "previous_date": None,
    },
    "zinc": {
        "value": 64, "value_numeric": 64, "unit": "mcg/dL", "ref_text": "60-130",
        "flag": "normal", "category": "minerals", "panel": "zinc",
        "previous_value": 100.0, "previous_date": "2025-04-08",
    },
    "lead_venous": {
        "value": "<1.0", "value_numeric": 1.0, "unit": "mcg/dL", "ref_text": "<3.5",
        "flag": "normal", "category": "heavy_metals", "panel": "lead",
        "previous_value": None, "previous_date": None,
    },

    # ──────── BLOOD TYPE ────────
    "abo_group": {
        "value": "A", "value_numeric": None, "unit": "", "ref_text": "",
        "flag": "normal", "category": "blood_type", "panel": "abo_rh",
        "previous_value": None, "previous_date": None,
    },
    "rh_type": {
        "value": "RH(D) POSITIVE", "value_numeric": None, "unit": "", "ref_text": "",
        "flag": "normal", "category": "blood_type", "panel": "abo_rh",
        "previous_value": None, "previous_date": None,
    },

    # ──────── TESTOSTERONE (KEY: 361 vs prior 577) ────────
    "testosterone_total": {
        "value": 361, "value_numeric": 361, "unit": "ng/dL", "ref_text": "250-1100",
        "flag": "normal", "category": "hormones", "panel": "testosterone",
        "previous_value": 577.0, "previous_date": "2025-04-08",
    },
    "testosterone_free": {
        "value": 72, "value_numeric": 72, "unit": "pg/mL", "ref_text": "35.0-155.0",
        "flag": "normal", "category": "hormones", "panel": "testosterone",
        "previous_value": 63.5, "previous_date": "2025-04-08",
    },

    # ──────── NMR LIPOPROTEIN FRACTIONATION ────────
    "ldl_particle_number": {
        "value": 2128, "value_numeric": 2128, "unit": "nmol/L",
        "ref_text": "<1138 (optimal); 1138-1409 (moderate); >1409 (high)",
        "flag": "high", "category": "lipids_advanced", "panel": "lipoprotein_nmr",
        "previous_value": 1787.0, "previous_date": "2025-04-17",
    },
    "ldl_small": {
        "value": 352, "value_numeric": 352, "unit": "nmol/L",
        "ref_text": "<142 (optimal); 142-219 (moderate); >219 (high)",
        "flag": "high", "category": "lipids_advanced", "panel": "lipoprotein_nmr",
        "previous_value": 274.0, "previous_date": "2025-04-17",
    },
    "ldl_medium": {
        "value": 611, "value_numeric": 611, "unit": "nmol/L",
        "ref_text": "<215 (optimal); 215-301 (moderate); >301 (high)",
        "flag": "high", "category": "lipids_advanced", "panel": "lipoprotein_nmr",
        "previous_value": 307.0, "previous_date": "2025-04-17",
    },
    "hdl_large": {
        "value": 6504, "value_numeric": 6504, "unit": "nmol/L",
        "ref_text": ">6729 (optimal); 6729-5353 (moderate); <5353 (high)",
        "flag": "low", "category": "lipids_advanced", "panel": "lipoprotein_nmr",
        "previous_value": 6969.0, "previous_date": "2025-04-17",
    },
    "ldl_pattern": {
        "value": "A", "value_numeric": None, "unit": "",
        "ref_text": "Optimal: Pattern A; High: Pattern B",
        "flag": "normal", "category": "lipids_advanced", "panel": "lipoprotein_nmr",
        "previous_value": None, "previous_date": None,
    },
    "ldl_peak_size": {
        "value": 221.0, "value_numeric": 221.0, "unit": "Angstrom",
        "ref_text": ">222.9 (optimal); 222.9-217.4 (moderate); <217.4 (high)",
        "flag": "low", "category": "lipids_advanced", "panel": "lipoprotein_nmr",
        "previous_value": 223.1, "previous_date": "2025-04-17",
    },

    # ──────── RESPIRATORY ALLERGY PROFILE (KEY — NEW v2 TEST) ────────
    # IgE class scale: 0=Absent, 0/1=Very Low, 1=Low, 2=Moderate, 3=High, 4-6=Very High
    # We store both the kU/L value (numeric) and the class (ordinal severity)
    "allergy_total_ige": {
        "value": 339, "value_numeric": 339, "unit": "kU/L", "ref_text": "<= 114",
        "flag": "high", "category": "allergies", "panel": "respiratory_allergy",
        "previous_value": None, "previous_date": None,
    },
    "allergy_dust_mite_d_pteronyssinus": {
        "value": 4.85, "value_numeric": 4.85, "unit": "kU/L",
        "ref_text": "Class 3 (High Level: 3.50-17.4)",
        "flag": "high", "category": "allergies", "panel": "respiratory_allergy",
        "ige_class": 3,
        "previous_value": None, "previous_date": None,
    },
    "allergy_dust_mite_d_farinae": {
        "value": 3.06, "value_numeric": 3.06, "unit": "kU/L",
        "ref_text": "Class 2 (Moderate Level: 0.70-3.49)",
        "flag": "high", "category": "allergies", "panel": "respiratory_allergy",
        "ige_class": 2,
        "previous_value": None, "previous_date": None,
    },
    "allergy_penicillium_notatum": {
        "value": "<0.10", "value_numeric": 0.10, "unit": "kU/L",
        "ref_text": "Class 0 (Absent/Undetectable)",
        "flag": "normal", "category": "allergies", "panel": "respiratory_allergy",
        "ige_class": 0,
        "previous_value": None, "previous_date": None,
    },
    "allergy_cladosporium_herbarum": {
        "value": "<0.10", "value_numeric": 0.10, "unit": "kU/L",
        "ref_text": "Class 0 (Absent/Undetectable)",
        "flag": "normal", "category": "allergies", "panel": "respiratory_allergy",
        "ige_class": 0,
        "previous_value": None, "previous_date": None,
    },
    "allergy_aspergillus_fumigatus": {
        "value": "<0.10", "value_numeric": 0.10, "unit": "kU/L",
        "ref_text": "Class 0 (Absent/Undetectable)",
        "flag": "normal", "category": "allergies", "panel": "respiratory_allergy",
        "ige_class": 0,
        "previous_value": None, "previous_date": None,
    },
    "allergy_alternaria_alternata": {
        "value": "<0.10", "value_numeric": 0.10, "unit": "kU/L",
        "ref_text": "Class 0 (Absent/Undetectable)",
        "flag": "normal", "category": "allergies", "panel": "respiratory_allergy",
        "ige_class": 0,
        "previous_value": None, "previous_date": None,
    },
    "allergy_cat_dander": {
        "value": 0.63, "value_numeric": 0.63, "unit": "kU/L",
        "ref_text": "Class 1 (Low Level: 0.35-0.69)",
        "flag": "high", "category": "allergies", "panel": "respiratory_allergy",
        "ige_class": 1,
        "previous_value": None, "previous_date": None,
    },
    "allergy_dog_dander": {
        "value": 0.60, "value_numeric": 0.60, "unit": "kU/L",
        "ref_text": "Class 1 (Low Level: 0.35-0.69)",
        "flag": "high", "category": "allergies", "panel": "respiratory_allergy",
        "ige_class": 1,
        "previous_value": None, "previous_date": None,
    },
    "allergy_cockroach": {
        "value": "<0.10", "value_numeric": 0.10, "unit": "kU/L",
        "ref_text": "Class 0 (Absent/Undetectable)",
        "flag": "normal", "category": "allergies", "panel": "respiratory_allergy",
        "ige_class": 0,
        "previous_value": None, "previous_date": None,
    },
    "allergy_maple_box_elder": {
        "value": "<0.10", "value_numeric": 0.10, "unit": "kU/L",
        "ref_text": "Class 0 (Absent/Undetectable)",
        "flag": "normal", "category": "allergies", "panel": "respiratory_allergy",
        "ige_class": 0,
        "previous_value": None, "previous_date": None,
    },
    "allergy_alder": {
        "value": 5.08, "value_numeric": 5.08, "unit": "kU/L",
        "ref_text": "Class 3 (High Level: 3.50-17.4)",
        "flag": "high", "category": "allergies", "panel": "respiratory_allergy",
        "ige_class": 3,
        "previous_value": None, "previous_date": None,
    },
    "allergy_birch": {
        "value": 5.07, "value_numeric": 5.07, "unit": "kU/L",
        "ref_text": "Class 3 (High Level: 3.50-17.4)",
        "flag": "high", "category": "allergies", "panel": "respiratory_allergy",
        "ige_class": 3,
        "previous_value": None, "previous_date": None,
    },
    "allergy_mountain_cedar": {
        "value": "<0.10", "value_numeric": 0.10, "unit": "kU/L",
        "ref_text": "Class 0 (Absent/Undetectable)",
        "flag": "normal", "category": "allergies", "panel": "respiratory_allergy",
        "ige_class": 0,
        "previous_value": None, "previous_date": None,
    },
    "allergy_walnut_tree": {
        "value": "<0.10", "value_numeric": 0.10, "unit": "kU/L",
        "ref_text": "Class 0 (Absent/Undetectable)",
        "flag": "normal", "category": "allergies", "panel": "respiratory_allergy",
        "ige_class": 0,
        "previous_value": None, "previous_date": None,
    },
    "allergy_cottonwood": {
        "value": "<0.10", "value_numeric": 0.10, "unit": "kU/L",
        "ref_text": "Class 0 (Absent/Undetectable)",
        "flag": "normal", "category": "allergies", "panel": "respiratory_allergy",
        "ige_class": 0,
        "previous_value": None, "previous_date": None,
    },
    "allergy_white_ash": {
        "value": "<0.10", "value_numeric": 0.10, "unit": "kU/L",
        "ref_text": "Class 0 (Absent/Undetectable)",
        "flag": "normal", "category": "allergies", "panel": "respiratory_allergy",
        "ige_class": 0,
        "previous_value": None, "previous_date": None,
    },
    "allergy_oak": {
        "value": 1.64, "value_numeric": 1.64, "unit": "kU/L",
        "ref_text": "Class 2 (Moderate Level: 0.70-3.49)",
        "flag": "high", "category": "allergies", "panel": "respiratory_allergy",
        "ige_class": 2,
        "previous_value": None, "previous_date": None,
    },
    "allergy_elm": {
        "value": "<0.10", "value_numeric": 0.10, "unit": "kU/L",
        "ref_text": "Class 0 (Absent/Undetectable)",
        "flag": "normal", "category": "allergies", "panel": "respiratory_allergy",
        "ige_class": 0,
        "previous_value": None, "previous_date": None,
    },
    "allergy_timothy_grass": {
        "value": 0.68, "value_numeric": 0.68, "unit": "kU/L",
        "ref_text": "Class 1 (Low Level: 0.35-0.69)",
        "flag": "high", "category": "allergies", "panel": "respiratory_allergy",
        "ige_class": 1,
        "previous_value": None, "previous_date": None,
    },
    "allergy_common_ragweed": {
        "value": "<0.10", "value_numeric": 0.10, "unit": "kU/L",
        "ref_text": "Class 0 (Absent/Undetectable)",
        "flag": "normal", "category": "allergies", "panel": "respiratory_allergy",
        "ige_class": 0,
        "previous_value": None, "previous_date": None,
    },
    "allergy_rough_pigweed": {
        "value": "<0.10", "value_numeric": 0.10, "unit": "kU/L",
        "ref_text": "Class 0 (Absent/Undetectable)",
        "flag": "normal", "category": "allergies", "panel": "respiratory_allergy",
        "ige_class": 0,
        "previous_value": None, "previous_date": None,
    },
    "allergy_sheep_sorrel": {
        "value": "<0.10", "value_numeric": 0.10, "unit": "kU/L",
        "ref_text": "Class 0 (Absent/Undetectable)",
        "flag": "normal", "category": "allergies", "panel": "respiratory_allergy",
        "ige_class": 0,
        "previous_value": None, "previous_date": None,
    },
    "allergy_nettle": {
        "value": "<0.10", "value_numeric": 0.10, "unit": "kU/L",
        "ref_text": "Class 0 (Absent/Undetectable)",
        "flag": "normal", "category": "allergies", "panel": "respiratory_allergy",
        "ige_class": 0,
        "previous_value": None, "previous_date": None,
    },
    "allergy_mouse_urine_proteins": {
        "value": "<0.10", "value_numeric": 0.10, "unit": "kU/L",
        "ref_text": "Class 0 (Absent/Undetectable)",
        "flag": "normal", "category": "allergies", "panel": "respiratory_allergy",
        "ige_class": 0,
        "previous_value": None, "previous_date": None,
    },

    # ──────── NEUROFILAMENT LIGHT CHAIN (NEW v2 TEST) ────────
    "nfl_neurofilament_light_chain": {
        "value": 0.81, "value_numeric": 0.81, "unit": "pg/mL", "ref_text": "<1.29",
        "flag": "normal", "category": "neurodegeneration", "panel": "nfl",
        "previous_value": None, "previous_date": None,
    },

    # ──────── CARDIO IQ + ADVANCED CARDIOMETABOLIC PANELS (NEW v2 TESTS) ────────
    # Collected 2026-04-01 (separate draw from 04-03 standard panel).
    # These are the most diagnostically meaningful additions in v2 — Insulin Resistance
    # Score gives a definitive insulin-resistance diagnosis, complementing the
    # fasting_insulin trend in the standard panel.

    # ── Cardio IQ Insulin Resistance Panel with Score ──
    "insulin_intact_lcms": {
        "value": 16, "value_numeric": 16, "unit": "uIU/mL", "ref_text": "<=16",
        "flag": "normal", "category": "metabolic", "panel": "cardio_iq_insulin_resistance",
        "previous_value": None, "previous_date": None,
        "note": "Different assay than standard panel fasting_insulin (14.3). LC/MS/MS method.",
    },
    "c_peptide": {
        "value": 2.26, "value_numeric": 2.26, "unit": "ng/mL", "ref_text": "0.68-2.16",
        "flag": "high", "category": "metabolic", "panel": "cardio_iq_insulin_resistance",
        "previous_value": None, "previous_date": None,
    },
    "insulin_resistance_score": {
        "value": 75, "value_numeric": 75, "unit": "score",
        "ref_text": "<33 sensitive; 33-66 impaired; >66 resistant",
        "flag": "high", "category": "metabolic", "panel": "cardio_iq_insulin_resistance",
        "previous_value": None, "previous_date": None,
        "note": "Definitively insulin resistant. Combines insulin and C-peptide. The headline metabolic finding.",
    },

    # ── LPA Aspirin Genotype ──
    "lpa_aspirin_genotype": {
        "value": "Ile/Ile", "value_numeric": None, "unit": None,
        "ref_text": "Genotype variant — affects aspirin response",
        "flag": "normal", "category": "pharmacogenomics", "panel": "lpa_aspirin_genotype",
        "previous_value": None, "previous_date": None,
    },

    # ── Lp-PLA2 Activity ──
    "lp_pla2_activity": {
        "value": 137, "value_numeric": 137, "unit": "nmol/min/mL", "ref_text": "<=123",
        "flag": "high", "category": "inflammation", "panel": "lp_pla2",
        "previous_value": None, "previous_date": None,
        "note": "Vascular-specific inflammation marker. Combined with hs-CRP for cardiovascular risk.",
    },

    # ── Apolipoprotein Evaluation (additional ApoB measurement + ApoA1) ──
    "cystatin_c": {
        "value": 0.88, "value_numeric": 0.88, "unit": "mg/L", "ref_text": "0.52-1.31",
        "flag": "normal", "category": "kidney", "panel": "apolipoprotein_evaluation",
        "previous_value": None, "previous_date": None,
    },
    "apolipoprotein_a1": {
        "value": 183, "value_numeric": 183, "unit": "mg/dL",
        "ref_text": "(no formal range printed)",
        "flag": "normal", "category": "lipids", "panel": "apolipoprotein_evaluation",
        "previous_value": None, "previous_date": None,
    },
    "apob_cardio_iq": {
        # Different assay than standard panel ApoB (116). Cardio IQ method gave 111. Both flagged high.
        "value": 111, "value_numeric": 111, "unit": "mg/dL",
        "ref_text": "Same target as standard ApoB (<90 optimal); Cardio IQ uses different method",
        "flag": "high", "category": "lipids", "panel": "apolipoprotein_evaluation",
        "previous_value": None, "previous_date": None,
        "note": "Methodological pair to standard panel apob (116). Both indicate elevated atherogenic particles.",
    },
    "apob_apoa1_ratio": {
        "value": 0.61, "value_numeric": 0.61, "unit": "ratio",
        "ref_text": "Lower is better; <0.7 generally favorable",
        "flag": "normal", "category": "lipids", "panel": "apolipoprotein_evaluation",
        "previous_value": None, "previous_date": None,
    },
    "aalp_apo_a1": {
        "value": 213.21, "value_numeric": 213.21, "unit": "nmol/L", "ref_text": "181.36-359.23",
        "flag": "normal", "category": "lipids", "panel": "apolipoprotein_evaluation",
        "previous_value": None, "previous_date": None,
    },
    "aalp_apo_c1": {
        "value": 45.10, "value_numeric": 45.10, "unit": "nmol/L", "ref_text": "23.11-57.57",
        "flag": "normal", "category": "lipids", "panel": "apolipoprotein_evaluation",
        "previous_value": None, "previous_date": None,
    },
    "aalp_apo_c2": {
        "value": 5.41, "value_numeric": 5.41, "unit": "nmol/L", "ref_text": "3.67-14.55",
        "flag": "normal", "category": "lipids", "panel": "apolipoprotein_evaluation",
        "previous_value": None, "previous_date": None,
    },
    "aalp_apo_c3": {
        "value": 19.70, "value_numeric": 19.70, "unit": "nmol/L", "ref_text": "11.34-40.54",
        "flag": "normal", "category": "lipids", "panel": "apolipoprotein_evaluation",
        "previous_value": None, "previous_date": None,
    },
    "aalp_apo_c4": {
        "value": 0.31, "value_numeric": 0.31, "unit": "nmol/L", "ref_text": "0.29-1.10",
        "flag": "normal", "category": "lipids", "panel": "apolipoprotein_evaluation",
        "previous_value": None, "previous_date": None,
    },

    # ── HDL Function Panel with HDLFx PCAD Score ──
    "hdlfx_pcec": {
        "value": 10.4, "value_numeric": 10.4, "unit": "% efflux/4hr", "ref_text": "8.9-14.2",
        "flag": "normal", "category": "lipids", "panel": "hdl_function",
        "previous_value": None, "previous_date": None,
        "note": "Cholesterol efflux capacity — measures HDL functionality, not just quantity.",
    },
    "hdlfx_pcad_score": {
        "value": 14, "value_numeric": 14, "unit": "score", "ref_text": "<72",
        "flag": "normal", "category": "lipids", "panel": "hdl_function",
        "previous_value": None, "previous_date": None,
    },

    # ── Cardio IQ Fibrinogen Antigen ──
    "fibrinogen": {
        "value": 296, "value_numeric": 296, "unit": "mg/dL",
        "ref_text": "180-350; CVD optimal <=350; high >350",
        "flag": "normal", "category": "inflammation", "panel": "fibrinogen",
        "previous_value": None, "previous_date": None,
    },

    # ── Adiponectin ──
    "adiponectin": {
        "value": 10.9, "value_numeric": 10.9, "unit": "ug/mL",
        "ref_text": "Male BMI>30: 2.2-12.9; Male BMI 25-30: not specified for males",
        "flag": "normal", "category": "metabolic", "panel": "adiponectin",
        "previous_value": None, "previous_date": None,
        "note": "Insulin-sensitizing adipokine. Higher = better insulin sensitivity; low associated with metabolic syndrome.",
    },

    # ── Cardio IQ Myeloperoxidase (MPO) ──
    "myeloperoxidase": {
        "value": 268, "value_numeric": 268, "unit": "pmol/L",
        "ref_text": "<470; >=540 elevated MACE risk",
        "flag": "normal", "category": "inflammation", "panel": "mpo",
        "previous_value": None, "previous_date": None,
    },

    # ── TMAO (Trimethylamine N-Oxide) ──
    "tmao": {
        "value": 1.4, "value_numeric": 1.4, "unit": "uM", "ref_text": "<6.2",
        "flag": "normal", "category": "metabolic", "panel": "tmao",
        "previous_value": None, "previous_date": None,
        "note": "Gut-microbiome derived metabolite; elevated levels associated with cardiovascular events.",
    },

    # ──────── GALLERI MULTI-CANCER EARLY DETECTION (NEW v2 TEST) ────────
    "galleri_cancer_signal": {
        "value": "NO CANCER SIGNAL DETECTED", "value_numeric": None, "unit": "",
        "ref_text": "No Cancer Signal Detected (negative result)",
        "flag": "normal", "category": "cancer_screening", "panel": "galleri",
        "previous_value": None, "previous_date": None,
    },
    "galleri_predicted_signal_origin": {
        "value": "NO PREDICTED SIGNAL ORIGIN", "value_numeric": None, "unit": "",
        "ref_text": "(reported only when signal detected)",
        "flag": "normal", "category": "cancer_screening", "panel": "galleri",
        "previous_value": None, "previous_date": None,
    },
}


# ──────── DERIVED OUT-OF-RANGE LIST ────────
# Anything flagged "high" or "low" — used for the draw summary item
def out_of_range_keys():
    return sorted([k for k, v in BIOMARKERS.items() if v.get("flag") in ("high", "low")])


# ──────── KEY FINDINGS (curated for daily brief / coaching context) ────────
KEY_FINDINGS = [
    "Insulin resistance: definitively confirmed by Cardio IQ Insulin Resistance Score 75 (cutoff: >66 = resistant). Combines fasting insulin 14.3 (5.7x increase from 2.5 last year) and elevated C-peptide 2.26 (>2.16 cutoff). The standalone insulin trend was suggestive; the IR score is conclusive.",
    "Testosterone fell: 577 → 361 ng/dL (still normal range, but downstream of insulin/adiposity pattern; suboptimal for symptoms)",
    "Omega-3 index dropped: 7.8% → 3.3% — High cardiovascular risk category despite supplementation",
    "ApoB elevated: 107 → 116 mg/dL standard panel; 111 mg/dL Cardio IQ assay (target <90; physician conversation re: statin/PCSK9 warranted)",
    "Lp-PLA2 137 nmol/min/mL (>123 cutoff) — vascular-specific inflammation marker elevated alongside hs-CRP 1.4. Compounds atherogenic risk.",
    "GGT rising: 13 → 31 U/L (still in range but 2.4x increase, possible MASLD signal alongside lipids)",
    "Vitamin D dropped: 117 → 28 ng/mL (was high last year, now insufficient — absorption check)",
    "Lipoprotein particle (LDL-P) 2128 — High; small/medium LDL elevated",
    "Total IgE 339 — Sensitized to dust mites (D1, D2), alder/birch trees, oak, cat/dog dander, timothy grass",
    "Galleri: No Cancer Signal Detected",
    "NfL: 0.81 pg/mL (<1.29) — neurodegeneration marker normal; healthy baseline established for future tracking",
    "Adiponectin 10.9 ug/mL — within male BMI>30 range but low-end (2.2-12.9). Consistent with insulin-resistance pattern.",
    "MPO 268, TMAO 1.4, Fibrinogen 296 — all within normal CV inflammation/risk markers; the pattern is lipid-driven not inflammation-driven.",
]


# ──────── VALIDATION REFERENCES (used by ingest dry-run) ────────
# These were referenced explicitly in Supplement_Protocol_2026-05_v2.md.
# If the ingest script's extracted values don't match these, abort — extraction is wrong.
VALIDATION_REFERENCES = {
    "insulin_fasting":          14.3,    # protocol: "insulin from 2.5 → 14.3"
    "testosterone_total":       361,     # protocol: "testosterone from 577 → 361"
    "omega_3_index":            3.3,     # protocol: "omega-3 from 7.8% → 3.3%"
    "apob":                     116,     # protocol: "ApoB 116"
    "ggt":                      31,      # protocol: "GGT moved 22 → 31"
    "vitamin_d_25oh":           28,      # protocol triggers absorption workup
    "crp_hs":                   1.4,     # protocol: "hs-CRP 1.4"
    "ldl_particle_number":      2128,    # protocol: "LDL-P 2128"
    "lp_pla2_activity":         137,     # protocol: "Lp-PLA2 137"
    "homocysteine":             9.2,     # protocol: "Homocysteine 9.2"
    "methylmalonic_acid":       122,     # protocol: "MMA 122"
    "magnesium_rbc":            5.9,     # protocol: "RBC magnesium (5.9)"
    "sodium":                   138,     # protocol: "Sodium 138 is fine"
    "zinc":                     64,      # protocol implies below baseline 100
    "insulin_resistance_score": 75,      # Cardio IQ confirmed insulin resistant
}


# ──────── S3 ARTIFACT REFERENCES (set by ingest script) ────────
S3_ARTIFACTS = {
    "standard_panel_pdf": "raw/matthew/labs/2026-04-03/standard_panel.pdf",
    "cardio_iq_nfl_pdf": "raw/matthew/labs/2026-04-03/cardio_iq_nfl_panel.pdf",
    "galleri_corrected_pdf": "raw/matthew/labs/2026-04-03/galleri_corrected.pdf",
    "galleri_grail_original_pdf": "raw/matthew/labs/2026-04-03/galleri_grail_original.pdf",
    "clinician_notes_2026_pdf": "raw/matthew/labs/2026-04-03/clinician_notes.pdf",
    "function_data_trends_pdf": "raw/matthew/labs/2026-04-03/function_data_trends.pdf",
    "supplement_protocol_md": "raw/matthew/labs/2026-04-03/supplement_protocol_v2.md",
}
