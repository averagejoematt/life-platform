# Testing Strategy

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-05-19

**Last updated:** 2026-05-19 (v8.0.0)

> What's tested, what isn't, and how to add tests without slowing yourself down.

---

## Test layers

| Layer | Location | Speed | Runs in CI? |
|---|---|---|---|
| Unit | `tests/test_*.py` (no integration mark) | ~3s for all | Yes, every push |
| Integration (AWS) | `tests/test_integration_aws.py` | ~24s | No — manual + nightly |
| Smoke (post-deploy) | `tests/smoke_test_site.sh` + `qa-smoke` Lambda | ~30s | Yes, after each deploy |
| Manual | Browser checks, MCP tool dispatch | Variable | No |

**Total tests:** 4991 `def test_` functions (auto-synced by `deploy/sync_doc_metadata.py`; do not hand-edit this number).

---

## Running tests

```bash
# All unit tests (fast — ~3 sec)
python3 -m pytest tests/ -m 'not integration' -q

# Specific file
python3 -m pytest tests/test_shared_modules.py -v

# Specific test
python3 -m pytest tests/test_shared_modules.py::test_retry_utils_backoff -v

# Show top-N slowest (find perf regressions)
python3 -m pytest tests/ --durations=20

# Coverage (requires pytest-cov)
python3 -m pytest tests/ -m 'not integration' \
    --cov=lambdas --cov=mcp --cov-report=term-missing --no-cov-on-fail
```

```bash
# Integration tests (requires AWS credentials)
python3 -m pytest tests/ -m integration -v
```

---

## Test categories

### 1. Shared module tests (`test_shared_modules.py`, `test_numeric.py`, etc.)
- Exercise `retry_utils`, `ai_calls`, `secret_cache`, `numeric`, `http_retry`, `rate_limiter`, `request_validator`, `compute_metadata`, `auth_breaker`
- Mock all AWS clients (boto3 with `moto` library)
- Run sub-millisecond per test

### 2. Lambda-handler tests
- For each new Lambda: smoke `lambda_handler(event, context)` with mocked AWS clients
- Validates event parsing + happy path + error paths
- Located in `tests/test_<lambda_name>.py`

