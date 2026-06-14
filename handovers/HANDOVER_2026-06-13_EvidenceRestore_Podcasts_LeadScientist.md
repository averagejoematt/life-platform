# HANDOVER — 2026-06-13 (Evidence-catalog restore · Podcasts: Chirp re-voice + Gemini single-pass · Dr. Eli Marsh PI persona)

> Evening session, post the cycle-4 reset. Three workstreams, all **deployed +
> verified live**. **PRs #109 and #110 merged to `main`** (tip `024a4e7`); **PR #111
> open and ready to merge** (its code is already live — merging just formalizes it).
>
> **Headlines:**
> 1. The reset's S3 purge had blanked four Evidence pages — restored + reset-proofed.
> 2. Podcasts moved off robotic Polly: chronicle → Google **Chirp 3: HD**; new **"The
>    Panel"** show; and **Episode 0 is now a genuine single-pass two-person interview
>    via Gemini 2.5** (the NotebookLM feel).
> 3. New **Dr. Eli Marsh — Principal Investigator**, a lead persona above the 8 coaches.

**Prior:** `handovers/HANDOVER_2026-06-13_StabilizationFutureGenesisSweep.md`.

---

## 0. Deploy Ledger — LIVE vs merged-only

| Change | PR | Deployed? |
|--------|----|-----------|
| Evidence catalog restore (supplements/experiments/challenges/habits) | #110 ✅merged | ✅ site-api full pkg + habitify ingestion + re-ingest + site sync; all 4 `/evidence/*` 200 |
| Podcasts → Google Chirp 3: HD + "The Panel" | #109 ✅merged | ✅ cdk Email+Web, personas→S3, site sync; chronicle re-voiced (all 5 episodes) |
| chronicle-podcast timeout 300→900s | #110 | ✅ live + in CDK (`email_stack.py`) |
| Dr. Eli Marsh PI persona + page | #111 (open) | ✅ configs→S3, site-api, site sync; `/api/coach_team` returns `lead`; live on `/story/coaches/` |
| Episode 0 → Gemini single-pass (Elena interviews Eli) | #111 (open) | ✅ `coach-panel-podcast` (full pkg), generated `/panelcast/wk0.wav` |

**No layer rebuild this session** — all new code is in bundled `lambdas/` root modules
(`google_tts.py`, `gemini_tts.py`) or per-lambda packages. Layer stays `v84` (no drift).

---

## 1. Evidence-catalog restore (#110) — root cause + reset-proofing
The cycle-4 reset purge (`deploy/generated/s3_purge_manifest_2026-06-13.txt`, driven by
`deploy/lib/safe_sync.sh`'s `--delete`) deleted the **`site/config/` catalog mirrors** the
read-only Evidence pages depend on. Canonical copies in the **root `config/` prefix**
survived (that prefix is delete-protected by bucket policy, ADR-032/046).

Fixes (all read from durable `config/` now, never the purged `site/config/` mirror):
- **supplements** → `config/supplement_registry.json` (full registry + science + 3 genome SNPs).
- **experiments** → live ledger runs overlaid with `config/experiment_library.json` (71: 4 available + 67 backlog), tagged `origin=live|library`.
- **challenges** → live overlaid with `config/challenges_catalog.json` (84: 18 available + 66 backlog).
- **habits** → sourced from **Habitify** (`USER#…#SOURCE#habitify` latest record's `habit_statuses`, grouped by area; ingestion now stamps per-habit `group`). **Blocked vices filtered server-side** via `_is_blocked_vice` (62 tracked → 60 shown).
- Front-end: `evidence.js` running/available/backlog split; habits grouped.
- The 3 catalogs are now also **version-controlled in repo `site/config/`** (belt-and-suspenders).
- Memory: `project_reset_purges_site_config.md` records the gotcha for the next reset.

## 2. Podcasts — Chirp re-voice + The Panel (#109) + Gemini Episode 0 (#111)
- **Chronicle podcast** → re-voiced to Elena's Chirp voice (`google_tts.py`, urllib + API key). All 5 back-catalogue episodes re-rendered. Timeout 900s so one `force` pass covers all.
- **"The Panel"** (`coach_panel_podcast_lambda.py`, weekly two-host) → Story section `/story/panel/`.
- **Episode 0** (`{"intro": true}`) → rewritten as a **single-pass two-person interview**: Elena interviews **Dr. Eli Marsh** via **Gemini 2.5 multi-speaker TTS** (`gemini_tts.py`) — genuine turn-taking, not stitched. PCM→WAV at `/panelcast/wk0.wav`. Chirp stitch retained only for the single-voice chronicle read-aloud.

## 3. Dr. Eli Marsh — Principal Investigator (#111)
A **non-operational** orchestrator persona (`type: meta`, `operational: false`, `lead: true`) — the boss of the 8 coaches, Matthew's single point of contact. Added to `config/personas.json` (10th distinct voice) + a board seat in `config/board_of_directors.json`. **Crucially NOT wired into the compute engine** → the 8-coach invariants/tests stay intact (registry gate 13 green). Surfaced as the lead of `/story/coaches/` (`site_api_coach._lead_block` → `/api/coach_team` `lead`; `dispatches.js` lead card; `story.css`).

## 4. Google keys / secret architecture (`life-platform/google-tts`)
ONE AWS secret, two fields:
- `api_key` → **Cloud TTS (Chirp)**, on the **managed AJM** GCP project.
- `gemini_key` → **Gemini 2.5**, on a **personal** Google account (the managed mattsusername.com domain blocks AI Studio — consumer accounts have it by default).
- A **3rd orphan key** exists on the managed project (the original, converted to Gemini, now unused) — **delete it in Google Cloud Console → Credentials** (not AWS).
- ⚠️ **Rotate-after-launch:** the Cloud TTS key (`…uDcc`) and the Gemini key (`AQ.Ab8…`) both appeared in chat — low blast radius (Cloud TTS restricted; Gemini is a personal key) but rotate as hygiene.

## 5. Open items / tech debt
- **Merge PR #111** (deployed + green; formalizes main).
- **Delete the orphan Google key** (managed project console) + **rotate the two chat-exposed keys**.
- **Weekly Panel → Gemini single-pass** (same `gemini_tts` module; Elena + 1 coach = 2 speakers, fits the cap). Currently still Chirp-stitched.
- **Gemini billing/account tech debt:** Gemini runs on a *personal* account separate from the managed AJM project — worth consolidating later (or moving Cloud TTS to the personal account too).
- Gemini TTS output is **WAV** (no MP3 transcode — no ffmpeg). Larger files (~9MB/episode); fine for the web player. RSS enclosure still says mp3 type — cosmetic.
- Deferred (unchanged): #16 ghost counterfactuals (cycle-3 correlations); Monarch financial integration.

## 6. Verified
Full suite **1799 passed** / 43 skipped / 10 xfailed. Lint (black+ruff) clean. All four
`/evidence/*` pages 200; `/story/coaches/` shows the PI; `/story/panel/` Episode 0 plays
the Gemini single-pass interview (hard-refresh to clear cache). Layer `v84`, no drift.

**Verified:** 2026-06-13 (evening).
