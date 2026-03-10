# Life Platform — Architecture Review Methodology

> Repeatable process for conducting comprehensive architecture reviews.
> First review: 2026-03-08 (v2.91.0). Reviews stored in docs/reviews/.  
> Tech Board: invoke as "tech board" or by name. 12 seats across Architecture, Security, Data, AI, Operations, Product, and FinOps.

---

## How to Run a Review

### Step 1: Generate the pre-compiled review bundle

```bash
cd ~/Documents/Claude/life-platform
python3 deploy/generate_review_bundle.py
```

This produces a single file `docs/reviews/REVIEW_BUNDLE_YYYY-MM-DD.md` that contains everything a reviewer needs — architecture, changelog, CDK state, source code samples, previous grades, incident patterns, and more. The reviewer reads ONE file instead of 10+.

**Why:** Reviews require reading ARCHITECTURE.md, SCHEMA.md, PROJECT_PLAN.md, CHANGELOG.md, INFRASTRUCTURE.md, RUNBOOK.md, INCIDENT_LOG.md, DECISIONS.md, INTELLIGENCE_LAYER.md, SLOs.md, plus source code. Loading all of these fills the context window before the review can be generated. The bundle compresses them into ~3000-5000 lines.

### Step 2: Start a new Claude session and paste:

```
Life Platform architecture review.

Read this single file from my filesystem:
- docs/reviews/REVIEW_BUNDLE_YYYY-MM-DD.md

Then conduct Architecture Review #N using the Technical Board of Directors from memory.
Go deep into actual code, AWS configs, and specific artifacts — not just generalized best practices.
Compare against previous review grades (included in the bundle).
Focus areas this cycle: [FILL IN WHAT CHANGED SINCE LAST REVIEW]
```

### Step 3: After the review

1. Save the review output to `docs/reviews/REVIEW_YYYY-MM-DD.md`
2. Update CHANGELOG.md with review version
3. Update handover
4. Update memory with new grades
5. `git add -A && git commit -m "vX.X.X: Architecture Review #N" && git push`

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

- **Critical:** Security flaw, data loss risk, safety concern
- **High:** Important weakness, should fix within 2 weeks
- **Medium:** Technical debt, improvement opportunity
- **Low:** Polish, optimization

## Effort Model

- **S:** 1-2 hours
- **M:** 3-6 hours  
- **L:** 8+ hours

---

## Legacy: Manual file-by-file approach

If the bundle generator isn't available, the old approach of reading individual files still works — but risks context exhaustion for platforms with 10+ large docs. Use the bundle approach for all future reviews.

The old `deploy/generate_review_bundle.sh` (bash version) captures AWS state but doesn't produce a self-contained review document. The Python version (`deploy/generate_review_bundle.py`) supersedes it.
