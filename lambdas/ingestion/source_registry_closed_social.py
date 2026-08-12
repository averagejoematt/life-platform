"""source_registry_closed_social.py — the CLOSED social platforms' registry entries (#1677).

A section of ``source_registry.SOURCE_REGISTRY``, not a second registry: the dict below is
spliced into it (``**CLOSED_SOCIAL_PASTE_SOURCES``) at definition, so every consumer still
reads ONE registry. It lives in its own file because the three entries carry a long
rationale — *why* these platforms are paste-only and what "registered" therefore does not
mean — and the parent module sits against the #1665 module-size ratchet.

X, Instagram and TikTok have no free read path: X needs a paid API tier, Instagram and
TikTok need Business/Creator Graph tokens behind app review. Provisioning any of it is
Matthew's money and Matthew's accounts, and the owner's 2026-08-12 decision is that it is
not being provisioned. So each entry carries ``inbound_mode: 'paste-only'`` — the
load-bearing declaration that this repo holds no client, no secret and no token read for
that platform, and that a record exists only because he pasted one
(``lambdas/ingestion/social_paste_inbox.py``, which lands it on the same SIMP-2 write
path a fetched post takes: same transform, same ``#{post_id}`` suffix, same S2 membrane).

v1.0.0 — 2026-08-12 (#1677, epic #1668)
"""

from typing import Any

# The paste-only value of the `inbound_mode` facet (documented in source_registry.py's
# facet block). Defined here, next to its only users, and re-exported by the parent.
INBOUND_PASTE_ONLY = "paste-only"

CLOSED_SOCIAL_PASTE_SOURCES: dict[str, dict[str, Any]] = {
    # "Registered" here does NOT mean "polling": a future session that wants polling must
    # flip `inbound_mode`, which is the review moment that decision deserves.
    #
    # freshness/monitored/active_api are all False for the same reason as the open three
    # (#1669/#1676) — a source with no automatic pipe must not appear on a freshness, QA
    # or liveness surface, where it would false-page on the owner simply not pasting.
    # Staleness here is not a fault: there is nothing to break.
    "x": {
        "label": "X",
        "checker_label": "X posts",
        "desc": "Inbound social — Matthew's own X posts (public voice), captured by paste",
        "category": "Inputs",
        "behavioral": True,  # a paste happens only when he does it
        "stale_hours": None,
        "freshness": False,  # no automatic pipe — never on a freshness surface (#1677)
        "monitored": False,
        "active_api": False,  # NO API access at all: the X tier is unprovisioned by decision
        "inbound_mode": INBOUND_PASTE_ONLY,
        "expected_days": None,
        "qa_tier": None,
        "method": "Manual paste (no token) — staged to PASTE# and ingested through the SIMP-2 framework",
        "metrics": "Posts — the outbound public voice, pasted back in",
        "posture": "portfolio",
        # Deliberately NO capture_channel: that facet drives the evening "you forgot to
        # log" nudges and is reserved for Matthew's three logging channels (#746/#1682).
        # A paste is opportunistic, not a daily obligation, and must not nag.
        "catalog": False,
        # No raw/ tree, and the ingestion config sets enable_raw_archive=False to match:
        # nothing is FETCHED, so there is no API response to archive. The staged
        # PASTE#{date}#{post_id} row in this source's own partition IS the raw record —
        # it holds exactly the strings the owner pasted. A raw_layout appears the day a
        # token-backed fetch does (box 1 of #1677), not before.
        "raw_layout": None,
    },
    "instagram": {
        "label": "Instagram",
        "checker_label": "Instagram posts",
        "desc": "Inbound social — Matthew's own Instagram posts (public voice), captured by paste",
        "category": "Inputs",
        "behavioral": True,
        "stale_hours": None,
        "freshness": False,
        "monitored": False,
        "active_api": False,  # Graph API needs a Business/Creator token + app review
        "inbound_mode": INBOUND_PASTE_ONLY,
        "expected_days": None,
        "qa_tier": None,
        "method": "Manual paste (no token) — staged to PASTE# and ingested through the SIMP-2 framework",
        "metrics": "Posts and reels — the outbound public voice, pasted back in",
        "posture": "portfolio",
        "catalog": False,
        # No raw/ tree, and the ingestion config sets enable_raw_archive=False to match:
        # nothing is FETCHED, so there is no API response to archive. The staged
        # PASTE#{date}#{post_id} row in this source's own partition IS the raw record —
        # it holds exactly the strings the owner pasted. A raw_layout appears the day a
        # token-backed fetch does (box 1 of #1677), not before.
        "raw_layout": None,
    },
    "tiktok": {
        "label": "TikTok",
        "checker_label": "TikTok posts",
        "desc": "Inbound social — Matthew's own TikTok posts (public voice), captured by paste",
        "category": "Inputs",
        "behavioral": True,
        "stale_hours": None,
        "freshness": False,
        "monitored": False,
        "active_api": False,  # Display API needs an approved app + Creator token
        "inbound_mode": INBOUND_PASTE_ONLY,
        "expected_days": None,
        "qa_tier": None,
        "method": "Manual paste (no token) — staged to PASTE# and ingested through the SIMP-2 framework",
        "metrics": "Videos — the outbound public voice, pasted back in",
        "posture": "portfolio",
        "catalog": False,
        # No raw/ tree, and the ingestion config sets enable_raw_archive=False to match:
        # nothing is FETCHED, so there is no API response to archive. The staged
        # PASTE#{date}#{post_id} row in this source's own partition IS the raw record —
        # it holds exactly the strings the owner pasted. A raw_layout appears the day a
        # token-backed fetch does (box 1 of #1677), not before.
        "raw_layout": None,
    },
}
