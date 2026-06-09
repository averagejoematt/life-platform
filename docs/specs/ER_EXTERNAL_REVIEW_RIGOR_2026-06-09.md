# SPEC — External-Review Rigor Series (ER-01 … ER-08)

**Date:** 2026-06-09
**Source:** A deliberately *external* technical-review lens applied to the platform (2026-06-09 session) — i.e. "how would ~10 real senior engineers, who do **not** share the platform's own rubric, react to this codebase?" Distinct from the internal Technical Board reviews (R1–R20), which are self-assessment against a rubric the platform authored.
**Scope:** Engineering rigor + honesty hardening. **Not** feature expansion. Every item here makes *existing* capability more trustworthy; none adds new analytic surface. This matters for the PG build-cap: rigor that de-risks what already ships is sanctioned even when net-new engines are not.
**Backlog home:** `docs/BACKLOG.md` → "🔬 External-Review rigor (ER-series)".

---

## Why this exists (the one-paragraph version)

The internal board has graded the platform A- for several reviews running, monotonically upward. An external panel would not dispute the *craft* — the IaC discipline (`create_platform_lambda` factory, per-function least-privilege IAM, OIDC with no long-lived keys), the single AI chokepoint with a hard budget ceiling, the single-table hygiene, and the clean, well-commented code are genuinely strong and rare for a solo build. What an external panel **would** refuse to drop is a specific cluster of findings that is *objective*, not aesthetic:

1. A data source died silently for 44 days and nothing screamed (observability has a real hole).
2. Test coverage is ~10% and the thin part is at the **upstream-API seams** — exactly where the next silent failure hides.
3. QA verifies that pages *render*; nothing verifies that the AI's *advice is correct* (correlative-only, confidence-labelled, no fabricated numbers). For a system whose entire output is AI judgment, the testing is inverted.

Everything else an external panel would say (too many ADRs, wrong database, over-provisioned for N=1, self-referential grading) is *arguable* and resolves to "depends what the project is for." The three above are not arguable. ER-01/02/03 close them. ER-04…08 address the arguable critiques by forcing a **recorded decision** rather than letting the answer stay implicit.

---

## How Claude Code should work an ER item (each session)

1. **Open:** read `handovers/HANDOVER_LATEST.md` then `CLAUDE.md`; confirm `main` is clean/pushed before starting.
2. **Scope:** ONE ER item per session unless trivially coupled. ER-01/02/03 are the priority tier — do these before the others. Confirm the item's gate is met.
3. **Rigor rule (the whole point):** these items are held to the standard they enforce. No causal language in any copy or comment that ships as part of them; computation in Python, never in an LLM; `N<30` low-confidence, `<12` preliminary (Henning standard). An eval harness that itself fakes confidence is worse than none.
4. **Deploy discipline (unchanged):** Matthew runs all deploys in terminal — never via MCP. Layer modules require a rebuild + `SHARED_LAYER_VERSION` bump. 10s between sequential Lambda deploys. New tests must run **offline** (no live AWS) so CI can gate on them.
5. **Close:** update `CHANGELOG.md` + `PROJECT_PLAN.md`; ADR in `docs/DECISIONS.md` where the item calls for one; `python3 deploy/sync_doc_metadata.py --apply` if counts changed; write handover; move the finished ER item out of `BACKLOG.md` into `CHANGELOG.md`.

---

## Priority tiers

| Tier | Items | Rationale |
|---|---|---|
| **1 — the objective gap** | ER-01, ER-02, ER-03 | The findings no external reviewer would drop. Highest value. |
| **2 — cheap honesty** | ER-05, ER-06 | Low effort, high credibility return. |
| **3 — recorded decisions** | ER-04, ER-07 | Convert "arguable" critiques into explicit, defensible choices. |
| **4 — defer-leaning** | ER-08 | Document the choice; don't migrate. |

---

## ER-01 — Infra-liveness heartbeat (the 44-day-outage class)  · **Tier 1** · Effort M

