"""
lambdas/web/site_api_vitals.py — homepage/dashboard endpoint FACADE.

Extracted from lambdas/web/site_api_lambda.py (P1.1 Phase B step 5, 2026-05-26);
grown further by #1240 when the vitals-adjacent cluster (glucose / sleep /
circadian / phenoage / labs / genome) moved here out of site_api_data.py.

#1654 (god-module breakup): at 2,559 lines this was the largest remaining
first-party module in the serving path. The handler LOGIC was split, by concern,
into cohesive sibling modules. The logic lives there; the 19 routed entrypoints
stay HERE as thin delegators, so the router bindings, `handler.__module__`, and
the test monkeypatch surface are all unchanged. No contract change.

  web/site_api_body.py       — /api/vitals, /api/weight_progress, /api/snapshot
      (the live body reading + the homepage fan-out)
  web/site_api_journey.py    — /api/journey, /api/timeline, /api/journey_timeline,
      /api/journey_waveform, /api/achievements (the progress record over time)
  web/site_api_character.py  — /api/character, /api/character_config,
      /api/character_receipt, /api/character_stats (the game layer)
  web/site_api_sleep.py      — /api/sleep_detail, /api/sleep_correlations,
      /api/circadian (the night)
  web/site_api_biomarkers.py — /api/labs, /api/glucose, /api/phenoage,
      /api/genome_risks (the measured chemistry + its privacy absolutes)

Each delegator hands its own globals() to the split handler as `_g`; the handler
reads the injectable/monkeypatched state back via `_g["<name>"]`. The split
modules do NOT import this facade, so there is no import cycle.

The `_g` surface here is wider than the observatory/intelligence slices because
this module's tests reach further into it:

  table / _query_source / _latest_item / _latest_item_asof / _latest_readiness /
  _get_profile / _experiment_date / EXPERIMENT_START / pre_start_meta /
  vitals_resolver — the standard injectables (test_vitals_frame,
  test_historical_window, test_window_name_honesty_1917, test_honest_read_guards_1084,
  test_pre_start_contract_sweep, test_character_not_instrumented, …).

  datetime — test_home_og_day_frame_1955 freezes the MODULE'S datetime class to pin
  the PT day index. Every split handler that reads the clock takes `datetime` from
  `_g`, so the freeze still reaches it.

  handle_vitals / handle_journey / handle_character — test_pre_start_countdown stubs
  these three on the facade and then calls handle_snapshot. Snapshot's fan-out
  therefore goes back through `_g` to the facade delegators (and so to the stubs)
  instead of binding the real functions at import time.

Source-text guards that used to read this one file now scan the whole family
(test_public_genetic_privacy_absolute, test_night_of_frame_1923,
test_achievement_first_earn_1624, test_pt_date_anchor_guard_1937,
test_genesis_blind_digest_and_readers_2150, test_character_targets_1412,
test_vitals_frame, test_gradability_liveness_cross_phase_2023) — guard the SET,
not the instance, so they keep biting after this split and the next one.
"""

# `datetime` is imported here for ONE reason: test_home_og_day_frame_1955 replaces
# this binding with a frozen class, and every split handler that reads the clock
# takes it back off `_g`. Do not remove it because nothing in this file calls it.
from datetime import datetime

import boto3  # noqa: F401 — `vitals.boto3` is the stub point test_labs_privacy patches client() on

# ── Split logic modules — the handler bodies live here; delegated to at call time. ──
from web import (
    site_api_biomarkers as _bio,
    site_api_body as _body,
    site_api_character as _character,
    site_api_journey as _journey,
    site_api_sleep as _sleep,
    vitals_resolver,  # #1369: the ONE current-vitals truth
)

# ── Re-exports for tests that read these FROM this module. `_latest_readiness` is
# also a genuine PATCH point (test_pre_start_countdown stubs it, then calls
# handle_snapshot) — snapshot reads it back via `_g`, so the patch lands.
from web.site_api_biomarkers import (  # noqa: F401 — re-export surface
    _GENETIC_CATEGORY_RE,
    _GENETIC_TEXT_RE,
    _strip_genetic_biomarkers,
)
from web.site_api_body import _MIN_AVG_N  # noqa: F401 — re-export surface

