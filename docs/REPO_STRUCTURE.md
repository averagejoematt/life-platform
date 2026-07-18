# Repository Structure

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-07-10

The canonical top-level layout. Read this before adding a new file so things land where they belong — the root stays intentional, not accreted.

## Top-level directories

### Active — the running system
| Dir | Purpose |
|---|---|
| `lambdas/` | All Lambda source, by stack: `ingestion/ compute/ email/ web/ operational/ intelligence/` + shared modules at the root (`ai_calls.py`, `bedrock_client.py`, `constants.py`, …) — bundled into every function (#781). |
| `mcp/` | MCP server — 66 tools across `tools_*.py` domain modules, wired in `registry.py`. |
| `cdk/` | Infrastructure-as-code — 9 CDK stacks (`stacks/*.py`), entry `app.py`. **The only way infra changes.** |
| `deploy/` | Build/deploy scripts — `build_bundle.py`, `deploy_lambda.sh`, `deploy_fleet.sh`, `deploy_site_api.sh`, `sync_site_to_s3.sh`, `restart_pipeline.py`, `sync_doc_metadata.py`, smoke tests, `lib/`. |
| `scripts/` | Operational helpers — `v4_build_*.py` site generators, `generate_adr_index.py`, `content_policy_scan.py`, migration tooling. |
| `tests/` | pytest (unit/contract/structural) + Playwright `visual_qa.py` + AI-vision QA. |
| `docs/` | Architecture, runbooks, ADRs (`DECISIONS.md`), schema, this file. Index in `docs/README.md`. |
| `config/` | DynamoDB schemas, `user_goals.json` (genesis/baseline source), feature configs. |
| `site/` | v4 static site (Cockpit/Story/Evidence), deployed to S3 + CloudFront. |
| `ci/` | CI support — `lambda_map.json` (source-file → function → stack mapping). |
| `handovers/` | Session handover docs. `HANDOVER_LATEST.md` is current; prior ones are dated + archived. |
| `remediation/` | Self-healing agent (`agent.py`, `automerge.py`) — driven by `.github/workflows/remediation-agent.yml`. |
| `assets/` | Repo-level static asset(s) (the platform icon). NB: site/OG images live under the S3 `generated/` prefix, not here. |
| `ingest/` | Local macOS `launchd` drop-folder watchers for manual data uploads (operational tooling, runs on the operator's machine). |
| `setup/` | One-time OAuth/credential setup scripts per integration (Garmin, Withings, Eight Sleep, …). Run locally for token rotation. |

### Audit-trail — run-once, kept as the incident/operation record
| Dir | Purpose |
|---|---|
| `patches/` | One-shot DDB/S3 data corrections (`patch_*.py`). Each is a dated surgical fix — kept for audit, never blindly re-run. |
| `backfill/` | One-shot historical data imports. Same discipline as `patches/`. |
| `seeds/` | Test/dev bootstrap data generators for DynamoDB state. |

### Local / scratch / generated — gitignored or owner-local
`datadrops/` (personal health data), `qa-screenshots/` (Playwright output), `show_and_tell/` (PDF-builder scratch), `captures/` (superseded capture harness — use `tests/visual_qa.py`), `spikes/` (exploratory prototypes, e.g. `pg14_ai_me`), and build artifacts (`cdk/cdk.out/`, `.venv/`, `__pycache__/`, `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`, `layer-build/`) — all gitignored. `archive/` holds pre-CDK v3.x snapshots as on-disk history only (nothing there runs).

Run `make clean` to reclaim local build/cache cruft (chiefly `cdk/cdk.out`, ~6 GB) — all of it is regenerated on demand.

## Where does X go?
- **New Lambda** → `lambdas/<category>/<name>_lambda.py` → register in `ci/lambda_map.json` → define in the right `cdk/stacks/*.py` via `create_platform_lambda`.
- **New MCP tool** → `mcp/tools_<domain>.py` → wire into `mcp/registry.py` (and `tests/test_wiring_coverage.py` will enforce it).
- **Infra / IAM / schedule change** → `cdk/stacks/` only — never the AWS console.
- **One-shot data fix** → `patches/patch_<desc>.py` (keep it; it's the audit trail).
- **One-shot data import** → `backfill/`.
- **A decision worth recording** → an ADR in `docs/DECISIONS.md`.
- **End-of-session handover** → rewrite `handovers/HANDOVER_LATEST.md` (archive the prior one as `HANDOVER_<date>_<Topic>.md`).
- **Throwaway experiment / prototype** → `spikes/` (kept out of the deployed product) or `/tmp`.

## Conventions
- Lambda handlers end in `*_lambda.py` and define `lambda_handler` (enforced by `tests/test_cdk_handler_consistency.py` + the size gate).
- Secrets live in AWS Secrets Manager under `life-platform/` — never in the repo.
- No build artifacts, caches, or `.venv`s are ever committed (`.gitignore` enforces this).
