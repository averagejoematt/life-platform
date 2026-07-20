# CHAT_MODES.md — conversation as an ingestion channel

> **Status:** foundation doc. The original scope (through "Why this matters beyond the
> journal itself" below) covers the connector-capability findings `#1480` verified and is
> unchanged since. `#1479` (chat-mode command library, same epic — `#1476` chat-journey:
> conversation as the 4th ingestion channel) adds the "The four chat modes" section below
> it, which defines the modes themselves and the command files that implement them.

## Why this exists

The revival plan for the Notion journal channel (the SOT for subjective data — it feeds
enrichment → PERMA flourishing → the Mind pillar) is Claude-interview entries: a
journal-interview chat mode that writes structured pages to the Notion journal database
via the Notion MCP connector (`notion-create-pages` / `notion-update-page`), rather than
Matthew hand-typing into Notion. This doc records what that connector can and can't set
on a page at creation time, verified against `lambdas/ingestion/notion_lambda.py`'s
actual parsing behavior (`tests/test_notion_mcp_page_guard_1480.py` pins the findings
below as regression tests).

## What the connector can set

Properties are passed to `notion-create-pages` as a flat JSON map: `property name →
string | number | null`. There is **no structural block** on setting a `select`
property (like `Template`) or a plain string/title/rich_text/number/checkbox property
at page-creation time, **provided**:
- the integration has write access to the target database, and
- the exact property name and a valid select-option name are used (e.g.
  `"Template": "Evening"` must match one of the database's actual select options —
  `Morning`, `Evening`, `Weekly Reflection`, `Stressor`, `Health Event`).

So: **`Template` does NOT need to be set by hand.** A journal-interview chat mode can
set it directly via the connector, and `notion_lambda.py`'s `parse_page()` recognizes it
through the canonical `TEMPLATE_SK` map exactly as if it had been picked from the Notion
UI — the ingest path is schema-flexible and doesn't distinguish creation method.

## The one gotcha: the Date property's expanded key syntax

**Date properties need an expanded key format, not a plain value.** A plain
`"Date": "2026-07-19"` is *not* the right shape — the Notion MCP tooling expects the
expanded key convention:

```
"date:Date:start": "2026-07-19"
"date:Date:end": null            (optional)
"date:Date:is_datetime": false   (optional)
```

This is documented explicitly on `notion-update-page`'s tool schema; `notion-create-pages`
uses the same underlying properties schema, but its (truncated) tool description doesn't
spell out the date-expansion convention as explicitly. **Flag this as the one thing worth
testing live before relying on it** — a malformed or omitted date key would silently
produce a page with no `Date` property set, not an error.

**Failure mode if the date key is wrong: degraded, not broken.** `notion_lambda.py`'s
`parse_page()` already tolerates a missing `Date` property — it falls back to the page's
`created_time`, converted to Pacific Time, to derive the entry's date
(`notion_lambda.py` ~L474–487). A malformed date key therefore doesn't lose the entry; it
just anchors it to "when the page was created" instead of an explicit (possibly
backdated) date. That matters if an entry is written the morning after the day it
describes — the created_time fallback would misdate it to the write day, not the day
being journaled about. `tests/test_notion_mcp_page_guard_1480.py` pins both the
happy path (explicit `Date` set) and the fallback path (created_time → PT date,
including the UTC-day-boundary case for late-night entries).

## Net effect

No property is structurally connector-blocked. The one operational caveat is getting
the Date property's expanded key syntax right — or accepting the created_time fallback,
which works but is less precise for backdated entries. This should be confirmed with one
live test page before a chat mode is relied on for daily journaling (see `#1480`'s PR
for the exact manual verification steps).

## Why this matters beyond the journal itself

The journal channel had gone dark for extended stretches with no alarm — the generic
per-source freshness check tolerates Notion for 14 days (a deliberately lenient
evening-nudge threshold for ad-hoc journaling, `#746`) and the `notion` source-registry
entry is `monitored: False`, which structurally excludes it from the freshness checker's
paging path at *any* staleness. `#1480` added a separate, tighter guard —
`check_notion_journal_staleness()` in `lambdas/emails/freshness_checker_lambda.py` —
that alerts when the journal goes dark for more than `NOTION_JOURNAL_DARK_ALERT_DAYS`
(default 7) days, because journaling is a daily practice and enrichment → PERMA
flourishing → the Mind pillar all go quiet with it. That guard's alert message points
back at this doc as the "what to do" — write an entry, or run a journal-interview chat
mode once one exists (`#1479`).

---

# The four chat modes (#1479)

This section is the follow-through the status note above anticipated — it does not
change or contradict anything recorded above, it defines what consumes those findings.

Conversation is the platform's fourth ingestion channel (epic `#1476`, alongside
wearables/APIs, manual uploads, and the Notion journal itself). Each mode below is a
**versioned, invocable playbook** — a `.claude/commands/*.md` file in this repo — usable
from Claude Code today. There is no separate "skills" location in this repo:
`.claude/commands/*.md` files ARE the skills (the available-skills list Claude Code
surfaces is generated 1:1 from these filenames).

