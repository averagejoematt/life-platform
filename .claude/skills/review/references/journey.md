# Rubric — `/review journey`

Loaded by `.claude/skills/review/SKILL.md`. The spine owns the phases, the evidence rule and the
verification pass. **The ADR-099 filing contract lives in exactly ONE place —
`.claude/agents/issue-filer.md` — and is never restated here or in any other rubric.** This file
owns the **checks, the collaborative step and the bar** for the chat↔platform seam.

**No clock — and that is a decision, not a lapse.** `scripts/operating_calendar.py` carries a dated
exemption for this lens: its trigger is *the seam changed* — a new MCP write tool ships, a chat
mode is added or rewritten, or Matthew says the claude.ai Project prompts feel out of sync with
what Claude Code actually does. A ritual whose trigger is an event already has a clock; cadencing
it on top would manufacture runs with nothing to audit.

This lens is smaller in scope and model than `full` or `sdlc`: a narrow, recurring check that ends
in a short report and, if warranted, filed issues. It is not a code-shipping session by default.

## What this lens grades

Whether the four chat modes (`daily-debrief`, `journal-interview`, `speak-to-coaches`,
`open-checkin` — `docs/coaching/CHAT_MODES.md`) still line up with what the platform actually
exposes: capture surfaces that went stale or dark, MCP tools that exist but nothing routes to, and
the one drift this lens can flag but not fix — the repo's skill files versus the Matthew-side
claude.ai Project prompts condensed from them.

**This lens is its own cautionary tale.** It once audited four of seven chat modes and hunted a
string that no longer existed anywhere in the tree, while reading as a healthy ritual. A drift
detector that has itself drifted reports clean for the same reason a broken smoke alarm does. So:
every check below names the file it diffs against, and step 1 is re-reading the contract rather
than trusting this file's summary of it.

## 1. Read the current contract

Read `docs/coaching/CHAT_MODES.md` in full — both the connector-capability section and the "four
chat modes" section — plus the skill files for the four modes
(`.claude/skills/daily-debrief/SKILL.md`, `.claude/skills/journal-interview/SKILL.md`,
`.claude/skills/speak-to-coaches/SKILL.md`, `.claude/skills/open-checkin/SKILL.md`). That is the
baseline every check below diffs against. If the mode list in `CHAT_MODES.md` and the skill corpus
disagree, that disagreement is finding #1.

## 2. Sweep the MCP tool inventory for capture-surface drift

Use `list_available_tools` (or read `mcp/registry.py` directly) to enumerate write tools that look
like capture surfaces — anything that logs, saves, writes or records something Matthew says or
decides (`log_*`, `save_*`, `write_platform_memory`, …). Cross-check every one against the
route-the-takeaways contract table in `CHAT_MODES.md`:

- **Orphaned write tool** — a capture-shaped tool that exists but no skill routes to it. Flag it:
  either a mode needs a new row, or the tool is genuinely dead and belongs on a future prune list.
  Don't remove it yourself; that's a separate decision.
- **Stale contract row** — a table row pointing at a tool that no longer exists in the registry, or
  whose schema changed shape (args renamed or removed) since the doc was written. Verify against the
  live schema, not memory.
- **New since last sweep** — any write tool shipped after the newest mode file's last edit is a
  candidate the contract hasn't absorbed yet.

The one-call session opener `get_capture_queues` (`mcp/tools_capture.py`) shipped and IS the
canonical opener. Check that every mode file and `CHAT_MODES.md` open with it rather than calling
the underlying queue tools separately — a mode still fanning out by hand is a live finding, not a
pending one.

## 3. Check for stale or dark channels

For each of the four capture modes, form a view of whether it looks used or dormant: `git log
--oneline -- <skill file>` for the contract's age, and for actual usage evidence read what has
landed in the underlying DDB partitions (recent `log_coach_checkin` / `save_insight` /
`write_platform_memory` activity via the read-side tools — `get_insights`, `get_decisions`,
`list_memory_categories`). A mode with zero real-world writes since it shipped isn't necessarily
broken, but it is worth a note: either Matthew isn't using it (fine, no alarm) or something about
it is friction (worth asking).

This is explicitly NOT the freshness-checker's job — that owns per-source staleness. This is about
whether the *chat modes themselves* are getting exercised, which nothing else monitors.

## 4. Check prompt/config parity against the claude.ai side (collaborative by necessity)

This repo cannot read the claude.ai Project prompts — they are a Matthew-side artifact with no API
surface this session can reach. So:

- Summarize, in plain language, what each mode file currently instructs (the shape of the
  interview, the routing table, any recent rule changes).
- Ask Matthew whether the claude.ai Project prompts still match — or, if he's willing, have him
  paste the current prompt text in for a side-by-side diff.
- Flag anything changed on the repo side since the last known condensation (`git log` on the mode
  files to date the most recent substantive change) as "likely needs re-condensing".
- **Never** attempt to write or push content into claude.ai from here — per `CHAT_MODES.md`'s
  condensation note that step is Matthew's, manual, out-of-band. This lens's job is only to make
  the drift visible.

## 5. Report

A short report — prose is enough unless findings are substantial:

- orphaned write tools / stale contract rows from step 2, each with a fix recommendation;
- dormant-mode observations from step 3 (informational, not alarms);
- parity status from step 4 — in sync / likely drifted / needs Matthew's input to know;
- any doc-wide update pass a shipped tool now requires, with every file that needs the edit named.

If findings warrant tracked work (a real drift fix, a genuinely dead tool, a contract gap), offer to
file them — but do not file automatically. This lens surfaces; it does not unilaterally expand the
backlog.

## The bar

A `/review journey` succeeds when, on top of the spine's bar: every one of the four modes was
actually opened and diffed (not sampled), every capture-shaped write tool in the live registry was
accounted for as routed or orphaned, and the parity verdict names which side is stale rather than
saying "may have drifted".
