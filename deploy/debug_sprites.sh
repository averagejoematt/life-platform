#!/bin/bash
echo "=== Check 1: Does the sprite exist in S3? ==="
aws s3 ls s3://matthew-life-platform/dashboard/avatar/base/ 2>&1

echo ""
echo "=== Check 2: Does data.json have avatar data? ==="
aws s3 cp s3://matthew-life-platform/dashboard/data.json - 2>/dev/null | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('avatar key exists:', 'avatar' in d)
if 'avatar' in d:
    print('avatar data:', json.dumps(d['avatar'], indent=2))
else:
    print('NO AVATAR DATA — renderAvatar() returns empty string')
    print('character_sheet exists:', 'character_sheet' in d)
    if 'character_sheet' in d:
        cs = d['character_sheet']
        print('  tier:', cs.get('tier'))
        print('  level:', cs.get('level'))
"

echo ""
echo "=== Check 3: Test sprite URL via curl ==="
curl -sI "https://dash.averagejoematt.com/avatar/base/foundation-frame1.png" | head -5
