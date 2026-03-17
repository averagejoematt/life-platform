#!/usr/bin/env python3
"""
BS-T2-5 patch — fix unsubscribe URL in chronicle_email_sender + email_subscriber.
Run from project root: python3 patch_bs_t2_5.py
"""
import re, sys, pathlib

ROOT = pathlib.Path(".")

# ─────────────────────────────────────────────────────────────
# 1. chronicle_email_sender_lambda.py
#    a) Replace multi-line unsub_url block + extract subscriber fields
#    b) (function sig + call site already done via sed)
# ─────────────────────────────────────────────────────────────
sender = ROOT / "lambdas/chronicle_email_sender_lambda.py"
text = sender.read_text()

OLD_UNSUB = (
    "    unsub_url   = (\n"
    "        f\"{SITE_URL}/api/subscribe\"\n"
    "        f\"?action=unsubscribe\"\n"
    "        f\"&email={urllib.parse.quote(subscriber_email)}\"\n"
    "    )"
)
NEW_UNSUB = (
    "    subscriber_email = subscriber.get(\"email\", \"\")\n"
    "    email_hash       = subscriber.get(\"email_hash\", \"\")\n"
    "    unsub_url = f\"{SITE_URL}/api/subscribe?action=unsubscribe&h={email_hash}\""
)

if OLD_UNSUB in text:
    text = text.replace(OLD_UNSUB, NEW_UNSUB)
    sender.write_text(text)
    print("✅ chronicle_email_sender_lambda.py — unsub URL patched")
elif "subscriber.get(\"email_hash\"" in text:
    print("⏭️  chronicle_email_sender_lambda.py — already patched, skipping")
else:
    print("❌ chronicle_email_sender_lambda.py — OLD block not found, manual edit needed")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────
# 2. email_subscriber_lambda.py
#    a) Fix welcome email raw-email unsub link → hash-based
#    b) Add handle_unsubscribe_by_hash() function
#    c) Update lambda_handler router to prefer &h= param
# ─────────────────────────────────────────────────────────────
subscriber = ROOT / "lambdas/email_subscriber_lambda.py"
text = subscriber.read_text()

# 2a — welcome email unsub link
OLD_WELCOME_UNSUB = 'f"&email={urllib.parse.quote(email)}"'
NEW_WELCOME_UNSUB = 'f"&h={_email_hash(email)}"'
if OLD_WELCOME_UNSUB in text:
    text = text.replace(OLD_WELCOME_UNSUB, NEW_WELCOME_UNSUB)
    print("✅ email_subscriber_lambda.py — welcome email unsub link patched")
elif NEW_WELCOME_UNSUB in text:
    print("⏭️  email_subscriber_lambda.py — welcome email already patched")
else:
    print("❌ email_subscriber_lambda.py — welcome email unsub line not found")
    sys.exit(1)

# 2b — insert handle_unsubscribe_by_hash() before handle_unsubscribe
NEW_FUNC = '''
def handle_unsubscribe_by_hash(email_hash: str) -> dict:
    """Token-safe unsubscribe — resolves subscriber by email_hash, never exposes raw email in URL."""
    if not email_hash or len(email_hash) != 64:
        return _redirect(f"{SITE_URL}/subscribe?error=invalid_token")

    now_iso = datetime.now(timezone.utc).isoformat()
    sk = f"EMAIL#{email_hash}"

    try:
        resp = table.get_item(Key={"pk": SUBSCRIBERS_PK, "sk": sk})
        existing = resp.get("Item")
    except Exception as exc:
        logger.error("unsubscribe_by_hash: DDB get failed: %s", exc)
        return _redirect(f"{SITE_URL}/subscribe?error=server_error")

    if not existing:
        return _redirect(f"{SITE_URL}/subscribe?unsubscribed=true")

    if existing.get("status") == "unsubscribed":
        return _redirect(f"{SITE_URL}/subscribe?unsubscribed=already")

    try:
        table.update_item(
            Key={"pk": SUBSCRIBERS_PK, "sk": sk},
            UpdateExpression="SET #s = :s, unsubbed_at = :u, updated_at = :u",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "unsubscribed", ":u": now_iso},
        )
    except Exception as exc:
        logger.error("unsubscribe_by_hash: DDB update failed: %s", exc)
        return _redirect(f"{SITE_URL}/subscribe?error=server_error")

    logger.info("unsubscribed by hash: %s", email_hash[:8])
    return _redirect(f"{SITE_URL}/subscribe?unsubscribed=true")

'''

ANCHOR = "def handle_unsubscribe(email: str) -> dict:"
if "handle_unsubscribe_by_hash" in text:
    print("⏭️  email_subscriber_lambda.py — handle_unsubscribe_by_hash already exists")
elif ANCHOR in text:
    text = text.replace(ANCHOR, NEW_FUNC + ANCHOR)
    print("✅ email_subscriber_lambda.py — handle_unsubscribe_by_hash inserted")
else:
    print("❌ email_subscriber_lambda.py — anchor for new function not found")
    sys.exit(1)

# 2c — update router to prefer &h= param
OLD_ROUTER = (
    "    if action == \"unsubscribe\":\n"
    "        email = params.get(\"email\", \"\")\n"
    "        if not email:\n"
    "            return _redirect(f\"{SITE_URL}/subscribe?error=missing_email\")\n"
    "        return handle_unsubscribe(email)"
)
NEW_ROUTER = (
    "    if action == \"unsubscribe\":\n"
    "        h = params.get(\"h\", \"\")\n"
    "        if h:\n"
    "            return handle_unsubscribe_by_hash(h)\n"
    "        email = params.get(\"email\", \"\")\n"
    "        if not email:\n"
    "            return _redirect(f\"{SITE_URL}/subscribe?error=missing_email\")\n"
    "        return handle_unsubscribe(email)"
)

if OLD_ROUTER in text:
    text = text.replace(OLD_ROUTER, NEW_ROUTER)
    print("✅ email_subscriber_lambda.py — router updated to prefer hash-based unsub")
elif "handle_unsubscribe_by_hash(h)" in text:
    print("⏭️  email_subscriber_lambda.py — router already updated")
else:
    print("❌ email_subscriber_lambda.py — router block not found")
    sys.exit(1)

subscriber.write_text(text)
print("\n✅ All patches applied. Ready to deploy.")
