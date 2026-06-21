# Handover — 2026-06-21 (Chronicle truthfulness + Podcast quality pipeline)

A long single-thread session driven by Matt's review of the Story door and the new weekly
podcast. Two workstreams: (1) make the chronicle tell the truth about the timeline + privacy,
(2) rebuild the podcast to a "would a real human believe this" bar with a QA gate that can
eventually run hands-off. **PRs #166–#182 merged + deployed; `origin/main` reconciled.**

---

## 1. Chronicle — now coherent + honest end-to-end

The public chronicle reads as one arc:

| | Title | Date | State |
|---|---|---|---|
| **Prologue · Part I** | The Body Votes First | June 7 (pre-genesis) | live |
| **Prologue · Part II** | The Empty Journal | June 11 (pre-genesis) | live |
| **Week 1** | The Week That Decided to Begin | June 20 | live |

- **Re-dated origin chapters → Prologue.** They were labelled "Week 1/Week 2" and their bodies
  narrated "the platform went live this week / 302→301 / Week 1 data" — stale recycled content that
  contradicted the June-14 genesis (314.52). Rewrote both as genuine pre-genesis backstory (Elena's
  run-up portrait, "before the machine turned on"), **preserving ~95% of the prose Matt liked** (the
  lag, the one perfect day, the empty journal, the watch in the drawer). Only the timeline framing
  changed.
- **Genesis-anchored week numbering** (`lambdas/emails/wednesday_chronicle_lambda.py`): week_num is
  the date math from genesis, NOT the installment count. Pre-genesis lead-ins are Prologue and never
  inflate the experiment week. Fixed the **"nine pounds in three weeks"** error (it was one week; the
  prior continuation-numbering counted the 2 prologue chapters as experiment weeks).
  `publish_to_journal` labels by date-vs-genesis ("Prologue · Part N" / "Week N"); **URLs stay
  sequential** (`/journal/posts/week-NN/`) so links don't break. `posts.json` gained a `label` field.
- **Vice/substance privacy guard (ABSOLUTE)** in both chronicle prompts — never name marijuana/porn
  even from journal data or when tied to grief; non-specific only or omit. (A regenerated draft had
  named marijuana explicitly → deleted out-of-band, guard added, regenerated clean.)
- **Nutrition-logging integrity** + **cold-reader grade-context** prompt rules (low cals = a real
  deliberate deficit, never "not logging"; ground or cut the platform grade for a new reader).
- **Layne Norton (a real person) → fictional Dr. Marcus Webb** everywhere it leaked: S3 board config
  (section_header + prose), both `web/` board-ask lambdas (`site_api_lambda` + `site_api_ai_lambda`),
  the measurements MCP tool, and the chronicle interview-routing prompt. Live draft + S3 config fixed.

### ⚠️ Chronicle follow-ups
- **`_FALLBACK_ELENA_PROMPT`** (only fires if the S3 board config fails to load) still carries the
  legacy real surnames Attia/Huberman/Walker/Norton — an all-or-nothing fictionalization cleanup,
  tracked but not done. The active config-driven path is clean.
- DDB chronicle source records were tangled (the public artifacts were hand-built + decoupled from
  DDB at Feb-22/May-04). Synced DDB records at `DATE#2026-06-07` / `2026-06-11` (phase=experiment,
  published, prologue) + retired the stale Feb-22 duplicate. **Verify the next Wednesday-chronicle
  publish rebuilds `posts.json` from DDB with the prologue still labelled correctly.**

---

## 2. Podcast (panelcast) — refit to the read-aloud Turing bar

**Matt's bar:** the *transcript* must pass for a real, human-made podcast (read aloud, no AI tells) —
real hook, dry humour, something learned, recommendable. Voices aside, the writing is the test.

Bugs he found in the first Episode 1 (all fixed): wrong-gender voice (Marcus Webb sounded female),
it said "week 2", a hallucinated "5 AM protein shake", no guest introduction, didn't feel like a
conversation.

- **A — Voice.** `_gemini_voice()` derives from the persona registry (`config/personas.json`
  `tts_voice`) — single source of truth, gender-correct. Killed the scrambled hardcoded table.
  Guard: `tests/test_panelcast_voice_gender.py`.
- **B — Grounding.** Script uses ONLY real coach-reads + week data; never invents scenes/times/sensory
  color. Chronicle is background, never quoted/lifted.
- **C — Intro + continuity + conversational.** Always introduce a guest the audience hasn't met
  (name + what they work on); carry the bet/thread; Turing-bar "no AI tells" directive; body-weight
  banned numeric AND spelled-out.
