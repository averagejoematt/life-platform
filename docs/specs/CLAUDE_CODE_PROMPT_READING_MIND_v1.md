# CLAUDE_CODE_PROMPT_READING_MIND_v1.md
**The Mind Pillar (Reading) — phased build plan + paste-ready Phase A prompt.**
Repo path: `docs/specs/CLAUDE_CODE_PROMPT_READING_MIND_v1.md`
Status: DRAFT v0.1 · 2026-06-29
Read first, in order: `docs/briefs/BRIEF_2026-06-29_reading_mind.md`, `docs/coaching/READING_CALIBRATION.md`, `docs/SPEC_READING_MIND_2026-06-29.md`.
> **Persona note (reconciled 2026-06-30):** archetype names herein (Lena / Priya / Nadia / Crowe / Theo / Mara) are **superseded** — reading coach is **Dr. Cora Vance** (`cora_vance`); see `docs/coaching/READING_CALIBRATION.md` §9 and `docs/BOARDS.md`. Kept as the original build record.

---

## 0. Norms (platform law — non-negotiable)

- **Deploy convention.** Write deploy scripts to `deploy/`; Matthew runs them in terminal. **Never execute deploy scripts via MCP.** `deploy/deploy_lambda.sh` auto-reads handler config from AWS — never hardcode zip names. Wait 10s between sequential Lambda deploys.
- **MCP rule.** Tool functions BEFORE the `TOOLS={}` dict. Never register a tool without its function in the same commit. `pytest tests/test_mcp_registry.py` before any MCP deploy.
- **Write tools.** draft → dry_run → commit; show the preview with an "inputs current through X" line; commit only on explicit confirmation. 10-write/conversation cap is real.
- **Anti-black-box.** Every composite decomposes to inputs. Every recommendation carries a reason string. Charts/Constellation refuse under their data thresholds with honest empty states.
- **Design law.** Ember = on-protocol/alive; muted ink = neutral/off-pace; **red = STATE alerts only — reading has no red states.** The reader's own words are the loudest type on the page.
- **Correlation honesty.** Direction-only under 2 weeks overlap; Pearson + chip at 2+ weeks; inverse-aware ember.
- **Henning standard.** Correlational only; confidence-labeled; n<30 = low confidence; no causal language.
- **Session ritual at end:** update `PLATFORM_FACTS` in `deploy/sync_doc_metadata.py` if counts changed → `python3 deploy/sync_doc_metadata.py --apply` → write handover + update `handovers/HANDOVER_LATEST.md` → update `CHANGELOG.md` → `git add -A && git commit && git push`.

---

## 1. Build order (dependency-correct; one phase per session)

### Phase A — Data layer (no UI)
- CDK: add the new reading entity patterns + **GSI1 (sparse recall-due)** + **GSI2 (state/time)** to `life-platform`. Additive / migration-safe only.
- Cover pipeline Lambda: Open Library → Google Books → designed placeholder; cache to `s3://matthew-life-platform/covers/`.
- Book enrichment: LLM tagging of `domainTags`, `themes`, `difficulty` subscores on add.
- **Acceptance:** all entity types read/write; covers cache with placeholder fallback; no public endpoint exposes `visibility=private` fields (test included); access patterns in spec §2 tested.
- **Deploy:** `deploy/deploy_reading_data.sh` (CDK diff first).

### Phase B — Engine + MCP (no site)
- MCP tools per spec §9 (functions before `TOOLS`; registry test green).
- **Recommender v1 — rules-based, transparent** (objective fn spec §4; reason strings; confidence + propose-and-dispose gating; trust-ladder state).
- **Onboarding interview** (calibration §8) — taste archaeology → `READING_PROFILE.tasteHypothesis`.
- **Acceptance:** a recommendation returns a decomposed reason string + confidence label; goal-domain books de-prioritized by default; low-n forces propose-and-dispose. `pytest tests/test_mcp_registry.py` green.
- **Deploy:** `deploy/deploy_reading_mcp.sh`.

### Phase C — Mind page + cockpit thread
- `/mind/`: shelf (warm spines, designed placeholders), roundedness wheel, difficulty ratchet, input-streak. Honest empty states by default.
- Cockpit `/now/`: today's reading line — current cover, "read today" tick, due recall prompt slot.
- Home: Mind becomes the seventh pillar, edges to Recovery/Mood.
- **Read the frontend-design skill (and `DESIGN_SYSTEM_V5.md`) before writing any component.** Spend boldness only on the signature (Phase E); keep C disciplined.
- **Acceptance:** mobile-responsive; reduced-motion respected; no red anywhere in reading; private fields never rendered publicly; empty states read as invitations; meets `A11Y_BASELINE.md`.
- **Deploy:** site build → CloudFront `E3S424OXQZ8NBE` invalidation via existing pipeline.

