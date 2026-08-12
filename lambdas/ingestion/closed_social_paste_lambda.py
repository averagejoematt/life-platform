"""closed_social_paste_lambda.py — closed-platform inbound capture by PASTE (#1677, epic #1668).

The manual-paste fallback for X, Instagram and TikTok. It is **not a second pipeline**:
it is a different ``fetch_day`` source. Everything downstream of ``fetch_day`` — the
SIMP-2 ``run_ingestion()`` runner, the ``#{post_id}``-suffixed write, the S2 provenance
membrane, the S5 sensitivity gate, the RAW_TIMESERIES classification — is the same code
a Bluesky or YouTube post travels through (``bluesky_lambda.py``, #1676).

    owner pastes  ->  social_paste_inbox.stage_paste()   [PASTE#{date}#{post_id} row]
                  ->  fetch_day()                        [reads the staged rows]
                  ->  run_ingestion()                    [the framework, unchanged]
                  ->  transform()                        [origin + channel stamped]
                  ->  DATE#{date}#{post_id}              [the ingested record]

**No token, by decision (owner, 2026-08-12).** X's paid API tier and the Instagram /
TikTok Graph tokens are not being provisioned — that is Matthew's money, his accounts
and app review. This module therefore reads NO secret, holds NO client and makes NO
platform HTTP call; ``authenticate()`` is a documented no-op. That is the point of the
issue's design: the capability works *before* any token exists. Acceptance boxes 1 and 3
of #1677 (token-backed polling) remain deliberately unbuilt.

Not on a schedule and not in CDK: there is nothing to poll. The entry points are
``ingest_pasted_day()`` (used by ``scripts/paste_social_post.py --ingest``, which runs
the identical framework path from the owner's laptop) and ``lambda_handler`` for the day
a scheduled or event-driven invoke earns its place.

v1.0.0 — 2026-08-12 (#1677, epic #1668)
"""

import os

from privacy import (
    broadcast_sensitivity_gate as gate,  # #1673: the fail-closed auto-publish sensitivity gate
    social_provenance as prov,  # #1670: the membrane
)

from ingestion import social_paste_inbox as inbox
from ingestion.ingestion_framework import IngestionConfig, run_ingestion

try:
    from common.platform_logger import get_logger

    logger = get_logger("closed-social-paste")
except ImportError:  # pragma: no cover — layer-module fallback (local tooling)
    import logging

    logger = logging.getLogger("closed-social-paste")

import boto3

# ── Per-channel config ─────────────────────────────────────────────────────────
# No `s3_archive_prefix`, and `enable_raw_archive=False`: nothing is FETCHED here, so
# there is no API response to archive. What a raw archive would hold — the exact strings
# the owner pasted — is already stored durably as the `PASTE#` staging row in the same
# table, so an S3 copy would be a duplicate under a raw/ prefix nothing else writes.
# The registry's `raw_layout: None` for these three says the same thing, and the day a
# token-backed fetch lands (box 1 of #1677) is the day both should change together,
# alongside the role_policies grant that lets a real Lambda write it.
_LOOKBACK = int(os.environ.get("LOOKBACK_DAYS", "7"))


def _config(source):
    return IngestionConfig(
        source_name=source,
        secret_id=None,  # NO secret: there is no token for these platforms, by decision
        schema_version=1,
        enable_raw_archive=False,  # nothing fetched -> nothing to archive (see above)
        # A paste can arrive days after the post — gap-fill the trailing week so a
        # back-dated paste still lands on its own day.
        enable_gap_detection=True,
        lookback_days=_LOOKBACK,
    )


CONFIGS = {channel: _config(channel) for channel in inbox.PASTE_ONLY_CHANNELS}


# ── Source callbacks ───────────────────────────────────────────────────────────


def authenticate(secret_data):
    """No-op. There is no credential for a paste — and deliberately no path to one.

    Kept as an explicit function (rather than an omitted callback) so the absence is
    legible: a reader looking for the X token finds this docstring instead of a TODO.
    """
    return {}


def _table():
    """The DDB table holding both the staged PASTE# rows and the ingested DATE# rows.

    Returns None when a client can't be built (offline/tests) — overridable in tests.
    """
    try:
        return boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-west-2")).Table(
            os.environ.get("TABLE_NAME", "life-platform")
        )
    except Exception:  # noqa: BLE001
        return None


