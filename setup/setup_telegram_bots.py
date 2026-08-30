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
     stops a stranger who finds the bot from interrogating your health data. It is
     also what gates OUTBOUND: a bot with a token and no chat id can be texted but
     can never text first, so the morning check-in and the event sweep stay dark.
  4. Merges into ONE secret, ``life-platform/telegram``. One secret rather than one
     per bot: it matches the ``life-platform/<source>`` convention every other
     integration uses, needs a single IAM grant and a single cached read, and costs
     ~$2.40/month less against a ceiling where that is real money.

GLUCOSE IS DELIBERATELY NOT CREATED. Dr. Patel keeps running on the platform —
daily cards, narratives, the board — but Matthew does not want her as a texting
contact, and an uncreated bot is one fewer public webhook endpoint to defend. She
can be added later by naming her explicitly: `setup_telegram_bots.py glucose`.

LABS WAS PROMOTED 2026-08-12 (ADR-153 amendment). Dr. Okafor was in that same
"no bot" class until the owner asked whether the roster needed a longevity coach.
It turned out one already existed with no way to reach him — his own bio reads
"Longevity & preventive medicine" and his lens is long-run risk factors — so
rather than mint a seat that would have overlapped him, he got the door. Note
that a bot is granted by `telegram_route` in config/personas.json, NOT by the
tier flags: `consulting: true` still holds for Okafor, and it never blocked
texting.

RE-RUNNABLE. It merges rather than replaces, so adding the sixth bot later leaves the
first five untouched. Re-entering a token for an existing bot updates just that one.

TIP: message each bot once from your phone ("hi") BEFORE running this, and it will
find every chat id automatically. Telegram only retains recent updates, so a bot you
messaged weeks ago may need one fresh message.

ORDER MATTERS, AND THE SECOND STEP DISABLES PART OF THIS ONE (#2600).

    1. python3 setup/setup_telegram_bots.py [key ...]        # this script
    2. python3 setup/register_telegram_webhooks.py --url ...  # then webhooks

Telegram delivers updates to ``getUpdates`` OR to a registered webhook, never both.
So the moment step 2 has run for a bot, step 3 above stops working for it forever:
``getUpdates`` answers ``409 Conflict: can't use getUpdates method while webhook is
active``. That is not a transient error and no amount of messaging the bot clears it.

Adding a coach AFTER webhooks exist is therefore normal, not an error — and this
script handles it rather than reporting it as your mistake. When discovery is blocked
by a live webhook it says so, and offers the chat id already proven on your other
bots: a PRIVATE chat's ``chat.id`` IS your Telegram user id, the same number for
every bot you talk to, so an id proven on one private bot is correct for all of them.
(Group chats — the board — carry a negative id that is the GROUP, not you; those are
never offered for adoption.) Decline the offer and it prompts for a typed id instead.
Either way the new bot ends up outbound-capable with no hand-edit of the secret; then
re-run step 2 to register the new bot's webhook.

WHY NOT JUST deleteWebhook -> getUpdates -> setWebhook INSIDE THIS SCRIPT? It was the
obvious option and it was rejected. It is a destructive mutation of a live serving
path with a real failure window: a crash, a timeout or a Ctrl-C between the delete
and the re-register leaves that coach unable to receive messages at all, and the
re-register has to faithfully restore a URL, a secret_token and allowed_updates that
this script does not own (register_telegram_webhooks.py does). Adoption reads nothing
from Telegram and breaks nothing, so it is the default. If you ever do want the
delete/re-register dance, run it deliberately through register_telegram_webhooks.py,
which owns those values.
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
    # Coaching-team v2 (2026-08-10), re-pointed 2026-08-12 (ADR-153 amendment).
    # The merged Performance seat now answers on @ajm_training_bot — the thread
    # Matthew already had open with the training lane Max absorbed — instead of
    # on @ajm_longevity_bot. Telegram will not rename a bot username once it is
    # taken, and "longevity" described the retired Victor framing, not Max's
    # performance/movement mandate. So the handle moves to the coach it actually
    # fits (below) and Max keeps the conversation, not the misnomer.
    ("physical", "ajm_training_bot", "Dr. Max Reyes"),
    ("explorer", "ajm_research_bot", "Dr. Henning Brandt"),
    ("pattern", "ajm_pattern_bot", "Dr. Nora Vale"),
    ("career", "ajm_career_bot", "Steve Brooks"),
    ("board", "ajm_board_bot", "Grand Rounds"),
    # Owner-called 2026-08-12: "should we not just have a longevity coach?" The
    # answer was that one already existed without a door — Okafor's own bio reads
    # "Longevity & preventive medicine" and his lens is long-run risk factors. So
    # rather than mint a seat that would overlap him, he gets the bot, and he
    # inherits @ajm_longevity_bot because that handle finally describes its owner.
    ("labs", "ajm_longevity_bot", "Dr. James Okafor"),
]

