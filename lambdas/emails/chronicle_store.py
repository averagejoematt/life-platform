"""lambdas/emails/chronicle_store.py — DynamoDB installment persistence, the
non-blocking "pending week" marker, and the FEAT-12 preview email, split out of
wednesday_chronicle_lambda.py (#1654). Facade state via the `_g` hand-off."""

import json
from datetime import datetime, timezone


def store_installment(
    date_str,
    week_num,
    title,
    stats_line,
    raw_markdown,
    body_html,
    themes,
    has_board,
    confidence_level="MEDIUM",
    confidence_badge_html="",  # BS-05
    status="published",
    approval_token=None,
    draft_journal_post_html=None,
    draft_journal_post_key=None,
    draft_journal_posts_json=None,
    draft_email_html=None,
    draft_recap_json=None,
    draft_share_kit_json=None,
    weekly_signal_data=None,
    weekly_signal_wins_losses=None,
    weekly_signal_board_quote=None,
    *,
    _g,
):
    """Store installment in DynamoDB for continuity and journal generation.

    FEAT-12: In preview mode, status="draft" with approval_token + pre-built HTML blobs stored
    so chronicle-approve Lambda can publish to S3 without re-generating content.
    """
    table = _g["table"]
    USER_ID = _g["USER_ID"]
    logger = _g["logger"]
    try:
        item = {
            "pk": f"USER#{USER_ID}#SOURCE#chronicle",
            "sk": f"DATE#{date_str}",
            "date": date_str,
            "source": "chronicle",
            "week_number": week_num,
            "title": title,
            "subtitle": f"Week {week_num} of The Measured Life",
            "stats_line": stats_line,
            "content_markdown": raw_markdown,
            "content_html": body_html,
            "word_count": len(raw_markdown.split()),
            "has_board_interview": has_board,
            "series_title": "The Measured Life",
            "author": "Elena Voss",
            "_confidence_level": confidence_level,  # BS-05
            "_confidence_badge_html": confidence_badge_html,  # BS-05 — used by chronicle-email-sender
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
        }
        if approval_token:
            item["approval_token"] = approval_token
        if draft_journal_post_html:
            item["draft_journal_post_html"] = draft_journal_post_html
        if draft_journal_post_key:
            item["draft_journal_post_key"] = draft_journal_post_key
        if draft_journal_posts_json:
            item["draft_journal_posts_json"] = draft_journal_posts_json
        if draft_email_html:
            item["draft_email_html"] = draft_email_html
        # Phase 3: the "previously on" recap, built now but committed to RECAP#latest
        # only when this week is published (chronicle_approve._commit_recap).
        if draft_recap_json:
            item["draft_recap_json"] = draft_recap_json
        # #405: the share kit, built at draft time, written to S3 at approve/publish.
        if draft_share_kit_json:
            item["draft_share_kit_json"] = draft_share_kit_json
        if weekly_signal_data:
            item["weekly_signal_data"] = json.dumps(weekly_signal_data) if isinstance(weekly_signal_data, dict) else weekly_signal_data
        if weekly_signal_wins_losses:
            item["weekly_signal_wins_losses"] = (
                json.dumps(weekly_signal_wins_losses) if isinstance(weekly_signal_wins_losses, dict) else weekly_signal_wins_losses
            )
        if weekly_signal_board_quote:
            item["weekly_signal_board_quote"] = weekly_signal_board_quote
        table.put_item(Item=item)
        logger.info(f"Installment stored: Week {week_num} (status={status})")
        # #1441: generation-time archive — the final installment markdown (both
        # the draft/preview and direct-publish paths land here) to
        # generated/qa_archive/. Fail-soft inside the module.
        try:
            import qa_archive

            qa_archive.archive_text(
                "chronicle",
                raw_markdown,
                meta={"week_number": week_num, "title": title, "status": status, "date": date_str},
            )
        except Exception as qa_e:  # noqa: BLE001 — the archive is never load-bearing
            logger.warning(f"[chronicle] qa_archive failed (non-fatal): {qa_e}")
    except Exception as e:
        logger.warning(f"Failed to store installment: {e}")


