# WORKORDER — Hevy routines land in root; force_title ignored on commit

Raised 2026-09-07 while committing `Foundation - Push - 1 - 1` (day 1 of the block).
Two independent defects, both long-standing, both silent. Athlete has been dragging every
routine into its folder by hand since the feature shipped.

---

## Problem A — every routine lands in the Hevy root folder

**Status:** root cause confirmed from CloudWatch. Fix is one line; verify before shipping.

**Evidence** — `/aws/lambda/life-platform-mcp`, 2026-09-07T04:01:52.822Z, request
`6c5878b4-1977-4706-8de7-03d7f555127a`:

```
[WARNING] list_folders failed; committing without folder: HTTP Error 400: Bad Request
```

**Chain.** `_ensure_folder()` (`mcp/tools_hevy_routine.py:90`) calls `wc.list_folders()`, which
400s. The handler catches `Exception`, logs a warning, returns `None`
(`# noqa: BLE001 - never block a commit on folder I/O`). `to_create_body` then sends
`folder_id: None` and the routine is created in root. The commit reports success, because it
*was* a success — only the foldering failed, and it failed by design without surfacing.

**Why the 400.** `hevy_write_client.py:289` is the only collection endpoint not using Hevy's
usual cap:

| Endpoint | `page_size` default | Observed |
|---|---|---|
| `/v1/exercise_templates` | 100 | OK |
| `/v1/routines` | 10 | OK |
| `/v1/workouts` | 10 | OK |
| **`/v1/routine_folders`** | **50** | **400** |

Auth is ruled out — `_request` raises `HevyAuthError` on 401/403 and did not; a wrong path
would 404. `pageSize=50` is the only anomaly in the request.

**Proposed fix** (`lambdas/training/hevy_write_client.py:289`):

```python
-def list_folders(page: int = 1, page_size: int = 50) -> dict[str, Any]:
+def list_folders(page: int = 1, page_size: int = 10) -> dict[str, Any]:
```

