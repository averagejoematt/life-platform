"""tests/test_grounded_intake_facts_6212.py — grounded nutrition and body-composition facts, pure (#6212).

Wired since #6291 through ONE reader only: `coach.personal_context`, behind the coach-context switch
(`coach_context_pilot.LIVE`, still False). The guard at the bottom pins that single importer.

Every series here is SYNTHETIC: invented dates in 2030, round invented weights and kcal. Nothing reads AWS, the
charter or the clock (the complete-log line is passed explicitly, or its reader is stubbed).
"""

from __future__ import annotations

import ast
import os
import pathlib
import re
import sys
from datetime import date, timedelta

import pytest

os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO))

from health import grounded_intake_facts as gif  # noqa: E402

# ── synthetic fixture values (invented; not any person's data) ────────────────────────────────────
AS_OF = date(2030, 3, 31)
PHASE_START = date(2030, 1, 1)
SYN_START_WEIGHT = 200.0
SYN_LOSS_PER_WEEK = 1.0
SYN_EXPENDITURE = 2500.0
SYN_COMPLETE_LINE = 800.0
SYN_CONSISTENT_LOG = 2000.0
SYN_LOW_LOG = 1200.0
SYN_HIGH_LOG = 3200.0
SYN_PARTIAL_LOG = 300.0
FORBIDDEN = ("definitely", "accurate", "confirmed", "proves")


def _days(n: int, end: date = AS_OF):
    return [end - timedelta(days=i) for i in range(n)]


def _weights(n_days: int = 63, every: int = 1):
    out = {}
    for d in _days(n_days):
        if (AS_OF - d).days % every == 0:
            out[d.isoformat()] = SYN_START_WEIGHT - SYN_LOSS_PER_WEEK / 7 * (d - PHASE_START).days
    return out


def _flat(value: float, n_days: int = 63):
    return {d.isoformat(): value for d in _days(n_days)}


def _facts(intake, *, weights=None, expenditure=None, line=SYN_COMPLETE_LINE, scans=None, scale=None, phase_start=PHASE_START):
    return gif.build_facts(
        as_of=AS_OF.isoformat(),
        intake_by_day=intake,
        weight_by_day=_weights() if weights is None else weights,
        expenditure_by_day=_flat(SYN_EXPENDITURE) if expenditure is None else expenditure,
        expenditure_source="synthetic wearable estimate",
        scans=scans or [],
        scale_bodycomp_days=scale or {},
        phase_start=phase_start.isoformat() if phase_start else None,
        complete_log_kcal=line,
    )


def _intake_fact(facts):
    found = [f for f in facts if f["label"] == gif.LABEL_INTAKE]
    return found[0] if found else None


def _all_text(fact):
    return " ".join([fact["statement"], fact["uncertainty"], fact["source"], *fact["limits"]]).lower()


SHAPE = {"label", "as_of", "source", "statement", "uncertainty", "basis", "limits"}


# ── Fact 1: each verdict path ─────────────────────────────────────────────────────────────────────


def test_consistent_uses_the_approved_sentence_verbatim():
    f = _intake_fact(_facts(_flat(SYN_CONSISTENT_LOG)))
    assert f is not None and set(f) == SHAPE
    assert f["basis"]["verdict"] == gif.VERDICT_CONSISTENT
    assert f["statement"] == gif.CONSISTENT_STATEMENT
    assert gif.CONSISTENT_STATEMENT == (
        "Logged intake appears broadly consistent with substantial real energy restriction and observed weight loss. "
        "Some recent under-logging remains possible, and expenditure estimates introduce meaningful uncertainty. "
        "The evidence does not support assuming that low logged intake is merely a missing export."
    )
    assert f["as_of"] == AS_OF.isoformat() and gif.METHOD_ID in f["source"]
    lo, hi = f["basis"]["implied_intake_widened_kcal"]
    assert lo <= f["basis"]["logged_mean_complete_days_kcal"] <= hi
    # the window starts after the water-shift exclusion or the 63-day cap, whichever is later
    assert f["basis"]["window_days"] <= gif.WINDOW_MAX_DAYS
    assert f["basis"]["weight_slope_lb_per_week"] == pytest.approx(-SYN_LOSS_PER_WEEK, abs=0.01)


