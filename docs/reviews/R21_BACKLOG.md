# R21 — Definitive Product + Technical Review (review record)

> **The backlog lives on GitHub Issues, not in this file (ADR-099).** Converted 2026-07-06:
> **epics #715–#723** (`type:epic`) + **stories #724–#758** (`type:story`, `model:*` labels, Now/Next/Later
> milestones), plus pre-existing #409 (→ epic #719) and #687 (→ epic #722). This file remains as the
> review's evidence record and executive summary only — do not work items from here.

**Date:** 2026-07-06 · **Reviewer:** Fable 5 (7-phase panel review) · **Evidence basis:** live site probes (15-fetch budget), MCP instrument reads, sampled code reads (layer v115, ~94 Lambdas), CI/cost/IAM pulls. Full phase ledgers in the session transcript/handover.
**Grading standard:** every claim below was verified in-session or is labeled. Confidence: High unless noted.

---

## Executive summary (one page)

**Overall grade: B.** The engine is elite and honest; the science it promises is stalled at zero; the audience loop is plumbed but the proof is invisible to anyone who skims. The gap between what this platform *is* and what a 90-second visitor (or crawler) can *see* is the whole review.

**The three findings that matter most:**

1. **The scientific credibility engine is not turning** (Phases 3-4). As of 2026-07-06: 0 experiments registered, 88 predictions all-pending with LLM-hallucinated IDs and target dates (2024/2025 dates on 2026 predictions — `intelligence_common.py:1537` lets the model author its own metadata, violating the platform's own ADR-106 "only code ships" rule), 0 graded outcomes in the 60-day track-record window, evaluator running daily and grading nothing. The site sells "track records, disagreements, falsifiable predictions"; the ledger is empty. The C-3 gradability fix (2026-07-05) addressed routing but not metadata.
2. **The proof layer is invisible to the skim** (Phase 2). Scorecard, chronicle list, predictions — all JS-only shells to crawlers, LLMs, and impatient skeptics. `/method/` is a nav hub with zero integrity content. No protagonist above the fold (no who, no stakes, no 16-attempts arc, no finish line). The best writing ("The Wall") has no subscribe CTA, no permalink in the sitemap, and RSS chronicle items link to the hub. Distribution: RSS fixed and alive; permalink/SEO/CTA plumbing still broken.
3. **Operational integrity is dark at the exact wrong layer** (Phase 4). Main CI: 30/30 recent runs non-success (one ruff error masking every downstream gate) while ~20 layer versions deployed out-of-band. Budget tier 1 is live *tonight*: coach narratives paused — the product's soul is the first thing the ceiling sacrifices, and the June breach was dev-caused, not reader-caused.

**The counterweight (what survives a hostile reviewer):** the honesty layer is real — deterministic number-gates on every narrative, staleness stamps everywhere, honest nulls (`pillar_coupling` omits thin pairs), a blocking quality gate with enforced cross-coach distinctiveness, and a live `board_ask` that grounds, defers across lanes by name, and admits its own data gaps. The persona layer is at or near 2026 state of the art. The AI-operated-org discipline (handovers, adversarial verification, ~50 verified stories in 3 days) is itself a market-grade asset.

**Single highest-leverage move:** code-stamp prediction metadata and grade the first prediction publicly (Epic 1, issues 1.1-1.5). It is small (S/M), it makes the platform's central claim *true*, and every distribution/story epic downstream gets its proof from it.

**Strongest surviving dissent:** the **Research Scientist** holds that rigor must come first — distributing an empty scorecard is marketing a lab with no experiments, and regression-to-the-mean makes the 17th attempt indistinguishable from success without pre-registration. The **Editor and Investor** hold that distribution must come first — audience compounds slowest, the rigor is currently invisible anyway, and a perfect experiment nobody reads proves nothing publicly. Synthesis (not a blend — a sequencing): Epic 1 is small enough to do *first and fast*, then Epic 2/7 ship its output. Both chairs signed off on the ordering; neither on the other's framing.

**Panel scoring: Value-to-thesis (1-5) × Reader-visible (1-5) ÷ Effort (1-5).**

| # | Epic | V | R | E | Score | Size |
|---|------|---|---|---|-------|------|
| E2 | Proof visible to the skim | 5 | 5 | 3 | **8.3** | M |
| E7 | Distribution engine | 4 | 4 | 2 | **8.0** | M |
| E1 | Make the science turn | 5 | 4 | 3 | **6.7** | M |
| E5 | Budget that protects the product | 4 | 3 | 2 | **6.0** | S |
| E9 | The career artifact | 4 | 3 | 2 | **6.0** | S/M |
| E6 | Falsifiable honesty layer (evals) | 4 | 2 | 2 | **4.0** | S/M |
| E4 | Fulfillment instrumentation | 5 | 3 | 4 | **3.8** | L |
| E3 | Release integrity | 4 | 2 | 3 | **2.7** | M |
| E8 | Perimeter close-out | 3 | 1 | 2 | **1.5** | S |

**Sequence (dependency-ordered, not pure score):** E3.1 (minutes, unblocks everything) → **E1** → **E2** → **E7** → E5 → E9 → E6 → E4 → E3 rest → E8. E4 is the thesis's differentiating half but needs Matthew's participation design first — start the *decision*, not the build, now.

**Next 3 Claude Code sessions:**
1. **Session A = E3.1 + E1** (green main, prediction integrity, first graded prediction, scorecard honest-state). Well-scoped, mostly deterministic.
2. **Session B = E2** (static proof render, /method/ trust page, protagonist fold, permalink unification). The flagship reader slice.
3. **Session C = E7 + E5.1/5.2** (audio debrief repoint, build-beat ritual, /verify/ page; budget tier re-order + brief hash-reuse).

---

## The epics

### E1 — Make the science turn (prediction & experiment integrity) — M
**Thesis impact:** the platform's central promise — falsifiable, scored, public N=1 science — is currently unproven; this epic makes it true.
**Success criteria:** ≥1 publicly visible graded prediction with a hit-rate number; ≥1 pre-registered experiment running with a timestamped public artifact; zero predictions in the store with past-or-null target dates; a liveness alarm that fires if grading stalls again.

- **1.1 Code-stamp prediction metadata** — remove `prediction_id`/`target_date` authorship from the LLM prompt (`intelligence_common.py:1537`, `:187`); code stamps ID = `pred_{today}_{semantic-slug-hash}`, validates `target_date` strictly future or rejects/repairs; semantic dedup key stops daily re-emission. AC: writer unit tests pin stamping; a seeded wrong-date LLM output is repaired or dropped; no new record can be ungradeable-by-construction. *Agent: Claude Code (Sonnet fine).* Deps: none.
- **1.2 Void the legacy prediction partition** — archive `SOURCE#coach_thread#` predictions (cycle-stamped per ADR-077 convention); migrate `mcp get_predictions` to `COACH#`. AC: MCP and public read the same store; legacy tombstoned, not deleted. *Claude Code.* Deps: 1.1.
- **1.3 Scientific-liveness heartbeat** — evaluator emits `decided_count`/`gradable_count` EMF; 14-day zero-decided heartbeat alarm (pattern: `monitoring_stack.py:_heartbeat_alarm`). AC: alarm exists, tested via metric math; fires on the *current* state if deployed today. *Claude Code, no-LLM logic.* Deps: none.
- **1.4 First pre-registered experiment, with a stopping rule** — register one experiment via `create_experiment` with a public S3 pre-registration artifact (timestamp, hypothesis, metric, window, stopping rule). Include the regression-to-the-mean defense in the design (Phase 6, Research Scientist). AC: artifact publicly fetchable; the experiment page renders it. *Fable-chat design + Matthew's choice of experiment; Claude Code ships.* Deps: none.
- **1.5 Scorecard honest empty state** — public scorecard states "evaluator live since {date}; N pending; 0 graded yet" instead of blanks (ADR-104 applied to the meta-layer). AC: no-JS HTML carries the sentence. *Claude Code.* Deps: 1.1 (numbers), E2.1 (render path) soft.

### E2 — Proof visible to the skim (static proof layer + trust page + protagonist) — M
**Thesis impact:** converts existing integrity into something a 90-second skeptic, Google, and LLM crawlers can actually see; the review's highest score.
**Success criteria:** curl (no JS) of home/method/scorecard/chronicle returns the headline numbers, the human, the trust mechanics, and a dated post list.

- **2.1 Static-render the proof surfaces** — at generation time (the OG-image/public_stats pattern already exists), bake current key numbers, scorecard summary, and the chronicle post list into served HTML (generated/ prefix per ADR-046); JS enhances rather than creates. AC: `curl /coaching/scorecard/ | grep` finds real numbers; chronicle list crawlable. *Claude Code.* Deps: 1.5 for content.
- **2.2 `/method/` becomes the trust document** — write the page the skeptic came for: the number-gate, pre-registration, quality gate, budget honesty, N=1 caveats, AI failure modes, "what would falsify this." Material all exists (ADR-104/105/108). AC: every Phase-2 "missing trust element" answered on one page. *Fable-chat writes; Claude Code ships.* Deps: none.
- **2.3 Protagonist above the fold** — who Matthew is, the 16-episodes arc, current stakes, and a provisional finish line (Phase 6 Skeptical Reader blind spot: "a documentary needs a third act"). AC: cold HTML answers "why this person, what's at stake, what's winning." *Matthew + Fable-chat copy; Claude Code ships.* Deps: Matthew's finish-line decision.
- **2.4 Permalink unification** — collapse the chronicle/journal dual identity (kill list, Phase 2); one URL scheme; all posts in sitemap; RSS items link permalinks; subscribe CTA + share affordance on every post page. AC: newest post reachable from RSS in one click; sitemap contains post URLs. *Claude Code (Sonnet).* Deps: none.

### E7 — Distribution engine (wedge-B plumbing) — M
**Thesis impact:** the site currently converts nobody because nothing travels; these are the cheapest channels that don't need the JS-shell fixed.
**Success criteria:** one recurring outbound artifact/week with zero marginal Matthew-effort; a /verify/ page; measurable subscriber growth (traffic digest already live).

- **7.1 Weekly build-beat as a wrap-gate** — the #380 checklist exists; make the session-wrap convention *require* the one-beat dispatch (merged work only). *Process + Sonnet mechanical.* Deps: none.
- **7.2 Daily audio debrief** — repoint the existing TTS pipeline (Chirp+Gemini, fail-closed) from weekly panelcast to a 2-minute daily "state of Matthew"; podcast feed = the distribution channel crawlers can't miss. **Kill attached:** panelcast weekly cadence → event-driven or retired (its no-episode alarm has been in ALARM since June). *Claude Code.* Deps: none.
- **7.3 `/verify/` page** — cross-links to device-platform public profiles, published `get_device_agreement` output (two devices disagreeing slightly = unfakeable authenticity), raw-JSON samples. *Claude Code.* Deps: none.

### E5 — A budget that protects the product — S
**Thesis impact:** the ceiling currently turns off the product first (tier 1 live during this review); at any success it becomes an auto-outage.
**Success criteria:** reader-facing AI is the *last* casualty; recurring inference cost per unchanged day ≈ 0.

- **5.1 Re-order the tiers** — dev/ensemble/internal pause before `board_ask`/narratives. *Claude Code; small ADR.* 
- **5.2 Hash-and-reuse unchanged briefs** — skip regeneration when the generation brief hash is unchanged (the quiet-stretch case). *Claude Code.* 
- **5.3 #409 batch API** — already queued; layer bump, attended. 
- **5.4 Surge-mode rule** — pre-decide the ceiling's behavior when 7-day uniques cross a threshold (traffic digest already measures). *Decision + 20 lines.*

### E9 — The career artifact (highest-EV wedge) — S/M
**Thesis impact:** the AI-operated-org story is the platform's most novel asset and runs on existing exhaust; it's also the proof that survives even if the weight arc stalls.
**Success criteria:** one essay/talk shipped externally; measured travel.

- **9.1 Distill "the org chart of one human + N agents"** from handovers/gates/failure lessons (the #408 tangle included — failures carry the credibility). *Fable-chat.* 
- **9.2 Publish + measure.** *Matthew.* Deps: 9.1.

### E6 — Falsifiable honesty layer (eval harness) — S/M
**Thesis impact:** "560 checks, 0 flags" is currently unfalsifiable; this makes the moat provable and safe to change.
**Success criteria:** seeded fabrications are caught; prompt/model changes replay a golden set before deploy.

- **6.1 Golden-brief harness + seeded-fault canaries** — ~30 frozen briefs × 8 coaches replayed via batch API on prompt/model/gate change; 5 mutated briefs assert the number-gate *catches* induced fabrication. *Claude Code.* Deps: 5.3 helpful (batch pricing).
- **6.2 Grounding receipts on board_ask** — one-line "grounded in: …" footer per answer. *Claude Code.* 
- **6.3 Retain verdict/regeneration pairs** — stop discarding the labeled dataset (S3, cycle-stamped). *no-LLM.*

### E4 — Fulfillment instrumentation (the differentiating half) — L
**Thesis impact:** connection/mood/fulfillment currently has architecture and no data (0 social logs; 41-day journal silence; 1 datapoint/90d); the thesis's second half has no evidence stream.
**Success criteria:** a fulfillment signal that survived one bad week; relationships pillar no longer silently flat-50.

- **4.1 Decision first:** choose the capture channel with the Ethicist's constraints (voice memo→HAE state-of-mind path exists; calendar/passive proxies; or an accepted ritual). *Matthew + Fable-chat. Blocks the rest.*
- **4.2 Manual-source reliability engineering** — staleness nudges (the now-fixed evening nudge), degraded-mode display, "manual source dark N days" surfaced kindly. *Claude Code.*
- **4.3 Honest pillar state** — public "not yet instrumented" for relationships instead of flat-50. *Claude Code, small.*
- **4.4 Publish the fulfillment story** once ≥4 weeks of data flows. *Fable-chat + Matthew.* Deps: 4.1-4.3.
- **Ethicist gate (standing):** decide how much of this half publishes *when it's bad*, before it's bad.

### E3 — Release integrity — M
**Thesis impact:** the honesty moat depends on gates that actually run; 30/30 red with out-of-band deploys is integrity theater.
**Success criteria:** 30 consecutive green main runs; site deploys via CI; drift check automated.

- **3.1 Fix the ruff import-sort error; get main green.** *Sonnet, minutes. Do first, today.*
- **3.2 Decouple the gate chain** — fast deploy-critical test subset gates deploy; full suite + visual-QA run independently (cicd-01). *Claude Code.*
- **3.3 Site deploy in CI** on merge (cicd-02) + wire `rollback_site.sh` into the failure path. *Claude Code, attended (touches deploy).* 
- **3.4 main==live reconciliation** — scheduled `/version.json` ancestry check (cicd-03). *no-LLM script.*

### E8 — Perimeter close-out — S (hygiene batch, risk-driven not score-driven)
- **8.1 #687 OIDC trust tighten** (attended, watched live CI run — already queued).
- **8.2 GitHub Pages decision** (10 minutes; carried unactioned for weeks).
- **8.3 MCP write-audit trail** — mutations (log_*/update_*/delete_*) logged to S3 audit (Phase 6 Red Team blind spot: the trusted write path has no trail). *Claude Code.*
- **8.4 Remediation agent: `auto` → `shadow`** until it earns its cost (zero merged PRs in ~6 weeks as of 07-03; re-verify first). *Decision + SSM.* 
- **8.5 Exercise one DR restore** — the doc exists; a tested restore doesn't (verify claim first). *Attended.*

---

## Consolidated kill list (all phases)

1. LLM-authored prediction metadata (`intelligence_common.py:1537`) → code-stamped (E1.1). **High**
2. Legacy `SOURCE#coach_thread#` prediction partition → archived (E1.2). **High**
3. Chronicle/journal dual identity → one permalink scheme (E2.4). **High**
4. Daily narrative regeneration on unchanged briefs → hash-and-reuse (E5.2). **High**
5. Weekly human-in-loop panelcast cadence → event-driven or retired (E7.2). **Medium**
6. `log_interaction` as the fiction of Pillar-7 instrumentation → re-source or honestly mark uninstrumented (E4.1/4.3). **High**
7. Remediation agent `auto` mode → `shadow` until it produces (E8.4). **Medium — re-verify output since 07-03 first**
8. Parked `hevy-webhook` FunctionURL → delete until Hevy ships webhooks. **Medium**
9. The strict all-or-nothing CI chain → decoupled (E3.2). **High**
10. Standing multi-model LLM Council → formally not-doing (ADR non-decision); narrow pre-publication verifier allowed. **Medium**
11. PERMA/Seligman citation garnish on n=1-day data → cut until n exists. **Medium**

## Open-questions register (verified-by-nobody; do not treat as findings)

- Do rendered (JS-on) pages show scorecard/track-record content today, and what does board_ask UI show as receipts? (Browser was unavailable; Playwright harness can answer offline.)
- Do `/method/` sub-pages (board/biology/benchmarks) already carry some trust content the hub lacks?
- Has any evaluation accrued since the 07-05 C-3 fix? (Needs days; check before building E1.5 copy.)
- Current confirmed-subscriber count (last verified 1, on 2026-07-03).
- Has a DR restore ever been exercised? GitHub Pages contents?
- Whether all 8 coaches' track records are empty (sampled: sleep).
- June's $79.8 breach attribution detail and per-surface Bedrock split (needed for E5/#409 sizing).

---
*R21 close-out: sync this file into docs/README.md index · update HANDOVER_LATEST.md · CHANGELOG entry · commit via the normal PR path (this file only; no code changed by the review). The review made zero mutations to code, data, or infrastructure.*
