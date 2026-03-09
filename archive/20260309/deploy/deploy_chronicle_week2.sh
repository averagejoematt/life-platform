#!/bin/bash
# deploy_chronicle_week2.sh — Fix Lambda packaging + publish Week 2 manually
# This week's installment was written from an off-the-record interview, not AI-generated
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
LAMBDA_DIR="$ROOT_DIR/lambdas"
REGION="us-west-2"
BUCKET="matthew-life-platform"
TABLE="life-platform"
FUNC_NAME="wednesday-chronicle"
CONTENT_FILE="$ROOT_DIR/content/chronicle_week2.md"
BLOG_DIST="E1JOC1V6E6DDYI"

echo "==========================================="
echo "  Chronicle Week 2: Fix Lambda + Publish"
echo "  \"The Empty Journal\" by Elena Voss"
echo "==========================================="

# ── PART 1: Fix Lambda Packaging ──────────────────────────────────
echo ""
echo "=== PART 1: Fix Lambda Packaging ==="
echo ""
echo "[1/2] Packaging Lambda (lambda_function.py + board_loader.py)..."
cd "$LAMBDA_DIR"
cp wednesday_chronicle_lambda.py lambda_function.py
rm -f wednesday_chronicle.zip
zip -j wednesday_chronicle.zip lambda_function.py board_loader.py
rm lambda_function.py
echo "  ✓ Zip created: $(du -h wednesday_chronicle.zip | cut -f1)"

echo ""
echo "[2/2] Deploying fixed Lambda..."
aws lambda update-function-code \
  --function-name "$FUNC_NAME" \
  --zip-file "fileb://wednesday_chronicle.zip" \
  --region "$REGION" \
  --output json | jq '{FunctionName, CodeSize, LastModified}'

aws lambda wait function-updated \
  --function-name "$FUNC_NAME" \
  --region "$REGION"
echo "  ✓ Lambda updated and active"

# ── PART 2: Publish Week 2 Content ────────────────────────────────
echo ""
echo "=== PART 2: Publish Week 2 ==="
echo ""

if [ ! -f "$CONTENT_FILE" ]; then
  echo "ERROR: Content file not found: $CONTENT_FILE"
  exit 1
fi

python3 << 'PYTHON_SCRIPT'
import boto3
import re
import json
from datetime import datetime, timezone

REGION = "us-west-2"
BUCKET = "matthew-life-platform"
TABLE = "life-platform"
USER_ID = "matthew"
SENDER = "awsdev@mattsusername.com"
RECIPIENT = "awsdev@mattsusername.com"

WEEK_NUM = 2
DATE_STR = "2026-03-03"  # End of coverage week
DATE_DISPLAY = "March 4, 2026"
TITLE = "The Empty Journal"
STATS_LINE = "Week 2 | February 25 – March 3, 2026 | Seattle, WA"

s3 = boto3.client("s3", region_name=REGION)
ddb = boto3.resource("dynamodb", region_name=REGION)
table = ddb.Table(TABLE)
ses = boto3.client("sesv2", region_name=REGION)

