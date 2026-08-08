"""tests/test_mcp_tools_health_behavior.py — behavioral contracts for the three
owner-facing health tools registered out of ``mcp/tools_health.py``:

    get_readiness_score        (tool_get_readiness_score)
    get_weight_loss_progress   (tool_get_weight_loss_progress)
    get_daily_metrics          (tool_get_daily_metrics -> movement | energy | hydration)

These are answers Matthew reads inside Claude Desktop / claude.ai and quotes back
as fact — "my readiness is 71.5", "my BMR is 1971 kcal", "I've plateaued for 14
days". The whole ``mcp/tools_*`` family had zero dedicated behavioral coverage
before this file, so the contracts pinned here are the ones a person acting on
the answer depends on:

  * ADR-104 honest numbers — an unmeasured component is ABSENT, never a factual
    0 and never a neutral-looking default. ``x or y`` over a legitimately-zero
    reading, ``.get(k, 0)`` over a missing field, and a hardcoded stand-in for a
    profile value the tool could not load are all the same defect wearing three
    hats.
  * ADR-105 rigor — an average, ratio or trend ships with the n behind it. Two
    code paths that publish the SAME field name must agree on whether n travels
    with it.
  * #1917 window-name honesty — a field or parameter named for an N-day window
    spans N days. ``end - timedelta(days=7)`` fed to an INCLUSIVE ``sk BETWEEN``
    is an 8-day window wearing a 7-day name.
  * Reader/writer field agreement — every DynamoDB field these tools read is
    checked against a writer that actually produces it. Where a writer's
    transform is pure (``ingestion.strava_lambda.transform``) the test DERIVES
    the produced field set by calling it, so the check cannot drift.
  * ADR-058 phase filtering — ``computed_metrics`` is EXPERIMENT_SCOPED, and the
    class is read out of ``lambdas/experiment/phase_taxonomy.py`` rather than
    restated here.
  * Empty-state honesty — a quiet platform gets an explicit error, never a
    fabricated score.

Everything runs against a hand-rolled bounded DynamoDB double patched onto
``mcp.core.table``, so the REAL ``query_source`` executes — its phase filter, its
``sk BETWEEN`` window, and its pagination loop are all exercised rather than
stubbed away. No MagicMock appears anywhere near the pagination loop. No AWS, no
network, no clock that moves: ``datetime.now`` is pinned via a ``datetime``
subclass so ``strptime``/``timedelta`` keep working on the same name.

Every arithmetic expectation is hand-derived in a comment beside the literal.
"""

from __future__ import annotations

import copy
import os
import threading
from datetime import datetime, timedelta, timezone

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")  # mcp.config reads these at import
os.environ.setdefault("USER_ID", "matthew")

import pytest  # noqa: E402

from mcp import core as mcore, tools_health as th  # noqa: E402
from mcp.registry import TOOLS  # noqa: E402

# ──────────────────────────────────────────────────────────────────────────────
# Frozen clock
# ──────────────────────────────────────────────────────────────────────────────

NOW = datetime(2026, 5, 10, 17, 40, 0, tzinfo=timezone.utc)  # 10:40 PT — same PT/UTC calendar day
TODAY = "2026-05-10"
_FROZEN = [NOW]


class _FrozenDatetime(datetime):
    """``datetime`` with a pinned ``now()``.

    A subclass, not a Mock: ``tools_health`` calls ``strptime`` and does
    ``timedelta`` arithmetic on this same name, and every one of those must keep
    working. ``strptime`` on a subclass returns the subclass, which subtracts
    cleanly against other instances.
    """

    @classmethod
    def now(cls, tz=None):
        return _FROZEN[0].astimezone(tz) if tz is not None else _FROZEN[0].replace(tzinfo=None)

    @classmethod
    def utcnow(cls):
        return _FROZEN[0].replace(tzinfo=None)


def freeze(dt: datetime) -> None:
    _FROZEN[0] = dt


