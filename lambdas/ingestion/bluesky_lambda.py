"""bluesky_lambda.py — inbound social ingestion: Bluesky (#1676, epic #1668).

S2 of the inbound social spine, extending the `youtube_lambda.py` reference
implementation (#1669) to a second open platform. Same shape: one
`SOURCE_REGISTRY` entry (facets only), one Lambda supplying
`authenticate/fetch_day/transform` to the SIMP-2 `run_ingestion()` framework, one CDK
block + secret + IAM policy, one `phase_taxonomy` classification. No second pipeline.

Auth: Bluesky's FREE, public, unauthenticated AppView endpoint —
``https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed`` — pulled via the
``urllib`` stdlib (repo rule: no requests/httpx). No API key or OAuth; the AppView
serves anyone's public feed by handle with no auth header at all.

Owner input (STILL REQUIRED): the Bluesky handle (e.g. ``mattsusername.bsky.social``).
Read from the ``life-platform/bluesky`` secret (key ``handle``) or the
``BLUESKY_HANDLE`` env var. Until the owner provisions it, the Lambda boots and
no-ops cleanly (fetch returns nothing) — it does NOT guess a handle. See
``_PLACEHOLDER_HANDLE`` below.

Write shape (framework-built): pk=``USER#matthew#SOURCE#bluesky``,
sk=``DATE#{date}#{post_id}`` (the ``#{post_id}`` suffix makes many-posts-per-day
addressable). Every record is stamped with ``channel`` and ``origin`` provenance from
day one (#1670) — the fields the membrane, S3 enrichment, and the S4 feed key on.

v1.0.0 — 2026-08-05 (#1676, epic #1668)
"""

import json
import os
import urllib.parse
import urllib.request
from decimal import Decimal

import boto3
from common.pacific_time import pacific_date_of

from ingestion.ingestion_framework import IngestionConfig, run_ingestion

try:
    from common.platform_logger import get_logger

    logger = get_logger("bluesky-ingestion")
except ImportError:  # pragma: no cover — layer-module fallback (local tooling)
    import logging

    logger = logging.getLogger("bluesky-ingestion")

try:
    from common.http_retry import urlopen_with_retry
except ImportError:  # pragma: no cover — layer-module fallback
    urlopen_with_retry = urllib.request.urlopen

from privacy import (
    broadcast_sensitivity_gate as gate,  # #1673: the fail-closed auto-publish sensitivity gate
    diary_publish,  # #1845: the cut->entry->engagement join
    social_provenance as prov,  # #1670: the membrane
)

# ── Config ───────────────────────────────────────────────────────────────────────
SOURCE = "bluesky"
CHANNEL = "bluesky"  # the `channel` provenance stamp (the platform this post came from)
SECRET_ID = "life-platform/bluesky"  # referenced, NOT created — owner provisions it
# A clearly-marked sentinel. NEVER a guessed real handle — the owner must supply one.
_PLACEHOLDER_HANDLE = "__OWNER_MUST_SUPPLY__.bsky.social"
# Public, keyless AppView endpoint — serves ANY account's public feed with no auth.
_FEED_URL = "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed?{qs}"
_MAX_TEXT_CHARS = 2000  # keep DDB items small; full text is in the raw S3 archive
_FEED_LIMIT = 100

config = IngestionConfig(
    source_name=SOURCE,
    secret_id=None,  # keyless public API — the handle is read best-effort in authenticate()
    s3_archive_prefix="raw/matthew/bluesky",
    schema_version=1,
    # Posting is sporadic; gap-fill the trailing week so a missed cron self-heals.
    enable_gap_detection=True,
    lookback_days=int(os.environ.get("LOOKBACK_DAYS", "7")),
)

# Per-invocation feed cache so the gap-fill loop (many dates) fetches the feed once.
_feed_cache: dict = {}

# Lazy S3 client for per-post raw archival (suffixed layout — see raw_layout facet).
_s3 = None
_S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")


def _resolve_handle(secret_data: dict) -> str:
    """Owner input: Bluesky handle from the secret, then env, then the placeholder sentinel."""
    handle = (secret_data or {}).get("handle") or os.environ.get("BLUESKY_HANDLE")
    return handle or _PLACEHOLDER_HANDLE


# ── Source callbacks ───────────────────────────────────────────────────────────────


