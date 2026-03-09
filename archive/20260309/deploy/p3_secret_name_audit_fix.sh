#!/bin/bash
# p3_secret_name_audit_fix.sh — Remove stale SECRET_NAME env var from habitify Lambda
set -euo pipefail
chmod +x "$0"
REGION="us-west-2"

echo "── P3: SECRET_NAME env var audit fix ──"

echo "Current habitify env vars:"
aws lambda get-function-configuration \
    --function-name habitify-data-ingestion \
    --region "$REGION" \
    --query "Environment.Variables" \
    --output json

# Fetch current env, write to temp file, strip SECRET_NAME, update Lambda
TMP=$(mktemp /tmp/habitify_env_XXXXXX.json)

aws lambda get-function-configuration \
    --function-name habitify-data-ingestion \
    --region "$REGION" \
    --query "Environment.Variables" \
    --output json > "$TMP"

# Build new env JSON without SECRET_NAME
python3 - "$TMP" <<'PYEOF'
import json, sys
with open(sys.argv[1]) as f:
    env = json.load(f)
removed = env.pop("SECRET_NAME", None)
if removed:
    print(f"[INFO] Removing SECRET_NAME={removed}", file=sys.stderr)
else:
    print("[INFO] SECRET_NAME not present — already clean", file=sys.stderr)
print(json.dumps({"Variables": env}))
PYEOF

# Re-run and capture output for the update call
NEW_ENV=$(python3 - "$TMP" <<'PYEOF'
import json, sys
with open(sys.argv[1]) as f:
    env = json.load(f)
env.pop("SECRET_NAME", None)
print(json.dumps({"Variables": env}))
PYEOF
)

rm -f "$TMP"

echo "Updating habitify-data-ingestion..."
aws lambda update-function-configuration \
    --function-name habitify-data-ingestion \
    --region "$REGION" \
    --environment "$NEW_ENV" \
    --query "Environment.Variables" \
    --output json

echo "✅ Done — SECRET_NAME removed from habitify-data-ingestion"
