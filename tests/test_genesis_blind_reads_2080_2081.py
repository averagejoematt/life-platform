"""tests/test_genesis_blind_reads_2080_2081.py — two more #1203-class consumers
read CROSS-PHASE.

Both sites were found by the derived call-site scan #2079 introduced with the
#2023 fix, and both are the same defect: a raw-source read that applies the
ADR-058 phase filter, while the experiment reset tags every pre-genesis row
`phase=pilot` (ADR-077). After a reset the read can therefore only see the days
elapsed since genesis.

  * #2080 — `daily_brief_lambda.scan_stale_sources` (was inline in
    `lambda_handler`): a newest-first `Limit: 1` recency query. DynamoDB applies
    `Limit` BEFORE `FilterExpression`, so the one row read is the pilot-tagged
    newest row, the filter drops it, and the query returns empty. Every source
    whose newest row predates genesis then reports "no data" — indistinguishable
    from a genuinely dead pipe — and the long-threshold sources (food_delivery
    90d, measurements 60d), whose newest row is legitimately old, produce a
    guaranteed false staleness alarm on every cycle.

  * #2081 — `anomaly_detector_lambda.fetch_range`: feeds a rolling 30-day
    baseline with `MIN_BASELINE_DAYS = 7`. For the first week of a cycle the
    window holds under 7 points and `compute_baseline` returns None on every
    metric (detection entirely OFF); from day 8 to day 30 the SD is computed
    over a truncated window, which is artificially tight and makes the detector
    over-fire on ordinary variance.

Structure mirrors tests/test_gradability_liveness_cross_phase_2023.py:

  1. a non-vacuous anchor — the fake table really reproduces the blindfold, so
     the guards below are not testing nothing;
  2. the instances — genesis-day fixtures for both consumers, plus the negative
     cases proving each consumer still does its job (a genuinely stale source
     still alarms with its true age; a genuinely absent baseline is still None);
  3. the SETS of sources both consumers read, derived from the modules' own
     constants and checked against phase_taxonomy — so a future source that IS
     legitimately phase-scoped cannot inherit the cross-phase read silently.

Every date in here is PINNED (`_TODAY`, `_GENESIS`); nothing does now-math
against the wall clock, so the file cannot start failing on a calendar boundary.
"""

from __future__ import annotations

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

sys.path.insert(0, str(REPO_ROOT / "lambdas"))
sys.path.insert(0, str(REPO_ROOT / "lambdas" / "emails"))

import anomaly_detector_lambda as anomaly  # noqa: E402
import daily_brief_lambda as brief  # noqa: E402
from experiment import phase_taxonomy as tax  # noqa: E402
from experiment.phase_filter import with_phase_filter  # noqa: E402

# Pinned clock. _GENESIS == _TODAY is "the reset happened this morning" — the
# worst case, and the one cycle 12 actually shipped (a same-day genesis).
_TODAY = date(2026, 8, 3)
_GENESIS = _TODAY

NEVER_HIDDEN_CLASSES = frozenset({tax.RAW_TIMESERIES, tax.CROSS_PHASE})


class PhaseAwareFakeTable:
    """Mini-DynamoDB faithful in the three ways this defect depends on:

    * it honours `sk BETWEEN` bounds and `begins_with`, so "the window bounds
      recency, not the phase tag" is a claim the negative tests can actually
      falsify;
    * it applies the phase FilterExpression when one is present;
    * it applies `Limit` BEFORE the filter and `ScanIndexForward` before that
      — which is the entire mechanism of #1203/#2080. A fake that filtered
      first would quietly make the bug untestable.
    """

    def __init__(self, rows):
        self.rows = rows
        self.query_calls = []

    def query(self, **kwargs):
        self.query_calls.append(kwargs)
        vals = kwargs.get("ExpressionAttributeValues") or {}
        items = [dict(r) for r in self.rows]

        cond = kwargs.get("KeyConditionExpression")
        if isinstance(cond, str):  # the expression-attribute form
            pk = vals.get(":pk")
            if pk is not None:
                items = [it for it in items if it.get("pk") == pk]
            lo, hi = vals.get(":s"), vals.get(":e")
            if lo is not None and hi is not None:
                items = [it for it in items if lo <= it["sk"] <= hi]
        else:  # the boto3 Key() condition object form
            expr = cond.get_expression() if cond is not None else None
            for pk_val, sk_prefix, sk_range in _flatten_key_condition(expr):
                if pk_val is not None:
                    items = [it for it in items if it.get("pk") == pk_val]
                if sk_prefix is not None:
                    items = [it for it in items if str(it["sk"]).startswith(sk_prefix)]
                if sk_range is not None:
                    lo, hi = sk_range
                    items = [it for it in items if lo <= str(it["sk"]) <= hi]

        items.sort(key=lambda it: it["sk"], reverse=not kwargs.get("ScanIndexForward", True))

        # Limit BEFORE the filter — DynamoDB's actual order, and the bug.
        limit = kwargs.get("Limit")
        if limit is not None:
            items = items[:limit]
        if kwargs.get("FilterExpression") and ":phase_experiment" in vals:
            current = vals[":phase_experiment"]
            items = [it for it in items if it.get("phase") in (None, current)]
        return {"Items": items}