def authenticate(secret_data):
    """No-op auth for the keyless public API; best-effort reads the owner-supplied handle.

    The framework is configured secret_id=None (the AppView needs no token), so it hands
    us an empty dict. We still try the ``life-platform/bluesky`` secret here for the
    handle — best-effort, so a not-yet-provisioned secret leaves us on the placeholder and
    the Lambda no-ops instead of erroring.
    """
    handle = _resolve_handle(secret_data)
    if handle == _PLACEHOLDER_HANDLE:
        try:
            client = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-west-2"))
            try:
                from common.secret_cache import get_secret_json

                secret = get_secret_json(SECRET_ID, client)
            except ImportError:
                secret = json.loads(client.get_secret_value(SecretId=SECRET_ID)["SecretString"])
            handle = _resolve_handle(secret)
        except Exception as e:  # noqa: BLE001 — secret absent/unprovisioned is expected pre-launch
            logger.info(f"bluesky handle not resolvable from secret (owner input pending): {e}")
    return {"handle": handle}


def _fetch_feed(handle: str) -> list:
    """Fetch the account's author feed once per invocation (cached across the gap-fill date loop).

    Excludes replies (``posts_no_replies``) — the feed is Matthew's own original public
    voice, mirroring the youtube reference (uploaded videos, not comment replies).
    """
    if handle in _feed_cache:
        return _feed_cache[handle]
    qs = urllib.parse.urlencode({"actor": handle, "limit": _FEED_LIMIT, "filter": "posts_no_replies"})
    url = _FEED_URL.format(qs=qs)
    req = urllib.request.Request(url, headers={"User-Agent": "life-platform/1.0", "Accept": "application/json"})
    with urlopen_with_retry(req, timeout=15) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    items = body.get("feed", [])
    _feed_cache[handle] = items
    return items


def _parse_entries(feed_items: list, handle: str) -> list:
    """Parse the AppView feed into flat per-post dicts (published/text/url/embed_url/...).

    Reposts (``reason`` present, e.g. ``app.bsky.feed.defs#reasonRepost``) are dropped —
    they aren't Matthew's own authored words. A quote-post or a post carrying an external
    embed link is kept; the embed URL feeds self-backlink detection (#1670).
    """
    entries = []
    for item in feed_items:
        if item.get("reason"):  # a repost, not an original post
            continue
        post = item.get("post") or {}
        uri = post.get("uri", "")
        if not uri:
            continue
        post_id = uri.rsplit("/", 1)[-1]
        record = post.get("record") or {}
        text = (record.get("text") or "")[:_MAX_TEXT_CHARS]
        embed_url = ""
        embed = record.get("embed") or {}
        external = embed.get("external") or {}
        if external.get("uri"):
            embed_url = external["uri"]
        author = post.get("author") or {}
        entries.append(
            {
                "post_id": post_id,
                "text": text,
                "url": f"https://bsky.app/profile/{handle}/post/{post_id}",
                "embed_url": embed_url,
                "published": record.get("createdAt", ""),
                "author": author.get("handle", handle),
                "like_count": post.get("likeCount"),
                "repost_count": post.get("repostCount"),
            }
        )
    return entries


def fetch_day(creds, date_str):
    """Return the account's posts published on ``date_str`` (Pacific calendar day).

    The AppView returns the recent feed at once; we fetch it (cached) and filter to the
    requested day. Returns None when the owner has not provisioned a handle, so the
    Lambda no-ops cleanly instead of hitting a bogus request.
    """
    handle = (creds or {}).get("handle") or _PLACEHOLDER_HANDLE
    if handle == _PLACEHOLDER_HANDLE:
        logger.info("bluesky handle not provisioned — skipping fetch (owner input pending)")
        return None
    feed_items = _fetch_feed(handle)
    entries = _parse_entries(feed_items, handle)
    day_entries = [en for en in entries if pacific_date_of(en.get("published")) == date_str]
    if not day_entries:
        return None
    return {"date": date_str, "handle": handle, "entries": day_entries}


def _archive_post_raw(entry: dict, date_str: str) -> None:
    """Suffixed per-post raw archive (raw/matthew/bluesky/YYYY/MM/DD-<post_id>.json).

    Matches the youtube per-post precedent so the raw_layout facet is honest and
    addressable per post. Best-effort — never blocks the DDB write.
    """
    global _s3
    if not _S3_BUCKET:
        return
    try:
        if _s3 is None:
            _s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-2"))
        year, month, day = date_str[:4], date_str[5:7], date_str[8:10]
        key = f"raw/matthew/bluesky/{year}/{month}/{day}-{entry['post_id']}.json"
        _s3.put_object(
            Bucket=_S3_BUCKET,
            Key=key,
            Body=json.dumps({"date": date_str, "raw_entry": entry}, default=str),
            ContentType="application/json",
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"bluesky per-post raw archive failed for {entry.get('post_id')}: {e}")


