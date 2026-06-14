# SPEC — Coaches-as-Characters + Story Rehoming + Footer (Claude Code build brief)

**Status:** Draft for review · **Date:** 2026-06-13 · **Owner:** Matthew
**Series:** `CC-00 … CC-08` (see `BACKLOG` section to merge) · **Realises:** PG-13 Phase 1 (surface the agents you already run), extended.
**Governing test:** *does this make Matthew more likely, or less likely, to reach 185?* Two-part answer:
- **Engagement / Wedge-B showcase** — surfacing the agents you already run (sanctioned, ~zero new build).
- **Adherence tool for Matthew (the stronger half).** The per-coach **stance** — "where I think you are right now, what I care most about *at this stage*, what I'm deliberately ignoring for now, and how it's honestly going" — is an anti-perfectionism mechanism (Maya's lane): it tells Matthew to do the *right* thing for the stage (show up; log food) instead of optimizing the wrong thing. The "care less right now" candor is a permission structure. This scores *better* than pure showcase, which is what lets the added richness through the build-cap honestly.

NOT net-new analytic engines. The stance ladder is **hand-authored config** (stable, cheap, safe); the dynamic "how it's going" rides the existing daily outputs (CC-07) or the one gated daily batch (CC-08). No new live AI endpoints.

**Wellbeing guardrail (non-negotiable, applies to the nutrition stance especially):** concern-watches (e.g. under-eating / binge patterns) are framed **supportively, correlatively, never prescriptively**. Do **not** publish a hard aggressive numeric target (e.g. a fixed "3 lb/week" mandate) as a coach goal; the *rate* defers to the existing `get_deficit_sustainability` monitoring, and the public stance leads with "log first, consistency over precision." Personal-board Marcus + Maya + Henning guard this content. Down-weeks always visible.

---

## 0. How to work this (deploy discipline — do not skip)

Same rules as a PG item:

1. **Open:** read `handovers/HANDOVER_LATEST.md` then `CLAUDE.md`; confirm `main` is pushed/clean before starting.
2. **One layer per session** where possible. Confirm a layer's gate is met before touching code. **CC-00 is a hard gate on everything else.**
3. **Deploy discipline (unchanged):** Matthew runs all deploys in terminal — never via MCP. Site: per-file `aws s3 cp` (NEVER `--delete` at bucket root) + CloudFront invalidation (`E3S424OXQZ8NBE`) always follows. Lambda: full `web/` package, never single-file (ADR-046); 10s between sequential Lambda deploys. MCP: run `pytest tests/test_mcp_registry.py -v` before deploy; tool functions go BEFORE the `TOOLS={}` dict. Layer modules (`ai_calls.py`, `html_builder.py`, etc.) require a layer rebuild + `SHARED_LAYER_VERSION` bump.
4. **Public AI rule (Anika/Dana) — applies to CC-08 only:** any reader-facing AI text must (a) keep the LLM strictly interpretive — math in Python, LLM narrates only, correlative + confidence-labelled (Henning standard); (b) be **generated once on the daily batch and cached** — never live-inferenced on page view; (c) ride the existing per-IP rate limits + budget-tier degrade (PG-10). One traffic spike must not empty the $75 ceiling.
5. **Editorial guardrails (all public surfaces):** no employer/role/industry; partner never named; only alcohol + food-delivery vice categories named publicly; bereavement opt-in only; correlative framing; down-weeks always visible.
6. **Truthfulness gate (ER-03):** every coach-authored public string passes the offline content gate — no banned causal connectives on correlations, confidence labels when N<30 / "preliminary" <12, **every output number present in the input** (anti-fabrication), no "Matthew"-prefixed output, no LLM arithmetic.
7. **Close:** update `CHANGELOG.md` + `PROJECT_PLAN.md` always; `python3 deploy/sync_doc_metadata.py --apply` if counts changed; write handover + update `HANDOVER_LATEST.md`; `git add -A && git commit && git push`. Move finished CC items from `BACKLOG.md` to `CHANGELOG.md`.

---

## 1. THE ONE GATING DECISION — confirm before CC-01 (CC-00)

There are three overlapping coach name-spaces today and they do not align:

| Name-space | Source | Members |
|---|---|---|
| Coach configs | `config/coaches/*.json` | `sleep, mind, training, nutrition, physical, glucose, labs, explorer` |
| Computation engine | `coach_computation_engine.py:COACH_IDS` | `dr_johansson, fitness_coach, nutrition_coach, mind_coach, sleep_coach, body_comp_coach, lifestyle_coach, recovery_coach` |
| Personal Board personas | `config/board_of_directors.json` | 20 personas (Sarah Chen, Victor Reyes, Marcus Webb, … + Henning, Elena, the Chair, Murthy — many of whom are NOT daily coaches) |

Only ~3 of 8 engine ids match the config ids (`nutrition/mind/sleep`); `training` vs `fitness`, `physical` vs `body_comp`, and `glucose/labs/explorer` vs `lifestyle/recovery/dr_johansson` diverge. The config `display_name`s ("Dr. Sarah Chen") also overlap with Board personas.

**Recommended model (default in this spec — CONFIRM or override):** **distinct-but-linked via a single canonical persona registry.**

- One registry, keyed by `persona_id`. Each persona: `{ persona_id, name, type: board|coach|both|narrator|meta, domain, short_bio, voice_spec_ref, coach_id?, engine_id?, board_role? }`.
- A persona can wear two hats: e.g. **Dr. Sarah Chen** is both the Board's Sports Scientist *and* the operational training/fitness coach. The registry links them; the public page shows both roles.
- **The public "Coaches" roster = the subset of personas with an operational `coach_id` + daily outputs** (the 8 with `COACH#` memory, predictions, influence-graph edges). The broader Board (Henning, Elena, the Chair, Murthy, etc.) stays on the existing `/evidence/board/` surface, cross-linked.
- The registry reconciles `config coach key ↔ engine COACH_ID ↔ board persona` once, in one file, consumed by **both** the engine and the site. This is what makes a coach's byline provably the coach who authored the data.

**Why this and not "they are the same objects":** the Board is a 20-persona advisory panel; most aren't daily coaches. Collapsing them loses that distinction and forces non-coach personas (a biostatistician, a journalist) into a "daily coach" frame they don't fit. Distinct-but-linked keeps both surfaces honest and is the smaller, cleaner data model.

> **DECISION REQUIRED FROM MATTHEW:** confirm "distinct-but-linked registry" (default), or choose "coaches ARE the board personas." Everything below assumes the default; the alternative mainly collapses §3's registry into `board_of_directors.json` and drops the `type` discriminator.

---

## 2. Architecture overview & build order

```
CC-00  Canonical persona registry  ........  GATE (config + reconcile; no UI)
   │
CC-09  Coach STANCE / stage playbook  .......  hand-authored config — the "where you are / care-most / care-less / how it's going" content backbone
   │
CC-01  The Coaches: roster + per-coach pages  (surface; ~zero new inference)
   ├── CC-02  Coach Report Card (grading: right/wrong, effectiveness, tuning log)
   ├── stance section on the coach page (current rung + plan + honest progress)  [from CC-09]
   ├── relationship graph viz (influence_graph)                                   [folds into CC-01]
   └── honesty/disclosure + ER-05 self-grade caveat                              [folds into CC-01/02]
CC-10  "My Team" personal page + tension map (get_coach_disagreements) — the page that's for YOU
CC-03  coach_tuning_log structure + backfill + change-discipline test
CC-05  Footer mega-menu restore  (Layer 4 — discoverability for everything below)
CC-06  Rehome orphaned story pages  (per-page verdicts; live in the footer)
CC-04  Clickable coach-name popover  (Layer 2 — wired across surfaces)
CC-07  Coach daily-journey timeline — surface EXISTING daily outputs (Layer 3a)
CC-08  Coach daily reflection BATCH — new inference, daily-batch, gated (Layer 3b)
```

Recommended sequence: **CC-00 → CC-09 → CC-03 → CC-01(+CC-02) → CC-10 → CC-05 → CC-06 → CC-04 → CC-07 → CC-08.** CC-09 (stance config) lands early — it's the hand-authored content backbone for both the coach pages and the My Team page, cheap and unblocking. CC-03 before CC-01 so the report card has its tuning-log source ready.

---

## 3. Data model / database

### 3.1 NEW — Canonical persona registry (CC-00)
`config/personas.json` (new; or a `personas` block appended to `board_of_directors.json` if the "same objects" fork is chosen).

```jsonc
{
  "version": "1",
  "personas": {
    "sarah_chen": {
      "name": "Dr. Sarah Chen",
      "type": "both",                 // board | coach | both | narrator | meta
      "domain": "exercise_physiology",
      "short_bio": "Sports scientist; periodization, recovery, ACWR.",
      "voice_spec_ref": "config/coaches/training_coach.json",
      "coach_config_key": "training_coach",
      "engine_id": "fitness_coach",   // the COACH_ID this persona authors as
      "board_role": "Sports Scientist"
    }
    // … 7 more operational coaches + the non-coach board personas (type:board)
  }
}
```
- **Single source of truth.** `coach_computation_engine.py` and the site both resolve coach identity through this file. Add `tests/test_persona_registry.py`: every `engine_id` in `COACH_IDS` resolves to exactly one persona; every `config/coaches/*.json` key maps; no orphans either direction.

### 3.2 EXISTING — read paths (no schema change)
- **Right/wrong + hit-rate:** `PREDICTION#` / `LEARNING#` partitions (per coach), via the same logic behind `get_coach_track_record` / `get_predictions`. D-05 validates the loop ~2026-06-17 — pages will be honestly thin before that (show "accruing" empty-states, CC-10).
- **Effectiveness/quality:** `coach_quality_gate` scores (per output; `PASS_SCORE_THRESHOLD=60`, advisory). Surface the trend, **labelled self-assessment** (ER-05).
- **Recent real outputs / daily journey source:** `COACH#<engine_id>` episodic memory + the daily-brief coach sections; cross-coach summary under `ENSEMBLE#`.
- **Relationships:** `config/coaches/influence_graph.json` (directed weights).
- **Voice/personality:** `config/coaches/*.json` (`structural_voice_rules`, `few_shot_examples`, `decision_style`).

### 3.3 NEW — Coach tuning changelog (CC-03)
`config/coaches/tuning_log.json` — append-only, operator-curated, git-versioned (git history IS the audit trail; the file is the human-readable surface).

```jsonc
{
  "entries": [
    {
      "date": "2026-05-25",
      "coach": "training_coach",
      "change_type": "prompt",        // prompt | voice | persona | few_shot | model
      "summary": "Stopped outputs opening with 'Matthew' (prompt instruction was being ignored).",
      "rationale": "ai_validator flagged drift; broke the in-voice opening rule.",
      "ref": "BACKLOG: training coach prompt drift; commit <sha>",
      "observed_effect": null         // fill in later when measurable
    }
  ]
}
```
- **Backfill** seed entries from git history + ADRs + BACKLOG (real examples already exist: the "Matthew"-prefix drift; quality-gate threshold decisions; few-shot additions).
- **Change-discipline test (CC-03):** `tests/test_coach_tuning_logged.py` — any diff to a `config/coaches/*.json` `structural_voice_rules`/`few_shot_examples` block, or to a coach prompt in `ai_calls.py`, must be accompanied by a new `tuning_log` entry whose `date` ≥ the prior tip. This keeps the changelog self-maintaining. (Implement as a pytest that diffs against `origin/main`, or a pre-commit hook.)

### 3.4 NEW — Daily coach commentary artifact (CC-08, gated)
`generated/coach_daily.json` (daily-batch output; public-readable; the `generated/` prefix is already PII-guarded by ER-06). One short per-coach reflection per day, cached. **Never** written per page view.

### 3.5 NEW — Coach stance / stage playbook (CC-09) — the content you asked for
`config/coaches/<coach>_stance.json` (new; or a `stance` block in each coach config). **Hand-authored** — this is the coach's *philosophy and stage priorities*, not a data claim, so it's cheap, stable, and safe. It's the structure behind "weighing in at 300, I just care that he shows up."

```jsonc
{
  "coach": "training_coach",
  "stage_ladder": [
    {
      "stage_id": "foundation",
      "entry": { "weight_gte": 270 },                 // resolves the CURRENT rung from real weight/phase
      "headline": "Just get to the gym.",
      "read_of_him": "At ~300 lb, the win is showing up at all. Everything else is noise right now.",
      "cares_most": ["consistency — 3 sessions/week", "slow cardio at high body weight", "light resistance, low joint risk"],
      "cares_less_right_now": ["program optimization", "intensity / RPE", "PRs", "the specific 'what'"],
      "plan": "Slow steady cardio + basic resistance; protect joints at high load; build the habit before the stimulus.",
      "graduation_gate": "3 sessions/week for 3 consecutive weeks → unlocks the 'build' rung",
      "watches": ["session_frequency", "joint_discomfort_flags"]
    },
    {
      "stage_id": "build",
      "entry": { "weight_lt": 270, "weight_gte": 240 },
      "headline": "Now we add a little structure.",
      "read_of_him": "Habit is there; body can take more.",
      "cares_most": ["progressive resistance", "Zone 2 volume"],
      "cares_less_right_now": ["max intensity", "advanced periodization"],
      "plan": "Introduce light periodization; keep cardio base.",
      "graduation_gate": "consistent progressive overload for 4 weeks → 'develop' rung",
      "watches": ["ACWR", "load_progression"]
    }
    // … further rungs, hand-authored per coach
  ]
}
```

**Nutrition stance — wellbeing-guarded example** (note how it leads with logging + consistency, holds concern-watches supportively, and does NOT hard-code an aggressive rate — the rate defers to `get_deficit_sustainability`):
```jsonc
{
  "coach": "nutrition_coach",
  "stage_ladder": [
    {
      "stage_id": "visibility",
      "entry": { "logging_consistency_lt": 0.6 },
      "headline": "First, I just need to see what you eat.",
      "read_of_him": "I can't coach what I can't see. Right now the only job is logging.",
      "cares_most": ["log food most days", "honest entries, not perfect ones"],
      "cares_less_right_now": ["macro precision", "hitting an exact deficit"],
      "concern_watches": ["very-low-intake days", "long gaps then large swings"],  // supportive framing only; surfaced as a gentle watch, never a restrictive instruction
      "plan": "Build the logging habit. Once we can see the pattern, we tune toward a sustainable, protein-forward deficit — pace set by the deficit-sustainability monitor, not a fixed number.",
      "graduation_gate": "logging ≥ 6/7 days for 2 weeks → 'tune' rung",
      "watches": ["logging_consistency"]
    }
    // 'tune' rung: protein-forward sustainable deficit, rate governed by get_deficit_sustainability; down-weeks visible
  ]
}
```

- **"Current stance" = resolve the active rung** from today's real weight/phase + the computed `watches` adherence facts. The *ladder* is config (stable); the *which-rung* and *how-it's-going* are computed at render/batch time. No new inference for the rung resolution — that's Python over existing data.
- A coach config validator (extend `test_persona_registry.py` or a sibling) checks every coach has a `stage_ladder`, bands are contiguous/non-overlapping, and `watches` reference real computable signals.

---

## 4. Configuration changes

- `config/personas.json` (CC-00) — new canonical registry.
- `config/coaches/<coach>_stance.json` (CC-09) — new, hand-authored stage ladders (the stance content). Wellbeing-guarded for nutrition.
- `config/coaches/tuning_log.json` (CC-03) — new, backfilled.
- No change to `influence_graph.json` or the per-coach voice configs (read-only surfacing).
- `redirects.map` / `sitemap.xml` / footer config updated for rehomed pages (CC-05/06).

---

## 5. Backend / API

New read-only endpoints in the `site-api` family (full `web/` package deploy; shaped-empty 200s on no data, never 503 — match S-01 pattern):

- `GET /api/coaches` → roster: `[{persona_id, name, domain, short_bio, headline_stat}]` resolved from the registry.
- `GET /api/coach/{persona_id}` → bio + `voice_spec` (curated subset of the config: humor, analogy domain, signature moves, relationship summary), `relationships` (influence_graph edges in/out), `report_card` (CC-02: hit-rate w/ N + confidence band, recent confirmed & refuted predictions, quality-gate trend labelled self-assessment, tuning_log entries), `recent_outputs` (from `COACH#`), and `daily` (from `coach_daily.json` once CC-08 ships).
- **Hardening:** reuse PG-10 (per-IP rate limit, tier-≥2 graceful 200 degrade, token caps, reserved concurrency). These endpoints are **read-only over pre-computed data** — no inference at request time, so they're cheap and safe by construction. CC-08's batch is the only writer that calls a model.

---

## 6. Prompts / personality changes

- **CC-07 (surface existing):** no prompt change. May need a small metadata tweak so each daily coach output is tagged with its `engine_id` for clean per-coach timeline attribution.
- **CC-08 (new, gated):** a per-coach **"daily reflection" prompt template** — input = that coach's slice of the day's/week's computed metrics; output = ≤120 words in the coach's voice (loads `structural_voice_rules` + 1–2 `few_shot_examples`), correlative-only, confidence-labelled, **no fabricated numbers, no LLM arithmetic** (ER-03). Runs in the existing daily batch, writes `coach_daily.json`, self-skips at budget tier ≥2.
- **Process change (CC-03):** every future coach prompt/voice edit appends a `tuning_log` entry (enforced by the discipline test). This is a workflow rule, not a prompt edit.

---

## 7. UI/UX flow (web design)

**New first-class Story section: "The Coaches"** (`/story/coaches/`), added as a section in `dispatches.js` `SECTIONS` and surfaced in nav + the new footer. (The old `/coaches/` was only a `<meta refresh>` redirect into the platform page — there is no rich page to restore; this is the destination the data always deserved.)

### 7.1 Roster (`/story/coaches/`)
Grid of 8 coach cards: persona name, domain, a one-line voice tell ("talks in periodization and compound interest"), a headline stat (hit-rate w/ N, or "accruing"), and an **AI-character marker** (small, honest: "AI persona · reads real data"). Cards link to the coach page.

### 7.2 Per-coach page anatomy (`/story/coaches/{id}/`)
1. **Header** — persona name, domain, board role if `type:both`, and the load-bearing disclosure: *"An AI character. Reads Matthew's real data; speaks in its own voice; correlative, never causal."*
2. **STANCE — "Where I think you are · What I'm focused on · How it's going" (CC-09) — lead with this.** This is the part that makes it feel like *your team*. Driven by the resolved current rung of the stance ladder + computed adherence facts + voice:
   - *Where I think you are:* the current rung's `read_of_him` — e.g. *"At ~300 lb, the win is showing up at all. Everything else is noise right now."*
   - *What I care most about right now / and what I'm deliberately ignoring:* `cares_most` vs `cares_less_right_now`, stated plainly. The "care less" candor is the anti-perfectionism feature — surface it as a feature, not fine print.
   - *The plan + what graduates you:* `plan` + `graduation_gate` — "do X for Y and we unlock the next focus." The coaching visibly levels up with him.
   - *How it's going, honestly:* the rung's `watches` rendered as computed adherence facts (gym frequency, logging streak…) + the coach's voice read. Down-weeks shown. A coach saying "so far, not yet — you've logged 2 of the last 7 days, and that's the whole job right now" is the honest, trust-building version. (CC-07 surfaces existing brief output here; CC-08 narrates it fresh daily.)
3. **Voice signature** — humor style, analogy domain, signature moves, a real `few_shot_example` as a sample. (Straight from config.)
4. **Relationships** — influence_graph viz: who this coach leans on / who leans on them (e.g. "Dr. Chen leans hardest on the sleep coach, 0.7 → 0.9"). Small directed-graph or ranked chips.
5. **THE REPORT CARD (CC-02)** — the keystone:
   - *Right / wrong:* recent **confirmed** predictions next to recent **refuted** ones, each with the actual outcome. Misses shown, not hidden.
   - *Hit-rate:* confirmed / (confirmed + refuted), **with N and a confidence band** (Henning). Below ~N=12: "preliminary."
   - *Effectiveness:* quality-gate score trend, **explicitly labelled "self-assessment, not external validation"** (ER-05). No single vanity number.
   - *Tuning changelog:* the `tuning_log` for this coach — "here's how this coach's prompt/voice changed, when, why, and whether it helped." Build-in-public gold; the honesty engine.
6. **Recent outputs** — this coach's recent real commentary (from `COACH#`).
7. **The daily journey** (CC-07/08) — reverse-chron timeline: today / this week / the arc. CC-07 surfaces existing outputs; CC-08 adds the daily cached reflection.

### 7.3 Clickable coach-name popover (CC-04, Layer 2)
One reusable component. Anywhere a coach is named — chronicle, AI lab notes, evidence pillars, the brief — the name becomes a chip → popover (persona + domain + one-line voice + "full page →"). Progressive disclosure (Mara): popover for the glance, page for the depth. Don't stamp it on every paragraph — name's first mention per section.

### 7.4 Footer mega-menu (CC-05, Layer 4)
Real footer nav across all three doors (`cockpit/story/evidence`), replacing the current minimal "← home". Columns: **The Story** (chronicle, lab notes, in my own words, timeline, about, **the coaches**), **The Evidence** (top topics), **The Cockpit**, **Context** (start, mission, methodology, privacy). This is where rehomed pages (CC-06) become discoverable.

### 7.5 Honesty treatment — woven through, not a page
Every coach surface wears the AI-persona marker; the report card always shows misses; rates always carry N + confidence; quality score always carries the self-assessment caveat. This is what makes vivid personalities safe (Lena/Henning).

### 7.6 "My Team" — the page that's for YOU (CC-10)
A personal aggregate view (lead of `/story/coaches/`, or its own `/story/coaches/` landing above the roster). This is the "my team" feeling Matthew asked for — *not* a per-coach page but the **team's collective read on him right now**:

- **The team's focus this stage** — one synthesized line: what the whole team is collectively prioritising for him at the current stage (derived from each coach's resolved `cares_most`). E.g. *"Right now the team agrees on two things: show up, and log food. Everything else waits."*
- **Each coach's current stance, one line** — name → their resolved `headline` + `read_of_him`, as a scannable team huddle. Click → full coach page.
- **The tension map** — where the team **disagrees** right now, from `get_coach_disagreements`. E.g. *"Your training coach wants more volume; your recovery coach wants you to back off this week."* This is the realest "team" signal there is, and it's honest — the disagreements already exist in the data. (Sofia: most shareable; Raj: most useful to Matthew — he sees the live tradeoff.)
- **What each coach is watching on you this week** — one `watches` metric per coach, glanceable (Mara's "north star per coach", prevents a wall of text).
- **Matthew's specifics** — current stage/rung across coaches, the single next graduation gate that's closest, and (optionally) a link into the cockpit `/now/` for the live numbers.

Data: all from CC-09 (stance) + `get_coach_disagreements` (exists) + computed `watches`. No new inference. CC-08's daily reflections, once live, give each huddle line a fresh daily voice.

---

## 8. Rehome the orphaned story pages (CC-06)

Per-page verdict (confirm each against the live file before acting — these are tree-level inferences):

| Legacy page | Verdict (proposed) |
|---|---|
| `/start/` | **Rehome** — the segment router (skeptic→methodology, builder→build log, midlife→chronicle). High conversion value (Jordan). |
| `/mission/` | **Rehome or fold** into Story › About. Confirm it isn't already the About tab's content. |
| `/first-person/` | **Already folded** → "AI lab notes" (the Third Wall). Verify, then 301. |
| `/elena/` | **Fold** into the Coaches/Story cast (Elena = narrator persona). |
| `/builders/`, `/community/`, `/accountability/`, `/progress/` | **Likely defer** — audience-dependent rooms that are worse empty (Mara). Decide explicitly; 301 to the nearest live home or keep noindex in `/legacy/`. |

Every rehome: 301 the old URL, update `sitemap.xml` + footer, no unintended 404s (migration-map DoD).

---

## 9. Acceptance criteria (per layer)

- **CC-00:** `test_persona_registry.py` green — every `COACH_ID` and every `config/coaches/*` key resolves to exactly one persona; no orphans. Engine + site both read the registry.
- **CC-01:** roster + 8 coach pages render from config with no hardcoded persona data; `tests/visual_qa.py` extended to cover roster + ≥2 coach pages, all PASS; shaped-empty 200s pre-D-05.
- **CC-02:** report card shows confirmed AND refuted predictions with N + confidence; quality score carries the self-assessment caveat; tuning log renders.
- **CC-03:** `tuning_log.json` backfilled from history; `test_coach_tuning_logged.py` fails a voice/prompt diff that lacks a log entry.
- **CC-04:** popover opens from a coach name in ≥3 surfaces; keyboard-accessible; no CLS regression (<0.1).
- **CC-05:** footer renders on all three doors; all links 200; smoke test green.
- **CC-06:** every rehomed URL 301s; post-cutover crawl returns no unintended 404s.
- **CC-07:** per-coach timeline renders real existing outputs; honest empty-state when thin.
- **CC-08:** `coach_daily.json` produced by the daily batch only; endpoint serves cached text; ER-03 content gate green on seeded fabricated-number / causal / unlabelled-N inputs; self-skips at tier ≥2 (never 5xx); never live-inferenced on page view.
- **CC-09:** every coach has a hand-authored `stage_ladder` with contiguous non-overlapping bands and `watches` that reference real computable signals (validator green); the coach page resolves the correct current rung from real weight/phase and renders `read_of_him` / `cares_most` / `cares_less_right_now` / `plan` / `graduation_gate` / honest progress; nutrition stance leads with logging + consistency and hard-codes no aggressive rate (rate deferred to `get_deficit_sustainability`); concern-watches render supportively (wellbeing-guard review passed).
- **CC-10:** "My Team" view renders the team's stage focus, each coach's one-line stance, the tension map from `get_coach_disagreements`, and one watch metric per coach; no new inference; honest empty-states pre-D-05.

---

## 10. Out of scope / build-cap guards

- **No new live AI endpoints.** CC-08 is a daily batch + cache, full stop.
- **No new analytic engines.** Report card = surfacing existing predictions + quality scores + one new operator-curated log.
- **No persona inflation.** 8 operational coaches; the broader Board stays on `/evidence/board/`, cross-linked. New coaches (PG-13 Phase 2 Scout/Adversary/Curator) are a separate, later, cost-gated decision — not in this spec.
- **Adversarial note (Reeves/Viktor):** the temptation here is to let "coaches on a journey" balloon into per-page live commentary and a growing cast. Held: CC-01..07 are surfacing; CC-08 is one contained daily artifact. If a session starts spawning new agents or live endpoints, stop — that's the itch, not this spec.

---

## 11. Board sign-off summary (for the record)

- **Maya (the reframe that matters):** the stance layer — especially the explicit "what I care *less* about right now" — is an anti-perfectionism adherence tool. It tells Matthew to do the right thing for the stage instead of over-optimizing. This is the half that actually moves 185, not just engagement.
- **Raj:** premium engagement loop + the cleanest enterprise-AI / Wedge-B showcase you have. The stage-ladder ("the coaching levels up as he does") and the tension map are the hooks. Ship CC-09/01/10/02/04.
- **Sofia:** the tension map ("my team doesn't always agree on me"), the report card, and the public tuning log are the shareable differentiators.
- **Reeves / Viktor:** acceptable *because* the stance ladder is hand-authored config and most of this is surfacing. CC-08 is still the line — daily-batch only, no cast growth. Don't let "how it's going" drift into live per-page inference.
- **Lena / Henning:** vivid is safe *only* with misses shown, N + confidence on every rate, the quality score labelled self-assessment (ER-05), and the "how it's going" read grounded in computed adherence facts (down-weeks visible), not vibes.
- **Marcus + Lena (wellbeing guard on nutrition):** concern-watches stay supportive and correlative; no published aggressive numeric target; rate governed by `get_deficit_sustainability`; lead with "log first." This is the one content area to review by hand before it ships.
- **Mara:** popover + progressive disclosure; one watch-metric per coach on the My Team huddle; footer for discoverability; don't clutter.
- **Dana / Anika:** read-only over pre-computed data is cheap by construction; CC-08 rides PG-10 + ER-03 or it doesn't ship.
