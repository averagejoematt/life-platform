Interview Matthew conversationally, compose a journal entry from his answers, and write
it to the Notion journal DB — the reviving replacement for hand-typing into Notion. See
`docs/coaching/CHAT_MODES.md` for the connector-capability findings this command depends
on (read it before the first real use of this command, not just this file) and the
route-the-takeaways contract.

**Notion is the sole journal source of truth.** This command never writes a journal entry
through a life-platform MCP tool — there is no such tool, by deliberate decision (dual-SOT
was rejected). The only write path is the Notion connector (`notion-create-pages` /
`notion-update-page`), which are external claude.ai connector tools, not part of this
repo's MCP registry. (The `publish` variant in step 6 is not an exception: it produces a
*public essay* on the separate "In my own words" surface via a PR — the private journal
entry, when one is written, still lands in Notion and only in Notion.)

## Arguments: $ARGUMENTS

Optional: `morning`, `evening`, or `weekly` to pick the variant directly, or `publish`
(#1567) to run the interview → approved-public-essay flow in step 6. Empty: ask
Matthew which one he wants (or infer from context — e.g. it's evening and he hasn't
journaled today → default to offering `evening`). After any regular variant, if the
conversation surfaced something that clearly wants a public airing, you may *offer* the
publish flow at the close ("want to turn this into a public essay?") — offer, never
assume.

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
- **Pull-quote nomination — optional, 0–2 lines, consent per line (#1568, ADR-142):**
  after the entry is written, you MAY nominate at most 2 lines from it as quote-worthy
  for the public "from the journal, in his words" surface. Runtime rules, all hard:
  - **Nominate verbatim lines only** — his exact words from the entry just written,
    never a paraphrase or a composite (ADR-104 grounding; the tool re-verifies).
  - **Refuse to nominate any line touching the taboo list** — the abstract/omit
    sections of `docs/content/ELENA_PREQUEL_BRIEF.md`: substances, family-specifics,
    age, private events (wedding/funeral/therapy/work specifics), real names. The
    `mark_journal_quote` tool enforces the same list in code (fail-closed), but the
    refusal starts with you: a taboo line is never even offered.
  - **Explicit per-line consent:** present each nominated line and ask plainly —
    "want this one public, word for word?" Only on an explicit yes for THAT line call
    `mark_journal_quote` with `approved: true` (date = the entry's date). Silence,
    "maybe", or a general "sure, whatever" is NOT consent to any specific line.
    No nomination lands anywhere without the mark — nothing is ever quotable by default.
  - **Never a nag:** if he says no (or nothing jumps out), drop it silently — zero
    nominations is the normal case, not a failure. Consent is revocable any time via
    `mark_journal_quote(action='unmark', …)`.
  - **The chronicle's never-quote rule is untouched** — this marked-line channel is
    the ONLY path journal words may take to the public site, and it never loosens
    deep-background anywhere else.
- Anything else that came up that isn't "journal entry" — a decision, an insight, a
  durable memory — route it per the CHAT_MODES.md contract, don't fold it silently into
  the journal page and leave it uncaptured elsewhere.
- The evening ledger stays drinks-only by decision — no evening-energy tap, no second
  numeric field (ADR-137). Mood lives in the journal + the nudge's `mood_valence`;
  don't invent capture surfaces at the close.

### 6. The `publish` variant — interview → approved public essay (#1567)

Compose a PUBLIC essay from what Matthew said in the interview and land it as a PR on
the "In my own words" surface (the #1566 generator — read `scripts/v4_build_journal.py`'s
header before the first run). This is the only journal-adjacent path that leaves Notion,
so every rule below is a **runtime rule of the command**, not guidance. The interview
itself runs exactly like step 2 — conversational, one question at a time; only the
composition and destination change.

**a. Grounding — the ADR-104 bar, stricter than step 3.** Every factual claim in the
essay must trace to (i) something Matthew actually said in *this* interview, or (ii)
computed platform data you read via a tool during this session (cite the number as
read, don't round it into a nicer story). Nothing invented: no color he didn't give,
no reconstructed dialogue, no invented chronology, no "surely he felt X" bridging. If
a paragraph needs a fact you don't have, ask him mid-interview or cut the paragraph.

**b. Privacy guardrails applied AT COMPOSITION TIME.** The standing rules are the
Privacy Guardrails + what-to-abstract sections of `docs/content/ELENA_PREQUEL_BRIEF.md`
— re-read them before composing, every time. In particular: abstract family,
relationship, substance, and age specifics; no names or identifying details of people
close to him; no locations/events specific enough to dox; emotional truth over
triggering detail. Shape the abstraction while composing — never draft raw and
sanitize afterward, because raw phrasing leaks through edits.

**c. The approval gate — Matthew approves the EXACT final text in-chat before any PR
opens.** Paste the complete essay body in the chat, plus the metadata he's implicitly
approving (title, excerpt, date, slug/url). He reviews line by line. Any change he
asks for produces a fresh *full* paste for re-approval — the text that lands in the PR
must be byte-for-byte the text he approved. No post-approval tightening, no silent
typo fixes; a typo fix is a new approval round. **If he does not approve (or goes
quiet, or says "not this one"): save the draft privately to Notion instead (step 4's
write path — pick a fitting template per step 1, note in the body that it's an
unpublished essay draft) and STOP. No approval → no PR, nothing public, ever.**

**d. Landing it — a PR, never a direct publish.** The approved essay is two files plus
metadata (the #1566 two-edit contract), on a branch, as an ordinary PR Matthew merges
himself:

1. Append one entry to `site/journal/blog.json` `posts[]` per its `_schema` (id,
   title, date, excerpt, `url: /journal/essays/<slug>/`, label, word_count…),
   **including the provenance line**:
   `"provenance": "composed from a YYYY-MM-DD interview, approved by Matthew"`
   (the *interview* date, not the publish date). The generator renders it after the
   body in the receipts register.
2. Write the approved body **verbatim** to `site/journal/essays/<slug>/body.md`
   (or `body.html` if what he approved was styled HTML) — the file content IS the
   approved text.

Verify before opening the PR: `python3 scripts/v4_build_journal.py` (dry-run — the new
page must render and pass the fail-closed `privacy_guard` gate) and
`python3 scripts/content_policy_scan.py` (essay bodies and blog.json sit inside its
`site/` scan scope automatically — no config change is ever needed for a new essay).
**A privacy-guard or scanner hit means rewrite → re-approve (back to c) — NEVER add an
essay path to the scanner's `ALLOWLIST_FILES`**; those path-keyed exemptions exist for
filter *definitions*, not for content, and allowlisting content would neuter the gate.
Publishing stays Matthew's act: merging the PR is the publish trigger (a `site/**`
merge auto-deploys, #750, and the deploy path is what passes the generator `--write`).
You never merge, never deploy, and never run `--write` yourself.
