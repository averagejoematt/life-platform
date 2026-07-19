Close out the current session: archive the outgoing handover, replace the CLAUDE.md
session-status block, update the persistent memory system, sweep doc impact, distill a build beat if
warranted, and commit the wrap (the "#365 wrap convention").

## Arguments: $ARGUMENTS

Optional: a short theme/slug for this session (e.g. `mobile-bug-bash`) to seed the
handover filename and titles. If empty, derive one from what the session actually did.

## Instructions

Run these five steps **in order**. Each has a hard guardrail — read it before acting.

### (a) Archive the outgoing handover, write the new one

1. Read the current `handovers/HANDOVER_LATEST.md` — pull its session date and slug from
   its title line (existing files follow `HANDOVER_<YYYY-MM-DD>_<Slug>.md`, e.g.
   `handovers/HANDOVER_2026-07-06_R22-review.md`).
2. `git mv handovers/HANDOVER_LATEST.md handovers/HANDOVER_<that-date>_<that-slug>.md` —
   this is a straight rename, the content does not change.
3. Write a **new** `handovers/HANDOVER_LATEST.md` for the session that's ending now. Match
   the shape of the archived files: the driving instruction/prompt, what shipped (PRs,
   merged/deployed status), what was verified (tests, smoke, live checks), gotchas hit,
   and the residual/next-picks queue. This file is the live driver the next session reads
   first (see `/uplevel` Phase 0 and `docs/README.md`).

### (b) Replace — never stack — the CLAUDE.md session-status block

`CLAUDE.md` has exactly ONE live block, under
`## Session status (the ONE live block — replace, don't stack)`. It has two parts: the
wrap-convention paragraph (boilerplate — leave it as-is) and one `**Verified:** ...`
paragraph beneath it (the actual content).

- **Overwrite that one `**Verified:**` paragraph in place.** Do not append a second
  paragraph, a diff-style addendum, or a "previous session" trailer — the block holds
  exactly one paragraph, full stop. Anything durable that doesn't fit a terse one-paragraph
  summary belongs in memory (step c) or, if it's a load-bearing repo convention, in
  `docs/CONVENTIONS.md` — not stacked here.
- The new paragraph: date, the instruction that drove the session, what shipped (PR
  numbers), deploy/test verification, gotchas, and the next-picks queue — the same shape
  as the paragraph you're replacing (see the current one for the pattern before you
  overwrite it).

### (c) Update the persistent memory system

Memory lives outside the repo at
`~/.claude/projects/-Users-matthewwalker-Documents-Claude-life-platform/memory/` — it is
NOT git-tracked and is a separate step from the commit in (f).

