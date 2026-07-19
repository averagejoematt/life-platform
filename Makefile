# Life Platform — Developer Makefile (OE-02)
# Usage: make <target>
# All targets run from the repo root.

.PHONY: help test lint syntax preflight deploy-mcp deploy-site deploy-cdk-web \
        deploy-cdk-operational fleet commit clean

PYTHON  := python3
PYTEST  := $(PYTHON) -m pytest
FLAKE8  := $(PYTHON) -m flake8

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-24s\033[0m %s\n", $$1, $$2}'

# ── Testing ──────────────────────────────────────────────────────────────────

test:  ## Run all tests with verbose output
	$(PYTEST) tests/ -v

test-quick:  ## Run tests, stop on first failure
	$(PYTEST) tests/ -x -q

lint:  ## Run flake8 on lambdas/ and mcp/
	$(FLAKE8) lambdas/ mcp/

format:  ## Apply ruff (lint+import-sort) then black. Config in pyproject.toml.
	$(PYTHON) -m ruff check --fix lambdas/ mcp/ cdk/ tests/ scripts/ deploy/
	$(PYTHON) -m black lambdas/ mcp/ cdk/ tests/ scripts/ deploy/

format-check:  ## Verify formatting (no changes) — will gate CI once the baseline lands
	$(PYTHON) -m ruff check lambdas/ mcp/ cdk/ tests/ scripts/ deploy/
	$(PYTHON) -m black --check lambdas/ mcp/ cdk/ tests/ scripts/ deploy/

preflight:  ## Match CI gates locally: black==25.9.0 + ruff==0.14.0 + mypy + py_compile + test_shared_modules
	@echo "Installing CI-pinned tool versions (black==25.9.0 ruff==0.14.0 mypy==2.1.0)…"
	pip install --quiet black==25.9.0 ruff==0.14.0 mypy==2.1.0
	@echo "1/5  black --check…"
	black --check lambdas/ mcp/ cdk/ tests/ scripts/ deploy/
	@echo "2/5  ruff check…"
	ruff check lambdas/ mcp/ cdk/ tests/ scripts/ deploy/
	@echo "3/5  mypy (tier-1 clean-module set)…"
	$(PYTHON) -m mypy --config-file mypy.ini \
		lambdas/secret_cache.py lambdas/retry_utils.py lambdas/phase_filter.py \
		lambdas/constants.py lambdas/bedrock_client.py lambdas/scoring_engine.py \
		lambdas/character_engine.py lambdas/intelligence_common.py lambdas/ai_calls.py \
		lambdas/ai_context.py lambdas/ai_summaries.py
	@echo "4/5  py_compile…"
	find lambdas/ mcp/ -name '*.py' -exec $(PYTHON) -m py_compile {} \;
	@echo "5/5  pytest test_shared_modules (matching CI scope)…"
	$(PYTEST) tests/test_shared_modules.py -v --tb=short
	@echo "Preflight passed — CI gates clear."

syntax:  ## Syntax-check all Python files in lambdas/ and mcp/
	find lambdas/ mcp/ -name '*.py' -exec $(PYTHON) -m py_compile {} \;
	@echo "Syntax OK"

check: lint syntax test  ## lint + syntax + test (full pre-deploy check)

# ── Lambda Deploys ────────────────────────────────────────────────────────────

fleet:  ## Push a shared-module change to every function's bundle (#781 retired the old `layer` rebuild step — one bundle, no layer)
	bash deploy/deploy_fleet.sh

deploy-mcp:  ## Deploy MCP Lambda (life-platform-mcp) — mcp-shaped full bundle (#781)
	bash deploy/deploy_lambda.sh life-platform-mcp mcp_server.py

deploy-site-api:  ## Deploy site-api Lambda — full-tree bundle (NOT deploy_lambda.sh: sibling imports, see ci/lambda_map.json)
	bash deploy/deploy_site_api.sh

deploy-anomaly:  ## Deploy anomaly-detector Lambda
	bash deploy/deploy_lambda.sh anomaly-detector lambdas/emails/anomaly_detector_lambda.py

deploy-daily-brief:  ## Deploy daily-brief Lambda
	bash deploy/deploy_lambda.sh daily-brief lambdas/emails/daily_brief_lambda.py

# ── Site Deploys ──────────────────────────────────────────────────────────────

deploy-site:  ## Sync site/ to S3 (averagejoematt.com static pages)
	bash deploy/sync_site_to_s3.sh

# ── CDK Deploys ───────────────────────────────────────────────────────────────

deploy-cdk-web:  ## CDK deploy LifePlatformWeb (us-east-1: CloudFront distributions only; site-api Lambda infra is owned by LifePlatformServe, us-west-2, #793)
	cd cdk && npx cdk deploy LifePlatformWeb

deploy-cdk-operational:  ## CDK deploy LifePlatformOperational (us-west-2: ops Lambdas)
	cd cdk && npx cdk deploy LifePlatformOperational

deploy-cdk-all:  ## CDK deploy all stacks (full infra update — use carefully)
	cd cdk && npx cdk deploy --all

cdk-diff:  ## Show CDK diff for all stacks (no deploy)
	cd cdk && npx cdk diff

# ── Git ───────────────────────────────────────────────────────────────────────

commit:  ## Stage all modified tracked files and open commit prompt
	git add -u
	@echo "Staged files:"; git diff --cached --name-only
	@echo "Run: git commit -m 'your message'"

# ── Housekeeping ──────────────────────────────────────────────────────────────

clean:  ## Remove local build/cache cruft (all gitignored; regenerated on demand)
	rm -rf cdk/cdk.out
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .mypy_cache .pytest_cache .ruff_cache cdk/.pytest_cache
	@echo "Cleaned cdk.out + caches. Left intact: .venv, cdk/.venv, datadrops/, qa-screenshots/, captures/."
	@echo "(For the big .venv dirs use: rm -rf .venv cdk/.venv show_and_tell/.venv && reinstall.)"
