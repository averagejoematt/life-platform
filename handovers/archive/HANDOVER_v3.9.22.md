# Handover — v3.9.22

## Session: Discoveries Page — Product Board Review + Timeline Rebuild

### What shipped this session (v3.9.21 → v3.9.22)

**v3.9.22**: Product Board reviewed Discoveries page. Two major outcomes:
1. Shipped DISC-1/DISC-2 (counterintuitive wiring + confidence threshold + critical API bug fix)
2. Matthew saw the shipped correlation table and said "I thought we said a timeline with weight loss, achievements, challenges." Board reconvened, agreed: correlation data belongs on Data Explorer, Discoveries should be a visual journey timeline. Page completely rebuilt.

### Product Board Reviews (2 rounds)

**Round 1** — reviewed existing correlation-focused page:
- Mara: counterintuitive section hardcoded, no middle confidence state, mobile hides wrong column
- James: sort by |r| not ideal, no "discovery score" weighting novelty/lag
- Sofia: no dates on discoveries, no behavioral response field, no shareability
- Lena: counterintuitive section makes causal claims without data, no analysis window dates
- Raj: page works as evidence room but not a destination — needs timeline, experiment links, engagement
- Tyrell: spotlight cards too similar, counterintuitive cards disconnected from design system
- Jordan: zero SEO (all JS-rendered), no discovery-specific email CTA
- Ava: disconnected from Chronicle, discoveries should auto-generate Elena content

**Round 2** — after Matthew's feedback:
- Board consensus: "We optimized the wrong page. We built the evidence room and forgot the courtroom."
- Raj: "Matthew uses 'discoveries' the way a visitor would — what has he discovered on this journey?"
- Sofia: "The discovery isn't the r-value, it's the behavioral response."
- Mara: vertical timeline with date rail + event cards is the right pattern
- James: DynamoDB partition per event type, multiple feed sources → unified timeline

### Changes Shipped

**lambdas/weekly_correlation_compute_lambda.py:**
- Added `EXPECTED_DIRECTIONS` map (23 pairs with domain-knowledge expected direction)
- Added `counterintuitive` and `expected_direction` fields per pair result
- Enhanced logging: `** COUNTERINTUITIVE` flag in CloudWatch
- Fix: `_dec_correlations()` handles `bool` before `int` (Decimal("False") crash)

**lambdas/site_api_lambda.py:**
- `handle_correlations()`: **Critical fix** — reads `record.get("correlations", {})` not `record.get("pairs", [])`. Page was showing empty state despite data existing. Handles both dict and list formats.
- `handle_correlations()`: Added `_METRIC_META` lookup (raw metric → human-readable label + source name). Surfaces `counterintuitive`, `expected_direction`, `start_date`, `end_date`.
- `handle_journey_timeline()`: NEW section 5 — FDR-significant correlation findings injected as timeline events. Counterintuitive findings flagged with amber "Surprise" type. Only first detection per pair shown.

**site/discoveries/index.html** — COMPLETE REBUILD as visual journey timeline:
- Vertical timeline: thin line on left, date markers (month + day), event cards on right
- 6 event types, color-coded: weight (green), level_up (teal), experiment (purple), finding (blue), counterintuitive (amber), milestone (gold)
- Filter bar: All / Weight / Level Up / Experiments / AI Findings / Surprises / Milestones
- Reverse chronological, stagger-animated card entrance
- Stats strip: total discoveries, days tracked, weight events, AI findings
- Explorer CTA: "Want the raw correlation data? Open Data Explorer →"
- Mobile responsive (single column, adjusted node positions)

**docs/DISCOVERIES_EVOLUTION_SPEC.md** — NEW:
- Full 12-task, 3-tier evolution roadmap from Round 1 review
- Note: Tier 1 tasks (DISC-1 through DISC-5) partially shipped, then page direction changed

### Deploy Log
- `weekly-correlation-compute` Lambda deployed (2x — bool fix on second deploy)
- `life-platform-site-api` Lambda deployed (2x — correlations fix, then timeline expansion)
- `site/discoveries/index.html` synced to S3 (2x — first correlation page, then timeline rebuild)
- CloudFront invalidated: `/discoveries/*`, `/api/correlations*`, `/api/journey_timeline*`
- Force-recomputed W13 correlations: 23 pairs, 5 FDR-significant, 1 counterintuitive, 88 days

### Validation
- `/api/correlations`: 23 pairs with human-readable labels, 5 FDR-significant, 1 counterintuitive (Steps → Sleep Score)
- `/api/journey_timeline`: Returns weight milestones, level-ups, experiments, FDR findings
- Top correlation: HRV → Recovery Score r=0.861 (Whoop × Whoop)
- Discoveries page renders vertical timeline with real events from journey_timeline API

### Files Modified
- `lambdas/weekly_correlation_compute_lambda.py` — EXPECTED_DIRECTIONS, counterintuitive flag, bool fix
- `lambdas/site_api_lambda.py` — correlations dict→list fix, _METRIC_META, timeline expansion
- `site/discoveries/index.html` — complete rebuild as journey timeline
- `docs/DISCOVERIES_EVOLUTION_SPEC.md` — new (evolution roadmap)
- `docs/CHANGELOG.md` — v3.9.22 entry
- `handovers/HANDOVER_v3.9.22.md` — this file
- `handovers/HANDOVER_LATEST.md` — updated pointer

### What the correlation work became
The DISC-1/DISC-2 work (counterintuitive flags, confidence threshold, _METRIC_META, dict→list fix) isn't wasted — it powers:
1. The `/api/correlations` endpoint used by Data Explorer (`/explorer/`)
2. The homepage featured discoveries section (HP-06 `?featured=true` mode)
3. The journey timeline's "AI Finding" and "Surprise" event cards

### Remaining from DISCOVERIES_EVOLUTION_SPEC.md
Many tasks are moot now that the page is a timeline, but some still apply:
- **DISC-3** (temporal metadata: first_detected, weeks_confirmed) — still valuable for timeline cards ("confirmed 8 weeks")
- **DISC-6** (discovery timeline) — effectively what we built, but could add r-value sparklines per finding card
- **DISC-7** (behavioral response field) — still the #1 upgrade: "what did I do about this finding?"
- **DISC-9** (SEO pre-rendering) — timeline events as static HTML for indexability
- **DISC-10** (discovery-specific email CTA) — "Get notified when new discoveries drop"
- **DISC-11** (auto-chronicle from findings) — still the content engine dream

### Next Steps (suggested)
1. Review the live timeline page — does it match your vision? Iterate on card content/layout.
2. The timeline currently shows ~12-15 events (Day 1, weight crossings, level-ups, experiments, findings). As more data accumulates, it will grow automatically.
3. Consider adding manual "insight" entries via `log_life_event` for moments the system can't detect (behavioral shifts, personal realizations).
4. DISC-7 (behavioral response annotations) would make each finding card tell a complete story.

### Critical Reminders
- `weekly-correlation-compute` Lambda name has NO `life-platform-` prefix (unlike site-api)
- macOS `aws lambda invoke` requires `fileb://` for JSON payloads (base64 error otherwise)
- Python `bool` is a subclass of `int` — always check `isinstance(v, bool)` before `isinstance(v, int)` when converting to Decimal
- The `/api/correlations` endpoint now correctly reads the `correlations` dict from DDB (was reading nonexistent `pairs` key)
