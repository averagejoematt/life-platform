"""tests/test_genesis_blind_brief_windows_2089.py — the daily brief's two SHARED
raw-source readers go cross-phase (#2089).

`daily_brief_lambda._latest_item` and `::fetch_range` are the generic readers behind
the brief's reader-facing trend windows. Both applied the ADR-058 phase filter, and
the experiment reset tags every pre-genesis row `phase=pilot` (ADR-077), so on a
fresh cycle both saw only the days elapsed since genesis:

  * `_latest_item` is the #1203 shape verbatim — newest-first `Limit: 1`. DynamoDB
    applies `Limit` BEFORE `FilterExpression`, so it read the one newest row,
    discarded it for being pilot-tagged, and returned nothing: a pre-genesis
    DEXA / labs / body-measurements record vanished from the brief entirely.
  * `fetch_range` returned a window truncated at genesis, so the 7/30-day HRV
    trend, the 60-day Strava window behind Banister CTL/ATL/TSB and the
    14/30/90-day weight trends were computed over days-since-genesis — a "7-day
    HRV trend" on Day 2 being one point.

The contract is the one #2079/#2080/#2081 settled: the BODY's timeseries does not
reset when the experiment does, and the date window is what bounds recency — not
the phase tag. The fix derives the decision from `phase_taxonomy` per source rather
than hard-coding `include_pilot=True`, because these are GENERIC readers:
`fetch_range` is also called with `habit_scores`, which is EXPERIMENT_SCOPED, and a
blanket flip would have silently widened the Sunday habit review too.

These two functions build the partition key from the module-level `USER_PREFIX`
constant, so the #2079 AST ratchet — which keys on a literal `#SOURCE#` inside the
function body — structurally cannot see them and never carried debt records for
them (that blind spot is #2090). This file is the pin instead.

Structure follows tests/test_genesis_blind_reads_2080_2081.py, whose DynamoDB fake
is reused rather than re-implemented (one definition of "Limit lands before the
filter"):

  1. a non-vacuous anchor — the fixture really reproduces the blindfold, asserted
     against the pre-#2089 read behaviour, so nothing below tests nothing;
  2. the instances — a genesis-day fixture for every window the issue names;
  3. the negative cases — the window still bounds the answer, an absent source is
     still absent, and the one EXPERIMENT_SCOPED caller stays current-cycle;
  4. the SET, derived by AST from the brief's own call sites and checked against
     phase_taxonomy, so a future call site cannot inherit either behaviour by
     accident.

Every date here is PINNED (`_TODAY`, `_GENESIS`, `_YESTERDAY`); nothing does
now-math against the wall clock, so this file cannot start failing on a calendar
boundary.
"""

from __future__ import annotations

import ast
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")

sys.path.insert(0, str(REPO_ROOT / "tests"))
sys.path.insert(0, str(REPO_ROOT / "lambdas"))
sys.path.insert(0, str(REPO_ROOT / "lambdas" / "emails"))

import daily_brief_lambda as brief  # noqa: E402
from content import html_builder  # noqa: E402
from experiment import phase_taxonomy as tax  # noqa: E402
from test_genesis_blind_reads_2080_2081 import PhaseAwareFakeTable, _rows  # noqa: E402

# Pinned clock. _GENESIS == _TODAY is "the reset happened this morning" — the worst
# case for this defect, and the one cycle 12 actually shipped (a same-day genesis).
_TODAY = date(2026, 8, 3)
_GENESIS = _TODAY
_YESTERDAY = (_TODAY - timedelta(days=1)).isoformat()

_BRIEF_SRC = (REPO_ROOT / "lambdas" / "emails" / "daily_brief_lambda.py").read_text()


def _win(days: int) -> tuple[str, str]:
    """The brief's own window shape: (today - days) .. yesterday, inclusive."""
    return (_TODAY - timedelta(days=days)).isoformat(), _YESTERDAY


def _series(source: str, field: str, days: int, value, end: date = _TODAY - timedelta(days=1)):
    """`days` consecutive daily rows ending at `end`, pilot-tagged before genesis."""
    return _rows(
        f"USER#matthew#SOURCE#{source}",
        field,
        {end - timedelta(days=i): value(i) for i in range(days)},
        genesis=_GENESIS,
    )


def _strava_series(days: int, minutes: float = 60.0):
    """Strava day records carrying one walk each — real `activities` payloads, so
    the Banister assertions run the production load model, not a stub."""
    rows = _series("strava", "activities", days, lambda i: [{"type": "Walk", "moving_time_seconds": minutes * 60}])
    return rows


