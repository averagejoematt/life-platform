# Synced chat skills — how the claude.ai copy is kept in lockstep with the repo (#5086)

Claude Desktop and Claude mobile do not read this repo. They run **account skills** stored by
claude.ai. One of them, `coach-session`, is the training coach; its source is
`.claude/skills/coach-session/SKILL.md` in this repo (the ONE source — `docs/coaching/COACH_SESSION.md`
is now a pointer to it). This page records how the account copy gets there, how drift is detected,
and the procedure that refreshes it.

## What was found (2026-10-19, read-only)

- The desktop app keeps two local copies of every account skill:
  - `~/.claude/skills/synced/<org-id>_<account-id>/coach-session/SKILL.md`
  - `~/Library/Application Support/Claude/local-agent-mode-sessions/skills-plugin/<org-id>/<account-id>/skills/coach-session/SKILL.md`

  They were byte-identical (244 lines).
- The `synced/<org>_<account>/` directory is written BY the app. Evidence:
  - It has a `manifest.json` listing every account skill with a server-side `skillId`, `source` and
    `updatedAt`. For coach-session that is `source: plugin`, `updatedAt` 2026-09-28T02:15:15Z.
  - It has a `.last-complete-round` stamp, rewritten on each sync round (the last one was the morning
    of 2026-10-19).
  - The local `SKILL.md` was written at 2026-09-28 02:21Z, six minutes after the server-side
    `updatedAt`.

  The sync runs **down, from the account to this machine**. That is an inference from those timestamps.
  Nobody watched a sync round overwrite a local edit, and this lane did not try it, because trying it
  means editing the owner's live skill.
- So a local file copy is **not** a sync procedure. An edit to the synced file would be overwritten on
  the next round, or would never reach claude.ai, mobile or another machine. **The account copy can only
  be replaced through the claude.ai UI.** That is an owner act; no lane does it.
- At filing, the synced copy still described the retired v0.4 four-session program, `draft_custom` as
  the normal flow, a role-play advisory board and a "remind him to git commit" step. The repo copy
  had moved on separately. The two had drifted both ways.

## The drift check

```bash
python3 scripts/check_synced_skill_drift.py            # discovers both local copies under ~
python3 scripts/check_synced_skill_drift.py --synced <path/to/SKILL.md>
SYNCED_SKILL_PATHS=<a>:<b> python3 scripts/check_synced_skill_drift.py
```

- It compares `name`, `description` and the body, with whitespace normalised, so a re-wrapped
  paragraph is not drift. Exit 0 means every copy found matches. Exit 1 means drift: each drifted copy
  is named, with a diff. Exit 2 means the repo source is missing.
- On a machine without the desktop app (CI included) it prints
  `skipped: no synced copy on this machine` and exits 0. That is a stated skip, not a pass.
- It never writes a synced copy.

## The refresh procedure (owner, in the claude.ai UI)

Run this after any merged change to `.claude/skills/coach-session/SKILL.md` reaches `main`:

1. Build the upload from `main`:
   `python3 scripts/check_synced_skill_drift.py --package ~/Downloads/coach-session.zip`.
   The zip holds `coach-session/SKILL.md`, with only `name` and `description` in its frontmatter.
   `allowed-tools` is a Claude Code key, so it is stripped.
2. In claude.ai, open **Settings → Capabilities → Skills** and find `coach-session`. Replace it with
   the zip: use the skill's own upload/replace action if it shows one, otherwise remove it and
   **Upload skill** with the zip. The menu labels may differ from these. What matters is that the
   account ends with one `coach-session` skill built from this zip.
3. Wait for the desktop app's next sync round, or restart the app. Then run
   `python3 scripts/check_synced_skill_drift.py`. It should report
   `coach-session: 2 of 2 synced copies match the repo source`. If it still reports drift, the upload did
   not replace the account copy, or the sync has not run yet.
4. Paste that line into the issue or PR that changed the skill.

Removing and re-uploading may give the skill a new server-side `skillId`. Nothing in this repo keys on
that id.

## Why not a local copy

The task brief asked for a local copy to be run once *if* the sync were a local file copy. It is not:
the local files are downstream of the account, as shown above. So the synced files were left untouched,
and the before-state the drift check reported is pasted on the #5086 PR. The after-state comes
from step 3, once the owner has uploaded.
