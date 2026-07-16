"""#595 (ADR-114) — the shared card engine: every registered card type renders from a
fixture, the daily og_image_lambda delegates its primitives to the engine (byte-identical
chrome), the uncertainty grammar draws a CI/n sub-line, and the #405 chronicle sweep
produces per-post honest-stats cards from posts.json.

PIL-gated: the drawing tests importorskip Pillow so a PIL-less CI simply skips them (the
same posture as test_og_moments, which fakes the card to stay PIL-free)."""

import io
import os
import sys

import pytest

os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

pytest.importorskip("PIL")

from web import card_engine as ce  # noqa: E402


def _png_size(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return len(buf.getvalue()), img.size


def test_brand_card_fonts_render_basic_latin():
    """Regression guard for the tofu bug: every off-site card font MUST map basic-Latin
    (A-Z / a-z / 0-9). The original Bebas Neue / Space Mono TTFs shipped as subsets with
    NO basic-Latin glyphs, so every card rendered as .notdef boxes from HP-13 until this
    fix — unnoticed because visual QA never inspects the generated PNGs. Detect a missing
    glyph with PIL only (no fontTools dep): a real letter's raster must differ from a
    guaranteed-unmapped private-use codepoint's raster; identical means both fell back to
    the same .notdef box."""
    from PIL import Image, ImageDraw, ImageFont

    fonts_dir = os.path.join(_REPO, "lambdas", "fonts")
    unmapped = chr(0xE000)  # private-use area — absent from any real Latin subset

    def _raster(f, ch):
        im = Image.new("L", (72, 72), 0)
        ImageDraw.Draw(im).text((6, 6), ch, fill=255, font=f)
        return im.tobytes()

    for fname in (ce.FONT_DISPLAY, ce.FONT_MONO, ce.FONT_MONO_BOLD):
        path = os.path.join(fonts_dir, fname)
        assert os.path.exists(path), f"card font not bundled: {fname} (build_bundle stages lambdas/fonts/)"
        f = ImageFont.truetype(path, 48)  # not ce.font() — that masks a missing file with load_default()
        notdef = _raster(f, unmapped)
        for ch in "AZmz09":
            assert _raster(f, ch) != notdef, f"{fname}: {ch!r} renders as .notdef — font lacks basic-Latin (the tofu bug)"


def test_every_registered_card_type_renders_from_a_fixture():
    fixtures = {
        "character": {
            "character": {"level": 17, "tier": "Foundation", "xp_total": 1240, "days_active": 34, "level_events_count": 3},
            "pillars": [{"name": "sleep", "level": 12}, {"name": "movement", "level": 9}],
        },
        "chronicle": {
            "title": "The week the streak broke",
            "label": "Week 05",
            "stats_line": "Weight: 300.8 lbs | Week Grade: avg 57 | T0 Streak: 0 days",
            "date": "2026-07-01",
        },
    }
    assert set(ce.registered_types()) == set(fixtures)  # the reach cards are wired
    for card_type, payload in fixtures.items():
        img = ce.render(card_type, payload)
        n, size = _png_size(img)
        assert size == (ce.W, ce.H) == (1200, 630)  # social-preview dimensions
        assert n > 500  # a real, non-empty card


def test_unknown_card_type_raises():
    with pytest.raises(KeyError):
        ce.render("no-such-card", {})


def test_og_image_lambda_delegates_primitives_to_the_engine():
    """The daily cards render byte-identically because they ARE the engine's
    primitives now — re-exported under the historic names, not re-implemented."""
    from web import og_image_lambda as og

    assert og._font is ce.font
    assert (og.W, og.H) == (ce.W, ce.H)
    for tok in ("BG", "TEXT", "MUTED", "FAINT", "GREEN"):
        assert getattr(og, tok) == getattr(ce, tok)
    # A daily card still builds through the delegated primitives.
    img = og.build_home({"journey": {"lost_lbs": 13.4}, "vitals": {"hrv_ms": 52}, "platform": {"days_in": 21, "tier0_streak": 3}})
    assert img.size == (1200, 630)


def test_character_card_never_carries_chronological_age():
    """ADR-104 + phenoage privacy: the card is computed-stats-only. Smuggling an age
    field into the payload changes NOTHING in the rendered card — the builder reads a
    fixed allowlist and never touches age. Byte-for-byte proof."""
    base = {
        "character": {"level": 40, "tier": "Discipline", "xp_total": 5000, "days_active": 90, "level_events_count": 4},
        "pillars": [{"name": "sleep", "level": 20}, {"name": "movement", "level": 18}],
    }
    with_age = {
        "character": {**base["character"], "chronological_age": 37, "age": 37, "birth_year": 1989},
        "pillars": base["pillars"],
    }
    a, _ = _png_size(ce.render("character", base))
    b_bytes = io.BytesIO()
    ce.render("character", with_age).save(b_bytes, format="PNG")
    base_bytes = io.BytesIO()
    ce.render("character", base).save(base_bytes, format="PNG")
    assert base_bytes.getvalue() == b_bytes.getvalue()  # age is ignored → identical card
    assert a > 500


def test_uncertainty_helper_draws_ci_and_n():
    """#551/ADR-105: a projected number on a card carries its CI + n, never a bare point."""
    img, draw = ce.base_canvas()
    ce.draw_uncertainty(draw, 48, 200, 182.0, "GOAL PROJECTION", ci=(176.0, 190.0), n=42, decimals=0, suffix=" lbs")
    # It rendered onto the canvas without error and the canvas is a full card.
    assert img.size == (1200, 630)


def test_chronicle_sweep_writes_honest_stats_cards_from_posts_json():
    """#405: the daily sweep draws one honest-stats card per published chronicle from
    posts.json — the stats line IS the creative, and the card slug matches the post URL
    (so a kit built off the same URL points at a card that exists)."""
    from web import og_moments as om

    class _S3:
        def __init__(self, objects):
            self.objects = objects
            self.puts = {}

        def get_object(self, Bucket, Key):
            import json

            class _B:
                def __init__(s, d):
                    s._d = d

                def read(s):
                    return s._d

            return {"Body": _B(json.dumps(self.objects[Key]).encode())}

        def put_object(self, Bucket, Key, Body, ContentType, CacheControl=None):
            self.puts[Key] = Body

    posts = {
        "posts": [
            {
                "url": "/journal/posts/week-05/",
                "title": "The week the streak broke",
                "label": "Week 05",
                "stats_line": "Weight: 300.8 lbs | Week Grade: avg 57 | T0 Streak: 0 days",
                "date": "2026-07-01",
            },
            {"url": "/journal/posts/week-04/", "title": "", "label": "Week 04", "stats_line": "x"},  # no title → skipped
        ]
    }
    s3 = _S3({"generated/journal/posts.json": posts})
    out = om._sweep_chronicles(s3)
    assert out == {"/journal/posts/week-05/": "/moments/assets/chronicle-week-05.png"}
    assert "generated/moments/assets/chronicle-week-05.png" in s3.puts
    assert s3.puts["generated/moments/assets/chronicle-week-05.png"][:4] == b"\x89PNG"  # a real PNG


def test_chronicle_sweep_is_fail_soft_without_posts_json():
    from web import og_moments as om

    class _S3:
        def get_object(self, Bucket, Key):
            raise KeyError(Key)

    assert om._sweep_chronicles(_S3()) == []
