"""audio_encode.py — compress synthesized speech for the public site (#1018).

The Panel's audio comes out of gemini_tts as 16-bit mono PCM in a WAV container
(24 kHz ≈ 385 kbps) — 16.6 MB for a 6-minute episode, served to cellular
readers. This module turns that WAV into a spoken-word MP3 (default 80 kbps
mono ≈ 3.5 MB per 6 min) via ``lameenc``, a ~250 KB LAME wheel shipped as the
standalone ``lameenc-layer`` (dependency-layer pattern, same as pillow/garth —
build+publish via deploy/build_lameenc_layer.sh; NOT the retired shared layer).

Fail-open BY DESIGN: if the layer is missing or the encode throws, the caller
gets the original WAV back (the pre-#1018 behavior) — a compression hiccup must
never strand an episode. The publish-or-HOLD quality gate is about content and
stays fail-closed; this step is transport weight only.

Why MP3, not the AAC/M4A the issue suggested: Lambda has no encoder binary and
there is no small AAC wheel (PyAV drags ~40 MB of FFmpeg libs; a static ffmpeg
layer is ~78 MB). lameenc is 250 KB, 80 kbps mono MP3 is transparent for
single-voice TTS speech, and audio/mpeg is the most compatible podcast
enclosure type there is. Same 3–4 MB outcome, 1/150th the machinery.
"""

import io
import logging
import os
import wave

logger = logging.getLogger("audio-encode")

# Spoken-word bitrate. 80 kbps mono is transparent for TTS speech; override via
# env for a quality/size retune without a code change. dispatches.js and
# deploy/restart_media_reset.py estimate duration-from-bytes at this rate when
# no duration_sec is available — keep them in sync if this default changes.
DEFAULT_KBPS = int(os.environ.get("PANELCAST_MP3_KBPS", "80"))


def wav_duration_sec(wav_bytes: bytes) -> int:
    """Duration of a WAV clip from its actual header (frames / framerate) — no
    44-byte-header assumptions. Returns 0 if the bytes aren't parseable WAV."""
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            rate = w.getframerate() or 1
            return int(w.getnframes() / rate)
    except Exception:
        return 0


def compress_wav(wav_bytes: bytes, bitrate_kbps: int = None) -> tuple:
    """WAV bytes → (audio_bytes, ext, content_type).

    Success: (mp3_bytes, "mp3", "audio/mpeg").
    Fail-open (lameenc unavailable, unparseable/odd-format WAV, or an encode
    that doesn't actually shrink): (wav_bytes, "wav", "audio/wav") — identical
    to the pre-#1018 publish, never an exception."""
    kbps = bitrate_kbps or DEFAULT_KBPS
    fallback = (wav_bytes, "wav", "audio/wav")
    try:
        import lameenc  # ships in lameenc-layer; absent in unit tests + un-migrated deploys
    except ImportError:
        logger.warning("[audio-encode] lameenc unavailable — publishing uncompressed WAV (fail-open)")
        return fallback
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            channels, sampwidth, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
            pcm = w.readframes(w.getnframes())
        if sampwidth != 2 or channels not in (1, 2):
            logger.warning("[audio-encode] unsupported WAV shape (width=%d ch=%d) — fail-open WAV", sampwidth, channels)
            return fallback
        enc = lameenc.Encoder()
        enc.set_bit_rate(kbps)
        enc.set_in_sample_rate(rate)
        enc.set_channels(channels)
        enc.set_quality(2)  # LAME quality 2 = high; encode speed is irrelevant at our volume
        enc.silence()  # lameenc prints LAME banners to stdout otherwise
        mp3 = bytes(enc.encode(pcm)) + bytes(enc.flush())
        if not mp3 or len(mp3) >= len(wav_bytes):
            logger.warning("[audio-encode] encode produced no gain (%d → %d bytes) — fail-open WAV", len(wav_bytes), len(mp3))
            return fallback
        logger.info("[audio-encode] WAV %d bytes → MP3 %d bytes (%d kbps, %d Hz, %d ch)", len(wav_bytes), len(mp3), kbps, rate, channels)
        return (mp3, "mp3", "audio/mpeg")
    except Exception as e:  # noqa: BLE001 — fail-open is the contract
        logger.warning("[audio-encode] encode failed (%s) — publishing uncompressed WAV (fail-open)", e)
        return fallback
