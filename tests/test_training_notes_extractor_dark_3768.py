"""tests/test_training_notes_extractor_dark_3768.py — the derived note layer cannot go dark silently (#3768).

THE INCIDENT
  The training-note extractor was dark from the day it shipped. `_derive_training_notes`
  ran on every ingest, called the bounded Haiku tail, and the tail raised AccessDenied
  every single time because `ingestion_hevy_backfill()` granted secret + S3 + DDB and no
  `bedrock:InvokeModel`. `extract_signals` caught the exception, set `degraded: true` and
  logged NOTHING, so:

    - fourteen days of `/aws/lambda/hevy-backfill` logs held no Bedrock line at all;
    - `training_notes#USAGE / MONTH#...` — bumped only AFTER a successful call — had no
      item for ANY month, which is the tell nobody was reading;
    - `get_freshness_status.training_notes_health` DID say `extractor_dark: true, 15/15
      degraded`, and that field was reachable only by calling the MCP tool by hand.

  Three independent signals of the same failure, none of them on a path a human or an
  alarm would cross. The measured consequence: on 2026-09-13 the coach was asked for a
  movement's history and answered "no notes", correctly, about a layer that could not
  have produced any.

WHAT THIS PINS
  1. the IAM grant exists (the cause);
  2. the degrade is LOGGED with its exception class (the missing evidence);
  3. a dark layer reaches the freshness checker's stale path (the missing alarm);
  4. the negative controls: a HEALTHY extractor must not log a degrade and must not
     report dark — a guard that fires on everything is not a guard.
"""

from __future__ import annotations

import ast
import logging
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))

from training import training_notes as tn  # noqa: E402


# ── 1. The cause: the role carries bedrock:InvokeModel ────────────────────────
def test_hevy_backfill_role_grants_bedrock_invoke():
    """Read by AST, not by import — cdk/ needs aws_cdk, which the unit lane does not have.

    The assertion is on the SHAPE the sibling ingestion roles use: the function's return
    is `_ingestion_base(...) + [_bedrock_statement()]`. A refactor that keeps the call but
    drops the concatenation is exactly the regression, so the test reads the return node
    rather than grepping for the string anywhere in the file.
    """
    src = (REPO / "cdk" / "stacks" / "role_policies_ingestion.py").read_text()
    tree = ast.parse(src)
    fn = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "ingestion_hevy_backfill"),
        None,
    )
    assert fn is not None, "ingestion_hevy_backfill() is gone — the role it defines is what #3768 fixed"
    ret = next((n for n in ast.walk(fn) if isinstance(n, ast.Return)), None)
    assert ret is not None and isinstance(ret.value, ast.BinOp), "the role no longer composes extra statements onto _ingestion_base"
    called = {n.func.id for n in ast.walk(ret.value) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_bedrock_statement" in called, (
        "ingestion_hevy_backfill() does not grant bedrock:InvokeModel. The on-ingest note "
        "extractor calls Haiku through bedrock_client; without this the layer is dark and "
        "every record silently carries degraded: true (#3768)."
    )


# ── 2. The missing evidence: a degrade says why, in the log ───────────────────
def _boom(_note, _taxonomy):
    raise PermissionError("An error occurred (AccessDeniedException) when calling the InvokeModel operation")


def test_llm_failure_logs_its_exception_class(caplog):
    with caplog.at_level(logging.WARNING, logger="training.training_notes"):
        out = tn.extract_signals("grip gave out before the quads did", llm_fn=_boom)

    assert out["degraded"] is True
    assert out["extracted_by"] == "deterministic"
    msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("PermissionError" in m for m in msgs), f"the degrade did not name its exception class: {msgs}"


def test_the_degrade_log_never_carries_the_note_text(caplog):
    """Raw notes are owner-private. The log line is for the operator, not a data channel."""
    secret = "left knee felt sharp on the last rep"
    with caplog.at_level(logging.WARNING, logger="training.training_notes"):
        tn.extract_signals(secret, llm_fn=_boom)
    for r in caplog.records:
        assert secret not in r.getMessage(), "the degrade log leaked the note text"


def test_a_healthy_extraction_logs_no_degrade(caplog):
    """NEGATIVE CONTROL — the warning must be the failure path, not a constant."""
    with caplog.at_level(logging.WARNING, logger="training.training_notes"):
        out = tn.extract_signals(
            "level 8 intervals",
            llm_fn=lambda _n, _t: [{"class": "progression", "summary": "level 8", "confidence": 0.9}],
        )
    assert out["degraded"] is False
    assert out["extracted_by"] == "hybrid"
    assert not [r for r in caplog.records if "llm degraded" in r.getMessage()]


