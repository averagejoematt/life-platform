"""
ai_review_pack_lambda.py — Weekly AI review-pack email (#1442, QA strategy D3).

The human editorial plane (plane 4 of the QA strategy, epic #1425). AI generations
are gate-checked at write time (ADR-104 grounding gate) and archived at generation
time (#1441 / D2 — `lambdas/qa_archive.py`), but nothing guaranteed a *human*
eyeball over the week's actual AI output — review was ad-hoc screenshot archaeology.

This Lambda curates ONE weekly email: for the trailing 7 days it reads the D2
archive (generated/qa_archive/text/ + .../screenshots/) and lays out every AI
generation — Chronicle, Board answers, Coach commentary, State of Matthew, Field
notes, Coach memoirs — as a scannable digest with an inline snippet and a link to
the full archived object. One email = a guaranteed weekly human read of every AI
surface.

Design notes:
  * READ-ONLY over the archive. It curates already-generated, already-gate-passed
    text — it makes NO Bedrock calls, so it needs no ai-keys/Bedrock grant and no
    budget-tier gate (a review of what already shipped can never be a budget risk).
  * The archive is S3-private (generated/qa_archive/ is NOT routed by CloudFront —
    web_stack only forwards specific /generated sub-paths). So the "link" for each
    generation is an AWS S3 console deep-link (auth-gated), not a public URL — the
    honest, no-new-exposure choice for an internal operator email.
  * Screenshots are the daily visual-qa renders the D2 leg uploads. Per its own
    caveat these are daily-sweep captures (what a reader saw that day), not
    per-generation captures — the email says so.
  * Degrades gracefully: a surface that generated nothing is shown as an explicit
    "nothing this week" note; a totally-quiet week still sends (the weekly eyeball
    is the point). A single corrupt archived object is skipped and counted, never
    fatal — the editorial email is the priority.

Schedule: Sunday 18:00 UTC (fixed, no DST drift) — after the Sunday weekly-digest
(16:00 UTC), covering the week just ended.

Liveness: operator-email class (a missing Sunday issue is noticed by its reader),
dated-exempt in tests/test_heartbeat_completeness.py (#1455).
"""

import html
import logging
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import boto3
import qa_archive

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
BUCKET = os.environ.get("BUCKET_NAME", "matthew-life-platform")
RECIPIENT = os.environ.get("EMAIL_RECIPIENT", "lifeplatform@mattsusername.com")
SENDER = os.environ.get("EMAIL_SENDER", "lifeplatform@mattsusername.com")
WINDOW_DAYS = int(os.environ.get("REVIEW_WINDOW_DAYS", "7"))

# Surface render order + human labels. Keyed by the qa_archive surface ids
# (lambdas/qa_archive.SURFACES) so a new surface there shows up here the moment
# it archives — unknown surfaces fall through to a title-cased label.
SURFACE_ORDER = ("chronicle", "state_of_matthew", "coach_brief", "board_ask", "field_notes", "memoir")
SURFACE_LABELS = {
    "chronicle": "Chronicle",
    "state_of_matthew": "State of Matthew",
    "coach_brief": "Coach Commentary",
    "board_ask": "Board Answers",
    "field_notes": "Field Notes",
    "memoir": "Coach Memoirs",
}
SURFACE_ICONS = {
    "chronicle": "📖",
    "state_of_matthew": "🧭",
    "coach_brief": "🗣️",
    "board_ask": "🎓",
    "field_notes": "🔬",
    "memoir": "📓",
}

_SNIPPET_CHARS = 360


def week_dates(end=None):
    """The WINDOW_DAYS calendar dates (YYYY-MM-DD), oldest-first, ending today (UTC)."""
    end = end or datetime.now(timezone.utc).date()
    return [(end - timedelta(days=i)).isoformat() for i in range(WINDOW_DAYS - 1, -1, -1)]


def _console_url(key):
    """AWS S3 console deep-link to one archived object (auth-gated — the archive is
    S3-private, not CloudFront-routed)."""
    return f"https://{REGION}.console.aws.amazon.com/s3/object/{BUCKET}?region={REGION}&prefix={quote(key)}"


def gather_week(dates):
    """Read the archive for `dates`. Returns:
      by_surface: {surface: [entry_dict, ...]}  (entry = archived JSON doc + _key)
      screenshots_by_date: {date: [key, ...]}
      read_errors: int  (objects that listed but failed to read/parse — skipped)

    list_day() raises loudly on AWS errors (the review pack wants a failed week
    visible, not silently empty). Individual object reads are fail-soft so one bad
    object can never sink the whole editorial email.
    """
    by_surface = {}
    screenshots_by_date = {}
    read_errors = 0
    for d in dates:
        for key in qa_archive.list_day(d, kind="text"):
            try:
                entry = qa_archive.read_entry(key)
            except Exception as e:  # noqa: BLE001 — skip the corrupt object, keep the email
                read_errors += 1
                logger.warning(f"[ai-review-pack] unreadable archive object {key}: {e}")
                continue
            entry["_key"] = key
            by_surface.setdefault(entry.get("surface", "unknown"), []).append(entry)
        shots = qa_archive.list_day(d, kind="screenshots")
        if shots:
            screenshots_by_date[d] = shots
    # Newest-first within each surface for a natural reading order.
    for entries in by_surface.values():
        entries.sort(key=lambda e: e.get("archived_at", ""), reverse=True)
    return by_surface, screenshots_by_date, read_errors


