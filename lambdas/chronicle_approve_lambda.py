"""
Chronicle Approve Lambda — v1.0.0 (FEAT-12)
Handles Matthew's one-click approve / request-changes decisions for Chronicle drafts.

Invoked via Lambda Function URL (HTTPS GET):
  ?date=YYYY-MM-DD&token=<hex32>&action=approve|request_changes

On approve:
  1. Validates token against DynamoDB draft record
  2. Writes pre-built blog post + index HTML to S3 (blog/)
  3. Writes pre-built journal post + posts.json to S3 (site/journal/)
  4. Creates CloudFront invalidation for affected paths
  5. Updates DynamoDB status: draft → published
  6. Invokes chronicle-email-sender to deliver to subscribers
  7. Returns HTML confirmation page

On request_changes:
  1. Validates token
  2. Updates DynamoDB status: draft → changes_requested
  3. Returns HTML confirmation page (no email sent; Matthew regenerates manually)

Security:
  - Token is a 32-byte (64-char hex) secret generated at draft creation time.
  - Each draft has a unique token stored in DynamoDB and included only in the
    preview email sent to RECIPIENT. Not guessable, not reusable.
  - Function URL has AuthType=NONE (token provides application-layer auth).
  - DynamoDB status check prevents double-approvals.
"""

import json
import os
import logging
import urllib.parse
import boto3
from datetime import datetime, timezone

try:
    from platform_logger import get_logger
    logger = get_logger("chronicle-approve")
except ImportError:
    logger = logging.getLogger("chronicle-approve")
    logger.setLevel(logging.INFO)

REGION     = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET  = os.environ["S3_BUCKET"]
USER_ID    = os.environ["USER_ID"]
CF_DIST_ID = os.environ.get("CF_DIST_ID", "E3S424OXQZ8NBE")
CHRONICLE_EMAIL_SENDER_ARN = os.environ.get("CHRONICLE_EMAIL_SENDER_ARN", "")

