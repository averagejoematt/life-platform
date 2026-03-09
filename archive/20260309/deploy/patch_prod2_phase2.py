#!/usr/bin/env python3
"""
PROD-2 Phase 2: S3 path prefixing
Scope: raw/ and config/ paths only (dashboard/buddy paths excluded — no CloudFront risk).

What this patches:
  Ingestion Lambdas (raw/ writes):
    health_auto_export_lambda.py  — raw/cgm_readings/, raw/blood_pressure/,
                                    raw/state_of_mind/, raw/workouts/,
                                    raw/health_auto_export/
    whoop_lambda.py               — raw/whoop/
    strava_lambda.py              — raw/strava/
    garmin_lambda.py              — raw/garmin/
    macrofactor_lambda.py         — raw/macrofactor*/
    apple_health_lambda.py        — raw/apple_health/
    withings_lambda.py            — raw/withings/
    eightsleep_lambda.py          — raw/eightsleep/

  MCP tools (raw/ reads):
    mcp/tools_cgm.py              — raw/cgm_readings/ reads + paginator prefix

  Config paths:
    lambdas/board_loader.py       — config/board_of_directors.json
    lambdas/character_engine.py   — config/character_sheet.json
    mcp/tools_board.py            — BOARD_S3_KEY hardcode
    mcp/tools_character.py        — CS_CONFIG_KEY hardcode + hardcoded S3_BUCKET

Run from project root:
  python3 deploy/patch_prod2_phase2.py [--dry-run]
"""

import re
import sys
import os

DRY_RUN = "--dry-run" in sys.argv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAMBDAS = os.path.join(BASE, "lambdas")
MCP     = os.path.join(BASE, "mcp")

changes_made = 0
errors = []


def patch_file(filepath, replacements, description=""):
    """Apply a list of (old_str, new_str) replacements to a file."""
    global changes_made
    try:
        with open(filepath, "r") as f:
            content = f.read()
        original = content
        for old, new in replacements:
            if old not in content:
                errors.append(f"MISS: {os.path.basename(filepath)}: pattern not found: {repr(old[:60])}")
                continue
            content = content.replace(old, new)
        if content == original:
            print(f"  ⚪ {os.path.basename(filepath)} — no changes")
            return
        count = sum(1 for o, n in replacements if o in original)
        if not DRY_RUN:
            with open(filepath, "w") as f:
                f.write(content)
        label = "[DRY RUN] " if DRY_RUN else ""
        print(f"  ✅ {label}{os.path.basename(filepath)} — {count} replacement(s){' (' + description + ')' if description else ''}")
        changes_made += 1
    except FileNotFoundError:
        errors.append(f"MISSING FILE: {filepath}")
        print(f"  ❌ {filepath} not found")


print("=== PROD-2 Phase 2: S3 path prefix patch ===")
print(f"Mode: {'DRY RUN' if DRY_RUN else 'LIVE'}")
print()

# ══════════════════════════════════════════════════════════════
# INGESTION LAMBDAS — raw/ write paths
# ══════════════════════════════════════════════════════════════

print("--- Ingestion Lambdas (raw/ writes) ---")

# health_auto_export_lambda.py
# 5 raw/ path patterns — all use f-strings with date components
patch_file(
    os.path.join(LAMBDAS, "health_auto_export_lambda.py"),
    [
        (
            'f"raw/cgm_readings/{date_str[:4]}/{date_str[5:7]}/{date_str[8:10]}.json"',
            'f"raw/{USER_ID}/cgm_readings/{date_str[:4]}/{date_str[5:7]}/{date_str[8:10]}.json"',
        ),
        (
            'f"raw/blood_pressure/{date_str[:4]}/{date_str[5:7]}/{date_str[8:10]}.json"',
            'f"raw/{USER_ID}/blood_pressure/{date_str[:4]}/{date_str[5:7]}/{date_str[8:10]}.json"',
        ),
        (
            'f"raw/state_of_mind/{date_str[:4]}/{date_str[5:7]}/{date_str[8:10]}.json"',
            'f"raw/{USER_ID}/state_of_mind/{date_str[:4]}/{date_str[5:7]}/{date_str[8:10]}.json"',
        ),
        (
            'f"raw/workouts/{date_str[:4]}/{date_str[5:7]}/{date_str[8:10]}.json"',
            'f"raw/{USER_ID}/workouts/{date_str[:4]}/{date_str[5:7]}/{date_str[8:10]}.json"',
        ),
        (
            '        f"raw/health_auto_export/"',
            '        f"raw/{USER_ID}/health_auto_export/"',
        ),
    ],
    "cgm_readings, blood_pressure, state_of_mind, workouts, health_auto_export",
)

