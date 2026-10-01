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

Optional: a short theme/slug (e.g. `mobile-bug-bash`) for the handover title; else derive one.

The wrap runs in **four phases — gather → write → verify → commit** (#3007). Step ids
((a)–(f), (e2)–(e12)) are stable anchors (tests, CONVENTIONS §9), not an order. Each gate's
history lives in its issue and its script's docstring; this file is contract + remedy.

## Phase 1 — Gather: one batched gate run, before anything is written

```bash
python3 scripts/wrap_gates.py            # --list prints the battery, DERIVED — read it there, not here
```

It runs, in parallel, every gate that does NOT read the finished handover ((e2), (e5), (e7),
(e8), (e10), (e11)), reports **all failures together** with each script's own exit code and
`UNVERIFIED` degrade verbatim, and prints a **draft marker-line block**. Fix reds with the
owning step's remedy and re-run; correct every `<placeholder>` in Phase 2 — the draft is a
start, never a record. **The Docs-CI leg runs ONCE, in Phase 3** (#4262): a Phase 1 run
could only judge docs Phase 2 was about to rewrite.

## Phase 2 — Write everything once (steps (a)–(e))

Write the handover ONCE in step (a), with the corrected draft plus the judgment lines from
(d), (e), (e3), (e8), (e9), (e12). **Marker lines are prompts (#4262)**: Phase 3 blocks only
on the (e4) residual section; the scripts behind the lines still block on their artifacts.

### (a) Archive the outgoing handover, write the new one

**Dated handovers live on the `session-archive` branch, NOT on `main` (#1650)** — never
`git mv` one onto `main` (`tests/test_archive_handover.py` is the ratchet).

1. Read the current `handovers/HANDOVER_LATEST.md` — its title line gives the date and slug
   (archived files are `HANDOVER_<YYYY-MM-DD>_<Slug>.md`).
2. Archive it: `python3 scripts/archive_handover.py --slug <that-slug>` (`--dry-run` to
   preview; plumbing only, never touches `HEAD` or the tree; refuses to clobber). If its push
   fails, re-run `git push origin session-archive` before (f).
3. **Overwrite** `handovers/HANDOVER_LATEST.md` in place, in the archived files' shape:
   driving instruction, what shipped (PRs, merged/deployed), what was verified, gotchas, the
   residual/next-picks queue (required — `scripts/check_handover_lines.py`) and the marker lines.

### (b) Replace — never stack — the CLAUDE.md session-status block

Under `## Session status (the ONE live block — replace, don't stack)`, leave the convention
paragraph and **overwrite the one `**Verified:** ...` paragraph in place** — no addendum or
trailer. Same shape as the one you replace (date, instruction, PRs, verification, gotchas,
next picks); anything durable goes to memory (c) or `docs/CONVENTIONS.md`.

### (c) Update the persistent memory system

Memory is outside git (never in the (f) commit). Durable lessons → a topic file
(`project_*`/`feedback_*`/`reference_*.md`) plus ONE `MEMORY.md` index line per touched topic.

- **Orphan/broken-link gate (#1259) — must print nothing** (basename match, `INDEX_*.md` included):
  ```bash
  cd ~/.claude/projects/-Users-matthewwalker-dev-life-platform/memory/
  for f in *.md; do [ "$f" = MEMORY.md ] && continue; base="${f%.md}"; \
    grep -qF "$base" MEMORY.md project_shipped_archive.md INDEX_*.md || echo "ORPHAN: $f"; done
  ```
- **Body-follows-index rule (#1342)** — a corrected index line obligates the SAME wrap to
  rewrite the body; run `python3 scripts/check_memory_body_facts.py` and review every hit.
- **Operating-knowledge ledger (#2848)** — every rule-class memory file has a row in
  `docs/OPERATING_KNOWLEDGE_LEDGER.md`:
  ```bash
  python3 scripts/check_operating_knowledge_ledger.py --live       # any UNLEDGERED: line gets a row; exit 2 = could not look
  python3 -m pytest tests/test_operating_knowledge_ledger_2848.py -q  # THE CI check — regenerate the snapshot in the same commit
  ```
  `--live` passing is NOT the ledger being correct: a new row stales CI's committed
  snapshot (red-ed main 2026-09-14). Statuses: `homed-here`/`already-homed`/`superseded`
  (cite a path) or `narrative`/`off-repo` (state a reason).
- **Close (c) with the memory backup** (the laptop is the only other copy):
  ```bash
  aws s3 sync ~/.claude/projects/-Users-matthewwalker-dev-life-platform/memory/ \
    s3://matthew-life-platform/claude-memory-backup/ --region us-west-2
  ```

### (d) Build beat OR explicit skip — this step always produces one of the two (#736)

Follow `docs/content/BUILD_DISPATCH_CHECKLIST.md`. **Eligible** only if this session's work
is merged to `main` AND deployed — an open PR, a staged deploy or a plan is not.

- Not eligible: the new `handovers/HANDOVER_LATEST.md` from step (a) carries one line (optional, #4262) —
  `**Build beat:** none — <one-clause reason>`. An empty week is honest; do not force a beat.
- Eligible: append ONE object to `beats` in `site/story/build/beats.json` (schema in the
  checklist; `prs` entries are `{"label", "url"}` objects, never strings; numbers measured,
  ADR-104) and write `**Build beat:** <beat id>`. Phase 3 runs `validate_beats.py`.

### (e) Doc-impact sweep OR explicit skip — a wrap gate, same shape as (d)

Every shipped change updates the wiki pages it invalidates (CONVENTIONS §8 — deploy →
QUICKSTART/CONVENTIONS, data → SCHEMA, MCP tools → the catalog, new ADR →
`scripts/generate_adr_index.py --apply`, site → SITE_MAP_AND_INTENT) and bumps `Verified:`;
a retired load-bearing path gets a `docs/_lint/tombstones.txt` rule in the same commit (#781).

- `python3 deploy/sync_doc_metadata.py --apply` — the doc-sync literal treadmill (#3007): run
  it here, never mid-session from a worktree (`/reconcile-branch` settles collisions).
- **Do not restate the doc-gate list (#3531).** `wrap_gates.py` DERIVES its doc leg from
  `.github/workflows/docs-ci.yml` via `deploy/restart_verify_gates.py`'s
  `docs_ci_gate_commands()`; its one declared omission is `MUTATING_GATES`
  (`skill_lint.py --self-test`, reason at `derived_doc_gates()`), and
  `tests/test_restart_verify_gates_3477.py` reds on any other.
- The new `handovers/HANDOVER_LATEST.md` carries one line either way (optional, #4262):
  `**Docs:** <pages updated>` or `**Docs:** none needed — <one-clause reason>`.
- **Decisions gate (#1343)** — a governance-consequential decision not already in
  `docs/DECISIONS.md` gets its ADR in the same commit (then `generate_adr_index.py --apply`).
  The handover carries one line either way:
  `**Decisions:** ADR-NNN filed` or `**Decisions:** none needed — <one-clause reason>`.

## Gate reference — the lettered wrap gates ((e2)–(e12))

### (e2) Green-main gate — a wrap gate, same shape as (d)/(e) (#1327)

Never declare "main GREEN" over a badge you did not read: `python3 scripts/check_main_green.py`
exit 1 → fix main, or write the decode and re-run with `--decoded`. STRANDED states (#1901,
CONVENTIONS §4d — parked at the production gate, or Plan-red/Deploy-skipped) name the class
and the recovery (`deploy/approve_deployment.sh`, or CDK deploy + `deploy_all=true`).
The handover carries one line either way: `**Main:** green (<sha>)`,
`**Main:** red — <decode>`, or `**Main:** stranded — <decode>`.

### (e3) Incident gate — a wrap gate, same shape as (d)/(e)/(e2) (#1332)

Every incident-class event this session — an auto-rollback firing, main red >1h, a data gap,
a quota/budget-tier event, real OR false positive — gets a `docs/INCIDENT_LOG.md` row, or
the handover says none. Silent omission is not an outcome.

- **Write the row through the `incident` skill** (`.claude/skills/incident/SKILL.md`) — it
  owns the row shape, the class-level tracker and the procedure edit; this step does not.
- **Regenerate the derived Patterns block in the SAME edit** —
  `python3 scripts/incident_log_patterns.py --apply` — Phase 3 re-runs its `--check` (#3682).
- **Stage it**: `docs/INCIDENT_LOG.md` is named in Phase 4's `git add` (#3682 — a row left
  dirty in a shared checkout once shipped inside an unrelated PR).
- The new `handovers/HANDOVER_LATEST.md` carries one line either way:
  `**Incidents:** <N row(s) added — one-clause list>` or `**Incidents:** none`.

### (e4) Residual-queue gate — a wrap gate, same shape as (d)/(e)/(e2)/(e3) (#1340)

Every residual/next-picks bullet cites an issue `#N` (file it, ADR-099 shape) or carries
`not-work — <reason>` (an ops reminder, an owner-only call).
`python3 scripts/check_residual_queue.py` must print `OK` (Phase 3 runs it).

### (e5) Stash + hook hygiene gate — a wrap gate, same shape as (d)/(e)/(e2)/(e3)/(e4) (#1326)

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
- The Phase 1 batch also runs the `worktree-reap` gate (#4259):
  `python3 scripts/worktree_reaper.py --apply --quiet --release-locks-older-than-days 7 --budget-seconds 240`.
  It removes every lane that `/land` released (or whose lane lock has sat idle 7 days) once it
  is clean and merged, and lists every **dirty** worktree by name without touching it. Its
  last line is `REAPER-SUMMARY …`; a dirty lane it names is yours to commit, park as a patch,
  or explain — the reaper never decides that for you. It was 348 worktrees / 97 locked on
  2026-09-27 because nothing released a lane; this gate is the one scheduled caller.

### (e7) Backlog-hygiene gate — a wrap gate, same shape as (d)/(e)/(e2)/(e3)/(e4)/(e5) (#1870, blocking since #1872)

The Phase 1 batch runs exactly this bare, blocking invocation:
```bash
python3 scripts/check_backlog_hygiene.py
```
It lints the open corpus against the ADR-099 amendment (#1865). **Blocking by default since #1872**
(which absorbed and deleted the old label-only script): a printed violator on an issue this
session filed, touched or closed may not be left unfixed. `--advisory` is the explicit
opt-out for reports. A `gh` fetch failure fails open (exit 0) — say so in the handover.
`now_liveness` / `now_lane_coverage` / `later_staleness` are (e9)'s input, not defects; the
bare run is lane-blind on purpose — (e9) re-runs it with `--lane <model>` (#3254).

### (e8) Closure-comment gate — a wrap gate, same shape as (d)/(e)/(e2)/(e3)/(e4)/(e5)/(e7) (#1870)

Every issue closed this session gets an outcome verdict from the session that merged it.

- List and comment:
  ```bash
  gh issue list -R averagejoematt/life-platform --state closed \
    --search "closed:>=$(date -u +%F)" --json number,title,stateReason
  gh issue comment <N> --body "$(cat <<'EOF'
  **Shipped:** <what changed> · PR #N · <live evidence>
  **Outcome:** <realized|partial|not-realized> — <did the ## Outcome sentence come true?>
  EOF
  )"
  ```
  ADR-099 amendment ¶3 verbatim; a `not planned` close gets the same two lines. Under
  ADR-104 an unverified `realized` is the failure — without live evidence write `partial`.
- **The closure DoD (#3318)** — the rules are the registry `scripts/closure_contract.py`
  (rendered into CONVENTIONS §4a2, never copied here). Phase 1 ran
  `python3 scripts/closure_sweep.py --session`; before commenting its `no-outcome-verdict`
  list IS the to-do. Re-run it after commenting and disposition every other code it prints
  (carrier `#N`, fold onto an open `#N`, `not-work — <home>`, reopen, or a dated registry
  entry). `no-live-proof` (#3595) exits 1 in any posture: an instrument's PR carries
  `Refs #N`, not a closing keyword, and closes only on a `**Live proof:**` comment.
- The handover carries one line either way: `**Closures:** #N, #M commented` or
  `**Closures:** none — no issues closed this session`; the sweep rides the same line as
  `· DoD: scanned N, hits K — <each disposition>` (or `· DoD: unverified — GitHub unreachable`).

### (e9) Now-refill + `Later` sweep — a wrap gate, same shape as (d)/(e)/(e2)–(e8) (#1870)

- **Refill `Now`.** If `Now` holds fewer than 3 actionable (non-`gate:owner`, non-`blocked:*`)
  **stories**, promote until it does — the plan is one call:
  ```bash
  python3 scripts/backlog_next.py --refill-now --lane <sonnet|opus|fable>   # THE plan, scoped to YOUR model
  python3 scripts/backlog_next.py --milestone Next                          # the donor pool in full
  ```
  Promote by printed rank. A promotion is TWO edits — milestone AND the body's score line
  `→ Now`. Only `type:story` counts; donors walk `Next` → `Later` → `Roadmap` (ADR-099 ¶3, one
  product pick per cycle). **`NO REMEDY IN THE CORPUS`** — file work, unblock, amend, or hand
  off; never lower `bc.NOW_LIVENESS_MIN`.
- **Sweep `Later`**: `python3 scripts/check_backlog_hygiene.py --advisory --rule later_staleness`.
  Every printed issue gets an explicit promote-or-close call (or "keep, because <reason>").
- The handover carries one line either way: `**Backlog:** Now <n> actionable (promoted
  #N, #M); Later sweep — <calls made>` or `**Backlog:** Now live at <n>; no stale Later
  issues`.

### (e10) Alarm-citation gate — a wrap gate, same shape as (d)/(e)/(e2)–(e9) (#1959)

`python3 scripts/check_alarm_citations.py` (Phase 1) reads live CloudWatch read-only and
cross-references `docs/alarm_citations.json`: an alarm in ALARM >72h needs an entry, one
>14 days needs a filed issue `#N` (#2378), and a fired-and-cleared flap inside the window
is answered the same way (#2912). Add the entry (file the issue first), or write the
shortfall into the handover and re-run with `--decoded`. AWS unreachable → `UNVERIFIED`,
exit 0 — say so. The handover carries one line either way: `**Alarms:** <N> red >72h, all cited`,
`**Alarms:** <M> uncited — named: <alarm names>`, or `**Alarms:** unverified — AWS unreachable`.

### (e11) Standing-warning triage gate — a wrap gate, same shape as (d)/(e)/(e2)–(e10) (#1966)

`python3 scripts/check_ci_warnings.py` (Phase 1) lists every `warning` annotation on the
latest green CI/CD run on main. Each gets an issue or a named no-action call, then
`--decoded`. GitHub unreachable → `UNVERIFIED`, exit 0 — say so.
The handover carries one line either way: `**CI warnings:** none`, `**CI warnings:**
<N> — <one-line triage per warning>`, or `**CI warnings:** unverified — GitHub unreachable`.

### (e12) Proportionality-ledger gate — a wrap gate, same shape as (d)/(e)/(e2)–(e11) (#2380, enforced by #2761)

`python3 scripts/check_proportionality_ledger.py` (Phase 3, advisory since #4262) passes only on a
`docs/PROPORTIONALITY.md` diff this session OR an explicit `**Ledger:**` line. A NEW standing
subsystem (CI gate, scheduled writer, watcher, alarm, workflow) gets its row (posture + rent +
demote trigger, ADR-103/144) in the wrap commit; a line claiming a row the ledger never saw
fails. The handover carries one line either way: `**Ledger:** <subsystem> row added`,
`**Ledger:** omitted — <reason>`, or `**Ledger:** none — no standing machinery shipped`.

## Phase 3 — Verify: the gates that read the finished handover

```bash
python3 scripts/wrap_gates.py --verify
```

Runs `scripts/check_handover_lines.py` (#4262 — blocks only on the (e4) residual section;
an absent "carries one line" marker prints `PROMPT`), (e4), (e12) (advisory), the (d) validators,
`tests/test_operating_knowledge_ledger_2848.py`, and **the Docs-CI leg** (`docs_ci_gate_commands()`
minus `MUTATING_GATES`) AFTER Phase 2 wrote `docs/INCIDENT_LOG.md`, `docs/alarm_citations.json`,
`docs/PROPORTIONALITY.md`, `docs/**` and `CLAUDE.md` (#3682). **It must exit 0 before (f).**

## Phase 4 — Commit

### (f) Commit the wrap

Phase 3 must have exited 0; stage repo-tracked artifacts only:

```bash
git add handovers/HANDOVER_LATEST.md CLAUDE.md docs/ site/story/build/beats.json   # beats.json only if (d) fired; docs/ covers (e) pages, (e3) docs/INCIDENT_LOG.md (#3682 — stage it explicitly), (e10) docs/alarm_citations.json, (e12) docs/PROPORTIONALITY.md
git commit -m "docs(wrap): <short session theme> (<n items/PRs shipped>)"
```

## Guardrails (do not relax these)

| Gate (the rule) | Step | Script / assertion | Handover line (a prompt since #4262; residual required) |
|---|---|---|---|
| Beat or explicit skip (#736); merged-and-live work only | (d) | `validate_beats.py` + `content_policy_scan.py` | `**Build beat:**` |
| Docs or explicit skip (wiki contract) | (e) | derived Docs-CI leg (Phase 3) | `**Docs:**` |
| Decisions or explicit skip (#1343) | (e) | `check_handover_lines.py` | `**Decisions:**` |
| Main declared from a read badge (#1327; stranded #1901/#2052) | (e2) | `scripts/check_main_green.py` | `**Main:**` |
| Incident rows or explicit skip (#1332), Patterns regenerated and staged (#3682) | (e3) | `incident_log_patterns.py --check` | `**Incidents:**` |
| Residual bullets cite `#N` or `not-work — <reason>` (#1340) | (e4) | `scripts/check_residual_queue.py` + `check_handover_lines.py` | the section (required) |
| Stash empty + hook fresh, or explained (#1326) | (e5) | `git stash list` + `session_postflight.py` | `**Stash/hooks:**` |
| Filing-contract violators fixed, not deferred (#1870, blocking since #1872) | (e7) | `scripts/check_backlog_hygiene.py` bare | fail-open noted |
| An outcome verdict — the ADR-099 closure comment — on every closure (#1870); an instrument closes on live proof (#3595) | (e8) | `closure_sweep.py --session` | `**Closures:**` |
| `Now` refilled by stored rank; every stale `Later` issue gets a promote-or-close call (#1870) | (e9) | `backlog_next.py --refill-now --lane <model>` | `**Backlog:**` |
| A red alarm >72h, or a flap, is cited or named (#1959/#2912) | (e10) | `scripts/check_alarm_citations.py` | `**Alarms:**` |
| A `::warning::` on green main is triaged (#1966) | (e11) | `scripts/check_ci_warnings.py` | `**CI warnings:**` |
| Standing machinery gets a PROPORTIONALITY row, or says why not (#2380, #2761) | (e12) | `scripts/check_proportionality_ledger.py` (advisory) | `**Ledger:**` |

Also binding: **replace, don't stack** (one status paragraph); **one live handover** on `main`
(#1650); **body follows index**, never an index-only patch (#1342).
