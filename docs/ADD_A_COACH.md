# Adding a Coach — the paved path

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-07-11
> **What this is:** the step-by-step, file-by-file procedure for extending the coach roster,
> grounded in how coaches *actually* wire together in this repo (not how they ought to).
> **The one-sentence version:** a coach is an **identity** (`config/personas.json`) that must
> line up, byte-for-byte, across four id name-spaces and ~a dozen files — and the persona
> registry test is the contract that proves it did.

Extending the coach moat is the product's core growth vector, and it has historically been the
weakest-paved path: the knowledge is scattered across `BOARDS.md`, ADR-040/047/055/106/108, and
`docs/coaching/READING_CALIBRATION.md` §9, and the persona-key ↔ coach-id duality is a footgun a
new engineer *will* trip on. This doc is the single map.

---

## 0. First decide: do you actually need an *operational* coach?

There are three tiers of "coach," and most additions do **not** need the top one. Pick the
smallest tier that does the job.

| Tier | What it is | What it costs | Where it lives |
|---|---|---|---|
| **Board persona** | An advisor/voice that appears on `/method/board/` and in email/observatory copy, but runs **no** compute pipeline. `operational: false`. | One `personas.json` entry + one `board_of_directors.json` member. No engine wiring. | Elena Voss, Dr. Eli Marsh, Cora Vance (today) all sit here — "features-gated to nothing, inert." |
| **Operational coach** | One of the daily-computed specialists: a STANCE#, a track record, predictions, a coach page, a podcast voice. `operational: true`. | Everything in §2–§10 below. Every id name-space must agree. | The current 8: sleep, training, nutrition, mind, physical, glucose, labs, explorer. |
| **Portrait** | A commissioned illustration for *either* of the above. Default is **sigil-only** (free, deterministic). Opt-in, behind the ADR-106 gate. | §8. Independent of operational status. | `config/portraits/<board_persona_key>.json` |

If you only need a new *voice on the board*, do §2 (personas.json) + the board member block and
stop. The rest of this doc is the operational path.

> **Invariant to respect:** the operational roster is deliberately **8** (`test_persona_registry`
> asserts `len(_operational()) == 8` in a couple of places, and the lead-persona test asserts
> "adding the lead must not change the operational count"). Making a 9th coach operational means
> **updating those count assertions too** — they are a guardrail, not a law of physics, but touch
> them consciously.

---

## 1. The mental model — four id name-spaces, one registry (read this or you will trip)

A single coach is referred to by **four different strings**, and the whole point of the CC-00
work (`config/personas.json` + `lambdas/persona_registry.py`) was to make them provably
reconcile so that a coach's public byline is *provably* the coach that authored the data.

| Name-space | Example (training coach) | Where it's the key | Rule (enforced by `test_persona_registry.py`) |
|---|---|---|---|
| **`persona_id`** | `training_coach` | top-level key in `config/personas.json` | For an operational coach, **must** be `<domain>_coach`. |
| **`coach_config_key`** | `training_coach` | filename of `config/coaches/<key>.json` + its `coach_id` field | **must equal `persona_id`.** |
| **`engine_id`** | `training_coach` | the `COACH_IDS` lists in the compute lambdas | **must equal `persona_id`** (no more `dr_johansson`-style aliases). |
| **`short_id`** | `training` | `intelligence_common.COACH_IDS_ALL`; short display | **must equal `persona_id` minus `_coach`.** |
| **`board_persona_key`** | `sarah_chen` | member key in `config/board_of_directors.json`; also the **portrait** filename | free-form; **must resolve** to a board member. |

> ### ⚠️ The footgun
> `persona_id` (`training_coach`) and `board_persona_key` (`sarah_chen`) are **different strings for
> the same coach**, on purpose. The engine, stance, predictions, and coach page all key off the
> `*_coach` persona_id. The board block, and the **portrait recipe filename**, key off the
> human-name `board_persona_key`. Get them crossed and the registry test fails — which is the
> system working as designed.
>
> **`docs/BOARDS.md` §"Coach Intelligence" is stale on this** — it still lists the *pre-CC-00*
> engine ids (`dr_johansson`, `fitness_coach`, `body_comp_coach`, …). Those names are dead. The
> live source of truth is `config/personas.json` + `lambdas/persona_registry.py`. Do not copy ids
> out of BOARDS.md.

