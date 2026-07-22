"""youtube_lambda.py — inbound social ingestion: YouTube (#1669, epic #1668).

The REFERENCE implementation of the inbound social spine. Rides the existing SIMP-2
ingestion framework (``run_ingestion``) exactly like the other pull sources — a source
is four coordinated edits (source_registry entry, this Lambda's authenticate/fetch_day/
transform, the CDK block + secret + IAM, and a phase_taxonomy class). S2–S11 (Bluesky,
Mastodon, X, Instagram, …) extend this instead of inventing a second pipeline.

Auth: YouTube's FREE, keyless per-channel RSS feed —
``https://www.youtube.com/feeds/videos.xml?channel_id=<CHANNEL_ID>`` — pulled via the
``urllib`` stdlib (repo rule: no requests/httpx). No API key or OAuth. The YouTube Data
API is a documented future upgrade (statistics, longer history), NOT v1.

Owner input (STILL REQUIRED): the channel id. Read from the ``life-platform/youtube``
secret (key ``channel_id``) or the ``YOUTUBE_CHANNEL_ID`` env var. Until the owner
provisions it, the Lambda boots and no-ops cleanly (fetch returns nothing) — it does NOT
guess a channel id. See ``_PLACEHOLDER_CHANNEL_ID`` below.

Write shape (framework-built): pk=``USER#matthew#SOURCE#youtube``,
sk=``DATE#{date}#{video_id}`` (the ``#{video_id}`` suffix makes many-videos-per-day
addressable). Every record is stamped with ``channel`` and ``origin`` provenance from
day one (#1670) — the fields the membrane, S3 enrichment, and the S4 feed key on.

v1.0.0 — 2026-07-21 (#1669)
"""

import json
import os
import urllib.request
import xml.etree.ElementTree as ET
from decimal import Decimal

import boto3
from ingestion_framework import IngestionConfig, run_ingestion
from pacific_time import pacific_date_of

try:
    from platform_logger import get_logger

    logger = get_logger("youtube-ingestion")
except ImportError:  # pragma: no cover — layer-module fallback (local tooling)
    import logging

    logger = logging.getLogger("youtube-ingestion")

try:
    from http_retry import urlopen_with_retry
except ImportError:  # pragma: no cover — layer-module fallback
    urlopen_with_retry = urllib.request.urlopen

import broadcast_sensitivity_gate as gate  # #1673: the fail-closed auto-publish sensitivity gate
import social_provenance as prov  # #1670: the membrane

# ── Config ───────────────────────────────────────────────────────────────────────
SOURCE = "youtube"
CHANNEL = "youtube"  # the `channel` provenance stamp (the platform this post came from)
SECRET_ID = "life-platform/youtube"  # referenced, NOT created — owner provisions it
# A clearly-marked sentinel. NEVER a guessed real channel id — the owner must supply one.
_PLACEHOLDER_CHANNEL_ID = "UC__OWNER_MUST_SUPPLY__"
_RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

# Atom + YouTube + Media RSS namespaces (the YouTube feed is Atom with yt:/media: extensions).
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}

_MAX_DESC_CHARS = 2000  # keep DDB items small; full text is in the raw S3 archive

config = IngestionConfig(
    source_name=SOURCE,
    secret_id=None,  # keyless RSS — the channel id is read best-effort in authenticate()
    s3_archive_prefix="raw/matthew/youtube",
    schema_version=1,
    # A channel posts sporadically; gap-fill the trailing week so a missed cron self-heals.
    enable_gap_detection=True,
    lookback_days=int(os.environ.get("LOOKBACK_DAYS", "7")),
)

# Per-invocation feed cache so the gap-fill loop (many dates) fetches the RSS once.
_feed_cache: dict = {}

# Lazy S3 client for per-post raw archival (suffixed layout — see raw_layout facet).
_s3 = None
_S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")


def _resolve_channel_id(secret_data: dict) -> str:
    """Owner input: channel id from the secret, then env, then the placeholder sentinel."""
    cid = (secret_data or {}).get("channel_id") or os.environ.get("YOUTUBE_CHANNEL_ID")
    return cid or _PLACEHOLDER_CHANNEL_ID


