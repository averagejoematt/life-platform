"""The public-input forecast stream's identity and switches (#6156; owner requirements 2026-11-21).

WHAT IT IS. A narrow stream of one or two deterministic forecasts a week, written by THE PLATFORM'S FORECAST RULE (a
named, versioned statistical rule — never a coach, never a language model), from the values the public Site API
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
#: Who made the call, in the machine voice a page prints. Never a coach name.
AUTHOR_ID = "forecast_rule"
AUTHOR_WORDS = "The platform's forecast rule"
DARK_REASON = "public_forecast_dark"


def is_forecast_partition(pk) -> bool:
    return str(pk or "") == FORECAST_PK


def run_sk(cycle: str) -> str:
    return f"{RUN_SK_PREFIX}{cycle}"
