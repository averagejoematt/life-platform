# HANDOVER — 2026-06-18 (PM) · Episode 0 voice-bleed RCA · CDN-path bug · git reconciliation

> Short session after the morning site-overhaul handover. Fixed the Episode 0 "Eli ends as
> Elena Voss" bug for real, found + fixed a CloudFront invalidation-path bug, and reconciled
> all post-#150 live work onto `main` as a clean PR. **Next: Matt's QA walkthrough.**

---

## 0. Git / PR state — READ FIRST
- **PR #151** (`chore/reconcile-live-state-after-150-2026-06-18`, head `74b5b530`, 1 commit, 57 files) — the **net delta of all work that went live after #150**, captured cleanly off `origin/main`. Everything in it is already deployed; merging is hygiene. **Merge once CI is green.**
- **PR-less branch `chore/coaching-docs-2026-06-18`** (head `d09fc6a4`, off `main`) — Matt's 5 coaching docs (`docs/coaching/…`), authored in a parallel claude.ai session. They originally landed *on the reconcile branch by accident*; split out so #151 stays pure. **Matt to decide:** open a PR for it, or keep iterating in claude.ai.
- After #151 merges, the old **`feat/temporal-frame-honesty-2026-06-17`** branch (25 commits, all now on main via #150 squash + #151) is redundant — safe to delete.
- ⚠️ **Pre-commit hook quirk:** `sync_doc_metadata.py` keeps bumping doc "Last updated" dates to **2026-06-19** (a day ahead) and leaves them unstaged in the working tree after each commit. Cosmetic; discarded each time. Worth a look at the hook's date source sometime.

## 1. Episode 0 "Eli ends as Elena Voss" — actually fixed now
The morning handover claimed the live cut already had the deterministic Elena sign-off. **It did not.** Timeline (all 2026-06-18 UTC):
- `01:48` dry-run draft written · `01:55` lambda deployed · `02:02` `wk0.wav` voiced · **`02:30` the sign-off fix (`fd5d69ed`) was committed.**
- So the live audio was voiced **28 min before the fix existed** → transcript ended `Eli → Elena(natural "I'm Elena Voss. Come back.")`, and Gemini's voice-bleed put Eli's voice on Elena's closing line. Exactly Matt's complaint.

**Fix applied this session:**
1. **Deployed `LifePlatformEmail`** (CDK) so the lambda actually carries `fd5d69ed` (+ `54459f6a` auto-invalidate). The deploy added the `cloudfront:CreateInvalidation` grant to `CoachPanelPodcastRole`.
2. **Re-voiced Episode 0** via `aws lambda invoke … --payload '{"intro": true}'`. The QA loop ran (rejected a couple drafts for monologue-length / weak friction), then stripped the natural tail and appended the deterministic `INTRO_SIGNOFF` as a **new Elena turn** → close is now `…Eli → Elena → Elena(sign-off)`, so any bleed is Elena→Elena. **Verified live transcript ends correctly.**

## 2. CloudFront invalidation path bug (`_invalidate_cdn`)
After re-voicing, Matt still saw the old cut on every browser incl. incognito. Root cause was **not** browser cache:
- `_invalidate_cdn` invalidated `f"/{PREFIX}/*"` = **`/generated/panelcast/*`** (the S3 **key** prefix). But CloudFront invalidations match the **viewer path**, and the public URL is **`/panelcast/*`** (the `generated/` prefix is stripped at the edge by S3GeneratedOrigin). So it cleared a path nobody requests; `/panelcast/wk0.wav` stayed cached (24h `max-age`).
- **Code fix** (`lambdas/emails/coach_panel_podcast_lambda.py`, in #151): derive `public_path = "/" + PREFIX.split("/",1)[1]` → invalidate `/panelcast/*`. Affects every future Friday auto-publish. **Ships on the next `LifePlatformEmail` deploy** (not yet deployed — low urgency).
- **Manual unblock:** `aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/panelcast/*"` — run, cleared the edge.

## 3. Concurrent-invocation race (lesson for next re-voice)
The `aws lambda invoke` CLI hit its **60 s read timeout** and **retried 3×** → 3 concurrent Episode-0 generations. The **last write won** (`20:37:02`), producing a **5:46** cut (346 s), not the 4:29 cut briefly observed at 20:34:41. All final artifacts (`wk0.wav` / `.transcript.json` / `.transcript.txt` / `episodes.json`) are internally consistent at `20:37:02`, 27 turns, correct ending — no corruption, just a longer cut than first reported.
- **Coincidence that confused QA:** the new *correct* cut (5:46) is nearly identical in length to the old *buggy* cut (5:47) — so judging by the duration timer looked "unchanged." **Verify by listening to the ending, not the timer.**
- **Next time:** invoke with `--cli-read-timeout 0` (or `--invocation-type Event`) so the CLI doesn't retry and spawn concurrent runs.

## 4. Open / next
- **Matt's QA walkthrough** (the main thing) → log findings into `~/.claude/plans/lively-swimming-rocket.md`, batch fixes. Confirm footer/`/version.json` SHA first.
- **Board-page "large intro font"** — still flagged, needs visual pinpoint during QA.
- **Merge PR #151** when CI green; then delete the old `feat/temporal-frame-honesty-2026-06-17` branch.
- **Coaching-docs branch** awaits Matt's call (PR vs continue in claude.ai).
- **CDN-path fix** lands on next `LifePlatformEmail` deploy (future episodes self-correct).

**Verified:** 2026-06-18 (PM). Episode 0 live cut ends Elena→Elena (confirmed via transcript + correct CloudFront object). PR #151 = clean reconcile, CI pending.
