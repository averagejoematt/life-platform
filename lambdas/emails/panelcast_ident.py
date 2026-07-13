"""panelcast_ident.py — the show's synthesized audio identity (#1179, epic #1082).

From Matthew's wk0 re-listen: the episode had no entrance. A real podcast opens
with an audio identity — the first credibility signal a stranger hears. This module
synthesizes that ident **in pure Python** (stdlib ``math``/``array``/``struct`` — numpy
is NOT in the bundle) so there is zero licensing surface (no samples, no third-party
audio) and no new dependency. The composition is FIXED and deterministic: the ident is
the show's identity, so it is byte-for-byte identical on every episode.

Aesthetic — "the measured life": a slow ascending broken chord (A-major: A3 → C#4 → E4
→ A4) over a low root drone (A2), soft sine/triangle blend with gentle raised-cosine
attack/release envelopes, moderate tempo. The motif resolves into a held A-major chord
~2s before speech, then ducks under Elena's first words with a ~1.8s equal-power
crossfade. The outro is a ~3.5s reprise of that final chord, swelling in under the tail
of the last line and fading out.

Integration (see ``coach_panel_podcast_lambda._publish_episode_audio``): the mix happens
at the raw-PCM stage BEFORE the lameenc MP3 encode — Gemini TTS returns 16-bit mono PCM
(24 kHz) wrapped in WAV; the publisher unwraps to PCM, calls :func:`mix_ident`, re-wraps,
then compresses exactly as before. Applies to episode 0 and every weekly episode.

Levels: the ident is normalized to ~-3 dBFS solo (the intro head) and sits ~-6 dBFS or
lower under speech (the outro reprise). Every output sample is clamped to int16 so no
sample can ever exceed the container — the "no clipping" contract is structural.

Env knobs (composition itself is not tunable — only presence and level):
- ``PANELCAST_IDENT``       on/off (default on) — off returns the speech untouched.
- ``PANELCAST_IDENT_GAIN``  float multiplier on the ident only (default 1.0, 0..2).
"""

import array
import io
import logging
import math
import os
import wave

logger = logging.getLogger("panelcast-ident")

# ── composition constants (FIXED — the show's identity; do not env-tune) ─────────
INTRO_SECONDS = 7.0  # total intro ident length before it hands off to speech
INTRO_XFADE_SECONDS = 1.8  # equal-power crossfade: ident ducks out, speech fades in
OUTRO_SECONDS = 3.5  # reprise length appended after the last line
OUTRO_OVERLAP_SECONDS = 1.6  # how far the outro swells in under the speech tail

IDENT_PEAK_SOLO = 0.72  # ≈ -2.9 dBFS — solo-playback peak the ident is normalized to
UNDER_GAIN = 0.6  # ident level while it coexists with speech (≈ -7 dBFS under)

_TRI_MIX = 0.32  # triangle content blended into the sine (warmth without brightness)
_FULL = 32767  # int16 positive full scale

# A-major identity: low drone root + ascending broken chord + resolved triad.
_A2 = 110.00
_A3, _CS4, _E4, _A4 = 220.00, 277.18, 329.63, 440.00
_RESOLVE_CHORD = (_A3, _CS4, _E4)  # the held A-major chord the motif resolves into


# ── env gates ────────────────────────────────────────────────────────────────────
def enabled() -> bool:
    """PANELCAST_IDENT — default ON; only an explicit off/0/false/no disables it."""
    return os.environ.get("PANELCAST_IDENT", "on").strip().lower() not in ("off", "0", "false", "no")


def _gain() -> float:
    """PANELCAST_IDENT_GAIN — ident-only multiplier, clamped to a sane 0..2."""
    try:
        return max(0.0, min(2.0, float(os.environ.get("PANELCAST_IDENT_GAIN", "1.0"))))
    except (TypeError, ValueError):
        return 1.0


# ── tone synthesis ────────────────────────────────────────────────────────────────
def _triangle(phase: float) -> float:
    """Unit triangle wave in [-1, 1] from a fractional phase (cheap, no harmonics sum)."""
    frac = phase % 1.0
    return 4.0 * abs(frac - 0.5) - 1.0


def _raised_cosine_env(i: int, n: int, attack: int, release: int) -> float:
    """Smooth per-sample envelope: raised-cosine attack, unity sustain, raised-cosine
    release. No hard edges → no clicks at note boundaries."""
    if i < attack:
        return 0.5 - 0.5 * math.cos(math.pi * i / attack)
    if i >= n - release:
        j = i - (n - release)
        return 0.5 + 0.5 * math.cos(math.pi * j / release)
    return 1.0