def d(date_str: str, days: int) -> str:
    """Fixture-date arithmetic. Never combined with a live clock (rule: no
    ``fixture date + datetime.now()`` time bombs)."""
    return (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")


def span_days(start: str, end: str) -> int:
    """Inclusive calendar-date count of a ``sk BETWEEN DATE#start .. DATE#end~``
    window — the number of dates the window can actually return."""
    return (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days + 1


# ──────────────────────────────────────────────────────────────────────────────
# Bounded, hand-rolled DynamoDB double
# ──────────────────────────────────────────────────────────────────────────────


def _flatten(cond, out):
    """Walk a boto3 ``KeyConditionExpression`` tree into (operator, values) pairs.

    Reading the real condition object rather than accepting whatever kwargs
    arrive is what lets this fake honour ``query_source``'s actual key
    expression — including the ``DATE#{end}~`` upper bound — instead of
    flattering it.
    """
    expr = cond.get_expression()
    if expr["operator"] == "AND":
        for sub in expr["values"]:
            _flatten(sub, out)
    else:
        out.append((expr["operator"], [getattr(v, "name", v) for v in expr["values"]]))
    return out


class FakeTable:
    """In-memory stand-in for the boto3 ``Table`` that ``mcp.core`` holds.

    Faithful where the tools depend on it:

      * ``query`` honours ``pk =`` and ``sk BETWEEN`` from the real condition
        tree, so a window bug in the tool shows up as missing rows here exactly
        as it would in production;
      * it honours the ADR-058 phase ``FilterExpression`` by reading the wanted
        phase value out of the query's own ``ExpressionAttributeValues``, so the
        test cannot drift from ``core._PHASE_FILTER_VALUES``;
      * with ``page_size`` set it returns a real ``LastEvaluatedKey``, driving
        ``query_source``'s pagination ``while True`` with a BOUNDED generator —
        never a MagicMock, which is how that loop becomes an OOM;
      * every call is recorded as ``(pk, start, end)`` so a test can assert the
        window a tool ASKED for, independently of what came back.

    ``parallel_query_sources`` fans out across threads, so the call log is
    lock-guarded.
    """

    def __init__(self, rows=None, profile=None, page_size=None, raise_sources=frozenset()):
        self.rows = [copy.deepcopy(r) for r in (rows or [])]
        self.profile = copy.deepcopy(profile) if profile is not None else None
        self.queries: list[tuple[str, str, str]] = []
        self.page_count = 0
        self.page_size = page_size
        self.raise_sources = set(raise_sources)
        self._lock = threading.Lock()

    # -- reads ---------------------------------------------------------------
    def get_item(self, Key=None, **kwargs):
        key = Key if Key is not None else kwargs.get("Key", {})
        if self.profile is not None and key.get("sk") == "PROFILE#v1":
            return {"Item": copy.deepcopy(self.profile)}
        return {}

    def query(self, **kwargs):
        parts = dict((op, vals) for op, vals in _flatten(kwargs["KeyConditionExpression"], []))
        pk = parts["="][1]
        lo = parts["BETWEEN"][1].replace("DATE#", "")
        hi = parts["BETWEEN"][2].replace("DATE#", "").rstrip("~")
        source = pk.split("#SOURCE#")[-1]
        if kwargs.get("ExclusiveStartKey") is None:
            with self._lock:
                self.queries.append((source, lo, hi))
        if source in self.raise_sources:
            raise RuntimeError(f"simulated DynamoDB failure reading {source}")

        matched = sorted(
            (r for r in self.rows if r.get("pk") == pk and lo <= str(r.get("sk", "")).replace("DATE#", "") <= hi),
            key=lambda r: r.get("sk", ""),
        )
        # ADR-058: phase filter, applied the way DynamoDB applies it — the wanted
        # value comes from the caller's own expression, never restated here.
        fexpr = kwargs.get("FilterExpression") or ""
        if "attribute_not_exists(#phase)" in fexpr:
            want = kwargs["ExpressionAttributeValues"][":phase_experiment"]
            matched = [r for r in matched if r.get("phase") is None or r.get("phase") == want]

        start = 0
        if kwargs.get("ExclusiveStartKey"):
            last = kwargs["ExclusiveStartKey"]["sk"]
            start = next((i for i, r in enumerate(matched) if r.get("sk") == last), -1) + 1
        page = matched[start:] if self.page_size is None else matched[start : start + self.page_size]
        self.page_count += 1
        out: dict = {"Items": [copy.deepcopy(r) for r in page]}
        if self.page_size is not None and page and (start + len(page)) < len(matched):
            out["LastEvaluatedKey"] = {"pk": pk, "sk": page[-1]["sk"]}
        return out

    # -- assertions helpers ---------------------------------------------------
    def window_for(self, source: str) -> tuple[str, str]:
        for s, lo, hi in self.queries:
            if s == source:
                return lo, hi
        raise AssertionError(f"{source!r} was never queried; queries={self.queries}")

    @property
    def sources_read(self) -> set[str]:
        return {q[0] for q in self.queries}


# ──────────────────────────────────────────────────────────────────────────────
# Row builders — keyed exactly the way the real partitions are keyed
# ──────────────────────────────────────────────────────────────────────────────

PK = "USER#matthew#SOURCE#"


def row(source: str, date: str, **fields) -> dict:
    return {"pk": PK + source, "sk": f"DATE#{date}", "date": date, **fields}


def whoop(date: str, **fields) -> dict:
    return row("whoop", date, **fields)


def whoop_full(date: str, recovery=60, hrv=45, rhr=55, sleep_score=80, eff=90, dur=7.5) -> dict:
    """A Whoop day carrying the field names ``lambdas/ingestion/whoop_lambda.py``
    actually writes (``sleep_quality_score`` / ``sleep_efficiency_percentage``),
    NOT the normalised aliases the tool reads — ``helpers.normalize_whoop_sleep``
    is what bridges them, and that bridge is part of what is under test."""
    return whoop(
        date,
        recovery_score=recovery,
        hrv=hrv,
        resting_heart_rate=rhr,
        sleep_quality_score=sleep_score,
        sleep_efficiency_percentage=eff,
        sleep_duration_hours=dur,
    )


def cmetrics(date: str, **fields) -> dict:
    return row("computed_metrics", date, **fields)


def garmin(date: str, **fields) -> dict:
    return row("garmin", date, **fields)


def withings(date: str, **fields) -> dict:
    return row("withings", date, **fields)


def apple(date: str, **fields) -> dict:
    return row("apple_health", date, **fields)


def strava(date: str, **fields) -> dict:
    return row("strava", date, **fields)


PROFILE = {
    "pk": "USER#matthew",
    "sk": "PROFILE#v1",
    "journey_start_date": "2026-04-01",
    "journey_start_weight_lbs": 320.0,
    "goal_weight_lbs": 200.0,
    "height_inches": 72,
}


# ──────────────────────────────────────────────────────────────────────────────
# Harness
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _frozen_and_isolated(monkeypatch):
    """Pin the clock the module observes and clear ``core``'s PROCESS-LEVEL
    profile cache.

    ``mcp.core._PROFILE_CACHE`` is a module global that survives across tests —
    the first test to call ``get_profile`` would otherwise pin its profile into
    every later one, which is exactly the kind of shared state that makes a
    suite pass in isolation and fail in order.
    """
    freeze(NOW)
    monkeypatch.setattr(th, "datetime", _FrozenDatetime)
    monkeypatch.setattr(mcore, "_PROFILE_CACHE", None, raising=False)
    yield
    mcore._PROFILE_CACHE = None
    freeze(NOW)


def install(monkeypatch, rows=None, profile=PROFILE, page_size=None, raise_sources=frozenset()) -> FakeTable:
    t = FakeTable(rows=rows, profile=profile, page_size=page_size, raise_sources=raise_sources)
    monkeypatch.setattr(mcore, "table", t)
    return t


# ──────────────────────────────────────────────────────────────────────────────
# 0. The tool SET, derived from the registry (never a hand-typed list)
# ──────────────────────────────────────────────────────────────────────────────

MODULE_TOOLS = {name: spec for name, spec in TOOLS.items() if getattr(spec["fn"], "__module__", "") == th.__name__}

# The tools this file actually drives. Compared against the derived set below so
# a fourth tool wired out of tools_health cannot ship untested.
EXERCISED = {"get_readiness_score", "get_weight_loss_progress", "get_daily_metrics"}


def test_the_registry_still_wires_tools_out_of_this_module():
    """Precondition for every derived guard below — if the module stopped
    exporting registered tools, they would all be silently vacuous."""
    assert MODULE_TOOLS, "mcp/registry.py no longer registers any mcp.tools_health function"


def test_every_registered_tools_health_tool_is_exercised_by_this_file():
    assert set(MODULE_TOOLS) == EXERCISED, f"undriven tools_health tools: {sorted(set(MODULE_TOOLS) - EXERCISED)}"


@pytest.mark.parametrize("name", sorted(EXERCISED))
def test_no_tool_declares_a_required_argument(name):
    """Each of these is reachable from a bare 'how am I doing?' with no args —
    the registry says ``required: []``, and the no-argument path is what every
    test below exercises by default."""
    assert MODULE_TOOLS[name]["schema"]["inputSchema"]["required"] == []


def _declared_views(tool: str) -> list[str]:
    """The `view` enum the registry publishes — the SET a schema-conformant
    client may send."""
    return MODULE_TOOLS[tool]["schema"]["inputSchema"]["properties"]["view"]["enum"]


# ──────────────────────────────────────────────────────────────────────────────
# 1. get_readiness_score — the one number that decides whether he trains
# ──────────────────────────────────────────────────────────────────────────────


def _readiness_rows(date=TODAY):
    """Every component present and fresh: Whoop recovery+sleep, pre-computed HRV
    trend and TSB, same-day Garmin Body Battery."""
    return [
        whoop_full(date, recovery=60, hrv=45, rhr=55, sleep_score=80),
        cmetrics(date, hrv_7d=44, hrv_30d=40, tsb=4),
        garmin(date, body_battery_end=70, hrv_last_night=48, resting_heart_rate=57),
    ]


def test_readiness_weights_every_component_and_reports_the_hand_derived_score(monkeypatch):
    """The published weights are 40/25/20/10/5. With all five present:

    whoop_recovery   60 * 0.40 = 24.0
    sleep_quality    80 * 0.25 = 20.0   (sleep_quality_score 80 -> sleep_score 80)
    hrv_trend        80 * 0.20 = 16.0   (44/40 = 1.10 -> 60 + 0.10*200 = 80)
    training_form    80 * 0.10 =  8.0   (tsb 4 -> 70 + 4*2.5 = 80)
    body_battery     70 * 0.05 =  3.5
                                -----
                                 71.5   / total weight 1.00 = 71.5  -> GREEN (>=70)
    """
    install(monkeypatch, _readiness_rows())
    out = th.tool_get_readiness_score({})
    assert out["readiness_score"] == 71.5
    assert out["label"] == "GREEN"
    assert out["data_completeness"] == "full"
    assert out["missing_components"] is None
    assert out["components"]["hrv_trend"]["raw"]["trend_pct"] == 10.0
    assert out["components"]["training_form"]["score"] == 80.0
    assert out["components"]["garmin_body_battery"]["score"] == 70.0


def test_readiness_carries_the_medical_disclaimer(monkeypatch):
    """R13-F09 — a health assessment never ships bare."""
    install(monkeypatch, _readiness_rows())
    assert "Not medical advice" in th.tool_get_readiness_score({})["_disclaimer"]


def test_readiness_has_an_explicit_no_data_branch(monkeypatch):
    """The `if not components` guard exists and returns an error rather than a
    score — the intent is right. The next test is about whether it is reachable."""
    monkeypatch.setattr(th, "_get_training_load", lambda a: {})
    install(monkeypatch, [])
    out = th.tool_get_readiness_score({})
    assert "error" in out
    assert "readiness_score" not in out and "label" not in out


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (ADR-104, P1, mcp/tools_health.py:192-213 + 307 tool_get_readiness_score): on a "
        "platform with NO data the `if not components: return {'error': ...}` guard is unreachable, "
        "because the TSB fallback calls `_get_training_load`, whose Banister model over an "
        "all-zeros load series yields ctl=atl=0 -> tsb_form 0.0 -> `clamp(70 + 0*2.5)` = a "
        "training_form component scoring 70.0. Total weight 0.10, so raw_score = 70.0 exactly, "
        "which clears the `>= 70` GREEN threshold. The tool answers a completely silent platform "
        "with 'readiness 70.0 / GREEN / You're primed - go ahead with your planned hard session.' "
        "A zero training load is an ABSENCE of training data, not measured freshness. Who it hurts: "
        "the worst possible day to be told to train hard is the day nothing is measuring him."
    ),
)
def test_readiness_on_a_platform_with_no_data_errors_rather_than_scoring_seventy(monkeypatch):
    install(monkeypatch, [])
    out = th.tool_get_readiness_score({})
    assert "error" in out, f"got readiness_score={out.get('readiness_score')} label={out.get('label')}"


def test_readiness_renormalises_the_remaining_weights_when_garmin_is_absent(monkeypatch):
    """(24.0 + 20.0 + 16.0 + 8.0) / 0.95 = 68 / 0.95 = 71.578... -> 71.6, and the
    shortfall is DISCLOSED rather than silently absorbed."""
    install(monkeypatch, [r for r in _readiness_rows() if "garmin" not in r["pk"]])
    out = th.tool_get_readiness_score({})
    assert out["readiness_score"] == 71.6
    assert out["data_completeness"] == "partial (95% weight covered)"
    assert out["missing_components"] == ["garmin body battery"]


