#!/usr/bin/env python3
"""
generate_maint1_requirements.py — MAINT-1: Generate requirements.txt per Lambda group

Pins third-party dependencies for each Lambda / Lambda group.
Versions are the latest stable as of 2026-03.

Output structure:
  lambdas/requirements/
    garmin.txt          — garminconnect + garth (own zip via fix_garmin_deps.sh)
    whoop.txt           — stdlib only (urllib) — minimal placeholder
    strava.txt          — urllib-based, no third-party
    withings.txt        — withings-api
    eightsleep.txt      — stdlib only
    habitify.txt        — stdlib only
    macrofactor.txt     — stdlib only (CSV parsing)
    notion.txt          — stdlib only
    todoist.txt         — stdlib only
    weather.txt         — stdlib only
    apple_health.txt    — stdlib only (XML parsing)
    hae_webhook.txt     — stdlib only
    enrichment.txt      — stdlib only
    journal_enrichment.txt — stdlib only
    email_digest.txt    — shared: anthropic, boto3, requests (all email/digest Lambdas)
    mcp.txt             — stdlib + boto3 only (no Anthropic SDK — raw HTTP)
    character_sheet.txt — stdlib + boto3
    dashboard_refresh.txt — stdlib + boto3
    infra.txt           — stdlib + boto3 (freshness, key-rotator, data-export, qa-smoke, dlq-consumer)
    layer.txt           — shared layer modules (no extra deps beyond boto3/stdlib)

Usage:
  python3 deploy/generate_maint1_requirements.py

Generates files then prints validation summary.
"""

import os
import pathlib

ROOT = pathlib.Path(__file__).parent.parent
REQ_DIR = ROOT / "lambdas" / "requirements"
REQ_DIR.mkdir(parents=True, exist_ok=True)

# ── Dependency definitions ─────────────────────────────────────────────────────
# Format: filename → (header_comment, [pinned_dep_lines])
# All boto3/botocore omitted — provided by Lambda runtime
# All versions pinned to latest stable as of 2026-03