- **D — Read-aloud QA gate + self-correcting revision loop.** `_WEEKLY_RUBRIC` (Turing-pass, guest
  intro, no dangling thread, real hook, genuine friction, grounded, no body weight, humour) →
  `_qa_gate`. On fail, `_revise_weekly_script()` feeds the judge's exact failures back to the writer
  and re-judges, **≤2 revisions**, then HOLD. *This loop turned a HOLD into a publishable episode and
  is the path to hands-off.*
- **Sensitivity gate** now `_is_current_crisis()` AI-adjudicates a regex hit: a genuine current-week
  crisis (HOLD, fail-closed) vs. backstory grief reference (proceed). It had been auto-holding strong
  weeks that merely referenced his mother's death.
- **Editor judge** retries once then **fails OPEN** on unparseable JSON (infra hiccup ≠ content
  verdict) — it had been hard-HOLDing every episode.
- **ER-03 digit-matching removed from the weekly gate** — it silently dropped turns whose numbers were
  spoken in words ("eight thousand"), leaving holes (an unanswered question). Grounding is the LLM
  judge's job now; safety hits still hard-HOLD.
- **`_published_posts()` reads the live `generated/journal/posts.json`** (was the dead
  `site/chronicle/posts.json`) — fixed the week-drift that made the panelcast think it was "week 2".

**Live:** Episode 0 (intro, Eli Marsh) + **Episode 1 — "Week 1 — Monday was a 49…"** (4:28, Elena +
Dr. Sarah Chen) at `/panelcast/wk1.wav`. Verified: proper guest intro, grounded, no body weight, no
vice, gender-correct voices.

### ⚠️ Podcast follow-ups / open
- **Human-in-the-loop (E) is still on** by Matt's call: review the next 2–3 weekly episodes; if each
  clears the QA gate AND matches his ear with no edits, graduate to autonomous. The Friday cron
  generates + HOLD-on-fail; Matt should still listen before each goes wide.
- **Matt to listen to Episode 1** and say if it matches the bar — his ear is the final calibration on
  the QA judge's rubric.
- Orphan `s3://…/generated/panelcast/wk2.wav` (a relabel leftover) can't be deleted (S3 policy blocks
  DeleteObject on `generated/*`) — unreferenced, harmless.

---

## 3. Service worker — JSON feeds were going stale

`site/sw.js` cached everything except `/api/*` + navigations **cache-first**, so `posts.json` /
`episodes.json` went stale and a new chronicle/podcast stayed hidden until the SW VERSION rolled.
Now any `.json` path is **fresh-first** (#178). Version rolled `db1d3dbd → 88b99f29`. This is why
"the chronicle showed 2 not 3" — pure cache; the data was always correct.

---

## State / housekeeping
- **PRs merged this session:** #166 feed-untangle · #167 QA-coverage · #168 lede · #169 June-budget ·
  #170 panelcast-decouple · #171 reset-lead-ins · #172 chronicle-continuation · #173 chronicle-prompt
  + Norton · #174 vice-guard · #175 genesis-weeks · #176 sensitivity-adjudication + voiced-guards ·
  #177 panelcast-chronicle-source · #178 SW-fresh-first · #179 voice + Turing-prompt · #181 QA-gate +
  re-roll + always-introduce · #182 reconcile (editor-robust + weekly-gate-keep-turns + revision loop).
  All deployed; `origin/main` aligned. (#180 was an unrelated Strava window fix that landed on main.)
- **Deploys live:** `LifePlatformEmail` (chronicle + panelcast), `LifePlatformWeb` (site-api Norton),
  `LifePlatformMcp` (measurements Norton), site sync (SW + prologue pages + posts.json).
- **Docs:** auto-synced via the pre-commit hook (Tools 135, Lambdas 81). Memory: new
  `project_panelcast_quality_bar`; updated `marijuana-and-porn-content-must-never-be-public` (added the
  AI-generator leak path).
- **Untracked local one-offs (records, not committed):** `deploy/_prologue_rewrite.py`,
  `deploy/_publish_week1.py`.

## Suggested next session
1. Matt listens to Episode 1 → tune `_WEEKLY_RUBRIC` / the writer prompt if his ear disagrees.
2. Watch the next 1–2 Friday episodes through the QA gate; decide on podcast autonomy.
3. Fictionalize the `_FALLBACK_ELENA_PROMPT` real names (low priority — fallback only).
4. Confirm the next Wednesday-chronicle publish rebuilds `posts.json` with the prologue labels intact.