CHRONICLE_PK = f"USER#{USER_ID}#SOURCE#chronicle"

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table    = dynamodb.Table(TABLE_NAME)
s3       = boto3.client("s3", region_name=REGION)
cf       = boto3.client("cloudfront", region_name="us-east-1")  # CF is global, endpoint is us-east-1
lam      = boto3.client("lambda", region_name=REGION)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _html_response(status_code: int, title: str, body: str) -> dict:
    """Return a Lambda Function URL response with a minimal HTML page."""
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{title}</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, sans-serif;
      background: #0f0f0f; color: #f5f5f5;
      display: flex; align-items: center; justify-content: center;
      min-height: 100vh; margin: 0; padding: 24px; box-sizing: border-box;
    }}
    .card {{
      background: #1a1a1a; border-radius: 12px; padding: 48px;
      max-width: 500px; width: 100%; text-align: center;
    }}
    .icon {{ font-size: 48px; margin-bottom: 16px; }}
    h1 {{ font-size: 24px; font-weight: 600; margin: 0 0 12px; color: #fff; }}
    p {{ color: #aaa; line-height: 1.6; margin: 0 0 24px; font-size: 15px; }}
    a {{ color: #f59e0b; text-decoration: none; font-size: 14px; }}
  </style>
</head>
<body>
  <div class="card">
    {body}
    <a href="https://averagejoematt.com/chronicle/">View the Chronicle →</a>
  </div>
</body>
</html>"""
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "text/html; charset=utf-8"},
        "body": html,
    }


def _get_draft(date_str: str) -> dict | None:
    """Read the draft installment from DynamoDB by date."""
    try:
        resp = table.get_item(Key={"pk": CHRONICLE_PK, "sk": f"DATE#{date_str}"})
        item = resp.get("Item")
        if not item:
            logger.warning(f"No installment found for date {date_str}")
            return None
        return item
    except Exception as exc:
        logger.error("DDB get_item failed: %s", exc)
        return None


def _publish_to_s3(item: dict) -> list[str]:
    """Write pre-built HTML artifacts to S3. Returns list of invalidated CF paths."""
    invalidation_paths = []

    # Blog post
    blog_post_key  = item.get("draft_blog_post_key", "")
    blog_post_html = item.get("draft_blog_post_html", "")
    blog_index_html = item.get("draft_blog_index_html", "")

    if blog_post_key and blog_post_html:
        s3.put_object(
            Bucket=S3_BUCKET, Key=blog_post_key,
            Body=blog_post_html, ContentType="text/html",
            CacheControl="max-age=3600",
        )
        logger.info("S3: wrote %s", blog_post_key)
        invalidation_paths.append("/" + blog_post_key)

    if blog_index_html:
        s3.put_object(
            Bucket=S3_BUCKET, Key="blog/index.html",
            Body=blog_index_html, ContentType="text/html",
            CacheControl="max-age=300",
        )
        logger.info("S3: wrote blog/index.html")
        invalidation_paths.append("/blog/")
        invalidation_paths.append("/blog/index.html")

    # Journal post
    journal_post_key  = item.get("draft_journal_post_key", "")
    journal_post_html = item.get("draft_journal_post_html", "")
    journal_posts_json = item.get("draft_journal_posts_json", "")

    if journal_post_key and journal_post_html:
        s3.put_object(
            Bucket=S3_BUCKET, Key=journal_post_key,
            Body=journal_post_html.encode("utf-8"),
            ContentType="text/html; charset=utf-8",
            CacheControl="max-age=300",
        )
        logger.info("S3: wrote %s", journal_post_key)
        # /generated/journal/posts/week-NN/index.html → /journal/posts/week-NN/*
        week_dir = "/".join(journal_post_key.split("/")[1:-1])  # strip "generated/" prefix and filename
        invalidation_paths.append(f"/{week_dir}/*")

    if journal_posts_json:
        s3.put_object(
            Bucket=S3_BUCKET, Key="generated/journal/posts.json",
            Body=journal_posts_json.encode("utf-8"),
            ContentType="application/json",
            CacheControl="max-age=300",
        )
        logger.info("S3: wrote generated/journal/posts.json")
        invalidation_paths.append("/journal/posts.json")

    return invalidation_paths


def _invalidate_cloudfront(paths: list[str]) -> None:
    """Create a CloudFront invalidation for the given paths."""
    if not paths or not CF_DIST_ID:
        return
    # Always include the chronicle page
    all_paths = list(set(paths + ["/chronicle/*", "/journal/*"]))
    try:
        cf.create_invalidation(
            DistributionId=CF_DIST_ID,
            InvalidationBatch={
                "Paths": {"Quantity": len(all_paths), "Items": all_paths},
                "CallerReference": f"chronicle-approve-{datetime.now(timezone.utc).isoformat()}",
            },
        )
        logger.info("CloudFront invalidation created for %d paths", len(all_paths))
    except Exception as exc:
        logger.warning("CloudFront invalidation failed (non-fatal): %s", exc)


def _mark_published(date_str: str) -> None:
    """Update DynamoDB status to published and clear the approval token."""
    try:
        table.update_item(
            Key={"pk": CHRONICLE_PK, "sk": f"DATE#{date_str}"},
            UpdateExpression=(
                "SET #s = :published, approved_at = :now "
                "REMOVE approval_token, draft_blog_post_html, draft_blog_index_html, "
                "draft_journal_post_html, draft_journal_posts_json, draft_email_html"
            ),
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":published": "published",
                ":now": datetime.now(timezone.utc).isoformat(),
            },
        )
        logger.info("DDB: installment %s marked as published", date_str)
    except Exception as exc:
        logger.error("DDB update failed: %s", exc)


def _mark_changes_requested(date_str: str) -> None:
    """Update DynamoDB status to changes_requested."""
    try:
        table.update_item(
            Key={"pk": CHRONICLE_PK, "sk": f"DATE#{date_str}"},
            UpdateExpression="SET #s = :cr, changes_requested_at = :now",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":cr": "changes_requested",
                ":now": datetime.now(timezone.utc).isoformat(),
            },
        )
        logger.info("DDB: installment %s marked as changes_requested", date_str)
    except Exception as exc:
        logger.error("DDB update failed: %s", exc)


def _invoke_email_sender() -> None:
    """Async-invoke the chronicle-email-sender Lambda to deliver to subscribers."""
    if not CHRONICLE_EMAIL_SENDER_ARN:
        logger.warning("CHRONICLE_EMAIL_SENDER_ARN not set — subscriber send skipped")
        return
    try:
        lam.invoke(
            FunctionName=CHRONICLE_EMAIL_SENDER_ARN,
            InvocationType="Event",  # async
            Payload=json.dumps({"source": "chronicle-approve"}).encode(),
        )
        logger.info("Invoked chronicle-email-sender (async)")
    except Exception as exc:
        logger.warning("Failed to invoke chronicle-email-sender (non-fatal): %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# HANDLER
# ─────────────────────────────────────────────────────────────────────────────

def lambda_handler(event, context):
    """Handle GET requests from the preview email approve/request_changes links."""
    logger.info("chronicle-approve: invoked")
    try:
        return _handle(event)
    except Exception as exc:
        logger.exception("chronicle-approve: unhandled error: %s", exc)
        return _html_response(500, "Error",
            '<div class="icon">⚠️</div>'
            '<h1>Something went wrong</h1>'
            '<p>An unexpected error occurred. Check CloudWatch logs for details.</p>')


def _handle(event: dict) -> dict:
    """Inner handler logic, wrapped by lambda_handler for top-level exception catching."""
    # Parse query string params from Function URL event
    qs = event.get("queryStringParameters") or {}
    date_str = qs.get("date", "").strip()
    token    = qs.get("token", "").strip()
    action   = qs.get("action", "").strip().lower()

    # ── Validate inputs ──────────────────────────────────────────────────────
    if not date_str or not token or action not in ("approve", "request_changes"):
        return _html_response(400, "Invalid Request",
            '<div class="icon">⚠️</div>'
            '<h1>Invalid Link</h1>'
            '<p>This approval link is missing required parameters. '
            'Check the preview email for the correct link.</p>')

    # ── Load draft ───────────────────────────────────────────────────────────
    item = _get_draft(date_str)
    if not item:
        return _html_response(404, "Not Found",
            '<div class="icon">🔍</div>'
            '<h1>Installment Not Found</h1>'
            f'<p>No Chronicle draft found for {date_str}.</p>')

    current_status = item.get("status", "")
    stored_token   = item.get("approval_token", "")
    week_num       = item.get("week_number", "?")
    title          = item.get("title", "Untitled")

    # ── Already processed? ───────────────────────────────────────────────────
    if current_status == "published":
        return _html_response(200, "Already Published",
            f'<div class="icon">✅</div>'
            f'<h1>Already Published</h1>'
            f'<p>Week {week_num}: &ldquo;{title}&rdquo; was already published.</p>')

    if current_status == "changes_requested":
        return _html_response(200, "Changes Already Requested",
            f'<div class="icon">📝</div>'
            f'<h1>Changes Already Requested</h1>'
            f'<p>Week {week_num} is queued for regeneration. '
            f'Re-run the wednesday-chronicle Lambda to generate a new draft.</p>')

    # ── Validate token ───────────────────────────────────────────────────────
    import hmac
    if not stored_token or not hmac.compare_digest(stored_token, token):
        logger.warning("chronicle-approve: token mismatch for %s", date_str)
        return _html_response(403, "Invalid Token",
            '<div class="icon">🔒</div>'
            '<h1>Invalid Token</h1>'
            '<p>The approval token is incorrect or has expired. '
            'Use the link from the preview email.</p>')

    # ── Perform action ───────────────────────────────────────────────────────
    if action == "approve":
        logger.info("chronicle-approve: APPROVING Week %s (%s)", week_num, date_str)

        invalidation_paths = _publish_to_s3(item)
        _invalidate_cloudfront(invalidation_paths)
        _mark_published(date_str)
        _invoke_email_sender()

        return _html_response(200, "Published!",
            f'<div class="icon">🎉</div>'
            f'<h1>Published!</h1>'
            f'<p>Week {week_num}: &ldquo;{title}&rdquo; is now live on averagejoematt.com.<br>'
            f'Subscribers will receive their email shortly.</p>')

    else:  # request_changes
        logger.info("chronicle-approve: CHANGES REQUESTED for Week %s (%s)", week_num, date_str)
        _mark_changes_requested(date_str)

        return _html_response(200, "Changes Requested",
            f'<div class="icon">📝</div>'
            f'<h1>Changes Requested</h1>'
            f'<p>Week {week_num}: &ldquo;{title}&rdquo; has been flagged for revision.<br>'
            f'Re-run the wednesday-chronicle Lambda (with a new prompt if needed) to generate a new draft.</p>')
