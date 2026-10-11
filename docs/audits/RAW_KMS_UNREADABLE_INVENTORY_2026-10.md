# Raw archive — objects whose KMS key no longer exists (#4634)

**Runs (all read-only — ListObjectsV2, HeadObject, kms:DescribeKey; nothing written, nothing copied):**

- 2026-10-09, `raw/` only: `python3 scripts/raw_kms_readability_inventory.py --prefix raw/ --check-backup --sample-get 25 --markdown`
  (every month), then the same with `--month 2026-05 --versions` for the version check
  (this run also made a 1-byte ranged GetObject on each affected object).
- **2026-10-11, the whole bucket, every month:** `python3 scripts/raw_kms_readability_inventory.py --prefix "" --check-backup --check-against-record --markdown`
  — 47,127 objects under 26 top-level prefixes, list + head only (the 109 objects under `config/` are listed past, never read).

**No key identifiers are recorded here, by rule** — the script reports keys only as opaque labels.

## What happened

From 2026-05-16 21:31Z to 2026-05-17 21:44Z the bucket default encryption was a
customer-managed KMS key (ADR-053 Phase 2.4). The default was reverted to SSE-S3, the
key was scheduled for deletion on 2026-05-24 and is now gone. Every object written in
that window still names the deleted key and cannot be decrypted. ADR-053 is amended
with the rule that follows (a key that has ever encrypted a retained object is never
scheduled for deletion until those objects are re-encrypted).

## Coverage

| Scope | Covered | Result |
|---|---|---|
| `raw/` — every object, every month (2026-02 → 2026-10), 39,309 objects | yes (2026-10-09, re-run 2026-10-11) | 25 undecryptable, all last-modified 2026-05; 0 HeadObject errors |
| Every other top-level prefix — 25 prefixes, 7,818 objects (table below) | yes (2026-10-11) | 0 undecryptable; every object SSE-S3; 0 HeadObject errors |
| `config/` — 109 objects | **pending — owner run** (out of bounds for unattended runs; `--include-config` is owner-only) | not inventoried |
| Root-level objects (no prefix) | yes (2026-10-11) | none exist |

KMS keys seen across the whole bucket: one (`cmk-1`), state **Missing** (DescribeKey → NotFound).
Every other object in every scanned prefix is SSE-S3.

### Every top-level prefix, every month (2026-10-11)

| Top-level prefix | Objects | Last-modified months | SSE-S3 | SSE-KMS | Undecryptable |
|---|---|---|---|---|---|
| `ai-canary-log/` | 40 | 2026-07 → 2026-10 (4) | 40 | 0 | 0 |
| `assets/` | 5 | 2026-03 | 5 | 0 | 0 |
| `blog/` | 8 | 2026-05 → 2026-09 (3) | 8 | 0 | 0 |
| `buddy/` | 3 | 2026-03 → 2026-10 (2) | 3 | 0 | 0 |
| `claude-memory-backup/` | 557 | 2026-07 → 2026-10 (4) | 557 | 0 | 0 |
| `coherence-log/` | 106 | 2026-06 → 2026-10 (5) | 106 | 0 | 0 |
| `dashboard/` | 276 | 2026-03 → 2026-10 (5) | 276 | 0 | 0 |
| `datadrops-archive/` | 167 | 2026-07 | 167 | 0 | 0 |
| `dead-letter-archive/` | 81 | 2026-03 → 2026-10 (6) | 81 | 0 | 0 |
| `deploys/` | 632 | 2026-09 → 2026-10 (2) | 632 | 0 | 0 |
| `design-sketches/` | 7 | 2026-07 | 7 | 0 | 0 |
| `drift-log/` | 24 | 2026-07 → 2026-10 (4) | 24 | 0 | 0 |
| `exports/` | 24 | 2026-03 | 24 | 0 | 0 |
| `generated/` | 2198 | 2026-04 → 2026-10 (6) | 2198 | 0 | 0 |
| `imports/` | 94 | 2026-02 → 2026-09 (4) | 94 | 0 | 0 |
| `mcp-audit/` | 360 | 2026-08 → 2026-10 (3) | 360 | 0 | 0 |
| `panelcast-holds/` | 1 | 2026-10 | 1 | 0 | 0 |
| `pip-audit/` | 3 | 2026-09 → 2026-10 (2) | 3 | 0 | 0 |
| `raw/` | 39309 | 2026-02 → 2026-10 (9) | 39284 | 25 | 25 |
| `recap/` | 73 | 2026-09 → 2026-10 (2) | 73 | 0 | 0 |
| `reconciliation/` | 28 | 2026-04 → 2026-10 (7) | 28 | 0 | 0 |
| `remediation-log/` | 194 | 2026-05 → 2026-10 (6) | 194 | 0 | 0 |
| `session-artifacts/` | 34 | 2026-07 | 34 | 0 | 0 |
| `site/` | 2855 | 2026-03 → 2026-10 (7) | 2855 | 0 | 0 |
| `story-desk/` | 17 | 2026-10 | 17 | 0 | 0 |
| `uploads/` | 31 | 2026-09 → 2026-10 (2) | 31 | 0 | 0 |
| `config/` | 109 | — | — | — | **pending (owner run)** |

