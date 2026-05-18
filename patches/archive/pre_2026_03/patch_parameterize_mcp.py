"""
patch_parameterize_mcp.py — Replace hardcoded config with os.environ reads

Replaces:
  - Hardcoded region, table, bucket, user prefix, secret name with env vars
  - Inline DynamoDB client re-creation at lines ~9048, ~9357
  - All 'USER#matthew' patterns with f-string using USER_ID

Idempotent: skips if already parameterized.

Usage:
    python3 patch_parameterize_mcp.py <path-to-lambda_function.py>
"""

import sys
import re

path = sys.argv[1] if len(sys.argv) > 1 else "lambda_function.py"

with open(path, "r") as f:
    content = f.read()

# ── Safety check ──────────────────────────────────────────────────────────────
if 'os.environ.get("TABLE_NAME"' in content:
    print("SKIP: MCP server already parameterized")
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

# ── 2. Replace module-level config block ─────────────────────────────────────
# Find and replace the hardcoded globals block

OLD_CONFIG = '''dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
table    = dynamodb.Table("life-platform")
secrets  = boto3.client("secretsmanager", region_name="us-west-2")
s3_client = boto3.client("s3", region_name="us-west-2")
S3_BUCKET = "matthew-life-platform"

USER_PREFIX     = "USER#matthew#SOURCE#"
PROFILE_PK      = "USER#matthew"
PROFILE_SK      = "PROFILE#v1"
API_SECRET_NAME = "life-platform/mcp-api-key"'''

NEW_CONFIG = '''# ── Configuration from environment variables (with backwards-compatible defaults) ──
_REGION         = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME      = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET       = os.environ.get("S3_BUCKET", "matthew-life-platform")
USER_ID         = os.environ.get("USER_ID", "matthew")
API_SECRET_NAME = os.environ.get("API_SECRET_NAME", "life-platform/mcp-api-key")

dynamodb  = boto3.resource("dynamodb", region_name=_REGION)
table     = dynamodb.Table(TABLE_NAME)
secrets   = boto3.client("secretsmanager", region_name=_REGION)
s3_client = boto3.client("s3", region_name=_REGION)

USER_PREFIX     = f"USER#{USER_ID}#SOURCE#"
PROFILE_PK      = f"USER#{USER_ID}"
PROFILE_SK      = "PROFILE#v1"'''

if OLD_CONFIG in content:
    content = content.replace(OLD_CONFIG, NEW_CONFIG)
    changes += 1
    print("  [2] Replaced module-level config block with os.environ reads")
else:
    print("  [2] WARNING: Could not find exact config block — trying partial replacements")
    
    # Try individual replacements as fallback
    replacements = [
        ('dynamodb = boto3.resource("dynamodb", region_name="us-west-2")',
         '_REGION = os.environ.get("AWS_REGION", "us-west-2")\nTABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")\nS3_BUCKET_NAME = os.environ.get("S3_BUCKET", "matthew-life-platform")\nUSER_ID = os.environ.get("USER_ID", "matthew")\n\ndynamodb = boto3.resource("dynamodb", region_name=_REGION)'),
        ('table    = dynamodb.Table("life-platform")', 'table    = dynamodb.Table(TABLE_NAME)'),
        ('secrets  = boto3.client("secretsmanager", region_name="us-west-2")', 'secrets  = boto3.client("secretsmanager", region_name=_REGION)'),
        ('s3_client = boto3.client("s3", region_name="us-west-2")', 's3_client = boto3.client("s3", region_name=_REGION)'),
        ('S3_BUCKET = "matthew-life-platform"', '# S3_BUCKET set above via os.environ'),
        ('USER_PREFIX     = "USER#matthew#SOURCE#"', 'USER_PREFIX     = f"USER#{USER_ID}#SOURCE#"'),
        ('PROFILE_PK      = "USER#matthew"', 'PROFILE_PK      = f"USER#{USER_ID}"'),
        ('API_SECRET_NAME = "life-platform/mcp-api-key"', 'API_SECRET_NAME = os.environ.get("API_SECRET_NAME", "life-platform/mcp-api-key")'),
    ]
    for old, new in replacements:
        if old in content:
            content = content.replace(old, new, 1)
            changes += 1


# ── 3. Fix inline DynamoDB re-creation inside functions ──────────────────────
# These create new boto3 resources with hardcoded values inside tool functions
inline_ddb = 'table = boto3.resource("dynamodb", region_name="us-west-2").Table("life-platform")'
inline_fix = 'table = boto3.resource("dynamodb", region_name=_REGION).Table(TABLE_NAME)'

count = content.count(inline_ddb)
if count > 0:
    content = content.replace(inline_ddb, inline_fix)
    changes += count
    print(f"  [3] Fixed {count} inline DynamoDB re-creation(s)")


# ── 4. Replace remaining hardcoded 'USER#matthew' patterns ───────────────────
# These are inside f-strings and query expressions throughout the code
# Pattern: "USER#matthew#SOURCE#" (literal string) → USER_PREFIX (variable)
# Pattern: "USER#matthew" (in pk values) → PROFILE_PK

# First handle ExpressionAttributeValues patterns
old_expr_source = '":pk": "USER#matthew#SOURCE#"'
new_expr_source = '":pk": USER_PREFIX'
# These are inside f-strings typically, so we need careful handling

