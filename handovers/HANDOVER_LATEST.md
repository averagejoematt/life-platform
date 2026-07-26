# HANDOVER — the Diary Studio: Cowork post-production desk + day-zero entry end-to-end + the diary-360 stories — 2026-07-26 (evening)

> Instruction thread: Matthew asked for a **Claude Cowork process for the video-diary
> workflow** (interviewer session → transcript → footage in a folder → cut recommendations
> → watermarks → splices), grounded in the "Vlog Field Manual" artifact; then iterated live
> as his actual day-zero footage arrived: trim-only, keep originals, standard file naming,
> film-style HUD watermark (Martian/Avatar references), options-per-surface cut plans, NAS
> archiving, Notion journal wiring; closed with a diary-360 synthesis ("what are we
> missing — product + science lens") and this wrap. Second session of the day — the
> morning reset-day session's handover is archived as
> `HANDOVER_2026-07-26_cycle-11-reset-genesis-eve.md`.

## What shipped

**On `main` (1 commit, pushed):**
- `fb2c79c4` — `.claude/commands/vlog.md`: the diary-360 priming bundle (previous entry +
  due on-tape claims + `One Thing I'm Avoiding` + pending coach reactions), the
  day-number risk curve (**micro** format days 1–7 + the 30s bad-day floor, ADR-104
  framing; day-30/60/90 rewatch retro), and the **TAPE NOTE** close — the verbatim-quote
  handoff the post-production desk string-matches into the whisper SRT for real clip
  timecodes.

**Issues filed (7):**
- **#1840** — Notion `Video Diary`/`Solo Recording` Template options were never added to
  the Journal schema: #1572/#1573 shipped **inert** (verified: API rejected the value;
  0 video_diary records ever; 61×journal + 1×morning fallbacks). Manual fix applied
  same-session via API (`ALTER COLUMN` with all 7 options; safe — all 41 pages had
  Template=NULL; original option IDs preserved). Story = the missing code↔SaaS-schema
  drift gate + WARNING-level fallback log + backfill posture for the 62 channel-less
  records. (Next)
- **#1841** claims ledger (diary claims → prediction machinery, graded, called back on
  tape) · **#1842** vocal biomarkers from SRTs (deterministic WPM/pause/filler) ·
  **#1843** diary-day reactivity tagging · **#1844** pre-registered spoken-vs-typed
  channel experiment · **#1845** cut→entry→engagement loop + the **Goodhart guardrail**
  (engagement may pick cuts, never questions) · **#1846** consent-gated diary shelf on
  `/story`.

**Live external state changed:**
- Notion Journal data source `d86e0aaa…`: Template select now has all 7 options.
- First **Video Diary** page filed (`3a909e62-f276-8107-a170-ec9b171ed7a5`, dated
  2026-07-26): day-zero transcript, his words verbatim under Q-headers, capture-mode
  caveat (speaker-mode = interviewer audible; future = one earbud), Footage pointer.
  Next notion-ingestion run should produce the first `channel: video_diary` record —
  and `maybe_react_to_diary` should return `private` (not `not_diary`). Worth checking.

**Outside the repo — the studio (`~/Documents/Claude/vlog/`, deliberately NOT in git):**
- Full post-production desk, all verified end-to-end on the real day-zero entry:
  `STUDIO.md` (Cowork standing instructions: 4 jobs, 5-axis rubric, privacy gate before
  ranking, by-surface option plans), `CHARACTER.md` (The Correspondent + priming bundle +
  wall-protocol floors + rewatch ritual), `PREFERENCES.md` (the taste ledger),
  `INSTALL.md`, `00_PASTE_INTO_COWORK.md`, `PUBLISH_LOG.md`, and `_scripts/`
  (ingest/transcribe/cut/overlay/captions/make_mark/day_rows/archive).
- **Day-zero entry processed**: 3.02 GB / 4K / 16:03 → whisper SRT (137 cues, 25.7s,
  ~37× realtime) → session folder + SESSION.md → by-surface cut plan (YT + 3 reels +
  2 stories, 4 HOLD items) → trimmed master (stream-copy, lossless, silencedetect-measured
  trim points) → rank-1 reel rendered with the film-HUD watermark + burned captions,
  frame-QA'd. Original byte-identical, renamed to the naming standard.
