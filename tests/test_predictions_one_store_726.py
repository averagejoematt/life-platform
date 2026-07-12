"""tests/test_predictions_one_store_726.py — one prediction store (#726, epic #715).

Pins the #726 contract: MCP `get_predictions` and the public
`site_api_coach.handle_predictions` read the SAME canonical store
(`COACH#{coach}_coach` / `PREDICTION#`), and neither reads the legacy
`SOURCE#coach_thread#` embedded arrays. Plus the void script's split rule:
`semantic_key` (the #725 stamp) exactly separates clean from corrupt.
"""

import ast
import os
import sys

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "lambdas"))

from fakes import FakeDdbTable  # noqa: E402


def _function_strings(path, func_name):
    """All string literals inside func_name's body, excluding its docstring."""
    tree = ast.parse(open(path).read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            body = node.body[1:] if isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) else node.body
            return [c.value for stmt in body for c in ast.walk(stmt) if isinstance(c, ast.Constant) and isinstance(c.value, str)]
    raise AssertionError(f"{func_name} not found in {path}")


class TestOneStore:
    def test_mcp_get_predictions_reads_canonical_store_only(self):
        strings = _function_strings(os.path.join(_ROOT, "mcp", "tools_coach_intelligence.py"), "tool_get_predictions")
        assert any("COACH#" in s for s in strings), "must query the COACH# partition"
        assert any("PREDICTION#" in s for s in strings), "must read PREDICTION# records"
        assert not any("coach_thread" in s for s in strings), "must NOT read the legacy coach_thread# store"

    def test_site_api_handle_predictions_reads_same_store(self):
        strings = _function_strings(os.path.join(_ROOT, "lambdas", "web", "site_api_coach.py"), "handle_predictions")
        assert any("COACH#" in s for s in strings)
        assert any("PREDICTION#" in s for s in strings)
        assert not any("coach_thread" in s for s in strings)


class TestGetPredictionsBehavior:
    def _fake_records(self):
        return [
            {
                "pk": "COACH#sleep_coach",
                "sk": "PREDICTION#pred_20260706_deep_sleep_rises",
                "prediction_id": "pred_20260706_deep_sleep_rises",
                "coach_id": "sleep_coach",
                "created_date": "2026-07-06",
                "claim_natural": "Deep sleep percentage will rise",
                "evaluation": {"type": "directional", "metric": "deep_pct", "evaluation_window_days": 14},
                "confidence": "high",
                "subdomain": "sleep",
                "status": "pending",
            },
            {
                "pk": "COACH#sleep_coach",
                "sk": "PREDICTION#pred_20260620_rhr_drops",
                "prediction_id": "pred_20260620_rhr_drops",
                "coach_id": "sleep_coach",
                "created_date": "2026-06-20",
                "claim_natural": "Resting heart rate will drop",
                "evaluation": {"type": "directional", "metric": "resting_heart_rate", "evaluation_window_days": 14},
                "confidence": "medium",
                "subdomain": "hrv",
                "status": "confirmed",
                "outcome": "hit",
                "outcome_date": "2026-07-04",
            },
        ]

    def _run(self, monkeypatch, args):
        import mcp.tools_coach_intelligence as tci

        recs = self._fake_records()
        queried_pks = []

        def _query_hook(_table, **kw):
            # Key("pk").eq(v) → the eq value sits in the condition's child values.
            cond = kw["KeyConditionExpression"]
            pk_val = cond._values[0]._values[1]
            queried_pks.append(pk_val)
            return {"Items": recs if pk_val == "COACH#sleep_coach" else []}

        monkeypatch.setattr(tci, "table", FakeDdbTable(query_hook=_query_hook))
        return tci.tool_get_predictions(args), queried_pks

    def test_maps_prediction_records(self, monkeypatch):
        out, pks = self._run(monkeypatch, {"coach_id": "sleep"})
        assert pks == ["COACH#sleep_coach"]  # bare id normalized to the evaluator's pk form
        assert out["total"] == 2
        assert out["summary"] == {"pending": 1, "confirmed": 1}
        newest = out["predictions"][0]
        assert newest["prediction_id"] == "pred_20260706_deep_sleep_rises"
        assert newest["claim"] == "Deep sleep percentage will rise"
        assert newest["metric"] == "deep_pct"
        assert newest["window_days"] == 14
        assert "COACH#" in out["store"]

    def test_status_filter(self, monkeypatch):
        out, _ = self._run(monkeypatch, {"coach_id": "sleep_coach", "status": "confirmed"})
        assert out["total"] == 1
        assert out["predictions"][0]["status"] == "confirmed"

    def test_all_coaches_queried_when_unfiltered(self, monkeypatch):
        import mcp.tools_coach_intelligence as tci

        _, pks = self._run(monkeypatch, {})
        assert len(pks) == len(tci.COACH_IDS)
        assert all(pk.startswith("COACH#") and pk.endswith("_coach") for pk in pks)


class TestVoidSplitRule:
    def test_semantic_key_separates_clean_from_corrupt(self):
        sys.path.insert(0, os.path.join(_ROOT, "deploy", "archive", "onetime"))
        from void_legacy_predictions_726 import split_predictions

        clean_pred = {"prediction_id": "pred_20260706_x", "semantic_key": "x", "status": "pending"}
        corrupt_dated = {"prediction_id": "pred_20240621_nervous_system_fracture", "status": "pending"}
        corrupt_null = {"prediction_id": "pred_20250000_y", "target_date": None, "status": "pending"}
        clean, corrupt = split_predictions([clean_pred, corrupt_dated, corrupt_null, "not-a-dict"])
        assert clean == [clean_pred]
        assert corrupt == [corrupt_dated, corrupt_null, "not-a-dict"]

    def test_empty_and_none(self):
        from void_legacy_predictions_726 import split_predictions

        assert split_predictions(None) == ([], [])
        assert split_predictions([]) == ([], [])
