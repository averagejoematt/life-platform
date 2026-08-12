"""social_paste_inbox.py — the manual-paste inbox for the CLOSED platforms (#1677, epic #1668).

X, Instagram and TikTok are the closed half of the inbound social membrane: pulling
them needs a paid API tier (X) or a Business/Creator Graph token behind app review
(Instagram, TikTok). Provisioning those is Matthew's money and Matthew's accounts —
a human-only act (`gate:owner` on #1677). Until it happens there is **no token**, and
this repo deliberately contains **no client, no secret read and no token path** for
those three platforms: an unused credential path is a claim that provisioning is
imminent, and it isn't.

What exists instead is the low-tech input path the issue specifies: Matthew pastes a
post, and it lands through the **same** transform/write path a framework-fetched post
takes. The fallback is NOT a second pipeline — it is a different ``fetch_day`` source:

    stage_paste()  ->  DDB staging row  ->  fetch_day()  ->  run_ingestion()
                                                              (SIMP-2 framework)
                                                          ->  transform()
                                                          ->  S2 membrane (origin)
                                                          ->  DATE#{date}#{post_id}

Staging rows live in the source's OWN partition under a ``PASTE#`` sort key:

    pk = USER#{user}#SOURCE#{channel}      sk = PASTE#{YYYY-MM-DD}#{post_id}

That deliberately introduces no new partition (so ``phase_taxonomy`` classifies a
pasted post exactly as it classifies the ingested one — RAW_TIMESERIES, via the
channel's own source key) and cannot collide with the ingested records, whose keys are
``DATE#…``: the framework's gap detector queries ``sk between DATE#a and DATE#b``, a
range ``PASTE#`` sorts entirely outside of.

Nothing here talks to a platform. The only inputs are the strings the owner pasted.

v1.0.0 — 2026-08-12 (#1677, epic #1668)
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from typing import Any


# ── The channel set ────────────────────────────────────────────────────────────
# Derived from the registry (guard-the-SET): the registry's `inbound_mode` facet is the
# ONE place a platform is declared paste-only, so this module cannot drift from it.
def _paste_only_channels() -> tuple[str, ...]:
    from ingestion.source_registry import paste_only_source_ids

    return tuple(paste_only_source_ids())


PASTE_ONLY_CHANNELS = _paste_only_channels()

# ── The staging key space ──────────────────────────────────────────────────────
PASTE_SK_PREFIX = "PASTE#"
# `capture` stamps HOW the row arrived, so a future token-backed poll (acceptance box 1
# of #1677) is distinguishable from a paste in the stored data, not just in the logs.
CAPTURE_PASTE = "paste"


def source_pk(channel: str, user_id: str | None = None) -> str:
    """The source partition a channel's records (ingested AND staged) live in."""
    user = user_id or os.environ.get("USER_ID", "matthew")
    return f"USER#{user}#SOURCE#{channel}"


def paste_sk(date_str: str, post_id: str) -> str:
    """The staging sort key for one pasted post on one Pacific day."""
    return f"{PASTE_SK_PREFIX}{date_str}#{post_id}"


# ── Post-id extraction (from the pasted permalink) ─────────────────────────────
# Deriving the id from the URL keeps a re-paste of the same post idempotent: same id ->
# same staging sk -> same ingested sk (DATE#{date}#{post_id}), so it overwrites rather
# than duplicating. A paste with no recognisable permalink falls back to a content hash,
# which is idempotent for an unchanged paste and honest about being synthesised.
_ID_PATTERNS: dict[str, tuple[re.Pattern, ...]] = {
    "x": (
        re.compile(r"(?:twitter\.com|x\.com)/[^/]+/status(?:es)?/(\d+)", re.I),
        re.compile(r"(?:twitter\.com|x\.com)/i/web/status/(\d+)", re.I),
    ),
    "instagram": (re.compile(r"instagram\.com/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)", re.I),),
    "tiktok": (
        re.compile(r"tiktok\.com/@[^/]+/video/(\d+)", re.I),
        re.compile(r"tiktok\.com/(?:v|embed)/(\d+)", re.I),
    ),
}

_SYNTHETIC_ID_PREFIX = "paste-"


def derive_post_id(channel: str, url: str = "", text: str = "", date_str: str = "") -> str:
    """The post's stable id: from its permalink when parseable, else a content hash.

    Never random — a second paste of the same post must resolve to the same id or the
    ``#{post_id}``-suffixed write stops being idempotent and the day grows duplicates.
    """
    for pattern in _ID_PATTERNS.get(channel, ()):
        m = pattern.search(url or "")
        if m:
            return m.group(1)
    digest = hashlib.sha256(f"{channel}|{date_str}|{url}|{text}".encode("utf-8")).hexdigest()[:12]
    return f"{_SYNTHETIC_ID_PREFIX}{digest}"


