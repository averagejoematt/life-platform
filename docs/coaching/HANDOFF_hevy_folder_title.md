> **Filed as #3670; fixed by the PR that carries this file.** Moved here from the repo
> root on landing — the root holds only durable project docs (CLAUDE/README/CONTRIBUTING/
> SECURITY), and this belongs beside its work order.
> **One correction to the section below:** the title-counter inflation is NOT the 2024-25
> backfill. `build_title_context` counts correctly; its anchors in
> `config/training_phases.json` were frozen at 2026-06-16 and had survived eleven resets.
> #3671 owns the durable fix. See the Resolution section of
> `WORKORDER_HEVY_FOLDER_AND_TITLE.md`.

Two silent bugs in the Hevy routine commit path. Both confirmed from logs and source on
2026-09-07 — the diagnosis below is done, do not re-derive it. Full write-up with evidence,
call chain and acceptance list: `docs/coaching/WORKORDER_HEVY_FOLDER_AND_TITLE.md` — read it first.

## A. Every routine lands in the Hevy root folder instead of its type folder

`GET /v1/routine_folders` returns 400. Confirmed in CloudWatch
(`/aws/lambda/life-platform-mcp`, 2026-09-07T04:01:52.822Z, request
`6c5878b4-1977-4706-8de7-03d7f555127a`):

    [WARNING] list_folders failed; committing without folder: HTTP Error 400: Bad Request

`_ensure_folder()` (`mcp/tools_hevy_routine.py:90`) catches it, returns None, and the routine
is created with `folder_id: null`. The commit reports success because the commit *did* succeed —
only the foldering failed, silently, by design (`# noqa: BLE001`).

Suspected cause: `lambdas/training/hevy_write_client.py:289` uses `page_size=50`. Every other
collection endpoint uses 10 (exercise_templates is the exception at 100). Auth is ruled out
(`_request` raises HevyAuthError on 401/403 and did not); a bad path would 404. pageSize=50 is
the only anomaly in the request.

**Verify before changing code.** Run `python3 scripts/diag_hevy_folders.py` (already written,
read-only, no writes or folder creation). Ship the fix only if section A fails at 50 and passes
at <=10; section C also tells you whether the response-shape parser at
`mcp/tools_hevy_routine.py:101` matches, which is a second candidate defect if C reports MISS.

Then: `page_size: int = 50` -> `10`, and confirm a fresh `draft_custom` -> `commit` lands in its
type folder.

Two things NOT to chase:
- `dry_run` showing `"folder_id": null` is expected. `_ensure_folder` runs only on the commit
  path, so the preview is always null.
- Existing routines cannot be moved by API. `folder_id` is create-only in Hevy and
  `to_update_body` omits it deliberately (`hevy_compiler.py:219`). Root-foldered routines have
  to be dragged in the app. The fix applies to new routines only.

## B. `force_title` passed on commit is silently discarded

`force_title` is parsed at DRAFT time (`mcp/tools_hevy_routine.py:785`) and stored on
`ir.inputs_snapshot` (line 809). `_resolve_title_inputs()` (line 848) reads the snapshot and
never looks at commit args, so a `force_title` on `commit` is dropped without warning, the
compiler re-renders the convention title, and the call still returns `{"status": "committed"}`.
The caller believes a rename landed that did not.

Correct usage is `draft_custom(force_title=true, title=...)` -> `dry_run` -> `commit`. This is a
docs defect causing a caller error, not broken logic. Fix the `manage_hevy_routine` description
(it currently reads "A title you pass is ignored unless you also set force_title=true", which
implies commit honours the pair — say both are draft-time only), and make `commit` warn or
reject rather than silently discard.

## The thing that actually matters

Both bugs survived because a failure was swallowed and reported as success. Fixing `page_size`
fixes today's symptom. The durable fix is that `_ensure_folder` failures surface in the commit
RESULT, not only in a CloudWatch warning nobody reads — e.g.
`{"status": "committed", ..., "folder": "unfoldered: <reason>"}`. Please do that one too.

## Related, lower priority

`build_title_context` counts performed history, which still includes the 484-workout backfill
from the 2024-25 cut, so day 1 of a new block rendered `Foundation - Push - 3 - 11`. Every future
routine inherits the inflation. Bound the counter's window to the current block, or exclude the
pre-2026-09 backfill.