- `day_rows.py` wires the HUD's metric stack to `generated/pulse.json` — measured-today
  signals only; live-tested (day 0 correctly emits NO rows + `DAY 000`).

## Verification
- Whisper transcription accuracy + full-duration coverage checked against the real entry.
- Every render frame-extracted and **looked at** (caught 3 real defects exit-0 would have
  shipped: ASS-unit caption scaling, plate/caption collision, alpha-ghost outline).
- Notion create round-tripped (rejected pre-fix, accepted post-fix); DDB queried to
  confirm the 0-video_diary/62-channel-less claims in #1840.
- `fb2c79c4` push: md-only change; green-main gate result below.

## Gotchas hit (durable ones → memory topics)
- **homebrew's slim `ffmpeg` has NO drawtext/subtitles** (no freetype/libass);
  `ffmpeg-full` is keg-only → never on PATH. → `reference_ffmpeg_slim_brew_and_ass_units`.
- **`subtitles=force_style` values are ASS script units (384×288 canvas), not pixels** —
  height-derived sizes render 6.7× too big, pinned to the top. Same memory topic.
- `-c copy` trims snap to the previous keyframe (~0.7s early here) — the right trade for
  a lossless master; recorded in SESSION.md.
- Speaker-mode recording puts the interviewer on tape; whisper doesn't diarise → every
  cut boundary hand-checked. One earbud from entry 001 makes it moot (CHARACTER.md §5).
- Notion select options do NOT auto-create on page write (hard validation_error) — the
  #1840 class.

## Wrap gates
**Build beat:** `2026-07-26-diary-studio-day-zero`
**Docs:** `docs/coaching/CHAT_MODES.md` vlog row updated (7 formats + TAPE NOTE close),
Verified bumped. Everything else is studio-side (outside the repo doc surface) or carried
by the issues.
**Decisions:** none needed — fixes and filed stories only; the Goodhart policy lands with
#1845, and the schema fix is a defect repair, not a posture change.
**Main:** red — R8-ST6 IAM-review gate on `d26f2a74` (the parallel session's reconcile
commit): CDK diff carries IAM/policy changes → Plan reds **by design** pending Matthew's
manual review (the `reference_r8st6_iam_review_gate` class; likely the #1781 IAM-drift
surface). Not a test failure; `fb2c79c4`'s other gates (v4 site gate, Docs CI, CodeQL)
all green, its CI/CD run queued behind the same state.
**Incidents:** none.
**Stash/hooks:** clean.

## Residual / next picks
- **Monday (genesis day):** `restart_verify.py` + Day-1 flip + first cron billing run +
  first-data watches — `not-work — standing owner ritual, carried from the morning session`.
- Verify first `video_diary` ingestion stamps `channel` + diary-reaction returns
  `private` — covered by **#1840** AC4.
- Diary-360 build order: **#1841** (claims ledger) → **#1842**/**#1843** (cheap, accrue
  from entry 001) → **#1844** → **#1845**/**#1846**.
- Cowork day-one bootstrap (Prompt 1 in `00_PASTE_INTO_COWORK.md`) — `not-work — Matthew
  runs it in the Cowork app; CAPABILITIES.md is its output; sandbox-vs-host ffmpeg is the
  open question it answers`.
- NAS: set `NAS_ROOT` in `_config/studio.env` once the share is mounted + first
  `archive.sh` run against real hardware — `not-work — owner decision + hardware`.
- `__full` ephemeral-by-default decision (3 GB near-duplicate per entry) — `not-work —
  owner storage decision, studio-side`.
- Carried from the morning session: paydown #1623 · #1333 · #1666 · #1425 · Dependabot;
  sub-agent set #1781/#1782/#1029/#741 · opus podcast #1738–#1741 · #1653 · #1650 ·
  #1756 · #1396; owner items #1336 · #1768/#1622 (parked) · #1029 (by 08-20) · LICENSES §5
  — `not-work — standing queue, unchanged this session`.
- Memory-index compaction to <140 lines (hook nudge) — `not-work — memory-dir maintenance
  reflex, next wrap`.

Full morning-session narrative: `git show
origin/session-archive:handovers/HANDOVER_2026-07-26_cycle-11-reset-genesis-eve.md`.
