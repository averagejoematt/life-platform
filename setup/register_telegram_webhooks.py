#!/usr/bin/env python3
"""register_telegram_webhooks.py — point every configured bot at the platform (#2364).

Run AFTER the CDK deploy that creates the telegram-webhook FunctionURL:

    python3 setup/register_telegram_webhooks.py --url https://XXXX.lambda-url.us-west-2.on.aws
    python3 setup/register_telegram_webhooks.py --status   # what Telegram has, per bot

Per configured bot it calls Telegram ``setWebhook`` with:

  * ``url``   = <function-url>/telegram/<routing key> — the path IS the routing, so
    the webhook Lambda knows which coach was texted without trusting the payload;
  * ``secret_token`` = the store's ``webhook_secret`` — Telegram echoes it on every
    delivery and the gateway rejects anything without it (fails closed).

The webhook_secret is GENERATED here on first run (secrets.token_urlsafe) and
persisted into the same ``life-platform/telegram`` store the tokens live in — one
secret, one IAM grant. Idempotent: re-running re-registers with the same values;
a new bot added later picks up the existing webhook_secret.

Also sets ``allowed_updates=["message"]`` — the platform only acts on plain new
messages (edits are deliberately not turns), so Telegram shouldn't even deliver
the rest.

THIS SCRIPT PERMANENTLY DISABLES getUpdates FOR EVERY BOT IT REGISTERS (#2600).

Telegram delivers updates to ``getUpdates`` OR to a registered webhook, never both.
Registering here is therefore a ONE-WAY door for the sibling script's chat-id
discovery: from this point on ``setup/setup_telegram_bots.py`` gets
``409 Conflict: can't use getUpdates method while webhook is active`` for these
bots, and no amount of messaging them will change that.

So the order is: configure tokens and chat ids FIRST, register SECOND.

    1. python3 setup/setup_telegram_bots.py [key ...]
    2. python3 setup/register_telegram_webhooks.py --url <function-url>

Adding a coach later is still fine — run (1) for the new key and it will detect the
409, explain it, and offer the chat id your other bots already proved (a private
chat's id is your Telegram user id, identical across bots), then run (2) again to
register the newcomer's webhook. What is NOT fine is hand-editing the secret, and
what this script deliberately does not do is call ``deleteWebhook`` to hand the
updates back: that is a live serving path, and a crash between the delete and the
re-register leaves a coach unable to receive anything at all.
"""

from __future__ import annotations

import argparse
import json
import secrets as pysecrets
import sys
import urllib.parse
import urllib.request

try:
    import boto3
except ImportError:  # pragma: no cover
    sys.exit("boto3 is required: pip3 install boto3")

REGION = "us-west-2"
STORE_PATH = "life-platform/telegram"
TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


def _api(token: str, method: str, payload: dict | None = None) -> dict:
    url = TELEGRAM_API.format(token=token, method=method)
    data = urllib.parse.urlencode(payload).encode() if payload else None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:  # type: ignore[attr-defined]
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"ok": False, "description": f"HTTP {e.code}"}
    except Exception as e:
        return {"ok": False, "description": str(e)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Register (or inspect) the coach bots' webhooks.")
    ap.add_argument("--url", help="the telegram-webhook FunctionURL base (no trailing slash)")
    ap.add_argument("--status", action="store_true", help="print each bot's current webhook info and exit")
    args = ap.parse_args()

    client = boto3.client("secretsmanager", region_name=REGION)
    store = json.loads(client.get_secret_value(SecretId=STORE_PATH)["SecretString"])
    bots = {k: v for k, v in store.items() if isinstance(v, dict) and v.get("bot_token")}
    if not bots:
        sys.exit("no bots configured — run setup/setup_telegram_bots.py first")

    if args.status:
        for key, entry in sorted(bots.items()):
            info = _api(entry["bot_token"], "getWebhookInfo").get("result") or {}
            url = info.get("url") or "— not set —"
            pending = info.get("pending_update_count", 0)
            err = info.get("last_error_message")
            print(f"  {key:11s} {url}" + (f"   pending={pending}" if pending else "") + (f"   last_error={err!r}" if err else ""))
        return 0

    if not args.url:
        sys.exit("--url is required to register (or use --status)")
    base = args.url.rstrip("/")

    wh_secret = store.get("webhook_secret")
    if not wh_secret:
        wh_secret = pysecrets.token_urlsafe(32)
        store["webhook_secret"] = wh_secret
        client.put_secret_value(SecretId=STORE_PATH, SecretString=json.dumps(store, indent=2, sort_keys=True))
        print("generated + stored webhook_secret (first run)")

    for key, entry in sorted(bots.items()):
        r = _api(
            entry["bot_token"],
            "setWebhook",
            {
                "url": f"{base}/telegram/{key}",
                "secret_token": wh_secret,
                "allowed_updates": json.dumps(["message"]),
                "drop_pending_updates": "false",
            },
        )
        mark = "✓" if r.get("ok") else "✗"
        print(f"  {mark} {key:11s} -> {base}/telegram/{key}" + ("" if r.get("ok") else f"   {r.get('description')}"))

    print("\ndone — send a bot a message and watch /aws/lambda/telegram-webhook + telegram-coach-worker logs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
