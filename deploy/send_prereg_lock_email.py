#!/usr/bin/env python3
"""send_prereg_lock_email.py — the one genesis-eve subscriber email (#1378, criterion 2):
"Predictions lock tonight — make yours."

One send, ever, per genesis: tells confirmed subscribers the board's opening
predictions are frozen and hash-stamped (with the fingerprint in the email), and
invites them to place their own call on the cockpit's predict-the-week widget
before Day 1 data exists.

HONESTY GUARDS:
  - The freeze must verify (hash match) before any email renders — the fingerprint
    the email prints must be the fingerprint of the actual frozen file.
  - "Lock tonight" is only true on genesis eve, so the script REFUSES to send on
    any other Pacific date. There is no override flag — late copy would be false copy.
  - Presentation rule (#976): no reset/prior-attempt language.

Delivery matches lambdas/emails/chronicle_email_sender_lambda.py: SES v2, the
confirmed-subscriber partition, per-recipient unsubscribe link, 1 send/sec.

Usage:
    python3 deploy/send_prereg_lock_email.py                     # dry-run: print subject + HTML + recipient count
    python3 deploy/send_prereg_lock_email.py --to me@example.com # single test send
    python3 deploy/send_prereg_lock_email.py --apply             # send to ALL confirmed subscribers
"""

import argparse
import json
import os
import sys
import time
import urllib.parse
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "deploy"))

import genesis_prereg_stamp  # noqa: E402

REGION = "us-west-2"
TABLE_NAME = "life-platform"
USER_ID = "matthew"
SUBSCRIBERS_PK = f"USER#{USER_ID}#SOURCE#subscribers"
SENDER = os.environ.get("EMAIL_SENDER", "lifeplatform@mattsusername.com")
SITE_URL = "https://averagejoematt.com"
SEND_RATE_PER_SEC = 1.0
PT = ZoneInfo("America/Los_Angeles")

BANNED_TOKENS = ("cycle", "reset", "restart", "attempt", "last time", "previous", "this time", "once more", "back on")

SUBJECT = "Predictions lock tonight — make yours"


def check_timing(today_pt: date, genesis: str) -> None:
    """ "Lock tonight" is only true the evening before Day 1 — refuse any other day."""
    eve = date.fromisoformat(genesis) - timedelta(days=1)
    if today_pt != eve:
        raise SystemExit(
            f'REFUSED: today is {today_pt} (Pacific) but genesis eve is {eve} — "predictions lock tonight" '
            "would be false copy on any other day. This email sends once, on the eve, or not at all."
        )


def build_email(stamp: dict, genesis: str, sub_email: str) -> tuple:
    """(subject, html) for one subscriber — pure, testable, no AWS."""
    day1 = datetime.strptime(genesis, "%Y-%m-%d").strftime("%B %-d, %Y")
    unsub_url = f"{SITE_URL}/api/subscribe?action=unsubscribe&email={urllib.parse.quote(sub_email)}"
    url = stamp["public_artifact_url"]
    sha = stamp["sha256"]
    html = f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f6f2e8;font-family:Georgia,'Times New Roman',serif;color:#2a251c;">
<div style="max-width:560px;margin:0 auto;padding:32px 24px;">
  <p style="font-family:Menlo,Consolas,monospace;font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#b45309;margin:0 0 16px;">averagejoematt &middot; the measured life</p>
  <h1 style="font-size:26px;font-style:italic;font-weight:normal;line-height:1.25;margin:0 0 16px;">Predictions lock tonight &mdash; make yours.</h1>
  <p style="font-size:16px;line-height:1.6;margin:0 0 14px;">
    Tomorrow morning &mdash; {day1} &mdash; a scale records the first number of a twelve-month
    experiment. The coaching board is already on the record: every opening prediction is written
    down, frozen, and sealed with a cryptographic fingerprint <em>before</em> any data exists to
    flatter it.
  </p>
  <p style="font-size:16px;line-height:1.6;margin:0 0 14px;">
    Now it&rsquo;s your turn. The predict-the-week widget on
    <a href="{SITE_URL}/cockpit/" style="color:#b45309;">the cockpit</a> takes your call on the
    opening week&rsquo;s numbers &mdash; place it tonight, before the first weigh-in lands, and the
    site keeps score for all of us.
  </p>
  <div style="background:#efe8d8;border-left:3px solid #b45309;padding:14px 16px;margin:0 0 14px;">
    <p style="font-family:Menlo,Consolas,monospace;font-size:11px;letter-spacing:1px;text-transform:uppercase;color:#6b6152;margin:0 0 8px;">The frozen record &middot; SHA-256</p>
    <p style="font-family:Menlo,Consolas,monospace;font-size:11px;word-break:break-all;margin:0 0 8px;">{sha}</p>
    <p style="font-size:13px;line-height:1.5;color:#6b6152;margin:0;">
      Verify it yourself, tonight or in a year:<br>
      <code style="font-size:11px;">curl -s {url} | shasum -a 256</code><br>
      If we ever edited the record after the freeze, the fingerprint would stop matching.
    </p>
  </div>
  <p style="font-size:16px;line-height:1.6;margin:0 0 24px;">
    Some of the board&rsquo;s calls will be wrong &mdash; that&rsquo;s the point of writing them down
    first. Come grade us. And put your own number where our numbers are.
  </p>
  <p style="text-align:center;margin:0 0 28px;">
    <a href="{SITE_URL}/cockpit/" style="display:inline-block;background:#b45309;color:#f6f2e8;font-family:Menlo,Consolas,monospace;font-size:12px;letter-spacing:2px;text-transform:uppercase;text-decoration:none;padding:12px 22px;border-radius:4px;">Make your prediction</a>
  </p>
  <p style="font-size:12px;color:#9a8f7c;border-top:1px solid #ddd3c0;padding-top:16px;margin:0;">
    You&rsquo;re receiving this because you follow the experiment at averagejoematt.com.
    <a href="{unsub_url}" style="color:#9a8f7c;">Unsubscribe</a>
  </p>
