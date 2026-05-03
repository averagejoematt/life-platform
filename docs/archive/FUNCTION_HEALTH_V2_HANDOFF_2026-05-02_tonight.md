# Function Health v2 — Site Updates, Supplements Page, MCP Tools

**Spec status:** Ready for Claude Code execution
**Source handover:** `handovers/HANDOVER_v6.8.1.md` ("Deferred Work" section)
**Trigger draw:** 2026-04-03 (8th draw, 153 biomarkers, 26 OOR)
**Headline finding driving this work:** Cardio IQ Insulin Resistance Score 75 (>66 cutoff = insulin resistant)

---

## Goal

The 2026-04-03 Function Health draw introduces four new data categories that the existing labs surface doesn't render: **Allergies, NfL, Galleri, Cardio IQ**. The Cardio IQ panel alone added 15 biomarkers including the headline IRS score. The labs page currently renders 7 historical draws under a v1 schema; we need v2 panels, plus the matching MCP intelligence layer and a supplements page.

Three workstreams in this spec, ordered by dependency:

1. **MCP tool additions** — adds the data primitives the site will consume
2. **Site updates (`site/labs/index.html`)** — renders the new panels
3. **Supplements page** — separate page, less coupled, can ship in parallel

Out of scope for this spec (handled elsewhere): TD-19 partition fix, free-text clinician notes ingestion (PDF surfaced as download only for now), board consults (Matthew's call separately).

---

## Workstream 1: MCP tool additions

### 1.1 `get_lab_deltas` — cross-draw movement query

**Purpose:** With 8 draws now, "show me everything that moved more than Nx year-over-year" becomes useful.

**Signature:**
```python
get_lab_deltas(
    comparison: str = "year_over_year",  # "year_over_year" | "since_first" | "latest_two"
    threshold: float = 1.5,              # multiplicative threshold (1.5 = ±50%)
    direction: str = "any",              # "any" | "rising" | "falling"
    panel: Optional[str] = None,         # filter to one panel (e.g. "lipids", "metabolic")
    limit: int = 50
) -> dict
```

**Returns:**
```python
{
    "comparison": "year_over_year",
    "threshold": 1.5,
    "from_draw": "2025-04-15",
    "to_draw": "2026-04-03",
    "deltas": [
        {
            "biomarker": "fasting_insulin",
            "from": 2.5, "to": 14.3,
            "ratio": 5.72, "pct_change": 472.0,
            "unit": "uIU/mL",
            "direction": "rising",
            "panel": "metabolic",
            "out_of_range": True
        },
        ...
    ],
    "summary": {
        "total_biomarkers_compared": 74,
        "moved_above_threshold": 12,
        "rising": 9, "falling": 3
    }
}
```

**Implementation notes:**
- Live in `mcp/labs.py` (existing module per session context)
- Reuse the DDB read path that `get_labs` uses; add a delta-computation step
- Comparison `"year_over_year"` finds the draw closest to (latest - 365 days); `"since_first"` uses draw 1; `"latest_two"` uses last two draws
- Must handle biomarkers that exist in latest draw but not in comparison draw (return them under a `new_biomarkers` key, separate from `deltas`)
- Allergy panel uses ordinal IgE classes — exclude from numeric delta computation by default (handled by `get_allergies` instead)

### 1.2 `get_allergies` — ordinal IgE class semantics

**Purpose:** Allergy panel data has different semantics from continuous biomarkers. IgE class is ordinal (Class 0–6). Standard delta math is meaningless ("Class 3" → "Class 4" isn't a 33% change).

**Signature:**
```python
get_allergies(
    draw_date: Optional[str] = None,     # default: latest draw with allergies
    min_class: int = 1,                  # filter out Class 0 (no sensitization)
    category: Optional[str] = None       # "environmental" | "dander" | "food" | None=all
) -> dict
```

**Returns:**
```python
{
    "draw_date": "2026-04-03",
    "total_ige": {"value": 339, "unit": "kU/L", "ref_max": 114, "x_above_max": 2.97},
    "sensitizations": [
        {"allergen": "alder", "ige_kU_L": 5.08, "class": 3, "category": "environmental_pollen"},
        {"allergen": "birch", "ige_kU_L": 5.07, "class": 3, "category": "environmental_pollen"},
        {"allergen": "d_pteronyssinus", "ige_kU_L": 4.85, "class": 3, "category": "dust_mite"},
        ...
    ],
    "summary": {
        "total_sensitizations": 9,
        "high_class_count": 3,    # class >=3
        "categories_present": ["dust_mite", "environmental_pollen", "dander"]
    }
}
```

**Implementation notes:**
- Class lookup: 0 (<0.10), 1 (0.10–0.34), 2 (0.35–0.69), 3 (0.70–3.49), 4 (3.50–17.4), 5 (17.5–49.9), 6 (≥50.0). Standard ImmunoCAP scale.
- Categorization map lives in `mcp/labs.py` as a constant — use the categories shown above

### 1.3 NfL / Galleri trending cadence

These two panels have annual-or-rarer cadence. Don't build a per-biomarker MCP tool — just augment `get_labs` to surface:

```python
# Inside existing get_labs() response
"cadence_trackers": {
    "nfl": {
        "last_drawn": "2026-04-03",
        "days_since_last": <calculated>,
        "recommended_cadence_days": 365,
        "next_due": "2027-04-03",
        "history": [{"date": "2026-04-03", "value": 0.81, "unit": "pg/mL"}, ...]
    },
    "galleri": {
        "last_drawn": "2026-04-03",
        "days_since_last": <calculated>,
        "recommended_cadence_days": 365,
        "next_due": "2027-04-03",
        "last_signal": "NO CANCER SIGNAL DETECTED",
        "history": [{"date": "2026-04-03", "signal": "NO CANCER SIGNAL DETECTED"}, ...]
    }
}
```

Cadence values are configurable in `mcp/labs.py` as constants — `NFL_CADENCE_DAYS = 365`, `GALLERI_CADENCE_DAYS = 365`. **Open question for Matthew:** confirm 365 is right or set differently. NfL specifically might warrant 6-month tracking given the neurodegeneration signal sensitivity. Default to 365; flag in the PR description.

### 1.4 Test commands

```bash
# Pre-deploy: registry sanity check (per memory rule)
python3 -m pytest tests/test_mcp_registry.py -v

# Manual smoke after deploy
# (via MCP from chat, replace with actual invocation pattern)
life-platform:get_lab_deltas comparison=year_over_year threshold=1.5
life-platform:get_allergies min_class=1
life-platform:get_labs view=results  # confirm cadence_trackers present
```

### 1.5 Deploy

Per platform conventions (memory):
- Tool functions go BEFORE `TOOLS={}` dict in `mcp_server.py`
- MCP Lambda needs full package zip: `zip -j $ZIP mcp_server.py mcp_bridge.py && zip -r $ZIP mcp/`
- 10s wait between sequential Lambda deploys
- Update `MCP_TOOL_CATALOG.md` with the new tools (count goes 123 → 125; only `get_lab_deltas` and `get_allergies` are new; cadence trackers are an existing-tool augment, not a new tool)

---

## Workstream 2: Site updates (`site/labs/index.html`)

### 2.1 Goal

Render the 8th draw with full v2 panel coverage. The existing page renders 7 historical draws under v1 schema (basic chemistry + lipids + hormones panels). v2 adds:

- **Cardio IQ panel** (15 biomarkers, including headline IRS score)
- **Allergy panel** (9 sensitizations + total IgE)
- **NfL** (1 biomarker, neurodegeneration baseline)
- **Galleri** (signal/no-signal qualitative result)

### 2.2 Editorial pattern reference

Apply the editorial pattern from `site/observatories/nutrition/index.html`, `training/index.html`, `mind/index.html` — narrative-first synthesis, then visualization, then per-metric detail. **Read those three observatories before designing the labs page additions.**

The current `site/labs/index.html` predates the editorial pattern; this is also an opportunity to nudge it closer to the observatory editorial style without doing the full V2 visual overhaul (which is gated until SIMP-1 Phase 2).

**Scope discipline:** *Don't* refactor the entire labs page in this PR. Add the v2 panels alongside the existing v1 rendering. Mark the page as "v1.5 — interim" in a code comment. Full V2 labs page redesign is its own future workstream after SIMP-1 Phase 2.

### 2.3 Required additions

**A. Cardio IQ Insulin Resistance Score visualizer (priority — this is the headline finding)**

Custom component: a horizontal threshold-band gauge.

```
[ 0 ─────── 33 ─────── 66 ─────── 100 ]
   sensitive  early-IR    insulin-resistant
                                ▲
                                75 (Matthew's value)
```

- Three bands with distinct colors (e.g. green / amber / red, but check existing site palette)
- Marker at current value (75)
- Text below: "Insulin Resistance Score 75 — definitively insulin resistant. Combines fasting insulin 14.3 (5.7× rise from 2.5 last year) and elevated C-peptide 2.26."
- Link/cross-ref to: ApoB 116/111, Lp-PLA2 137, Vitamin D collapse, Testosterone collapse (the "metabolic constellation")

**B. Cardio IQ panel rendering (15 biomarkers)**

Standard panel-table format, but with Cardio IQ-specific reference ranges (these are cutoff-based, not normal-range-based for several biomarkers — IRS has the <33/33-66/>66 cutoffs; Lp-PLA2 has the >123 cutoff).

Biomarkers to render (from the handover OOR list, plus the in-range Cardio IQ ones from `draw_2026_04_03.py`):
- Insulin Resistance Score (75, OOR)
- Lp-PLA2 Activity (137, OOR)
- ApoB Cardio IQ (111, OOR)
- C-peptide (2.26, OOR)
- Plus the in-range Cardio IQ biomarkers (ApoE eval, HDL Function, Fibrinogen, Adiponectin, MPO, TMAO — values from `backfill/draw_2026_04_03.py`)

**C. Allergy panel rendering**

Different from continuous-biomarker rendering — use the `get_allergies` MCP response shape:
- Total IgE prominently (339, 3× upper limit)
- Sensitizations grouped by category (dust mite, environmental pollen, dander)
- Display IgE class as colored chips (Class 1/2 amber, Class 3+ red)
- Note: "Allergy results are surfaced for completeness but are not actionable in the platform's optimization loop" — cite from handover decision pending board input

**D. NfL + Galleri cadence widgets**

Small "annual sentinel" widgets:
- "NfL — last drawn 2026-04-03 (29 days ago) — value 0.81 pg/mL — next due 2027-04-03"
- "Galleri — last drawn 2026-04-03 (29 days ago) — NO CANCER SIGNAL DETECTED — next due 2027-04-03"

**E. Trend charts for high-movement biomarkers**

Time-series Chart.js charts for the year-over-year movers identified by `get_lab_deltas`:
- Fasting insulin (2.5 → 14.3)
- Testosterone total (577 → 361)
- Omega-3 index (7.8% → 3.3%)
- Vitamin D 25-OH (117 → 28)
- ApoB (history → 116)
- GGT (history → current)

Use existing Chart.js infrastructure already on the labs page. One chart per biomarker, 8-point time series.

### 2.4 Acceptance criteria

- [ ] Page renders without JS errors in Chrome + Safari
- [ ] All 153 biomarkers from 2026-04-03 draw are queryable by viewer (at minimum via "View all biomarkers" expander) — they don't all need to be visible in the editorial view, but they must be reachable
- [ ] IRS gauge prominently displays the 75 score in the threshold-band visual
- [ ] Allergy section shows all 9 sensitizations + total IgE
- [ ] NfL + Galleri cadence widgets show "29 days ago" relative date
- [ ] Year-over-year trend charts present for at least 6 biomarkers (insulin, T, omega-3, vit D, ApoB, GGT)
- [ ] Page loads in <3s on broadband (existing perf target)
- [ ] No regressions to existing 7-draw rendering

### 2.5 Deploy

`site-api` Lambda + S3 sync per existing labs page deploy pattern. Use `deploy/deploy_lambda.sh` for the Lambda, separate S3 sync for static assets. CloudFront invalidation: `E3S424OXQZ8NBE`.

---

## Workstream 3: Supplements page

### 3.1 Source

`Supplement_Protocol_2026-05_v2.md` is in S3 at `s3://matthew-life-platform/raw/matthew/labs/2026-04-03/supplement_protocol_v2.md`.

Claude Code: **read this file first** before designing the page. Page structure depends on the protocol's structure.

### 3.2 Decisions Matthew must make before merge

Two open decisions in the prior handover that Claude Code cannot make autonomously:

**Decision A — Public vs private?**
- Recommendation: **private**. Discusses specific dosages and clinical context tied to lab values. Public version risks looking like medical advice.
- Implementation if private: gate behind the same auth pattern used by other private surfaces on averagejoematt.com (verify pattern in repo before building)
- Implementation if public: render with a prominent "personal protocol, not medical advice" banner

**Decision B — Static page vs Habitify-tied widget?**
- Recommendation: **static page first, Habitify integration in a follow-up**. Faster to ship; doesn't block on Habitify TD-11 (phantom-failed habits) which would distort completion display.
- Future Habitify integration becomes useful once TD-11 is fixed (real "completed/skipped/not yet" states)

**Action:** Surface both decisions in the PR description. Don't merge until Matthew confirms.

### 3.3 Page structure (assuming static, private)

Pattern: editorial intro → protocol stack → rationale per supplement → references.

- **Intro:** 1–2 paragraphs. What this protocol is, when last updated (2026-05), what lab draw drove the changes (2026-04-03)
- **The stack:** rendered from the .md file as structured cards (one per supplement: name, dose, timing, form, source, rationale)
- **Recent changes:** a "what changed in v2" callout — omega-3 liquid added, Methyl-Guard Plus selected, etc., from session memory + .md file
- **References:** lab values that triggered changes (link to relevant labs page sections via anchor)
- **Disclaimer:** prominently, at top and bottom

### 3.4 Acceptance criteria

- [ ] Page renders all supplements from `Supplement_Protocol_2026-05_v2.md` in a structured way
- [ ] "Recent changes" section reflects v2 deltas vs prior protocol (Claude Code: check git history of the .md file or read prior version from S3 if archived)
- [ ] Disclaimer present
- [ ] Auth gating in place if Matthew picks "private"
- [ ] Anchored links from labs page to supplements page where relevant (e.g. omega-3 index callout links to the omega-3 supplement card)

### 3.5 Deploy

Same pattern as labs page. Add a `site/supplements/index.html` route.

---

## Cross-workstream housekeeping

### Doc updates triggered by this work

Per memory conventions, update on merge:
- `CHANGELOG.md` — always
- `PROJECT_PLAN.md` — always
- `MCP_TOOL_CATALOG.md` — workstream 1 adds 2 new tools (count 123 → 125)
- `FEATURES.md` — workstreams 2 + 3 add new public surfaces
- `USER_GUIDE.md` — supplements page warrants a section if private
- `ARCHITECTURE.md` — only if MCP module structure changes (it shouldn't — additive)

End-of-session ritual (memory):
1. Update `PLATFORM_FACTS` in `deploy/sync_doc_metadata.py` (MCP tool count 125)
2. `python3 deploy/sync_doc_metadata.py --apply`
3. Write handover + update `HANDOVER_LATEST.md`
4. Update `CHANGELOG.md`
5. `git add -A && git commit && git push`

### Test suite

Run before deploy:
```bash
python3 -m pytest tests/test_mcp_registry.py -v   # MCP rule (memory)
python3 -m pytest tests/ -v                        # full suite if exists
```

### Open questions for Matthew (surface in PR description)

1. NfL cadence — confirm 365 days, or shorten to 180?
2. Supplements page public/private — recommendation: private. Confirm.
3. Supplements page Habitify integration — defer until TD-11? Recommendation: yes.
4. Allergy results — render at all, or hide pending board input on actionability? Recommendation: render with the "not actionable in optimization loop" caveat.

---

## Sequencing recommendation for Claude Code

If executing in one session, order:
1. Workstream 1 first (MCP tools) — site work in workstream 2 consumes them
2. Workstream 3 (supplements page) can be done in parallel — independent of MCP work
3. Workstream 2 (labs page) last — depends on workstream 1

Estimated session size: large. If splitting, natural break is after workstream 1 deploys cleanly (you have new MCP tools live, can verify in chat, then return for site work).
