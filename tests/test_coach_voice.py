"""tests/test_coach_voice.py — behavior pins for coach voice notes (#2494).

The mechanism: a qualifying coach reply is SPOKEN — Telegram ``sendVoice``, in the
persona's own ``tts_voice`` — instead of typed.

What is pinned here, in the order the defects would actually appear:

* **the transport**, because it is the part that could break everything else: a
  text send must still be ``application/x-www-form-urlencoded``, and only a call
  carrying a ``(filename, bytes)`` part may go multipart. `_tg_body` is the seam
  #2485 split out, and this file is what stops the multipart branch from leaking
  into the ~dozen text sends that share it;
* **the gates**, each pinned by its own failure: an ungrounded turn, a paused
  tier, a data-heavy reply, a coach with no posture, a coach with a posture but no
  voice. Every one of them must fall back to the TYPED reply — the feature may
  never be the reason a coach says nothing;
* **absence honesty (ADR-104)**: no configured posture and no configured
  ``tts_voice`` each mean silence-from-this-feature, never a stand-in voice.

No real Telegram call and no real TTS call: the transport is a recorder and the
synthesizer is injected.
"""

from __future__ import annotations

import os
import sys
from urllib.parse import parse_qs

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from coach import coach_voice, telegram_worker_lambda as worker  # noqa: E402

MP3 = b"\xff\xfb\x90\x00fake-mp3-frames"
SPEAKABLE = "Good. Take the rest day and come back Thursday."
# NB the shape: the rate word opens the posture and the "never" qualifier lives in a
# LATER clause. That is exactly the reading ``posture_permits_voice`` implements —
# an opening "Never" forbids; a trailing "never for numbers" narrows.
POSTURE = {"texting_style": {"voice_note_posture": "Occasionally, for short encouragement. Never for numbers."}}


def _synth(text, voice_name):
    _synth.calls.append((text, voice_name))
    return MP3


_synth.calls = []


def _always_sample(monkeypatch):
    """Take the occasional-ness out of the equation.

    Load-bearing, not convenience: without it a gate test can pass because the
    sampler happened to decline this sentence, which is a pass for the wrong
    reason — it survives a mutation that removes the gate entirely. (Measured:
    the missing-``tts_voice`` pin did exactly that before this was added.)"""
    monkeypatch.setattr(coach_voice, "sampled", lambda text, rate: rate > 0)


@pytest.fixture(autouse=True)
def _reset():
    _synth.calls = []
    yield


# ── The transport: the urlencoded contract must survive the multipart branch ──


def test_a_text_send_is_still_form_urlencoded():
    """The mutation guard for every existing send. If the multipart branch ever
    catches a plain payload, this is the test that says so."""
    body, ctype = worker._tg_body({"chat_id": 42, "text": "hey"})
    assert ctype == "application/x-www-form-urlencoded"
    assert parse_qs(body.decode()) == {"chat_id": ["42"], "text": ["hey"]}


def test_a_payload_with_an_audio_part_goes_multipart_and_carries_the_bytes():
    body, ctype = worker._tg_body({"chat_id": 42, "voice": ("voice.mp3", MP3)})
    assert ctype.startswith("multipart/form-data; boundary=")
    boundary = ctype.split("boundary=", 1)[1]
    assert body.startswith(f"--{boundary}\r\n".encode()) and body.endswith(f"--{boundary}--\r\n".encode())
    assert b'name="chat_id"' in body and b"\r\n\r\n42\r\n" in body
    assert b'name="voice"; filename="voice.mp3"' in body and b"Content-Type: audio/mpeg" in body
    assert MP3 in body, "the audio must survive encoding byte-for-byte"
    assert boundary.encode() not in MP3, "a boundary that can appear in the payload would corrupt the upload"


# ── The gates ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("status", ["held", "paused", "capped", "error", "reacted", None])
def test_only_a_grounded_reply_is_ever_spoken(status):
    """Synthesis runs AFTER the grounding gate or not at all — a held turn's honest
    deferral is a thing to read, not a thing to hear a friend say."""
    assert coach_voice.qualifies([SPEAKABLE], status=status, tier=0) is False


def test_a_grounded_reply_qualifies():
    assert coach_voice.qualifies([SPEAKABLE], status="sent", tier=0) is True
    assert coach_voice.qualifies([SPEAKABLE], status="regenerated", tier=0) is True


def test_voice_notes_pause_at_the_same_tier_chat_pauses():
    """Not a second literal: the gate calls the SAME ``budget_refusal`` the reply
    path obeys, so the two can never drift apart."""
    from coach import coach_chat

    paused = next(t for t in range(4) if coach_chat.budget_refusal(t, 0) is not None)
    assert coach_voice.qualifies([SPEAKABLE], status="sent", tier=paused) is False
    assert coach_voice.qualifies([SPEAKABLE], status="sent", tier=paused - 1) is True
    assert coach_voice.qualifies([SPEAKABLE], status="sent", tier=None) is True, "an unknown tier must not mute the coach"


