---
name: wrap
description: "Close out the current session: run the gate battery, archive the outgoing handover, replace the CLAUDE.md status block, update memory, sweep the backlog and commit. Use at the end of a working session, or when asked to wrap up."
user-invocable: true
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, Task, Agent, TodoWrite
---

Close out the current session: archive the outgoing handover, replace the CLAUDE.md
session-status block, update the persistent memory system, sweep doc impact, distill a build beat if
warranted, and commit the wrap (the "#365 wrap convention").

## Arguments: $ARGUMENTS

Optional: a short theme/slug for this session (e.g. `mobile-bug-bash`) to seed the
handover filename and titles. If empty, derive one from what the session actually did.

## Instructions

The wrap runs in **four phases — gather → write → verify → commit** (#3007). The
lettered step ids ((a)–(f), (e2)–(e12); (e6) never existed) are stable anchors — tests
and the CONVENTIONS §9 gate registry point at them — so they name gates and duties, not
an execution order. Each step has a hard guardrail — read it before acting.

## Phase 1 — Gather: one batched gate run, before anything is written

Run the whole battery once:

```bash
python3 scripts/wrap_gates.py
```

It runs every gate that does NOT read the finished handover — the (e2) green-main
check, the (e5) stash + postflight pair, the (e7) filing-contract linter (bare,
blocking-by-default), the (e10) alarm board, the (e11) warning triage, and the (e) doc
checkers — in parallel (they are independent and several are network-bound; ~10–15s
total), reports **all failures together**, and prints a **draft marker-line block**
with each script-determined outcome pre-filled. Every gate's own semantics, exit codes
and degrade behaviour (`UNVERIFIED`, fail-open) are unchanged and surfaced verbatim in
the batch output — this is batching, not weakening.

- Fix what is red using the owning step's remediation below, then re-run the batch. An
  honest `--decoded`-style acknowledgement still happens on the owning step's own terms.
- Carry the draft block into Phase 2 and write the handover **once** — correct the
  pre-filled lines and fill every `<placeholder>`; the draft is a start, never a record.

## Phase 2 — Write everything once (steps (a)–(e))

The handover is written a single time in step (a), carrying ALL the gate marker lines
(the corrected Phase 1 draft plus the session-judgment lines from (d), (e), (e3),
(e8), (e9), (e12)). Phase 3 asserts each line is present (#3006) — do not plan to come
back and append them one gate at a time; that treadmill is what #3007 removed.

### (a) Archive the outgoing handover, write the new one

**Dated handovers live on the `session-archive` branch, NOT on `main` (#1650).** `main`
tracks exactly one handover — `handovers/HANDOVER_LATEST.md`, the live pointer — plus
`handovers/README.md`. `.gitignore` enforces it, and `tests/test_archive_handover.py` is
the ratchet. Never `git mv` the outgoing handover into a dated file on `main`; that is the
old flow and it is what grew the directory to 489 files.

1. Read the current `handovers/HANDOVER_LATEST.md` — pull its session date and slug from
   its title line (archived files follow `HANDOVER_<YYYY-MM-DD>_<Slug>.md`, e.g.
   `HANDOVER_2026-07-06_R22-review.md`).
2. Archive it onto `session-archive`:
   ```bash
   python3 scripts/archive_handover.py --slug <that-slug>   # add --dry-run first to preview
   ```
   The script builds the archive commit with git plumbing — it never checks out
   `session-archive`, never moves `HEAD`, and never touches the working tree (safe with
   concurrent worktrees active). It derives the date from the handover, refuses rather than
   clobbering an existing entry, is a no-op on identical content, and pushes
   `session-archive` when it succeeds. If the push fails (offline, no remote), the commit
   is safe on the local ref — re-run `git push origin session-archive` before closing (f).
   Read the archive later with `git show origin/session-archive:handovers/<name>.md` (see
   `handovers/README.md`).
3. **Overwrite** `handovers/HANDOVER_LATEST.md` in place with the handover for the session
   that's ending now — the file stays at the same path, only its content changes. Match
   the shape of the archived files: the driving instruction/prompt, what shipped (PRs,
   merged/deployed status), what was verified (tests, smoke, live checks), gotchas hit,
   and the residual/next-picks queue. This file is the live driver the next session reads
   first (see `/uplevel` Phase 0 and `docs/README.md`). **Write it complete in one pass:**
   include every gate marker line — the corrected Phase 1 draft block plus the
   session-judgment lines each gate step below defines. Phase 3's
   `scripts/check_handover_lines.py` asserts every marker line is present (#3006), so a
   missing line now fails the wrap loudly instead of reading complete.
4. **Standing-alarms checklist (#1329, folded into step (e10)):** the full alarm-board
   reconcile — enumerate every CloudWatch alarm in ALARM state and require a citation
   for anything red >72h — now lives in step (e10) below and supersedes this item's
   original freshness/staleness-only scope (#1959: the #1329 version was scoped and
   advisory — 3 alarms sat red 9–15 days with one incident row between them). Do
   step (e10) instead of hand-checking here. Manual-rotation SECRET staleness is
   NOT a CloudWatch alarm (Secrets Manager `DescribeSecret`, not `describe-alarms`)
   so it's still worth a glance on its own — see `docs/SECRETS_ROTATION.md`
   "Monitoring" + `remediation/agent.py`'s `stale_secret_escalations` — but the
   alarm board itself is (e10)'s job now, not this item's.

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
  A topic file reachable from none of `MEMORY.md`, `project_shipped_archive.md` or an
  `INDEX_*.md` roll-up is invisible to every future session (repo CI can't own this — the memory dir is outside
  the repo). Index any `ORPHAN:` line before closing (c):
  ```bash
  cd ~/.claude/projects/-Users-matthewwalker-Documents-Claude-life-platform/memory/
  for f in *.md; do [ "$f" = MEMORY.md ] && continue; base="${f%.md}"; \
    grep -qF "$base" MEMORY.md project_shipped_archive.md INDEX_*.md || echo "ORPHAN: $f"; done
  ```
  (2026-08-15: the grep omitted `INDEX_*.md` and so reported **98 false orphans** every
  wrap — the ~55-entry review-discipline set is rolled up in `INDEX_review_discipline.md`,
  which `MEMORY.md` points at rather than listing inline. A gate that cries wolf 98 times
  is one nobody reads; true orphan count was zero.)
  (Match the basename, not `$f` — an index entry may reference a topic as a `[[wikilink]]`
  without the `.md`, and a naive `.md` grep would false-flag it.)
- **Body-follows-index rule (#1342)** — when a `MEMORY.md` index line is corrected (a stale
  fact hedged or fixed), the SAME wrap rewrites the topic file's BODY too. An index-only
  patch is not an outcome: a corrected index line over a still-wrong body is worse than no
  fix at all — the next session trusts the index, opens the body for depth, and gets the
  stale directive anyway (this is exactly how `project_launch_dates.md`'s "always use
  2026-04-01" survived three genesis re-anchors after its index line was hedged).
- **Memory-body fact-drift grep (#1342) — run this every wrap; review any hit before
  closing (c).** `check_doc_facts.py` guards the repo doc surface for stale genesis/
  date/stack-name literals but structurally can't see this dir (it's outside git) — this
  is the wrap-time equivalent for the memory bodies, checked against the same ground
  truth (`lambdas/common/constants.py`):
  ```bash
  python3 scripts/check_memory_body_facts.py
  ```
  Fix any flagged body (a categorical genesis/date directive disagreeing with the live
  `EXPERIMENT_START_DATE`, or a retired-stack-ownership literal — extend
  `STALE_STACK_CLAIMS` in the script when a new ownership move needs policing) before
  closing (c). The script no-ops harmlessly if the memory dir isn't present (e.g. a
  fresh machine) — it is a session reflex, not something repo CI can enforce.
- **Rule of placement:** session-specific narrative → `HANDOVER_LATEST.md` → the
  `session-archive` branch at the next wrap (step a). Durable
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
  `id`, `date`, `title`, `shipped`, `why_it_mattered`, `gotcha`, `honest_miss`, `prs` — all FOUR
  prose sections are required and `validate_beats.py` rejects a beat missing any (#1120); this
  list omitted `why_it_mattered` until 2026-08-09, which cost a wrap one validation cycle
  (schema + example in the
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
- Run the machinery before the wrap commit — all must be green (the four checkers
  already ran in the Phase 1 batch; re-run them individually only while fixing a red):
  ```bash
  python3 deploy/sync_doc_metadata.py --apply
  python3 scripts/check_doc_links.py && python3 scripts/check_doc_tombstones.py && \
  python3 scripts/check_doc_index.py && python3 scripts/generate_adr_index.py --check
  ```
  **`sync_doc_metadata.py --apply` is the doc-sync literal treadmill** (#3007): it
  stamps ~8 unrelated docs (`alarm`/`lambda_count`/`tool_count` doc headers — the
  counters themselves moved to the generated `lambdas/web/platform_counts.py` in #3101)
  and concurrent PRs collide on those doc-header literals — the driver reconciles them at merge time
  via `/reconcile-branch`. Run it deliberately at the wrap, never mid-session from a
  worktree, and expect its diff to be the wrap commit's, not a feature branch's.
- The new `handovers/HANDOVER_LATEST.md` must carry one line either way:
  `**Docs:** <pages updated>` or `**Docs:** none needed — <one-clause reason>`.
- **Decisions gate (#1343) — same silent-omission-is-not-an-outcome shape.** Ask: did this
  session make a governance-consequential decision (an architecture/data/deploy-posture
  choice, not just an implementation detail) that isn't already in `docs/DECISIONS.md`?
  If yes, file the ADR in the same commit and run `scripts/generate_adr_index.py --apply`
  (already required above). The handover carries one line either way:
  `**Decisions:** ADR-NNN filed` or `**Decisions:** none needed — <one-clause reason>`.

## Gate reference — the lettered wrap gates ((e2)–(e12))

Each step below is one gate's contract and remediation. The (e2)/(e5)/(e7)/(e10)/(e11)
checks **already ran in the Phase 1 batch** — reuse its output, and re-run a script
individually only while fixing a red. (e3)/(e4)/(e8)/(e9) are session duties done while
writing in Phase 2. (e4)/(e12) — plus the line-presence assertion — are re-checked
mechanically in Phase 3. Every gate's marker line lands in the ONE Phase 2 handover
write.

### (e2) Green-main gate — a wrap gate, same shape as (d)/(e) (#1327)

A wrap may not declare "main GREEN" over a badge it never read (2026-07-18: a status
block said `main GREEN (1c641b6a)` while that sha's own push run had FAILED).

- Run `python3 scripts/check_main_green.py` before the wrap commit (Phase 1 batch runs
  this; re-run it standalone only while fixing a red).
  - Exit 0 (latest completed non-cancelled CI/CD run on main succeeded): done.
  - Exit 1: either fix main now, or write the explicit decode line into the handover —
    `**Main:** red — <one-line cause>` (e.g. "pre-existing Withings DLQ transient") —
    then re-run with `--decoded`. **Silent omission is not an outcome.**
  - The gate also classifies the two STRANDED deploy states (#1901,
    CONVENTIONS.md §4d) — a run parked `waiting` at the production approval gate
    (> ~2h), or the R8-ST6 Plan-red/Deploy-skipped shape. These are NOT ordinary
    reds: the decode line names the class and the pending recovery step
    (`deploy/approve_deployment.sh` / the CDK deploy + `deploy_all=true` dispatch),
    e.g. `**Main:** stranded — run <id> waiting at the production gate, #1901 class`.
- The handover carries one line either way: `**Main:** green (<sha>)`,
  `**Main:** red — <decode>`, or `**Main:** stranded — <decode>`.

### (e3) Incident gate — a wrap gate, same shape as (d)/(e)/(e2) (#1332)

Every session ends with either a `docs/INCIDENT_LOG.md` row for any incident-class event
that happened this session, or an explicit `**Incidents:** none` line — silent omission is
not an outcome (mirrors the build-beat gate, #736). This closed the gap where ≥6 site
auto-rollback firings and several other incident-class events lived only in memory topic
files or a handover clause while `docs/INCIDENT_LOG.md` looked like a clean month.

- **Incident-class events**: an auto-rollback firing (site-deploy or a Lambda smoke gate),
  main red for >1h, a data gap discovered, or a quota/budget-tier event — real OR a false
  positive (a false alarm still cost investigation time and belongs in the record, tagged
  as such).
- For each one, add a row to the Incident History table in `docs/INCIDENT_LOG.md` (match
  the existing columns: Date | Severity | Summary | Root Cause | TTD | TTR | Data Loss?)
  and bump the `Last updated:` line at the top of the file.
- The new `handovers/HANDOVER_LATEST.md` must carry one line either way:
  `**Incidents:** <N row(s) added — one-clause list>` or `**Incidents:** none`.
- A live auto-rollback firing already publishes to SNS — this row is the audit half of
  that event. Add it the SAME session the firing happens (or the next wrap with visibility
  into it) — do not let it wait for a quarterly backfill.

### (e4) Residual-queue gate — a wrap gate, same shape as (d)/(e)/(e2)/(e3) (#1340)

Every residual/next-picks bullet in the new `handovers/HANDOVER_LATEST.md` must either
cite a GitHub issue number or carry an explicit `not-work — <reason>` tag — silent
omission fails this checklist. The residual queue is not a sanctioned shadow backlog:
ADR-099's "new work enters as an issue or not at all" invariant has to hold here too, or a
parked defect gets independently re-discovered (and re-paid-for) by a later review.

- Before closing the wrap, run the gate against the handover you just wrote in step (a)
  (the Phase 3 verify batch runs this):
  ```bash
  python3 scripts/check_residual_queue.py
  ```
  It must print `OK` — zero ungated bullets.
- If a bullet is a real, unfiled follow-up: file it (`gh issue create …`, ADR-099 shape),
  then cite its number in the bullet. If it's a standing ops reminder or a decision only
  Matthew can make (not a backlog item), tag it `not-work — <one-clause reason>` instead
  of inventing an issue for it.

### (e5) Stash + hook hygiene gate — a wrap gate, same shape as (d)/(e)/(e2)/(e3)/(e4) (#1326)

The stash stack and the installed pre-commit hook are both **local, untracked**
state that git never refreshes on `pull`/`merge` — a stale entry in either can sit
invisible for weeks (2026-07-18: a stash from several merges back sat on the
shared stack while 3+ concurrent worktrees were active — the documented
stash-pop-race incident class; the installed hook kept calling a script #818
deleted, fail-open via `[[ -f ]]`, so its doc-sync half silently no-oped).

- Run `git stash list` (the Phase 1 batch runs it). It **must print nothing**, or every entry must be
  explained (inspected via `git stash show -p stash@{N}` and either dropped or
  intentionally kept with a one-line reason). Memory rule: stash is BANNED in
  concurrent sessions — if you didn't put it there this session, inspect and
  drop it, don't leave it for the next session to trip over.
- Run `python3 deploy/session_postflight.py` (also in the Phase 1 batch) and confirm the `hook freshness`
  line is 🟢. If 🔴 (stale or not installed), run `bash scripts/install_hooks.sh`
  and re-check before closing the wrap.
- The handover carries one line either way: `**Stash/hooks:** clean` or
  `**Stash/hooks:** <what was found + what you did about it>`.

### (e7) Backlog-hygiene gate — a wrap gate, same shape as (d)/(e)/(e2)/(e3)/(e4)/(e5) (#1870, blocking since #1872)

The ADR-099 filing contract is only real if something re-reads it after filing. #1863
measured the gap: `scripts/check_story_labels.py`'s `model:*` rule was the ONLY
validation a filed issue ever got, so #1858 and #1859 — filed mid-session on 2026-07-27
with no milestone, no score line and no `## Outcome` — were invisible to every ranked
query and nothing noticed. That script's single rule is now absorbed and it is deleted
(#1872) — this gate is the only filing-contract check.

- Run (the Phase 1 batch runs exactly this bare, blocking invocation):
  ```bash
  python3 scripts/check_backlog_hygiene.py
  ```
  It lints the whole open corpus against the ADR-099 amendment (#1865): one `type:*` /
  `area:*` / `model:*`, `prio:*` + a milestone on work issues, a `## Outcome` naming a
  sanctioned audience, 3–5 `## Acceptance` boxes, the canonical `**Score:**` line whose
  `→ <milestone>` matches the real one, the `**Epic:**` link, epic `## Stories` coverage,
  `Now`-queue liveness, and stale `Later` issues.
- **Blocking by default (#1872, the ADR-108 promotion pattern):** #1867 landed advisory
  deliberately (the corpus was known-dirty); #1868 backfilled it to zero violations, #1872
  re-measured that clean state held and flipped the default to exit 1 on any violation —
  see the dated ADR-099 amendment in `docs/DECISIONS.md` for the measured evidence.
  A printed violator on an issue this session filed, touched or closed may not be left unfixed.
  `--advisory` is available as an explicit opt-out when you need the report without the
  exit code (e.g. the (e9) `later_staleness` sweep below).
- **Live-fetch failure stays fail-open even blocking:** if `gh` isn't authenticated/
  reachable from this session, the linter fails open (prints a skip note, exits 0) — a
  missing `gh` auth or no network must never wedge the wrap. Note that in the handover
  rather than silently skipping the check.
- Its `now_liveness`, `now_lane_coverage` and `later_staleness` findings are not defects —
  they are (e9)'s input. Carry them there rather than fixing them here. Since #3254
  `now_liveness` prints its own derived remedy (the issues to promote and both edits each
  one needs), so (e9) is execution, not diagnosis.
- **The bare invocation is lane-blind on purpose** (it is the corpus-wide contract check).
  When (e9) acts on the queue, re-run it as `--lane <sonnet|opus|fable>` for the session's
  own model — the count otherwise includes stories the running model cannot start (#3254).

### (e8) Closure-comment gate — a wrap gate, same shape as (d)/(e)/(e2)/(e3)/(e4)/(e5)/(e7) (#1870)

Every issue closed this session gets an outcome verdict, or the wrap is incomplete —
**silent omission is not an outcome.** #1863 measured the hole: **53 of the last 60 closed
issues have zero comments**, and the ownership gap is structural — `issue-filer.md` never
closes issues, `worktree-implementer.md` may not touch them, and `Fixes #N` closes
silently. ADR-099's amended closure contract names the owner: **the session that merges the
PR, enforced at `/wrap`** — the only actor holding the diff and the live evidence at the
same moment. This is the ADR-105 loop finally closed on a product forecast, not just a
health one.

- List what closed this session, then comment on each:
  ```bash
  gh issue list -R averagejoematt/life-platform --state closed \
    --search "closed:>=$(date -u +%F)" --json number,title,stateReason
  gh issue comment <N> --body "$(cat <<'EOF'
  **Shipped:** <what changed> · PR #N · <live evidence>
  **Outcome:** <realized|partial|not-realized> — <did the ## Outcome sentence come true?>
  EOF
  )"
  ```
  Those two lines are the contract's shape verbatim (ADR-099 amendment ¶3) — don't
  re-invent them.
- `not-realized` and `partial` are legitimate, expected verdicts; recording one honestly is
  the entire point. **Under ADR-104, a `realized` verdict you did not actually verify is
  the specific failure this contract exists to prevent** — if the live evidence isn't in
  hand, write `partial` with what's missing. A blank comment is better than a fabricated one.
- A `not planned` close gets the **same two lines** with a one-clause reason (e.g.
  `**Shipped:** nothing — superseded by #1866` / `**Outcome:** not-realized — the outcome
  is now #1866's`).
- **Do not backfill older closures.** The amendment settled it: closed stories are
  going-forward-only, because reconstructing them would be AI guesswork presented as
  record. #1873 owns the ~23 closed epics.
- The handover carries one line either way: `**Closures:** #N, #M commented` or
  `**Closures:** none — no issues closed this session`.

**The closure DoD (#3318) — the same closures, audited against the contract.** Session K's
audit found 5 escapes in ~60 closes that the (e8) comment alone cannot catch: a stray
`Fixes` closing an issue whose author then wrote "stays OPEN" *after* `closedAt` (#2848), a
scope assertion posted hours after the close (#2670), and closing comments naming a
residual with no carrier (#2938, #2921, #3208 — the #2845 shape). The rules are the
registry `scripts/closure_contract.py` (rendered into `docs/CONVENTIONS.md` §4a2, never
copied); this step applies them to THIS session's closures only — no new standing ritual.

- The Phase 1 batch already ran `python3 scripts/closure_sweep.py --session` (the window is
  `closed:>=` today UTC, the same list as above). Before the (e8) comments exist, every
  issue it lists as `no-outcome-verdict` is simply the (e8) to-do; **after** commenting,
  re-run it and read the other codes: `unhomed-residual` means a closing comment named a
  residual and disposed it nowhere — fix the comment (carrier `#N`, fold onto a named open
  issue `#N`, or `not-work — <home>`); `post-close-comment` / `post-close-assertion` means
  the issue was still being worked after it closed — reopen it or disposition it (a dated
  `DISPOSITIONED_ESCAPES` entry in the registry, with a reason); `epic-children-open` means
  an epic closed over an open child — reopen the epic or re-home the child.
- Posture is **advisory** (`warn`: the sweep exits 0 whatever it finds) until the flip bar
  in the registry docstring is met on real wraps; a printed hit on an issue this session
  closed may still not be left undispositioned — the exit code is not the contract, the
  line is.
- The sweep's verdict rides the (e8) line above rather than adding a thirteenth marker: after
  the comments, the `**Closures:**` line reads `#N, #M commented · DoD: scanned N, hits K —
  <each hit's disposition>` (or `· DoD: unverified — GitHub unreachable`, the (e7) degrade
  shape). The battery itself is the dead-man for the machinery: `wrap_gates.py` cannot
  complete its gather phase if `scripts/closure_sweep.py` is missing or crashes.

### (e9) Now-refill + `Later` sweep — a wrap gate, same shape as (d)/(e)/(e2)–(e8) (#1870)

ADR-099's own maintenance rule (3) — "a monthly ~10-minute triage sweep closes-or-demotes
stale issues" — had **no implementation anywhere in the repo** until this step. The
measured cost: `Later` held 33 open issues with **0 of the last 30 closures** coming from
it, while `Now` sat at zero actionable work (all 3 open `Now` stories carried
`gate:owner`) and nothing said so. A monthly sweep nobody ever ran becomes per-session
upkeep the wrap can't skip.

- **Refill `Now`.** (e7)'s `now_liveness` finding is the trigger: if `Now` holds fewer than
  3 actionable (non-`gate:owner`, non-`blocked:*`) **stories**, promote until it does.
  **You do not have to work out which ones — the finding prints its own remedy (#3254), and
  the full plan with the exact commands is one call:**
  ```bash
  python3 scripts/backlog_next.py --refill-now --lane <sonnet|opus|fable>   # THE plan, scoped to YOUR model
  python3 scripts/backlog_next.py --milestone Next                          # the donor pool in full, if you want to look
  ```
  Promote **by the printed rank** — the stored ADR-099 score line is the selector, never a
  fresh re-scoring (that habit is the headline finding #1863 fixed). Four things the plan
  encodes that the old prose version of this step got wrong or left out:
  - **A promotion is TWO edits.** `gh issue edit <N> --milestone Now` moves the milestone;
    ADR-099 ¶5 also requires the body's **score line** `→ <milestone>` arrow to be
    retargeted to `→ Now`. The milestone edit alone just swaps a blocking `now_liveness`
    finding for a blocking `score_line_canonical` one and the wrap stays red. The plan
    prints the rewritten line for every pick.
  - **Only `type:story` counts.** `now_liveness` selects on stories, so promoting a
    `type:bug` or `type:chore` moves the queue's depth and not the gate.
  - **`Next` is not the only donor.** The walk is `Next` → `Later` → **`Roadmap`**, the
    ADR-099 order. The `Roadmap` step is that ADR's amendment ¶3 promotion path, capped at
    **one product pick**, flagged as such in the plan — and confirming that no other
    `Roadmap`→`Now` promotion was taken this experiment cycle is the one step the corpus
    cannot derive for you, so it is yours.
  - **Pass `--lane <your model>`.** `now_liveness` counts stories; work is partitioned by
    `model:*` and a session runs in one lane. Measured 2026-08-27: the whole sanctioned
    refill supply was 12 startable stories and **all 12 were `model:fable`** while the
    session was all-Opus — a lane-blind promotion would have turned the gate green and
    added zero startable work. Lane-scoped, the plan refuses those picks and says so.
    `check_backlog_hygiene.py --lane <model>` (or `BACKLOG_LANE=<model>`) scopes the gate
    the same way. The advisory `now_lane_coverage` covers the other half — a `Now` that is
    at the floor but concentrated in one lane.
  - **`NO REMEDY IN THE CORPUS`** is a real verdict the plan prints when even the full
    sanctioned walk cannot reach the floor. It names the levers in order — file work, or
    unblock a named `gate:owner`/`blocked:*` story, or amend ADR-099 ¶3 to raise the
    product-pick rate, or hand the wrap to a session in the lane that has the work.
    **Never lower `bc.NOW_LIVENESS_MIN` to clear it**; the floor moves by ADR, not by wrap.
  An empty queue reported is honest, an empty queue unsaid is the failure. And note the
  standing tension, which is a feature: labelling a story `blocked:*` **honestly** is what
  fires this gate. The gate is right to fire — the queue really is not live — and the fix
  is the plan above, never a quieter label.
- **Sweep `Later`.** The stale list is (e7)'s `later_staleness` output:
  ```bash
  python3 scripts/check_backlog_hygiene.py --advisory --rule later_staleness
  ```
  Every printed issue gets an **explicit promote-or-close call this session** — promote it
  (`gh issue edit <N> --milestone Next`) if it still matters, or close it (`gh issue close
  <N> --reason "not planned"`, plus its (e8) comment) if it doesn't. "Keep it on `Later`"
  is a legitimate third call, but only when stated out loud with a one-clause reason —
  never by silence. An aged `Later` issue is a triage signal, never a defect: `later_staleness`
  findings are ADVISORY severity, so this rule can never fail the gate even under (e7)'s
  blocking default.
- The handover carries one line either way: `**Backlog:** Now <n> actionable (promoted
  #N, #M); Later sweep — <calls made>` or `**Backlog:** Now live at <n>; no stale Later
  issues`.

### (e10) Alarm-citation gate — a wrap gate, same shape as (d)/(e)/(e2)–(e9) (#1959)

Nothing owned "an alarm red >72h must cite an incident row or issue #" — the #1329
standing-alarms item (step (a).4) was scoped to freshness/staleness alarms and was
advisory only (a next-picks note, no `describe-alarms` enumeration, no fail
condition). At the 2026-07-28 review 6 alarms were red simultaneously against one
incident row in the session ledger; a new red could hide among the chronic ones.

- Run (in the Phase 1 batch):
  ```bash
  python3 scripts/check_alarm_citations.py
  ```
  It reads live CloudWatch state (`describe_alarms(StateValue="ALARM")`, read-only —
  no writes, no alarm mutation) and cross-references the curated registry
  `docs/alarm_citations.json` (exact `AlarmName` -> `{"citation": "#N or an incident
  row", "note": "..."}`, hand-maintained the same way `remediation/agent.py`'s
  `MANUAL_ROTATION_SECRETS` is). Every alarm that has been in ALARM **>72h** must
  have an entry, or the gate names it explicitly and exits 1. **Tenure escalation
  (#2378): any alarm in ALARM >14 days is a MANDATORY issue-or-fix — its citation
  must reference a filed issue (`#N`), or the gate red-flags it; a prose/incident-row
  citation line stops counting at that tenure (qa-smoke-warnings sat structurally red
  21+ days behind a tidy citation).** **Flap visibility (#2912): the gate also reads
  `describe-alarm-history` (read-only) over the same 72h window and flags every alarm
  whose ALARM episode both fired and cleared inside it — such an episode never appears
  in `describe_alarms(StateValue="ALARM")`, so current-state duration is structurally
  blind to it (measured: 35 OK→ALARM cycles with 1–3 min dwells off one planted
  datapoint). A transition count is the honest signal (ADR-104); a flagged flap needs a
  registry entry or an explicit named handover line + `--decoded`, same as a standing
  red.**
- If a printed alarm is a genuine gap: add a `docs/alarm_citations.json` entry (file
  the issue first if none exists yet, ADR-099 shape) — or, if it's not really
  actionable this session, write the shortfall explicitly into the handover and
  re-run with `--decoded` to close this step honestly (same contract as (e2)'s
  `check_main_green.py --decoded`). Do not leave a printed uncited alarm unfixed
  AND unacknowledged.
- **AWS-unreachable degrade:** if CloudWatch can't be reached (no creds, offline),
  the script prints `UNVERIFIED` and exits 0 on its own — note that in the handover
  rather than claiming a clean board (mirrors (e7)'s `gh`-unavailable fail-open
  shape).
- The handover carries one line either way: `**Alarms:** <N> red >72h, all cited`,
  `**Alarms:** <M> uncited — named: <alarm names>`, or `**Alarms:** unverified — AWS
  unreachable`.

### (e11) Standing-warning triage gate — a wrap gate, same shape as (d)/(e)/(e2)–(e10) (#1966)

A `::warning::` on an otherwise-green main run is easy to normalize into background
noise precisely BECAUSE main still reads green — #1966's own finding is the proof: the
#1349 suite-duration warner tripped on a green run and the optimize-or-raise decision
sat unactioned for a week with nothing obligated to look at it.

- Run (in the Phase 1 batch):
  ```bash
  python3 scripts/check_ci_warnings.py
  ```
  It reads the check-run annotations GitHub attached to the latest **green** completed
  CI/CD run on main (read-only, no writes) and lists every `annotation_level ==
  "warning"` it finds — e.g. the #1349 coverage-gap/duration-budget warnings, or any
  future one. A not-yet-green newest run reads as "nothing to triage yet" (that's step
  (e2)'s job, not this one's).
- For each warning printed: file an issue for it (ADR-099 shape, cite it in the
  handover) or make the deliberate no-action call THIS session and write the one-line
  reason into the handover — then re-run with `--decoded` to close this step honestly
  (same contract as (e2)'s `check_main_green.py --decoded`). Do not leave a printed
  warning unfixed AND unacknowledged.
- **GitHub-unreachable degrade:** if the API can't be reached, the script prints
  `UNVERIFIED` and exits 0 on its own — note that in the handover rather than claiming a
  clean board (mirrors (e10)'s AWS-unreachable shape).
- The handover carries one line either way: `**CI warnings:** none`, `**CI warnings:**
  <N> — <one-line triage per warning>`, or `**CI warnings:** unverified — GitHub
  unreachable`.

### (e12) Proportionality-ledger gate — a wrap gate, same shape as (d)/(e)/(e2)–(e11) (#2380, enforced by #2761)

The first version of this gate (#2380) was four lines of prose wedged into step (e10)'s
header — no step letter, no script, no required handover line, no guardrail bullet, and
a conditional trigger ("IF this session landed standing machinery ...") that nothing
evaluated. Measured result (#2761): zero `docs/PROPORTIONALITY.md` commits in its first
week while four standing subsystems shipped with real rent (#2572, #2552, #2527, #2578).
A check that cannot fail is a check that never ran. Same fix as (d)/(e3): the line is
unconditional, the assertion is a script.

- Run (after the new handover from step (a) is written; the Phase 3 verify batch runs
  this):
  ```bash
  python3 scripts/check_proportionality_ledger.py
  ```
  It must exit 0. It passes only when the session shows a `docs/PROPORTIONALITY.md`
  diff (working tree/index, or committed since the previous `docs(wrap)` commit) OR the
  handover carries an explicit `**Ledger:**` line.
- **If this session landed a NEW standing subsystem** (CI gate, scheduled writer,
  watcher, alarm, workflow): add its row to `docs/PROPORTIONALITY.md` — posture + rent +
  demote trigger, ADR-103/144 — in the wrap commit, and write
  `**Ledger:** <subsystem> row added` in the handover. A line claiming a row while the
  ledger shows no diff this session FAILS the gate: writing the line without landing the
  row is the exact silent pass this step replaces.
- **If standing machinery shipped but the row is deliberately deferred:**
  `**Ledger:** omitted — <reason>` (explicit and auditable; a bare `omitted` without a
  reason fails).
- **If nothing standing shipped:** `**Ledger:** none — no standing machinery shipped`.
- **Git-unreachable degrade:** the script prints `UNVERIFIED` for the diff leg and only
  an explicit `**Ledger:**` line can pass — note the degrade in the handover (mirrors
  (e7)/(e10)'s shape).
- The handover carries one line either way: `**Ledger:** <subsystem> row added`,
  `**Ledger:** omitted — <reason>`, or `**Ledger:** none — no standing machinery
  shipped`.

## Phase 3 — Verify: the gates that read the finished handover

```bash
python3 scripts/wrap_gates.py --verify
```

Runs — reporting all failures together — `scripts/check_handover_lines.py` (#3006:
every gate marker line, derived from THIS file's own "carries one line" contracts and
never hand-listed, must be present in the new handover; measured cost of the prose-only
era: 20 missing lines in a 25-handover window, all in four truncated wraps), the (e4)
residual-queue gate, the (e12) proportionality-ledger gate, and the (d) beat
validators. **It must exit 0 before the wrap commit.** A truncated wrap now fails
loudly instead of producing a handover that reads complete and is not.

## Phase 4 — Commit

### (f) Commit the wrap

Phase 3's `wrap_gates.py --verify` must have exited 0 first.

Stage the repo-tracked wrap artifacts only (memory-dir changes from step (c) are outside
git and are never part of this commit):

```bash
git add handovers/HANDOVER_LATEST.md CLAUDE.md docs/ site/story/build/beats.json   # beats.json only if (d) fired; docs/ only if (e) touched pages or (e10) updated docs/alarm_citations.json
git commit -m "$(cat <<'EOF'
docs(wrap): <short session theme> (<n items/PRs shipped>)
EOF
)"
```

Match the style of prior wrap commits (e.g. `28a5d603 docs(wrap): mobile bug-bash
session — status block, handover, build beat (9 R22 smalls #836–#845)`).

## Guardrails (do not relax these)

Every gate states the same contract — an explicit line or artifact, never silence — and
since #3006 every marker line is ASSERTED by `scripts/check_handover_lines.py` in Phase
3, with the marker set derived from this file's own step contracts (never hand-listed).
The registry (#3007 — one row per former guardrail bullet, no rule dropped):

| Gate (the rule) | Step | Script / assertion | Required handover line |
|---|---|---|---|
| Beat or explicit skip (#736); **merged-work-only dispatch** — a beat narrates what shipped and is live, never a plan or an open PR | (d) | `validate_beats.py` + `content_policy_scan.py` (Phase 3); line asserted by `check_handover_lines.py` | `**Build beat:** <id or "none — reason">` |
| Docs or explicit skip (wiki contract) — the wiki checkers must be green at the wrap commit | (e) | doc checkers (Phase 1); line asserted by `check_handover_lines.py` | `**Docs:** <pages or "none needed — reason">` |
| Decisions or explicit skip (#1343) — a governance decision must never land only in a workflow file or a commit message | (e) | `check_handover_lines.py` | `**Decisions:** <ADR-NNN filed or "none needed — reason">` |
| Main is declared from a read badge, never assumed (#1327; stranded classes #1901/#2052) | (e2) | `scripts/check_main_green.py` exit 0, clean or `--decoded` (Phase 1) | `**Main:** green (<sha>)` / `red — <decode>` / `stranded — <decode>` |
| Incident rows or explicit skip (#1332) — every incident-class event gets a `docs/INCIDENT_LOG.md` row the same session | (e3) | rows in `docs/INCIDENT_LOG.md`; line asserted by `check_handover_lines.py` | `**Incidents:** <rows added or "none">` |
| Residual queue cites an issue, never silence (#1340) — every residual/next-picks bullet carries `#<issue>` or `not-work — <reason>`; the gate script must print `OK` before the wrap commit | (e4) | `scripts/check_residual_queue.py` (Phase 3) | (per-bullet tags, not one marker line) |
| Stash empty + hook fresh, or explained (#1326) | (e5) | `git stash list` + `deploy/session_postflight.py` (Phase 1) | `**Stash/hooks:** clean` / `<found + action>` |
| Filing-contract violators get fixed, not deferred (#1870, blocking since #1872 — which absorbed and deleted the old #1349 `model:*`-only gate). A printed violator on an issue this session filed, touched or closed may not be left unfixed; a live-fetch failure still fails open (exit 0), noted in the handover | (e7) | `scripts/check_backlog_hygiene.py` bare (Phase 1) | (fail-open noted in handover) |
| Outcome verdict on every closure, never silence (#1870) — the ADR-099 closure comment (`**Shipped:** …` + `**Outcome:** <realized\|partial\|not-realized> — …`) on each issue closed, `not planned` closes included; a fabricated `realized` is worse than a blank comment (ADR-104) | (e8) | line asserted by `check_handover_lines.py` | `**Closures:** <#N commented or "none — …">` |
| The queue is refilled or its depth is reported, never silence (#1870) — `Now` below 3 actionable gets promotions by stored rank from the derived `Next → Later → Roadmap` plan (#3254), scoped to the session's `--lane`; every `Later` issue untouched >60d gets an explicit promote-or-close call | (e9) | `scripts/backlog_next.py --refill-now --lane <model>`; line asserted by `check_handover_lines.py` | `**Backlog:** …` |
| A red alarm >72h cites something, or the wrap names it (#1959); since #2912 a FIRED-AND-CLEARED flap in the 72h window is answered the same way — never waved through because the board "looks green now" | (e10) | `scripts/check_alarm_citations.py` exit 0, clean or `--decoded` (Phase 1); `docs/alarm_citations.json` | `**Alarms:** …` |
| A `::warning::` on green main gets triaged, or the wrap names it (#1966) — an issue or an explicit named decision, never left both unfixed and unacknowledged | (e11) | `scripts/check_ci_warnings.py` exit 0, clean or `--decoded` (Phase 1) | `**CI warnings:** …` |
| Standing machinery gets a `docs/PROPORTIONALITY.md` row, or the wrap says why not (#2380, enforced by #2761) — a line claiming a row the ledger never saw fails loudly | (e12) | `scripts/check_proportionality_ledger.py` (Phase 3) | `**Ledger:** …` |
| Every marker line above is PRESENT — a truncated wrap fails loudly, not silently (#3006) | Phase 3 | `scripts/check_handover_lines.py` (markers derived from this file) | all of the above |

Not tabular, still binding:

- **Replace, don't stack.** CLAUDE.md's status block is one paragraph, always.
- **One live block.** `handovers/HANDOVER_LATEST.md` is the only "current" handover — and
  since #1650 it is the only handover tracked on `main` at all; everything else is archived
  under its dated name on the `session-archive` branch by `scripts/archive_handover.py`.
  A dated `HANDOVER_*.md` committed to `main` reds `tests/test_archive_handover.py`.
- **Body follows index, never an index-only patch (#1342).** A `MEMORY.md` index-line
  correction is not complete until the same wrap rewrites the topic file's body too; step
  (c)'s memory-body-drift grep must be reviewed clean (or its hits fixed) before closing.
