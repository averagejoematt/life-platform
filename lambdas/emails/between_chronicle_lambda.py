"""
between_chronicle_lambda.py — #398: the machine's between-chronicle note.

Confirmed subscribers received exactly one thing (the weekly Chronicle) while
the platform kept computing between-week findings that never reached the
inbox. This Lambda assembles a short "since the last installment" note PURELY
from already-computed records — ZERO new inference:

  - monthly what-changed deltas + newly-significant correlations
    (USER#…#SOURCE#what_changed / SNAPSHOT#current — the same record
    /api/what_changed serves, so every number matches the public API)
  - freshly graded predictions (COACH#… PREDICTION# status confirmed/refuted —
    the same records /api/predictions serves)
  - coach stance shifts (COACH#… STANCE#latest how_my_read_changed — the same
    text the coaching pages render)

Honesty rules:
  - Sends ONLY when there is real, previously-unsent content: the assembled
    digest is content-hashed and compared to the last-sent marker
    (SOURCE#email_digest / STATE#between_chronicle); an unchanged or empty
    period sends nothing — never padded filler.
  - No open tracking of any kind (no pixel, no per-link redirects) — the
    standing privacy tradeoff holds; the feature is judged on content.
  - Honors the platform-wide EXTERNAL_EMAILS_ENABLED kill switch.

Schedule: weekly, Sunday 17:00 UTC (mid-gap between Wednesday chronicles).
"""

import hashlib
import json
import logging
import os
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import boto3

try:
    from platform_logger import get_logger

    logger = get_logger("between-chronicle")
except ImportError:
    logger = logging.getLogger("between-chronicle")
    logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
SITE_URL = os.environ.get("SITE_URL", "https://averagejoematt.com")
SENDER = os.environ.get("EMAIL_SENDER", "Elena Voss <elena@averagejoematt.com>")
SEND_RATE_PER_SEC = float(os.environ.get("SEND_RATE_PER_SEC", "14.0"))
DECIDED_WINDOW_DAYS = int(os.environ.get("DECIDED_WINDOW_DAYS", "10"))

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"
SUBSCRIBERS_PK = f"{USER_PREFIX}subscribers"
MARKER_PK = f"{USER_PREFIX}email_digest"
MARKER_SK = "STATE#between_chronicle"

COACH_IDS = [
    "sleep_coach",
    "nutrition_coach",
    "training_coach",
    "mind_coach",
    "physical_coach",
    "glucose_coach",
    "labs_coach",
    "explorer_coach",
]

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)
ses = boto3.client("sesv2", region_name=REGION)


from digest_utils import d2f as _d2f  # shared bundled helpers (#970)


def _scrub(text: str) -> str:
    """Fail-soft privacy scrub — the sources are already public-gated, this is
    defense-in-depth on anything narrative."""
    try:
        import privacy_guard

        out, _n = privacy_guard.scrub(str(text))
        return out
    except Exception:
        return str(text)


# ── Gather (already-computed records only — the same ones the public APIs serve) ──


