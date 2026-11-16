# Film a set: design (#5779)

> **Status:** proposed — **deferred** (owner ruling 2026-11-11). Nothing is built. **Owner:** Matthew. **Written:** 2026-11-11.
>
> **Owner rulings 2026-11-11:** D1 no build — a manual trial of 3–5 clips in the Claude chat first; the Phase 0 script only if those reviews change something he does. D2 retire if 2 of the first 5 manual reviews are wrong or change nothing. D3/D4/D9/D10/D12 deferred until Phase 0 is earned. D5 delete after review. D6 guidance only. D7 no. D8 a cue-sheet lane now for bench, squat, conventional deadlift and one-arm DB row (barbell row if served), still-visible vs not-visible cues, `REVIEWED=False` until he approves each; they render in Hevy notes regardless of filming. D11 StrengthLog accepted provisionally for accessories; the four anchors carry no reference until he supplies one he has watched.
> **Nothing in this document is built.** No upload surface, Lambda, IAM, bucket rule or model call exists for it,
> and none is built until the owner approves this design (issue acceptance, third box).
> **Part of:** epic #5770 (exercise library, PR #5804). Companion: [form_references_proposed.md](form_references_proposed.md).

## 1. What it is

Matthew films one set on his phone. The platform turns the clip into a handful of still frames, a vision model
compares those frames to **that movement's cue sheet**, and the result is stored as an owner-only review beside his
other exercise notes. Nothing about it is public, ever. It is an aid for a person with no coach in the room, not a
verdict: it says which cues the frames show, which they do not, and which they cannot tell.

**What this is not:** a pain or injury tool, a load or intensity tool, a body-composition tool, or a public feature.

## 2. Prerequisites the design found (read first)

