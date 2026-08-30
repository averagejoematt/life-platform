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
| 018 CodeQL backlog | **STALE-as-filed / REGRESSED → TRIAGED 08-23; REGREW + RE-TRIAGED 08-29** | D0.7 done: #151 js/redos FIXED (d02e64d63); #152 dismissed false-positive (integer counter, name heuristic); #153–157 dismissed intentional (emoji-block ranges); #3047 closed on verified 0. Then six NEW high-severity alerts grew from new code 08-25→08-26 (#162–168: 4× clear-text-logging on secret NAMES/S3 keys/quota counts, 2× url-substring in test fakes) and sat open 3–4 days — all six dismissed 2026-08-29 with per-alert reasons (Fable re-grade walk; `diligence_verify` DIL-018 red → green same day) | D0.7 complete. The honest residual is CADENCE, not state: steady-state-0 holds only when a session looks — new-alert triage has no dead-man. Class question stays on #2578 (the declared-armed sentinel that did not fire) |
| 019 integration tests not a pre-merge gate | **STALE (row added 2026-08-29 — the id was missing from this register entirely; Fable re-grade walk)** | At filing, only the deploy-critical subset ran pre-merge. Since #3025 the FULL unit suite is a named pre-merge check on every PR ("Full unit suite (pre-merge, issue 3025)" — observed live on PR #3295, 2026-08-29). Live-EDGE integration (Playwright visual QA, HTTP smoke, edge-429 observation) runs post-deploy by DESIGN — ADR-076's three QA layers + auto-rollback | Pre-merge full suite = done (#3025). The post-deploy placement of browser/edge integration is the recorded ADR-076 architecture, not a gap; revisit on commercialization (a tenant cannot be rolled back out of an error they already saw) |
| 020 security tests pass against a false production model | **CONFIRMED (row added 2026-08-29 — previously only named in the header fold line)** | The report's thesis proved live repeatedly after filing: Session F (08-27) found five green instruments measuring nothing; the census itself had counted ten libraries as gates on a filename substring. Remediation is the #2578 program: 565 gates inventoried by derivation, `PROVEN_CAN_FAIL` mutation registry + re-runnable harness (`scripts/gate_census_mutations.py --run` — plant the defect, watch the red, revert), the sentinel two-half bar (detect AND cannot-observe must both prove), fixture-must-be-the-wire discipline | Owned by #2578 (open epic, active); the unproven-gate ceiling is a ratchet (committed 541, live 534 on 08-28) — the disposition is the program, and the program is measurably draining |
| 022 shared-code change ⇒ fleet-wide redeploy (~104 fns) | **CONFIRMED → PRICED (row added 2026-08-29 — the id was missing from this register entirely)** | True by construction: the #781 one-bundle rule stages the whole `lambdas/` tree into every function, so a `common/` edit redeploys the fleet. This is the RECORDED trade (docs/CONVENTIONS.md §1): it bought the death of the layer-skew class (functions running different shared-code versions), which had produced real incidents; fleet deploys are scripted (`build_bundle.py` + postflight content-greps, never sha-trust) | PRICED: revisit trigger = bundle size or cold-start cost crossing the budget close's line, a per-function isolation need, or commercialization. Until then one artifact = one truth is the cheaper defect class |
| 021 auto site-deploy vs narrative | **CONFIRMED** | site-deploy.yml no approval by design (#750); org-chart essay claims universal click | Essay + /method/build editorial **corrected 2026-08-23** (D0.5 sweep — honest lane split: engine deploys gate on production approval, site auto-deploys behind QA + auto-rollback) |
| 023 heartbeat silent-fail | **STALE** | #1196 fixed; `test_heartbeat_completeness.py` + live liveness gauge | — |
| 025 idempotency/replay | **CONFIRMED (arch risk) → CENSUS LANDED + FIX LANDED** (2026-08-24) | Was: "7 email senders + write-MCP + webhooks; no enterprise-wide inventory". The census found the sender surface **4× wider than the finding assumed — 28 SES-sending handlers, not 7** (derived by AST, not hand-listed). It also found the premise sharper than stated: the replay vector is not hypothetical — `dlq_consumer_lambda.classify_message` **defaults an unrecognised failure to TRANSIENT**, and `retry_message` re-invokes the original function with the original payload on `rate(6 hours)`, while the only durable guard in place (#2860's in-flight lease) is **1200s**, so a redrive was structurally invisible to it. And the daily brief wrote its completion row ~445 lines AFTER the SES call, so "sent then crashed" lost the only evidence the mail went out | **`docs/IDEMPOTENCY.md` is the census** (now in the docs index): the 3 replay vectors, which existing gate covers which (`send_guard` = operator safety, `daily_brief_lock` = in-flight lease, neither = replay), then every path × trigger × dedup-mechanism-today × redrive-safe × evidence pointer. **Honest verdicts, not optimistic ones:** 6 of 28 senders replay-safe (`daily_brief` — this PR; `monthly_digest` #1658; `chronicle_email_sender` #2112 `delivered_at`; `wednesday_chronicle` #2254; `coach_nudge` `_reserve_day`; `coach_panel_podcast` artifact check), 22 not. **Cheap gap fixed in the same PR:** new `lambdas/common/send_ledger.py` — the durable half, reusing the `email_log` row the status page already reads, given a `period_key` naming WHICH letter was sent (a sort-key-only check misses a redrive crossing UTC midnight, which the 17:00-UTC brief hits ~half the time); wired into daily-brief as a pre-send guard + a completion write moved to **one line after** the SES call. Fail-open both halves; `force_send` honoured via `dry_run.force_requested` so the vocabulary stays single-sourced (#2255/#2222). **Two guards:** `tests/test_send_replay_guard_dil025.py` drives the REAL EventBridge scheduled event through the REAL `dlq_consumer.retry_message` (proving the replayed payload is byte-identical to the original) and then through `lambda_handler` — mutation-proved: disabling the guard in source makes the acceptance test fail. `tests/test_idempotency_census_dil025.py` derives the sender set from the SAME AST walk #2222 uses, so a 29th sender must add a row or red. **Non-cheap classes filed, not hand-waved:** #3113 (22 remaining senders — `milestone_digest`/`partner_email` mail third parties, done first), #3114 (timestamp/uuid-keyed MCP writes; `manage_reading debrief` also starts a 2nd recall clock), #3115 (Todoist/Hevy creates with no vendor idempotency key), #3118 (site-api-ai follow-up append burns 2 of 3 reader turns; date-prefixed S3 doors reset moderation status), #3119 (HAE residuals). **Good news recorded too:** HAE water/caffeine do NOT double-count (absolute `SET` + reading-map recompute), and the vote/follow/certify family's conditional-dedup-row-before-counter is the pattern the rest should copy |
| 026 S3 noncurrent growth | **CONFIRMED → FIXED 2026-08-24 (pending post-merge apply)** | Was: `imports/` uncovered (2.23GB measured 08-23, 2.07GB reconfirmed 08-24); no drift assertion (only post-hoc 50GB alarm, which cannot name which prefix drifted). Live sizing (`list_object_versions` by top-level prefix, 08-24): `deploys/` dominates noncurrent bytes (41.5GB) but its #2642 rule IS live and matches declared config exactly — a 7-day rolling-window artifact of this session's deploy velocity, not a coverage gap | `imports/` covered (`deploy/s3_lifecycle.json` + `apply_s3_lifecycle.sh`, 7d noncurrent/keep-1, same shape as `raw/`); declared-vs-live drift assertion live in `deploy/drift_sentinel.py::check_s3_lifecycle` (weekly, mutation-proved missing/extra/changed-rule both directions, wired into the existing report → needs-human path); `life-platform-s3-bucket-size-high` re-derived 50GB→65GiB from the measured ~52-55GB steady state (ADR-105, ~20-25% headroom). Deploy note: needs `bash deploy/apply_s3_lifecycle.sh` post-merge in addition to `cdk deploy LifePlatformMonitoring` — the lifecycle bucket is out-of-IaC and CDK does not touch it |
| 024 clock-based sequencing | **CONFIRMED → FIX LANDED 2026-08-24** | Was: 5 compute lambdas run blind on cron; no completeness manifest. Now (#3049): every run of the five judges its declared inputs against the registry's OWN `stale_hours` and stamps the verdict onto its output — `input_status` ∈ complete/partial/unknown plus a per-source `input_manifest` (fresh/stale/missing/paused/unknown, PT-framed, DST-correct). Stamped at ONE chokepoint (`common.compute_metadata.tag_record`, which already stamps run_id/computed_at/phase), so the 8 declared output partitions get it with zero call-site plumbing. Published on `/api/character` and rendered as a labeled block in the daily brief (ADR-104). **Crons unchanged** — the issue's explicit scope guard, pinned by `test_no_new_event_wiring_in_compute_stack`. Evidence: `tests/test_input_manifest_contract_3049.py` (54 tests; 3-way mutation proof recorded in its docstring — cannot-say-partial 6 red, cannot-say-fresh 10 red, chokepoint-unwired 2 red). The DST half found a REAL bug in this module's first draft: Python's aware-datetime subtraction ignores tzinfo when both operands share the same tzinfo object, silently reverting to naive wall-clock arithmetic across both 2026 transitions | #3049 — residual: the manifest is provenance, not a gate (no run is blocked); chaining an upstream `partial` through downstream derived partitions is a named follow-on |
| 028 raw-layout drift | **REVERIFIED 2026-08-24 — facets existed but were unproven; live walk found + fixed real drift** | `tests/test_dil028_raw_layout_replay.py` (48 tests): a registry-driven scanner walk proves `raw_date_key`/`raw_year_prefix`/`raw_date_key_candidates` resolve every scheme family (framework `YYYY-MM-DD.json`, HAE `DD.json`, legacy no-user-segment, hevy flat-UUID) against REAL `aws s3 ls` listings (read-only, no writes), plus one backfill-reconcile test per family proving the REAL writer code (`ingestion_framework._archive_raw`, HAE's `save_*_to_s3`, `hevy_common.normalize_workout`/`archive_raw`) and the registry's reader-side resolver agree on the same key. The walk found the drift #1256 only prose-documented for todoist/garmin ALSO existed, undocumented, on eightsleep/withings/strava — all five now carry a machine-readable `filename_legacy` facet + the new `raw_date_key_candidates()` resolver (`lambdas/ingestion/source_registry.py`). Deliberately NOT a hard cutover date: live evidence on garmin shows a post-migration gap-fill re-fetched 2026-05-05..05-16 into the CURRENT format despite naming pre-migration dates — the generation depends on when an object was written, not what date it names. Residual (explicitly out of scope): `raw/matthew/whoop/{cycle,sleep,recovery,workout}/`, a structurally distinct pre-2026 per-metric-type archive the current facet doesn't model — filed as a follow-up if pre-2026-05-17 whoop replay is ever needed | D3 replay-proof test — DONE |
| 027 single-region recovery | **CONFIRMED → COMPROMISE BUILD LANDED 2026-08-24** (autonomy-safe half) | SECURITY accepted no cross-region; DISASTER_RECOVERY scored "S3 bucket deletion" **NOT RECOVERABLE** and "us-west-2 outage" **hours-days, no DR region**. The irreplaceable surface is `raw/` alone — **measured 2026-08-24: 37,665 objects / 541,451,065 bytes (0.50 GiB), +563 objects / 16.2 MiB per 30d** — everything else (DDB metrics, derived artifacts, the whole site) recomputes from it. **Cross-ACCOUNT was investigated first and is not reachable**: `aws organizations list-accounts` returns exactly ONE account (205930651321, `o-zfnwrqb9mx`), so there is no second account to replicate into today | **Cross-REGION replication of `raw/*` built** (us-west-2 → us-east-2, deliberately not us-east-1 where LifePlatformWeb's ACM/CloudFront control plane already lives): new CDK-owned `LifePlatformBackup` stack (`cdk/stacks/backup_stack.py`) with a versioned, public-access-blocked, `RETAIN` replica bucket carrying its own `ProtectRawBackupFromDeployScripts` Deny (mirrors the primary's pattern, extended to `DeleteBucket`) + its own 30d noncurrent expiry; a replication role scoped to `raw/*` read and replica write, **with no `s3:ReplicateDelete`**; `DeleteMarkerReplication: Disabled` so source deletes never propagate (both halves guarded, `tests/test_raw_replication_dil027.py`). Source-side config is out-of-IaC by the imported-bucket constraint (`deploy/s3_replication.json` + `apply_s3_replication.sh`, the established lifecycle-script pattern; ledger row added). Source versioning was **already Enabled** (verified live, not assumed). Standing assertion: `deploy/sentinel_replication.py` in the weekly sentinel — config parity, destination versioning, and a registry-driven wire probe that reds on FAILED / stuck-PENDING / COMPLETED-but-absent-replica / **un-backfilled history**, and reports `degraded` rather than `clean` when it observed nothing (#2578). **Covers regional failure + primary-bucket destruction; does NOT cover account-level compromise** — that residual is the dated priced row below. **The owner-present timed restore drill is a scheduled owner appointment and remains open** |
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
| 049 founder-calibrated scoring | **CONFIRMED (arch) → D4 cheap half LANDED 2026-08-24** | single-subject validity doesn't go away with a label (that half stays PRICED below); the labeling gap is real and now closed on the two surfaces the inventory found unlabeled | D4 score-transparency (cheap half) — see detail below; single-subject validity PRICED (commercialization / a second subject) |
| 050 deletion propagation map | **PARTIALLY** | archives well-documented; propagation machinery absent | D3/D-later |
| 051 accessibility coverage | **STALE (reverify)** | WCAG audit due | D-later |
| 052 self-referential grading | **CONFIRMED** | REVIEW_METHODOLOGY concedes it; **this external review is the answer** | ongoing (external re-grade cadence) |

### DIL-049 — score-transparency sweep (D4 cheap half, done 2026-08-24, part of #3042)

The finding is real and split into two halves that don't share a fix. **Single-subject
validity** — every score on the platform is calibrated against one person's own history,
n=1 by design — is not something a label can close; it stays a dated PRICED acceptance
(revisit trigger: a second subject, or commercialization). **The cheap half** is
different: does every public score surface say what happens when its input data is
missing, and does a score built from a thin/degraded window render identically to one
built from a full one? That's a labeling sweep, not a research problem, and it was
mostly already done by prior work (#3049/DIL-024, #1084/#1917, #1370, #747, #2388) —
the sweep's job was to find what that prior work missed.

**Inventory (every public score surface, 2026-08-24):**

| Surface | Missing-data answer | Low-n/thin-window answer | What changed |
|---|---|---|---|
| `/api/character` pillar scores | Already excellent: per-pillar `data_coverage`, `coverage_hold`, `not_instrumented`/`not_instrumented_note`, `absent_behaviors`, #2388 `absence` state, document-level `input_manifest` (#3049/DIL-024) | Coverage-gated leveling (below the coverage floor a day carries no leveling signal, ADR-104) already stated on /method/game | Nothing — already labeled. **Found one real gap: the whole-life `composite_score` averages only the instrumented pillars but never said how many** — a 3-of-7 composite rendered identically to a 7-of-7 one. Added `composite_pillar_count`/`composite_pillar_total`/`composite_note` (labeling only, no computation change) |
| `/api/snapshot` readiness score (the Cockpit hero) | **Gap found**: `computed_metrics` (the record backing it) already carries `input_manifest` from #3049 — daily-metrics-compute is one of the five stamped Lambdas — but `_latest_readiness()` never read it, so a readiness score built on stale/missing whoop input rendered identically to a clean one | `readiness_components` already serves the score's real inputs (#492/M-4); no separate n to disclose (single-day score, not a window average) | Added `input_manifest` to the `_latest_readiness()` payload (shared `_public_input_manifest` helper, moved to `web/site_api_common.py` so both `/api/character` and the readiness block use the same shape/wording) + a `.rd-confidence` caption on `/cockpit/` that only renders when the note is non-empty |
| `/api/vitals` (weight/HRV/recovery/RHR/sleep) | Already excellent — the reference pattern this sweep followed: `window_disclosure`, `*_30d` fields null below `_MIN_AVG_N`/below a genuine 30-day window, `weight_as_of`/`recovery_as_of`/`sleep_as_of` divergence called out in prose | Same — `hrv_avg_n`/`hrv_avg_window_days` ride beside the average | Nothing — reference implementation, no gap |
| `/api/calibration` (coach prediction Brier scores) | `label`/`score`/`calibration` verdict is n-gated (`n < 3` → "nascent"; `skilled` is `None`, never punished as False, when undefined); `not_yet_skillful` is a distinct dignified state from "well-calibrated" (#1370) | Same fields carry the n directly (`n`, `n_eff` where applicable) | Nothing — already labeled |
| `/api/character_calibration` (felt-reality pillar calibration) | Confidence grammar already explicit: below `FELT_CALIBRATION_MIN_WEEKS` → `"uncalibrated (n=X)"` with no `r`; between MIN and CI_MIN weeks → point estimate with `ci95: null` (never a fabricated band) | Same — `n_weeks`/`gates` published per pillar | Nothing — already labeled |
| `/method/game` (composition explainer) | "When the data goes dark" section already narrates the full rule set: absent behaviors score 0, sensors drop out of the weight sum, thin days blend toward neutral for *display only* (level gates read the unblended number), a never-instrumented pillar shows a placeholder not a reading, neglect atrophy, visible XP debt. The headline section already states the composite's renormalization rule | N/A — this page is the static rulebook, not a live score | Nothing — the rule was already documented; the live surface just never showed whether the rule was doing anything *today* (see the `/api/character` row above) |

**Constraint honored:** every change above is additive labeling on top of an unchanged
score computation — no `character_engine.py`, `daily_metrics_compute_lambda.py`, or
`calibration_core.py` line changed. Tests:
`tests/test_dil049_score_transparency.py` (7 tests, each surface's disclosure proved
both ways — appears when thin/degraded, absent or silent when complete — the
mutation-proof shape: deleting either branch of the new code fails one test in its
pair).

## Findings our verification produced (not in the report)

1. `main` has **no required status checks at all** — `main-required-fast-lane` unapplied; CONTRIBUTING's "PRs required" is false. → D0.6.
2. **CodeQL regrew 7 alerts (2 high)**, one a recurrence-shaped hit on #1902's clear-text-logging class; `drift_sentinel.check_codeql_alerts` did not surface it → a #2578 can-it-fail question. → D0.7. **Triaged 2026-08-23: 1 fixed, 6 dismissed with reasons (see DIL-018 row); the "recurrence" was a name-heuristic false positive on an integer counter.**
3. `budget_guard` tier-3 hard stop **shares the fail-open SSM path** — a grant regression silently disables the ceiling. → **CLOSED 2026-08-23** (#3059, deployed: public inference fails closed via `FAIL_CLOSED_FEATURES`, split excepts, `budget-tier-unreadable` alarm live — see DIL-036 row). #2824 keeps the generalized set-guard.
4. `check_doc_facts.py` **scans no `.js`** — the site's most-quoted number ships un-guarded. → **CLOSED 2026-08-23** (D0.5 sweep: the ceiling-literal scan now covers `site/**/*.js` + `site/**/*.html` (legacy excepted) + the `v4_*` generators, with planted-defect mutation proof in `tests/test_doc_facts_budget_2899.py`). D2 owns the wider truth manifest.
5. Privacy-tier registry and DATA_GOVERNANCE prose are **unreconciled twin sources**. → **CLOSED 2026-08-23** (#3045/ADR-155: full port + `tests/test_data_governance_tier_guard_3045.py` reconciles both directions — an unported prose row OR an ungoverned registry entry reds the build, mutation-proved on planted defects both ways).
6. `GradableCount` metric emitted but **no ratio alarm** — a permanently-ungradeable majority is invisible. → D0.4.
7. `imports/` (health uploads) noncurrent versions **uncovered by lifecycle**, no drift assertion. → **CLOSED 2026-08-24** (see DIL-026 row): coverage + `check_s3_lifecycle` drift assertion landed; `bash deploy/apply_s3_lifecycle.sh` still pending post-merge.

## Priced-acceptance register (dated; revisit triggers)

**Finalized 2026-08-25 (D5).** Every priced acceptance now has a dated row in
`docs/PROPORTIONALITY.md` with a named revisit trigger. "PRICED" with nothing behind it is
the same shape as the stale `MANAGED_WHERE_LEDGER` that manufactured three of this
report's own false positives, and it is not a disposition this register is willing to ship.

| Priced row (in `docs/PROPORTIONALITY.md`) | DIL | Revisit trigger |
|---|---|---|
| Absent commercial control plane | 033/034/037/043/044/045/046 | a commercialization decision — a second user, any paid tier, or a contractual/regulated obligation. **Not date-based:** waiting does not make a customer appear |
| No clinician-reviewed hazard register (full model) | 031 | a second user · any public claim crossing from description into diagnosis/treatment · a real adverse event traced to platform output · commercialization. D4 builds the clinical-**lite** half regardless |
| Key-person concentration / no segregation of duties | 047/048 | a second operator exists · the owner-handoff drill finds the written record insufficient · commercialization. The honest residual is recovery **time**, not recoverability — and it is explicitly NOT closed by the DIL-027 backup, which protects data, not decision continuity |
| Self-approvable production gate | 004 residual (#2834) | a second operator exists. The gate is live and blocking (re-verified 2026-08-25 by `diligence_verify.py`); the residual is that its sole reviewer is its sole author — a deliberate *pause* with an audit record, which is real, and not an *independent check*, which would be a self-flattering claim |
| No edge WAF | 014 | 2026-10-15 (owner-set), or immediately on observed abuse / a non-self-inflicted spike fire / commercialization |
| Single-ACCOUNT recovery residual | 027 | a second AWS account · a failed restore drill · commercialization · `raw/` > ~50 GiB · otherwise 2027-02-24 (detail below) |
| No independent evidence coaching changes behavior; feature surface exceeds visible evidence | 039/040 | first graded-prediction cohort matures (≥10 graded outcomes — earliest window 2026-08-31, so this trigger is MECHANICAL, not aspirational) · any public claim that coaching caused an outcome · commercialization. *(Row added 2026-08-29 — the Fable re-grade walk found 039/040 marked "PRICED / D-later" with no row here, the exact shape this section calls itself unwilling to ship)* |
| Single-subject validity of all scoring/calibration | 049 (the non-cheap half; D4's transparency sweep shipped the cheap half) | a second subject · any external claim of generalization · a published methods artifact. *(Row added 2026-08-29, same walk)* |

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

## D5 — the acceptance instrument (2026-08-25)

`scripts/diligence_verify.py` is the report's §15 verification playbooks, scripted. It
exists so the dispositions above stop being prose an assessor has to trust and become
checks an assessor can run. It answers one question per playbook, against **live** state:
*if an external reviewer re-ran this check today, what would they see?*

That framing is why almost nothing in it reads the repo. A grep proving `field_tiers.py`
declares a field Tier-2 is not evidence — the evidence is that the live public API does
not serve it. Four families, mirroring §15's grouping:

| Family | Playbooks | What it asserts |
|---|---|---|
| `control` | 4 | production approval gate live · main ruleset active (deletion + non-fast-forward) · vulnerability alerts enabled · 0 open CodeQL alerts |
| `privacy` | 3 | no tracked file declares itself PRIVATE · the 5 relocated coaching docs 404 on the raw endpoint · no owner-only field appears on 4 public API payloads |
| `prediction` | 2 | calibration is internally coherent (a `skilled` claim must follow from `brier_skill`, both directions) · the gradable-share alarm exists and is OK |
| `edge` | 3 | live `script-src` is exactly `'self'` · the nightly real-edge 429 observation is installed and wired · public data is fresh **and dates itself** (ADR-104 window disclosure) |

**First full run, 2026-08-25 01:5xZ — `12 PASS · 0 FAIL · 0 UNVERIFIED`, exit 0 under
`--strict`.** Bundle: `docs/reviews/evidence/diligence_verify_2026-08-25.json`.

### Three verdicts, not two — and why that is the whole design

`UNVERIFIED` is a first-class outcome alongside `PASS`/`FAIL`, and is never folded into
either. The failure mode this guards is the one the program has now found three times in
its own machinery: `drift_sentinel.check_codeql_alerts` had declared itself armed for
weeks while **never once successfully reading the code-scanning API** (#3112 — a
billing-scoped token, a missing `security-events: read` scope, and an error-treated-as-
no-drift fail-soft, each independently sufficient), and every one of those defects
produced a clean-looking result. So here: an auth failure, a transport error, a changed
API shape, an emptied registry vocabulary, or an unexpected exception all yield
`UNVERIFIED` with a stated reason. `--strict` — the mode the evidence pack is generated
in — exits non-zero on it. **An evidence bundle with an unobserved row is not an evidence
bundle.**

### The instrument is mutation-proved, because an unfalsifiable instrument is worthless

`tests/test_diligence_verify_d5.py` (36 tests) plants a defect at the seam each playbook
reads and asserts the verdict flips: a demoted approval gate, a dropped `non_fast_forward`
rule, a re-disabled Dependabot, an open CodeQL alert, a planted PRIVATE marker, a
re-served coaching doc, a leaked owner-only field, a calibration surface claiming skill it
has not earned (**and** one understating skill it has), a returned `'unsafe-inline'`, a
re-allowlisted CDN, an unwired 429 observation, stale data, a dropped window disclosure.
A second group asserts the `UNVERIFIED` paths. The suite was itself checked for vacuity:
neutering three playbooks turns four tests red.

### Honest scope — what this instrument does NOT prove

- **Coverage is 14 of 52 findings** (`DIL-001/002/004/005/006/007/008/011/014/015/018/023/
  024/032`), and that fraction is **derived from the playbook registry at runtime**, never
  hand-typed — a hand-maintained copy of it is exactly the literal-drift class #3101 killed.
  The remainder are priced acceptances, commercial gaps, and product findings that no
  script can verify; they are answered by the dated rows above, not by this run.
- **`privacy_relocated_docs_are_404` proves the current surface is gone, nothing more.**
  Historical copies remain reachable by direct sha — the dated risk acceptance under
  DIL-001 — and no HTTP check can or should claim otherwise.
- **`edge_rate_limit_enforced` proves the nightly observation is installed, wired and
  able to fail — not that last night's run observed a 429.** That verdict lives in the
  qa-smoke output's own RED / could-not-observe vocabulary (#3058). The first draft of
  this playbook cited the aggregate `qa-smoke-failures` alarm as evidence and so printed
  `PASS` directly above `alarm = ALARM`; the citation was removed rather than explained.
- **One first-draft false positive is recorded here deliberately.** The initial
  no-PRIVATE-markers playbook used a naive substring test and flagged *this register*,
  which quotes the marker inside a table cell as DIL-001's evidence. The fix was not a
  special case but the single-source one: the playbook now imports the canonical
  predicate from `tests/test_no_private_markers_3043.py`, which already documented that
  quote as benign. Two guards with two definitions of the same word is the twin-sources
  drift class closed elsewhere in this same register (DIL-011/#3045).

### Standing use

Run before any external re-grade, and after any change to the control plane, privacy
surface, or CSP. The bundle is deterministic — two runs over unchanged state produce
byte-identical JSON (pinned by test), so a diff between dated bundles is a real change in
the platform's posture rather than noise.

---
*Register opened 2026-08-23 (A-Grade Program, Phase S2-close). Updated per phase. D5's
`scripts/diligence_verify.py` is the acceptance instrument; its dated bundles under
`docs/reviews/evidence/` are the live-evidence column.*