def gather_digest() -> dict:
    """Assemble the between-chronicle content. Every value is read verbatim
    from a record a public endpoint already serves."""
    digest = {"deltas": [], "unlocked": [], "decided": [], "stance_shifts": []}

    # 1. Monthly motion — the /api/what_changed record.
    try:
        wc = _d2f(table.get_item(Key={"pk": f"{USER_PREFIX}what_changed", "sk": "SNAPSHOT#current"}).get("Item") or {})
        if not wc.get("honest_null"):
            digest["deltas"] = (wc.get("deltas") or [])[:6]
            digest["unlocked"] = (wc.get("newly_unlocked") or [])[:4]
    except Exception as e:
        logger.warning("what_changed read skipped: %s", e)

    # 2. Freshly graded predictions — the /api/predictions records.
    cutoff = (datetime.now(timezone.utc) - timedelta(days=DECIDED_WINDOW_DAYS)).strftime("%Y-%m-%d")
    for cid in COACH_IDS:
        try:
            resp = table.query(
                KeyConditionExpression="pk = :pk AND begins_with(sk, :s)",
                ExpressionAttributeValues={":pk": f"COACH#{cid}", ":s": "PREDICTION#"},
                ScanIndexForward=False,
                Limit=30,
            )
            for rec in (_d2f(i) for i in resp.get("Items", [])):
                if rec.get("status") not in ("confirmed", "refuted"):
                    continue
                decided_at = str(rec.get("evaluated_at") or (rec.get("evaluation") or {}).get("evaluated_at") or "")[:10]
                if decided_at and decided_at < cutoff:
                    continue  # graded before the window — already narratable last time
                digest["decided"].append(
                    {
                        "coach": cid.replace("_coach", "").replace("_", " "),
                        "claim": str(rec.get("claim_natural", ""))[:200],
                        "status": rec["status"],
                        "notes": str(rec.get("outcome_notes") or "")[:200],
                        "decided_at": decided_at,
                    }
                )
        except Exception as e:
            logger.warning("predictions read skipped for %s: %s", cid, e)
    digest["decided"] = digest["decided"][:6]

    # 3. Stance shifts — the coaching pages' STANCE#latest "how my read changed".
    for cid in COACH_IDS:
        try:
            st = _d2f(table.get_item(Key={"pk": f"COACH#{cid}", "sk": "STANCE#latest"}).get("Item") or {})
            shift = str(st.get("how_my_read_changed") or "").strip()
            if shift:
                digest["stance_shifts"].append(
                    {
                        "coach": cid.replace("_coach", "").replace("_", " "),
                        "shift": shift[:280],
                        "stage": str((st.get("stage") or {}).get("label", "") if isinstance(st.get("stage"), dict) else "")[:80],
                    }
                )
        except Exception as e:
            logger.warning("stance read skipped for %s: %s", cid, e)
    digest["stance_shifts"] = digest["stance_shifts"][:4]

    # 4. #537: Elena's editorial read — she signs this email, so her one-line
    # stance (PERSONA#elena STANCE#latest, receipts-gated) frames it. Garnish,
    # never content: it doesn't count toward has_real_content.
    try:
        st = _d2f(table.get_item(Key={"pk": "PERSONA#elena", "sk": "STANCE#latest"}).get("Item") or {})
        if st.get("headline_stance") and not st.get("grounding_flag"):
            digest["elena_note"] = str(st["headline_stance"])[:320]
    except Exception as e:
        logger.warning("elena stance read skipped: %s", e)

    return digest


def digest_hash(digest: dict) -> str:
    return hashlib.sha256(json.dumps(digest, sort_keys=True, default=str).encode()).hexdigest()


def has_real_content(digest: dict) -> bool:
    return bool(digest["deltas"] or digest["unlocked"] or digest["decided"] or digest["stance_shifts"])


# ── Build (plain HTML, no tracking pixel, no per-link redirects) ─────────────


def build_email(digest: dict, sub_email: str) -> tuple:
    unsub = f"{SITE_URL}/api/subscribe?action=unsubscribe&email={urllib.parse.quote(sub_email)}"
    parts = [
        '<div style="background:#0b0f0d;color:#e8f0e8;font-family:Georgia,serif;padding:28px;max-width:640px;margin:auto;">',
        '<p style="font-family:monospace;font-size:11px;letter-spacing:.08em;color:#8aaa90;text-transform:uppercase;">since the last installment · what the machine found</p>',
    ]
    # #537: Elena signs this email — her current editorial read opens it.
    if digest.get("elena_note"):
        parts.append(f'<p style="margin:14px 0 4px;font-size:14px;font-style:italic;color:#cfd8cf;">{_scrub(digest["elena_note"])}</p>')
        parts.append('<p style="margin:0 0 10px;font-family:monospace;font-size:11px;color:#5a7565;">— Elena, where I currently stand</p>')
    if digest["deltas"]:
        parts.append('<h2 style="font-size:18px;margin:18px 0 6px;">The month moved</h2>')
        for d in digest["deltas"]:
            arrow = "▲" if (d.get("delta") or 0) > 0 else "▼"
            parts.append(
                f'<p style="margin:4px 0;font-family:monospace;font-size:13px;color:#cfd8cf;">{arrow} '
                f'{_scrub(d.get("label", ""))}: {d.get("this_month_avg")} {_scrub(d.get("unit") or "")} '
                f'vs {d.get("prior_month_avg")} prior 30d ({_scrub(d.get("direction", ""))})</p>'
            )
    if digest["unlocked"]:
        parts.append('<h2 style="font-size:18px;margin:18px 0 6px;">Newly significant</h2>')
        for u in digest["unlocked"]:
            txt = u.get("interpretation") or f"{u.get('metric_a', '')} ↔ {u.get('metric_b', '')}"
            r = f" (r={round(float(u['r']), 2)})" if isinstance(u.get("r"), (int, float)) else ""
            parts.append(f'<p style="margin:4px 0;font-size:14px;color:#cfd8cf;">{_scrub(txt)}{r} — correlative, not causal.</p>')
    if digest["decided"]:
        parts.append('<h2 style="font-size:18px;margin:18px 0 6px;">Calls that graded</h2>')
        for p in digest["decided"]:
            verdict = "✓ called it" if p["status"] == "confirmed" else "✗ got it wrong"
            parts.append(
                f'<p style="margin:6px 0;font-size:14px;color:#cfd8cf;"><strong>{verdict}</strong> — '
                f'the {_scrub(p["coach"])} coach: “{_scrub(p["claim"])}”'
                + (f' <span style="color:#8aaa90;">{_scrub(p["notes"])}</span>' if p["notes"] else "")
                + "</p>"
            )
    if digest["stance_shifts"]:
        parts.append('<h2 style="font-size:18px;margin:18px 0 6px;">Coaches who changed their read</h2>')
        for s in digest["stance_shifts"]:
            parts.append(
                f'<p style="margin:6px 0;font-size:14px;color:#cfd8cf;"><strong>{_scrub(s["coach"])}</strong>'
                + (f' <span style="color:#8aaa90;">({_scrub(s["stage"])})</span>' if s["stage"] else "")
                + f": {_scrub(s['shift'])}</p>"
            )
    parts.append(
        f'<p style="margin-top:22px;font-size:13px;color:#8aaa90;">Every number above is the same one the public site serves. '
        f'Single-subject experiment (N=1) — patterns, never proof. <a href="{SITE_URL}/cockpit/" style="color:#8aaa90;">The live cockpit →</a></p>'
        f'<p style="margin-top:14px;font-family:monospace;font-size:11px;color:#5a7565;">No open tracking on this email. '
        f'<a href="{unsub}" style="color:#5a7565;">unsubscribe</a></p></div>'
    )
    n_bits = len(digest["deltas"]) + len(digest["unlocked"]) + len(digest["decided"]) + len(digest["stance_shifts"])
    subject = f"Between chronicles: {n_bits} thing{'s' if n_bits != 1 else ''} the machine found"
    return subject, "".join(parts)


