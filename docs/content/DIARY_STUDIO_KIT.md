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
S3, cost-gated against the $85 ceiling). For an unattended watched-folder setup,
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

## Honest-numbers note (ADR-104/105)

A video diary introduces **no new numeric signal** into character scoring — it
reuses the identical enrichment fields as typed journal, from the same Haiku pass.
`channel` is provenance metadata only and never enters the scoring math. No Methods
Registry entry or new personal-variance threshold is required for this story. If a
future story derives a *new* diary-specific numeric signal (e.g. a
speech-prosody affect score from the #1573 transcription path), that signal — not
this one — takes the Methods Registry + threshold ripple before it touches scoring.