- Durable, reusable lessons (a gotcha that will recur, an incident narrative, a completed
  program's outcome) go to a topic file there — `project_*.md` for a body of work,
  `feedback_*.md` for a working-style correction, `reference_*.md` for a technical
  reflex/workaround — cross-linked with `[[other_topic]]` where relevant.
- Add or update ONE line per touched topic under the matching section of `MEMORY.md`
  (e.g. `## Active Work`), pointing at the topic file. Don't let a topic file exist
  un-indexed.
- **Orphan/broken-link gate (#1259) — run this every wrap; it must print nothing.**
  A topic file reachable from neither `MEMORY.md` nor `project_shipped_archive.md` is
  invisible to every future session (repo CI can't own this — the memory dir is outside
  the repo). Index any `ORPHAN:` line before closing (c):
  ```bash
  cd ~/.claude/projects/-Users-matthewwalker-Documents-Claude-life-platform/memory/
  for f in *.md; do [ "$f" = MEMORY.md ] && continue; base="${f%.md}"; \
    grep -qF "$base" MEMORY.md project_shipped_archive.md || echo "ORPHAN: $f"; done
  ```
  (Match the basename, not `$f` — an index entry may reference a topic as a `[[wikilink]]`
  without the `.md`, and a naive `.md` grep would false-flag it.)
- **Rule of placement:** session-specific narrative → `handovers/` (step a). Durable
  lessons/reflexes → memory topic files (this step) or `docs/CONVENTIONS.md` if it's a
  load-bearing repo-wide rule. The CLAUDE.md status block (step b) is a terse pointer,
  never the primary home for either.

**Close step (c) with the memory backup** — snapshot the laptop-only memory dir to
private, versioned S3 (wiki continuity contract; the laptop is the only other copy):
```bash
aws s3 sync ~/.claude/projects/-Users-matthewwalker-Documents-Claude-life-platform/memory/ \
  s3://matthew-life-platform/claude-memory-backup/ --region us-west-2
```

### (d) Build beat OR explicit skip — this step always produces one of the two (#736)

Follow `docs/content/BUILD_DISPATCH_CHECKLIST.md` exactly. This is a **wrap gate**: the
wrap is incomplete until it has produced EITHER a beat OR an explicit skip line — silent
omission is not an outcome.

- **Eligibility:** only write a beat if this session's work is merged to `main` AND
  deployed (verify: PRs actually merged, `main == live` for the touched surfaces). A PR
  that's still open, a deploy that's staged, or a plan for next session is NOT eligible.
- **If not eligible (or nothing public-worthy shipped): record the skip explicitly.**
  The new `handovers/HANDOVER_LATEST.md` from step (a) must carry one line —
  `**Build beat:** none — <one-clause reason>` (e.g. "PRs open, merges await Matthew").
  An empty week is honest; an unexplained empty slot is not. Do not force a beat.
- **If eligible:** add the beat (below) AND put `**Build beat:** <beat id>` in the
  handover, so every handover records the gate's outcome either way.
- The beat itself: append one object to `beats` in `site/story/build/beats.json` with fields
  `id`, `date`, `title`, `shipped`, `gotcha`, `honest_miss`, `prs` (schema + example in the
  checklist). **`prs` entries are `{"label": "PR #953", "url": "https://github.com/…/pull/953"}`
  objects, never bare strings** (string PRs redded `test_build_dispatches` for every
  concurrent session, 2026-07-10). Distill from the new `HANDOVER_LATEST.md` you just
  wrote in step (a).
- **One beat max per session** even if several things shipped — pick the story, mention
  the rest in a clause.
- Numbers in the beat must come from the handover/PR/measured output (ADR-104 honesty
  bar) — never invented.
- Run `python3 scripts/content_policy_scan.py && python3 scripts/validate_beats.py`
  locally before committing (#953 — the beats schema validator catches malformed `prs`
  before it reds `test_build_dispatches` repo-wide; CI re-checks both on every push).

### (e) Doc-impact sweep OR explicit skip — a wrap gate, same shape as (d)

The wiki contract (CONVENTIONS §8): every shipped change either updates the wiki pages
it invalidates, or the handover records why none were needed. **Silent omission is not
an outcome.**

- For each item shipped this session, name the canonical docs it touches (deploy paths →
  QUICKSTART/CONVENTIONS; data model → SCHEMA; algorithms → docs/engines/; new/retired
  MCP tools → regenerate the catalog; new ADR → `scripts/generate_adr_index.py --apply`;
  secrets/accounts → SECRETS_MAP/ACCOUNTS; site → SITE_AUTHORING/SITE_MAP_AND_INTENT).
  Update them, bump each touched page's `Verified:` date.
- **If something load-bearing was retired** (script/service/pattern): add a rule to
  `docs/_lint/tombstones.txt` in the same commit — that is what stops every other page
  from teaching the dead path (the #781 lesson).
- Run the machinery before the wrap commit — all must be green:
  ```bash
  python3 deploy/sync_doc_metadata.py --apply
  python3 scripts/check_doc_links.py && python3 scripts/check_doc_tombstones.py && \
  python3 scripts/check_doc_index.py && python3 scripts/generate_adr_index.py --check
  ```
- The new `handovers/HANDOVER_LATEST.md` must carry one line either way:
  `**Docs:** <pages updated>` or `**Docs:** none needed — <one-clause reason>`.

### (e2) Green-main gate — a wrap gate, same shape as (d)/(e) (#1327)

A wrap may not declare "main GREEN" over a badge it never read (2026-07-18: a status
block said `main GREEN (1c641b6a)` while that sha's own push run had FAILED).

- Run `python3 scripts/check_main_green.py` before the wrap commit.
  - Exit 0 (latest completed non-cancelled CI/CD run on main succeeded): done.
  - Exit 1: either fix main now, or write the explicit decode line into the handover —
    `**Main:** red — <one-line cause>` (e.g. "pre-existing Withings DLQ transient") —
    then re-run with `--decoded`. **Silent omission is not an outcome.**
- The handover carries one line either way: `**Main:** green (<sha>)` or
  `**Main:** red — <decode>`.

### (e3) Stash + hook hygiene gate — a wrap gate, same shape as (d)/(e)/(e2) (#1326)

The stash stack and the installed pre-commit hook are both **local, untracked**
state that git never refreshes on `pull`/`merge` — a stale entry in either can sit
invisible for weeks (2026-07-18: a stash from several merges back sat on the
shared stack while 3+ concurrent worktrees were active — the documented
stash-pop-race incident class; the installed hook kept calling a script #818
deleted, fail-open via `[[ -f ]]`, so its doc-sync half silently no-oped).

- Run `git stash list`. It **must print nothing**, or every entry must be
  explained (inspected via `git stash show -p stash@{N}` and either dropped or
  intentionally kept with a one-line reason). Memory rule: stash is BANNED in
  concurrent sessions — if you didn't put it there this session, inspect and
  drop it, don't leave it for the next session to trip over.
- Run `python3 deploy/session_postflight.py` and confirm the `hook freshness`
  line is 🟢. If 🔴 (stale or not installed), run `bash scripts/install_hooks.sh`
  and re-check before closing the wrap.
- The handover carries one line either way: `**Stash/hooks:** clean` or
  `**Stash/hooks:** <what was found + what you did about it>`.

### (f) Commit the wrap

Stage the repo-tracked wrap artifacts only (memory-dir changes from step (c) are outside
git and are never part of this commit):

```bash
git add handovers/ CLAUDE.md docs/ site/story/build/beats.json   # beats.json only if (d) fired; docs/ only if (e) touched pages
git commit -m "$(cat <<'EOF'
docs(wrap): <short session theme> (<n items/PRs shipped>)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

Match the style of prior wrap commits (e.g. `28a5d603 docs(wrap): mobile bug-bash
session — status block, handover, build beat (9 R22 smalls #836–#845)`).

## Guardrails (verbatim from CLAUDE.md — do not relax these)

- **Replace, don't stack.** CLAUDE.md's status block is one paragraph, always.
- **One live block.** `handovers/HANDOVER_LATEST.md` is the only "current" handover;
  everything else is archived under its dated name.
- **Merged-work-only dispatch.** A build beat narrates what shipped and is live — never
  a plan, never an open PR.
- **Beat or explicit skip, never silence (#736).** Every wrap's handover carries a
  `**Build beat:** <id or "none — reason">` line; step (d) cannot be skipped implicitly.
- **Docs or explicit skip, never silence (wiki contract).** Every wrap's handover carries
  a `**Docs:** <pages or "none needed — reason">` line; step (e) cannot be skipped
  implicitly, and the wiki checkers must be green at the wrap commit.