def test_readiness_excludes_a_garmin_record_more_than_a_day_staler_than_whoop(monkeypatch):
    """Garmin ingestion is paused (ADR-074); a Body Battery from two days ago must
    not enter today's score at full weight, and the exclusion must say so."""
    rows = [r for r in _readiness_rows() if "garmin" not in r["pk"]]
    rows.append(garmin(d(TODAY, -2), body_battery_end=95, hrv_last_night=48))
    install(monkeypatch, rows)
    out = th.tool_get_readiness_score({})
    assert "garmin_body_battery" not in out["components"]
    assert out["data_completeness"] == "partial (95% weight covered)"


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (P2, mcp/tools_health.py:253-302 tool_get_readiness_score): the staleness branch "
        "builds `device_agreement = {'status': 'unavailable', 'reason': '<garmin date> is >1 day "
        "older than whoop - stale data excluded'} ` and then the very next block, guarded only by "
        "`if 'whoop_recovery' in components and garmin_today is not None`, OVERWRITES it with a "
        "cross-check computed from that same excluded record. So a Garmin reading the tool just "
        "refused to score at 5% weight is still used to publish 'device_agreement: available, "
        "confidence: high' — the reliability signal for the whole score. The overwrite must also "
        "be gated on `not garmin_stale`."
    ),
)
def test_readiness_does_not_cross_check_against_a_record_it_declared_too_stale(monkeypatch):
    rows = [r for r in _readiness_rows() if "garmin" not in r["pk"]]
    rows.append(garmin(d(TODAY, -2), body_battery_end=95, hrv_last_night=48))
    install(monkeypatch, rows)
    da = th.tool_get_readiness_score({})["device_agreement"]
    assert da["status"] == "unavailable"
    assert "stale" in da["reason"]


def test_readiness_never_returns_a_silent_null_for_the_device_cross_check(monkeypatch):
    """#492/M-7 — when the Whoop/Garmin cross-check cannot run, it says WHY."""
    install(monkeypatch, [r for r in _readiness_rows() if "garmin" not in r["pk"]])
    da = th.tool_get_readiness_score({})["device_agreement"]
    assert da["status"] == "unavailable" and da["reason"]
    assert "garmin" in da["reason"].lower()


def test_readiness_cross_checks_whoop_against_garmin_with_hand_derived_deltas(monkeypatch):
    """HRV 45 vs 48 -> delta -3.0 ms, |3| <= 10 -> agree.
    RHR 55 vs 57 -> delta -2.0 bpm, |2| <= 3  -> agree.  Both agree -> high."""
    install(monkeypatch, _readiness_rows())
    da = th.tool_get_readiness_score({})["device_agreement"]
    assert da["status"] == "available" and da["confidence"] == "high"
    assert da["checks"]["hrv"]["delta_ms"] == -3.0
    assert da["checks"]["rhr"]["delta_bpm"] == -2.0


def test_readiness_flags_a_large_inter_device_disagreement_as_low_confidence(monkeypatch):
    """HRV 45 vs 20 -> delta 25 ms, > 20 -> flag -> confidence low. A flagged day
    is the tool telling him the number itself is shaky."""
    rows = [r for r in _readiness_rows() if "garmin" not in r["pk"]]
    rows.append(garmin(TODAY, body_battery_end=70, hrv_last_night=20, resting_heart_rate=57))
    install(monkeypatch, rows)
    da = th.tool_get_readiness_score({})["device_agreement"]
    assert da["checks"]["hrv"]["status"] == "flag" and da["confidence"] == "low"


def test_readiness_hides_a_pilot_phase_computed_metrics_row(monkeypatch):
    """ADR-058. ``computed_metrics`` is EXPERIMENT_SCOPED — the class is read out
    of the taxonomy registry, not restated — so a row tombstoned by a cycle reset
    must not speak for the current cycle."""
    from experiment import phase_taxonomy

    assert phase_taxonomy.classify(PK + "computed_metrics") == phase_taxonomy.EXPERIMENT_SCOPED
    rows = _readiness_rows()
    rows.append(cmetrics(d(TODAY, -1), readiness_score=99, readiness_colour="GREEN", phase="pilot"))
    install(monkeypatch, rows)
    out = th.tool_get_readiness_score({})
    assert "_precomputed_cross_check" not in out


def test_readiness_surfaces_the_precomputed_cross_check_when_one_exists(monkeypatch):
    """The drift detector between the live tool and daily-metrics-compute."""
    rows = _readiness_rows()
    rows[1] = cmetrics(TODAY, hrv_7d=44, hrv_30d=40, tsb=4, readiness_score=70.2, readiness_colour="GREEN")
    install(monkeypatch, rows)
    out = th.tool_get_readiness_score({})
    assert out["_precomputed_cross_check"]["readiness_score"] == 70.2


def test_readiness_paginates_the_whoop_partition_without_dropping_rows(monkeypatch):
    """``query_source``'s ``while True`` pagination, driven by a BOUNDED fake that
    really returns LastEvaluatedKey. With page_size 1 the 8-date window is walked
    a page at a time and the newest scored record still wins."""
    rows = [whoop_full(d(TODAY, -i), recovery=50 + i) for i in range(6)] + [cmetrics(TODAY, hrv_7d=44, hrv_30d=40)]
    t = install(monkeypatch, rows, page_size=1)
    out = th.tool_get_readiness_score({})
    assert out["components"]["whoop_recovery"]["raw"]["date"] == TODAY
    assert out["components"]["whoop_recovery"]["score"] == 50.0
    assert t.page_count > len(t.queries), "the fake never paginated — the loop was not exercised"


def test_readiness_reports_the_actual_data_date_when_the_overnight_has_not_happened(monkeypatch):
    """Asking for a date whose sleep hasn't been recorded must not stamp the
    request onto older data — it reports the real as-of date and warns."""
    rows = [whoop_full(d(TODAY, -2)), cmetrics(d(TODAY, -2), hrv_7d=44, hrv_30d=40)]
    install(monkeypatch, rows)
    out = th.tool_get_readiness_score({"date": TODAY})
    assert out["date"] == d(TODAY, -2)
    assert out["requested_date"] == TODAY
    assert out["is_forward_dated"] is True
    assert "staleness_warning" in out


def test_readiness_live_hrv_fallback_publishes_the_n_behind_both_averages(monkeypatch):
    """ADR-105. With no computed_metrics record the tool recomputes the HRV trend
    from raw Whoop — and that path DOES ship n_days_7d / n_days_30d beside the
    averages. This is the honest half of the pair; the next test is the other."""
    rows = [whoop_full(d(TODAY, -i), hrv=40 + i) for i in range(8)]
    install(monkeypatch, rows)
    raw = th.tool_get_readiness_score({})["components"]["hrv_trend"]["raw"]
    assert raw["source"] == "live_whoop_query"
    assert raw["n_days_7d"] and raw["n_days_30d"]


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (ADR-105, P2, mcp/tools_health.py:120-130 tool_get_readiness_score): the "
        "PRE-COMPUTED hrv_trend branch publishes `hrv_7d_avg_ms` and `hrv_30d_baseline_ms` with "
        "NO n, while the live-fallback branch 40 lines below publishes the identical field names "
        "WITH `n_days_7d`/`n_days_30d`. Same reader, same key names, opposite rigor — so whether "
        "Matthew can tell a 30-day baseline from a 2-day one depends on whether "
        "daily-metrics-compute happened to run. It should carry the n stored beside the average."
    ),
)
def test_readiness_precomputed_hrv_trend_also_publishes_its_n(monkeypatch):
    install(monkeypatch, _readiness_rows())
    raw = th.tool_get_readiness_score({})["components"]["hrv_trend"]["raw"]
    assert raw["source"] == "pre_computed_metrics"
    assert "n_days_7d" in raw and "n_days_30d" in raw


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (#1917 window-name honesty, P2, mcp/tools_health.py:41-42 tool_get_readiness_score): "
        "`d7_start = end - timedelta(days=7)` is fed to `query_source`, whose key condition is an "
        "INCLUSIVE `sk BETWEEN DATE#start AND DATE#end~` — so the '7-day' window spans 8 calendar "
        "dates and the '30-day' baseline spans 31. The results are published as `hrv_7d_avg_ms`, "
        "`hrv_30d_baseline_ms` and `n_days_7d`, all of which name a window they do not span. Should "
        "be `days=6` / `days=29`. Who it hurts: the HRV trend ratio — the 20%-weighted component — "
        "is computed over 8/31 days while being labelled 7/30."
    ),
)
def test_readiness_seven_day_window_really_spans_seven_days(monkeypatch):
    t = install(monkeypatch, _readiness_rows())
    th.tool_get_readiness_score({})
    lo, hi = t.window_for("whoop")
    assert span_days(lo, hi) == 7


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (ADR-104, P2, mcp/tools_health.py:231 tool_get_readiness_score): "
        "`bb = garmin_today.get('body_battery_end') or garmin_today.get('body_battery_high')`. "
        "A fully-depleted Body Battery of 0 is a REAL reading — and the strongest 'rest today' "
        "signal Garmin produces — but it is falsy, so the `or` silently substitutes the day's "
        "HIGH. Here end=0 becomes 95. The record-selection guard 13 lines above correctly uses "
        "`is not None`; only the value read uses `or`. Who it hurts: Matthew is told GREEN/95 on "
        "the day his own device measured total depletion."
    ),
)
def test_readiness_treats_a_body_battery_of_zero_as_a_real_depleted_reading(monkeypatch):
    install(monkeypatch, [garmin(TODAY, body_battery_end=0, body_battery_high=95)])
    out = th.tool_get_readiness_score({})
    assert out["components"]["garmin_body_battery"]["score"] == 0.0


