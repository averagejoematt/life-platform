"""
lambdas/web/site_api_data.py — domain-data endpoint handlers.

Extracted from lambdas/web/site_api_lambda.py (P1.1 Phase B step 6, 2026-05-26).
The vitals-adjacent cluster (glucose / sleep / circadian / phenoage / labs /
genome) and the intelligence-adjacent cluster (correlations / forecast /
scenarios / state_of_matthew / inference_receipt / wrong / pillar_coupling) were
split out into site_api_vitals.py and site_api_intelligence.py respectively
(#1240). What remains here is the genuine data grab-bag: habits, experiments,
the ledger/discoveries, pipeline freshness, and the S3-config passthroughs.

Endpoints routed from this module (kept in sync by tests/test_site_api_data_split.py):
  /api/changes-since, /api/observatory_week
  /api/cycle_compare, /api/survival
  /api/device_agreement, /api/last_sync, /api/source_freshness, /api/presence
  /api/discoveries, /api/ledger, /api/what_changed
  /api/experiments, /api/supplements, /api/vice_streaks, /api/fulfillment_ritual,
  /api/fulfillment_index
  /api/character_calibration (#1409 — felt-reality calibration ledger, aggregates only)
  /api/habits, /api/habit_streaks, /api/habit_registry
  /api/routine (#1066 — the prescribed training block, counts-only projection)
  /api/tools_baseline, /api/platform_stats
  /api/protocols, /api/domains

  Handler bodies were extracted into cohesive web/site_api_{freshness,habits,
  protocols,ledger,fulfillment,rollups}.py modules (#1654). This file keeps the
  routed entrypoints as thin delegators plus the shared + monkeypatched state the
  split modules read back through the `_g` facade-globals hand-off (each delegator
  passes its own globals()), so routes, contracts, and the test monkeypatch surface
  are unchanged.
"""

import json
import os
from datetime import datetime, timezone

import boto3
import habit_causality
from boto3.dynamodb.conditions import Key
from source_registry import (  # #392: canonical source classification (bundled lambdas/ tree)
    DEFAULT_STALE_HOURS as _FRESHNESS_DEFAULT_STALE_HOURS,
    engagement_channels,
    manual_capture_sources,
    public_board_sources,
    public_paused_sources,
    stale_hours_overrides,
)

from web.site_api_common import (
    EXPERIMENT_START,
    PT,
    S3_REGION,
    USER_PREFIX,
    _decimal_to_float,
    _experiment_date,
    _is_blocked_vice,
    _load_s3_json,
    _query_source,
    logger,
    pre_start_meta,
    table,
)

# These names have no in-file use of their own — they are the facade's re-export /
# monkeypatch surface: the split handlers read them via the `_g` hand-off (`_g["<name>"]`,
# where _g is a delegator's globals()), and tests read/patch them on this module
# (e.g. sad._query_source, sad.EXPERIMENT_START, sad.PT). Referenced so the linter counts
# them as used.
__reexport__ = (_query_source, _experiment_date, pre_start_meta, EXPERIMENT_START, _FRESHNESS_DEFAULT_STALE_HOURS, PT, habit_causality)

# ── Split handler modules — the logic lives here; delegated to at call time. Each
# handler receives this facade's globals() (`_g`) from its delegator and reads the
# injectable/monkeypatched state via `_g["<name>"]`. The helpers do NOT import this
# module, so there is no import cycle.
from web import (
    site_api_freshness as _freshness,
    site_api_fulfillment as _fulfillment,
    site_api_habits as _habits,
    site_api_ledger as _ledger,
    site_api_protocols as _protocols,
    site_api_rollups as _rollups,
)

# ── Source freshness registries (public pipeline-status feed, #392) ──────────
# Derived from the ONE canonical registry (source_registry.py). Kept on the facade
# because tests read/patch them here (sad._FRESHNESS_SOURCES, …) and the split
# freshness handlers read them back via the `_g` hand-off.
_FRESHNESS_SOURCES = public_board_sources()
_FRESHNESS_STALE_HOURS = stale_hours_overrides(_FRESHNESS_SOURCES)
_FRESHNESS_PAUSED = public_paused_sources()
_MANUAL_CAPTURE = manual_capture_sources()

# #975: the manual engagement channels (food / journal / training / habits) the
# engine derives from — read by the cockpit presence row via the `_g` hand-off.
_ENGAGEMENT_CHANNELS = engagement_channels()

