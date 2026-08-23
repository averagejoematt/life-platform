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
| 001 | Public Tier-2 coaching docs | **CONFIRMED → FIX LANDED** (#3043, 2026-08-23; pending driver S3 upload + merge) | Was: 5 `Status: PRIVATE / internal` files under `docs/coaching/` return 200 on raw.githubusercontent; `DATA_GOVERNANCE.md` scope note claims "repo is PRIVATE" (false since 07-20 public flip); `check_doc_facts.py:690` gate hardcodes "truth is PRIVATE" (would red the honest fix) | D0.1 done: 5 files `git rm`'d → `s3://matthew-life-platform/config/coaching/` (driver uploads BEFORE merge); scope note rewritten to the true PUBLIC posture; gate un-inverted (asserts LIVE visibility via `gh api`, offline = loud SKIP); marker guard `tests/test_no_private_markers_3043.py` (mutation-proved: red on the 5 pre-removal, green after). **Dated risk acceptance — see below.** |
| 002 | Rate-limit identity bypass (#1221) | **STALE** | #1221 CLOSED 2026-08-21; `common/client_ip.py` fails closed to a constant, XFF fallback deleted, AST-guarded fleet-wide (`test_rate_limit_identity_1221.py`); live wire proof 6×forged-XFF → `400 400 400 429 429 429` | Docstring residual **closed 2026-08-23** (D0.5 sweep — module + function docstrings now state the fail-closed reality, interim framed as history); edge-observation decision remains (#2828, D1) |
| 003 | Deletion promise vs 548-day retention | **CONFIRMED (worse)** → **FIX LANDED 2026-08-23, deploy pending** | Was: `/privacy/` promised "immediately"/"entirely" while `subscriber_retention.py` retained plaintext 548d; unsubscribe carried **plaintext email, no token**. Fix (#3044 PR): anonymize-at-unsubscribe (`handle_unsubscribe` scrubs inline; `RETENTION_WINDOW_DAYS` 548→0, weekly sweep = backstop), signed-HMAC unsub tokens across all 7 senders (`common/unsubscribe_token.py`), `/privacy/` §05 rewritten to the implemented contract (hash-retained suppression + 7-day hard-delete SLA), `docs/API.md` corrected. Evidence: `tests/test_unsubscribe_token_3044.py` deletion-evidence test + `test_e2e_write_paths.py` lifecycle. **Merged ≠ deployed** — closes only after the 6 Lambdas + cdk IAM + site deploy | D0.2 — landed; deploy + legacy-link sunset 2026-09-22 |
| 004 | Production approval absent | **WRONG (live)** | `gh api …/environments/production` → `required_reviewers` rule live + actively blocking (3 runs `waiting` today); ledger row stale (Verified 07-09) manufactured this; residual = self-approvable + admin-bypass | Ledger **corrected 2026-08-23** (D0.5 sweep — every row re-verified live, per-row Verified column, monthly re-verify dead-man on the #2832 calendar); residual PRICED under #2834 |
| 007 | 75 pending / 0 graded | **PARTIALLY (re-diagnosed) — fix landed (#3046, deploy pending)** | Two systems conflated (coach predictions vs `/api/calibration` n=30 @80%); nothing due before 08-24 (domain-min windows); REAL defect: 28/50 pending were `eval_type: qualitative` = structurally ungradeable, violating closed #715's own criterion. Landed: emission contract (`gradeable_by` stamped; qualitative → status `observation`, never pending — regression test re-asserts #715 crit. 3), evaluator retires legacy pending-qualitative at window end, scorecard/API carry due-vs-pending context ("0 due yet — earliest …") + labeled observational class, `GradableShare` metric + `prediction-gradable-share-low` alarm (< 0.5, 3d). First real grades observed 08-24+ as windows mature | D0.4 — shipped, needs deploy (evaluator+state-updater+site-api Lambdas, Monitoring stack, coaching rebuild) |

### DIL-001 historical exposure — dated risk acceptance (2026-08-23, #3043)

The five relocated coaching docs were world-readable **2026-05 → 2026-07-13** (repo
public since inception) and again **2026-07-20 → 2026-08-23** (the deliberate public
flip). A git-history rewrite was evaluated and **ruled ineffective**: GitHub retains
~1,454 pull refs that keep force-pushed content reachable by direct sha, so a rewrite
would break every commit reference and external link while erasing nothing (the same
analysis as the CLAUDE.md authorship decision; the off-repo remediation plan holds the
full pricing). **Accepted:** the historical copies in git history remain reachable;
the containment is forward-looking — the tree carries no PRIVATE-marked file (guarded
structurally), the live surface returns 404, and any future marker reds CI. Incident
row: the in-band `PRIVATE` marker was an intent with no enforcing control from the
day the repo first went public; the control now exists. Revisit trigger: any future
repo-visibility change, or GitHub shipping ref-level purge tooling.

## P1 / P2 register (condensed — full detail in the phase plan)

| DIL | Verdict | Note | Disposition |
|---|---|---|---|
| 005 main ruleset weak | **PARTIALLY** | No PR rule/reviewers ✅; understated — main has **NO required checks** (`main-required-fast-lane` never applied); "Actions bypass" WRONG (bypass_actors empty; posture uses a User actor, #2198) | CONTRIBUTING **corrected 2026-08-23** (D0.5 sweep — posture file named as source of truth, "PRs required" claim removed; ledger row now says NOT YET APPLIED + User bypass); D0.6 apply posture still pending |
| 006 vuln/Dependabot disabled | **WRONG (live)** | `vulnerability-alerts` 204=enabled; `automated-security-fixes` on; 0 open alerts; ledger stale | Ledger **corrected 2026-08-23** (D0.5 sweep — row re-verified live: enabled since 07-20) |
| 008 Tier-2 on public APIs | **CONFIRMED** | `/api/vitals` (HRV/RHR/recovery/weight), `/api/labs` (named lipid panel) unauthenticated; no ADR records it | D0.3 publication ADR + registry port |
| 009 "100% IaC" false | **CONFIRMED** | README headline vs MANAGED_WHERE_LEDGER's honest 13-row out-of-IaC ring | README **corrected 2026-08-23** (D0.5 sweep — "CDK-managed application infra with a declared out-of-IaC ring", ledger linked) |
| 010/035 doc contradictions | **MIXED** | (a) README $85 & $150 CONFIRMED; (b) ONBOARDING GSI WRONG (agrees); (c) "repo private" WRONG (conditional only); (d) TESTING retired-test WRONG; (e) COST_TRACKER authoritative + live-site `.js`/editorial $85 ×4 STALE | (a)+(e) **corrected 2026-08-23** (D0.5 sweep — README row, evidence_meta.js, inference blurb, /method/build lede + org-chart essay via their generators; `check_doc_facts.py` now scans site `.js`/`.html` + v4 generators for the ceiling family, mutation-proofed); D2 truth manifest remains |
| 011 field-privacy registry subset | **CONFIRMED** | #2803 registry = 3 fields; all DATA_GOVERNANCE Tier-2 = TIER_PUBLIC-by-omission | D0.3 full port |
| 012 public operational recon | **CONFIRMED → DISPOSED per family** (#3043, 2026-08-23) | account id ×7, live IAM policies, 29 secret names, break-glass ordering | Pass done: **break-glass/day-1 ordering REDACTED** from `docs/ACCOUNTS.md` (to the owner's estate kit; the ⚠️ UNDOCUMENTED estate rows stay — `check_reentry_hardening.py` parses them, the loud gap is deliberate) · **account id ACCEPTED** (dated note `infra/iam/README.md` — identifier not credential, in every CDK ARN) · **IAM policies ACCEPTED** (same note — reviewable source of truth, no credentials; boundary = OIDC trust) · **secret-name inventory ACCEPTED** (dated note `docs/SECRETS_MAP.md` — names not values) · residual: BENCH-1 numeric anchors in shipped code/tests → folded to #3045 |
| 013 tokens in URLs | **PARTIALLY (worse)** → **FIX LANDED 2026-08-23, deploy pending** | Unsubscribe leg closed by #3044: signed short-lived token carrying the email HASH (no PII in any generated URL); tokenless GET cannot mutate; legacy plaintext links sunset 2026-09-22. Confirm-token-in-query-string leg remains as-is (random, stored server-side, 48h, single-purpose) — accepted | folded into D0.2 — landed, deploy pending |
| 014 no edge-abuse control | **CONFIRMED (severity ↓)** | WAF removed (deliberate, also WAFv2 target-incompatible); limiter now fail-closed + fan-out-priced | #2828 decision, D1 |
| 015 CSP unsafe-inline + jsdelivr | **CONFIRMED** | `csp.py` ships both (ADR-057 W-08 accepted); `a11y_audit.py:86` coupled | D1 CSP hardening |
| 016 bundled/static/stale secrets | **CONFIRMED** | `ingestion-keys` bundle; static provider keys; `notion` retire-candidate live | #2890 (re-scoped), D1 |
| 017 native-layer scanning | **STALE** | `pip_audit_lambda` coverage guard reds RED on unscanned layer; SBOM (syft) emitted; pip-audit enforced | closed by prior work |
| 018 CodeQL backlog | **STALE-as-filed / REGRESSED → TRIAGED 08-23** | D0.7 done: #151 js/redos FIXED (d02e64d63); #152 dismissed false-positive (integer counter, name heuristic); #153–157 dismissed intentional (emoji-block ranges). Open=1 pending re-scan of the fix; sentinel can-it-fail question filed on #2578 | D0.7 complete; #3047 closes on verified 0 |
| 021 auto site-deploy vs narrative | **CONFIRMED** | site-deploy.yml no approval by design (#750); org-chart essay claims universal click | Essay + /method/build editorial **corrected 2026-08-23** (D0.5 sweep — honest lane split: engine deploys gate on production approval, site auto-deploys behind QA + auto-rollback) |
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
| 042 essay overstates autonomy | **CONFIRMED** | essay "daily self-merge before coffee" vs Mon/Wed/Fri shadow | Essay **corrected 2026-08-23** (D0.5 sweep — Mon/Wed/Fri cadence + shadow-mode demotion stated in the essay itself, framed as the org chart working) |
| 047/048 org resilience / segregation | **CONFIRMED (arch)** | solo key-person | PRICED + owner-handoff drill (D3) |
| 049 founder-calibrated scoring | **CONFIRMED** | single-subject validity | D4 score-transparency (cheap half) + PRICED |
| 050 deletion propagation map | **PARTIALLY** | archives well-documented; propagation machinery absent | D3/D-later |
| 051 accessibility coverage | **STALE (reverify)** | WCAG audit due | D-later |
| 052 self-referential grading | **CONFIRMED** | REVIEW_METHODOLOGY concedes it; **this external review is the answer** | ongoing (external re-grade cadence) |

## Findings our verification produced (not in the report)

1. `main` has **no required status checks at all** — `main-required-fast-lane` unapplied; CONTRIBUTING's "PRs required" is false. → D0.6.
2. **CodeQL regrew 7 alerts (2 high)**, one a recurrence-shaped hit on #1902's clear-text-logging class; `drift_sentinel.check_codeql_alerts` did not surface it → a #2578 can-it-fail question. → D0.7. **Triaged 2026-08-23: 1 fixed, 6 dismissed with reasons (see DIL-018 row); the "recurrence" was a name-heuristic false positive on an integer counter.**
3. `budget_guard` tier-3 hard stop **shares the fail-open SSM path** — a grant regression silently disables the ceiling. → #2824 / D1.
4. `check_doc_facts.py` **scans no `.js`** — the site's most-quoted number ships un-guarded. → **CLOSED 2026-08-23** (D0.5 sweep: the ceiling-literal scan now covers `site/**/*.js` + `site/**/*.html` (legacy excepted) + the `v4_*` generators, with planted-defect mutation proof in `tests/test_doc_facts_budget_2899.py`). D2 owns the wider truth manifest.
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
