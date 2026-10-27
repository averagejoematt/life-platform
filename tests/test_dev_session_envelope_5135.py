"""tests/test_dev_session_envelope_5135.py — the dev-session envelope (#5135).

On 2026-10-18 dev sessions metered $27.37 in one UTC day while the #4589 laptop cap
($5 a run, $10 in any 24 hours) was live. The spend was two bursts, both on the laptop
(`LambdaFunction=dev-session`): the Story Desk season re-stage at `DEV_AI_BUDGET_USD=20`
plus repair passes (04:15–05:40Z, $16.87), then three more repair passes (17:45–18:25Z,
$10.47) started while the trailing 24 hours already held $16.87 — so only a run with a
named number could send at all. As shipped, a named number switched the 24-hour check off
for its run, and nothing bounded the sum of named runs.

What is held here:
  * a REPLAY of that day's real 5-minute series (read-only CloudWatch, the
    `CallerClass=dev-session` copy of `LifePlatform/AI` `EstimatedCostUSD`) through
    `decide`: as shipped every dollar goes; now the day stops at the largest number named;
  * a replay of October's real hourly series: the month stops at the owner's $60;
  * the month is checked first and no named number lifts it, and its refusal does not
    advertise an override that cannot help;
  * the windows are re-read during a run, so a concurrent lane's spend is seen;
  * the MCP Lambda's dev-session calls are counted (same series) but never refused;
  * the cost governor publishes the month as `DevSessionSpendMTD`, and the alarm bar is
    derived from the cap module (80 % of $60), never typed twice.

Dollar figures only — no health data. Run: python3 -m pytest tests/test_dev_session_envelope_5135.py -v
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import budget_ceilings  # noqa: E402
from ai import bedrock_client as bc, budget_guard, dev_session_cap as cap  # noqa: E402

# ── the metering rows (read 2026-10-25, get-metric-statistics, CallerClass=dev-session) ──
# 2026-10-18, 5-minute Sums: (bucket start UTC, dollars, calls). Total $27.37, 265 calls.
OCT18_5MIN = (
    ("04:15", 0.273, 5), ("04:20", 0.869, 13), ("04:25", 1.032, 11), ("04:30", 1.265, 11),
    ("04:35", 1.072, 8), ("04:40", 1.271, 10), ("04:45", 1.574, 12), ("04:50", 0.269, 2),
    ("05:00", 0.600, 12), ("05:05", 1.127, 14), ("05:10", 1.350, 14), ("05:15", 1.356, 12),
    ("05:20", 1.057, 9), ("05:25", 1.401, 11), ("05:30", 1.292, 10), ("05:35", 1.065, 8),
    ("17:00", 0.015, 8), ("17:45", 0.314, 3), ("17:50", 0.922, 8), ("17:55", 0.822, 9),
    ("18:00", 1.823, 16), ("18:05", 1.932, 15), ("18:10", 1.418, 11), ("18:15", 1.676, 17),
    ("18:20", 1.563, 12), ("21:10", 0.007, 4),
)  # fmt: skip
# Month-to-date dev-session spend before 10-18 04:00Z (10-01..10-17), and October's later
# hourly rows (bucket, dollars) after the 10-18 day, through 10-25 22:00Z.
OCT_BEFORE_18TH = 30.91
OCT_AFTER_18TH = (
    ("10-23 18", 3.403), ("10-25 00", 0.010), ("10-25 02", 0.005), ("10-25 03", 0.002),
    ("10-25 06", 1.185), ("10-25 07", 0.491), ("10-25 14", 0.011), ("10-25 16", 0.010),
    ("10-25 17", 0.005), ("10-25 22", 0.011),
)  # fmt: skip
LARGEST_NUMBER_NAMED_ON_THE_18TH = 20.0  # season_rebuild.py at DEV_AI_BUDGET_USD=20 (docs/alarm_citations.json)


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _calls(rows):
    """Each 5-minute bucket as its individual calls, the bucket's dollars split evenly."""
    for t, usd, n in rows:
        for _ in range(n):
            yield _minutes(t), usd / n