def is_synthetic_post_id(post_id: str) -> bool:
    """True when the id was hashed from content because the paste carried no permalink."""
    return str(post_id or "").startswith(_SYNTHETIC_ID_PREFIX)


# ── Normalisation ──────────────────────────────────────────────────────────────


def _pacific_date(published_at: str) -> str | None:
    """The Pacific calendar day of an ISO timestamp (the platform-wide day convention)."""
    if not published_at:
        return None
    try:
        from common.pacific_time import pacific_date_of

        return pacific_date_of(published_at)
    except Exception:  # noqa: BLE001 — an unparseable paste timestamp is the caller's problem, not a crash
        return None


def _today_pacific() -> str:
    from common.pacific_time import pacific_now

    return pacific_now().date().strftime("%Y-%m-%d")


def normalize_paste(
    channel: str,
    *,
    url: str = "",
    text: str = "",
    published_at: str = "",
    author: str = "",
    post_id: str = "",
    date_str: str = "",
) -> dict[str, Any]:
    """Turn what the owner pasted into the SAME flat entry shape the framework sources emit.

    The keys (``post_id``/``text``/``url``/``embed_url``/``published``/``author``) are the
    ones ``bluesky_lambda._parse_entries`` and ``youtube_lambda`` produce, because the
    transform downstream of this is the same transform. That is the whole design
    constraint: one shape in, one write path out.
    """
    if channel not in PASTE_ONLY_CHANNELS:
        raise ValueError(f"{channel!r} is not a paste-only closed platform (expected one of {list(PASTE_ONLY_CHANNELS)})")
    text = (text or "").strip()
    url = (url or "").strip()
    resolved_date = date_str or _pacific_date(published_at) or _today_pacific()
    return {
        "post_id": post_id or derive_post_id(channel, url=url, text=text, date_str=resolved_date),
        "text": text,
        "url": url,
        # A pasted post carries no separate embed link — the permalink IS the only URL we
        # have. Declared (not omitted) so the membrane's text_fields sweep is uniform.
        "embed_url": "",
        "published": published_at or "",
        "author": (author or "").strip(),
        "date": resolved_date,
        "capture": CAPTURE_PASTE,
    }


# ── Staging (write) ────────────────────────────────────────────────────────────


def stage_paste(table, channel: str, *, user_id: str | None = None, now: str | None = None, **paste) -> dict[str, Any]:
    """Write one pasted post into the staging inbox. Idempotent on (channel, date, post_id).

    All values are strings — there is no numeric field on a pasted post (engagement
    counts are not pasted; a token-backed poll is what would carry them), so the
    Decimal-before-DDB rule has nothing to convert here. Anything numeric added later
    must be cast at THIS call site.
    """
    entry = normalize_paste(channel, **paste)
    item = {
        "pk": source_pk(channel, user_id),
        "sk": paste_sk(entry["date"], entry["post_id"]),
        "channel": channel,
        "capture": CAPTURE_PASTE,
        "staged_at": now or datetime.now(timezone.utc).isoformat(),
        **{k: v for k, v in entry.items() if v != ""},
    }
    table.put_item(Item=item)
    return item


# ── Staging (read) — this is the `fetch_day` source ────────────────────────────


def staged_entries(table, channel: str, date_str: str, user_id: str | None = None) -> list[dict[str, Any]]:
    """Every post staged for ``date_str`` on ``channel``, in the framework entry shape.

    This is what the closed-platform ``fetch_day`` returns instead of an API response.
    """
    from boto3.dynamodb.conditions import Key

    resp = table.query(
        KeyConditionExpression=Key("pk").eq(source_pk(channel, user_id)) & Key("sk").begins_with(f"{PASTE_SK_PREFIX}{date_str}#"),
    )
    entries = []
    for item in resp.get("Items", []):
        entries.append(
            {
                "post_id": item.get("post_id", ""),
                "text": item.get("text", ""),
                "url": item.get("url", ""),
                "embed_url": item.get("embed_url", ""),
                "published": item.get("published", ""),
                "author": item.get("author", ""),
                "capture": item.get("capture", CAPTURE_PASTE),
            }
        )
    return [e for e in entries if e["post_id"]]
