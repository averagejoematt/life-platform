"""tests/test_eyeball_isolation_1390.py — the eyeball-calibration isolation guard (#1390).

AC#4 (load-bearing): estimate values can NEVER reach a nutrition metric path, the DDB
nutrition partition, or the coach deterministic payload — estimates exist only to be
graded. This proves that both statically and at runtime, plus covers the honest zero/low-n
reliability states (AC#3), budget gating (AC#5), and the cost measurement.

The isolation is proved two ways so a future refactor can't quietly break it:
  * STATIC (grep/AST): the eyeball partition literal appears in NO nutrition write path and
    in the coach deterministic-payload builder; and eyeball_calibration.py names NO nutrition
    partition — the estimate values have no code edge into nutrition either direction.
  * RUNTIME: the write functions refuse any non-eyeball pk; a graded record + a reliability
    artifact carry only error stats, never a raw macro value that could be re-ingested.
"""

import ast
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_LAMBDAS = ROOT / "lambdas"
sys.path.insert(0, str(_LAMBDAS))

import budget_guard  # noqa: E402
import eyeball_calibration as ec  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fakes import FakeDdbTable  # noqa: E402

# The DDB nutrition partitions (raw MacroFactor + its derived meals). Nothing eyeball
# may ever write to these; the estimate literal may never appear in their writers.
_NUTRITION_PK_TOKENS = ("SOURCE#macrofactor", "SOURCE#nutrition")

# The files that WRITE nutrition data (the raw ingest + the derived-meal projection) and
# the coach deterministic-payload builder. The eyeball literal must appear in none of them.
_NUTRITION_WRITE_PATHS = [
    _LAMBDAS / "ingestion" / "macrofactor_lambda.py",
    _LAMBDAS / "meal_projection.py",
]
_COACH_PAYLOAD_BUILDER = _LAMBDAS / "coach_register.py"

_EYEBALL_TOKENS = ("eyeball_estimate", "EYEBALL_PK", "eyeball_calibration")


# ── STATIC direction 1: no nutrition write path (nor the coach payload) references eyeball ──
@pytest.mark.parametrize("path", _NUTRITION_WRITE_PATHS + [_COACH_PAYLOAD_BUILDER])
def test_nutrition_and_coach_paths_never_name_eyeball(path):
    text = path.read_text(encoding="utf-8")
    for token in _EYEBALL_TOKENS:
        assert token not in text, f"{path.name} references eyeball token {token!r} — estimate/nutrition isolation breach"


# ── STATIC direction 2: eyeball module names no nutrition partition ──────────────
def test_eyeball_module_names_no_nutrition_partition():
    text = (_LAMBDAS / "eyeball_calibration.py").read_text(encoding="utf-8")
    for token in _NUTRITION_PK_TOKENS:
        # allow the token inside a comment ONLY as a documented truth-field name; but the
        # partition strings themselves must never appear (the module reads truth passed in,
        # never a nutrition pk).
        assert token not in text, f"eyeball_calibration.py names nutrition partition {token!r} — must never touch it"