def test_readiness_discloses_a_thin_component_set(monkeypatch):
    """The honest half: a score built from Body Battery (5%) plus the always-present
    zero-load training_form (10%) discloses 15% coverage and names what is missing."""
    install(monkeypatch, [garmin(TODAY, body_battery_end=95)])
    out = th.tool_get_readiness_score({})
    assert out["data_completeness"] == "partial (15% weight covered)"
    assert sorted(out["missing_components"]) == ["hrv trend", "sleep quality", "whoop recovery"]


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (ADR-105, P2, mcp/tools_health.py:311-319 + 361-371 tool_get_readiness_score): the "
        "GREEN/YELLOW/RED label — the single thing a reader quotes — is emitted with no uncertainty "
        "marker whatsoever. `data_completeness` sits four keys away and is a free-text string, so a "
        "score synthesised from ONE 5%-weight component reads exactly like a five-component score. "
        "The label should carry its own confidence (e.g. `label_confidence`) derived from "
        "total_weight. Who it hurts: 'readiness GREEN' quoted from a lone stale Body Battery."
    ),
)
def test_readiness_label_carries_its_own_confidence_marker(monkeypatch):
    install(monkeypatch, [garmin(TODAY, body_battery_end=95)])
    out = th.tool_get_readiness_score({})
    assert out.get("label_confidence") is not None


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (ADR-104 honest dates, P2, mcp/tools_health.py:353-359 tool_get_readiness_score): "
        "`_data_dates` is collected from ONLY whoop_recovery / sleep_quality / "
        "garmin_body_battery. When the score is built purely from a pre-computed metrics row — the "
        "hrv_trend + training_form components, which carry no `raw.date` — `as_of_date` falls back "
        "to the REQUESTED date, `is_forward_dated` is False and no staleness_warning ships, even "
        "though `_cm` may be the newest row in a 7-day lookback. Here a six-day-old record is "
        "presented as today's readiness. Who it hurts: a stale score dated today."
    ),
)
def test_readiness_from_a_stale_computed_metrics_row_reports_the_real_data_date(monkeypatch):
    stale = d(TODAY, -6)
    install(monkeypatch, [cmetrics(stale, hrv_7d=44, hrv_30d=40, tsb=4)])
    out = th.tool_get_readiness_score({})
    assert out["date"] == stale
    assert out["is_forward_dated"] is True


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (P2, mcp/tools_health.py:40-42 tool_get_readiness_score): `date` is taken straight "
        "from args and handed to `datetime.strptime` with no validation and no try/except, so a "
        "malformed date raises ValueError out of the tool (and an explicit `{'date': None}` raises "
        "TypeError, because `args.get('date', default)` returns the stored None). The MCP caller "
        "gets a stack-trace error instead of 'that date could not be parsed'. Every other bad-input "
        "path in this module returns an error dict — `tool_get_daily_metrics` does exactly that for "
        "an unknown view."
    ),
)
@pytest.mark.parametrize("bad", ["last tuesday", "2026-13-45", "", None])
def test_readiness_returns_an_error_dict_for_an_unparseable_date(monkeypatch, bad):
    install(monkeypatch, _readiness_rows())
    out = th.tool_get_readiness_score({"date": bad})
    assert isinstance(out, dict) and "error" in out


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (ADR-105 provenance, P3, mcp/tools_health.py:388-394 tool_get_readiness_score): "
        "`_precomputed_cross_check` is presented as a drift check against 'daily-metrics-compute "
        "(9:40 AM)', but `_cm` is selected as `next(exact-date match, newest-in-7-day-window)` — so "
        "the cross-check value can be up to 7 days old and ships with no date. A drift detector "
        "that compares today's live score against last week's stored one reports drift that isn't "
        "there (or hides drift that is)."
    ),
)
def test_readiness_cross_check_states_which_day_it_was_computed_for(monkeypatch):
    rows = [whoop_full(TODAY), cmetrics(d(TODAY, -5), readiness_score=70.2, readiness_colour="GREEN")]
    install(monkeypatch, rows)
    out = th.tool_get_readiness_score({})
    assert out["_precomputed_cross_check"].get("date") == d(TODAY, -5)


def test_readiness_derives_sleep_quality_from_efficiency_when_no_score_exists(monkeypatch):
    """Whoop's `sleep_quality_score` alias is absent but efficiency is present:
    score = clamp(efficiency - 25) = 90 - 25 = 65, and the scoring METHOD is
    published so the number is never mistaken for a native Whoop sleep score."""
    rows = [whoop(TODAY, recovery_score=60, hrv=45, sleep_efficiency_percentage=90, sleep_duration_hours=7.5)]
    install(monkeypatch, rows)
    sq = th.tool_get_readiness_score({})["components"]["sleep_quality"]
    assert sq["score"] == 65.0
    assert sq["raw"]["scoring_method"] == "derived_from_efficiency"


def test_readiness_red_tells_him_to_rest_and_names_the_hrv_reason(monkeypatch):
    """recovery 10 * 0.40 =  4.0
    sleep    10 * 0.25 =  2.5
    hrv      30/40 = 0.75 -> clamp(60 + (-0.25)*200) = 10 -> 10 * 0.20 = 2.0 (trend -25.0%)
    tsb     -30 -> clamp(70 - 75) = 0        -> 0 * 0.10 = 0.0
                                     total 8.5 / 0.95 = 8.947 -> 8.9  -> RED
    """
    rows = [whoop_full(TODAY, recovery=10, sleep_score=10), cmetrics(TODAY, hrv_7d=30, hrv_30d=40, tsb=-30)]
    install(monkeypatch, rows)
    out = th.tool_get_readiness_score({})
    assert out["readiness_score"] == 8.9 and out["label"] == "RED"
    assert "Recovery day" in out["recommendation"]
    assert "below your baseline" in out["recommendation"]
    assert out["components"]["training_form"]["raw"]["form_status"].startswith("very fatigued")


def test_readiness_yellow_names_both_the_recovery_and_the_sleep_shortfall(monkeypatch):
    """recovery 45*0.40 = 18.0 ; sleep 45*0.25 = 11.25 ; hrv ratio 1.0 -> 60*0.20 = 12.0 ;
    tsb 0 -> 70*0.10 = 7.0   -> 48.25 / 0.95 = 50.789 -> 50.8 -> YELLOW"""
    rows = [whoop_full(TODAY, recovery=45, sleep_score=45), cmetrics(TODAY, hrv_7d=40, hrv_30d=40, tsb=0)]
    install(monkeypatch, rows)
    out = th.tool_get_readiness_score({})
    assert out["readiness_score"] == 50.8 and out["label"] == "YELLOW"
    assert "prioritise aerobic work" in out["recommendation"]
    assert "Sleep quality was below average" in out["recommendation"]


def test_readiness_green_with_strong_form_suggests_a_pr_attempt(monkeypatch):
    """recovery 90*0.40 = 36.0 ; sleep 90*0.25 = 22.5 ; hrv 1.1 -> 80*0.20 = 16.0 ;
    tsb 10 -> clamp(70+25) = 95*0.10 = 9.5  -> 84.0 / 0.95 = 88.42 -> 88.4 -> GREEN"""
    rows = [whoop_full(TODAY, recovery=90, sleep_score=90), cmetrics(TODAY, hrv_7d=44, hrv_30d=40, tsb=10)]
    install(monkeypatch, rows)
    out = th.tool_get_readiness_score({})
    assert out["readiness_score"] == 88.4 and out["label"] == "GREEN"
    assert "PR attempt" in out["recommendation"]


def test_readiness_labels_a_duration_proxy_training_load_as_such(monkeypatch):
    """M-3/#490 — when the stored TSB was built from duration/HR rather than power,
    the payload says so instead of presenting a TSS-like estimate as measured."""
    rows = [whoop_full(TODAY), cmetrics(TODAY, tsb=4, tsb_load_basis={"confidence": "duration_proxy"})]
    install(monkeypatch, rows)
    raw = th.tool_get_readiness_score({})["components"]["training_form"]["raw"]
    assert raw["load_basis"] == "duration_proxy"
    assert "duration-proxy basis" in raw["load_basis_note"]


def test_readiness_falls_back_to_live_whoop_when_the_computed_metrics_read_fails(monkeypatch):
    """A DynamoDB failure on the pre-computed partition must degrade to the live
    calculation, not take the whole answer down."""
    rows = [whoop_full(d(TODAY, -i), hrv=40 + i) for i in range(8)]
    t = install(monkeypatch, rows, raise_sources={"computed_metrics"})
    out = th.tool_get_readiness_score({})
    assert "computed_metrics" in t.sources_read
    assert out["components"]["hrv_trend"]["raw"]["source"] == "live_whoop_query"


def test_hydration_still_answers_when_the_weight_lookup_fails(monkeypatch):
    """The bodyweight target is a nicety; a Withings outage must not cost him the
    hydration report — it falls back to the flat default."""
    install(monkeypatch, HYDRATION_ROWS, raise_sources={"withings"})
    target = th.tool_get_daily_metrics({"view": "hydration"})["target"]
    assert target["daily_target_ml"] == 3000
    assert target["weight_kg"] is None