**The loader** (`lambdas/persona_registry.py`) is the read API both the compute engine and the
site-api go through: `by_coach_config_key()`, `by_engine_id()`, `by_short_id()`, `display_name()`,
`tts_voice()`, `operational_personas()`, `board_personas()`. It prefers S3
(`config/personas.json`) and falls back to the bundled repo file. **`config/personas.json` is not
in the lambda bundle** — it is read from S3, so §10's S3 sync is mandatory, not optional.

---

## 2. The worked example — promote **Dr. Cora Vance** from board to operational

Cora Vance already exists as a **non-operational** board persona (the Reading Coach for the Mind
pillar — `config/personas.json` key `cora_vance`, `config/board_of_directors.json` member
`cora_vance`, mandate in `docs/coaching/READING_CALIBRATION.md` §9). She is "features-gated to
nothing," exactly like Elena Voss and Eli Marsh. Making her a real daily coach is the cleanest
worked example, because it exercises the footgun head-on.

**Her ids, chosen to satisfy §1:**

| Name-space | Value | Note |
|---|---|---|
| `persona_id` | `reading_coach` | a **NEW** key — must be `<domain>_coach`, so `cora_vance` cannot be it. |
| `coach_config_key` | `reading_coach` | ⇒ file `config/coaches/reading_coach.json`, `coach_id: "reading_coach"`. |
| `engine_id` | `reading_coach` | added to every `COACH_IDS` list (§5). |
| `short_id` | `reading` | `reading_coach`.replace("_coach","") — add to `COACH_IDS_ALL`. |
| `board_persona_key` | `cora_vance` | already resolves — the existing board member. |
| display `name` | `Dr. Cora Vance` | must be distinct from the other 8 (it is). |

So "add Cora as a coach" = **create a new `reading_coach` operational persona that links to the
existing `cora_vance` board member.** The name-space split is the whole lesson.

The steps below use `reading_coach` / `cora_vance` throughout. Substitute your own
`<domain>_coach` / `<board_key>` when you add a different coach.

---

## 3. Identity — `config/personas.json` + `config/board_of_directors.json`

**3a. Add the operational persona** to `config/personas.json` → `personas` (append at the end of
the 8 operational block, in display order). Required fields for an operational coach (the test
`test_operational_personas_have_coach_fields` enforces every one):

```jsonc
"reading_coach": {
  "name": "Dr. Cora Vance",
  "type": "both",              // operational coaches MUST be type "both"
  "operational": true,
  "domain": "reading",
  "short_bio": "Reading Coach for the Mind pillar — periodizes reading the way Dr. Sarah Chen periodizes training.",
  "emoji": "📖",
  "color": "#c2855b",
  "coach_config_key": "reading_coach",   // == persona_id
  "engine_id": "reading_coach",          // == persona_id
  "short_id": "reading",                 // == persona_id minus "_coach"
  "voice_spec_ref": "config/coaches/reading_coach.json",
  "board_persona_key": "cora_vance",     // resolves to the existing board member
  "board_role": "Reading Coach — The Mind Pillar",
  "tts_voice": "en-US-Chirp3-HD-<unique>"  // see §7 — must not clash
}
```

If you are promoting an existing board persona (like Cora), **delete or downgrade its old
board-only entry** (`cora_vance` was `type: board, operational: false`) so there is exactly one
persona per coach — otherwise the name-distinctness / count assertions fight you.

**3b. The board member already exists for Cora.** For a brand-new coach with no board presence,
add a member to `config/board_of_directors.json` → `members` keyed by your `board_persona_key`
(shape: `name`, `title`, `type: "fictional_advisor"`, `emoji`, `color`, `domains[]`,
`data_sources[]`, `voice{tone,style,catchphrase}`, `principles[]`, `personality{…}`,
`relationship_to_matthew`). `test_board_persona_keys_resolve` fails until the `board_persona_key`
resolves here.