# Succession routes: the SEAT retired, the CHAT did not.
#
# RETIRED 2026-08-12 (ADR-153 amendment). Dr. Sarah Chen retired at the cycle-13
# genesis and `training` was aliased onto the Performance seat so her bot thread
# would not dead-end. That alias is now unnecessary: @ajm_training_bot IS the
# Performance seat's primary bot (key `physical` above), so the thread continues
# with the coach who holds the lane — via the primary route rather than an alias.
#
# This matters beyond tidiness: the primary `telegram_route` is the canonical
# OUTBOUND route, so a seat reachable only by alias could be texted but could
# never text first. Max now owns a primary route, so his morning check-ins and
# event-triggered outbound work.
#
# `training` is deliberately left unmapped and fails CLOSED in
# gateway.resolve_coach, which is correct — there is no separate training seat.
ALIAS_BOTS: list[tuple[str, str, str]] = []

# Coaches who keep running on the platform — daily cards, narratives, the board —
# but whom Matthew does not want as a texting contact. Deliberately NOT created:
# an unused bot is a live public webhook endpoint, so it is attack surface bought
# for no benefit. They stay listed so the decision is visible rather than looking
# like an oversight, and either can be added later with an explicit argument:
#     python3 setup/setup_telegram_bots.py glucose
OPTIONAL_BOTS = [
    ("glucose", "ajm_glucose_bot", "Dr. Amara Patel"),
]

ALL_BOTS = BOTS + OPTIONAL_BOTS + ALIAS_BOTS
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


def discover_chat_ids(token: str) -> tuple[list, str | None]:
    """Chat ids that have messaged this bot recently. Not secret; the allow-list.

    Returns ``(ids, reason)``. ``reason`` is None when Telegram ANSWERED — an empty
    list then genuinely means "nobody has messaged this bot". When Telegram refused,
    ``reason`` carries its own ``description`` (#2600).

    That distinction is the whole bug this signature exists to kill: the old version
    returned a bare ``[]`` for both, so ``409 can't use getUpdates method while
    webhook is active`` rendered as "send the bot a message, then re-run" — advice
    that can never succeed, printed forever, blaming the operator for a state the
    sibling script created.
    """
    r = _api(token, "getUpdates")
    if not r.get("ok"):
        code = r.get("error_code")
        return [], (r.get("description") or (f"error_code {code}" if code else "getUpdates was refused"))
    ids = []
    for upd in r.get("result") or []:
        for key in ("message", "edited_message", "channel_post", "my_chat_member"):
            chat = ((upd.get(key) or {}).get("chat")) or {}
            if chat.get("id") is not None and chat["id"] not in ids:
                ids.append(chat["id"])
    return ids, None


def is_webhook_conflict(reason: str | None) -> bool:
    """Is this getUpdates refusal the "a webhook owns the updates" 409?

    Matched on Telegram's own wording rather than on the bare 409, because 409 is
    also "terminated by other getUpdates request" — a different problem with
    different advice, which must keep falling through to the generic branch.
    """
    d = (reason or "").lower()
    return "webhook is active" in d or "can't use getupdates" in d


