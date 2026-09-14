"""tests/test_recap_deliver_3747.py — both paths, and neither silently.

THE OWNER'S CHOICE (2026-09-13)
  *"if it is free, the image can be sent to me on telegram and email, otherwise just
  email, later on i may narrow it down to one distribution path."*

Both are free at this volume, so both ship — as ONE fan-out over a channel list, so
narrowing later deletes a name rather than unpicking a design. And they do different jobs:
Telegram's sendPhoto re-encodes (fast to his phone), the email attachment is the lossless
original he actually uploads.

WHAT IS PINNED
  1. the multipart encoder stopped hardcoding audio/mpeg WITHOUT moving the voice path
  2. the email carries a real image/png ATTACHMENT, not an inline cid: image — the job is
     to hand him a file, and an inline render gives him a screenshot instead
  3. a dry run sends nothing, on either channel
  4. an unconfigured bot is "dark", a broken send is "error:<Type>" — a deployment state
     and a failure must not read the same in the record
  5. one channel failing never suppresses the other
"""

from __future__ import annotations

import email as email_lib
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))

from coach.coach_voice import AUDIO_CONTENT_TYPE, multipart_body  # noqa: E402
from content import recap_deliver as rd  # noqa: E402

_PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 512


# ── 1. The encoder generalised without moving the path it already served ──────
def test_the_voice_path_still_declares_audio_by_default():
    body, _ct = multipart_body({"chat_id": "1"}, {"voice": ("a.mp3", b"xx")})
    assert f"Content-Type: {AUDIO_CONTENT_TYPE}".encode() in body
    assert AUDIO_CONTENT_TYPE == "audio/mpeg"


def test_a_png_part_declares_image_png():
    body, ct = multipart_body({"chat_id": "1"}, {"photo": ("recap.png", _PNG)}, content_type="image/png")
    assert b"Content-Type: image/png" in body
    assert b"audio/mpeg" not in body
    assert ct.startswith("multipart/form-data; boundary=")


def test_the_photo_part_carries_the_bytes_and_a_filename():
    body, _ct = multipart_body({"chat_id": "1"}, {"photo": ("recap-2026-09-13.png", _PNG)}, content_type="image/png")
    assert b'filename="recap-2026-09-13.png"' in body
    assert _PNG in body


# ── 2. The email hands him a file ─────────────────────────────────────────────
def test_the_email_carries_a_real_png_attachment():
    raw = rd.build_email(_PNG, "Day 8 · 2.3 lb down", subject="Day 8", sender="a@b.c", recipient="d@e.f", filename="recap.png")
    msg = email_lib.message_from_bytes(raw)

    attachments = [p for p in msg.walk() if p.get_content_disposition() == "attachment"]
    assert len(attachments) == 1, "expected exactly one attachment"
    part = attachments[0]
    assert part.get_content_type() == "image/png"
    assert part.get_filename() == "recap.png"
    assert part.get_payload(decode=True) == _PNG, "the attachment is not the card that was rendered"


def test_the_caption_is_the_body_so_he_can_copy_it_from_either_channel():
    raw = rd.build_email(_PNG, "Day 8 · 2.3 lb down", subject="Day 8", sender="a@b.c", recipient="d@e.f")
    msg = email_lib.message_from_bytes(raw)
    body = next(p for p in msg.walk() if p.get_content_type() == "text/plain")
    assert "2.3 lb down" in body.get_payload(decode=True).decode()


def test_there_is_no_inline_image_pretending_to_be_the_deliverable():
    """A cid: render looks nicer and gives him a screenshot instead of the original."""
    raw = rd.build_email(_PNG, "x", subject="s", sender="a@b.c", recipient="d@e.f")
    assert b"cid:" not in raw


# ── 3/4/5. The fan-out's outcomes ─────────────────────────────────────────────
class _SES:
    def __init__(self):
        self.sent = []

    def send_raw_email(self, **kw):
        self.sent.append(kw)
        return {"MessageId": "live-1"}


def _secret(token="fake-bot-token", chat_ids=(12345,)):  # noqa: S107 — a test double, not a credential
    return lambda: {"headcoach": {"bot_token": token, "chat_ids": list(chat_ids)}}


