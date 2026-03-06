"""
patch_parameterize_daily_brief.py — Replace hardcoded config with os.environ reads

Replaces:
  - Hardcoded region, table, bucket, email addresses with env vars
  - Anthropic secret name with env var
  - All 'USER#matthew' patterns with env-var-derived variables
  - DASHBOARD_BUCKET with env var

Idempotent: skips if already parameterized.

Usage:
    python3 patch_parameterize_daily_brief.py <path-to-lambda_function.py>
"""

import sys
import re

path = sys.argv[1] if len(sys.argv) > 1 else "lambda_function.py"

with open(path, "r") as f:
    content = f.read()

# ── Safety check ──────────────────────────────────────────────────────────────
if 'os.environ.get("TABLE_NAME"' in content:
    print("SKIP: Daily Brief already parameterized")
    sys.exit(0)

changes = 0

# ── 1. Add 'import os' after existing imports ────────────────────────────────
if "import os" not in content:
    content = content.replace(
        "import json\n",
        "import json\nimport os\n",
        1
    )
    changes += 1
    print("  [1] Added 'import os'")

# ── 2. Replace AWS client block ──────────────────────────────────────────────
OLD_CLIENTS = '''# -- AWS clients ---------------------------------------------------------------
dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
table    = dynamodb.Table("life-platform")
ses      = boto3.client("sesv2", region_name="us-west-2")
s3       = boto3.client("s3", region_name="us-west-2")
secrets  = boto3.client("secretsmanager", region_name="us-west-2")

RECIPIENT = "awsdev@mattsusername.com"
SENDER    = "awsdev@mattsusername.com"'''

NEW_CLIENTS = '''# -- Configuration from environment variables (with backwards-compatible defaults) --
_REGION    = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET  = os.environ.get("S3_BUCKET", "matthew-life-platform")
USER_ID    = os.environ.get("USER_ID", "matthew")
RECIPIENT  = os.environ.get("EMAIL_RECIPIENT", "awsdev@mattsusername.com")
SENDER     = os.environ.get("EMAIL_SENDER", "awsdev@mattsusername.com")
ANTHROPIC_SECRET = os.environ.get("ANTHROPIC_SECRET", "life-platform/anthropic")

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"
PROFILE_PK  = f"USER#{USER_ID}"

# -- AWS clients ---------------------------------------------------------------
dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table    = dynamodb.Table(TABLE_NAME)
ses      = boto3.client("sesv2", region_name=_REGION)
s3       = boto3.client("s3", region_name=_REGION)
secrets  = boto3.client("secretsmanager", region_name=_REGION)'''

if OLD_CLIENTS in content:
    content = content.replace(OLD_CLIENTS, NEW_CLIENTS)
    changes += 1
    print("  [2] Replaced AWS client block with env-var config")
else:
    print("  [2] WARNING: Could not find exact client block — trying partial replacements")
    pairs = [
        ('dynamodb = boto3.resource("dynamodb", region_name="us-west-2")',
         '_REGION = os.environ.get("AWS_REGION", "us-west-2")\nTABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")\nS3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")\nUSER_ID = os.environ.get("USER_ID", "matthew")\nANTHROPIC_SECRET = os.environ.get("ANTHROPIC_SECRET", "life-platform/anthropic")\nUSER_PREFIX = f"USER#{USER_ID}#SOURCE#"\nPROFILE_PK = f"USER#{USER_ID}"\n\ndynamodb = boto3.resource("dynamodb", region_name=_REGION)'),
        ('table    = dynamodb.Table("life-platform")', 'table    = dynamodb.Table(TABLE_NAME)'),
        ('ses      = boto3.client("sesv2", region_name="us-west-2")', 'ses      = boto3.client("sesv2", region_name=_REGION)'),
        ('s3       = boto3.client("s3", region_name="us-west-2")', 's3       = boto3.client("s3", region_name=_REGION)'),
        ('secrets  = boto3.client("secretsmanager", region_name="us-west-2")', 'secrets  = boto3.client("secretsmanager", region_name=_REGION)'),
        ('RECIPIENT = "awsdev@mattsusername.com"', 'RECIPIENT = os.environ.get("EMAIL_RECIPIENT", "awsdev@mattsusername.com")'),
        ('SENDER    = "awsdev@mattsusername.com"', 'SENDER    = os.environ.get("EMAIL_SENDER", "awsdev@mattsusername.com")'),
    ]
    for old, new in pairs:
        if old in content:
            content = content.replace(old, new, 1)
            changes += 1

