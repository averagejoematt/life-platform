# Handover — 2026-07-04 (session 3) The Data-Source Health Review

**The owner-requested per-source integration review is COMPLETE and awaiting Matthew's read.** Deliverables (this PR, branch `review/data-source-health`):

- `docs/reviews/DATA_SOURCE_HEALTH_REVIEW_2026-07.md` — 15 sources × 8 dimensions, per-source scorecards, posture table, 7 executive themes, the journal free-text extraction roadmap (3 phases), and the Stage-0 reconciliation record.
- `docs/reviews/DATA_SOURCE_HEALTH_REVIEW_2026-07_findings.json` — the machine-readable appendix (same schema family as the 2026-07 platform review).

**Funnel: 71 raw → 5 cross-lane duplicates merged → 66 distinct → all 66 adversarially confirmed (7 adjusted), 0 dropped; 4 sub-claims refuted and recorded.** Method: Stage-0 live evidence baseline (freshness API, alarm history, per-partition latest-SK, sentinels, EventBridge states, MCP EMF) → 5 per-source lanes + 3 cross-cutting lenses, probe-required findings → independent adversarial verifier per lane re-opened every citation and re-ran every probe (live numbers reproduced to the decimal).

## Headlines (what Matthew should read first)

- **Two P1s:** X-1 — Hevy ingestion failure is invisible end-to-end (errors return a 500 *body* from a successful invocation; the liveness alarm watches a metric Hevy never emits, treat-missing NOT_BREACHING — it can never fire). J-1 — **the entire journal enrichment layer's output has been wiped**: Notion re-ingestion full-item `put_item` clobbers all 23 `enriched_*` fields; 0/50 records enriched; every consumer (coaches, hypothesis engine, /data/mind) reads None. The backfill fix costs cents.
- **Both live alarms at review time are instrument misfires:** the Strava reconciliation ALARM is a UTC/local window-edge false positive (the "missing" walk is stored — C-1); the freshness ALARM's residual driver is Todoist's 62h-max-healthy-age vs 48h threshold (E-3). The June red was pre-#392 misclassification and #392 demonstrably fixed it (metric dropped 4→1 within hours of the deploy).
- **A dozen dead writer↔reader couplings** (theme 2): TDEE chain (B-1), brief/digest strength wired to a partition dead since March (B-2), character body-fat fields that never existed (B-3), unified-sleep merge rules reading nonexistent fields (A-2), journal trajectory tool that can never output (J-3), mind coach double-dead (J-4).
- **Honesty recorded, not surfaced** (theme 4): TSB is 100% Hevy-proxy with `confidence: hevy_fallback` stored and consumed by nothing while a coach prompt says "TSB −87" (M-3, C-5/C-6); the site labels an 8-day-old weight "today" (M-5).
- **Two "S3-triggered" ingesters have no trigger:** measurements (B-4 — the next tape-measure upload silently does nothing) and the apple_health XML path (D-5 — which is lucky, since it's also a latent clobber).
- **Privacy-forward:** J-8 — `/api/journal_analysis` will publicly serve per-day journal one-line summaries the moment journaling resumes (phaseless cache records pass the phase filter). Decide before Phase 2 of the roadmap.

## What happens next (Session 2 of the review→backlog pipeline, GATED)

1. Matthew reads the review. 2. On green-light: score the 66 findings per ADR-099 (gates → `(Impact×Confidence)/Effort` → terciles), file epics+stories (`area:data`, privacy-passed bodies), write the manifest. Consider authoring `scripts/file_backlog_from_manifest.py` — the missing automation link from the last batch (issues were filed ad-hoc). 3. The journal roadmap Phase 1 (backfill + clobber-proofing + dead-consumer fixes) is the single highest-value S-effort cluster and could ship as its own early batch.

## Notes for the fixer

- `source_state.py` (C-3) and any registry change ship in the **shared layer** — CONVENTIONS §1 sequence.
- E-1's poisoned Todoist snapshot fields (since ≥05-10) are point-in-time and unrecoverable — annotate the range, don't try to backfill.
- The review ran read-only from worktree `.claude/worktrees/ds-health-review` @ `40cbbc4a`; no code, config, or deploy was touched. Stage-0 baseline + lane reports + verdicts live in the session scratchpad (`…/scratchpad/dsr/`) if the findings need re-tracing.
- CLAUDE.md drift the review itself hit (fold into any doc-truth batch): "Todoist at 2x daily" (actual 1×, TD-12), the `raw/{source}/{datatype}/…` S3 convention (matches nothing — X-9), ADR-057's "WAF protects HAE" (false — D-7).