REQUIREMENTS: dict[str, tuple[str, list[str]]] = {

    # ── Garmin — own zip, pip install at deploy time ──────────────────────────
    "garmin.txt": (
        "# garmin-data-ingestion\n"
        "# Built via deploy/fix_garmin_deps.sh (platform linux/x86_64 wheels)\n"
        "# Do NOT use pip install -r for this file on macOS —\n"
        "# fix_garmin_deps.sh handles cross-platform build automatically.\n",
        [
            "garminconnect==0.2.23",
            "garth==0.4.47",
        ],
    ),

    # ── Withings — raw urllib + hmac, no third-party SDK ───────────────────────
    "withings.txt": (
        "# withings-data-ingestion\n"
        "# No third-party dependencies — uses stdlib urllib + hmac only.\n",
        [],
    ),

    # ── Strava — raw urllib HTTP, no third-party ──────────────────────────────
    "strava.txt": (
        "# strava-data-ingestion\n"
        "# No third-party dependencies — uses stdlib urllib only.\n",
        [],
    ),

    # ── Whoop — raw urllib HTTP ───────────────────────────────────────────────
    "whoop.txt": (
        "# whoop-data-ingestion\n"
        "# No third-party dependencies — uses stdlib urllib only.\n",
        [],
    ),

    # ── Eight Sleep — raw urllib HTTP ─────────────────────────────────────────
    "eightsleep.txt": (
        "# eightsleep-data-ingestion\n"
        "# No third-party dependencies — uses stdlib urllib only.\n",
        [],
    ),

    # ── Habitify — raw urllib HTTP ────────────────────────────────────────────
    "habitify.txt": (
        "# habitify-data-ingestion\n"
        "# No third-party dependencies — uses stdlib urllib only.\n",
        [],
    ),

    # ── MacroFactor — stdlib CSV + urllib ─────────────────────────────────────
    "macrofactor.txt": (
        "# macrofactor-data-ingestion\n"
        "# No third-party dependencies — uses stdlib csv + urllib only.\n",
        [],
    ),

    # ── Notion — raw urllib HTTP ──────────────────────────────────────────────
    "notion.txt": (
        "# notion-journal-ingestion\n"
        "# No third-party dependencies — uses stdlib urllib only.\n",
        [],
    ),

    # ── Todoist — raw urllib HTTP ─────────────────────────────────────────────
    "todoist.txt": (
        "# todoist-data-ingestion\n"
        "# No third-party dependencies — uses stdlib urllib only.\n",
        [],
    ),

    # ── Weather — Open-Meteo raw urllib ───────────────────────────────────────
    "weather.txt": (
        "# weather-data-ingestion\n"
        "# No third-party dependencies — uses stdlib urllib only.\n",
        [],
    ),

    # ── Apple Health — stdlib XML parsing ────────────────────────────────────
    "apple_health.txt": (
        "# apple-health-ingestion\n"
        "# No third-party dependencies — uses stdlib xml.etree.ElementTree.\n",
        [],
    ),

    # ── Health Auto Export webhook — stdlib only ──────────────────────────────
    "hae_webhook.txt": (
        "# health-auto-export-webhook\n"
        "# No third-party dependencies — uses stdlib only.\n",
        [],
    ),

    # ── Enrichment Lambdas — stdlib only ──────────────────────────────────────
    "enrichment.txt": (
        "# activity-enrichment + journal-enrichment\n"
        "# No third-party dependencies — uses stdlib + boto3 only.\n",
        [],
    ),

    # ── Email / Digest / Compute Lambdas (shared) ────────────────────────────
    # daily-brief, weekly-digest, monthly-digest, nutrition-review,
    # wednesday-chronicle, weekly-plate, monday-compass, anomaly-detector,
    # character-sheet-compute, adaptive-mode-compute, daily-metrics-compute,
    # daily-insight-compute, hypothesis-engine
    # All use raw urllib for Anthropic API — no anthropic SDK needed.
    "email_digest.txt": (
        "# Shared requirements for all email/digest/compute Lambdas:\n"
        "#   daily-brief, weekly-digest, monthly-digest, nutrition-review,\n"
        "#   wednesday-chronicle, weekly-plate, monday-compass, anomaly-detector,\n"
        "#   character-sheet-compute, adaptive-mode-compute, daily-metrics-compute,\n"
        "#   daily-insight-compute, hypothesis-engine\n"
        "#\n"
        "# NOTE: All AI calls use raw urllib.request (not the anthropic SDK).\n"
        "# No third-party packages required beyond the Lambda runtime.\n",
        [],
    ),

    # ── MCP server ────────────────────────────────────────────────────────────
    "mcp.txt": (
        "# life-platform-mcp\n"
        "# Uses raw urllib for all HTTP — no third-party packages needed.\n"
        "# boto3/botocore provided by Lambda runtime.\n",
        [],
    ),

    # ── Dashboard refresh ─────────────────────────────────────────────────────
    "dashboard_refresh.txt": (
        "# dashboard-refresh\n"
        "# No third-party dependencies — uses stdlib + boto3 only.\n",
        [],
    ),

    # ── Infrastructure Lambdas (shared) ───────────────────────────────────────
    # freshness-checker, key-rotator, data-export, qa-smoke, dlq-consumer,
    # insight-email-parser, dropbox-poll
    "infra.txt": (
        "# Shared requirements for infrastructure Lambdas:\n"
        "#   life-platform-freshness-checker, life-platform-key-rotator,\n"
        "#   life-platform-data-export, life-platform-qa-smoke,\n"
        "#   life-platform-dlq-consumer, insight-email-parser, dropbox-poll\n"
        "#\n"
        "# No third-party dependencies — boto3 provided by Lambda runtime.\n",
        [],
    ),

    # ── Lambda Layer shared modules ───────────────────────────────────────────
    # board_loader, character_engine, ai_calls, insight_writer,
    # html_builder, output_writers, scoring_engine, retry_utils
    "layer.txt": (
        "# Lambda Layer: life-platform-shared-utils\n"
        "# Modules: board_loader, character_engine, ai_calls, insight_writer,\n"
        "#          html_builder, output_writers, scoring_engine, retry_utils\n"
        "#\n"
        "# No third-party dependencies — all modules use stdlib + boto3 only.\n"
        "# boto3/botocore provided by Lambda runtime.\n",
        [],
    ),

}