**Problem.** The Garmin outage ran 44 days unnoticed. The existing `freshness_checker_lambda.py` + `slo-source-freshness` alarm are **behavioral-freshness** checks ("is the newest `DATE#` record recent?"). They are structurally noisy on a personal platform because "no new data" is ambiguous — it can mean *the user didn't log / wear the device* (benign) **or** *the ingestion Lambda has been erroring on every run for weeks* (critical). That ambiguity is exactly why the signal got ignored until the gap was 44 days wide. (See S-06 / N-01 in BACKLOG — the team already noticed the alarm is "structurally noisy.")

**The missing signal is infra-liveness, not data-freshness.** For each *active OAuth/API* source, assert that the ingestion Lambda **ran and completed its upstream fetch without error** on its expected schedule — independently of whether new data came back. A source where the API call 200s but returns an empty set is *healthy*; a source whose OAuth refresh has been 401/429-ing for a week is *dead* even if the user also happened not to log anything. Today nothing distinguishes these.

**Approach.**
- Each ingestion Lambda already runs under the SIMP-2 `ingestion_framework`. Have the framework emit a structured per-run outcome to a dedicated DDB sentinel key (e.g. `USER#system / INGEST_HEALTH#{source}`) **and** an EMF metric: `last_success_ts`, `last_attempt_ts`, `consecutive_failures`, `last_error_class` (auth / throttle / transport / parse).
- A single daily `pipeline_heartbeat` check (extend `pipeline_health_check_lambda.py`, don't add a Lambda) reads those sentinels and asserts, per active source: `consecutive_failures < threshold` AND `last_attempt_ts` within `(schedule_interval × 2)`. A source that simply *stopped being scheduled* is the worst case and must be caught (the heartbeat is the thing that notices the cron silently stopped).
- Escalate on a **streak**, not a single blip (the existing canary 2-consecutive-fail buffer pattern is the precedent — reuse it). Streak ≥ 3 of the same source's `auth`/`throttle` class → distinct alert subject (you don't run a pager, so make it unmissable in the digest); single blips stay silent.
- Keep behavioral-freshness and infra-liveness as **two separate metrics** with two separate alarms. This is the S-06 (b) option, now mandatory rather than optional.

**Files.** `lambdas/ingestion_framework.py` (emit outcome), `lambdas/operational/pipeline_health_check_lambda.py` (the heartbeat assertion), `cdk/stacks/monitoring_stack.py` (the new infra-liveness alarm + metric-math), `lambdas/operational/freshness_checker_lambda.py` (ensure it stays behavioral-only).

**Acceptance.**
- Simulate a source's ingestion failing on every run (mock the upstream to 401): heartbeat flips that source to a failure streak and emits the distinct alert within ≤ 2 expected intervals — **with zero new `DATE#` data required to trigger it.**
- A source the user genuinely didn't feed (no new data, but the Lambda ran and 200'd) does **not** alert.
- A source whose schedule is silently removed is caught by the `last_attempt_ts` staleness arm.
- Offline unit tests for the health-decision function covering all four error classes + the streak buffer.

**Gate.** None. Do first.

---

## ER-02 — Upstream-API contract tests (recorded-response fixtures)  · **Tier 1** · Effort M

**Problem.** The ingestion `transform()` unit tests (the ~14 added in the blind-spot sweep) pin *your* logic against a **fixed input** — they prove that given payload X you write DDB shape Y. They do **not** notice when the vendor changes payload X out from under you (a field rename, a nesting change, a type change). That class of drift currently corrupts data silently and is only caught downstream, if ever. This is the literal mechanism of the next 44-day-class incident.

**Approach.**
- Capture one real (scrubbed) response per endpoint per active source as a **recorded fixture** under `tests/fixtures/upstream/{source}/{endpoint}.json`. Scrub PII/tokens; keep structure.
- Write contract tests that assert the **shape contract** the transform depends on: required keys present, types correct, nesting intact, enum/units stable. The test fails loudly when a fixture refreshed from live no longer matches — i.e. when the vendor drifted.
- Provide a `deploy/refresh_upstream_fixtures.py` that re-pulls live, re-scrubs, and shows a diff, so refresh is a deliberate, reviewed act — the diff *is* the drift report.
- Prioritise the sources whose silent drift hurts most: Whoop (multi-endpoint: recovery/sleep/cycle/workout), Withings (the SCHEMA.md cross-check in L-08 already found 3 query-breaking wrong field names — demonstrated history), Apple Health / HAE (L-08 found the XML table 6-of-7 wrong).

