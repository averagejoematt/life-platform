"""
lambdas/web/site_api_coach.py — coach intelligence + miscellaneous endpoint FACADE.

Extracted from lambdas/web/site_api_lambda.py (P1.1 Phase B extension, 2026-05-27).

These were previously inline `if path == "/api/X":` blocks at the bottom
of lambda_handler. Each block did custom query-param parsing + DDB lookup,
so they didn't fit the ROUTES dispatch pattern (which calls handlers
with no args). Now they're proper functions taking event, callable from
the dispatcher as `return handle_X(event)`.

#1654 (god-module breakup): at 2,664 lines this was the largest remaining module
in the serving path. The handler LOGIC was split, by concern, into cohesive sibling
modules. The logic lives there; the 19 routed entrypoints stay HERE as thin
delegators, so the router bindings, `handler.__module__`, and the test monkeypatch
surface are all unchanged. No contract change.

  web/site_api_coach_profile.py   — /api/coaches, /api/coach/{persona_id}
      (who each coach IS: registry, authored character, report card, #1387 dossier)
  web/site_api_coach_stance.py    — /api/coach_team
      (what they think RIGHT NOW: STANCE#latest, the ladder scaffold, held-since,
      the integrator digest, tensions, the live dispute)
  web/site_api_coach_ledger.py    — /api/calibration, /api/predictions,
      /api/coach_docket, /api/panel_ledger, /api/voice_fidelity
      (calls with skin in the game, and how they turned out — one PREDICTION#/CALIB#
      fetch spine so season stays a derived subset of career, #1376/#1527/#2063)
  web/site_api_coach_narrative.py — /api/coach_analysis, /api/ai_analysis,
      /api/coach_timeline, /api/recap, /api/experiment_synthesis,
      /api/weekly_priority, /api/month_rollup
      (guarded reads of pre-computed prose: the staleness refusal + the #802
      regeneration-paused disclosure are what make these one concern)
  web/site_api_thirdwall.py       — /api/field_notes, /api/decisions,
      /api/journal_quotes, /api/diary_reactions
      (the human voice on the record, all four screened all-or-nothing through the
      one `_public_decision_note` rule — #1568/#1569/#1675)

Endpoints:
  /api/coach_docket     — the Dispute Docket (#1386): open positions with frozen stakes + resolved history
  /api/field_notes      — weekly Field Notes (optional ?week= param)
  /api/decisions        — logged decisions carrying a verbatim note (#1569, the widened Third Wall)
  /api/journal_quotes   — consent-per-line verbatim journal pull-quotes (#1568, ADR-142)
  /api/ai_analysis      — cached AI expert analysis (?expert= param)
  /api/coach_analysis   — coach intelligence dashboard (?domain= param)
  /api/predictions      — coach prediction ledger (?status=&coach_id=&limit=)
  /api/coach_timeline   — coach thread timeline (?coach_id= param)
  /api/weekly_priority  — integrator synthesis (cross-domain weekly priority)
  /api/month_rollup     — integrator month rollup (trailing ~4 weeks, #1115)

How the split preserves the monkeypatch surface
-----------------------------------------------
Each delegator hands its own globals() to the split handler as `_g`; the handler
reads the injectable/monkeypatched state back via `_g["<name>"]`. The split modules
do NOT import this facade, so there is no import cycle.

`_g` is wide here because this module's suite reaches deep into it. `table` alone is
monkeypatched in 13 test files; `EXPERIMENT_START` is repointed by
test_pre_start_contract_sweep's genesis sweep; `_load_s3_json`, `_parallel_fetch`,
`_current_cycle`, `_current_day_n`, `_integrator_digest`, `_regeneration_paused` and
`_stance_latest` are each stubbed by name and then reached through a handler that
calls them. Every one of those fan-outs goes back through `_g` to THIS module, so
the stubs land exactly as they did pre-split.

For the same reason the cross-seam helpers below are WRAPPERS, not re-exports: a
re-export is not a patch point (#2192's lesson). `_stance_block` is called by the
coach page in `_profile` and by the team view in `_stance`; both reach it through
`_g`, so `monkeypatch.setattr(site_api_coach, "_stance_latest", …)` still changes
what `_stance_block` sees. Only genuinely pure helpers (`_reader_reason`,
`_stance_from_latest`, `_public_decision_note`, `_regeneration_paused`,
`_current_cycle`, `_parallel_fetch`) are plain re-exports — they read no facade
state, so a re-export and a wrapper are the same object either way.

Source-text/AST guards that used to read this ONE file now scan the whole family via
tests/site_api_family.py — #1841's public-surface privacy absolute (no public read of
the on-tape claims partition), #726's canonical-prediction-store pin, #1986's
byline-fallback pin, #1675's serve/render field pair. Guard the SET, not the instance,
so they keep biting after this split and the next one.
"""