def test_readiness_survives_a_failing_training_load_fallback(monkeypatch):
    """The 264-day Banister fallback is the slowest thing this tool can do; if it
    blows up the remaining components must still produce an answer."""

    def _boom(_args):
        raise RuntimeError("strava read failed")

    monkeypatch.setattr(th, "_get_training_load", _boom)
    install(monkeypatch, [whoop_full(TODAY, recovery=60, sleep_score=80)])
    out = th.tool_get_readiness_score({})
    assert "training_form" not in out["components"]
    # 60*0.40 + 80*0.25 = 24 + 20 = 44 / 0.65 = 67.69 -> 67.7
    assert out["readiness_score"] == 67.7


# ──────────────────────────────────────────────────────────────────────────────
# 2. get_weight_loss_progress — the core coaching report
# ──────────────────────────────────────────────────────────────────────────────

# Four weigh-ins, exactly 7 days apart, losing 3 lbs/week.
WEIGH_INS = [
    withings("2026-04-01", weight_lbs=320.0),
    withings("2026-04-08", weight_lbs=317.0),
    withings("2026-04-15", weight_lbs=314.0),
    withings("2026-04-22", weight_lbs=311.0),
]


def test_weight_loss_reports_hand_derived_rate_bmi_and_projection(monkeypatch):
    """height 72in, so BMI = 703 * lbs / 72^2 = 703 * lbs / 5184.

    current 311 lbs -> 703*311/5184 = 218633/5184 = 42.176 -> 42.2 (Obese Class II band is
      35 <= bmi < 40, so 42.2 is still Class III)
    weekly rate at each of the last 3 points: (prior - current)/7 * 7 = 3.0 lbs/wk
    avg_weekly = (3.0+3.0+3.0)/3 = 3.0
    total_lost = 320.0 - 311.0 = 9.0
    weeks_remaining = (311 - 200)/3.0 = 37.0
    pct_complete = 100 * (320-311)/(320-200) = 900/120 = 7.5
    """
    install(monkeypatch, WEIGH_INS)
    out = th.tool_get_weight_loss_progress({})
    assert out["current_weight_lbs"] == 311.0
    assert out["current_bmi"] == 42.2
    assert out["current_bmi_category"] == "Obese Class III"
    assert out["total_lost_lbs"] == 9.0
    assert out["avg_weekly_loss_lbs"] == 3.0
    assert out["projection"]["lbs_remaining"] == 111.0
    assert out["projection"]["weeks_remaining"] == 37.0
    assert out["projection"]["pct_complete"] == 7.5


def test_weight_loss_flags_a_rate_above_the_acsm_safe_ceiling(monkeypatch):
    """3.0 lbs/wk > 2.5 -> the lean-mass warning fires on every affected point."""
    install(monkeypatch, WEIGH_INS)
    out = th.tool_get_weight_loss_progress({})
    flagged = [p for p in out["weight_series"] if "Losing too fast" in p.get("rate_flag", "")]
    assert len(flagged) == 3


def test_weight_loss_names_the_next_bmi_milestone_with_the_lbs_to_cross(monkeypatch):
    """Weight at BMI 39.9 with height 72in = 39.9 * 5184 / 703 = 206841.6/703 = 294.227 lbs.
    lbs_to_cross = 311 - 294.227 = 16.773 -> 16.8
    weeks_at_current_pace = 16.8 / mean(last 4 rates = [3.0,3.0,3.0]) = 16.8/3.0 = 5.6
    """
    install(monkeypatch, WEIGH_INS)
    nm = th.tool_get_weight_loss_progress({})["next_milestone"]
    assert nm["lbs_to_cross"] == 16.8
    assert nm["weeks_at_current_pace"] == 5.6


def test_weight_loss_honours_an_explicit_start_date(monkeypatch):
    """The caller's window is used verbatim rather than being overridden by
    journey_start — and the DDB query proves it."""
    t = install(monkeypatch, WEIGH_INS)
    out = th.tool_get_weight_loss_progress({"start_date": "2026-04-15", "end_date": "2026-04-22"})
    assert t.window_for("withings") == ("2026-04-15", "2026-04-22")
    assert [p["date"] for p in out["weight_series"]] == ["2026-04-15", "2026-04-22"]


def test_weight_loss_reports_the_pre_genesis_state_instead_of_an_inverted_query(monkeypatch):
    """A genesis anchored ahead of today would make start > end and raise a DDB
    ValidationException; the guard returns the honest pre-genesis answer."""
    profile = dict(PROFILE, journey_start_date="2026-09-01")
    install(monkeypatch, WEIGH_INS, profile=profile)
    out = th.tool_get_weight_loss_progress({"end_date": TODAY})
    assert out["pre_genesis"] is True
    assert out["journey_start_date"] == "2026-09-01"


def test_weight_loss_errors_rather_than_inventing_a_weight_when_the_scale_is_quiet(monkeypatch):
    install(monkeypatch, [])
    out = th.tool_get_weight_loss_progress({})
    assert "error" in out and "current_weight_lbs" not in out


def test_weight_loss_errors_when_withings_rows_carry_no_weight_field(monkeypatch):
    install(monkeypatch, [withings("2026-04-01", fat_ratio=38.0)])
    assert "weight_lbs" in th.tool_get_weight_loss_progress({})["error"]


def test_weight_loss_detects_a_plateau_from_a_tight_recent_spread(monkeypatch):
    """Three weigh-ins inside the 14-day lookback, spread 310.4 - 310.0 = 0.4 < 1.5."""
    rows = [
        withings(d(TODAY, -4), weight_lbs=310.2),
        withings(d(TODAY, -2), weight_lbs=310.4),
        withings(TODAY, weight_lbs=310.0),
    ]
    install(monkeypatch, rows)
    plateau = th.tool_get_weight_loss_progress({})["plateau_detected"]
    assert plateau["detected"] is True
    assert plateau["weight_range_lbs"] == pytest.approx(0.4, abs=1e-9)


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (#1917 window-name honesty, P1, mcp/tools_health.py:540-545 "
        "tool_get_weight_loss_progress): `duration_days` is the HARDCODED literal 14 and the note "
        "reads 'Scale has moved less than 1.5 lbs in 14 days' — regardless of how far the three "
        "qualifying weigh-ins actually span. Here they span 4 days (TODAY-4 .. TODAY) and the tool "
        "still asserts a 14-day plateau. Should report the real first-to-last span. Who it hurts: "
        "Matthew reads a 14-day stall that never happened and cuts calories in response."
    ),
)
def test_weight_loss_plateau_duration_is_the_real_span_not_a_literal_fourteen(monkeypatch):
    rows = [
        withings(d(TODAY, -4), weight_lbs=310.2),
        withings(d(TODAY, -2), weight_lbs=310.4),
        withings(TODAY, weight_lbs=310.0),
    ]
    install(monkeypatch, rows)
    plateau = th.tool_get_weight_loss_progress({})["plateau_detected"]
    assert plateau["duration_days"] == 4  # TODAY-4 .. TODAY


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (P2, mcp/tools_health.py:532-534 tool_get_weight_loss_progress): plateau detection "
        "filters on `datetime.now(timezone.utc).date() - point_date <= 14` — a LIVE clock spliced "
        "into a report whose window the caller chose. Ask for a historical `end_date` and "
        "`recent_14` is empty, so a real plateau inside the requested window is invisible; the same "
        "`<= 14` also admits FUTURE-dated points (negative day counts). The 14-day lookback must "
        "hang off `end_date`, the report's own anchor."
    ),
)
def test_weight_loss_plateau_lookback_hangs_off_the_requested_end_date(monkeypatch):
    """The same three tight weigh-ins, moved into a historical window that the
    caller explicitly asks about."""
    rows = [
        withings("2026-02-20", weight_lbs=310.2),
        withings("2026-02-22", weight_lbs=310.4),
        withings("2026-02-24", weight_lbs=310.0),
    ]
    install(monkeypatch, rows, profile=dict(PROFILE, journey_start_date="2026-02-01"))
    out = th.tool_get_weight_loss_progress({"end_date": "2026-02-24"})
    assert out["plateau_detected"] is not None


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (ADR-104, P1, mcp/tools_health.py:523 tool_get_weight_loss_progress): "
        "`weeks_at_current_pace` divides by `max(mean(last 4 weekly rates), 0.1)`. When the recent "
        "pace is a GAIN the mean is negative, the floor clamps it to 0.1 lb/wk, and the tool "
        "publishes a confident finite ETA (here 11.8/0.1 = 118.0 weeks) for a milestone he is "
        "currently moving AWAY from. The floor was meant to avoid a divide-by-zero; it manufactures "
        "a direction instead. Should be None with the reversal stated. Who it hurts: a countdown "
        "to a goal while gaining 2 lbs/week."
    ),
)
def test_weight_loss_gives_no_eta_when_the_recent_pace_is_a_gain(monkeypatch):
    rows = [
        withings("2026-04-01", weight_lbs=300.0),
        withings("2026-04-08", weight_lbs=302.0),
        withings("2026-04-15", weight_lbs=304.0),
        withings("2026-04-22", weight_lbs=306.0),
    ]
    install(monkeypatch, rows)
    nm = th.tool_get_weight_loss_progress({})["next_milestone"]
    assert nm["weeks_at_current_pace"] is None


