#!/usr/bin/env python3
"""
Patch lambdas/site_api_lambda.py: stop returning 503 when character sheet is
not yet computed.

PROBLEM:
    /api/character_stats returns HTTP 503 {"error": "Character sheet not
    computed yet"} when no record exists in DDB. 503 means "Service
    Unavailable" — implies the service is broken. The actual situation is
    "the data doesn't exist yet." This:
      - triggers WAF/CloudFront 5xx alarms
      - skews error budgets
      - shows up as a real failure in visual_qa
      - misrepresents the system state to clients

FIX:
    Return 200 with {"computed": false, "character_stats": null,
    "pillars": null} and a 5-minute cache. Homepage already handles this
    cleanly: it checks `if (cs.level)` (falsy → falls through to vitals
    fallback), and primary character data comes from public_stats.json
    anyway.

ANCHORS:
    Edits one branch in handle_character_stats() at line ~938-939.
    Idempotent — safe to re-run.

DEPLOY:
    Run this script, then redeploy the Lambda (note the source-file arg):
      python3 deploy/patch_character_stats_503_to_200.py
      bash deploy/deploy_lambda.sh life-platform-site-api lambdas/site_api_lambda.py

NOT FIXED HERE:
    This is just one of ~16 "503-for-missing-data" anti-patterns in
    site_api_lambda.py. The other call sites are tracked separately for a
    bulk pass; this script only fixes character_stats because that's the
    one the homepage hits on every page load.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "lambdas" / "site_api_lambda.py"

OLD = '''    if not record:
        return _error(503, "Character sheet not computed yet")

    PILLARS = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]'''

NEW = '''    if not record:
        # Pre-compute / data-not-yet-available is NOT a 5xx situation.
        # Return 200 with computed=false so:
        #   - WAF/CloudFront alarms don't fire on a normal "no data yet" state
        #   - Homepage gauge fallback chain works (cs.level falsy → vitals API)
        #   - Clients can branch on the flag without parsing magic strings
        # 5-min cache: short enough that the first compute lands quickly,
        # long enough that 50k visitors don't hammer DDB.
        return _ok({
            "character_stats": None,
            "pillars": None,
            "computed": False,
            "reason": "Character sheet not yet computed for today or yesterday",
        }, cache_seconds=300)

    PILLARS = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]'''


def main():
    if not TARGET.is_file():
        print(f"ERROR: {TARGET} not found")
        return 1

    src = TARGET.read_text()

    # Idempotency check
    if '"reason": "Character sheet not yet computed for today or yesterday"' in src:
        print("Already patched — no changes made.")
        print()
        print("If the live Lambda still returns 503, you need to deploy:")
        print("    bash deploy/deploy_lambda.sh life-platform-site-api lambdas/site_api_lambda.py")
        return 0

    if OLD not in src:
        print(f"ERROR: Anchor not found in {TARGET}.")
        print(f"       The handle_character_stats() handler may have been modified.")
        print(f"       Look around line 938 for the `if not record:` branch and")
        print(f"       verify it still matches the OLD anchor in this script.")
        return 2

    src = src.replace(OLD, NEW, 1)
    TARGET.write_text(src)
    print(f"Patched {TARGET}")
    print()
    print("Next: redeploy the Lambda (deploy_lambda.sh requires source file as arg 2)")
    print("    bash deploy/deploy_lambda.sh life-platform-site-api lambdas/site_api_lambda.py")
    print()
    print("Then verify (wait ~10s for CloudFront cache to clear):")
    print("    curl -s -o /dev/null -w 'HTTP %{http_code}\\n' \\")
    print("      https://averagejoematt.com/api/character_stats")
    print("    # expect: HTTP 200 (was HTTP 503)")
    print()
    print("Then re-run visual_qa — homepage should pass:")
    print("    python3 tests/visual_qa.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
