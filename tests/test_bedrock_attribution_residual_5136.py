"""tests/test_bedrock_attribution_residual_5136.py — #5136: no Bedrock dollar reaches the meter unnamed in silence.

WHERE THE $35.52 CAME FROM (read-only CloudWatch, 2026-10-23)
-------------------------------------------------------------
`get_platform_cost` (the /api/inference_receipt `attribution.unattributed_usd`) showed $35.52 in
the `unknown` row for October. That is `EstimatedCostUSD{LambdaFunction=unknown}` = $30.88 x the
receipt's 1.15 buffer, and it splits into two callers:

  * $30.65 dated 10-01 19-20Z, 10-02 01-02Z, 10-03 03Z — the same hours, to the cent per UTC day,
    as `EstimatedCostUSD{CallerClass=dev-session}`: the workstation Story Desk season rebuilds that
    #4589 traced. Its fix (PR #4598, the `dev-session` label) merged 10-04 08:01Z, AFTER the spend,
    and the meter cannot re-label a datapoint — so the row is history, not a live hole.
  * $0.23 at 10-04 16:25Z, 10-11 15:15Z, 10-18 15:10Z — 9 calls each, the exact minutes of the
    three `Fresh-Eyes Discovery` workflow runs. That caller was still unnamed; it is named now.

WHAT IS PINNED HERE
-------------------
  1. The fresh-eyes calls are metered under `fresh-eyes-discovery` (driven end-to-end through the
     script's own call sites with the REAL `bedrock_client.attributed_to`).
  2. An unnamed call is LOUD: metering it prints the UNATTRIBUTED warning naming the workflow and
     entrypoint (acceptance box 4 — "an un-tagged call cannot reach the meter silently").
  3. The receipt dates the residual and splits it at the day the workstation label landed, so a
     month total can no longer be read as a live hole when it is history (ADR-104).
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO / "lambdas", _REPO / "lambdas" / "web", _REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from ai import bedrock_client  # noqa: E402

_HAIKU = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


@pytest.fixture(autouse=True)
def _ci_context(monkeypatch):
    """Pin the CI context: the one context where an unlabelled call still lands in `unknown`."""
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    monkeypatch.delenv("INVOCATION_CONTEXT", raising=False)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_WORKFLOW", "Fresh-Eyes Discovery")
    monkeypatch.delenv("GITHUB_WORKFLOW_REF", raising=False)


class _RecordingBedrock:
    """Stands in for the bedrock_client module: the REAL attributed_to, a fake invoke that
    records which feature the chokepoint would meter the call under."""

    attributed_to = staticmethod(bedrock_client.attributed_to)

    def __init__(self, text=""):
        self.features = []
        self._text = text

    def invoke(self, body, model_name=None):
        self.features.append(bedrock_client.feature_name())
        return {"content": [{"type": "text", "text": self._text}]}


# ── 1. the last unnamed caller is named ────────────────────────────────────────
def test_fresh_eyes_label_is_allowlisted_and_claimed_by_the_budget_ledger():
    import ai_budget_ledger
    import fresh_eyes_discovery as fed

    assert fed.FRESH_EYES_FEATURE in bedrock_client.ATTRIBUTABLE_FEATURES, "an unlisted label is ignored -> unknown"
    assert fed.FRESH_EYES_FEATURE in ai_budget_ledger.claimed_attribution_keys(), "an unclaimed dimension reds the monthly close"


def test_every_fresh_eyes_bedrock_call_is_metered_under_its_label(tmp_path, monkeypatch):
    """Both call sites (the per-screenshot vision read and the board synthesis), through the
    script's own functions. NEGATIVE CONTROL — verified by mutation: replacing either
    `_attributed_invoke(bedrock, body, model_name)` with `bedrock.invoke(body, model_name=model_name)`
    turns the matching assertion red with `['unknown']`."""
    import fresh_eyes_discovery as fed

    shot = tmp_path / "door.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 1024)
    bedrock = _RecordingBedrock()
    monkeypatch.setattr(fed, "_image_blocks", lambda path: [{"type": "text", "text": "(image)"}])  # no real image work
    fed.vision_read(bedrock, "home", "/", str(shot), "page")
    assert bedrock.features == ["fresh-eyes-discovery"], bedrock.features

    bedrock = _RecordingBedrock()
    fed.synthesize_board(bedrock, [{"note": "x", "audiences": ["reddit_newcomer"], "pages": ["home"], "count": 1, "severity": "low"}], [])
    assert bedrock.features == ["fresh-eyes-discovery"], bedrock.features
    assert bedrock_client.feature_name() == "unknown", "the label leaked past the call"


# ── 2. an unnamed call is loud ─────────────────────────────────────────────────
class _FakeCW:
    def __init__(self):
        self.metric_data = []

    def put_metric_data(self, **kw):
        self.metric_data.extend(kw["MetricData"])


def test_an_unlabelled_ci_call_cannot_reach_the_meter_silently(monkeypatch, capsys):
    """Acceptance box 4. The spend is still metered (dropping it would hide real money) AND the
    run's own log names who spent it. NEGATIVE CONTROL — verified by mutation: deleting the
    `_note_unattributed(feature, cost)` line in `_emit_usage_metrics` turns this red."""
    cw = _FakeCW()
    monkeypatch.setattr(bedrock_client, "_CW", cw)
    bedrock_client._emit_usage_metrics({"input_tokens": 1000, "output_tokens": 100}, _HAIKU)
    err = capsys.readouterr().err
    assert "UNATTRIBUTED Bedrock spend" in err, err
    assert "workflow='Fresh-Eyes Discovery'" in err and "caller_class=ci" in err
    named = {m["Dimensions"][0]["Value"] for m in cw.metric_data if m.get("Dimensions") and m["Dimensions"][0]["Name"] == "LambdaFunction"}
    assert named == {"unknown"}, "the residual must still be metered, under its historic name"


def test_a_named_call_is_quiet(monkeypatch, capsys):
    monkeypatch.setattr(bedrock_client, "_CW", _FakeCW())
    with bedrock_client.attributed_to("fresh-eyes-discovery"):
        bedrock_client._emit_usage_metrics({"input_tokens": 1000, "output_tokens": 100}, _HAIKU)
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "daily-brief")
    bedrock_client._emit_usage_metrics({"input_tokens": 1000, "output_tokens": 100}, _HAIKU)
    assert "UNATTRIBUTED" not in capsys.readouterr().err


def test_a_workstation_call_is_named_dev_session_and_quiet(monkeypatch, capsys):
    """The dev-session row is the one the laptop cap (DEV_AI_BUDGET_USD) governs — named, not residual."""
    for var in ("GITHUB_ACTIONS", "CI", "GITHUB_WORKFLOW"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(bedrock_client, "_CW", _FakeCW())
    bedrock_client._emit_usage_metrics({"input_tokens": 1000, "output_tokens": 100}, _HAIKU)
    assert bedrock_client.feature_name() == "dev-session"
    assert "UNATTRIBUTED" not in capsys.readouterr().err


def test_the_tripwire_never_costs_the_datapoint_or_the_call(monkeypatch):
    """Fail-open: a broken stderr must neither raise into the AI call nor drop the metered spend."""

    class _BrokenStderr:
        def write(self, *a, **k):
            raise OSError("stderr closed")

        def flush(self):
            raise OSError("stderr closed")

    cw = _FakeCW()
    monkeypatch.setattr(bedrock_client, "_CW", cw)
    monkeypatch.setattr(bedrock_client.sys, "stderr", _BrokenStderr())
    bedrock_client._emit_usage_metrics({"input_tokens": 1, "output_tokens": 1}, _HAIKU)  # must not raise
    assert any(m["MetricName"] == "EstimatedCostUSD" for m in cw.metric_data), "the tripwire cost the datapoint"


# ── 3. the receipt dates the residual ──────────────────────────────────────────
def _ts(day, hour):
    return datetime(2026, 10, day, hour, tzinfo=timezone.utc)


# The October 2026 `unknown` row as CloudWatch returned it (unbuffered USD).
_OCTOBER_UNKNOWN = [
    (_ts(1, 19), 1.08),
    (_ts(1, 20), 12.42),
    (_ts(2, 1), 2.08),
    (_ts(2, 2), 13.57),
    (_ts(3, 3), 1.50),
    (_ts(4, 16), 0.0757),
    (_ts(11, 15), 0.0835),
    (_ts(18, 15), 0.0752),
]


def test_the_residual_is_dated_and_split_at_the_label_date():
    from web import site_api_budget as budget

    split = budget._residual_split(_OCTOBER_UNKNOWN)
    days = split["unattributed_by_day"]
    assert [d["date"] for d in days] == ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-11", "2026-10-18"]
    assert split["residual_labels_since"] == "2026-10-04"
    assert split["unattributed_before_labels_usd"] == round((1.08 + 12.42 + 2.08 + 13.57 + 1.50) * 1.15, 4)
    assert split["unattributed_since_labels_usd"] == round((0.0757 + 0.0835 + 0.0752) * 1.15, 4)
    total = split["unattributed_before_labels_usd"] + split["unattributed_since_labels_usd"]
    assert round(total, 2) == 35.52, "the split must sum to the figure #5136 quotes"


def test_an_empty_or_naive_series_is_handled():
    from web import site_api_budget as budget

    assert budget._residual_split([])["unattributed_by_day"] == []
    naive = budget._residual_split([(datetime(2026, 11, 2, 5), 0.5), (None, 9.0)])
    assert naive["unattributed_by_day"] == [{"date": "2026-11-02", "usd": 0.575}]
    assert naive["unattributed_before_labels_usd"] == 0.0


class _CW:
    """/api/inference_receipt's CloudWatch: one model, one named feature + the `unknown` row."""

    def list_metrics(self, Namespace, MetricName, **kw):
        if Namespace == "AWS/Bedrock":
            return {"Metrics": [{"Dimensions": [{"Name": "ModelId", "Value": _HAIKU}]}]}
        return {"Metrics": [{"Dimensions": [{"Name": "LambdaFunction", "Value": f}]} for f in ("daily-brief", "unknown")]}

    def get_metric_data(self, MetricDataQueries, StartTime, EndTime, **kw):
        out = []
        for q in MetricDataQueries:
            dims = q["MetricStat"]["Metric"]["Dimensions"]
            is_unknown_cost = dims[0]["Value"] == "unknown" and q["MetricStat"]["Metric"]["MetricName"] == "EstimatedCostUSD"
            pts = _OCTOBER_UNKNOWN if is_unknown_cost else [(_ts(5, 0), 100.0)]
            out.append({"Id": q["Id"], "Timestamps": [t for t, _ in pts], "Values": [v for _, v in pts]})
        return {"MetricDataResults": out}