# ── 3. The missing alarm: a dark layer reaches the stale path ─────────────────
def test_freshness_checker_folds_in_the_derived_layer_health():
    """The health function existed and its ONLY reader was an MCP field.

    `training_notes_health`'s own docstring says "hook into get_freshness_status" — it was
    hooked into the MCP tool, which no schedule calls, and not into the Lambda that pages.
    This pins the Lambda side: the module imports the health function and appends to
    `stale_sources`, the same list the SNS alert, the email body and the SLO metric all
    read (the #3563 class — a fail-soft path with no dead-man).
    """
    src = (REPO / "lambdas" / "emails" / "freshness_checker_lambda.py").read_text()
    assert "training_notes_health" in src, "the freshness checker does not consult the derived-layer health at all"
    tree = ast.parse(src)
    handler = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "lambda_handler"), None)
    assert handler is not None
    seg = ast.get_source_segment(src, handler) or ""
    assert "training_notes_health" in seg, "the health check is not inside lambda_handler — it would never run"
    idx = seg.index("training_notes_health")
    assert (
        "stale_sources.append" in seg[idx : idx + 2000]
    ), "a dark extractor does not reach stale_sources, so it rides neither the SNS alert nor the email"


# ── 4. The health function's own truth table ──────────────────────────────────
class _FakeTable:
    """Minimal query stub: the raw hevy partition, then per-exercise projection rows."""

    def __init__(self, workouts, notes_rows):
        self._workouts = workouts
        self._notes = notes_rows

    def query(self, **kw):
        # The two queries are told apart by what they project, which is stable: the raw
        # sweep asks for the exercise list, the per-record probe asks only for `degraded`.
        proj = kw.get("ProjectionExpression", "")
        if "exercises" in proj:
            return {"Items": self._workouts}
        values = getattr(kw.get("KeyConditionExpression"), "_values", ())
        flat = " ".join(str(getattr(v, "_values", v)) for v in values)
        for tid, rows in self._notes.items():
            if tid in flat:
                return {"Items": rows}
        return {"Items": []}


_TODAY_WORKOUT = [{"date": tn.pacific_today(), "exercises": [{"template_id": "ABC123", "name": "Squat", "notes": "felt strong"}]}]


def test_health_reports_dark_when_every_record_is_degraded():
    t = _FakeTable(_TODAY_WORKOUT, {"ABC123": [{"degraded": True}]})
    h = tn.training_notes_health(t, lookback_days=14)
    assert h["checked"] is True
    assert h["extractor_dark"] is True
    assert h["noted_exercise_sessions"] == 1 and h["degraded"] == 1


def test_health_reports_dark_when_records_are_missing_entirely():
    t = _FakeTable(_TODAY_WORKOUT, {})
    h = tn.training_notes_health(t, lookback_days=14)
    assert h["extractor_dark"] is True
    assert h["missing_records"] == 1


def test_health_reports_healthy_when_records_are_clean():
    """NEGATIVE CONTROL — `extractor_dark` must be able to be False."""
    t = _FakeTable(_TODAY_WORKOUT, {"ABC123": [{"degraded": False}]})
    h = tn.training_notes_health(t, lookback_days=14)
    assert h["extractor_dark"] is False
    assert h["records_found"] == 1 and h["degraded"] == 0


def test_health_says_nothing_when_there_are_no_notes_to_extract():
    """No noted sessions is not a dark extractor — absence of input, not absence of output."""
    t = _FakeTable([{"date": tn.pacific_today(), "exercises": [{"template_id": "ABC123", "name": "Squat", "notes": ""}]}], {})
    h = tn.training_notes_health(t, lookback_days=14)
    assert h["extractor_dark"] is False
    assert h["noted_exercise_sessions"] == 0


# ── 5. The repair path exists and is bounded ──────────────────────────────────
def test_backfill_exposes_a_reextract_mode():
    """The window the extractor was dark for is already ingested — nothing revisits it."""
    src = (REPO / "lambdas" / "ingestion" / "hevy_backfill_lambda.py").read_text()
    tree = ast.parse(src)
    names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert "reextract_training_notes" in names, "no repair path — the dark window stays dark forever"
    handler = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "lambda_handler")
    seg = ast.get_source_segment(src, handler) or ""
    assert "reextract_days" in seg, "the repair mode is unreachable from an invoke"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