def make_fetch_day(channel):
    """Build the framework's ``fetch_day`` for one channel — reading the paste inbox.

    This is the ONE place the closed platforms differ from the open ones: where Bluesky
    calls an AppView endpoint, this queries the staged pastes for the day. Same return
    shape, so the framework and the transform below cannot tell the difference.
    """

    def fetch_day(creds, date_str):
        table = _table()
        if table is None:
            logger.info(f"{channel}: no DDB table available — nothing to ingest")
            return None
        entries = inbox.staged_entries(table, channel, date_str)
        if not entries:
            return None
        return {"date": date_str, "channel": channel, "entries": entries}

    return fetch_day


def _origin_for(channel, entry, table):
    """#1670 membrane: stamp origin (human|platform) via the ledger + self-backlink.

    A pasted post is *usually* ``origin: human`` — that is the whole reason the fallback
    exists — but "pasted" is not itself proof of human authorship: the owner can paste a
    post the platform syndicated on his behalf (#1402), and that echo must still be
    caught. So the paste path runs the SAME classifier as every fetched source rather
    than hard-coding the answer.
    """
    return prov.classify_post_origin(
        table,
        channel=channel,
        post_id=entry["post_id"],
        text_fields=[entry.get("text"), entry.get("embed_url"), entry.get("url")],
    )


def _sensitivity_for(entry):
    """#1673 gate: stamp the fail-closed auto-publish verdict on an origin:human post."""
    text = entry.get("text") or ""
    try:
        return gate.classify_and_stamp(text, offtopic_classifier=gate.bedrock_offtopic_classifier)
    except Exception as e:  # noqa: BLE001 — never let the gate break ingestion; hold on error
        logger.warning(f"sensitivity gate errored for {entry.get('post_id')}: {e}")
        return {gate.STATUS_ATTR: gate.SENSITIVITY_HELD, gate.REASON_ATTR: f"gate error: {e}"}


def make_transform(channel):
    """Build the framework's ``transform`` for one channel.

    Mirrors ``bluesky_lambda.transform`` field for field — ``sk_suffix=#{post_id}``,
    ``channel`` + ``origin`` provenance (#1670), the #1673 sensitivity verdict on human
    posts, and the channel-agnostic ``title``/``description``/``thumbnail_url`` trio the
    broadcast card reads (#2221) — plus ``capture: 'paste'``, the one honest difference:
    a reader of the stored row can tell how it arrived.
    """

    def transform(raw, date_str):
        records = []
        table = _table()  # one handle for the whole day-batch
        for entry in raw.get("entries", []):
            origin = _origin_for(channel, entry, table)
            text = entry.get("text", "")
            record = {
                "source": channel,
                "sk_suffix": f"#{entry['post_id']}",
                "channel": channel,
                "origin": origin,
                "capture": inbox.CAPTURE_PASTE,
                "post_id": entry["post_id"],
                "post_type": "post",
                "date": date_str,
                "url": entry.get("url", ""),
                "text": text,
                "embed_url": entry.get("embed_url", ""),
                "title": text.split("\n", 1)[0][:120],
                "description": text,
                # Declared and EMPTY on purpose: a paste carries no image URL, and the
                # front-end puts thumbnail_url straight into <img src> (#2221).
                "thumbnail_url": "",
                "published_at": entry.get("published", ""),
                "author": entry.get("author", ""),
            }
            if origin == prov.ORIGIN_HUMAN:
                record.update(_sensitivity_for(entry))
            # No engagement counts: likes/views are not pasted. If a token-backed poll
            # ever adds them (box 1 of #1677) they must be cast to Decimal here.
            records.append({k: v for k, v in record.items() if v != ""})
        return records

    return transform


# ── Entry points ───────────────────────────────────────────────────────────────


def ingest_pasted_day(channel, event=None, context=None):
    """Run the FULL framework ingestion for one channel over the staged pastes.

    Called by the Lambda handler and by ``scripts/paste_social_post.py --ingest``; both
    routes execute the identical ``run_ingestion()`` path, which is the acceptance the
    issue asks for (a pasted post lands the same way a fetched one does).
    """
    if channel not in inbox.PASTE_ONLY_CHANNELS:
        raise ValueError(f"{channel!r} is not a paste-only closed platform (expected one of {list(inbox.PASTE_ONLY_CHANNELS)})")
    return run_ingestion(
        CONFIGS[channel],
        authenticate,
        make_fetch_day(channel),
        make_transform(channel),
        event or {},
        context,
    )


def lambda_handler(event: dict, context) -> dict:
    if isinstance(event, dict) and event.get("healthcheck"):
        return {"statusCode": 200, "body": "ok"}
    channel = (event or {}).get("channel") or os.environ.get("PASTE_CHANNEL", "")
    try:
        return ingest_pasted_day(channel, event, context)
    except Exception as e:
        logger.error("lambda_handler failed: %s", e, exc_info=True)
        raise