def test_weight_loss_flags_a_stalled_rate_over_a_long_daily_series(monkeypatch):
    """16 daily weigh-ins dropping 0.01 lb/day: the 7-day-paired rate is
    (w[i-7] - w[i]) = 0.07 lb/wk — non-negative, under 0.25, and the series is
    longer than 14 points, so the 'review deficit' nudge fires."""
    rows = [withings(d("2026-04-25", i), weight_lbs=round(310.0 - 0.01 * i, 2)) for i in range(16)]
    install(monkeypatch, rows)
    out = th.tool_get_weight_loss_progress({})
    assert any("Very slow" in p.get("rate_flag", "") for p in out["weight_series"])


def test_weight_loss_omits_bmi_entirely_when_height_is_recorded_as_zero(monkeypatch):
    """The honest branch: `calc_bmi` returns None for a falsy height, so no BMI,
    no clinical category and no milestone are published. Note the asymmetry with
    a MISSING height — see the next test."""
    install(monkeypatch, WEIGH_INS, profile=dict(PROFILE, height_inches=0))
    out = th.tool_get_weight_loss_progress({})
    assert out["current_bmi"] is None
    assert out["current_bmi_category"] is None
    assert out["next_milestone"] is None


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (ADR-104, P1, mcp/tools_health.py:406 + 439-443 tool_get_weight_loss_progress): "
        "`height_in = profile.get('height_inches', 70)` — when the profile cannot be loaded the "
        "tool silently assumes 70in and publishes a BMI, a CLINICAL BMI CATEGORY, milestone "
        "crossings and lbs-to-cross derived from that guess, with no note anywhere that the height "
        "was assumed. At 311 lbs the assumed 70in gives BMI 44.6 vs 42.2 at his real 72in. Absent "
        "input should yield an absent BMI, not a fabricated clinical classification."
    ),
)
def test_weight_loss_omits_bmi_when_height_is_unknown(monkeypatch):
    install(monkeypatch, WEIGH_INS, profile={"pk": "USER#matthew", "sk": "PROFILE#v1"})
    out = th.tool_get_weight_loss_progress({})
    assert out["current_bmi"] is None and out["current_bmi_category"] is None


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (ADR-105, P2, mcp/tools_health.py:550 + 556-565 tool_get_weight_loss_progress): "
        "`avg_weekly_loss_lbs` is a mean over `weekly_rates` and it — plus the projected goal date "
        "and pct_complete derived from it — ships with no n. Three paired weigh-ins and thirty "
        "produce identically-confident output. The projection block should state how many weekly "
        "rates back the average."
    ),
)
def test_weight_loss_projection_states_how_many_weekly_rates_it_averaged(monkeypatch):
    install(monkeypatch, WEIGH_INS)
    proj = th.tool_get_weight_loss_progress({})["projection"]
    assert proj.get("n_weekly_rates") == 3


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (P2, mcp/tools_health.py:555 tool_get_weight_loss_progress): the projected goal "
        "date is `datetime.now(utc) + weeks_remaining` — anchored to the WALL CLOCK rather than to "
        "the last weigh-in the projection was computed from. Request a historical `end_date` (or "
        "just go three weeks without stepping on the scale) and the goal date silently slides "
        "forward while the underlying rate never changed. Should be last-weigh-in + weeks_remaining."
    ),
)
def test_weight_loss_projects_forward_from_the_last_weigh_in_not_from_now(monkeypatch):
    install(monkeypatch, WEIGH_INS)
    proj = th.tool_get_weight_loss_progress({"end_date": "2026-04-22"})["projection"]
    # weeks_remaining 37.0 -> 259 days past the LAST weigh-in (2026-04-22), not past NOW
    assert proj["projected_goal_date"] == d("2026-04-22", 259)


# ──────────────────────────────────────────────────────────────────────────────
# 3. get_daily_metrics — the view dispatcher
# ──────────────────────────────────────────────────────────────────────────────


def test_daily_metrics_routes_every_view_the_registry_declares(monkeypatch):
    """Derived-SET guard: the schema's `view` enum and the dispatcher's
    VALID_VIEWS must not drift apart. A newly declared enum value that isn't
    routed would answer "Unknown view" to a schema-conformant client."""
    monkeypatch.setattr("mcp.tools_lifestyle._get_movement_score", lambda a: {"_view": "movement"})
    install(monkeypatch, [])
    for view in _declared_views("get_daily_metrics"):
        out = th.tool_get_daily_metrics({"view": view})
        assert "Unknown view" not in str(out.get("error", "")), view


def test_daily_metrics_rejects_an_unknown_view_with_the_declared_alternatives(monkeypatch):
    install(monkeypatch, [])
    out = th.tool_get_daily_metrics({"view": "sleep"})
    assert "Unknown view" in out["error"]
    assert set(out["valid_views"]) == set(_declared_views("get_daily_metrics"))


def test_daily_metrics_defaults_to_movement(monkeypatch):
    monkeypatch.setattr("mcp.tools_lifestyle._get_movement_score", lambda a: {"_view": "movement"})
    install(monkeypatch, [])
    assert th.tool_get_daily_metrics({})["_view"] == "movement"


# ── 3a. view=energy ───────────────────────────────────────────────────────────

ENERGY_ROWS = [
    withings(TODAY, weight_lbs=220.0),
    strava(TODAY, total_moving_time_seconds=3600, activities=[{"moving_time_seconds": 3600, "kilojoules": 900}]),
]


def test_energy_computes_mifflin_st_jeor_bmr_from_weight_height_and_age(monkeypatch):
    """220 lbs -> 220 * 0.453592 = 99.79024 kg;  72 in -> 182.88 cm
    BMR(male) = 10*99.79024 + 6.25*182.88 - 5*age + 5
              = 997.9024 + 1143.0 - 175 + 5 = 1970.9 -> 1971   (age falls back to 35)
    """
    install(monkeypatch, ENERGY_ROWS)
    out = th.tool_get_daily_metrics({"view": "energy"})
    assert out["bmr_formula"] == "Mifflin-St Jeor"
    assert out["bmr_kcal"] == 1971.0
    assert out["current_weight_lbs"] == 220.0


def test_energy_derives_the_calorie_target_and_implied_loss_rate(monkeypatch):
    """No day-level kJ exists (see the writer test below), so exercise energy falls
    to the MET proxy: 6 * 99.79024 kg * 1.0 h = 598.74 -> 599 kcal.
    ex_daily_7d_avg = 599 / 7 = 85.57 -> 86 ; tdee_7d = 1971 + 86 = 2057
    calorie_target(7d) = 2057 - 500 = 1557
    implied_weekly_loss = 500 * 7 / 3500 = 1.0 lb
    """
    install(monkeypatch, ENERGY_ROWS)
    out = th.tool_get_daily_metrics({"view": "energy"})
    assert out["exercise_kcal_7d_daily_avg"] == 86.0
    assert out["tdee_7d_avg"] == 2057.0
    assert out["calorie_target_based_on_7d"] == 1557.0
    assert out["implied_weekly_loss_lbs"] == 1.0


def test_energy_reports_the_bmr_drop_since_the_journey_start_weight(monkeypatch):
    """320 lbs -> 145.14944 kg -> BMR 10*145.14944 + 1143 - 175 + 5 = 2424.5 -> 2424 (banker's
    rounding of .49444 is irrelevant; the value rounds down to 2424).
    reduction = 2424 - 1971 = 453
    """
    install(monkeypatch, ENERGY_ROWS)
    change = th.tool_get_daily_metrics({"view": "energy"})["bmr_change_since_start"]
    assert change["bmr_at_start_weight"] == 2424.0
    assert change["bmr_now"] == 1971.0
    assert change["bmr_reduction_kcal"] == 453.0


def test_energy_errors_rather_than_guessing_a_weight(monkeypatch):
    install(monkeypatch, [strava(TODAY, total_moving_time_seconds=3600)])
    assert "error" in th.tool_get_daily_metrics({"view": "energy"})


def test_energy_uses_the_female_mifflin_constant_when_the_profile_says_so(monkeypatch):
    """BMR(female) = 10*kg + 6.25*cm - 5*age - 161
                   = 997.9024 + 1143.0 - 175 - 161 = 1804.9 -> 1805
    start weight 320 lbs -> 145.14944 kg -> 1451.4944 + 1143 - 175 - 161 = 2258.5 -> 2258
    """
    install(monkeypatch, ENERGY_ROWS, profile=dict(PROFILE, biological_sex="Female"))
    out = th.tool_get_daily_metrics({"view": "energy"})
    assert out["bmr_kcal"] == 1805.0
    assert out["bmr_change_since_start"]["bmr_at_start_weight"] == 2258.0