@pytest.fixture
def genesis_day(monkeypatch):
    """The whole fixture: 90 days of history, every row pre-genesis and therefore
    pilot-tagged, plus one periodic record per `_latest_item` source."""
    rows = []
    # HRV: 60 for the trailing week, 50 before it — a trend the 7d/30d comparison
    # can actually resolve, and a flat 7d-only window cannot.
    rows += _series("whoop", "hrv", 30, lambda i: 60.0 if i < 7 else 50.0)
    rows += _strava_series(60)
    rows += _series("withings", "weight_lbs", 90, lambda i: 320.0 + i * 0.1)
    rows += _series("apple_health", "steps", 7, lambda i: 8000.0 + i)
    rows += _series("habitify", "completed", 7, lambda i: float(i))
    rows += _series("supplements", "taken", 7, lambda i: float(i))
    # habit_scores is EXPERIMENT_SCOPED — the Sunday review is a current-cycle view.
    rows += _series("habit_scores", "score", 7, lambda i: 80.0 - i)
    # Periodic records read by _latest_item — each newest row is pre-genesis, which
    # is the normal state of a DEXA/labs partition on any given day.
    rows += _rows("USER#matthew#SOURCE#dexa", "body_fat_pct", {date(2026, 6, 14): 41.2}, genesis=_GENESIS)
    rows += _rows("USER#matthew#SOURCE#measurements", "waist_in", {date(2026, 7, 20): 52.5}, genesis=_GENESIS)
    rows += _rows("USER#matthew#SOURCE#labs", "hba1c", {date(2026, 5, 2): 5.9}, genesis=_GENESIS)
    table = PhaseAwareFakeTable(rows)
    monkeypatch.setattr(brief, "table", table)
    return table


@pytest.fixture
def pre_fix(monkeypatch):
    """Restore the pre-#2089 read: the phase filter on every source, no exceptions.

    Used only by the anchor tests below, which assert the blindfold is reproducible
    in this fixture — the point being that the guards are non-vacuous.
    """
    monkeypatch.setattr(brief, "_source_reads_cross_phase", lambda source: False)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Non-vacuous anchor — the fixture reproduces the blindfold
# ══════════════════════════════════════════════════════════════════════════════


def test_pre_fix_latest_item_loses_the_pre_genesis_record(genesis_day, pre_fix):
    """The #1203 mechanism, on this fixture: Limit:1 newest-first reads the one
    pilot-tagged row and the filter drops it, so the brief's "latest measurements"
    line reports nothing at all."""
    assert brief._latest_item("dexa") is None
    assert brief._latest_item("measurements") is None
    assert brief._latest_item("labs") is None


def test_pre_fix_windows_come_back_empty_on_genesis_day(genesis_day, pre_fix):
    """…and the range half: on Day 1 every window is entirely pre-genesis, so a
    phase-filtered read returns nothing to trend over."""
    assert brief.fetch_range("whoop", *_win(30)) == []
    assert brief.fetch_range("strava", *_win(60)) == []
    assert brief.fetch_range("withings", *_win(90)) == []


def test_pre_fix_hrv_trend_and_tsb_degenerate(genesis_day, pre_fix):
    """The two reader-facing numbers the issue names, computed the way the brief
    computes them, on the pre-fix read: no trend, and no load model.

    #2221: the TSB half used to assert 0.0 — the "zeroed load model" this issue was
    about, where an empty window produced a number the readiness scorer read as
    balanced form. `compute_tsb` now returns absence for an empty window, so the
    degenerate read is degenerate all the way to the reader rather than arriving as
    a fabricated mid-scale figure. The blindness this test pins is unchanged; only
    what the blindness now LOOKS like has moved.
    """
    hrv_7d = [float(r["hrv"]) for r in brief.fetch_range("whoop", *_win(7)) if "hrv" in r]
    hrv_30d = [float(r["hrv"]) for r in brief.fetch_range("whoop", *_win(30)) if "hrv" in r]
    assert hrv_7d == [] and hrv_30d == []
    assert html_builder.hrv_trend_str(None, None) == "no trend data"
    assert brief.compute_tsb(brief.fetch_range("strava", *_win(60)), _TODAY) is None


# ══════════════════════════════════════════════════════════════════════════════
# 2. The instances — every window the issue names, on genesis day
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "source,expected",
    [("dexa", "body_fat_pct"), ("measurements", "waist_in"), ("labs", "hba1c")],
)
def test_latest_item_returns_the_pre_genesis_record(genesis_day, source, expected):
    """Acceptance: on genesis day `_latest_item` still returns the newest DEXA /
    body-measurement / labs record, even though it predates the reset."""
    item = brief._latest_item(source)
    assert item is not None, f"{source}: the latest record vanished after the reset"
    assert expected in item


