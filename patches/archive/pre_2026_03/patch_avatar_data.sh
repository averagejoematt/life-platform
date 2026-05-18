#!/bin/bash
# Quick patch: Add avatar data to existing dashboard + buddy data.json
# Does NOT trigger email — just patches the S3 JSON files
# Run once, then tomorrow's Daily Brief takes over

set -e

echo "=== Patching data.json with avatar data ==="

python3 << 'PYEOF'
import boto3, json

s3 = boto3.client("s3", region_name="us-west-2")
ddb = boto3.resource("dynamodb", region_name="us-west-2")
table = ddb.Table("life-platform")
BUCKET = "matthew-life-platform"

# --- Get latest character sheet ---
resp = table.query(
    KeyConditionExpression="pk = :pk",
    ExpressionAttributeValues={":pk": "USER#matthew#SOURCE#character_sheet"},
    ScanIndexForward=False,
    Limit=1,
)
cs = resp["Items"][0] if resp.get("Items") else None
if not cs:
    print("[ERROR] No character sheet found")
    exit(1)

cs_level = int(cs.get("character_level", 1))
cs_tier = cs.get("character_tier", "Foundation")
cs_emoji = cs.get("character_tier_emoji", "\U0001f528")
cs_xp = int(cs.get("character_xp", 0))
print(f"[INFO] Character Sheet: Level {cs_level}, {cs_tier}, {cs_xp} XP")

# --- Get latest weight (30-day lookback) ---
from datetime import datetime, timedelta, timezone
today = datetime.now(timezone.utc).date()
avatar_weight = None
for lookback in [7, 14, 30]:
    start = (today - timedelta(days=lookback)).isoformat()
    w_resp = table.query(
        KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
        ExpressionAttributeValues={
            ":pk": "USER#matthew#SOURCE#withings",
            ":s": f"DATE#{start}",
            ":e": f"DATE#{today.isoformat()}",
        },
        ScanIndexForward=False,
    )
    for item in w_resp.get("Items", []):
        wt = item.get("weight_lbs")
        if wt:
            avatar_weight = float(str(wt))
            break
    if avatar_weight:
        break

print(f"[INFO] Avatar weight: {avatar_weight}")

# --- Build avatar data ---
start_w, goal_w = 302, 185
cw = avatar_weight or start_w
composition_score = max(0, min(100, ((start_w - cw) / (start_w - goal_w)) * 100))
if composition_score >= 75:
    body_frame = 3
elif composition_score >= 36:
    body_frame = 2
else:
    body_frame = 1

pillar_names = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]
badges = {}
for pn in pillar_names:
    pd = cs.get(f"pillar_{pn}", {})
    lvl = int(pd.get("level", 1)) if pd else 1
    if lvl >= 61:
        badges[pn] = "bright"
    elif lvl >= 41:
        badges[pn] = "dim"
    else:
        badges[pn] = "hidden"

raw_effects = cs.get("active_effects", [])
effect_names = [e.get("name", "").lower().replace(" ", "_") for e in raw_effects if e.get("name")]

avatar = {
    "tier": cs_tier.lower(),
    "body_frame": body_frame,
    "composition_score": round(composition_score, 1),
    "badges": badges,
    "effects": effect_names,
    "expressions": {"eyes": "normal", "posture": "normal", "skin_tone": "normal", "ground": "normal"},
    "elite_crown": cs_level >= 81,
    "alignment_ring": False,
}
print(f"[INFO] Avatar: {avatar['tier']}, frame {body_frame}, {composition_score:.1f}% to goal")

# --- Build character_sheet for dashboard ---
cs_dashboard = {
    "level": cs_level,
    "tier": cs_tier,
    "tier_emoji": cs_emoji,
    "xp": cs_xp,
    "pillars": {
        pn: {
            "level": int((cs.get(f"pillar_{pn}") or {}).get("level", 1)),
            "tier": (cs.get(f"pillar_{pn}") or {}).get("tier", "Foundation"),
            "raw_score": float((cs.get(f"pillar_{pn}") or {}).get("raw_score", 0) or 0),
        }
        for pn in pillar_names
    },
    "events": [
        {k: (int(v) if k in ("old_level", "new_level") else v)
         for k, v in e.items()}
        for e in cs.get("level_events", [])
    ],
    "effects": [{"name": e.get("name"), "emoji": e.get("emoji")} for e in raw_effects],
}

# --- Patch dashboard/data.json ---
obj = s3.get_object(Bucket=BUCKET, Key="dashboard/data.json")
dash = json.loads(obj["Body"].read())
dash["character_sheet"] = cs_dashboard
dash["avatar"] = avatar
s3.put_object(
    Bucket=BUCKET, Key="dashboard/data.json",
    Body=json.dumps(dash, default=str),
    ContentType="application/json", CacheControl="max-age=300",
)
print("[OK] dashboard/data.json patched")

# --- Patch buddy/data.json ---
try:
    obj2 = s3.get_object(Bucket=BUCKET, Key="buddy/data.json")
    buddy = json.loads(obj2["Body"].read())
    buddy["character_sheet"] = {
        "level": cs_level, "tier": cs_tier,
        "tier_emoji": cs_emoji, "events": cs_dashboard["events"],
    }
    buddy["avatar"] = avatar
    s3.put_object(
        Bucket=BUCKET, Key="buddy/data.json",
        Body=json.dumps(buddy, default=str),
        ContentType="application/json", CacheControl="max-age=300",
    )
    print("[OK] buddy/data.json patched")
except Exception as e:
    print(f"[WARN] buddy/data.json patch failed: {e}")

print("\n=== Done — refresh dash.averagejoematt.com ===")
PYEOF
