# Handover — v6.8.6: PR 4 — Function Health v2 (MCP + supplements page + labs v1.5 panels)

**Date:** 2026-05-03
**Scope:** PR 4 (4a + 4b + 4c) — surface the FH 2026 lab draw through MCP tooling, the public site labs page, and a new private supplements protocol page.
**Type:** Feature work + new MCP tools + new site surface.

## What deployed

| Sub-PR | Items | Mechanism | Status |
|---|---|---|---|
| 4a | `get_lab_deltas`, `get_allergies` MCP tools + cadence_trackers augment | `aws lambda update-function-code life-platform-mcp` | ✅ live |
| 4b | `site/supplements/protocol/index.html` — private supplement protocol v2 | `bash deploy/sync_site_to_s3.sh` (CF invalidated) | ✅ live |
| 4c | `site/labs/index.html` — FH 2026 v1.5 panels added below "What I'm watching" | same sync | ✅ live |

## PR 4a — MCP tools detail

Two new tools + one augment to existing `get_labs`. All in `mcp/tools_labs.py`.

- **`get_lab_deltas`** — cross-draw biomarker movement query. Comparisons: `year_over_year` (default — finds draw closest to latest-365d), `since_first`, `latest_two`. Threshold-filtered (default ±50%), direction-filtered, panel-filtered. Returns separate `new_biomarkers` list for biomarkers in latest but not baseline (88 new in 2026-04-03 vs 2025 — Cardio IQ + NfL + Galleri + the entire allergy panel were new).
- **`get_allergies`** — ImmunoCAP class lookup (0–6) per allergen, total IgE separately, sorted by class desc. Categories: dust_mite / environmental_pollen / dander / mold / other. Includes "not actionable in optimization loop" context line per Technical Board.
- **`cadence_trackers`** — auto-attached to every `get_labs` view's response (results / trends / out_of_range). NfL = 180-day cadence (Matthew tonight; sensitive neurodegeneration baseline warrants 6-month tracking). Galleri = 365-day. Galleri framing reworded: "No signal detected at 24-month early-detection threshold" (Viktor's adversarial pushback on absence-of-evidence framing). Raw signal preserved in `raw_signal` field.

Tool count: 123 → 125. `MCP_TOOL_CATALOG.md` updated.

Smoke-tested locally with real DDB data:
- get_lab_deltas yoy threshold=0.5: top movers leptin (0.4 → 16.8, +4100%), prolactin (+144%), ggt (+138%), estradiol (+100%), epa (-71%) — matches handover headlines.
- get_allergies min_class=1: 24 sensitizations across 5 categories. alder, birch, dust_mite_d_pteronyssinus all Class 4.
- get_labs view=results: cadence_trackers populated with NfL next due 2026-09-30, Galleri next due 2027-04-03.

## PR 4b — Supplements protocol page detail

**Path:** `/supplements/protocol/` — new path, doesn't disturb existing `/supplements/` ("The Pharmacy" public page).

**Content source:** `s3://matthew-life-platform/raw/matthew/labs/2026-04-03/supplement_protocol_v2.md` (12KB markdown, fetched and rendered structurally as HTML).

