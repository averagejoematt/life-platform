"""panelcast_brand_open.py — the frozen V1 brand open (#1187).

Every episode starts with the SAME recorded open: Elena's V1 line
("One ordinary life. Every number, in the open. This is The Measured Life.
averagejoematt dot com.") over a licence-cleared music bed. The asset is
FROZEN — rendered once, approved by ear, stored in S3, and prepended
verbatim. It is never re-synthesized per episode, so the brand hook cannot
drift between weeks and costs no TTS spend.

Supersedes #1179's per-episode synthesized arpeggio ident (``panelcast_ident``),
which is disabled by default as of this module — the two must never both fire,
or an episode opens twice.

Where the asset lives
---------------------
``config/panelcast/brand_open.wav`` — 24 kHz mono 16-bit PCM, matching the
Gemini TTS output format so the splice is a raw byte concatenation with no
resample. The Panel role already holds ``s3:GetObject`` on ``config/*``
(``S3ConfigRead``); it holds only ``s3:PutObject`` — NOT read — on
``generated/panelcast/*``, so the published-episode prefix cannot serve as the
asset's home without an IAM change.

**The asset is write-once and lives ONLY in S3** — deliberately not in the
repo. ``config/`` has no automated repo→S3 deploy path (#2019), which is a
drift hazard for files that change with the code; a frozen asset that is
uploaded once and never edited has no drift surface at all. To replace it,
re-render and re-upload deliberately (see the #1187 runbook on the issue).

Format discipline
-----------------
The open is spliced ONLY when its (sample_rate, channels, sample_width)
match the episode exactly. A mismatched splice would not fail loudly — it
would play the open at the wrong speed and pitch, which is the failure mode
this check exists to prevent.

Fail-open BY DESIGN
-------------------
Any error — asset absent, S3 throw, odd WAV shape, format mismatch — returns
the episode audio unchanged and publishes a cold open. The brand hook is
identity polish; it must never strand an episode. Absence is logged at
WARNING so a silently missing asset is visible rather than inferred.

Environment
-----------
- ``PANELCAST_BRAND_OPEN``      on/off (default on) — off returns speech untouched.
- ``PANELCAST_BRAND_OPEN_KEY``  override the S3 key (default as above).
"""

import io
import logging
import os
import wave

import boto3

logger = logging.getLogger()

S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
REGION = os.environ.get("AWS_REGION", "us-west-2")
BRAND_OPEN_KEY = os.environ.get("PANELCAST_BRAND_OPEN_KEY", "config/panelcast/brand_open.wav")

# Beat between the open's tail and the first spoken turn. The open already
# fades out over its last 1.5s, so this is a breath, not a gap to fill.
GAP_SECONDS = 0.35

# Per-container cache: the asset is frozen, so one GET per warm container is
# the whole cost. Keyed by S3 key so an env override cannot serve a stale body.
_ASSET_CACHE: dict = {}

_s3_client = None


def _s3():
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client("s3", region_name=REGION)
    return _s3_client


def enabled() -> bool:
    """PANELCAST_BRAND_OPEN — default ON; only an explicit off/0/false/no disables it."""
    return os.environ.get("PANELCAST_BRAND_OPEN", "on").strip().lower() not in ("off", "0", "false", "no")


def _fetch_asset(key: str) -> tuple:
    """Return (pcm_bytes, channels, sampwidth, framerate) for the frozen open.

    Cached per container. Raises on any failure — every caller is inside the
    fail-open boundary of :func:`prepend_into_wav`."""
    if key in _ASSET_CACHE:
        return _ASSET_CACHE[key]
    body = _s3().get_object(Bucket=S3_BUCKET, Key=key)["Body"].read()
    with wave.open(io.BytesIO(body), "rb") as w:
        spec = (w.readframes(w.getnframes()), w.getnchannels(), w.getsampwidth(), w.getframerate())
    if not spec[0]:
        raise ValueError("brand open asset contains no frames")
    _ASSET_CACHE[key] = spec
    return spec


def prepend_into_wav(wav_bytes: bytes) -> bytes:
    """WAV-in → WAV-out: prepend the frozen brand open to an episode.

    Mirrors ``panelcast_ident.mix_into_wav``'s contract exactly — same stage in
    the publish path (raw PCM, before the lameenc encode), same fail-open
    guarantee. Returns the input unchanged on any error."""
    try:
        if not enabled():
            return wav_bytes

        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            channels, sampwidth, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
            speech = w.readframes(w.getnframes())
        if sampwidth != 2 or not speech:
            return wav_bytes

        open_pcm, o_ch, o_sw, o_rate = _fetch_asset(BRAND_OPEN_KEY)

        # A mismatched splice plays at the wrong pitch rather than failing —
        # refuse it and publish a cold open instead.
        if (o_ch, o_sw, o_rate) != (channels, sampwidth, rate):
            logger.warning(
                "[panelcast-brand-open] format mismatch — asset %dch/%dB/%dHz vs episode %dch/%dB/%dHz; cold open",
                o_ch,
                o_sw,
                o_rate,
                channels,
                sampwidth,
                rate,
            )
            return wav_bytes

        gap = b"\x00" * (int(GAP_SECONDS * rate) * channels * sampwidth)

        buf = io.BytesIO()
        with wave.open(buf, "wb") as out:
            out.setnchannels(channels)
            out.setsampwidth(sampwidth)
            out.setframerate(rate)
            out.writeframes(open_pcm + gap + speech)
        logger.info(
            "[panelcast-brand-open] prepended frozen open (%d PCM bytes) to speech (%d) → %d",
            len(open_pcm),
            len(speech),
            len(open_pcm) + len(gap) + len(speech),
        )
        return buf.getvalue()
    except Exception as e:  # noqa: BLE001 — fail-open is the contract
        logger.warning("[panelcast-brand-open] prepend failed (%s) — publishing cold open (fail-open)", e)
        return wav_bytes
