"""#1187 — the frozen V1 brand open.

The contract under test is narrow and load-bearing:

1. The frozen open is prepended verbatim, ahead of the speech, at the raw-PCM stage.
2. It is fetched ONCE per container — an episode must not re-download it, and a
   frozen asset must never be re-rendered.
3. A format mismatch is REFUSED. This is the only failure here that would not
   announce itself: a 44.1kHz asset spliced onto a 24kHz episode plays the brand
   hook at the wrong pitch and speed, and still publishes cleanly.
4. Every error path is fail-open — a missing asset publishes a cold open rather
   than stranding the episode.
"""

import io
import os
import sys
import wave

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from emails import panelcast_brand_open as bo  # noqa: E402

SR = 24000
CH = 1
SW = 2


def _wav(pcm: bytes, rate=SR, channels=CH, sampwidth=SW) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sampwidth)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _pcm_of(wav_bytes: bytes) -> bytes:
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        return w.readframes(w.getnframes())


class _FakeBody:
    def __init__(self, data):
        self._d = data

    def read(self):
        return self._d


class _FakeS3:
    """Counts GETs so the per-container cache can be asserted, not assumed."""

    def __init__(self, payload=None, raises=None):
        self.payload = payload
        self.raises = raises
        self.calls = 0

    def get_object(self, Bucket=None, Key=None):  # noqa: N803 — boto3 kwarg casing
        self.calls += 1
        if self.raises:
            raise self.raises
        return {"Body": _FakeBody(self.payload)}


@pytest.fixture(autouse=True)
def _clear_cache(monkeypatch):
    bo._ASSET_CACHE.clear()
    monkeypatch.delenv("PANELCAST_BRAND_OPEN", raising=False)
    yield
    bo._ASSET_CACHE.clear()


def _install(monkeypatch, fake):
    monkeypatch.setattr(bo, "_s3", lambda: fake)


OPEN_PCM = b"\x11\x22" * 2400  # 0.2s of distinctive non-silent frames
SPEECH_PCM = b"\x33\x44" * 4800  # 0.4s


def test_open_is_prepended_ahead_of_speech(monkeypatch):
    fake = _FakeS3(payload=_wav(OPEN_PCM))
    _install(monkeypatch, fake)

    out = _pcm_of(bo.prepend_into_wav(_wav(SPEECH_PCM)))

    assert out.startswith(OPEN_PCM), "the frozen open must lead the episode"
    assert out.endswith(SPEECH_PCM), "the speech must survive the splice intact"
    gap = int(bo.GAP_SECONDS * SR) * CH * SW
    assert len(out) == len(OPEN_PCM) + gap + len(SPEECH_PCM)
    assert out[len(OPEN_PCM) : len(OPEN_PCM) + gap] == b"\x00" * gap


def test_asset_fetched_once_per_container(monkeypatch):
    fake = _FakeS3(payload=_wav(OPEN_PCM))
    _install(monkeypatch, fake)

    for _ in range(4):
        bo.prepend_into_wav(_wav(SPEECH_PCM))

    assert fake.calls == 1, "the frozen asset must be cached, not re-fetched per episode"


@pytest.mark.parametrize(
    "rate,channels,sampwidth",
    [
        (44100, CH, SW),  # wrong sample rate — would play fast and high
        (SR, 2, SW),  # wrong channel count — would play at half speed
        (SR, CH, 1),  # wrong sample width — would play as noise
    ],
)
def test_format_mismatch_is_refused(monkeypatch, rate, channels, sampwidth):
    """The silent-corruption case: a mismatched splice publishes cleanly and
    sounds wrong. It must be refused, not resampled or best-efforted."""
    fake = _FakeS3(payload=_wav(OPEN_PCM, rate=rate, channels=channels, sampwidth=sampwidth))
    _install(monkeypatch, fake)

    episode = _wav(SPEECH_PCM)
    assert bo.prepend_into_wav(episode) == episode, "mismatched asset must yield a cold open"


def test_missing_asset_fails_open(monkeypatch):
    _install(monkeypatch, _FakeS3(raises=RuntimeError("NoSuchKey")))
    episode = _wav(SPEECH_PCM)
    assert bo.prepend_into_wav(episode) == episode


def test_empty_asset_fails_open(monkeypatch):
    _install(monkeypatch, _FakeS3(payload=_wav(b"")))
    episode = _wav(SPEECH_PCM)
    assert bo.prepend_into_wav(episode) == episode


def test_disabled_returns_speech_untouched(monkeypatch):
    monkeypatch.setenv("PANELCAST_BRAND_OPEN", "off")
    fake = _FakeS3(payload=_wav(OPEN_PCM))
    _install(monkeypatch, fake)

    episode = _wav(SPEECH_PCM)
    assert bo.prepend_into_wav(episode) == episode
    assert fake.calls == 0, "disabled must not even reach S3"


def test_enabled_env_gate(monkeypatch):
    monkeypatch.setenv("PANELCAST_BRAND_OPEN", "off")
    assert bo.enabled() is False
    monkeypatch.setenv("PANELCAST_BRAND_OPEN", "on")
    assert bo.enabled() is True
    monkeypatch.delenv("PANELCAST_BRAND_OPEN", raising=False)
    assert bo.enabled() is True  # default ON


def test_garbage_episode_wav_fails_open(monkeypatch):
    _install(monkeypatch, _FakeS3(payload=_wav(OPEN_PCM)))
    assert bo.prepend_into_wav(b"not a wav at all") == b"not a wav at all"


def test_ident_is_off_by_default_so_opens_cannot_stack():
    """#1187 supersedes #1179 — if both fired, every episode would open twice."""
    from emails import panelcast_ident

    os.environ.pop("PANELCAST_IDENT", None)
    assert panelcast_ident.enabled() is False