def _bursts():
    """The two runs of the day (the 17:00 / 21:10 crumbs are the MCP Lambda and a probe)."""
    first = [c for c in _calls(OCT18_5MIN) if _minutes("04:15") <= c[0] < _minutes("06:00")]
    second = [c for c in _calls(OCT18_5MIN) if _minutes("17:45") <= c[0] < _minutes("19:00")]
    return first, second


def _decide_as_shipped_4589(run_spent, day_before_run, override):
    """The #4589 rule this issue found the gap in, kept verbatim for the before/after."""
    if override is not None:
        return "over" if run_spent >= override else None
    if run_spent >= cap.PER_RUN_USD:
        return "over"
    return "over" if day_before_run + run_spent >= cap.PER_DAY_USD else None


def _replay(runs, decide, override, month_before=OCT_BEFORE_18TH):
    """Send each run's calls in order through `decide`; a run stops at its first refusal.
    Returns the dollars that went, per run. All runs fall inside one trailing 24 hours."""
    sent_per_run, sent_before = [], 0.0
    for calls in runs:
        run_spent = 0.0
        for _t, usd in calls:
            if decide is _decide_as_shipped_4589:
                reason = decide(run_spent, sent_before, override)
            else:
                reason = decide(run_spent, sent_before, override, month_before + sent_before)
            if reason is not None:
                break
            run_spent += usd
        sent_per_run.append(run_spent)
        sent_before += run_spent
    return sent_per_run


# ── box 1 + 2: the replay ────────────────────────────────────────────────────────────
def test_the_fixture_is_the_metered_day():
    assert sum(usd for _t, usd, _n in OCT18_5MIN) == pytest.approx(27.37, abs=0.01)
    assert sum(n for _t, _u, n in OCT18_5MIN) == 265
    first, second = _bursts()
    assert sum(u for _t, u in first) == pytest.approx(16.87, abs=0.01)
    assert sum(u for _t, u in second) == pytest.approx(10.47, abs=0.01)


def test_as_shipped_the_named_runs_stacked_and_every_dollar_went():
    """The gap, reproduced: under the #4589 rule each named run is inside its own cap and
    the day check is off for it, so both bursts go in full ($27.34 of the $27.37)."""
    sent = _replay(_bursts(), _decide_as_shipped_4589, LARGEST_NUMBER_NAMED_ON_THE_18TH)
    assert sum(sent) == pytest.approx(27.34, abs=0.01)


def test_now_the_same_traffic_stops_at_the_largest_number_named():
    """Same calls, same named number, current rule: the first burst goes ($16.87 < $20),
    the second stops when the 24-hour total reaches $20. One call's overshoot at most."""
    first, second = _bursts()
    biggest_call = max(u for _t, u in first + second)
    sent = _replay([first, second], cap.decide, LARGEST_NUMBER_NAMED_ON_THE_18TH)
    assert sent[0] == pytest.approx(16.87, abs=0.01)
    assert sum(sent) <= LARGEST_NUMBER_NAMED_ON_THE_18TH + biggest_call
    assert sum(sent) < 27.37 - 7.0, sent


def test_now_the_second_burst_naming_its_own_10_dollars_never_starts():
    """Session BY's three passes ran against a '$10 allowance' with $16.87 already in the
    window. A named $10 is now a ceiling on the 24-hour total, so the first call is refused."""
    first, second = _bursts()
    passes = [second[:33], second[33:66], second[66:]]
    sent = _replay([first] + passes, cap.decide, 10.0)
    assert sent[1:] == [0.0, 0.0, 0.0], sent
    window = sum(u for _t, u in first)
    assert "does not add to it" in cap.decide(0.0, window, 10.0, OCT_BEFORE_18TH + window)


def test_with_no_number_named_the_day_stops_at_ten_dollars():
    first, second = _bursts()
    biggest_call = max(u for _t, u in first + second)
    # Even split into many small runs (each under $5), the day still stops at $10.
    small_runs = [first[i : i + 20] for i in range(0, len(first), 20)] + [second]
    sent = _replay(small_runs, cap.decide, None)
    assert sum(sent) <= cap.PER_DAY_USD + biggest_call


