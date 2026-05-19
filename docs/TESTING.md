# Testing Strategy

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

**Total tests:** 1,217 passing (as of 2026-05-19) + 41 skipped + 10 xfailed + 15 deselected.

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
  - `test_i9_dlq_empty` — DLQ near-zero
  - `test_i10_mcp_lambda_responds` — MCP roundtrip
  - `test_i11_data_reconciliation_running` — weekly reconciliation alive
  - `test_i12_mcp_tool_shape` — tool dispatch returns expected shape
  - `test_i13_freshness_checker_returns_valid_data` — pipeline health

### 4. Layer-version consistency tests (`test_layer_version_consistency.py`)
- **LV1:** No hardcoded layer ARN with version number in CDK stacks
- **LV2:** All consumers in `ci/lambda_map.json` referenced in CDK
- **LV3:** All layer modules in lambda_map exist on disk
- **LV4:** Consumer-list min count (catches truncation)
- **LV5:** Hardcoded ARN only in `constants.py`
- **LV6:** Source-vs-AWS check — `SHARED_LAYER_VERSION` constant matches latest published (V2 P0.2 follow-up; prevents the regression bomb)

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

---

## What's NOT tested

| What | Why not | Risk |
|---|---|---|
| Actual Anthropic API responses | Cost + flakiness | Low (mocked) |
| Email rendering in real mail clients | Manual visual check | Medium (rendering quirks) |
| Static site visual regression | No screenshot diffing | Medium (cosmetic only) |
| Whoop/Garmin/etc. live OAuth flows | Requires real creds | High — but covered by smoke + post-deploy alarms |
| CloudFront cache behavior | Hard to test deterministically | Low (CF is reliable) |
| WAF rate-limit accuracy | Would require burst-testing | Low (CloudWatch tracks blocks) |
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
# 2. Add to deploy/build_layer.sh MODULES list
# 3. Add to ci/lambda_map.json skip_deploy
# 4. Add to cdk/stacks/constants.py if needed
# 5. Write tests/test_<new_module>.py
```

---

**Verified:** 2026-05-19
