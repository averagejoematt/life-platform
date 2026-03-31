#!/usr/bin/env python3
"""
patch_dexa_2026_03_30.py — Add 2026-03-30 DexaFit DEXA scan + correct 2025-05-10 baseline.

Changes:
  1. NEW  — 2026-03-30  DexaFit Seattle DEXA scan (standard + 360 report)
  2. PATCH — 2025-05-10  Corrects weight/lean/fat/visceral to match official scan history
             (original seed used preliminary report figures)

Source PDFs:
  - Standard DexaFit report (body score, body fat, lean mass, bone, visceral fat)
  - DexaFit 360 report (biological age, 360 score, ALMI, FFMI, FMI, limb MBR, symmetry)

Schema:
  PK = USER#matthew#SOURCE#dexa
  SK = DATE#YYYY-MM-DD

Usage:
  python3 patch_dexa_2026_03_30.py          # dry run
  python3 patch_dexa_2026_03_30.py --write  # write to DynamoDB
"""

import boto3
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal

TABLE_NAME = "life-platform"
REGION = "us-west-2"
DEXA_PK = "USER#matthew#SOURCE#dexa"
NOW = datetime.now(timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════
# 1.  NEW SCAN: 2026-03-30  — DexaFit Seattle
#     Source: Standard report + DexaFit 360 report
# ═══════════════════════════════════════════════════════════════

dexa_2026 = {
    "pk": DEXA_PK,
    "sk": "DATE#2026-03-30",
    "scan_date": "2026-03-30",
    "provider": "dexafit_seattle",
    "provider_address": "111 W John St, Seattle WA",
    "scan_type": "dexa",
    "updated_at": NOW,

    # ── Body Score (DexaFit proprietary) ──────────────────────
    "body_score": {
        "grade": "C-",
        "numeric": Decimal("70"),
        "percentile": Decimal("24"),
        "rating": "needs_focus",
        "suggested_next_visit_days": 90,
    },

    # ── Core Body Composition ─────────────────────────────────
    "body_composition": {
        "total_mass_lb": Decimal("311.7"),
        "body_fat_pct": Decimal("42.7"),
        "fat_mass_lb": Decimal("133.1"),
        "lean_mass_lb": Decimal("170.6"),
        "bone_mineral_content_lb": Decimal("8.0"),
        "android_fat_pct": Decimal("51"),
        "gynoid_fat_pct": Decimal("48"),
        "ag_ratio": Decimal("1.06"),
        "visceral_fat_lb": Decimal("3.21"),
        "visceral_fat_g": Decimal("1456"),   # 3.21 lb × 453.592
    },

    # ── Bone Health ───────────────────────────────────────────
    "bone": {
        "bmc_lb": Decimal("8.0"),
        "t_score": Decimal("3.90"),           # DexaFit proprietary whole-body score
        "z_score": Decimal("3.90"),
        "t_score_change": Decimal("-0.50"),
        "bmd_by_region": {                     # g/cm²  and age-sex percentile
            "total_body": {"bmd": Decimal("1.593"), "percentile": 96},
            "trunk":      {"bmd": Decimal("1.339"), "percentile": 94},
            "head":       {"bmd": Decimal("2.726"), "percentile": 90},
            "arms":       {"bmd": Decimal("1.310"), "percentile": 90},
            "legs":       {"bmd": Decimal("1.661"), "percentile": 94},
            "ribs":       {"bmd": Decimal("1.077"), "percentile": 86},
            "spine":      {"bmd": Decimal("1.553"), "percentile": 94},
            "pelvis":     {"bmd": Decimal("1.472"), "percentile": 92},
        },
    },

    # ── Segmental Body Fat ────────────────────────────────────
    "segmental_fat": {
        "total_pct": Decimal("42.7"),
        "total_lb": Decimal("133.1"),
        "arms_pct": Decimal("31.1"),
        "arms_lb": Decimal("11.3"),
        "arms_left_lb": Decimal("5.6"),
        "arms_right_lb": Decimal("5.6"),
        "trunk_pct": Decimal("44.0"),
        "trunk_lb": Decimal("62.0"),
        "trunk_left_lb": Decimal("31.1"),
        "trunk_right_lb": Decimal("31.2"),
        "legs_pct": Decimal("46.7"),
        "legs_lb": Decimal("57.0"),
        "legs_left_lb": Decimal("28.6"),
        "legs_right_lb": Decimal("28.6"),
    },

    # ── Segmental Lean Mass ───────────────────────────────────
    "segmental_lean": {
        "total_lb": Decimal("170.6"),
        "arms_pct": Decimal("65.8"),
        "arms_lb": Decimal("23.9"),
        "arms_left_lb": Decimal("11.9"),
        "arms_right_lb": Decimal("11.9"),
        "trunk_pct": Decimal("54.3"),
        "trunk_lb": Decimal("77.0"),
        "trunk_left_lb": Decimal("38.4"),
        "trunk_right_lb": Decimal("38.3"),
        "legs_pct": Decimal("50.8"),
        "legs_lb": Decimal("62.0"),
        "legs_left_lb": Decimal("31.1"),
        "legs_right_lb": Decimal("31.1"),
    },

    # ── Derived Indices ───────────────────────────────────────
    "indices": {
        "almi_kg_m2": Decimal("13.1"),         # Appendicular Lean Mass Index — elite, 99th %tile
        "ffmi_kg_m2": Decimal("27.1"),         # Fat-Free Mass Index — above average
        "fmi_kg_m2":  Decimal("20.2"),         # Fat Mass Index — excess fat, 99th %tile
        "almi_percentile": 99,
        "ffmi_rating": "above_average",
        "fmi_rating": "excess_fat",
    },

    # ── DexaFit 360 Data ──────────────────────────────────────
    "score_360": {
        "score": Decimal("194"),
        "rating": "needs_focus",
        "change": Decimal("-106"),
        "biological_age": 42,
        "chronological_age": 37,
        "biological_age_delta": Decimal("+5"),   # bio age is 5yr older than chrono
        "bio_age_rating": "needs_focus",
        "bio_age_vs_peer": "average",             # within 1 std deviation
    },

    # ── Limb Detail (from 360 report) ─────────────────────────
    "limbs": {
        "right_arm": {
            "total_lb": Decimal("18.1"),
            "lean_lb": Decimal("11.9"),
            "fat_lb": Decimal("5.6"),
            "lean_pct": Decimal("65"),
            "fat_pct": Decimal("30"),
            "mbr": Decimal("19.8"),               # Muscle-to-Bone Ratio
        },
        "left_arm": {
            "total_lb": Decimal("18.1"),
            "lean_lb": Decimal("11.9"),
            "fat_lb": Decimal("5.6"),
            "lean_pct": Decimal("65"),
            "fat_pct": Decimal("30"),
            "mbr": Decimal("19.8"),
        },
        "right_leg": {
            "total_lb": Decimal("61.3"),
            "lean_lb": Decimal("31.1"),
            "fat_lb": Decimal("28.6"),
            "lean_pct": Decimal("50"),
            "fat_pct": Decimal("46"),
            "mbr": Decimal("19.4"),
        },
        "left_leg": {
            "total_lb": Decimal("61.3"),
            "lean_lb": Decimal("31.1"),
            "fat_lb": Decimal("28.6"),
            "lean_pct": Decimal("50"),
            "fat_pct": Decimal("46"),
            "mbr": Decimal("19.4"),
        },
        "arm_symmetry": Decimal("0.0"),
        "leg_symmetry": Decimal("0.0"),
    },

    # ── Score Factor Targets (from standard report) ───────────
    "targets": {
        "total_mass_lb": Decimal("296"),
        "body_fat_pct": Decimal("40"),
        "lean_mass_lb": Decimal("171"),
        "visceral_fat_lb": Decimal("1.00"),
        "t_score": Decimal("3.90"),
        "almi_kg_m2": Decimal("13.1"),
        "ffmi_kg_m2": Decimal("27.1"),
    },

    # ── Changes vs Baseline (2025-05-10) ─────────────────────
    "changes_vs_baseline": {
        "total_mass_lb": Decimal("+111.8"),
        "fat_mass_lb": Decimal("+102.0"),
        "lean_mass_lb": Decimal("+9.7"),
        "visceral_fat_lb": Decimal("+2.15"),
        "almi_kg_m2": Decimal("+1.97"),
        "ffmi_kg_m2": Decimal("+1.49"),
        "t_score": Decimal("-0.50"),
    },
}


# ═══════════════════════════════════════════════════════════════
# 2.  PATCH: 2025-05-10  — Correct baseline body composition
#     Original seed used preliminary/incorrect report values.
#     Corrected values sourced from scan history in 2026-03-30 report.
#
#     Errors corrected:
#       weight_lb:    190.2 → 199.9
#       fat_mass_lb:   29.8 → 31.1   (199.9 × 15.6%)
#       lean_mass_lb: 150.3 → 160.9
#       visceral_fat_lb: 0.5 → 1.06
#       body_score_grade: (missing) → A-
#       t_score: 1.4 → 4.4
# ═══════════════════════════════════════════════════════════════

dexa_2025_patch = {
    "pk": DEXA_PK,
    "sk": "DATE#2025-05-10",
    "scan_date": "2025-05-10",
    "provider": "dexafit_seattle",
    "provider_address": "111 W. John St. Suite 203A, Seattle WA 98119",
    "scan_type": "dexa",
    "updated_at": NOW,
    "patch_note": "Corrected 2026-03-30 — original seed had preliminary report values",

    # ── Body Score ─────────────────────────────────────────────
    "body_score": {
        "grade": "A-",
        "numeric": Decimal("93"),              # from 360 trend chart baseline
        "rating": "excellent",
    },

    # ── Core Body Composition (corrected) ─────────────────────
    "body_composition": {
        "total_mass_lb": Decimal("199.9"),     # was 190.2
        "body_fat_pct": Decimal("15.6"),       # unchanged
        "fat_mass_lb": Decimal("31.1"),        # was 29.8; 199.9 × 15.6% ≈ 31.2, report shows 31.1
        "lean_mass_lb": Decimal("160.9"),      # was 150.3
        "bone_mineral_content_lb": Decimal("7.9"),  # from BMC history chart baseline ~7.9
        "android_fat_pct": Decimal("22.1"),   # retained from seed (posture report)
        "gynoid_fat_pct": Decimal("19.6"),
        "ag_ratio": Decimal("1.13"),           # retained from seed
        "visceral_fat_lb": Decimal("1.06"),    # was 0.5
        "visceral_fat_g": Decimal("481"),      # 1.06 lb × 453.592
    },

    # ── Bone (corrected T-score) ──────────────────────────────
    "bone": {
        "t_score": Decimal("4.40"),            # from scan history; was 1.4 in seed
        "z_score": Decimal("4.40"),
    },

    # ── Posture assessment — retained from original seed ──────
    "posture": {
        "method": "kinetisense_3d",
        "notes": "Full posture data retained from original seed_physicals_dexa.py",
    },

    # ── Interpretations — retained from seed ─────────────────
    "interpretations": {
        "strengths": [
            "Leaner than 85% of men same age",
            "Low visceral fat — elite category for heart/liver health and insulin sensitivity",
            "Exceptional lean mass retention post-120lb weight loss",
            "Bone mineral density T-score 4.4 — excellent longevity profile",
        ],
        "areas_for_focus": [
            "Android-to-gynoid fat ratio 1.13 — slightly elevated (target 1.0 or lower)",
            "Mild limb asymmetry (common, manageable)",
            "Consistent left-side rotation from shoulders to ankles",
            "Right hip tilt — anterior pelvic tilt or glute deactivation",
            "Forward shoulder posture — possible upper-cross syndrome",
        ],
        "goals_6mo": {
            "body_fat_target_pct": "12-13",
            "fat_loss_target_lb": "5-7",
            "ag_ratio_target": "1.0 or lower",
            "lean_mass": "maintain or grow",
        },
    },
}


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

ALL_ITEMS = [
    ("NEW",   "2026-03-30", dexa_2026),
    ("PATCH", "2025-05-10", dexa_2025_patch),
]


def decimal_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError


def item_size_kb(item):
    return len(json.dumps(item, default=decimal_default).encode("utf-8")) / 1024


def print_summary(op, date, item):
    bc = item.get("body_composition", {})
    bs = item.get("body_score", {})
    bn = item.get("bone", {})
    print(f"  [{op}] {date}")
    print(f"         Total mass:  {bc.get('total_mass_lb', '?')} lb")
    print(f"         Body fat:    {bc.get('body_fat_pct', '?')}%  |  Fat: {bc.get('fat_mass_lb', '?')} lb  |  Lean: {bc.get('lean_mass_lb', '?')} lb")
    print(f"         Visceral:    {bc.get('visceral_fat_lb', '?')} lb")
    print(f"         Body score:  {bs.get('grade', '?')}  |  T-Score: {bn.get('t_score', '?')}")
    if "indices" in item:
        idx = item["indices"]
        print(f"         ALMI: {idx.get('almi_kg_m2', '?')} kg/m²  |  FFMI: {idx.get('ffmi_kg_m2', '?')} kg/m²  |  FMI: {idx.get('fmi_kg_m2', '?')} kg/m²")
    if "score_360" in item:
        s360 = item["score_360"]
        print(f"         360 Score: {s360.get('score', '?')}  |  Bio Age: {s360.get('biological_age', '?')} (chrono: {s360.get('chronological_age', '?')})")
    print(f"         Item size:   {item_size_kb(item):.1f} KB")
    print()


def main():
    write_mode = "--write" in sys.argv

    print("=" * 60)
    print("Life Platform — DEXA Patch: Add 2026-03-30 + Fix 2025-05-10")
    print("=" * 60)
    print(f"Mode:  {'WRITE' if write_mode else 'DRY RUN'}")
    print(f"Table: {TABLE_NAME} ({REGION})")
    print()

    for op, date, item in ALL_ITEMS:
        print_summary(op, date, item)

    if not write_mode:
        print("DRY RUN — no data written. Run with --write to apply.")
        print()
        print("Verification after write:")
        print(f'  aws dynamodb query \\')
        print(f'    --table-name {TABLE_NAME} \\')
        print(f'    --key-condition-expression "pk = :pk" \\')
        print(f'    --expression-attribute-values \'{{"pk": {{"S": "{DEXA_PK}"}}}}\' \\')
        print(f'    --projection-expression "sk, scan_date, body_composition.total_mass_lb, body_composition.body_fat_pct" \\')
        print(f'    --region {REGION}')
        return

    ddb = boto3.resource("dynamodb", region_name=REGION)
    table = ddb.Table(TABLE_NAME)

    for op, date, item in ALL_ITEMS:
        print(f"  Writing [{op}] {date}... ", end="", flush=True)
        table.put_item(Item=item)
        print("done")

    print()
    print(f"Done! {len(ALL_ITEMS)} items written.")
    print()
    print("Verify:")
    print(f'  aws dynamodb query \\')
    print(f'    --table-name {TABLE_NAME} \\')
    print(f'    --key-condition-expression "pk = :pk" \\')
    print(f'    --expression-attribute-values \'{{"pk": {{"S": "{DEXA_PK}"}}}}\' \\')
    print(f'    --projection-expression "sk, body_composition.total_mass_lb, body_composition.body_fat_pct" \\')
    print(f'    --region {REGION}')


if __name__ == "__main__":
    main()
