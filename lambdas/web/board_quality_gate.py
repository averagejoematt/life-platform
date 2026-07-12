"""
board_quality_gate.py — #968: the ADR-108 coach quality gate on the public board.

The coach-voiced board answers (/api/board_ask initial ask + follow-up turns in
site_api_ai_lambda) run the SAME coach-quality-gate lambda the daily brief
enforces (ADR-108: anti-pattern phrases, decision-class ceiling, voice
distinctiveness, cross-coach similarity — measured 10.2% real-failure rate on
daily outputs), reusing `ai_calls._invoke_quality_gate_sync` +
`_quality_gate_correction_note` so there is ONE payload shape and ONE
correction-note dialect platform-wide.

Disposition differs from the brief BY DESIGN: the brief holds a failing draft
(nothing publishes that cycle); here a reader is synchronously waiting, so the
gate is evaluate-then-regenerate-once under a HARD TIME BUDGET and FAILS OPEN —
a fired verdict that can't be corrected in budget is served anyway (logged +
`BoardQualityGateFired` CloudWatch metric + eval retention), never a
reader-facing timeout or a second refusal class. Rationale: the factual
fabrication class is already fail-closed upstream (the ADR-104 grounding gate);
this gate protects voice fidelity, and an off-voice-but-grounded answer beats
no answer. Budget tiers: both board handlers early-return via
`_ai_paused_response()` before any generation, so this gate (downstream of
generation) is structurally inside the same budget gating.

The time budget derives from the REAL Lambda deadline
(`context.get_remaining_time_in_millis()`, captured per-invocation via
`set_lambda_context()` in `site_api_ai_lambda.lambda_handler`): no context
(direct handler calls in tests/local) means the budget is unknowable, so the
gate skips — fail-open, consistent with "never gate what you can't bound".

Scope posture (ADR-103 ledger row, 2026-07-11): the gate covers the two
reader-facing coach-voiced surfaces (daily brief + this board) and is
deliberately NOT extended to inter_coach_dialogue / coach_memoir (internal,
lower stakes, ADR-108's measurement doesn't transfer unmeasured) nor to
/api/ask + /api/explain (narrator-voiced — no coach_id/voice spec to gate on).
"""

import logging
import os

import boto3

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

REGION = os.environ.get("DYNAMODB_REGION", "us-west-2")

QG_EVAL_MIN_REMAINING_MS = 14_000  # evaluate only with ≥14s left (gate ≈2-5s + response margin)
QG_REGEN_MIN_REMAINING_MS = 12_000  # corrective rewrite only with ≥12s left (regen + re-ground ≈4-7s)
QG_INVOKE_TIMEOUT_S = 10  # client-side cap — the gate lambda's internal retry backoff must never stall a reader

_QG_LAMBDA_CLIENT = None
_LAMBDA_CONTEXT = None  # set per-invocation via set_lambda_context()
_CW = None


def set_lambda_context(context) -> None:
    """Capture the invocation context so the hard time budget can be enforced
    off the REAL Lambda deadline. Called once per invocation by the handler."""
    global _LAMBDA_CONTEXT
    _LAMBDA_CONTEXT = context


def _remaining_ms():
    """Milliseconds left in THIS invocation, or None when unknowable (direct
    handler calls in tests/local runs carry no Lambda context)."""
    try:
        if _LAMBDA_CONTEXT is not None:
            return int(_LAMBDA_CONTEXT.get_remaining_time_in_millis())
    except Exception:
        pass
    return None


def _qg_lambda_client():
    """Lambda client for the gate invoke — tight timeouts, no botocore retries,
    so the 30s site-api-ai deadline can never be eaten by the gate call."""
    global _QG_LAMBDA_CLIENT
    if _QG_LAMBDA_CLIENT is None:
        from botocore.config import Config as _BotoCfg

        _QG_LAMBDA_CLIENT = boto3.client(
            "lambda",
            region_name=REGION,
            config=_BotoCfg(connect_timeout=2, read_timeout=QG_INVOKE_TIMEOUT_S, retries={"max_attempts": 0}),
        )
    return _QG_LAMBDA_CLIENT


def _cw_client():
    global _CW
    if _CW is None:
        _CW = boto3.client("cloudwatch", region_name=REGION)
    return _CW


def quality_findings(report: dict) -> list:
    """Translate a gate report into eval-retention findings — the same mapping
    `ai_calls._retain_coach_brief_flag` applies on the daily-brief surface."""
    findings = []
    for v in report.get("anti_pattern_violations") or []:
        phrase = v.get("phrase") if isinstance(v, dict) else v
        if phrase:
            findings.append({"type": "anti_pattern", "detail": phrase})
    for v in report.get("decision_class_violations") or []:
        if isinstance(v, dict):
            findings.append({"type": "decision_class", "detail": v.get("excerpt", "")})
    for flag in report.get("cross_coach_similarity_flags") or []:
        if isinstance(flag, dict):
            findings.append({"type": "cross_coach_similarity", "detail": flag.get("reason", "")})
    return findings


def enforce(pid: str, answer: str, regenerate_fn, is_grounded_fn, retain_fn, endpoint: str = "board_ask") -> str:
    """#968: run the ADR-108 quality gate over a grounded board answer.

    Returns the text to serve — ALWAYS returns text (fail-open contract; see
    the module docstring). On a fired verdict with budget left: ONE corrective
    rewrite (`regenerate_fn(note)`), accepted only if it still passes the
    ADR-104 grounding check (`is_grounded_fn`) — a voice fix must never
    smuggle in a fabricated number. The corrected draft is NOT re-scored (a
    re-score costs ~3s and cannot change the serve decision under fail-open);
    the retained draft/final pair (`retain_fn`, fail-soft in the caller) is
    the offline review trail.
    """
    remaining = _remaining_ms()
    if remaining is None or remaining < QG_EVAL_MIN_REMAINING_MS:
        if remaining is not None:
            logger.info(f"[{endpoint}] {pid} quality gate skipped — {remaining}ms left (fail-open)")
        return answer
    try:
        from ai_calls import _invoke_quality_gate_sync, _quality_gate_correction_note

        report = _invoke_quality_gate_sync(_qg_lambda_client(), pid, answer, None)
    except Exception as e:
        logger.warning(f"[{endpoint}] {pid} quality gate unavailable (fail-open): {e}")
        return answer
    if report.get("passed", True):
        return answer

    final, disposition = answer, "flagged_kept"
    remaining = _remaining_ms()
    if remaining is not None and remaining >= QG_REGEN_MIN_REMAINING_MS:
        try:
            candidate = regenerate_fn(_quality_gate_correction_note(report))
            if (candidate or "").strip() and is_grounded_fn(candidate):
                final, disposition = candidate, "flagged_corrected"
        except Exception as e:
            logger.warning(f"[{endpoint}] {pid} quality regen failed — serving original (fail-open): {e}")
    logger.warning(f"[{endpoint}] {pid} ADR-108 quality gate fired (score={report.get('score')}) — {disposition}")
    retain_fn(
        pid,
        disposition,
        answer,
        final,
        quality_findings(report),
        extra={"endpoint": endpoint, "gate": "adr108_quality", "score": report.get("score")},
    )
    try:
        _cw_client().put_metric_data(
            Namespace="LifePlatform/AI",
            MetricData=[
                {
                    "MetricName": "BoardQualityGateFired",
                    "Dimensions": [{"Name": "CoachID", "Value": pid}],
                    "Value": 1,
                    "Unit": "Count",
                }
            ],
        )
    except Exception as e:
        logger.warning(f"[{endpoint}] {pid} quality gate metric emit failed (non-fatal): {e}")
    return final
