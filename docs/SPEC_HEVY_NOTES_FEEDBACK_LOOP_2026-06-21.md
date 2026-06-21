# Build Outline & Design Brief — Training Notes Feedback Loop (Derived Note-Signal Layer) — v1.0

> **Destination in repo:** `docs/SPEC_HEVY_NOTES_FEEDBACK_LOOP_2026-06-21.md`
> **Date:** 2026-06-21 · **Version:** 1.0 (pre-build outline)
> **Status:** Pre-build outline. Build instructions → `docs/specs/CLAUDE_CODE_PROMPT_HEVY_NOTES_v1.md`.
> **Boards consulted:** Personal (full — what's worth extracting + the safety lens), Technical (full), Product (light — the two-way-voice loop).
> **Related / prior art:** `docs/SPEC_MEAL_GROUPING_2026-06-19.md` (the derived-projection-over-untouched-raw pattern this mirrors), `docs/SCHEMA.md` (single-table keys, ADR-005 no-GSI), the `ruck_log` overlay (notes-correct-the-number precedent), `get_freshness_status` (silent-failure guard hook), `TRAINING_CALIBRATION.md` (the consumer — pre-flight + autoregulation gates).

A build outline, not line-level code. Captures the architecture, the signal taxonomy, the schema, the cost-bounded extractor, the safety handling for pain, and the two-way loop that is the whole point.

---

## 1. Goal & scope

Matthew has started writing freeform notes on individual Hevy exercises (first session: 2026-06-20). Today that signal **evaporates after one read** — the raw note syncs and sits on the workout, but there is no structured, queryable, *progressive* view of it. This feature adds a **derived note-signal layer** over the raw Hevy notes so that:

1. **Coaches see the arc, not the latest line.** The cycling note "flat level 10 today" → next day "up to level 18" → day after "intervals between 6 and 7" becomes a **per-exercise timeline** the coach reads as a trajectory, and prescribes the next step from ("today, intervals 6↔8").
2. **The descriptions get better.** Extracted progression/form/equipment signals feed the next routine's exercise notes — the two-way voice. A struggle-then-resolution on one lift ("lowered it and it made sense") can surface a pattern that informs cues on others.
3. **Safety signals are never lost.** A pain/joint note is elevated, not buried — it reaches the next pre-flight and the training thread.

The mental model Matthew gave, verbatim in spirit: *a two-way voice, as if a personal trainer were standing next to him during the set.* The number tells the coach **how hard**; the note tells the coach **why** — and the why is what was missing.

### Invariants (non-negotiable)

1. **Raw notes are untouched.** The extracted signal layer is a derived projection. The raw Hevy `notes` (per-exercise) and `description` (per-workout) fields stay the source of truth — verbatim, queryable, never mutated, never deleted. Every signal record stores `note_raw` exactly as written. The signal view is *additive*.
2. **Inferred, and labelled as such.** An extracted signal is an inference over natural language. Every signal carries `confidence` + `extracted_by` (`deterministic` / `haiku` / `hybrid`). No surface presents an extracted signal as ground truth without that treatment (Henning standard).
3. **Notes never silently overwrite numbers.** A note that qualifies a logged metric ("that RPE 9 was shins, not calves") emits an **overlay** the coach reads — it never mutates the raw logged RPE/load. Raw wins; interpretation is additive (the `ruck_log` override precedent: persisted overlay, raw is the under/over-count beneath it).
4. **Conservation of notes.** Every non-empty raw note maps to exactly one signal record (which may carry ≥1 signals). A note is never dropped on extraction failure — on failure it is stored with `note_raw` + deterministic signals only, flagged `extracted_by:"deterministic"` and `degraded:true`. The pipeline going dark must be **visible**, not silent (freshness hook, §8).
5. **Pain is never missed.** The `pain_discomfort` class has a deterministic floor that fires regardless of the LLM (§6). False positives are acceptable here by design.
6. **Private.** Training notes are personal free text. They are never an auto-public surface. No website rendering without an explicit, separate gate (Yael / Henning).

Non-goals: editing notes back into Hevy (it stays authoritative for what was written); transcribing/voice; a notes UI (the input is Hevy's native field — zero new surface, by design).

---

## 2. Board discussion (the design tensions, resolved)

**Is a pipeline justified, or just read the raw field? — Viktor Sorokin (Principal of No).**
Reading one note in one session is a single tool call (done live 2026-06-20). The infrastructure is justified *only* by the two things a raw read can't do cheaply: the **per-exercise progression across sessions**, and **cross-exercise pattern detection**. Without the distill, every pre-flight re-reads every workout's raw notes and re-derives the arc by hand — lossy, unrepeatable, and it scales badly as note history grows. **Gate (Viktor + the meal-layer precedent): the per-exercise timeline and the loop-back into descriptions are the deliverable. Extraction without the loop is vanity logging — it does not ship alone.**

**The schema is the crux — Omar Khalil (data architect).**
Matthew's requirement *"progressive notes vs just the most recent"* is a sort-key decision. Key the projection by **exercise identity** (Hevy `template_id`, stable across sessions) so one Query returns the date-sorted arc. No GSI; within ADR-005. (§5.)

**LLM richness vs rigor & cost — Anika Patel vs Dana Torres / Henning Brandt.**
Anika: notes are too freeform for pure regex ("more shins than calf" needs a model). Dana/Henning: then bound it exactly like the meal namer — cheapest capable model (Haiku), hash-cache so unchanged notes never re-extract, run only on non-empty notes (most are blank → $0), constrained JSON, frozen-as-data, correctable, never a read-path dependency. **Resolution: deterministic-first, LLM for the semantic tail.**

**Pain is the one safety-critical class — Dr. Iris Tanaka (interim Sports Med, narrow veto mandate).**
"Everything else here is optimization. A 'sharp knee' note is the single signal that must never be lost in a distill." → deterministic pain lexicon fires independently of the LLM; pain doesn't just sit in the projection, it **elevates** (insight + training-thread flag + next pre-flight). The LLM is a second pass on top, never the only catch. (§6, §7.)

**Notes can correct numbers — but never silently — Henning Brandt.**
The RPE-caveat case is a note correcting a logged number. Handle as an overlay the coach reads, confidence-tagged; raw logged value untouched (Invariant 3).

**Adherence is half the value — Coach Maya Rodriguez.**
"Don't let the engineers discard 'enjoyed it' as noise. For this athlete the off-switch is the whole game; capturing what he likes biases the plan toward continuity — the highest-leverage variable there is." → `sentiment_adherence` is a first-class class.

**The two-way voice — Mara Chen / Raj Mehta (Product, light touch).**
Mara: input friction is already zero (Hevy's native field) — protect that; the moment it needs an app, it dies. Raj: the loop is note → better next description → more notes; ship the loop-back or it's a diary. Notes stay private (this is a coaching loop, not content).

**Could another team own this? / what breaks at 2am — Elena Reyes / Jin Park.**
It rides the existing Hevy ingest; it is a post-ingest derive step, not a parallel pipeline. Idempotent upsert by stable key; Hevy edits re-extract on note-hash change; resumable batch backfill (trivial now — ~1 day of notes — but designed for growth).

---

## 3. Empirical grounding (the seed corpus)

The 2026-06-20 Recovery session is the seed corpus — 5 non-empty notes across 9 exercises. They already validate the taxonomy:

| Exercise | Raw note | Classes it exercises |
|---|---|---|
| Standing Calf Raise | "Last time I didn't use a platform… this time I did so much harder from balance perspective" | `progression` (added platform → full ROM), `form_technique` (balance), `equipment_setup` |
| Seated Calf Raise | "New machine… some of this was more foot and shins then calf RPE" | `rpe_caveat` (RPE 9 inflated — not true calf overload), `equipment_setup`, `form_technique` |
| Pallof Press | "First time I've done this ever today and enjoyed it" | `sentiment_adherence` (positive, novel) |
| Farmers Walk | "Grip gave out before strength, then forearm burn… yards equals steps so easier to count" | `limiter` (grip-before-strength), `logging_quirk` (distance field = steps, not yards/m) |
| Cycling | "Low effort level 10 for whole thing" | `progression` (level=10, easy) — the exact arc-anchor for the loop |

Two facts shaped the design: (a) notes are **sparse** (5 of 9 here; most exercises will carry none) — so "run only on non-empty notes" is the dominant cost lever; (b) a single note routinely carries **multiple classes** (the calf and farmers notes each carry 3) — so a signal record holds a *list* of signals, not one label.

---

## 4. Phase 0 — measure before building

Cheap, no production code. Resolves what would otherwise bias the build:

- **Sync fidelity check.** Confirm the Hevy ingest reliably carries per-exercise `notes` *and* per-workout `description` (today: per-exercise confirmed via `get_workout_detail`; description field present but empty). Confirm behaviour on a **Hevy-side edit** — does a re-synced workout bring the updated note (so the hash-cache re-extract path is real), or does Hevy only push on create? This determines whether the nightly sweep is a backstop or load-bearing.
- **Taxonomy freeze from real notes.** Lock the §5 class list against the seed corpus + the next ~1–2 weeks of real notes (Matthew just started — let a little history accrue). Output: frozen `signals` enum + a deterministic pattern set for the rule-pass classes (numeric `level`/`load`, the pain lexicon, equipment keywords, the steps-vs-yards quirk).
- **Pain lexicon draft.** Assemble + red-team the lexicon (sharp, twinge, tweak, pinch, niggle, "joint", knee/elbow/shoulder/wrist/hip/lower-back + pain/hurt/sore-in-a-bad-way). Over-inclusive on purpose; Iris signs off.

**Output of Phase 0:** frozen taxonomy, deterministic pattern set, pain lexicon, edit-resync answer, and Matthew's locked params (§13).

---

## 5. Architecture & data model

### One derive path; raw stays sovereign

```
Hevy workout ingest (raw, untouched)  ◄── SOURCE OF TRUTH
   │  (read-only: per-exercise `notes`, per-workout `description`)
   ▼
note extractor  (per NON-EMPTY note only)
   1. deterministic pass   — numeric level/load, pain lexicon (always), equipment kw, logging-quirk kw
   2. LLM pass (Haiku)     — semantic signals → constrained JSON over the frozen taxonomy
   3. hash-cache           — skip if note_hash unchanged (handles Hevy edits + re-imports)
   4. conserve + degrade   — every note → exactly one record; on LLM failure keep raw + deterministic, flag degraded
   ▼
NOTE-SIGNAL projection  (derived, versioned, correctable)  ── keyed by EXERCISE for the timeline
   │
   ├─► pain elevation     — pain_flag → insight + training-thread flag + next pre-flight (§7)
   │
   ▼
coach reads:  get_exercise_notes(exercise, lookback)         ── the arc
description generator (manage_hevy_routine):  consumes latest progression/equipment/sentiment  ── the loop-back (Phase 2)
```

The ingest/backfill stop at the **NOTE-SIGNAL projection** (the only thing the coach reads for "what he told me"). Raw notes remain the only thing read for verbatim text.

### Schema (single-table, no GSI — ADR-005)

New derived source label **`training_notes`** (add to `SCHEMA.md §Sources`). *(Source-agnostic name chosen over `hevy_notes` so a future non-Hevy note source folds in — pending Matthew's lock, §13.)*

**Signal record** — keyed by **exercise** so the timeline is a single Query:
- `pk = USER#matthew#SOURCE#training_notes#EXERCISE#<hevy_template_id>`
- `sk = DATE#YYYY-MM-DD#WORKOUT#<workout_id>`

```
exercise_name     "Standing Calf Raise (Barbell)"
exercise_template "E53CCBE5"
workout_uid       "hevy:dc3e3b10-..."
note_raw          "<verbatim — never mutated>"
note_hash         "<sha256 of note_raw>"           # cache key; re-extract only on change
signals           [ { class, summary, value?, confidence } , ... ]   # ≥1 per note
pain_flag         false
sentiment         "positive" | "neutral" | "negative" | null
degraded          false                            # true = LLM failed/capped, deterministic-only
extracted_by      "deterministic" | "haiku" | "hybrid"
algo_version      "note-extractor@1.0.0"
extracted_at      <ts>
```

`signals[].class` ∈ the frozen taxonomy (§ below). `value` is structured where the class supports it (e.g. `{level:10, character:"flat"}` for a cycling `progression`; `{rom:"full","aid":"platform"}` for the calf).

**Correction overlay** — `sk = DATE#…#WORKOUT#<id>#CORRECTION`: `{ signals?, pain_flag?, sentiment?, corrected_by:"matthew", at }`. Wins forever, survives recompute (ruck-log / meal-correction precedent).

**Per-workout view** needs no new item — the raw workout already holds every exercise's note; a "notes from this session" read is free off `get_workout_detail`. The derived projection exists for the **per-exercise timeline** and the **structured signals**, which raw can't serve.

### The signal taxonomy (frozen in Phase 0)

Each `{class, summary, value?, confidence}`:

- `progression` — level/load/ROM/volume change. The arc anchor. *(cycling L10→L18→intervals; calf platform→full ROM)*
- `form_technique` — technique state / cue that worked or didn't. *("balance harder", "form clicked")*
- **`pain_discomfort`** — joint/tendon/bad-pain. **Safety: deterministic floor, sets `pain_flag`, elevated.**
- `rpe_caveat` — qualifies a logged metric. **Overlay only, never overwrites raw** (Invariant 3).
- `equipment_setup` — machine/tool/setup change. *("new machine", "no platform", "used straps")*
- `limiter` — what capped the set. *("grip gave out before strength")*
- `sentiment_adherence` — affect / enjoyment. **First-class (Maya).** *("enjoyed it", "hated", "felt strong")*
- `logging_quirk` — a data-integrity note about how he logs. *("distance = steps not yards")*
- `environment` — *("travel gym", "crowded", "outdoor")*
- `deviation` — Matthew changed the pushed routine: added/removed/swapped exercises, changed sets/loads. Derived by **diffing the pushed routine vs the performed Hevy workout** (not from a note) — durable preference & capacity signal. *(sent 5 leg exercises, did 10; swapped a DB for a barbell)*
- `rest_adherence` — prescribed rest vs actual rest per exercise. Surfaces where he consistently needs more (or less) rest; feeds a **bidirectional** rest-intent cue (coach may deliberately prescribe "rest discipline matters more than load today"). *(Phase 0 must confirm Hevy exposes actual per-set rest.)*

---

## 6. The extractor — deterministic-first, LLM tail, pain floor

```
note = exercise.notes
if blank(note): skip                                  # dominant path → $0
sig = []
sig += deterministic_pass(note)                       # numeric level/load; equipment kw; logging-quirk kw
pain = pain_lexicon_hit(note)                          # ALWAYS runs; over-inclusive
if cache.has(note_hash): record = cache.get; pain = pain or record.pain   # reuse; pain re-checked deterministically
else:
    try:    sig += haiku_extract(note, TAXONOMY)       # constrained JSON, max_tokens tight
    except: degraded = True                            # keep raw + deterministic sig; never drop (Invariant 4)
    cache.put(note_hash, ...)
pain_flag = pain or any(s.class=="pain_discomfort" for s in sig)   # deterministic OR llm → flag
emit(record); if pain_flag: elevate(record)            # §7
```

- **Deterministic pain net is authoritative for the flag.** The LLM can *add* a pain signal but can never *clear* the deterministic hit. Better a false "check your knee" than a missed real one (Iris).
- **Hash-cache** keys on `note_raw` text → an unchanged note across re-imports costs nothing; a Hevy edit changes the hash → re-extract. (Phase 0 confirms edits re-sync.)
- **Cost discipline (Dana):** non-empty-only + Haiku + constrained JSON (~note-length in, ≤~64 tokens out) + hash-cache + batch backfill + monthly cap with **fail-safe to `degraded` deterministic-only** on breach. Realistic steady-state cost: pennies (notes are sparse and repetitive once the cache warms).

---

## 7. Pain elevation (the safety path)

`pain_flag == true` triggers, in order:
1. **Insight** (`save_insight`, tags `["training","pain","<exercise>"]`) — durable, shows in the coaching log.
2. **Training-thread annotation** — so Dr. Sarah Chen's thread carries it into the next session's continuity read.
3. **Next pre-flight surface** — `get_exercise_notes` returns `pain_flag` prominently; the §4 autoregulation gates in `TRAINING_CALIBRATION.md` already say *"sharp or localized joint/tendon pain → stop that movement"* — this wires a written pain note straight into that gate instead of relying on Matthew to re-mention it.

Pain has **no confidence floor** — it surfaces even at low confidence (Invariant 5). Matthew can dismiss a false positive via the correction overlay; the dismissal persists.

---

## 8. The two-way loop (Phase 2 — the wedge)

This is what makes it a coach and not a diary (Raj / Viktor's gate):

- **Pre-flight input.** The coaching session protocol (`COACH_SESSION.md` step 2) gains `get_exercise_notes` for the lifts in play — the per-exercise arc joins `get_exercise_history` as a standard pull.
- **Description generation.** When `manage_hevy_routine` (draft_custom) writes an exercise note, it consumes the latest `progression`/`equipment_setup`/`sentiment` signals for that exercise and writes the next cue from them. *Cycling: last L10 flat → L18 → "today, intervals 6↔8 by feel."* *Calf: "keep the platform; hold load — the full-ROM deficit is the progression."*
- **Cross-exercise pattern detection (Henning-gated).** A recurring shape ("form-struggle resolved by dropping load") across ≥ n exercises/sessions surfaces as an insight — n-floored (default 3), correlative framing, confidence + n on every claim. Never a causal verdict.

**Determinism boundary:** the *facts* the coach acts on (the numeric progression, the pain flag) are deterministic or human-written; the LLM supplies only the *semantic summary* of fuzzy notes, frozen-as-data and correctable. A wrong semantic summary is a display nit fixed in one correction — it never silently changes a prescribed load.

---

## 9. MCP surface

One read tool in Phase 1; extend in Phase 2. Tool fn **before** `TOOLS={}`; implementing fn in the **same commit** as registration; `pytest tests/test_mcp_registry.py` green before deploy; deploy via `bash deploy/deploy_mcp_split.sh` (full `mcp/` dir).

- `get_exercise_notes(exercise | template_id, lookback_days?)` → the per-exercise timeline (date-sorted signals + raw notes + pain flags). Phase 1.
- Phase 2 actions (fold into a `manage_training_notes` fat tool, SIMP-1 ≤80): `timeline` · `recent_pain` · `patterns` · `correct`.

---

## 10. Phasing (sequence is a gate)

- **Phase 0** — sync-fidelity + edit-resync check, taxonomy freeze, pain-lexicon red-team, param lock (§4, §13). No production code.
- **Phase 1** — Extractor (deterministic + Haiku + hash-cache + pain floor + conservation/degrade) → `training_notes` projection keyed by exercise → `get_exercise_notes` read tool → pain elevation (§7). **Private. No loop-back, no website.** Eyeball accuracy against real notes for ~1–2 weeks.
- **Phase 2** — Close the loop: `get_exercise_notes` into the pre-flight + description generator; cross-exercise pattern detection (n-floored); correction tool. **Gate: Phase 2 is what justifies the build (Viktor) — Phase 1 alone is instrumentation, useful privately but not the goal.**

---

## 11. Safety, rigor & cost (summary)

- **Provenance (Omar):** writes only to `SOURCE#training_notes`; a test asserts zero writes to `SOURCE#hevy`/raw workout partitions.
- **Idempotency (Jin):** upsert by stable `DATE#…#WORKOUT#<id>`; re-import/edit never duplicates; backfill is a resumable batch, not a hot loop.
- **Conservation (Invariant 4):** every non-empty note → exactly one record; failures degrade, never drop; `degraded`/format-drift visible in `get_freshness_status`.
- **Safety (Iris, Invariant 5):** deterministic pain floor; pain elevated with no confidence floor.
- **Honesty (Henning):** `confidence` + `extracted_by` everywhere; notes never overwrite raw numbers (Invariant 3); pattern claims n-floored + correlative.
- **Privacy (Yael, Invariant 6):** private; no public surface without a separate gate; least-privilege IAM on the extractor Lambda.
- **Cost (Dana):** non-empty-only + Haiku + hash-cache + cap + fail-safe ⇒ pennies steady-state; Batch API for any backfill.

---

## 12. Doc-update implications (when Phase 1 lands)

Per the trigger matrix: CHANGELOG + PROJECT_PLAN always; SCHEMA + DECISIONS (new `training_notes` source + NOTE-SIGNAL projection + a short ADR "derived note-signal projection, never mutate raw Hevy notes; notes overlay numbers, never overwrite"); MCP_TOOL_CATALOG + RUNBOOK (`get_exercise_notes`); DATA_DICTIONARY (new derived domain); COST_TRACKER only when the Haiku extractor first runs at volume. Update `PLATFORM_FACTS` in `deploy/sync_doc_metadata.py` then `python3 deploy/sync_doc_metadata.py --apply`. Archive this outline to `docs/archive/` once a full Phase-1 spec supersedes it.

---

## 13. Decisions — LOCKED 2026-06-21

- **Source label:** `training_feedback_loop`.
- **Trigger:** **on-ingest, right after each session** (fast feedback). **No edit-resync / retroactive handling** — real-time only; after-the-fact corrections are handled by Matthew in chat during workout development. The Phase-0 edit-resync test and the edit-driven nightly sweep are **dropped**. (A light nightly backstop may still catch a fully-missed session, but is not for edits.)
- **Pain elevation:** all three — insight + training-thread flag + next-pre-flight surface.
- **A note does not auto-change the plan (reframed from a numeric 'confidence floor').** A note is **one more input to the coach's reasoning**, never an automatic mutation. Behaviour: fold the signal into the read; if it's a judgment call, the coach **reasons about it, or asks Matthew a question** — never silently acts, never silently ignores. (Pain is the exception — always surfaced.) Confidence still rides every signal for honest weighting.
- **Pattern n-floor:** 3.
- **LLM:** Haiku 4.5, monthly cap (~300), fail-safe to deterministic-only + alarm.

## 14. Additions surfaced 2026-06-21 (fold into build)

**14.1 Deviation capture (routine-as-pushed vs workout-as-performed).** New `deviation` class (§5). Today the only reference is what was *pushed*; what Matthew *actually did* (the completed Hevy workout) is the truth and is already available via `get_workout_detail`. Diff the two per session → added/removed/swapped exercises, set/load deltas. Long-term this is a strong preference + capacity signal ('consistently adds a 4th set', 'swaps DB→barbell'). Cheap — pure diff, no LLM.

**14.2 Rest-time adherence.** New `rest_adherence` class (§5). Matthew is deliberately extending rest this first week. Capture prescribed-rest vs actual-rest where Hevy exposes it (**Phase 0 confirms availability**); surface where he needs more/less, trend it, and make it **bidirectional** — the coach may deliberately prescribe rest discipline as the day's focus ('today, holding 90s rest matters more than the load'). Where Hevy doesn't expose per-set rest, the notes loop captures it qualitatively.

**14.3 Recovery-conditional descriptors (fixes night-before staleness).** *Surfaced live, now promoted to its own spec:* see **`docs/SPEC_RECOVERY_ADAPTIVE_AUTHORING_2026-06-21.md`** (edge-case-proof night-before authoring: tier-agnostic routines, wrist-band self-selection, freshness-gated authoring, subtract-only ceiling, week-position floors). The 2026-06-21 routine was built the night before and hard-stamped `recovery_tier=yellow` off Jun 20's reading; Matthew woke GREEN 95%. The bike-level branch ('YELLOW → L10; GREEN → intervals 6↔8') sources from the `progression` timeline here, but the full authoring design lives in the dedicated spec.

**14.4 BUG — `get_muscle_volume` staleness + core-mapping (own ticket / RCA).** *Surfaced live, two distinct defects:*
  - **Staleness/lag:** the night-before pull (Jun 14–20) reported Calves 10 / 'lagging' and Core 0; the next-morning re-pull (Jun 14–21) reported Calves 14 / 'optimal' with most groups jumping — the latest session(s) weren't aggregated when first read, so synthesis ran on incomplete volume. Same failure-class as the Strava high-water-mark blindness — **a volume read must know whether the most recent sessions are counted, or flag that they aren't.**
  - **Core-mapping:** anti-rotation / standing core (Pallof Press, loaded carries) buckets into **`Other`**, so `core_sets` reads 0 even when done two days running. Map these to core, or never assert 'core = 0' off a map that can't see them.
  Coaching-engine data bug (not a feedback-loop feature) — **raise as its own bug ticket / RCA**; captured here because it surfaced alongside the notes work and the feedback loop's value depends on the volume read being trustworthy.

---

*v1.1 — params locked + additions 14.1–14.4 folded in, 2026-06-21. Boards: Personal full, Technical full, Product light. Mirrors the meal-layer derived-projection pattern. Redline freely.*
