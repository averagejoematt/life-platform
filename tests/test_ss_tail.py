"""tests/test_ss_tail.py — the SS self-sustainability tail (2026-06-30).

SS-11 — editorial-image guardrail: a quality/denylist gate before an auto-picked
        Pexels cover ships (the counterweight to "fully automatic").
SS-09 — podcast format rotation: a deterministic per-week entry-point lens so the
        weekly show doesn't feel formulaic by episode 26.

All offline — no network, no AWS.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

import editorial_image as ei  # noqa: E402

# ── SS-11: editorial-image guardrail ─────────────────────────────────────────


def _photo(w=1600, h=900, alt="quiet shoreline at dawn"):
    return {"width": w, "height": h, "alt": alt, "src": {"landscape": "http://x/img.jpg"}, "photographer": "A. Smith"}


class TestAcceptable:
    def test_good_landscape_passes(self):
        assert ei._acceptable(_photo()) is True

    def test_too_small_rejected(self):
        assert ei._acceptable(_photo(w=800, h=500)) is False

    def test_portrait_rejected(self):
        assert ei._acceptable(_photo(w=900, h=1600)) is False

    def test_people_alt_rejected(self):
        assert ei._acceptable(_photo(alt="a woman running on the beach")) is False
        assert ei._acceptable(_photo(alt="portrait of a man")) is False
        assert ei._acceptable(_photo(alt="crowd at a concert")) is False

    def test_text_brand_rejected(self):
        assert ei._acceptable(_photo(alt="a billboard with a logo")) is False

    def test_word_boundary_no_false_positive(self):
        # Word-boundary matching: "permanent" must not trip the "man" term.
        assert ei._acceptable(_photo(alt="permanent mist over the mountains")) is True
        # but a real "woman" (whole word) is correctly rejected.
        assert ei._acceptable(_photo(alt="a woman on the shore")) is False

    def test_malformed_rejected(self):
        assert ei._acceptable({}) is False
        assert ei._acceptable({"width": None, "height": None}) is False


class TestSearchPicksAcceptable:
    def _run(self, monkeypatch, photos):
        captured = {}

        class _Resp:
            def __init__(self, payload):
                self._p = payload

            def read(self):
                import json

                return json.dumps(self._p).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=0):
            return _Resp({"photos": photos})

        monkeypatch.setattr(ei.urllib.request, "urlopen", fake_urlopen)
        return ei._search("key", "dawn fog landscape", 0), captured

    def test_skips_denylisted_to_first_clean(self, monkeypatch):
        photos = [
            _photo(alt="a man hiking"),  # rejected
            _photo(alt="misty forest light"),  # accepted
        ]
        (dl, credit), _ = self._run(monkeypatch, photos)
        assert dl == "http://x/img.jpg"
        assert "A. Smith" in credit

    def test_no_acceptable_ships_nothing(self, monkeypatch):
        photos = [_photo(alt="portrait of a woman"), _photo(w=400, h=300)]
        (dl, credit), _ = self._run(monkeypatch, photos)
        assert dl is None and credit is None  # fail-closed: no cover rather than a bad one


# ── SS-09: podcast format rotation ───────────────────────────────────────────


def test_episode_angle_rotates_deterministically():
    import coach_panel_podcast_lambda as pod

    n = len(pod._EPISODE_ANGLES)
    assert n >= 4  # a real rotation, not a token one
    # deterministic + cycles by week
    assert pod._episode_angle(1) == pod._episode_angle(1 + n)
    assert pod._episode_angle(1) != pod._episode_angle(2)
    # every week maps to a real non-empty angle
    for wk in range(0, 30):
        assert isinstance(pod._episode_angle(wk), str) and pod._episode_angle(wk).strip()


def test_episode_angle_handles_bad_input():
    import coach_panel_podcast_lambda as pod

    assert pod._episode_angle(None) == pod._EPISODE_ANGLES[0]
    assert pod._episode_angle("nope") == pod._EPISODE_ANGLES[0]
