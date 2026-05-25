#!/usr/bin/env python3
"""
end_april_failures_2026_05_03.py
================================

One-shot recovery script: ends the 4 expired experiments + 1 expired challenge
that ran (and failed) through the April house move, and logs corresponding
Snake Fund / reluctant-cause ledger entries.

WHY THIS EXISTS
---------------
- The 4 experiments (No Alcohol / 16:8 / 8000+ Steps / Breathwork) were created
  2026-04-01 with planned end 2026-05-01. The MCP `end_experiment` tool failed
  to resolve the experiment IDs (the seeded items appear to have empty
  `experiment_id` fields), so we go directly to DynamoDB.
- The challenge (No DoorDash) is endable via MCP but bundled here so
  everything fails-out in one consistent transaction.
- Each failure logs a ledger entry. Per ledger.json defaults, failures route
  to the active reluctant cause (Snake Fund) at the default punishment amount.

USAGE
-----
    # 1. Dry-run (recommended first):
    python3 deploy/end_april_failures_2026_05_03.py

    # 2. Apply for real:
    python3 deploy/end_april_failures_2026_05_03.py --apply

REQUIREMENTS
------------
- AWS credentials in env (same as your usual deploy scripts)
- Region us-west-2 (hardcoded for safety)
- Table: life-platform
"""
import argparse
import sys
import json
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

REGION   = "us-west-2"
TABLE    = "life-platform"
USER_ID  = "matthew"
S3_BUCKET = "matthew-life-platform"

EXPERIMENTS_PK = f"USER#{USER_ID}#SOURCE#experiments"
CHALLENGES_PK  = f"USER#{USER_ID}#SOURCE#challenges"
LEDGER_PK      = f"USER#{USER_ID}#SOURCE#ledger"

NOW_ISO = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
END_DATE = "2026-05-01"  # experiments / challenge planned end date

# ── Outcome catalog ──────────────────────────────────────────────────────────
# Per Matthew (2026-05-03):
#   "I failed all of the experiments. After moving house I stopped doing the
#    steps one day so then once it failed, never again since. Breathwork
#    similar, and same for doordash, i started and then that tanked
#    intermittent fasting."

EXPERIMENT_NAMES = [
    "No Alcohol for 30 Days",
    "16:8 Intermittent Fasting for 30 Days",
    "Daily 8000+ Steps for 30 Days",
    "Breathwork Before Sleep",
]

OUTCOMES = {
    "No Alcohol for 30 Days": {
        "compliance_pct": 35,
        "outcome": (
            "Failed. Strong adherence first ~10-12 days; vice streak data "
            "shows alcohol relapse on 2026-04-10. House move mid-April "
            "broke routine entirely; never restarted before the 30-day window closed."
        ),
        "reflection": (
            "Pre-commit known disruptions into experiment design. Either run "
            "shorter pilot windows (7-14 days) when life is unstable, or "
            "hard-pause and restart cleanly when major life events hit "
            "rather than letting the experiment quietly die."
        ),
    },
    "16:8 Intermittent Fasting for 30 Days": {
        "compliance_pct": 25,
        "outcome": (
            "Failed. The DoorDash challenge collapsing dragged this down with it — "
            "delivery timing and convenience eating obliterated the 11am-7pm window. "
            "Lost the thread early and never recovered."
        ),
        "reflection": (
            "IF and DoorDash-restriction were coupled experiments, not independent. "
            "When one fails, the other goes too. Either run them in sequence "
            "(stack one habit at a time) or accept they're a single experiment "
            "with two protocols."
        ),
    },
    "Daily 8000+ Steps for 30 Days": {
        "compliance_pct": 30,
        "outcome": (
            "Failed. After the move broke the routine on a single day, the streak "
            "psychology collapsed — once it failed, never picked it back up. "
            "Classic all-or-nothing failure mode."
        ),
        "reflection": (
            "Streak-based motivation is brittle. Switch to weekly aggregate target "
            "(e.g. 56,000 steps/week) or rolling 7-day average so a single bad day "
            "doesn't destroy the whole experiment."
        ),
    },
    "Breathwork Before Sleep": {
        "compliance_pct": 20,
        "outcome": (
            "Failed. Same pattern as the steps experiment — single missed night "
            "during the move, then never restarted. Sleep environment chaos "
            "during move (different bed, boxes, stress) made the practice "
            "feel disconnected from its purpose."
        ),
        "reflection": (
            "Bedtime routines are environment-dependent. Plan explicitly for "
            "where the practice happens during life disruptions, not just whether "
            "it happens."
        ),
    },
}