# ── Send ─────────────────────────────────────────────────────────────────────


def _get_confirmed_subscribers() -> list:
    confirmed = []
    kwargs = {
        "KeyConditionExpression": "pk = :pk",
        "FilterExpression": "#s = :confirmed",
        "ExpressionAttributeNames": {"#s": "status"},
        "ExpressionAttributeValues": {":pk": SUBSCRIBERS_PK, ":confirmed": "confirmed"},
    }
    while True:
        resp = table.query(**kwargs)
        confirmed.extend(_d2f(i) for i in resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return confirmed


def lambda_handler(event: dict, context) -> dict:
    event = event or {}
    digest = gather_digest()
    h = digest_hash(digest)

    if not has_real_content(digest):
        logger.info("no real content this period — sending nothing (honest silence)")
        return {"statusCode": 200, "sent": 0, "skipped": "empty_period"}

    try:
        marker = _d2f(table.get_item(Key={"pk": MARKER_PK, "sk": MARKER_SK}).get("Item") or {})
    except Exception:
        marker = {}
    if marker.get("content_hash") == h:
        logger.info("digest unchanged since last send — sending nothing")
        return {"statusCode": 200, "sent": 0, "skipped": "unchanged"}

    if event.get("dry_run"):
        subject, html = build_email(digest, "preview@example.com")
        return {"statusCode": 200, "dry_run": True, "subject": subject, "digest": digest, "html_bytes": len(html)}

    if os.environ.get("EXTERNAL_EMAILS_ENABLED", "true").lower() != "true":
        logger.info("[kill-switch] EXTERNAL_EMAILS_ENABLED=false — skipping subscriber send")
        return {"statusCode": 200, "sent": 0, "skipped": "external_emails_disabled"}

    subs = _get_confirmed_subscribers()
    if not subs:
        logger.info("no confirmed subscribers — no-op")
        return {"statusCode": 200, "sent": 0, "skipped": "no_subscribers"}

    rate_delay = 1.0 / max(SEND_RATE_PER_SEC, 0.1)
    sent = failed = 0
    for i, sub in enumerate(subs):
        email = (sub.get("email") or "").strip()
        if not email:
            continue
        subject, html = build_email(digest, email)
        try:
            ses.send_email(
                FromEmailAddress=SENDER,
                Destination={"ToAddresses": [email]},
                Content={
                    "Simple": {"Subject": {"Data": subject, "Charset": "UTF-8"}, "Body": {"Html": {"Data": html, "Charset": "UTF-8"}}}
                },
            )
            sent += 1
        except Exception as exc:
            failed += 1
            logger.error("send failed to %s…: %s", email[:6], exc)
        if i < len(subs) - 1:
            time.sleep(rate_delay)

    try:
        table.put_item(
            Item={
                "pk": MARKER_PK,
                "sk": MARKER_SK,
                "content_hash": h,
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "sent_count": sent,
            }
        )
    except Exception as e:
        logger.warning("marker write failed (next run may resend): %s", e)

    logger.info("between-chronicle note sent: %d ok, %d failed", sent, failed)
    return {"statusCode": 200, "sent": sent, "failed": failed}
