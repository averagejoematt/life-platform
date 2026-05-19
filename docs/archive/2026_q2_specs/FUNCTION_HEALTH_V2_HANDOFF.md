# FUNCTION_HEALTH_V2_HANDOFF — Site + MCP Spec for FH 2026 Draw

**Date:** 2026-05-03
**Source:** v6.8.1 handover ("Deferred Work" section) + Technical Board consult on observatory rendering, 2026-05-02.
**Scope:** Take the FH 2026 draw (already ingested, 153 biomarkers in DDB at `DATE#2026-04-03`) and surface it through the public site and MCP tooling.
**Out of scope:** Personal Board consult on the FH 2026 *findings* — see the separate Personal Board deliberation document.

---

## Technical Board Consult — Observatory Rendering for the New Test Categories

### The question

The FH 2026 draw added five categories that the existing `site/labs/index.html` doesn't render: **Cardio IQ comprehensive panel, NfL, Galleri, allergy panel, and clinician notes.** Should all five surface on the public site? Where? In what shape? And what's the editorial frame given that one of these categories (allergies) is real but not part of the platform's optimization loop?

The board also weighed in on the **MCP tool surface** for cross-draw delta queries, and on a structural decision about chronic out-of-range rendering.

### Round 1 — opening positions

**Sarah Chen (Product, ex-Strava):** "Stop and ask: what do these categories *unlock for the user*? The existing labs page is a results-history view. The new categories aren't symmetric — the Cardio IQ panel is *diagnostic-grade information* about IR; the allergy panel is a *single-draw curiosity*; NfL is a *baseline anchor for a multi-year trend that doesn't have data yet*; Galleri is a *negative-result confirmation*. Treating them all the same is a category error. Each one needs its own framing."

**Priya Sridharan (Architecture):** "I want to flag a data-modeling concern up front. The existing labs page assumes biomarkers have continuous numeric values + reference ranges. The allergy panel is *ordinal* — class 0/1/2/3 — and total IgE is a continuous count. Galleri is *binary* (signal/no signal). Treating these with the same chart component will produce ugly defaults. Either we extend the chart abstraction or we render different categories with different components. I lean toward different components — the data shape is genuinely different."

**Henning Müller (Stats):** "Trend analysis works for biomarkers we've measured 3+ times. With 8 draws, we're crossing that threshold for the standard panel. NfL has 1 draw — there is no trend, and pretending there is would be statistical theater. Same with the Cardio IQ — 1 draw, no slope. Don't render trend lines for single-point data. Render the value + reference range + cohort context if available."

**Omar Patel (Data):** "Backing Henning. The instinct will be to extend the existing trend-line aesthetic to every new biomarker because consistency is good. Resist. Single-point data needs a different visual language: a band chart with the value plotted against the reference range, no slope, no projection."

**Anika Reddy (AI / LLM):** "The clinician notes PDF is pure unstructured text and the platform's strongest asset is the editorial layer — Elena Voss, Paul Conti. I'd extract the clinician notes via Haiku once into a structured `findings` JSON (3-5 points, plain-English) and surface those as quotations in the labs page narrative, not as a downloadable PDF. The PDF can stay in S3 as a backup."

**Sarah Chen:** "Counter — a 'download the report' button is a feature, not a bug. People who arrived from Hacker News will want the original artifact. Surface both: structured findings as quotations + a download button to the original. Let the user decide which to consume."

**Dana Kowalski (FinOps):** "Haiku extraction is ~$0.01 per page. Clinician notes is one page. This is a non-issue cost-wise. I'd rather hear about query patterns. The new MCP tools `get_lab_deltas` and `get_allergies` — what's the read path? If they hit DynamoDB on every call without caching, they'll be expensive at scale. Right now scale is 'Matthew + a few site visitors,' but plan the cache layer in from day one."

**Viktor Ivanov (Adversarial):** "Two sharp questions. First, the allergy panel shows IgE-mediated sensitization — that is *medical information*. Are we comfortable rendering it on a public site with the same casual treatment as VO2max? Second, the Galleri 'no cancer signal detected' is a 24-month early-detection screen with limited sensitivity. Rendering it as a green checkmark next to 'no cancer' is potentially misleading — the absence of evidence is not evidence of absence. The framing language matters."

