## 🎭 Coaches-as-Characters (CC-series) — 2026-06-13

**Source:** Product Board working session, 2026-06-13. **Full spec (architecture/DB/config/UI-UX/prompts/acceptance):** `docs/specs/SPEC_COACHES_AS_CHARACTERS_2026-06-13.md`.
**Realises:** PG-13 Phase 1 (surface the agents you already run), extended with a per-coach **report card** (right/wrong, effectiveness, tuning changelog) and a per-coach **stance** ("where I think you are / what I care most about / what I'm ignoring for now / how it's going").
**Governing test:** two halves — (1) engagement / Wedge-B showcase (surfacing, ~zero build), and (2) **the stronger half: an adherence tool for Matthew.** The stance's "care less right now" candor is an anti-perfectionism mechanism (Maya) — it scores better than pure showcase, which is what lets the richness through the build-cap. The only new-inference item (CC-08) is a once-daily cached batch behind PG-10 + ER-03. No new live AI endpoints; no new analytic engines; no cast growth.
**Wellbeing guardrail (nutrition stance):** concern-watches supportive/correlative only; NO published aggressive numeric target; rate deferred to `get_deficit_sustainability`; lead with "log first." Hand-review before ship (Marcus/Maya/Henning).
**Build order:** CC-00 → CC-09 → CC-03 → CC-01(+02) → CC-10 → CC-05 → CC-06 → CC-04 → CC-07 → CC-08.

### CC-00 — Canonical persona registry (GATE) · Effort S–M
- **Why:** three divergent coach name-spaces (`config/coaches/*` keys vs `coach_computation_engine.COACH_IDS` vs `board_of_directors.json` personas) — only ~3/8 align (`training` vs `fitness`, `physical` vs `body_comp`, `glucose/labs/explorer` vs `lifestyle/recovery/dr_johansson`). A coach's public byline must provably be the coach that authored the data.
- **Action:** new `config/personas.json` keyed by `persona_id` (`type: board|coach|both|narrator|meta`, `domain`, `short_bio`, `coach_config_key`, `engine_id`, `board_role`); reconcile all three; engine + site both resolve identity through it. `tests/test_persona_registry.py` (no orphans either direction).
- **Gate:** 🔴 **Matthew decision** — confirm "distinct-but-linked registry" (spec default: public coaches = the 8 with an operational `coach_id`; broader Board stays on `/evidence/board/`) vs "coaches ARE the board personas." Blocks all CC items.

### CC-01 — The Coaches: roster + per-coach pages (surfacing) · Effort M
- New first-class Story section `/story/coaches/` (added to `dispatches.js SECTIONS`). Roster grid → per-coach page: persona, voice signature (humor/analogy/signature-moves + a real `few_shot_example`), relationship graph (`influence_graph.json`), recent real outputs (`COACH#`), AI-character disclosure. Pure surfacing from existing config/memory — no new inference. **Note:** old `/coaches/` was a `<meta refresh>` redirect, not a page — this is net-new (the destination the data deserved).
- **Acceptance:** 8 pages render from config, zero hardcoded persona data; `visual_qa` extended (roster + ≥2 coach pages); shaped-empty 200s pre-D-05. **Gate:** CC-00.

### CC-02 — Coach Report Card (grading mechanism) · Effort M
- The keystone, folds into the coach page: **right/wrong** (recent confirmed vs refuted predictions w/ outcomes, from `PREDICTION#`/`LEARNING#`), **hit-rate** (with N + confidence band, Henning; "preliminary" <N≈12), **effectiveness** (`coach_quality_gate` trend, labelled "self-assessment, not external validation" per ER-05), **tuning changelog** (CC-03). ~90% surfacing existing signals.
- **Acceptance:** misses shown alongside hits; rates carry N + confidence; quality score carries self-assessment caveat. **Gate:** CC-01 + CC-03.

