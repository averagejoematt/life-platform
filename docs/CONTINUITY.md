# CONTINUITY — if the AI is gone

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-07-10
> **Sources of truth:** handovers/, .claude/commands/, mcp memory tool code, this repo's git history

This page maps every piece of operational state that lives **outside `docs/`** — where
it is, how a human reads it, and how to export it. The bar: with all AI tooling powered
down, an engineer holding only this repo (plus AWS access — see `docs/AWS_ACCESS.md`)
can reconstruct what the platform was doing, what the last session changed, and what
the accumulated institutional memory says.

There are six state surfaces. Three are in this repo (`handovers/`, the CLAUDE.md
session block, `.claude/commands/`), one is in DynamoDB (platform memory), one is on
Matthew's laptop only (Claude Code file memory — **one of the TWO laptop-only assets (see the launchd runtime below)**), and one
is on GitHub (the Issues backlog).

---

## 1. `handovers/` — the session log

Every working session ends with a handover file. This is the platform's operational
diary: what shipped, what was deployed, what broke, what is waiting on Matthew.

- **`handovers/HANDOVER_LATEST.md`** — the live driver: the most recent session's full
  narrative. Read this first; it is always the "where were we" document.
- **`handovers/HANDOVER_<date>_<slug>.md`** — one file per prior session, dated.
- **`handovers/archive/`** — older per-session files plus the pre-2026-07 diary,
  archived from CLAUDE.md at `handovers/archive/CLAUDE_MD_SESSION_DIARY_2026-07-03.md`.

**The wrap convention (#365):** at session close, the outgoing session (a) writes its
handover file, (b) archives the previous `HANDOVER_LATEST.md` under its dated name, and
(c) REPLACES the single session-status block at the bottom of `CLAUDE.md` — it never
stacks. So: `CLAUDE.md` block = last session's summary; `HANDOVER_LATEST.md` = last
session's detail; dated files = history.

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

To reconstruct history: read `HANDOVER_LATEST.md`, then walk the dated files backwards.
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
(what the MCP tools accept) and `lambdas/phase_taxonomy.py` — which also decides reset
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
~/.claude/projects/-Users-matthewwalker-Documents-Claude-life-platform/memory/
```

It is **per-machine and NOT in git**. Contents (as of 2026-07-10: `MEMORY.md` + ~104
topic files):

- **`MEMORY.md`** — the index: a categorized map of every topic file with a one-line
  summary each. Read this first; it is the table of contents.
- **`project_*.md`** (~64) — program/feature state: what shipped, what's pending, the
  per-program narrative (e.g. experiment resets, the coach-portraits program).
- **`reference_*.md`** (~23) — incident write-ups behind the rules in
  `docs/CONVENTIONS.md`: the full story of each deploy/CI/git trap.
- **`feedback_*.md`** (~16) — Matthew's working-style preferences and standing
  authorization boundaries (e.g. "I run deploys", heartbeat progress).
- **`security_*.md`** (1) — security incident detail kept out of the public repo.

**The risk, plainly:** everything else on this page has at least one durable home
(git, DynamoDB with PITR, GitHub). This directory exists on one laptop. If the laptop
dies, the incident narratives and preference memory die with it — the rules survive in
`docs/CONVENTIONS.md`, but the *why* behind them doesn't. Recommended operator habit —
back it up to the private S3 bucket:

```bash
aws s3 sync ~/.claude/projects/-Users-matthewwalker-Documents-Claude-life-platform/memory/ \
  s3://matthew-life-platform/claude-memory-backup/ --region us-west-2
```

**Never commit this directory (or its export) to the repo — the repo is public** and
memory files contain personal detail and security-incident narrative by design.

## 5. `.claude/commands/` — the skills are human runbooks

Each skill file is a step-by-step process document. They were written to drive an AI
session, but a human can follow them directly:

| Skill | Process it encodes |
|---|---|
| `wrap.md` | Session close: archive the handover, replace the CLAUDE.md status block, update memory, distill a build beat (the #365 convention, §1–2 above) |
| `deploy.md` | Deploying a Lambda, the site, or the fleet — the one-bundle rules (#781), ownership boundaries, verification steps |
| `uplevel.md` | The improvement-session driver: fresh-eyes survey → rank against the north star → ship one flagship slice end-to-end |
| `qa.md` | The render-level QA sweep of averagejoematt.com (smoke + Playwright visual QA) |
| `accuracy-review.md` | The truth audit: are the published numbers true and the AI prose grounded (the layer above `/qa`) |
| `site-review.md` | The holistic narrative/UX review: does each page's story land (human-in-the-loop) |
| `reconcile-branch.md` | Merging concurrent PRs that each touch the doc-sync literals (`PLATFORM_STATS`) without clobbering each other |

## 6. GitHub Issues — the backlog (ADR-099)

The forward-work backlog is GitHub Issues, not a file. `docs/BACKLOG.md` is a frozen
archive. Conventions:

- **Epics** carry `type:epic`; **ranked stories** carry `type:story` and link up to an
  epic. Milestones express horizon: **Now / Next / Later**.
- A shipping PR carries `Fixes #N` so merge closes the story.
- Seed a session from: `gh issue list --label type:story --milestone Now --state open`.
- Label taxonomy in use (`gh label list`): `type:epic|story` · `area:site-ux|ai|growth|
  data|infra|security|docs|claude-workflow` · routing labels `model:opus|sonnet|fable`
  (which class of model/effort the work needs) · wedge labels `wedge:build-in-public|
  transformation-gated` · remediation-agent labels `auto-fix-safe` / `needs-review`
  (ADR-064/065) · `parity-debt` (backfill ↔ live drift) · `parked-register` (the one
  gated/won't-do register issue) · plus GitHub defaults (`bug`, `documentation`, …).

## 7. Day-1 reading order for a human successor

1. `README.md` — what this repo is.
2. `docs/README.md` — the wiki home: the full categorized doc index.
3. `docs/ONBOARDING.md` — the mental model.
4. `docs/QUICKSTART.md` + `docs/AWS_ACCESS.md` — first commands, AWS auth and access.
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
