#!/usr/bin/env python3
"""v4_build_data_sources.py — generate site/data/data_sources.json from the registry (#498).

The old file self-labeled "single source of truth for all data sources" while
being a stale March-era hand copy: missing hevy, ids that matched no DDB
partition (applehealth, mf_workouts), HAE sub-datatypes listed as sources.
Now the catalogue derives from lambdas/source_registry.py (ingestion sources,
with the review's posture verdict) plus the clinical/archive partitions that
aren't pipeline sources but are real data. Runs in deploy/sync_site_to_s3.sh
next to v4_build_rss.py — never hand-edit the JSON.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))

from source_registry import catalog_entries  # noqa: E402

# Non-pipeline partitions that belong in the public catalogue: clinical truths
# (episodic, no cron) and the one archive. These aren't SOURCE_REGISTRY entries
# because they have no ingestion pipe to classify — but they are real data.
CLINICAL_AND_ARCHIVE = [
    {
        "id": "labs",
        "name": "Blood labs",
        "category": "Clinical",
        "metrics": "Blood biomarkers (episodic panels)",
        "method": "Manual entry from lab PDFs",
        "posture": "load-bearing",
    },
    {
        "id": "dexa",
        "name": "DEXA",
        "category": "Clinical",
        "metrics": "Body-composition scans",
        "method": "Manual entry per scan",
        "posture": "load-bearing",
    },
    {
        "id": "genome",
        "name": "Genome",
        "category": "Clinical",
        "metrics": "SNP clinical interpretations",
        "method": "One-time import",
        "posture": "load-bearing",
    },
    {
        "id": "state_of_mind",
        "name": "State of Mind",
        "category": "Inputs",
        "metrics": "Affect self-reports (Apple State of Mind)",
        "method": "Health Auto Export webhook",
        "posture": "portfolio",
    },
    {
        "id": "macrofactor_workouts",
        "name": "MacroFactor workouts",
        "category": "Archive",
        "metrics": "Historical strength log (pre-Hevy)",
        "method": "Frozen archive — no writer",
        "posture": "archive",
    },
    {
        "id": "chronicling",
        "name": "Chronicling",
        "category": "Archive",
        "metrics": "Pre-platform habit history",
        "method": "Frozen archive — no writer",
        "posture": "archive",
    },
]


def build() -> dict:
    sources = catalog_entries() + CLINICAL_AND_ARCHIVE
    return {
        "_meta": {
            "generated_by": "scripts/v4_build_data_sources.py — from lambdas/source_registry.py (#498); never hand-edit",
            "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "count": len(sources),
        },
        "sources": sources,
    }


def main():
    out = ROOT / "site" / "data" / "data_sources.json"
    payload = build()
    # Idempotent modulo the date stamp: only rewrite when content actually changed,
    # so a no-op sync doesn't churn the file.
    if out.exists():
        try:
            current = json.loads(out.read_text())
            if current.get("sources") == payload["sources"]:
                print(f"data_sources.json unchanged ({len(payload['sources'])} sources)")
                return
        except (json.JSONDecodeError, OSError):
            pass
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(f"data_sources.json regenerated: {len(payload['sources'])} sources")


if __name__ == "__main__":
    main()
