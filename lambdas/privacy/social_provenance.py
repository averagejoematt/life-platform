"""social_provenance.py — the provenance membrane for inbound social ingestion (#1670).

THE loop-breaker for The Social Membrane epic (#1668). The platform ALREADY posts
OUT (outbound syndication, #1402/#1622/#1629). Once inbound ingestion (#1669) exists,
a naive poll would re-ingest the platform's OWN outbound posts, re-display them as
"Matthew's voice," and risk re-broadcasting them — "a spanning tree of posting new
tweets to the website" (Matthew). The membrane stamps every ingested post with an
`origin` axis and excludes platform-authored echoes from the voice feed (S4),
enrichment (S3), and any re-broadcast candidate set.

Two provenance signals, deterministic and unit-tested (both kinds of fixture):

  1. The outbound-broadcast ledger. The outbound syndication path (#1402) records
     every post it creates as a ``BROADCAST_ORIGIN#{channel}`` / ``POST#{post_id}``
     DynamoDB row (post id + URL). Inbound ingestion cross-references it; a match is
     ``origin: platform``. #1402's outbound code does not exist in the tree yet — this
     module provides ``record_broadcast_origin()`` for that call-site to use when it
     lands (see the module TODO), and the inbound side already queries via
     ``is_in_broadcast_ledger()``.

  2. Self-backlink detection (secondary signal). A post whose text/links point back to
     ``averagejoematt.com`` is a platform echo even if it is absent from the ledger
     (e.g. the ledger write failed, or the post predates #1402). Caught with an empty
     ledger — see the unit tests.

Everything human-origin flows through; only ``origin: platform`` is filtered. The core
classifier (``classify_origin``) is a pure function of two booleans so it is trivially
testable without AWS; the convenience wrappers do the DDB/text lookups around it.

The ledger rows are provenance truth that must survive an experiment reset (a platform
post from cycle N is still platform-authored in cycle N+1), so ``BROADCAST_ORIGIN#`` is
classified SYSTEM_STATE in ``phase_taxonomy`` — the phase machinery ignores it entirely.

v1.0.0 — 2026-07-21 (#1670, epic #1668)
"""

from __future__ import annotations

from datetime import datetime, timezone

# ── Origin axis ────────────────────────────────────────────────────────────────
ORIGIN_HUMAN = "human"
ORIGIN_PLATFORM = "platform"
VALID_ORIGINS = frozenset({ORIGIN_HUMAN, ORIGIN_PLATFORM})

# The platform's own canonical home. A post that links back here is a platform echo.
SELF_DOMAINS = ("averagejoematt.com",)

# ── Outbound-broadcast ledger schema ───────────────────────────────────────────
# One row per post the outbound syndication path (#1402) creates.
#   pk = BROADCAST_ORIGIN#{channel}   sk = POST#{post_id}
# Kept forever, cross-cycle (SYSTEM_STATE in phase_taxonomy — never tagged/wiped).
_LEDGER_PK_PREFIX = "BROADCAST_ORIGIN#"
_LEDGER_SK_PREFIX = "POST#"


def broadcast_ledger_key(channel: str, post_id: str) -> dict:
    """The DDB primary key for a post's broadcast-origin ledger row."""
    return {"pk": f"{_LEDGER_PK_PREFIX}{channel}", "sk": f"{_LEDGER_SK_PREFIX}{post_id}"}


