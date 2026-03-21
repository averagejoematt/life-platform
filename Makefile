# Life Platform — Developer Makefile (OE-02)
# Usage: make <target>
# All targets run from the repo root.

.PHONY: help test lint syntax deploy-mcp deploy-site deploy-cdk-web \
        deploy-cdk-operational layer commit

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

syntax:  ## Syntax-check all Python files in lambdas/ and mcp/
	find lambdas/ mcp/ -name '*.py' -exec $(PYTHON) -m py_compile {} \;
	@echo "Syntax OK"

check: lint syntax test  ## lint + syntax + test (full pre-deploy check)

# ── Lambda Deploys ────────────────────────────────────────────────────────────

layer:  ## Rebuild Lambda layer (shared modules: ai_calls, board_loader, etc.)
	bash deploy/build_layer.sh

deploy-mcp:  ## Deploy MCP Lambda (life-platform-mcp)
	bash deploy/deploy_lambda.sh life-platform-mcp

deploy-site-api:  ## Deploy site-api Lambda (life-platform-site-api)
	bash deploy/deploy_lambda.sh life-platform-site-api

deploy-anomaly:  ## Deploy anomaly-detector Lambda
	bash deploy/deploy_lambda.sh anomaly-detector

deploy-daily-brief:  ## Deploy daily-brief Lambda
	bash deploy/deploy_lambda.sh daily-brief

# ── Site Deploys ──────────────────────────────────────────────────────────────

deploy-site:  ## Sync site/ to S3 (averagejoematt.com static pages)
	bash deploy/sync_site_to_s3.sh

deploy-sprint7:  ## Deploy Sprint 7 site changes (tier-0 script)
	bash deploy/deploy_sprint7_tier0.sh

# ── CDK Deploys ───────────────────────────────────────────────────────────────

deploy-cdk-web:  ## CDK deploy LifePlatformWeb (us-east-1: CloudFront, site-api Lambda)
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
