#!/usr/bin/env python3
"""The Permanence Contract's nightly run (#1400).

One scheduled function, two obligations, in this order:

1. **Measure the silence** (``continuity_watch``) — how many days since the
   platform last heard from a source that only reports when a person acts.
2. **Rebuild the public archive** (``public_archive``) — everything the site
   already publishes, packaged as one download at a fixed address, with a
   manifest carrying a checksum and an honest list of what was left out.

The measurement runs *first* on purpose: at the trigger threshold the archive
is sealed as a dated final edition rather than overwritten, so the state has to
be known before anything is written.

Published artefacts (all under the archive prefix, all world-readable — that is
the point of them):

* ``latest.tar.gz``   — the archive
* ``manifest.json``   — inventory, checksum, exclusions, contract version
* ``continuity.json`` — the clock, the state, and the terms themselves
* ``final-YYYY-MM-DD.tar.gz`` — written once, only if the switch trips

Nothing here writes to DynamoDB: the contract's own state lives in the
published ``continuity.json``, which means the state a reader can see and the
state the switch acts on are the same document. Every write is gated on
``common.dry_run``, so a hand invoke with ``{"dry_run": true}`` builds the whole
archive, reports on it, and touches nothing.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import boto3
from common import dry_run
from common.send_guard import guarded_send_email

from operational import continuity_watch as watch, permanence_terms as terms, public_archive, public_archive_registry as reg

try:
    from common.platform_logger import get_logger

    logger = get_logger("permanence")
except ImportError:  # pragma: no cover - logging fallback only
    logger = logging.getLogger("permanence")
    logger.setLevel(logging.INFO)

TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
REGION = os.environ.get("AWS_REGION", "us-west-2")
EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "awsdev@mattsusername.com")
EMAIL_RECIPIENT = os.environ.get("EMAIL_RECIPIENT", "awsdev@mattsusername.com")
CONTINUITY_CONTACTS_SECRET = os.environ.get("CONTINUITY_CONTACTS_SECRET", "life-platform/continuity-contacts")

EMF_NAMESPACE = "LifePlatform/Permanence"

# Numeric encoding of the contract state, so CloudWatch can alarm on it.
# `unknown` is -1 and deliberately NOT between active and notice: a failed
# measurement must never be mistaken for a healthy one on a graph.
STATE_CODES = {
    watch.STATE_UNKNOWN: -1,
    watch.STATE_ACTIVE: 0,
    watch.STATE_NOTICE: 1,
    watch.STATE_WARNING: 2,
    watch.STATE_TRIGGERED: 3,
}


def _clients():
    return (
        boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME),
        boto3.client("s3", region_name=REGION),
        boto3.client("ses", region_name=REGION),
        boto3.client("secretsmanager", region_name=REGION),
    )


def _read_previous_continuity(s3) -> Optional[dict]:
    try:
        body = s3.get_object(Bucket=S3_BUCKET, Key=reg.ARCHIVE_CONTINUITY_KEY)["Body"].read()
        return json.loads(body)
    except Exception:  # noqa: BLE001 - first run, or a transient read; neither is news
        return None


def _continuity_contacts(secrets) -> list[str]:
    """Continuity contacts, from Secrets Manager only.

    Never from an environment variable or a constant: this repository is
    public, and the people in this list did not sign up to be in it.
    Absence is reported honestly rather than silently — a contract that says
    "the contacts are told" while no contacts exist would be a lie.
    """
    try:
        from common.secret_cache import get_secret_json  # noqa: PLC0415 - optional dependency at import time

        payload = get_secret_json(CONTINUITY_CONTACTS_SECRET, secrets)
    except Exception as exc:  # noqa: BLE001
        logger.warning("continuity contacts unavailable (%s)", type(exc).__name__)
        return []
    raw = payload.get("contacts") if isinstance(payload, dict) else None
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.split(",")]
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def _emf(state: str, days_silent, archive_bytes: int, entry_count: int, api_captured: int, api_declared: int, built: bool = True) -> str:
    """One EMF line.

    ``ArchiveBuilt`` is the heartbeat gauge the alarm counts samples of, so it
    is emitted ONLY when an archive was actually published. A run that declines
    to publish (``built=False``) still reports its diagnostics but leaves the
    heartbeat without a sample — two such days and the alarm fires. Emitting
    ``ArchiveBuilt=0`` would have been worse than useless: SampleCount counts
    datapoints, not values, so a zero would keep the heartbeat green while the
    archive quietly went stale."""
    metrics = [
        {"Name": "ArchiveBytes"},
        {"Name": "ArchiveEntryCount"},
        {"Name": "ApiRoutesCaptured"},
        {"Name": "ApiRoutesMissed"},
        {"Name": "ContinuityState"},
        {"Name": "ContinuityDaysSilent"},
    ]
    if built:
        metrics.insert(0, {"Name": "ArchiveBuilt"})
    doc = {
        "_aws": {
            "Timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": EMF_NAMESPACE,
                    "Dimensions": [[]],
                    "Metrics": metrics,
                }
            ],
        },
        "ArchiveBytes": int(archive_bytes),
        "ArchiveEntryCount": int(entry_count),
        "ApiRoutesCaptured": int(api_captured),
        "ApiRoutesMissed": int(api_declared - api_captured),
        "ContinuityState": STATE_CODES.get(state, -1),
        "ContinuityDaysSilent": int(days_silent) if isinstance(days_silent, int) else -1,
        "state": state,
    }
    if built:
        doc["ArchiveBuilt"] = 1
    return json.dumps(doc)


def _publish(s3, key: str, body: bytes, content_type: str, cache_seconds: int) -> None:
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=body,
        ContentType=content_type,
        CacheControl=f"max-age={cache_seconds}, public",
    )


def _notify(ses, secrets, doc: dict, is_dry: bool) -> dict:
    """Send one continuity transition email. Returns an honest outcome record."""
    contacts = _continuity_contacts(secrets)
    recipients = contacts or [EMAIL_RECIPIENT]
    body = watch.notification_body(
        doc,
        reg.PUBLIC_ORIGIN + reg.ARCHIVE_PUBLIC_PATH,
        reg.PUBLIC_ORIGIN + reg.ARCHIVE_MANIFEST_PUBLIC_PATH,
    )
    try:
        guarded_send_email(
            ses,
            is_dry,
            Source=EMAIL_SENDER,
            Destination={"ToAddresses": recipients},
            Message={
                "Subject": {"Data": watch.notification_subject(doc)},
                "Body": {"Text": {"Data": body}},
            },
        )
    except Exception as exc:  # noqa: BLE001 - a failed send must not lose the published state
        logger.error("continuity notification failed: %s", type(exc).__name__)
        return {"sent": False, "reason": "send_failed", "contacts_configured": bool(contacts)}
    return {"sent": not is_dry, "reason": "dry_run" if is_dry else None, "contacts_configured": bool(contacts)}


def lambda_handler(event, context):
    """Entry point. Wraps `_run` so a failure is logged with its traceback and
    then re-raised — re-raised, not swallowed, because the error alarm and the
    withheld heartbeat are both how a broken contract becomes visible."""
    try:
        return _run(event)
    except Exception as exc:
        logger.error("permanence run failed: %s", exc, exc_info=True)
        raise


def _run(event):  # noqa: C901 - a linear sequence, not a branch thicket
    event = event if isinstance(event, dict) else {}
    is_dry = dry_run.stash(event)
    now = datetime.now(timezone.utc)
    now_iso = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")

    table, s3, ses, secrets = _clients()

    # 1 ── measure the silence
    signals = watch.read_signals(table, USER_ID)
    verdict = watch.evaluate(signals, now.date())
    previous = _read_previous_continuity(s3)
    state_doc = watch.apply_transition(previous, verdict, now_iso)

    # 2 ── build the archive (no writes yet)
    # The clock's verdict goes IN, so the manifest inside the tarball carries it
    # too: someone who only ever has the file can still see what state the
    # contract was in when it was made.
    continuity_summary = {
        "state": state_doc["state"],
        "days_silent": state_doc.get("days_silent"),
        "last_signal_date": state_doc.get("last_signal_date"),
        "frozen": state_doc.get("frozen"),
        "path": reg.ARCHIVE_CONTINUITY_PUBLIC_PATH,
    }
    built = public_archive.build_archive(s3, S3_BUCKET, now=now, continuity=continuity_summary)
    manifest = built["manifest"]

    was_frozen = bool((previous or {}).get("frozen"))
    newly_triggered = state_doc.get("frozen") and not was_frozen
    final_key = f"{reg.ARCHIVE_PREFIX}final-{built['day']}.tar.gz"

    state_doc["archive"] = {
        "path": reg.ARCHIVE_PUBLIC_PATH,
        "manifest_path": reg.ARCHIVE_MANIFEST_PUBLIC_PATH,
        "bytes": manifest["archive"]["bytes"],
        "sha256": manifest["archive"]["sha256"],
        "built_at": manifest["generated_at"],
        "final_edition": f"/archive/final-{built['day']}.tar.gz" if state_doc.get("frozen") else None,
    }
    state_doc["terms"] = terms.public_terms()

    # 3 ── publish
    # The rolling copy moves unless the contract is frozen and was ALREADY
    # frozen. Written as "already", not "now", on purpose: the trigger run
    # itself makes one last rolling write so /archive/latest.tar.gz IS the
    # sealed final edition, and a thaw run resumes publishing rather than
    # leaving the stable address pinned to the day the switch tripped.
    publish_rolling = not (state_doc.get("frozen") and was_frozen)

    # An hour of API outage must not replace a complete archive with a hollow
    # one. A PARTIAL capture still publishes — the manifest says 87/115 and the
    # reader can see it — but a total failure is an outage, not an archive, and
    # overwriting yesterday's good copy with it would destroy the only thing
    # this run exists to protect. Declining also withholds the heartbeat
    # datapoint, so two such nights raise the alarm instead of passing quietly.
    api_blackout = manifest["api"]["routes_declared"] > 0 and manifest["api"]["routes_captured"] == 0
    if api_blackout:
        publish_rolling = False
        newly_triggered = False
        logger.error("permanence: every API route failed — declining to overwrite the archive with an empty one")

    published: list[str] = []
    if dry_run.persistence_enabled(event):
        if newly_triggered:
            # Seal the final edition BEFORE the rolling copy stops moving, so
            # the dated artefact exists even if a later step fails.
            _publish(s3, final_key, built["tarball"], "application/gzip", 86400)
            published.append(final_key)
        if publish_rolling:
            _publish(s3, reg.ARCHIVE_TARBALL_KEY, built["tarball"], "application/gzip", 3600)
            published.append(reg.ARCHIVE_TARBALL_KEY)
            _publish(s3, reg.ARCHIVE_MANIFEST_KEY, json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"), "application/json", 300)
            published.append(reg.ARCHIVE_MANIFEST_KEY)
        _publish(s3, reg.ARCHIVE_CONTINUITY_KEY, json.dumps(state_doc, indent=2, sort_keys=True).encode("utf-8"), "application/json", 300)
        published.append(reg.ARCHIVE_CONTINUITY_KEY)

    # 4 ── notify on a transition (the guard suppresses the send on a dry run)
    notification = None
    if state_doc.get("notify"):
        notification = _notify(ses, secrets, state_doc, is_dry)

    print(
        _emf(
            state_doc["state"],
            state_doc.get("days_silent"),
            manifest["archive"]["bytes"],
            manifest["entry_count"],
            manifest["api"]["routes_captured"],
            manifest["api"]["routes_declared"],
            built=not api_blackout,
        )
    )

    summary = {
        "dry_run": is_dry,
        "state": state_doc["state"],
        "days_silent": state_doc.get("days_silent"),
        "frozen": state_doc.get("frozen"),
        "archive_bytes": manifest["archive"]["bytes"],
        "entry_count": manifest["entry_count"],
        "api_captured": manifest["api"]["routes_captured"],
        "api_declared": manifest["api"]["routes_declared"],
        "published": published,
        "archive_published": reg.ARCHIVE_TARBALL_KEY in published,
        "api_blackout": api_blackout,
        "notification": notification,
        "terms_version": terms.TERMS_VERSION,
    }
    logger.info("permanence run: %s", json.dumps(summary))
    return {"statusCode": 200, "body": json.dumps(summary)}
