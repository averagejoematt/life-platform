# External Acquisition-Diligence Response Register — 2026-08-23

**Source:** independent buy-side review `Life_Platform_Acquisition_Diligence_and_Remediation_Report.pdf`
(2026-08-23; 52 findings DIL-001–052; 5 P0; weighted 4.47/10; "conditional no-go").
**This register** is the platform's per-finding disposition, produced after a claim-by-claim
fact-check against **live** repo / GitHub API / site state on 2026-08-23 (three independent
verification agents, confidence 1.0). It is the acquirer-grade evidence pack and the
re-grade instrument for **[EPIC] The A-Grade Program (#3042)**.

**Tracking issues (filed 2026-08-23, label `review:diligence-2026-08-23`):** #3042 epic ·
#3043 privacy containment (DIL-001/012) · #3044 subscriber trust (DIL-003/013) · #3045
Tier-2 publication ADR (DIL-008/011, gate:owner) · #3046 prediction gradeability (DIL-007) ·
#3047 CodeQL regrowth (DIL-018) · #3048 CSP hardening (DIL-015) · #3049 source-completeness
(DIL-024) · #3050 AI-safety eval matrix (DIL-029/030/031). Folds: #2824 (DIL-036) · #2828
(DIL-014) · #2890 (DIL-016) · #2578 (sentinel/DIL-020) · #2986 (DIL-010/035) · #2834
(DIL-004 residual) · #2799 (DIL-026).

**Disposition vocabulary:** `CONFIRMED` (true today, remediation owned) · `STALE` (was true,
already fixed — the report read a closed state or an out-of-date doc) · `WRONG` (misread of
current state — evidence below) · `PRICED` (accepted with a dated PROPORTIONALITY row + a
named revisit trigger). A finding is not "answered" until its row cites live evidence.

> **The most important finding is not in the report.** The report's own false positives
> (DIL-004, DIL-006, and half of DIL-005) were **manufactured by the platform's stale
> self-descriptions** — `docs/MANAGED_WHERE_LEDGER.md` (self-stamped Verified 2026-07-09,
> ~7 weeks stale) contradicting the current `deploy/github_posture.json`. Documentation
> truth is not a scored domain here; it is the external-assessment attack surface, and
> Phase D0.5 + D2 exist to close it.

---

## P0 register

| DIL | Title | Verdict | Live evidence (2026-08-23) | Disposition |
|---|---|---|---|---|
| 001 | Public Tier-2 coaching docs | **CONFIRMED** | 5 `Status: PRIVATE / internal` files under `docs/coaching/` return 200 on raw.githubusercontent; `DATA_GOVERNANCE.md` scope note claims "repo is PRIVATE" (false since 07-20 public flip); `check_doc_facts.py:690` gate hardcodes "truth is PRIVATE" (would red the honest fix) | D0.1 — relocate + fix gate + marker guard |
| 002 | Rate-limit identity bypass (#1221) | **STALE** | #1221 CLOSED 2026-08-21; `common/client_ip.py` fails closed to a constant, XFF fallback deleted, AST-guarded fleet-wide (`test_rate_limit_identity_1221.py`); live wire proof 6×forged-XFF → `400 400 400 429 429 429` | Residual: stale `client_ip.py` docstrings (D0.5) + edge-observation decision (#2828, D1) |
| 003 | Deletion promise vs 548-day retention | **CONFIRMED (worse)** | `/privacy/` promises "immediately"/"entirely"; `subscriber_retention.py` retains plaintext 548d then anonymizes; unsubscribe carries **plaintext email, no token**, unauthenticated GET mutation across 7 senders | D0.2 — subscriber trust package |
| 004 | Production approval absent | **WRONG (live)** | `gh api …/environments/production` → `required_reviewers` rule live + actively blocking (3 runs `waiting` today); ledger row stale (Verified 07-09) manufactured this; residual = self-approvable + admin-bypass | D0.5 corrects ledger; residual PRICED under #2834 |
| 007 | 75 pending / 0 graded | **PARTIALLY (re-diagnosed)** | Two systems conflated (coach predictions vs `/api/calibration` n=30 @80%); nothing due before 08-24 (domain-min windows); REAL defect: 28/50 pending are `eval_type: qualitative` = structurally ungradeable, violating closed #715's own criterion | D0.4 — gradeability + scorecard honesty |

## P1 / P2 register (condensed — full detail in the phase plan)

| DIL | Verdict | Note | Disposition |
|---|---|---|---|
| 005 main ruleset weak | **PARTIALLY** | No PR rule/reviewers ✅; understated — main has **NO required checks** (`main-required-fast-lane` never applied); "Actions bypass" WRONG (bypass_actors empty; posture uses a User actor, #2198) | D0.6 apply posture; CONTRIBUTING corrected D0.5 |
| 006 vuln/Dependabot disabled | **WRONG (live)** | `vulnerability-alerts` 204=enabled; `automated-security-fixes` on; 0 open alerts; ledger stale | D0.5 ledger correction |
| 008 Tier-2 on public APIs | **CONFIRMED** | `/api/vitals` (HRV/RHR/recovery/weight), `/api/labs` (named lipid panel) unauthenticated; no ADR records it | D0.3 publication ADR + registry port |
| 009 "100% IaC" false | **CONFIRMED** | README headline vs MANAGED_WHERE_LEDGER's honest 13-row out-of-IaC ring | D0.5 README correction |
| 010/035 doc contradictions | **MIXED** | (a) README $85 & $150 CONFIRMED; (b) ONBOARDING GSI WRONG (agrees); (c) "repo private" WRONG (conditional only); (d) TESTING retired-test WRONG; (e) COST_TRACKER authoritative + live-site `.js`/editorial $85 ×4 STALE | D0.5 + D2 truth manifest |
| 011 field-privacy registry subset | **CONFIRMED** | #2803 registry = 3 fields; all DATA_GOVERNANCE Tier-2 = TIER_PUBLIC-by-omission | D0.3 full port |
| 012 public operational recon | **CONFIRMED** | account id ×7, live IAM policies, 29 secret names, break-glass ordering | D0.1 recon-surface pass |
| 013 tokens in URLs | **PARTIALLY (worse)** | confirm token in query string yes; unsubscribe = plaintext email, no token | folded into D0.2 |
| 014 no edge-abuse control | **CONFIRMED (severity ↓)** | WAF removed (deliberate, also WAFv2 target-incompatible); limiter now fail-closed + fan-out-priced | #2828 decision, D1 |
| 015 CSP unsafe-inline + jsdelivr | **CONFIRMED** | `csp.py` ships both (ADR-057 W-08 accepted); `a11y_audit.py:86` coupled | D1 CSP hardening |
| 016 bundled/static/stale secrets | **CONFIRMED** | `ingestion-keys` bundle; static provider keys; `notion` retire-candidate live | #2890 (re-scoped), D1 |
| 017 native-layer scanning | **STALE** | `pip_audit_lambda` coverage guard reds RED on unscanned layer; SBOM (syft) emitted; pip-audit enforced | closed by prior work |
| 018 CodeQL backlog | **STALE-as-filed / REGRESSED → TRIAGED 08-23** | D0.7 done: #151 js/redos FIXED (d02e64d63); #152 dismissed false-positive (integer counter, name heuristic); #153–157 dismissed intentional (emoji-block ranges). Open=1 pending re-scan of the fix; sentinel can-it-fail question filed on #2578 | D0.7 complete; #3047 closes on verified 0 |
| 021 auto site-deploy vs narrative | **CONFIRMED** | site-deploy.yml no approval by design (#750); org-chart essay claims universal click | D0.5 essay correction |
| 023 heartbeat silent-fail | **STALE** | #1196 fixed; `test_heartbeat_completeness.py` + live liveness gauge | — |
| 024 clock-based sequencing | **CONFIRMED** | 5 compute lambdas run blind on cron; no completeness manifest | D3 source-completeness contract |
| 025 idempotency/replay | **CONFIRMED (arch risk)** | 7 email senders + write-MCP + webhooks; no enterprise-wide inventory | D3 idempotency census |
| 026 S3 noncurrent growth | **CONFIRMED** | `imports/` uncovered (2.23GB); no drift assertion (only post-hoc 50GB alarm) | D3 (#2799 home) |
| 027 single-region recovery | **CONFIRMED** | SECURITY accepts no cross-region | PRICED + cross-account backup for raw/ (D3) |
| 028 raw-layout drift | **STALE (reverify)** | #1256 closed; `raw_layout` facets exist | D3 replay-proof test |
| 029 stale-cycle grounding | **STALE (reverify)** | closed coach-correction epic; standing assurance = D4 | D4 eval matrix |
| 030 stored-text injection | **STALE (reverify)** | #811 closed; expansion coverage = D4 | D4 eval matrix |
| 031 clinical operating model | **COMMERCIAL GAP** | no clinician-reviewed hazard register | D4 clinical-LITE build + PRICED (full) |
| 032 prediction grading/calibration | **CONFIRMED** | folds into DIL-007 diagnosis | D0.4 |
| 036 budget guard fail-open | **CONFIRMED (+ sharper)** | tier-3 hard stop shares the bare `except → tier 0` SSM read | folded into #2824, D1 |
| 037/033/034/043/044/045/046 commercial | **COMMERCIAL GAP** | single-user by design | PRICED (revisit trigger = commercialization) |
| 038 complexity vs use | **PARTIALLY** | gate count 425-vs-490 CONFIRMED (#3000); MCP "11 of 133" WRONG (31 of 143 served; live 76) | #3000 / #2578 |
| 039/040 outcome + IA | **CONFIRMED** | product; deprioritized | PRICED / D-later |
| 041 API contract baselines | **STALE (reverify)** | #1436 closed | D5 contract check |
| 042 essay overstates autonomy | **CONFIRMED** | essay "daily self-merge before coffee" vs Mon/Wed/Fri shadow | D0.5 essay correction |
| 047/048 org resilience / segregation | **CONFIRMED (arch)** | solo key-person | PRICED + owner-handoff drill (D3) |
| 049 founder-calibrated scoring | **CONFIRMED** | single-subject validity | D4 score-transparency (cheap half) + PRICED |
| 050 deletion propagation map | **PARTIALLY** | archives well-documented; propagation machinery absent | D3/D-later |
| 051 accessibility coverage | **STALE (reverify)** | WCAG audit due | D-later |
| 052 self-referential grading | **CONFIRMED** | REVIEW_METHODOLOGY concedes it; **this external review is the answer** | ongoing (external re-grade cadence) |

## Findings our verification produced (not in the report)

1. `main` has **no required status checks at all** — `main-required-fast-lane` unapplied; CONTRIBUTING's "PRs required" is false. → D0.6.
2. **CodeQL regrew 7 alerts (2 high)**, one a recurrence-shaped hit on #1902's clear-text-logging class; `drift_sentinel.check_codeql_alerts` did not surface it → a #2578 can-it-fail question. → D0.7. **Triaged 2026-08-23: 1 fixed, 6 dismissed with reasons (see DIL-018 row); the "recurrence" was a name-heuristic false positive on an integer counter.**
3. `budget_guard` tier-3 hard stop **shares the fail-open SSM path** — a grant regression silently disables the ceiling. → #2824 / D1.
4. `check_doc_facts.py` **scans no `.js`** — the site's most-quoted number ships un-guarded. → D0.5 / D2.
5. Privacy-tier registry and DATA_GOVERNANCE prose are **unreconciled twin sources**. → D0.3.
6. `GradableCount` metric emitted but **no ratio alarm** — a permanently-ungradeable majority is invisible. → D0.4.
7. `imports/` (health uploads) noncurrent versions **uncovered by lifecycle**, no drift assertion. → D3.

## Priced-acceptance register (dated; revisit triggers)

_Populated as PROPORTIONALITY rows land. Standing entries: DIL-027 single-region residual
(after cross-account raw/ backup) · DIL-031 full clinical operating model · DIL-033/034/037/
043/044/045/046 commercial control plane — all **revisit trigger = a commercialization
decision**; DIL-004 self-approval residual — **structural to a solo operator**, priced under
#2834 · DIL-047/048 key-person — priced after the owner-handoff drill._

---
*Register opened 2026-08-23 (A-Grade Program, Phase S2-close). Updated per phase; D5 runs
`scripts/diligence_verify.py` (the report's §15 playbooks, scripted) to regenerate the
live-evidence column before the external re-grade.*