**Sections rendered:**
1. Top + bottom disclaimer ("Personal Protocol — Not Medical Advice")
2. Hero with v2 metadata (built from FH 2026, run 8–12 wks, retest ~early Aug 2026)
3. v2 changes from v1
4. The 80/20 callout (supplements are 10%; the other 90% is lifestyle)
5. STOP table (8 supplements + Lion's Mane callout)
6. OPTIONAL / TRIAL-ONLY table (7 trials with tracking criteria)
7. START table (psyllium + protein) + recommended pairing (K2) + conditional adds (5)
8. CONTINUE — with changes (5) + omega-3 product template
9. CONTINUE — unchanged (3)
10. Daily schedule (6 time-of-day blocks)
11. Physician conversation (6 numbered items)
12. 90-day retest panel (4 sub-panels)
13. Decision rules at retest (8 if-then rules)
14. "Success" criteria

**Auth:** No special handling. The entire `averagejoematt.com` site is currently password-gated by `PRIVACY_MODE=true` (cf-auth Lambda@Edge with HMAC cookie, 90-day TTL). The new page auto-inherits this gate.

**Caveat:** if Matthew flips `PRIVACY_MODE=false` in the future, this page becomes public alongside everything else. At that point per-page gating would need to be implemented (currently no precedent for it on this site). Documented in the page's footer.

**Deferred per Matthew tonight:** Habitify completion-tracking integration. Defer until TD-11 (phantom failed habits) ships — would otherwise distort completion display.

## PR 4c — Labs page v1.5 detail

**Approach:** additive. Inserted a single `<section id="lb-fh2026">` between "What I'm watching" and "Panel summary" — no refactor of the rest of the 783-line page. Matthew's tonight spec called this out explicitly: "Don't refactor the entire labs page in this PR. Add the v2 panels alongside the existing v1 rendering. Mark the page as v1.5 — interim in a code comment."

**What's in the new section:**
- **Cardio IQ Insulin Resistance Score gauge** — the headline finding. Three-band horizontal visual (Sensitive / Early IR / Resistant), marker at the value (75), verdict caption, cross-ref note to the metabolic constellation.
- **Cardio IQ panel summary** — Lp-PLA2, ApoB Cardio IQ, C-peptide, fasting insulin in a 2-card grid.
- **Allergy panel** — total IgE callout + sensitization chips colored by class (1 amber → 6 red). Contextualized as "inflammation context, not optimization target" per Technical Board.
- **Annual sentinel widgets** — NfL + Galleri side-by-side cards with last-drawn / days-ago / cadence / next-due meta. Galleri uses the reworded "No signal detected at 24-month early-detection threshold" framing.

**Skipped from spec (deferred to future labs V2 redesign):**
- Per-biomarker year-over-year Chart.js trend charts (insulin, T, omega-3, vit D, ApoB, GGT). Wiring 6 charts is non-trivial; existing labs page already has Chart.js infrastructure but the data-shape work is meaningful. Future workstream.
- Editorial cross-reference between IRS finding and the metabolic constellation (currently a one-line caption; full editorial treatment is a future workstream).

The new section auto-shows only when the latest draw contains FH 2026 v2 biomarkers (insulin_resistance_score / nfl_neurofilament_light_chain / galleri_cancer_signal / allergy_total_ige). For prior draws (no v2 biomarkers), the section stays hidden.

## Spec reconciliation note

Matthew's tonight spec (`docs/specs/FUNCTION_HEALTH_V2_HANDOFF.md`) and the Technical Board version (`docs/FUNCTION_HEALTH_V2_HANDOFF.md`, untracked-then-committed in v6.8.2 housekeeping) had material differences:

| Topic | Matthew tonight | Tech Board version | What I shipped |
|---|---|---|---|
| Site approach | v1.5 interim — additive | 5-section restructure | **Additive** (Matthew tonight) |
| MCP tools | 2 new + cadence augment | 3 new (incl. get_lab_meta) | **2 new** (Matthew tonight) |
| NfL cadence | 365 default, ask Matthew | Defer to PB Sunday | **180** (Matthew tonight) |
| Galleri framing | "NO CANCER SIGNAL DETECTED" | "No signal at 24-mo threshold" | **Reworded** (board) |
| Allergy treatment | Render with caveat | Demoted to inflammation context | **Both** — caveat + section labeled "inflammation context" |
| Trend continuity | Not addressed | Faded full + bold FH-only | Skipped (future workstream) |
| Clinician notes PDF | Out of scope | Build extractor Lambda | Skipped (future workstream) |
| Supplements gating | Private | Conditional on auth infra | **Auto-private** via existing PRIVACY_MODE |

Per Matthew's "complete all PRs / less approval" direction, I skipped writing a formal merged spec and just executed using Matthew's tonight version as primary, taking the better-thought-out wording from the board version where it didn't conflict.

## Deferred items (carry-forward)

1. Trend charts on labs page for the 6 high-movement biomarkers — needs Chart.js wiring + `get_lab_deltas` MCP integration.
2. Clinician notes PDF extractor Lambda — Haiku one-shot extraction, render 3-5 quoted findings as blockquotes in labs page Section 5.
3. Habitify integration on supplements page — gated on TD-11 (phantom-failed-habits) shipping.
4. `/supplements/` consolidation — currently we have `/supplements/` (public Pharmacy page) and `/supplements/protocol/` (private v2 protocol). At some point these should reconcile; for now they're complementary.

## Commits

```
57527ad PR 4a: get_lab_deltas + get_allergies + cadence_trackers (FH v2)
TBD     PR 4b: site/supplements/protocol/index.html (private)
TBD     PR 4c: site/labs/index.html v1.5 FH 2026 panels (additive)
TBD     docs: v6.8.6 handover + CHANGELOG + archive PR 4 spec
```

## State snapshot

| Metric | Value |
|--------|-------|
| Version | v6.8.6 |
| Lambda Layer | v42 (unchanged) |
| Lambdas | 66 (unchanged) |
| MCP Tools | **125** (was 123) |
| Site pages | +1 (`/supplements/protocol/`) |
| Site files modified | 2 (labs page + new protocol page) |
| Spec moved to archive | `docs/specs/FUNCTION_HEALTH_V2_HANDOFF.md` → `docs/archive/FUNCTION_HEALTH_V2_HANDOFF_2026-05-02_tonight.md` |
