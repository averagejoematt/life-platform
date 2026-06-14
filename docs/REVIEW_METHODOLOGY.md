# Life Platform — Architecture Review Methodology

> Repeatable process for conducting comprehensive architecture reviews.
> First review: 2026-03-08 (v2.91.0). Latest: V2 audit (2026-05-17, 76 findings, ~33 shipped, formally closed in ADR-057).
> Reviews stored in `docs/reviews/`; V2-style audits in `docs/v2-audits/`.
> Tech Board: invoke as "tech board" or by name. 12 seats across Architecture, Security, Data, AI, Operations, Product, and FinOps.
> Last updated: 2026-06-14 (v8.6.0)

---

## ⚠️ What these grades are — and are not (ER-05)

**Every grade produced by this process is internal self-assessment by AI personas
against a rubric the platform authored.** It measures *conformance to the platform's
own stated values* — not external quality, not market validation, not "an A from the
industry." The grades have only ever ratcheted upward, which is exactly what a
self-authored rubric graded by the same kind of model that built the system would
predict; it is a useful internal QA signal and nothing more.

**The only trustworthy A-grade arbiter is one real senior engineer who has never
seen this project, reading it cold.** That is the standing recommendation. To make
it cheap to act on, `deploy/generate_review_bundle.py` produces a single self-contained
bundle a cold external reviewer can read with **no repo access** — the intended input
to that one external review. Treat any internal letter grade as "passes our own bar,"
never as "validated." Reproduce this caveat at the top of every review document.

---

## How to Run a Review

### Step 1: Commit everything and update the resolved-findings table

Before generating the bundle, the Section 13b resolved-findings table in `generate_review_bundle.py` **must be current**. Every finding from the previous review should be marked RESOLVED with a proof pointer, or left as PENDING with a reason. This is the most important pre-review maintenance task.

Also ensure:
- `docs/CHANGELOG.md` reflects all work since the last review
- `docs/PROJECT_PLAN.md` has up-to-date status on all items
- `git add -A && git commit` — the bundle reads live files

### Step 2: Generate the pre-compiled review bundle

```bash
cd ~/Documents/Claude/life-platform
python3 deploy/generate_review_bundle.py
```

This produces `docs/reviews/REVIEW_BUNDLE_YYYY-MM-DD.md` containing:
- Platform state snapshot + latest handover
- Full CHANGELOG (400 lines)
- Architecture, Infrastructure, ADRs, SLOs, Incident Log, Intelligence Layer
- CDK state including full `ci-cd.yml` content and test suite function names
- Source code samples (key Lambdas + MCP handler)
- Previous review grades + **last review full content**
- **Section 13b: Resolved findings inventory** — explicit table with proof pointers

### Step 3: Start a fresh Opus session and use this prompt

```
Life Platform Architecture Review #[N].

Read this single file from my filesystem:
  docs/reviews/REVIEW_BUNDLE_YYYY-MM-DD.md

Then conduct Architecture Review #[N] using the full Technical Board of Directors (all 12 members).

IMPORTANT PROCESS RULES — follow these before issuing any finding:

1. Read Section 13b (RESOLVED FINDINGS INVENTORY) completely before writing a single finding.
   If a finding you were about to raise appears in that table as RESOLVED, skip it and note
   it as confirmed-resolved instead. Re-issuing resolved findings wastes review budget.

2. For any finding related to CI/CD, testing, IAM, secrets, or observability: cite the
   specific file or code artifact that either confirms the problem or confirms the resolution.
   Do not issue findings based on documentation claims — verify against the actual source files
   included in this bundle (ci-cd.yml, test file listings, role_policies.py, etc.).

3. Distinguish clearly between:
   - NEW finding (not present in previous review, not in resolved table)
   - REGRESSION (was resolved, now broken again — cite evidence)
   - CONFIRMED RESOLVED (was a finding, now verified fixed — acknowledge and move on)
   - PERSISTING (was a finding, still not addressed — re-issue with original finding ID)

4. Grade each dimension against the previous review's grade. Explain movement up or down
   with specific evidence from the bundle, not general principles.

Focus areas this cycle: [FILL IN — e.g., "observability improvements, new MCP canary, X-Ray tracing, CI/CD layer tests"]

Previous review: [FILL IN with prior review # and version]. Current version: [FILL IN].
```

### Step 4: After the review

1. Save output → `docs/reviews/REVIEW_YYYY-MM-DD_v[N].md`
2. Update Section 13b in `generate_review_bundle.py` with all new findings + resolutions
3. Update CHANGELOG.md with review version
4. Update handover
5. Update memory with new grades
6. `git add -A && git commit -m "vX.X.X: Architecture Review #N" && git push`

---

## Review Cadence

- **Monthly:** Quick review — incidents + new features only (~30 min)
- **Quarterly:** Full review all dimensions (~2-3 hours)
- **Pre-milestone:** Full review before productization/open-source/handoff decisions

---

## Technical Board of Directors (12 seats)