def test_logged_below_implied_states_a_gap_range():
    f = _intake_fact(_facts(_flat(SYN_LOW_LOG)))
    assert f["basis"]["verdict"] == gif.VERDICT_BELOW
    assert "may be incomplete by roughly" in f["statement"]
    assert re.search(r"roughly [\d,]+ to [\d,]+ kcal a day", f["statement"])
    assert "not a measured" in f["statement"]


def test_logged_above_implied():
    f = _intake_fact(_facts(_flat(SYN_HIGH_LOG)))
    assert f["basis"]["verdict"] == gif.VERDICT_ABOVE
    assert "sits above the intake implied" in f["statement"]


def test_implied_range_uses_both_densities_and_the_error_band():
    f = _intake_fact(_facts(_flat(SYN_CONSISTENT_LOG)))
    b = f["basis"]
    assert b["kcal_per_lb"] == [gif.KCAL_PER_LB_LOW, gif.KCAL_PER_LB_HIGH]
    assert b["expenditure_error_fraction"] == gif.EXPENDITURE_ERROR_FRACTION
    lo, hi = b["implied_intake_kcal"]
    wlo, whi = b["implied_intake_widened_kcal"]
    assert wlo < lo <= hi < whi


def test_complete_partial_missing_counts_and_both_means():
    intake = _flat(SYN_CONSISTENT_LOG)
    days = sorted(intake)
    for d in days[-5:]:
        intake[d] = SYN_PARTIAL_LOG  # five partial days (under the complete line) inside the window
    for d in days[-10:-5]:
        del intake[d]  # five missing days inside the window
    f = _intake_fact(_facts(intake))
    b = f["basis"]
    assert b["partial_days"] == 5 and b["missing_days"] == 5
    assert b["complete_days"] == b["window_days"] - 10
    assert b["logged_mean_all_logged_days_kcal"] < b["logged_mean_complete_days_kcal"]
    assert b["complete_log_kcal"] == SYN_COMPLETE_LINE


def test_water_shift_days_after_the_declared_start_are_excluded():
    late_start = AS_OF - timedelta(days=gif.WATER_SHIFT_DAYS + gif.WINDOW_MIN_DAYS + 3)
    f = _intake_fact(_facts(_flat(SYN_CONSISTENT_LOG), phase_start=late_start))
    assert f["basis"]["window_start"] == (late_start + timedelta(days=gif.WATER_SHIFT_DAYS)).isoformat()


# ── Fact 1: insufficient data returns NO fact ─────────────────────────────────────────────────────


def test_insufficient_data_returns_no_intake_fact():
    """Every insufficient path in one test (one census gate), reporting every path that wrongly built a fact."""
    cases = {
        "few_complete_days": ({"intake": _flat(SYN_CONSISTENT_LOG, n_days=gif.MIN_COMPLETE_DAYS - 1)}),
        "few_weigh_ins": {"weights": dict(list(_weights().items())[: gif.MIN_WEIGH_INS - 1])},
        "no_expenditure": {"expenditure": {}},
        "no_complete_line": {"line": None},
        "window_too_short": {"phase_start": AS_OF - timedelta(days=gif.WATER_SHIFT_DAYS + gif.WINDOW_MIN_DAYS - 5)},
        "no_intake": {"intake": {}},
    }
    built = []
    for name, kw in cases.items():
        intake = kw.pop("intake", _flat(SYN_CONSISTENT_LOG))
        if _intake_fact(_facts(intake, **kw)) is not None:
            built.append(name)
    assert not built, f"insufficient paths that still built Fact 1: {built}"