> **ADR-040:** the cast is *openly-fictional advisors, never real public figures.* A new coach is
> a fictional persona. Do not model one on a findable real person (this also gates the portrait —
> §8, the reverse-image check).

---

## 4. The canonical constant — `lambdas/persona_registry.py`

`OPERATIONAL_COACH_IDS` is hard-coded (so compute lambdas import the id list without an S3
round-trip at module load). Add your id **in the same display order** as `personas.json`:

```python
OPERATIONAL_COACH_IDS = [
    "sleep_coach", "training_coach", "nutrition_coach", "mind_coach",
    "physical_coach", "glucose_coach", "labs_coach", "explorer_coach",
    "reading_coach",          # ← added
]
# OPERATIONAL_SHORT_IDS derives automatically (strips "_coach").
```

`test_persona_registry_constant_matches_json` asserts this list equals the `operational: true`
personas **in order**. Order matters.

---

## 5. The voice spec, the stance ladder, and **every** hard-coded coach-id list

### 5a. Voice spec — `config/coaches/reading_coach.json`

The personality/voice config the narrative pipeline reads. Copy an existing one
(`config/coaches/training_coach.json` is a good template) and rewrite for the new coach. Shape
(see any existing file for the full spec):

- `coach_id` (**must equal `coach_config_key`**), `display_name`, `domain`
- `structural_voice_rules` — `opening_patterns{preferred[],forbidden[],rotation_rule}`,
  `sentence_rhythm`, `uncertainty_style`, `analogy_domain`, `paragraph_structure`, `humor_style`,
  `relationship_to_others`, `signature_moves[]`
- `decision_style` — `default_evidence_threshold`, `comfort_with_bold_claims`, `revision_style`
- `few_shot_examples[]` — 2–3 full-length exemplar outputs in the coach's voice
- `anti_pattern_detection` — `phrase_blacklist[]`, `structural_blacklist[]`, `staleness_threshold`

`test_voice_spec_refs_exist_and_match` checks the file exists and its `coach_id` matches, and
`test_config_coaches_match_operational_personas` checks the set of `config/coaches/*_coach.json`
`coach_id`s equals the operational registry keys — no orphans either direction.

### 5b. Stance ladder — `config/coaches/reading_coach_stance.json`