def test_energy_honours_a_custom_deficit_target(monkeypatch):
    """750 kcal/day -> 750*7/3500 = 1.5 lb/week implied, and the target shifts with it:
    tdee_7d 2057 - 750 = 1307."""
    install(monkeypatch, ENERGY_ROWS)
    out = th.tool_get_daily_metrics({"view": "energy", "target_deficit_kcal": 750})
    assert out["implied_weekly_loss_lbs"] == 1.5
    assert out["calorie_target_based_on_7d"] == 1307.0


def test_energy_uses_day_level_kilojoules_when_the_field_is_present(monkeypatch):
    """The kJ branch itself is correct — 900 kJ counted 1:1 as kcal, 900/7 = 128.57
    -> 129 kcal/day. It is simply never reached in production, because nothing
    writes `total_kilojoules` (see the two xfails immediately below)."""
    rows = [withings(TODAY, weight_lbs=220.0), strava(TODAY, total_kilojoules=900, total_moving_time_seconds=3600)]
    install(monkeypatch, rows)
    assert th.tool_get_daily_metrics({"view": "energy"})["exercise_kcal_7d_daily_avg"] == 129.0


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (reader/writer field mismatch, P2, mcp/tools_health.py:628 "
        "_get_energy_expenditure — same class at mcp/tools_nutrition.py:646, mcp/helpers.py:75, "
        "mcp/tools_lifestyle.py:1677): every one of them reads a DAY-LEVEL `total_kilojoules` off "
        "the strava partition, and `ingestion/strava_lambda.py:300-311 transform()` never writes "
        "it — it rolls up total_distance_miles / total_moving_time_seconds / "
        "total_elevation_gain_feet / total_zone2_seconds and nothing else. The per-activity "
        "`kilojoules` IS captured (strava_lambda.py:173), it just is never summed. This test calls "
        "the real transform, so it cannot drift from the writer."
    ),
)
def test_the_strava_writer_produces_the_day_level_kilojoules_field_these_tools_read():
    from ingestion import strava_lambda

    produced = strava_lambda.transform(
        {"activities": [{"kilojoules": 900, "moving_time_seconds": 3600, "distance_miles": 5.0}]},
        TODAY,
    )[0]
    assert "total_kilojoules" in produced


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (ADR-104 provenance, P2, mcp/tools_health.py:627-633 _get_energy_expenditure): the "
        "consequence of the missing `total_kilojoules` rollup above. `total_kj` is always 0, so "
        "every TDEE this tool has ever returned came from the `6 kcal/kg/h` duration proxy rather "
        "than from the power/kJ data Strava supplied — and the payload says nothing about which "
        "branch ran. 900 kJ of real work is reported as 599 proxy kcal. Fix either the writer or "
        "read `sum(a['kilojoules'] for a in activities)`; either way label the basis."
    ),
)
def test_energy_uses_the_measured_kilojoules_when_strava_supplied_them(monkeypatch):
    from ingestion import strava_lambda

    day = strava_lambda.transform({"activities": [{"kilojoules": 900, "moving_time_seconds": 3600}]}, TODAY)[0]
    day.pop("source", None)  # the row builder supplies pk/sk/date; `source` would collide
    install(monkeypatch, [withings(TODAY, weight_lbs=220.0), row("strava", day.pop("date"), **day)])
    out = th.tool_get_daily_metrics({"view": "energy"})
    # 900 kJ over one day -> 900/7 = 128.6 -> 129 kcal/day, not the 599/7 = 86 proxy
    assert out["exercise_kcal_7d_daily_avg"] == 129.0


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (ADR-104 fabricated input, P1, mcp/tools_health.py:614-620 "
        "_get_energy_expenditure): `age_years = (datetime.now(timezone.utc) - "
        "datetime.strptime(dob_str, '%Y-%m-%d')).days / 365.25` subtracts a NAIVE datetime from an "
        "AWARE one, which raises TypeError on every single call. The bare `except Exception: pass` "
        "swallows it, so `age_years` is always None and always falls back to the hardcoded 35. The "
        "profile's real date_of_birth can never reach the BMR — it is dead code that looks live. "
        "Mifflin-St Jeor is 5 kcal per year of age, so at DOB 1980 the BMR is overstated by ~57 "
        "kcal/day, and that error propagates into tdee, calorie_target and bmr_change_since_start."
    ),
)
def test_energy_uses_the_profile_date_of_birth_for_the_bmr_age_term(monkeypatch):
    dob = "1980-01-01"
    install(monkeypatch, ENERGY_ROWS, profile=dict(PROFILE, date_of_birth=dob))
    # age from the FIXTURE clock (never datetime.now): (2026-05-10 - 1980-01-01).days / 365.25
    age = (NOW.replace(tzinfo=None) - datetime.strptime(dob, "%Y-%m-%d")).days / 365.25
    expected = round(10 * (220 * 0.453592) + 6.25 * (72 * 2.54) - 5 * age + 5, 0)
    assert th.tool_get_daily_metrics({"view": "energy"})["bmr_kcal"] == expected


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (P1, mcp/tools_health.py:590-592 _get_energy_expenditure): `end_date` comes from "
        "args but BOTH window starts are computed from `datetime.now()` — `d30_start = now - 30`, "
        "`d7_start = now - 7`. Ask for a historical end_date and the tool issues `sk BETWEEN "
        "DATE#<recent> AND DATE#<older>~`, which DynamoDB rejects with a ValidationException; the "
        "result is stamped `as_of_date: <requested>` regardless. `start_date` is declared in the "
        "registry schema for this tool and is ignored entirely. The window must hang off end_date."
    ),
)
def test_energy_windows_hang_off_the_requested_end_date(monkeypatch):
    t = install(monkeypatch, ENERGY_ROWS)
    th.tool_get_daily_metrics({"view": "energy", "end_date": "2026-03-01"})
    assert all(lo <= hi for _, lo, hi in t.queries), f"inverted query window: {t.queries}"


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (#1917, P2, mcp/tools_health.py:591-592 + 640-641 _get_energy_expenditure): the "
        "windows are `now - 7` / `now - 30` fed to an INCLUSIVE `sk BETWEEN`, so they span 8 and 31 "
        "dates — but the totals are then divided by the literals 7 and 30 and published as "
        "`exercise_kcal_7d_daily_avg` / `exercise_kcal_30d_daily_avg`. An 8-day sum over a 7-day "
        "divisor overstates the daily average by 1/7 (~14%), which flows straight into tdee_7d_avg "
        "and the calorie target he eats to."
    ),
)
def test_energy_seven_day_window_really_spans_seven_days(monkeypatch):
    t = install(monkeypatch, ENERGY_ROWS)
    th.tool_get_daily_metrics({"view": "energy"})
    windows = [(lo, hi) for s, lo, hi in t.queries if s == "strava"]
    assert min(span_days(lo, hi) for lo, hi in windows) == 7


# ── 3b. view=hydration ────────────────────────────────────────────────────────

HYDRATION_ROWS = [
    withings(TODAY, weight_lbs=220.0),
    apple("2026-05-01", water_intake_ml=3000),
    apple("2026-05-02", water_intake_ml=3200),
    apple("2026-05-03", water_intake_ml=2000),
    apple("2026-05-04", water_intake_ml=3400),
    apple("2026-05-05", water_intake_ml=400),  # below the 500ml reading floor -> not data
]


def test_hydration_targets_thirtyfive_ml_per_kg_of_bodyweight(monkeypatch):
    """220 lbs -> 99.8 kg (rounded to 1dp by the tool); 99.8 * 35 = 3493 ml.
    3493 / 29.5735 ml-per-US-fl-oz = 118.11 -> 118.1 oz."""
    install(monkeypatch, HYDRATION_ROWS)
    target = th.tool_get_daily_metrics({"view": "hydration"})["target"]
    assert target["weight_kg"] == 99.8
    assert target["daily_target_ml"] == 3493
    assert target["daily_target_oz"] == 118.1


def test_hydration_summary_is_hand_derivable_from_the_four_real_readings(monkeypatch):
    """Readings >= 500ml: 3000, 3200, 2000, 3400  (the 400ml row is not data).
    avg_ml   = 11600/4 = 2900
    avg_oz   = 2900/29.5735 = 98.06 -> 98.1
    pct_target per day: 85.9 / 91.6 / 57.3 / 97.3 ; scores 86 / 92 / 57 / 97
    avg_score = 332/4 = 83.0
    met_target (>= 90% of 3493 = 3143.7): False / True / False / True -> 2 deficit days
    adequacy = (4-2)/4 * 100 = 50.0
    """
    install(monkeypatch, HYDRATION_ROWS)
    out = th.tool_get_daily_metrics({"view": "hydration"})
    assert out["period"]["days_with_data"] == 4
    assert out["summary"]["zero_data_days"] == 1
    assert out["summary"]["avg_ml"] == 2900.0
    assert out["summary"]["avg_oz"] == 98.1
    assert out["summary"]["avg_score"] == 83.0
    assert out["summary"]["adequacy_rate_pct"] == 50.0
    assert out["summary"]["deficit_days"] == 2