**Verify first:** `python3 scripts/diag_hevy_folders.py` (read-only; sweeps pageSize, controls
against `/v1/routines`, dumps the response shape, reports the day-1 routine's folder_id).
Do not ship the change until section A of that output fails at 50 and passes at <=10.

**Second-order fix — stop the silent failure.** Even fixed, `_ensure_folder` will swallow the
next folder outage the same way. It should not block a commit, but the commit result must carry
the miss so it is visible at the call site, e.g. return
`{"status": "committed", ..., "folder": "unfoldered: <reason>"}` instead of only a CloudWatch
warning nobody reads. This defect survived months precisely because it was invisible.

**Not a bug, do not chase:** `dry_run` reporting `"folder_id": null` is expected —
`_ensure_folder` runs only on the commit path, so the preview is always null.

**No retroactive fix exists.** `folder_id` is create-only in Hevy and `to_update_body` omits it
deliberately (`hevy_compiler.py:219`). Routines already in root can only be moved by dragging
them in the app. The fix applies to newly created routines only.

---

## Problem B — `force_title` silently ignored when passed on commit

**Status:** root cause confirmed by reading. Not a code defect — a documentation defect that
causes a caller error. The tool did what it was written to do.

`force_title` is parsed at DRAFT time (`mcp/tools_hevy_routine.py:785`) and persisted onto
`ir.inputs_snapshot` (line 809). At commit, `_resolve_title_inputs()` (line 848) checks
`ir.inputs_snapshot["force_title"]` and never looks at the commit arguments. A `force_title`
passed on `commit` is therefore dropped without warning; the compiler re-renders the convention
title and the PUT writes it back. The call still returns `{"status": "committed"}`, so the
caller believes the rename landed. It did not — the routine was renamed by hand in the app.

**Correct usage:** `draft_custom(force_title=true, title="...")` -> `dry_run` -> `commit`.

**Fixes, in priority order:**
1. Correct the `manage_hevy_routine` tool description. It currently reads *"A title you pass is
   ignored unless you also set force_title=true"*, which implies commit honours the pair. State
   that both are draft-time only.
2. Have `commit` reject (or warn loudly on) a `force_title`/`title` argument rather than
   silently discarding it. Same class of bug as A: a silent no-op reported as success.

---

## Related: the title counter itself

Separate from B. The compiler rendered `Foundation - Push - 3 - 11` for what is day 1 of a new
block, because `build_title_context` counts performed history and the raw Hevy store still holds
the 484-workout backfill from the 2024-25 cut. Every future routine inherits the inflation.
Fix = bound the counter's history window to the current block (or exclude pre-2026-09 backfill).
Until then the title must be forced at draft time on every commit.

---

## Acceptance

- [ ] `scripts/diag_hevy_folders.py` section A confirms the pageSize cap
- [ ] `list_folders` page_size corrected; a fresh `draft_custom` -> `commit` lands in its type folder
- [ ] `_ensure_folder` failures surface in the commit result, not only in CloudWatch
- [ ] tool description corrected; `commit` warns on a discarded `force_title`
- [ ] title counter bounded to the current block

---

## Resolution (2026-09-06, #3670)

**A — confirmed and fixed.** `scripts/diag_hevy_folders.py` run live 2026-09-06 ~21:30 PT:

```
A. pageSize sweep on /v1/routine_folders
   pageSize=10  -> 200
   pageSize=11  -> 400  {"error":"pageSize must be less than or equal to 10"}
   pageSize=50  -> 400  <-- PRODUCTION VALUE
B. control on /v1/routines:  10 -> 200,  50 -> 400   (same cap, API-wide)
C. response shape at pageSize=10: keys ['page','page_count','routine_folders'] -> parser MATCH
D. 'Foundation - Push - 1 - 1'  folder_id=None
```

The cap is API-wide, not folder-specific; `/v1/exercise_templates` at 100 is a genuine
verified-live exception. Section C clears the line-101 parser. `list_folders` now defaults to
`HEVY_MAX_PAGE_SIZE = 10`.

**The second-order fix — the one that mattered.** `_ensure_folder` now returns
`(folder_id, miss_reason)` and `_action_commit` carries the outcome in its own result:

```
{"status": "committed", ..., "folder": "unfoldered: list_folders failed (HTTPError: HTTP Error 400: Bad Request)"}
```

Guarded by `test_commit_result_names_the_failure_when_foldering_fails`, which forces
`list_folders` to raise and asserts the commit both succeeds *and* names the miss. A mutation
restoring the silent swallow reds it.

**B — fixed as a warning, not a rejection.** `commit` now returns a `warnings` entry naming any
`title`/`force_title` it cannot honour and stating the correct draft-time sequence. It is not a
hard reject because the commit itself is valid — only the caller's expectation about the title
is wrong. The `manage_hevy_routine` description now says both are draft-time only.

**The title counter — root cause corrected.** It is **not** the 484-workout 2024-25 backfill.
`build_title_context` counts faithfully; the anchors it counts *from* are stale:

| | |
|---|---|
| `config/training_phases.json` `current_started` | `2026-06-16` (N anchor) |
| `config/training_phases.json` `reset_epoch_date` | `2026-06-16` (Y anchor) |
| `EXPERIMENT_START_DATE` | `2026-09-06` (cycle-17 genesis) |

`deploy/restart_pipeline.py` never references this file, so both anchors survived eleven
resets — ADR-077's phase taxonomy governs DynamoDB partitions and has no jurisdiction over
config files. Measured live (read-only DDB, 2026-09-06):

```
anchor 2026-06-16: distinct performed=10 (Y=11)  push=2 (N=3)   <- the observed 'Foundation - Push - 3 - 11'
anchor 2026-09-06: distinct performed=0  (Y=1)   push=0 (N=1)
```

This PR hand re-anchors **`reset_epoch_date` only** to `2026-09-06`. `current`/`current_started`
are deliberately untouched: the phase advances only when Matthew says so, and only the
experiment counter Y zeroes on a reset. The next title therefore reads
**`Foundation - Push - 3 - 1`**, not `- 1 - 1` — N stays anchored to the phase. **#3671** owns
the durable fix (derive the anchor from `EXPERIMENT_START_DATE`, or give the reset ownership of
the config anchors), and makes this hand edit unnecessary.

**Also corrected in passing:** `_action_archive` said it did a "rename + folder-move". Hevy's
`folder_id` is create-only and `to_update_body` omits it, so the move never reached the wire.
The behaviour is unchanged (it cannot be fixed by API); the comment and the result now say so.
