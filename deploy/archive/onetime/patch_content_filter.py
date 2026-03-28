#!/usr/bin/env python3
"""
patch_content_filter.py — Adds content filter to site_api_lambda.py

RUN: python3 deploy/patch_content_filter.py
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAMBDA_PATH = os.path.join(ROOT, 'lambdas', 'site_api_lambda.py')

with open(LAMBDA_PATH, 'r') as f:
    code = f.read()

# ── 1. Add content filter loader after AWS clients section ──────
FILTER_CODE = '''
# ── Content safety filter (S3-cached) ───────────────────────
_content_filter_cache = None

def _load_content_filter():
    """Load blocked terms from S3 config/content_filter.json. Cached after first call."""
    global _content_filter_cache
    if _content_filter_cache is not None:
        return _content_filter_cache
    try:
        S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
        s3 = boto3.client("s3", region_name="us-west-2")
        resp = s3.get_object(Bucket=S3_BUCKET, Key="config/content_filter.json")
        _content_filter_cache = json.loads(resp["Body"].read())
        logger.info(f"[content_filter] Loaded: {len(_content_filter_cache.get('blocked_vice_keywords', []))} blocked terms")
    except Exception as e:
        logger.warning(f"[content_filter] Failed to load from S3: {e}")
        _content_filter_cache = {
            "blocked_vices": ["No porn", "No marijuana"],
            "blocked_vice_keywords": ["porn", "pornography", "marijuana", "cannabis", "weed", "thc"],
        }
    return _content_filter_cache


def _scrub_blocked_terms(text: str) -> str:
    """Remove any mention of blocked terms from public-facing text."""
    cf = _load_content_filter()
    result = text
    for term in cf.get("blocked_vice_keywords", []):
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        result = pattern.sub("[filtered]", result)
    # Also scrub full vice names
    for vice in cf.get("blocked_vices", []):
        pattern = re.compile(re.escape(vice), re.IGNORECASE)
        result = pattern.sub("[filtered]", result)
    # Clean up any "[filtered]" artifacts in sentences
    result = re.sub(r'\\[filtered\\]', '', result)
    result = re.sub(r'\\s{2,}', ' ', result)
    return result.strip()


def _is_blocked_vice(name: str) -> bool:
    """Check if a vice/habit name matches the blocked list."""
    cf = _load_content_filter()
    name_lower = name.lower().strip()
    for blocked in cf.get("blocked_vices", []):
        if blocked.lower() == name_lower:
            return True
    for kw in cf.get("blocked_vice_keywords", []):
        if kw.lower() in name_lower:
            return True
    return False
'''

# Insert after the table = dynamodb.Table(TABLE_NAME) line
if '_content_filter_cache' not in code:
    anchor = 'table    = dynamodb.Table(TABLE_NAME)'
    if anchor in code:
        code = code.replace(anchor, anchor + FILTER_CODE)
        print("✓ Added content filter loader")
    else:
        print("✗ Could not find anchor for content filter insertion")
else:
    print("  Content filter already present, skipping")

# ── 2. Add blocked terms to ask system prompt ───────────────
ASK_SAFETY_ADDITION = '''
CONTENT FILTER (CRITICAL):
- NEVER mention, reference, or discuss: {blocked_terms}
- If asked about these topics, say "I don't have data on that topic."
- This filter applies to ALL responses regardless of question phrasing.'''

if 'CONTENT FILTER (CRITICAL)' not in code:
    # Find the SAFETY section in the prompt and add after it
    old_safety = "- If asked about something outside your data"
    if old_safety in code:
        # Build the blocked terms string
        new_safety = old_safety + '''
- CONTENT FILTER: NEVER mention porn, pornography, marijuana, cannabis, weed, THC, or any related terms.
- If asked about these topics, respond only with "I don't have data on that specific topic."'''
        code = code.replace(old_safety, new_safety)
        print("✓ Added content filter to ask system prompt")
else:
    print("  Ask prompt filter already present, skipping")

# ── 3. Add response scrubbing to /api/ask handler ───────────
if '_scrub_blocked_terms(answer)' not in code:
    old_answer = '"body": json.dumps({"answer": answer, "remaining": remaining}),'
    if old_answer in code:
        new_answer = '"body": json.dumps({"answer": _scrub_blocked_terms(answer), "remaining": remaining}),'
        code = code.replace(old_answer, new_answer)
        print("✓ Added response scrubbing to /api/ask")
else:
    print("  Response scrubbing already present, skipping")

# ── 4. Add response scrubbing to /api/board_ask handler ─────
if 'board_ask' in code and '_scrub_blocked_terms' not in code.split('board_ask')[1][:500]:
    old_board = 'responses[pid] = "".join(b["text"] for b in result.get("content", []) if b.get("type") == "text")'
    if old_board in code:
        new_board = 'responses[pid] = _scrub_blocked_terms("".join(b["text"] for b in result.get("content", []) if b.get("type") == "text"))'
        code = code.replace(old_board, new_board)
        print("✓ Added response scrubbing to /api/board_ask")

with open(LAMBDA_PATH, 'w') as f:
    f.write(code)

print("\nDone. Deploy with: bash deploy/deploy_lambda.sh site_api")