def test_latest_item_returns_the_newest_row_not_just_any_row(genesis_day):
    """Newest-first is preserved: two pre-genesis DEXA rows, the later one wins."""
    genesis_day.rows.extend(_rows("USER#matthew#SOURCE#dexa", "body_fat_pct", {date(2026, 7, 30): 39.8}, genesis=_GENESIS))
    assert brief._latest_item("dexa")["body_fat_pct"] == pytest.approx(39.8)


@pytest.mark.parametrize("days", [7, 30])
def test_hrv_windows_are_whole_across_genesis(genesis_day, days):
    """The 7/30-day HRV windows hold every day in them, not just days-since-genesis."""
    assert len(brief.fetch_range("whoop", *_win(days))) == days


def test_hrv_trend_resolves_on_genesis_day(genesis_day):
    """The scorecard's HRV trend phrase, built exactly as the brief builds it
    (lines ~573-577 + html_builder.hrv_trend_str), reads a real trend on Day 1."""
    hrv_7d = [float(r["hrv"]) for r in brief.fetch_range("whoop", *_win(7)) if "hrv" in r]
    hrv_30d = [float(r["hrv"]) for r in brief.fetch_range("whoop", *_win(30)) if "hrv" in r]
    assert len(hrv_7d) == 7 and len(hrv_30d) == 30
    phrase = html_builder.hrv_trend_str(sum(hrv_7d) / len(hrv_7d), sum(hrv_30d) / len(hrv_30d))
    assert phrase != "no trend data"
    assert "trending up" in phrase  # 60 over the week vs a 30-day mean pulled down by the 50s


def test_banister_runs_over_the_whole_60_day_window(genesis_day):
    """The 60-day Strava window behind CTL/ATL/TSB. Fully loaded, a steady 60-day
    walking block sits near equilibrium (CTL ≈ ATL, |TSB| small); truncated to
    zero days it collapses to 0.0, which downstream reads as perfect freshness."""
    strava_60d = brief.fetch_range("strava", *_win(60))
    assert len(strava_60d) == 60
    ctl, atl, tsb = brief.training_load.compute_ctl_atl_tsb(strava_60d, _TODAY)
    assert ctl > 0 and atl > 0
    assert tsb != 0.0
    assert brief.compute_tsb(strava_60d, _TODAY) == tsb


@pytest.mark.parametrize("days", [14, 30, 90])
def test_weight_windows_are_whole_across_genesis(genesis_day, days):
    """The 14/30/90-day weight-trend windows (brief lines ~584, 593, 610, 629)."""
    assert len(brief.fetch_range("withings", *_win(days))) == days


def test_weight_trend_has_both_ends_on_genesis_day(genesis_day):
    """Mirrors the brief's own latest-weight and week-ago-weight derivations. Both
    ends of the weekly delta exist on Day 1 instead of the delta blanking."""
    recent = brief.fetch_range("withings", *_win(30))
    latest = next((brief.safe_float(w, "weight_lbs") for w in reversed(recent) if brief.safe_float(w, "weight_lbs")), None)

    week_ago = None
    target = (_TODAY - timedelta(days=7)).isoformat()
    for w in brief.fetch_range("withings", *_win(14)):
        if w.get("sk", "").replace("DATE#", "") <= target:
            week_ago = brief.safe_float(w, "weight_lbs") or week_ago

    assert latest is not None and week_ago is not None
    assert latest != week_ago, "a weekly delta needs two distinct ends"


def test_the_other_cross_phase_windows_are_whole(genesis_day):
    """apple_health (7d CGM context), habitify (7d) and supplements (7d, CROSS_PHASE
    by ADR-077 dec A — medication safety, never hidden)."""
    assert len(brief.fetch_range("apple_health", *_win(7))) == 7
    assert len(brief.fetch_range("habitify", *_win(7))) == 7
    assert len(brief.fetch_range("supplements", *_win(7))) == 7


# ══════════════════════════════════════════════════════════════════════════════
# 3. The negative cases — the fix widened the phase tag, not the question
# ══════════════════════════════════════════════════════════════════════════════


def test_the_window_still_bounds_the_answer(genesis_day):
    """Cross-phase is not unbounded: a 7-day window over a 90-day partition still
    returns 7 rows. The date range is what answers "recent", as the contract says."""
    assert len(brief.fetch_range("withings", *_win(7))) == 7
    assert len(brief.fetch_range("withings", "2026-01-01", "2026-01-05")) == 0