## The modes

| Mode | Command file | What it's for | Cadence |
|---|---|---|---|
| **Daily debrief** | `.claude/commands/daily-debrief.md` | Post-workout review + night-before session authoring (`manage_hevy_routine` draft→dry_run→commit). Condensed from `docs/coaching/COACH_SESSION.md`, which stays the full source. | Nightly, when training |
| **Journal interview** | `.claude/commands/journal-interview.md` | Claude interviews Matthew, composes a journal entry, writes it to the Notion journal DB (Morning / Evening / Weekly Reflection / Stressor / Health Event templates). | Daily / ad hoc |
| **Speak to coaches** | `.claude/commands/speak-to-coaches.md` | Works the open coach check-in queue (`#915`) one question at a time, conversationally; optional habit-reflection pass; weekly Field Notes response. | Ad hoc, whenever Matthew has a few minutes |
| **Open check-in** | `.claude/commands/open-checkin.md` | Free-form talk with no queue to work — Matthew just talks, Claude routes whatever comes up to the right write tool at the close. | Whenever |

A fifth command, `.claude/commands/journey-review.md`, is not a capture mode — it's the
periodic ritual that audits these four for drift (MCP inventory sweep, stale-channel
check, prompt/config parity against the claude.ai Project prompts). See its own file for
scope.

**`get_capture_queues` (`#1478`) is SHIPPED and is the canonical opener.** Every mode's
queue-gathering step is that ONE call — it aggregates the coach check-in queue, habit
reflection counts, the week's field-note status, evening-intake status (`logged_tonight`,
`tonight_count`, dose-response arming), due reading recalls, and freshness flags. The
individual tools (`get_coach_checkin_queue`, `get_habit_reflection_queue`,
`get_field_notes`, `get_freshness_status`, `get_due_recalls`) remain for mid-session
depth — e.g. `get_coach_checkin_queue` when a fresh question should be *generated*; the
opener deliberately never triggers generation.

