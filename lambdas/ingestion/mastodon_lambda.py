"""mastodon_lambda.py — inbound social ingestion: Mastodon (#1676, epic #1668).

S2 of the inbound social spine, extending the `youtube_lambda.py` reference
implementation (#1669) to a second open platform (alongside `bluesky_lambda.py`). Same
shape: one `SOURCE_REGISTRY` entry (facets only), one Lambda supplying
`authenticate/fetch_day/transform` to the SIMP-2 `run_ingestion()` framework, one CDK
block + secret + IAM policy, one `phase_taxonomy` classification. No second pipeline.

Auth: every Mastodon instance's FREE, public REST API — public statuses are readable
with no auth header at all. Pulled via the ``urllib`` stdlib (repo rule: no
requests/httpx). Two calls per fetch: an account lookup (username -> numeric account id,
cached) then the account's public statuses.

Owner input (STILL REQUIRED): the home instance domain + the account username (e.g.
instance ``mastodon.social``, handle ``mattsusername``). Read from the
``life-platform/mastodon`` secret (keys ``instance``/``handle``) or the
``MASTODON_INSTANCE``/``MASTODON_HANDLE`` env vars. Until the owner provisions them, the
Lambda boots and no-ops cleanly (fetch returns nothing) — it does NOT guess an instance
or handle. See ``_PLACEHOLDER_INSTANCE``/``_PLACEHOLDER_HANDLE`` below.

Write shape (framework-built): pk=``USER#matthew#SOURCE#mastodon``,
sk=``DATE#{date}#{post_id}`` (the ``#{post_id}`` suffix makes many-posts-per-day
addressable). Every record is stamped with ``channel`` and ``origin`` provenance from
day one (#1670) — the fields the membrane, S3 enrichment, and the S4 feed key on.

v1.0.0 — 2026-08-05 (#1676, epic #1668)
"""

import json
import os
import re
import urllib.parse
import urllib.request
from decimal import Decimal
from typing import Any

import boto3
from common.pacific_time import pacific_date_of

from ingestion.ingestion_framework import IngestionConfig, run_ingestion

try:
    from common.platform_logger import get_logger

    logger = get_logger("mastodon-ingestion")
except ImportError:  # pragma: no cover — layer-module fallback (local tooling)
    import logging

    logger = logging.getLogger("mastodon-ingestion")

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
SOURCE = "mastodon"
CHANNEL = "mastodon"  # the `channel` provenance stamp (the platform this post came from)
SECRET_ID = "life-platform/mastodon"  # referenced, NOT created — owner provisions it
# Clearly-marked sentinels. NEVER a guessed real instance/handle — the owner must supply them.
_PLACEHOLDER_INSTANCE = "__OWNER_MUST_SUPPLY__"
_PLACEHOLDER_HANDLE = "__OWNER_MUST_SUPPLY__"
_MAX_TEXT_CHARS = 2000  # keep DDB items small; full text is in the raw S3 archive
_STATUSES_LIMIT = 40
_HTML_TAG_RE = re.compile(r"<[^>]+>")

config = IngestionConfig(
    source_name=SOURCE,
    secret_id=None,  # keyless public API — instance/handle are read best-effort in authenticate()
    s3_archive_prefix="raw/matthew/mastodon",
    schema_version=1,
    # Posting is sporadic; gap-fill the trailing week so a missed cron self-heals.
    enable_gap_detection=True,
    lookback_days=int(os.environ.get("LOOKBACK_DAYS", "7")),
)

# Per-invocation cache so the gap-fill loop (many dates) resolves the account + fetches
# statuses once. Keyed by (instance, handle).
_account_id_cache: dict = {}
_statuses_cache: dict = {}

# Lazy S3 client for per-post raw archival (suffixed layout — see raw_layout facet).
_s3 = None
_S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")


def _resolve_instance_handle(secret_data: dict) -> tuple:
    """Owner input: instance + handle from the secret, then env, then placeholder sentinels."""
    secret_data = secret_data or {}
    instance = secret_data.get("instance") or os.environ.get("MASTODON_INSTANCE") or _PLACEHOLDER_INSTANCE
    handle = secret_data.get("handle") or os.environ.get("MASTODON_HANDLE") or _PLACEHOLDER_HANDLE
    return instance, handle


# ── Source callbacks ───────────────────────────────────────────────────────────────