@pytest.mark.parametrize(
    "text",
    [
        "170 g protein, 2100 kcal, 38 % carbs — hold that through Friday.",
        "Three things:\n- sleep\n- protein\n- zone 2",
        "You slept 7.1, 6.4, 7.8, 6.9 and 7.2 this week.",
        "x" * (coach_voice.MAX_CHARS + 1),
    ],
)
def test_data_heavy_replies_stay_text(text):
    assert coach_voice.is_data_heavy(text) is True
    assert coach_voice.qualifies([text], status="sent", tier=0) is False


def test_one_figure_in_a_sentence_is_still_speakable():
    assert coach_voice.is_data_heavy("Nice — that's 3 sessions this week. Keep it.") is False


def test_a_burst_stays_text():
    """A voice note is one message. A multi-bubble burst is a conversation shape
    that a single audio file cannot carry."""
    assert coach_voice.qualifies([SPEAKABLE, "And drink something."], status="sent", tier=0) is False


# ── Absence honesty (ADR-104) ─────────────────────────────────────────────────


def test_a_persona_with_no_posture_never_speaks(monkeypatch):
    """No configured posture is not permission to improvise one — the same rule
    ``emoji_posture`` follows. This is why the feature ships dark: a coach with a
    perfectly good ``tts_voice`` still says nothing until the owner writes its
    spoken register."""
    _always_sample(monkeypatch)
    monkeypatch.setattr("coach.persona_core.load_voice_spec", lambda *a, **k: {"texting_style": {"emoji_posture": "Essentially never."}})
    monkeypatch.setattr("coach.persona_registry.tts_voice", lambda *a, **k: "en-US-Chirp3-HD-Kore")
    assert coach_voice.voice_note([SPEAKABLE], persona_id="physical_coach", status="sent", tier=0, synth=_synth) is None
    assert _synth.calls == []


@pytest.mark.parametrize("posture", [None, "", "   ", "Never — he reads, he doesn't listen."])
def test_postures_that_forbid_voice(posture):
    assert coach_voice.posture_permits_voice(posture) is False
    assert coach_voice.posture_rate(posture) == 0.0


def test_a_rate_word_sets_how_often_a_qualifying_reply_is_spoken():
    assert coach_voice.posture_rate("Rarely. Only after a hard session.") < coach_voice.posture_rate("Occasionally, short ones.")
    assert coach_voice.posture_rate("Occasionally, short ones.") < coach_voice.posture_rate("Often — he likes hearing it.")
    assert coach_voice.posture_rate("Short spoken notes.") == coach_voice._DEFAULT_RATE


def test_sampling_is_deterministic_and_actually_selective():
    texts = [f"Sentence number {i} of the sample." for i in range(400)]
    picked = [t for t in texts if coach_voice.sampled(t, 0.25)]
    assert 0 < len(picked) < len(texts), "a rate of 0.25 must select some replies and reject others"
    assert all(coach_voice.sampled(t, 0.25) for t in picked), "the same text must always make the same choice"
    assert not any(coach_voice.sampled(t, 0.0) for t in texts)
    assert all(coach_voice.sampled(t, 1.0) for t in texts)


def test_no_shipped_coach_is_armed_yet():
    """The mechanism ships dark on purpose: arming a coach means writing that
    coach's own spoken register, which is the owner's call, not this module's.
    When the first posture lands, this pin is the place that records it."""
    import glob
    import json

    armed = []
    for path in sorted(glob.glob(os.path.join(os.path.dirname(__file__), "..", "config", "coaches", "*.json"))):
        with open(path, encoding="utf-8") as fh:
            spec = json.load(fh)
        style = (spec or {}).get("texting_style") if isinstance(spec, dict) else None
        if isinstance(style, dict) and coach_voice.posture_permits_voice(style.get("voice_note_posture")):
            armed.append(os.path.basename(path))
    assert armed == [], f"a coach was armed for voice notes without updating this pin: {armed}"


def test_a_posture_without_a_registry_voice_sends_no_voice_note(monkeypatch):
    """The one case that would otherwise put a stranger's voice on the phone."""
    _always_sample(monkeypatch)
    monkeypatch.setattr("coach.persona_core.load_voice_spec", lambda *a, **k: POSTURE)
    monkeypatch.setattr("coach.persona_registry.tts_voice", lambda *a, **k: None)
    assert coach_voice.voice_note([SPEAKABLE], persona_id="physical_coach", status="sent", tier=0, synth=_synth) is None
    assert _synth.calls == [], "no voice configured must mean no synthesis, not a default voice"


# ── The happy path + the fallbacks ────────────────────────────────────────────


