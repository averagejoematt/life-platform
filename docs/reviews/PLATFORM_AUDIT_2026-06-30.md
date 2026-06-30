## Platform Audit — Final Report
**Date:** 2026-06-30 · **Scope:** averagejoematt.com / life-platform (AWS us-west-2) · **Findings surviving adversarial verification:** 23 across 10 lenses

---

### 1. Executive Summary

The platform is **fundamentally healthy**. The adversarial sweep surfaced **zero P0 and zero P1 findings** — there is no active data-loss, no live credential compromise, no broken core pipeline, and no exploitable public write that escalates to authenticated data. The engine's defining strengths (single-table discipline, the LeadingKeys IAM pattern, the Coherence Sentinel, freshness/reconciliation heartbeats, budget guard, the enforced format gate) are real and mostly working as designed. What remains is a **long tail of P2/P3 quality, correctness, and hygiene issues** — the kind a maturing single-maintainer system accretes — none individually urgent, but several clustering into systemic patterns worth more than the sum of their parts.

The **headline risks** are four P2 findings, two of which are the same root cause: **UTC-vs-Pacific date selection** silently breaks two scheduled features. The `circadian-compliance` lambda (7 PM PT cron) and the `evening-nudge` lambda (8 PM PT cron) both compute their working date in UTC, which is *tomorrow* in Pacific time during their scheduled window — so circadian scores an empty future day and publishes the garbage to the public cockpit, while the nudge reports every manual source "not logged" on every run. Both are textbook **incoherent-but-green**: 200 responses, records written, every liveness/freshness check passing, output wrong. The other two P2s are a **CI gate-coverage hole** (pushes that touch only `cdk/`, `ci/`, or `config/` run no pipeline at all — so IAM, alarm, and layer-version changes bypass the very gates built to police them, and the remediation auto-merge ALLOWLIST relies on a post-merge re-run that provably never happens for its own files) and a **dead `role=button`** on the flagship Cockpit consistency band (announced to assistive tech as "open detail," wired to nothing). The strongest systemic signal across the P3 tier is **multiple-source-of-truth drift**: three diverged vice denylists (the chronicle's only deterministic gate misses "edible/edibles," an explicitly-moderated substance), CI-vs-dev tooling pins that disagree by a year, and onboarding/architecture docs whose auto-synced headers mask stale bodies — all variations on "the same fact lives in N places and they've drifted."

---

### 2. Severity Dashboard

**By severity**

| Severity | Count |
|----------|-------|
| P0 | 0 |
| P1 | 0 |
| P2 | 4 |
| P3 | 19 |
| **Total** | **23** |

**By lens**

| Lens | Prefix | Count | Severities |
|------|--------|-------|-----------|
| Security | SEC | 2 | P3, P3 |
| Architecture | ARCH | 0 | — |
| Cost | COST | 1 | P3 |
| Reliability | REL | 3 | P3, P3, P3 |
| Correctness | BUG | 5 | P2, P2, P3, P3, P3 |
| Code Quality | CQ | 4 | P3 ×4 |
| Privacy | PRIV | 3 | P3 ×3 |
| DevOps / CI-CD | DEVOPS | 2 | P2, P3 |
| Product / IA | PROD | 1 | P3 |
| Frontend / a11y | FE | 2 | P2, P3 |

---

### 3. Systemic Themes

These cross-cutting patterns are the real output of the audit; the individual findings are instances.

1. **UTC-vs-Pacific date selection (incoherent-but-green).** Three findings (BUG-01, BUG-02, BUG-03) share one root cause: code computes "today"/"the latest complete day" with `datetime.now(timezone.utc)` while the data is keyed by the Pacific day the behavior occurred, and the consumers run in the PT evening (≈01:00–03:00 UTC the next day). The platform already has the canonical fix (`ZoneInfo("America/Los_Angeles")`, used in `output_writers.py:1313` and inside the very same circadian file's `_parse_time_to_hour`). This is the same class as the #133 circadian DST fix — that one fixed time-of-day parsing; the *day-selection* sibling was never swept. **A single shared `pacific_today()` helper in the layer would close all three and prevent recurrence.**

2. **Silent-failure detectors that can themselves go silent.** REL-01: every alarm uses `treat_missing_data=NOT_BREACHING`, including the alarms whose entire job is to catch silence (ingest-liveness, interior-gap, reconciliation, coherence-overall). A *crashing* producer trips an Errors alarm; a producer that simply *stops being invoked* emits no metric and the detector sits OK forever. The team solved this once (the WR-48 freshness heartbeat) but never generalized it. This is the meta-monitoring blind spot at the foundation of the whole "catch the silent failure" program.

3. **Multiple-source-of-truth divergence.** The most frequent P3 pattern. Vice denylists exist in three places that have drifted (PRIV-01); format/lint pins differ between CI and `requirements-dev.txt` (CQ-01); the config comments call the gate "advisory" while CI enforces it (CQ-04). Each is a place where one fact should live once. **Several findings recommend the same remedy: collapse to one canonical source + a CI test asserting the others derive from it** — the exact pattern the platform already adopted for `measurable_metrics`/`canonical_facts` in the coherence program.

4. **Documentation drift behind a fresh façade.** CQ-02/CQ-03/PRIV-03: auto-sync stamps *one header line* fresh (`sync_doc_metadata.py`), which makes a reader trust the stale body. ARCHITECTURE.md says layer v76 (code is v92), CLAUDE.md self-labels "136 tools — source of truth" (actual 144), DATA_GOVERNANCE.md understates deployed deletion/export tooling and the public biomarker set. For docs whose *stated purpose* is to be authoritative (architecture reference, compliance answer sheet), drift is a governance risk, not a cosmetic one.

5. **IAM least-privilege known-but-not-applied.** SEC-01 and DEVOPS-02: the team demonstrably knows the right pattern (`site_api_ai` scopes writes with `LeadingKeys: RATE#*`) yet the sibling public `site_api` role has unconditioned PutItem/UpdateItem on the entire health table; the OIDC deploy trust subject is `repo:*` (any ref) on a role that reads every secret and overwrites any lambda. Both are bounded by being single-maintainer, but the blast radius is maximal where it matters.

6. **CI/auto-merge gate coverage holes (the masking class).** DEVOPS-01 + CQ-01/CQ-04: the push-path filter excludes `cdk/`/`ci/`/`config/`, so infra/IAM/layer changes get no pipeline — and the auto-merge gate's comment asserts a post-merge CI re-run that does not exist for its own ALLOWLIST. Compounded by the recurring black/ruff "masking" failure mode CLAUDE.md repeatedly recounts.

7. **Built-but-stranded surfaces.** PROD-01 (the entire Reading/Mind pillar — first-ever GSIs, 8 tools, a page — is undiscoverable from nav/home/sitemap), BUG-01 (circadian publishes a meaningless score publicly), and FE-01 (a Cockpit control announced as interactive, wired to nothing). High build investment, zero or negative user value as shipped.

---

### 4. P0, P1 & P2 Findings (detailed)

> **There are no P0 or P1 findings.** The four P2 findings below are the highest-severity issues in the audit and constitute the headline risk surface; they are documented to the P0/P1 standard.

---

#### BUG-01 — circadian-compliance scores the wrong (empty, future-PT) day every evening
**Severity:** P2 · **Lens:** Correctness · **Confidence:** High
**Location:** `lambdas/compute/circadian_compliance_lambda.py:492` (date derivation), `:214/:241/:138` (source fetches); `cdk/stacks/compute_stack.py:337` (cron `0 2 * * ? *` = 7 PM PT); served at `lambdas/web/site_api_data.py:1937`.
**What & why:** The handler derives `today_str = event.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")`. At 02:00 UTC the Pacific date is the *previous* day, so the UTC date is *tomorrow in PT* — a day that hasn't happened yet. Strava (`start_date_local`), MacroFactor, and Notion/journal are all PT-keyed, so every component reads an empty day and collapses to no-data defaults (morning_light → 5 "unable to confirm," meal_timing → 12 "No MacroFactor data"). #133 fixed time-of-day DST parsing; the day-*selection* bug is separate and remains.
**Impact:** The entire circadian feature emits a near-constant baseline "no data" score every day, computed against an empty day, and that meaningless number is published on the public `/now` cockpit "tonight's forecast" tile. Incoherent-but-green: 200, record written, all checks pass, output wrong.
**Recommendation:** Derive the working date in Pacific time (`datetime.now(ZoneInfo("America/Los_Angeles"))`), the canonical pattern already used elsewhere in this file. Add a unit test pinning the clock to 02:30 UTC asserting `today_str` is the PT date. **Merge the fix with BUG-02/BUG-03 via a shared `pacific_today()` layer helper.**

---

#### BUG-02 — evening-nudge always reports every manual source missing (UTC date in an 8 PM PT cron)
**Severity:** P2 · **Lens:** Correctness · **Confidence:** High
**Location:** `lambdas/emails/evening_nudge_lambda.py:187` (date), `:53/:80/:102` (completeness checks); `cdk/stacks/email_stack.py:268` (cron `0 3 * * ? *` = 8 PM PT).
**What & why:** The nudge's purpose is to remind Matthew before midnight PT about manual data not yet logged *today*. But it computes `today = datetime.now(timezone.utc)` and reads that UTC date for supplements (`get_item DATE#<utc-today>`), journal (`begins_with DATE#<utc-today>#journal#`), and apple_health/state-of-mind. At 03:00 UTC the PT date is the previous day, so the UTC date is tomorrow-in-PT — zero records regardless of what was logged.
**Impact:** The nudge is a permanent false alarm: it emails "supplements/journal/state-of-mind not logged" every single evening even when everything was logged hours earlier. It can never report a source complete during its window. Classic alarm-fatigue: trains the user to ignore it — the same failure the coherence program is trying to avoid.
**Recommendation:** Use the Pacific date for `today`. Add a test pinning the clock to 03:30 UTC asserting the PT date is queried. **Same root cause and same fix as BUG-01 — do them together.**

---

#### DEVOPS-01 — CI push-path filter excludes cdk/, ci/, config/ → infra/IAM/layer changes get no main-branch pipeline
**Severity:** P2 · **Lens:** DevOps / CI-CD · **Confidence:** High
**Location:** `.github/workflows/ci-cd.yml:30-36` (push paths), `:391-456` (Plan/diff/IAM gates), `:504-548` (layer-consistency gate); `remediation/automerge.py:16-18` (false comment), `:51-58` (ALLOWLIST).
**What & why:** `ci-cd.yml` triggers on push to main only for `lambdas/**`, `mcp/**`, `mcp_server.py`, `tests/**`. A commit touching *only* `cdk/` (role_policies.py, monitoring_stack.py, `SHARED_LAYER_VERSION`), `ci/lambda_map.json`, or `config/` runs **no CI at all** — so the cdk-diff destroy gate, the IAM/policy human-review gate, the stateful-resource assertions, and the layer-version-consistency gate are silently skipped for exactly the change classes they exist to police. The remediation auto-merge ALLOWLIST explicitly auto-merges `role_policies.py`, `lambda_map.json`, and `monitoring_stack.py`, and its own comment claims "CI re-runs them on main after merge" — which is **false** for those paths.
**Impact:** An auto-merged or hand-pushed IAM grant, alarm change, or layer bump lands on main with no lint/test/cdk-diff validation and no IAM-review gate. A black/ruff-dirty cdk file also reds the *next* unrelated `lambdas/` push (the masking class). The documented post-merge safety net does not exist for the most safety-critical files.
**Recommendation:** Add `cdk/**`, `ci/lambda_map.json`, and `config/**` to the push paths (at minimum the lint + cdk-diff Plan gates), or split a dedicated infra-validation workflow on those paths. Correct the `automerge.py` comment to stop asserting a non-existent re-run. **Interacts with DEVOPS-02 and SEC-01: an IAM-grant change is the highest-value thing to gate.**

---

#### FE-01 — Cockpit consistency "band" is a dead role=button (announced interactive, no handler)
**Severity:** P2 · **Lens:** Frontend / Accessibility · **Confidence:** High
**Location:** `site/now/index.html:142-147` (markup); `site/assets/js/cockpit.js:117-134` (pillarRow wires only `.row` buttons); no `.band` listener exists anywhere in cockpit.js.
**What & why:** The consistency band is `<div class="band" ... tabindex="0" role="button" aria-label="Consistency — open detail">`, exposing it to AT/keyboard users as an actionable button. No JS ever attaches a click or keydown handler to `.band`; `cockpit.js` references it only in show/hide arrays. The real pillar handler (`togglePillar`) binds to dynamically-created `<button class="row">` elements, not this static div.
**Impact:** Keyboard users tab onto a control announced "Consistency — open detail, button," press Enter/Space, and nothing happens (WCAG 4.1.2 Name/Role/Value, 2.1.1 Keyboard). Mouse clicks also no-op. This is the flagship, installable-PWA, primary-mobile page — the most-visited surface.
**Recommendation:** Decide intent. If display-only (the design comment calls it "a cross-cutting discipline band, not a sixth peer tile"), remove `role="button"`/`tabindex="0"` and reword the aria-label to drop "open detail." If it should drill in, wire a click + keydown(Enter/Space) handler to the same detail path the `.row` buttons use and toggle `aria-expanded`.

---

### 5. Full Findings Register

#### Security (SEC)
| ID | Sev | Title | Location | Recommendation |
|----|-----|-------|----------|----------------|
| SEC-01 | P3 | Public site_api role grants unconditioned PutItem/UpdateItem on the whole table | `cdk/stacks/role_policies.py:1721-1725` (cf. correct `:1792-1801`) | Add `dynamodb:LeadingKeys` StringLike enumerating legit write partitions, mirroring `site_api_ai`. |
| SEC-02 | P3 | `/api/challenge_checkin` + `/api/experiment_suggest` unauthenticated & unthrottled; overwrite Matthew's records | `lambdas/web/site_api_social.py:1187-1270`, `:1273-1294` | Apply the existing DDB rate limiter (1/IP/challenge/day; 3/IP/hr); reconsider anonymous writes into the authoritative ledger. |

#### Cost (COST)
| ID | Sev | Title | Location | Recommendation |
|----|-----|-------|----------|----------------|
| COST-01 | P3 | cost_governor docstring says "Runs hourly"; schedule is every 8h | `lambdas/operational/cost_governor_lambda.py:20,25`; `cdk/stacks/operational_stack.py:268` | Update docstring to "3x/day (every 8h)"; note 8h detection lag + actual-mtd backstop. |

#### Reliability (REL)
| ID | Sev | Title | Location | Recommendation |
|----|-----|-------|----------|----------------|
| REL-01 | P3 | Silent-failure alarms use `treat_missing_data=NB` — blind to producer/cron death (only freshness has a heartbeat) | `cdk/stacks/monitoring_stack.py:84,134-196`; `operational_stack.py:539` | Generalize the WR-48 heartbeat to liveness/interior-gap/reconciliation/coherence; consider BREACHING for always-emitting gauges. |
| REL-02 | P3 | DLQ consumer: async re-invoke + immediate delete + receive_count reset → permanent-failure escalation never triggers | `lambdas/operational/dlq_consumer_lambda.py:208-236,117-121,384-416` | Track retries by stable id (function+payload hash) in an S3 ledger; delete only after confirming outcome or a per-message cap. |
| REL-03 | P3 | DLQ consumer drains ≤10 msgs per 6h run (40/day max) — bursts clear slowly | `dlq_consumer_lambda.py:55,352-358`; `operational_stack.py:11` | Loop receive_message to drain within a time budget; raise frequency when depth>0. |

#### Correctness (BUG)
| ID | Sev | Title | Location | Recommendation |
|----|-----|-------|----------|----------------|
| BUG-01 | P2 | circadian-compliance scores the wrong (empty future-PT) day; garbage published to /now | `circadian_compliance_lambda.py:492,214,241,138`; `compute_stack.py:337` | Derive date in Pacific time; test at 02:30 UTC. (Shared helper w/ BUG-02/03.) |
| BUG-02 | P2 | evening-nudge reports every manual source missing (UTC date in 8 PM PT cron) | `evening_nudge_lambda.py:187,53,80,102`; `email_stack.py:268` | Use Pacific date; test at 03:30 UTC. |
| BUG-03 | P3 | Nutrition MCP "latest complete day" helper returns wrong day in the UTC-evening window | `mcp/tools_nutrition.py:63,653` | Compute latest-complete-day default in PT; share `pacific_today()`. |
| BUG-04 | P3 | `handle_vitals` no-op `sorted(key=lambda _:0)` + discarded comprehension; trend correctness depends on accidental ordering | `lambdas/web/site_api_vitals.py:82-84,170,172` | Remove no-op sorts + dead line 84; add tests pinning hrv/rhr trend ordering contract. |
| BUG-05 | P3 | Coherence Sentinel endpoint-shape check false-ALARMs on a legitimately-empty post-reset board (treats 0 as blank) | `lambdas/coherence_invariants.py:263,279`; `coherence_sentinel_lambda.py:221` | Gate non_degenerate on experiment-age, exclude count paths, or defer to check_prediction_health; add post-reset replay test. |

#### Code Quality (CQ)
| ID | Sev | Title | Location | Recommendation |
|----|-----|-------|----------|----------------|
| CQ-01 | P3 | Dev tooling pins diverge from enforced CI gates (black/ruff/playwright) | `requirements-dev.txt:18-29`; `ci-cd.yml:93,939` | Pin requirements-dev to CI's exact versions (black 25.9.0, ruff 0.14.0, playwright 1.58.0), or have CI install `-r requirements-dev.txt`. |
| CQ-02 | P3 | ARCHITECTURE.md body stale (layer v76 vs v92, ADR-078 vs ADR-086, 30 modules) behind a fresh auto-synced header | `docs/ARCHITECTURE.md:3,5,102`; `constants.py:37` | Extend sync_doc_metadata.py to rewrite body tokens, or reference constants.py/DECISIONS.md; add a test asserting body == SHARED_LAYER_VERSION. |
| CQ-03 | P3 | CLAUDE.md (first-read onboarding) carries stale counts (73/55 lambdas, 136 tools self-labeled "source of truth," v91) | `CLAUDE.md:16,64,90` | Update counts or point to the auto-maintained header; fix the "136" first since it invites trust. |
| CQ-04 | P3 | pyproject.toml/Makefile comments call the format/lint gate "advisory/staged/deferred"; CI enforces it | `pyproject.toml:7-9`; `Makefile:31`; `ci-cd.yml:95-99` | Update comments to state the gate is enforced and black/ruff are CI-pinned. |

#### Privacy (PRIV)
| ID | Sev | Title | Location | Recommendation |
|----|-----|-------|----------|----------------|
| PRIV-01 | P3 | Three diverged vice denylists; chronicle publish gate misses "edible/edibles" | `lambdas/privacy_guard.py:30-38`; `wednesday_chronicle_lambda.py:2574`; `seeds/content_filter.json:13`; `site_api_ai_lambda.py:264`; `site_api_common.py:275` | Make content_filter.json the single source; have privacy_guard load it; add a superset test; route generated/ artifacts (not just site/) through a vice scan. |
| PRIV-02 | P3 | HAE ingestion webhook accepts the auth token as a `?key=` query param (log-leak surface) | `lambdas/ingestion/health_auto_export_lambda.py:1374-1376` | Drop the `?key=` fallback if a header is possible; else confirm/strip query-string in CF/API-GW logs, shorten rotation, document in DATA_GOVERNANCE.md, treat as compromised-on-log. |
| PRIV-03 | P3 | DATA_GOVERNANCE.md stale: understates deployed delete/export tooling, omits the 9 public PhenoAge markers, mis-states P7.1/P7.3 | `docs/DATA_GOVERNANCE.md:34,123-128,136-166`; `operational_stack.py:382-410`; `site_api_data.py:2247-2360` | Refresh to reflect deployed data_export/delete_user_data lambdas + IAM; note /api/phenoage markers (cross-ref PHY-01); close P7.1/P7.3; add to post-deploy verification. |

#### DevOps / CI-CD (DEVOPS)
| ID | Sev | Title | Location | Recommendation |
|----|-----|-------|----------|----------------|
| DEVOPS-01 | P2 | Push-path filter excludes cdk/ci/config → infra/IAM/layer changes get no pipeline; auto-merge comment falsely claims a post-merge re-run | `ci-cd.yml:30-36,391-456,504-548`; `remediation/automerge.py:16-18,51-58` | Add cdk/**, ci/lambda_map.json, config/** to push paths (lint + cdk-diff), or a dedicated infra workflow; fix the automerge comment. |
| DEVOPS-02 | P3 | OIDC trust subject is `repo:org/repo:*` — privileged deploy role assumable from any git ref | `deploy/setup_github_oidc.sh:90-93,108-128,217-227` | Tighten StringLike to `ref:refs/heads/main` / `environment:production`; split read-only-diff (plan/QA) from write (deploy) into two roles. |

#### Product / Information Architecture (PROD)
| ID | Sev | Title | Location | Recommendation |
|----|-----|-------|----------|----------------|
| PROD-01 | P3 | Reading/Mind pillar is an orphan — a whole built door undiscoverable from nav/home/data/sitemap | `site/mind/index.html:2,43,46-51`; `site/now/index.html:171`; `site/sitemap.xml:12`; `site/data/index.html:46`; `site/index.html:99-108` | Decide IA: promote /mind/ to a 6th door (home loop + door bar + sitemap) OR fold into the Data door; record the home in SITE_MAP_AND_INTENT.md. |

#### Frontend / Accessibility (FE)
| ID | Sev | Title | Location | Recommendation |
|----|-----|-------|----------|----------------|
| FE-01 | P2 | Cockpit consistency band is a dead role=button (announced "open detail," no handler) | `site/now/index.html:142-147`; `cockpit.js:117-134` | Either strip role/tabindex/"open detail" (display-only) or wire click+keydown to the `.row` detail path with `aria-expanded`. |
| FE-02 | P3 | Interactive SVG charts are mouse-only (no touch/pointer) — tooltip unreachable on the mobile-first PWA | `site/assets/js/motion.js:32-40`; `charts.js:70` | Add Pointer Events (pointermove/down/leave) mirroring the mouse logic; reuse existing math. (Screen-reader aria-label summary mitigates the gist.) |

**Dedup / merge notes:**
- **BUG-01 / BUG-02 / BUG-03** are one root cause (UTC-vs-PT date selection) across three surfaces — fix as a single shared `pacific_today()` layer helper, but tracked separately because they're distinct lambdas/consumers with distinct blast radii.
- **CQ-01 + CQ-04** are the same "format gate truth lives in N places" issue (pins vs. comments); fix together.
- **CQ-02 + CQ-03 + PRIV-03** are the same documentation-drift class (auto-synced header masking a stale body).
- **DEVOPS-01** overlaps SEC-01/DEVOPS-02: the unguarded push path is *how* an unscoped IAM change reaches main without review — they compound.
- **No re-raise of accepted tradeoffs:** PHY-01 (public PhenoAge markers — only flagged as a doc-accuracy gap in PRIV-03, not as a leak), ADR-046 generated/ prefix, D-01 cache behavior, Garmin best-effort degradation, and the CE-self-cost 8h governor cadence are honored as deliberate.

---

### 6. Prioritized Remediation Roadmap

**Tier 0 — Quick wins (hours, high value, do first)**
1. **BUG-01 + BUG-02 (P2):** ship the `pacific_today()` helper and convert both crons. Highest user-visible correctness win — stops publishing a meaningless circadian score and silences a permanent false-alarm email. Fold BUG-03 (P3) into the same change.
2. **FE-01 (P2):** one-line decision — strip the misleading role/label, or wire the handler. Flagship-page accessibility, trivial fix.
3. **PRIV-01 (P3):** add `edible`/`edibles` to `privacy_guard.VICE_KEYWORDS` *today* (the urgent half), then follow with the single-source refactor + superset test. The chronicle's only deterministic gate must not miss an explicitly-moderated substance.
4. **COST-01, CQ-03, CQ-04, BUG-04:** doc/comment one-liners + dead-code removal with a pinning test.

**Tier 1 — Gate & guardrail integrity (days, prevents whole failure classes)**
5. **DEVOPS-01 (P2):** add `cdk/**`, `ci/lambda_map.json`, `config/**` to CI push paths and correct the auto-merge comment. Closes the masking class and restores the IAM-review gate for the changes that need it most. Pairs with **SEC-01** and **DEVOPS-02** (scope the site_api write with LeadingKeys; tighten the OIDC subject) — do the IAM hardening behind the now-enforced gate.
6. **REL-01 (P3):** generalize the WR-48 heartbeat to the other silent-failure producers. This is the meta-fix that makes the entire silent-failure layer trustworthy.
7. **CQ-01 (P3):** unify CI and dev tooling pins (single source). Removes a recurring red-main / wasted-cycle tax.

**Tier 2 — Hardening & hygiene (scheduled, lower urgency)**
8. **SEC-02 (P3):** rate-limit `challenge_checkin` / `experiment_suggest`; revisit anonymous writes into the authoritative ledger.
9. **REL-02 + REL-03 (P3):** DLQ escalation-by-stable-id + drain-loop. Restores the permanent-failure email/archive path and burst recovery.
10. **BUG-05 (P3):** post-reset false-alarm guard on the Sentinel endpoint-shape check (keeps coherence-overall honest).
11. **PRIV-02 (P3):** remove/secure the HAE `?key=` token path; rotate; document.
12. **CQ-02 + PRIV-03 (P3):** doc-truth refresh + (ideally) a post-deploy doc-drift check so headers stop masking stale bodies.
13. **PROD-01 + FE-02 (P3):** make the Reading/Mind IA decision (6th door vs. fold-in) so the build investment isn't stranded; add touch/pointer support to the charts.

**Why this order:** Tier 0 fixes the only issues producing *wrong public output and false alarms right now* at near-zero risk. Tier 1 closes the gate holes so future IAM/infra changes can't bypass review and the silent-failure detectors can't themselves go dark — the structural patterns. Tier 2 is genuine hardening with no live impairment. Nothing here is P0/P1: there is no fire to put out, only debt to retire before it compounds.