def authenticate(secret_data):
    """No-op auth for the keyless public API; best-effort reads the owner-supplied instance/handle.

    The framework is configured secret_id=None (public statuses need no token), so it
    hands us an empty dict. We still try the ``life-platform/mastodon`` secret here —
    best-effort, so a not-yet-provisioned secret leaves us on the placeholders and the
    Lambda no-ops instead of erroring.
    """
    instance, handle = _resolve_instance_handle(secret_data)
    if instance == _PLACEHOLDER_INSTANCE or handle == _PLACEHOLDER_HANDLE:
        try:
            client = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-west-2"))
            try:
                from common.secret_cache import get_secret_json

                secret = get_secret_json(SECRET_ID, client)
            except ImportError:
                secret = json.loads(client.get_secret_value(SecretId=SECRET_ID)["SecretString"])
            instance, handle = _resolve_instance_handle(secret)
        except Exception as e:  # noqa: BLE001 — secret absent/unprovisioned is expected pre-launch
            logger.info(f"mastodon instance/handle not resolvable from secret (owner input pending): {e}")
    return {"instance": instance, "handle": handle}


def _get_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "life-platform/1.0", "Accept": "application/json"})
    with urlopen_with_retry(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _resolve_account_id(instance: str, handle: str) -> str:
    """Resolve a username to the instance's numeric account id (cached per invocation)."""
    cache_key = (instance, handle)
    if cache_key in _account_id_cache:
        return _account_id_cache[cache_key]
    qs = urllib.parse.urlencode({"acct": handle})
    url = f"https://{instance}/api/v1/accounts/lookup?{qs}"
    account = _get_json(url)
    account_id = account.get("id", "")
    _account_id_cache[cache_key] = account_id
    return account_id


def _fetch_statuses(instance: str, handle: str) -> list:
    """Fetch the account's recent public statuses once per invocation (cached).

    Excludes replies and boosts (``exclude_replies``/``exclude_reblogs``) — the feed is
    Matthew's own original public voice, mirroring the youtube/bluesky reference sources.
    """
    cache_key = (instance, handle)
    if cache_key in _statuses_cache:
        return _statuses_cache[cache_key]
    account_id = _resolve_account_id(instance, handle)
    if not account_id:
        _statuses_cache[cache_key] = []
        return []
    qs = urllib.parse.urlencode({"exclude_replies": "true", "exclude_reblogs": "true", "limit": _STATUSES_LIMIT})
    url = f"https://{instance}/api/v1/accounts/{account_id}/statuses?{qs}"
    statuses = _get_json(url)
    if not isinstance(statuses, list):
        statuses = []
    _statuses_cache[cache_key] = statuses
    return statuses


def _strip_html(html: str) -> str:
    """Mastodon status content is HTML (``<p>...</p>``) — strip tags for the plain-text field."""
    return _HTML_TAG_RE.sub(" ", html or "").replace("&amp;", "&").replace("&#39;", "'").strip()


def _parse_entries(statuses: list) -> list:
    """Parse the account's statuses into flat per-post dicts (published/text/url/...).

    Non-public statuses (unlisted/private/direct) are dropped — this source ingests only
    what's already public, per the issue's privacy constraint. The raw HTML ``content`` is
    kept alongside the stripped text so self-backlink detection (#1670) can also catch a
    link buried in an ``<a href>`` the plain-text strip would otherwise lose.
    """
    entries = []
    for status in statuses:
        if status.get("visibility") != "public":
            continue
        if status.get("reblog"):  # a boost, not an original post
            continue
        post_id = str(status.get("id", ""))
        if not post_id:
            continue
        raw_content = status.get("content", "")
        entries.append(
            {
                "post_id": post_id,
                "text": _strip_html(raw_content)[:_MAX_TEXT_CHARS],
                "raw_content": raw_content[:_MAX_TEXT_CHARS],
                "url": status.get("url", ""),
                "published": status.get("created_at", ""),
                "author": (status.get("account") or {}).get("username", ""),
                "favourites_count": status.get("favourites_count"),
                "reblogs_count": status.get("reblogs_count"),
            }
        )
    return entries


def fetch_day(creds, date_str):
    """Return the account's public statuses published on ``date_str`` (Pacific calendar day).

    The API returns the recent statuses at once; we fetch them (cached) and filter to the
    requested day. Returns None when the owner has not provisioned an instance/handle, so
    the Lambda no-ops cleanly instead of hitting a bogus request.
    """
    instance = (creds or {}).get("instance") or _PLACEHOLDER_INSTANCE
    handle = (creds or {}).get("handle") or _PLACEHOLDER_HANDLE
    if instance == _PLACEHOLDER_INSTANCE or handle == _PLACEHOLDER_HANDLE:
        logger.info("mastodon instance/handle not provisioned — skipping fetch (owner input pending)")
        return None
    statuses = _fetch_statuses(instance, handle)
    entries = _parse_entries(statuses)
    day_entries = [en for en in entries if pacific_date_of(en.get("published")) == date_str]
    if not day_entries:
        return None
    return {"date": date_str, "instance": instance, "handle": handle, "entries": day_entries}


def _archive_post_raw(entry: dict, date_str: str) -> None:
    """Suffixed per-post raw archive (raw/matthew/mastodon/YYYY/MM/DD-<post_id>.json).

    Matches the youtube/bluesky per-post precedent so the raw_layout facet is honest and
    addressable per post. Best-effort — never blocks the DDB write.
    """
    global _s3
    if not _S3_BUCKET:
        return
    try:
        if _s3 is None:
            _s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-2"))
        year, month, day = date_str[:4], date_str[5:7], date_str[8:10]
        key = f"raw/matthew/mastodon/{year}/{month}/{day}-{entry['post_id']}.json"
        _s3.put_object(
            Bucket=_S3_BUCKET,
            Key=key,
            Body=json.dumps({"date": date_str, "raw_entry": entry}, default=str),
            ContentType="application/json",
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"mastodon per-post raw archive failed for {entry.get('post_id')}: {e}")


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
    that links back to averagejoematt.com, checked against BOTH the stripped text and the
    raw HTML so an ``<a href>``-only link is still caught) catches an echo even with an
    empty ledger.
    """
    return prov.classify_post_origin(
        _ledger_table(),
        channel=CHANNEL,
        post_id=entry["post_id"],
        text_fields=[entry.get("text"), entry.get("raw_content"), entry.get("url")],
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
    """Map the day's parsed statuses to framework DDB records (one per post).

    Each record sets ``sk_suffix=#{post_id}`` → sk=``DATE#{date}#{post_id}``, stamps
    ``channel`` + ``origin`` provenance (#1670), the ``diary_*`` publication provenance
    when the post is a published diary cut (#1845), and — for human-origin posts — the
    #1673 ``sensitivity_status`` auto-publish verdict. ``source``/``sk_suffix`` are
    consumed by the framework; everything else persists. The raw HTML ``raw_content`` is
    NOT persisted to DDB (only used for self-backlink detection) — the stripped ``text``
    is what downstream surfaces read.
    """
    records = []
    diary_table = _ledger_table()  # one handle for the whole day-batch
    for entry in raw.get("entries", []):
        _archive_post_raw(entry, date_str)
        origin = _origin_for(entry)
        text = entry.get("text", "")
        record = {
            "source": SOURCE,
            "sk_suffix": f"#{entry['post_id']}",
            "channel": CHANNEL,
            "origin": origin,
            "post_id": entry["post_id"],
            "post_type": "post",
            "date": date_str,
            "url": entry.get("url", ""),
            "text": text,
            # #2221 — the broadcast card (`web/site_api_social._broadcast_card`) is
            # channel-agnostic: it reads `title`/`description`/`thumbnail_url` off EVERY
            # ingested-post row. A microblog post has no title, so the transform
            # normalises here rather than teaching the reader three shapes: the caption
            # is the post's own first line, the excerpt is its body. `thumbnail_url` is
            # declared and left EMPTY on purpose — the API's status payload carries no thumbnail this transform persists — and the front-end
            # (site/assets/js/dispatches.js) puts thumbnail_url straight into <img src>.
            "title": text.split("\n", 1)[0][:120],
            "description": text,
            "thumbnail_url": "",
            "published_at": entry.get("published", ""),
            "author": entry.get("author", ""),
        }
        record.update(_diary_stamp(entry, diary_table))
        if origin == prov.ORIGIN_HUMAN:
            record.update(_sensitivity_for(entry))
        if entry.get("favourites_count") is not None:
            record["favourites_count"] = Decimal(str(entry["favourites_count"]))  # Decimal before DDB
        if entry.get("reblogs_count") is not None:
            record["reblogs_count"] = Decimal(str(entry["reblogs_count"]))
        # Drop empty strings to keep items lean.
        records.append({k: v for k, v in record.items() if v != ""})
    return records


# ── Lambda entry point ─────────────────────────────────────────────────────────────


def lambda_handler(event: dict, context) -> dict:
    if isinstance(event, dict) and event.get("healthcheck"):
        return {"statusCode": 200, "body": "ok"}
    try:
        return run_ingestion(config, authenticate, fetch_day, transform, event, context)
    except Exception as e:
        logger.error("lambda_handler failed: %s", e, exc_info=True)
        raise
