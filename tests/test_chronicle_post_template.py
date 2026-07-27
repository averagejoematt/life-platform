"""tests/test_chronicle_post_template.py — #384: the individual chronicle post page
is on the v5 "The Measured Life" template.

Pins the five acceptance criteria of the story-hosted post page so a template
regression can't silently re-introduce the retired chrome:
  * AC1 — the live five-door story-top nav (no legacy /platform//character//#experiment links),
  * AC2 — og:image is the editorial cover when one exists (og-home fallback otherwise),
  * AC3 — rel=canonical + structured-data @id both point at the un-redirected /journal/posts/ URL
          (the retired /chronicle/posts/ path is gone),
  * AC4 — an end-of-read subscribe CTA linking /subscribe/,
  * (AC5 — "verified live on the newest post" is post-deploy + weekly-publish gated; not unit-testable.)

All offline — editorial_image is force-disabled so no S3/network fetch happens; the
template is rendered via publish_to_journal(write_to_s3=False).
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

import wednesday_chronicle_lambda as chron  # noqa: E402

_BODY = "<p>It was a quiet, steady week — nothing dramatic, everything trending the right way.</p><p>More.</p>"
_INSTALLMENTS = [
    {"date": "2026-06-24", "week_number": 3, "title": "Prior", "stats_line": ""},
    {"date": "2026-07-01", "week_number": 4, "title": "The weight of a steady week", "stats_line": "Weight 298 lb"},
]


class _NoS3:
    """Neutralize the prior-manifest read so the test is hermetic regardless of live
    AWS creds — publish_to_journal(write_to_s3=False) never writes, it only reads
    generated/journal/posts.json to carry covers forward; force that to miss."""

    def get_object(self, *a, **k):
        raise RuntimeError("offline")


def _render(monkeypatch, cur_image=None):
    """Render the post page HTML offline. editorial_image is force-off so no fetch runs;
    cur_image lets a test inject a cover to exercise the og:image path."""
    import editorial_image

    monkeypatch.setattr(chron, "s3", _NoS3())
    monkeypatch.setattr(editorial_image, "enabled", lambda: bool(cur_image))
    if cur_image is not None:
        monkeypatch.setattr(editorial_image, "fetch_and_store", lambda *a, **k: cur_image)
    post_key, post_html, _posts_json = chron.publish_to_journal(
        title="The weight of a steady week",
        stats_line="Weight 298 lb · Recovery 64% · 5 workouts",
        body_html=_BODY,
        week_num=4,
        date_str="2026-07-01",
        all_installments=_INSTALLMENTS,
        write_to_s3=False,
    )
    return post_key, post_html


# ── AC1: the live five-door nav; legacy links gone ────────────────────────────


def test_ac1_five_door_story_top_nav(monkeypatch):
    _key, html = _render(monkeypatch)
    assert 'class="story-top"' in html
    for door in ('href="/cockpit/"', 'href="/data/"', 'href="/coaching/"', 'href="/protocols/"', 'href="/story/"'):
        assert door in html, door
    # the story door is the current one (the post lives under it)
    assert 'href="/story/" aria-current="page"' in html


def test_ac1_legacy_chrome_removed(monkeypatch):
    _key, html = _render(monkeypatch)
    for legacy in ('class="nav__link"', 'class="nav__brand"', 'href="/#experiment"', 'href="/platform/"', 'class="footer"', "base.css"):
        assert legacy not in html, legacy


# ── AC2: og:image is the editorial cover, with a graceful fallback ────────────


def test_ac2_og_image_is_editorial_cover(monkeypatch):
    cover = {"image_url": "https://averagejoematt.com/generated/editorial/chronicle/week-04.jpg", "image_credit": "Unsplash / X"}
    _key, html = _render(monkeypatch, cur_image=cover)
    assert f'<meta property="og:image" content="{cover["image_url"]}">' in html
    assert f'<meta name="twitter:image" content="{cover["image_url"]}">' in html
    # the cover also renders in the header art with its credit
    assert cover["image_url"] in html and cover["image_credit"] in html


def test_ac2_og_image_falls_back_when_no_cover(monkeypatch):
    _key, html = _render(monkeypatch)  # editorial disabled → no cover
    assert '<meta property="og:image" content="https://averagejoematt.com/assets/images/og-home.png">' in html


# ── AC3: canonical + structured-data point at the un-redirected /journal/ URL ─


def test_ac3_canonical_and_structured_data_use_journal_path(monkeypatch):
    _key, html = _render(monkeypatch)
    # 2026-07-01 is the 2nd installment by date → sequential index week-02
    canon = "https://averagejoematt.com/journal/posts/week-02/"
    assert f'<link rel="canonical" href="{canon}">' in html
    assert f'"@id": "{canon}"' in html
    # the retired path must be gone everywhere in the document
    assert "/chronicle/posts/" not in html


# ── AC4: the end-of-read subscribe CTA ────────────────────────────────────────


def test_ac4_subscribe_cta_present(monkeypatch):
    _key, html = _render(monkeypatch)
    assert 'class="post-cta"' in html
    assert 'href="/subscribe/"' in html
    # the footer also carries a follow-by-email link (site-foot)
    assert 'class="site-foot"' in html


# ── the key still targets the sequential post path ────────────────────────────


def test_post_key_is_sequential_week_path(monkeypatch):
    key, _html = _render(monkeypatch)
    assert key == "generated/journal/posts/week-02/index.html"


# ── #1803: the cover image must land in posts.json on a FIRST-EVER publish ────
# Root cause: wednesday_chronicle_lambda synthesizes a placeholder dict for
# all_installments when the installment isn't in DDB yet (first publish of a new
# date). publish_to_journal's manifest loop decides "is this the post being
# published right now" (and therefore gets the freshly-fetched cur_image) via
# sk == f"DATE#{date_str}" (ac753774, tie-safe same-date ordering). The
# synthesized dict never set sk, so the freshly-fetched image never reached the
# manifest even though the post's own HTML/og:image rendered it fine.


def _publish_and_get_manifest_entry(monkeypatch, installments, cur_image, date_str="2026-07-01"):
    """Call publish_to_journal like _render does, but return the parsed posts.json
    manifest entry for date_str instead of the HTML (#1803 needs the manifest,
    not the post page, since the bug is manifest-only)."""
    import json as _json

    import editorial_image

    monkeypatch.setattr(chron, "s3", _NoS3())
    monkeypatch.setattr(editorial_image, "enabled", lambda: True)
    monkeypatch.setattr(editorial_image, "fetch_and_store", lambda *a, **k: cur_image)
    _post_key, _html, posts_json_str = chron.publish_to_journal(
        title="The weight of a steady week",
        stats_line="Weight 298 lb · Recovery 64% · 5 workouts",
        body_html=_BODY,
        week_num=1,
        date_str=date_str,
        all_installments=installments,
        write_to_s3=False,
    )
    manifest = _json.loads(posts_json_str)
    return next(p for p in manifest["posts"] if p["date"] == date_str)


def test_1803_cover_image_lands_on_first_ever_publish_with_sk_set(monkeypatch):
    """The FIXED shape: the synthesized installment carries sk (as
    wednesday_chronicle_lambda now stamps it) — the manifest entry for that date
    must carry the freshly-fetched cover, not an empty image_url."""
    cover = {"image_url": "https://averagejoematt.com/generated/editorial/chronicle/week-01.jpg", "image_credit": "Unsplash / Y"}
    installment = {
        "title": "The weight of a steady week",
        "week_number": 1,
        "date": "2026-07-01",
        "sk": "DATE#2026-07-01",  # the #1803 fix
        "stats_line": "Weight 298 lb",
        "word_count": 10,
        "content_markdown": "It was a quiet week.",
        "has_board_interview": False,
    }
    entry = _publish_and_get_manifest_entry(monkeypatch, [installment], cover)
    assert entry["image_url"] == cover["image_url"]
    assert entry["image_credit"] == cover["image_credit"]


def test_1803_missing_sk_reproduces_the_pre_fix_bug(monkeypatch):
    """Regression pin: WITHOUT sk (the pre-fix synthesized shape), the manifest
    entry's image_url stays empty even though a fresh cover was fetched — this
    reproduces the exact #1803 bug and guards against silently re-dropping the
    sk stamp from wednesday_chronicle_lambda's synthesis dicts."""
    cover = {"image_url": "https://averagejoematt.com/generated/editorial/chronicle/week-01.jpg", "image_credit": "Unsplash / Y"}
    installment = {
        "title": "The weight of a steady week",
        "week_number": 1,
        "date": "2026-07-01",
        # no "sk" key — the pre-fix shape
        "stats_line": "Weight 298 lb",
        "word_count": 10,
        "content_markdown": "It was a quiet week.",
        "has_board_interview": False,
    }
    entry = _publish_and_get_manifest_entry(monkeypatch, [installment], cover)
    assert entry["image_url"] == ""