def test_hydration_reports_the_n_behind_its_averages(monkeypatch):
    """ADR-105: `days_with_data` and `zero_data_days` are both published, so a
    3-of-30-days average is visibly a 3-day average."""
    install(monkeypatch, HYDRATION_ROWS)
    out = th.tool_get_daily_metrics({"view": "hydration"})
    assert out["period"]["days_with_data"] + out["summary"]["zero_data_days"] == 5


def test_hydration_errors_when_no_reading_clears_the_five_hundred_ml_floor(monkeypatch):
    install(monkeypatch, [withings(TODAY, weight_lbs=220.0), apple("2026-05-01", water_intake_ml=100)])
    out = th.tool_get_daily_metrics({"view": "hydration"})
    assert "error" in out and out["zero_data_days"] == 1


def test_hydration_errors_when_apple_health_is_silent(monkeypatch):
    install(monkeypatch, [withings(TODAY, weight_lbs=220.0)])
    assert "HAE" in th.tool_get_daily_metrics({"view": "hydration"})["error"]


def test_hydration_honours_an_explicit_target_override(monkeypatch):
    """4000 ml / 29.5735 = 135.26 -> 135.3 oz."""
    install(monkeypatch, HYDRATION_ROWS)
    target = th.tool_get_daily_metrics({"view": "hydration", "target_ml": 4000})["target"]
    assert target["daily_target_ml"] == 4000.0
    assert target["daily_target_oz"] == 135.3


def test_hydration_falls_back_to_a_flat_default_and_says_so_when_weight_is_unknown(monkeypatch):
    """No Withings row in the 14-day lookback: the target is the flat 3000 ml
    default and `basis` names it rather than implying a bodyweight calculation."""
    install(monkeypatch, [r for r in HYDRATION_ROWS if "withings" not in r["pk"]])
    target = th.tool_get_daily_metrics({"view": "hydration"})["target"]
    assert target["daily_target_ml"] == 3000
    assert target["weight_kg"] is None
    assert target["basis"] == "3000ml default"


def test_hydration_skips_a_row_that_carries_no_date(monkeypatch):
    """A malformed row must not become a breakdown entry keyed on an empty date."""
    rows = list(HYDRATION_ROWS) + [{"pk": PK + "apple_health", "sk": "DATE#2026-05-06", "water_intake_ml": 3000}]
    install(monkeypatch, rows)
    out = th.tool_get_daily_metrics({"view": "hydration"})
    assert out["period"]["days_with_data"] == 4
    assert all(r["date"] for r in out["daily_breakdown"])


def test_hydration_recommendations_name_the_gap_the_miss_rate_and_the_inversion(monkeypatch):
    """No weight -> 3000 ml target.
    intake 1500 / 1600 / 2400 / 2500 -> avg 8000/4 = 2000, which is below 0.8*3000 = 2400
      -> gap = (3000-2000)/1000 = 1.0 L/day
    met_target needs >= 2700 -> 0 of 4 met -> 4 deficit days > 4*0.5 -> the miss-rate rec
    exercise days (>20 min) 05-01/05-02 avg 1550 vs rest days 05-03/05-04 avg 2450
      -> drinking LESS on training days -> the inversion rec
    """
    acts = [{"moving_time_seconds": 1800, "average_heartrate": 140}]
    rows = [
        apple("2026-05-01", water_intake_ml=1500),
        apple("2026-05-02", water_intake_ml=1600),
        apple("2026-05-03", water_intake_ml=2400),
        apple("2026-05-04", water_intake_ml=2500),
        strava("2026-05-01", activities=acts),
        strava("2026-05-02", activities=acts),
    ]
    install(monkeypatch, rows)
    out = th.tool_get_daily_metrics({"view": "hydration"})
    assert out["exercise_correlation"]["exercise_days_avg_ml"] == 1550.0
    assert out["exercise_correlation"]["rest_days_avg_ml"] == 2450.0
    recs = " | ".join(out["recommendations"])
    assert "Add ~1.0L/day" in recs
    assert "4/4 days" in recs
    assert "drinking LESS on training days" in recs


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (ADR-104, P2, mcp/tools_health.py:771 _get_hydration_score): "
        "`'exercise_min': ex['total_min'] if ex else 0` renders a day with NO Strava record as a "
        "factual zero minutes of exercise. Ten lines further down that fabricated 0 is used to "
        "CLASSIFY the day: `rest_days = [r for r in daily_rows if r['exercise_min'] <= 20]`, so "
        "every unmeasured day is counted as a rest day and the 'you drink LESS on training days' "
        "recommendation is computed against a rest-day average made mostly of unknowns. Absence "
        "should be None and excluded from the split."
    ),
)
def test_hydration_does_not_report_an_unmeasured_day_as_zero_exercise_minutes(monkeypatch):
    install(monkeypatch, HYDRATION_ROWS)
    rows = th.tool_get_daily_metrics({"view": "hydration"})["daily_breakdown"]
    assert all(r["exercise_min"] is None for r in rows)


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (P2, mcp/tools_health.py:791-797 _get_hydration_score): `current_streak_days` walks "
        "`reversed(daily_rows)`, but daily_rows contains only days that cleared the 500ml floor — "
        "unlogged days were `continue`d out. The streak therefore jumps calendar gaps: two "
        "on-target days in April and two in May read as a 4-day streak across a 17-day silence. It "
        "is also not anchored to today, so a streak that ended weeks ago is still reported as "
        "'current'. Should break on a missing calendar day and on staleness."
    ),
)
def test_hydration_streak_breaks_across_a_gap_of_unlogged_days(monkeypatch):
    rows = [
        withings(TODAY, weight_lbs=220.0),
        apple("2026-04-20", water_intake_ml=3500),
        apple("2026-04-21", water_intake_ml=3500),
        apple("2026-05-09", water_intake_ml=3500),
        apple("2026-05-10", water_intake_ml=3500),
    ]
    install(monkeypatch, rows)
    assert th.tool_get_daily_metrics({"view": "hydration"})["summary"]["current_streak_days"] == 2


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (P3, mcp/tools_health.py:719 + 833 _get_hydration_score): the target is "
        "`max(2500, weight_kg * 35)` but `basis` is unconditionally the string "
        "f'35ml/kg x {weight_kg}kg'. When the 2500ml floor wins, the stated basis multiplies out to "
        "a DIFFERENT number than the target it claims to explain (120 lbs -> 54.4 kg -> 1904 ml, "
        "reported as the basis for a 2500 ml target). Latent at Matthew's weight; wrong the moment "
        "it is not."
    ),
)
def test_hydration_basis_states_the_floor_when_the_floor_is_what_set_the_target(monkeypatch):
    rows = [withings(TODAY, weight_lbs=120.0), apple("2026-05-01", water_intake_ml=2000)]
    install(monkeypatch, rows)
    target = th.tool_get_daily_metrics({"view": "hydration"})["target"]
    assert target["daily_target_ml"] == 2500
    assert "2500" in target["basis"]


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (P2, mcp/tools_health.py:691-692 _get_hydration_score): same class as the energy "
        "view — `start_date` defaults to `now - 30` while `end_date` comes from args, so passing "
        "only `end_date` (a documented registry parameter) yields an inverted `sk BETWEEN` window "
        "that DynamoDB rejects. Two of the three views behind get_daily_metrics share this bug."
    ),
)
def test_hydration_windows_hang_off_the_requested_end_date(monkeypatch):
    t = install(monkeypatch, HYDRATION_ROWS)
    th.tool_get_daily_metrics({"view": "hydration", "end_date": "2026-03-01"})
    assert all(lo <= hi for _, lo, hi in t.queries), f"inverted query window: {t.queries}"


# ──────────────────────────────────────────────────────────────────────────────
# 4. Cross-cutting: no tool reaches a partition it has no business reading
# ──────────────────────────────────────────────────────────────────────────────


def test_readiness_reads_only_the_four_partitions_it_documents(monkeypatch):
    """A readiness check has no reason to touch labs, genome or nutrition. Pinned
    so a future 'while we're here' read shows up as a test failure rather than as
    a widened blast radius on an owner-facing tool."""
    t = install(monkeypatch, _readiness_rows())
    th.tool_get_readiness_score({})
    assert t.sources_read <= {"computed_metrics", "whoop", "garmin"}


def test_weight_loss_reads_only_withings(monkeypatch):
    t = install(monkeypatch, WEIGH_INS)
    th.tool_get_weight_loss_progress({})
    assert t.sources_read == {"withings"}


def test_no_health_tool_reaches_the_genome_or_labs_partitions(monkeypatch):
    """Genome per-variant identifiers are Tier-2 owner-only and labs are
    CROSS_PHASE clinical truth; neither belongs in a readiness/weight/energy
    answer. Asserted across every registered tool in the module at once."""
    monkeypatch.setattr("mcp.tools_lifestyle._get_movement_score", lambda a: {})
    t = install(monkeypatch, _readiness_rows() + WEIGH_INS + HYDRATION_ROWS)
    for name in sorted(MODULE_TOOLS):
        MODULE_TOOLS[name]["fn"]({})
    for view in _declared_views("get_daily_metrics"):
        th.tool_get_daily_metrics({"view": view})
    assert not (t.sources_read & {"genome", "labs", "dexa"})