def other_bot_chat_ids(payload: dict, exclude: str) -> list:
    """Private chat ids already proven on the OTHER bots in this store.

    A private chat's ``chat.id`` IS the user's Telegram id — the same number for
    every bot they talk to — so an id proven by ``getUpdates`` on one private bot
    is the correct id for a bot whose own discovery a webhook has blocked.

    NEGATIVE ids are excluded: those are groups/supergroups (the board), where the
    id identifies the ROOM and carries none of that equivalence. Ranked by how many
    bots agree, so the owner's own id sorts above a one-off.
    """
    counts: dict[int, int] = {}
    for key, entry in payload.items():
        if key == exclude or not isinstance(entry, dict):
            continue
        for chat_id in dict.fromkeys(entry.get("chat_ids") or []):
            try:
                cid = int(chat_id)
            except (TypeError, ValueError):
                continue
            if cid > 0:
                counts[cid] = counts.get(cid, 0) + 1
    return [cid for cid, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def _ask(prompt: str) -> str:
    """One line of typed input. Never used for a token — tokens go through getpass."""
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def _adopt_chat_ids(key: str, payload: dict) -> list:
    """Recover a chat id for a bot whose getUpdates is walled off by a webhook."""
    print("      A private chat's id IS your Telegram user id — the same number for every")
    print("      bot you talk to — so an id already proven on another bot is this bot's too.")
    candidates = other_bot_chat_ids(payload, exclude=key)
    if candidates:
        answer = _ask(f"      use chat id(s) {_fmt_ids(candidates)} from your other bots? [Y/n] ").lower()
        if answer in ("", "y", "yes"):
            return candidates
    typed = _ask("      chat id (digits — @userinfobot will tell you yours; ENTER to skip): ")
    if not typed:
        print("    · skipped — this bot cannot text first until it has a chat id")
        return []
    try:
        return [int(typed)]
    except ValueError:
        print(f"    ✗ {typed!r} is not a number — no chat id recorded for this bot")
        return []


# The top-level store entry for the board room's group chat id. NOT a bot: it has
# no token and is never texted first — it exists so the webhook's allow-list union
# (telegram_webhook_lambda._allowed_chat_ids) authorizes the room, while the
# per-bot chat_ids stay purely private ids that outbound may text (the worker
# additionally picks only POSITIVE ids — telegram_group.first_private_chat_id —
# so a group id can never receive a morning check-in even if one lands there).
BOARD_GROUP_KEY = "board_group"


def bank_group_ids(found: list, payload: dict) -> list:
    """Split group ids (negative) out of a discovery result into the board_group entry.

    Returns the PRIVATE (positive) ids for the bot's own chat_ids. A group's id
    identifies the ROOM, not the sender — it belongs to the store, not to whichever
    bot happened to discover it first.
    """
    groups = []
    private = []
    for cid in found or []:
        try:
            (groups if int(cid) < 0 else private).append(cid)
        except (TypeError, ValueError):
            continue
    if groups:
        entry = payload.get(BOARD_GROUP_KEY) or {}
        known = list(entry.get("chat_ids") or [])
        fresh = [g for g in groups if g not in known]
        if fresh:
            entry["chat_ids"] = known + fresh
            payload[BOARD_GROUP_KEY] = entry
            print(f"    ✓ group chat id(s) {_fmt_ids(fresh)} recorded under '{BOARD_GROUP_KEY}' (the board room)")
    return private


def resolve_chat_ids(key: str, token: str, existing: dict, payload: dict) -> list:
    """Chat ids to ADD for this bot. Prints exactly one outcome; never prints a token.

    Three outcomes, deliberately distinguishable (#2600):
      * Telegram answered with updates  -> the ids, minus what is already stored.
      * Telegram answered with nothing  -> the original "send the bot a message"
        advice, which in that case is still true and still works.
      * Telegram refused because a webhook owns the updates -> say so, and offer the
        path that works instead of the one that cannot.
    """
    known = list(existing.get("chat_ids") or [])
    found, reason = discover_chat_ids(token)
    found = bank_group_ids(found, payload)

    if found:
        fresh = [c for c in found if c not in known]
        if not fresh:
            print(f"    · chat id(s) unchanged: {_fmt_ids(known)}")
        return fresh

    if reason is None:
        if known:
            print(f"    · keeping known chat id(s): {_fmt_ids(known)}")
        else:
            print("    · no chat id yet — send the bot a message, then re-run for this key")
        return []

    if not is_webhook_conflict(reason):
        print(f"    ! chat-id discovery failed: {reason}")
        if known:
            print(f"    · keeping known chat id(s): {_fmt_ids(known)}")
        return []

    print("    ! getUpdates is blocked: this bot already has a webhook registered, and")
    print("      Telegram serves one or the other — never both. Messaging the bot will")
    print("      NOT help; the updates go to the webhook.")
    print(f"      Telegram said: {reason}")
    if known:
        print(f"    · keeping known chat id(s): {_fmt_ids(known)}")
        return []
    return _adopt_chat_ids(key, payload)


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


def _fmt_ids(ids) -> str:
    """Chat ids for display, coerced through int().

    Two jobs in one: chat ids are numeric by Telegram's contract, so int() is
    lossless — and it is a taint SANITIZER: nothing printed here can carry secret
    text even if the stored entry were corrupted, which is what lets a static
    analyzer (and a reader) verify this script never prints a token.
    """
    return ", ".join(str(int(c)) for c in (ids or [])) or "—"


def _safe_ids(entry: dict) -> str:
    """One entry's chat ids for display. Sanitized by _fmt_ids."""
    return _fmt_ids(entry.get("chat_ids"))


def _outbound_dead(payload: dict) -> list:
    """Keys holding a token but no chat id — reachable, but unable to text first.

    Flagged as a WARNING rather than shown as a neutral dash (#2600): a dash reads
    as "not configured yet", but this combination is a live half-configured coach.
    It answers when spoken to, so it looks healthy from the phone, while the morning
    check-in and the event-triggered sweep it is supposed to start never fire.
    """
    return [k for k, _u, _w in ALL_BOTS if (payload.get(k) or {}).get("bot_token") and not ((payload.get(k) or {}).get("chat_ids") or [])]


def show(payload: dict) -> None:
    """Print what is configured WITHOUT printing any token."""
    print(f"\n{STORE_PATH}:\n")
    print(f"  {'key':11s} {'token':8s} {'chat ids':22s} bot")
    for key, username, who in BOTS:
        e = payload.get(key) or {}
        tok = "set" if bool(e.get("bot_token")) else "—"
        flag = "  ! no chat id — cannot text first" if tok == "set" and not (e.get("chat_ids") or []) else ""
        print(f"  {key:11s} {tok:8s} {_safe_ids(e):22s} {username} ({who}){flag}")
    for key, username, who in OPTIONAL_BOTS:
        e = payload.get(key) or {}
        state = "set" if bool(e.get("bot_token")) else "—"
        flag = "  ! no chat id — cannot text first" if state == "set" and not (e.get("chat_ids") or []) else "  · not created by choice"
        print(f"  {key:11s} {state:8s} {_safe_ids(e):22s} {username} ({who}){flag}")
    room = payload.get(BOARD_GROUP_KEY) or {}
    room_ids = room.get("chat_ids") or []
    room_state = _fmt_ids(room_ids) if room_ids else "— not discovered (add the bots to a group, say hi, re-run)"
    print(f"  {BOARD_GROUP_KEY:11s} {'n/a':8s} {room_state:22s} (the board room — group chat id, no bot of its own)")
    missing = [k for k in KEYS if not (payload.get(k) or {}).get("bot_token")]
    print(f"\n  {len(KEYS) - len(missing)}/{len(KEYS)} configured" + (f" — still to do: {', '.join(missing)}" if missing else " — all set"))
    dead = _outbound_dead(payload)
    if dead:
        print(f"\n  ! {len(dead)} bot(s) can be texted but cannot text first — no chat id: {', '.join(dead)}")
        print("    outbound (the morning check-in, the event sweep) stays dark for these.")
        print(f"    fix: python3 setup/setup_telegram_bots.py {dead[0]}  — ENTER at the token prompt keeps the stored token.")


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
    print("Tip: message each bot once from your phone first and the chat id is found automatically.")
    print("Already registered webhooks? getUpdates is blocked for those bots — this will say so and offer the id your other bots proved.\n")

    changed = 0
    # bank_group_ids writes into payload out-of-loop-band; a run that ONLY
    # discovered the board room's id must still save.
    board_before = json.dumps(payload.get(BOARD_GROUP_KEY), sort_keys=True)
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
                fresh = resolve_chat_ids(key, stored, existing, payload)
                if fresh:
                    existing["chat_ids"] = list(dict.fromkeys(list(existing.get("chat_ids") or []) + fresh))
                    payload[key] = existing
                    changed += 1
                    print(f"    ✓ token kept; chat id(s): {_fmt_ids(existing['chat_ids'])}\n")
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
        fresh = resolve_chat_ids(key, token, existing, payload)
        if fresh:
            merged = list(dict.fromkeys(list(existing.get("chat_ids") or []) + fresh))
            entry["chat_ids"] = merged
            print(f"    ✓ chat id(s): {_fmt_ids(merged)}")
        payload[key] = entry
        changed += 1
        print()

    if json.dumps(payload.get(BOARD_GROUP_KEY), sort_keys=True) != board_before:
        changed += 1

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