**The evening is ONE flow (`#1484`).** The journal-interview *evening* variant is the
unified evening ritual, bridging what used to be four separately-skippable surfaces:
interview → Notion write → the one-tap drinks count (always offered when
`logged_tonight` is false — the arming dose-response engine needs the zeros too) → at
most ONE pending coach check-in question, only if it fits the conversation → any
habit-miss "why" that surfaced naturally. Under 10 minutes; when time runs short the
journal entry wins and the bridges drop, never the reverse. `log_evening_intake`
defaults its date to the PACIFIC evening (matching the nudge link's write path) and is
observably idempotent — re-logging the same evening updates the row and returns
`previous_count`, never double-counts. The ledger stays drinks-only by decision — no
evening-energy tap (ADR-137).

## The route-the-takeaways contract

Every mode ends the same way in spirit: whatever Matthew said gets routed to the ONE
correct write tool. This table is the contract every command file points back to instead
of re-deriving it:

| Takeaway type | Write tool | Notes |
|---|---|---|
| Coach check-in answer | `log_coach_checkin` | VERBATIM (ADR-104), or `skip=true` — always valid, zero penalty. |
| Habit trigger / reward / why-missed | `log_habit_reflection` | Optional pass only, never nag or schedule. |
| Weekly Field Notes response | `log_field_note_response` | The week's AI Lab Notes must already exist (`get_field_notes` first). |
| Insight / hypothesis / pattern noticed | `save_insight` | Returns `insight_id` for a later `update_insight_outcome` call. |
| A decision (followed/overrode platform advice) | `log_decision` | Outcome recorded later via `update_decision_outcome`. |
| Durable context (calibration, failure pattern, what worked, milestone, weekly plate, personal curve, experiment result) | `write_platform_memory` | `category` must be one of the 7 enum values — see the tool schema. |
| Evening drinks count | `log_evening_intake` | PRIVATE (`#1405`) — 0-4 tap, no free text. Defaults to the Pacific evening; idempotent (re-log updates, returns `previous_count`). Drinks-only by decision — ADR-137. |
| Journal entry (Morning/Evening/Weekly Reflection/Stressor/Health Event) | Notion connector (`notion-create-pages`) | **Not** an MCP write — Notion is the sole journal SOT (dual-SOT rejected, see the 2026-07-18 chat-journey session notes). Use the expanded date-key syntax from the section above. |
| Night-before training session | `manage_hevy_routine` (`draft_custom` → `dry_run` → `commit`) | Never pass `title` — it's auto-rendered. |

Each command file below states which rows of this table it uses; none should invent a
write path not on this list.

## Verbatim / skip rules

- **`log_coach_checkin` answers are VERBATIM, never paraphrased** (ADR-104 — the platform
  never puts words in Matthew's mouth). Claude may ask a clarifying follow-up, but the
  text passed to `answer` is what Matthew actually said.
- **Skipping any queued question is always valid, zero penalty, never nagged.** This
  applies to `log_coach_checkin` (`skip=true`) and to `get_habit_reflection_queue` items
  Matthew doesn't want to discuss — silently move on, don't ask twice in one session.
- **`log_habit_reflection` and the habit-reflection pass generally are OPTIONAL and
  reactive** — only surface them when Matthew is already reflecting on his day/week in
  the conversation. Never schedule or open a session with "let's talk about your habits."
- **Journal-interview composition is a synthesis, not a transcript** — Claude may
  organize and tighten Matthew's spoken answers into prose, unlike the coach-checkin
  verbatim bar. It should still stay faithful to what he actually said; it is not license
  to invent detail he didn't give (ADR-104's grounded-generation posture applies to any
  narrative surface, including a composed journal entry).

## claude.ai vs. Claude Code: the repo is upstream

Matthew also runs these modes as Project prompts inside a claude.ai Project (mobile/
web, no repo checkout). **The repo's command files here are the single source of
truth; the claude.ai Project prompts are a Matthew-side artifact condensed FROM them —
never the reverse.** Concretely:

- A behavior change (a new write tool, a changed routing rule, a new verbatim/skip rule)
  is made in the relevant `.claude/commands/*.md` file first, and in this doc's
  route-the-takeaways contract if it adds or changes a row.
- The claude.ai Project prompt is then hand-condensed from the updated command file —
  that condensation step is Matthew's, not automated (no MCP write path pushes prompt
  text into claude.ai). It happens on Matthew's own cadence, not per-commit.
- Because the condensation is manual and out-of-band, the two surfaces **can drift**.
  `.claude/commands/journey-review.md` is the periodic check for that drift — it doesn't
  fix it (it can't reach the claude.ai side), it flags it so Matthew can re-condense.
- If the two surfaces ever visibly disagree in a live session, the repo file wins — a
  claude.ai Project prompt is never the tiebreaker.