1. **There is no per-movement cue sheet in the library.** `config/exercise_library.json` (PR #5804, v0.1) carries
   `gates` of kind `clinical_cue` but no cue list. The cue sheets that exist are in
   `lambdas/training/form_cue_sheets.py` (#5573): hand-written, general, `REVIEWED = False`, and they cover **six
   patterns only** (`lateral_raise`, `rear_delt_fly`, `triceps_pushdown`, `overhead_triceps_extension`, `carry`,
   `biceps_curl`). None covers a barbell bench, squat, deadlift or row, which are the lifts he most wants checked
   (133, 99, 87 exposures). The module is explicit that a movement with no sheet gets no reply rather than a guess.
   So a review needs a sheet that is (a) written for the movement and (b) owner-reviewed. Cue-sheet authoring is a
   **separate prerequisite lane**, and the first filmable movements are the ones with a sheet he has approved.
2. **This would be the platform's first AI verdict on his form.** `form_cue_sheets.py` states "no AI verdict on
   form exists anywhere in this path" (ADR-105: deterministic first). Adding one needs an explicit owner ruling and
   an ADR (section 11, D1), not just a merge.
3. **The reviewed object is a still, not a movement.** Frames cannot show tempo, bar speed or most timing faults.
   The cue sheet for a filmable movement must be split into cues a still can show (posture, joint stack, bar or
   handle position at fixed points, range at the bottom or top) and cues it cannot (speed, rhythm, breathing).
   Only the first group is reviewed; the second is stated as "not visible in stills".

## 3. The flow

```
phone -> private ingress -> owner-only private prefix -> frame extraction -> cue-sheet review (Bedrock vision)
      -> review record in the exercise note layer (owner-only) -> owner reads it (MCP / coach packet / Telegram)
      -> clip deleted on the retention clock; frames never persisted
```

1. **Capture.** He films a set (one set, side or 45-degree angle, whole body and the implement in frame) and sends
   it with a caption naming the movement, as `/formcheck <movement>`. The movement must resolve to a library id; an
   unresolved name is refused with a reply, not guessed.
2. **Store.** The clip lands under a private prefix (section 5). An index row records movement id, date, clip key,
   size, status. The sender is checked to be his own 1:1 chat.
3. **Extract.** A fixed number of frames is sampled across the set (section 6).
4. **Review.** One `bedrock_client.invoke()` call with the frames and that movement's cue sheet (section 7).
5. **Log.** The structured review is written to the exercise note layer (section 8), and a short text reply goes
   back to him on the channel he used.
6. **Expire.** The clip is deleted by the retention clock (section 5). Frames were never stored.

## 4. Capture: which existing private ingress can carry a video

No new public surface is allowed. The candidates, from the repo as it stands:

| Ingress | Precedent | Carries video? | Verdict |
|---|---|---|---|
| **Telegram headcoach bot, his 1:1 chat** | `lambdas/coach/progress_capture.py` (#3758): one bot, one chat, magic-byte check, size cap, idempotent on `file_unique_id`, always replies on refusal; registered as `capture_channel: "telegram"` in `lambdas/ingestion/source_registry.py` | Yes in principle: the Bot API takes video messages. But its `getFile` download is capped at **20 MB** (Telegram's own documented limit; confirm before build), and `progress_capture.MAX_BYTES` is 20 MB for photos | **Recommended for Phase 1.** Same trust boundary as the progress photos he already sends. A phone-recorded clip sent as a Telegram *video* is recompressed and is usually small enough for 10 to 20 seconds; a clip sent as a *file* is the original and is not. Over the cap is refused with a reply that tells him to trim to the set. |
| Dropbox app folder | `lambdas/ingestion/dropbox_poll_lambda.py` polls `Apps/Life Platform/` every 2 hours and copies CSVs to `uploads/macrofactor/` | Yes, no size problem | **Fallback.** It would need a second folder and a new branch in a Lambda that today knows only MacroFactor CSVs, and a 2-hour poll is a slow loop for "check my set". Worth it only if Telegram's cap proves too tight. |
| Health Auto Export webhook | HAE sources in `docs/ARCHITECTURE.md` | No. It is a metrics webhook, not a file channel | Not suitable. |
| Notion | Journal capture channel | Not a video path; attaching media to a Notion page would also put body video in a third-party workspace | Not suitable. |
| A presigned S3 PUT minted by an owner-authenticated MCP tool | The private `uploads/` prefix | Yes, any size | Needs a new owner-authenticated MCP tool and a phone-side shortcut. It is the only option with no size cap, but it is a new write surface; keep it as a Phase 2 option. |
| **No ingress at all: laptop script** | `deploy/` and `scripts/` already run AWS and Bedrock calls from his laptop under the dev-session cap | Yes, AirDrop or iCloud the clip to the laptop | **Recommended for Phase 0.** See section 12. |

**Recommendation:** Phase 0 is the laptop script (no ingress, no Lambda). Phase 1 adds Telegram on the existing bot.
Dropbox and presigned PUT stay as documented fallbacks. Nothing here adds a public endpoint.

## 5. Storage: owner-only, private, with a retention clock

**Tier.** `docs/DATA_GOVERNANCE.md` Tier 2, owner-only, **with no carve-out and no public projection of any kind**:
the progress-photo row's stance applies exactly (no aggregate, no thumbnail, no count, no existence on any page). A
video of his body is more identifying than a still and it is the highest-sensitivity thing the platform would hold.
It would be declared in `lambdas/privacy/field_tiers.py` as `TIER_OWNER_ONLY` before the first byte is written
(ADR-154's order: tier first), and opt out of the public data-source catalogue the way `progress_photos` does.

**Where.** A new prefix `uploads/form_clips/YYYY/MM/<date>-<movement id>-<n>.<ext>`, **not** `generated/` and
**not** `site/`. `deploy/bucket_policy.json` grants anonymous `s3:GetObject` only on `site/*` and a named list of
`generated/*` keys; `uploads/*` is in neither, and is also in the policy's `DeleteObject` deny list for the admin
principals (it protects against deploy scripts, and does not stop lifecycle expiry).

Why `uploads/` and not `raw/matthew/...` where the progress photos live: `raw/` is "forever" retention, is
delete-protected and is replicated cross-region (DIL-027) because photos "cannot be recomputed". A form clip is the
opposite: it is disposable once reviewed, and he should be able to be rid of it. `uploads/` already has a
lifecycle rule (`uploads-expire-30d`: current objects 30 days, non-current 7), so a clip auto-expires with **no new
lifecycle rule**. Confirm before build that `uploads/` is not replicated (the data-governance table lists
replication for `raw/` only).

**Retention and deletion.**

| Artifact | Kept | How it goes |
|---|---|---|
| Clip (S3) | Up to 30 days, the existing lifecycle ceiling | Lifecycle expiry; plus an explicit delete by the review Lambda once the review is stored, unless he asks to keep it (D5) |
| Frames | **Never persisted.** Held in Lambda `/tmp` or laptop temp dir for the one call | Removed at the end of the invocation (`finally`), including on error |
| Review record (DDB) | Kept, like his other exercise notes | Owner can delete a record; no model reads it back into any public artifact |
| Model-side | Bedrock's data-retention terms for prompts and images (AWS-side; not verified by this lane) | Confirm before Phase 1 (D12 below) |

**Deletion on request.** `lambdas/operational/delete_user_data_lambda.py` already names `uploads/`. The design adds
the new prefix and DDB sk family to its sweep list as a build task, so "delete everything" covers clips.

**Other people in frame.** A gym clip can include bystanders. The capture reply tells him to frame it so nobody else is
recognisable, and the extractor does not retain frames, so this is bounded rather than eliminated (D6).

## 6. Frame extraction

- **Tool.** ffmpeg, as already used in the repo for audio/video work (`scripts/transcribe_solo.py`, the vlog studio
  kit in `docs/content/DIARY_STUDIO_KIT.md`). Two traps from the 2026-07-26 note, both of which exit 0: Homebrew's
  default `ffmpeg` is now a slim build with no `drawtext` or `subtitles`, and the full build (`ffmpeg-full`) is
  keg-only and never on `PATH`. **Frame extraction needs neither** (it is decode, scale, JPEG encode), so the slim
  build is enough on the laptop, and the check is to look at an extracted frame, not the exit code.
- **Where it runs.** The laptop in Phase 0. In a Lambda, **no ffmpeg exists today**: `lambdas/ai/audio_encode.py`
  records that Lambda has no encoder binary and that a static ffmpeg layer is about 78 MB; and the platform has "one
  bundle, no layer" (#781, `docs/CONVENTIONS.md` section 1). So Phase 1 needs an owner decision on how ffmpeg gets
  into a Lambda (D3): a static binary inside the function's own bundle (78 MB uncompressed is within the 250 MB
  limit but fattens one function), or a small container-image function for this feature only. This is the single
  largest build-cost item and the reason Phase 0 exists.
- **Sampling.** Probe duration with `ffprobe`; refuse a clip over 60 seconds or over the size cap. Take **8 frames**
  evenly spaced between the first and last 5% of the clip (so the setup and the rack are excluded), scaled to a
  1024-pixel long edge, JPEG quality about 80. Frame index and timestamp travel with each image so the review can
  cite "frame 3". No face or body cropping.
- **Hard limits.** 8 frames normal, 12 absolute maximum, so the per-review cost has a ceiling (compare
  `coach_vision.MAX_IMAGES = 6`). Image blocks are built through the one sanctioned image-prepare path; any new
  `{"type": "image"}` construction site must be registered in the census
  (`tests/test_shared_image_prepare_3079.py`), a build task.

## 7. The review: Bedrock vision through the chokepoint only

- **Call.** One `bedrock_client.invoke()` per clip (ADR-062); no second client, no direct `bedrock-runtime`. Same
  shape as the weekly coach-vision read, which is the working precedent
  (`lambdas/coach/coach_vision.py`: injected `invoke`, schema-validated reply, loud failure rather than a silent
  skip, grounding check on the text).
- **Model and route.** A new route `film_a_set` on the **VISION tier** in `lambdas/ai/model_routing.py`, which is
  Haiku 4.5 today (`TIER_MODELS`, "image input (the meal-photo estimate)"). A new feature also needs a
  `budget_guard._FEATURE_CUTOFF` entry (`tests/test_model_routing_4770.py` holds the two key sets equal).
- **Budget tier.** ADR-125 bands (CLAUDE.md, AI Inference): 0 all AI runs; 1 internal/dev AI paused; 2 reader narratives paused; 3 hard
  cutoff. A form review is an owner-initiated, internal aid that no reader sees and nothing else depends on, so
  place it in **band 1** (pauses first), unlike `coach_vision` which sits in band 2 as coach voice. A paused review
  is reported to him as paused ("not reviewed, budget"), never silently dropped and never fabricated. From the laptop
  the dev-session cap (`lambdas/ai/dev_session_cap.py`: $5 a run, $10 per 24 hours, with a monthly envelope) also
  applies and is far above this feature's spend.
- **Input.** The frames, the movement's owner-reviewed cue sheet split into still-visible cues (section 2.3), and a
  fixed instruction block. **No bodyweight, load, history, pain flags, or note text goes into the prompt.** The model
  needs the cues and the pictures and nothing else; this also keeps the privacy surface of the call minimal.
- **Output.** Strict JSON (schema validated; a reply off-schema is rejected, not repaired):
  per cue id, `shown | not_shown | cannot_tell` with the frame numbers that support it; at most three "to try next
  time" items, each tied to a cue id; and one confidence word. `cannot_tell` is always a legal answer and is the
  default when the angle hides the joint.
- **Grounding.** Every cue id in the reply must be one that was sent; every frame number must exist; free text
  crosses `grounded_generation.grounding_findings` as coach vision does. Fail closed: a flagged review is withheld
  and recorded as withheld.

### Cost per review (from `lambdas/ai/bedrock_client.py` `PRICES`, not a guess)

Haiku 4.5 on the VISION tier: **$1.00 per million input tokens, $5.00 per million output tokens** (`PRICES["haiku"]`).
Inputs to the estimate:

- An image costs about width x height / 750 tokens (Anthropic's published estimate; the repo's own
  `bedrock_client.py` comment cites "up to 1,568 visual tokens per tile" as the ceiling for the QA judge). A
  1024 x 576 frame is about 790 tokens.
- 8 frames = about 6,300 tokens. Cue sheet and instructions about 1,200. **Input about 7,500 tokens.**
- Output capped at 700 tokens (`coach_vision.MAX_TOKENS`).

| Case | Input tok | Output tok | Cost |
|---|--:|--:|--:|
| **Typical: 8 frames, Haiku 4.5** | 7,500 | 700 | 7,500 x $1/M + 700 x $5/M = $0.0075 + $0.0035 = **$0.011** |
| Same, with the regional `us.` 10% premium the table does not include (`bedrock_client.py` note) | | | **$0.012** |
| Ceiling: 12 frames, Haiku 4.5 | 10,600 | 700 | $0.0106 + $0.0035 = **$0.014** |
| Alternative: 8 frames on Sonnet 4.6 (`PRICES["sonnet"]`, $3/$15) | 7,500 | 700 | $0.0225 + $0.0105 = **$0.033** |
| Alternative: 8 frames on Sonnet 5.5 (`PRICES["sonnet-5-5"]`, $2/$10, rates marked UNVERIFIED there) | 7,500 | 700 | $0.015 + $0.007 = **$0.022** |

Prompt caching does not help: frames differ on every call and the cue sheet is far below the cacheable-prefix floor
(`lambdas/ai/prompt_cache.py`). At about 10 reviews a week (40 a month) the typical case is **about $0.45 a month**,
and even the Sonnet 4.6 alternative is about $1.30, against the $215 monthly ceiling (ADR-063/133). Cost is not the
constraint; the constraint is whether a still-frame model can be trusted on form at all (section 9, D2). The
estimate assumes the token-per-image rule above; the first Phase-0 run should read the actual
`usage.input_tokens` from the response and correct this table.

## 8. Logging to the exercise note layer

The note layer is `lambdas/training/training_notes.py` plus `note_requests.py` (#5573), whose owner-only partition is
`USER#matthew#SOURCE#training_constraints` (`TIER_OWNER_ONLY`, no public projection) and whose MCP reader is
`get_exercise_notes`. The review is logged there:

- **Row:** same partition, a new sort-key family `FORMREVIEW#<YYYY-MM-DD>#<movement id>#<n>`, written once under
  `attribute_not_exists(sk)` (the `note_requests` idempotence rule). Fields: movement id, clip index key, frame count,
  per-cue result with frame numbers, the to-try items, confidence, model id, prompt/cue-sheet version, cost, status
  (`reviewed | withheld | paused | refused`). **No video, no frames, no body description beyond cue results.**
- **Reuses an existing tier and partition** rather than adding a source, which avoids a new `SOURCE_CLASS` entry, a
  `docs/SCHEMA.md` row and a registry row; the build lane still adds the sk family to the schema doc.
- **Read by:** `get_exercise_notes` and the coach packet, owner-only. A review is context for the coach chat, the way
  an open `form_guidance` request is.
- **What it does not do:** it does not write into a Hevy routine. `docs/coaching/HEVY_NOTE_STANDARD.md` rule R6 and
  the "effort first, then one reason and one cue" grammar govern what the platform writes on the wire. Whether a
  review's top item may become that one cue in his next session is an owner decision (D7), default **no**.
- **N=1 library overlay:** `exercise_library.n1_view` carries coded note signals including `form_check_requested`.
  A count of reviews per movement may join the private overlay (`config/coaching/exercise_library.private.json`),
  counts and cue ids only, never text.

## 9. What a review may and may not say

**May say** (form cues only): for each still-visible cue on that movement's sheet, whether the frames show it, do
not show it, or cannot tell; where in the set (frame numbers); up to three things to try next time, each phrased as
a cue from the sheet; and a one-line statement of the limit ("from still frames; speed and rhythm are not visible").

**May not say, enforced in code, not only in the prompt:**

| Class | Why | Enforcement |
|---|---|---|
| Pain, discomfort, injury, risk of injury, strain, tear, a diagnosis, a body region described as hurt or at risk | Never a clinical read; owner-held pain handling lives in `training_constraints` and the library's `pain_flag_exclusion` gate | Output schema has no field for it; a deterministic lexicon check on every free-text string fails closed (withheld) |
| Any change to intensity: load, reps, sets, RPE, "go heavier", "deload", "stop", "skip" | Load and effort are the deterministic planner's and the owner's; a model must not move them | Same lexicon check; the schema has no load field |
| Body composition, weight, appearance, comparison to anyone | Out of scope and the sensitive class | Same check; no such data is in the prompt |
| A confident verdict the frames cannot support | ADR-104 honest numbers, ADR-105 uncertainty | `cannot_tell` is legal and default; cue claims must cite frames; confidence is a word, never a score |

**Pain-flagged movements are not reviewed.** If the movement carries a current pain or joint-discomfort flag in the
note layer (the library's `pain_flag_exclusion` gate), the capture reply says the movement is held and sends nothing
to the model. This is the one place where the film-a-set flow reads the pain layer, and it reads it only to refuse.

**Wrong-by-construction cases** are stated rather than hidden: bad angle, bar out of frame, loose clothing hiding a
joint, low light. The extractor does not try to fix them; the review returns `cannot_tell` for the affected cues and
says "re-film from the side".

## 10. Privacy and the privacy tests the build must ship

- **Tier:** DATA_GOVERNANCE Tier 2, owner-only, no carve-out (section 5).
- **Never in a public artifact:** not in `generated/`, `site/`, the public archive (`/archive/*`), any coach narrative,
  email, chronicle, podcast, or the Story Desk. The issue's fourth acceptance box ("no clip or frame is publicly
  reachable (privacy test in the design)") is met by these tests, each to be written in the build lane, each with a
  mutation control proving it can fail:
  1. **Bucket-policy reachability:** `deploy/bucket_policy.json` has no `Allow` for a non-owner principal whose
     `Resource` matches `uploads/form_clips/*` (a pattern test over every statement; mutation: add the prefix to
     `PublicReadGenerated` and the test must fail).
  2. **No public route:** no CloudFront behaviour, origin path or `site_api*` role names the prefix (the
     `tests/test_progress_viewer_privacy_3760.py` pattern); the prefix is absent from every sitemap, feed, nav and QA
     page registry.
  3. **Tier registry:** the sk family is stamped `TIER_OWNER_ONLY` in `lambdas/privacy/field_tiers.py` and absent from
     every published projection (`tests/test_data_governance_tier_guard_3045.py` keeps this section and the registry
     in step).
  4. **Isolation:** no module under `lambdas/web/`, `lambdas/email/` or the public-archive builder imports the review
     writer or reads the sk family (the `tests/test_coach_vision_isolation_3759.py` pattern).
  5. **Frames never stored:** a test over the extractor that fails if any code path writes a frame to S3 or DDB, and
     that the temp directory is removed on both success and exception.
  6. **Prompt minimality:** a test that the request body contains only frames, the cue sheet and the fixed
     instructions (no bodyweight, no loads, no note text).
- **Logs.** The review Lambda logs ids and counts, never frame bytes or model output text.
- **Bystanders:** section 5 / D6.

## 11. Failure modes

| Failure | Behaviour |
|---|---|
| Clip over the size or duration cap | Refused, reply tells him to trim; nothing stored |
| Not a video (magic-byte check, as `progress_capture` does for JPEG) | Refused with a reply |
| Movement does not resolve to a library id, or has no approved cue sheet | Refused with a reply; no model call |
| Pain-flagged movement | Held, reply says so, no model call (section 9) |
| ffmpeg missing or extraction yields fewer than 4 frames | Loud failure (Errors datapoint and the DLQ path, as `coach_vision` does), reply "could not read the clip" |
| Budget tier at or above the band | `paused` row and reply; no call |
| Bedrock throttled, access denied, or model change | Raise, not swallow, so the absence alarm and DLQ see it; he is told it failed |
| Reply off-schema, ungrounded cue id, or banned-lexicon hit | Withheld; row written with `status: withheld`; nothing shown |
| Telegram redelivery | Idempotent on `file_unique_id` (as the photo path) |
| Clip upload succeeds but the Lambda dies | Clip expires on the 30-day lifecycle; no frames existed; row stays `pending` and is swept |
| A review is wrong | It is a still-frame model's read; he can mark it wrong, and wrong marks are counted so the feature can be retired on evidence (D2) |

## 12. Phasing

- **Phase 0, laptop only (recommended first build, after approval).** `scripts/film_a_set_review.py`: he AirDrops a
  clip to the laptop; the script samples frames with local ffmpeg, calls `bedrock_client.invoke()` under the
  dev-session cap, writes the `FORMREVIEW#` row (owner-credential DDB write, the same pattern as other owner
  scripts), deletes the temp frames. No ingress, no Lambda, no IAM change, no new public or private surface. It
  answers the real question (is a still-frame review of any use to him?) for the cost of one script, and the first run
  corrects the token estimate.
- **Phase 1, Telegram + Lambda (only if Phase 0 earns it).** `/formcheck`, the ffmpeg-in-Lambda decision (D3), the
  prefix, IAM, the budget feature, the tier registry, and the six privacy tests.
- **Phase 2, optional.** Presigned-PUT for large clips or Dropbox.

**Post-merge ops for this PR:** none. It is documentation and a proposal list only; nothing deploys.

## 13. Decisions needed from the owner before any build

| # | Decision | Recommendation |
|---|---|---|
| D1 | Is an AI form review wanted at all, given it would be the platform's first AI verdict on his form (ADR-105 bar, ADR needed)? | Yes, as Phase 0 only, advisory, owner-only |
| D2 | What evidence retires it? (e.g. he marks N reviews wrong, or a coach/PT spot-check disagrees) | Count wrong marks; retire at 3 of the first 10 |
| D3 | If Phase 1: how does ffmpeg get into a Lambda: static binary in the function bundle, or a container-image function? (Contradicts "no layer" #781 if a layer) | Decide only after Phase 0 earns Phase 1 |
| D4 | Ingress for Phase 1: Telegram (20 MB cap, trim to the set) or Dropbox / presigned PUT | Telegram |
| D5 | Clip retention: delete right after review, keep the 30-day lifecycle ceiling, or keep on request | Delete after review; lifecycle as backstop |
| D6 | Bystanders in frame: accept "frame it clean" guidance, or require a crop/blur step | Guidance only; frames are never stored |
| D7 | May a review's top item become the "one cue" in his next Hevy pinned note (HEVY_NOTE_STANDARD R6 grammar)? | No; coach packet only |
| D8 | Which movements first, and who reviews and approves their cue sheets (six patterns exist, unreviewed; none for barbell lifts) | Start with the six; author and review barbell sheets as a separate lane |
| D9 | Budget band 1 (pauses first) or band 2 like `coach_vision` | Band 1 |
| D10 | Model: Haiku 4.5 on the VISION tier ($0.011), or a Sonnet-class model ($0.022 to $0.033) for a better read | Haiku for Phase 0, compare on the same clips |
| D11 | Approve, strike or substitute each row of the proposed form-reference list ([form_references_proposed.md](form_references_proposed.md)) | Per row |
| D12 | Confirm AWS's Bedrock retention terms for image inputs are acceptable for body video | Confirm before Phase 1 |

## 14. Where this lives

- Issue #5779; epic #5770; library PR #5804 and `docs/coaching/EXERCISE_LIBRARY.md`.
- Existing pieces reused: `lambdas/coach/progress_capture.py`, `lambdas/coach/coach_vision.py`,
  `lambdas/training/form_cue_sheets.py`, `lambdas/training/note_requests.py`, `lambdas/ai/bedrock_client.py`,
  `lambdas/ai/model_routing.py`, `lambdas/ai/budget_guard.py`, `lambdas/ai/dev_session_cap.py`,
  `deploy/bucket_policy.json`, `docs/DATA_GOVERNANCE.md`.
