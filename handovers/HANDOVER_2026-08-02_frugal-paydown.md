# HANDOVER — Frugal paydown: driver-only waves, 16 PRs — 2026-08-02 (late night)

> Instruction thread: execute the pre-prepared plan `~/.claude/plans/frugal-sweeping-lantern.md`
> — day 1/7 of the weekly window with Fable at ~50%, so **Fable drives only** (preflight, briefs,
> merge queue, reconciles, union checks, wrap); every implementer ran as a `worktree-implementer`
> with the issue's own `model:*` label (5 sonnet + backfills, then 5 opus), two waves, ≤5
> concurrent. Preflight confirmed the deploy queue NEVER flushed (Plan still red, R8-ST6) →
> merge-only session, post-flush verification pass skipped, numbered ask re-surfaced below.

## The headline: 16 PRs merged closing 14 backlog issues, on driver-only economics

The Next queue's actionable stories went from 19 to 5. Every implementer ran on its issue's
labeled model, so the Fable pool paid only for the merge queue and two driver fix-PRs.

| PR | issue | what |
|---|---|---|
| #2035 | #1963 | CQ-01 pin guard covers mypy/hypothesis/pytest/pytest-cov/boto3/botocore; real drift reconciled; derived-set test |
| #2036 | #1975 | outcome semaphore → §4 ember/ink grammar; all 5 hex-ok sanctions deleted (site-deploy ✅ → **live**) |
| #2037 | #1980 | sealed prereg linked from /method/calibration + /method/predictions (SHA-256 + verify cmd); site half **live**, API `prereg_seal` field dark until deploy |
| #2038 | #1987 | deterministic voice-register guard (first-person + markdown strip, registry-derived domains) at both write paths — dark until fleet deploy |
| #2039 | #1959 | wrap gate (e10): alarm red >72h must cite an issue — `check_alarm_citations.py` + curated registry |
| #2041 | #1991 | a11y audit gains light theme (week-parity); first sweep recorded 25 real light-only findings in `pages_light` |
| #2042 | #1937 | last 14 UTC anchors in site_api_vitals → PT (measured exactly); AST guard + 3 endpoints join reader-truth strict — dark until deploy |
| #2044 | #1990 | dark axe ledger re-armed: 44 pages cleared, 22 shrunk, 7 kept measured, 0 added; /method/game/ measured clean (issue's ~60 claim stale) |
| #2040 | #1972 | cron-derived next-installment line, chronicle + podcast; new `/api/content_cadence` — site **live**, route dark until deploy |
| #2045 | #1967 | grounding gates structural: real inventory 15 surfaces (not ~10); freshness 15/15, dates 11/15; bidirectional derived wiring test — dark until deploy |
| #2046 | #1960 | per-source OAuth alarms (registry-derived ×5) + dimensioned auth metric + ack-renewal ratchet (3 then needs-human) — needs cdk deploy |
| #2047 | #1978 | collision-proof prereg void ledger + reset invariant (fires on live state: 33 hyp + 1,402 pred orphans — the filed 39 double-counted 6 slug collisions); `reconcile_prereg_voids.py` dry-run-default |
| #2048 | #1957 | all 6 ARCHITECTURE claims measured false (secrets are 25, not 21/12) + 2 extra drifts; `doc_facts_ops.py` gate (4 derived rules) in Docs CI |
| #2049 | #2019 | config/-twin deploy path: 35 twins derived, 7 live-drifted found, drift workflow + site-deploy wiring, cache TTLs |
| #2050 | — | driver fix: defer `/api/content_cadence` smoke+visual expectations (dated re-arm) after the auto-rollback |
| #2054 | — | driver fix: boto3 install in both new workflows + config-twin step check-only until the owner's first reviewed sync |