# Handle the common pattern in query calls: .eq("USER#matthew#SOURCE#<source>")
# Replace .eq("USER#matthew#SOURCE#" + source) with .eq(USER_PREFIX + source)
pattern_eq_concat = r'\.eq\("USER#matthew#SOURCE#" \+ '
replace_eq_concat = '.eq(USER_PREFIX + '
count_eq = len(re.findall(pattern_eq_concat, content))
if count_eq > 0:
    content = re.sub(pattern_eq_concat, replace_eq_concat, content)
    changes += count_eq
    print(f"  [4a] Fixed {count_eq} .eq(\"USER#matthew#SOURCE#\" + ...) patterns")

# Handle f-string patterns: f"USER#matthew#SOURCE#{source}"
pattern_fstr = r'f"USER#matthew#SOURCE#\{([^}]+)\}"'
replace_fstr = r'f"{USER_PREFIX}\1"'
# Actually these should just use USER_PREFIX + var
# Let's be more careful
pattern_fstr2 = r'"USER#matthew#SOURCE#" \+ '
replace_fstr2 = 'USER_PREFIX + '
count_f = content.count('"USER#matthew#SOURCE#" + ')
if count_f > 0:
    content = content.replace('"USER#matthew#SOURCE#" + ', 'USER_PREFIX + ')
    changes += count_f
    print(f"  [4b] Fixed {count_f} string concat patterns")

# Handle dict literal patterns: "pk": "USER#matthew#SOURCE#" + source
# and ExpressionAttributeValues
pattern_expr = r'":pk": "USER#matthew#SOURCE#" \+ '
replace_expr = '":pk": USER_PREFIX + '
count_e = len(re.findall(pattern_expr, content))
if count_e > 0:
    content = re.sub(pattern_expr, replace_expr, content)
    changes += count_e
    print(f"  [4c] Fixed {count_e} ExpressionAttributeValues patterns")

# Handle "pk": "USER#matthew#SOURCE#travel" (literal full pk values)
pattern_literal = r'"pk": "USER#matthew#SOURCE#(\w+)"'
replace_literal = r'"pk": USER_PREFIX + "\1"'
count_lit = len(re.findall(pattern_literal, content))
if count_lit > 0:
    content = re.sub(pattern_literal, replace_literal, content)
    changes += count_lit
    print(f"  [4d] Fixed {count_lit} literal pk value patterns")

# Handle "pk": "USER#matthew" (profile pk)
old_profile = '"pk": "USER#matthew"'
new_profile = '"pk": PROFILE_PK'
count_p = content.count(old_profile)
if count_p > 0:
    content = content.replace(old_profile, new_profile)
    changes += count_p
    print(f"  [4e] Fixed {count_p} profile pk patterns")

# Handle ":pk": "USER#matthew" in ExpressionAttributeValues
old_expr_profile = '":pk": "USER#matthew"'
new_expr_profile = '":pk": PROFILE_PK'
count_ep = content.count(old_expr_profile)
if count_ep > 0:
    content = content.replace(old_expr_profile, new_expr_profile)
    changes += count_ep
    print(f"  [4f] Fixed {count_ep} expression profile pk patterns")

# Handle Key({"pk": ... patterns  
old_key_profile = '"pk": "USER#matthew", "sk":'
new_key_profile = '"pk": PROFILE_PK, "sk":'
count_kp = content.count(old_key_profile)
if count_kp > 0:
    content = content.replace(old_key_profile, new_key_profile)
    changes += count_kp
    print(f"  [4g] Fixed {count_kp} Key profile patterns")

# ── 5. Fix variable assignments: pk = "USER#matthew#SOURCE#<source>" ─────────
pattern_var_assign = r'(\w+)\s*=\s*"USER#matthew#SOURCE#(\w+)"'
def _replace_var_assign(m):
    return f'{m.group(1)} = USER_PREFIX + "{m.group(2)}"'
count_va = len(re.findall(pattern_var_assign, content))
if count_va > 0:
    content = re.sub(pattern_var_assign, _replace_var_assign, content)
    changes += count_va
    print(f"  [5a] Fixed {count_va} variable assignment patterns")

# ── 6. Fix .eq("USER#matthew#SOURCE#<source>") — literal Key conditions ───────
pattern_eq_literal = r'\.eq\("USER#matthew#SOURCE#(\w+)"\)'
replace_eq_literal = r'.eq(USER_PREFIX + "\1")'
count_eql = len(re.findall(pattern_eq_literal, content))
if count_eql > 0:
    content = re.sub(pattern_eq_literal, replace_eq_literal, content)
    changes += count_eql
    print(f"  [6] Fixed {count_eql} .eq() literal source patterns")

# ── 7. Fix constant PK definitions: SOMETHING_PK = "USER#matthew#SOURCE#..." ─
# Already caught by pattern_var_assign above

# ── 8. Verify no remaining hardcoded matthew references ──────────────────────
remaining = []
for i, line in enumerate(content.split("\n"), 1):
    if "matthew" in line.lower() and not any(skip in line for skip in [
        "#", "Matthew", "CHANGELOG", "handover", "commit", "version",
        "comment", "docstring", "USER_ID", "# ──"
    ]):
        remaining.append(f"  Line {i}: {line.strip()[:100]}")

if remaining:
    print(f"\n  ⚠️  {len(remaining)} lines still reference 'matthew' (review manually):")
    for r in remaining[:10]:
        print(r)


# ── Write ─────────────────────────────────────────────────────────────────────
with open(path, "w") as f:
    f.write(content)

print(f"\n  ✅ MCP server parameterized — {changes} changes applied")