def _label(surface):
    return SURFACE_LABELS.get(surface, surface.replace("_", " ").title())


def _snippet(text):
    text = (text or "").strip()
    if len(text) > _SNIPPET_CHARS:
        text = text[:_SNIPPET_CHARS].rstrip() + "…"
    return html.escape(text) or "<em>(empty)</em>"


def _meta_line(entry):
    """A compact, human-friendly context line per surface, from the archived meta."""
    surface = entry.get("surface")
    meta = entry.get("meta") or {}
    variant = entry.get("variant")
    bits = []
    if surface == "board_ask":
        if meta.get("question"):
            bits.append("Q: " + str(meta["question"]))
        if meta.get("grounded") is not None:
            bits.append("grounded" if meta.get("grounded") else "ungrounded")
    elif surface == "chronicle":
        if meta.get("title"):
            bits.append(str(meta["title"]))
        if meta.get("week_number") is not None:
            bits.append(f"week {meta['week_number']}")
        if meta.get("status"):
            bits.append(str(meta["status"]))
    elif surface == "state_of_matthew":
        bits.append("narrated" if meta.get("narrated") else "fallback (not AI-narrated)")
        if meta.get("model"):
            bits.append(str(meta["model"]))
    elif surface == "coach_brief":
        if meta.get("output_type"):
            bits.append(str(meta["output_type"]))
    elif surface == "memoir":
        if meta.get("quarter"):
            bits.append(f"quarter {meta['quarter']}")
    elif surface == "field_notes":
        if meta.get("week"):
            bits.append(f"week {meta['week']}")
    if variant:
        bits.insert(0, str(variant))
    return html.escape(" · ".join(str(b) for b in bits))


def _entry_card(entry):
    when = entry.get("archived_at", "")[:16].replace("T", " ")
    meta_line = _meta_line(entry)
    meta_html = f'<div style="color:#9ca3af;font-size:12px;margin:2px 0 8px;">{meta_line}</div>' if meta_line else ""
    return f"""
      <div style="background:#12162e;border:1px solid #2a2d4a;border-radius:8px;padding:12px 14px;margin-bottom:10px;">
        <div style="display:flex;justify-content:space-between;font-size:11px;color:#6b7280;margin-bottom:4px;">
          <span>{html.escape(when)} UTC</span>
          <a href="{_console_url(entry['_key'])}" style="color:#6366f1;text-decoration:none;">open in S3 &rsaquo;</a>
        </div>
        {meta_html}
        <div style="color:#d1d5db;font-size:13px;line-height:1.5;white-space:pre-wrap;">{_snippet(entry.get('text'))}</div>
      </div>"""


def _surface_section(surface, entries):
    icon = SURFACE_ICONS.get(surface, "•")
    label = _label(surface)
    if not entries:
        body = '<div style="color:#6b7280;font-size:12px;font-style:italic;padding:6px 0;">Nothing generated this week.</div>'
    else:
        body = "".join(_entry_card(e) for e in entries)
    return f"""
    <div style="margin-bottom:26px;">
      <div style="font-size:14px;font-weight:700;color:#ffffff;border-bottom:1px solid #2a2d4a;padding-bottom:6px;margin-bottom:10px;">
        {icon} {html.escape(label)} <span style="color:#6b7280;font-weight:400;font-size:12px;">({len(entries)})</span>
      </div>
      {body}
    </div>"""


def _screenshots_section(screenshots_by_date):
    total = sum(len(v) for v in screenshots_by_date.values())
    if not total:
        inner = '<div style="color:#6b7280;font-size:12px;font-style:italic;">No page screenshots archived this week.</div>'
    else:
        rows = []
        for d in sorted(screenshots_by_date):
            keys = screenshots_by_date[d]
            links = " · ".join(
                f'<a href="{_console_url(k)}" style="color:#6366f1;text-decoration:none;">{html.escape(k.rsplit("/", 1)[-1])}</a>'
                for k in sorted(keys)
            )
            rows.append(
                f'<div style="font-size:12px;color:#9ca3af;margin-bottom:6px;"><span style="color:#d1d5db;">{d}</span> — {links}</div>'
            )
        inner = "".join(rows)
    return f"""
    <div style="margin-bottom:26px;">
      <div style="font-size:14px;font-weight:700;color:#ffffff;border-bottom:1px solid #2a2d4a;padding-bottom:6px;margin-bottom:10px;">
        🖼️ Page screenshots <span style="color:#6b7280;font-weight:400;font-size:12px;">({total})</span>
      </div>
      <div style="color:#6b7280;font-size:11px;margin-bottom:8px;">Daily visual-QA renders of the AI pages — what a reader saw that day (not per-generation captures).</div>
      {inner}
    </div>"""