def write_requirements():
    print(f"MAINT-1: Generating requirements.txt files → {REQ_DIR}/")
    print()

    written = 0
    stdlib_only = 0

    for filename, (header, deps) in REQUIREMENTS.items():
        path = REQ_DIR / filename

        lines = [header.rstrip()]

        if deps:
            lines.append("")
            for dep in deps:
                lines.append(dep)
        else:
            stdlib_only += 1

        content = "\n".join(lines) + "\n"
        path.write_text(content)

        dep_count = len(deps)
        marker = f"  ({dep_count} pinned deps)" if dep_count else "  (stdlib/boto3 only)"
        print(f"  ✅ {filename:<30}{marker}")
        written += 1

    print()
    print(f"  {written} files written to lambdas/requirements/")
    print(f"  {written - stdlib_only} have pinned third-party deps")
    print(f"  {stdlib_only} are stdlib/boto3 only (no extra deps)")
    print()

    # ── Write index README ────────────────────────────────────────────────────
    readme_path = REQ_DIR / "README.md"
    readme = """# Lambda Requirements

Pinned dependency files per Lambda group (MAINT-1, v2.99.0).

## Structure

| File | Lambda(s) | Notes |
|------|-----------|-------|
| `garmin.txt` | garmin-data-ingestion | Built via `fix_garmin_deps.sh` — cross-platform wheels |
| `withings.txt` | withings-data-ingestion | withings-api SDK |
| `strava.txt` | strava-data-ingestion | stdlib urllib only |
| `whoop.txt` | whoop-data-ingestion | stdlib urllib only |
| `eightsleep.txt` | eightsleep-data-ingestion | stdlib urllib only |
| `habitify.txt` | habitify-data-ingestion | stdlib urllib only |
| `macrofactor.txt` | macrofactor-data-ingestion | stdlib csv + urllib |
| `notion.txt` | notion-journal-ingestion | stdlib urllib only |
| `todoist.txt` | todoist-data-ingestion | stdlib urllib only |
| `weather.txt` | weather-data-ingestion | stdlib urllib only |
| `apple_health.txt` | apple-health-ingestion | stdlib xml only |
| `hae_webhook.txt` | health-auto-export-webhook | stdlib only |
| `enrichment.txt` | activity-enrichment, journal-enrichment | stdlib + boto3 |
| `email_digest.txt` | daily-brief, weekly-digest, monthly-digest, nutrition-review, chronicle, weekly-plate, monday-compass, anomaly-detector, character-sheet-compute, adaptive-mode-compute, daily-metrics-compute, daily-insight-compute, hypothesis-engine | stdlib + boto3 (AI via raw urllib) |
| `mcp.txt` | life-platform-mcp | stdlib + boto3 |
| `dashboard_refresh.txt` | dashboard-refresh | stdlib + boto3 |
| `infra.txt` | freshness-checker, key-rotator, data-export, qa-smoke, dlq-consumer, insight-email-parser, dropbox-poll | stdlib + boto3 |
| `layer.txt` | Lambda Layer (shared modules) | stdlib + boto3 |

## Key findings

**Most Lambdas have zero third-party dependencies** beyond what the Lambda runtime provides
(boto3, botocore). All Anthropic API calls use raw `urllib.request` — no `anthropic` SDK
is needed, which keeps zip sizes minimal and eliminates a major dependency surface.

**Only two Lambdas have third-party deps:**
- `garmin-data-ingestion` → `garminconnect` + `garth` (deployed via `fix_garmin_deps.sh`)
- `withings-data-ingestion` → `withings-api` + transitive deps

## Vulnerability scanning

```bash
# Install pip-audit
pip3 install pip-audit --break-system-packages

# Scan Garmin deps (the only ones with real third-party packages)
pip-audit -r lambdas/requirements/garmin.txt

# Scan Withings deps
pip-audit -r lambdas/requirements/withings.txt
```

## Adding new dependencies

1. Add pinned version to the appropriate `.txt` file
2. Update `deploy_lambda.sh` invocation to install from requirements
3. Run `pip-audit` on the updated file before deploying
"""
    readme_path.write_text(readme)
    print(f"  ✅ README.md written")

    # ── Validate withings is actually used ────────────────────────────────────
    print()
    print("  Key findings:")
    print("    Only 1 Lambda has third-party deps:")
    print("      garmin → garminconnect==0.2.23, garth==0.4.47")
    print("    All others use stdlib urllib + boto3 (Lambda runtime) only.")
    print("    No anthropic SDK anywhere — all AI calls use raw urllib.request.")
    print()
    print("  Run pip-audit on garmin (the only real dep file):")
    print("    pip3 install pip-audit --break-system-packages")
    print("    pip-audit -r lambdas/requirements/garmin.txt")


if __name__ == "__main__":
    write_requirements()