def test_a_dry_run_sends_nothing_on_either_channel(monkeypatch):
    ses = _SES()
    called = {"telegram": 0}
    monkeypatch.setattr(rd, "send_photo", lambda *a, **k: called.__setitem__("telegram", called["telegram"] + 1))

    out = rd.deliver(
        _PNG, "cap", dry_run=True, telegram_secret_getter=_secret(), ses_client=ses, sender="a@b.c", recipient="d@e.f", subject="s"
    )

    assert out == {"telegram": "dry_run", "email": "dry_run"}
    assert called["telegram"] == 0, "a dry run still called Telegram"
    assert ses.sent == [], "a dry run still reached SES"


def test_a_live_run_sends_on_both(monkeypatch):
    """NEGATIVE CONTROL — the dry-run test above proves nothing if this cannot send."""
    ses = _SES()
    seen = {}
    monkeypatch.setattr(rd, "send_photo", lambda token, chat, png, cap, **k: seen.update({"chat": chat, "png": png, "cap": cap}))

    out = rd.deliver(_PNG, "cap", telegram_secret_getter=_secret(), ses_client=ses, sender="a@b.c", recipient="d@e.f", subject="s")

    assert out == {"telegram": "ok", "email": "ok"}
    assert seen["chat"] == 12345 and seen["png"] == _PNG
    assert len(ses.sent) == 1 and ses.sent[0]["ConfigurationSetName"] == "life-platform-emails"


def test_an_unconfigured_bot_is_dark_not_an_error():
    out = rd.deliver(_PNG, "cap", channels=["telegram"], telegram_secret_getter=lambda: {})
    assert out == {"telegram": "dark"}, "an unconfigured bot must not read as a send failure"


def test_a_group_chat_id_is_never_the_destination():
    """Negative ids are groups. An unsolicited card belongs in the 1:1 thread."""
    out = rd.deliver(_PNG, "cap", channels=["telegram"], telegram_secret_getter=_secret(chat_ids=(-100200,)))
    assert out == {"telegram": "dark"}


def test_a_broken_send_is_recorded_by_its_exception_type(monkeypatch):
    def _boom(*a, **k):
        raise TimeoutError("telegram is down")

    monkeypatch.setattr(rd, "send_photo", _boom)
    out = rd.deliver(_PNG, "cap", channels=["telegram"], telegram_secret_getter=_secret())
    assert out == {"telegram": "error:TimeoutError"}


def test_one_channel_failing_does_not_suppress_the_other(monkeypatch):
    """A Telegram outage should not also cost him the lossless copy in his inbox."""

    def _boom(*a, **k):
        raise TimeoutError("down")

    monkeypatch.setattr(rd, "send_photo", _boom)
    ses = _SES()
    out = rd.deliver(_PNG, "cap", telegram_secret_getter=_secret(), ses_client=ses, sender="a@b.c", recipient="d@e.f", subject="s")

    assert out["telegram"].startswith("error:")
    assert out["email"] == "ok"
    assert len(ses.sent) == 1


def test_narrowing_to_one_path_is_deleting_a_name(monkeypatch):
    """The owner said he may narrow later. That must not be a redesign."""
    ses = _SES()
    monkeypatch.setattr(rd, "send_photo", lambda *a, **k: None)
    out = rd.deliver(_PNG, "cap", channels=["email"], ses_client=ses, sender="a@b.c", recipient="d@e.f", subject="s")
    assert out == {"email": "ok"}


# ── The caption ───────────────────────────────────────────────────────────────
def test_the_caption_is_assembled_from_the_card_never_generated():
    copies = [
        {"hero": "2.3 lb", "label": "DOWN THIS WEEK", "lines": ["319.7 lb today"]},
        {"hero": "8/8", "label": "TIER-0 HABITS", "lines": ["4-day streak"]},
    ]
    caption = rd.caption_for(copies, day_label="Day 8", date_label="Sat 13 Sep")

    assert "Day 8" in caption and "2.3 lb" in caption and "319.7 lb today" in caption
    assert "8/8" in caption
    for token in caption.replace("\n", " ").split():
        # Every substantive token must have come from the copy or the labels — nothing
        # invented. (Connectives are the only additions.)
        assert token in str(copies) or token in {"—", "·", "Day", "8", "Sat", "13", "Sep"} or token.islower()


def test_the_caption_respects_telegrams_cap():
    copies = [{"hero": "x" * 900, "label": "Y" * 900, "lines": ["z" * 900]}]
    assert len(rd.caption_for(copies, day_label="Day 8")) <= rd.CAPTION_MAX


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