def _flatten_key_condition(expr):
    """Yield (pk_value, sk_begins_with_prefix, sk_between_bounds) from a boto3 Key
    condition — exactly one member of each triple is non-None.

    `between` is honoured (#2109) because `intelligence_common.build_data_inventory`
    expresses its 90-day sweep as `Key("sk").between(...)` in the Key-OBJECT form. A
    fake that silently ignored the bound would return the whole partition, which would
    make "the window still bounds the answer" untestable there — and, worse, would let
    a COUNT assertion pass for the wrong reason.
    """
    if expr is None:
        return
    operator = expr.get("operator")
    values = expr.get("values", ())
    if operator == "AND":
        for sub in values:
            yield from _flatten_key_condition(sub.get_expression())
        return
    attr, operand = values[0], values[1]
    name = getattr(attr, "name", None)
    if name == "pk" and operator == "=":
        yield operand, None, None
    elif name == "sk" and operator == "begins_with":
        yield None, operand, None
    elif name == "sk" and operator == "BETWEEN":
        yield None, None, (operand, values[2])


def _rows(pk, field, values_by_date, genesis=_GENESIS):
    """Build DDB rows, tagging every row dated before `genesis` phase=pilot —
    exactly what the reset tagger writes, with post-genesis rows untagged the way
    a fresh ingestion write lands them."""
    out = []
    for d, value in sorted(values_by_date.items()):
        row = {"pk": pk, "sk": "DATE#" + d.isoformat(), field: value}
        if d < genesis:
            row["phase"] = "pilot"
        out.append(row)
    return out


def _daily(field, days, end=_TODAY, value=lambda i: 100.0 + i, genesis=_GENESIS, pk=None):
    series = {end - timedelta(days=i): value(i) for i in range(days)}
    return _rows(pk or "USER#matthew#SOURCE#whoop", field, series, genesis=genesis)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Non-vacuous anchor — the fake table reproduces the blindfold
# ══════════════════════════════════════════════════════════════════════════════


def test_fake_table_applies_limit_before_the_filter():
    """The mechanism of #1203/#2080. A newest-first Limit:1 read of a partition
    whose newest row is pilot-tagged must come back EMPTY when phase-filtered —
    if this stops holding, every #2080 guard below is vacuous."""
    table = PhaseAwareFakeTable(_daily("hrv", 30, genesis=_TODAY + timedelta(days=1)))
    kwargs = {
        "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
        "ExpressionAttributeValues": {
            ":pk": "USER#matthew#SOURCE#whoop",
            ":s": "DATE#2000-01-01",
            ":e": "DATE#2999-01-01",
        },
        "Limit": 1,
        "ScanIndexForward": False,
    }
    assert table.query(**with_phase_filter(dict(kwargs)))["Items"] == []
    assert len(table.query(**with_phase_filter(dict(kwargs), include_pilot=True))["Items"]) == 1


