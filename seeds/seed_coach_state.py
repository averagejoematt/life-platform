"""
Seed Coach Intelligence State — Phase 1E

Initializes DynamoDB records for the Coach Intelligence Architecture:
1. COACH# records for all 8 coaches (empty threads, Beta(1,1) priors, early relationship, voice state)
2. NARRATIVE#arc STATE#current → early_baseline
3. ENSEMBLE#influence_graph CONFIG#v1 from local config file

Usage:
  python3 seeds/seed_coach_state.py [--dry-run]

Safe to re-run — uses put_item (idempotent overwrites).
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal

import boto3

TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
REGION = "us-west-2"

COACHES = [
    {"coach_id": "sleep_coach", "display_name": "Dr. Lisa Park", "domain": "sleep_science"},
    {"coach_id": "nutrition_coach", "display_name": "Dr. Marcus Webb", "domain": "nutrition"},
    {"coach_id": "training_coach", "display_name": "Dr. Sarah Chen", "domain": "exercise_physiology"},
    {"coach_id": "mind_coach", "display_name": "Dr. Nathan Reeves", "domain": "psychiatry"},
    {"coach_id": "physical_coach", "display_name": "Dr. Victor Reyes", "domain": "body_composition"},
    {"coach_id": "glucose_coach", "display_name": "Dr. Amara Patel", "domain": "metabolic_health"},
    {"coach_id": "labs_coach", "display_name": "Dr. James Okafor", "domain": "clinical_pathology"},
    {"coach_id": "explorer_coach", "display_name": "Dr. Henning Brandt", "domain": "biostatistics"},
]

CONFIDENCE_SUBDOMAINS = {
    "sleep_coach": ["sleep_duration", "sleep_architecture", "sleep_recovery", "circadian_timing", "hrv_sleep_correlation"],
    "nutrition_coach": ["calorie_adherence", "protein_adequacy", "macro_balance", "meal_timing", "deficit_sustainability"],
    "training_coach": ["training_load", "progressive_overload", "recovery_adequacy", "modality_balance", "zone2_adequacy"],
    "mind_coach": ["emotional_assessment", "behavioral_patterns", "journal_analysis", "stress_management", "avoidance_detection"],
    "physical_coach": ["weight_trajectory", "body_composition", "lean_mass", "visceral_fat", "metabolic_markers"],
    "glucose_coach": ["glucose_variability", "time_in_range", "meal_response", "fasting_glucose", "metabolic_flexibility"],
    "labs_coach": ["biomarker_interpretation", "supplement_impact", "lifestyle_correlation", "trend_detection", "risk_assessment"],
    "explorer_coach": ["cross_domain_correlation", "hypothesis_generation", "n1_methodology", "signal_detection", "causal_inference"],
}

now_iso = datetime.now(timezone.utc).isoformat()


def _dec(val):
    """Convert to Decimal for DynamoDB."""
    if isinstance(val, float):
        return Decimal(str(val))
    if isinstance(val, int):
        return Decimal(val)
    return val


def build_items():
    """Build all DynamoDB items to seed."""
    items = []

    for coach in COACHES:
        cid = coach["coach_id"]
        pk = f"COACH#{cid}"

        # Voice state — empty, ready to accumulate
        items.append({
            "pk": pk,
            "sk": "VOICE#state",
            "recent_openings": [],
            "overused_patterns": [],
            "signature_patterns_to_reinforce": [],
            "anti_patterns": [],
            "last_updated": now_iso,
        })

        # Relationship state — early phase
        items.append({
            "pk": pk,
            "sk": "RELATIONSHIP#state",
            "rapport_level": "early",
            "known_responsiveness": {
                "engages_with": ["data-driven insights", "specific actionable steps"],
                "resistant_to": ["vague encouragement", "overly cautious hedging"],
                "motivational_profile": "responds to direct honesty over diplomacy",
            },
            "topics_covered_depth": {},
            "inside_references": [],
            "journey_phase": "early_baseline",
            "last_updated": now_iso,
        })

        # Compressed state — empty initial
        items.append({
            "pk": pk,
            "sk": "COMPRESSED#latest",
            "coach_id": cid,
            "display_name": coach["display_name"],
            "domain": coach["domain"],
            "summary": f"{coach['display_name']} — early baseline phase. No outputs generated yet. Observing and building data context.",
            "key_concerns": [],
            "key_recommendations": [],
            "active_threads": [],
            "active_predictions": [],
            "confidence_state": {},
            "recent_themes": [],
            "last_output_date": None,
            "compressed_at": now_iso,
        })

        # Bayesian confidence priors — Beta(1,1) = uninformed
        for subdomain in CONFIDENCE_SUBDOMAINS.get(cid, []):
            items.append({
                "pk": pk,
                "sk": f"CONFIDENCE#{subdomain}",
                "subdomain": subdomain,
                "alpha": _dec(1.0),
                "beta": _dec(1.0),
                "mean": _dec(0.5),
                "sample_size": _dec(0),
                "last_updated": now_iso,
            })

    # Narrative arc — early_baseline
    items.append({
        "pk": "NARRATIVE#arc",
        "sk": "STATE#current",
        "phase": "early_baseline",
        "entered_date": "2026-04-01",
        "description": "Establishing norms, building data",
        "coaching_tone": "Observational, curious, low-intervention",
        "risk_tolerance": "low",
        "decision_class_ceiling": "observational",
        "transition_history": [],
        "last_updated": now_iso,
    })

    # Influence graph from config file
    influence_path = os.path.join(os.path.dirname(__file__), "..", "config", "coaches", "influence_graph.json")
    if os.path.exists(influence_path):
        with open(influence_path) as f:
            graph = json.load(f)
        items.append({
            "pk": "ENSEMBLE#influence_graph",
            "sk": "CONFIG#v1",
            "weights": graph.get("weights", {}),
            "notes": graph.get("notes", ""),
            "last_reviewed": graph.get("last_reviewed", "2026-04-06"),
            "last_updated": now_iso,
        })
    else:
        print(f"[WARN] Influence graph config not found at {influence_path} — skipping")

    return items


def seed(dry_run=False):
    items = build_items()
    print(f"Built {len(items)} items to seed")

    if dry_run:
        for item in items:
            print(f"  [DRY] {item['pk']} / {item['sk']}")
        print(f"\n[DRY RUN] Would write {len(items)} items. Use without --dry-run to execute.")
        return

    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    table = dynamodb.Table(TABLE_NAME)

    written = 0
    for item in items:
        # Convert all float values to Decimal for DynamoDB
        clean = json.loads(json.dumps(item, default=str), parse_float=Decimal)
        try:
            table.put_item(Item=clean)
            written += 1
        except Exception as e:
            print(f"  [ERROR] {item['pk']} / {item['sk']}: {e}")

    print(f"\nSeeded {written}/{len(items)} items to {TABLE_NAME}")


def upload_configs_to_s3(dry_run=False):
    """Upload config files to S3."""
    s3 = boto3.client("s3", region_name=REGION)
    config_root = os.path.join(os.path.dirname(__file__), "..", "config")

    uploads = [
        ("computation/ewma_params.json", "config/computation/ewma_params.json"),
        ("computation/seasonal_adjustments.json", "config/computation/seasonal_adjustments.json"),
        ("coaches/influence_graph.json", "config/coaches/influence_graph.json"),
        ("narrative/arc_definitions.json", "config/narrative/arc_definitions.json"),
    ]

    # Also upload any coach voice specs
    coaches_dir = os.path.join(config_root, "coaches")
    if os.path.isdir(coaches_dir):
        for fname in os.listdir(coaches_dir):
            if fname.endswith(".json") and fname != "influence_graph.json":
                uploads.append((f"coaches/{fname}", f"config/coaches/{fname}"))

    for local_rel, s3_key in uploads:
        local_path = os.path.join(config_root, local_rel)
        if not os.path.exists(local_path):
            print(f"  [SKIP] {local_rel} — not found")
            continue
        if dry_run:
            print(f"  [DRY] {local_rel} → s3://{S3_BUCKET}/{s3_key}")
        else:
            s3.upload_file(local_path, S3_BUCKET, s3_key)
            print(f"  [OK] {local_rel} → s3://{S3_BUCKET}/{s3_key}")

    print(f"\nConfig upload {'simulated' if dry_run else 'complete'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed Coach Intelligence state")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be written without writing")
    args = parser.parse_args()

    print("=" * 60)
    print("Coach Intelligence Architecture — State Seed")
    print("=" * 60)
    print()

    print("Step 1: Upload config files to S3")
    upload_configs_to_s3(dry_run=args.dry_run)
    print()

    print("Step 2: Seed DynamoDB coach state")
    seed(dry_run=args.dry_run)
    print()

    print("Done.")
