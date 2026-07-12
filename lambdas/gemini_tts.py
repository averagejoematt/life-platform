"""gemini_tts.py — single-pass, multi-speaker TTS via Gemini 2.5 (AI Studio key).

Generates a genuine two-person conversation in ONE pass — turn-taking, intonation
and timing are natural (the "NotebookLM" feel), unlike per-line Chirp stitching.
Used for Episode 0 (Elena interviews the Principal Investigator) and available to
the weekly Panel (Elena + one coach). Gemini multi-speaker caps at 2 speakers,
which is exactly these formats.

Auth: the `gemini_key` field of the life-platform/google-tts secret — a personal
AI Studio key (the managed mattsusername.com domain blocks AI Studio, so the key
comes from a consumer Google account). Plain API key over urllib, no OAuth.

Output: Gemini returns 16-bit PCM (L16 @ 24 kHz, mono); we wrap it in a WAV header
(browsers play WAV natively). Publishers compress it to spoken-word MP3 via
lambdas/audio_encode.py (lameenc-layer, #1018) — WAV at ~385 kbps is a 16.6 MB
cellular toll per 6-min episode; the encoder fails open back to this WAV.
"""

import base64
import json
import os
import struct
import urllib.error
import urllib.request

import boto3
from secret_cache import get_secret_json

SECRET_NAME = os.environ.get("GOOGLE_TTS_SECRET", "life-platform/google-tts")
MODEL = os.environ.get("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
SAMPLE_RATE = 24000
# Prefer ONE call so the whole conversation is truly single-pass (no prosody reset
# at a seam — an 8-turn split produced an audible "handoff" ~2 min in). A full
# ~20-28 turn / ~7 min episode fits one Gemini call (verified). Only splits if a
# script is exceptionally long; PCM from same model+voices concatenates cleanly.
MAX_TURNS_PER_CALL = 40

_sm = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-west-2"))


class GeminiTTSError(RuntimeError):
    pass


def _key() -> str:
    s = get_secret_json(SECRET_NAME, _sm)
    k = s.get("gemini_key")
    if not k:
        raise GeminiTTSError(f"{SECRET_NAME} missing gemini_key")
    return k


def _wav(pcm: bytes, rate: int = SAMPLE_RATE) -> bytes:
    """Wrap mono 16-bit PCM in a WAV container."""
    n = len(pcm)
    return (
        b"RIFF"
        + struct.pack("<I", 36 + n)
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
        + b"data"
        + struct.pack("<I", n)
        + pcm
    )


def _call(transcript: str, label_voice: dict) -> bytes:
    cfgs = [{"speaker": s, "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": v}}} for s, v in label_voice.items()]
    body = {
        "contents": [{"parts": [{"text": transcript}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"multiSpeakerVoiceConfig": {"speakerVoiceConfigs": cfgs}},
        },
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={_key()}"
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:  # noqa: S310 — constant Google API base
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise GeminiTTSError(f"Gemini TTS {e.code}: {e.read().decode('utf-8', 'ignore')[:300]}") from e
    parts = (payload.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
    b64 = next((p["inlineData"]["data"] for p in parts if isinstance(p, dict) and "inlineData" in p), None)
    if not b64:
        raise GeminiTTSError("Gemini TTS response missing audio")
    return base64.b64decode(b64)


def synthesize_dialogue(turns: list, label_voice: dict, style: str = "") -> bytes:
    """turns: [{"speaker": <label present in label_voice>, "line": str}] → WAV bytes.

    The whole transcript is voiced in one pass (chunked only if very long), so the
    two speakers genuinely converse. ``label_voice`` maps each speaker label to a
    Gemini prebuilt voice (e.g. {"Elena": "Aoede", "Eli": "Charon"})."""
    groups = [turns[i : i + MAX_TURNS_PER_CALL] for i in range(0, len(turns), MAX_TURNS_PER_CALL)] or [[]]
    pcm = b""
    for g in groups:
        if not g:
            continue
        lines = "\n".join(f"{t['speaker']}: {t['line']}" for t in g)
        transcript = (style + "\n\n" if style else "") + lines
        pcm += _call(transcript, label_voice)
    return _wav(pcm)