# ── Source callbacks ───────────────────────────────────────────────────────────────


def authenticate(secret_data):
    """No-op auth for keyless RSS; best-effort reads the owner-supplied channel id.

    The framework is configured secret_id=None (RSS needs no token), so it hands us an
    empty dict. We still try the ``life-platform/youtube`` secret here for the channel id
    — best-effort, so a not-yet-provisioned secret leaves us on the placeholder and the
    Lambda no-ops instead of erroring.
    """
    channel_id = _resolve_channel_id(secret_data)
    if channel_id == _PLACEHOLDER_CHANNEL_ID:
        try:
            client = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-west-2"))
            try:
                from secret_cache import get_secret_json

                secret = get_secret_json(SECRET_ID, client)
            except ImportError:
                secret = json.loads(client.get_secret_value(SecretId=SECRET_ID)["SecretString"])
            channel_id = _resolve_channel_id(secret)
        except Exception as e:  # noqa: BLE001 — secret absent/unprovisioned is expected pre-launch
            logger.info(f"youtube channel id not resolvable from secret (owner input pending): {e}")
    return {"channel_id": channel_id}


def _fetch_feed(channel_id: str) -> str:
    """Fetch the channel RSS once per invocation (cached across the gap-fill date loop)."""
    if channel_id in _feed_cache:
        return _feed_cache[channel_id]
    url = _RSS_URL.format(channel_id=channel_id)
    req = urllib.request.Request(url, headers={"User-Agent": "life-platform/1.0"})
    with urlopen_with_retry(req, timeout=15) as resp:
        body = resp.read().decode("utf-8")
    _feed_cache[channel_id] = body
    return body


def _parse_entries(feed_xml: str) -> list:
    """Parse the Atom feed into flat per-video dicts (published/title/url/thumbnail/...)."""
    entries = []
    root = ET.fromstring(feed_xml)
    for e in root.findall("atom:entry", _NS):
        video_id = e.findtext("yt:videoId", default="", namespaces=_NS)
        if not video_id:
            continue
        link_el = e.find("atom:link[@rel='alternate']", _NS)
        url = (link_el.get("href") if link_el is not None else "") or f"https://www.youtube.com/watch?v={video_id}"
        group = e.find("media:group", _NS)
        description = ""
        thumbnail_url = ""
        views = None
        if group is not None:
            description = (group.findtext("media:description", default="", namespaces=_NS) or "")[:_MAX_DESC_CHARS]
            thumb = group.find("media:thumbnail", _NS)
            if thumb is not None:
                thumbnail_url = thumb.get("url", "")
            stats = group.find("media:community/media:statistics", _NS)
            if stats is not None and stats.get("views"):
                try:
                    views = int(stats.get("views"))
                except (TypeError, ValueError):
                    views = None
        entries.append(
            {
                "video_id": video_id,
                "title": e.findtext("atom:title", default="", namespaces=_NS),
                "url": url,
                "published": e.findtext("atom:published", default="", namespaces=_NS),
                "updated": e.findtext("atom:updated", default="", namespaces=_NS),
                "author": e.findtext("atom:author/atom:name", default="", namespaces=_NS),
                "description": description,
                "thumbnail_url": thumbnail_url,
                "views": views,
            }
        )
    return entries


def fetch_day(creds, date_str):
    """Return the channel's videos published on ``date_str`` (Pacific calendar day).

    RSS carries all recent videos at once; we fetch the feed (cached) and filter to the
    requested day. Returns None when the owner has not provisioned a channel id, so the
    Lambda no-ops cleanly instead of hitting a bogus URL.
    """
    channel_id = (creds or {}).get("channel_id") or _PLACEHOLDER_CHANNEL_ID
    if channel_id == _PLACEHOLDER_CHANNEL_ID:
        logger.info("youtube channel id not provisioned — skipping fetch (owner input pending)")
        return None
    feed_xml = _fetch_feed(channel_id)
    entries = _parse_entries(feed_xml)
    day_entries = [en for en in entries if pacific_date_of(en.get("published")) == date_str]
    if not day_entries:
        return None
    return {"date": date_str, "channel_id": channel_id, "entries": day_entries}