# Genesis dates per cycle — the explicit record (SSM holds only the current cycle
# number). Read by the rollup handlers (cycle_compare / survival) via the `_g` hand-off;
# tests patch it here.
CYCLE_GENESES = {
    1: "2026-04-01",  # original launch (Day 1)
    2: "2026-06-01",  # first reset (ADR-077 tooling)
    3: "2026-06-08",  # baseline 311.62
    4: "2026-06-14",  # current run — Sunday-anchored routine (baseline 306.87)
    5: "2026-07-12",  # appended by restart_pipeline --close-cycle
    6: "2026-07-13",  # appended by restart_pipeline --close-cycle
    7: "2026-07-18",  # appended by restart_pipeline --close-cycle
    8: "2026-07-19",  # appended by restart_pipeline --close-cycle
    9: "2026-07-20",  # appended by restart_pipeline --close-cycle
    10: "2026-07-22",  # appended by restart_pipeline --close-cycle
}

# #1066: container cache for the training-phase registry (read by the routine handler
# via the `_g` hand-off; the routine test patches sad._load_phase_state).
_phase_state_cache = None


def _days_dark(last_update: str, now: datetime) -> int | None:
    """Whole days between a source's newest YYYY-MM-DD record and `now`, floored at
    0; None when there is no last_update. The "dark N days" figure for the public
    degraded stamp — computed, never fabricated (ADR-104)."""
    if not last_update:
        return None
    try:
        last = datetime.strptime(last_update[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
    return max(0, (now.date() - last.date()).days)


def _load_phase_state() -> dict:
    """config/training_phases.json (ADR-067): the ordered training phases + the
    current block. Canonical root config/ prefix (not the site/config mirror —
    that one is purged by experiment resets). Container-cached like the other
    S3 config reads — phase flips are manual and rare."""
    global _phase_state_cache
    if _phase_state_cache is None:
        _phase_state_cache = _load_s3_json("config/training_phases.json", "training_phases")
    return _phase_state_cache


def _experiment_catalog(exclude_ids: set, exclude_names: set) -> list:
    """experiment_library.json → display items tagged origin='library', so the page
    shows the pipeline (planned/backlog experiments) even when nothing is running."""
    S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
    out = []
    try:
        s3_client = boto3.client("s3", region_name=S3_REGION)
        obj = s3_client.get_object(Bucket=S3_BUCKET, Key="config/experiment_library.json")
        lib = json.loads(obj["Body"].read())
    except Exception as e:
        logger.warning("[experiments] library unavailable: %s", e)
        return out
    for exp in lib.get("experiments", []):
        if exp.get("id") in exclude_ids:
            continue
        if (exp.get("name") or "").strip().lower() in exclude_names:
            continue
        # library status: 'active' = promoted/ready to run → "available"; else backlog.
        shelf = "available" if exp.get("status") == "active" else "backlog"
        out.append(
            {
                "id": exp.get("id"),
                "name": exp.get("name", "Unnamed"),
                "status": shelf,
                "origin": "library",
                # Substitute the {duration} token in the library hypothesis_template (was
                # rendering literally: "16:8 fasting for {duration} days will reduce...").
                "hypothesis": (exp.get("hypothesis_template", "") or "").replace(
                    "{duration}", str(exp.get("suggested_duration_days") or "several")
                ),
                "pillar": exp.get("pillar", ""),
                "difficulty": exp.get("difficulty"),
                "evidence_tier": exp.get("evidence_tier"),
                "result_summary": exp.get("why_it_matters", "") or exp.get("description", ""),
                "planned_duration_days": exp.get("suggested_duration_days"),
                "tags": exp.get("tags", []),
                "votes": exp.get("votes", 0),
                # Source attribution: where the idea came from (published study citation +
                # first supporting evidence URL). Surfaced on the site so each experiment
                # shows its provenance rather than appearing to arrive from nowhere.
                "evidence_citation": exp.get("evidence_citation"),
                "source_url": ((exp.get("evidence_for") or [{}])[0] or {}).get("url"),
            }
        )
    # most-voted backlog first, then alphabetical
    out.sort(key=lambda x: (-(x.get("votes") or 0), x.get("name", "").lower()))
    return out


def _habits_from_habitify() -> list:
    """Latest Habitify record → [{name, group, frequency, scheduled_today}], filtered."""
    pk = f"{USER_PREFIX}habitify"
    resp = table.query(KeyConditionExpression=Key("pk").eq(pk), ScanIndexForward=False, Limit=1)
    items = _decimal_to_float(resp.get("Items", []))
    if not items:
        return []
    statuses = items[0].get("habit_statuses") or {}
    out = []
    for name, st in statuses.items():
        if _is_blocked_vice(name):
            continue
        st = st if isinstance(st, dict) else {}
        out.append(
            {
                "name": name,
                "group": st.get("group") or "Other",
                "frequency": st.get("periodicity") or "daily",
                "scheduled_today": bool(st.get("scheduled_today", True)),
            }
        )
    return out


def handle_tools_baseline() -> dict:
    """GET /api/tools_baseline — thin entrypoint; logic in rollups split module."""
    return _rollups.tools_baseline(_g=globals())


def handle_platform_stats() -> dict:
    """GET /api/platform_stats — thin entrypoint; logic in rollups split module."""
    return _rollups.platform_stats()


def handle_source_freshness() -> dict:
    """GET /api/source_freshness — thin entrypoint; logic in freshness split module."""
    return _freshness.source_freshness(_g=globals())


def handle_device_agreement() -> dict:
    """GET /api/device_agreement — thin entrypoint; logic in freshness split module."""
    return _freshness.device_agreement(_g=globals())


def handle_last_sync() -> dict:
    """GET /api/last_sync — thin entrypoint; logic in freshness split module."""
    return _freshness.last_sync(_g=globals())


def handle_presence() -> dict:
    """GET /api/presence — thin entrypoint; logic in freshness split module."""
    return _freshness.presence(_g=globals())


def handle_ledger() -> dict:
    """GET /api/ledger — thin entrypoint; logic in ledger split module."""
    return _ledger.ledger(_g=globals())


def handle_what_changed() -> dict:
    """GET /api/what_changed — thin entrypoint; logic in ledger split module."""
    return _ledger.what_changed(_g=globals())


def handle_discoveries() -> dict:
    """GET /api/discoveries — thin entrypoint; logic in ledger split module."""
    return _ledger.discoveries(_g=globals())


def handle_habit_streaks() -> dict:
    """GET /api/habit_streaks — thin entrypoint; logic in habits split module."""
    return _habits.habit_streaks(_g=globals())


def handle_experiments() -> dict:
    """GET /api/experiments — thin entrypoint; logic in protocols split module."""
    return _protocols.experiments(_g=globals())


def handle_supplements() -> dict:
    """GET /api/supplements — thin entrypoint; logic in protocols split module."""
    return _protocols.supplements(_g=globals())


def handle_routine() -> dict:
    """GET /api/routine — thin entrypoint; logic in protocols split module."""
    return _protocols.routine(_g=globals())


def handle_vice_streaks() -> dict:
    """GET /api/vice_streaks — thin entrypoint; logic in habits split module."""
    return _habits.vice_streaks(_g=globals())


def handle_character_calibration() -> dict:
    """GET /api/character_calibration — thin entrypoint; logic in fulfillment split module."""
    return _fulfillment.character_calibration(_g=globals())


def handle_fulfillment_ritual() -> dict:
    """GET /api/fulfillment_ritual — thin entrypoint; logic in fulfillment split module."""
    return _fulfillment.fulfillment_ritual(_g=globals())


def handle_fulfillment_index() -> dict:
    """GET /api/fulfillment_index — thin entrypoint; logic in fulfillment split module."""
    return _fulfillment.fulfillment_index(_g=globals())


def handle_habits() -> dict:
    """GET /api/habits — thin entrypoint; logic in habits split module."""
    return _habits.habits(_g=globals())


def handle_protocols() -> dict:
    """GET /api/protocols — thin entrypoint; logic in protocols split module."""
    return _protocols.protocols(_g=globals())


def handle_domains() -> dict:
    """GET /api/domains — thin entrypoint; logic in protocols split module."""
    return _protocols.domains()


def handle_habit_registry() -> dict:
    """GET /api/habit_registry — thin entrypoint; logic in habits split module."""
    return _habits.habit_registry(_g=globals())


def handle_changes_since(qs: dict = None) -> dict:
    """GET /api/changes-since — thin entrypoint; logic in rollups split module."""
    return _rollups.changes_since(qs, _g=globals())


def handle_observatory_week(qs: dict = None) -> dict:
    """GET /api/observatory_week — thin entrypoint; logic in rollups split module."""
    return _rollups.observatory_week(qs, _g=globals())


def handle_cycle_compare() -> dict:
    """GET /api/cycle_compare — thin entrypoint; logic in rollups split module."""
    return _rollups.cycle_compare(_g=globals())


def handle_survival() -> dict:
    """GET /api/survival — thin entrypoint; logic in rollups split module."""
    return _rollups.survival(_g=globals())
