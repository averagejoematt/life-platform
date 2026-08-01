"""tests/test_window_name_honesty_1917.py — #1917 window-name honesty, guarded as a SET.

THE DEFECT. `/api/vitals` published `weight_delta_30d: -4.1` and `hrv_30d_avg: 55.2`
on Day 6 of cycle 11. The arithmetic was honest — #1084 clamps live trailing windows
at genesis (ADR-077 "clamped, not hidden") so neither number reached into a prior
cycle. What was NOT honest was the NAME: a genesis-clamped window carried 6 days of
data under a key that claims 30. qa-smoke's reader_truth check flagged it, and since
qa-smoke is ci-cd's smoke oracle, it auto-rolled-back 100 healthy Lambdas.

WHY A DERIVED GUARD. The two offenders were found by an AI prose check, not by an
invariant — a third would not have been caught. `tests/test_honest_read_guards_1084.py`
already asserted these exact fields' min-n semantics and still missed the naming bug,
because it was written against the fields someone REMEMBERED. So this file does not
enumerate: it AST-scans `lambdas/web/` for every published `_Nd`-suffixed JSON key and
requires each to be REGISTERED below. A new window-named field fails this test until
its author states what window it really covers. See the memory note "guard the SET,
not the instance".

THE RUBRIC. Not every short window is a lie, and conflating the two would make the
guard noise. The distinction is extensive vs. intensive:

  * EXTENSIVE (counts, sums, totals) — "3 workouts in the last 30 days" is TRUE on
    Day 6. A count over a partly-elapsed window understates; it never overstates.
    These need only be declared.

  * INTENSIVE (averages, means, deltas, rates, percentages) — "30-day average = 55.2"
    computed from 6 days is a DIFFERENT CLAIM than its name makes. These must either
    gate the `_Nd`-named key on a genuinely full window, or carry an explicit,
    issue-linked `gap` recording that they do not yet.

`gap` is the honest escape hatch, and it is deliberately load-bearing: it keeps
un-fixed debt VISIBLE in a registry rather than invisible in the absence of a test.
"""

import ast
import json
import os
import pathlib
import re
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from web import site_api_vitals as vitals  # noqa: E402

_WEB = pathlib.Path(__file__).resolve().parent.parent / "lambdas" / "web"

# A published JSON key naming a day-window: foo_30d, hrv_30d_avg, avg_7d_g, ...
_WINDOW_KEY = re.compile(r"^(?:.*_)?(\d+)d(?:_.*)?$")

EXTENSIVE = "extensive"  # count/sum over the window — a short window understates, never overstates
INTENSIVE = "intensive"  # mean/delta/rate over the window — a short window MISSTATES

