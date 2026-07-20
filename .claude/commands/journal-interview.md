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

### 0. Open with one call (evening especially)

Call `get_capture_queues` once before the first question — it returns everything the
bridging steps below need in a single read: the evening-intake status (`logged_tonight`,
`tonight_count`, dose-response arming progress), the open coach check-in questions, and
the habit-reflection counts. Don't recite any of it at Matthew — it's your pre-flight
picture, not an agenda. Skip-without-penalty applies to every queue it reports.

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
- **Evening — this is THE unified evening flow (#1484)**: how did today actually go,
  what stood out, mood, anything unresolved. The evening variant is deliberately a
  bridge across every evening surface, sequenced in step 5: interview → Notion write →
  the one-tap drinks count → (optionally) ONE pending coach check-in question →
  (optionally) a habit-miss "why" that already surfaced. Whole thing lands in under
  10 minutes — if it's running long, the journal entry wins and the bridges drop
  first, never the reverse.
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

### 5. Close out — the evening bridge sequence (#1484)

- Confirm the page was created (echo back what was written, or fetch it back if the date
  key needs verifying per step 4).
- **Evening only — the intake tap, ALWAYS offered, one tap:** if step 0's
  `evening_intake` shows `logged_tonight: false`, ask for tonight's drinks count and call
  `log_evening_intake` (0-4, count only — no free text needed, the texture already lives
  in the journal entry). Don't wait for him to mention drinking — the whole point is
  that the arming dose-response engine needs the zeros too; a quiet "and drinks
  tonight — zero?" is the tap. If he already logged (`logged_tonight: true`), skip
  silently unless he corrects the number — the tool is idempotent: re-logging the same
  evening updates the row (it returns `previous_count`), never double-counts. The
  tool defaults the date to the Pacific evening — only pass `date` explicitly for a
  backdated entry (yesterday's evening written this morning).
- **At most ONE coach check-in question, only if it fits:** if step 0's queue has an
  open question that the conversation already brushed against, offer it ("Reeves has
  been wondering X — want to answer while we're here?"). One question maximum, skip is
  always fine, and the answer goes to `log_coach_checkin` VERBATIM (not the journal's
  composed prose — pull his actual words for the checkin answer specifically). Working
  the full queue is `speak-to-coaches`' job, not this flow's.
- **Habit-miss "why", only if it surfaced on its own:** if the interview naturally
  produced the why behind a missed habit (or the driver behind a completed one), route
  it to `log_habit_reflection`. Reactive only — never open a habit line of questioning
  from the queue counts (CHAT_MODES.md's optional-and-reactive rule).
- Anything else that came up that isn't "journal entry" — a decision, an insight, a
  durable memory — route it per the CHAT_MODES.md contract, don't fold it silently into
  the journal page and leave it uncaptured elsewhere.
- The evening ledger stays drinks-only by decision — no evening-energy tap, no second
  numeric field (ADR-137). Mood lives in the journal + the nudge's `mood_valence`;
  don't invent capture surfaces at the close.