The months are the objects' CURRENT last-modified months; the bucket is versioned, and a
version-level census was not run (see "Not done here").

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

## The scheduled check (#4634 box 3)

`.github/workflows/raw-kms-readability.yml`, Mondays 14:29 UTC plus `workflow_dispatch`, runs
`python3 scripts/raw_kms_readability_inventory.py --prefix raw/ --check-against-record --sample-readable 20 --markdown`
under the remediation role (no new IAM). It fails when the set of undecryptable objects under
`raw/` differs from the list in **The affected objects** above — in either direction — when any
HeadObject fails, or when any of 20 random should-be-readable objects fails a 1-byte read. The
list above is therefore load-bearing: **a re-fetch that makes a recorded object readable must
remove its bullet in the same change**, or the next Monday run goes red (by design).

## Backup bucket and version check (2026-10-11)

Read-only, 2026-10-11 ~19:30Z: the backup bucket `matthew-life-platform-raw-backup` was HeadObject'd for
every one of the 25 recorded keys and their noncurrent versions listed, with
`python3 scripts/raw_kms_readability_inventory.py --prefix raw/ --month 2026-05 --check-backup --versions --markdown`.
It scanned 1215 objects under `raw/` in 2026-05, with 0 HeadObject errors, and found the same 25 undecryptable objects.

| Source path | Undecryptable | Re-fetchable from vendor | Readable older version | Copies in backup bucket | Backup check errors | Unrecoverable |
|---|---|---|---|---|---|---|
| `raw/matthew/health_auto_export` | 14 | no — webhook push, no vendor re-fetch | 0 | 0 | 0 | yes |
| `raw/matthew/strava` | 1 | yes — vendor API serves history | 0 | 0 | 0 | no |
| `raw/matthew/whoop` | 3 | yes — vendor API serves history | 0 | 0 | 0 | no |
| `raw/matthew/withings` | 5 | yes — vendor API serves history | 0 | 0 | 0 | no |
| `raw/todoist` | 2 | partly — completions re-fetchable, point-in-time snapshots are not | 0 | 0 | 0 | no |

**Conclusion.** No readable older version and no backup copy exists for any of the 25 objects, so the 14 Apple
Health payloads have no second copy anywhere and are recorded as unrecoverable; the 11 others (Strava, Whoop,
Withings, Todoist) await the owner's vendor re-fetch or waiver.

The scheduled check `raw-kms-readability.yml` ran green on 2026-10-11T19:07Z (run 38166655589) against this record.

## Not done here (owner boxes on #4634)

- `config/`: `python3 scripts/raw_kms_readability_inventory.py --prefix config/ --include-config --markdown` — owner-run, then add its row above.
- The count above is CURRENT versions. Noncurrent versions of other `raw/` keys written in the
  window are dead too but are not a loss of their own (their current version decides readability);
  a version-level census was not run.
- Re-fetch the re-fetchable days (Withings, Whoop, Strava, Todoist completions) — a write, owner's call
  (or a waiver: every affected day is before the experiment's genesis). Each re-fetched object then
  leaves the list above in the same change.
- Decide whether the unreadable objects stay as tombstones (raw/* is delete-protected, ADR-046).
- The scheduled check's first LIVE (GitHub Actions, remediation role) output — after merge, by
  `gh workflow run raw-kms-readability.yml`.