def test_default_complete_line_is_the_titration_rule_value(monkeypatch):
    from health import titration

    monkeypatch.setattr(titration, "settings", lambda *a, **k: {"complete_log_kcal": SYN_COMPLETE_LINE})
    assert gif.default_complete_log_kcal() == SYN_COMPLETE_LINE
    facts = gif.build_facts(
        as_of=AS_OF,
        intake_by_day=_flat(SYN_CONSISTENT_LOG),
        weight_by_day=_weights(),
        expenditure_by_day=_flat(SYN_EXPENDITURE),
        expenditure_source="synthetic",
        scans=[],
        scale_bodycomp_days={},
        phase_start=PHASE_START,
    )
    assert _intake_fact(facts)["basis"]["complete_log_kcal"] == SYN_COMPLETE_LINE


def test_unreadable_default_line_returns_no_intake_fact(monkeypatch):
    from health import titration

    def boom(*a, **k):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(titration, "settings", boom)
    facts = gif.build_facts(
        as_of=AS_OF,
        intake_by_day=_flat(SYN_CONSISTENT_LOG),
        weight_by_day=_weights(),
        expenditure_by_day=_flat(SYN_EXPENDITURE),
        expenditure_source="synthetic",
        scans=[],
        scale_bodycomp_days={},
    )
    assert _intake_fact(facts) is None


# ── Fact 2: the scan record ───────────────────────────────────────────────────────────────────────


def _scan_fact(facts):
    return next(f for f in facts if f["label"] == gif.LABEL_SCAN)


def test_no_scan_yields_a_none_stored_fact():
    f = _scan_fact(_facts(_flat(SYN_CONSISTENT_LOG), scans=[]))
    assert set(f) == SHAPE
    assert "No body-composition scan is stored" in f["statement"]
    assert f["basis"]["scans_stored"] == 0


def test_scan_before_phase_start_is_historical_with_lean_caveat():
    scan = {"date": "2029-06-01", "provider": "synthetic", "weight_lb": SYN_START_WEIGHT, "lean_mass_lb": 140.0}
    f = _scan_fact(_facts(_flat(SYN_CONSISTENT_LOG), scans=[scan]))
    assert "dated 2029-06-01" in f["statement"]
    assert gif.HISTORICAL_LABEL in f["statement"]
    assert "predates the phase start" in f["statement"]
    assert gif.LEAN_MASS_CAVEAT in f["statement"]
    assert f["basis"]["historical"] is True and f["basis"]["fields_present"] == ["lean_mass_lb", "weight_lb"]


def test_scan_in_phase_but_far_from_start_weight_is_historical():
    scan = {"date": PHASE_START.isoformat(), "weight_lb": SYN_START_WEIGHT + gif.SCAN_WEIGHT_TOLERANCE_LB + 3}
    f = _scan_fact(_facts(_flat(SYN_CONSISTENT_LOG), weights=_weights(n_days=120), scans=[scan]))
    assert f["basis"]["historical"] is True
    assert "differs from the phase-start weight" in f["statement"]


def test_scan_in_phase_near_start_weight_is_not_labelled_historical():
    scan = {"date": (PHASE_START + timedelta(days=2)).isoformat(), "weight_lb": SYN_START_WEIGHT}
    f = _scan_fact(_facts(_flat(SYN_CONSISTENT_LOG), weights=_weights(n_days=120), scans=[scan]))
    assert f["basis"]["historical"] is False
    assert gif.HISTORICAL_LABEL not in f["statement"]
    assert gif.LEAN_MASS_CAVEAT in f["statement"]


def test_scan_without_phase_start_defaults_to_historical():
    scan = {"date": "2030-02-01", "weight_lb": SYN_START_WEIGHT}
    f = _scan_fact(_facts(_flat(SYN_CONSISTENT_LOG), scans=[scan], phase_start=None))
    assert f["basis"]["historical"] is True


# ── Fact 3: home-scale limits ─────────────────────────────────────────────────────────────────────


def _scale_fact(facts):
    found = [f for f in facts if f["label"] == gif.LABEL_SCALE]
    return found[0] if found else None


def test_no_scale_days_yields_no_scale_fact():
    assert _scale_fact(_facts(_flat(SYN_CONSISTENT_LOG), scale={})) is None