def test_fake_table_hides_pilot_rows_across_a_window():
    """…and the #2081 half: a phase-filtered 30-day range read of an all-pilot
    partition returns nothing, while a cross-phase read returns the window."""
    table = PhaseAwareFakeTable(_daily("hrv", 30, genesis=_TODAY + timedelta(days=1)))
    kwargs = {
        "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
        "ExpressionAttributeValues": {
            ":pk": "USER#matthew#SOURCE#whoop",
            ":s": "DATE#2000-01-01",
            ":e": "DATE#2999-01-01",
        },
    }
    assert table.query(**with_phase_filter(dict(kwargs)))["Items"] == []
    assert len(table.query(**with_phase_filter(dict(kwargs), include_pilot=True))["Items"]) == 30


# ══════════════════════════════════════════════════════════════════════════════
# 2a. #2080 — the brief's per-source staleness scan
# ══════════════════════════════════════════════════════════════════════════════


def _brief_rows(last_seen_by_source, genesis=_GENESIS):
    """One row per source at its stated last-seen date, plus a little history."""
    rows = []
    for src, last in last_seen_by_source.items():
        pk = f"USER#matthew#SOURCE#{src}"
        rows.extend(_rows(pk, "value", {last - timedelta(days=i): float(i) for i in range(3)}, genesis=genesis))
    return rows


def test_staleness_scan_sees_pre_genesis_rows_on_genesis_day(monkeypatch):
    """The issue's negative test. Genesis is TODAY, so every existing row is
    pilot-tagged. A source that wrote yesterday is FRESH and must not be reported
    stale — before the fix it came back "no data" (a dead pipe) instead."""
    fresh = {src: _TODAY - timedelta(days=1) for src in brief.STALENESS_SOURCES}
    monkeypatch.setattr(brief, "table", PhaseAwareFakeTable(_brief_rows(fresh)))
    assert brief.scan_stale_sources(_TODAY) == []


def test_staleness_scan_does_not_phase_filter(monkeypatch):
    """The contract, stated directly against the wire kwargs."""
    table = PhaseAwareFakeTable(_brief_rows({src: _TODAY for src in brief.STALENESS_SOURCES}))
    monkeypatch.setattr(brief, "table", table)
    brief.scan_stale_sources(_TODAY)
    assert table.query_calls, "the scan issued no queries at all"
    assert all(kw.get("FilterExpression") is None for kw in table.query_calls)


def test_long_threshold_sources_no_longer_false_alarm_every_cycle(monkeypatch):
    """The concrete cost of the bug. food_delivery and measurements have
    deliberately long thresholds because their newest row is legitimately old —
    which also guarantees it is pre-genesis and pilot-tagged. Phase-filtered,
    both reported "no data" on Day 1 of every cycle; cross-phase they report their
    true age and stay silent while inside their threshold.

    #2221: the ages are derived from the module's own thresholds, which now come
    from source_registry rather than a hand-kept literal (food_delivery was 90d
    here against the registry's 14d — the brief was UNDER-reporting a genuinely
    stale food-delivery pipe for 76 days).
    """
    last_seen = {src: _TODAY - timedelta(days=1) for src in brief.STALENESS_SOURCES}
    for _long in ("food_delivery", "measurements"):
        _inside = max(1, int(brief.STALENESS_THRESHOLD_OVERRIDE_DAYS[_long]) - 1)
        last_seen[_long] = _TODAY - timedelta(days=_inside)
    monkeypatch.setattr(brief, "table", PhaseAwareFakeTable(_brief_rows(last_seen)))
    assert brief.scan_stale_sources(_TODAY) == []


def test_a_genuinely_stale_source_still_alarms_with_its_true_age(monkeypatch):
    """The gate must keep doing its job. Reading cross-phase does not make a dead
    pipe look alive — the DATE arithmetic, not the phase tag, decides — and the
    reported age is now the real one instead of None/'no data'."""
    last_seen = {src: _TODAY - timedelta(days=1) for src in brief.STALENESS_SOURCES}
    last_seen["whoop"] = _TODAY - timedelta(days=9)
    monkeypatch.setattr(brief, "table", PhaseAwareFakeTable(_brief_rows(last_seen)))
    stale = brief.scan_stale_sources(_TODAY)
    assert [s["source"] for s in stale] == ["whoop"]
    assert stale[0]["age_days"] == 9
    assert stale[0]["last_date"] == (_TODAY - timedelta(days=9)).isoformat()


