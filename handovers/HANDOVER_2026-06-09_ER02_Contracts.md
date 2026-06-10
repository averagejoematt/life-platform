# HANDOVER — 2026-06-09 (ER-02: upstream-API contract tests)

> First item of the **ER-series** (external-review rigor, `docs/specs/ER_EXTERNAL_REVIEW_RIGOR_2026-06-09.md`).
> ER-02 closes the Tier-1 "thin coverage at the upstream-API seam" finding: contract
> tests that fail when a *vendor* drifts a payload, not just when *our* logic regresses.
> **Tests only — no deploy, no layer change.** `main` is clean; commit/push left to Matthew.

**Previous handover:** `handovers/HANDOVER_2026-06-09_BlindSpotSweep.md` (local-folder hygiene + the security/observability/testing/governance blind-spot sweep).

---

## What shipped (ER-02)

The `transform()` unit tests (the ~14 from the blind-spot sweep) pin **our** logic
against a fixed input. They do **not** notice when a vendor changes the payload out
from under the transform — a field rename / renest / retype. That drift corrupts data
silently and is the literal mechanism of the next 44-day-class incident. ER-02 adds the
missing seam coverage:

- **`tests/test_upstream_contracts.py`** — fully **offline**, gating. Three tests, parametrized over a contract registry:
  1. `test_fixture_shape_contract` — asserts every key-path + type the transform reads (catches rename/renest/retype, pinpoints the drifted path).
  2. `test_fixture_roundtrips_transform` — runs the **real** extractor (`_extract_recovery/_extract_sleep/_extract_cycle/_extract_workout`, `_parse_measurements`, `process_blood_glucose`, `strava._normalize`, `garmin.transform`) on the fixture and asserts the expected output fields. Ties the fixture to live code, so drift on *either* side fails.
  3. `test_fixtures_have_no_secrets` — no committed fixture may carry a token/bearer/JWT/email.
- **`tests/fixtures/upstream/{source}/{endpoint}.json`** — 9 scrubbed, committed fixtures: **whoop** recovery/sleep/cycle/workout · **withings** measures · **hae/Apple Health** blood_glucose/blood_pressure · strava activity · garmin daily. Bootstrapped **offline** from the blind-spot-sweep sample payloads + the documented HAE webhook shape — no creds needed for a first green suite.
- **`deploy/refresh_upstream_fixtures.py`** — the LIVE-refresh path (Matthew runs it, with creds). Re-pulls one day per source, **scrubs** tokens/PII (drops credential keys, redacts inline JWT/bearer/email), asserts the scrub is clean before writing, and prints a unified diff vs. the committed fixture. **The diff is the drift report.** Live-refreshable: whoop/withings/garmin (their `fetch_day` returns raw vendor JSON); `--from-file` (scrub a captured payload) for strava (its `fetch_day` returns normalized output) + hae (webhook-push). The scrub/secret-scanner here is the single source of truth shared with test #3.
- **CI:** explicit **"Upstream-API contract tests (ER-02)"** gating step added to the `test` job in `.github/workflows/ci-cd.yml` (the full-suite step also covers it).
- **`tests/fixtures/upstream/README.md`** — provenance table + refresh workflow.

## Verification (done this session)
- Offline suite green: **1630 passed**, 43 skipped, 10 xfailed (`pytest tests/ -q --ignore=tests/test_integration_aws.py`).
- Acceptance proven by injection: renaming `recovery_score` in a fixture → 2 failures (shape + round-trip); planting `access_token` in a fixture → 1 failure (no-secrets guard); restored → 19/19 green.
- Refresh tool offline smoke: `--from-file` with a planted token → token dropped, scrub-clean assertion holds, drift diff printed. `flake8` clean on both new files. (black/ruff not installed locally — CI enforces; new code is black-formatted, all code lines ≤140.)

## Operator follow-ups
- **Commit + push** (left to you). Suggested branch/PR; CI's new gating step + full suite should pass offline.
- **Optional, later (your terminal, with creds):** run `python3 deploy/refresh_upstream_fixtures.py --date <a-recent-day>` to replace the bootstrapped fixtures with real scrubbed captures and surface any *current* drift. `hae/*` + `strava/*` are synthetic-but-shape-accurate until you do (`--from-file` for those two).

## Next ER items (sequencing per the spec)
- **ER-01** — infra-liveness heartbeat (closes the headline 44-day-outage finding). Tier 1.
- **ER-03 Layer 1** — deterministic AI-output faithfulness guards (offline, gating). Tier 1.
- Then ER-05/06 (cheap honesty), ER-04/07 (recorded decisions), ER-03 Layer 2 / ER-08.

## Note
- There is **no `PROJECT_PLAN.md`** in the repo; `docs/BACKLOG.md` is the active roadmap/plan tracker and was updated (ER count 8→7, ER-02 marked ✅ → CHANGELOG, totals adjusted).

## Verify quickly
- `python3 -m pytest tests/test_upstream_contracts.py -v` → 19 passed.
- `python3 -m pytest tests/ -q --ignore=tests/test_integration_aws.py` → offline green.
- `git status` clean before you start; this session leaves new/modified files staged for your commit.
