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
| 003 | Deletion promise vs 548-day retention | **CONFIRMED (worse)** → **FIXED + DEPLOYED 2026-08-23** | Was: `/privacy/` promised "immediately"/"entirely" while `subscriber_retention.py` retained plaintext 548d; unsubscribe carried **plaintext email, no token**. Fix (#3044 PR): anonymize-at-unsubscribe (`handle_unsubscribe` scrubs inline; `RETENTION_WINDOW_DAYS` 548→0, weekly sweep = backstop), signed-HMAC unsub tokens across all 7 senders (`common/unsubscribe_token.py`), `/privacy/` §05 rewritten to the implemented contract (hash-retained suppression + 7-day hard-delete SLA), `docs/API.md` corrected. Evidence: `tests/test_unsubscribe_token_3044.py` deletion-evidence test + `test_e2e_write_paths.py` lifecycle. **DEPLOYED 2026-08-23 17:40–42Z**: cdk Email+Web (token-secret grants + all sender code, postflight-verified), `life-platform-delete-user-data` (window-0 backstop), `/privacy/` copy via site-deploy | D0.2 — DONE; residual = legacy-link sunset 2026-09-22 + next Monday sweep anonymizes the legacy backlog |
| 004 | Production approval absent | **WRONG (live)** | `gh api …/environments/production` → `required_reviewers` rule live + actively blocking (3 runs `waiting` today); ledger row stale (Verified 07-09) manufactured this; residual = self-approvable + admin-bypass | Ledger **corrected 2026-08-23** (D0.5 sweep — every row re-verified live, per-row Verified column, monthly re-verify dead-man on the #2832 calendar); residual PRICED under #2834 |
| 007 | 75 pending / 0 graded | **PARTIALLY (re-diagnosed) — fix landed (#3046), DEPLOYED 2026-08-23** | Two systems conflated (coach predictions vs `/api/calibration` n=30 @80%); nothing due before 08-24 (domain-min windows); REAL defect: 28/50 pending were `eval_type: qualitative` = structurally ungradeable, violating closed #715's own criterion. Landed: emission contract (`gradeable_by` stamped; qualitative → status `observation`, never pending — regression test re-asserts #715 crit. 3), evaluator retires legacy pending-qualitative at window end, scorecard/API carry due-vs-pending context ("0 due yet — earliest …") + labeled observational class, `GradableShare` metric + `prediction-gradable-share-low` alarm (< 0.5, 3d). First real grades observed as windows mature (corpus-derived earliest: 2026-08-31) | D0.4 — DONE: evaluator+state-updater+site-api deployed 17:20Z (live: pending 83→34, observational 49 split out), `prediction-gradable-share-low` alarm live (Monitoring stack 17:24Z), coaching shells rebuilt against the deployed API (a9e497538) |

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
| 008 Tier-2 on public APIs | **CONFIRMED → FIX LANDED** (#3045, 2026-08-23) | Was: `/api/vitals` (HRV/RHR/recovery/weight), `/api/labs` (named lipid panel) unauthenticated; no ADR recorded it. The port sweep found the served surface WIDER than the report saw: sleep-stage trio (`/api/sleep_detail`), lean mass (nutrition surface), full DEXA summary (physical surface — an unrecorded 2026-06-06 owner call) | D0.3 done: **ADR-155** records the owner consent (`gate:owner` signed 2026-08-23) — the full currently-served surface is deliberately published, NOTHING stripped; publication is now an explicit `TIER_OWNER_PUBLISHED` stamp in `field_tiers.py` citing the ADR, never an omission (`is_publishable()` fails closed; `strip_map()` never strips a published field) |
| 009 "100% IaC" false | **CONFIRMED** | README headline vs MANAGED_WHERE_LEDGER's honest 13-row out-of-IaC ring | README **corrected 2026-08-23** (D0.5 sweep — "CDK-managed application infra with a declared out-of-IaC ring", ledger linked) |
| 010/035 doc contradictions | **MIXED** | (a) README $85 & $150 CONFIRMED; (b) ONBOARDING GSI WRONG (agrees); (c) "repo private" WRONG (conditional only); (d) TESTING retired-test WRONG; (e) COST_TRACKER authoritative + live-site `.js`/editorial $85 ×4 STALE | (a)+(e) **corrected 2026-08-23** (D0.5 sweep — README row, evidence_meta.js, inference blurb, /method/build lede + org-chart essay via their generators; `check_doc_facts.py` now scans site `.js`/`.html` + v4 generators for the ceiling family, mutation-proofed); **D2 truth manifest DONE 2026-08-24**: the ceiling family collapsed to ONE source (#2898 CLOSED, PR #3080 deployed — `cost_governor_lambda` constants, `site_api_budget`/`core_stack` derive, `renderCost` reads live `/api/receipts` with omit-when-stale, derivation guard in the premerge lane, mutation-proved 5 ways; found+fixed the live page telling readers \$150 while the August window base is \$200); the public-claims registry live (PR #3072 — 4 behavioral claims with wire-real comparators both directions: remediation mode vs SSM+automerge, deploy lanes vs posture+workflows, deletion promise vs retention constants, auto-merge caps vs automerge.py; discovery reds an unregistered claim-bearing generator; PROPORTIONALITY row) |
| 011 field-privacy registry subset | **CONFIRMED → FIX LANDED** (#3045, 2026-08-23) | Was: #2803 registry = 3 fields; all DATA_GOVERNANCE Tier-2 = TIER_PUBLIC-by-omission | D0.3 done: every DATA_GOVERNANCE Tier-2 row ported — field-level (whoop raw biometrics + stage fields, the full withings BodyScan measure family, reading `retentionScore`/`moodSnapshot`) or source-level (`SOURCE_TIERS`: notion, state_of_mind, macrofactor, strava, hevy, sick_days, supplements, genome, dexa, labs, private_intake, flourishing, felt_probe, reading, cgm_readings); #2803 wiring test covers the widened vocabulary (42 discovered pairs, every one decided); the twin-sources drift class is CLOSED by `tests/test_data_governance_tier_guard_3045.py` (both directions, mutation-proved) |
| 012 public operational recon | **CONFIRMED → DISPOSED per family** (#3043, 2026-08-23) | account id ×7, live IAM policies, 29 secret names, break-glass ordering | Pass done: **break-glass/day-1 ordering REDACTED** from `docs/ACCOUNTS.md` (to the owner's estate kit; the ⚠️ UNDOCUMENTED estate rows stay — `check_reentry_hardening.py` parses them, the loud gap is deliberate) · **account id ACCEPTED** (dated note `infra/iam/README.md` — identifier not credential, in every CDK ARN) · **IAM policies ACCEPTED** (same note — reviewable source of truth, no credentials; boundary = OIDC trust) · **secret-name inventory ACCEPTED** (dated note `docs/SECRETS_MAP.md` — names not values) · **BENCH-1 numeric anchors ACCEPTED, dated 2026-08-23** (#3045 disposition): the run-gate weight (240 lb) and regain-asymmetry ratio (~0.79x) in `mcp/tools_benchmark.py` are functional code constants; the quantity they anchor — the owner's weight — is itself TIER_OWNER_PUBLISHED (ADR-155, served daily on `/api/vitals`), so the anchors disclose nothing beyond the consented surface. Dated note at the constant; revisit trigger: weight ever leaves the published set |
| 013 tokens in URLs | **PARTIALLY (worse)** → **FIXED + DEPLOYED 2026-08-23** | Unsubscribe leg closed by #3044: signed short-lived token carrying the email HASH (no PII in any generated URL); tokenless GET cannot mutate; legacy plaintext links sunset 2026-09-22. Confirm-token-in-query-string leg remains as-is (random, stored server-side, 48h, single-purpose) — accepted | folded into D0.2 — DONE (deployed with DIL-003, 17:40–42Z) |
| 014 no edge-abuse control | **CONFIRMED (severity ↓) → OBSERVATION HALF LIVE 2026-08-23** | WAF removed 2026-06 (CloudFront IS a valid WAFv2 target — the incompatibility notes apply to the MCP Function URL and the HAE HTTP API only); limiter fail-closed + fan-out-priced. **#3058 deployed+verified 19:00Z**: nightly qa-smoke `ratelimit:edge_429` trips one real 429 at $0 model cost (RED / could-not-observe / budget-⏸ vocabulary, no vacuous green; two AST lockstep pins); first live run OBSERVED a real 429 from the deployed Lambda; #1439's manual-only posture re-decided on the record (the 08-14 incident postdates it) | **PRICED 2026-08-23 (owner decision): no WAF — dated acceptance, revisit 2026-10-15** (or on observed abuse / non-self-inflicted spike fire / commercialization). PROPORTIONALITY row names the compensating stack; #2828 CLOSED on the decision |
| 015 CSP unsafe-inline + jsdelivr | **CONFIRMED → FIXED + DEPLOYED 2026-08-23** | Fix (#3060, merged fac0826e0 + cdk Web deploy 19:5xZ): real surface was 266 inline blocks / ~920KB / 91 pages (V2's "21.5KB/15 blocks" was stale) → **0**; production `script-src` is exactly `'self'` (extraction + `application/json` data islands — no hash entries needed); jsdelivr DROPPED (axe-core already vendored; `a11y_audit.py:86` moved to CDP evaluate in the same change); `/legacy/` isolated on a compat policy. **Live-verified**: smoke 246/0 with the new source-derived CSP assertion (hardened on `/`, compat on `/legacy/`); site-deploy 32662800968 green end-to-end (real-browser visual-QA, zero JS errors, no rollback) | #3048 CLOSED on live evidence; residuals filed on the PR (generator chrome drift follow-up; subdomains out of DIL-015 scope) |
| 016 bundled/static/stale secrets | **CONFIRMED → PARTIALLY FIXED 2026-08-23** | D1 pass: rotation owner + expiry/next-action recorded per family (SECRETS_MAP rotation register, ⚠️ loud-gap convention for GitHub-UI PAT expiries); us-east-1 "replicas" **justified in writing** (cf-auth/buddy-auth are edge-native and were missing from the map entirely — now rows; site-api-origin-secret is the one true CFN-region-local twin); `notion` deletion batched to owner with a required pre-check (live LastAccessedDate 2026-07-25 contradicts the recorded 2026-03-09 — a reader still exists) | #2890 re-scoped to per-family PRICED split/merge/keep decisions (blast radius + $ delta per family, never a default consolidation target); residual = disposition table + owner deletion + CE delta |
| 017 native-layer scanning | **STALE** | `pip_audit_lambda` coverage guard reds RED on unscanned layer; SBOM (syft) emitted; pip-audit enforced | closed by prior work |
| 018 CodeQL backlog | **STALE-as-filed / REGRESSED → TRIAGED 08-23** | D0.7 done: #151 js/redos FIXED (d02e64d63); #152 dismissed false-positive (integer counter, name heuristic); #153–157 dismissed intentional (emoji-block ranges). Open=1 pending re-scan of the fix; sentinel can-it-fail question filed on #2578 | D0.7 complete; #3047 closes on verified 0 |
| 021 auto site-deploy vs narrative | **CONFIRMED** | site-deploy.yml no approval by design (#750); org-chart essay claims universal click | Essay + /method/build editorial **corrected 2026-08-23** (D0.5 sweep — honest lane split: engine deploys gate on production approval, site auto-deploys behind QA + auto-rollback) |
| 023 heartbeat silent-fail | **STALE** | #1196 fixed; `test_heartbeat_completeness.py` + live liveness gauge | — |
| 024 clock-based sequencing | **CONFIRMED** | 5 compute lambdas run blind on cron; no completeness manifest | D3 source-completeness contract |
| 025 idempotency/replay | **CONFIRMED (arch risk)** | 7 email senders + write-MCP + webhooks; no enterprise-wide inventory | D3 idempotency census |
| 026 S3 noncurrent growth | **CONFIRMED** | `imports/` uncovered (2.23GB); no drift assertion (only post-hoc 50GB alarm) | D3 (#2799 home) |
| 027 single-region recovery | **CONFIRMED → COMPROMISE BUILD LANDED 2026-08-24** (autonomy-safe half) | SECURITY accepted no cross-region; DISASTER_RECOVERY scored "S3 bucket deletion" **NOT RECOVERABLE** and "us-west-2 outage" **hours-days, no DR region**. The irreplaceable surface is `raw/` alone — **measured 2026-08-24: 37,665 objects / 541,451,065 bytes (0.50 GiB), +563 objects / 16.2 MiB per 30d** — everything else (DDB metrics, derived artifacts, the whole site) recomputes from it. **Cross-ACCOUNT was investigated first and is not reachable**: `aws organizations list-accounts` returns exactly ONE account (205930651321, `o-zfnwrqb9mx`), so there is no second account to replicate into today | **Cross-REGION replication of `raw/*` built** (us-west-2 → us-east-2, deliberately not us-east-1 where LifePlatformWeb's ACM/CloudFront control plane already lives): new CDK-owned `LifePlatformBackup` stack (`cdk/stacks/backup_stack.py`) with a versioned, public-access-blocked, `RETAIN` replica bucket carrying its own `ProtectRawBackupFromDeployScripts` Deny (mirrors the primary's pattern, extended to `DeleteBucket`) + its own 30d noncurrent expiry; a replication role scoped to `raw/*` read and replica write, **with no `s3:ReplicateDelete`**; `DeleteMarkerReplication: Disabled` so source deletes never propagate (both halves guarded, `tests/test_raw_replication_dil027.py`). Source-side config is out-of-IaC by the imported-bucket constraint (`deploy/s3_replication.json` + `apply_s3_replication.sh`, the established lifecycle-script pattern; ledger row added). Source versioning was **already Enabled** (verified live, not assumed). Standing assertion: `deploy/sentinel_replication.py` in the weekly sentinel — config parity, destination versioning, and a registry-driven wire probe that reds on FAILED / stuck-PENDING / COMPLETED-but-absent-replica / **un-backfilled history**, and reports `degraded` rather than `clean` when it observed nothing (#2578). **Covers regional failure + primary-bucket destruction; does NOT cover account-level compromise** — that residual is the dated priced row below. **The owner-present timed restore drill is a scheduled owner appointment and remains open** |
| 028 raw-layout drift | **STALE (reverify)** | #1256 closed; `raw_layout` facets exist | D3 replay-proof test |
| 029 stale-cycle grounding | **STALE (reverify)** | closed coach-correction epic; standing assurance = D4 | D4 eval matrix |
| 030 stored-text injection | **STALE (reverify)** | #811 closed; expansion coverage = D4 | D4 eval matrix |
| 031 clinical operating model | **COMMERCIAL GAP** | no clinician-reviewed hazard register | D4 clinical-LITE build + PRICED (full) |
| 032 prediction grading/calibration | **CONFIRMED** | folds into DIL-007 diagnosis | D0.4 |
| 036 budget guard fail-open | **CONFIRMED (+ sharper) → FIXED + DEPLOYED 2026-08-23** | Fix (#3059, merged 837c97504): bare except split into named classes (ParameterNotFound / ClientError.Code / Unexpected) each logging `BUDGET_TIER_UNREADABLE reason=<class>` at ERROR; `FAIL_CLOSED_FEATURES=("website_ai",)` exported and consulted by `allow()` — public /api/ask + /api/board_ask are DENIED tier-3-equivalent on unreadable budget state (AST-pinned to the real `_ai_paused_response` wire path), while `current_tier()` stays fail-open 0 fleet-wide (protect-longest for the brief/narratives is deliberate — the "sharper" tier-3-backstop sub-finding is answered by design: a phantom tier 3 would take the protect-longest fleet down with the public surface, so the split lives at `allow()` + the alarm). 23 tests, mutation-proved both directions. **Deployed 19:00Z: cdk Monitoring (`budget-tier-unreadable` alarm live, metric filter on site-api-ai logs) + site-api-ai deploy_and_verify PASS** | Fold under #2824 stands for the generalized grant-enumeration set guard; residual = alarm routes to digest (not paging) matching sibling budget alarms — escalation posture is an owner call |
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
3. `budget_guard` tier-3 hard stop **shares the fail-open SSM path** — a grant regression silently disables the ceiling. → **CLOSED 2026-08-23** (#3059, deployed: public inference fails closed via `FAIL_CLOSED_FEATURES`, split excepts, `budget-tier-unreadable` alarm live — see DIL-036 row). #2824 keeps the generalized set-guard.
4. `check_doc_facts.py` **scans no `.js`** — the site's most-quoted number ships un-guarded. → **CLOSED 2026-08-23** (D0.5 sweep: the ceiling-literal scan now covers `site/**/*.js` + `site/**/*.html` (legacy excepted) + the `v4_*` generators, with planted-defect mutation proof in `tests/test_doc_facts_budget_2899.py`). D2 owns the wider truth manifest.
5. Privacy-tier registry and DATA_GOVERNANCE prose are **unreconciled twin sources**. → **CLOSED 2026-08-23** (#3045/ADR-155: full port + `tests/test_data_governance_tier_guard_3045.py` reconciles both directions — an unported prose row OR an ungoverned registry entry reds the build, mutation-proved on planted defects both ways).
6. `GradableCount` metric emitted but **no ratio alarm** — a permanently-ungradeable majority is invisible. → D0.4.
7. `imports/` (health uploads) noncurrent versions **uncovered by lifecycle**, no drift assertion. → D3.

## Priced-acceptance register (dated; revisit triggers)

_Populated as PROPORTIONALITY rows land. Standing entries: DIL-031 full clinical operating
model · DIL-033/034/037/043/044/045/046 commercial control plane — all **revisit trigger = a
commercialization decision**; DIL-004 self-approval residual — **structural to a solo
operator**, priced under #2834 · DIL-047/048 key-person — priced after the owner-handoff drill._

### DIL-027 — single-ACCOUNT recovery residual (dated 2026-08-24)

**What was built instead of the ideal.** The ideal control is a backup in a *different AWS
account*, so that a compromise of this account's credentials cannot reach it. That was
investigated first and is **not available**: `aws organizations list-accounts` returns exactly
one ACTIVE account (205930651321, org `o-zfnwrqb9mx`, joined 2026-07-12). Standing up a second
account, its billing relationship, its OIDC trust and its break-glass path is an owner
decision with real ongoing operational rent — not an autonomous build. So the compromise the
owner approved shipped: **cross-region replication of `raw/*` into an isolated, delete-protected
bucket in us-east-2.**

**What the backup DOES cover**
- **Regional failure.** us-west-2 goes away; `raw/` is readable in us-east-2. Deliberately not
  us-east-1 — LifePlatformWeb's ACM certs and CloudFront config already live there, so a
  us-east-1 event would otherwise take the platform and its backup together.
- **Primary-bucket destruction.** A separate bucket, separate versioning, its own Deny on
  `DeleteObject` / `DeleteObjectVersion` / `DeleteBucket` for `matthew-admin`, and
  `DeleteMarkerReplication: Disabled` + no `s3:ReplicateDelete` on the role — a delete on the
  source does not propagate. `RemovalPolicy.RETAIN`, so a `cdk destroy` cannot take it either.
- **Silent decay of the above.** `deploy/sentinel_replication.py` re-asserts the whole chain
  weekly and can turn red on five independent causes.

**What it does NOT cover — the accepted residual**
- **Account-level compromise.** Same account, same root, same credential blast radius. An
  attacker (or a catastrophic mistake) with account-level power can reach both buckets. The
  Deny statements name `matthew-admin` specifically and are removable by a principal that can
  edit bucket policies.
- **Everything outside `raw/`.** By design and by definition: DDB metrics, generated artifacts
  and the site are all recomputable from `raw/` plus git. DDB's own protection stays PITR (35d).
- **A proven restore.** The configuration is asserted; the *recovery* is not yet drilled. The
  owner-present timed restore drill is a scheduled appointment, explicitly out of scope here.

**Measured cost of the control** (ADR-105 — from the live inventory 2026-08-24, not a guess).
raw/ = 37,665 objects / 541,451,065 bytes = **0.504 GiB**, growing **563 objects / 16.2 MiB per
30 days**. At us-east-2 S3 Standard rates: storage 0.504 GiB × $0.023 = **$0.0116/mo**;
replication PUTs 563 × $0.005/1,000 = **$0.0028/mo**; cross-region transfer 0.0158 GiB × $0.02 =
**$0.0003/mo**. **Ongoing ≈ $0.015/month (~$0.18/year)**, rising about $0.0004/mo each month at
the current capture rate. One-time backfill of the pre-existing history ≈ **$0.49** (37,665 PUTs
$0.19 + 0.50 GiB transfer $0.01 + S3 Batch Operations job $0.29). **S3 Standard was chosen over
Standard-IA on the measurement, not the reflex**: mean object size is 14.4 KB against IA's 128 KB
minimum billable size, so IA would bill ~4.8 GB for 0.50 GB and cost ~5× more (~$0.06/mo).

**So the residual is not priced in dollars — the backup is effectively free. It is priced in
blast radius**: one account's compromise still reaches everything.

**Revisit triggers** (any one):
1. A second AWS account exists for any reason (then the destination moves cross-account — the
   stack and the replication configuration are already parameterized in
   `cdk/stacks/constants.py`).
2. The owner-present restore drill is performed and finds the replica unusable.
3. Commercialization, a second user, or any regulated/contractual data obligation.
4. `raw/` grows past ~50 GiB, at which point the storage line stops being a rounding error and
   the tiering decision should be re-measured rather than re-assumed.
5. Otherwise: **2027-02-24** (six months), re-read with the quarterly PROPORTIONALITY pass.

---
*Register opened 2026-08-23 (A-Grade Program, Phase S2-close). Updated per phase; D5 runs
`scripts/diligence_verify.py` (the report's §15 playbooks, scripted) to regenerate the
live-evidence column before the external re-grade.*