def build_html(dates, by_surface, screenshots_by_date, read_errors):
    total = sum(len(v) for v in by_surface.values())
    active_surfaces = sum(1 for s in SURFACE_ORDER if by_surface.get(s))
    start_label = _fmt_date(dates[0])
    end_label = _fmt_date(dates[-1])

    sections = "".join(_surface_section(s, by_surface.get(s, [])) for s in SURFACE_ORDER)
    # Any archived surface not in our known order still gets shown (fail-open).
    for s in sorted(set(by_surface) - set(SURFACE_ORDER)):
        sections += _surface_section(s, by_surface[s])
    sections += _screenshots_section(screenshots_by_date)

    err_html = ""
    if read_errors:
        err_html = (
            f'<div style="color:#fb923c;font-size:12px;margin-top:6px;">'
            f"⚠️ {read_errors} archived object(s) could not be read and were skipped — check CloudWatch.</div>"
        )

    return f"""<div style="max-width:640px;margin:0 auto;background:#1a1a2e;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:22px;color:#e0e0e0;">
  <div style="text-align:center;margin-bottom:24px;">
    <div style="font-size:11px;letter-spacing:2px;color:#6366f1;font-weight:600;margin-bottom:4px;">LIFE PLATFORM · EDITORIAL REVIEW</div>
    <div style="font-size:23px;font-weight:700;color:#ffffff;">🗂️ Weekly AI Review Pack</div>
    <div style="color:#9ca3af;font-size:13px;margin-top:4px;">{start_label} – {end_label}</div>
    <div style="margin-top:10px;font-size:12px;color:#9ca3af;">
      <span style="color:#f59e0b;font-weight:700;">{total}</span> generation(s) across
      <span style="color:#f59e0b;font-weight:700;">{active_surfaces}</span> surface(s)
    </div>
    {err_html}
  </div>
  <div style="color:#9ca3af;font-size:12px;line-height:1.5;margin-bottom:20px;">
    The week's AI output, gate-passed and archived at generation time. Scan each surface;
    open any object in S3 for the full text. This is the human editorial pass over every AI surface.
  </div>
  {sections}
  <div style="text-align:center;padding:16px 0;border-top:1px solid #2a2d4a;margin-top:12px;">
    <div style="color:#6b7280;font-size:11px;">Weekly AI Review Pack · Life Platform · QA editorial plane (#1442)</div>
  </div>
</div>"""


def _fmt_date(d):
    try:
        return datetime.strptime(d, "%Y-%m-%d").strftime("%b %-d")
    except Exception:
        return d


def record_email_send(table, lambda_name):
    """Write a completion record so the status page can track the last send."""
    import time as _time

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        table.put_item(
            Item={
                "pk": f"USER#matthew#SOURCE#email_log#{lambda_name}",
                "sk": f"DATE#{today}",
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "status": "success",
                "ttl": int(_time.time()) + 86400 * 90,
            }
        )
    except Exception as e:
        logger.info(f"[ai-review-pack] status-tracking write failed (non-fatal): {e}")


def lambda_handler(event, context):
    try:
        return _run(event, context)
    except Exception as e:
        logger.error("Weekly AI Review Pack failed: %s", e)
        raise


def _run(event, context):
    logger.info("Weekly AI Review Pack starting...")
    dates = week_dates()
    by_surface, screenshots_by_date, read_errors = gather_week(dates)
    total = sum(len(v) for v in by_surface.values())
    logger.info(
        f"[ai-review-pack] {total} generations, {sum(len(v) for v in screenshots_by_date.values())} screenshots, {read_errors} read errors over {dates[0]}..{dates[-1]}"
    )

    html_body = build_html(dates, by_surface, screenshots_by_date, read_errors)
    subject = f"🗂️ Weekly AI Review Pack · {_fmt_date(dates[0])}–{_fmt_date(dates[-1])} · {total} generation(s)"

    ses = boto3.client("sesv2", region_name=REGION)
    ses.send_email(
        FromEmailAddress=SENDER,
        Destination={"ToAddresses": [RECIPIENT]},
        Content={
            "Simple": {
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Html": {"Data": html_body, "Charset": "UTF-8"}},
            }
        },
    )
    logger.info(f"Sent: {subject}")

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
    record_email_send(table, "ai-review-pack")
    return {
        "statusCode": 200,
        "body": f"{total} generations across {sum(1 for s in by_surface if by_surface[s])} surfaces; {read_errors} read errors",
    }