import os

# `datetime` is imported here for ONE reason: it is the facade's clock hand-off —
# every split handler that reads the wall clock takes it back off `_g`, so freezing
# this binding still reaches them. Do not remove it because nothing here calls it.
from datetime import datetime

import boto3
from experiment.phase_filter import singleton_visible, with_phase_filter  # noqa: F401 — re-export surface (#946/ADR-058)

# ── CC-00/CC-09 modules — bundled into the site-api code package like every other
# lambdas/ module (#781: one bundle, no separate layer, so there's no deploy-race
# window for these to lag behind). Imported defensively anyway so a corrupted or
# partial deploy can't break the whole handler — the coaches endpoints just serve
# shaped-empty 200s if these modules are ever unavailable.
try:
    from coach import coach_stance, persona_registry

    _COACH_MODULES = True
except Exception:  # pragma: no cover - defensive guard, not expected in practice post-#781
    coach_stance = None
    persona_registry = None
    _COACH_MODULES = False

# ── Split logic modules — the handler bodies live here; delegated to at call time. ──
from web import (
    site_api_coach_ledger as _ledger,
    site_api_coach_narrative as _narrative,
    site_api_coach_profile as _profile,
    site_api_coach_stance as _stance,
    site_api_thirdwall as _thirdwall,
)

# ── Re-exports: constants tests read off this module, plus the PURE helpers (they
# read no facade state, so a re-export IS the patch point — see the module docstring).
from web.site_api_coach_ledger import (  # noqa: F401 — re-export surface
    _CALIB_COACH_ID_MAP,
    _CALIB_COACH_NAMES,
    _DOCKET_MAX_PAGES,
    _MAX_QUERY_PAGES,
    _PREDICTION_PROJECTION_FIELDS,
    DOCKET_OPEN_LIMIT,
    DOCKET_RESOLVED_LIMIT,
    _current_cycle,
    _parallel_fetch,
)
from web.site_api_coach_narrative import _regeneration_paused  # noqa: F401 — re-export surface
from web.site_api_coach_profile import _DISCLOSURE, _LEAD_FALLBACK, _reader_reason  # noqa: F401 — re-export surface
from web.site_api_coach_stance import _stance_from_latest  # noqa: F401 — re-export surface

# ── Monkeypatch/injection surface — kept on the facade so `monkeypatch.setattr(coach, …)`
# still lands here and the delegators can hand these to the split handlers via `_g`.
from web.site_api_common import (
    EXPERIMENT_START,
    PT,
    USER_PREFIX,
    _decimal_to_float,
    _error,
    _load_s3_json,
    _ok,
    _scrub_blocked_terms,
    logger,
    pre_start_meta,
    prereg_seal_meta,
    table,
)
from web.site_api_thirdwall import _public_decision_note  # noqa: F401 — re-export surface (imported by site_api_diary)

try:
    from common.constants import EXPERIMENT_BASELINE_WEIGHT_LBS
except Exception:  # pragma: no cover - constants.py ships in every bundle (#781); defensive only
    EXPERIMENT_BASELINE_WEIGHT_LBS = 306.87

# ── CC-00/01/02/09 — Coaches-as-Characters surfacing ─────────────────────────
_S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
_S3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-2"))

# These names have no direct in-file reference of their own — they are the facade's
# monkeypatch/hand-off surface: the split handlers read them via `_g` (`_g["<name>"]`,
# where `_g` is a delegator's globals()), and tests read/patch them on this module.
# Referenced here so the linter counts them as used.
__facade_state__ = (
    table,
    EXPERIMENT_START,
    EXPERIMENT_BASELINE_WEIGHT_LBS,
    USER_PREFIX,
    PT,
    _load_s3_json,
    _decimal_to_float,
    _error,
    _ok,
    _scrub_blocked_terms,
    logger,
    pre_start_meta,
    prereg_seal_meta,
    datetime,
    persona_registry,
    coach_stance,
    _COACH_MODULES,
    _S3,
    _S3_BUCKET,
)