**Raj Mehta (Startup CTO):** "Viktor's right on both. On allergies — render them, but in a separate 'Inflammation context' section, not as headline biomarkers. On Galleri — render the result as 'no signal at 24-month sensitivity threshold,' not 'no cancer.' The framing is the difference between honest health journalism and clickbait wellness."

### Round 2 — convergence

The board converged on a specific structural recommendation:

**Re-architect `site/labs/index.html` from a flat 'all biomarkers, scrollable' page into five distinct sections:**

1. **Headline.** The single most important finding from the latest draw, with editorial framing. For the 2026-04-03 draw, this is the IR Score 75. One section, one chart, narrative paragraph. Maximum prominence.

2. **Trends.** Biomarkers with 3+ measurements rendered as trend lines with reference range bands. ApoB, total cholesterol, LDL-C, vitamin D, insulin, etc. Existing rendering pattern, refined.

3. **New baselines.** Single-point biomarkers from this draw — NfL, Cardio IQ panel, Galleri. Rendered as value-against-range bands with no slope. Each gets a sentence of editorial framing explaining what the baseline means and when it'll be re-measured.

4. **Inflammation context.** A side-section, not headline. Allergy panel goes here, alongside hs-CRP and Lp-PLA2. Framing: "These markers describe the inflammatory environment in which the headline findings exist. They're not the optimization target; they're context."

5. **The full report.** Download button to the original PDF + a structured findings block (extracted via Haiku one-time) that quotes the clinician's qualitative read. Honest about what was extracted vs what's in the PDF.

This is **not five separate pages** — it's five distinct sections in a single labs page, each with appropriate visual treatment.

### Specific resolutions from the board

| Question | Resolution |
|---|---|
| Should allergies be rendered? | Yes, but in "Inflammation context" section, not as headline biomarkers. |
| Should Galleri show as "no cancer"? | No. Render as "No signal detected at 24-month early-detection threshold." Anika's wording. |
| Should NfL render a trend? | No. Single point. Render as baseline anchor with explicit "this is the baseline; next read at [date TBD]." |
| Should Cardio IQ render as one panel or fold into existing categories? | One panel — it's a coherent diagnostic suite. Embed the IR Score as headline; render the other 9 markers as a sub-section under Cardio IQ. |
| Should clinician notes PDF be processed? | Yes — Haiku extraction once, surface 3-5 findings as quoted narrative, retain PDF download. |
| Should the trend line cross the bad-quality 2024-06-01 draw? | Open question — see "Trend continuity" discussion below. |

### Trend continuity discussion (unresolved by board, needs your call)

Henning flagged: "We have 8 draws spanning 2019-05-01 to 2026-04-03 but they're from at least three different testing labs (Quest, Function/Quest, prior PCP). Reference ranges and assays differ. A trend line drawn through them is approximately accurate but not technically rigorous. Do we add a footnote acknowledging this, or do we render only the Function-Health-only sub-trend (2025-04 + 2026-04)?"

Three options:
- **A.** Render the full 8-draw trend with a footnote: "Cross-lab trend; assay variation may affect comparisons."
- **B.** Render two trend lines: full historical (faded) + Function Health only (bold). Lets the eye see both stories.
- **C.** Function Health only. Cleanest but loses the long-term trajectory.

My recommendation: **B.** Most honest + most informative.

---

## Site Implementation Spec

### File targets

**Primary:**
- `site/labs/index.html` — restructure into 5 sections.
- `lambdas/site_writer.py` — extend to handle new section data.

**Secondary:**
- New: `lambdas/clinician_notes_extractor_lambda.py` — Haiku extraction, runs once per new draw.
- `mcp/tools_labs.py` — add new tools (see MCP section below).

### Section 1 — Headline

For 2026-04-03 specifically, the headline is the IR Score. Component:

```
[Insulin Resistance Score chart]
- Visual: horizontal band chart with three zones:
    Sensitive (<33) — green band
    Impaired (33-66) — yellow band
    Resistant (>66) — red band
  Plot the value 75 with a marker on the band.
- Narrative paragraph below (200-300 words):
    What this score is.
    What 75 means.
    What the platform is doing about it (link to Personal Board consult).
- Citation: link to the Cardio IQ test methodology.
```

Make this section configurable per-draw — the headline finding changes between draws. Add a `headline_biomarker` field to a new draw-metadata schema in DDB:

```
pk = USER#matthew#SOURCE#labs#metadata
sk = DATE#2026-04-03
attrs:
  headline_biomarker: "insulin_resistance_score"
  headline_narrative_md: "..."
  cycle_label: "Cycle 2"
```

The headline narrative is hand-written per draw (not auto-generated). Quality matters more than automation here.

### Section 2 — Trends

Existing rendering pattern. Apply Henning's "render only when ≥3 measurements" rule strictly. List of biomarkers that qualify after the 2026-04-03 draw:

- Lipid panel (cholesterol_total, ldl_c, hdl, triglycerides, non_hdl_c, apob)
- Hormones (testosterone_total, shbg)
- Glucose markers (glucose, hba1c, insulin, c_peptide)
- Inflammation (crp_hs, ggt)
- Vitamins (vitamin_d_25oh)
- Liver (alt, ast)
- Kidney (creatinine, bun, egfr)
- CBC components (hemoglobin, hematocrit, platelets, wbc, neutrophils, lymphocytes, etc.)

Apply the **Option B trend rendering**: faded full-history line + bold Function-Health-only sub-line.

### Section 3 — New baselines

Cardio IQ panel + NfL + Galleri.

Cardio IQ rendering:
- IR Score is in the Headline section, not duplicated here.
- Other 9 Cardio IQ markers (Lp-PLA2 activity, ApoE evaluation, HDL Function, Fibrinogen, Adiponectin, MPO, TMAO, etc.) render as **value-against-range bands.** No trend lines. Each marker shows: value, range, color-coded against threshold, one-sentence editorial framing.

NfL rendering:
- Single value (0.81 pg/mL) plotted against age-adjusted reference range.
- Editorial framing: "Baseline neurodegeneration biomarker. Will be re-measured at [annual cadence — needs Personal Board input]."

Galleri rendering:
- Result: "No signal detected at 24-month early-detection threshold."
- Add a one-paragraph framing block explaining what Galleri does and doesn't detect.
- Link to the GRAIL methodology.

### Section 4 — Inflammation context

Allergy panel + hs-CRP + Lp-PLA2 grouped together.

Allergy rendering — the IgE class is ordinal, not continuous, so use a different chart pattern:
- Horizontal bar chart, one row per allergen, color-coded by class (0/1/2/3).
- Show class boundaries on the bar.
- Total IgE rendered separately as a single number with a 3x-upper-limit framing.

Editorial frame for the section: "These markers describe the inflammatory environment in which the headline findings exist. They're not the optimization target; they're context for understanding the headline."

### Section 5 — The full report

- Download button: links to S3 pre-signed URL for the consolidated PDF (or links per panel — your call; one button is cleaner).
- Structured findings block: 3-5 quoted findings extracted from the clinician notes via Haiku. Format: blockquote per finding, with an "extracted from clinician notes" attribution line.
- Honest meta-line: "These findings were extracted by AI from the clinician's report. The full report is downloadable above."

### Editorial language guidelines

- Avoid wellness-influencer language. The platform's voice is honest health journalism, not "your body is healing!"
- Don't over-claim from single data points. Use language like "this draw shows" rather than "your X is."
- Don't downplay severe findings. The IR Score 75 deserves direct framing — "definitively insulin resistant" is honest, not alarmist.
- Reference Personal Board consults inline where they add interpretive depth.

---

## MCP Tool Additions

Three new tools to add to `mcp/tools_labs.py`. All three will trip TD-21 timezone bug if `tools_labs.py` shares the same import problem — verify before implementation.

### `life-platform:get_lab_deltas`

Cross-draw biomarker comparison. Returns biomarkers with absolute or % change exceeding a threshold.

**Args:**
- `from_date` (required): YYYY-MM-DD of comparison baseline draw.
- `to_date` (optional, default latest): YYYY-MM-DD of target draw.
- `threshold_pct` (optional, default 25): minimum % change to include.
- `direction` (optional: improved | worsened | both, default both).
- `category` (optional): filter by lipids/metabolic/etc.

**Returns:**
```
{
  "from_date": "2025-04-17",
  "to_date": "2026-04-03",
  "deltas": [
    {
      "biomarker": "omega_3_index",
      "from_value": 7.8,
      "to_value": 3.3,
      "pct_change": -57.7,
      "absolute_change": -4.5,
      "direction": "worsened",
      "category": "fatty_acids",
      "clinical_significance": "Crossed below 4% mortality-risk threshold"
    },
    ...
  ],
  "summary": {
    "total_changed": 14,
    "improved": 2,
    "worsened": 12
  }
}
```

