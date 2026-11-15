"""tests/test_surge_baseline_excludes_reading_5936.py — #5936: the surge bar is set by the PRIOR weeks.

THE DEFECT
──────────
`cost_governor_lambda` read the weekly `UniqueVisitors7d` series twice, both windows ending
at `now`: once for the reading under test (the newest point) and once for the baseline the
engage bar is derived from (`mean + 3*SD`). The newest point sat in both, so a traffic jump
raised its own bar. On the recorded series (aggregate site traffic, public in the issue)

    1116, 1158, 1255, 1032, 977, 1278, 1547, 2603

the bar was 2955 with 2603 inside the baseline, and 1765 over the seven readings before it.
A ~2.2x reader arrival — exactly what ADR-133's surge ceiling exists for — did not engage.
Structurally it never could: a point inside a sample of n sits at most (n-1)/sqrt(n) SD above
that sample's mean (2.47 for n=8), below the K=3 the rule uses.

WHAT EACH TEST OWNS
───────────────────
  A. the regression: the recorded series yields bar 1765 and surge engages, through the
     pure split AND through the handler's own CloudWatch read.
  B. the contract: across shapes of series, the baseline never contains the reading under
     test, and always ends strictly before it.
  C. the counter-case: a flat series does not engage, so A cannot pass by engaging always.
"""

from datetime import datetime, timedelta, timezone

import pytest
from operational import cost_governor_surge as surge

RECORDED_SERIES = [1116, 1158, 1255, 1032, 977, 1278, 1547, 2603]
# Frozen clock (#4848): passed as the functions' own `now` argument, so nothing here reads the
# wall clock. The digest emits Sundays 17:00 PT; the governor runs within the week.
FROZEN_NOW = datetime(2026, 11, 14, 1, 0, tzinfo=timezone.utc)
LAST_READING_AT = datetime(2026, 11, 9, 0, 0, tzinfo=timezone.utc)


def _weekly_points(values, last_at=LAST_READING_AT):
    """Oldest-first values -> [(timestamp, value)] one week apart, ending at `last_at`."""
    n = len(values)
    return [(last_at - timedelta(days=7 * (n - 1 - i)), v) for i, v in enumerate(values)]


@pytest.fixture
def gov():
    from operational import cost_governor_lambda

    return cost_governor_lambda


# ── A. the regression on the recorded series ─────────────────────────────────────────────
def test_a_recorded_series_bar_is_1765_and_surge_engages():
    recent, baseline = surge.split_reading_and_baseline(_weekly_points(RECORDED_SERIES), FROZEN_NOW)
    assert recent == 2603
    assert baseline == RECORDED_SERIES[:-1], baseline
    threshold, rule = surge.surge_threshold_from_baseline(baseline)
    assert threshold == 1765, rule
    assert "n=7" in rule, rule
    decision = surge.decide(recent, threshold, prev_surge_active=False)
    assert decision.active is True, f"2603 against bar {threshold} did not engage"
    # The defect, kept as the mutation witness: with the reading inside, the bar is 2955
    # and the same reading cannot engage.
    bad_threshold, _ = surge.surge_threshold_from_baseline(RECORDED_SERIES)
    assert bad_threshold == 2955
    assert surge.decide(2603, bad_threshold, prev_surge_active=False).active is False


def test_a_handler_read_splits_the_recorded_series(gov, monkeypatch):
    """The Lambda's own read path, fed the recorded series as CloudWatch datapoints."""
    datapoints = [{"Timestamp": ts, "Maximum": float(v)} for ts, v in _weekly_points(RECORDED_SERIES)]
    seen = {}

    class _CW:
        def get_metric_statistics(self, **kw):
            seen.update(kw)
            assert kw["MetricName"] == "UniqueVisitors7d"
            return {"Datapoints": list(reversed(datapoints))}

    monkeypatch.setattr(gov, "_cw", _CW())
    recent, baseline = gov._surge_reading_and_baseline(FROZEN_NOW)
    assert (recent, baseline) == (2603, RECORDED_SERIES[:-1])
    assert gov.surge_threshold_from_baseline(baseline)[0] == 1765
    # The window must reach far enough back to hold a full baseline BEFORE the reading.
    assert seen["StartTime"] <= LAST_READING_AT - timedelta(days=7 * gov.SURGE_BASELINE_WEEKS)


# ── B. the contract: the baseline never contains the reading under test ─────────────────
def test_b_baseline_never_contains_the_reading_under_test():
    """Every shape is checked by TIMESTAMP, not by value — a repeated value elsewhere in the
    series is legitimate; the reading's own point inside its baseline is not. One test that
    iterates and reports every offender (a parametrized gate counts once per parameter)."""
    offenders = []
    for n_points in (0, 1, 2, 5, 8, 9, 12):
        values = [1000 + 37 * i for i in range(n_points)]
        pts = _weekly_points(values)
        recent, baseline = surge.split_reading_and_baseline(pts, FROZEN_NOW)
        if not pts:
            if (recent, baseline) != (None, []):
                offenders.append((n_points, recent, baseline))
            continue
        latest_ts, latest_val = max(pts, key=lambda p: p[0])
        prior = [v for ts, v in sorted(pts) if ts < latest_ts]
        if (
            recent != latest_val
            or baseline != prior[-surge.SURGE_BASELINE_WEEKS :]
            or latest_val in baseline  # values are distinct here, so this IS the point
            or len(baseline) > surge.SURGE_BASELINE_WEEKS
        ):
            offenders.append((n_points, recent, baseline))
    assert not offenders, f"baseline contained or mis-ended at the reading under test: {offenders}"


def test_b_baseline_ends_before_the_reading_even_with_a_same_value_week():
    """A prior week equal to the reading stays in the baseline (it is a different week);
    only the reading's own point is excluded."""
    values = [1200, 1100, 1200]
    recent, baseline = surge.split_reading_and_baseline(_weekly_points(values), FROZEN_NOW)
    assert recent == 1200 and baseline == [1200, 1100]


def test_b_stale_series_has_no_reading_under_test():
    """Nothing in the lookback -> no signal (None), which `decide` fails closed on."""
    stale_last = FROZEN_NOW - timedelta(days=surge.SURGE_RECENT_LOOKBACK_DAYS + 1)
    recent, _baseline = surge.split_reading_and_baseline(_weekly_points(RECORDED_SERIES, stale_last), FROZEN_NOW)
    assert recent is None
    assert surge.decide(recent, 1765, prev_surge_active=False).active is False


# ── C. the counter-case ─────────────────────────────────────────────────────────────────
def test_c_a_flat_series_does_not_engage():
    flat = [1100, 1120, 1090, 1110, 1105, 1095, 1115, 1112]
    recent, baseline = surge.split_reading_and_baseline(_weekly_points(flat), FROZEN_NOW)
    threshold, rule = surge.surge_threshold_from_baseline(baseline)
    assert surge.decide(recent, threshold, prev_surge_active=False).active is False, rule
