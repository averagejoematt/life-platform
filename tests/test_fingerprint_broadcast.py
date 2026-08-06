"""tests/test_fingerprint_broadcast.py — #1402: the Daily Fingerprint broadcast payload.

What is pinned here is the governance, not the prose. The caption's wording may change;
these five properties may not:

  1. The payload sources ONLY from already-public `generated/` artifacts and from the
     five allowlisted `public_stats.json` fields — a private field cannot leak into it
     even when it is sitting right next to an allowlisted one in the same block.
  2. No body-composition claim can reach a caption (ADR-140 rule 5).
  3. No engagement bait can reach a caption (the no-gloss rule in prose).
  4. Zero AI — the module cannot reach `bedrock_client` (ADR-140 rule 1 / ADR-108).
  5. No AUTOMATED surface may post this artifact class; a thin day is never offered.
"""

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import pytest  # noqa: E402
from content import fingerprint_broadcast as fb  # noqa: E402
from web.fingerprint import SIGNAL_COUNT, build_mark  # noqa: E402

DATE = "2026-08-05"

# A realistic public_stats.json shape: allowlisted fields sitting in the SAME blocks as
# fields that must never be broadcast. weight_lbs is the one that matters — it is public
# on the site, so a privacy filter would wave it through; it is excluded here because
# ADR-140 rule 5 excludes body composition from syndication regardless of publicness.
STATS = {
    "platform": {"days_in": 4, "tier0_streak": 2, "mcp_tools": 76, "lambdas": 99},
    "vitals": {
        "recovery_pct": 44.0,
        "sleep_hours": 7.2,
        "hrv_ms": 35.0,
        "weight_lbs": 322,
        "weight_delta_7d": 5.3,
        "rhr_bpm": 60.0,
    },
    "journey": {"lost_lbs": 13.4, "current_weight_lbs": 322},
    "hero": {"why_paragraph": "a narrative paragraph that is not a broadcastable number"},
}

FULL_METRICS = {"recovery": 44.0, "sleep_hours": 7.2, "hrv": 35.0, "streak": 2}
THIN_METRICS = {"recovery": 44.0}  # 1 signal < THIN_N ⇒ warming up


def _build(metrics=None, stats=None, attempt=12):
    return fb.build_broadcast(
        date_str=DATE,
        mark=build_mark(DATE, FULL_METRICS if metrics is None else metrics),
        stats=STATS if stats is None else stats,
        total_signals=SIGNAL_COUNT,
        attempt=attempt,
    )


# ── 1. structural allowlist ──────────────────────────────────────────────────


def test_projection_reaches_only_allowlisted_public_fields():
    public = fb.project_public(STATS)
    assert set(public) == {f"{b}.{k}" for b, k in fb.PUBLIC_SOURCE_FIELDS}
    assert public["platform.days_in"] == 4
    assert public["vitals.recovery_pct"] == 44.0


def test_payload_carries_no_value_from_an_unlisted_field():
    """The un-allowlisted neighbours — weight, deltas, RHR, the hero paragraph — must not
    appear anywhere in the serialized payload, by value or by phrase."""
    import json

    blob = json.dumps(_build())
    for forbidden in ("322", "13.4", "5.3", "60.0", "why_paragraph", "a narrative paragraph"):
        assert forbidden not in blob, f"{forbidden!r} leaked into the broadcast payload"


def test_every_url_is_an_allowlisted_public_moments_artifact():
    payload = _build()
    assert payload["card_url"] == "/moments/assets/fingerprint-2026-08-05.png"
    assert payload["permalink"] == "/moments/fingerprint/2026-08-05/"
    for url in (payload["card_url"], payload["permalink"]):
        assert url.startswith(fb.PUBLIC_URL_PREFIXES)
    with pytest.raises(fb.BroadcastContentError):
        fb.assert_public_artifact("/private/notes/2026-08-05.png")
    with pytest.raises(fb.BroadcastContentError):
        fb.assert_public_artifact("https://example.com/moments/x.png")


# ── 2. no body claim ─────────────────────────────────────────────────────────


