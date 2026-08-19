"""source_registry_social.py — the social/broadcast channel derivation (#2806/#2807/
#2808), split out of source_registry.py to keep it under the #1665 module-size hard
ceiling (the #2610 extraction precedent: `cdk/stacks/role_policies.py` -> per-domain
siblings #2604, `cdk/stacks/monitoring_dashboards.py` out of `monitoring_stack.py`
#2610, `lambdas/emails/weekly_digest_extractors.py` out of `weekly_digest_lambda.py`
#2221).

A cohesive sibling, not a second registry — `source_registry.py` re-exports
``social_channel_source_ids`` at its own top level (``from
ingestion.source_registry_social import social_channel_source_ids  # noqa: F401``), so
every existing caller (``cdk/stacks/ingestion_stack.py``,
``lambdas/web/site_api_social.py``, ``lambdas/emails/daily_brief_lambda.py``, and the
tests) keeps importing it via ``ingestion.source_registry`` unchanged.

The one registry-derived vocabulary for "which channels count as social" (#2806/#2807/
#2808) — three consumers had each hand-typed their own copy and drifted apart, uniquely
excluding the three paste-only closed platforms (x/instagram/tiktok, #1677: they landed
in the registry AFTER the enrichment lambda's env and the site's `_BROADCAST_SOURCES`
tuple were last hand-edited): the enrichment lambda's `SOCIAL_CHANNELS` env
(`cdk/stacks/ingestion_stack.py`, now derived at synth time), the broadcast feed +
membrane dashboard's `_BROADCAST_SOURCES` (`lambdas/web/site_api_social.py`), and the
daily brief's coach-context channel read (`lambdas/emails/daily_brief_lambda.py`).
"""

from typing import Any


def social_channel_source_ids() -> list:
    """Every inbound social/broadcast channel (epic #1668) — the three fetched, open
    platforms (youtube/bluesky/mastodon) UNION the three paste-only closed platforms
    (x/instagram/tiktok, `paste_only_source_ids()`). `paste_only_source_ids()` is a
    strict subset by construction: every paste-only source also carries
    `social_channel: True` in the registry's `SOURCE_REGISTRY` dict.

    Imports `SOURCE_REGISTRY` lazily (function-local, not module-level) — this module
    is imported BY `source_registry.py` (for the re-export above) before
    `SOURCE_REGISTRY` exists, so a top-level `from ingestion.source_registry import
    SOURCE_REGISTRY` here would be a circular import. By the time anything actually
    CALLS this function, `source_registry` has finished loading.
    """
    from ingestion.source_registry import SOURCE_REGISTRY

    registry: dict[str, dict[str, Any]] = SOURCE_REGISTRY
    return sorted(k for k, v in registry.items() if v.get("social_channel"))
