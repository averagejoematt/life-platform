# Life Platform — Architecture Review Methodology

> Repeatable process for conducting comprehensive architecture reviews.
> First review: 2026-03-08 (v2.91.0). Results: docs/REVIEW_2026-03-08.md

---

## How to Run a Review

### 1. Generate the review bundle
```bash
bash deploy/generate_review_bundle.sh
```

### 2. Open a Claude session and paste:

```
I need you to conduct a comprehensive architecture review of my Life Platform.

Read these files from my filesystem:
- docs/ARCHITECTURE.md
- docs/SCHEMA.md  
- docs/PROJECT_PLAN.md
- docs/INFRASTRUCTURE.md
- docs/RUNBOOK.md
- docs/INCIDENT_LOG.md
- docs/COST_TRACKER.md

Then sample source code:
- mcp/handler.py (first 150 lines)
- lambdas/ directory listing
- deploy/ directory listing
- 2-3 Lambda source files (first 100 lines each)

Review against docs/REVIEW_METHODOLOGY.md dimensions.
Compare against previous findings in docs/REVIEW_2026-03-08.md.

Focus areas this cycle: [FILL IN WHAT CHANGED SINCE LAST REVIEW]

Produce:
1. Executive summary with letter grades
2. Findings table (Critical/High/Medium/Low)
3. Updated risk register
4. Updated improvement backlog
5. What improved since last review
6. What regressed since last review
7. Updated roadmap
```

### 3. Review cadence
- **Monthly:** Quick review — incidents + new features only (~30 min)
- **Quarterly:** Full review all dimensions (~2-3 hours)
- **Pre-milestone:** Full review before productization/open-source/handoff decisions

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