def test_a_source_that_never_wrote_is_still_reported_no_data(monkeypatch):
    """An empty partition is genuinely 'no data' — that branch is preserved; the
    bug was that a NON-empty partition also produced it."""
    # #2221: the absent source is picked off the module's own (now registry-derived)
    # list rather than named — `garmin` used to be the literal here, and it left the
    # set when the brief stopped watching a deliberately paused source.
    _absent = brief.STALENESS_SOURCES[0]
    last_seen = {src: _TODAY for src in brief.STALENESS_SOURCES if src != _absent}
    monkeypatch.setattr(brief, "table", PhaseAwareFakeTable(_brief_rows(last_seen)))
    stale = brief.scan_stale_sources(_TODAY)
    assert [(s["source"], s["age_days"]) for s in stale] == [(_absent, None)]


def test_staleness_scan_survives_every_day_of_the_opening_week(monkeypatch):
    """Not just Day 1: the blindfold lasted for as long as a source had not yet
    written a post-genesis row, which for a daily-cadence source is any day the
    ingestion has not run yet."""
    for age in range(0, 7):
        genesis = _TODAY - timedelta(days=age)
        last_seen = {src: genesis - timedelta(days=1) for src in brief.STALENESS_SOURCES}
        monkeypatch.setattr(brief, "table", PhaseAwareFakeTable(_brief_rows(last_seen, genesis=genesis)))
        stale = brief.scan_stale_sources(_TODAY)
        assert all(s["age_days"] is not None for s in stale), f"reported 'no data' on day {age + 1} of the cycle"


def test_staleness_scan_read_error_is_non_fatal(monkeypatch):
    """Unchanged WR-48 contract: the banner is best-effort. A read failure must
    never take the whole brief down."""

    class _Boom:
        def query(self, **kwargs):
            raise RuntimeError("throttled")

    monkeypatch.setattr(brief, "table", _Boom())
    assert brief.scan_stale_sources(_TODAY) == []


# ══════════════════════════════════════════════════════════════════════════════
# 2b. #2081 — the anomaly detector's rolling baseline
# ══════════════════════════════════════════════════════════════════════════════


def _anomaly_table(days=30, genesis=_GENESIS, field="recovery_score", value=lambda i: 60.0 + (i % 5)):
    """A month of daily whoop rows ending yesterday — the window compute_baseline
    actually reads (it ends at end_date - 1 day)."""
    end = _TODAY - timedelta(days=1)
    series = {end - timedelta(days=i): value(i) for i in range(days)}
    return PhaseAwareFakeTable(_rows("USER#matthew#SOURCE#whoop", field, series, genesis=genesis))


def test_baseline_is_active_on_day_one_with_the_pre_genesis_window(monkeypatch):
    """The issue's negative test. Genesis is TODAY, so the whole 30-day history is
    pilot-tagged. Before the fix compute_baseline saw 0 points, returned None, and
    anomaly detection was OFF."""
    monkeypatch.setattr(anomaly, "table", _anomaly_table())
    mean, sd, cv, z_threshold, n, baseline_type = anomaly.compute_baseline("whoop", "recovery_score", _TODAY)
    assert mean is not None and sd is not None
    assert n == 30, f"the baseline saw {n} points, not the full 30-day window"
    assert baseline_type == "rolling_30d"
    assert z_threshold is not None


def test_sd_window_is_thirty_days_regardless_of_genesis(monkeypatch):
    """The 'artificially tight SD' half. The same underlying series must produce
    the SAME baseline whether genesis is today, a week ago, or a year ago — the
    rolling window is what bounds it, so the detector's sensitivity no longer
    depends on how recently the experiment restarted."""
    reference = None
    for genesis_days_ago in (0, 1, 3, 7, 29, 365):
        monkeypatch.setattr(anomaly, "table", _anomaly_table(genesis=_TODAY - timedelta(days=genesis_days_ago)))
        result = anomaly.compute_baseline("whoop", "recovery_score", _TODAY)
        if reference is None:
            reference = result
        assert result == reference, f"baseline moved when genesis was {genesis_days_ago}d ago"
    assert reference[4] == 30  # sample_size


def test_baseline_does_not_phase_filter(monkeypatch):
    """The contract, on the wire."""
    table = _anomaly_table()
    monkeypatch.setattr(anomaly, "table", table)
    anomaly.compute_baseline("whoop", "recovery_score", _TODAY)
    assert table.query_calls
    assert all(kw.get("FilterExpression") is None for kw in table.query_calls)