# ── Read markdown ──
import os
root = os.environ.get("ROOT_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
content_path = os.path.join(root, "content", "chronicle_week2.md")
if not os.path.exists(content_path):
    # Fallback
    content_path = os.path.expanduser("~/Documents/Claude/life-platform/content/chronicle_week2.md")
with open(content_path) as f:
    raw_markdown = f.read()

# ── Extract body (skip title/byline/first hr) ──
lines = raw_markdown.strip().split("\n")
body_lines = []
past_header = False
hr_count = 0
for line in lines:
    if line.strip() == "---":
        hr_count += 1
        if hr_count == 1 and not past_header:
            past_header = True
            body_lines.append(line)
            continue
    if past_header:
        body_lines.append(line)
    # Skip # title and *byline* lines
    elif line.startswith("# ") or (line.startswith("*") and "Elena Voss" in line):
        continue

body_md = "\n".join(body_lines).strip()

# ── Markdown to HTML (same logic as Lambda) ──
def markdown_to_html(md_text):
    lines = md_text.strip().split("\n")
    html_parts = []
    in_blockquote = False
    bq_buffer = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("> "):
            if not in_blockquote:
                in_blockquote = True
                bq_buffer = []
            bq_buffer.append(stripped[2:])
            continue
        elif in_blockquote:
            bq_text = " ".join(bq_buffer)
            bq_text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', bq_text)
            bq_text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', bq_text)
            html_parts.append(f'<blockquote>{bq_text}</blockquote>')
            in_blockquote = False
            bq_buffer = []
        if stripped == "---":
            html_parts.append("<hr>")
            continue
        if not stripped:
            continue
        if stripped.startswith("*") and stripped.endswith("*") and not stripped.startswith("**"):
            inner = stripped[1:-1]
            html_parts.append(f'<p class="signature"><em>{inner}</em></p>')
            continue
        text = stripped
        text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
        text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
        html_parts.append(f"<p>{text}</p>")

    if in_blockquote and bq_buffer:
        bq_text = " ".join(bq_buffer)
        bq_text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', bq_text)
        bq_text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', bq_text)
        html_parts.append(f'<blockquote>{bq_text}</blockquote>')

    return "\n".join(html_parts)

body_html = markdown_to_html(body_md)
print(f"  Body HTML: {len(body_html)} chars")

# ── 1. Store in DynamoDB ──
print("[1/5] Storing in DynamoDB...")
item = {
    "pk": f"USER#{USER_ID}#SOURCE#chronicle",
    "sk": f"DATE#{DATE_STR}",
    "date": DATE_STR,
    "source": "chronicle",
    "week_number": WEEK_NUM,
    "title": TITLE,
    "subtitle": f"Week {WEEK_NUM} of The Measured Life",
    "stats_line": STATS_LINE,
    "content_markdown": raw_markdown,
    "content_html": body_html,
    "word_count": len(raw_markdown.split()),
    "has_board_interview": False,
    "series_title": "The Measured Life",
    "author": "Elena Voss",
    "generated_at": datetime.now(timezone.utc).isoformat(),
}
table.put_item(Item=item)
print("  ✓ DynamoDB: chronicle partition updated")

# ── 2. Build blog post HTML ──
print("[2/5] Building blog post...")
prev_link = '<a href="week-01.html">&larr; Week 1</a>'
blog_post = f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{TITLE} — The Measured Life</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <header>
    <a href="index.html" class="series-title">The Measured Life</a>
    <p class="byline">An ongoing chronicle by Elena Voss</p>
    <nav class="site-nav"><a href="index.html">Archive</a><a href="about.html">About</a></nav>
  </header>
  <main>
    <article>
      <h1>"{TITLE}"</h1>
      <p class="meta">Week {WEEK_NUM} &middot; {DATE_DISPLAY}</p>
      <p class="stats">{STATS_LINE}</p>
      <div class="body">
        {body_html}
      </div>
    </article>
    <nav class="post-nav">
      {prev_link}
      <a href="index.html">All installments</a>
    </nav>
  </main>
  <footer>
    <p>&copy; 2026 The Measured Life. A chronicle of one man's attempt to change.</p>
  </footer>
</body>
</html>'''

s3.put_object(Bucket=BUCKET, Key="blog/week-02.html", Body=blog_post,
              ContentType="text/html; charset=utf-8", CacheControl="max-age=3600")
print("  ✓ S3: blog/week-02.html uploaded")

# ── 3. Update blog index ──
print("[3/5] Updating blog index...")
# Query all installments for index
resp = table.query(
    KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
    ExpressionAttributeValues={
        ":pk": f"USER#{USER_ID}#SOURCE#chronicle",
        ":prefix": "DATE#",
    },
    ScanIndexForward=False,
)
all_items = resp.get("Items", [])

# Build hero (latest = week 2)
latest = all_items[0] if all_items else None
l_title = latest.get("title", "Untitled") if latest else TITLE
l_wn = int(latest.get("week_number", WEEK_NUM)) if latest else WEEK_NUM
l_date = latest.get("date", DATE_STR) if latest else DATE_STR
try:
    l_dt = datetime.strptime(l_date, "%Y-%m-%d")
    l_date_display = l_dt.strftime("%B %-d, %Y")
except:
    l_date_display = l_date
l_filename = f"week-{l_wn:02d}.html"
l_kicker = "Prologue" if l_wn == 0 else f"Week {l_wn}"
l_stats = latest.get("stats_line", "") if latest else STATS_LINE
l_stats_html = f'<p style="font-family:-apple-system,sans-serif;font-size:12px;color:#bbb;margin-top:4px;">{l_stats}</p>' if l_stats else ""
hero_html = f'''<div class="hero">
      <div class="kicker">{l_kicker} &middot; {l_date_display}</div>
      <h2><a href="{l_filename}">"{l_title}"</a></h2>
      {l_stats_html}
      <a href="{l_filename}" class="read-link">Read {l_kicker.lower()} &rarr;</a>
    </div>'''

# Build archive entries
entries_html = ""
for inst in all_items:
    t = inst.get("title", "Untitled")
    wn = int(inst.get("week_number", 0))
    d = inst.get("date", "?")
    try:
        dt = datetime.strptime(d, "%Y-%m-%d")
        dd = dt.strftime("%B %-d, %Y")
    except:
        dd = d
    fn = f"week-{wn:02d}.html"
    label = "Prologue" if wn == 0 else f"Week {wn}"
    entries_html += f'''<li>
          <a href="{fn}">\\"{t}\\" <span class="label">{label}</span></a>
          <span class="date">{dd}</span>
        </li>\n'''

index_html = f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>The Measured Life &mdash; by Elena Voss</title>
  <link rel="stylesheet" href="style.css">
  <style>
    .hero {{ padding: 48px 0 40px; border-bottom: 1px solid #e5e5e0; }}
    .hero .kicker {{ font-family: -apple-system, sans-serif; font-size: 11px; letter-spacing: 2px; text-transform: uppercase; color: #999; margin-bottom: 16px; }}
    .hero h2 {{ font-size: 32px; font-weight: 400; font-style: italic; color: #1a1a1a; line-height: 1.3; margin: 0 0 16px; }}
    .hero h2 a {{ color: inherit; text-decoration: none; }}
    .hero h2 a:hover {{ color: #444; }}
    .hero .read-link {{ font-family: -apple-system, sans-serif; font-size: 13px; color: #333; text-decoration: none; letter-spacing: 0.5px; border-bottom: 1px solid #ccc; padding-bottom: 2px; }}
    .hero .read-link:hover {{ color: #000; border-color: #333; }}
    .series-intro {{ padding: 32px 0; font-size: 16px; color: #777; line-height: 1.7; border-bottom: 1px solid #e5e5e0; }}
    .archive-section {{ padding: 28px 0 0; }}
    .archive-label {{ font-family: -apple-system, sans-serif; font-size: 11px; letter-spacing: 2px; text-transform: uppercase; color: #bbb; margin-bottom: 16px; }}
    .archive-list {{ list-style: none; padding: 0; }}
    .archive-list li {{ padding: 14px 0; border-bottom: 1px solid #f0f0ea; display: flex; justify-content: space-between; align-items: baseline; }}
    .archive-list li a {{ color: #333; text-decoration: none; font-size: 17px; }}
    .archive-list li a:hover {{ color: #000; }}
    .archive-list .date {{ font-family: -apple-system, sans-serif; font-size: 12px; color: #bbb; white-space: nowrap; margin-left: 16px; }}
    .archive-list .label {{ font-family: -apple-system, sans-serif; font-size: 11px; letter-spacing: 0.5px; color: #999; text-transform: uppercase; }}
  </style>
</head>
<body>
  <header>
    <span class="series-title">The Measured Life</span>
    <p class="byline">An ongoing chronicle by Elena Voss</p>
    <nav class="site-nav"><a href="index.html">Archive</a><a href="about.html">About</a></nav>
  </header>
  <main>
    {hero_html}
    <div class="series-intro">
      What happens when a 37-year-old tech executive decides to transform his health using a custom-built AI platform that tracks everything his body produces? "The Measured Life" is an ongoing chronicle following one man's attempt to change &mdash; tracked by 19 data sources, coached by artificial intelligence, and observed by a journalist who's seen it all. New installments every Wednesday.
    </div>
    <div class="archive-section">
      <div class="archive-label">All Installments</div>
      <ul class="archive-list">
        {entries_html}
      </ul>
    </div>
  </main>
  <footer>
    The Measured Life &middot; A chronicle by Elena Voss &middot; Est. 2026
  </footer>
</body>
</html>'''

s3.put_object(Bucket=BUCKET, Key="blog/index.html", Body=index_html,
              ContentType="text/html; charset=utf-8", CacheControl="max-age=300")
print("  ✓ S3: blog/index.html updated")

# ── 4. Send email ──
print("[4/5] Sending email...")
blog_url = "https://blog.averagejoematt.com/week-02.html"
email_html = f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f5f5f0;font-family:Georgia,'Times New Roman',serif;">
<div style="max-width:600px;margin:24px auto;background:#fafaf9;border-radius:4px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,0.06);">

  <!-- Masthead -->
  <div style="padding:32px 40px 20px;border-bottom:1px solid #e5e5e0;text-align:center;">
    <p style="font-family:-apple-system,sans-serif;font-size:11px;letter-spacing:3px;color:#999;margin:0 0 8px;text-transform:uppercase;">The Measured Life</p>
    <p style="font-family:-apple-system,sans-serif;font-size:13px;color:#666;margin:0;">An ongoing chronicle by Elena Voss</p>
  </div>

  <!-- Title block -->
  <div style="padding:28px 40px 8px;">
    <h1 style="font-size:26px;font-weight:400;color:#1a1a1a;margin:0 0 8px;line-height:1.3;font-style:italic;">"{TITLE}"</h1>
    <p style="font-family:-apple-system,sans-serif;font-size:12px;color:#999;margin:0;">Week {WEEK_NUM} &middot; {DATE_DISPLAY}</p>
    <p style="font-family:-apple-system,sans-serif;font-size:11px;color:#b0b0a8;margin:6px 0 0;">{STATS_LINE}</p>
  </div>

  <!-- Body -->
  <div style="padding:12px 40px 32px;font-size:16px;line-height:1.75;color:#333;">
    <style>
      p {{ margin: 0 0 18px; }}
      blockquote {{ margin: 20px 0; padding: 12px 20px; border-left: 3px solid #d4d4c8; background: #f0f0ea; font-style: italic; color: #555; font-size: 15px; line-height: 1.7; }}
      blockquote strong {{ font-style: normal; color: #333; }}
      hr {{ border: none; border-top: 1px solid #e5e5e0; margin: 28px 0; }}
      .signature {{ text-align: center; color: #999; font-size: 14px; }}
    </style>
    {body_html}
  </div>

  <!-- Footer -->
  <div style="padding:20px 40px;border-top:1px solid #e5e5e0;text-align:center;">
    <p style="font-family:-apple-system,sans-serif;font-size:11px;color:#999;margin:0;">
      Read the full series at <a href="{blog_url}" style="color:#666;">averagejoematt.com/blog</a>
    </p>
  </div>

</div>
</body>
</html>'''

subject = f'The Measured Life — Week {WEEK_NUM}: "{TITLE}"'
ses.send_email(
    FromEmailAddress=SENDER,
    Destination={"ToAddresses": [RECIPIENT]},
    Content={"Simple": {
        "Subject": {"Data": subject, "Charset": "UTF-8"},
        "Body":    {"Html": {"Data": email_html, "Charset": "UTF-8"}},
    }},
)
print(f"  ✓ Email sent: {subject}")

# ── 5. Also fix Week 1 S3 permission (if previous week never published to blog) ──
print("[5/5] Checking Week 1 blog post...")
try:
    s3.head_object(Bucket=BUCKET, Key="blog/week-01.html")
    print("  ✓ Week 1 already on blog")
except:
    # Week 1 was stored in DDB but blog publish failed (AccessDenied)
    # Retrieve from DDB and publish
    try:
        w1_resp = table.get_item(Key={
            "pk": f"USER#{USER_ID}#SOURCE#chronicle",
            "sk": "DATE#2026-02-28",
        })
        w1 = w1_resp.get("Item")
        if w1 and w1.get("content_html"):
            w1_html = f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{w1.get("title", "Untitled")} — The Measured Life</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <header>
    <a href="index.html" class="series-title">The Measured Life</a>
    <p class="byline">An ongoing chronicle by Elena Voss</p>
    <nav class="site-nav"><a href="index.html">Archive</a><a href="about.html">About</a></nav>
  </header>
  <main>
    <article>
      <h1>"{w1.get("title", "Untitled")}"</h1>
      <p class="meta">Week 1 &middot; February 28, 2026</p>
      <div class="body">
        {w1.get("content_html", "")}
      </div>
    </article>
    <nav class="post-nav">
      <a href="week-00.html">&larr; Prologue</a>
      <a href="index.html">All installments</a>
      <a href="week-02.html">Week 2 &rarr;</a>
    </nav>
  </main>
  <footer>
    <p>&copy; 2026 The Measured Life. A chronicle of one man's attempt to change.</p>
  </footer>
</body>
</html>'''
            s3.put_object(Bucket=BUCKET, Key="blog/week-01.html", Body=w1_html,
                          ContentType="text/html; charset=utf-8", CacheControl="max-age=3600")
            print(f"  ✓ Week 1 published to blog (was missing due to earlier AccessDenied)")
        else:
            print("  ⚠ Week 1 not found in DynamoDB")
    except Exception as e:
        print(f"  ⚠ Could not publish Week 1: {e}")

print()
print("All content published successfully!")
PYTHON_SCRIPT

# ── PART 3: CloudFront Invalidation ──────────────────────────────
echo ""
echo "=== PART 3: CloudFront Cache Invalidation ==="
echo ""
aws cloudfront create-invalidation \
  --distribution-id "$BLOG_DIST" \
  --paths "/index.html" "/week-02.html" "/week-01.html" \
  --output json | jq '.Invalidation.Id'
echo "  ✓ CloudFront invalidation started (1-2 min to clear)"

# ── Summary ──────────────────────────────────────────────────────
echo ""
echo "==========================================="
echo "  ✓ Chronicle Week 2 published!"
echo "==========================================="
echo ""
echo "  Lambda:  wednesday-chronicle packaging fixed"
echo "  Email:   Sent to awsdev@mattsusername.com"
echo "  Blog:    https://blog.averagejoematt.com/week-02.html"
echo "  Index:   https://blog.averagejoematt.com/"
echo "  DynamoDB: Week 2 stored in chronicle partition"
echo ""
echo "  Check email inbox + blog in 1-2 minutes."
echo ""
