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
from typing import Optional

import boto3
from common.secret_cache import get_secret_json

SECRET_NAME = os.environ.get("GOOGLE_TTS_SECRET", "life-platform/google-tts")
ENDPOINT = "https://texttospeech.googleapis.com/v1/text:synthesize"
# Google TTS hard limit is 5000 bytes of input per request; stay well under.
# This is a REQUEST-size cap, not a sentence-size cap — see PER_SENTENCE_CHARS
# below, which is the actually load-bearing constraint (#2148 fix-forward).
CHUNK_CHARS = 4500
# Google's per-SENTENCE limit (#2148 fix-forward, 2026-08-06): the #2154 fix
# only capped CHUNK_CHARS (request size) and left an em-dash-heavy 493-byte
# sentence intact under that cap — Google 400'd it anyway with "sentences
# that are too long," because Google re-segments the request text with its
# OWN sentence splitter and enforces a MUCH smaller per-sentence limit than
# the 5000-byte request cap. No official numeric limit is published for
# Chirp 3: HD; the closest documented data point found (community report
# against the same voice family and the same error text) recommends keeping
# each spoken line under ~80-100 characters. 200 is a conservative middle
# ground: real margin above that folklore floor (so ordinary short sentences
# — median ~120 chars in real chronicle prose — pass through untouched) while
# staying well under the measured 493-byte failure (#2148's real incident
# sentence). Treat this as an empirically-reasoned constant, not a cited spec
# — revisit if Google ever documents the real number.
PER_SENTENCE_CHARS = 200
DEFAULT_LANG = "en-US"

# Clause-boundary patterns tried in preference order when a single sentence
# alone exceeds a length cap (originally CHUNK_CHARS for #2148; now also used
# at the smaller PER_SENTENCE_CHARS cap for the fix-forward above) — Google
# TTS 400s with "sentences that are too long" on the house style's long
# em-dash-heavy compound sentences, and the old packer only ever grouped
# WHOLE sentences, never split one. Each pattern is a lookbehind/lookahead
# split so the delimiter stays attached to the clause it ends and no word is
# ever broken.
_CLAUSE_BOUNDARIES = (
    r"(?<=—)\s*",  # em-dash — the house style's dominant clause break
    r"(?<=[;])\s+",  # semicolon
    r"(?<=[,])\s+",  # comma
    r"\s+(?=(?:and|but|or|so|yet|nor)\s)",  # coordinating conjunction
)
# Characters a clause-boundary split can leave dangling at the end of a piece
# (the delimiter itself, plus surrounding whitespace) — stripped before a
# terminal period is appended so termination never produces "...clause —."
_DANGLING_BOUNDARY_CHARS = " ,;:—"

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


def _terminate(piece: str, limit: Optional[int] = None) -> str:
    """Ensure `piece` ends with sentence-ending punctuation (#2148 fix-forward).
    A clause-boundary or hard split produces a fragment with no terminal
    punctuation of its own (a comma, em-dash, or bare word at the cut point);
    left that way, Google's OWN sentence segmenter keeps reading past it as
    one continuing (long) sentence, so the per-sentence cap above is
    meaningless unless every resulting piece is ALSO stamped as a complete
    sentence. Idempotent: a piece that already ends in . ! or ? (the common
    case — most sentences never need splitting) passes through unchanged.

    If `limit` is given and the piece is already sitting exactly at it (only
    possible via `_hard_split`'s degenerate mid-word cut, which has no
    delimiter to trade for the period), trims one trailing character to make
    room rather than push the piece over the cap — the terminal period is
    what keeps the NEXT piece from re-triggering Google's per-sentence limit,
    so it must never be the reason THIS piece does."""
    piece = piece.strip()
    if not piece:
        return piece
    if piece[-1] in ".!?":
        return piece
    piece = piece.rstrip(_DANGLING_BOUNDARY_CHARS).rstrip()
    if limit is not None and len(piece) + 1 > limit:
        piece = piece[: max(limit - 1, 0)]
    return piece + "."


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


def _sentence_pieces(text: str) -> list:
    """Split `text` into individual spoken SENTENCES, each <= PER_SENTENCE_CHARS
    and each terminated with sentence-ending punctuation (#2148 fix-forward).
    This is the layer Google's own segmenter actually sees: a sentence over
    the (much smaller than CHUNK_CHARS) per-sentence cap gets cut at the same
    clause-boundary cascade `_split_oversized` already uses for the CHUNK_CHARS
    case — em-dash, semicolon, comma, then coordinating conjunction, never
    mid-word — and every resulting piece is stamped with a terminal period via
    `_terminate` so it reads to Google as a short, COMPLETE sentence rather
    than a continuing fragment. Splitting at PER_SENTENCE_CHARS (200) already
    guarantees every piece is also under CHUNK_CHARS (4500), so no separate
    CHUNK_CHARS-level split is needed here — that cap is enforced downstream
    by `_pack` in `_chunks`, which re-batches these short sentences into
    fewer, larger TTS requests."""
    pieces = []
    for sent in re.split(r"(?<=[.!?])\s+", text or ""):
        if sent:
            for piece in _split_oversized(sent, PER_SENTENCE_CHARS):
                pieces.append(_terminate(piece, PER_SENTENCE_CHARS))
    return pieces


def _chunks(text: str):
    """Split into TTS request chunks, each <= CHUNK_CHARS, in original order.
    Sentences are first cut down to individually Google-safe units via
    `_sentence_pieces` (#2148 fix-forward — the per-sentence cap, not just
    the per-request cap), then those short, terminated sentences are packed
    back together up to CHUNK_CHARS per request — the same outer batching
    this function always did, unrelated to and unaffected by the per-sentence
    fix — so the request set never contains a chunk over CHUNK_CHARS AND no
    sentence within any chunk exceeds Google's own (much smaller) per-sentence
    limit, regardless of how long any one sentence in the source prose is."""
    return _pack(_sentence_pieces(text), CHUNK_CHARS)


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