</div>
</body></html>"""
    low = (SUBJECT + " " + html).lower()
    hits = sorted({tok for tok in BANNED_TOKENS if tok in low})
    if hits:
        raise SystemExit(f"presentation rule violation in the email: {hits}")
    return SUBJECT, html


def get_confirmed_subscribers() -> list:
    """Confirmed subscriber records — same partition/filter as the chronicle sender."""
    import boto3

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
    kwargs = {
        "KeyConditionExpression": "pk = :pk",
        "FilterExpression": "#s = :confirmed",
        "ExpressionAttributeNames": {"#s": "status"},
        "ExpressionAttributeValues": {":pk": SUBSCRIBERS_PK, ":confirmed": "confirmed"},
    }
    out = []
    while True:
        resp = table.query(**kwargs)
        out.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            return out
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def send_one(ses, email: str, subject: str, html: str) -> None:
    ses.send_email(
        FromEmailAddress=SENDER,
        Destination={"ToAddresses": [email]},
        Content={"Simple": {"Subject": {"Data": subject, "Charset": "UTF-8"}, "Body": {"Html": {"Data": html, "Charset": "UTF-8"}}}},
    )


def main():
    ap = argparse.ArgumentParser(description='Send the genesis-eve "predictions lock tonight" subscriber email (#1378)')
    ap.add_argument("--apply", action="store_true", help="send to ALL confirmed subscribers (default: dry-run)")
    ap.add_argument("--to", help="send a single test email to this address instead")
    args = ap.parse_args()

    frozen = json.loads(genesis_prereg_stamp.FROZEN_PATH.read_text())
    stamp = genesis_prereg_stamp.require_valid_stamp(frozen)
    genesis = frozen["genesis"]
    check_timing(datetime.now(PT).date(), genesis)

    if args.to:
        subject, html = build_email(stamp, genesis, args.to)
        import boto3

        send_one(boto3.client("sesv2", region_name=REGION), args.to, subject, html)
        print(f"TEST SEND → {args.to}")
        return 0

    subject, preview_html = build_email(stamp, genesis, "reader@example.com")
    if not args.apply:
        try:
            n = len(get_confirmed_subscribers())
            print(f"Would send to {n} confirmed subscriber(s).")
        except Exception as e:
            print(f"(could not count subscribers offline: {e})")
        print(f"\nSubject: {subject}\n\n{preview_html}")
        print("\nDRY RUN — nothing sent. Re-run with --apply (all subscribers) or --to <addr> (one test send).")
        return 0

    import boto3

    ses = boto3.client("sesv2", region_name=REGION)
    subs = [s for s in get_confirmed_subscribers() if (s.get("email") or "").strip()]
    print(f"Sending to {len(subs)} confirmed subscriber(s) at {SEND_RATE_PER_SEC}/s…")
    sent = failed = 0
    for i, sub in enumerate(subs):
        email = sub["email"].strip()
        subject, html = build_email(stamp, genesis, email)
        try:
            send_one(ses, email, subject, html)
            sent += 1
            print(f"  sent {i + 1}/{len(subs)} ({email[:6]}…)")
        except Exception as e:
            failed += 1
            print(f"  FAILED {email[:6]}…: {e}")
        if i < len(subs) - 1:
            time.sleep(1.0 / SEND_RATE_PER_SEC)
    print(f"Done — sent {sent}, failed {failed}.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