def test_october_replayed_stops_at_the_monthly_envelope_whatever_number_is_named():
    """October's real dev-session series, every run naming $1,000: only the month binds.
    The month crossed $60 on 10-23 at 18:00Z (cum $61.68); from there nothing goes."""
    hours = [("10-18 " + t[:2], usd) for t, usd, _n in OCT18_5MIN] + list(OCT_AFTER_18TH)
    month, sent, refused_from = OCT_BEFORE_18TH, 0.0, None
    for bucket, usd in hours:
        if cap.decide(0.0, 0.0, 1000.0, month) is not None:
            refused_from = refused_from or bucket
            continue
        month += usd
        sent += usd
    assert month <= cap.PER_MONTH_USD + max(u for _b, u in hours)
    assert refused_from is not None and refused_from.startswith(("10-23", "10-25")), refused_from
    assert month < OCT_BEFORE_18TH + 27.37 + sum(u for _b, u in OCT_AFTER_18TH), "October's actual total was $63.42"


# ── the pure rule ────────────────────────────────────────────────────────────────────
def test_the_month_is_checked_first_and_no_named_number_lifts_it():
    assert cap.decide(0.0, 0.0, None, cap.PER_MONTH_USD - 0.01) is None
    said = cap.decide(0.0, 0.0, 500.0, cap.PER_MONTH_USD)
    assert said and "this calendar month" in said and "does not raise it" in said
    assert "$60.00" in cap.decide(1.0, 0.0, None, cap.PER_MONTH_USD - 1.0)


def test_the_owner_numbers_are_the_ruling():
    assert cap.PER_MONTH_USD == 60.0 and cap.MONTH_ALARM_FRACTION == 0.8, "owner ruling 2026-10-26 on #5135"
    assert budget_ceilings.dev_session_month_cap_usd() == 60.0
    assert budget_ceilings.dev_session_month_alarm_usd() == 48.0


def test_the_month_read_starts_at_00z_on_the_first():
    cw = MagicMock()
    cw.get_metric_statistics.return_value = {"Datapoints": [{"Sum": 30.0}, {"Sum": 1.5}]}
    now = datetime(2026, 10, 18, 4, 30, tzinfo=timezone.utc)
    assert cap.read_month_spend(cw, now) == 31.5
    kw = cw.get_metric_statistics.call_args.kwargs
    assert kw["StartTime"] == datetime(2026, 10, 1, tzinfo=timezone.utc) and kw["EndTime"] == now
    assert kw["Dimensions"] == [{"Name": "CallerClass", "Value": "dev-session"}]
    cw.reset_mock()
    assert cap.read_month_spend(cw, datetime(2026, 11, 1, 0, 0, 10, tzinfo=timezone.utc)) == 0.0
    assert cw.get_metric_statistics.call_count == 0, "no read across an empty window at rollover"


# ── through the chokepoint ───────────────────────────────────────────────────────────
ONE_CALL_USAGE = {"input_tokens": 1_000_000, "output_tokens": 0}  # $3.00 on Sonnet
SONNET = "us.anthropic.claude-sonnet-4-6"


class _Windows:
    """A fake CloudWatch that answers the day read and the month read separately."""

    def __init__(self, day=0.0, month=0.0):
        self.day, self.month, self.reads = day, month, 0

    def get_metric_statistics(self, **kw):
        self.reads += 1
        span_h = (kw["EndTime"] - kw["StartTime"]).total_seconds() / 3600
        value = self.day if abs(span_h - cap.DAY_WINDOW_HOURS) < 1e-6 else self.month
        return {"Datapoints": [{"Sum": value}]}

    def put_metric_data(self, **_kw):
        return None


