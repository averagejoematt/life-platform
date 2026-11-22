"""The public-input forecast stream's identity and switches (#6156; owner requirements 2026-11-21).

WHAT IT IS. A narrow stream of deterministic forecasts — one a week in the pilot (``FORECASTS_PER_CYCLE``) — each a
**rules-based platform forecast** (a named, versioned statistical rule — never a coach, never a language model), from the values the public Site API
already serves, so readers have a prospective call to make their own call beside (#6114). The producer is
``coach.public_forecast``; this module is the part every reader of the rows needs without importing it.

WHERE THE ROWS LIVE. ``USER#matthew#SOURCE#public_forecast`` / ``PREDICTION#<id>`` — the #1841 diary-claims pattern:
the canonical ``PREDICTION#`` record shape in a partition of its own with ``coach_id = ""``, so

  * the ONE grader (``coach.coach_prediction_evaluator``) grades it by scanning one more partition — same code, same
    statuses, same frozen-spec rules, and the "nothing changes" comparison stamped at grading (``coach.coach_baseline``);
  * it is in NO coach's record: every coach record, scoreboard, calibration headline and ``/api/ledger_export`` reads
    ``COACH#<coach>`` partitions only, and the grader writes no ``CONFIDENCE#`` or ``LEARNING#`` row for an empty
    ``coach_id`` — so a forecast can never enter the coaches-versus-guess calibration sample.

THE SWITCHES (both default off):
  * ``STREAM_LIVE`` — committed. False: nothing is filed, and ``common.prediction_publication`` classifies every row of
    this partition PRIVATE (``public_forecast_dark``) — graded, kept, served nowhere.
  * ``coach.public_forecast.SWITCH_PARAM`` — the runtime kill switch, SSM ``/life-platform/public-forecast``, read by the
    producer before filing (a literal there, so the grant lockstep can check it); only the value ``on`` files.
    An absent, unreadable or other value is OFF (fail closed). The parameter is NOT created by this change.
A forecast is filed only when BOTH say on; a filed forecast is published only while ``STREAM_LIVE`` is on, and then
only through the existing structural rule (it is graded on a public metric).
"""

from __future__ import annotations

#: The committed switch. Turning it on is the owner's act (one reviewed line); tests/test_public_forecast_6156.py pins it.
STREAM_LIVE = False

USER_ID = "matthew"
SOURCE_NAME = "public_forecast"
FORECAST_PK = f"USER#{USER_ID}#SOURCE#{SOURCE_NAME}"
SK_PREFIX = "PREDICTION#"
RUN_SK_PREFIX = "RUN#"  # one stamp per cycle — the dead-man's input (operational.public_brief_qa)
#: ``PREDICTION#.source`` of every forecast row.
FORECAST_SOURCE = "public_forecast"
#: Who made the call, in the machine voice a page prints. Never a coach name (owner ruling 2026-11-22 §5: label it
#: accurately as a **rules-based platform forecast** — a deterministic public-data rule, not an AI coach).
AUTHOR_ID = "forecast_rule"
LABEL = "rules-based platform forecast"
AUTHOR_WORDS = "Rules-based platform forecast"
#: The record this row belongs to: its own — never a coach's record, never the coaches-versus-guess sample, never a
#: calibration total. The "nothing changes" guess graded beside it keeps its own rule id (``coach_baseline.RULE_ID``).
RECORD = "platform_forecast"
DARK_REASON = "public_forecast_dark"

#: The pilot (owner ruling 2026-11-22 §5: "a limited one-forecast-per-week pilot"): forecasts filed per weekly cycle.
#: Weight only; the alternating recovery/sleep rule stays in the registry but is not filed while this is 1.
FORECASTS_PER_CYCLE = 1

#: THE FROZEN EVALUATION RULE for this partition (owner ruling 2026-11-22 §5 "Scoring"; chosen before the first live
#: forecast and never tuned against outcomes). A forecast is RIGHT when its number lands strictly closer to the graded
#: reading than the "nothing changes" guess does (the last reading before filing); a tie goes to the guess, because the
#: rule has to beat doing nothing. It has no tolerance to tune. The ±1 SD band coach number calls are graded with is
#: NOT used here: ``scripts/public_forecast_backtest.py`` showed it cannot tell this rule from the guess. The grading
#: of existing coach calls and historical rows is unchanged — the grader applies this only to a spec carrying
#: ``scoring == SCORING_RULE``, which only this partition's producer writes.
SCORING_RULE = "closer_than_nothing_changes"
SCORING_VERSION = 1
SCORING_WORDS = (
    "right when the forecast lands closer to the reading on the target day than a guess that nothing changes (the last "
    "reading before the forecast was made); a tie counts for the guess"
)

#: The reader-call door's item id for a forecast is ``<READER_SHORT>:<prediction id>`` (#6170). Never a coach's short id
#: (tests/test_public_forecast_reader_6170.py pins that no coach is named this).
READER_SHORT = "forecast"


def is_forecast_partition(pk) -> bool:
    return str(pk or "") == FORECAST_PK


def run_sk(cycle: str) -> str:
    return f"{RUN_SK_PREFIX}{cycle}"