**Files.** `tests/fixtures/upstream/**`, `tests/test_upstream_contracts.py`, `deploy/refresh_upstream_fixtures.py`, wire into `.github/workflows/ci-cd.yml` as a **gating** offline job (no live calls in CI — it asserts against committed fixtures).

**Acceptance.**
- Each active source has ≥1 committed fixture + a contract test asserting its shape.
- Hand-mutating a fixture (rename a field the transform reads) makes its contract test fail.
- The refresh tool produces a human-readable diff and never writes tokens/PII into a fixture (a scrub assertion guards this).

**Gate.** None. This is the "recorded-response contract tests for upstream APIs" already flagged in the handover as the next testing step.

---

## ER-03 — AI-output eval harness (the "is the advice correct" gap)  · **Tier 1** · Effort M–L

**Problem.** `tests/visual_ai_qa.py` verifies that pages *render*. Nothing verifies that the coach/insight **content** obeys the standard the platform sells: correlative-only (never causal), confidence-labelled, no number that wasn't in the input, no math the LLM did itself. For a system whose entire value proposition is *honest* AI judgment, this is the single most important untested surface — and it's the one the internal board structurally can't see, because the board is the same kind of AI being asked to grade.

**Framing (keep it on the right side of the build-cap).** This is **not** a new analytic engine. It is a truthfulness gate on engines that already ship. Reeves/Viktor's "build-itch" flag does not apply: ER-03 adds *scrutiny*, not capability.