The hand-authored stage ladder (`config/coaches/<coach>_stance.json`), resolved by
`lambdas/coach_stance.py` as the **silent fallback** for the coach page's "read of him" when the
evidence-derived `STANCE#` record isn't available. Shape: `coach`, `band_metric`, and a
`stage_ladder[]` of rungs, each `{stage_id, entry{metric,min,max}, headline, read_of_him,
cares_most[], cares_less_right_now[], plan, graduation_gate, watches[]}`. Bands must tile the
metric contiguously (`resolve_stage` walks half-open `[min, max)` bands). `watches[]` should
name real signals — each `watches` entry must be in `coach_stance.py`'s `KNOWN_SIGNALS`
whitelist (add the signal there if it's novel; `tests/test_coach_stance.py` enforces this).
`coach_stance.py` itself is coach-id-generic — no code change beyond the whitelist.

> The **live** "read of him" is the evidence-derived `STANCE#` record, not this file — see
> `docs/engines/COACH_STANCE.md`. The stance engine (`coach_history_summarizer.py`, the Sunday
> 6 AM PT weekly + event-triggered refresh) **iterates its own `ALL_COACH_IDS` list** and
> produces a STANCE# for every coach in it automatically — so once your id is in that list (5c)
> the stance machinery picks the coach up. This ladder is only the cold-start fallback.

### 5c. ⚠️ Every hard-coded coach-id list — the registry test guards only *four* of them

`test_persona_registry.py` enforces agreement for exactly these code lists:

- `lambdas/coach/coach_computation_engine.py` → `COACH_IDS`
- `lambdas/coach/coach_prediction_evaluator.py` → `COACH_IDS`
- `lambdas/coach/coach_narrative_orchestrator.py` → `ALL_COACH_IDS`
- `lambdas/intelligence_common.py` → `COACH_IDS_ALL` (short ids)

**But several other lambdas keep their OWN coach-id list that the test does NOT catch.** These
are the ones that will silently drop your coach from a surface if you forget them. Grep before you
trust this list (`grep -rn "COACH_IDS\|ALL_COACH_IDS\|COACH_NAMES" lambdas/`), then update each:

- `lambdas/coach/coach_history_summarizer.py` → `ALL_COACH_IDS` (the **stance + history** engine)
- `lambdas/coach/coach_ensemble_digest.py` → `ALL_COACH_IDS` (the cross-coach ensemble)
- `lambdas/emails/between_chronicle_lambda.py` → `COACH_IDS`
- `lambdas/operational/coherence_sentinel_lambda.py` → `COACH_IDS`
- `lambdas/compute/state_of_matthew_lambda.py` → `COACH_NAMES` (a dict id→name; `COACH_IDS` derives from its keys)
- `mcp/tools_coach_intelligence.py` → `COACH_IDS` (**short** ids) + `COACH_NAMES` (bare-id → display name; note it strips the `_coach` suffix)

> **This is the single biggest trap in the whole procedure.** Four lists have a test; the rest do
> not. Treat the grep as the checklist, not this doc — a new list could appear after this doc was
> written.

Lambdas that route through `persona_registry.OPERATIONAL_COACH_IDS` instead of a private list
(e.g. `lambdas/web/site_api_coach.py`, `coach_daily_reflection_lambda.py`,
`coach_memoir_lambda.py`, `coach_panel_podcast_lambda.py`, `voice_fidelity_harness.py`) need
**no** change — they pick up the new coach for free once §4 is done. Prefer that pattern for any
new code.

### 5d. ⚠️ Per-coach *code*, not lists — the wrappers, wiring tuples, and display rows

Beyond the id lists, several files carry **one entry (or function) per coach** that you must add
by hand. None of these iterate the registry; all silently omit your coach if forgotten.

- **`lambdas/ai_calls.py`** — a thin per-coach entry wrapper `call_<coach>_coach_v2(data, profile,
  api_key)` (the existing 8 are `call_sleep_coach_v2` … `call_explorer_coach_v2`) plus the
  `_build_<domain>_data` builder it depends on. The pipeline *core* (`_run_coach_v2_pipeline`,
  `_enforce_quality_gate`) is coach-generic — but the wrapper + data builder are per-coach and
  **must** be added. (This is the one place §9's "you don't touch the gates" does not extend to.)
- **`lambdas/emails/daily_brief_lambda.py`** — add the `"<coach>_coach_v2_text": ""` default and
  the `("<short>", ai_calls.call_<coach>_coach_v2, "<Label>")` wiring tuple.
- **`lambdas/html_builder.py`** — add the `<coach>_coach_v2_text` parameter and the coach's
  display row, which **hard-codes the display name and hex color** (e.g. glucose `#2dd4bf`,
  explorer `#e879f9`). Keep the color equal to the persona's `color` in `personas.json`.
- **`lambdas/web/site_api_ai_lambda.py`** — add the coach's `{"name", "title", "lens"}` dict entry
  (and, if you renamed/aliased, `LEGACY_PERSONA_MAP`).

### 5e. Site render — mostly registry-driven, two exceptions

The `/coaching/` surface is fed by `lambdas/web/site_api_coach.py` (`handle_coaches` iterates the
operational personas — **no per-coach code**) and hydrated by `site/assets/js/coaching.js`
(fetches `/api/coaches`, derives domain by stripping `_coach`). Two things still need a hand:

- **`site/assets/js/coaching.js` → `OBS_DOMAINS`** — the set of domains that show an observatory
  panel. Add your domain **only if** it has observatory data (`/api/observatory_week`).
- **The static shell** — `site/coaching/**/index.html` is generated by
  **`scripts/v4_build_coaching.py`**. Per repo rule, if you touch the coaching HTML, change the
  generator and regenerate — do not hand-edit the shell (it drifts on the next build). The roster
  itself is hydrated at runtime from the API, so a new coach usually needs a regenerate-and-deploy,
  not a shell edit.

---

## 6. Cross-coach influence + domain routing

- **`config/coaches/influence_graph.json`** — directed `coach → coach` weights (read by
  `coach_narrative_orchestrator.py`, `inter_coach_dialogue_lambda.py`, `site_api_coach.py`
  `_relationships`, and `phase_taxonomy.py`). Add the new coach's outbound edges (and inbound
  edges from existing coaches where the relationship is real). Missing edges degrade gracefully,
  but the coach's "relationships" panel will be empty until you add them.
- **`coach_narrative_orchestrator.py` → `COACH_DOMAINS`** — the deterministic map from coach id to
  the site-protocol pillars it reacts to (`sleep`/`movement`/`nutrition`/`mental`/`metabolic`/…).
  Add your coach's domain(s) so it sees the right challenges/experiments and not others. (`None`
  = all, as `explorer_coach` uses.)