def test_caption_carries_no_body_claim():
    caption = _build()["caption"]
    lowered = caption.lower()
    for token in ("lbs", "weight", "bmi", "body fat", "waist", "lost"):
        assert token not in lowered


@pytest.mark.parametrize(
    "bad",
    [
        "The daily fingerprint — day 4. Down 13.4 lbs since genesis.",
        "Weight held flat this week.",
        "Body fat trending down.",
        "Lost ground on the streak.",
    ],
)
def test_body_claim_assertion_rejects(bad):
    with pytest.raises(fb.BroadcastContentError):
        fb.assert_no_body_claims(bad)


# ── 3. provenance, not bait ──────────────────────────────────────────────────


def test_caption_is_templated_provenance_with_day_attempt_and_as_of():
    caption = _build()["caption"]
    assert caption.startswith("The daily fingerprint — day 4, attempt 12, as of 2026-08-05.")
    assert f"4 of {SIGNAL_COUNT} signals reported" in caption
    assert "https://averagejoematt.com/moments/fingerprint/2026-08-05/" in caption
    assert "utm_source=bluesky" in caption and "utm_campaign=fingerprint" in caption


def test_caption_omits_rather_than_guesses_a_missing_day_or_attempt():
    payload = _build(stats={"vitals": STATS["vitals"]}, attempt=None)
    assert payload["caption"].startswith("The daily fingerprint — as of 2026-08-05.")
    assert payload["day"] is None and payload["attempt"] is None


def test_no_engagement_bait_in_either_template_branch():
    for metrics in (FULL_METRICS, THIN_METRICS):
        fb.assert_no_engagement_bait(_build(metrics)["caption"])
    with pytest.raises(fb.BroadcastContentError):
        fb.assert_no_engagement_bait("You won't believe day 4. Link in bio.")


def test_caption_fits_a_bluesky_post_without_truncation():
    """300 is Bluesky's hard limit; a provenance caption that needs truncating loses the
    provenance first, since the link is kept last."""
    assert len(_build()["caption"]) <= 300
    assert len(_build(THIN_METRICS)["caption"]) <= 300


def test_caption_is_deterministic():
    assert _build()["caption"] == _build()["caption"]


# ── 4. zero AI ───────────────────────────────────────────────────────────────


def test_module_has_no_reachable_ai_call():
    with open(os.path.join(_REPO, "lambdas", "content", "fingerprint_broadcast.py")) as fh:
        source = fh.read().lower()
    # The docstring names ADR-108 and bedrock_client to explain WHY there is no call, so
    # the gate is on executable lines only.
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    code = code.split('"""', 2)[-1]  # drop the module docstring
    for banned in ("bedrock", "ai_calls", "anthropic", "invoke("):
        assert banned not in code, f"{banned!r} is reachable from the broadcast module"


# ── 5. automated posting is denied; a thin day is not offered ────────────────


def test_automated_syndication_is_structurally_denied():
    assert fb.AUTOMATED_SYNDICATION_ALLOWED is False
    payload = _build()
    assert "ADR-140" in payload["automated_syndication"]
    assert "#1629" in payload["automated_syndication"]


def test_warming_up_day_is_published_but_not_offered():
    payload = _build(THIN_METRICS)
    assert payload["warming_up"] is True
    assert payload["syndicatable"] is False
    # The card and permalink still exist — the archive has no holes.
    assert payload["card_url"] and payload["permalink"]
    assert "too thin to earn the glow" in payload["caption"]


def test_full_day_is_offerable():
    payload = _build()
    assert payload["warming_up"] is False
    assert payload["syndicatable"] is True
    assert payload["signals_reported"] == 4 and payload["signals_tracked"] == SIGNAL_COUNT


def test_signal_count_matches_the_marks_own_denominator():
    """The caption's denominator must be the mark's, not a typed constant that drifts."""
    mark = build_mark(DATE, FULL_METRICS)
    payload = _build()
    assert payload["signals_reported"] == mark["n"]
    assert payload["signals_tracked"] == SIGNAL_COUNT