# ── the registry ────────────────────────────────────────────────────────────
# key -> (kind, gap). `gap` is None when the field is safe by kind (extensive) or
# genuinely gated (intensive); otherwise it is an issue reference explaining why an
# intensive field may still publish under a possibly-under-filled window name.
REGISTRY: dict[str, tuple[str, str | None]] = {
    # ── intensive + GATED by #1917 (the fix) ────────────────────────────────
    # These read None until the window they are named for is genuinely covered;
    # the real value ships alongside under a window-generic name.
    "weight_delta_30d": (INTENSIVE, None),
    "hrv_30d_avg": (INTENSIVE, None),
    "hrv_30d_n": (EXTENSIVE, None),  # an n, gated with its average so the pair never disagrees
    # `weight_delta_7d` is written by daily_brief over an exactly-7-day lookback
    # (week_ago_weight) and carries `weight_delta_window_days` — named for its real
    # window as of #1917, when it was corrected from `weight_delta_30d`.
    "weight_delta_7d": (INTENSIVE, None),
    # Found BY this scan, not by qa-smoke and not by reading: seven more means on
    # /api/glucose and /api/sleep, in the same file as the reported bug. They use
    # the PREFIX form (`30d_avg_mg_dl`), which every `_30d`-suffix grep — including
    # the one I ran first — misses. Gated identically.
    "30d_avg_mg_dl": (INTENSIVE, None),
    "30d_avg_tir": (INTENSIVE, None),
    "30d_avg_optimal": (INTENSIVE, None),
    "30d_avg_std": (INTENSIVE, None),
    "30d_avg_recovery": (INTENSIVE, None),
    "30d_avg_score": (INTENSIVE, None),
    "30d_avg_efficiency": (INTENSIVE, None),
    # ── intensive, NOT yet gated — declared debt, not silence ───────────────
    # Each publishes a mean/delta over a genesis-clamped window and so under-fills
    # its name on Day 1..N-1 of a cycle, exactly as /api/vitals did. None is as
    # reader-visible as the two qa-smoke caught: they are on lower-traffic
    # surfaces and several already ship an explicit n beside the claim (ADR-105),
    # which is a partial mitigation, not a fix.
    "mean_7d": (INTENSIVE, "#1919 — ships n_scored_7d beside it (ADR-105 partial mitigation)"),
    "mean_30d": (INTENSIVE, "#1919 — ships n_scored_30d beside it (ADR-105 partial mitigation)"),
    "trend_7d": (INTENSIVE, "#1919 — a per-day series, not a scalar claim; lower risk"),
    "trend_vs_prior_30d": (INTENSIVE, "#1919 — window-over-window comparison on a clamped window"),
    "cal_7d_avg": (INTENSIVE, "#1919 — nutrition 7d mean over a clamped window"),
    "pro_7d_avg": (INTENSIVE, "#1919 — nutrition 7d mean over a clamped window"),
    "avg_7d_g": (INTENSIVE, "#1919 — protein 7d mean surfaced to the AI layer"),
    "total_protein_30d_avg_g": (INTENSIVE, "#1919 — 30d mean over a clamped window"),
    "sleep_hours_30d_avg": (INTENSIVE, "#1919 — written by daily_brief, carried by site_stats_refresh"),
    "group_90d_avgs": (INTENSIVE, "#1919 — habit group means over a clamped 90d window"),
    "uptime_90d": (INTENSIVE, "#1919 — a percentage; platform uptime, not experiment-scoped data"),
    "composite_delta_1d": (INTENSIVE, None),  # a 1-day window is full from Day 2; nothing to under-fill
    # ── extensive: counts and sums. Safe by kind. ───────────────────────────
    "binge_days_30d": (EXTENSIVE, None),
    "count_30d": (EXTENSIVE, None),
    "daily_modality_minutes_30d": (EXTENSIVE, None),
    "distinct_exercises_30d": (EXTENSIVE, None),
    "journal_entries_30d": (EXTENSIVE, None),
    "n_scored_7d": (EXTENSIVE, None),
    "n_scored_30d": (EXTENSIVE, None),
    "orders_30d": (EXTENSIVE, None),
    "relapses_90d": (EXTENSIVE, None),
    "resisted_90d": (EXTENSIVE, None),
    "sessions_30d": (EXTENSIVE, None),
    "sessions_90d": (EXTENSIVE, None),
    "strength_sessions_30d": (EXTENSIVE, None),
    "total_interactions_30d": (EXTENSIVE, None),
    "total_miles_30d": (EXTENSIVE, None),
    "total_minutes_30d": (EXTENSIVE, None),
    "total_rucks_30d": (EXTENSIVE, None),
    "total_sets_30d": (EXTENSIVE, None),
    "total_spend_30d": (EXTENSIVE, None),
    "total_temptations_90d": (EXTENSIVE, None),
    "total_walks_30d": (EXTENSIVE, None),
    "workouts_30d": (EXTENSIVE, None),
    "workouts_90d": (EXTENSIVE, None),
    "z2_trailing_7d_min": (EXTENSIVE, None),
}