### 3. Integration tests (`test_integration_aws.py`)
- Live AWS calls — read-only verification of deployed state
- Marked `@pytest.mark.integration` so they don't run in CI by default
- Key tests:
  - `test_i1_lambda_handlers_match_expected` — all `ci/lambda_map.json` Lambdas exist in AWS
  - `test_i2_lambda_layer_version_current` — all consumers on latest layer
  - `test_i3_spot_check_lambda_invocability` — random Lambdas don't error on healthcheck
  - `test_i9_dlq_no_deploy_caused_messages` — no deploy-caused DLQ messages (pre-existing transients warn, #1327)
  - `test_i10_mcp_lambda_responds` — MCP roundtrip
  - `test_i11_data_reconciliation_running` — weekly reconciliation alive
  - `test_i12_mcp_tool_shape` — tool dispatch returns expected shape
  - `test_i13_freshness_checker_returns_valid_data` — pipeline health

### 4. Shared-code distribution invariant (post-#781)
The layer-consistency suite (LV1–LV6) was retired with the shared layer (#781/ADR-131 —
there is no layer version to keep consistent). The surviving invariant:
- `test_i2_shared_layer_retired` (integration) — zero functions reference the retired
  layer `life-platform-shared-utils`; the CI plan job asserts the same.
- `tests/test_deploy_bundle_paths.py` — CDK and `deploy_site_api.sh` stay on the ONE
  bundle channel (`deploy/build_bundle.py`).

### 5. MCP orphan tool tests (`test_mcp_orphan_tools.py`)
- Catches `def tool_*` functions that aren't registered in `mcp/registry.py`
- Uses a ratchet: `AUDITED_AT = 64` — new orphans cause failures, existing accepted as legacy
- Plan: ratchet down toward 0 as MCP tool pruning happens

### 6. Wiring coverage tests (`test_wiring_coverage.py`)
- Every MCP tool in `mcp/tools_*.py` is callable + has a JSON schema
- Every AI Lambda goes through `ai_output_validator` (W3)
- No causal language in prompts (W4 — `"makes you", "causes"` banned phrases)

### 7. Schema/IAM/secrets consistency
- `test_ddb_patterns.py` — DDB writes use Decimal, not float
- `test_iam_secrets_consistency.py` — every secret referenced in `role_policies.py` exists; every grant has a known secret
- `test_role_policies.py` — IAM statements are well-formed
- `test_secret_references.py` — code's secret names match Secrets Manager actual names

### 8. CI/handler consistency
- `test_cdk_handler_consistency.py` — every CDK Lambda definition's `handler="..."` matches a real `def lambda_handler` in source

### 9. Type/style ratchets
- `test_handler_type_hints.py` — handlers have type hints (rolling allowlist of legacy handlers)
- `test_logger_discipline.py` — Lambdas use `platform_logger` (not bare `print`)

### 10. Site-API route tests (`test_site_api_routes.py`)
- Every route in `_SIMPLE_ROUTES` and `ROUTES` is dispatched
- No-growth rule on `site_api_lambda.py` LOC count (catches lazy adds without refactor)

### 11. AI-output faithfulness harness (`test_ai_output_faithfulness.py`) — ER-03 Layer 1
The **inverted-testing** fix: `visual_ai_qa.py` checks that pages *render*; this
checks that the coach/insight AI *content* obeys the honesty standard the platform
sells. Offline + **gating** in CI (no AWS, no inference). The deterministic engine
is `lambdas/er03_gate.py` (`er03_check`) — the same gate the coach daily-reflection
batch and The Panel enforce at publish time. Two parts:
- **Labelled corpus** (`tests/fixtures/ai_inputs/faithfulness_cases.json`) of
  `(input → output)` pairs — good outputs must PASS; planted-bad outputs must FAIL
  with the expected reason. Asserts the four failure classes: a **fabricated
  number** (any output number not in the input — also catches LLM arithmetic), a
  **causal connective** on a correlation, an **unhedged small-N** claim (`N<30`
  needs confidence framing), and a **"Matthew"-prefixed** opening.
- **Wiring-coverage guard** — the reader-facing paths that are supposed to be
  gated (`coach_daily_reflection_lambda`, `coach_panel_podcast_lambda`) must still
  route through `er03_gate`, so a refactor can't silently drop the truthfulness gate.

The rubric lives in the gate module + the corpus README, not in a buried prompt
string. **Layer 2** (a budget-gated Haiku judge vs an in-repo rubric, self-skipping
at budget tier ≥2) is intentionally deferred — see
`docs/specs/ER_EXTERNAL_REVIEW_RIGOR_2026-06-09.md`. Refresh good cases from real
outputs deliberately; never weaken a planted-bad case to make CI green.

### 12. Public-surface PII / guardrail guard (`test_public_surface_pii_guard.py`) — ER-06
Editorial guardrails + `docs/DATA_GOVERNANCE.md` are *policy*; this is the
**structural** test that the published static site can't leak them. Offline +
**gating**, it runs the same scanner the deploy uses (`deploy/pii_surface_guard.py`)
over the committed `site/` tree. Three arms:
- **Blocked-vice** (always-on) — no `blocked_vice_keywords` from
  `seeds/content_filter.json` (the policy-blocked categories) on the public surface.
- **Structural PII** (always-on) — US SSN, 16-digit card-like numbers, and
  non-allowlisted email addresses (the PII classes in `DATA_GOVERNANCE.md`).
- **Literal denylist** (best-effort) — partner name / employer / role / industry
  from a **non-committed** source (`config/pii_denylist.local.json`, gitignored, or
  env `PII_DENYLIST_JSON` as a CI secret). These literals never live in git (repo went
  private 2026-07-13, but the site is public and the discipline holds regardless); absent
  → that arm self-skips, the always-on arms still gate.

The **same scanner runs fail-closed inside `sync_site_to_s3.sh` before the S3 sync**
— this test is the CI half of the same gate. (Its first run caught a real leak: the
published `challenges_catalog.json` shipped two `public:false` blocked-category
templates; those were stripped and the read-path `_is_blocked_vice(name **or** id)`
bug fixed.)

### 13. AI-content QA — the four planes (QA strategy D-lane, epic #1425)
AI output is defended in four complementary planes; nothing else is a substitute
for the plane below it:
1. **Generation-time honesty gate** (plane 1) — the deterministic ADR-104 grounding
   gate / `er03_check` fires at publish time on every AI narrative surface; a
   fabricated number or unhedged small-N claim is blocked or regenerated before a
   reader ever sees it.
2. **Faithfulness harness** (plane 2) — section 11 above: an offline labelled corpus
   proves the gate still catches the four failure classes, wiring-guarded so a
   refactor can't drop it.
3. **Generation-time archive** (plane 3, D2 / #1441) — `lambdas/qa_archive.py` copies
   every gate-passed generation to `generated/qa_archive/` (text + daily screenshots,
   90-day retention) so any past generation is reconstructable, not screenshot
   archaeology.
4. **Human editorial plane** (plane 4, D3 / #1442) — the **weekly AI review-pack email**
   (`lambdas/emails/ai_review_pack_lambda.py`, Sunday 18:00 UTC). It curates plane-3's
   archive for the trailing week into one scannable email — Chronicle, Board answers,
   Coach commentary, State of Matthew, Field notes, Coach memoirs, each with an inline
   snippet and an S3 link — guaranteeing a human eyeball over every AI surface at the
   cost of scanning one email. It reads the archive only (no Bedrock calls, no budget
   gate) and degrades gracefully: a surface that produced nothing shows an explicit
   note; a quiet week still sends. Tests: `tests/test_ai_review_pack.py`.

---

## What's NOT tested

| What | Why not | Risk |
|---|---|---|
| Actual Anthropic API responses | Cost + flakiness | Low (mocked) |
| Email rendering in real mail clients | Manual visual check | Medium (rendering quirks) |
| Static site visual regression | No screenshot diffing | Medium (cosmetic only) |
| Whoop/Garmin/etc. live OAuth flows | Requires real creds | High — but covered by smoke + post-deploy alarms |
| CloudFront cache behavior | Hard to test deterministically | Low (CF is reliable) |
| In-Lambda rate-limit accuracy under burst | Would require live burst-testing | Low (DDB counters + the 429 path are unit-tested) |
| Subscriber email deliverability | SES auto-handles bounces/complaints | Low |

---

## Writing new tests

### Pattern for a new Lambda test

```python
# tests/test_<lambda_name>.py
import json
from unittest.mock import patch, MagicMock

def test_lambda_handler_happy_path():
    # Arrange
    event = {"date": "2026-05-19"}
    mock_table = MagicMock()
    mock_table.query.return_value = {"Items": [{"sk": "DATE#2026-05-19"}]}

    with patch("lambdas.my_lambda.table", mock_table):
        from lambdas.my_lambda import lambda_handler
        result = lambda_handler(event, None)

    # Assert
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["status"] == "ok"


def test_lambda_handler_error():
    event = {}  # malformed
    from lambdas.my_lambda import lambda_handler
    result = lambda_handler(event, None)
    assert result["statusCode"] == 400
```

### Pattern for an integration test

```python
import pytest
pytestmark = pytest.mark.integration

def test_my_lambda_is_alive():
    boto3 = _get_boto3()  # helper in test_integration_aws.py
    lc = boto3.client("lambda", region_name="us-west-2")
    cfg = lc.get_function_configuration(FunctionName="my-lambda")
    assert cfg["State"] == "Active"
```

### Pattern for an MCP tool test

```python
# tests/test_my_mcp_tool.py
def test_my_tool_returns_correct_shape():
    from mcp.tools_<module> import tool_my_tool
    result = tool_my_tool(some_arg="value")
    assert "status" in result  # standardized envelope
    assert result["status"] in ("ok", "partial", "error")
```

---

## CI/CD test invocation

In `.github/workflows/ci-cd.yml`:

```yaml
- name: Run unit tests
  run: python3 -m pytest tests/ -m 'not integration' -v --tb=short

- name: Run linters
  run: |
    flake8 lambdas/ mcp/ --select=E9,F63,F7,F82 --count --show-source --statistics
    find lambdas/ mcp/ -name '*.py' -exec python3 -m py_compile {} \;
```

CI fails on:
- Any unit test failure
- `E9` (syntax) / `F63` (assertion always-true) / `F7` (forward reference) / `F82` (undefined name)
- `py_compile` errors

CI does NOT fail on style-only flake8 issues (E2xx etc.) — those are warnings.

---

## Pre-commit hooks (not configured)

Considered, deferred per ADR-057 W-08 (similar cost/benefit). If you want:
```bash
# In .pre-commit-config.yaml
- repo: https://github.com/pre-commit/pre-commit-hooks
  hooks: [trailing-whitespace, end-of-file-fixer]
- repo: local
  hooks:
    - id: pytest-fast
      name: pytest (unit only)
      entry: python3 -m pytest tests/ -m 'not integration' -q
      language: system
      pass_filenames: false
```

Then `pre-commit install`.

---

## QA Strategy Scorecard (quarterly re-grade, #1451)

**Baseline set:** 2026-07-18, by the QA & Testing Strategy review (`review:qa-strategy-2026-07-18`
label; epic [#1425](https://github.com/averagejoematt/life-platform/issues/1425), a three-agent
survey with every finding verified against the repo). This is the **durable record** — the
`/sdlc-review` quarterly checklist step (below, and in `.claude/commands/sdlc-review.md`)
re-grades against it and overwrites the "Current" column each run so the next re-grade always
diffs against the *previous* run, not perpetually against 2026-07-18.

### The 8 axes

| Axis | Baseline (2026-07-18) | Target | Current | Evidence for baseline grade |
|---|---|---|---|---|
| Deploy gating | A− | A | A− | Production-approval gate + post-deploy smoke + auto-rollback exist and are exercised on every deploy, but `visual-qa` is not yet the only gate with edge cases (see ADR-076 history) and the approval-gate itself has had live drift incidents (#1319 — GitHub env protection dropping on a repo-visibility flip). |
| Render breadth | C | A− | C | `tests/visual_qa.py` `PAGES` covered ~35 of ~80 live pages at baseline — 44 live pages (including live-data/AI/write pages) had zero render coverage. |
| FE unit tests | F | B | F | Zero JavaScript unit-test harness existed; no front-end code has ever run under a unit test. |
| API contracts | B− | A− | B− | ~118 `/api` endpoints (101 `ROUTES` + 13 `_SIMPLE_ROUTES` + ~23 inline) with no per-endpoint schema baselines and no E2E coverage of the 8 write paths. |
| AI-content QA | B | A− | B | `visual_ai_qa.py` (Haiku vision) and the ER-03 faithfulness harness exist and gate, but AI QA is not yet tiered/budget-visible — a budget-tier pause degrades silently rather than reporting. |
| Monitoring | B | A | B | Alarms + qa-smoke exist, but notification hygiene gaps: no codified urgent-SNS email path, no qa-smoke heartbeat alarm, advisory scheduled-workflow failures don't self-file issues. |
| Mobile / cross-browser | C+ | B+ | C+ | No scheduled WebKit/mobile run; desktop Chromium is the only browser under test. |
| Accessibility (a11y) | C | B+ | C | No `axe-core` audit or baseline gate anywhere in the harness. |

### Grading rubric — what justifies moving a letter grade

Keep this concrete and checkable per axis; a re-grade must cite the specific evidence, not a
vibe. General ladder (apply per-axis with the axis's own coverage denominator):

- **F → D/C** — the practice exists only as a manual step or a doc, with zero automated/CI
  enforcement. Bump to C requires: at least one automated check exists and runs in CI (even if
  advisory), covering a *non-trivial* fraction of the surface (state the fraction).
- **C → B / B+** — automated coverage crosses a real majority of the relevant surface (state
  the numerator/denominator, e.g. "62/80 pages", "1 of 3 browser engines"), OR a structural
  registry drives the coverage so new surface is added automatically rather than by memory.
  Cite the PR/commit that shipped it.
- **B / B− → A− / A** — coverage is at or near completeness for the axis's denominator AND the
  check **gates** (blocks merge/deploy on failure) rather than running advisory-only. Cite the
  gating config (CI job `needs`/`continue-on-error` state) and, if available, one real incident
  the gate caught (a regression that would otherwise have shipped).
- **A− → A** — the above holds, the gate has run clean (no manual overrides, no silent skips)
  across the trailing quarter, and any known failure mode of the gate itself (e.g. AI-judge
  false positives, budget-tier pauses) has a documented, non-silent fallback.

A re-grade that can't produce this evidence for a proposed bump leaves the grade where it was —
"we shipped some of the stories" is not itself a grade change; the coverage/gating facts are.

### Quarterly re-grade checklist (run from `/sdlc-review`)

1. Re-read this table (baseline + target + current) before grading — it is the anchor; do not
   re-derive targets from memory.
2. For each of the 8 axes, re-grade against **current reality** using the rubric above: state
   the fraction/denominator, whether the check gates or is advisory, and cite the file/command/
   `gh run` evidence (same evidence rule as the rest of `/sdlc-review`).
3. Diff each axis's new grade against the **Current** column here (not always the 2026-07-18
   baseline) and record the delta: improved / flat / regressed.
4. Fold the re-graded table + deltas into this run's `docs/reviews/SDLC_REVIEW_<date>.md` as a
   labeled subsection (Phase 3) — it is part of that review's artifact, not a separate doc.
5. Any axis that **regressed** vs its prior Current grade, or remains **two or more quarters
   short of target with no evidence of movement**, gets a story filed via the `issue-filer`
   agent per ADR-099 (`type:story`, `area:claude-workflow`, `review:qa-strategy-<date>` label,
   linked to epic #1425), same as any other `/sdlc-review` finding.
6. After the review lands, update the **Current** column in this table (in the same PR as the
   review artifact) so the next quarterly re-grade diffs against this run.

**First scheduled re-grade:** ~2026-10 (next `/sdlc-review` quarterly cadence after this table
was created), tracked via a comment on epic #1425.

---

## Adding tests for V2 cleanup work

When you remove a Lambda or rename a file, also remove its tests:
```bash
git rm tests/test_<removed_lambda>.py
# Update test_logger_discipline allowlist if needed
# Update test_mcp_orphan_tools KNOWN_ORPHANS if MCP tools removed
```

When you add new shared module:
```bash
# 1. Write the module in lambdas/
# 2. No packaging step — deploy/build_bundle.py ships the whole lambdas/ tree (#781)
# 3. Add to ci/lambda_map.json skip_deploy
# 4. Add to cdk/stacks/constants.py if needed
# 5. Write tests/test_<new_module>.py
```

---

**Verified:** 2026-05-19
