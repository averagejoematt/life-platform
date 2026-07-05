"""#405 — the per-chronicle share kit: built from ALREADY-PUBLISHED fields only, its
canonical URL + card slug pinned to the seq the post is actually written to, the honest
stats line preserved verbatim (never sanitized), and the caption a paste-ready recombination
carrying no numbers the post doesn't already show."""

import os
import sys

os.environ.setdefault("AWS_REGION", "us-west-2")
# wednesday_chronicle_lambda reads these at import for its SES/S3 wiring.
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "test@example.com")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

import chronicle_share_kit as k  # noqa: E402

_STATS = "Weight: 300.8 lbs | Week Grade: avg 57 | T0 Streak: 0 days"
_MD = (
    "# The week the streak broke\n\n"
    "The rain did not let up all week, and neither did the sense that something had "
    "slipped. By Thursday the streak was gone, and he knew it before the app told him.\n\n"
    "There were, as ever, numbers."
)


def _kit():
    return k.build_kit(
        title="The week the streak broke",
        stats_line=_STATS,
        label="Week 05",
        date_str="2026-07-01",
        canonical_url="https://averagejoematt.com/journal/posts/week-05/",
        excerpt_source=_MD,
        week_number=5,
    )


def test_kit_carries_only_published_values_and_the_honest_stats_line():
    kit = _kit()
    assert kit["stats_line"] == _STATS  # verbatim — a 57 with a broken streak is the point
    assert kit["canonical_url"] == "https://averagejoematt.com/journal/posts/week-05/"
    assert kit["title"] == "The week the streak broke"
    assert kit["label"] == "Week 05"
    # The excerpt is real prose from the post (not the title line, not the stats block).
    assert "rain did not let up" in kit["excerpt"]
    assert "#" not in kit["excerpt"] and "|" not in kit["excerpt"]


def test_card_url_slug_matches_the_canonical_post_url():
    """The kit's card must live at the same slug the post is written to, so the daily
    sweep's card and the kit reference agree."""
    kit = _kit()
    assert kit["card_url"] == "https://averagejoematt.com/moments/assets/chronicle-week-05.png"
    assert k.kit_s3_key(kit["canonical_url"]) == "generated/moments/share-kits/week-05/kit.json"


def test_caption_is_paste_ready_with_stats_and_link_and_no_new_numbers():
    kit = _kit()
    cap = kit["caption"]
    assert _STATS in cap  # the honest line
    assert kit["canonical_url"] in cap  # the link
    assert "The week the streak broke" in cap
    # No number appears in the caption that isn't in the title/stats/excerpt already.
    import re

    published = kit["title"] + " " + kit["label"] + " " + _STATS + " " + kit["excerpt"]
    for num in re.findall(r"\d+(?:\.\d+)?", cap.replace(kit["canonical_url"], "")):
        assert num in published, f"caption invented a number: {num}"


def test_email_block_escapes_and_surfaces_the_kit():
    block = k.kit_email_block(_kit())
    assert "Share kit" in block
    assert "chronicle-week-05.png" in block
    assert "/journal/posts/week-05/" in block
    # HTML-hostile content is escaped.
    evil = k.build_kit(
        title="<script>x</script>",
        stats_line="a & b",
        label="Week 06",
        date_str="2026-07-08",
        canonical_url="https://averagejoematt.com/journal/posts/week-06/",
        excerpt_source="Plain prose paragraph long enough to be chosen as the excerpt here.",
    )
    b2 = k.kit_email_block(evil)
    assert "<script>" not in b2 and "&lt;script&gt;" in b2


def test_journal_post_ref_seq_matches_the_written_post_slug():
    """journal_post_ref must reproduce publish_to_journal's seq/label so the kit's
    canonical URL points at the real post. Pins the two together against drift."""
    import wednesday_chronicle_lambda as wc

    installments = [
        {"date": "2026-06-25"},  # prologue (before genesis)
        {"date": "2026-07-01"},  # week 1 area
        {"date": "2026-07-08"},
    ]
    # Sorted dates → seq is 1-based position; url is week-{seq:02d}.
    seq, label, url = wc.journal_post_ref("2026-07-08", installments, week_num=2)
    assert seq == 3
    assert url == "https://averagejoematt.com/journal/posts/week-03/"
    # And the kit built off that URL lands on the matching card slug.
    kit = k.build_kit(title="t", stats_line="s", label=label, date_str="2026-07-08", canonical_url=url, excerpt_source="prose " * 20)
    assert kit["card_url"].endswith("chronicle-week-03.png")


def test_empty_excerpt_source_still_produces_a_valid_kit():
    kit = k.build_kit(
        title="Quiet week",
        stats_line=_STATS,
        label="Week 07",
        date_str="2026-07-15",
        canonical_url="https://averagejoematt.com/journal/posts/week-07/",
        excerpt_source="",
    )
    assert kit["excerpt"] == ""
    assert _STATS in kit["caption"]
    assert kit["canonical_url"] in kit["caption"]
