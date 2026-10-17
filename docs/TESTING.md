# Testing Strategy

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-10-17

**Last updated:** 2026-10-17 (re-verified against `.github/workflows/`, `pytest.ini`, `pyproject.toml` and `tests/`; the QA Strategy Scorecard section was not re-graded)

> What's tested, what isn't, and how to add tests without slowing yourself down.

---

## Test layers

| Layer | Location | Speed | Runs in CI? |
|---|---|---|---|
| Unit | `tests/test_*.py` (no integration mark) | Minutes — sharded across three runner legs in CI (`ci-test.yml`) | Yes — PRs (`pr-checks.yml`) and every push to main |
| Integration (AWS) | `tests/test_integration_aws.py` (`@pytest.mark.integration`) | ~24s when run alone | Excluded from the unit lanes; a named subset (I1, I2, I4–I9, I22–I24) runs post-deploy in `ci-cd.yml`; the rest manual |
| Smoke (post-deploy) | `deploy/smoke_test_site.sh` + the `life-platform-qa-smoke` Lambda | ~30s | Yes, after each deploy |
| Manual | Browser checks, MCP tool dispatch | Variable | No |

**Total tests:** derived, never committed — `test_count` is stamped into every Lambda bundle by `deploy/build_bundle.py`, served at `/api/platform_stats` (#4250).

---

## Running tests

```bash
# All offline tests (what the suite runs; the integration marker needs live AWS)
python3 -m pytest tests/ -m 'not integration' -q

# Specific file
python3 -m pytest tests/test_shared_modules.py -v

# Specific test
python3 -m pytest tests/test_shared_modules.py::test_retry_utils_backoff -v

# The PR fast lane's selection (what the required check runs)
python3 -m pytest tests/ -m "deploy_critical and not integration and not serial" -q -n auto --dist loadfile

# Show top-N slowest (find perf regressions)
python3 -m pytest tests/ --durations=20
# Duration budget (#1847/#4252): the full suite is too big for one runner, so CI/CD
# splits it into three legs (two parallel shards + the serial pass) and grades coverage
# once over the union. Do not restate a test count or a minutes figure here — they rot
# within weeks; read the last green run. The Unit-Tests job warns when it nears its
# duration budget via scripts/coverage_gap_warn.py (#1349).
# Known failure shape: a test that hangs SILENTLY while memory climbs is a
# mock-fed infinite loop (e.g. DDB pagination on a truthy MagicMock
# LastEvaluatedKey, #1847/#1849) — it OOM-kills CI runners with
# "runner has received a shutdown signal", which reads as a mystery
# cancellation, not as the test's fault.

# Coverage (requires pytest-cov)
python3 -m pytest tests/ -m 'not integration' \
    --cov=lambdas --cov=mcp --cov-report=term-missing --no-cov-on-fail
# The coverage floor is `fail_under` in pyproject.toml (an up-only ratchet,
# tests/test_coverage_floor_ratchet.py) — read it there, never restate it.
```

```bash
# Integration tests (requires AWS credentials)
python3 -m pytest tests/ -m integration -v
```

---

## Test categories

### 1. Shared module tests (`test_shared_modules.py`, `test_numeric.py`, etc.)
- Exercise `retry_utils`, `ai_calls`, `secret_cache`, `numeric`, `http_retry`, `rate_limiter`, `request_validator`, `compute_metadata`, `auth_breaker`
- Mock AWS clients (`unittest.mock` and hand-built stubs; `moto` is not a dependency)
- No live AWS: CI asserts no real credentials resolve (ci-cd.yml, "AWS creds parity")

### 2. Lambda-handler tests
- For each new Lambda: smoke `lambda_handler(event, context)` with mocked AWS clients
- Validates event parsing + happy path + error paths
- Located in `tests/test_<lambda_name>.py`

### 3. Integration tests (`test_integration_aws.py`)
- Live AWS calls — read-only verification of deployed state
- Marked `@pytest.mark.integration` so they don't run in CI by default
- Key tests:
  - `test_i1_lambda_handlers_match_expected` — all `ci/lambda_map.json` Lambdas exist in AWS
  - `test_i2_shared_layer_retired` — no function references the retired shared layer
  - `test_i3_spot_check_lambda_invocability` — random Lambdas don't error on healthcheck
  - `test_i9_dlq_no_deploy_caused_messages` — no deploy-caused DLQ messages (pre-existing transients warn, #1327)
  - `test_i10_mcp_lambda_responds` — MCP roundtrip
  - `test_i11_data_reconciliation_running` — weekly reconciliation alive
  - `test_i12_mcp_tool_call_response_shape` — tool dispatch returns expected shape
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
- Uses a ratchet: `AUDITED_AT` in the test file (now 0 — any orphan fails); the dated history and the removal procedure are `docs/MCP_TOOL_AUDIT.md`

### 6. Wiring coverage tests (`test_wiring_coverage.py`)
- Every MCP tool in `mcp/tools_*.py` is callable + has a JSON schema
- Every AI Lambda goes through `ai_output_validator` (W3)
- No causal language in prompts (W4 — `"makes you", "causes"` banned phrases)

### 7. Schema/IAM/secrets consistency
- `test_ddb_patterns.py` — DDB key construction, reserved-word handling, `schema_version` and validate-before-write on ingestion puts (D1–D4); Decimal-not-float is a convention (CLAUDE.md) enforced by the write paths' own tests
- `test_iam_secrets_consistency.py` — every secret referenced in `role_policies.py` is a known secret; every grant has a known secret
- `test_role_policies.py` — IAM statements are well-formed
- `test_secret_references.py` — OFFLINE: every secret-name literal in Lambda source is in `KNOWN_SECRETS` and none is in `DELETED_SECRETS` (SR1–SR5); it does not call Secrets Manager

### 8. CI/handler consistency
- `test_cdk_handler_consistency.py` — every CDK Lambda definition's `handler="..."` matches a real `def lambda_handler` in source

### 9. Type/style ratchets
- `test_handler_type_hints.py` — handlers have type hints (a baseline that can only decrease)
- `test_logger_discipline.py` — no new bare `print` in Lambdas (baseline count; use `platform_logger`)
- `mypy` on the clean-module set (`scripts/mypy_clean_set.py`, ADR-080) is a CI gate, not a pytest file

### 10. Site-API route tests (`test_site_api_routes.py`)
- The `_SIMPLE_ROUTES` / `ROUTES` tables parse, have no duplicate paths or handlers, every handler is defined, paths are well-formed and methods are valid verbs
- Also holds the wire-contract replay (frozen to the capture clock in `_capture.json`, #4864); API response shapes are baselined in `tests/api_schemas/`

### 11. AI-output faithfulness harness (`test_ai_output_faithfulness.py`) — ER-03 Layer 1
The **inverted-testing** fix: `visual_ai_qa.py` checks that pages *render*; this
checks that the coach/insight AI *content* obeys the honesty standard the platform
sells. Offline + **gating** in CI (no AWS, no inference). The deterministic engine
is `lambdas/experiment/er03_gate.py` (`er03_check`) — the same gate the coach daily-reflection
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
- **Blocked-vice** — no channel-configured `blocked_vice_keywords` (the
  policy-blocked categories) on the public surface. The vocabulary comes from the
  ER-06 non-committed channel (#2370: env `CONTENT_FILTER_JSON` / gitignored
  `config/content_filter.local.json` / the private S3 copy) — armed in CI via the
  repo secret, REQUIRED fail-closed on the deploy path (`--require-vice`), and a
  `--tracked` repo-hygiene arm scans every git-tracked JSON for the same terms.
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
3. **Generation-time archive** (plane 3, D2 / #1441) — `lambdas/common/qa_archive.py` copies
   every gate-passed generation to `generated/qa_archive/` (text + daily screenshots,
   90-day retention) so any past generation is reconstructable, not screenshot
   archaeology.
4. **Human editorial plane** (plane 4, D3 / #1442) — the **weekly AI review-pack email**
   (`lambdas/emails/ai_review_pack_lambda.py`; its cron is the `ai-review-pack` row of `model/platform_model.json`). It curates plane-3's
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

### Traps that have redded main — read before adding a test

Each of these was green alone and red in CI, or green everywhere and wrong. They are the
*test-authoring* half of the instrument rules the `/prove-it` skill carries.

- **An import-time, env-derived module global is order-fragile.** `S3_BUCKET = os.environ.get(...)`
  freezes at *first* import; in the full suite another test usually imported the module
  earlier under a different env, so an assertion on it passes solo and fails in CI — and a
  red Unit Tests job skips Deploy for the real Lambda. Pin the global inside the test
  (`monkeypatch.setattr(mod, "S3_BUCKET", ...)`) and reproduce the ordering before trusting green.
- **A packaged module ignores `sys.modules` stubs.** After `lambdas/` became packages (ADR-146),
  `monkeypatch.setitem(sys.modules, "bedrock_client", fake)` silently stopped applying —
  CPython's `from PKG import MOD` prefers the parent package's bound attribute — and eight
  "unit" tests began issuing real inference calls, failing only for want of credentials. Use
  `stub_bundled_module` in `tests/bundle_stubs.py`, which patches both; grep the suite for
  `setitem(sys.modules` and `types.ModuleType(` whenever a module moves.
- **After a split, the old module is a re-export, not a patch point.** `monkeypatch.setattr(old_module, "helper", fake)`
  patches the re-export while the moved function resolves `helper` in its own globals, so
  the real path runs. Repoint every `setattr`/`patch.object` at the symbol's real home, and
  run `ruff` (F821) after trimming a re-export list — a symbol another check still reads
  fails at call time, not import time.
- **A substring asserted absent from `json.dumps(result)` flakes about one run in ten** when
  the result carries `isoformat()` timestamps — microseconds alone will eventually contain
  the digits. Scrub volatile keys first (the `_semantic_blob` pattern) and sweep with
  `grep -rn 'not in json.dumps' tests/`.
- **The orphan-partition gate resolves writers by AST, not dataflow.** A `lambdas/web/` write
  whose `pk` is built outside the `put_item`/`update_item` call reads as writerless and reds
  `tests/test_site_partition_orphans.py`. Put conditional destinations inline in the call.
  And run the full suite **without `-x`** before pushing — `-x` hid this red behind an
  unrelated one.
- **A fixture's clock is the handler's clock.** A fixture computing its expectation from
  `datetime.now(timezone.utc).date()` for a handler on `pacific_today()` is one day ahead
  between 17:00 PT and midnight; the test shipped green because CI ran at 13:00 PT and broke
  `main` 24h later on someone else's commit. Derive the expectation through the handler's
  own clock helper, and if a check can only fail during part of the day, something must
  exercise it there (a faked clock or a dated re-run) — `/prove-it`, "a window it never
  runs in".
- **API schema baselines are captured wholesale.** `deploy/capture_api_schemas.py`
  re-snapshots every endpoint and rewrites `tests/api_schemas/_exemptions.json` in one run;
  run against a freshly reset platform it codifies Day-1 shapes as the baseline. Leave a
  single `capture-failed` exemption standing until a deliberately timed capture on stable
  data, and say so in the PR.

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

`ci-cd.yml` is an orchestrator over reusable workflows; the gates live in these files (read the step names there, they are the gate ids in `scripts/gate_census.py`):

| Workflow | Job (check name) | What it gates |
|---|---|---|
| `pr-checks.yml` | `Collect + deploy-critical + format` (**required**) | `pytest --collect-only`, the `deploy_critical` lane (`-n auto --dist loadfile`, then the serial complement), mypy on the clean set, `black --check`, `ruff check`, the bundle-boot gate |
| `pr-checks.yml` | `Full unit suite (pre-merge, issue 3025)` (**required**) | the whole tree, parallel pass then `-m serial`, after reconciling doc literals and regenerating the platform model in-workspace |
| `ci-lint.yml` | `Lint + Syntax Check` | flake8 (full report advisory; `E9,F63,F7,F82` blocking), `black --check`, `ruff check`, mypy clean set, py_compile, pip-audit, gitleaks, lambda_map coverage, content-policy scan, `bash -n` on `deploy/` |
| `ci-test.yml` | `Unit Tests` (3 shard legs + combine) | the exhaustive offline suite; coverage floor and ratchet; non-gating for deploy (#416, ADR-117) |
| `ci-cd.yml` | `Deploy-critical tests` | `-m "deploy_critical and not integration"` — gates Plan → Deploy |
| `docs-ci.yml` | `Wiki drift gates` | the doc gates (`python3 scripts/ci_gate_commands.py docs-ci.yml` lists them) |

**The format gate** (identical in the PR lane and Lint): `black --check lambdas/ mcp/ cdk/ tests/ scripts/ deploy/ qa/` (line length 140, `pyproject.toml`; `.json` is never run through black) and `ruff check` over the same directories (rules E/W/F/I/S). flake8 (`.flake8`, `E501` ignored) is the syntax/undefined-name floor. The tool versions are pinned via `scripts/ci_pins.py` from `requirements-dev.txt`; `deploy/agent_commit.sh` uses the pinned black.

Style-only flake8 findings do not fail CI; black, ruff, mypy-clean-set, `py_compile` and the E9/F63/F7/F82 floor do.

---

## Pre-commit and commit-msg hooks

Installed per clone by `bash scripts/install_hooks.sh` (the hooks live in untracked `.git/hooks/`, so rerun it after cloning and whenever it changes; `python3 deploy/session_postflight.py` reports hook freshness). The commit-msg hook enforces Conventional Commits and refuses tool-attribution lines; agents commit through `deploy/agent_commit.sh`. Details: `CONTRIBUTING.md`. Never bypass them (`--no-verify`).

---

## QA Strategy Scorecard (quarterly re-grade, #1451)

**Baseline set:** 2026-07-18, by the QA & Testing Strategy review (`review:qa-strategy-2026-07-18`
label; epic [#1425](https://github.com/averagejoematt/life-platform/issues/1425), a three-agent
survey with every finding verified against the repo). This is the **durable record** — the
`/review sdlc` quarterly checklist step (below, and in `.claude/skills/review/references/sdlc.md`)
re-grades against it and overwrites the "Current" column each run so the next re-grade always
diffs against the *previous* run, not perpetually against 2026-07-18.

### The 8 axes

| Axis | Baseline (2026-07-18) | Target | Current | Evidence for baseline grade |
|---|---|---|---|---|
| Deploy gating | A− | A | A− | Production-approval gate + post-deploy smoke + auto-rollback exist and are exercised on every deploy, but `visual-qa` is not yet the only gate with edge cases (see ADR-076 history) and the approval-gate itself has had live drift incidents (#1319 — GitHub env protection dropping on a repo-visibility flip). |
| Render breadth | C | A− | C | `qa/visual_qa.py` `PAGES` covered ~35 of ~80 live pages at baseline — 44 live pages (including live-data/AI/write pages) had zero render coverage. |
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

### Quarterly re-grade checklist (run from `/review sdlc`)

1. Re-read this table (baseline + target + current) before grading — it is the anchor; do not
   re-derive targets from memory.
2. For each of the 8 axes, re-grade against **current reality** using the rubric above: state
   the fraction/denominator, whether the check gates or is advisory, and cite the file/command/
   `gh run` evidence (same evidence rule as the rest of `/review sdlc`).
3. Diff each axis's new grade against the **Current** column here (not always the 2026-07-18
   baseline) and record the delta: improved / flat / regressed.
4. Fold the re-graded table + deltas into this run's `docs/reviews/SDLC_REVIEW_<date>.md` as a
   labeled subsection (Phase 3) — it is part of that review's artifact, not a separate doc.
5. Any axis that **regressed** vs its prior Current grade, or remains **two or more quarters
   short of target with no evidence of movement**, gets a story filed via the `issue-filer`
   agent — its contract (labels, score line, epic linkage) lives in
   `.claude/agents/issue-filer.md` and is not restated here. Carry the
   `review:qa-strategy-<date>` batch label. Epic #1425 that owned the original baseline is
   CLOSED; route the filing to the live class owner per the class-first rule rather than
   reviving it. Same as any other `/review sdlc` finding.
6. After the review lands, update the **Current** column in this table (in the same PR as the
   review artifact) so the next quarterly re-grade diffs against this run.

**First scheduled re-grade:** ~2026-10 (the next `/review sdlc` quarterly cadence after this
table was created). The clock that enforces it is the `sdlc-review` entry in
`scripts/operating_calendar.py`, which carries this obligation on the entry itself — it used to
hang off a comment on epic #1425, which is now closed.

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
# 3. Add to ci/lambda_map.json (skip_deploy if it is not a standalone Lambda)
# 4. Add to cdk/stacks/constants.py if needed
# 5. Write tests/test_<new_module>.py
```

---

**Verified:** 2026-10-17
