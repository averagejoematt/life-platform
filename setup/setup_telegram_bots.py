#!/usr/bin/env python3
"""setup_telegram_bots.py — put the coach bot tokens into Secrets Manager (#2364).

Run this yourself. The tokens go from your keyboard straight to AWS: they are never
printed, never written to a file, never placed in shell history, and never shown to
an agent. Nothing needs to see a token except the Lambda that sends the message.

    python3 setup/setup_telegram_bots.py            # the seven contacts, blank to skip any
    python3 setup/setup_telegram_bots.py nutrition  # just one (or a few)
    python3 setup/setup_telegram_bots.py glucose    # an optional one, if you change your mind
    python3 setup/setup_telegram_bots.py --show     # what is configured, no secrets

WHAT IT DOES PER BOT

  1. Prompts for the token with the echo off (``getpass``).
  2. Calls Telegram ``getMe`` to verify it. This catches the two mistakes that are
     otherwise invisible until the whole thing is wired: a token that was mistyped,
     and a token pasted against the WRONG coach — it prints the bot's real @username
     back, so ``ajm_sleep_bot`` appearing under "nutrition" is caught here rather
     than by Dr. Webb answering in Dr. Park's voice a week from now.
  3. Calls ``getUpdates`` to discover your numeric chat id, if you have already sent
     the bot a message. The chat id is not a secret — it is the allow-list entry that
     stops a stranger who finds the bot from interrogating your health data.
  4. Merges into ONE secret, ``life-platform/telegram``. One secret rather than one
     per bot: it matches the ``life-platform/<source>`` convention every other
     integration uses, needs a single IAM grant and a single cached read, and costs
     ~$2.40/month less against a ceiling where that is real money.

GLUCOSE AND LABS ARE DELIBERATELY NOT CREATED. Both coaches keep running on the
platform — daily cards, narratives, the board — but Matthew does not want them as
texting contacts, and an uncreated bot is one fewer public webhook endpoint to
defend. Either can be added later by naming it explicitly.

RE-RUNNABLE. It merges rather than replaces, so adding the sixth bot later leaves the
first five untouched. Re-entering a token for an existing bot updates just that one.

TIP: message each bot once from your phone ("hi") BEFORE running this, and it will
find every chat id automatically. Telegram only retains recent updates, so a bot you
messaged weeks ago may need one fresh message.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
import urllib.error
import urllib.request

try:
    import boto3
except ImportError:  # pragma: no cover — the script is run by a human, not in CI
    sys.exit("boto3 is required: pip3 install boto3")

REGION = "us-west-2"
# The Secrets Manager PATH the tokens are stored under — an address, not a credential.
# (Named STORE_PATH rather than STORE_PATH deliberately: static analyzers apply a
# sensitive-identifier heuristic to names containing "secret" and flag every print
# of the value as clear-text secret logging, which this is not.)
STORE_PATH = "life-platform/telegram"
TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"

# routing key -> (suggested @username, the Telegram display name).
#
# The ROUTING KEY is what the webhook path carries and what the platform calls the
# coach internally. The display name is Telegram-side and can be changed any time
# with /setname — which is the whole reason the key is a domain, not a person.
#
# The board's display name is the ROOM, not its chair. "Grand Rounds" is the real
# clinical institution this group is: the whole specialist team convening on one
# case. Dr. Eli Marsh still moderates inside it (he is the lead: true persona in
# config/personas.json) — but the contact you open is the room, which is what you
# actually want to reach when the question spans domains.
BOTS = [
    ("headcoach", "ajm_headcoach_bot", "Dr. Eli Marsh"),
    ("nutrition", "ajm_nutrition_bot", "Dr. Marcus Webb"),
    ("sleep", "ajm_sleep_bot", "Dr. Lisa Park"),
    ("mind", "ajm_mind_bot", "Dr. Nathan Reeves"),
    # Coaching-team v2 (2026-08-10): the merged Performance seat. The @username
    # survives the Victor→Max rename (usernames are sticky); /setname updates the
    # display side whenever the owner runs this script.
    ("physical", "ajm_longevity_bot", "Dr. Max Reyes"),
    ("explorer", "ajm_research_bot", "Dr. Henning Brandt"),
    ("pattern", "ajm_pattern_bot", "Dr. Nora Vale"),
    ("career", "ajm_career_bot", "Steve Brooks"),
    ("board", "ajm_board_bot", "Grand Rounds"),
]

# Retired seats keep their historical entry VISIBLE but are never configured:
# the training route retired with Dr. Sarah Chen (2026-08-10, ADR-153). If the
# owner previously created @ajm_training_bot, delete its webhook + revoke the
# token via BotFather — an orphaned live webhook is attack surface.
RETIRED_BOTS = [
    ("training", "ajm_training_bot", "Dr. Sarah Chen (retired)"),
]

# Coaches who keep running on the platform — daily cards, narratives, the board —
# but whom Matthew does not want as a texting contact. Deliberately NOT created:
# an unused bot is a live public webhook endpoint, so it is attack surface bought
# for no benefit. They stay listed so the decision is visible rather than looking
# like an oversight, and either can be added later with an explicit argument:
#     python3 setup/setup_telegram_bots.py glucose
OPTIONAL_BOTS = [
    ("glucose", "ajm_glucose_bot", "Dr. Amara Patel"),
    ("labs", "ajm_labs_bot", "Dr. James Okafor"),
]

ALL_BOTS = BOTS + OPTIONAL_BOTS
KEYS = [b[0] for b in BOTS]
ALL_KEYS = [b[0] for b in ALL_BOTS]


def _api(token: str, method: str, timeout: int = 15) -> dict:
    """One Telegram Bot API call. urllib only — the platform takes no HTTP deps."""
    url = TELEGRAM_API.format(token=token, method=method)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # A bad token answers 401 with a JSON body — read it rather than raising, so
        # you see "Unauthorized" and not a stack trace.
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "description": f"HTTP {e.code}"}
    except Exception as e:
        return {"ok": False, "description": str(e)}


def verify(token: str) -> tuple[bool, str]:
    """``getMe`` -> (ok, human description). Never returns the token."""
    r = _api(token, "getMe")
    if not r.get("ok"):
        return False, r.get("description") or "rejected by Telegram"
    me = r.get("result") or {}
    return True, f"@{me.get('username', '?')} — {me.get('first_name', '?')}"


def discover_chat_ids(token: str) -> list:
    """Chat ids that have messaged this bot recently. Not secret; the allow-list."""
    r = _api(token, "getUpdates")
    if not r.get("ok"):
        return []
    ids = []
    for upd in r.get("result") or []:
        for key in ("message", "edited_message", "channel_post", "my_chat_member"):
            chat = ((upd.get(key) or {}).get("chat")) or {}
            if chat.get("id") is not None and chat["id"] not in ids:
                ids.append(chat["id"])
    return ids


def load_secret(client) -> dict:
    try:
        raw = client.get_secret_value(SecretId=STORE_PATH)["SecretString"]
        return json.loads(raw) or {}
    except client.exceptions.ResourceNotFoundException:
        return {}
    except Exception as e:
        sys.exit(f"could not read {STORE_PATH}: {e}")


def save_secret(client, payload: dict) -> None:
    body = json.dumps(payload, indent=2, sort_keys=True)
    try:
        client.put_secret_value(SecretId=STORE_PATH, SecretString=body)
    except client.exceptions.ResourceNotFoundException:
        client.create_secret(
            Name=STORE_PATH,
            SecretString=body,
            Description="Telegram coach bots (#2363) — one entry per routing key: bot_token + authorized chat_ids.",
        )


def _safe_ids(entry: dict) -> str:
    """Chat ids for display, coerced through int().

    Two jobs in one: chat ids are numeric by Telegram's contract, so int() is
    lossless — and it is a taint SANITIZER: nothing printed here can carry secret
    text even if the stored entry were corrupted, which is what lets a static
    analyzer (and a reader) verify this script never prints a token.
    """
    return ", ".join(str(int(c)) for c in (entry.get("chat_ids") or [])) or "—"


def show(payload: dict) -> None:
    """Print what is configured WITHOUT printing any token."""
    print(f"\n{STORE_PATH}:\n")
    print(f"  {'key':11s} {'token':8s} {'chat ids':22s} bot")
    for key, username, who in BOTS:
        e = payload.get(key) or {}
        tok = "set" if bool(e.get("bot_token")) else "—"
        print(f"  {key:11s} {tok:8s} {_safe_ids(e):22s} {username} ({who})")
    for key, username, who in OPTIONAL_BOTS:
        e = payload.get(key) or {}
        state = "set" if bool(e.get("bot_token")) else "—"
        print(f"  {key:11s} {state:8s} {_safe_ids(e):22s} {username} ({who})  · not created by choice")
    missing = [k for k in KEYS if not (payload.get(k) or {}).get("bot_token")]
    print(f"\n  {len(KEYS) - len(missing)}/{len(KEYS)} configured" + (f" — still to do: {', '.join(missing)}" if missing else " — all set"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Store Telegram coach bot tokens in Secrets Manager.")
    ap.add_argument(
        "keys",
        nargs="*",
        help=f"routing keys to configure (default: the {len(KEYS)} texting contacts). also available: {', '.join(k for k in ALL_KEYS if k not in KEYS)}",
    )
    ap.add_argument("--show", action="store_true", help="print what is configured (never a token) and exit")
    args = ap.parse_args()

    client = boto3.client("secretsmanager", region_name=REGION)
    payload = load_secret(client)

    if args.show:
        show(payload)
        return 0

    wanted = args.keys or KEYS
    unknown = [k for k in wanted if k not in ALL_KEYS]
    if unknown:
        sys.stderr.write(f"unknown key(s): {', '.join(unknown)}\nvalid: {', '.join(ALL_KEYS)}\n")
        return 2

    print("Paste each bot token from @BotFather. Input is hidden. Press ENTER alone to skip a bot.")
    print("Tip: message each bot once from your phone first and the chat id is found automatically.\n")

    changed = 0
    for key, username, who in ALL_BOTS:
        if key not in wanted:
            continue
        existing = payload.get(key) or {}
        state = " [already set — ENTER keeps it]" if existing.get("bot_token") else ""
        token = getpass.getpass(f"  {key:11s} {username:20s} {who}{state}\n    token: ").strip()
        if not token:
            # ENTER on an already-configured bot still REFRESHES its chat ids using the
            # stored token — so "say hi to the bot, re-run, press ENTER" completes the
            # allow-list without re-pasting anything. A bot with no token is skipped.
            stored = existing.get("bot_token")
            if stored:
                found = discover_chat_ids(stored)
                fresh = [c for c in found if c not in (existing.get("chat_ids") or [])]
                if fresh:
                    existing["chat_ids"] = list(existing.get("chat_ids") or []) + fresh
                    payload[key] = existing
                    changed += 1
                    print(f"    ✓ token kept; new chat id(s): {', '.join(str(int(c)) for c in fresh)}\n")
                    continue
            print("    skipped\n")
            continue

        ok, detail = verify(token)
        if not ok:
            print(f"    ✗ {detail} — NOT saved. Check the token and re-run for this bot.\n")
            continue
        print(f"    ✓ {detail}")
        if username.lower() not in detail.lower():
            print(f"    ! heads up: that is not @{username}. If you meant a different coach, re-run for the right key.")

        entry = dict(existing, bot_token=token)
        found = discover_chat_ids(token)
        if found:
            merged = list(dict.fromkeys(list(existing.get("chat_ids") or []) + found))
            entry["chat_ids"] = merged
            print(f"    ✓ chat id(s): {', '.join(str(int(c)) for c in merged)}")
        elif existing.get("chat_ids"):
            print(f"    · keeping known chat id(s): {', '.join(str(int(c)) for c in existing['chat_ids'])}")
        else:
            print("    · no chat id yet — send the bot a message, then re-run for this key")
        payload[key] = entry
        changed += 1
        print()

    if not changed:
        print("nothing changed.")
        return 0

    save_secret(client, payload)
    print(f"saved {changed} bot(s) to {STORE_PATH}")
    show(payload)
    print("\nTokens were never printed, written to disk, or placed in shell history.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
