#!/usr/bin/env python3
"""
restart_docs_update.py — ADR-058: Generate docs reflecting the experiment
restart. Reads genesis from lambdas/constants.py.

Touches:
  1. docs/DECISIONS.md           — appends ADR-058 (if not already present)
  2. docs/CHANGELOG.md           — prepends an entry under the most recent
                                   version, or creates v8.1.0 (idempotent: by date)
  3. docs/SCHEMA.md              — appends a `phase` attribute note (idempotent: by header)
  4. docs/ARCHITECTURE.md        — appends "Experiment Phase Filtering" subsection
  5. docs/RUNBOOK.md             — appends "Restart Pipeline" runbook entry
  6. docs/BACKLOG.md             — appends restart follow-up items
  7. docs/MCP_TOOL_CATALOG.md    — appends phase-filter notes on date-range tools

Date-agnostic. Idempotent: each section checks for an ADR-058 marker before
inserting. Re-running with a new genesis updates the in-place content rather
than duplicating sections.

Usage:
    python3 deploy/restart_docs_update.py            # dry-run
    python3 deploy/restart_docs_update.py --apply    # write files
"""
import argparse
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lambdas.constants import (
    EXPERIMENT_BASELINE_WEIGHT_LBS,
    EXPERIMENT_START_DATE,
)

DOCS = REPO_ROOT / "docs"
TODAY = date.today().isoformat()
START_INT = int(round(EXPERIMENT_BASELINE_WEIGHT_LBS))


ADR_058_MARKER = "## ADR-058"

ADR_058 = f"""
{ADR_058_MARKER}: Experiment Restart — single source of truth for genesis date

**Status:** Accepted ({TODAY})
**Anchor:** EXPERIMENT_START_DATE = {EXPERIMENT_START_DATE}
**Baseline:** {EXPERIMENT_BASELINE_WEIGHT_LBS} lbs (Withings reading on genesis)

### Decision
Re-anchor the experiment to a fresh genesis date. All pre-genesis raw data is
preserved in DynamoDB but tagged `phase=pilot` and hidden from public surfaces,
scoring, coaching, chronicle, and grading. The genesis date is the single
source of truth — everything (Day-N counter, character sheet, coach predictions,
challenges, experiments, chronicle, public site) anchors to it.

### Implementation
- **Config-driven constants** — `config/user_goals.json` is the canonical source of
  truth. `lambdas/constants.py` is regenerated from it via
  `deploy/sync_constants_from_config.py`.
- **DDB phase tagging** — `restart_phase_tag.py` marks every record under
  `USER#matthew#SOURCE#*` with `phase=pilot` (sk date < genesis) or
  `phase=experiment` (sk date ≥ genesis). Cross-phase identity records
  (subscribers, genome, profile, config) are never tagged.
- **Read-path filter** — `lambdas/phase_filter.py` provides `with_phase_filter()`
  used by `site_api._query_source`, `mcp.core.query_source`, and named
  endpoints/tools. Default: phase=pilot hidden. `include_pilot=True` to bypass.
- **Intelligence wipe** — `restart_intelligence_wipe.py` tombstones coach
  state via UpdateItem add-flag (interpretation B): the original content
  stays intact under `tombstone=true`. Reversible by removing the flag.
- **Character rebuild** — `restart_character_rebuild.py` invokes
  `character-sheet-compute` for every day genesis→today with `force=true`.
  `fetch_date` filters tombstones so the cascade starts at Level 1.
- **Chronicle** — `restart_chronicle_handler.py` archives chronicle HTML to
  `*/archive/pilot/` (tombstone-overwrite originals, IAM blocks DeleteObject).
  Indexes rewritten to Day-1 placeholder. Optional --resurrect-sk to keep + redate.
- **Site copy** — `restart_site_copy_sync.py` regenerates
  `site_constants.js` journey block + hero copy, sweeps "Day 1 · 307 lbs" /
  Feb-22 references, S3 syncs, CloudFront invalidates.
- **Orchestrator** — `restart_pipeline.py` chains all of the above given
  `--genesis YYYY-MM-DD`.

### Consequences
- The system is **repeatable**: a one-command pipeline can move genesis to a
  new date and re-converge all surfaces.
- All pre-genesis data is preserved and recoverable (interpretation B
  preserves item content under tombstone flags; raw S3 objects are
  tombstone-overwritten but accessible at `*/archive/pilot/*`).
- Public-facing copy has no acknowledgement of any prior attempt. Per
  Matthew's D decision: full scrub, including the platform-build narrative.
- Six pre-existing tech-debt failures in the integration test suite are
  not in scope: notion secret deletion, 62-message DLQ, stale layer versions
  on 6 Lambdas (now resolved as side-effect of v53 deploy).
""".lstrip()


