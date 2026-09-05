# CONTINUITY — if the AI is gone

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-08-30 (the datadrops backup leg is AUTOMATED in the same daily job, not a manual push — the `BACKUP_DATADROPS` switch never existed and the §3c TCC posture was resolved by the ~/dev relocation; handovers/ split to the `session-archive` branch, #1650)
> **Sources of truth:** handovers/HANDOVER_LATEST.md + the `session-archive` branch, .claude/skills/, mcp memory tool code, this repo's git history

This page maps every piece of operational state that lives **outside `docs/`** — where
it is, how a human reads it, and how to export it. The bar: with all AI tooling powered
down, an engineer holding only this repo (plus AWS access — see `docs/AWS_ACCESS.md`)
can reconstruct what the platform was doing, what the last session changed, and what
the accumulated institutional memory says.

There are six state surfaces. Three are in this repo (the session log — `handovers/` on
`main` plus the `session-archive` branch — the CLAUDE.md
session block, `.claude/skills/`), one is in DynamoDB (platform memory), one is on
Matthew's laptop only (Claude Code file memory — **one of the TWO laptop-only assets (see the launchd runtime below)**), and one
is on GitHub (the Issues backlog).

---

## 1. The session log — `handovers/` on `main` + the `session-archive` branch

Every working session ends with a handover file. This is the platform's operational
diary: what shipped, what was deployed, what broke, what is waiting on Matthew.

Since **#1650** the log is split in two, so the product tree reads as engineering rather
than transcript (`docs/ENGINEERING_STANDARDS.md` §1) — **both halves travel with the
repo**, so a clone is still self-sufficient:

- **On `main`: `handovers/HANDOVER_LATEST.md`** — the live driver: the most recent
  session's full narrative. Read this first; it is always the "where were we" document.
  It is the ONLY handover tracked on `main` (plus `handovers/README.md`, the pointer).
- **On the `session-archive` branch: `handovers/HANDOVER_<date>_<slug>.md`** — one file
  per prior session, dated — and **`handovers/archive/`**, the older per-session files
  plus the pre-2026-07 diary
  (`handovers/archive/CLAUDE_MD_SESSION_DIARY_2026-07-03.md`).

```bash
git fetch origin session-archive
git log  origin/session-archive --oneline -- handovers/          # the log of the log
git show origin/session-archive:handovers/HANDOVER_2026-07-21_Glass-Engine.md
git worktree add ../life-platform-sessions origin/session-archive   # browse the corpus
```

The archive branch is parented on `main` and the files kept their original `handovers/…`
paths, so `git log --follow` walks a handover's history straight through the split.

**The wrap convention (#365):** at session close, the outgoing session (a) archives the
previous `HANDOVER_LATEST.md` onto `session-archive` under its dated name
(`python3 scripts/archive_handover.py --slug <slug>`) and overwrites
`HANDOVER_LATEST.md` in place with its own, and (b) REPLACES the single session-status
block at the bottom of `CLAUDE.md` — it never stacks. So: `CLAUDE.md` block = last
session's summary; `HANDOVER_LATEST.md` = last session's detail; the archive branch =
history.

A real handover (2026-07-10) has this structure — they are consistent enough to skim
mechanically:

```markdown
# HANDOVER — <one-line what-happened title> — <date>

> Instruction (evolving): <the user's actual words that drove the session>

## The shape of the session          ← narrative: what was attempted, forks taken
## What shipped (all MERGED + DEPLOYED + VERIFIED)   ← issue # → PR #, per item
## Deploys + verification            ← which lambdas/site went live, evidence
## Gotchas (new this session)        ← hard-won lessons before they reach docs/memory
**Build beat:** <slug or "none — reason">            ← the #736 public-dispatch gate
## Residual — waiting on Matthew     ← the open human-gated queue
## Watch                             ← things that should be checked next session
```

To reconstruct history: read `HANDOVER_LATEST.md` on `main`, then walk the dated files on
`session-archive` backwards (`git log origin/session-archive --oneline -- handovers/`).
Durable lessons are supposed to graduate out of handovers into `docs/CONVENTIONS.md`
(rules) or the Claude Code memory system (§4, incident narratives) — a gotcha that only
exists in a handover is a lesson that has not been homed yet.

## 2. The CLAUDE.md session-status block

The bottom of `CLAUDE.md` ("Session status — the ONE live block") holds a single
paragraph-sized summary of the most recent session: what was verified, headline items
shipped, new gotchas, and the deferred queue. It is **ephemeral by design** — each wrap
replaces it wholesale. Read it as "what was the last session doing", nothing more.
Anything durable is supposed to have flowed to `docs/CONVENTIONS.md`, the topic memory
(§4), or the convention sections higher up in `CLAUDE.md`. If the block contradicts a
canonical doc, the doc wins and the block is just newer context.

## 3. Platform memory in DynamoDB (the machine's memory)

The platform's compounding intelligence substrate — failure patterns, "what worked"
records, weekly plate history, hypothesis monitoring — lives in ONE partition of the
`life-platform` table (us-west-2):

```
pk = USER#matthew#SOURCE#platform_memory
sk = MEMORY#<category>#<YYYY-MM-DD>
```

The canonical writer/reader interface is `mcp/tools_memory.py` (tools
`write_platform_memory` / `read_platform_memory` / `list_memory_categories` /
`delete_platform_memory`); several compute lambdas also write directly
(`lambdas/emails/weekly_plate_lambda.py`, `lambdas/compute/failure_pattern_compute_lambda.py`,
`lambdas/compute/hypothesis_engine_lambda.py`, `lambdas/compute/daily_insight_compute_lambda.py`).
Records are plain DDB items: `category`, `date`, `stored_at`, plus arbitrary
content fields (floats stored as `Decimal`).

**Categories** are enumerated in two places: `mcp/tools_memory.py::VALID_CATEGORIES`
(what the MCP tools accept) and `lambdas/experiment/phase_taxonomy.py` — which also decides reset
semantics (ADR-077): `MEMORY_DURABLE_CATEGORIES` (e.g. `baseline_snapshot`) survive an
experiment restart; `MEMORY_SCOPED_CATEGORIES` (e.g. `failure_pattern`/`failure_patterns`
— both spellings exist, `weekly_plate`, `what_worked`, `hypothesis_monitoring`, …) are
experiment-scoped and tombstoned at restart. Don't trust any static list of what's
actually populated — query it (as of 2026-07-10 the live partition held 27 records
across 5 categories).

**Read it with the plain AWS CLI** (read-only):

```bash
aws dynamodb query --table-name life-platform --region us-west-2 \
  --key-condition-expression "pk = :pk AND begins_with(sk, :sk)" \
  --expression-attribute-values '{":pk":{"S":"USER#matthew#SOURCE#platform_memory"},":sk":{"S":"MEMORY#"}}'
```

**Export it** with `scripts/export_platform_memory.py` (stdlib + boto3, read-only):

```bash
python3 scripts/export_platform_memory.py --dry-run     # per-category counts, writes nothing
python3 scripts/export_platform_memory.py               # one markdown file per category → ./memory_export/
```

`memory_export/` is gitignored — the export contains personal data and this repo is
public.

## 4. Claude Code file memory — one of the TWO laptop-only assets

Claude Code's cross-session memory for this project lives at:

```
~/.claude/projects/-Users-matthewwalker-dev-life-platform/memory/
```

It is **per-machine and NOT in git**. The file counts drift constantly, so read them
rather than quoting them (`ls <dir> | wc -l`, `ls <dir>/reference_*.md | wc -l`). The
four families:

- **`MEMORY.md`** — the index: a categorized map of every topic file with a one-line
  summary each. Read this first; it is the table of contents. Its `Review Discipline`
  section is split out into `INDEX_review_discipline.md`.
- **`project_*.md`** — program/feature state: what shipped, what's pending, the
  per-program narrative (e.g. experiment resets, the coach-portraits program).
- **`reference_*.md`** — incident write-ups behind the repo's rules: the full story of
  each trap. The **rules** live in `docs/CONVENTIONS.md` (deploy/CI/git) and
  `docs/OPERATING_DISCIPLINE.md` (adjudicating work, driving a session); these files
  carry the narrative that page deliberately does not.
- **`feedback_*.md`** — Matthew's working-style preferences and standing authorization
  boundaries (e.g. "I run deploys", heartbeat progress).
- **`security_*.md`** — security incident detail kept out of the public repo.

**The risk, plainly:** everything else on this page has at least one durable home
(git, DynamoDB with PITR, GitHub). This directory exists on one laptop. If the laptop
dies, the incident narratives and preference memory die with it — the *rules* survive in
`docs/CONVENTIONS.md` and `docs/OPERATING_DISCIPLINE.md`, but the *why* behind them does
not. **#2848 audited this corpus** — the review-discipline half on 2026-08-27 (154 entries,
the frozen record is `docs/OPERATING_DISCIPLINE.md` Appendix A) and the whole index on
2026-08-30. The maintained answer to *which entry is homed where* is
**`docs/OPERATING_KNOWLEDGE_LEDGER.md`**: one row per memory file, with its repo home or the
stated reason it has none (session narrative, security detail, tooling that lives outside
the repo, the owner's own profile). What a successor consequently still cannot learn from
this repo is `docs/OPERATING_DISCIPLINE.md` §7 — the per-rule incident narrative, by design,
and the multi-lane concurrency *pattern*; the deploy-authorization boundary that used to be
on that list is now §5 of that page. Recommended operator habit — back it up to the private
S3 bucket:

```bash
aws s3 sync ~/.claude/projects/-Users-matthewwalker-dev-life-platform/memory/ \
  s3://matthew-life-platform/claude-memory-backup/ --region us-west-2
```

**Automated since 2026-07-11 (#1026):** the daily launchd agent
`com.matthewwalker.claude-memory-backup` runs this memory sync at 09:15 (+ RunAtLoad) —
RPO is ~1 day instead of "whenever the last wrap ran". The wrap-step sync stays as
belt-and-suspenders.

**The `datadrops/` → `datadrops-archive/` leg runs in the SAME job, unconditionally.** It
is not a manual push and there is no `BACKUP_DATADROPS` switch — that variable appears
nowhere in the script and never has. The TCC rationale behind the old "manual by decision"
framing was retired on 2026-08-30 when the repo moved to `~/dev`, which TCC does not
protect (`docs/NEW_MACHINE_BOOTSTRAP.md` §3c). To force an off-schedule run:
`bash setup/claude_memory_backup.sh` — both legs, no flags.

> **Read the log, not the schedule.** That leg ran daily and *failed* daily from
> 2026-07-11 to 2026-08-30 while these pages described it as deliberately idle. A backup
> that is failing and a backup that is manual by choice are indistinguishable from the
> documentation — the only honest check is the `rc=` line in
> `~/Library/Logs/claude-backup/backup-YYYYMMDD.log`.

> **Where the script lives (resolved 2026-08-31).** `setup/claude_memory_backup.sh`, in
> git, with its LaunchAgent versioned beside it at
> `setup/com.matthewwalker.claude-memory-backup.plist`. launchd runs the repo file
> directly: **no staged copy, no installer.** The staged `~/.local/bin` copy has been
> deleted.
>
> That staging is what broke this backup. The header claimed a repo copy was the source
> and an `install.sh` staged it; neither had ever existed, so the only copy was untracked,
> carried a hard-coded `~/Documents` path, and went stale when the repo moved — failing
> every run for seven weeks while reporting a TCC cause that no longer applied. Outside
> git, nothing could see it. `tests/test_backup_agent_path_contract.py` now asserts the
> installed agent still names the repo file, and that no staged copy has reappeared.

**Never commit this directory (or its export) to the repo** — whatever the repo's
visibility at the time (it has been public, private and public again), memory files contain
personal detail and security-incident narrative by design and must stay out of git; the
discipline is permanent.

## 5. `.claude/skills/` — the skills are human runbooks

Each skill file is a step-by-step process document. They were written to drive an AI
session, but a human can follow them directly:

| Skill | Process it encodes |
|---|---|
| `wrap.md` | Session close: archive the handover, replace the CLAUDE.md status block, update memory, distill a build beat (the #365 convention, §1–2 above) |
| `deploy/SKILL.md` | Deploying a Lambda, the site, or the fleet — the one-bundle rules (#781), ownership boundaries, verification steps |
| `uplevel.md` | The improvement-session driver: fresh-eyes survey → rank against the north star → ship one flagship slice end-to-end |
| `qa.md` | The render-level QA sweep of averagejoematt.com (smoke + Playwright visual QA) |
| `review/SKILL.md` | The one graded-review spine. Seven lenses, each a rubric in `review/references/<lens>.md`: `accuracy` (the truth audit — are the published numbers true and the AI prose grounded, the layer above `/qa`), `site` (the holistic narrative/UX review — does each page's story land, human-in-the-loop), plus `craft`, `sdlc`, `full`, `platform` and `journey`. Cadence, exemptions and the dead-man live in `scripts/operating_calendar.py`, not in the skill |
| `reconcile-branch.md` | Merging concurrent PRs that each touch the doc-sync literals (`PLATFORM_STATS`) without clobbering each other |

## 6. GitHub Issues — the backlog (ADR-099)

The forward-work backlog is GitHub Issues, not a file. `docs/BACKLOG.md` is a frozen
archive. Conventions:

- **Epics** carry `type:epic`; **ranked stories** carry `type:story` and link up to an
  epic. Milestones express horizon: **Now / Next / Later**.
- A shipping PR carries `Fixes #N` so merge closes the story.
- Seed a session from: `python3 scripts/backlog_next.py` — ranks the open corpus by each
  issue's own stored ADR-099 score, prints its `## Outcome` line, and falls through
  Now → Next → Later out loud when a milestone has nothing actionable (#1866).
- Label taxonomy in use (`gh label list` — this census must match the live output, not
  drift into an intended state): `type:epic|story|bug|chore` (#1864 — `type:bug` a
  defect in shipped behavior, `type:chore` maintenance with no user-visible outcome,
  distinct from `type:story` product/feature work) · `area:site-ux|ai|growth|data|
  infra|security|docs|claude-workflow` · routing labels `model:opus|sonnet|fable`
  (which class of model/effort the work needs) · wedge labels `wedge:build-in-public|
  transformation-gated` · remediation-agent labels `auto-fix-safe` / `needs-review`
  (ADR-064/065) · `parity-debt` (backfill ↔ live drift) · `parked-register` (the one
  gated/won't-do register issue) · **severity** `prio:P0|P1|P2|P3` (#1864 — mirrors the
  score line's `P<n>` prefix so label and score line can never disagree; `prio:P0` is
  the PM-override class ADR-099 already sanctions, "a live reader-facing defect
  outranks the effort denominator" — not a fifth severity tier) · **readiness**
  `gate:owner` (blocked on a human-only act — an AWS console click, a judgment only
  Matthew can make) vs `blocked:dep` (blocked on another issue landing first) — the two
  are not synonyms, an issue can carry either, both, or neither · `review:*` (12 dated
  idempotency labels, one per filed review batch — e.g. `review:sdlc-2026-07-18`,
  `review:pm-backlog-2026-07-27` — reconciled via `gh issue list --label review:<slug>
  --state all` before refiling, per the 2026-07-18 ADR-099 amendment; not a manifest
  file) · `auto-filed` (opened by an advisory scheduled workflow on failure, #1447;
  auto-closes on recovery) · plus GitHub defaults (`bug`, `documentation`, …).

## 7. Day-1 reading order for a human successor

1. `README.md` — what this repo is.
2. `docs/README.md` — the wiki home: the full categorized doc index.
3. `docs/ONBOARDING.md` — the mental model.
4. `docs/QUICKSTART.md` + `docs/AWS_ACCESS.md` — first commands, AWS auth and access.
   (If the machine itself is gone: `docs/NEW_MACHINE_BOOTSTRAP.md` — the from-zero
   rebuild runbook that restores the two laptop-only assets in §4 + §7 below.)
5. `docs/ARCHITECTURE.md` — the system: stacks, lambdas, data flows.
6. `docs/SCHEMA.md` — the DynamoDB field reference.
7. `docs/RUNBOOK.md` — daily operations and troubleshooting.
8. `docs/CONVENTIONS.md` — the load-bearing reflexes; read before touching deploy/CI.
9. `docs/DECISIONS.md` — the ADR index: why things are the way they are.
10. **This page** — then go to the live state: `handovers/HANDOVER_LATEST.md`, the
    CLAUDE.md status block, `gh issue list --milestone Now`, and (if you need the
    machine's memory) the platform-memory export in §3.


## The seventh + eighth surfaces (added 2026-07-10 — CTO-grader falsifications)

The original six-surface map missed two. Recorded here so the claim "every state surface
outside docs/" stays true:

**7. The macOS launchd ingest runtime (the OTHER laptop-only asset).** Manual-drop
ingestion runs on Matthew's Mac, not in AWS: `ingest/com.matthewwalker.life-platform-ingest.plist`
(drop-folder watchers: Apple Health exports, MacroFactor, historical backfills),
`setup/com.matthewwalker.calendar-sync.plist`, and the MacroFactor drop agent under
`datadrops/`. The CODE survives in git; the RUNTIME dies with the laptop — scheduled
API ingestion (AWS) continues, but manual-drop sources silently stop. Reinstall on a
new machine: `bash ingest/install.sh` (+ re-point the drop folders). 

**8. Runtime config in S3 (`config/` prefix).** Live behavior-shaping state editable
WITHOUT any deploy: `s3://matthew-life-platform/config/<user>/board_of_directors.json`
(the coach/persona roster — ADR-012), `config/<user>/character_sheet.json` (leveling/EMA
constants), `config/training_phases.json`, `config/user_goals.json` (genesis/baseline),
plus the root `config/` catalogs the Evidence pages read. Read them:
`aws s3 ls s3://matthew-life-platform/config/ --recursive`. They are delete-protected
(bucket policy) and S3-versioned; the restart pipeline re-syncs some from the repo's
`config/` — see `docs/PHASE_TAXONOMY.md` for which survive a reset.

**Memory backup is now a wrap-step habit** (not merely "recommended"): the wrap skill's
step (c) ends with `aws s3 sync ~/.claude/projects/<slug>/memory/ s3://matthew-life-platform/claude-memory-backup/ --region us-west-2`
so every session close snapshots the laptop-only memory into versioned, private S3.
