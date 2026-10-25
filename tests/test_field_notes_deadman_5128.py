"""tests/test_field_notes_deadman_5128.py — a HELD field-notes edition is visible, and heartbeats the dead-man.

2026-W42 (2026-10-18T18:00:28Z): the grounding gate held the note and nothing said so. #5128:
  * a hold writes `generated: false, reason: grounding_held, detail` in the SEPARATE held partition
    (never FN_PK — /api/field_notes list mode would render it as a week);
  * every run emits FieldNotesOutcome (1 = edition exists, 0 = held/crashed) as EMF, the series behind
    the `field-notes-missing` alarm (compute_stack.py).
"""

import json
import os
import re
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "intelligence"))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import field_notes_lambda as fnl  # noqa: E402
import pytest  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402

_PROMPT = "BASE PROMPT — this week: resting heart rate 64 bpm, recovery 55 percent."
BAD = {"ai_present": "Resting heart rate held at 10.7 bpm all week.", "ai_tone": "mixed"}
GOOD = {"ai_present": "Resting heart rate held at 64 bpm all week.", "ai_tone": "mixed"}


@pytest.fixture()
def wired(monkeypatch):
    import common.qa_archive as qa_archive
    import experiment.eval_retention as eval_retention

    t = FakeDdbTable(rows=[], seed_store=False)
    monkeypatch.setattr(fnl, "table", t)
    monkeypatch.setattr(fnl, "_get_api_key", lambda: "k")
    monkeypatch.setattr(fnl, "gather_week_data", lambda s, e: {})
    monkeypatch.setattr(fnl, "get_prior_notes", lambda w: [])
    monkeypatch.setattr(fnl, "build_prompt", lambda w, d, p: _PROMPT)
    monkeypatch.setattr(eval_retention, "retain", lambda *a, **k: True)
    monkeypatch.setattr(qa_archive, "archive_text", lambda *a, **k: None)
    return t


def _metric(capsys):
    lines = [json.loads(ln) for ln in capsys.readouterr().out.splitlines() if ln.startswith("{") and "_aws" in ln]
    assert len(lines) == 1, lines
    return lines[0]


def test_held_edition_writes_marker_and_emits_zero(wired, monkeypatch, capsys):
    monkeypatch.setattr(fnl, "_call_notes_model", lambda p, k: BAD)
    resp = fnl.lambda_handler({"manual_week": "2026-W42"}, None)
    assert json.loads(resp["body"])["status"] == "held"
    marker = [p for p in wired.puts if p["pk"] == fnl.FN_HELD_PK]
    assert len(marker) == 1
    m = marker[0]
    assert m["sk"] == "WEEK#2026-W42" and m["generated"] is False and m["reason"] == "grounding_held"
    assert "10.7" in m["detail"]
    assert [p for p in wired.puts if p["pk"] == fnl.FN_PK] == [], "the marker must never land in the reader partition"
    metric = _metric(capsys)
    assert metric["FieldNotesOutcome"] == 0
    spec = metric["_aws"]["CloudWatchMetrics"][0]
    assert spec["Namespace"] == "LifePlatform/FieldNotes" and spec["Dimensions"] == [["Job"]]


def test_written_edition_emits_one_and_no_marker(wired, monkeypatch, capsys):
    monkeypatch.setattr(fnl, "_call_notes_model", lambda p, k: GOOD)
    resp = fnl.lambda_handler({"manual_week": "2026-W42"}, None)
    assert json.loads(resp["body"])["status"] == "ok"
    assert [p for p in wired.puts if p["pk"] == fnl.FN_HELD_PK] == []
    assert _metric(capsys)["FieldNotesOutcome"] == 1


def test_crash_writes_marker_and_emits_zero(wired, monkeypatch, capsys):
    def boom(p, k):
        raise RuntimeError("bedrock down")

    monkeypatch.setattr(fnl, "_call_notes_model", boom)
    resp = fnl.lambda_handler({"manual_week": "2026-W42"}, None)
    assert resp["statusCode"] == 500
    marker = [p for p in wired.puts if p["pk"] == fnl.FN_HELD_PK]
    assert marker and marker[0]["reason"] == "generation_failed" and marker[0]["generated"] is False
    assert _metric(capsys)["FieldNotesOutcome"] == 0


def test_alarm_declared_in_compute_stack_matches_the_emitter():
    src = open(os.path.join(_REPO, "cdk", "stacks", "compute_stack.py")).read()
    block = src[src.index('alarm_name="field-notes-missing"') :]
    block = block[: block.index("add_alarm_action")]
    assert f'namespace="{fnl.METRIC_NAMESPACE}"' in block
    assert f'metric_name="{fnl.METRIC_NAME}"' in block
    assert f'"Job": "{fnl.METRIC_DIMENSION["Job"]}"' in block
    assert "TreatMissingData.BREACHING" in block
    assert re.search(r"evaluation_periods=7", block) and re.search(r"datapoints_to_alarm=7", block)


def test_successful_run_resolves_an_existing_marker_conditionally(wired, monkeypatch, capsys):
    monkeypatch.setattr(fnl, "_call_notes_model", lambda p, k: GOOD)
    fnl.lambda_handler({"manual_week": "2026-W42"}, None)
    ups = [u for u in wired.updates if u["Key"]["pk"] == fnl.FN_HELD_PK]
    assert len(ups) == 1 and ups[0]["ConditionExpression"] == "attribute_exists(pk)"