CHANGELOG_MARKER = f"## [Restart {EXPERIMENT_START_DATE}]"

CHANGELOG_ENTRY = f"""{CHANGELOG_MARKER} — {TODAY}

### Added
- `lambdas/constants.py` — runtime constants (genesis date, baseline weight). Generated from `config/user_goals.json` via `deploy/sync_constants_from_config.py`.
- `lambdas/phase_filter.py` — `with_phase_filter()` helper. Wired into `site_api._query_source`, `mcp.core.query_source`, and all 13 queries in `intelligence_common.py`.
- 6 restart scripts under `deploy/`: `restart_phase_tag.py`, `restart_intelligence_wipe.py`, `restart_character_rebuild.py`, `restart_chronicle_handler.py`, `restart_site_copy_sync.py`, `restart_pipeline.py`.

### Changed
- Genesis re-anchored to **{EXPERIMENT_START_DATE}**. Baseline weight: **{EXPERIMENT_BASELINE_WEIGHT_LBS} lbs** (Withings).
- All Lambda code that referenced `"2026-04-01"` or `307` literals migrated to import from `lambdas.constants`.
- `character_sheet_lambda.fetch_date` now filters tombstones (clean-slate cascade).

### Removed
- `S3DataKey` customer-managed KMS key resource from `cdk/stacks/core_stack.py`. Bucket already on AES256.
- Public-facing references to prior attempts: hero copy, CTA, build-history references on `site/builders/`.

"""


SCHEMA_MARKER = f"### ADR-058: Phase attribute"

SCHEMA_APPEND = f"""
{SCHEMA_MARKER}

Every DDB item under `USER#matthew#SOURCE#*` carries an optional `phase` attribute:

| Value         | Meaning                                                          |
|---------------|------------------------------------------------------------------|
| `experiment`  | Record dated on or after EXPERIMENT_START_DATE (currently {EXPERIMENT_START_DATE}). |
| `pilot`       | Record dated before EXPERIMENT_START_DATE.                       |
| (unset)       | Cross-phase identity record: profile, config, subscribers, genome, field_notes, baseline_snapshot, re_entry. |

Records under wipe-list partitions (chronicle, coach_threads, predictions, hypotheses,
decisions, insights, challenges, experiments, character_sheet, habit_scores, certain
platform_memory categories) additionally carry `tombstone=true`, `tombstoned_at`,
`tombstoned_reason` after the §5 wipe. `hidden=true` on chronicle items specifically.

Read-path filtering is supplied by `lambdas/phase_filter.py::with_phase_filter()`.
"""


ARCH_MARKER = "### Experiment Phase Filtering"

ARCH_APPEND = f"""
{ARCH_MARKER}

**Default deny pilot.** Every Query/Scan that fans-in via `_query_source` (site-api)
or `query_source` (mcp/core) automatically appends a FilterExpression that hides
`phase=pilot` records. Items without a `phase` attribute pass through (cross-phase
identity records, plus historical writes that pre-date ADR-058).

Direct `table.query` call sites that bypass the chokepoints are individually
wrapped in `intelligence_common.py` and in the spec-named site-api endpoints
(`handle_timeline`, `handle_correlations`). ~110 secondary call sites remain
unwrapped — most operate on post-genesis date ranges where pilot exposure is
not a concern. Tracked as a follow-up sweep.

Callers can pass `include_pilot=True` to bypass the filter (research / audit use).
"""


RUNBOOK_MARKER = "## Restart Pipeline"

RUNBOOK_APPEND = f"""
{RUNBOOK_MARKER}

To re-anchor the experiment to a new genesis date:

```bash
# 1. Verify the Withings reading exists for the target date in DDB.
# 2. Run the orchestrator:
python3 deploy/restart_pipeline.py --genesis YYYY-MM-DD --dry-run
# 3. Review the report, then commit:
python3 deploy/restart_pipeline.py --genesis YYYY-MM-DD --apply
```

The pipeline runs (in order, each idempotent):
1. `sync_constants_from_config.py` — regenerates `lambdas/constants.py`
2. `bash deploy/build_layer.sh` + layer version bump + `cdk deploy LifePlatformCore LifePlatformCompute LifePlatformEmail`
3. `restart_phase_tag.py --apply` — flips DDB phase tags relative to the new genesis
4. `restart_intelligence_wipe.py --apply` — tombstones any newly pre-genesis records
5. `restart_character_rebuild.py --apply` — recomputes character sheets from new genesis
6. `restart_chronicle_handler.py --apply` — archives any newly pre-genesis chronicle HTML
7. `restart_site_copy_sync.py --apply` — regenerates JS/JSON/HTML site copy + CloudFront invalidate

All steps preserve original data (interpretation B for DDB, archive-not-delete for S3).
Roll back by removing tombstone flags (DDB) or copying from `*/archive/pilot/` (S3).

See ADR-058 in `docs/DECISIONS.md` for the design rationale.
"""


