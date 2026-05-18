#!/bin/bash
# ============================================================
#  Patch monthly-digest Lambda: add Haiku API retry logic
#  Downloads live code, applies the patch, redeploys.
# ============================================================

set -e

FUNCTION_NAME="monthly-digest"
REGION="us-west-2"
TMP_ZIP="/tmp/monthly_digest_current.zip"
TMP_DIR="/tmp/monthly_digest_patch"
TMP_PY="$TMP_DIR/lambda_function.py"

echo ""
echo "=== Patching $FUNCTION_NAME for Haiku API retry logic ==="
echo ""

# 1. Download current deployed code
echo "[1/5] Downloading current deployed code..."
DOWNLOAD_URL=$(aws lambda get-function \
  --function-name "$FUNCTION_NAME" \
  --region "$REGION" \
  --query "Code.Location" \
  --output text)

curl -s -o "$TMP_ZIP" "$DOWNLOAD_URL"
echo "  ✓ Downloaded to $TMP_ZIP"

# 2. Extract
echo "[2/5] Extracting..."
rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR"
unzip -q "$TMP_ZIP" -d "$TMP_DIR"
echo "  ✓ Extracted: $(ls $TMP_DIR)"

# 3. Check current state
echo "[3/5] Checking current code..."
if grep -q "call_anthropic_with_retry" "$TMP_PY"; then
  echo "  ⚠ Retry logic already present — no changes needed."
  echo ""
  echo "Nothing to do. Exiting."
  exit 0
fi

if ! grep -q "urlopen" "$TMP_PY"; then
  echo "  ⚠ WARNING: Could not find urlopen in lambda_function.py"
  echo "  File contents:"
  ls "$TMP_DIR"
  exit 1
fi

echo "  ✓ urlopen found — patch needed"

# 4. Apply patch using Python (more reliable than sed for multiline)
echo "[4/5] Applying retry patch..."

python3 << 'PYEOF'
import re, sys

with open("/tmp/monthly_digest_patch/lambda_function.py", "r") as f:
    src = f.read()

# Add time and urllib.error imports after existing urllib.request import
src = src.replace(
    "import urllib.request\n",
    "import time\nimport urllib.error\nimport urllib.request\n",
    1
)

# Check we didn't already do it
if src.count("import time") > 1:
    src = src.replace("import time\nimport time\n", "import time\n")

# Add the retry helper before the first def that calls urlopen
# We insert it before the first def that contains 'urlopen'
RETRY_HELPER = '''
def call_anthropic_with_retry(req, timeout=30, max_attempts=2, backoff_s=5):
    """Call Anthropic API with 2-attempt retry and 5s backoff on transient errors."""
    for attempt in range(1, max_attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            print(f"[WARN] Anthropic API HTTP {e.code} on attempt {attempt}/{max_attempts}")
            if attempt < max_attempts and e.code in (429, 529, 500, 502, 503, 504):
                time.sleep(backoff_s)
            else:
                raise
        except urllib.error.URLError as e:
            print(f"[WARN] Anthropic API network error on attempt {attempt}/{max_attempts}: {e}")
            if attempt < max_attempts:
                time.sleep(backoff_s)
            else:
                raise


'''

# Find the def that contains urlopen — insert helper before it
pattern = r'(\ndef [a-zA-Z_]+[^:]*:\n(?:[ \t]+.*\n)*?[ \t]+urllib\.request\.urlopen)'
match = re.search(pattern, src)
if match:
    insert_at = match.start()
    src = src[:insert_at] + RETRY_HELPER + src[insert_at:]
    print("  Retry helper inserted")
else:
    print("  WARNING: Could not find urlopen function to insert before — aborting")
    sys.exit(1)

# Now replace all urlopen calls with retry wrapper
# Pattern: with urllib.request.urlopen(req, timeout=N) as r:
#               return json.loads(r.read())[...
# Replace with: resp = call_anthropic_with_retry(req, timeout=N)
#               return resp[...

def replace_urlopen(src):
    # Match the with/urlopen/return pattern
    pattern = (
        r'([ \t]+)with urllib\.request\.urlopen\((req(?:_[a-z]+)?), timeout=(\d+)\) as r:\n'
        r'\1    return json\.loads\(r\.read\(\)\)(.*)'
    )
    def sub(m):
        indent = m.group(1)
        req_var = m.group(2)
        timeout = m.group(3)
        rest = m.group(4)
        return (f'{indent}resp = call_anthropic_with_retry({req_var}, timeout={timeout})\n'
                f'{indent}return resp{rest}')
    new_src, n = re.subn(pattern, sub, src)
    print(f"  Replaced {n} urlopen call(s)")
    return new_src

src = replace_urlopen(src)

with open("/tmp/monthly_digest_patch/lambda_function.py", "w") as f:
    f.write(src)

print("  Patch applied successfully")
PYEOF

echo "  ✓ Patch applied"

# 5. Repackage and redeploy
echo "[5/5] Repackaging and deploying..."
NEW_ZIP="/tmp/monthly_digest_patched.zip"
cd "$TMP_DIR" && zip -j "$NEW_ZIP" lambda_function.py
cd - > /dev/null

aws lambda update-function-code \
  --function-name "$FUNCTION_NAME" \
  --zip-file "fileb://$NEW_ZIP" \
  --region "$REGION" > /dev/null

aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"
echo "  ✓ Deployed"

# Also save the patched version locally
cp "$TMP_PY" ~/Documents/Claude/life-platform/monthly_digest_lambda.py
echo "  ✓ Saved locally: ~/Documents/Claude/life-platform/monthly_digest_lambda.py"

echo ""
echo "=== Done. monthly-digest now has 2-attempt retry with 5s backoff ==="
echo ""
echo "Verify the patch landed:"
echo "  grep -n 'call_anthropic_with_retry\|time.sleep' ~/Documents/Claude/life-platform/monthly_digest_lambda.py | head -10"
