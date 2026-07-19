# /journey-review — re-audit the chat↔platform integration

Periodic ritual that checks the four chat modes (`daily-debrief`, `journal-interview`,
`speak-to-coaches`, `open-checkin` — `docs/coaching/CHAT_MODES.md`, epic `#1476`) for
drift: capture surfaces that went stale or dark, MCP tools that exist but nothing routes
to, and the one drift this ritual can flag but not fix — the repo's command files versus
the Matthew-side claude.ai Project prompts condensed from them. This is NOT a code-shipping
session by default; it's a survey that ends in a short report and, if warranted, backlog
issues for what it finds. Model/scope smaller than `/frontier-plan` or `/sdlc-review` —
this is a narrow, recurring check, not a full-platform review.

Cadence: run this every few weeks, or whenever a new MCP write tool ships, or whenever
Matthew mentions the claude.ai Project prompts feel out of sync with what Claude Code
actually does.

## Arguments: $ARGUMENTS

Optional: a specific worry to seed the sweep with (e.g. "I think the habit reflection
queue never gets used" or "the claude.ai journal prompt still mentions a template I
renamed"). Empty: run the full unseeded sweep below.

## Instructions

### 1. Read the current contract

Read `docs/coaching/CHAT_MODES.md` in full (both the connector-capability section and
the "four chat modes" section) and all five `.claude/commands/{daily-debrief,
journal-interview,speak-to-coaches,open-checkin,journey-review}.md` files. This is the
baseline every check below diffs against.

### 2. Sweep the MCP tool inventory for capture-surface drift

Use `list_available_tools` (or read `mcp/registry.py` directly) to enumerate write tools
that look like capture surfaces — anything that logs, saves, writes, or records something
Matthew says or decides (`log_*`, `save_*`, `write_platform_memory`, etc.). Cross-check
every one against the route-the-takeaways contract table in `CHAT_MODES.md`:

- **Orphaned write tool**: a capture-shaped tool that exists but no command file routes
  to it. Flag it — either a command needs a new row, or the tool is genuinely dead and
  belongs on a future prune list (don't remove it yourself; that's a separate decision).
- **Stale contract row**: a table row pointing at a tool that no longer exists in the
  registry, or whose schema changed shape (args renamed/removed) since the doc was
  written. Verify against the live schema, not memory.
- **New since last sweep**: any write tool shipped after the newest command file's last
  edit is a candidate the contract hasn't absorbed yet.

Also check whether `#1478` (`get_capture_queues`) has shipped — if it has, this is a
must-fix: every command file and `CHAT_MODES.md` currently say "call the individual queue
tools until #1478 ships." That's now a stale claim requiring an update pass, not just a
finding to file.

### 3. Check for stale or dark channels

For each of the four capture modes, form a view (from git history — `git log --oneline
-- <file>` on the command file, and for actual usage evidence look at what's actually
landed in the underlying DDB partitions this session can read, e.g. recent
`log_coach_checkin`/`save_insight`/`write_platform_memory` activity via the read-side
tools like `get_insights`, `get_decisions`, `list_memory_categories`) for whether the mode
looks used or dormant. A mode with zero real-world writes since it shipped isn't
necessarily broken, but it's worth a note — either Matthew isn't using it (fine, no
alarm), or something about it is friction (worth asking).

This is explicitly NOT the freshness-checker's job (that's `#1480`'s
`check_notion_journal_staleness` and the general per-source checks) — this is about
whether the *chat modes themselves* are getting exercised, which nothing else monitors.

### 4. Check prompt/config parity against the claude.ai side

This repo cannot read the claude.ai Project prompts directly — they're a Matthew-side
artifact with no API surface this session can reach. So this check is necessarily
collaborative, not automatic:

- Summarize, in plain language, what each command file currently instructs (the shape
  of the interview, the routing table, any recent rule changes).
- Ask Matthew directly whether the claude.ai Project prompts still match — or, if he's
  willing, have him paste the current claude.ai prompt text into the conversation for a
  side-by-side diff.
- Flag anything that's changed on the repo side since the last known condensation (use
  git log on the command files to date the most recent substantive change) as "likely
  needs re-condensing."
- Never attempt to write or push content into claude.ai from here — per
  `CHAT_MODES.md`'s condensation note, that step is Matthew's, manual, out-of-band. This
  ritual's job is only to make the drift visible.

### 5. Report

Produce a short report (prose, not necessarily a new doc file — a handover-style summary
is enough unless findings are substantial):
- Orphaned write tools / stale contract rows found in step 2, with a fix recommendation
  each (add a row, or flag for a future prune pass).
- Dormant-mode observations from step 3 (informational, not alarms).
- Parity status from step 4 — in sync / likely drifted / needs Matthew's input to know.
- If `#1478` shipped: the required update pass (list every file that says "until #1478
  ships").

If findings are substantial enough to warrant tracked work (a real drift fix, a genuinely
dead tool, a contract gap), offer to file them as GitHub issues per the standing ADR-099
convention — but do not file automatically; this ritual surfaces, it doesn't unilaterally
expand the backlog.