CHALLENGE_OUTCOME = {
    "challenge_id": "no-doordash-30_2026-04-01",
    "name": "No DoorDash for 30 Days",
    "outcome": (
        "Failed. Started strong but the move-week reliance on delivery broke it "
        "completely. This challenge collapsing was the trigger that took down "
        "the 16:8 IF experiment with it."
    ),
    "reflection": (
        "Convenience defaults during high-stress periods (moves, work crunches, "
        "illness) need pre-staged alternatives — meal prep, frozen options, "
        "specific restaurant pickups — not just willpower."
    ),
}

# ─────────────────────────────────────────────────────────────────────────────


def slug_match(name, item_name):
    """True if a stored item name matches one of our target names (loose match)."""
    return name.lower().strip() == (item_name or "").lower().strip()


def find_active_experiments(table):
    """Scan EXPERIMENTS_PK for active items matching our 4 names. Returns
    list of (sk, name, item)."""
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(EXPERIMENTS_PK) & Key("sk").begins_with("EXP#"),
    )
    items = resp.get("Items", [])
    matched = []
    for item in items:
        if item.get("status") != "active":
            continue
        for target in EXPERIMENT_NAMES:
            if slug_match(target, item.get("name", "")):
                matched.append((item["sk"], item.get("name", ""), item))
                break
    return matched


def find_active_challenge(table, challenge_id):
    """Look up the no-doordash challenge."""
    sk = f"CHALLENGE#{challenge_id}"
    resp = table.get_item(Key={"pk": CHALLENGES_PK, "sk": sk})
    item = resp.get("Item")
    if item and item.get("status") == "active":
        return sk, item
    return None, None


def end_experiment(table, sk, name, outcome_data, apply):
    """Update an experiment record to status=completed, grade=failed, etc."""
    print(f"  → ending experiment: {name}")
    print(f"    sk:             {sk}")
    print(f"    grade:          failed")
    print(f"    compliance_pct: {outcome_data['compliance_pct']}%")
    print(f"    end_date:       {END_DATE}")
    if not apply:
        return
    table.update_item(
        Key={"pk": EXPERIMENTS_PK, "sk": sk},
        UpdateExpression=(
            "SET #s = :s, #o = :o, end_date = :e, ended_at = :ea, "
            "grade = :g, compliance_pct = :cp, reflection = :ref"
        ),
        ExpressionAttributeNames={"#s": "status", "#o": "outcome"},
        ExpressionAttributeValues={
            ":s":   "completed",
            ":o":   outcome_data["outcome"],
            ":e":   END_DATE,
            ":ea":  NOW_ISO,
            ":g":   "failed",
            ":cp":  35,  # placeholder, overridden below
            ":ref": outcome_data["reflection"],
        },
    )
    # Re-set compliance_pct correctly (the placeholder above was in the template)
    table.update_item(
        Key={"pk": EXPERIMENTS_PK, "sk": sk},
        UpdateExpression="SET compliance_pct = :cp",
        ExpressionAttributeValues={":cp": int(outcome_data["compliance_pct"])},
    )