def _scan(root: pathlib.Path) -> dict[str, list[str]]:
    """Every string dict-key in `root`/*.py that names a day-window.

    Deliberately structural (ast) rather than textual: a regex over source would
    also match window names in comments, docstrings and local variables, none of
    which a reader ever sees. Only literal keys of dict displays are published.
    """
    found: dict[str, list[str]] = {}
    for path in sorted(root.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            if not isinstance(node, ast.Dict):
                continue
            for key in node.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str) and _WINDOW_KEY.match(key.value):
                    found.setdefault(key.value, []).append(f"{path.name}:{key.lineno}")
    return found


# ── the set guard ───────────────────────────────────────────────────────────


def test_every_published_window_field_is_registered():
    """A new `_Nd` field must state what window it really covers."""
    unregistered = {k: v for k, v in _scan(_WEB).items() if k not in REGISTRY}
    assert not unregistered, (
        "Unregistered window-named field(s) published by lambdas/web/.\n"
        "A key named for an N-day window is a claim about N days of data. Add each to\n"
        "REGISTRY in this file as EXTENSIVE (a count/sum — safe) or INTENSIVE (a\n"
        "mean/delta/rate — must gate on a full window, or carry an issue-linked gap):\n"
        + "\n".join(f"  {k}  ({', '.join(v)})" for k, v in sorted(unregistered.items()))
    )


def test_registry_has_no_dead_entries():
    """The registry decays into fiction if removed fields linger — keep it derived."""
    published = _scan(_WEB)
    dead = sorted(k for k in REGISTRY if k not in published)
    assert not dead, f"REGISTRY lists field(s) lambdas/web/ no longer publishes; delete them: {dead}"


def test_intensive_fields_are_gated_or_carry_a_declared_gap():
    """An average over a partly-elapsed window is a different claim than its name.

    Every INTENSIVE entry must either be gated (gap is None) or name the issue that
    tracks it. This is what keeps un-fixed debt visible instead of merely untested.
    """
    for key, (kind, gap) in sorted(REGISTRY.items()):
        if kind == INTENSIVE and gap is not None:
            assert gap.startswith("#"), f"{key}: an intensive field's gap must reference an issue, got {gap!r}"


def test_scanner_actually_fires_on_a_new_field(tmp_path):
    """Negative test: prove the scan catches an injected field.

    Without this, a scanner that silently matched nothing would pass every assertion
    above — the exact failure mode that let docs-ci report a green it never earned
    (#1908). Assert the mechanism, not just its current verdict.
    """
    (tmp_path / "site_api_injected.py").write_text('def h():\n    return {"fabricated_45d_avg": 1.0}\n')
    assert "fabricated_45d_avg" in _scan(tmp_path)
    assert "fabricated_45d_avg" not in REGISTRY, "the injected fixture name must not be registered"

    # ...and that it ignores a window name that is not a published key.
    (tmp_path / "site_api_comment.py").write_text('# hrv_99d_avg in a comment\nX = "hrv_99d_avg"\n')
    assert "hrv_99d_avg" not in _scan(tmp_path)


# ── the behavioural guard: /api/vitals on a short cycle ─────────────────────

_NOW = datetime.now(timezone.utc)


