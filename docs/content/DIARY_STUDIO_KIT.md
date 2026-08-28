# Diary Studio Kit

The owner-side setup + operating notes for the Diary Studio (epic #1564 — video
diaries with Claude as the live interviewer). The heavy `/vlog` chat mode and
format library land under #1571; this file is the durable home for the parts
**Matthew** owns by hand, starting with the one Notion change that lets a video
diary flow the existing journal pipeline.

## Owner follow-up (REQUIRED — Notion, Matthew-side) — #1572 AC1

The transcript landing path (#1572) is code-complete on the platform side, but it
only activates once the Notion schema offers the template. **Claude cannot change
Notion; this is yours to click:**

1. Open the journal database in Notion.
2. Edit the existing **Template** select property (the same one that already holds
   `Morning`, `Evening`, `Stressor`, `Health Event`, `Weekly Reflection`).
3. Add a new select option with the **exact** value:

   ```
   Video Diary
   ```

   The value must match exactly (capital V, capital D, single space) — the
   ingestion lambda keys the `video_diary` channel off this literal string
   (`lambdas/ingestion/notion_lambda.py` `TEMPLATE_SK` / `MULTI_PER_DAY`).

That's the whole owner step. Nothing else in Notion changes — the page body is the
transcript, and every other property is read dynamically as usual.

## What happens automatically once a "Video Diary" page exists

No second pipeline (epic #1564 / #1388 AC1). A page tagged `Video Diary` rides the
exact existing path:

1. **Ingest** — hourly `notion-data-ingestion` picks it up, writes it under
   `USER#matthew#SOURCE#notion` / `DATE#YYYY-MM-DD#journal#video_diary#<stable-id>`,
   stamps `channel="video_diary"`, and archives the raw page JSON to
   `s3://matthew-life-platform/raw/matthew/notion/…` (same as any journal page).
   Multiple recordings in one day are supported and dedup by page id.
2. **Enrich** — `journal-enrichment` processes it with **no** template whitelist
   (it enriches any `#journal#` entry ≥ 20 words), producing the same ~25
   `enriched_*` fields as a typed entry.
3. **Flourishing** — the day's `SOURCE#flourishing` PERMA row is projected, now
   carrying `channels` / `channel_entry_counts` so the signal can be read by
   channel.
4. **Character** — `character-sheet` merges the entry's enriched signals into the
   day's journal view (template-agnostic; `video_diary` is in-range).
5. **Hypothesis candidates** — `journal-analyzer` turns any grounded
   `enriched_causal_hints` into `HYPO_CANDIDATE#<slug>` rows the hypothesis engine
   can seed on.

Channel provenance surfaces to the coach/MCP via `get_mood` (per-day `channels` +
a `channel_note`) and `get_flourishing_trend` (`channels_present`).

## Coach reactions on lab-notes (#1574) — the V3-consent opt-in

When a diary entry lands, the relevant coach (routed by the entry's enriched themes —
**mind coach by default**) can write ONE short, grounded reaction that renders on the
public **lab-notes** surface (`/coaching/lab-notes/`) beside a V3-consented sliver of
the entry — the coaches responding to the human, not just the sensors. Producer:
`lambdas/coach/coach_diary_reaction.py`; served by `/api/diary_reactions`; the private
entry is reduced to a leak-proof public context by `lambdas/privacy/diary_consent.py` BEFORE
anything is generated or stored.

**A diary entry is PRIVATE by default — nothing crosses to the public reaction unless
you explicitly opt it in.** Two owner-set Notion properties on the diary page control
this (the `#1483` quote/allude/never tiers, entry-level until the per-line ADR ships):

- `public_reaction_consent` — set to **`allude`** to allow a public reaction that may
  reference the entry's *theme* only (no verbatim words ever), or **`quote`** to also
  allow one specific line to be quoted. **Absent / anything else ⇒ private ⇒ no
  reaction, nothing renders** (fail-closed).
- `public_quote` — (quote tier only) the ONE verbatim line you cleared for quoting. It
  is honored only if it is a literal substring of the entry body (ADR-104 grounding);
  a paraphrase or typo is dropped and the reaction falls back to allude (theme-only).

Budget: gated on the `coach_diary_reaction` reader-narrative feature (`budget_guard`)
— pauses at **tier 2** with the other reader narratives; one Haiku/Sonnet call per
entry; a paused call yields no reaction. Quality: the draft passes the ADR-108
coach quality gate (hold-or-publish, no regenerate — keeps the one-call bound).

**When it fires (#1756).** The reaction is produced by the daily **journal-enrichment**
pass (6:30 AM PT), right after that entry's enrichment lands — the same pipeline, no
second one, and the only place the enriched themes the routing uses exist. So: record
today, mark the consent property, and the reaction appears the next morning. Practical
consequences worth knowing:

- **Marking consent later still works.** Editing the Notion page bumps its
  `last_edited_time`, which re-ingests and re-enriches the entry — and the next
  enrichment pass produces the reaction.
- **One reaction per entry, ever.** The reaction is keyed per entry
  (`DATE#<date>#<channel>#<entry-uid>`), and an entry that already has one is skipped
  before any model call — so re-enrichment (the Sunday 30-day sweep, a schema bump, an
  edit) never re-spends or overwrites. Two recordings on the SAME day each keep their
  own reaction. To deliberately regenerate one, invoke `coach-diary-reaction` manually
  with `{"entry": {...}, "force": true}`.
- **Un-marking does not retract a published reaction.** Consent is read at generation
  time; removing the property afterwards stops future reactions but does not delete the
  stored row — delete the row (or ask for it to be deleted) to pull it off the site.
- **Failures are silent by design.** A budget pause, a quality-gate hold, or an AI error
  yields no reaction and no error: enrichment is never failed by a reaction, and an
  absent reaction renders nothing on lab-notes.

## Solo recordings — local Whisper, no interviewer (#1573)

A **solo recording** is a raw diary made WITHOUT Claude in the room — a voice memo
or a solo video to the Luna, no live interview. It rides the exact same landing
path as a Video Diary, with its own channel provenance (`solo_recording`) so
downstream can tell an unattended solo take apart from an interviewed one and from
a typed entry.

### The transcription script (owner runs it locally) — `scripts/transcribe_solo.py`

Transcription happens **on Matthew's machine** — it is NOT a deployed lambda and
NOT a cloud API call. The audio/video **never leaves the device**; only the
resulting TEXT transcript is posted to Notion.

**Local dependency (install once):**

```bash
# Preferred — openai-whisper (pip; also needs ffmpeg on PATH):
pip install -U openai-whisper
brew install ffmpeg

# Alternative — whisper.cpp (compiled binary + a ggml .bin model):
#   https://github.com/ggerganov/whisper.cpp
```

**Usage:**

```bash
# Transcribe only (prints the transcript, writes nothing):
python3 scripts/transcribe_solo.py ~/Recordings/2026-07-25-solo.m4a

# Transcribe + create the Solo Recording Notion page (needs NOTION_API_KEY +
# NOTION_DATABASE_ID, or --database-id):
python3 scripts/transcribe_solo.py ~/Recordings/2026-07-25-solo.m4a --post-to-notion

# whisper.cpp instead of the pip package:
python3 scripts/transcribe_solo.py rec.m4a --engine whisper.cpp \
  --binary /path/to/whisper-cli --model /path/to/ggml-base.en.bin --post-to-notion

# Preview the exact Notion payload without posting (no network):
python3 scripts/transcribe_solo.py rec.m4a --post-to-notion --dry-run
```

The page body is the transcript; only a **pointer** to the recording (filename +
duration) is recorded as page properties — the video/audio file itself is never
uploaded (#1573 AC2; Matthew separately decides if/when full video ever goes to
S3, cost-gated against the $215 ceiling). For an unattended watched-folder setup,
stage the launchd wrapper + this script to `~/.local/bin`, NOT under `~/Documents`
(the TCC ~/Documents trap — a LaunchAgent reading ~/Documents exits 126).

### Owner follow-up (REQUIRED — Notion, Matthew-side)

As with the Video Diary template, add one more select option to the journal
database's **Template** property, with the **exact** value:

```
Solo Recording
```

Capital S, capital R, single space — the ingestion lambda keys the
`solo_recording` channel off this literal string (`notion_lambda.py` `TEMPLATE_SK`
/ `MULTI_PER_DAY`; `flourishing.py` `_TEMPLATE_CHANNEL`). Once the option exists,
the transcript page flows the same ingest → enrich → flourishing → character →
hypothesis path as everything above, and surfaces distinctly in `get_mood`
(per-day `channels` + `channel_note`) and `get_flourishing_trend`
(`channels_present`) as `solo_recording`.

## The Goodhart rule — engagement may pick cuts, never questions (#1845)

**Standing policy. This is the load-bearing rule of the whole diary surface, and it is
not negotiable per-session.**

> Engagement metrics **MAY inform which cut gets published**.
> They **MUST NEVER reach the interviewer's priming, question selection, format choice,
> or capture protocol.**

**Why.** The diary is an instrument, and the platform now derives real numbers from it —
enrichment themes, flourishing channels, vocal biomarkers (#1842), the diary-day
intervention test (#1843), the spoken-vs-typed divergence prereg (#1844), the on-tape
claims ledger (#1841). Every one of those reads the tape as evidence about Matthew's
life. The moment a question is chosen because a similar moment performed well, the tape
becomes evidence about the audience instead — and nothing downstream can detect the
substitution after the fact, because the contamination arrives as ordinary-looking
sentences. Selection pressure on the **output** (which of the things he already said gets
clipped) leaves the instrument intact. Selection pressure on the **input** destroys it.
That asymmetry is the entire rule.

**Explicitly, what engagement data may and may not influence:**

| Engagement MAY inform | Why it's safe |
|---|---|
| `cut_selection` — which already-recorded moment gets clipped and published next | The moment already happened, unprompted; picking among finished takes cannot change what was said |
| `surface_choice` — which surface (reel/short/yt) an already-chosen cut is rendered for | Format of the artifact, not of the interview |
| `publish_timing` — when an already-chosen cut goes out | Distribution, not capture |
| `ops_report` — counting what was published and what happened to it, for Matthew's own review | Reading the record is not steering it |

| Engagement MUST NEVER inform | What it would corrupt |
|---|---|
| `interview_priming` — the context loaded before a session (`/vlog` step 0) | The interviewer would arrive already pointed at what performs |
| `question_selection` — which questions get asked, or which follow-up is pursued | The answers stop being evidence about his life |
| `format_choice` — which diary format is proposed (daily/weekly/debrief/retro/team/vent/micro) | Format choice IS a question about what the night is for |
| `capture_protocol` — how, when, or how long a session is recorded | Reactivity becomes audience-shaped, which #1843 is trying to measure |
| `coach_context` — anything a coach persona sees | Coaches feed the interview; contamination arrives one hop later |
| `prompt_context` — any LLM prompt that shapes what Matthew is asked | The general case of all of the above |

**How it is enforced (structural, not aspirational).** The rule lives in code as well as
here — `lambdas/privacy/diary_publish.py`:

- `engagement_by_entry()` is the only reader of joined engagement data, and it **requires**
  a declared `purpose=`, checked against `ENGAGEMENT_MAY_INFORM` / `ENGAGEMENT_MUST_NEVER_INFORM`
  (the two tables above are those two dicts). Anything unlisted is refused **fail-closed** —
  a genuinely new output-side use has to be argued for and added, never assumed benign.
- A forbidden purpose raises `GoodhartViolation` rather than returning empty, so the
  refusal reads as a design error and not as "no data yet."
- `tests/test_diary_publish_1845.py` asserts that **nothing under `mcp/` or
  `lambdas/coach/` imports the module at all**. The interviewer's context comes from MCP
  tools, so "no tool the interviewer can call can reach engagement" is enforced by import
  graph: a future PR that wires one in fails CI instead of quietly winning the argument.
- No MCP tool exposes publication engagement. That absence is deliberate and is the
  guardrail's main load-bearing surface — adding one would need this rule amended first.

**In the room.** If Matthew asks on camera how a clip did, answer him — it's his life and
his channel. Just don't let the answer choose the next question. The `/vlog` skill carries
the same instruction at the top of its interview discipline section.

## Publishing a cut — the log format the platform reads (#1845)

The studio's `PUBLISH_LOG.md` is the loop's only entry point: what got published, from
which session, and which entry it came from. Six columns, header-driven (the platform
parses by column NAME, so extra columns are safe):

```
| date | session | cut | surface | link | entry |
|---|---|---|---|---|---|
| 2026-07-27 | 2026-07-26_retro_day-zero | 2026-07-26_day00_cut01_reel_more-day-ones.mp4 | reel | https://youtu.be/… | <notion page url or —> |
```

The `entry` column is the addition: the Notion page URL of the diary entry the cut came
from (`SESSION.md`'s `notion:` line). It is what turns "a clip did well" into "this
*truth* resonated" — the platform derives the entry's exact sort key from the page id, the
same way the ingestion Lambda does. Leave it `—` when the session wasn't routed; the
platform then resolves the entry by date, and only when that date has exactly one
recording (two takes in a day is legal, and guessing between them would attach engagement
to the wrong entry).

**Owner follow-up (Matthew-side, one edit):** the studio folder is deliberately outside
this repo, so add the `entry` column to `~/Documents/Claude/vlog/PUBLISH_LOG.md`'s header
and note it in `STUDIO.md` §Job 4. The five-column log still parses (the entry pointer is
simply absent), so nothing breaks before you do.

Then, after posting:

```bash
# Dry run — parse, validate, print what would be written, touch nothing:
python3 scripts/sync_diary_publications.py ~/Documents/Claude/vlog/PUBLISH_LOG.md
# Write the publication rows:
python3 scripts/sync_diary_publications.py ~/Documents/Claude/vlog/PUBLISH_LOG.md --apply
# Check the log and the ledger still agree:
python3 scripts/sync_diary_publications.py ~/Documents/Claude/vlog/PUBLISH_LOG.md --verify
```

Each admitted row becomes one `DIARY_PUBLISH#{channel}` / `POST#{post_id}` row —
provenance only, never a word of tape. From then on `youtube-data-ingestion` stamps every
matching inbound post with `diary_session_slug` / `diary_cut_id` / `diary_surface` /
`diary_entry_sk`, and the engagement that feed carries is joinable back to the entry that
produced it. The gate refuses (loudly, naming the cell to fix) any row whose cut filename
doesn't follow `STUDIO.md` §2b or whose filename and surface column disagree.

**What engagement actually exists today:** `views`, and only when YouTube's keyless RSS
feed bothers to include it — the feed frequently omits statistics entirely, and likes,
comments and watch time need the YouTube Data API, which is not wired. Absent stays
absent (ADR-104): a cut with no reported views contributes nothing to a rollup and is
never counted as zero, and every rollup carries its own n.

## Honest-numbers note (ADR-104/105)

A video diary introduces **no new numeric signal** into character scoring — it
reuses the identical enrichment fields as typed journal, from the same Haiku pass.
`channel` is provenance metadata only and never enters the scoring math. No Methods
Registry entry or new personal-variance threshold is required for this story. If a
future story derives a *new* diary-specific numeric signal (e.g. a
speech-prosody affect score from the #1573 transcription path), that signal — not
this one — takes the Methods Registry + threshold ripple before it touches scoring.
