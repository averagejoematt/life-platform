# The video diary as a multi-layer signal source — signal inventory, influence matrix, and the won't-do list

**Date:** 2026-07-25 · **Story:** #1743 (epic #1564, The Diary Studio) · **Type:** SPIKE — no production change · **Feeds:** #1577 (scope verdict), #1571, #1570, #1627, #1623 · **Session:** parallel fable session, docs-only

## The question

The diary corpus (#1572 Video Diary channel, #1573 solo Whisper path) carries four signal
layers; today the platform harvests only the first. What should the intelligence layer over
this corpus extract, what may it influence, and what must it never influence?

**Verdict up front: harvest layer 1 fully (already shipped — nothing more to build there),
add two $0 deterministic side-signals from layers 2 and 4 in analysis-only mode, refuse
layer 3 permanently, and let nothing new move a score, prompt a coach, or reach a reader
before a Methods Registry entry and the #1627 spiral circuit breaker exist.** The
recommended v1 adds **zero new Bedrock calls**. The most valuable single output of this
spike is the won't-do list (§8): most of what a video corpus *could* yield is confident,
ungrounded, unfalsifiable output — exactly what ADR-104/105 exist to prevent.

---

## 1. Ground truth — the corpus as shipped (verified 2026-07-25)

Source: `lambdas/ingestion/notion_lambda.py`, `lambdas/ingestion/journal_enrichment_lambda.py`,
`lambdas/flourishing.py`, `lambdas/diary_consent.py`, `lambdas/coach/coach_diary_reaction.py`,
`scripts/transcribe_solo.py`, `docs/content/DIARY_STUDIO_KIT.md`.

- **There is no separate diary corpus.** A diary is a Notion journal page (Template
  `Video Diary` or `Solo Recording`) that flows the existing journal pipeline: hourly
  `notion-data-ingestion` → DDB (`pk USER#matthew#SOURCE#notion`,
  `sk DATE#{date}#journal#{video_diary|solo_recording}#{page-id-suffix}`) → daily Haiku
  enrichment (6:30 AM PT, `SCHEMA_VERSION = 2`, ~24 `enriched_*` fields) → deterministic
  flourishing row → nightly deterministic `journal-analyzer` → `HYPO_CANDIDATE#` rows.
- **Channel is provenance only.** `lambdas/flourishing.py:34` — "the channel is provenance
  only: it never feeds character scoring math." This is a deliberate, documented invariant
  (DIARY_STUDIO_KIT: a video diary introduces *no new numeric signal*).
- **Media never leaves the device.** `scripts/transcribe_solo.py` runs local Whisper;
  only a filename pointer + `duration_(s)` land in Notion. Raw footage/audio is never
  uploaded; `raw/matthew/diary/` is a reserved, delete-protected prefix that is currently
  **empty** (0 objects) — the durable artifact today is the Notion page JSON under
  `raw/matthew/notion/`.
- **Consent is entry-level and fail-closed.** `lambdas/diary_consent.py`: tiers
  `quote | allude | private`; anything absent or malformed resolves `private`; a cleared
  quote is honored only if it is a literal substring of `raw_text` (ADR-104 grounding);
  `raw_text` and `enriched_notable_quote` never enter the public context object.
- **The one reader-facing consumer is dormant.** `coach_diary_reaction.py` (#1574) is
  code-complete, budget-registered (`coach_diary_reaction: 2` in
  `lambdas/budget_guard.py`), and served at `/api/diary_reactions` — but has **no CDK
  function and no trigger** (`grep -rn coach_diary_reaction cdk/ deploy/` is empty). See
  story S-0 in §7. A second latent defect: its sk `DATE#{date}#{channel}` collides when
  two same-day entries share a channel.
- **No prosody, audio-DSP, or video-frame analysis exists anywhere in the repo.** The
  Fingerprint (#1379, `lambdas/web/fingerprint.py`) is pure/stdlib, consumes six
  device/streak metrics, no journal input; a burned-in video overlay has not shipped.
- **#1577** (conversational partitions → enrichment) is OPEN with zero code; its channel
  vocabulary does not yet exist in `flourishing.py`.

---

## 2. The four-layer signal model

Summary table; each layer detailed below. "Cost" is marginal cost over what already runs.

| Layer | Extractable today? | New capture/compute needed | Cost | Confidence in the signal | Verdict |
|---|---|---|---|---|---|
| 1. What he said | **Yes — shipped end-to-end** | none | ~cents/entry (Haiku, existing cron) | Moderate-high; LLM-coded 1–5 scores carry a provenance line, grounded-quote discipline at write time | **KEEP (done)** |
| 2. How he said it | Partially — transcript mechanics only | Whisper timestamp post-processing (local, deterministic) | $0 AI, ~4 numeric fields/entry storage | **Unvalidated** — descriptive-only until a correlation study passes | **NARROW KEEP: deterministic speech mechanics, analysis-only.** LLM affect inference: REFUSE |
| 3. What he looks like | No — and there is deliberately no footage in the cloud to compute over | frame pipeline + video upload + a defensible method (none exists) | n/a | None that survives ADR-105 | **REFUSE, permanently** (§8) |
| 4. Cadence and avoidance | Yes — deterministic, from existing DDB rows | small deterministic detectors | $0 | High for the *fact* of cadence; nil for any inferred *meaning* without the #1627 detector frame | **NARROW KEEP: cadence → private circuit-breaker input; theme-drop → private check-in question.** Silence-based LLM avoidance claims: REFUSE |

### 2.1 Layer 1 — semantic content (shipped; the marginal work is zero)

The enrichment schema already extracts mood/energy/stress (1–5), sentiment, emotions,
themes, cognitive patterns, growth signals, avoidance flags *as stated in the text*,
ownership, social quality, flow, values, gratitude, behaviors, entities, and grounded
`causal_hints` — and the flourishing projection turns six of those into the only
journal-derived numbers that touch character scoring (`values_alignment`,
`social_quality_score`), each stamped with the mandatory provenance line
("LLM-coded from journal text (model …)", `flourishing.py:212`).

Two honest caveats, both cheap to check and neither blocking:

1. **Channel shift.** Spoken diary text is longer, more rambling, and less composed than
   typed journal text. The enrichment prompt was tuned on typed entries. Whether
   `enriched_*` distributions differ by channel is an empirical question — a one-off
   deterministic comparison once n ≥ 20 video-channel entries exist (story S-1). Until
   then, treat cross-channel comparisons of enriched scores as descriptive only
   (ADR-105 rule 1).
2. **`enriched_avoidance_flags` is layer 1, not layer 4.** It codes avoidance *he
   mentions* ("I've been putting off X"). That is grounded in his own words and fine.
   It must not be conflated with inferring avoidance from what he *didn't* say (§2.4).

**Extraction verdict: complete. Reject the "run a bigger model over the transcript for
deeper readings" move** — a Sonnet re-read of the same text produces more confident prose,
not more signal, and every downstream consumer already receives the coded fields.

### 2.2 Layer 2 — prosody, pace, energy, affect

What a diary *recording* has that typed text does not: timing. Whisper emits per-segment
timestamps, which support a small set of **deterministic, locally computed, $0** transcript
mechanics:

- `speech_wpm` — words per active-speech minute
- `pause_fraction` — silence share of total duration
- `filler_rate` — filler tokens per 100 words (fixed public wordlist)
- `median_utterance_words`

These are honest *measurements* (of speech mechanics, not of feelings). Everything beyond
them — pitch, energy contours, voice-quality affect scoring — fails the bar:

- **Validity.** Speech-emotion inference has weak cross-context validity even in
  literature settings; a single-speaker home recording with varying rooms, mic distance,
  and hour-of-day is noise-dominated. An unvalidated "energy score" is precisely "the
  kind of number this platform exists to refuse" (#1743) and violates ADR-105 rule 4
  (thresholds from personal variance — which requires a validated metric first).
- **LLM affect narration** ("he sounds flat today") is unfalsifiable and ungrounded —
  the character engine's behavioral-absence semantics and the grounded-generation gate
  (ADR-104, `lambdas/grounded_generation.py`) were written to stop exactly this class of
  confident invention. Refused permanently (§8).
- **Voice is identifying** (#1388 AC3: "pitch-shift or text-only are the acceptable
  public forms") — so no layer-2 derivative may ever be public regardless of validity.

**Verdict: capture the four deterministic mechanics as side-car metadata on the Notion
pointer (like `duration_(s)` today), consumed by nothing.** They earn any influence only
by passing a validation study (story S-3): after ≥ 30 sessions, correlate each against the
same-day self-anchored signals (`enriched_energy`, `enriched_mood`) with effective-n
corrected CIs per `lambdas/stats_core.py`. If nothing correlates, the honest outcome is a
documented "measured, found uninformative, retired" entry — a valid and useful end state.

### 2.3 Layer 3 — longitudinal physique and appearance

The most obviously valuable-looking layer, and the one to refuse. Three independent
reasons, any one of which suffices:

1. **No honest method exists at this scale.** Body-composition inference from monocular
   home video of one subject is confounded by lens (the capture camera is wide-angle —
   geometric distortion varies with distance), lighting, clothing, posture, and framing.
   There is no deterministic computation to put in front of an LLM verdict (ADR-105
   rule 3), no personal-variance baseline to derive thresholds from (rule 4), and no way
   to attach an honest uncertainty to a frame-derived claim (rule 1). Anything produced
   would be pseudo-measurement.
2. **The platform already measures this domain properly.** Withings weight with
   trailing-7-day-mean semantics (#1626: "never a single weigh-in"), labs, and the
   deficit-sustainability machinery are the sanctioned body-composition instruments. A
   visual estimate adds no information to a scale and a lab panel; it adds only a second,
   worse voice.
3. **The standing exclusion.** The #1619 board verdict excluded milestone and
   body-composition content from automated surfaces **on the merits — "not deferred, not
   descoped: denied"** — because automated public victory-claims create a documented harm
   pattern for this user (rationale held privately — `docs/PLATFORM_CONTEXT.md`,
   PRIVATE). The same pattern applies with more force to appearance commentary: for a
   subject with a documented relapse cycle whose self-image is part of the thing being
   measured, a machine opinion about how he looks is not neutral telemetry — it is an
   input into the loop being measured, with the sign of its effect unknown and
   plausibly negative in exactly the weeks it would matter.

The failure mode is worth naming precisely: an appearance model is wrong in the ordinary
weeks (noise) and harmful in the vulnerable weeks (a flat or negative reading landing
mid-spiral, where #1627's rule — "the system's job is to check on him, not to congratulate
him" — cuts both ways: neither congratulation nor criticism).

**What remains legitimately available from this layer: nothing automated.** If the owner
ever wants a before/after visual for the public story, that is a manually curated,
consented *content* decision under #1570 diary cards — not a signal, not this design's
concern. Note there is also **no corpus to compute over**: footage stays on-device by
standing invariant, and building a video-upload pipeline *in order to* enable appearance
inference would be constructing the hazard. Refused (§8, items 1–2).

### 2.4 Layer 4 — cadence and avoidance

Two distinct sub-signals with opposite risk profiles.

**(a) Recording cadence — which days he records.** Deterministic, extractable today from
channel-stamped DDB rows. The platform's own governance already identifies where this
signal belongs: #1623 — "it generates the platform's single best downturn signal: the
notes stopping" — and #1627, whose spiral circuit breaker consumes leading indicators
privately and fails closed. A sustained diary-cadence drop (against his own trailing
baseline, per ADR-105 rule 4) is a candidate *sixth* input to the #1627 detector,
alongside valence-below-p25, training gap, habit collapse, and sleep-midpoint variance.

What cadence must **not** be:

- **A character-scoring input.** The epic invariant (#1564) is explicit: "skipped
  sessions are 'no data,' never failure." Wiring cadence into the character sheet would
  force a `behavioral: true|false` choice (`character_engine._weighted_pillar_score`),
  and `behavioral: true` scores absence as 0 at full weight — structurally converting a
  voluntary reflective practice into a graded habit. That both violates the invariant
  and poisons the signal (a diary kept to protect a score stops being candid).
- **Public.** #1627: "Suppression is never surfaced publicly — the absence of a note is
  the signal, and it is a private one." A public cadence surface turns silence into an
  audience-visible event, which #1623 explicitly rejected in favor of the private
  channel. The only public form ADR-124 sanctions is honest aggregate absence ("no
  entries this week") — never per-day patterns, never interpretation.

**(b) Topic avoidance — which topics he circles and drops.** Split it the same way:

- **Deterministic theme-drop detection** — a theme from the fixed 8-way vocabulary
  (`journal_analyzer.categorize_themes`) that appeared in ≥ 3 entries and then goes
  silent ≥ 14 days — is a real, computable *fact* ("theme X last appeared N days ago").
  Its one legitimate consumer is a **private check-in question**: a coach asks "you
  haven't mentioned X lately — want to talk about it?" through the existing check-in
  queue. Phrased as a question it is the "catch him instead of watching him" move;
  falsifiable (he answers), cheap, and consistent with #1627's framing. It must never be
  phrased as a claim about his state, and never appear on a public surface.
- **LLM avoidance inference** — a model asserting *why* a topic went quiet, or that
  silence means avoidance at all — is mental-state inference from absent evidence.
  ADR-104's first principle (absence is "no data") applies with full force: the
  deterministic detector may observe that a theme stopped; nothing may claim to know
  what that means. Refused (§8, item 3).

---

## 3. The influence matrix

Rows = consumers; columns = layers as scoped above (L2 = the four deterministic speech
mechanics only; L3 = any appearance-derived signal; L4a = cadence, L4b = theme-drop).
**Allowed** = may consume today under existing gates · **Gated** = may consume only after
the named gate · **Forbidden** = never, with the governing rule.

| Consumer | L1 semantic | L2 speech mechanics | L3 appearance | L4a cadence | L4b theme-drop |
|---|---|---|---|---|---|
| **Coaches (private briefs/reactions)** | **Allowed** — shipped: consent-gated diary reactions (#1574); deterministic mood block in briefs (#549, "not one piece of raw text in it") | **Gated** — descriptive side-note only after S-3 validation; never before | **Forbidden** — §2.3; #1619 exclusion + ADR-105 (no method) | **Gated** — visible only as the #1627 detector's private output, after S-4 | **Gated** — one check-in *question* via S-5; never a claim |
| **Character sheet / flourishing** | **Allowed** — shipped (`values_alignment`, `social_quality_score`); channel never in the math | **Forbidden until promoted** — Methods Registry entry + personal-variance thresholds + ADR-104 absence semantics decided (ADR-105 rule 4; epic #1564 invariant); no candidate signal has earned this | **Forbidden** — ADR-104 (a score must be earned deterministically; no honest deterministic source exists) + #1619 | **Forbidden** — epic invariant: skipped session = no data, never failure; `behavioral: true` semantics would score absence as a miss | **Forbidden** — absence of a topic is not a measurement (ADR-104) |
| **Hypothesis engine** | **Allowed** — shipped (`HYPO_CANDIDATE#` with verbatim grounded quotes; deterministic pre-registered verdicts per ADR-105 rule 3) | **Gated** — a validated mechanic may become a `METRIC_KEYWORDS` cause/effect metric only after S-3 + Methods Registry | **Forbidden** — no hypothesis may take an appearance estimate as either arm (ADR-105 rule 1: no honest uncertainty exists) | **Gated** — cadence as a *context* covariate in candidate provenance is harmless but low-value; not worth building | **Forbidden as auto-candidate** — a "he avoids X → Y" hypothesis manufactured from silence is ungrounded by construction |
| **Experiments / challenge ideation** | **Allowed** — shipped chain (hypotheses → `challenge_generator`, `source_hypothesis_id`) | **Gated** — same promotion path as hypothesis engine | **Forbidden** — no experiment may target or measure appearance (#1619; spiral-safety) | **Allowed, narrowly** — an experiment *about the practice itself* ("record 3×/week for 4 weeks; compare flourishing coverage") is legitimate and self-consenting | **Forbidden** — an experiment designed around an inferred avoidance is intervention on an unmeasured construct |
| **Public site / emails** | **Gated** — the shipped consent chain: entry-level `quote|allude|private` fail-closed; theme river aggregates with n; chronicle never quotes the journal (`chronicle_prompt.py:95`); `/api/journal_analysis` aggregates only | **Forbidden** — an unvalidated number public is ADR-105 rule 1 violated at the front door; voice-derived features are identifying (#1388 AC3) | **Forbidden** — raw footage never public (#1388/#1564 invariant); appearance commentary excluded (#1619) | **Forbidden** — silence is a private signal (#1627/#1623); only ADR-124-style honest aggregate absence may render | **Forbidden** — same, plus third-party/topic sensitivity (#1483) |
| **Spiral circuit breaker (#1627)** | **Gated** — valence via State of Mind is already input 1; enriched sentiment could corroborate *after* the detector exists | **Gated** — only if S-3 shows a mechanic is a leading indicator; deterministic path only | **Forbidden** — the breaker must be pure and deterministic ("no LLM anywhere in the path"); appearance has no deterministic source | **Allowed as candidate input** — S-4; fail-closed semantics already match (#1627: missing data suppresses celebration) | **Gated** — theme-drop may inform the private check-on-him flow, not the suppression predicate, until studied |
| **Private milestone digest (#1623)** | Forbidden as content source (digest fires only from the `MILESTONE#` ledger) | Forbidden | Forbidden (#1619: milestones + body-composition excluded permanently) | **Allowed implicitly** — the digest's silence *is* the cadence signal, by design | Forbidden |

Reading the matrix: **every cell that moves beyond today's shipped behavior routes through
exactly two gates** — the Methods Registry (§4) for anything numeric, and the #1627
circuit breaker for anything that could fire during a spiral. No third path.

---

## 4. Guardrails and the Methods Registry sketch

The four house rules, applied to this corpus:

1. **ADR-104 — absence semantics.** A day without a diary is "no data" for every layer.
   No consumer may treat non-recording as a miss, a mood signal, or a default value.
   The single sanctioned interpreter of absence is the #1627 detector — private,
   deterministic, fail-closed — and even there absence *suppresses* output rather than
   generating claims.
2. **ADR-104 — grounded generation.** Any narrative that references diary content passes
   the existing gates: number/date allow-lists, `ungrounded_behavioral_findings`
   (#1699), consent-gated quote grounding (`diary_consent._grounded_quote`). No new
   narrative surface is proposed by this design, so no new gate work is required for v1.
3. **ADR-105 — deterministic before LLM.** Every proposed extraction in §2 is
   deterministic (timestamps, counts, dates). No LLM verdict about the corpus is
   proposed anywhere in v1. The only LLM touching diary content remains the existing
   Haiku enrichment pass and the (dormant, gated) Sonnet diary reaction.
4. **Budget (ADR-063/125/133).** §5. v1 registers no new budget features because it
   makes no new AI calls.

**Methods Registry sketch** — the promotion contract for *any* diary-derived signal that
could ever move a number. Proposed as `docs/METHODS_REGISTRY.md` (story S-6; the epic
names the registry as a requirement but no file exists yet). One entry per signal:

```
## <signal_name>                      e.g. speech_wpm
- Producer:            <file.py::function>  (deterministic; cite the computation)
- Definition:          exact formula, units, and the fixed wordlists/constants it uses
- Channel provenance:  which channels produce it; cross-channel comparability statement
- Absence semantics:   ADR-104 class — "no data" | behavioral-miss | measured-gap (+ why)
- Validation:          study ref, n, effective n (stats_core), CI, verdict date
- Thresholds:          personal-variance derivation (percentile bands) or "descriptive only"
- Status:              analysis-only → advisory (visible, moves nothing) → scoring
- Consumers allowed:   explicit allowlist (matrix row cites)
- Budget feature key:  lambdas/budget_guard.py key, or "deterministic — none"
- Spiral gating:       whether any output keyed to this signal is a celebratory emitter
                       (if yes: must appear in the #1627 wiring test)
```

Promotion from `analysis-only` requires: validation row filled with effective-n CIs;
thresholds derived from ≥ 30 sessions of personal variance; an explicit
`behavioral`/measured decision for the character config if scoring is the target; and —
for anything that could produce a positive/celebratory output — the #1627 detector live
and the emitter enumerated in its wiring test. Demotion ("measured, found uninformative,
retired") is a first-class outcome recorded in the same entry.

---

## 5. Cost model against the budget-guard tiers

Baseline facts: tiers are fractional bands (≈73/87/97%) of the effective ceiling
(ADR-133); features register in `lambdas/budget_guard.py::_FEATURE_CUTOFF` + the ladder
test (`tests/test_budget_guard_ladder.py`) + an `allow()` call at the entry point;
unregistered features default to hard-stop-only (cutoff 3), which is why registration is
mandatory, not optional hygiene.

| Item | AI cost | Tier posture | Storage |
|---|---|---|---|
| L1 enrichment of a diary entry | 1 Haiku call/entry (~fractions of a cent), **already running** — no new registration (rides the enrichment lambda) | effectively band 1 economics, negligible | in-place `enriched_*` attrs, existing |
| Coach diary reaction (#1574, once triggered per S-0) | 1 Sonnet call, `max_tokens=220`, per consented entry | **registered: `coach_diary_reaction: 2`** (reader narrative — pauses at tier 2, correct band per ADR-125) | one small DDB row/day/channel |
| L2 speech mechanics (S-2) | **$0** — local, deterministic, computed at transcription time on the owner's machine | none — no `allow()` call exists to make | ~4 numeric Notion properties/entry (→ DDB attrs via ingestion); negligible |
| L2 validation study (S-3) | **$0** — pure `stats_core` computation | none | one report in `docs/reviews/` |
| L4a cadence input (S-4) | **$0** — deterministic DDB date scan inside the #1627 detector | none (the breaker is LLM-free by AC) | none new |
| L4b theme-drop question (S-5) | **$0** at detection; the question rides the existing check-in queue (no generation — the question template is deterministic) | none for v1; if a narrated variant is ever wanted it registers band 1 (internal) first | one queue row per firing (rare: ≥14-day windows + cooldown) |
| L3 | — | — | — (refused; also avoids the real cost center: video storage/egress, which stays $0 because footage never uploads) |

**Net: the recommended v1 adds ~$0/month AI and ~$0 storage.** The only Bedrock spend in
the whole diary domain remains the existing enrichment Haiku call and the dormant tier-2
Sonnet reaction. At tier 2 the reaction pauses honestly (no fabricated reaction); at
tier 3 everything narrative is already stopped; the deterministic layer-2/4 signals keep
computing at every tier because they cost nothing — which is the correct shape: **the
measurements survive a budget crunch; only the narration pauses** (ADR-125's audience
ordering, applied by construction).

---

## 6. Sequencing — pressure-testing "analysis-only first," and the #1577 verdict

**#1577 AC2's analysis-only-first recommendation survives pressure-testing, strengthened.**
The case for skipping straight to influence would require at least one layer-2/4 signal
with known validity — none exists (n = a handful of entries as of this spike; the
video-channel corpus is days old). Analysis-only is not caution theater here; it is the
only posture ADR-105 permits when personal-variance thresholds cannot yet be computed.
The promotion gate is defined (§4), so analysis-only is not a parking lot — it is a
pipeline stage with an exit criterion and a deadline forced by data volume (≥ 30 sessions
≈ one quarter at a 2–3×/week cadence).

**Verdict on #1577's scope: do not widen it.** #1577 should stay exactly what it is —
the same enrichment schema over the three conversational partitions with channel
provenance and dedup. Diary transcripts already flow the pipeline it extends (#1572
landed that), and layers 2–4 are a different kind of work (deterministic side-car +
governance) that would bloat a clean story. The one connective change worth making when
#1577 lands: its new channel vocabulary and this spike's Methods Registry should be the
same registry, not two.

Sequencing constraints that bind (in order):

1. **#1627 before any celebratory or state-referencing emitter** — the epic-#1619
   sequencing rule is non-negotiable and applies to diary-keyed outputs too.
2. **S-0 (trigger wiring) before any diary-reaction expectations** — the shipped consumer
   currently never fires.
3. **Data volume before validation** — S-3 and S-1 are calendar-gated by corpus growth,
   not effort.

---

## 7. Candidate follow-up stories (for owner triage — deliberately NOT filed)

**S-0 · ops: wire the coach-diary-reaction trigger (and fix the same-day sk collision)** —
`coach_diary_reaction.lambda_handler` has no CDK function, no EventBridge rule, and no
caller; the read endpoint and lab-notes render are live but nothing produces rows. Add the
CDK function + a post-enrichment trigger (it must run *after* the 6:30 AM enrichment pass,
which produces the themes it routes on), and widen the sk to include the entry suffix so
two same-day recordings on one channel don't overwrite. Effort: **S**. (Genuine bug-class
finding of this spike; highest immediate value.)

**S-1 · analysis: channel-shift calibration of the enrichment schema** — once ≥ 20
video/solo entries exist, a one-off deterministic comparison of `enriched_*` distributions
by channel (typed vs spoken), reported with effective-n CIs; outcome is a short
`docs/reviews/` note and, if shift is material, a prompt-tuning follow-up. No production
change. Effort: **S** (calendar-gated).

**S-2 · capture: deterministic speech-mechanics side-car in `transcribe_solo.py`** —
compute `speech_wpm`, `pause_fraction`, `filler_rate`, `median_utterance_words` from
Whisper segment timestamps at transcription time; write them as Notion properties beside
`duration_(s)`. Local, $0, consumed by nothing. Includes the Methods Registry entries
(status: analysis-only). Effort: **S**.

**S-3 · analysis: speech-mechanics validation study** — after ≥ 30 sessions, correlate
each S-2 metric against same-day `enriched_energy`/`enriched_mood`/State-of-Mind valence
using `stats_core` (effective n, CIs). Ships a keep/retire verdict per metric into the
Methods Registry. This is the **only** story that can ever promote layer 2. Effort: **M**
(calendar-gated ≈ one quarter).

**S-4 · safety: diary cadence as a candidate #1627 circuit-breaker input** — blocked by
#1627 shipping. Add cadence-drop-vs-personal-trailing-baseline as a sixth leading
indicator in the deterministic detector; fail-closed; suppression reasons include it;
covered by the breaker's wiring test. Effort: **S–M** (mostly analysis of the right
baseline window).

**S-5 · coaching: deterministic theme-drop → one private check-in question** — detector:
theme (8-way fixed vocabulary) present in ≥ 3 entries then absent ≥ 14 days → enqueue one
templated question on the check-in queue, per-theme cooldown ≥ 30 days, never public,
never a claim, suppressed entirely while #1627 indicates a suspected spiral (a check-in
question is fine; a *pattern-observation* question mid-spiral needs the human, not the
queue — route those to the private digest channel instead). Blocked by #1627. Effort: **M**.

**S-6 · governance: `docs/METHODS_REGISTRY.md` + wiring test** — create the registry
(schema in §4) seeded with the six existing flourishing signals and the S-2 mechanics;
add a test asserting every producer writing into a scoring-consumed partition has an
entry (the enforcement teeth the epic's invariant currently lacks). Effort: **M**.
Recommended **first** among the non-ops stories — it is the gate everything else cites.

Suggested order: S-0 → S-6 → S-2 → (corpus grows) → S-1, S-3 → (after #1627) → S-4, S-5.

---

## 8. The won't-do list — permanent refusals, with reasons

1. **Automated physique / body-composition / appearance inference from footage — never.**
   No method survives ADR-105 (no deterministic computation, no honest uncertainty, no
   personal-variance baseline); the domain is already properly instrumented (scale +
   labs, trailing-mean semantics per #1626); and the #1619 board verdict excludes
   body-composition content from automated surfaces on the merits, permanently
   (documented harm pattern; rationale held privately — `docs/PLATFORM_CONTEXT.md`,
   PRIVATE). This includes building video upload *in order to* make such inference
   possible later.
2. **Any machine commentary on how he looks — never, on any surface, at any tier.** Even
   as a "neutral observation" in a private brief: for a subject whose self-image is part
   of the measured system, appearance commentary is an uncontrolled intervention, wrong
   in ordinary weeks and hazardous in vulnerable ones (§2.3).
3. **LLM inference of mood, affect, or avoidance from silence, tone, or delivery —
   never.** Absence is "no data" (ADR-104); tone-reading is unfalsifiable narration
   dressed as measurement (ADR-105 rule 3 inverted). Deterministic detectors may state
   facts ("theme X last appeared N days ago"; "speech rate was Y wpm"); nothing may
   claim to know what those facts mean about his inner state.
4. **Any layer-2/3/4 derivative on a public surface — never.** Voice features are
   identifying (#1388 AC3); silence is a private signal by design (#1627: "suppression
   is never surfaced publicly"; #1623's whole premise); unvalidated numbers public
   violate ADR-105 rule 1 at the front door. Public exposure of diary content remains
   exactly the shipped consent chain: entry-level fail-closed tiers, grounded quotes
   only, aggregate themes with n.
5. **Diary cadence as a character-scoring or habit-graded input — never.** The epic
   invariant ("skipped sessions are 'no data,' never failure") is load-bearing twice
   over: honesty (ADR-104) and signal preservation — a diary kept to protect a score
   stops being candid, which destroys layer 1 to fake layer 4.
6. **Celebratory or milestone-flavored output keyed to diary signal before the #1627
   circuit breaker exists — never** (and after it exists, only through its wiring test).
   The #1619 sequencing rule — detector before broadcaster — applies to every emitter
   this design could create.
7. **Raw footage or audio leaving the owner's device without an explicit owner opt-in —
   never.** Standing invariant (#1564/#1388). `raw/matthew/diary/` stays a
   pointer/transcript prefix; the media cost center stays at $0 and the leak surface
   stays at zero bytes.

What this list deliberately leaves on the table is most of what a "video intelligence"
feature would advertise — affect scores, appearance tracking, avoidance profiling. The
platform's position, consistent with its own precedents, is that those are not signals it
declined to build well; they are numbers that cannot be built honestly at n = 1 with this
capture chain, aimed at exactly the person a wrong number would harm.

---

## 9. Open questions for the owner

1. **S-5's mid-spiral routing** — when the breaker indicates a suspected spiral AND a
   theme-drop fires, v1 routes nothing to the queue. Should it instead nudge the private
   digest channel (#1623's 5–8 humans)? That is a judgment call about the humans, not
   the code.
2. **Interview-session cadence** — `/vlog` interview transcripts (#1571, unbuilt) will
   share the `video_diary` channel. Should interviewed vs solo sessions be
   distinguishable in provenance (they differ in prompting, hence in what cadence
   means)? Cheap now (a Notion property), annoying later.
3. **Methods Registry location** — §4 proposes `docs/METHODS_REGISTRY.md`; if the owner
   prefers it machine-readable (a `config/` JSON the wiring test parses), S-6 should say
   so before it ships.