def test_baseline_window_still_excludes_older_history(monkeypatch):
    """Reading cross-phase does not widen the window. History older than the
    lookback stays out — otherwise the SD would drift toward a lifetime SD and
    the detector would under-fire."""
    end = _TODAY - timedelta(days=1)
    series = {end - timedelta(days=i): 60.0 for i in range(30)}
    series.update({end - timedelta(days=i): 999.0 for i in range(40, 90)})  # far outside the window
    monkeypatch.setattr(
        anomaly,
        "table",
        PhaseAwareFakeTable(_rows("USER#matthew#SOURCE#whoop", "recovery_score", series)),
    )
    mean, sd, _cv, _z, n, _t = anomaly.compute_baseline("whoop", "recovery_score", _TODAY)
    assert n == 30
    assert mean == pytest.approx(60.0)
    assert sd == pytest.approx(0.0)


def test_a_genuinely_sparse_source_still_returns_no_baseline(monkeypatch):
    """MIN_BASELINE_DAYS is preserved: fewer than 7 real points in the window is
    still no baseline. Un-blinding the read turns detection back ON, it does not
    switch the minimum off."""
    monkeypatch.setattr(anomaly, "table", _anomaly_table(days=anomaly.MIN_BASELINE_DAYS - 1))
    mean, sd, _cv, _z, n, _t = anomaly.compute_baseline("whoop", "recovery_score", _TODAY)
    assert mean is None and sd is None
    assert n == anomaly.MIN_BASELINE_DAYS - 1


def test_fetch_range_read_error_still_returns_empty(monkeypatch):
    """Unchanged fail-soft contract."""

    class _Boom:
        def query(self, **kwargs):
            raise RuntimeError("throttled")

    monkeypatch.setattr(anomaly, "table", _Boom())
    assert anomaly.fetch_range("whoop", "2026-07-01", "2026-08-01") == []


# ══════════════════════════════════════════════════════════════════════════════
# 3. The SETS of sources — derived from each module, checked against the taxonomy
# ══════════════════════════════════════════════════════════════════════════════


def test_every_staleness_source_is_a_never_hidden_class():
    """Why the #2080 read may be cross-phase, enforced over the derived set rather
    than the sources that happened to be checked by hand. Add a source to
    STALENESS_SOURCES that phase_taxonomy classes EXPERIMENT_SCOPED and this fails
    — which is the moment to revisit the read, not to inherit it."""
    for src in brief.STALENESS_SOURCES:
        cls = tax.SOURCE_CLASS.get(src)
        assert cls is not None, f"staleness source '{src}' is unclassified in phase_taxonomy"
        assert cls in NEVER_HIDDEN_CLASSES, f"staleness source '{src}' is {cls}; a cross-phase read is unjustified"


def test_every_anomaly_metric_source_is_a_never_hidden_class():
    """Same guard for #2081, derived from the detector's own METRICS table."""
    for source, field, _label, _low_is_bad in anomaly.METRICS:
        cls = tax.SOURCE_CLASS.get(source)
        assert cls is not None, f"anomaly metric {field} → source '{source}' is unclassified in phase_taxonomy"
        assert cls in NEVER_HIDDEN_CLASSES, f"anomaly metric {field} → '{source}' is {cls}; a cross-phase baseline is unjustified"


def test_staleness_thresholds_cover_only_real_sources():
    """A threshold override for a source that is no longer scanned is dead config
    that reads as protection."""
    unknown = set(brief.STALENESS_THRESHOLD_OVERRIDE_DAYS) - set(brief.STALENESS_SOURCES)
    assert not unknown, f"threshold overrides for sources that are not scanned: {sorted(unknown)}"


def test_the_scan_is_still_wired_into_the_brief():
    """The extraction must not have orphaned the banner: lambda_handler still calls
    it, and nothing rebuilt an inline copy alongside."""
    src = (REPO_ROOT / "lambdas" / "emails" / "daily_brief_lambda.py").read_text()
    assert "scan_stale_sources(datetime.now(timezone.utc).date())" in src
    assert src.count("def scan_stale_sources") == 1
    assert "_STALE_OVERRIDE" not in src, "the inline staleness block came back"
