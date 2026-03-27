#!/usr/bin/env python3
"""
add_experiments.py — Append 6 new experiments from Product Board brainstorm
Run: python3 deploy/add_experiments.py
"""
import json
import os

PROJECT_ROOT = os.path.expanduser("~/Documents/Claude/life-platform")
LIB_PATH = os.path.join(PROJECT_ROOT, "config", "experiment_library.json")

NEW_EXPERIMENTS = [
    {
        "id": "sauna-2x-week-6wk",
        "name": "Sauna 2x/Week for 6 Weeks",
        "description": "Regular sauna use to test cardiovascular and recovery benefits",
        "pillar": "movement",
        "evidence_tier": "strong",
        "evidence_summary": "4-7 sauna sessions/week associated with 40% reduction in all-cause mortality",
        "evidence_citation": "Laukkanen et al., JAMA Internal Medicine, 2015",
        "suggested_duration_days": 42,
        "difficulty": "moderate",
        "experiment_type": "measurable",
        "hypothesis_template": "Regular sauna use (2x/week, 20 min at 174\u00b0F) will improve HRV by >5% and reduce resting heart rate",
        "protocol_template": "20 minutes at 174\u00b0F (79\u00b0C), 2x per week. Hydrate before and after. No cold plunge after (isolate variable).",
        "metrics_measurable": ["hrv", "resting_heart_rate", "recovery_score", "sleep_quality"],
        "tags": ["heat", "cardiovascular", "recovery"],
        "status": "backlog"
    },
    {
        "id": "cold-plunge-3x-week",
        "name": "Cold Plunge 2 min, 3x/Week",
        "description": "Deliberate cold exposure for dopamine and mood",
        "pillar": "mental",
        "evidence_tier": "strong",
        "evidence_summary": "Cold water immersion increases dopamine 250%, norepinephrine 530%",
        "evidence_citation": "Šrámek et al., 2000; Huberman Lab",
        "suggested_duration_days": 28,
        "difficulty": "hard",
        "experiment_type": "measurable",
        "hypothesis_template": "Cold plunge (2 min, 3x/week) will increase morning HRV and improve subjective mood scores",
        "protocol_template": "2 minutes in cold water (50-59\u00b0F), 3x per week. Morning preferred. No warm shower after for 20 min.",
        "metrics_measurable": ["hrv", "mood_score", "energy_score"],
        "tags": ["cold", "dopamine", "mental"],
        "status": "backlog"
    },
    {
        "id": "zone2-150-min-week",
        "name": "Zone 2 Cardio 150+ min/Week",
        "description": "Sustained Zone 2 base building for 8 weeks",
        "pillar": "movement",
        "evidence_tier": "strong",
        "evidence_summary": "Zone 2 training is the highest-evidence longevity modality",
        "evidence_citation": "Attia, Outlive; WHO guidelines",
        "suggested_duration_days": 56,
        "difficulty": "moderate",
        "experiment_type": "measurable",
        "hypothesis_template": "150+ min/week Zone 2 for 8 weeks will improve cardiac efficiency (pace-at-HR) by >5%",
        "protocol_template": "Minimum 150 minutes per week in Zone 2 (60-70% max HR). Walking, cycling, or rucking.",
        "metrics_measurable": ["zone2_minutes", "cardiac_efficiency", "resting_heart_rate"],
        "tags": ["zone2", "cardio", "longevity"],
        "status": "backlog"
    },
    {
        "id": "morning-sunlight-blue-blockers",
        "name": "Morning Sunlight + Evening Blue Blockers",
        "description": "Full circadian protocol: morning light + evening protection",
        "pillar": "sleep",
        "evidence_tier": "strong",
        "evidence_summary": "Morning light advances circadian phase; evening blue blockers preserve melatonin onset",
        "evidence_citation": "Huberman Lab; Chang et al., PNAS 2015",
        "suggested_duration_days": 21,
        "difficulty": "moderate",
        "experiment_type": "measurable",
        "hypothesis_template": "Combined morning sunlight + evening blue blockers will reduce sleep onset latency and increase deep sleep %",
        "protocol_template": "10+ min outdoor light within 30 min of waking. Blue-blocking glasses from sunset. Track with Whoop/Eight Sleep.",
        "metrics_measurable": ["sleep_onset_latency", "deep_sleep_pct", "sleep_efficiency"],
        "tags": ["circadian", "light", "sleep"],
        "status": "backlog"
    },
    {
        "id": "trf-12pm-8pm",
        "name": "Time-Restricted Eating (12pm-8pm)",
        "description": "8-hour eating window for metabolic benefits",
        "pillar": "nutrition",
        "evidence_tier": "strong",
        "evidence_summary": "TRF improves insulin sensitivity, reduces inflammation",
        "evidence_citation": "Panda, The Circadian Code; Sutton et al., Cell Metabolism 2018",
        "suggested_duration_days": 28,
        "difficulty": "moderate",
        "experiment_type": "measurable",
        "hypothesis_template": "8-hour eating window (12pm-8pm) will reduce fasting glucose variability and improve time-in-range",
        "protocol_template": "First meal at 12pm, last bite by 8pm. Black coffee/tea/water only before noon. Track via CGM + MacroFactor.",
        "metrics_measurable": ["glucose_variability", "time_in_range", "fasting_glucose"],
        "tags": ["TRF", "fasting", "metabolic"],
        "status": "backlog"
    },
    {
        "id": "eliminate-alcohol-30d",
        "name": "Eliminate Alcohol 30 Days",
        "description": "Complete alcohol elimination to measure sleep and recovery impact",
        "pillar": "discipline",
        "evidence_tier": "strong",
        "evidence_summary": "Even moderate alcohol disrupts REM sleep, suppresses HRV, impairs recovery for 3+ days",
        "evidence_citation": "Attia, Outlive; Huberman Lab; Walker, Why We Sleep",
        "suggested_duration_days": 30,
        "difficulty": "moderate",
        "experiment_type": "measurable",
        "hypothesis_template": "30 days zero alcohol will improve REM % by >10% and HRV by >5ms",
        "protocol_template": "Zero alcohol for 30 days. No exceptions. Track REM %, HRV, recovery score via Whoop.",
        "metrics_measurable": ["rem_pct", "hrv", "recovery_score", "sleep_efficiency"],
        "tags": ["alcohol", "sleep", "recovery"],
        "status": "backlog"
    }
]


def main():
    print("\n═══ Add 6 New Experiments ═══\n")

    with open(LIB_PATH, "r") as f:
        lib = json.load(f)

    existing_ids = {e["id"] for e in lib.get("experiments", [])}
    added = 0

    for exp in NEW_EXPERIMENTS:
        if exp["id"] in existing_ids:
            print(f"  · {exp['id']}: already exists")
        else:
            lib["experiments"].append(exp)
            existing_ids.add(exp["id"])
            added += 1
            print(f"  ✓ {exp['id']}: added ({exp['name']})")

    lib["updated"] = "2026-03-26"

    with open(LIB_PATH, "w") as f:
        json.dump(lib, f, indent=2, ensure_ascii=False)

    total = len(lib["experiments"])
    print(f"\nAdded {added} experiments. Library now has {total} total.")
    print(f"\nDeploy:")
    print(f"  aws s3 cp config/experiment_library.json s3://matthew-life-platform/config/experiment_library.json --region us-west-2")
    print(f"  aws s3 cp config/experiment_library.json s3://matthew-life-platform/site/config/experiment_library.json --region us-west-2")


if __name__ == "__main__":
    main()
