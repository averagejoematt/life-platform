# SPEC_READING_MIND_2026-06-29.md
**The Mind Pillar (Reading) — feature spec: data model, services, and the recommendation engine.**
Repo path: `docs/SPEC_READING_MIND_2026-06-29.md`
Status: DRAFT v0.1 · 2026-06-29
Fold-into note: once stable, propagate to canonical `ARCHITECTURE.md` + `SCHEMA.md` + `DECISIONS.md` (ADR) + `MCP_TOOL_CATALOG.md` + `DATA_GOVERNANCE.md` per the doc-update matrix. Harmonize with the existing `SPEC_MIND_PAGE_REDESIGN_2026-06-21.md` (this extends the Mind page, does not replace it).

Infra: single-table DynamoDB `life-platform`, S3 `matthew-life-platform`, Lambda (us-west-2), EventBridge, CloudFront `E3S424OXQZ8NBE`, custom MCP server. New SOT domain = **reading**.

---

## 1. Data model (single-table `life-platform`, new entity types)

IDs: `bookId` = stable hash of ISBN-13 or OLID; fall back to slug(title+author).

**BOOK#`<bookId>`** — catalog item (shared facts) · `PK=BOOK#<bookId>`, `SK=META`
- `title, author, isbn13, olid, pageCount, format` (print|ebook|audio)
- `domainTags[]` (fiction, history, science, philosophy, biography, poetry, business…), `themes[]`, `era`
- `difficulty: { length, density, prose, structure, composite }` (LLM-tagged, recalibrated against his data)
- `coverS3Key` (or null → designed placeholder), `source`, `enrichedAt`

**READING#`<bookId>`** — his relationship to a book (state machine) · `PK=READING#<bookId>`, `SK=STATE`
- `status` (want|reading|finished|abandoned), `startedAt, finishedAt|abandonedAt`
- `abandonReason` (wrong-time|wrong-book|stalled|other) — **strongest negative signal; required on abandon**
- `currentPage, rating, curriculumPhaseAtStart`
- `retentionScore` (**private**, n-gated, nullable), `lastProbeAt`

**READING_SESSION#`<ts>`** — input events (mirror workout sessions) · `PK=READING#<bookId>`, `SK=SESSION#<iso-ts>`
- `date, minutes, pages, location, moodSnapshot` — feeds the input-streak and the mind-body bridge

**READING_NOTE#`<bookId>`#`<noteId>`** · `PK=READING#<bookId>`, `SK=NOTE#<noteId>`
- `type` (highlight|reflection|synthesis), `text, createdAt, public` (bool)

**RECALL#`<bookId>`#`<promptId>`** — spaced retrieval (**private**) · `PK=READING#<bookId>`, `SK=RECALL#<promptId>`
- `prompt, intervalIndex, nextDue (iso)`, `performanceHistory[] ({askedAt, gistScore, note})`

**RECOMMENDATION#`<ts>`** — audit trail / Cora's track record · `PK=READING#REC`, `SK=REC#<iso-ts>`
- `bookId, reasonString, inputsSnapshot, confidence`
- `prediction { finishWindowDays, expectedRating, gapFilled, hopedEffect }`
- `status` (surfaced|accepted|rejected|deferred), `resolvedOutcome` (right|surprised|unexpected|miss), `resolvedAt`

**READING_PROFILE** — calibration state (one item) · `PK=READING#PROFILE`, `SK=CURRENT`
- `tasteHypothesis, ratchetPosition, seasonBias, trustLadderMode` (propose|shortlist|surprise), `wheelDistribution`

**Constellation** — nodes + edges (signature; gated)
- `PK=READING#IDEA#<ideaId>`, `SK=META` → `{ label, sourceBookIds[], embeddingRef, recency }`
- `PK=READING#IDEA#<ideaId>`, `SK=EDGE#<otherIdeaId>` → `{ weight, rationale }`

---

## 2. Access patterns (the table is designed around these)

1. Current reading + queue → `status` via GSI2.
2. Reading history over a date range (trend/streak) → sessions by date via GSI2.
3. All notes for a book → `PK=READING#<bookId>`, `SK begins_with NOTE#`.
4. Due recall prompts (the EventBridge sweep) → **sparse GSI1** on `nextDue`.
5. Roundedness wheel (domain distribution) → finished `READING#` joined to `BOOK#.domainTags`; cache on `READING_PROFILE.wheelDistribution`.
6. Cora's track record → `PK=READING#REC`, `SK begins_with REC#`, filter resolvedOutcome.
7. Constellation graph → `PK begins_with READING#IDEA#`.

---

## 3. GSIs (single-table discipline — add only what the patterns need)

- **GSI1 — recall due (sparse).** Only items with an active `nextDue` project here. `GSI1PK=RECALL_DUE`, `GSI1SK=<nextDue iso>`. Sweep: `query GSI1 where GSI1SK <= now`.
- **GSI2 — reading state/time.** `GSI2PK=READING_STATUS#<status>` (or `READING_SESSION`), `GSI2SK=<iso date>`. Serves current-reading, queue, history-by-date without scans.

No third GSI unless a pattern demands it. Document any addition as an ADR in `DECISIONS.md`.

---

## 4. The recommender — objective function

`fit(book | state)` = weighted sum of normalized component scores, minus penalties:

```
fit =  w_cap     * capacity_fit(book, recovery, deficit, travel, taskload)
     + w_diff    * difficulty_fit(book.difficulty, ratchetPosition, week_color)
     + w_breadth * breadth_gain(book.domainTags, wheelDistribution)
     + w_mom     * momentum_fit(book, current_streak_genre, recent_likes)
     + w_res     * journal_resonance(book.embeddingRef, journal_embeddings)   // §5
     + w_phase   * phase_fit(book, curriculumPhase)
     - p_whip    * whiplash_penalty(book, last_finished)
     - p_rep     * repeat_pattern_penalty(book, last_2_books)
     - p_goal    * goal_domain_penalty(book.domainTags)                       // anti-Goggins
```

- **Weights shift by phase.** Phase 1: `w_cap` + completion-probability dominate; breadth/diff low. Later: breadth/depth rise. Weight sets live on config, versioned.
- **Reason string** = top-N contributing terms in plain language. If `fit` can't decompose, the book isn't surfaced (anti-black-box, hard).
- **Confidence** = f(n_finished, n_abandoned). Below threshold → low-confidence label + **propose-and-dispose only**.
- **Trust ladder** gates autonomy on Cora's audited hit rate (`RECOMMENDATION` outcomes): `propose → shortlist → surprise-me`. Surprise-me unlocks only past a real hit rate. Mode on `READING_PROFILE`.
- Rules-based v1 (transparent, no ML). ML deferred until n≥30 labeled outcomes — and layered *over* the explainable base, never replacing the reason string.

---

## 5. Journal-resonance service

- Embed journal entries (existing journal SOT) + `BOOK#.themes`; cosine similarity → `journal_resonance` weight in §4.
- Surfaces resonant titles with a reason tied to his **own words**.
- **Privacy:** runs entirely within-platform; embeddings/journal text never leave. No external send.
- **Henning gate:** resonance is a *pull weight*, confidence-labeled — never the sole reason.

---

## 6. The mind-body bridge (correlation hooks)

- Join `READING_SESSION#` to sleep/HRV/mood/glucose via the existing `get_cross_source_correlation` machinery; N=1 reading experiments via the existing experiment framework.
- **Correlation honesty (existing thresholds):** direction-only under 2 weeks overlap; Pearson + chip at 2+ weeks. Inverse-aware ember applies.
- Output lives in protocols (experiments/discoveries) and the **private** data view. Never a reason reading must "perform" — reading stays pleasure, not a KPI (Cora's mandate, READING_CALIBRATION §9).

---

## 7. Recall scheduling (EventBridge)

- Expanding intervals per `intervalIndex`; `nextDue` written on each `RECALL#`.
- Daily sweep Lambda queries **GSI1** (sparse, due) → surfaces prompts to the cockpit; on answer, scores gist, appends to `performanceHistory`, advances `intervalIndex`/`nextDue`, updates (private) `retentionScore` once n-gate passes.
- **DST-safe cron** — schedule UTC, guard the local-time boundary.

---

## 8. Cover pipeline

On add: Open Library Covers (ISBN/OLID) → Google Books fallback → **designed placeholder** (generated spine, house palette, display-face title/author). Cache to `s3://matthew-life-platform/covers/<bookId>.jpg`; store `coverS3Key`. Never hot-link.

---

## 9. MCP tool surface (follow the MCP rules)

Hard rules: **tool functions BEFORE the `TOOLS={}` dict**; never register a tool whose function isn't in the same commit; `pytest tests/test_mcp_registry.py` before any MCP deploy; 10-write/conversation cap is metered. Write tools follow **draft → dry_run → commit** (mirror the Hevy routine pipeline).

- Reads: `get_reading_shelf`, `get_reading_recommendation`, `get_reading_profile`, `get_constellation`, `get_reading_history`, `get_due_recalls`, `get_reading_track_record`.
- Writes (draft→dry_run→commit): `add_book`, `update_reading_status`, `log_reading_session`, `add_reading_note`, `answer_recall`, `run_book_debrief`, `log_recommendation_outcome`, `update_reading_profile`.

---

## 10. Public / private split (architectural, not cosmetic)

- **Private** (hidden by default, his toggle): `retentionScore`, all `RECALL#`, the cognitive-reserve/longevity framing, the mind-body correlations. Stored with `visibility=private`; **site-api MUST NOT serve these fields on any public endpoint** — enforced server-side, not just hidden in the UI.
- **Public projection:** currently-reading, finished shelf, `READING_NOTE` where `public=true`, input streak, Constellation.
- A bad retention week is never reachable from the public surface, by construction.

---

## 11. Freshness & integrity

- `get_freshness_status` covers reading sources; green = recency-only, never completeness.
- n-gates everywhere (retention, wheel, Constellation). Empty/green = hypothesis → verify by direct read.

---

## 12. Doc-update consequences (when this lands)

CHANGELOG + PLATFORM_NORTH_STAR/BACKLOG (always). ARCHITECTURE + SCHEMA + DECISIONS (new data model). DATA_GOVERNANCE (new `reading` SOT domain + private fields). MCP_TOOL_CATALOG + OPERATOR_GUIDE (new tools). COST_TRACKER if new services (embeddings, cover cache). Archive this draft to `docs/archive/` once folded into canon.

---

*Cross-reference: BRIEF_2026-06-29_reading_mind, READING_CALIBRATION, CLAUDE_CODE_PROMPT_READING_MIND_v1.*