def _set_chronicle_pending(week_num, reason, display, *, _g):
    """Record a non-blocking 'pending installment' marker on generated/journal/posts.json
    so the Chronicle listing can say WHY no new week landed instead of just going stale
    (#803 — the same silent-skip fix already shipped for the Panel podcast, see
    coach_panel_podcast_lambda._set_pending, 2026-06-20). Called when a week's draft is
    generated and then withheld (budget guard, privacy gate) rather than published — the
    week number can legitimately advance past a held week, so the marker also tells a
    reader whose numbering was skipped and why, rather than leaving a silent gap.

    A successful publish rewrites posts.json via publish_to_journal() (which never writes
    a `pending` key), so the marker clears itself the next time a week actually ships.
    Fail-open: surfacing a pending state must never break the run."""
    s3 = _g["s3"]
    S3_BUCKET = _g["S3_BUCKET"]
    logger = _g["logger"]
    try:
        try:
            doc = json.loads(s3.get_object(Bucket=S3_BUCKET, Key="generated/journal/posts.json")["Body"].read())
        except Exception:
            doc = {"posts": []}
        doc["pending"] = {
            "week": week_num,
            "reason": reason,
            "display": display,
            "noted_at": datetime.now(timezone.utc).isoformat(),
        }
        s3.put_object(
            Bucket=S3_BUCKET,
            Key="generated/journal/posts.json",
            Body=json.dumps(doc, indent=2).encode("utf-8"),
            ContentType="application/json",
            CacheControl="max-age=300",
        )
        logger.info(f"[chronicle] pending marker set: week={week_num} reason={reason}")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[chronicle] _set_chronicle_pending failed (non-fatal): {e}")


def _send_preview_email(title, week_num, date_str, approval_token, email_html, kit_block="", *, _g):
    """Send preview email to RECIPIENT with Approve / Request Changes links.

    The approve link goes to APPROVE_LAMBDA_URL with ?date=, token=, action=approve.
    The request_changes link uses action=request_changes.

    #405: `kit_block` is the copy-paste share-kit HTML — surfaced right in this approval
    email so posting is a 60-second paste (or ignored). It's injected before </body>.
    """
    APPROVE_LAMBDA_URL = _g["APPROVE_LAMBDA_URL"]
    ses = _g["ses"]
    SENDER = _g["SENDER"]
    RECIPIENT = _g["RECIPIENT"]
    logger = _g["logger"]
    if not APPROVE_LAMBDA_URL:
        logger.warning("FEAT-12: APPROVE_LAMBDA_URL not set — preview email links will be dead")

    base_url = APPROVE_LAMBDA_URL.rstrip("/")
    approve_url = f"{base_url}?date={date_str}&token={approval_token}&action=approve"
    changes_url = f"{base_url}?date={date_str}&token={approval_token}&action=request_changes"

    preview_banner = f"""
<div style="background:#1a1a1a;color:#fff;padding:20px 32px;font-family:-apple-system,sans-serif;margin-bottom:0;border-bottom:3px solid #f59e0b;">
  <p style="margin:0 0 6px;font-size:12px;letter-spacing:2px;text-transform:uppercase;color:#f59e0b;">PREVIEW — Not yet published</p>
  <p style="margin:0 0 16px;font-size:14px;color:#ccc;">Week {week_num}: &ldquo;{title}&rdquo; is ready for review.</p>
  <a href="{approve_url}"
     style="display:inline-block;background:#16a34a;color:#fff;padding:12px 28px;border-radius:6px;text-decoration:none;font-size:14px;font-weight:600;margin-right:12px;">
    ✓ Approve &amp; Publish
  </a>
  <a href="{changes_url}"
     style="display:inline-block;background:#dc2626;color:#fff;padding:12px 28px;border-radius:6px;text-decoration:none;font-size:14px;font-weight:600;">
    ✗ Request Changes
  </a>
</div>
"""
    # Inject the preview banner at the top of the email body
    preview_email = email_html.replace("<body>", "<body>" + preview_banner, 1)
    if "<body>" not in email_html:
        preview_email = preview_banner + email_html
    # #405: surface the share kit near the end of the email (after the read).
    if kit_block:
        if "</body>" in preview_email:
            preview_email = preview_email.replace("</body>", kit_block + "</body>", 1)
        else:
            preview_email = preview_email + kit_block

    subject = f'[PREVIEW] The Measured Life — Week {week_num}: "{title}"'
    try:
        ses.send_email(
            FromEmailAddress=SENDER,
            Destination={"ToAddresses": [RECIPIENT]},
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Html": {"Data": preview_email, "Charset": "UTF-8"}},
                }
            },
        )
        logger.info(f"FEAT-12: Preview email sent for Week {week_num}")
    except Exception as e:
        logger.error(f"FEAT-12: Failed to send preview email: {e}")
        raise
