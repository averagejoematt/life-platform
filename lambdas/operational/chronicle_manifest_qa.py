"""chronicle_manifest_qa — #3485 dead-man: the live journal manifest never carries an archived post.

The 2026-09-04 18:00Z auto-publish sweep republished cycle 15's tombstoned Week-1 draft on
Day 0 of cycle 16 and overwrote generated/journal/posts.json with a draft-time snapshot of
FOUR previous-cycle posts. Nothing on the platform noticed; a review panel did, seven hours
later. This check reads the manifest the site actually serves and asks DynamoDB whether
each post's chronicle row is still current — a tombstoned or non-current-phase row behind a
live post is a red, not a warning: it is the previous cycle narrating as this one.

Sibling of acwr_liveness_qa / raw_archive_qa: the check takes its collaborators as
arguments so qa_smoke_lambda stays a registry, not a host.
"""

from __future__ import annotations

import json

from experiment.phase_filter import singleton_visible

MANIFEST_KEY = "generated/journal/posts.json"


def check_chronicle_manifest_provenance(table, s3, bucket: str, Check, tier, *, chronicle_pk: str = "USER#matthew#SOURCE#chronicle"):
    c = Check("chronicle:manifest_provenance", "Content Truth", tier)
    try:
        body = s3.get_object(Bucket=bucket, Key=MANIFEST_KEY)["Body"].read()
        posts = (json.loads(body) or {}).get("posts") or []
    except Exception as exc:  # noqa: BLE001 — a missing manifest is its own (loud) finding
        c.fail(f"could not read {MANIFEST_KEY}: {exc}")
        return [c]
    archived = []
    unknown = []
    for post in posts:
        date = str(post.get("date") or "")
        if not date:
            continue
        try:
            row = table.get_item(Key={"pk": chronicle_pk, "sk": f"DATE#{date}"}).get("Item")
        except Exception as exc:  # noqa: BLE001
            c.fail(f"DDB error reading DATE#{date}: {exc}")
            return [c]
        if row is None:
            unknown.append(date)
            continue
        if row.get("tombstone") or row.get("tombstoned_at") or not singleton_visible(row):
            archived.append(f"{date} ({post.get('title', '?')!s}: phase={row.get('phase')!r} cycle={row.get('cycle')!r})")
    if archived:
        c.fail(
            f"{len(archived)} archived post(s) live in the manifest — the previous cycle is narrating as this one: {'; '.join(archived)}"
        )
    elif unknown:
        # A manifest entry with no chronicle row at all is a lesser class (a lead-in
        # re-dated by the reset is normal); report it, do not alarm on it.
        c.warn(f"{len(posts)} post(s) in the manifest, {len(unknown)} with no chronicle row: {', '.join(unknown)}")
    else:
        c.ok(f"{len(posts)} post(s) in the manifest, every chronicle row current")
    return [c]