def _archive_post_raw(entry: dict, date_str: str) -> None:
    """Suffixed per-post raw archive (raw/matthew/youtube/YYYY/MM/DD-<video_id>.json).

    Matches the notion many-items-per-day precedent so the raw_layout facet is honest and
    addressable per post. Best-effort — never blocks the DDB write. (The framework ALSO
    writes a per-day feed snapshot; this is the canonical per-post copy.)
    """
    global _s3
    if not _S3_BUCKET:
        return
    try:
        if _s3 is None:
            _s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-2"))
        year, month, day = date_str[:4], date_str[5:7], date_str[8:10]
        key = f"raw/matthew/youtube/{year}/{month}/{day}-{entry['video_id']}.json"
        _s3.put_object(
            Bucket=_S3_BUCKET,
            Key=key,
            Body=json.dumps({"date": date_str, "raw_entry": entry}, default=str),
            ContentType="application/json",
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"youtube per-post raw archive failed for {entry.get('video_id')}: {e}")


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

    The classifier is fail-open (a ledger lookup error → not-in-ledger); the self-backlink
    signal (a post that links back to averagejoematt.com) catches an echo even with an
    empty ledger.
    """
    return prov.classify_post_origin(
        _ledger_table(),
        channel=CHANNEL,
        post_id=entry["video_id"],
        text_fields=[entry.get("title"), entry.get("description"), entry.get("url")],
    )


def _sensitivity_for(entry: dict) -> dict:
    """#1673 gate: stamp the fail-closed auto-publish verdict on an origin:human post.

    Runs the sensitivity classifier over the post's title + description and returns the
    ``sensitivity_status``/``sensitivity_reason``/``sensitivity_categories`` attributes the
    S4 feed (#1672) filters on. The off-topic layer routes through Bedrock (budget-gated,
    fail-closed); ANY failure resolves to HELD, never auto-publish. Only ``origin:human``
    posts are gated — a platform echo is already excluded by the #1670 membrane and never
    reaches the feed. Fail-closed if classification itself throws.
    """
    text = " ".join(t for t in (entry.get("title"), entry.get("description")) if t)
    try:
        return gate.classify_and_stamp(text, offtopic_classifier=gate.bedrock_offtopic_classifier)
    except Exception as e:  # noqa: BLE001 — never let the gate break ingestion; hold on error
        logger.warning(f"sensitivity gate errored for {entry.get('video_id')}: {e}")
        return {gate.STATUS_ATTR: gate.SENSITIVITY_HELD, gate.REASON_ATTR: f"gate error: {e}"}


def transform(raw, date_str):
    """Map the day's parsed videos to framework DDB records (one per video).

    Each record sets ``sk_suffix=#{video_id}`` → sk=``DATE#{date}#{video_id}``, stamps
    ``channel`` + ``origin`` provenance (#1670), and — for human-origin posts — the #1673
    ``sensitivity_status`` auto-publish verdict. ``source``/``sk_suffix`` are consumed by
    the framework; everything else persists.
    """
    records = []
    for entry in raw.get("entries", []):
        _archive_post_raw(entry, date_str)
        origin = _origin_for(entry)
        record = {
            "source": SOURCE,
            "sk_suffix": f"#{entry['video_id']}",
            "channel": CHANNEL,
            "origin": origin,
            "post_id": entry["video_id"],
            "post_type": "video",
            "date": date_str,
            "title": entry.get("title", ""),
            "url": entry.get("url", ""),
            "thumbnail_url": entry.get("thumbnail_url", ""),
            "description": entry.get("description", ""),
            "published_at": entry.get("published", ""),
            "author": entry.get("author", ""),
        }
        # #1673: classify origin:human posts before they can appear in the S4 feed. A
        # platform echo (#1670) is never displayed, so it needs no sensitivity verdict.
        if origin == prov.ORIGIN_HUMAN:
            record.update(_sensitivity_for(entry))
        if entry.get("views") is not None:
            record["views"] = Decimal(str(entry["views"]))  # Decimal before DDB
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
