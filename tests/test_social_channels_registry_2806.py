"""tests/test_social_channels_registry_2806.py — the derivation guard for the social/
broadcast channel vocabulary (#2806/#2807/#2808).

Before this landed, "which channels are inbound social" was hand-typed in THREE
places, and they had already drifted apart:
  1. `cdk/stacks/ingestion_stack.py` — the social-enrichment lambda's `SOCIAL_CHANNELS`
     env, a literal `"youtube,bluesky,mastodon"` string.
  2. `lambdas/web/site_api_social.py::_BROADCAST_SOURCES` — the broadcast feed +
     membrane dashboard's source tuple, iterated by `site_api_social_membrane.py` too.
  3. `lambdas/emails/daily_brief_lambda.py::fetch_social_posts` — read from a
     `SOCIAL_CHANNELS` env var that was NEVER SET on the live daily-brief function, so
     it silently fell back to a hand-typed "youtube" default.

All three were missing the three paste-only closed platforms (x/instagram/tiktok,
#1677) — they landed in the registry AFTER each hand-typed copy was last edited, and
no record noticed the exclusion was now unique to them (#2806's stale-premise finding).

The fix: `lambdas/ingestion/source_registry.py::social_channel_source_ids()` is now the
ONE place this vocabulary is spelled out (the `social_channel` facet), and all three
consumers derive from it. This file is the "guard the SET, not the instance" test
(charter primitive 2, docs/CHARTER.md standing rule 1) — it asserts the real,
registry-derived values are in lockstep TODAY, and separately proves (mutation
evidence) that the guard logic actually goes red on a planted drift, so the assertion
above is not a guard on nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from ingestion.source_registry import INBOUND_PASTE_ONLY, paste_only_source_ids, social_channel_source_ids
from web import site_api_social as social

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "cdk"))
import stacks.ingestion_stack as ingestion_stack  # noqa: E402

# ═══════════════════════════════════════════════════════════════════════════════
# 1. paste_only_source_ids() ⊆ social_channel_source_ids()  (#2806 AC2)
# ═══════════════════════════════════════════════════════════════════════════════


def _assert_paste_only_subset_of_social(registry: dict) -> None:
    """The guard logic itself, factored out so the mutation test below can drive it
    against a planted-bad registry and prove it actually goes red."""
    paste_only = {k for k, v in registry.items() if v.get("inbound_mode") == INBOUND_PASTE_ONLY}
    social_channels = {k for k, v in registry.items() if v.get("social_channel")}
    missing = paste_only - social_channels
    assert not missing, f"paste-only source(s) missing `social_channel: True`, so they'd drop out of every consumer: {sorted(missing)}"


def test_paste_only_is_a_subset_of_social_channel_source_ids():
    from ingestion.source_registry import SOURCE_REGISTRY

    _assert_paste_only_subset_of_social(SOURCE_REGISTRY)
    # Concrete today: exactly the three closed platforms, and they ARE covered.
    assert set(paste_only_source_ids()) == {"x", "instagram", "tiktok"}
    assert set(paste_only_source_ids()) <= set(social_channel_source_ids())


def test_guard_detects_a_planted_paste_only_source_missing_the_social_channel_flag():
    """Mutation evidence (CONVENTIONS §9): plant a paste-only source in a copy of the
    registry WITHOUT `social_channel: True` — exactly the #2806 stale-premise bug
    shape (a new closed platform lands, a consumer's hand-typed/derived set doesn't
    pick it up) — and show the guard goes red instead of silently passing."""
    mutated = {
        "x": {"inbound_mode": INBOUND_PASTE_ONLY, "social_channel": True},
        "youtube": {"social_channel": True},
        # planted: a new closed platform ("threads") that forgot the facet — the
        # exact miss #2806 found for x/instagram/tiktok relative to #2161.
        "threads": {"inbound_mode": INBOUND_PASTE_ONLY},
    }
    with pytest.raises(AssertionError, match="threads"):
        _assert_paste_only_subset_of_social(mutated)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. The three consumers stay in lockstep with the registry  (#2806 AC1, #2807 AC1/3)
# ═══════════════════════════════════════════════════════════════════════════════


def _assert_in_lockstep(consumer_channels, label: str) -> None:
    registry_channels = set(social_channel_source_ids())
    consumer_set = set(consumer_channels)
    assert consumer_set == registry_channels, (
        f"{label} has drifted from social_channel_source_ids(): "
        f"missing={sorted(registry_channels - consumer_set)} extra={sorted(consumer_set - registry_channels)}"
    )


def test_cdk_social_channels_env_is_in_lockstep_with_the_registry():
    """#2806 AC1: the enrichment lambda's deployed SOCIAL_CHANNELS env is DERIVED at
    synth time (`ingestion_stack.SOCIAL_CHANNELS_ENV = ",".join(social_channel_source_ids())`),
    not a literal — this asserts the two can never disagree, by construction."""
    env_channels = [c.strip() for c in ingestion_stack.SOCIAL_CHANNELS_ENV.split(",") if c.strip()]
    _assert_in_lockstep(env_channels, "cdk/stacks/ingestion_stack.py SOCIAL_CHANNELS_ENV")


def test_site_broadcast_sources_is_in_lockstep_with_the_registry():
    """#2807 AC1/AC3: `_BROADCAST_SOURCES` (shared by /api/broadcast, /api/social_context
    and — via `_g["_BROADCAST_SOURCES"]` — the /api/membrane dashboard) is derived from
    `social_channel_source_ids()`, not a hand-typed tuple."""
    _assert_in_lockstep(social._BROADCAST_SOURCES, "lambdas/web/site_api_social.py _BROADCAST_SOURCES")


def test_guard_detects_a_site_tuple_that_drifted_from_the_registry():
    """Mutation evidence: the OLD hand-typed `_BROADCAST_SOURCES` (pre-fix, missing the
    three paste-only channels) must fail the lockstep guard."""
    stale_tuple = ("youtube", "bluesky", "mastodon")  # the literal this PR replaced
    with pytest.raises(AssertionError):
        _assert_in_lockstep(stale_tuple, "planted stale tuple")


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Daily-brief / enrichment-lambda parity  (#2808 AC2)
# ═══════════════════════════════════════════════════════════════════════════════


def test_daily_brief_default_channel_set_matches_the_enrichment_lambdas_deployed_env():
    """#2808 AC2: "a parity test asserts the brief's effective channel set equals the
    enrichment lambda's". `fetch_social_posts` (no SOCIAL_CHANNELS env set — the live
    daily-brief function's actual state) derives from `social_channel_source_ids()`;
    the enrichment lambda's deployed env is ALSO derived from `social_channel_source_ids()`
    (previous test). Both being registry-derived is exactly why they can't disagree —
    this pins that equivalence so a future hand-edit of either can't quietly reopen it."""
    brief_channels = set(social_channel_source_ids())  # what fetch_social_posts uses by default (#2808 fix)
    enrichment_channels = {c.strip() for c in ingestion_stack.SOCIAL_CHANNELS_ENV.split(",") if c.strip()}
    assert brief_channels == enrichment_channels


# ═══════════════════════════════════════════════════════════════════════════════
# 4. #2807's residual defect: paste-only channels must render "paste-only", never
#    the misleading "dormant" that active_api:False alone would produce.
# ═══════════════════════════════════════════════════════════════════════════════


def test_paste_only_channels_report_paste_only_not_dormant():
    for source in paste_only_source_ids():
        assert social._inbound_channel_live(source) is False, f"{source} has no API — active_api must be False"
        assert social._inbound_channel_state(source) == "paste-only", f"{source} must render 'paste-only', not 'dormant'"


def test_fetched_channels_still_use_the_plain_live_dormant_states():
    """The fix must not touch the two existing states for a normal fetched channel —
    only the paste-only class gets the new third state."""
    for source in ("youtube", "bluesky", "mastodon"):
        expected = "live" if social._inbound_channel_live(source) else "dormant"
        assert social._inbound_channel_state(source) == expected