**Approach (two layers, cheap first).**
- **Layer 1 — deterministic guards (do first, ~zero inference cost):** an offline harness that feeds fixture inputs (a fixed day's metrics, a known-empty genesis week, a sparse-data week, an outlier week) through the coach/insight code paths (`ai_calls` / `ai_summaries` / `coach_computation_engine`), captures outputs, and asserts:
  - no causal connectives from a banned list ("because", "causes", "leads to", "drives", "due to") applied to correlations, outside whitelisted contexts;
  - every quantitative claim carries a confidence/sample qualifier when `N<30`, and "preliminary" when `<12`;
  - **every number in the output appears in the input** (the anti-fabrication assertion — highest-value single check; an LLM inventing a plausible figure is the failure that most damages the honesty thesis);
  - no output starts with "Matthew" (the known prompt-drift bug already in the backlog).
  Same *pattern* as `tests/test_ai_endpoint_hardening.py` (invariant guards) but applied to generated *output* on fixtures, run offline.
- **Layer 2 — LLM-judge against a rubric (optional, budget-gated):** a Haiku judge scores outputs against an explicit rubric (faithfulness, calibration, no causal overreach) and fails below threshold. Gate behind the budget tier (must self-skip at tier ≥ 2, same as the vision QA) so it can never empty the ceiling or false-block.

**Files.** `tests/fixtures/ai_inputs/**`, `tests/test_ai_output_faithfulness.py` (Layer 1, offline, **gating**), `tests/ai_judge_qa.py` (Layer 2, advisory, budget-gated). Extend `lambdas/ai_output_validator.py` if its assertions overlap rather than duplicating.

**Acceptance.**
- Layer 1 runs offline in CI and gates. Seeding a fixture-output with a fabricated number, a causal claim on a correlation, or an unlabelled `N=4` finding makes it fail.
- Layer 2 self-skips at budget tier ≥ 2 and never blocks on a 5xx.
- The harness is documented in `docs/TESTING.md`; the rubric lives in-repo (not buried in a code-string prompt).

**Gate.** None for Layer 1. Layer 2 gated on a budget-tier-0 window + a cost check.

---

## ER-04 — MCP tool utilisation audit + prune (the 8% problem)  · **Tier 3** · Effort M

**Problem.** 133 registered MCP tools; EMF `LifePlatform/MCP ToolInvocations` shows ~11 touched in 30 days (~8%). The framing-skeptic's strongest point: capability was built faster than demand for it, even from the single user who is also the builder. **This sharpens existing `B-02`** (which is *time-gated* to re-evaluate 2026-07-17) into a *decision-driven* audit available now.

**Approach.** Not blind deletion — a recorded decision per tool, three buckets:
- **used** (called in last 30/90d per the EMF metric);
- **justified-long-tail** (legitimately rare: clinical-lab tools used per blood draw, longitudinal research tools, benchmark comparisons — keep, annotate the cadence that justifies them);
- **dead weight** (neither used nor justified) → prune in batches of 10–20, ratcheting the orphan count down (the `AUDITED_AT` ratchet in B-02 already exists).
- First-pass dead-weight candidates already named in B-02: `tools_lifestyle.py` orphans (~3,400 LOC), `tools_correlation.py` (~1,553 LOC), the various `compare_*_periods` variants.

**Files.** `mcp/registry.py`, the `tools_*.py` modules being pruned, `tests/test_wiring_coverage.py` (must stay green — enforces every registered tool is wired), `docs/MCP_TOOL_CATALOG.md`, `docs/DECISIONS.md` (one ADR recording the keep/justify/prune policy + the 90d-utilisation trigger as the standing rule).

**Acceptance.** Every tool classified; dead-weight batch(es) removed with wiring-coverage + MCP registry tests green; catalog and registry count reconcile via `sync_doc_metadata.py`; the ADR records the rule so this doesn't recur.

**Gate.** Supersedes B-02's date gate — can start now. Coordinate so it doesn't ride a reset.

---

## ER-05 — De-weight the self-grade + external-review readiness  · **Tier 2** · Effort S

**Problem.** The A- is self-assessment by AI personas against a rubric the platform authored; the grades only ever ratchet up. A useful internal QA loop — but **not** external validation, and nothing in the repo says so. A reader (or future Matthew) could mistake the internal grade for a market signal.

**Approach.**
- Add a prominent caveat to `docs/REVIEW_METHODOLOGY.md` and the top of each review: *these grades are internal self-assessment against a self-authored rubric; they measure conformance to the platform's own values, not external quality; the only external signal is a review by an engineer who has never seen the project.*
- Confirm `deploy/generate_review_bundle.py` produces a genuinely self-contained single-file bundle a real external reviewer could read cold, and record in `REVIEW_METHODOLOGY.md` that the standing recommendation is **one** real external senior-engineer review as the actual A-grade arbiter.

**Files.** `docs/REVIEW_METHODOLOGY.md`, the review template, optionally `deploy/generate_review_bundle.py`.

**Acceptance.** The self-assessment caveat is unmissable; the bundle reads coherently with no repo access; the "get one external review" recommendation is recorded as the path to a *trusted* grade.

**Gate.** None.

---

## ER-06 — PII-to-public-surface guarantee (tested)  · **Tier 2** · Effort S–M

**Problem.** Editorial guardrails (no employer/role/industry; partner unnamed; only alcohol + food-delivery vice categories named publicly; bereavement opt-in) and `docs/DATA_GOVERNANCE.md` exist as *policy*. The security reviewer's note: there is no **structural test** that the published surface can't leak them. The `generated/` S3 prefix is Lambda-written daily — a prompt/template change could surface a guarded string with no gate catching it.

**Approach.** A gating test that scans the about-to-be-published artifacts (the `site/` build output + a dry-run of the `generated/` writers: `public_stats.json`, `character_stats.json`, journal/chronicle posts, OG-image alt text) for guardrail violations: a denylist of guarded strings (employer/role/industry tokens, partner name, vice categories beyond the allowed two, bereavement markers unless an opt-in flag is set) plus the broader PII classes in `DATA_GOVERNANCE.md`. Fail the build on a hit. Keep the denylist out of the public repo (load from a secret or a gitignored config) if the repo is public.

**Files.** `tests/test_public_surface_pii_guard.py`, a config source for the denylist (Secrets Manager or gitignored), wire into the site-deploy smoke (`deploy/smoke_test_site.sh`) and/or CI as a **gate** before `sync_site_to_s3.sh`.

**Acceptance.** Injecting a guarded string into a published artifact fails the gate; the denylist is not committed in cleartext to a public repo; the check runs before any publish path.

**Gate.** None.

---

## ER-07 — Complexity posture ledger (load-bearing vs scaffolding)  · **Tier 3** · Effort M

**Problem.** An external panel splits hard on "over-provisioned for N=1" — and the split is entirely about *purpose* (working tool → cut 70%; learning vehicle + portfolio + build-in-public → the excess is the point). The architecture can't answer which frame is right; only Matthew can. Right now the answer is *implicit*, so complexity accretes without a decision ever being made.

**Scope note (honesty boundary).** This is deliberately a **technical posture decision**, not a referendum on whether to build vs. do the health work. It asks "is each subsystem load-bearing, justified-as-learning, or retireable?" — an architecture question, recorded once.

**Approach.** One pass classifying each major subsystem into **(a) load-bearing** (platform breaks without it), **(b) justified-as-portfolio/learning** (kept deliberately, eyes open, even though N=1 doesn't need it), **(c) retire candidate**. Rule on at minimum: the self-healing remediation agent + auto-merge gate, multi-region edge (us-east-1), the budget-tier machinery, per-Lambda DLQs vs. the consolidated approach, X-Ray-on-everything, the three persona boards. Output: one ADR ("complexity posture, 2026-06") and *act on* anything in (c). The deliverable is the **decision**, not necessarily deletions — but it must be explicit and dated so the next accretion has something to answer to.

**Files.** `docs/DECISIONS.md` (the posture ADR), `docs/ARCHITECTURE.md` (a short "complexity posture" subsection linking it), plus any retirements that fall out.

**Acceptance.** Every listed subsystem has an explicit (a)/(b)/(c) verdict + one-line rationale; (c) items scheduled or removed; the ADR states the standing rule for adding future complexity (e.g. "new enterprise-pattern infra must name which frame justifies it").

**Gate.** None. Decision-only; no deploy risk.

---

## ER-08 — DynamoDB-vs-analytical-store decision ADR  · **Tier 4 (defer-leaning)** · Effort S (doc) + optional spike

**Problem.** A data engineer's contrarian read: single-table DynamoDB (no GSIs, composite-key-only) is an awkward fit for analytical, cross-source, time-series data, and the large MCP query layer is partly compensating for how hard the store is to query. The choice may well be *right* (operational simplicity, cost, PITR, it works) — but it's currently **implicit**, never confronted.

**Approach.** **Do not migrate.** Write the honest ADR that states *why* single-table DynamoDB was chosen, what it costs in query expressiveness, and the explicit trigger that would justify revisiting (e.g. "if the correlation/Evidence query layer needs ad-hoc analytical queries, evaluate DuckDB-over-Parquet-in-S3 as a read-side analytical layer *alongside* DDB — not a replacement"). Optionally a tiny, time-boxed spike: point DuckDB at the existing S3 `raw/` JSON and re-implement one correlation query, purely to size the alternative. Keep it in `spikes/`.

**Files.** `docs/DECISIONS.md`, `docs/SCHEMA.md` (link), optional `spikes/er08_duckdb_readside/`.

**Acceptance.** The ADR makes the implicit explicit with an honest cost statement and a concrete revisit trigger; any spike stays in `spikes/` and ships nothing.

**Gate.** Low priority. Defer behind Tiers 1–3.

---

## Sequencing recommendation

1. **ER-02** (contract tests) — small, high-leverage, unblocks confidence in everything else.
2. **ER-01** (heartbeat) — closes the headline finding.
3. **ER-03 Layer 1** (deterministic faithfulness guards) — closes the inverted-testing finding cheaply.
4. **ER-06** + **ER-05** — cheap honesty, one short session.
5. **ER-04** + **ER-07** — the recorded-decision pass; one session each.
6. **ER-03 Layer 2**, **ER-08** — when budget-tier and appetite allow.

The first three are the ones a real external reviewer would refuse to sign off without. Everything after converts taste-critiques into defensible, dated decisions.
