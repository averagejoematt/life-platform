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
from common.secret_cache import get_secret_json

SECRET_NAME = os.environ.get("GOOGLE_TTS_SECRET", "life-platform/google-tts")
ENDPOINT = "https://texttospeech.googleapis.com/v1/text:synthesize"
# Google TTS hard limit is 5000 bytes of input per request; stay well under.
CHUNK_CHARS = 4500
DEFAULT_LANG = "en-US"

# Clause-boundary patterns tried in preference order when a single sentence
# alone exceeds CHUNK_CHARS (#2148 — Google TTS 400s with "sentences that are
# too long" on the house style's long em-dash-heavy compound sentences, and
# the old packer only ever grouped WHOLE sentences, never split one). Each
# pattern is a lookbehind/lookahead split so the delimiter stays attached to
# the clause it ends and no word is ever broken.
_CLAUSE_BOUNDARIES = (
    r"(?<=—)\s*",  # em-dash — the house style's dominant clause break
    r"(?<=[;])\s+",  # semicolon
    r"(?<=[,])\s+",  # comma
    r"\s+(?=(?:and|but|or|so|yet|nor)\s)",  # coordinating conjunction
)

_sm = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-west-2"))


class GoogleTTSError(RuntimeError):
    pass


def _api_key() -> str:
    s = get_secret_json(SECRET_NAME, _sm)
    key = s.get("api_key") or s.get("apiKey") or s.get("key")
    if not key:
        raise GoogleTTSError(f"{SECRET_NAME} missing api_key")
    return key


def _hard_split(text: str, limit: int) -> list:
    """Last-resort split when no natural boundary exists within `limit` chars
    (a degenerate run with no punctuation and — usually — no whitespace
    either). Cuts at the nearest whitespace at or before `limit`; only cuts
    mid-word if the run has no whitespace at all within that span."""
    out = []
    while len(text) > limit:
        cut = text.rfind(" ", 0, limit)
        if cut <= 0:
            cut = limit  # no whitespace to break on — unavoidable mid-word cut
        out.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        out.append(text)
    return out


def _split_oversized(text: str, limit: int) -> list:
    """Split a single sentence that alone exceeds `limit` into pieces that
    each fit, preferring natural clause boundaries — em-dash, semicolon,
    comma, then coordinating conjunctions — in that order, never mid-word.
    Recurses through the boundary list so a piece that's still oversized
    after (say) an em-dash split gets tried against semicolons next, etc."""
    if len(text) <= limit:
        return [text]
    for pattern in _CLAUSE_BOUNDARIES:
        parts = [p for p in re.split(pattern, text) if p]
        if len(parts) > 1:
            pieces = []
            for part in parts:
                pieces.extend(_split_oversized(part, limit))
            return _pack(pieces, limit)
    # No natural boundary anywhere in this run — hard split.
    return _hard_split(text, limit)


def _pack(pieces, limit: int) -> list:
    """Greedily re-merge adjacent pieces up to `limit` chars each, preserving
    order — keeps request count (and TTS prosody) as close to the original
    sentence-level packing as possible after a piece has been split."""
    out, cur = [], ""
    for piece in pieces:
        candidate = f"{cur} {piece}".strip() if cur else piece
        if len(candidate) > limit and cur:
            out.append(cur)
            cur = piece
        else:
            cur = candidate
    if cur:
        out.append(cur)
    return out


def _chunks(text: str):
    """Split into TTS request chunks, each <= CHUNK_CHARS, in original order.
    Sentences are packed together up to the limit; a single sentence that
    ALONE exceeds the limit (#2148) is first split into sub-sentence clause
    pieces via `_split_oversized` and those pieces are packed the same way,
    so the request set never contains a chunk over CHUNK_CHARS regardless of
    how long any one sentence in the source prose is."""
    pieces = []
    for sent in re.split(r"(?<=[.!?])\s+", text or ""):
        if sent:
            pieces.extend(_split_oversized(sent, CHUNK_CHARS))
    return _pack(pieces, CHUNK_CHARS)


def _synthesize_chunk(text: str, voice_name: str, lang: str, volume_gain_db: float = 0.0) -> bytes:
    audio_cfg = {"audioEncoding": "MP3"}
    if volume_gain_db:
        audio_cfg["volumeGainDb"] = volume_gain_db
    body = json.dumps(
        {
            "input": {"text": text},
            "voice": {"languageCode": lang, "name": voice_name},
            "audioConfig": audio_cfg,
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


def synthesize(text: str, voice_name: str, lang: str = DEFAULT_LANG, volume_gain_db: float = 0.0) -> bytes:
    """Synthesize text to MP3 bytes in a specific Chirp 3: HD voice. Chunks long
    text and concatenates MP3 frames (valid: same voice/bitrate per call).
    ``volume_gain_db`` balances loudness across voices in a multi-voice dialogue."""
    audio = b""
    for chunk in _chunks(text):
        if chunk.strip():
            audio += _synthesize_chunk(chunk, voice_name, lang, volume_gain_db)
    return audio
