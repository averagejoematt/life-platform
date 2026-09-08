"""chronicle_manifest_qa — #3485 dead-man: the live journal manifest never carries an archived post.

The 2026-09-04 18:00Z auto-publish sweep republished cycle 15's tombstoned Week-1 draft on
Day 0 of cycle 16 and overwrote generated/journal/posts.json with a draft-time snapshot of
FOUR previous-cycle posts. Nothing on the platform noticed; a review panel did, seven hours
later. This check reads the manifest the site actually serves and asks DynamoDB whether
each post's chronicle row is still current — a tombstoned or non-current-phase row behind a
live post is a red, not a warning: it is the previous cycle narrating as this one.

Sibling of acwr_liveness_qa / raw_archive_qa: the check takes its collaborators as
arguments so qa_smoke_lambda stays a registry, not a host.

#3650 — HOW A POST IS MATCHED TO ITS ROW, and why it is not by key.
  A chronicle row's `sk` is its ORIGINAL publication slot; its `date` ATTRIBUTE is the
  effective date the manifest serves. A reset re-dates a carried-forward lead-in by
  writing the new date into the attribute and LEAVING THE SK ALONE, so the two diverge
  routinely and by design — live example: "Before the Numbers" is `sk=DATE#2026-02-28`
  with `date=2026-08-31`.

  This check used to reconstruct a key as `DATE#{post["date"]}` and `get_item` it. For
  that post it fetched `DATE#2026-08-31` — a DIFFERENT, tombstoned cycle-15 row that
  happens to occupy that slot — and reported the manifest as serving an archived post.
  The site was never serving it. The check reported a red every night from 2026-09-03,
  and a permanently-red nightly is a nightly nobody reads: `qa-smoke-failures` sat in
  ALARM for days, so a REAL manifest regression would have been invisible next to it.

  Matching is now on the row's own `date` attribute PLUS its title, because the date
  alone is genuinely ambiguous — `date=2026-08-31` matches both `DATE#2026-08-31`
  (cycle 15, tombstoned) and `DATE#2026-02-28` (cycle 17, live). One scan of the
  partition replaces N get_items, and an ambiguous match is REPORTED rather than
  silently resolved to whichever row sorts first.
"""

from __future__ import annotations

import json

from experiment.phase_filter import singleton_visible

MANIFEST_KEY = "generated/journal/posts.json"


def _chronicle_rows(table, chronicle_pk: str) -> list[dict]:
    """Every `DATE#` row in the chronicle partition, paginated.

    One scan instead of a get_item per post: the partition is small (tens of rows), and
    matching needs the whole set anyway because the key cannot be reconstructed.
    """
    from boto3.dynamodb.conditions import Key as _Key

    out: list[dict] = []
    kwargs = {"KeyConditionExpression": _Key("pk").eq(chronicle_pk) & _Key("sk").begins_with("DATE#")}
    while True:
        resp = table.query(**kwargs)
        out.extend(resp.get("Items") or [])
        nxt = resp.get("LastEvaluatedKey")
        if not nxt:
            return out
        kwargs["ExclusiveStartKey"] = nxt


def _match(rows: list[dict], date: str, title: str) -> list[dict]:
    """Rows whose `date` ATTRIBUTE is this post's date, narrowed by title when needed.

    Title is only used to disambiguate — a post whose date matches exactly one row is
    matched on the date alone, so a re-titled post is still found.
    """
    by_date = [r for r in rows if str(r.get("date") or "") == date]
    if len(by_date) <= 1:
        return by_date
    titled = [r for r in by_date if str(r.get("title") or "") == title]
    return titled if titled else by_date


def check_chronicle_manifest_provenance(table, s3, bucket: str, Check, tier, *, chronicle_pk: str = "USER#matthew#SOURCE#chronicle"):
    c = Check("chronicle:manifest_provenance", "Content Truth", tier)
    try:
        body = s3.get_object(Bucket=bucket, Key=MANIFEST_KEY)["Body"].read()
        posts = (json.loads(body) or {}).get("posts") or []
    except Exception as exc:  # noqa: BLE001 — a missing manifest is its own (loud) finding
        c.fail(f"could not read {MANIFEST_KEY}: {exc}")
        return [c]
    try:
        rows = _chronicle_rows(table, chronicle_pk)
    except Exception as exc:  # noqa: BLE001 — an unreadable partition is its own loud finding
        c.fail(f"DDB error scanning {chronicle_pk}: {exc}")
        return [c]

    archived = []
    unknown = []
    ambiguous = []
    for post in posts:
        date = str(post.get("date") or "")
        if not date:
            continue
        matches = _match(rows, date, str(post.get("title") or ""))
        if len(matches) > 1:
            # Deliberately not resolved here. Two live rows claiming one served post is a
            # data fault worth naming; picking one would hide it behind a green check.
            ambiguous.append(
                f"{date} ({post.get('title', '?')!s}: {len(matches)} rows — {', '.join(sorted(m.get('sk', '?') for m in matches))})"
            )
            continue
        if not matches:
            unknown.append(date)
            continue
        row = matches[0]
        if row.get("tombstone") or row.get("tombstoned_at") or not singleton_visible(row):
            archived.append(f"{date} ({post.get('title', '?')!s}: phase={row.get('phase')!r} cycle={row.get('cycle')!r})")
    if ambiguous:
        c.fail(
            f"{len(ambiguous)} manifest post(s) match more than one chronicle row — cannot tell which the site serves: {'; '.join(ambiguous)}"
        )
        return [c]
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