# ── Helper wrappers — the pre-split signatures, kept so every caller and every
#    `monkeypatch.setattr(site_api_coach, …)` in the suite lands unchanged. Each
#    hands this module's globals() to the sibling as `_g`. ─────────────────────


def _registry():
    """Delegated to web.site_api_coach_profile._registry."""
    return _profile._registry(_g=globals())


def _lead_byline():
    """Delegated to web.site_api_coach_profile._lead_byline."""
    return _profile._lead_byline(_g=globals())


def _latest_weight_lbs():
    """Delegated to web.site_api_coach_profile._latest_weight_lbs."""
    return _profile._latest_weight_lbs(_g=globals())


def _track_record(coach_id):
    """Delegated to web.site_api_coach_profile._track_record."""
    return _profile._track_record(coach_id, _g=globals())


def _conversation_references(coach_id, limit=5):
    """Delegated to web.site_api_coach_profile._conversation_references."""
    return _profile._conversation_references(coach_id, limit, _g=globals())


def _quality_trend(coach_id):
    """Delegated to web.site_api_coach_profile._quality_trend."""
    return _profile._quality_trend(coach_id, _g=globals())


def _tuning_log_for(coach_id):
    """Delegated to web.site_api_coach_profile._tuning_log_for."""
    return _profile._tuning_log_for(coach_id, _g=globals())


def _voice_subset(coach_config_key):
    """Delegated to web.site_api_coach_profile._voice_subset."""
    return _profile._voice_subset(coach_config_key, _g=globals())


def _relationships(coach_id):
    """Delegated to web.site_api_coach_profile._relationships."""
    return _profile._relationships(coach_id, _g=globals())


def _character(p):
    """Delegated to web.site_api_coach_profile._character."""
    return _profile._character(p, _g=globals())


def _working_hypotheses(coach_id, limit=6):
    """Delegated to web.site_api_coach_profile._working_hypotheses."""
    return _profile._working_hypotheses(coach_id, limit, _g=globals())


def _coach_daily(coach_id):
    """Delegated to web.site_api_coach_profile._coach_daily."""
    return _profile._coach_daily(coach_id, _g=globals())


def _coach_memoir(coach_id):
    """Delegated to web.site_api_coach_profile._coach_memoir."""
    return _profile._coach_memoir(coach_id, _g=globals())


def _recent_outputs(coach_id, limit=25):
    """Delegated to web.site_api_coach_profile._recent_outputs."""
    return _profile._recent_outputs(coach_id, limit, _g=globals())


def _dossier_block(coach_id):
    """Delegated to web.site_api_coach_profile._dossier_block."""
    return _profile._dossier_block(coach_id, _g=globals())


def _stance_latest(coach_id):
    """Delegated to web.site_api_coach_stance._stance_latest."""
    return _stance._stance_latest(coach_id, _g=globals())


def _stance_history(coach_id, limit=8):
    """Delegated to web.site_api_coach_stance._stance_history."""
    return _stance._stance_history(coach_id, limit, _g=globals())


def _stance_held_since(coach_id, current_stage_label):
    """Delegated to web.site_api_coach_stance._stance_held_since."""
    return _stance._stance_held_since(coach_id, current_stage_label, _g=globals())


def _stance_block(coach_id, weight_lbs):
    """Delegated to web.site_api_coach_stance._stance_block."""
    return _stance._stance_block(coach_id, weight_lbs, _g=globals())


def _integrator_digest():
    """Delegated to web.site_api_coach_stance._integrator_digest."""
    return _stance._integrator_digest(_g=globals())


def _latest_cycle_digest():
    """Delegated to web.site_api_coach_stance._latest_cycle_digest."""
    return _stance._latest_cycle_digest(_g=globals())


def _latest_dispute():
    """Delegated to web.site_api_coach_stance._latest_dispute."""
    return _stance._latest_dispute(_g=globals())


def _team_tensions():
    """Delegated to web.site_api_coach_stance._team_tensions."""
    return _stance._team_tensions(_g=globals())


def _lead_block(team_focus):
    """Delegated to web.site_api_coach_stance._lead_block."""
    return _stance._lead_block(team_focus, _g=globals())


def _docket_rows(prefix, limit, newest_first):
    """Delegated to web.site_api_coach_ledger._docket_rows."""
    return _ledger._docket_rows(prefix, limit, newest_first, _g=globals())


