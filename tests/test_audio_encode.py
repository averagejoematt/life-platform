"""tests/test_audio_encode.py — #1018 spoken-word compression (offline).

audio_encode turns the Panel's Gemini WAV (16-bit mono PCM @ 24 kHz, ~385 kbps)
into ~80 kbps MP3 via lameenc, and MUST fail open to the original WAV whenever
lameenc is unavailable or the input is odd — a compression hiccup can never
strand an episode. lameenc ships in the lameenc-layer, not requirements-dev, so
the real-encode test self-skips where the wheel isn't installed.
"""

import io
import math
import os
import struct
import sys
import wave

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import audio_encode  # noqa: E402

try:
    import lameenc  # noqa: F401

    HAVE_LAMEENC = True
except ImportError:
    HAVE_LAMEENC = False


def _sine_wav(seconds: float = 2.0, rate: int = 24000, freq: float = 440.0) -> bytes:
    """A tiny 16-bit mono PCM WAV — the exact shape gemini_tts._wav produces."""
    n = int(seconds * rate)
    pcm = b"".join(struct.pack("<h", int(20000 * math.sin(2 * math.pi * freq * i / rate))) for i in range(n))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def test_wav_duration_from_header():
    assert audio_encode.wav_duration_sec(_sine_wav(seconds=3.0)) == 3
    assert audio_encode.wav_duration_sec(b"not a wav at all") == 0


def test_fail_open_without_lameenc(monkeypatch):
    """Layer missing → the caller gets the WAV back, byte-identical (pre-#1018 publish)."""
    monkeypatch.setitem(sys.modules, "lameenc", None)  # import lameenc → ImportError
    wav = _sine_wav()
    body, ext, mime = audio_encode.compress_wav(wav)
    assert (body, ext, mime) == (wav, "wav", "audio/wav")


def test_fail_open_on_unparseable_input():
    junk = b"RIFFgarbage-that-is-not-wav" * 10
    if not HAVE_LAMEENC:
        pytest.skip("lameenc not installed — the ImportError fallback already covers this env")
    body, ext, mime = audio_encode.compress_wav(junk)
    assert (body, ext, mime) == (junk, "wav", "audio/wav")


@pytest.mark.skipif(not HAVE_LAMEENC, reason="lameenc wheel not installed (ships via lameenc-layer)")
def test_real_encode_shrinks_and_is_mp3():
    wav = _sine_wav(seconds=5.0)
    body, ext, mime = audio_encode.compress_wav(wav)
    assert (ext, mime) == ("mp3", "audio/mpeg")
    # MP3 magic: ID3 tag or MPEG frame sync
    assert body[:3] == b"ID3" or (body[0] == 0xFF and (body[1] & 0xE0) == 0xE0)
    # ~385 kbps PCM → 80 kbps target: expect a real shrink, not a rounding win
    assert len(body) < len(wav) / 3