# ── 3. Replace Anthropic secret name ─────────────────────────────────────────
old_anthro = 'secrets.get_secret_value(SecretId="life-platform/anthropic")'
new_anthro = 'secrets.get_secret_value(SecretId=ANTHROPIC_SECRET)'
c = content.count(old_anthro)
if c > 0:
    content = content.replace(old_anthro, new_anthro)
    changes += c
    print(f"  [3] Fixed {c} Anthropic secret reference(s)")

# ── 4. Replace DASHBOARD_BUCKET ──────────────────────────────────────────────
old_dash = 'DASHBOARD_BUCKET = "matthew-life-platform"'
new_dash = 'DASHBOARD_BUCKET = S3_BUCKET  # From env var'
if old_dash in content:
    content = content.replace(old_dash, new_dash)
    changes += 1
    print("  [4] Replaced DASHBOARD_BUCKET with S3_BUCKET reference")

# ── 5. Replace "USER#matthew#SOURCE#" + source patterns ─────────────────────
# Pattern: "USER#matthew#SOURCE#" + source (in fetch_date, fetch_range, etc.)
old_concat = '"USER#matthew#SOURCE#" + '
new_concat = 'USER_PREFIX + '
c = content.count(old_concat)
if c > 0:
    content = content.replace(old_concat, new_concat)
    changes += c
    print(f"  [5a] Fixed {c} USER#matthew#SOURCE# concat patterns")

# Pattern: ":pk": "USER#matthew#SOURCE#<literal>" (ExpressionAttributeValues with literal source)
pattern_literal_expr = r'":pk": "USER#matthew#SOURCE#(\w+)"'
replace_literal_expr = r'":pk": USER_PREFIX + "\1"'
c = len(re.findall(pattern_literal_expr, content))
if c > 0:
    content = re.sub(pattern_literal_expr, replace_literal_expr, content)
    changes += c
    print(f"  [5b] Fixed {c} literal ExpressionAttributeValues patterns")

# Pattern: "pk": "USER#matthew#SOURCE#<literal>" (Key dict with literal source)
pattern_literal_key = r'"pk": "USER#matthew#SOURCE#(\w+)"'
replace_literal_key = r'"pk": USER_PREFIX + "\1"'
c = len(re.findall(pattern_literal_key, content))
if c > 0:
    content = re.sub(pattern_literal_key, replace_literal_key, content)
    changes += c
    print(f"  [5c] Fixed {c} literal Key dict patterns")

# ── 6. Replace "USER#matthew" profile patterns ───────────────────────────────
# Key={"pk": "USER#matthew", "sk": "PROFILE#v1"}
old_profile_key = '"pk": "USER#matthew", "sk": "PROFILE#v1"'
new_profile_key = '"pk": PROFILE_PK, "sk": "PROFILE#v1"'
c = content.count(old_profile_key)
if c > 0:
    content = content.replace(old_profile_key, new_profile_key)
    changes += c
    print(f"  [6a] Fixed {c} profile key patterns")

# Any remaining "USER#matthew" (but not in comments/strings we want to keep)
old_user = '"USER#matthew"'
new_user = 'PROFILE_PK'
c = content.count(old_user)
if c > 0:
    content = content.replace(old_user, new_user)
    changes += c
    print(f"  [6b] Fixed {c} remaining USER#matthew references")

# ── 7. Handle .eq("USER#matthew#SOURCE#" patterns in Key conditions ──────────
old_eq = '.eq("USER#matthew#SOURCE#" + '
new_eq = '.eq(USER_PREFIX + '
c = content.count(old_eq)
if c > 0:
    content = content.replace(old_eq, new_eq)
    changes += c
    print(f"  [7] Fixed {c} .eq() Key condition patterns")

# ── 8. Verify ────────────────────────────────────────────────────────────────
remaining = []
for i, line in enumerate(content.split("\n"), 1):
    if "matthew" in line.lower() and not any(skip in line for skip in [
        "#", "Matthew", "USER_ID", "USER_PREFIX", "PROFILE_PK", "S3_BUCKET",
        "print(", "comment", "docstring", "# ──", "DASHBOARD_BUCKET"
    ]):
        remaining.append(f"  Line {i}: {line.strip()[:100]}")

if remaining:
    print(f"\n  ⚠️  {len(remaining)} lines still reference 'matthew' (review manually):")
    for r in remaining[:10]:
        print(r)

# ── Write ─────────────────────────────────────────────────────────────────────
with open(path, "w") as f:
    f.write(content)

print(f"\n  ✅ Daily Brief parameterized — {changes} changes applied")
