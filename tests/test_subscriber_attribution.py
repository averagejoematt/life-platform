"""Subscriber attribution — precedence, canary isolation, privacy (#1621).

The epic's 60-day growth gate is graded on "where did subscribers come from". These
tests pin the three properties that make that number trustworthy:

  1. Precedence UTM > free-text > referrer (the issue's stated AC), and that the three
     signals stay SEPARATE attributes rather than collapsing into one string.
  2. `source='canary'` behaviour is unchanged and canary rows carry NO attribution —
     a synthetic subscriber silently entering the attribution numerator would corrupt
     the exact metric this story exists to produce.
  3. The `Referer` header is reduced to a bare host before storage. A full Referer URL
     can carry PII in its query string and the subscriber partition's retention is
     UNSIGNED (docs/DATA_GOVERNANCE.md), so anything written there is written for keeps.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from utm import normalize, referrer_host, with_utm  # noqa: E402


def _build(**kwargs):
    """Import lazily — email_subscriber_lambda constructs boto3 clients at import."""
    from web.email_subscriber_lambda import build_attribution

    return build_attribution(**kwargs)


@pytest.fixture(autouse=True, scope="module")
def _stub_aws():
    """email_subscriber_lambda builds boto3 resources at import time."""
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
    yield


# ── Precedence (the issue's AC) ──────────────────────────────────────────────


def test_precedence_utm_beats_free_text_and_referrer():
    attrs = _build(
        source="a friend told me",
        referrer="https://news.ycombinator.com/item?id=123",
        utm={"utm_source": "reddit"},
    )
    assert attrs["source"] == "reddit"


def test_precedence_free_text_beats_referrer_when_no_utm():
    attrs = _build(source="a friend told me", referrer="https://news.ycombinator.com/item?id=123")
    assert attrs["source"] == "a friend told me"


def test_precedence_referrer_used_when_no_utm_and_no_real_free_text():
    """The old dead-code path, now live.

    The form posts `src || 'subscribe-page'`, so the free-text field is NEVER empty on
    a real signup — that is precisely why the referrer fallback never executed. The
    placeholder must not count as a self-report.
    """
    attrs = _build(source="subscribe-page", referrer="https://news.ycombinator.com/item?id=123")
    assert attrs["source"] == "news.ycombinator.com"


def test_precedence_falls_back_to_subscribe_page_when_nothing_known():
    attrs = _build(source="subscribe-page")
    assert attrs["source"] == "subscribe-page"
    attrs = _build()
    assert attrs["source"] == "subscribe_page"


# ── The signals stay separate ────────────────────────────────────────────────


def test_three_signals_stored_as_separate_attributes():
    """The whole point: measured, self-reported and weak-measured must stay
    distinguishable. Collapsing them is what the issue is about."""
    attrs = _build(
        source="Reddit",
        referrer="https://old.reddit.com/r/quantifiedself/comments/abc/",
        utm={"utm_source": "reddit", "utm_medium": "social", "utm_campaign": "quantifiedself"},
    )
    assert attrs["attr_utm_source"] == "reddit"
    assert attrs["attr_utm_medium"] == "social"
    assert attrs["attr_utm_campaign"] == "quantifiedself"
    assert attrs["attr_self_reported"] == "Reddit"
    assert attrs["attr_referrer_host"] == "old.reddit.com"
    # …and the backward-compatible collapsed field is still populated.
    assert attrs["source"] == "reddit"


def test_absent_signals_are_omitted_not_stored_empty():
    attrs = _build(source="subscribe-page")
    for key in ("attr_utm_source", "attr_utm_medium", "attr_utm_campaign", "attr_referrer_host"):
        assert key not in attrs, f"{key} should be omitted, not stored empty"


# ── Canary isolation ─────────────────────────────────────────────────────────


def test_canary_source_is_preserved_exactly():
    """`source == 'canary'` gates the confirmation-email skip
    (email_subscriber_lambda) and is the exclusion filter for every subscriber count
    in the platform. It must survive attribution untouched."""
    assert _build(source="canary")["source"] == "canary"


def test_canary_carries_no_attribution_even_with_utm_and_referrer():
    """A canary row that picked up a UTM would resolve `source` to that UTM, dropping
    out of the `source <> canary` exclusion filter and entering the attribution
    numerator as a real signup. Hard short-circuit."""
    attrs = _build(
        source="canary",
        referrer="https://old.reddit.com/r/quantifiedself/",
        utm={"utm_source": "reddit", "utm_medium": "social", "utm_campaign": "x"},
    )
    assert attrs == {"source": "canary"}


def test_canary_stays_distinguishable_from_a_real_reddit_signup():
    canary = _build(source="canary", utm={"utm_source": "reddit"})
    real = _build(source="subscribe-page", utm={"utm_source": "reddit"})
    assert canary["source"] != real["source"]


# ── Privacy: referrer host only ──────────────────────────────────────────────


def test_referrer_path_and_query_are_discarded():
    """A full Referer can carry PII (search terms, session ids, a third party's own
    tracking params). Only the host is retained."""
    attrs = _build(source="subscribe-page", referrer="https://mail.example.org/inbox?token=SECRET&user=matthew%40example.com")
    assert attrs["attr_referrer_host"] == "mail.example.org"
    serialized = repr(attrs)
    for leaked in ("SECRET", "matthew", "inbox", "token"):
        assert leaked not in serialized


def test_referrer_userinfo_and_port_stripped():
    assert referrer_host("https://user:pass@news.example.com:8443/x") == "news.example.com"


def test_same_site_referrer_is_not_an_acquisition_signal():
    assert referrer_host("https://averagejoematt.com/cockpit/") == ""
    assert referrer_host("https://www.averagejoematt.com/data/") == ""


@pytest.mark.parametrize("bad", ["", "   ", None, "not-a-url", "javascript:alert(1)", "http://localhost/x", "///"])
def test_referrer_junk_yields_empty(bad):
    assert referrer_host(bad) == ""


# ── Normalization ────────────────────────────────────────────────────────────


def test_utm_values_are_normalized_to_safe_tokens():
    assert normalize("  Reddit  ") == "reddit"
    assert normalize("Quantified Self") == "quantified-self"
    assert normalize("<script>alert(1)</script>") == "script-alert-1-script"
    assert normalize(None) == ""
    assert len(normalize("x" * 500)) == 64


def test_utm_normalization_applied_at_the_write_boundary():
    attrs = _build(source="subscribe-page", utm={"utm_source": "  REDDIT  "})
    assert attrs["attr_utm_source"] == "reddit"
    assert attrs["source"] == "reddit"


# ── The outbound helper ──────────────────────────────────────────────────────


def test_with_utm_tags_a_bare_url():
    out = with_utm("https://averagejoematt.com/story/", source="rss", medium="feed")
    assert "utm_source=rss" in out and "utm_medium=feed" in out


def test_with_utm_preserves_existing_query_params():
    out = with_utm("https://averagejoematt.com/data/?tab=sleep", source="rss", medium="feed")
    assert "tab=sleep" in out and "utm_source=rss" in out


def test_with_utm_is_idempotent():
    once = with_utm("https://averagejoematt.com/story/", source="rss", medium="feed", campaign="chronicle")
    assert with_utm(once, source="other", medium="other", campaign="other") == once


def test_rss_guid_stays_untagged_while_link_is_tagged():
    """Tagging <guid isPermaLink="true"> would change every historical item's identity
    and re-notify every feed subscriber of every past post on the next build."""
    import pathlib

    src = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "v4_build_rss.py"
    text = src.read_text(encoding="utf-8")
    assert "<link>{esc(tagged_link)}</link>" in text
    assert '<guid isPermaLink="true">{esc(link)}</guid>' in text