def test_scale_fact_cites_study_and_omits_offset_without_a_close_scan():
    scale = {"2030-03-20": {"body_fat_pct": 30.0}}
    scan = {"date": "2029-06-01", "body_fat_pct": 25.0}
    f = _scale_fact(_facts(_flat(SYN_CONSISTENT_LOG), scans=[scan], scale=scale))
    assert set(f) == SHAPE
    assert "PMID 21236715" in f["source"] and gif.METHOD_ID in f["source"]
    assert "cannot by themselves establish lean-tissue loss" in f["statement"]
    assert f["basis"]["offset"] is None and "closest pair" not in f["statement"]


def test_scale_fact_adds_offset_when_scan_within_window():
    scale = {"2030-03-20": {"body_fat_pct": 30.0}, "2030-01-10": {"body_fat_pct": 31.0}}
    scan = {"date": "2030-03-25", "body_fat_pct": 27.5}
    f = _scale_fact(_facts(_flat(SYN_CONSISTENT_LOG), scans=[scan], scale=scale))
    off = f["basis"]["offset"]
    assert off["scale_day"] == "2030-03-20" and off["scan_day"] == "2030-03-25"
    assert off["scale_minus_scan"] == {"body_fat_pct": 2.5}
    assert "closest pair" in f["statement"]


# ── wording ───────────────────────────────────────────────────────────────────────────────────────


def test_no_forbidden_phrase_in_any_fact_on_any_path():
    scan = {"date": "2030-03-25", "body_fat_pct": 27.5, "weight_lb": SYN_START_WEIGHT}
    scale = {"2030-03-20": {"body_fat_pct": 30.0}}
    seen = 0
    for log in (SYN_CONSISTENT_LOG, SYN_LOW_LOG, SYN_HIGH_LOG):
        for scans in ([], [scan]):
            for f in _facts(_flat(log), scans=scans, scale=scale):
                text = _all_text(f)
                seen += 1
                for word in FORBIDDEN:
                    assert word not in text, f"{f['label']} says {word!r}"
                assert "measured intake" not in f["statement"].lower()
    assert seen >= 15
    src = (_REPO / "lambdas/health/grounded_intake_facts.py").read_text().lower()
    for word in FORBIDDEN:
        assert word not in src, word


# ── the module carries no personal literal ────────────────────────────────────────────────────────


def test_no_personal_literal_in_the_source():
    """No numeric literal >= 100 except as the value of a module-level UPPER_CASE named constant, and no string
    carrying a three-digit lb or four-digit kcal figure."""
    path = _REPO / "lambdas/health/grounded_intake_facts.py"
    tree = ast.parse(path.read_text())
    allowed = set()
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if all(isinstance(t, ast.Name) and t.id.isupper() for t in targets):
                allowed.update(id(n) for n in ast.walk(node))
    offenders = []
    for node in ast.walk(tree):
        if id(node) in allowed or not isinstance(node, ast.Constant):
            continue
        v = node.value
        if isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v) >= 100:
            offenders.append((node.lineno, v))
        if isinstance(v, str) and re.search(r"\b\d{3}(\.\d+)?\s*lb|\b\d,?\d{3}\s*kcal", v):
            offenders.append((node.lineno, v))
    assert not offenders, offenders


# ── ONE-IMPORTER guard (#6291) ────────────────────────────────────────────────────────────────────
# premerge-gate: sweeps lambdas/ and mcp/ for any import of the #6212 module (#2372)
# #6291 wired it through the switch-gated personal-context assembly ONLY; a second importer is a second,
# unevaluated path for these facts into a prompt.
ALLOWED_IMPORTERS = {"lambdas/coach/personal_context.py"}


def test_module_is_imported_only_by_the_personal_context_assembly():
    me = (_REPO / "lambdas/health/grounded_intake_facts.py").resolve()
    found = set()
    for root in ("lambdas", "mcp"):
        for py in (_REPO / root).rglob("*.py"):
            if py.resolve() == me:
                continue
            if "grounded_intake_facts" in py.read_text(errors="ignore"):
                found.add(str(py.relative_to(_REPO)))
    assert found == ALLOWED_IMPORTERS, f"#6212 facts reach a prompt only through coach.personal_context (#6291); importers: {sorted(found)}"
