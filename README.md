# session-archive — the ship's log

This branch is the **archive of `handovers/`**: one markdown file per Claude Code session,
2026-02 → present. It was split out of `main` by **#1650** so the product tree reads as
engineering, not transcript.

## What lives here

- `handovers/HANDOVER_<YYYY-MM-DD>_<Slug>.md` — one dated file per closed session.
- `handovers/archive/` — the older per-session files plus the pre-2026-07 CLAUDE.md
  session diary (`CLAUDE_MD_SESSION_DIARY_2026-07-03.md`).

## What is NOT here

`handovers/HANDOVER_LATEST.md` — the **live** driver for the current session — stays
tracked on `main`. That is the only handover the wrap ritual, `/uplevel`, the review
skills, `deploy/generate_review_bundle.py` and `scripts/check_residual_queue.py` resolve.

## How to read it

```bash
git fetch origin session-archive
git log origin/session-archive --oneline -- handovers/          # the log of the log
git show origin/session-archive:handovers/HANDOVER_2026-07-21_Glass-Engine.md
git worktree add ../life-platform-sessions origin/session-archive   # browse the whole corpus
```

This branch's first commit is parented on `main`, and the files keep their original
`handovers/…` paths — so `git log --follow` walks a handover's full history straight
through the split. Nothing was rewritten and nothing was lost.

## How it grows

`/wrap` step (a) appends the outgoing handover here via `scripts/archive_handover.py`
(on `main`), which writes the commit with git plumbing — it never checks this branch out
and never touches the working tree.

**Never merge this branch into `main`.** It is an archive ref, not a feature branch.