# whoop_lambda.py — 4 raw/whoop/ paths (via _s3_put helper)
patch_file(
    os.path.join(LAMBDAS, "whoop_lambda.py"),
    [
        (
            '_s3_put(s3_client, f"raw/whoop/recovery/{year}/{month}/{day}.json"',
            '_s3_put(s3_client, f"raw/{USER_ID}/whoop/recovery/{year}/{month}/{day}.json"',
        ),
        (
            '_s3_put(s3_client, f"raw/whoop/sleep/{year}/{month}/{day}.json"',
            '_s3_put(s3_client, f"raw/{USER_ID}/whoop/sleep/{year}/{month}/{day}.json"',
        ),
        (
            '_s3_put(s3_client, f"raw/whoop/cycle/{year}/{month}/{day}.json"',
            '_s3_put(s3_client, f"raw/{USER_ID}/whoop/cycle/{year}/{month}/{day}.json"',
        ),
        (
            '_s3_put(s3_client, f"raw/whoop/workout/{year}/{month}/{day}/{wid}.json"',
            '_s3_put(s3_client, f"raw/{USER_ID}/whoop/workout/{year}/{month}/{day}/{wid}.json"',
        ),
    ],
    "recovery, sleep, cycle, workout",
)

# strava_lambda.py
patch_file(
    os.path.join(LAMBDAS, "strava_lambda.py"),
    [
        (
            'f"raw/strava/activities/{date_str[:4]}/{date_str[5:7]}/{date_str[8:10]}.json"',
            'f"raw/{USER_ID}/strava/activities/{date_str[:4]}/{date_str[5:7]}/{date_str[8:10]}.json"',
        ),
    ],
)

# garmin_lambda.py
patch_file(
    os.path.join(LAMBDAS, "garmin_lambda.py"),
    [
        (
            'f"raw/garmin/{target_date[:4]}/{target_date[5:7]}/{target_date[8:10]}.json"',
            'f"raw/{USER_ID}/garmin/{target_date[:4]}/{target_date[5:7]}/{target_date[8:10]}.json"',
        ),
    ],
)

# macrofactor_lambda.py
patch_file(
    os.path.join(LAMBDAS, "macrofactor_lambda.py"),
    [
        (
            'f"raw/macrofactor{sub}/{now.strftime(\'%Y/%m\')}/{fname}"',
            'f"raw/{USER_ID}/macrofactor{sub}/{now.strftime(\'%Y/%m\')}/{fname}"',
        ),
    ],
)

# apple_health_lambda.py
patch_file(
    os.path.join(LAMBDAS, "apple_health_lambda.py"),
    [
        (
            'f"raw/apple_health/{year}/{month}/{day_num}.json.gz"',
            'f"raw/{USER_ID}/apple_health/{year}/{month}/{day_num}.json.gz"',
        ),
    ],
)

# withings_lambda.py
patch_file(
    os.path.join(LAMBDAS, "withings_lambda.py"),
    [
        (
            'f"raw/withings/measurements/{date_str[:4]}/{date_str[5:7]}/{date_str[8:10]}.json"',
            'f"raw/{USER_ID}/withings/measurements/{date_str[:4]}/{date_str[5:7]}/{date_str[8:10]}.json"',
        ),
    ],
)

# eightsleep_lambda.py
patch_file(
    os.path.join(LAMBDAS, "eightsleep_lambda.py"),
    [
        (
            'f"raw/eightsleep/{wake_date[:4]}/{wake_date[5:7]}/{wake_date[8:10]}.json"',
            'f"raw/{USER_ID}/eightsleep/{wake_date[:4]}/{wake_date[5:7]}/{wake_date[8:10]}.json"',
        ),
    ],
)

print()
print("--- MCP tools (raw/ reads) ---")

# tools_cgm.py — 3 raw/cgm_readings/ references
# The file imports USER_ID from mcp.config at line 12
patch_file(
    os.path.join(MCP, "tools_cgm.py"),
    [
        (
            'key = f"raw/cgm_readings/{y}/{m}/{d}.json"',
            'key = f"raw/{USER_ID}/cgm_readings/{y}/{m}/{d}.json"',
        ),
        (
            'Prefix=f"raw/cgm_readings/{prefix_year}"',
            'Prefix=f"raw/{USER_ID}/cgm_readings/{prefix_year}"',
        ),
        (
            'parts = key.replace("raw/cgm_readings/", "").replace(".json", "").split("/")',
            'parts = key.replace(f"raw/{USER_ID}/cgm_readings/", "").replace(".json", "").split("/")',
        ),
    ],
    "read key, paginator prefix, key parser",
)