class _SSM:
    def get_parameter(self, Name):
        if Name == "/life-platform/budget-tier":
            return {"Parameter": {"Value": "0"}}
        return {"Parameter": {"Value": json.dumps({"ceiling": 85.0, "surge_active": False})}}


def test_the_served_receipt_and_the_mcp_tool_carry_the_dated_residual(monkeypatch):
    """The wire, not just the helper: the route serves the split, the schema baseline pins it,
    and get_platform_cost reads it into a sentence that separates history from a live hole."""
    from web import site_api_intelligence as sai

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            fixed = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
            return fixed.replace(tzinfo=None) if tz is None else fixed.astimezone(tz)

    monkeypatch.setattr(sai._budget, "datetime", _Frozen)
    monkeypatch.setattr(sai.boto3, "client", lambda service, **kw: _CW() if service == "cloudwatch" else _SSM())
    resp = sai.handle_inference_receipt()
    assert resp["statusCode"] == 200, resp
    attribution = json.loads(resp["body"])["attribution"]
    assert attribution["unattributed_usd"] == round(sum(v for _, v in _OCTOBER_UNKNOWN) * 1.15, 4)
    assert attribution["unattributed_since_labels_usd"] == round((0.0757 + 0.0835 + 0.0752) * 1.15, 4)
    assert len(attribution["unattributed_by_day"]) == 6

    snapshot = json.loads((_REPO / "tests" / "api_schemas" / "api_inference_receipt.json").read_text())
    pinned = snapshot["shape"]["keys"]["attribution"]["keys"]
    new_keys = ("unattributed_by_day", "unattributed_before_labels_usd", "unattributed_since_labels_usd", "residual_labels_since")
    missing = [k for k in new_keys if k not in pinned or k not in attribution]
    assert not missing, missing

    sys.path.insert(0, str(_REPO))
    from mcp import tools_platform

    monkeypatch.setattr(tools_platform, "_surface", lambda name, params=None: {"data": {"attribution": attribution}})
    reading = tools_platform.tool_get_platform_cost()["unattributed_reading"]
    assert "before 2026-10-04" in reading and "dev-session" in reading and "UNATTRIBUTED Bedrock spend" in reading