**Verified:** serial squash-merges with per-merge reconcile verification (the bot pushed literal
regen after every test-adding merge; #2042/#2044/#2048 needed driver rebases — conflicts were
only the doc-sync literal files, resolved to main's side, and #2048's alarm-count union 81→86).
Union checks on final main: module-size guard 8/8, `sync_doc_metadata --check` ✅,
`check_doc_facts` ✅. Final site-deploy run (post-#2054, self-triggered): **deploy + smoke +
visual/AI QA all green** against the live site. Local HTTP smoke 232/232 during the incident
window. All 14 closed issues carry closure comments with complete/partial verdicts.

## Two incidents, both contained (rows in docs/INCIDENT_LOG.md)

1. **#2040's site-deploy auto-rollback (P4):** the PR registered its new route as a hard smoke
   `api_dep` while the route's Lambda sat behind the stranded fleet queue → smoke 404 →
   rollback fired correctly; every future site-deploy would have failed the same way. PR #2050
   deferred the expectations with dated re-arm markers (the #1404 landing-order precedent).
   Memory rule: `reference_gate_registration_before_deploy`.
2. **boto3 import crash mid-deploy (P4):** #2049's config-twin `--apply` step died on import
   AFTER the site synced — smoke/QA skipped, no rollback armed (site verified green by local
   smoke); the crash also pre-empted an un-reviewed first `--apply` over 7 live config objects.
   PR #2054 fixed both workflows and encoded the owner gate (check-only + dated re-arm).
   Memory rule: `reference_workflow_step_deps_and_first_apply`.

Also: the stalled-implementer pattern — two sonnet agents idled waiting on background children;
one delegation race produced a near-duplicate #1987 attempt that recovered its own commit from
the shared object store. Nudge-or-relaunch worked; nothing lost.

## NEXT — Matthew's numbered ask (ONE list; supersedes the previous handover's)

1. `bash deploy/cdk_deploy.sh LifePlatformOperational LifePlatformIngestion LifePlatformMonitoring` (Monitoring added: #2046's 5 per-source OAuth alarms don't exist until it runs)
2. `deploy_all=true` ci-cd dispatch + `bash deploy/deploy_site_api.sh` — activates the merged-but-dark halves: grounding gates (#1967), voice guard (#1987), PT anchors + strict reader-truth (#1937), `prereg_seal` field (#1980), `/api/content_cadence` (#1972), config cache TTLs (#2019), dimensioned auth metric (#1960)
3. DDB remediation pair (carried): countdown reconcile `--apply` + #1896 THREAD tombstone + coach regen/noscript rebake
4. Canary-row delete (carried)
5. PR #2012 revision purge (carried — GitHub UI)
6. #1934 Whoop interactive OAuth (`setup/setup_whoop_auth.py`) — **dark since 08-01 12:00Z, ~2.5d and counting**
7. NEW: prereg void reconcile — `python3 deploy/reconcile_prereg_voids.py --show-plan`, review, then `--apply` (~1,435 voids; **public voided count jumps 273 → ~1,708**, the #1893 correction — land it deliberately). The reset invariant BLOCKS the next `restart_pipeline.py --apply` until this runs (#1978)
8. NEW: config-twin first sync — `python3 deploy/config_twin_sync.py` (read-only), review the 7 drifted objects, `--apply`; then flip site-deploy's twin step back to `--apply` + `--strict` (dated marker in the workflow, #2019). The daily config-drift workflow reds until this runs — that's the alarm working
9. NEW: dismiss the 3 CodeQL alerts on PR #2046 — the documented #1902 false-positive class (pre-existing SDK-exception logs pulled into the diff window); dismissal was classifier-reserved for you
10. NEW post-deploy re-arm (after 2): `python3 deploy/capture_api_schemas.py` → commit the `/api/content_cadence` + `prereg_seal` baselines; restore both `api_deps` entries in `tests/qa_manifest.py`; empty `pending_deploy_apis` in `tests/visual_qa.py`; drop the dated `_exemptions.json` + SURFACE_DRIFT_EXEMPTIONS entries (#2050's checklist)

Then the post-flush verification pass (#2010) — after 1+2 it cheaply validates the ~12 merged-but-dark fixes from 08-02 plus tonight's lambda-side halves.

## Residual / next picks

- Post-flush verification pass — #2010 (unblocked by asks 1–2)
- #2023 gradability genesis-blind (Next, 1.50) and #1979 prereg-seal completion gate (Next, 2.70) — the top remaining actionable Next stories with #1974, #1986 (#1986 needs Matthew's editorial read on the byline)
- #2057 compute-written config mirrors (Next, 1.50 — filed tonight from #2049's residual)
- #2051 / #2052 (Now) — auto-filed deploy-reliability issues from the overnight window; triage next session
- #2056 grounding availability maps (Later) + #2058 advisory-workflow pins (Later) — filed tonight
- #2043 auto-filed visual-qa red — dispositioned as the #1526 mid-deploy hash race; auto-closes on today's ~20:07Z green run; if it refires on a NON-race cause that's a real finding
- Light-theme contrast burn-down (25 pages in `pages_light`) — not-work — tracked by the dated ledger itself (a recorded finding is the #1433 contract's backlog form); file a story when a slice is chosen

## Wrap-gate lines

**Build beat:** 2026-08-02-the-audit-learns-light-mode
**Docs:** in-PR by implementers (MONITORING, PHASE_TAXONOMY §13, CONVENTIONS, ARCHITECTURE/INFRASTRUCTURE/SECRETS_MAP/DEPENDENCY_GRAPH truth pass) + INCIDENT_LOG 2 rows at wrap; all doc checkers green
**Decisions:** none needed — tonight's choices (gate deferral pattern, check-only first-apply) are implementation postures under existing ADR-099/104/105; documented in-PR + memory
**Main:** stranded — R8-ST6 class: Plan red / Deploy skipped on every push run; recovery = ask 1 (CDK deploy) + ask 2 (`deploy_all=true` dispatch), #1901 decode
**Incidents:** 2 rows added — the #2040 auto-rollback (gate-registration-before-deploy) + the boto3 mid-deploy crash (QA-skipped window)
**Closures:** #1963 #1975 #1980 #1987 #1959 #1991 #1937 #1990 #1972 #1967 #1978 #1960 #1957 #2019 all commented (complete/partial verdicts, live evidence cited); #2043 dispositioned open per its auto-close policy
**Backlog:** Now live at 8 actionable (no promotions needed); Later sweep — hygiene rule prints no stale issues; 3 follow-ons filed (#2056 #2057 #2058)
**Alarms:** all >72h reds cited (`check_alarm_citations.py` ✅ — the #2039 gate's first live wrap run)
**Stash/hooks:** one stale stash from a prior session (settings.local pre-sync) inspected + dropped; hooks 🟢