def record_broadcast_origin(table, channel: str, post_id: str, url: str = "", **extra) -> dict:
    """Write a ``BROADCAST_ORIGIN#`` ledger row for a post the platform just syndicated.

    Called by the outbound syndication path (#1402) at the moment it creates a post,
    so inbound ingestion can later recognise that post as ``origin: platform``. The
    write is idempotent (a plain put_item on a stable key) — re-syndicating the same
    post id just overwrites an identical row.

    #1402's outbound code is NOT in the tree yet; this is the ready-to-call hook for
    when it lands (see module docstring). The inbound side already queries it.
    """
    item = {
        **broadcast_ledger_key(channel, post_id),
        "channel": channel,
        "post_id": post_id,
        "url": url,
        "origin": ORIGIN_PLATFORM,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    item.update({k: v for k, v in extra.items() if v is not None})
    table.put_item(Item=item)
    return item


def is_in_broadcast_ledger(table, channel: str, post_id: str) -> bool:
    """True iff a post is recorded in the outbound-broadcast ledger.

    Fail-open on any read error (returns False → the post is NOT force-classified
    platform by the ledger; the self-backlink signal still applies). A missing
    ledger row is the common case for genuine human posts.
    """
    try:
        resp = table.get_item(Key=broadcast_ledger_key(channel, post_id))
    except Exception:  # noqa: BLE001 — provenance lookup must never break ingestion
        return False
    return bool(resp.get("Item"))


# ── Self-backlink detection ─────────────────────────────────────────────────────


def has_self_backlink(*text_fields: str) -> bool:
    """True iff any provided text/URL references one of the platform's own domains.

    Deterministic and AWS-free — pass a post's title, description, and any explicit
    link URLs. A platform-authored card almost always links back to the site; this
    catches the echo even when the ledger has no row for it.
    """
    haystack = " ".join(str(f) for f in text_fields if f).lower()
    return any(domain in haystack for domain in SELF_DOMAINS)


# ── The classifier ───────────────────────────────────────────────────────────────


def classify_origin(*, in_ledger: bool, self_backlink: bool) -> str:
    """Pure, deterministic origin decision from the two provenance signals.

    Either signal is sufficient to mark a post as a platform echo; absent both, the
    post is human-authored. A pure function of two booleans so the decision table is
    exhaustively unit-testable without any AWS or network dependency.
    """
    if in_ledger or self_backlink:
        return ORIGIN_PLATFORM
    return ORIGIN_HUMAN


def classify_post_origin(table, *, channel: str, post_id: str, text_fields=None) -> str:
    """Convenience: run both lookups for a single post and return its origin.

    ``table`` may be None (skips the ledger lookup — self-backlink only), which is
    what unit tests use to prove a self-linking post is caught with an empty ledger.
    """
    in_ledger = is_in_broadcast_ledger(table, channel, post_id) if table is not None else False
    self_backlink = has_self_backlink(*(text_fields or []))
    return classify_origin(in_ledger=in_ledger, self_backlink=self_backlink)


# ── Exclusion helpers (the membrane's read-side enforcement) ─────────────────────
# S3 (enrichment), S4 (voice feed), and any re-broadcast set MUST filter platform
# echoes out. Those stories aren't built yet, so the membrane ships the reusable
# predicates + a query-layer filter they will call. All treat a MISSING origin as
# human (every ingested post is stamped from day one, #1669; a legacy/unstamped row
# is a genuine human post, never a platform echo — only an explicit `platform` stamp
# is excluded).


def is_platform_origin(post: dict) -> bool:
    """True iff a post is an explicit platform-authored echo."""
    return (post or {}).get("origin") == ORIGIN_PLATFORM


def is_human_origin(post: dict) -> bool:
    """True iff a post is human-authored (or unstamped legacy) — the includable set."""
    return not is_platform_origin(post)


# Named for their call sites so the intent is legible where S3/S4/re-broadcast wire in.
is_enrichable = is_human_origin  # S3: only human posts enrich into coach signals
is_displayable_voice = is_human_origin  # S4: /story/broadcast/ shows human posts (S5 adds the sensitivity gate ON TOP)
is_rebroadcast_candidate = is_human_origin  # never re-syndicate a platform echo


def filter_human(posts):
    """Keep only human-origin posts — the membrane applied to any in-memory list."""
    return [p for p in posts if is_human_origin(p)]


def human_origin_filter_expression():
    """A boto3 FilterExpression excluding platform echoes, for the query layer (S4).

    Usage (S4 /story/broadcast/ query):
        table.query(..., FilterExpression=social_provenance.human_origin_filter_expression())

    ``origin <> 'platform'`` (rather than ``origin = 'human'``) so an unstamped legacy
    row is still returned — only an explicit platform stamp is filtered out.
    """
    from boto3.dynamodb.conditions import Attr

    return Attr("origin").ne(ORIGIN_PLATFORM)