---

## 7. Podcast voice — `tts_voice`

Every operational coach + Elena Voss must have a **distinct, persistent** Google Chirp 3: HD voice
(`en-US-Chirp3-HD-*`), used by the coach-panel podcast. `test_podcast_voice_map_complete_and_unique`
and `test_lead_persona_nonoperational_with_distinct_voice` assert uniqueness. Pick a
`Chirp3-HD` voice not already taken by any coach, Elena, or Eli Marsh (grep `tts_voice` in
`config/personas.json`), gender-appropriate to the persona, and set it on the `personas.json`
entry (§3a).

---

## 8. Portrait (optional) — ADR-106, sigil-only by default

**The default for a new coach is sigil-only** — deterministic, free, on-brand
(`docs/design/PORTRAIT_RUNBOOK.md` §5). Everything renders through the fallback chain
`portrait(c) || sigil(c)` (`site/assets/js/portraits.js`), so an uncommissioned coach renders
correctly with **zero** portrait work.

If you want a commissioned portrait, it is a **hard gate — Matthew only** (ADR-106,
`docs/design/PORTRAIT_RUNBOOK.md`). Summary, do not shortcut:

1. **Ground in the persona doc** — one physical brief derived from the board block. AI may
   generate 6–10 **reference candidates** in a single pinned-style session; references live
   **outside the repo**, never checked in.
2. **Reverse-image sanity check** — no resemblance to a findable real person (ADR-040). A hit kills
   the candidate.
3. **Trace, don't embed** — winners are traced into the vector layer schema and hand-cleaned. The
   **recipe JSON is the only artifact**; the raster is discarded.
4. **Ship** the recipe to **`config/portraits/<board_persona_key>.json`** (note: keyed by
   `board_persona_key`, e.g. `cora_vance.json`, with a `persona_id` field == that key — **not** the
   `reading_coach` engine id). **Wire it to the coach id via the recipe's `aliases` array** — e.g.
   `amara_patel.json` carries `"aliases": ["glucose_coach", "rhonda_patrick"]`, which is how the
   `glucose_coach` page resolves to the `amara_patel` portrait. `scripts/v4_build_portraits.py`
   regenerates the bundled `portrait_data.js` (marked GENERATED — do not hand-edit).
5. **The contact-sheet gate** — all personas side-by-side, light + dark, at 40/56/96 px. Matthew
   approves the *sheet*, recorded in `_meta.sign_off` (no sign-off ⇒ validation fails ⇒ the recipe
   never renders). Then `tests/test_portrait_recipes.py` + `tests/visual_qa.py --screenshot --ai-qa`.

The one-sentence rule: **AI may sketch, only code ships, only Matthew approves.**

---

## 9. The AI gates — coach-generic, no change (but the *entry wrapper* in §5d is per-coach)

Adding a coach requires **no** change to the AI safety gates themselves — they operate per-coach
over whatever coach is passed in. (The one caveat is the `call_<coach>_coach_v2` entry wrapper +
`_build_<domain>_data` builder in `ai_calls.py`, which you *do* add — see §5d. The gate *logic* is
untouched.)

- **Coach quality gate (ADR-108)** — `ai_calls._enforce_quality_gate` (cross-coach distinctiveness
  + quality, regenerate-or-hold). Runs on each coach's generated narrative. A distinct voice spec
  (§5a) is how your coach *passes* it — two coaches that sound alike get flagged.
