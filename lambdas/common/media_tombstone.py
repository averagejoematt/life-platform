"""The restart tombstone for generated media — one shape, shared by its writer and its readers (#4365).

A reset cannot delete under ``generated/*`` (ADR-046: DeleteObject is denied for the
admin principal, and the bucket is versioned), so ``deploy/restart_media_reset.py``
copies each live episode object to ``archive/pilot/`` and OVERWRITES the original key
with a small JSON marker::

    {"tombstone": true, "tombstoned_at": "...", "archived_to": "...", "tombstoned_reason": "experiment_restart_<date>"}

The key survives, so a bare ``head_object`` answers 200 for it. The weekly Panel's
"already published?" check did exactly that and treated the 186-byte ``wk{1,2,4}.wav``
tombstones left by the 2026-07-12 reset as real episodes: weeks 1 and 2 of the current
cycle were skipped in ~0.3 s with no log line.

``media_presence`` (and ``first_published`` over a producer's candidate keys) is the existence check every producer that publishes under a
tombstoned surface uses instead of a bare head: it reads the stored object's own
shape. A tombstone is written by one function here (``tombstone_body``) and recognised
by one function here (``parse_tombstone``), so the writer and the readers cannot drift.
"""

import json

# The tombstone writer's output is ~200 bytes; the smallest real episode is megabytes.
# Anything at or below this size is not a publishable episode, tombstone or not.
TOMBSTONE_MAX_BYTES = 4096

PRESENT = "present"
ABSENT = "absent"
TOMBSTONE = "tombstone"
UNDERSIZED = "undersized"


def tombstone_body(tombstoned_at: str, archived_to: str, reason: str) -> bytes:
    """The marker the restart overwrites a live media key with (the writer side)."""
    return json.dumps({"tombstone": True, "tombstoned_at": tombstoned_at, "archived_to": archived_to, "tombstoned_reason": reason}).encode()


def parse_tombstone(body: bytes) -> dict | None:
    """The tombstone document when ``body`` is one, else None (the reader side)."""
    if not body or len(body) > TOMBSTONE_MAX_BYTES:
        return None
    try:
        doc = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None
    return doc if isinstance(doc, dict) and doc.get("tombstone") is True else None


def media_presence(s3, bucket: str, key: str) -> tuple[str, dict]:
    """Is ``key`` a real published media object? Returns ``(status, detail)``.

    status is PRESENT, ABSENT (no such key), TOMBSTONE (the restart marker — detail is
    its document) or UNDERSIZED (a stub at or under TOMBSTONE_MAX_BYTES that is not a
    tombstone — detail carries its size). Only PRESENT counts as published."""
    try:
        head = s3.head_object(Bucket=bucket, Key=key)
    except Exception:
        return ABSENT, {}
    size = head.get("ContentLength")
    if isinstance(size, int) and size > TOMBSTONE_MAX_BYTES:
        return PRESENT, {"bytes": size}
    try:
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read(TOMBSTONE_MAX_BYTES + 1)
    except Exception:
        # The head answered but the body did not. With a known small size it is still a
        # stub; with no size we cannot tell, and keep the old answer (present) so a read
        # hiccup never re-synthesises a real episode.
        return (UNDERSIZED, {"bytes": size}) if isinstance(size, int) else (PRESENT, {})
    doc = parse_tombstone(body)
    if doc is not None:
        return TOMBSTONE, doc
    if len(body) <= TOMBSTONE_MAX_BYTES:
        return UNDERSIZED, {"bytes": len(body)}
    return PRESENT, {"bytes": size}


def first_published(s3, bucket: str, keys: list[str], logger) -> str | None:
    """The first of ``keys`` holding real published media, or None. A tombstone or an
    undersized stub on a key is logged by name (week/date, key, reason) and skipped —
    the run it no longer short-circuits then says why it went on."""
    for key in keys:
        status, detail = media_presence(s3, bucket, key)
        if status == PRESENT:
            return key
        if status == TOMBSTONE:
            logger.info(
                "[media] %s is a restart tombstone (reason=%s archived_to=%s), not a published episode",
                key,
                detail.get("tombstoned_reason"),
                detail.get("archived_to"),
            )
        elif status == UNDERSIZED:
            logger.warning("[media] %s is a %s-byte stub, not a published episode", key, detail.get("bytes"))
    return None
