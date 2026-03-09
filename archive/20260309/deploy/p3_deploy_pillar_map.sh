#!/bin/bash
# p3_deploy_pillar_map.sh — Upload verified project_pillar_map.json to S3
# Run from project root.
set -euo pipefail
chmod +x "$0"
aws s3 cp config/project_pillar_map.json \
    s3://matthew-life-platform/config/project_pillar_map.json \
    --region us-west-2
echo "✅ project_pillar_map.json uploaded to S3"
echo "Verify: aws s3 cp s3://matthew-life-platform/config/project_pillar_map.json - | python3 -m json.tool"