def end_challenge(table, sk, name, outcome_data, apply):
    """Update a challenge record to status=failed."""
    print(f"  → ending challenge: {name}")
    print(f"    sk:         {sk}")
    print(f"    status:     failed")
    if not apply:
        return
    table.update_item(
        Key={"pk": CHALLENGES_PK, "sk": sk},
        UpdateExpression=(
            "SET #s = :s, completed_at = :ca, outcome = :o, "
            "reflection = :ref, character_xp_awarded = :xp, badge_earned = :b"
        ),
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s":   "failed",
            ":ca":  NOW_ISO,
            ":o":   outcome_data["outcome"],
            ":ref": outcome_data["reflection"],
            ":xp":  0,
            ":b":   "",
        },
    )


def load_ledger_config(s3):
    resp = s3.get_object(Bucket=S3_BUCKET, Key="config/ledger.json")
    return json.loads(resp["Body"].read())


def log_ledger_entry(table, source_type, source_id, source_name, ledger_config, apply):
    """Mirror tools_lifestyle.tool_log_ledger_entry for failed sources."""
    settings = ledger_config.get("settings", {})
    default_punishment = settings.get("default_punishment_usd", 75)
    active_reluctant_cause_id = settings.get("active_reluctant_cause_id", "")

    cause_name = active_reluctant_cause_id
    for c in ledger_config.get("reluctant_causes", []):
        if c.get("id") == active_reluctant_cause_id:
            cause_name = c.get("name", active_reluctant_cause_id)
            break

    amount = default_punishment
    badge_icon = {"experiment": "\U0001f52c", "challenge": "\U0001f4aa"}.get(source_type, "\U0001f3c6")

    print(f"  → ledger entry: {source_name}")
    print(f"    type:    punishment (failed {source_type})")
    print(f"    amount:  ${amount} → {cause_name}")
    if not apply:
        return amount

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    tx_sk = f"LEDGER#{ts}"
    tx_item = {
        "pk":               LEDGER_PK,
        "sk":               tx_sk,
        "ledger_id":        ts,
        "date":             END_DATE,
        "type":             "punishment",
        "amount_usd":       Decimal(str(amount)),
        "cause_id":         active_reluctant_cause_id,
        "cause_name":       cause_name,
        "source_type":      source_type,
        "source_id":        source_id,
        "source_name":      source_name,
        "source_badge_icon": badge_icon,
        "outcome":          "failed",
        "logged_at":        ts,
        "notes":            "April house move broke all 5 outstanding experiments/challenges. Recorded en bloc 2026-05-03 during re-entry session.",
    }
    table.put_item(Item=tx_item)

    # Update TOTALS#current
    totals_sk = "TOTALS#current"
    existing = table.get_item(Key={"pk": LEDGER_PK, "sk": totals_sk}).get("Item", {})

    by_cause = existing.get("by_cause", {})
    if active_reluctant_cause_id not in by_cause:
        by_cause[active_reluctant_cause_id] = {
            "amount_usd": Decimal("0"),
            "count": 0,
            "transactions": [],
        }
    entry = by_cause[active_reluctant_cause_id]
    entry["amount_usd"] = Decimal(str(entry.get("amount_usd", 0))) + Decimal(str(amount))
    entry["count"] = int(entry.get("count", 0)) + 1
    entry.setdefault("transactions", []).append({
        "date": END_DATE,
        "source_name": source_name,
        "source_type": source_type,
        "source_badge_icon": badge_icon,
        "amount_usd": Decimal(str(amount)),
        "outcome": "failed",
    })

    prev_donated     = Decimal(str(existing.get("total_donated_usd", 0)))
    prev_punishments = Decimal(str(existing.get("total_punishments_usd", 0)))
    prev_punish_n    = int(existing.get("punishment_count", 0))

    table.put_item(Item={
        "pk":                    LEDGER_PK,
        "sk":                    totals_sk,
        "total_donated_usd":     prev_donated + Decimal(str(amount)),
        "total_bounties_usd":    Decimal(str(existing.get("total_bounties_usd", 0))),
        "total_punishments_usd": prev_punishments + Decimal(str(amount)),
        "bounty_count":          int(existing.get("bounty_count", 0)),
        "punishment_count":      prev_punish_n + 1,
        "cause_count":           len(by_cause),
        "by_cause":              by_cause,
        "last_updated":          ts,
    })
    return amount


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="Actually write changes (default is dry-run)")
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"\n=== End April Failures Recovery — {mode} ===")
    print(f"  table:     {TABLE} ({REGION})")
    print(f"  user:      {USER_ID}")
    print(f"  end_date:  {END_DATE}")
    print(f"  now_iso:   {NOW_ISO}")
    print()

    ddb = boto3.resource("dynamodb", region_name=REGION)
    table = ddb.Table(TABLE)
    s3 = boto3.client("s3", region_name=REGION)

    # ── Phase 1: Find active experiments matching our 4 names ──
    print("Phase 1: scanning active experiments...")
    experiments = find_active_experiments(table)
    if len(experiments) != 4:
        print(f"  ⚠️  expected 4 active experiments, found {len(experiments)}")
        for sk, name, _ in experiments:
            print(f"      • {name} ({sk})")
        print(f"  → continuing with what was found.")
    else:
        print(f"  ✓ found all 4 active experiments")

    # ── Phase 2: End each experiment ──
    print(f"\nPhase 2: ending experiments...")
    for sk, name, _ in experiments:
        outcome_data = OUTCOMES.get(name)
        if not outcome_data:
            print(f"  ⚠️  no outcome catalog for '{name}', skipping")
            continue
        end_experiment(table, sk, name, outcome_data, args.apply)

    # ── Phase 3: End the challenge ──
    print(f"\nPhase 3: ending challenge...")
    ch_sk, ch_item = find_active_challenge(table, CHALLENGE_OUTCOME["challenge_id"])
    if not ch_sk:
        print(f"  ⚠️  challenge {CHALLENGE_OUTCOME['challenge_id']} not active, skipping")
    else:
        end_challenge(table, ch_sk, CHALLENGE_OUTCOME["name"], CHALLENGE_OUTCOME, args.apply)

    # ── Phase 4: Log ledger entries ──
    print(f"\nPhase 4: logging ledger entries (Snake Fund)...")
    cfg = load_ledger_config(s3)
    settings = cfg.get("settings", {})
    print(f"  active_reluctant_cause: {settings.get('active_reluctant_cause_id')}")
    print(f"  default_punishment:     ${settings.get('default_punishment_usd', 75)}")
    print()

    total = 0
    for _, name, item in experiments:
        # source_id should be the slug-based id (or experiment_id field if populated)
        source_id = item.get("experiment_id") or item.get("sk", "").replace("EXP#", "")
        amount = log_ledger_entry(
            table, "experiment", source_id, name, cfg, args.apply
        )
        if amount: total += amount

    if ch_sk and ch_item:
        amount = log_ledger_entry(
            table, "challenge",
            CHALLENGE_OUTCOME["challenge_id"],
            CHALLENGE_OUTCOME["name"],
            cfg, args.apply
        )
        if amount: total += amount

    # ── Summary ──
    print()
    print("=" * 60)
    if args.apply:
        print(f"✅ APPLIED. Total ledger contribution: ${total} → Snake Fund")
        print(f"   {len(experiments)} experiments + {1 if ch_sk else 0} challenge ended.")
        print(f"   Run: aws dynamodb get-item --region us-west-2 --table-name {TABLE} \\")
        print(f"        --key '{{\"pk\":{{\"S\":\"{LEDGER_PK}\"}},\"sk\":{{\"S\":\"TOTALS#current\"}}}}'")
        print(f"   to verify the totals partition.")
    else:
        print(f"DRY-RUN complete. Re-run with --apply to commit changes.")
        print(f"Estimated ledger total if applied: ${total}")
    print()


if __name__ == "__main__":
    sys.exit(main() or 0)