`clinical_significance` is computed against threshold-crossing logic (e.g. "crossed below cardio-protective range," "crossed above resistance threshold"). Optional but high-value.

### `life-platform:get_allergies`

Allergy panel surface. Different semantics from generic biomarker queries because IgE class is ordinal.

**Args:**
- `class_filter` (optional: 1+, 2+, 3+) — minimum class to include.
- `category_filter` (optional: environmental, food, all) — currently only environmental tested but the schema should anticipate.

**Returns:**
```
{
  "draw_date": "2026-04-03",
  "total_ige": 339,
  "total_ige_status": "elevated",
  "allergens": [
    {
      "allergen": "dust_mite_d_pteronyssinus",
      "value_ku_l": 4.85,
      "class": 3,
      "class_label": "High Level",
      "category": "environmental"
    },
    ...
  ],
  "summary": {
    "high_class": 3,
    "moderate_class": 2,
    "low_class": 3
  }
}
```

### `life-platform:get_lab_meta`

Metadata about the draws themselves — useful for the new Trend Continuity rendering and for any UI that needs to know "what panels were collected on what date."

**Args:**
- `date` (optional): YYYY-MM-DD.

**Returns:**
```
{
  "draws": [
    {
      "date": "2026-04-03",
      "panels": ["standard", "cardio_iq", "nfl", "galleri", "allergies"],
      "biomarker_count": 153,
      "out_of_range_count": 26,
      "lab": "Function Health (Quest-mediated)",
      "headline_biomarker": "insulin_resistance_score"
    },
    ...
  ]
}
```

---

## Supplements page rendering

Per v6.8.1 handover, this is in S3 (`Supplement_Protocol_2026-05_v2.md`) but not rendered. Three options:

- **A.** Render as static page on averagejoematt.com.
- **B.** Build a "supplement tracker" widget tied to Habitify completion.
- **C.** Render as a private page (login-gated) given dosage specifics.

**Recommendation:** Option C for now — the dosage specifics are clinical and shouldn't be mistaken for a recommendation by anonymous site visitors. Add an authenticated route. Defer the Habitify-integrated tracker to a later sprint.

If authentication infra doesn't exist yet, defer the supplements page entirely until it does. The compute is small; the legal/optics surface area is real.

---

## NfL / Galleri trending cadence

Open question, requires Personal Board input on Sunday. Options:

- **NfL:** annual (cheapest signal, most actionable in a slow-degenerating disease horizon) vs quarterly (overkill at this stage of life).
- **Galleri:** annual (per GRAIL recommendation) vs every 2 years (cost-saving) vs only when other markers shift.

Bring this to the Personal Board consult on the FH findings. Don't implement cadence logic until decided.

---

## Order of build

1. **Sunday:** `clinician_notes_extractor_lambda.py` (Haiku extraction, one-time run for 2026-04-03). Cheap, unblocks Section 5 narrative.
2. **Sunday:** Decide cadence questions (NfL, Galleri).
3. **Next session:** `get_lab_deltas` MCP tool — quickest win, lots of reuse value.
4. **Following session:** Re-architect `site/labs/index.html` into 5 sections. Headline section first (2026-04-03 specific).
5. **Following session:** Cardio IQ + NfL + Galleri rendering (Section 3).
6. **Following session:** Allergy panel rendering (Section 4) + `get_allergies` MCP tool.
7. **Following session:** Trend continuity (Option B implementation).
8. **Final session:** `get_lab_meta` + Supplements page (gated on authentication infra).

Total estimated effort: 4-6 focused sessions for site work + 2 sessions for MCP tools.

---

## Acceptance criteria

- The labs page has 5 distinct sections, each with appropriate visual language.
- The IR Score 75 is the headline of the 2026-04-03 view, with a band chart and narrative.
- Allergy data is rendered as ordinal class bars, not continuous lines.
- Galleri reads "No signal detected at 24-month early-detection threshold," not "No cancer."
- NfL renders as a baseline, not a trend.
- The clinician notes PDF is downloadable, and 3-5 structured findings are quoted in narrative.
- `get_lab_deltas`, `get_allergies`, `get_lab_meta` MCP tools work end-to-end.
- The Cardio IQ panel renders as a coherent suite, not scattered across categories.