### CC-09 — Coach stance / stage playbook (the "where you are / care-most / care-less / how it's going" content) · Effort M
- **Why:** the feature that makes it feel like *your team* and the strongest adherence lever. Each coach gets a hand-authored **stage ladder**: per weight/phase band → `read_of_him`, `cares_most`, `cares_less_right_now` (the anti-perfectionism candor), `plan`, `graduation_gate`, `watches`. The *ladder* is config (stable, cheap, safe); the *current rung* resolves from real weight, and *how-it's-going* renders from computed adherence facts + voice. No new inference.
- **Action:** new `config/coaches/<coach>_stance.json` per coach (backfill all 8); validator (contiguous non-overlapping bands; `watches` reference real signals); render the stance section as the **lead** of the coach page. **Nutrition stance wellbeing-guarded** (see header).
- **Acceptance:** correct rung resolves from real weight/phase; stance section renders; nutrition stance hard-codes no aggressive rate; concern-watches supportive. **Gate:** CC-00.

### CC-10 — "My Team" personal page + tension map · Effort M
- **Why:** the page that's *for Matthew* — the team's collective read on him right now, not a per-coach page. The "my team" feeling.
- **Action:** lead view at `/story/coaches/` (above the roster): team's stage focus (synthesized from each coach's `cares_most`), each coach's one-line current stance (huddle), the **tension map** of live disagreements from `get_coach_disagreements` ("training wants volume, recovery wants rest"), one `watches` metric per coach, and Matthew's current rung + closest graduation gate. All from CC-09 + existing `get_coach_disagreements`; no new inference.
- **Acceptance:** renders focus + huddle + tension map + per-coach watch; honest empty-states pre-D-05. **Gate:** CC-09 + CC-01.

### CC-03 — Coach tuning changelog + change-discipline · Effort S–M
- New `config/coaches/tuning_log.json` (append-only, git-versioned): `{date, coach, change_type, summary, rationale, ref, observed_effect}`. **Backfill** from git history / ADRs / BACKLOG (real seeds exist: the "Matthew"-prefix prompt drift; quality-gate threshold decisions). `tests/test_coach_tuning_logged.py`: any diff to a `config/coaches/*` voice block or a coach prompt in `ai_calls.py` requires a matching new log entry.
- **Acceptance:** backfilled; the test fails an unlogged voice/prompt diff. **Gate:** none (do before CC-02).

### CC-04 — Clickable coach-name popover (Layer 2) · Effort S–M
- One reusable component; coach names across chronicle / AI lab notes / evidence pillars / brief → popover (persona + one-line voice + "full page →"). Progressive disclosure; first mention per section only.
- **Acceptance:** opens in ≥3 surfaces; keyboard-accessible; no CLS regression. **Gate:** CC-01.

### CC-05 — Footer mega-menu restore (Layer 4) · Effort S
- Real footer nav across all three doors (replaces minimal "← home"): Story (incl. the Coaches), Evidence, Cockpit, Context (start/mission/methodology/privacy). The discoverability home for rehomed pages.
- **Acceptance:** renders on all doors; all links 200; smoke green. **Gate:** none.

### CC-06 — Rehome orphaned story pages · Effort M
- Per-page verdict + 301: `/start/` **rehome** (segment router — conversion value); `/mission/` rehome-or-fold into About; `/first-person/` verify→folded into AI lab notes; `/elena/` fold into the cast; `/builders//community//accountability//progress/` **likely defer** (worse empty — explicit decision each). Update `sitemap.xml` + footer; no unintended 404s (migration-map DoD).
- **Acceptance:** each rehomed URL 301s; post-cutover crawl clean. **Gate:** confirm each verdict against the live file.

### CC-07 — Coach daily-journey timeline: surface existing (Layer 3a) · Effort S–M
- Per-coach reverse-chron timeline (today/week/arc) from the daily-brief coach sections + `COACH#` memory. May need a metadata tweak to tag each daily output with its `engine_id` for attribution. No new inference.
- **Acceptance:** renders real outputs; honest empty-state when thin. **Gate:** CC-01.

### CC-08 — Coach daily reflection batch (Layer 3b) · Effort M · GATED
- The one new-inference item: a per-coach ≤120-word daily reflection in the coach's voice, generated **once on the daily batch**, written to `generated/coach_daily.json` (PII-guarded prefix), surfaced on coach pages + popover teasers. **Never live-inferenced on page view.** Correlative-only, confidence-labelled, no fabricated numbers, no LLM math (ER-03); self-skips at budget tier ≥2 (PG-10).
- **Acceptance:** batch-only writer; endpoint serves cached text; ER-03 gate green on seeded fabricated-number/causal/unlabelled-N inputs; tier-≥2 self-skip (no 5xx). **Gate:** CC-01 + PG-10 (done) + ER-03 Layer 1.
