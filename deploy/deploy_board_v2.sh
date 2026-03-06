#!/bin/bash
# deploy_board_v2.sh — Board of Directors config update
# Changes: +Paul Conti, +Vivek Murthy, -Matthew Walker (folded into Park)
set -euo pipefail

CONFIG_DIR="$HOME/Documents/Claude/life-platform/config"
BUCKET="matthew-life-platform"
REGION="us-west-2"

echo "=== Deploy Board of Directors v2.0.0 ==="
echo ""
echo "Changes:"
echo "  + Dr. Paul Conti (psychiatry, grief, identity, defense mechanisms)"
echo "  + Dr. Vivek Murthy (social connection, loneliness, male isolation)"
echo "  - Dr. Matthew Walker (retired — domains folded into Dr. Lisa Park)"
echo "  ~ Dr. Lisa Park expanded (sleep_science, cognitive_performance, chronotype)"
echo ""

# Upload to S3
echo "[1/2] Uploading to S3..."
aws s3 cp "$CONFIG_DIR/board_of_directors.json" \
  "s3://$BUCKET/config/board_of_directors.json" \
  --content-type "application/json" \
  --region "$REGION"
echo "  ✓ S3 config updated"

# Verify
echo ""
echo "[2/2] Verifying..."
MEMBER_COUNT=$(aws s3 cp "s3://$BUCKET/config/board_of_directors.json" - --region "$REGION" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['members']))")
echo "  ✓ Members in S3: $MEMBER_COUNT"

echo ""
echo "=== Done ==="
echo "  Board config live. All Lambdas will pick up changes within 5 minutes (cache TTL)."
echo ""
echo "  Current board (13 members):"
echo "    Fictional: Chen, Webb, Park, Okafor, Rodriguez"
echo "    Real: Norton, Patrick, Attia, Huberman, Conti (NEW), Murthy (NEW)"
echo "    Narrator: Elena Voss"
echo "    Meta: The Chair"
