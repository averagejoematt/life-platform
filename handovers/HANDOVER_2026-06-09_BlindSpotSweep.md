# HANDOVER — 2026-06-09 (Local-folder hygiene + the "blind-spot" sweep: security · observability · testing · governance)

> A continuation of the 2026-06-08 A-grade work. Two arcs landed: a **local-folder
> best-practice sweep** (repo hygiene, ~6.5 GB reclaimed, documented layout) and a
> **"what are we missing" blind-spot sweep** across security, observability, testing,
> and governance. ~10 PRs merged; the new `life-platform-ops` dashboard + 3 alarms
> are deployed + verified live. `main` is clean.

> ✅ **State:** everything merged + deployed EXCEPT the final Tier-3 governance PR
> (this session's last — merge-only, no deploy). Secret-scanning was already on;
> the monitoring deploy is done.

**Previous handover:** `handovers/HANDOVER_2026-06-08_ResetAGradeAdoptionInbox.md` (the reset + A-grade gates + CDK orphan adoption → ∅ + inbox triage).

---

## 1. Local-folder best-practice sweep (PRs #71, #72)
- **`.gitignore` hardened** + untracked a stale committed QA report (`deploy/qa_report/`, ~6 MB). Closed every ignore gap (cdk.out, caches, node_modules, layer-build, show_and_tell, captures).
- **Removed dead top-level dirs** (`blog/`, `audit/`, `captures/`, root `layer-build/`) — evidence-verified unreferenced (the live `/blog/` is Lambda-generated to S3, not the repo dir).
- **`make clean`** target added (+ a follow-up fix: it must NOT delete `cdk/layer-build`, which `core_stack` needs as a CDK asset). Reclaims ~6.5 GB (`cdk/cdk.out`) — repo went 10 GB → 3.5 GB.
- **`docs/REPO_STRUCTURE.md`** — canonical top-level layout + "where does X go" rules, linked from README + docs index.

## 2. Blind-spot sweep — security (Tier 1, PR #73, ADR-082)
- **ruff `S` (flake8-bandit) = free SAST** — high-signal rules ON (exec/eval/pickle/shell-injection/…); convention-noise documented-out in `pyproject.toml`. Audit found **zero real findings** (no hardcoded secret *values* — Secrets-Manager discipline confirmed); value is forward-looking.
- **All GitHub Actions SHA-pinned** (was mutable `@vN` — injection vector) + **Dependabot** added (github-actions + dev/cdk pip).
- **pip-audit** broadened + loud-but-non-blocking.
- **Secret scanning + push protection** — verified **already enabled** (public repo). Owner toggle for **Dependabot alerts** (security advisories) is the one optional extra still off.

## 3. Blind-spot sweep — observability (Tier 2, PR #78) — DEPLOYED
- **CDK-managed `life-platform-ops` dashboard** (was a hand-built console dashboard living in no code — the gap that let the 2026 Garmin 44-day outage go alarm-less). 5 rows: ingestion freshness, **per-source ingestion Lambda health (SEARCH)**, compute pipeline, AI spend + budget tier, DLQ + consumer.
- **3 new alarms** on previously-unwatched signals: `remediation-dispatcher-errors`, `dlq-consumer-errors`, `budget-tier-escalation`. 13 → 16 alarms.
- **Deploy note:** the manual console `life-platform-ops` dashboard had to be deleted first (`aws cloudwatch delete-dashboards`) before `cdk deploy LifePlatformMonitoring` could create the CDK one. **Done + verified** (dashboard live, 3 alarms OK/INSUFFICIENT_DATA-as-expected).

## 4. Blind-spot sweep — testing (Tier 2, PR #79)
- **14 ingestion-`transform()` unit tests** (whoop/withings/strava/garmin) — pinning the raw-payload → DDB-schema contract. Schema regressions (renamed field, drifted unit conversion) now caught pre-deploy, not live at 4 AM. Offline suite 1598 → 1612; coverage 9% → ~10%.

## 5. Blind-spot sweep — governance (Tier 3 — THIS session's final PR, ADR-083/084)
- **ADR-083** — single-region (us-west-2) accepted as a documented decision (RPO≈0 within-region via PITR + versioning; region-loss RTO hours-to-days is fine for a solo daily-brief platform; revisit triggers logged).
- **ADR-084** — coverage *philosophy* + ratchet cadence: why ~10% offline is honest (glue is integration-tested live; 80% would mean mocking glue = false confidence), the layered safety net, and the **coverage floor raised 8 → 9%**. mypy-clean set grows by intent.
- **RUNBOOK** — saved Logs-Insights triage queries (ingestion / compute / AI failures).
- **pre-commit framework deliberately deferred** — conflicts with the bespoke `sync_doc_metadata` git hook; CI already gates ruff/black/mypy.

## 6. Dependabot cleanup (PR #81)
- Configured Dependabot to **skip ruff/black minor+major** bumps (a formatter bump reformats the repo + must move CI's inline pins in lockstep — a deliberate event, not an auto-merge). #77/#80 churn closed; the safe bumps (boto3/pytest/playwright/cdk) merged.

---

## Operator follow-ups
- **None blocking.** Merge the final Tier-3 governance PR (merge-only, no deploy).
- **Optional:** enable **Dependabot alerts** in repo Settings → Security (free; complements the update PRs).

## Known / deferred (documented, not gaps)
- **GuardDuty/Config** — deferred (ADR-079, compensating controls). **Cross-region DR** — accepted (ADR-083). **pre-commit** — deferred (ADR-084). **og-image-generator** adoption + the latent `web_stack` `life-platform-og-image` handler bug — tracked in ADR-081. **Recorded-response contract tests** for upstream APIs — the natural next testing step after #79.

## Verify quickly
- `python3 -m pytest tests/ -q --ignore=tests/test_integration_aws.py` (offline green; live `test_i13` freshness is reset-day-sparse + CI-excluded).
- `aws cloudwatch list-dashboards --region us-west-2` → `life-platform-ops` present (CDK-managed).
- `du -sh .` ≈ 3.5 GB after `make clean`; `git status` clean.