def test_eyeball_module_writes_only_its_own_pk_statically():
    """AST: every string constant in eyeball_calibration.py that carries a SOURCE# token
    names ONLY the eyeball source."""
    tree = ast.parse((_LAMBDAS / "eyeball_calibration.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and "SOURCE#" in node.value:
            assert "SOURCE#eyeball_estimate" in node.value, f"unexpected SOURCE partition literal: {node.value!r}"


# ── RUNTIME: write guard refuses any non-eyeball pk ──────────────────────────────
def test_write_estimate_refuses_foreign_pk():
    table = FakeDdbTable()
    bad = ec.build_estimate_item({"calories": 500})
    bad["pk"] = "USER#matthew#SOURCE#macrofactor"  # try to smuggle into nutrition
    with pytest.raises(ec.EyeballIsolationError):
        ec.write_estimate(table, bad)
    assert table.puts == []  # nothing landed


def test_write_grade_refuses_foreign_pk():
    table = FakeDdbTable()
    bad = ec.build_grade_item("abc123", {"status": "graded", "macros": {}})
    bad["pk"] = "USER#matthew#SOURCE#nutrition"
    with pytest.raises(ec.EyeballIsolationError):
        ec.write_grade(table, bad)
    assert table.puts == []


def test_estimate_lands_only_in_eyeball_partition():
    table = FakeDdbTable()
    item = ec.build_estimate_item({"calories": 640, "protein_g": 40, "carbs_g": 55, "fat_g": 22}, estimate_id="deadbeef")
    sk = ec.write_estimate(table, item)
    assert sk.startswith("ESTIMATE#")
    assert len(table.puts) == 1
    put = table.puts[0]
    assert put["pk"] == ec.EYEBALL_PK
    assert put["never_nutrition"] is True and put["data_class"] == "estimate"
    # Decimal-before-write: no bare python floats in the stored macros.
    for v in put["estimate"].values():
        assert not isinstance(v, float), f"un-Decimal'd float in estimate: {v!r}"
        assert isinstance(v, (Decimal, int)) or v is None


# ── RUNTIME: grade + reliability artifact carry no raw macro into a nutrition shape ──
def test_grade_output_has_no_nutrition_pk_and_only_error_stats():
    truth = {"total_calories_kcal": 700, "total_protein_g": 45, "total_carbs_g": 60, "total_fat_g": 25}
    grade = ec.grade_against_truth({"calories": 640, "protein_g": 40, "carbs_g": 55, "fat_g": 22}, truth)
    assert grade["status"] == "graded"
    flat = repr(grade)
    assert "pk" not in grade and "SOURCE#" not in flat  # no partition key anywhere
    cal = grade["macros"]["calories"]
    assert cal["signed_error"] == 640 - 700 and cal["abs_error"] == 60
    assert round(cal["pct_error"], 2) == round((-60 / 700) * 100, 2)


def test_grade_honest_absence_when_truth_missing():
    """No truth -> every macro grades null, status ungraded — never a fabricated 0-error."""
    grade = ec.grade_against_truth({"calories": 500, "protein_g": 30, "carbs_g": 40, "fat_g": 20}, None)
    assert grade["status"] == "ungraded"
    assert all(grade["macros"][m] is None for m in ec.MACROS)


def test_grade_partial_truth_grades_only_present_macros():
    truth = {"total_calories_kcal": 700}  # only calories logged
    grade = ec.grade_against_truth({"calories": 640, "protein_g": 40}, truth)
    assert grade["status"] == "graded"
    assert isinstance(grade["macros"]["calories"], dict)
    assert grade["macros"]["protein_g"] is None


# ── AC#3: reliability artifact honest zero/low-n/reported states ─────────────────
def _grade_item(date, pct_by_macro):
    macros = {m: ({"pct_error": pct_by_macro[m]} if m in pct_by_macro else None) for m in ec.MACROS}
    return ec.build_grade_item("id" + date.replace("-", ""), {"status": "graded", "macros": macros}, date=date)


def test_reliability_empty_state():
    art = ec.build_reliability_artifact([])
    assert art["state"] == "empty" and art["n_days"] == 0
    for m in ec.MACROS:
        assert art["macros"][m]["sufficient"] is False
        assert art["macros"][m]["mape_pct"] is None  # no fabricated stat on n=0


def test_reliability_low_n_withholds_stats():
    grades = [_grade_item(f"2026-07-1{d}", {"calories": 10.0 * d}) for d in range(1, 4)]  # 3 days
    art = ec.build_reliability_artifact(grades, min_n=5)
    assert art["state"] == "low_n" and art["n_days"] == 3
    cal = art["macros"]["calories"]
    assert cal["n"] == 3 and cal["sufficient"] is False and cal["mape_pct"] is None


def test_reliability_reported_state_computes_stats():
    # 6 days of calorie pct errors -> above min_n, stats present.
    pcts = [10.0, -20.0, 15.0, -5.0, 8.0, -12.0]
    grades = [_grade_item(f"2026-07-0{d+1}", {"calories": pcts[d]}) for d in range(6)]
    art = ec.build_reliability_artifact(grades, min_n=5)
    assert art["state"] == "reported"
    cal = art["macros"]["calories"]
    assert cal["n"] == 6 and cal["sufficient"] is True
    assert cal["mape_pct"] == round(sum(abs(p) for p in pcts) / 6, 1)
    assert cal["bias_pct"] == round(sum(pcts) / 6, 1)
    assert cal["trend"]["direction"] in ("improving", "worsening", "flat")


def test_reliability_artifact_contains_no_raw_macro_values():
    """The published artifact must carry only aggregate error stats — no raw estimate/truth
    grams or kcal that could be mistaken for or re-ingested as nutrition data."""
    pcts = [10.0, -20.0, 15.0, -5.0, 8.0, -12.0]
    grades = [_grade_item(f"2026-07-0{d+1}", {"calories": pcts[d]}) for d in range(6)]
    art = ec.build_reliability_artifact(grades, min_n=5)
    allowed_keys = {"n", "sufficient", "mape_pct", "median_abs_pct", "bias_pct", "trend"}
    trend_keys = {"earlier_mape_pct", "recent_mape_pct", "direction"}
    for m in ec.MACROS:
        cell = art["macros"][m]
        assert set(cell).issubset(allowed_keys), f"{m} cell leaks keys: {set(cell) - allowed_keys}"
        assert "estimate" not in cell and "truth" not in cell
        if cell.get("trend"):
            assert set(cell["trend"]).issubset(trend_keys)


# ── AC#5: budget gating + Bedrock chokepoint ─────────────────────────────────────
def test_estimate_paused_at_budget_tier(monkeypatch):
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 1)  # band-1 cutoff -> blocked

    def _must_not_call(*a, **k):
        raise AssertionError("bedrock invoke_fn called while budget-paused")

    out = ec.estimate_from_photo("BASE64", invoke_fn=_must_not_call)
    assert out["status"] == "paused"


def test_estimate_runs_and_routes_through_invoke_fn(monkeypatch):
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    captured = {}

    def _fake_invoke(body, model_name=None):
        captured["body"] = body
        captured["model_name"] = model_name
        return {
            "content": [
                {
                    "type": "text",
                    "text": '{"calories": 640, "protein_g": 40, "carbs_g": 55, "fat_g": 22, "confidence": "low", "note": "bowl"}',
                }
            ]
        }

    out = ec.estimate_from_photo("BASE64IMG", media_type="image/png", invoke_fn=_fake_invoke)
    assert out["status"] == "ok"
    assert out["macros"] == {"calories": 640, "protein_g": 40, "carbs_g": 55, "fat_g": 22}
    assert out["confidence"] == "low" and out["note"] == "bowl"
    # routed on the Haiku tier, with an image content block (ADR-062 chokepoint shape)
    assert captured["model_name"] == "claude-haiku-4-5-20251001"
    content = captured["body"]["messages"][0]["content"]
    assert any(b.get("type") == "image" for b in content)
    img = next(b for b in content if b["type"] == "image")
    assert img["source"]["media_type"] == "image/png" and img["source"]["data"] == "BASE64IMG"


def test_estimate_unparseable_response_is_soft_error(monkeypatch):
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    out = ec.estimate_from_photo("X", invoke_fn=lambda body, model_name=None: {"content": [{"type": "text", "text": "I cannot tell."}]})
    assert out["status"] == "error"


def test_estimated_monthly_cost_is_about_a_dollar():
    """AC#5: cost measured. At 1 photo/day the metered Haiku cost is ~$1/mo (comfortably
    under $2)."""
    cost = ec.estimated_monthly_cost(photos_per_day=1.0)
    assert 0 < cost["monthly_usd"] < 2.0, cost
    assert "haiku" in cost["model"].lower()