| Seat | Name | Standing Question |
|------|------|------------------|
| Cloud Architect | Priya Nakamura | "Is the system shape right?" |
| AWS Serverless | Marcus Webb | "Is this the right AWS implementation?" |
| Security + IAM | Yael Cohen | "How could this fail or be exploited?" |
| SRE / Ops | Jin Park | "What breaks at 2 AM?" |
| Code Quality | Elena Reyes | "Could another team own this?" |
| Data Architect | Omar Khalil | "Is the data model coherent?" |
| AI/LLM Systems | Anika Patel | "Is the intelligence layer trustworthy?" |
| Statistician | Henning Brandt | "Are the conclusions actually valid?" |
| Product | Sarah Chen | "Is this solving the right problem in the cleanest way?" |
| Startup CTO | Raj Srinivasan | "What's the wedge and where are you fooling yourself?" |
| Adversarial | Viktor Sorokin | "Is this actually necessary?" |
| FinOps | Dana Torres | "What does this cost at scale?" |

Sub-boards: Architecture Review (Priya, Marcus, Yael, Jin, Elena, Omar) · Intelligence & Data (Anika, Henning, Omar, Elena) · Productization (Raj, Sarah, Viktor, Dana, Priya)

---

## Review Dimensions

1. Architecture (coupling, modularity, failure domains, scale bottlenecks)
2. Security (IAM, secrets, auth, input validation, supply chain)
3. Reliability (retry, DLQ, idempotency, failure propagation, DR)
4. Observability (logging, metrics, alarms, dashboards, SLOs)
5. Cost (Lambda, DDB, AI tokens, CloudWatch, growth projection)
6. Code quality (modularity, testing, dependencies, deploy process)
7. Data quality (validation, schema versioning, reconciliation, lineage)
8. AI rigor (causal claims, output validation, hallucination controls, disclaimers)
9. Operability (can someone else run this? how long to onboard?)
10. Productization readiness (multi-tenant, IaC, CI/CD, team handoff)

---

## Severity Model

| Severity | Definition |
|----------|------------|
| Critical | Security flaw, data loss risk, safety concern |
| High | Important weakness, fix within 2 weeks |
| Medium | Technical debt, improvement opportunity |
| Low | Polish, optimization |

## Effort Model

| Effort | Time |
|--------|------|
| S | 1-2 hours |
| M | 3-6 hours |
| L | 8+ hours |

---

## Why Reviews Go Stale (and how to prevent it)

The single biggest failure mode is Opus re-flagging already-resolved findings. This happens because:

1. **Bundle carries claims, not proof** — docs say "CI exists" but Opus can't verify without seeing the file. Fix: bundle now includes full `ci-cd.yml` and test function names.
2. **No resolved-findings inventory** — Opus saw previous findings with no resolution status. Fix: Section 13b explicit table with proof pointers.
3. **Changelog was truncated** — 150 lines = 2-3 versions. Fix: now 400 lines.
4. **Previous review findings were hardcoded** — static list in generator never updated. Fix: generator now reads last review `.md` file dynamically.
5. **Review prompt had no verification instruction** — Opus wasn't told to check before flagging. Fix: explicit rules 1-4 in the prompt above.

**Maintenance rule:** After every session where findings are resolved, update Section 13b in `generate_review_bundle.py` immediately. Don't defer to review time.

---

## V2 Audit Learnings (2026-05-17)

The V2 audit produced ~130 findings across 8 phases — ~33 shipped, ~37 deferred-with-rationale (closed in ADR-057), the rest superseded or merged. Things to do differently next time:

1. **Verify before recommending.** ~10% of V2 findings had wrong premises (P1.2 said the WAF was orphaned — it wasn't, it protects HAE webhook; P5.2 proposed prompt-caching savings below Anthropic's 1024-token cache minimum; P5.7 said to build a coach prediction evaluator that already existed and was running daily). Future auditors must read the actual code/AWS state before issuing the finding, not just the docs. Section 13b helps for resolved findings but doesn't catch wrong-premise *new* findings.

2. **Audit the docs alongside the code.** The V1 ADR list, ONBOARDING, ARCHITECTURE all carried stale Lambda counts, MCP tool counts, ADR counts, and layer versions for 2–6 months. The fix is to **bake live commands into the docs** (e.g., `grep -c '"name":' mcp/registry.py`, `aws lambda list-functions … | wc -l`) so the next reader can re-verify in 5 seconds rather than asking "is this stale?"

3. **Close formally, not "later."** Phase 6 (multi-user), P4.3 (split intelligence_common.py), P8.6 (Lambda Power Tuning), and several others were on the backlog for months with no progress and no decision. ADR-057 closed them with documented re-open triggers. **Indefinitely-open items are debt; formally-closed items are clarity.** Convert to closure or active work on every audit pass.

4. **Bundle still matters.** The pre-compiled review bundle (Section 13b inventory + full ci-cd.yml + test function names + last review .md content + 400-line CHANGELOG) is still the single biggest defense against re-flagging. Don't skip generating it.

5. **Plan != ship.** V2 had 76 findings *planned* and ~33 *shipped*. The shipped:planned ratio is fine but the plan must include explicit "defer-or-do" decisions on every item before audit close — otherwise the unplanned remainder leaks into the next audit as "you didn't do this."

6. **Track corrections in the closure ADR.** ADR-057 is the V2 record. The next audit pass should produce a similar ADR — every item closed, every premise correction documented, every re-open trigger named.

---

**Verified:** 2026-05-19
