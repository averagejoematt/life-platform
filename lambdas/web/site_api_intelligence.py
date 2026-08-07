"""
lambdas/web/site_api_intelligence.py — intelligence-surface endpoint FACADE.

Extracted from lambdas/web/site_api_lambda.py (P1.1 Phase B step 3, 2026-05-26);
grown further by #1240 when the intelligence-adjacent cluster moved here out of
site_api_data.py.

#1654 (god-module breakup, the 4th and last named target — the one held in the
2026-07-25 comment until #1656's mypy work settled): the handler LOGIC was split,
by concern, into cohesive sibling modules. The logic lives there; the routed
entrypoints stay HERE as thin delegators, so the router bindings, every
`handler.__module__ == "web.site_api_intelligence"` assertion in
tests/test_site_api_data_split.py, and the test monkeypatch surface are all
unchanged.

  web/site_api_status.py    — /api/status, /api/status/summary (the active
      pipeline probe, per-source freshness, component rollup, one traffic light)
      + the response cache those two share
  web/site_api_pulse.py     — /api/pulse, /api/pulse_history
  web/site_api_discovery.py — /api/hypotheses, /api/intelligence_summary,
      /api/pillar_coupling, /api/correlations (the statistical-discovery surface)
  web/site_api_foresight.py — /api/forecast, /api/scenarios,
      /api/state_of_matthew, /api/wrong (predictions and their public reckoning)
  web/site_api_budget.py    — /api/inference_receipt, /api/receipts, and the
      /api/status cost block (the AI-spend envelope, from the governor's numbers)

Each delegator hands its own globals() to the split handler as `_g`; the handler
reads the injectable/monkeypatched state (table / _query_source / _latest_item /
_get_profile / EXPERIMENT_START / resolve_vitals / pre_start_meta /
_budget_cost_block) back via `_g["<name>"]`. The split modules do NOT import this
facade, so there is no import cycle.

site_api_budget's two handlers are the one exception: nothing in that module
reads injectable state, so they take no `_g`. Its only substitutable dependency
is `boto3.client`, and the tests that stub it patch the attribute on the shared
boto3 *module object* (`sai.boto3` is that same object) rather than on a
module-level binding — so it reaches the split code either way. `import boto3`
therefore stays on this facade.

Tests that patch `intel.table` / `intel._latest_item` / `intel._get_profile` /
`intel.EXPERIMENT_START` / `intel.resolve_vitals` and then call `intel.handle_*`
keep working unchanged; tests that read `sai._budget_cost_block` /
`sai._BUDGET_TIER_STATUS` / `sai._TIER_SEMANTICS` / `sai._ADR133_BASE_CEILING_USD`
/ `sai._BREAKDOWN_MAX_AGE_S` / `sai._BEDROCK_PRICES` / `sai._AI_SAFETY_BUFFER` /
`sad._price_for_model` read them through the re-exports below.
"""

import boto3  # noqa: F401 — `sai.boto3` is the stub point tests patch client() on

# ── Split logic modules — the handler bodies live here; delegated to at call time. ──
from web import (
    site_api_budget as _budget,
    site_api_discovery as _discovery,
    site_api_foresight as _foresight,
    site_api_pulse as _pulse,
    site_api_status as _status,
)

# ── Re-exports for tests/callers that read these budget constants + helpers FROM this
# module (test_status_cost_honesty, test_receipts_endpoint, test_inference_receipt_ceiling).
from web.site_api_budget import (  # noqa: F401 — re-export surface
    _ADR133_BASE_CEILING_USD,
    _AI_SAFETY_BUFFER,
    _BEDROCK_PRICES,
    _BREAKDOWN_MAX_AGE_S,
    _BUDGET_TIER_STATUS,
    _TIER_SEMANTICS,
    _budget_cost_block,
    _price_for_model,
)

# ── Monkeypatch/injection surface — kept on the facade so `monkeypatch.setattr(intel, …)`
# still lands here and the delegators can hand these to the split handlers via `_g`.
from web.site_api_common import (
    EXPERIMENT_START,
    _get_profile,
    _latest_item,
    _query_source,
    pre_start_meta,
    table,
)

# ── Re-exports for tests that READ these private helpers/constants FROM this module
# (test_experiment_gates::test_coupling_floor_uses_registry reads `_COUPLING_MIN_N`;
# test_wrong_feed_1377::test_no_llm_in_the_path runs inspect.getsource on
# `_wrong_obituary`). A re-export is not a patch point — but both of these are read,
# never patched, so the binding is enough and the assertions still bite the real
# definition in the owning module.
from web.site_api_discovery import _COUPLING_MIN_N  # noqa: F401 — re-export surface
from web.site_api_foresight import _wrong_obituary  # noqa: F401 — re-export surface
from web.vitals_resolver import resolve_vitals  # #1369: the ONE current-vitals truth

# These names have no direct in-file reference of their own — they are the facade's
# monkeypatch/hand-off surface: the split handlers read them via `_g` (`_g["<name>"]`,
# where `_g` is a delegator's globals()), and tests read/patch them on this module.
# Referenced here so the linter counts them as used.
__facade_state__ = (
    table,
    _query_source,
    _latest_item,
    _get_profile,
    EXPERIMENT_START,
    resolve_vitals,
    pre_start_meta,
    _budget_cost_block,
)


# ── Thin routed delegators — identical name/signature/__module__ to the pre-split
# handlers; each hands its own globals() to the split handler as `_g`. ──────────────
def handle_status() -> dict:
    """GET /api/status — delegated to web.site_api_status."""
    return _status.status(_g=globals())


def handle_status_summary() -> dict:
    """GET /api/status/summary — delegated to web.site_api_status."""
    return _status.status_summary(_g=globals())


def handle_pulse() -> dict:
    """GET /api/pulse — delegated to web.site_api_pulse."""
    return _pulse.pulse(_g=globals())


def handle_pulse_history() -> dict:
    """GET /api/pulse_history — delegated to web.site_api_pulse."""
    return _pulse.pulse_history(_g=globals())


def handle_hypotheses() -> dict:
    """GET /api/hypotheses — delegated to web.site_api_discovery."""
    return _discovery.hypotheses(_g=globals())


def handle_intelligence_summary() -> dict:
    """GET /api/intelligence_summary — delegated to web.site_api_discovery."""
    return _discovery.intelligence_summary(_g=globals())


def handle_pillar_coupling() -> dict:
    """GET /api/pillar_coupling — delegated to web.site_api_discovery."""
    return _discovery.pillar_coupling(_g=globals())


def handle_correlations(event: dict = None) -> dict:
    """GET /api/correlations — delegated to web.site_api_discovery."""
    return _discovery.correlations(event, _g=globals())


def handle_forecast() -> dict:
    """GET /api/forecast — delegated to web.site_api_foresight."""
    return _foresight.forecast(_g=globals())


def handle_scenarios() -> dict:
    """GET /api/scenarios — delegated to web.site_api_foresight."""
    return _foresight.scenarios(_g=globals())


def handle_state_of_matthew() -> dict:
    """GET /api/state_of_matthew — delegated to web.site_api_foresight."""
    return _foresight.state_of_matthew(_g=globals())


def handle_wrong() -> dict:
    """GET /api/wrong — delegated to web.site_api_foresight."""
    return _foresight.wrong(_g=globals())


def handle_inference_receipt() -> dict:
    """GET /api/inference_receipt — delegated to web.site_api_budget."""
    return _budget.inference_receipt()


def handle_receipts() -> dict:
    """GET /api/receipts — delegated to web.site_api_budget."""
    return _budget.receipts()
