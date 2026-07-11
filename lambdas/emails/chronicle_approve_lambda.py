"""
Chronicle Approve Lambda — v1.0.0 (FEAT-12)
Handles Matthew's one-click approve / request-changes decisions for Chronicle drafts.

Invoked via Lambda Function URL (HTTPS GET):
  ?date=YYYY-MM-DD&token=<hex32>&action=approve|request_changes

On approve:
  1. Validates token against DynamoDB draft record
  2. Writes pre-built journal post + posts.json to S3 (generated/journal/)
  3. Creates CloudFront invalidation for affected paths
  4. Updates DynamoDB status: draft → published
  5. Invokes chronicle-email-sender to deliver to subscribers
  6. Returns HTML confirmation page

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
import logging
import os
from datetime import datetime, timezone

import boto3

try:
    from platform_logger import get_logger

    logger = get_logger("chronicle-approve")
except ImportError:
    logger = logging.getLogger("chronicle-approve")
    logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET = os.environ["S3_BUCKET"]
USER_ID = os.environ.get("USER_ID", "matthew")
CF_DIST_ID = os.environ.get("CF_DIST_ID", "E3S424OXQZ8NBE")
CHRONICLE_EMAIL_SENDER_ARN = os.environ.get("CHRONICLE_EMAIL_SENDER_ARN", "")
# #537: Elena's post-publish state extraction (name, not ARN — same account/region).
ELENA_STATE_UPDATER_NAME = os.environ.get("ELENA_STATE_UPDATER_NAME", "elena-state-updater")
# #734: the weekly Panel podcast is EVENT-DRIVEN — a published chronicle is the
# "this week earned an episode" trigger (the old standing Friday cron was retired).
COACH_PANEL_PODCAST_NAME = os.environ.get("COACH_PANEL_PODCAST_NAME", "coach-panel-podcast")

CHRONICLE_PK = f"USER#{USER_ID}#SOURCE#chronicle"

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)
s3 = boto3.client("s3", region_name=REGION)
cf = boto3.client("cloudfront", region_name="us-east-1")  # CF is global, endpoint is us-east-1
lam = boto3.client("lambda", region_name=REGION)


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

    # Journal post
    journal_post_key = item.get("draft_journal_post_key", "")
    journal_post_html = item.get("draft_journal_post_html", "")
    journal_posts_json = item.get("draft_journal_posts_json", "")

    if journal_post_key and journal_post_html:
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=journal_post_key,
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
            Bucket=S3_BUCKET,
            Key="generated/journal/posts.json",
            Body=journal_posts_json.encode("utf-8"),
            ContentType="application/json",
            CacheControl="max-age=300",
        )
        logger.info("S3: wrote generated/journal/posts.json")
        invalidation_paths.append("/journal/posts.json")

    # #405: the per-chronicle share kit → its stable generated location (served via
    # the already-routed /moments/* behavior). Built at draft time; written on publish
    # so it never goes live ahead of the post it links to. Fail-soft.
    share_kit_json = item.get("draft_share_kit_json", "")
    if share_kit_json:
        try:
            kit = json.loads(share_kit_json) if isinstance(share_kit_json, str) else share_kit_json
            slug = (str(kit.get("canonical_url", "")).rstrip("/").split("/") or ["post"])[-1] or "post"
            kit_key = f"generated/moments/share-kits/{slug}/kit.json"
            s3.put_object(
                Bucket=S3_BUCKET,
                Key=kit_key,
                Body=(share_kit_json if isinstance(share_kit_json, str) else json.dumps(kit)).encode("utf-8"),
                ContentType="application/json",
                CacheControl="max-age=300",
            )
            logger.info("S3: wrote %s", kit_key)
            invalidation_paths.append(f"/moments/share-kits/{slug}/kit.json")
        except Exception as exc:
            logger.warning("share kit write failed (non-fatal): %s", exc)

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
                "REMOVE approval_token, "
                "draft_journal_post_html, draft_journal_posts_json, draft_email_html, draft_recap_json, "
                "draft_share_kit_json"
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


def _commit_recap(item: dict) -> None:
    """Phase 3: commit the week's pre-built 'previously on' recap to RECAP#latest +
    RECAP#{date} when the week is actually published. The recap is grounded in
    published history, so it only goes live alongside the week it summarizes.
    Fail-soft — a recap commit failure never blocks publishing the installment."""
    raw = item.get("draft_recap_json")
    if not raw:
        return
    try:
        recap = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(recap, dict) or not recap.get("story_so_far"):
            return
        date_str = item.get("date") or str(item.get("sk", "")).replace("DATE#", "")
        base = dict(recap)
        base["pk"] = CHRONICLE_PK
        base["source"] = "chronicle_recap"
        base["status"] = "published"
        base["generated_at"] = datetime.now(timezone.utc).isoformat()
        for sk in (f"RECAP#{date_str}", "RECAP#latest"):
            row = dict(base)
            row["sk"] = sk
            table.put_item(Item=row)
        logger.info("[recap] committed RECAP#latest + RECAP#%s on publish", date_str)
    except Exception as exc:
        logger.warning("[recap] _commit_recap failed (non-fatal): %s", exc)


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


def _invoke_elena_state_updater(date_str: str) -> None:
    """#537: async-invoke Elena's post-publish state extraction. Runs ONLY on the
    publish paths (approve click + stale-draft sweep) — never at draft time, so a
    rejected draft can't poison her memory. Fail-soft: a missed invoke just means
    her notebook ages a week."""
    try:
        lam.invoke(
            FunctionName=ELENA_STATE_UPDATER_NAME,
            InvocationType="Event",  # async
            Payload=json.dumps({"date": date_str}).encode(),
        )
        logger.info("Invoked elena-state-updater for %s (async)", date_str)
    except Exception as exc:
        logger.warning("Failed to invoke elena-state-updater (non-fatal): %s", exc)


def _invoke_coach_panel_podcast() -> None:
    """#734: async-invoke the weekly Panel podcast now that a chronicle has
    published — the event-driven replacement for the retired Friday cron ("ships
    only when a week earns an episode"). Sends an empty-shaped event so the Panel's
    own reset-proof week-selection (_select_week_post: latest current-cycle post by
    date) runs UNCHANGED and it self-gates (idempotent + publish-or-HOLD). Fail-soft:
    a missed invoke just means no episode this cycle, never a broken approval."""
    try:
        lam.invoke(
            FunctionName=COACH_PANEL_PODCAST_NAME,
            InvocationType="Event",  # async
            Payload=json.dumps({"source": "chronicle-approve"}).encode(),
        )
        logger.info("Invoked coach-panel-podcast (async, event-driven)")
    except Exception as exc:
        logger.warning("Failed to invoke coach-panel-podcast (non-fatal): %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# AUTO-PUBLISH SWEEP (SS-01) — the self-sustaining fail-safe: a chronicle draft must
# never stay dark just because the approve link wasn't clicked. A daily schedule
# sweeps drafts older than the review window and publishes them via the SAME path the
# approve click uses (privacy/vice guards already ran at draft time). "Editor review
# window + a fail-safe" — how a real team keeps the weekly running.
# ─────────────────────────────────────────────────────────────────────────────


def _find_stale_drafts(hours: float, max_days: float) -> list[dict]:
    """Chronicle DATE# drafts inside the auto-publish WINDOW: older than the review
    window (`hours`) but newer than `max_days`. The upper bound is the safety: a draft
    abandoned for weeks (changes-requested, superseded, a pre-genesis leftover) must NOT
    be resurrected — only a recently-unapproved one (the 'forgot to click' case)."""
    from boto3.dynamodb.conditions import Key

    now = datetime.now(timezone.utc).timestamp()
    stale_before = now - hours * 3600.0  # must be older than this
    too_old_before = now - max_days * 86400.0  # but newer than this
    out = []
    try:
        resp = table.query(KeyConditionExpression=Key("pk").eq(CHRONICLE_PK) & Key("sk").begins_with("DATE#"))
    except Exception as exc:
        logger.error("sweep: DDB query failed: %s", exc)
        return out
    for it in resp.get("Items", []):
        if it.get("status") != "draft":
            continue
        ga = str(it.get("generated_at") or "")
        try:
            ts = datetime.fromisoformat(ga.replace("Z", "+00:00")).timestamp()
        except Exception:
            continue  # no/unparseable timestamp → skip (don't auto-publish a malformed record)
        if too_old_before <= ts <= stale_before:
            out.append(it)
    return out


def _sweep_stale_drafts(hours: float, max_days: float = 10.0, dry_run: bool = False) -> list[dict]:
    """Publish every stale draft via the approve path. Returns what was (would be) published."""
    drafts = _find_stale_drafts(hours, max_days)
    published = []
    for item in drafts:
        date_str = item.get("date") or str(item.get("sk", "")).replace("DATE#", "")
        wk = item.get("week_number", "?")
        if dry_run:
            published.append({"date": date_str, "week": wk, "dry_run": True})
            continue
        try:
            paths = _publish_to_s3(item)
            _invalidate_cloudfront(paths)
            _commit_recap(item)  # Phase 3: commit the "previously on" recap with the week
            _mark_published(date_str)
            _invoke_elena_state_updater(date_str)  # #537: published → update her memory
            published.append({"date": date_str, "week": wk})
            logger.info("sweep: auto-published Week %s (%s) — no approval within %sh", wk, date_str, hours)
        except Exception as exc:
            logger.warning("sweep: auto-publish failed for %s: %s", date_str, exc)
    if published and not dry_run:
        _invoke_email_sender()  # one subscriber-delivery trigger for the batch
        _invoke_coach_panel_podcast()  # #734: a published week earns a Panel episode
    logger.info("chronicle auto-publish sweep: %d draft(s) handled (hours=%s, dry_run=%s)", len(published), hours, dry_run)
    return published


# ─────────────────────────────────────────────────────────────────────────────
# HANDLER
# ─────────────────────────────────────────────────────────────────────────────


def lambda_handler(event: dict, context) -> dict:
    """Approve/request-changes (Function-URL GET) — or a scheduled auto-publish sweep."""
    logger.info("chronicle-approve: invoked")
    # SS-01 — scheduled sweep (EventBridge sends {"sweep": true} or source=aws.events).
    if isinstance(event, dict) and (event.get("sweep") or event.get("source") == "aws.events"):
        hours = float(os.environ.get("CHRONICLE_AUTOPUBLISH_HOURS", "48"))
        max_days = float(os.environ.get("CHRONICLE_AUTOPUBLISH_MAX_DAYS", "10"))
        published = _sweep_stale_drafts(hours, max_days, dry_run=bool(event.get("dry_run")))
        return {"statusCode": 200, "swept": published}
    try:
        return _handle(event)
    except Exception as exc:
        logger.exception("chronicle-approve: unhandled error: %s", exc)
        return _html_response(
            500,
            "Error",
            '<div class="icon">⚠️</div>'
            "<h1>Something went wrong</h1>"
            "<p>An unexpected error occurred. Check CloudWatch logs for details.</p>",
        )


def _handle(event: dict) -> dict:
    """Inner handler logic, wrapped by lambda_handler for top-level exception catching."""
    # Parse query string params from Function URL event
    qs = event.get("queryStringParameters") or {}
    date_str = qs.get("date", "").strip()
    token = qs.get("token", "").strip()
    action = qs.get("action", "").strip().lower()

    # ── Validate inputs ──────────────────────────────────────────────────────
    if not date_str or not token or action not in ("approve", "request_changes"):
        return _html_response(
            400,
            "Invalid Request",
            '<div class="icon">⚠️</div>'
            "<h1>Invalid Link</h1>"
            "<p>This approval link is missing required parameters. "
            "Check the preview email for the correct link.</p>",
        )

    # ── Load draft ───────────────────────────────────────────────────────────
    item = _get_draft(date_str)
    if not item:
        return _html_response(
            404,
            "Not Found",
            '<div class="icon">🔍</div>' "<h1>Installment Not Found</h1>" f"<p>No Chronicle draft found for {date_str}.</p>",
        )

    current_status = item.get("status", "")
    stored_token = item.get("approval_token", "")
    week_num = item.get("week_number", "?")
    title = item.get("title", "Untitled")

    # ── Already processed? ───────────────────────────────────────────────────
    if current_status == "published":
        return _html_response(
            200,
            "Already Published",
            f'<div class="icon">✅</div>'
            f"<h1>Already Published</h1>"
            f"<p>Week {week_num}: &ldquo;{title}&rdquo; was already published.</p>",
        )

    if current_status == "changes_requested":
        return _html_response(
            200,
            "Changes Already Requested",
            f'<div class="icon">📝</div>'
            f"<h1>Changes Already Requested</h1>"
            f"<p>Week {week_num} is queued for regeneration. "
            f"Re-run the wednesday-chronicle Lambda to generate a new draft.</p>",
        )

    # ── Validate token ───────────────────────────────────────────────────────
    import hmac

    if not stored_token or not hmac.compare_digest(stored_token, token):
        logger.warning("chronicle-approve: token mismatch for %s", date_str)
        return _html_response(
            403,
            "Invalid Token",
            '<div class="icon">🔒</div>'
            "<h1>Invalid Token</h1>"
            "<p>The approval token is incorrect or has expired. "
            "Use the link from the preview email.</p>",
        )

    # ── Perform action ───────────────────────────────────────────────────────
    if action == "approve":
        logger.info("chronicle-approve: APPROVING Week %s (%s)", week_num, date_str)

        invalidation_paths = _publish_to_s3(item)
        _invalidate_cloudfront(invalidation_paths)
        _commit_recap(item)  # Phase 3: commit the "previously on" recap with the week
        _mark_published(date_str)
        _invoke_email_sender()
        _invoke_elena_state_updater(date_str)  # #537: published → update her memory
        _invoke_coach_panel_podcast()  # #734: a published week earns a Panel episode

        return _html_response(
            200,
            "Published!",
            f'<div class="icon">🎉</div>'
            f"<h1>Published!</h1>"
            f"<p>Week {week_num}: &ldquo;{title}&rdquo; is now live on averagejoematt.com.<br>"
            f"Subscribers will receive their email shortly.</p>",
        )

    else:  # request_changes
        logger.info("chronicle-approve: CHANGES REQUESTED for Week %s (%s)", week_num, date_str)
        _mark_changes_requested(date_str)

        return _html_response(
            200,
            "Changes Requested",
            f'<div class="icon">📝</div>'
            f"<h1>Changes Requested</h1>"
            f"<p>Week {week_num}: &ldquo;{title}&rdquo; has been flagged for revision.<br>"
            f"Re-run the wednesday-chronicle Lambda (with a new prompt if needed) to generate a new draft.</p>",
        )