@pytest.fixture
def laptop(monkeypatch):
    for var in ("AWS_LAMBDA_FUNCTION_NAME", "GITHUB_ACTIONS", "CI", "INVOCATION_CONTEXT", "BEDROCK_SHADOW_MODE", cap.OVERRIDE_ENV):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DEV_AI_CAP_UNDER_TEST", "1")
    # The envelope starts 2026-11-01 (#5406); these tests are about the envelope once it exists,
    # so they must not depend on the wall clock. tests/test_dev_session_effective_from_5406.py
    # holds the dated edge itself.
    monkeypatch.setattr(cap, "MONTH_CAP_EFFECTIVE_FROM", date(2026, 10, 1))
    cap._reset_for_tests()
    bedrock = MagicMock()
    bedrock.invoke_model.side_effect = lambda **_k: {
        "body": io.BytesIO(
            json.dumps({"content": [{"type": "text", "text": "ok"}], "usage": ONE_CALL_USAGE, "stop_reason": "end_turn"}).encode()
        )
    }
    windows = _Windows()
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(cap, "time", SimpleNamespace(monotonic=lambda: clock.now))
    monkeypatch.setattr(bc, "_client", lambda: bedrock)
    monkeypatch.setattr(bc, "_cw", lambda: windows)
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    yield SimpleNamespace(bedrock=bedrock, windows=windows, clock=clock)
    cap._reset_for_tests()


def _call():
    return bc.invoke({"messages": [{"role": "user", "content": "x"}], "max_tokens": 8}, model_name=SONNET)


def test_a_named_run_is_refused_at_the_month_and_told_the_env_var_will_not_help(laptop, monkeypatch, capsys):
    laptop.windows.month = 55.0
    monkeypatch.setenv(cap.OVERRIDE_ENV, "40")
    _call()  # month 58
    _call()  # month 61
    with pytest.raises(cap.DevSessionBudgetExceeded) as stop:
        _call()
    assert laptop.bedrock.invoke_model.call_count == 2
    text = str(stop.value)
    assert "monthly envelope is $60.00" in text and "PER_MONTH_USD" in text
    assert "re-run with DEV_AI_BUDGET_USD" not in text, "an override cannot lift the month, so it is not offered"


def test_a_concurrent_lanes_spend_is_seen_at_the_next_re_read(laptop, monkeypatch):
    monkeypatch.setenv(cap.OVERRIDE_ENV, "9")
    _call()
    _call()  # this run: $6; day 0 + 6 < 10
    # Another lane spends $4 meanwhile; CloudWatch now holds this run's $6 + its $4.
    laptop.windows.day, laptop.windows.month = 10.0, 10.0
    _call()  # not yet re-read: still allowed (run 6 < 9, day 6 < 10)
    assert laptop.bedrock.invoke_model.call_count == 3
    laptop.clock.now += cap.REFRESH_SECONDS
    laptop.windows.day, laptop.windows.month = 13.0, 13.0  # this run's $9 + the other lane's $4
    with pytest.raises(cap.DevSessionBudgetExceeded) as stop:
        _call()
    assert "set by DEV_AI_BUDGET_USD" in str(stop.value) or "in the last 24 hours" in str(stop.value)
    assert laptop.windows.reads == 4, "two windows, read at the first call and once more after REFRESH_SECONDS"


def test_a_re_read_sees_the_other_lane_before_this_run_reaches_its_own_number(laptop, monkeypatch):
    monkeypatch.setenv(cap.OVERRIDE_ENV, "12")
    _call()  # run $3
    laptop.clock.now += cap.REFRESH_SECONDS
    laptop.windows.day = 3.0 + 9.0  # this run's $3 + another lane's $9 → others $9, total $12
    with pytest.raises(cap.DevSessionBudgetExceeded) as stop:
        _call()
    assert "lets that total reach $12.00" in str(stop.value)


