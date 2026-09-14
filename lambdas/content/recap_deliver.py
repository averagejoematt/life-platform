"""recap_deliver.py — the card reaches his phone, or the run says why (#3747).

THE OWNER'S CHOICE

*"if it is free, the image can be sent to me on telegram and email, otherwise just email,
later on i may narrow it down to one distribution path."*

Both are free at this volume: Telegram's Bot API charges nothing and the coach bot already
holds the credential, and an SES message with a ~45 KB PNG is a fraction of a cent. So
both ship — as ONE fan-out step over a channel list, so narrowing later is deleting a
name rather than unpicking a design.

WHY BOTH, BEYOND THE COST

Telegram's `sendPhoto` re-encodes: it is the fast path to his phone and the wrong thing to
upload to Instagram afterwards. The email attachment is the lossless original. Two
channels are not redundancy here — they are two different jobs.

THE POSTURE THIS SITS UNDER

`fingerprint_broadcast.AUTOMATED_SYNDICATION_REASON` records the standing rule: *"no
automated surface posts a vitals-derived mark. Human selection only."* Delivering
privately to the owner so he chooses what to post is that rule honoured, not bypassed —
and it is why nothing here talks to Instagram.

FAILURE IS REPORTED, NOT SWALLOWED

`telegram_worker._tg` is deliberately fire-and-log: a failed coach reply must never make
Lambda retry and double-bill. This is the opposite case. Whether the card arrived is the
whole point of the run, and the picker row records it per channel — so `send_photo`
raises and `deliver` catches per channel, letting one path fail without silencing the
other.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Callable

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
PNG_CONTENT_TYPE = "image/png"
#: Telegram's own cap on a photo caption.
CAPTION_MAX = 1024


def send_photo(token: str, chat_id: str | int, png: bytes, caption: str = "", *, filename: str = "recap.png", timeout: int = 20) -> dict:
    """One `sendPhoto` call. RAISES on failure — the caller records the outcome."""
    from coach.coach_voice import multipart_body

    fields: dict[str, Any] = {"chat_id": str(chat_id)}
    if caption:
        fields["caption"] = caption[:CAPTION_MAX]
    body, content_type = multipart_body(fields, {"photo": (filename, png)}, content_type=PNG_CONTENT_TYPE)
    req = urllib.request.Request(
        TELEGRAM_API.format(token=token, method="sendPhoto"),
        data=body,
        headers={"Content-Type": content_type},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — a pinned api.telegram.org URL
        payload = json.loads(resp.read() or b"{}")
    if not payload.get("ok"):
        raise RuntimeError(f"telegram sendPhoto returned not-ok: {str(payload)[:200]}")
    return payload


def build_email(png: bytes, caption: str, *, subject: str, sender: str, recipient: str, filename: str = "recap.png") -> bytes:
    """A MIME message carrying the caption as text and the card as a real attachment.

    An inline `cid:` image would look nicer in the mail client and would be the wrong
    choice: the job of this message is to hand him a FILE he can upload, and a client that
    renders an inline image gives him a screenshot instead of the original.
    """
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(caption or "Today's card is attached.")
    msg.add_attachment(png, maintype="image", subtype="png", filename=filename)
    return msg.as_bytes()


def _deliver_telegram(png: bytes, caption: str, *, secret_getter: Callable[[], dict] | None, bot_key: str, filename: str) -> str:
    from coach import telegram_group

    entry = (secret_getter() if secret_getter else {}).get(bot_key) or {}
    token = entry.get("bot_token")
    chat_id = telegram_group.first_private_chat_id(entry.get("chat_ids") or [])
    if not token or not chat_id:
        # Not an error: an unconfigured bot is a deployment state, not a failure of the
        # card. Say "dark" so the picker row distinguishes it from a send that broke.
        logger.warning("telegram recap delivery is dark: token=%s chat=%s", bool(token), bool(chat_id))
        return "dark"
    send_photo(token, chat_id, png, caption, filename=filename)
    return "ok"


def _deliver_email(png: bytes, caption: str, *, ses_client, sender: str, recipient: str, subject: str, filename: str, dry_run: bool) -> str:
    from common.send_guard import guarded_send_raw_email

    raw = build_email(png, caption, subject=subject, sender=sender, recipient=recipient, filename=filename)
    guarded_send_raw_email(
        ses_client,
        dry_run,
        Source=sender,
        Destinations=[recipient],
        RawMessage={"Data": raw},
        ConfigurationSetName="life-platform-emails",
    )
    return "dry_run" if dry_run else "ok"


def deliver(
    png: bytes,
    caption: str,
    *,
    channels: list[str] | None = None,
    dry_run: bool = False,
    telegram_secret_getter: Callable[[], dict] | None = None,
    telegram_bot_key: str = "headcoach",
    ses_client=None,
    sender: str = "",
    recipient: str = "",
    subject: str = "",
    filename: str = "recap.png",
) -> dict[str, str]:
    """Fan the card out. Returns {channel: ok|dry_run|dark|error:<Type>} per channel.

    One channel failing never suppresses another: a Telegram outage should not also cost
    him the lossless copy in his inbox.
    """
    out: dict[str, str] = {}
    for channel in channels or ["telegram", "email"]:
        try:
            if dry_run and channel == "telegram":
                out[channel] = "dry_run"
            elif channel == "telegram":
                out[channel] = _deliver_telegram(
                    png, caption, secret_getter=telegram_secret_getter, bot_key=telegram_bot_key, filename=filename
                )
            elif channel == "email":
                out[channel] = _deliver_email(
                    png,
                    caption,
                    ses_client=ses_client,
                    sender=sender,
                    recipient=recipient,
                    subject=subject or "Today's card",
                    filename=filename,
                    dry_run=dry_run,
                )
            else:
                out[channel] = "error:UnknownChannel"
        except Exception as e:  # noqa: BLE001
            logger.error("recap delivery failed on %s: %s: %s", channel, type(e).__name__, e)
            out[channel] = f"error:{type(e).__name__}"
    return out


def caption_for(copies: list[dict[str, Any]], *, day_label: str, date_label: str = "") -> str:
    """The text beside the image — his to paste, or to ignore.

    Assembled from the card's own copy, never generated: a caption is published with the
    image and is subject to the same gate, so it says exactly what the card says.
    """
    bits: list[str] = []
    head = copies[0] if copies else {}
    if head.get("hero") and head.get("label"):
        bits.append(f"{head['hero']} — {str(head['label']).lower()}")
    for line in (head.get("lines") or [])[:2]:
        bits.append(str(line))
    if len(copies) > 1:
        second = copies[1]
        if second.get("hero") and second.get("label"):
            bits.append(f"{second['hero']} {str(second['label']).lower()}")
    head_line = " · ".join(x for x in (day_label, date_label) if x)
    body = "\n".join(bits)
    return f"{head_line}\n{body}".strip()[:CAPTION_MAX]