def _ledger_table():
    """The DDB table the #1670 membrane queries for BROADCAST_ORIGIN# rows (lazy).

    Returns None if a client can't be built (offline/tests) — classification then falls
    back to the self-backlink signal, which needs no AWS. Overridable in tests.
    """
    try:
        return boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-west-2")).Table(
            os.environ.get("TABLE_NAME", "life-platform")
        )
    except Exception:  # noqa: BLE001
        return None


def _origin_for(entry: dict) -> str:
    """#1670 membrane: stamp origin (human|platform) via the ledger + self-backlink.

    Fail-open (a ledger lookup error → not-in-ledger); the self-backlink signal (a post
    that links back to averagejoematt.com) catches an echo even with an empty ledger.
    """
    return prov.classify_post_origin(
        _ledger_table(),
        channel=CHANNEL,
        post_id=entry["post_id"],
        text_fields=[entry.get("text"), entry.get("embed_url"), entry.get("url")],
    )


def _sensitivity_for(entry: dict) -> dict:
    """#1673 gate: stamp the fail-closed auto-publish verdict on an origin:human post.

    Only ``origin:human`` posts are gated — a platform echo is already excluded by the
    #1670 membrane and never reaches the feed. Fail-closed if classification itself throws.
    """
    text = entry.get("text") or ""
    try:
        return gate.classify_and_stamp(text, offtopic_classifier=gate.bedrock_offtopic_classifier)
    except Exception as e:  # noqa: BLE001 — never let the gate break ingestion; hold on error
        logger.warning(f"sensitivity gate errored for {entry.get('post_id')}: {e}")
        return {gate.STATUS_ATTR: gate.SENSITIVITY_HELD, gate.REASON_ATTR: f"gate error: {e}"}


def _diary_stamp(entry: dict, table) -> dict:
    """#1845: stamp diary provenance when this post is a published diary cut.

    Fail-open: a lookup error means "diary origin unknown", never a broken ingest.
    """
    try:
        publication = diary_publish.lookup_publication(table, CHANNEL, entry["post_id"])
        return diary_publish.publication_stamp(publication)
    except Exception as e:  # noqa: BLE001 — provenance is never allowed to break ingestion
        logger.warning(f"diary publication lookup failed for {entry.get('post_id')}: {e}")
        return {}


def transform(raw, date_str):
    """Map the day's parsed posts to framework DDB records (one per post).

    Each record sets ``sk_suffix=#{post_id}`` → sk=``DATE#{date}#{post_id}``, stamps
    ``channel`` + ``origin`` provenance (#1670), the ``diary_*`` publication provenance
    when the post is a published diary cut (#1845), and — for human-origin posts — the
    #1673 ``sensitivity_status`` auto-publish verdict. ``source``/``sk_suffix`` are
    consumed by the framework; everything else persists.
    """
    records = []
    diary_table = _ledger_table()  # one handle for the whole day-batch
    for entry in raw.get("entries", []):
        _archive_post_raw(entry, date_str)
        origin = _origin_for(entry)
        record = {
            "source": SOURCE,
            "sk_suffix": f"#{entry['post_id']}",
            "channel": CHANNEL,
            "origin": origin,
            "post_id": entry["post_id"],
            "post_type": "post",
            "date": date_str,
            "url": entry.get("url", ""),
            "text": entry.get("text", ""),
            "embed_url": entry.get("embed_url", ""),
            "published_at": entry.get("published", ""),
            "author": entry.get("author", ""),
        }
        record.update(_diary_stamp(entry, diary_table))
        if origin == prov.ORIGIN_HUMAN:
            record.update(_sensitivity_for(entry))
        if entry.get("like_count") is not None:
            record["like_count"] = Decimal(str(entry["like_count"]))  # Decimal before DDB
        if entry.get("repost_count") is not None:
            record["repost_count"] = Decimal(str(entry["repost_count"]))
        # Drop empty strings to keep items lean.
        records.append({k: v for k, v in record.items() if v != ""})
    return records


# ── Lambda entry point ─────────────────────────────────────────────────────────────


def lambda_handler(event, context):
    if isinstance(event, dict) and event.get("healthcheck"):
        return {"statusCode": 200, "body": "ok"}
    try:
        return run_ingestion(config, authenticate, fetch_day, transform, event, context)
    except Exception as e:
        logger.error("lambda_handler failed: %s", e, exc_info=True)
        raise