def _query_partition(pk, sk_prefix, projection_fields=None, paginate=False):
    """Delegated to web.site_api_coach_ledger._query_partition."""
    return _ledger._query_partition(pk, sk_prefix, projection_fields, paginate, _g=globals())


def _fetch_prediction_partition(coach_pk):
    """Delegated to web.site_api_coach_ledger._fetch_prediction_partition."""
    return _ledger._fetch_prediction_partition(coach_pk, _g=globals())


def _prefetch_calibration_partitions(cids):
    """Delegated to web.site_api_coach_ledger._prefetch_calibration_partitions."""
    return _ledger._prefetch_calibration_partitions(cids, _g=globals())


def _score_coach_calibration(cid, records=None):
    """Delegated to web.site_api_coach_ledger._score_coach_calibration."""
    return _ledger._score_coach_calibration(cid, records, _g=globals())


def _current_day_n() -> int:
    """Delegated to web.site_api_coach_narrative._current_day_n."""
    return _narrative._current_day_n(_g=globals())


# ── Thin routed delegators — identical name/signature/__module__ to the pre-split
#    handlers; each hands its own globals() to the split handler as `_g`. ───────


def handle_ai_analysis(event):
    """GET /api/ai_analysis — delegated to web.site_api_coach_narrative."""
    return _narrative.handle_ai_analysis(event, _g=globals())


def handle_calibration(event):
    """GET /api/calibration — delegated to web.site_api_coach_ledger."""
    return _ledger.handle_calibration(event, _g=globals())


def handle_coach(event):
    """GET /api/coach/{persona_id} — delegated to web.site_api_coach_profile."""
    return _profile.handle_coach(event, _g=globals())


def handle_coach_analysis(event):
    """GET /api/coach_analysis — delegated to web.site_api_coach_narrative."""
    return _narrative.handle_coach_analysis(event, _g=globals())


def handle_coach_docket(event):
    """GET /api/coach_docket — delegated to web.site_api_coach_ledger."""
    return _ledger.handle_coach_docket(event, _g=globals())


def handle_coach_team(event):
    """GET /api/coach_team — delegated to web.site_api_coach_stance."""
    return _stance.handle_coach_team(event, _g=globals())


def handle_coach_timeline(event):
    """GET /api/coach_timeline — delegated to web.site_api_coach_narrative."""
    return _narrative.handle_coach_timeline(event, _g=globals())


def handle_coaches(event):
    """GET /api/coaches — delegated to web.site_api_coach_profile."""
    return _profile.handle_coaches(event, _g=globals())


def handle_decisions(event):
    """GET /api/decisions — delegated to web.site_api_thirdwall."""
    return _thirdwall.handle_decisions(event, _g=globals())


def handle_diary_reactions(event):
    """GET /api/diary_reactions — delegated to web.site_api_thirdwall."""
    return _thirdwall.handle_diary_reactions(event, _g=globals())


def handle_experiment_synthesis():
    """GET /api/experiment_synthesis — delegated to web.site_api_coach_narrative."""
    return _narrative.handle_experiment_synthesis(_g=globals())


def handle_field_notes(event):
    """GET /api/field_notes — delegated to web.site_api_thirdwall."""
    return _thirdwall.handle_field_notes(event, _g=globals())


def handle_journal_quotes(event):
    """GET /api/journal_quotes — delegated to web.site_api_thirdwall."""
    return _thirdwall.handle_journal_quotes(event, _g=globals())


def handle_month_rollup():
    """GET /api/month_rollup — delegated to web.site_api_coach_narrative."""
    return _narrative.handle_month_rollup(_g=globals())


def handle_panel_ledger(event):
    """GET /api/panel_ledger — delegated to web.site_api_coach_ledger."""
    return _ledger.handle_panel_ledger(event, _g=globals())


def handle_predictions(event):
    """GET /api/predictions — delegated to web.site_api_coach_ledger."""
    return _ledger.handle_predictions(event, _g=globals())


def handle_recap():
    """GET /api/recap — delegated to web.site_api_coach_narrative."""
    return _narrative.handle_recap(_g=globals())


def handle_voice_fidelity(event):
    """GET /api/voice_fidelity — delegated to web.site_api_coach_ledger."""
    return _ledger.handle_voice_fidelity(event, _g=globals())


def handle_weekly_priority(event):
    """GET /api/weekly_priority — delegated to web.site_api_coach_narrative."""
    return _narrative.handle_weekly_priority(event, _g=globals())