def _arm(monkeypatch, voice="en-US-Chirp3-HD-Kore"):
    monkeypatch.setattr("coach.persona_core.load_voice_spec", lambda *a, **k: POSTURE)
    monkeypatch.setattr("coach.persona_registry.tts_voice", lambda *a, **k: voice)
    _always_sample(monkeypatch)


def test_an_armed_persona_speaks_in_its_own_voice(monkeypatch):
    _arm(monkeypatch)
    audio = coach_voice.voice_note([SPEAKABLE], persona_id="physical_coach", status="sent", tier=0, synth=_synth)
    assert audio == MP3
    assert _synth.calls == [(SPEAKABLE, "en-US-Chirp3-HD-Kore")]


def test_a_tts_failure_falls_back_to_text_rather_than_silence(monkeypatch):
    _arm(monkeypatch)

    def boom(text, voice_name):
        raise RuntimeError("google 400: sentences that are too long")

    assert coach_voice.voice_note([SPEAKABLE], persona_id="physical_coach", status="sent", tier=0, synth=boom) is None


def test_empty_audio_falls_back_to_text(monkeypatch):
    _arm(monkeypatch)
    assert coach_voice.voice_note([SPEAKABLE], persona_id="physical_coach", status="sent", tier=0, synth=lambda t, v: b"") is None


def test_a_spoken_note_stays_under_the_tts_per_sentence_cap(monkeypatch):
    """MAX_CHARS exists partly so ``google_tts``'s ~200-char per-SENTENCE cap
    (#2148) never has to hard-split a coach's line mid-clause on the phone."""
    from ai import google_tts

    assert coach_voice.MAX_CHARS <= google_tts.CHUNK_CHARS
    assert all(len(p) <= google_tts.PER_SENTENCE_CHARS for p in google_tts._sentence_pieces(SPEAKABLE))


# ── The worker wiring: spoken INSTEAD of typed, never in addition ─────────────


class TestWorkerSend:
    @pytest.fixture(autouse=True)
    def _wire(self, monkeypatch):
        self.sent = []
        self.metrics = []
        monkeypatch.setattr(worker, "_tg", lambda token, method, payload: self.sent.append((method, payload)))
        monkeypatch.setattr(worker, "_current_tier", lambda: 0)
        monkeypatch.setattr(worker, "_s3_client", lambda: None)
        monkeypatch.setattr(worker, "_emit_metric", lambda name, cid: self.metrics.append((name, cid)))
        yield

    def test_an_unarmed_send_is_typed_exactly_as_before(self, monkeypatch):
        monkeypatch.setattr(worker.coach_voice, "voice_note", lambda *a, **k: None)
        out = worker._send_bubbles("tok", 1, [SPEAKABLE], persona_id="physical_coach", status="sent")
        assert [m for m, _ in self.sent] == ["sendMessage"]
        assert out == [SPEAKABLE] and self.metrics == []

    def test_an_armed_send_speaks_and_does_not_also_type(self, monkeypatch):
        monkeypatch.setattr(worker.coach_voice, "voice_note", lambda *a, **k: MP3)
        out = worker._send_bubbles("tok", 1, [SPEAKABLE], persona_id="physical_coach", status="sent")
        methods = [m for m, _ in self.sent]
        assert methods == ["sendVoice"], "a voice note replaces the typed reply; sending both is a duplicate"
        assert self.sent[0][1]["voice"] == (coach_voice.FILENAME, MP3)
        assert out == [SPEAKABLE], "what is STORED is the text either way — the thread must stay readable"
        assert self.metrics == [("TelegramVoiceNoteSent", "physical_coach")]

    def test_an_unsolicited_path_never_speaks(self, monkeypatch):
        """Check-ins, referrals and the event sweep pass no persona_id/status, so a
        coach can never open a conversation with an audio file out of nowhere.

        Everything else is armed for real here — spec, registry voice, sampler — so
        the ONLY thing keeping this typed is the missing opt-in."""
        _arm(monkeypatch)
        monkeypatch.setattr("ai.google_tts.synthesize", lambda *a, **k: MP3)
        worker._send_bubbles("tok", 1, [SPEAKABLE])
        assert [m for m, _ in self.sent] == ["sendMessage"]
        assert worker._send_bubbles("tok", 1, [SPEAKABLE], persona_id="physical_coach", status="sent") == [SPEAKABLE]
        assert [m for m, _ in self.sent] == ["sendMessage", "sendVoice"], "the opt-in is the only difference between these two"

    def test_referral_markers_are_stripped_before_anything_is_spoken(self, monkeypatch):
        seen = []
        monkeypatch.setattr(worker.coach_voice, "voice_note", lambda bubbles, **k: seen.append(list(bubbles)) or MP3)
        worker._send_bubbles("tok", 1, [SPEAKABLE + "\n[[REFER: sleep_coach]]"], persona_id="physical_coach", status="sent")
        assert seen and "[[REFER" not in "".join(seen[0]), "machine syntax must never be spoken aloud"