def test_a_failed_re_read_keeps_the_last_good_figures(laptop):
    laptop.windows.day = 8.0
    _call()  # allowed at 8; the day is now 8 + 3 = 11
    laptop.clock.now += cap.REFRESH_SECONDS
    laptop.windows.get_metric_statistics = MagicMock(side_effect=RuntimeError("throttled"))
    with pytest.raises(cap.DevSessionBudgetExceeded) as stop:
        _call()  # a zeroed re-read would let this go (run $3 < $5, day $3 < $10)
    assert "in the last 24 hours" in str(stop.value)
    assert laptop.bedrock.invoke_model.call_count == 1


def test_the_mcp_lambda_is_counted_in_the_class_but_never_refused(laptop, monkeypatch):
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "life-platform-mcp")
    monkeypatch.setenv("INVOCATION_CONTEXT", "dev")
    laptop.windows.day = laptop.windows.month = 500.0
    assert bc.caller_class() == "dev-session", "counted: it lands on the dev-session series the envelope sums"
    _call()
    assert laptop.bedrock.invoke_model.call_count == 1 and laptop.windows.reads == 0, "never refused, never reads"


def test_the_coverage_is_written_in_the_owning_file():
    src = open(os.path.join(ROOT, "lambdas", "ai", "dev_session_cap.py"), encoding="utf-8").read()
    doc = src.split('"""', 2)[1]
    for heading in ("THE CLASS THIS GOVERNS", "COVERAGE", "REFUSED", "COUNTED", "NEVER", "PER MONTH"):
        assert heading in doc, heading
    owner = open(os.path.join(ROOT, "lambdas", "ai", "bedrock_client.py"), encoding="utf-8").read()
    assert "ai/dev_session_cap.py` (COVERAGE)" in owner, "the class definition points at the coverage"


# ── box 3: the gauge and the alarm ───────────────────────────────────────────────────
def test_the_governor_publishes_the_month_as_its_own_gauge():
    from operational import episodic_premise

    cw = MagicMock()
    cw.get_metric_statistics.return_value = {"Datapoints": [{"Sum": 63.42}]}
    start, now = datetime(2026, 11, 1, tzinfo=timezone.utc), datetime(2026, 11, 25, 22, tzinfo=timezone.utc)  # in force (#5406)
    assert episodic_premise.publish_dev_session_month(cw, "CallerClass", start, now) == pytest.approx(63.42)
    kw = cw.get_metric_statistics.call_args.kwargs
    assert kw["Dimensions"] == [{"Name": "CallerClass", "Value": "dev-session"}] and kw["StartTime"] == start
    put = cw.put_metric_data.call_args.kwargs
    assert put["Namespace"] == "LifePlatform/Budget"
    assert put["MetricData"] == [{"MetricName": "DevSessionSpendMTD", "Value": pytest.approx(63.42), "Unit": "None"}]
    cw.get_metric_statistics.side_effect = RuntimeError("throttled")
    assert episodic_premise.publish_dev_session_month(cw, "CallerClass", start, now) is None, "never raises into the tier decision"
    gov_src = open(os.path.join(ROOT, "lambdas", "operational", "cost_governor_lambda.py"), encoding="utf-8").read()
    assert "_episodic.publish_dev_session_month(_cw, CALLER_CLASS_DIMENSION, month_start, now)" in gov_src, "the governor calls it"


def test_the_alarm_reads_the_gauge_at_the_derived_bar_and_is_separate_from_the_daily_totals():
    src = open(os.path.join(ROOT, "cdk", "stacks", "monitoring_token_alarms.py"), encoding="utf-8").read()
    assert "DEV_SESSION_MONTH_ALARM_USD = _BUDGET.dev_session_month_alarm_usd()" in src, "derived, never typed"
    block = src[src.index('"AiDevSessionMonthHigh"') :]
    call = block[: block.index(")\n")]
    assert '"ai-dev-session-month-high"' in call and '"LifePlatform/Budget"' in call and '"DevSessionSpendMTD"' in call
    assert "DEV_SESSION_MONTH_ALARM_USD" in call and "to_digest=True" in call
    assert not re.search(r"\b48(\.0)?\b", call), "the bar is the derivation, not a literal"
    assert "AlarmRule.from_alarm(" not in block, "not folded into the production composites"
