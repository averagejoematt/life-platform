"""tests/test_panelcast_ident.py — the synthesized audio ident PCM mixer (#1179).

Pure-Python at the PCM layer (no lameenc / no network): output length arithmetic,
equal-power crossfade envelope monotonicity, the int16 no-clipping guarantee under a
hot speech signal, determinism (the ident is the show's identity — byte-identical every
render), and the off-switch passthrough. See epic #1082.
"""

import array
import math
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

import panelcast_ident as ident  # noqa: E402

SR = 24000


def _samples(pcm: bytes):
    a = array.array("h")
    a.frombytes(pcm)
    return a


def _speech(seconds: float, amp: int = 30000, freq: float = 180.0, sr: int = SR) -> bytes:
    """A hot mono int16 speech stand-in — near full-scale to stress the clipping guard."""
    n = int(seconds * sr)
    a = array.array("h", [0] * n)
    for i in range(n):
        a[i] = int(amp * math.sin(2 * math.pi * freq * i / sr))
    return a.tobytes()


def _frames(pcm: bytes, channels: int = 1) -> int:
    return (len(pcm) // 2) // channels


# ── length arithmetic ──────────────────────────────────────────────────────────────
def test_output_length_is_intro_plus_speech_plus_outro_minus_overlaps():
    speech = _speech(4.0)  # > intro_xfade + outro_overlap frames, so a real middle exists
    out = ident.mix_ident(speech, SR, 1, enabled_override=True)

    intro_frames = _frames(ident.render_ident(SR, 1))
    outro_frames = _frames(ident.render_outro(SR, 1))
    speech_frames = _frames(speech)
    xf, ovl = ident.crossfade_plan(speech_frames, intro_frames, outro_frames, SR)

    expected = intro_frames + speech_frames + outro_frames - xf - ovl
    assert _frames(out) == expected
    # The episode is meaningfully longer than the bare speech (ident really was added).
    assert _frames(out) > speech_frames + intro_frames // 2


def test_short_speech_does_not_double_mix_or_go_negative():
    """A clip shorter than the two fade regions combined must still produce a valid,
    correctly-sized episode (the crossfade_plan guard) — real episodes are minutes long,
    but robustness is cheap and the preview path exercises seconds."""
    speech = _speech(1.0)  # 1s < intro_xfade + outro_overlap (~3.4s)
    intro_frames = _frames(ident.render_ident(SR, 1))
    outro_frames = _frames(ident.render_outro(SR, 1))
    speech_frames = _frames(speech)
    xf, ovl = ident.crossfade_plan(speech_frames, intro_frames, outro_frames, SR)
    assert xf + ovl <= speech_frames  # the middle never goes negative
    out = ident.mix_ident(speech, SR, 1, enabled_override=True)
    assert _frames(out) == intro_frames + speech_frames + outro_frames - xf - ovl
    assert all(-32768 <= v <= 32767 for v in _samples(out))


def test_ident_present_at_head():
    """The head of the episode is the intro ident, not speech — the entrance exists."""
    speech = _speech(4.0)
    out = _samples(ident.mix_ident(speech, SR, 1, enabled_override=True))
    speech_s = _samples(speech)
    # First frame of speech is silence (sin(0)==0); the mixed head is the ident, non-zero.
    head = out[: int(0.5 * SR)]
    assert any(abs(v) > 200 for v in head)
    # The head does not equal the speech head (the ident replaced it).
    assert list(out[:1000]) != list(speech_s[:1000])


# ── equal-power crossfade envelope ──────────────────────────────────────────────────
def test_crossfade_envelope_monotonic_and_equal_power():
    n = int(ident.INTRO_XFADE_SECONDS * SR)
    fade_in, fade_out = ident.equal_power_fades(n)
    assert len(fade_in) == len(fade_out) == n
    # fade_in rises monotonically 0→1; fade_out falls monotonically 1→0.
    assert all(fade_in[i] <= fade_in[i + 1] + 1e-12 for i in range(n - 1))
    assert all(fade_out[i] >= fade_out[i + 1] - 1e-12 for i in range(n - 1))
    assert fade_in[0] == 0.0 and abs(fade_in[-1] - 1.0) < 1e-9
    assert abs(fade_out[0] - 1.0) < 1e-9 and abs(fade_out[-1]) < 1e-9
    # Equal power: sin² + cos² == 1 at every step (constant perceived loudness).
    for a, b in zip(fade_in, fade_out):
        assert abs(a * a + b * b - 1.0) < 1e-9


def test_equal_power_fades_edge_cases():
    assert ident.equal_power_fades(0) == ([], [])
    assert ident.equal_power_fades(1) == ([1.0], [0.0])


# ── no clipping: every sample within int16 ─────────────────────────────────────────
def test_no_sample_exceeds_int16_under_hot_speech():
    speech = _speech(4.0, amp=32760)  # near full scale — worst case for the mix sum
    out = _samples(ident.mix_ident(speech, SR, 1, enabled_override=True, gain=2.0))
    assert out  # non-empty
    assert all(-32768 <= v <= 32767 for v in out)


def test_clamp_helper_extremes():
    assert ident._clamp_i16(50000.0) == 32767
    assert ident._clamp_i16(-50000.0) == -32768
    assert ident._clamp_i16(0.4) == 0


def test_rendered_ident_within_solo_peak():
    intro = _samples(ident.render_ident(SR, 1))
    peak = max(abs(v) for v in intro)
    # Normalized to ~-3 dBFS solo (0.72·32767 ≈ 23592), never near full scale.
    assert peak <= int(ident.IDENT_PEAK_SOLO * 32767) + 2
    assert peak > int(0.5 * 32767)  # and it is a real, audible tone


# ── determinism: the identity is fixed ─────────────────────────────────────────────
def test_render_ident_deterministic():
    assert ident.render_ident(SR, 1) == ident.render_ident(SR, 1)
    assert ident.render_outro(SR, 1) == ident.render_outro(SR, 1)


def test_mix_deterministic():
    speech = _speech(4.0)
    assert ident.mix_ident(speech, SR, 1, enabled_override=True) == ident.mix_ident(speech, SR, 1, enabled_override=True)


# ── off-switch / passthrough ───────────────────────────────────────────────────────
def test_off_switch_returns_speech_unchanged():
    speech = _speech(4.0)
    assert ident.mix_ident(speech, SR, 1, enabled_override=False) == speech


def test_empty_speech_returns_unchanged():
    assert ident.mix_ident(b"", SR, 1, enabled_override=True) == b""


def test_enabled_env_gate(monkeypatch):
    monkeypatch.setenv("PANELCAST_IDENT", "off")
    assert ident.enabled() is False
    monkeypatch.setenv("PANELCAST_IDENT", "on")
    assert ident.enabled() is True
    monkeypatch.delenv("PANELCAST_IDENT", raising=False)
    assert ident.enabled() is True  # default ON


def test_gain_env_clamped(monkeypatch):
    monkeypatch.setenv("PANELCAST_IDENT_GAIN", "5.0")
    assert ident._gain() == 2.0
    monkeypatch.setenv("PANELCAST_IDENT_GAIN", "-1")
    assert ident._gain() == 0.0
    monkeypatch.setenv("PANELCAST_IDENT_GAIN", "bogus")
    assert ident._gain() == 1.0


# ── stereo path (defensive — Gemini is mono, but the mixer must be channel-correct) ──
def test_stereo_length_and_bounds():
    n = int(4.0 * SR)
    a = array.array("h", [0] * (n * 2))
    for i in range(n):
        v = int(20000 * math.sin(2 * math.pi * 180 * i / SR))
        a[2 * i] = v
        a[2 * i + 1] = v
    speech = a.tobytes()
    out = _samples(ident.mix_ident(speech, SR, 2, enabled_override=True))
    assert len(out) % 2 == 0
    assert all(-32768 <= v <= 32767 for v in out)
