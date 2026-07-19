Interview Matthew conversationally, compose a journal entry from his answers, and write
it to the Notion journal DB — the reviving replacement for hand-typing into Notion. See
`docs/coaching/CHAT_MODES.md` for the connector-capability findings this command depends
on (read it before the first real use of this command, not just this file) and the
route-the-takeaways contract.

**Notion is the sole journal source of truth.** This command never writes a journal entry
through a life-platform MCP tool — there is no such tool, by deliberate decision (dual-SOT
was rejected). The only write path is the Notion connector (`notion-create-pages` /
`notion-update-page`), which are external claude.ai connector tools, not part of this
repo's MCP registry.

## Arguments: $ARGUMENTS

Optional: `morning`, `evening`, or `weekly` to pick the variant directly. Empty: ask
Matthew which one he wants (or infer from context — e.g. it's evening and he hasn't
journaled today → default to offering `evening`).

## Instructions

### 1. Pick the template

Valid `Template` select values on the live Notion journal DB: `Morning`, `Evening`,
`Weekly Reflection`, `Stressor`, `Health Event`. This command drives the three routine
ones (Morning/Evening/Weekly Reflection); if what Matthew describes is really a Stressor
or Health Event entry, use that template value instead and adapt the interview
questions to fit — don't force a routine-template shape onto an off-cycle entry.

### 2. Interview conversationally — don't hand him a form

Ask a few open questions, one at a time, adapting to what he says rather than running a
fixed checklist. Rough shape per variant (adapt, don't recite verbatim):

- **Morning**: how'd you sleep / how do you feel, what's today's shape (training,
  work, anything specific on your mind), any intention for the day.
- **Evening**: how did today actually go, what stood out, mood, anything unresolved.
  Bridge to two things before closing (see step 4): `log_evening_intake` if he mentions
  drinking, and any pending coach check-in question that's a natural fit for the
  conversation already happening (`get_coach_checkin_queue` — offer it, don't force it).
- **Weekly Reflection**: zoom out — what pattern showed up this week across training/
  nutrition/mood/work, what he'd change, what he's proud of. Consider pairing with a
  `get_field_notes` read for the current week and offering to fold in a response to the
  AI Lab Notes if there's something worth disputing/adding (routes to
  `log_field_note_response`, not this entry).

### 3. Compose the entry

Synthesize his answers into prose — organize and tighten, but stay faithful to what he
actually said (this is composition, not the coach-checkin VERBATIM bar; see
CHAT_MODES.md's verbatim/skip rules for the distinction). Do not invent detail he didn't
give you — a composed journal entry is still a narrative surface (ADR-104's
grounded-generation posture applies).

### 4. Write the page — the date-key gotcha is load-bearing, don't skip it

Call `notion-create-pages` with:
- `Template`: the exact select value chosen in step 1.
- The title/body properties per the DB's actual schema (check with the connector's
  search/fetch tools if unsure of exact property names — CHAT_MODES.md's finding is that
  exact names + valid option names are required, there's no fuzzy match).
- **The date, using the expanded key syntax** — `"date:Date:start": "YYYY-MM-DD"`
  (optionally `"date:Date:end"` / `"date:Date:is_datetime"`). **Do not** pass a plain
  `"Date": "YYYY-MM-DD"` — per CHAT_MODES.md that does not set the property.
  - For a backdated entry (e.g. an evening entry written the next morning about
    yesterday), get this right deliberately — if the date key is wrong or omitted,
    `notion_lambda.py` falls back to the page's `created_time` (Pacific Time), which
    would misdate the entry to today instead of the day it's actually about.
  - **CHAT_MODES.md flags this as unverified in a live write as of this writing** — if
    this is among the first live uses of this command, confirm the date actually landed
    (fetch the page back, or check it renders with the right date on `/mind/journal/` or
    wherever the site surfaces it) before trusting the date key silently on future runs.
    If it fails, that's a degraded-not-broken outcome per CHAT_MODES.md — don't panic,
    just note it and prefer explicit Matthew confirmation of the date until fixed.

### 5. Close out

- Confirm the page was created (echo back what was written, or fetch it back if the date
  key needs verifying per step 4).
- If step 2's evening bridge surfaced a drinks count, call `log_evening_intake` now (0-4
  tap, count only — no free text needed, that already lives in the journal entry).
- If step 2 surfaced an answer to a pending coach check-in question, call
  `log_coach_checkin` with that answer VERBATIM (not the journal's composed prose —
  pull his actual words for the checkin answer specifically).
- Anything else that came up that isn't "journal entry" — a decision, an insight, a
  durable memory — route it per the CHAT_MODES.md contract, don't fold it silently into
  the journal page and leave it uncaptured elsewhere.
