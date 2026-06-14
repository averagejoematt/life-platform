"""google_tts.py — Google Cloud Text-to-Speech (Chirp 3: HD) over urllib.

Replaces Polly for the podcasts: Chirp 3: HD is the voice family behind
NotebookLM — far more natural than Polly neural. Auth is a plain API key in
Secrets Manager (`life-platform/google-tts` → {"api_key": ...}); the REST
synthesize endpoint accepts ?key=, so no OAuth/JWT/crypto dependency (stays on
the stdlib-urllib convention). $30/1M chars with 1M free chars/month → our
podcast volume is effectively free.

A plain lambdas/ root module (not a layer module): it's bundled into each
podcast lambda's asset automatically, so adding it needs no layer rebuild.
"""

import base64
import json
import os
import re
import urllib.error
import urllib.request

import boto3
from secret_cache import get_secret_json

SECRET_NAME = os.environ.get("GOOGLE_TTS_SECRET", "life-platform/google-tts")
ENDPOINT = "https://texttospeech.googleapis.com/v1/text:synthesize"
# Google TTS hard limit is 5000 bytes of input per request; stay well under.
CHUNK_CHARS = 4500
DEFAULT_LANG = "en-US"

_sm = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-west-2"))


class GoogleTTSError(RuntimeError):
    pass


def _api_key() -> str:
    s = get_secret_json(SECRET_NAME, _sm)
    key = s.get("api_key") or s.get("apiKey") or s.get("key")
    if not key:
        raise GoogleTTSError(f"{SECRET_NAME} missing api_key")
    return key


def _chunks(text: str):
    """Split at sentence boundaries, each under CHUNK_CHARS."""
    out, cur = [], ""
    for sent in re.split(r"(?<=[.!?])\s+", text or ""):
        if len(cur) + len(sent) + 1 > CHUNK_CHARS and cur:
            out.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    if cur:
        out.append(cur)
    return out


def _synthesize_chunk(text: str, voice_name: str, lang: str) -> bytes:
    body = json.dumps(
        {
            "input": {"text": text},
            "voice": {"languageCode": lang, "name": voice_name},
            "audioConfig": {"audioEncoding": "MP3"},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{ENDPOINT}?key={_api_key()}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 — constant Google API base
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:300]
        raise GoogleTTSError(f"Google TTS {e.code}: {detail}") from e
    audio_b64 = payload.get("audioContent")
    if not audio_b64:
        raise GoogleTTSError("Google TTS response missing audioContent")
    return base64.b64decode(audio_b64)


def synthesize(text: str, voice_name: str, lang: str = DEFAULT_LANG) -> bytes:
    """Synthesize text to MP3 bytes in a specific Chirp 3: HD voice. Chunks long
    text and concatenates MP3 frames (valid: same voice/bitrate per call)."""
    audio = b""
    for chunk in _chunks(text):
        if chunk.strip():
            audio += _synthesize_chunk(chunk, voice_name, lang)
    return audio