def _add_note(buf: list, start: int, freq: float, dur_s: float, sr: int, amp: float, attack_s: float, release_s: float) -> None:
    """Sum one enveloped sine/triangle note into ``buf`` starting at sample ``start``."""
    n = int(dur_s * sr)
    attack = max(1, int(attack_s * sr))
    release = max(1, int(release_s * sr))
    if attack + release > n:  # keep the envelope well-formed for short notes
        attack = release = max(1, n // 2)
    two_pi_f = 2.0 * math.pi * freq
    for i in range(n):
        pos = start + i
        if pos >= len(buf):
            break
        t = i / sr
        sine = math.sin(two_pi_f * t)
        tri = _triangle(freq * t)
        env = _raised_cosine_env(i, n, attack, release)
        buf[pos] += amp * env * ((1.0 - _TRI_MIX) * sine + _TRI_MIX * tri)


def _normalize(buf: list, target_peak: float) -> list:
    """Scale ``buf`` so its absolute peak equals ``target_peak`` (guarantees the solo
    level regardless of how the summed voices happened to add up)."""
    peak = max((abs(x) for x in buf), default=0.0)
    if peak <= 0.0:
        return buf
    scale = target_peak / peak
    return [x * scale for x in buf]


def _render_intro_float(sr: int) -> list:
    """Mono float ident (peak-normalized to IDENT_PEAK_SOLO): low drone + ascending
    A-major broken chord + a held resolved triad that sustains toward the crossfade."""
    n = int(INTRO_SECONDS * sr)
    buf = [0.0] * n
    # Low root drone under the whole ident (fades in slowly, releases at the end).
    _add_note(buf, 0, _A2, INTRO_SECONDS, sr, amp=0.34, attack_s=0.8, release_s=1.4)
    # Ascending broken chord — the "measured" motif. Moderate tempo (~0.62s spacing).
    spacing = 0.62
    for k, freq in enumerate((_A3, _CS4, _E4, _A4)):
        onset = 0.5 + k * spacing
        _add_note(buf, int(onset * sr), freq, dur_s=1.5, sr=sr, amp=0.5, attack_s=0.06, release_s=0.5)
    # Resolved A-major chord — swells in right after the 4th note and holds ~2s before
    # the crossfade (so the ear hears resolution, then the duck).
    resolve_onset = 0.5 + 4 * spacing
    resolve_dur = INTRO_SECONDS - resolve_onset
    for freq in _RESOLVE_CHORD:
        _add_note(buf, int(resolve_onset * sr), freq, dur_s=resolve_dur, sr=sr, amp=0.32, attack_s=0.15, release_s=0.9)
    return _normalize(buf, IDENT_PEAK_SOLO)


def _render_outro_float(sr: int) -> list:
    """Mono float outro (peak-normalized): a soft reprise of the resolved A-major chord
    over the drone, self-enveloped so it swells in and fades out on its own."""
    n = int(OUTRO_SECONDS * sr)
    buf = [0.0] * n
    _add_note(buf, 0, _A2, OUTRO_SECONDS, sr, amp=0.30, attack_s=1.0, release_s=1.2)
    for freq in _RESOLVE_CHORD:
        _add_note(buf, 0, freq, dur_s=OUTRO_SECONDS, sr=sr, amp=0.30, attack_s=1.0, release_s=1.2)
    return _normalize(buf, IDENT_PEAK_SOLO)


# ── equal-power crossfade envelopes ───────────────────────────────────────────────
def equal_power_fades(n: int):
    """Return (fade_in, fade_out) length-``n`` equal-power envelopes. fade_in rises
    monotonically 0→1, fade_out falls monotonically 1→0; fade_in²+fade_out²==1."""
    if n <= 0:
        return [], []
    if n == 1:
        return [1.0], [0.0]
    fin, fout = [], []
    for i in range(n):
        x = i / (n - 1)
        fin.append(math.sin(0.5 * math.pi * x))
        fout.append(math.cos(0.5 * math.pi * x))
    return fin, fout


# ── PCM helpers ────────────────────────────────────────────────────────────────────
def _clamp_i16(v: float) -> int:
    return -32768 if v <= -32768 else (32767 if v >= 32767 else int(round(v)))


def crossfade_plan(n_frames: int, intro_frames: int, outro_frames: int, sample_rate: int):
    """Resolve (intro_xfade, outro_overlap) in frames for a speech clip of ``n_frames``.

    The nominal fades come from the composition constants, capped to the ident lengths.
    Guard: if the two fade regions would together exceed the speech (a very short clip —
    real episodes are minutes long, but the preview/tests exercise seconds), split the
    available frames between them so the middle never goes negative and no speech frame
    is double-mixed."""
    xf = min(int(INTRO_XFADE_SECONDS * sample_rate), intro_frames, n_frames)
    ovl = min(int(OUTRO_OVERLAP_SECONDS * sample_rate), outro_frames, n_frames)
    if xf + ovl > n_frames:
        xf = min(xf, n_frames // 2)
        ovl = min(ovl, n_frames - xf)
    return xf, ovl


def _floats_to_pcm(mono: list, channels: int, gain: float = 1.0) -> bytes:
    """Mono float samples (unit range) → int16 PCM, replicated across ``channels``."""
    out = array.array("h", bytes(2 * channels * len(mono)))
    for f, s in enumerate(mono):
        val = _clamp_i16(s * _FULL * gain)
        base = f * channels
        for c in range(channels):
            out[base + c] = val
    return out.tobytes()


def render_ident(sample_rate: int, channels: int = 1) -> bytes:
    """Public: the intro ident as int16 PCM at solo level (~-3 dBFS). Deterministic —
    identical bytes on every call for a given (sample_rate, channels)."""
    return _floats_to_pcm(_render_intro_float(sample_rate), channels)


def render_outro(sample_rate: int, channels: int = 1) -> bytes:
    """Public: the outro reprise as int16 PCM at solo level. Deterministic."""
    return _floats_to_pcm(_render_outro_float(sample_rate), channels)


def mix_ident(speech_pcm: bytes, sample_rate: int, channels: int = 1, enabled_override=None, gain=None) -> bytes:
    """Prepend the intro ident (equal-power crossfade under the first words) and append
    the outro reprise (swelling in under the last line's tail) to ``speech_pcm``.

    ``speech_pcm`` is int16 PCM, ``channels``-interleaved (Gemini is mono). Returns the
    mixed int16 PCM. If the ident is disabled or the speech is empty, returns the speech
    bytes unchanged (the off-switch / dry-run contract). Every sample is clamped to
    int16 — the no-clipping guarantee is structural, not probabilistic.

    Output length (frames) == intro + speech + outro − intro_xfade − outro_overlap; only
    the head (intro+crossfade) and tail (outro overlap+reprise) are float-mixed — the
    bulk of the speech is copied verbatim, so memory/CPU stay flat on long episodes."""
    use = enabled() if enabled_override is None else enabled_override
    if not use or not speech_pcm:
        return speech_pcm
    g = _gain() if gain is None else max(0.0, min(2.0, float(gain)))

    speech = array.array("h")
    speech.frombytes(speech_pcm)
    frame_bytes = 2 * channels
    n_frames = len(speech) // channels
    if n_frames == 0:
        return speech_pcm

    intro = _render_intro_float(sample_rate)
    outro = _render_outro_float(sample_rate)
    xf, ovl = crossfade_plan(n_frames, len(intro), len(outro), sample_rate)
    fade_in, fade_out = equal_power_fades(xf)

    # 1) intro head, played solo, up to the crossfade (int16, ident-only).
    head = _floats_to_pcm(intro[: len(intro) - xf], channels, gain=g)

    # 2) crossfade: intro tail ducks out (equal-power) while speech fades in.
    xbuf = array.array("h", bytes(frame_bytes * xf))
    ib = len(intro) - xf
    for i in range(xf):
        ident_val = intro[ib + i] * _FULL * g * fade_out[i]
        base = i * channels
        for c in range(channels):
            xbuf[base + c] = _clamp_i16(ident_val + speech[i * channels + c] * fade_in[i])
    xfade = xbuf.tobytes()

    # 3) speech middle — copied verbatim (no float math on the bulk of the episode).
    mid_start = xf * frame_bytes
    mid_end = (n_frames - ovl) * frame_bytes
    mid = speech_pcm[mid_start:mid_end]

    # 4) outro: reprise swells in under the speech tail (overlap), then plays out solo.
    obuf = array.array("h", bytes(frame_bytes * len(outro)))
    tail0 = n_frames - ovl  # first speech frame the outro overlaps
    for k in range(len(outro)):
        ident_val = outro[k] * _FULL * g * UNDER_GAIN
        base = k * channels
        if k < ovl:
            for c in range(channels):
                obuf[base + c] = _clamp_i16(ident_val + speech[(tail0 + k) * channels + c])
        else:
            for c in range(channels):
                obuf[base + c] = _clamp_i16(ident_val)
    outro_bytes = obuf.tobytes()

    return head + xfade + mid + outro_bytes


def mix_into_wav(wav_bytes: bytes) -> bytes:
    """WAV-in → WAV-out convenience for the publish path: unwrap the episode WAV to
    PCM, mix the ident (:func:`mix_ident`), re-wrap with the same format. Fail-open BY
    DESIGN — any error (ident off, odd WAV shape, synth throw) returns the original WAV
    unchanged. The ident is identity polish; it must never strand an episode."""
    try:
        if not enabled():
            return wav_bytes
        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            channels, sampwidth, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
            pcm = w.readframes(w.getnframes())
        if sampwidth != 2 or not pcm:
            return wav_bytes
        mixed = mix_ident(pcm, rate, channels)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as out:
            out.setnchannels(channels)
            out.setsampwidth(sampwidth)
            out.setframerate(rate)
            out.writeframes(mixed)
        logger.info("[panelcast-ident] mixed ident: speech %d → episode %d PCM bytes", len(pcm), len(mixed))
        return buf.getvalue()
    except Exception as e:  # noqa: BLE001 — fail-open is the contract
        logger.warning("[panelcast-ident] ident mix failed (%s) — publishing speech-only WAV (fail-open)", e)
        return wav_bytes
