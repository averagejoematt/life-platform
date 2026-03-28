#!/usr/bin/env python3
"""
fix_habitify_cdk.py — Add Habitify Lambda to CDK ingestion stack and fix IAM policy.

Changes:
  1. role_policies.py: fix ingestion_habitify() to use life-platform/habitify
     (not ingestion-keys — ADR-014: dedicated secret, not bundled)
  2. ingestion_stack.py: insert Habitify as item 5 after Withings

Run from project root:
  python3 deploy/fix_habitify_cdk.py
"""
from pathlib import Path

ROOT = Path(__file__).parent.parent

# ─────────────────────────────────────────────────────────────────────────────
# 1. role_policies.py — fix secret name
# ─────────────────────────────────────────────────────────────────────────────
rp_path = ROOT / "cdk/stacks/role_policies.py"
rp = rp_path.read_text()

OLD_RP = '''def ingestion_habitify() -> list[iam.PolicyStatement]:
    return _ingestion_base(
        "habitify",
        secret_name="life-platform/ingestion-keys",  # COST-B: bundled 2026-03-10
        s3_prefix="raw/matthew/habitify/*",
    )'''

NEW_RP = '''def ingestion_habitify() -> list[iam.PolicyStatement]:
    # ADR-014: life-platform/habitify has its own dedicated secret (restored 2026-03-10
    # after accidental deletion). NOT bundled in ingestion-keys — keep separate.
    return _ingestion_base(
        "habitify",
        secret_name="life-platform/habitify",
        s3_prefix="raw/matthew/habitify/*",
    )'''

if OLD_RP in rp:
    rp_path.write_text(rp.replace(OLD_RP, NEW_RP, 1))
    print("  ✅ role_policies.py: fixed ingestion_habitify() secret → life-platform/habitify")
elif NEW_RP in rp:
    print("  ℹ️  role_policies.py: already using life-platform/habitify")
else:
    print("  ❌ role_policies.py: could not find ingestion_habitify() block — manual fix needed")


# ─────────────────────────────────────────────────────────────────────────────
# 2. ingestion_stack.py — insert Habitify block after Withings
# ─────────────────────────────────────────────────────────────────────────────
stack_path = ROOT / "cdk/stacks/ingestion_stack.py"
stack = stack_path.read_text()

HABITIFY_BLOCK = '''
        # ── 5. Habitify — 6:15 AM PT daily (same window as Withings)
        # Restored to CDK management after IAM drift incident (2026-03-18).
        # Uses dedicated secret life-platform/habitify per ADR-014.
        create_platform_lambda(self, "HabitifyIngestion",
            function_name="habitify-data-ingestion",
            source_file="lambdas/habitify_lambda.py",
            handler="habitify_lambda.lambda_handler",
            schedule="cron(15 14 * * ? *)",
            timeout_seconds=180, alarm_name="ingestion-error-habitify",
            environment={"HABITIFY_SECRET_NAME": "life-platform/habitify"},
            shared_layer=shared_utils_layer,
            custom_policies=rp.ingestion_habitify(),
            alerts_topic=None, **{k: v for k, v in shared.items() if k != "alerts_topic"})
'''

# Find the anchor: end of Withings block
WITHINGS_ANCHOR = '''            custom_policies=rp.ingestion_withings(), **shared)'''

STRAVA_ANCHOR_VARIANTS = [
    "\n        # ── 5.",
    "\n        # ── 6.",
]

if "habitify-data-ingestion" in stack:
    print("  ℹ️  ingestion_stack.py: Habitify already present")
elif WITHINGS_ANCHOR in stack:
    # Insert Habitify after Withings, renumber subsequent items
    new_stack = stack.replace(
        WITHINGS_ANCHOR + "\n",
        WITHINGS_ANCHOR + "\n" + HABITIFY_BLOCK,
        1,
    )
    # Renumber items after Habitify (5→6, 6→7, ... 15→16)
    # Items currently numbered 5-15 need to become 6-16
    for old_num in range(15, 4, -1):  # go backwards to avoid double-replacement
        new_num = old_num + 1
        old_comment = f"        # ── {old_num}."
        new_comment = f"        # ── {new_num}."
        # Only renumber if it's not the Habitify block we just inserted
        new_stack = new_stack.replace(old_comment, new_comment)

    stack_path.write_text(new_stack)
    print("  ✅ ingestion_stack.py: inserted Habitify as item 5, renumbered 5-15 → 6-16")
else:
    print("  ❌ ingestion_stack.py: could not find Withings anchor — check manually")
    print(f"     Looking for: {repr(WITHINGS_ANCHOR)}")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Update docstring item count (15 → 16 Lambdas)
# ─────────────────────────────────────────────────────────────────────────────
stack = stack_path.read_text()
if "Covers 15 Lambdas" in stack:
    stack_path.write_text(stack.replace("Covers 15 Lambdas", "Covers 16 Lambdas", 1))
    print("  ✅ ingestion_stack.py: updated docstring 15 → 16 Lambdas")

print("""
============================================================
NEXT STEPS:
  1. cd ~/Documents/Claude/life-platform/cdk
  2. source .venv/bin/activate
  3. npx cdk diff LifePlatformIngestion
  4. Review — should show HabitifyIngestion Lambda + updated IAM role
  5. npx cdk deploy LifePlatformIngestion --require-approval never
  6. Verify: aws lambda invoke --function-name habitify-data-ingestion \\
       --region us-west-2 --payload '{}' --no-cli-pager /tmp/h.json && cat /tmp/h.json
============================================================
""")