### Phase D — The loop
- **Debrief** as a Third Wall instance (Lena hoped ↔ how it hit); writes public takeaway + resolves the `RECOMMENDATION` prediction.
- **Recall scheduling** on EventBridge (sparse GSI1 sweep, expanding intervals, DST-safe).
- **Private retention** (gist + changed-prior, n-gated) on the private data view + difficulty-ratchet feedback.
- **Acceptance:** two clocks never merged in UI; retention score doesn't render until n-gate passes; recall prompts surface in the cockpit when due; abandons capture a reason.
- **Deploy:** `deploy/deploy_reading_loop.sh` + EventBridge rule (UTC, DST-guarded).

### Phase E — Gated backlog (signature + dazzle, earned)
Build only once the loop is proven on real data (Mara's gate): the **Constellation** (signature; honest single-point empty state; ember=recency; reduced-motion = instant settle), **journal-resonance** (embeddings, within-platform only), **mind-body bridge** (reading×sleep/HRV/mood experiments, correlation-honest), **voice debrief**, **mnemonic medium** (synthesis → spaced-repetition artifact).

---

## 2. Guardrails (check every phase)

Anti-black-box reason strings · red only for STATE (none in reading) · two-clock retention, n-gated, private-by-default · public/private enforced server-side · preserved dissent on the coaching page (Lena vs Maya; Nadia vs Priya; Mara's restraint) — **reconcile personas against `docs/BOARDS.md` first** · honest empty states everywhere · correlational + confidence-labeled.

---

## 3. Definition of done (per phase)

Tests green (incl. `test_mcp_registry` for any MCP change) · acceptance met · deploy scripts to `deploy/` (NOT executed via MCP) · docs updated per the matrix (spec §12) · handover + CHANGELOG written · committed and pushed.

---

## 4. PASTE-READY — PHASE A ONLY

```
Read these four docs in full before doing anything, in this order:
  docs/briefs/BRIEF_2026-06-29_reading_mind.md
  docs/coaching/READING_CALIBRATION.md
  docs/SPEC_READING_MIND_2026-06-29.md
  docs/specs/CLAUDE_CODE_PROMPT_READING_MIND_v1.md
They are canon. Do not invent structure that contradicts them. If something is
ambiguous, stop and ask me — do not guess.

TASK: Build PHASE A only (the reading data layer). Nothing from later phases.
Per the build plan §1 Phase A:
  - CDK: add the new reading entity patterns + GSI1 (sparse recall-due) and
    GSI2 (state/time) to the life-platform table. Additive/migration-safe only.
  - Cover pipeline Lambda: Open Library -> Google Books -> designed placeholder;
    cache to s3://matthew-life-platform/covers/. Never hot-link.
  - Book enrichment on add: LLM-tag domainTags, themes, difficulty subscores.
  - Entities + visibility per SPEC_READING_MIND_2026-06-29 sections 1 and 10.

NON-NEGOTIABLE NORMS:
  - Write ALL deploy steps as scripts to deploy/ for ME to run in terminal.
    DO NOT execute any deploy script yourself. CDK diff before apply.
  - No public endpoint may serve any field marked visibility=private. Enforce
    server-side, and add a test that proves it.
  - Write tests for every Phase A access pattern in the spec section 2.
  - Do NOT touch the MCP tool registry in this phase (that is Phase B).

ACCEPTANCE (all must pass before done):
  - All reading entity types read/write correctly.
  - Covers cache, with the designed placeholder on miss.
  - Private fields provably unreachable from any public path (test included).
  - All new tests green.

WHEN DONE, run the session ritual:
  - Update PLATFORM_FACTS in deploy/sync_doc_metadata.py if counts changed,
    then python3 deploy/sync_doc_metadata.py --apply
  - Update CHANGELOG.md; note ARCHITECTURE/SCHEMA/DATA_GOVERNANCE deltas per the
    doc-update matrix (reading is a new SOT domain).
  - Write the handover and update handovers/HANDOVER_LATEST.md.
  - git add -A && git commit && git push.
  - Then give me the list of deploy scripts to run, in order, and stop.
```

---

*Cross-reference: BRIEF_2026-06-29_reading_mind, READING_CALIBRATION, SPEC_READING_MIND_2026-06-29.*