# ── Monkeypatch/injection surface — kept on the facade so `monkeypatch.setattr(vitals, …)`
# still lands here and the delegators can hand these to the split handlers via `_g`.
from web.site_api_common import (
    EXPERIMENT_START,
    USER_PREFIX,
    _experiment_date,
    _get_profile,
    _latest_item,
    _latest_item_asof,
    _query_source,
    pre_start_meta,
    table,
)

# These names have no direct in-file reference of their own — they are the facade's
# monkeypatch/hand-off surface: the split handlers read them via `_g` (`_g["<name>"]`,
# where `_g` is a delegator's globals()), and tests read/patch them on this module.
# Referenced here so the linter counts them as used.
__facade_state__ = (
    table,
    _query_source,
    _latest_item,
    _latest_item_asof,
    _get_profile,
    _experiment_date,
    EXPERIMENT_START,
    pre_start_meta,
    vitals_resolver,
    datetime,
    USER_PREFIX,
    _MIN_AVG_N,
    boto3,
)


def _latest_readiness() -> dict | None:
    """The stored readiness components — delegated to web.site_api_body.

    A WRAPPER, not a re-export: the split implementation takes `_g`, and this is a
    genuine patch point (test_pre_start_countdown stubs it on the facade, then calls
    handle_snapshot — which reads it back through `_g`, so the stub lands). Callers
    outside the facade (test_data_truth_batch) keep the original zero-arg signature.
    """
    return _body._latest_readiness(_g=globals())


# ── Thin routed delegators — identical name/signature/__module__ to the pre-split
# handlers; each hands its own globals() to the split handler as `_g`. ──────────────
def handle_vitals(date: str | None = None) -> dict:
    """GET /api/vitals — delegated to web.site_api_body."""
    return _body.vitals(date, _g=globals())


def handle_weight_progress() -> dict:
    """GET /api/weight_progress — delegated to web.site_api_body."""
    return _body.weight_progress(_g=globals())


def handle_snapshot() -> dict:
    """GET /api/snapshot — delegated to web.site_api_body."""
    return _body.snapshot(_g=globals())


def handle_journey() -> dict:
    """GET /api/journey — delegated to web.site_api_journey."""
    return _journey.journey(_g=globals())


def handle_timeline() -> dict:
    """GET /api/timeline — delegated to web.site_api_journey."""
    return _journey.timeline(_g=globals())


def handle_journey_timeline() -> dict:
    """GET /api/journey_timeline — delegated to web.site_api_journey."""
    return _journey.journey_timeline(_g=globals())


def handle_journey_waveform() -> dict:
    """GET /api/journey_waveform — delegated to web.site_api_journey."""
    return _journey.journey_waveform(_g=globals())


def handle_achievements() -> dict:
    """GET /api/achievements — delegated to web.site_api_journey."""
    return _journey.achievements(_g=globals())


def handle_character(date: str | None = None) -> dict:
    """GET /api/character — delegated to web.site_api_character."""
    return _character.character(date, _g=globals())


def handle_character_config() -> dict:
    """GET /api/character_config — delegated to web.site_api_character."""
    return _character.character_config(_g=globals())


def handle_character_receipt(date: str | None = None, verify: bool = False) -> dict:
    """GET /api/character_receipt — delegated to web.site_api_character."""
    return _character.character_receipt(date, verify, _g=globals())


def handle_character_stats() -> dict:
    """GET /api/character_stats — delegated to web.site_api_character."""
    return _character.character_stats(_g=globals())


def handle_sleep_detail() -> dict:
    """GET /api/sleep_detail — delegated to web.site_api_sleep."""
    return _sleep.sleep_detail(_g=globals())


def handle_sleep_correlations() -> dict:
    """GET /api/sleep_correlations — delegated to web.site_api_sleep."""
    return _sleep.sleep_correlations(_g=globals())


def handle_circadian() -> dict:
    """GET /api/circadian — delegated to web.site_api_sleep."""
    return _sleep.circadian(_g=globals())


def handle_glucose() -> dict:
    """GET /api/glucose — delegated to web.site_api_biomarkers."""
    return _bio.glucose(_g=globals())


def handle_phenoage() -> dict:
    """GET /api/phenoage — delegated to web.site_api_biomarkers."""
    return _bio.phenoage(_g=globals())


def handle_genome_risks() -> dict:
    """GET /api/genome_risks — delegated to web.site_api_biomarkers."""
    return _bio.genome_risks(_g=globals())


def handle_labs() -> dict:
    """GET /api/labs — delegated to web.site_api_biomarkers."""
    return _bio.labs()