print()
print("--- Config paths ---")

# board_loader.py — add user_id param (backward-compatible default "matthew")
patch_file(
    os.path.join(LAMBDAS, "board_loader.py"),
    [
        (
            'def load_board(s3_client, bucket, force_refresh=False):',
            'def load_board(s3_client, bucket, force_refresh=False, user_id="matthew"):',
        ),
        (
            'resp = s3_client.get_object(Bucket=bucket, Key="config/board_of_directors.json")',
            'resp = s3_client.get_object(Bucket=bucket, Key=f"config/{user_id}/board_of_directors.json")',
        ),
    ],
    "add user_id param, prefix config key",
)

# character_engine.py — add user_id param (backward-compatible default "matthew")
patch_file(
    os.path.join(LAMBDAS, "character_engine.py"),
    [
        (
            'def load_character_config(s3_client, bucket, force_refresh=False):',
            'def load_character_config(s3_client, bucket, force_refresh=False, user_id="matthew"):',
        ),
        (
            'resp = s3_client.get_object(Bucket=bucket, Key="config/character_sheet.json")',
            'resp = s3_client.get_object(Bucket=bucket, Key=f"config/{user_id}/character_sheet.json")',
        ),
    ],
    "add user_id param, prefix config key",
)

# tools_board.py — import USER_ID, make BOARD_S3_KEY dynamic
patch_file(
    os.path.join(MCP, "tools_board.py"),
    [
        (
            'from mcp.config import s3_client, S3_BUCKET, logger',
            'from mcp.config import s3_client, S3_BUCKET, USER_ID, logger',
        ),
        (
            'BOARD_S3_KEY = "config/board_of_directors.json"',
            'BOARD_S3_KEY = f"config/{USER_ID}/board_of_directors.json"',
        ),
    ],
    "import USER_ID, dynamic config key",
)

# tools_character.py — fix hardcoded S3_BUCKET + make CS_CONFIG_KEY dynamic
# The Phase 4 section mid-file has: import time; import boto3; S3_BUCKET = hardcoded; CS_CONFIG_KEY
# We add `import os as _os` to that section, then use env vars for both values.
tc_path = os.path.join(MCP, "tools_character.py")

patch_file(
    tc_path,
    [
        # Extend the Phase 4 import block: add `import os as _os` after boto3
        (
            'import time\nimport boto3\n\nREWARDS_PK = USER_PREFIX + "rewards"\nS3_BUCKET = "matthew-life-platform"\nCS_CONFIG_KEY = "config/character_sheet.json"',
            'import time\nimport boto3\nimport os as _os\n\nREWARDS_PK   = USER_PREFIX + "rewards"\nS3_BUCKET    = _os.environ.get("S3_BUCKET", "matthew-life-platform")  # PROD-2 Phase 2\n_CS_USER_ID  = _os.environ.get("USER_ID", "matthew")                  # PROD-2 Phase 2\nCS_CONFIG_KEY = f"config/{_CS_USER_ID}/character_sheet.json"          # PROD-2 Phase 2',
        ),
    ],
    "fix hardcoded S3_BUCKET, dynamic CS_CONFIG_KEY",
)

print()
print("=== Summary ===")
print(f"  Files changed: {changes_made}")
if errors:
    print(f"  ⚠️  Misses/errors ({len(errors)}):")
    for e in errors:
        print(f"    {e}")
else:
    print(f"  ✅ No misses")

if DRY_RUN:
    print()
    print("DRY RUN — no files written. Re-run without --dry-run to apply.")
else:
    print()
    print("Next steps:")
    print("  1. Run the S3 migration: bash deploy/migrate_s3_prod2_phase2.sh")
    print("     (copies existing raw/ → raw/matthew/ and config/*.json → config/matthew/)")
    print("  2. Deploy changed Lambdas: bash deploy/deploy_prod2_phase2.sh")
    print("  3. Verify: aws s3 ls s3://matthew-life-platform/raw/matthew/ --recursive | head -20")
    print("  4. After 7+ days of verified operation, old paths can be deleted")