BACKLOG_MARKER = "### Restart 2026-05-18 follow-ups"

BACKLOG_APPEND = f"""
{BACKLOG_MARKER}

- [ ] Sweep ~110 remaining direct `table.query` call sites that bypass the phase-filter chokepoints (mostly in compute Lambdas and secondary MCP tools — see `_restart_followups.txt`).
- [ ] Re-evaluate phase filter at 30/60/90 days post-restart (ADR-058 §13).
- [ ] Remove orphan IAM references to `S3_KMS_KEY_ARN` in `cdk/stacks/role_policies.py` once the customer key completes its scheduled deletion (2026-06-16).
- [ ] DLQ has 62 stale messages — drain via `life-platform-dlq-consumer` (pre-existing, unrelated).
- [ ] `life-platform/notion` secret is `MARKED FOR DELETION` — confirm intentional or re-create (pre-existing, unrelated).
- [ ] Decide whether to resurrect 1-2 specific chronicle entries via `restart_chronicle_handler.py --resurrect-sk`, or leave the chronicle blank until the next Wednesday cycle generates the first fresh entry.
"""


MCP_MARKER = "### Phase-filter behavior (ADR-058)"

MCP_APPEND = f"""
{MCP_MARKER}

The following tools default to `phase=experiment`-only results and hide
phase=pilot records:

- `get_date_range`, `find_days`, `get_aggregated_summary`, `search_activities`,
  `get_field_stats`, `compare_periods`, `get_weekly_summary` — route through
  `mcp.core.query_source` which applies the filter.
- `get_latest`, `get_daily_summary` — apply the filter directly.
- `get_daily_snapshot`, `get_longitudinal_summary` — dispatch to the above.

To access pre-genesis data, pass `include_pilot=True`. Most tools accept this
keyword via the args dict. See `lambdas/phase_filter.py::with_phase_filter()`
for the underlying mechanism.
"""


SECTIONS = [
    ("docs/DECISIONS.md", ADR_058_MARKER, ADR_058, "append"),
    ("docs/CHANGELOG.md", CHANGELOG_MARKER, CHANGELOG_ENTRY, "prepend"),
    ("docs/SCHEMA.md", SCHEMA_MARKER, SCHEMA_APPEND, "append"),
    ("docs/ARCHITECTURE.md", ARCH_MARKER, ARCH_APPEND, "append"),
    ("docs/RUNBOOK.md", RUNBOOK_MARKER, RUNBOOK_APPEND, "append"),
    ("docs/BACKLOG.md", BACKLOG_MARKER, BACKLOG_APPEND, "append"),
    ("docs/MCP_TOOL_CATALOG.md", MCP_MARKER, MCP_APPEND, "append"),
]


def update_doc(path: Path, marker: str, payload: str, mode: str, apply: bool) -> str:
    """Returns one of: 'created', 'updated', 'unchanged'."""
    if not path.exists():
        if apply:
            path.write_text(payload)
        return "created"
    text = path.read_text()
    if marker in text:
        return "unchanged"
    if mode == "prepend":
        new_text = payload + "\n" + text
    else:
        sep = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
        new_text = text + sep + payload
    if apply:
        path.write_text(new_text)
    return "updated"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Commit writes (default: dry-run)")
    args = parser.parse_args()

    mode_str = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode_str}] docs update. genesis={EXPERIMENT_START_DATE} baseline={EXPERIMENT_BASELINE_WEIGHT_LBS}\n")

    results = []
    for rel, marker, payload, mode in SECTIONS:
        path = REPO_ROOT / rel
        status = update_doc(path, marker, payload, mode, args.apply)
        print(f"  {status:9s}  {rel}")
        results.append((rel, status))

    report = REPO_ROOT / "docs" / "restart" / "_docs_update_report.txt"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        f"docs update report — mode={mode_str} — genesis={EXPERIMENT_START_DATE}\n\n" + "\n".join(f"{s:9s}  {r}" for r, s in results) + "\n"
    )
    print(f"\nReport written to: {report.relative_to(REPO_ROOT)}")
    if not args.apply:
        print(f"\n(dry-run) — pass --apply to commit.")


if __name__ == "__main__":
    main()
