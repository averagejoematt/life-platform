# `handovers/` — the live session pointer

This directory holds **exactly one tracked handover**: `HANDOVER_LATEST.md`, the driver the
next session reads first. Everything else is process exhaust and lives on the
**`session-archive` branch** of this repo (#1650, owner decision 2026-07-25 — an archive
branch in THIS repo, not a sibling repo).

`docs/ENGINEERING_STANDARDS.md` §1: *"Process exhaust stays out of the product tree.
Session handovers, RCA scratch, and review churn are engineering-log, not product — keep
only the live pointer in-tree."*

## Reading the archive

```bash
git fetch origin session-archive
git log origin/session-archive --oneline -- handovers/
git show origin/session-archive:handovers/HANDOVER_2026-07-21_Glass-Engine.md
git worktree add ../life-platform-sessions origin/session-archive   # browse the whole corpus
```

The archive branch is parented on `main` and the files keep their original `handovers/…`
paths, so `git log --follow` walks a handover's history straight through the split.
Nothing was rewritten; nothing was lost.

## Writing a handover (the `/wrap` ritual)

`/wrap` step (a) archives the outgoing `HANDOVER_LATEST.md` onto `session-archive` and
then overwrites `HANDOVER_LATEST.md` in place:

```bash
python3 scripts/archive_handover.py --slug <session-slug>   # --dry-run to preview
```

The script writes the archive commit with git plumbing — it never checks out
`session-archive` and never touches your working tree (worktree-pollution safe). It is
idempotent: re-running with the same target name is a no-op if the content is unchanged.

## What is gitignored here

`.gitignore` ignores `handovers/*` except `HANDOVER_LATEST.md` and this README — so a
dated handover left on disk after a wrap can never be re-committed to `main` by accident.

**Never merge `session-archive` into `main`.** It is an archive ref, not a feature branch.
