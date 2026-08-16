# /fullreview — 2026-08-16 delta (Fable)

**Run:** `wf_8ccd5caf-049` · 7 lenses, one grader + one lean-REFUTED verifier each, all Fable.
**Scope:** `08c7af26..d7df1148e` (~60 PRs, the 08-09→08-15 week: gate audit, bug bash + queue, silent-failure drain, instruments, alarm board, MCP sweep, coaching team v2).
**Anchors:** applied verbatim from the 08-09 delta + 07-28 partial. Machine artifact: `fullreview_grades_2026-08-16_delta.json`.

| lens | prior | now | verifier | findings |
|---|---|---|---|---|
| security | B+ | **B+** | B (agrees) | 3 |
| principal | A- | **A-** | A- (agrees) | 4 |
| cto | A- | **A-** | A- (agrees) | 5 |
| narrative | B | **B+** | B+ (agrees) | 4 |
| aiq | B | **B+** | B+ (agrees) | 5 |
| observability | B+ | **A-** | A- (agrees) | 4 |
| integrations | B+ | **A-** | A- (agrees) | 2 |

**Headline:** Four lenses up (narrative B->B+, aiq B->B+, observability B+->A-, integrations B+->A-), three held (security B+, principal A-, cto A-). All 7 verifier letters agree with their graders; 27 findings -> 26 CONFIRMED + 1 ADJUSTED, 0 refuted — an unusually clean first pass against the historic ~50% FP rate.

## Filed from this review (label `review:2026-08-16`)

P2/P3 confirmed findings filed as issues by the issue-filer pass; `note`-severity findings live only in the JSON artifact (each carries its evidence + repro):

- **SEC-3** (note, security) — Five send paths log the first 6 characters of subscriber email addresses to CloudWatch · note (artifact only)
- **F1** (P2, principal) — Minimal-lane collection-import class fixed per-instance twice in 48h; no set guard exists for the third recurrence · FILED
- **F4** (note, principal) — Verified fixed (positive verification, not a defect): the three headline instrument defects all carry real regression coverage at HEAD · note (artifact only)
- **CTO-1** (P3, cto) — Remediation-agent workflow installs its entire toolchain unpinned — npm claude-code + four pip packages float to latest in a job holding AWS OIDC creds and a PR-writing token · FILED
- **CTO-2** (P3, cto) — The one-legged-pin class extends beyond the CDK CLI: pip-audit (ENFORCED CVE gate) and pip-licenses are pinned inline-only with no Dependabot leg, and the smoke-test + golden-brief gates install boto3/pytest unpinned, evading the CQ-01 guard · FILED
- **CTO-3** (P3, cto) — The #2380 proportionality wrap gate silently failed for every session since it landed: zero ledger commits since 08-10 while the week shipped standing machinery with $, surface, and attention rent · FILED
- **CTO-4** (P3, cto) — check_main_green's completed-run verdict never compares head_sha to main HEAD, so the documented swallowed-push shape (a push that mints ZERO runs) reads as green · FILED
- **NARR-1** (P2, narrative) — Live coach cards state the food-log absence as 'four days' when the true gap is 52 days — contradicting /api/character's own absence facts one page hop away, and misattributing the cause to cycle start · FILED
- **NARR-2** (P3, narrative) — Persona display identity is hardcoded in three lambda files and has drifted from the registry — the same coach renders different colors/titles on different live pages · FILED
- **NARR-3** (note, narrative) — Two identity-glyph collisions inside the operational cast render on the same page: eli_marsh and glucose_coach share the microscope emoji; physical_coach and labs_coach share color #f59e0b · note (artifact only)
- **NARR-4** (note, narrative) — The public voice-fidelity scoreboard lists the retired training_coach seat (and omits eli_marsh) with nothing explaining the ghost persona · note (artifact only)
- **AIQ-1** (P3, aiq) — Gate-infra exception at the analyzer's main publish site ships UNGATED narrative to a public surface (fail-open residue of the #2391 hold) · FILED
- **AIQ-4** (note, aiq) — Confirm-before-FAIL counts only second-pass HIGHs as confirmation — a real finding flapping high↔medium can never FAIL the gate · note (artifact only)
- **AIQ-5** (note, aiq) — Spot-check inconclusive: the coach_team tensions prose cites '1,500 calorie protocol' and 'Three weeks without glucose data' — dated, but neither number traced to a stored fact in this session · note (artifact only)
- **OBS-1** (P2, observability) — daily-brief-no-invocations-24h and daily-debrief-no-invocations-24h structurally cannot fire — notBreaching over a metric that goes missing, not zero, in the failure mode · FILED
- **OBS-2** (note, observability) — 8 of 12 alarm_citations.json entries describe alarms that are now OK — the registry drifts green-side and the checker only enforces the missing direction · note (artifact only)
- **OBS-3** (note, observability) — slo-warmer-completeness is a byte-identical duplicate of mcp-warmer-error and measures errors, not completeness · note (artifact only)
- **INT-1** (P2, integrations) — resolve_source_state ignores per-source registry thresholds — get_sources misstates slow-cadence sources as 'stale' and get_freshness_status contradicts itself in one row · FILED
- **INT-2** (note, integrations) — mcp/registry.py schema hint hand-types 12 source names while the tool's derived valid set is 14 — hevy and weather missing · note (artifact only)

**Dupes correctly suppressed:** SEC-1→#1221, SEC-2→#2654, plus per-lens dupe_of entries in the JSON.

**Unchanged lenses:** reader, data-architect (2026-08-09 delta); cpo, designer, dataviz, qs, a11y, cost, devex, growth (2026-08-02 delta / 2026-07-28 partial) — grades stand.