def _d(days_ago: int) -> str:
    return (_NOW - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def _whoop(date_str, hrv):
    return {"sk": f"DATE#{date_str}", "recovery_score": 66, "hrv": hrv, "resting_heart_rate": 52, "sleep_duration_hours": 7.2}


def _weigh(date_str, lbs):
    return {"sk": f"DATE#{date_str}", "weight_lbs": lbs}


@pytest.fixture
def short_cycle(monkeypatch):
    """Reproduce cycle 11 Day 6: genesis 5 days back, 3 weigh-ins, 5 HRV readings."""
    genesis = _d(5)
    data = {
        "whoop": [_whoop(_d(i), 50.0 + i) for i in range(5, 0, -1)],
        "withings": [_weigh(_d(5), 321.1), _weigh(_d(4), 316.3), _weigh(_d(0), 317.0)],
    }
    monkeypatch.setattr(vitals, "EXPERIMENT_START", genesis)

    def _fake_query_source(source, start, end, include_pilot=False):
        return [dict(r) for r in data.get(source, []) if start <= r["sk"].replace("DATE#", "") <= end]

    monkeypatch.setattr(vitals, "_query_source", _fake_query_source)
    monkeypatch.setattr(vitals, "_latest_item", lambda *_a, **_k: {})
    monkeypatch.setattr(vitals, "_latest_item_asof", lambda *_a, **_k: {})
    monkeypatch.setattr(
        vitals.vitals_resolver,
        "resolve_vitals",
        lambda *_a, **_k: {
            "recovery_pct": 96.0,
            "recovery_status": "green",
            "hrv_ms": 55.0,
            "rhr_bpm": 63.0,
            "recovery_as_of": _d(0),
            "sleep_hours": 7.4,
            "sleep_as_of": _d(0),
            "steps": None,
            "steps_source": None,
            "steps_as_of": None,
        },
    )
    return genesis


def test_window_named_keys_are_null_on_a_short_cycle(short_cycle):
    """The #1917 regression, verbatim: no `_30d` key may carry a value on Day 6.

    Reverting the gate in site_api_vitals.py fails exactly here.
    """
    v = json.loads(vitals.handle_vitals()["body"])["vitals"]
    assert v["weight_delta_30d"] is None, "a 5-day weight delta must not publish under a 30d name"
    assert v["hrv_30d_avg"] is None, "a 5-reading mean must not publish under a 30d name"
    assert v["hrv_30d_n"] is None, "n must vanish with the average it describes, or the pair contradicts itself"


def test_the_real_numbers_are_still_published(short_cycle):
    """ "Clamped, not hidden" (ADR-077): gating the NAME must not suppress the VALUE."""
    v = json.loads(vitals.handle_vitals()["body"])["vitals"]
    assert v["weight_delta_lbs"] == -4.1, "317.0 - 321.1, the real observed change"
    assert v["weight_delta_window_days"] == 5, "the span between the first and last weigh-in used"
    assert v["hrv_avg_ms"] is not None
    assert v["hrv_avg_n"] == 5
    assert v["hrv_avg_window_days"] == 5


def test_a_full_window_restores_the_window_named_keys(monkeypatch):
    """Date-independent: the same code publishes `_30d` once 30 days really elapsed."""
    genesis = _d(400)
    data = {
        "whoop": [_whoop(_d(i), 50.0 + i) for i in range(29, 0, -1)],
        "withings": [_weigh(_d(30), 321.1), _weigh(_d(0), 317.0)],
    }
    monkeypatch.setattr(vitals, "EXPERIMENT_START", genesis)
    monkeypatch.setattr(
        vitals,
        "_query_source",
        lambda source, start, end, include_pilot=False: [
            dict(r) for r in data.get(source, []) if start <= r["sk"].replace("DATE#", "") <= end
        ],
    )
    monkeypatch.setattr(vitals, "_latest_item", lambda *_a, **_k: {})
    monkeypatch.setattr(vitals, "_latest_item_asof", lambda *_a, **_k: {})
    monkeypatch.setattr(
        vitals.vitals_resolver,
        "resolve_vitals",
        lambda *_a, **_k: {
            "recovery_pct": 96.0,
            "recovery_status": "green",
            "hrv_ms": 55.0,
            "rhr_bpm": 63.0,
            "recovery_as_of": _d(0),
            "sleep_hours": 7.4,
            "sleep_as_of": _d(0),
            "steps": None,
            "steps_source": None,
            "steps_as_of": None,
        },
    )
    v = json.loads(vitals.handle_vitals()["body"])["vitals"]
    assert v["hrv_30d_avg"] is not None, "a genuinely 30-day window must publish under its name"
    assert v["hrv_30d_n"] == 29
    assert v["weight_delta_30d"] == -4.1, "a 30-day span publishes under the 30d name"
    assert v["weight_delta_window_days"] == 30