- **Grounded-generation gate (ADR-104)** — the number gate + `grounding_guard`, applied in the
  coach-v2 pipeline (`_run_coach_v2_pipeline`) and the stance engine. Automatic.
- **Prediction loop (ADR-055)** — `coach_prediction_evaluator.py` grades `PREDICTION#`/`LEARNING#`
  for every coach in its `COACH_IDS` (which you updated in §5c); credibility
  (`intelligence_common.compute_credibility`) then reads the track record. No new wiring.

Your job is to make the coach *have a distinct, grounded voice*; the gates do the rest.

---

## 10. Verify, then deploy (from main, by the operator)

### 10a. Tests — the registry test is the contract

```bash
python3 -m pytest tests/test_persona_registry.py -v      # the no-orphans contract
python3 -m pytest tests/test_coach_stance.py -v           # stance ladder + KNOWN_SIGNALS
python3 -m pytest tests/test_portrait_recipes.py -v       # only if you shipped a portrait
grep -rn "COACH_IDS\|ALL_COACH_IDS\|COACH_NAMES" lambdas/ mcp/  # eyeball every private list (§5c/§5d)
black lambdas/ mcp/ && flake8 lambdas/ mcp/               # never run black on .json
```

`test_persona_registry.py` is designed to **fail until every name-space and the registry agree**.
Green here means the four-name-space reconciliation holds. It does **not** cover the §5c private
lists — that's the grep's job.

### 10b. Deploy (post-merge, from `main`, by Matthew — never from a worktree)

1. **Sync config to S3** — the compute + site-api lambdas read config from S3:
   - `config/coaches/*_coach.json` (voice specs) + `influence_graph.json` are covered by
     `bash deploy/deploy_coach_intelligence.sh`.
   - **`config/personas.json` and `config/coaches/<coach>_stance.json` are NOT covered by that
     script's glob** — sync them explicitly:
     `aws s3 cp config/personas.json s3://matthew-life-platform/config/personas.json` and the same
     for the `_stance.json`. (Confirm against the current script before running — this is a known
     gap in the paved path.)
2. **Deploy the fleet** — the private coach-id lists ship inside every function bundle (#781, one
   bundle, no layer), so a coach-id change reaches the fleet via `bash deploy/deploy_fleet.sh` or
   `cd cdk && npx cdk deploy --all` (CI fleet-deploys automatically on unmapped `lambdas/`
   changes). Key functions: compute engine, prediction evaluator, narrative orchestrator, history
   summarizer, ensemble digest, coherence sentinel, between-chronicle, state-of-Matthew,
   coach-panel podcast, daily-brief (`ai_calls` wrappers + `html_builder` rows ride along), the
   **MCP** lambda (`mcp/tools_coach_intelligence.py`), **site-api-ai**, and **site-api**
   (`bash deploy/deploy_site_api.sh`).
3. **Portrait only:** the site auto-deploys on a `site/**` push (site-deploy.yml) after
   `v4_build_portraits.py` regenerates `portrait_data.js`.

### 10c. Post-deploy verification

- `curl https://averagejoematt.com/api/coach_analysis` → the new coach appears in the roster.
- Its coach page renders (sigil or portrait), track record + stance block populate over the first
  daily cycle.
- The coach-panel podcast voice map has no clash.

---

## Cross-links

- **`docs/BOARDS.md`** — the persona boards (⚠️ its Coach-Intelligence id list is *stale* — §1).
- **`docs/engines/COACH_STANCE.md`** — the STANCE# engine + the ADR-108 quality gate, in depth.
- **`docs/design/PORTRAIT_RUNBOOK.md`** — the portrait style bible + commissioning gate (§8).
- **`docs/coaching/READING_CALIBRATION.md`** §9 — Cora Vance's mandate & standing disagreements
  (PRIVATE-flagged coaching content).
- **ADRs:** ADR-040 (fictional advisors) · ADR-047 (coach intelligence: stateless→stateful) ·
  ADR-055 (prediction loop closure) · ADR-104 (grounded generation) · ADR-106 (coach portraits) ·
  ADR-108 (coach quality gate).
- **Source of truth for the id contract:** `config/personas.json`, `lambdas/persona_registry.py`,
  `tests/test_persona_registry.py`.