def test_an_absent_source_is_still_absent(genesis_day):
    """A source with no rows at all still reads empty — the fix does not invent data."""
    assert brief._latest_item("eightsleep") is None
    assert brief.fetch_range("eightsleep", *_win(30)) == []


def test_experiment_scoped_habit_scores_stays_current_cycle(genesis_day):
    """`fetch_range` is generic and IS called with habit_scores (the Sunday weekly
    habit review), which phase_taxonomy classes EXPERIMENT_SCOPED — derived
    intelligence the reset tombstones on purpose. A blanket include_pilot=True would
    have widened it silently; the taxonomy-derived flip must not."""
    assert tax.classify("USER#matthew#SOURCE#habit_scores") == tax.EXPERIMENT_SCOPED
    assert brief.fetch_range("habit_scores", *_win(7)) == []
    assert genesis_day.query_calls[-1].get("FilterExpression"), "the scoped read lost its phase filter"


def test_cross_phase_reads_carry_no_filter_expression(genesis_day):
    """The complement: a non-scoped read must not send the phase FilterExpression
    at all — asserting the mechanism, not just the row count."""
    brief.fetch_range("whoop", *_win(7))
    assert "FilterExpression" not in genesis_day.query_calls[-1]
    brief._latest_item("dexa")
    assert "FilterExpression" not in genesis_day.query_calls[-1]


def test_an_unclassified_source_keeps_the_current_cycle_filter(genesis_day):
    """Fail-soft and conservative: phase_taxonomy.classify raises for an unknown
    source by design, and the reader must fall back to the PRE-fix behaviour rather
    than silently widening a read nobody has classified."""
    assert brief._source_reads_cross_phase("not_a_real_source_2089") is False
    brief.fetch_range("not_a_real_source_2089", *_win(7))
    assert genesis_day.query_calls[-1].get("FilterExpression")


# ══════════════════════════════════════════════════════════════════════════════
# 4. The SET — derived from the brief's own call sites, checked against the taxonomy
# ══════════════════════════════════════════════════════════════════════════════


def _literal_sources_read_by(*func_names: str) -> set[str]:
    """Every literal source name the brief passes to the named readers (AST-derived,
    so a call site added later is covered without editing this file)."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(_BRIEF_SRC)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id not in func_names:
            continue
        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            found.add(node.args[0].value)
    return found


def test_the_derivation_finds_the_known_call_sites():
    """Prove the AST derivation fires before trusting it to guard anything."""
    sources = _literal_sources_read_by("_latest_item", "fetch_range")
    assert {"dexa", "labs", "measurements", "whoop", "strava", "withings", "habit_scores"} <= sources


def test_every_source_these_readers_touch_is_classified():
    """No source reaches `_latest_item` / `fetch_range` without a taxonomy class —
    an unclassified one would silently take the conservative (genesis-blind) branch."""
    unclassified = sorted(s for s in _literal_sources_read_by("_latest_item", "fetch_range") if s not in tax.SOURCE_CLASS)
    assert not unclassified, (
        "these sources are read by the brief's shared readers but are absent from "
        "phase_taxonomy.SOURCE_CLASS, so their reads fall back to the genesis-blind "
        "branch: " + ", ".join(unclassified)
    )


def test_the_read_decision_agrees_with_the_taxonomy():
    """The guard on the SET rather than the instance: for every source these readers
    actually touch, the cross-phase decision equals "not EXPERIMENT_SCOPED"."""
    for source in sorted(_literal_sources_read_by("_latest_item", "fetch_range")):
        expected = tax.classify(f"USER#matthew#SOURCE#{source}") != tax.EXPERIMENT_SCOPED
        assert brief._source_reads_cross_phase(source) is expected, f"{source}: read decision disagrees with phase_taxonomy"


def test_both_readers_route_through_the_taxonomy_decision():
    """A revert-catcher at the source level: neither reader may call
    `with_phase_filter` without passing the derived decision. Cheap, and it fires on
    exactly the edit that would silently restore #2089."""
    tree = ast.parse(_BRIEF_SRC)
    for name in ("_latest_item", "fetch_range"):
        func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
        seg = (ast.get_source_segment(_BRIEF_SRC, func) or "").replace(" ", "")
        assert "with_phase_filter(" in seg
        assert "include_pilot=_source_reads_cross_phase(source)" in seg, f"{name} no longer derives its phase scope (#2089)"
