# Raw archive — objects whose KMS key no longer exists (#4634)

**Run:** 2026-10-09, `python3 scripts/raw_kms_readability_inventory.py --prefix raw/ --check-backup --sample-get 25 --markdown`
(every month), then the same with `--month 2026-05 --versions` for the version check
(read-only: ListObjectsV2, HeadObject, kms:DescribeKey, a 1-byte ranged GetObject; nothing written).
**No key identifiers are recorded here, by rule** — the script reports keys only as opaque labels.

## What happened

From 2026-05-16 21:31Z to 2026-05-17 21:44Z the bucket default encryption was a
customer-managed KMS key (ADR-053 Phase 2.4). The default was reverted to SSE-S3, the
key was scheduled for deletion on 2026-05-24 and is now gone. Every object written in
that window still names the deleted key and cannot be decrypted. ADR-053 is amended
with the rule that follows (a key that has ever encrypted a retained object is never
scheduled for deletion until those objects are re-encrypted).

## Coverage of this run

| Scope | Covered | Result |
|---|---|---|
| `raw/` — every object, every month (2026-02 → 2026-10), 39,259 objects | yes | 25 undecryptable, all last-modified 2026-05; 0 HeadObject errors |
| Every other top-level prefix (`generated/`, `site/`, exports, …) | **no** — owner run | not inventoried tonight |
| `config/` | **no** — out of bounds for unattended runs; `--include-config` is owner-only | not inventoried |

KMS keys seen under `raw/`: one (`cmk-1`), state **Missing** (DescribeKey → NotFound).
Everything else under `raw/` is SSE-S3.

## Undecryptable objects, by prefix and month

| Source path | Month | Objects in that cell | Undecryptable |
|---|---|---|---|
| `raw/matthew/health_auto_export` | 2026-05 | 436 | 14 |
| `raw/matthew/strava` | 2026-05 | 1 | 1 |
| `raw/matthew/whoop` | 2026-05 | 66 | 3 |
| `raw/matthew/withings` | 2026-05 | 31 | 5 |
| `raw/todoist` | 2026-05 | 31 | 2 |

Total 25 — the same count the 2026-10-04 data-source sweep's verifier found from May alone,
now confirmed across every month of `raw/`.

## Per source: re-fetchable, backup copy, verdict

The backup check is EVERY affected key (25 of 25), HeadObject against the cross-region
raw backup bucket; a 404 is proof of absence, a 403/5xx would be reported as an error
and is not (this run: 25 × 404, 0 errors; the same credentials list and read other keys in
that bucket). The bucket is versioned, so `--versions` also heads every NONCURRENT version
of each affected key: none decrypts (spot-checked by listing: each affected Withings day has
two versions, 16:05Z and 17:05Z on 05-17, and Strava 05/09 has 22:10Z and 23:10Z on 05-16 —
both inside the window).

| Source path | Undecryptable | Re-fetchable from the vendor | Readable older version | Copies in backup bucket | Verdict |
|---|---|---|---|---|---|
| `raw/matthew/health_auto_export` (Apple Health webhook payloads) | 14 | no — a push has no vendor re-fetch | 0 of 14 | 0 of 14 | **unrecoverable** |
| `raw/todoist` | 2 | partly — completions yes, point-in-time snapshots no | 0 of 2 | 0 of 2 | snapshot portion **unrecoverable**; completions re-fetchable |
| `raw/matthew/withings/measurements` | 5 | yes | 0 of 5 | 0 of 5 | re-fetchable (owner box: re-fetch) |
| `raw/matthew/whoop/{cycle,recovery,sleep}` | 3 | yes | 0 of 3 | 0 of 3 | re-fetchable (owner box: re-fetch) |
| `raw/matthew/strava/activities` | 1 | yes | 0 of 1 | 0 of 1 | re-fetchable (owner box: re-fetch) |

A 1-byte ranged GetObject on all 25 affected objects fails with `AccessDenied` (the error S3
returns when the object's KMS key cannot be used), while the same call on an SSE-S3 neighbour
(`raw/matthew/whoop/cycle/2026/03/10.json`) succeeds — the failure is observed, not inferred.

## The affected objects

Apple Health webhook payloads — **unrecoverable** (no vendor re-fetch, no backup copy):

- `raw/matthew/health_auto_export/2026/05/16_213115.json`
- `raw/matthew/health_auto_export/2026/05/16_223325.json`
- `raw/matthew/health_auto_export/2026/05/16_231406.json`
- `raw/matthew/health_auto_export/2026/05/17_005749.json`
- `raw/matthew/health_auto_export/2026/05/17_010149.json`
- `raw/matthew/health_auto_export/2026/05/17_021951.json`
- `raw/matthew/health_auto_export/2026/05/17_073156.json`
- `raw/matthew/health_auto_export/2026/05/17_153701.json`
- `raw/matthew/health_auto_export/2026/05/17_170939.json`
- `raw/matthew/health_auto_export/2026/05/17_170949.json`
- `raw/matthew/health_auto_export/2026/05/17_194142.json`
- `raw/matthew/health_auto_export/2026/05/17_202420.json`
- `raw/matthew/health_auto_export/2026/05/17_204326.json`
- `raw/matthew/health_auto_export/2026/05/17_214433.json`

Todoist — snapshot portion unrecoverable, completions re-fetchable:

- `raw/todoist/2026/05/16.json`
- `raw/todoist/2026/05/2026-05-17.json`

Re-fetchable from the vendor (not yet re-fetched — owner box):

- `raw/matthew/strava/activities/2026/05/09.json`
- `raw/matthew/whoop/cycle/2026/05/17.json`
- `raw/matthew/whoop/recovery/2026/05/17.json`
- `raw/matthew/whoop/sleep/2026/05/17.json`
- `raw/matthew/withings/measurements/2026/05/10.json`
- `raw/matthew/withings/measurements/2026/05/12.json`
- `raw/matthew/withings/measurements/2026/05/13.json`
- `raw/matthew/withings/measurements/2026/05/16.json`
- `raw/matthew/withings/measurements/2026/05/17.json`

Note the file dates are the vendor-day the object describes, not the write time; the
encryption followed the write. Spot-checked: `strava/activities/2026/05/09.json` was last
modified 2026-05-16T23:10Z and `withings/measurements/2026/05/10.json` 2026-05-17T17:05Z,
both inside the window (the sweep's verifier recorded the window from all 25).

## What this means for "recoverable from raw"

Any replay or back-fill that rebuilds history from `raw/` cannot read these 25 objects.
For the Apple Health window the DynamoDB records written at ingest time (from these
payloads, before the key was deleted) are now the only copy of that data — a replay
must skip these keys rather than treat their absence as "no data".

## Not done here (owner boxes on #4634)

- Inventory every other top-level prefix, and `config/` (`--prefix <p>`; `--include-config` by hand).
- The count above is CURRENT versions. Noncurrent versions of other `raw/` keys written in the
  window are dead too but are not a loss of their own (their current version decides readability);
  a version-level census was not run.
- Re-fetch the re-fetchable days (Withings, Whoop, Strava, Todoist completions) — a write.
- Decide whether the unreadable objects stay as tombstones (raw/* is delete-protected, ADR-046).
- The scheduled check (the script exits 1 on any dead key, so it can back one) and its first live output.
