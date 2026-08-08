"""tests/test_mcp_tools_cgm_behavior.py — behavioral contracts for the MCP CGM
tools served by ``mcp/tools_cgm.py``:

    get_cgm   (view = dashboard | fasting)

This is the most medically consequential tool in the MCP surface. When Matthew
asks Claude Desktop "how's my glucose", "what's my time in range", "am I
pre-diabetic" or "is my fasting glucose real", the dict this module returns IS
the answer — nothing downstream re-derives it, and every number in it is read as
clinical fact. The ``mcp/tools_*`` family had **zero** dedicated behavioural
coverage before #1658 tranche 3.

The contracts pinned here:

  * **ADR-104 honest numbers** — a day the sensor did not measure is ABSENT. A
    glucose ``min`` of 0 mg/dL, a ``time_in_range`` of 0%, or a variability SD of
    0 are not facts about Matthew's blood; they are ``.get(key, 0)`` about a
    missing DynamoDB attribute, and once they enter a mean they fabricate a
    clinical flag.
  * **ADR-105 rigor** — every mean, percentile, z-score, agreement band and trend
    ships with the n behind it; a distribution statistic from a single night is
    not a distribution.
  * **Units** — the whole module is mg/dL. The writer
    (``lambdas/ingestion/health_auto_export_lambda.py::process_blood_glucose``)
    converts mmol/L at ingest with the 18.0182 factor, so every threshold
    constant here (100 / 140 / 70 / 180 / 25 SD) must be an mg/dL threshold. A
    100 mmol/L "optimal" bar would be nonsense, and a 5.5 mg/dL one would flag
    every day.
  * **Reader/writer field parity** — every DynamoDB attribute and every S3 key
    this module reads is checked against the Lambda that writes it. This is the
    class that left six features silently dark in tranche 2.
  * **#1917 window-name honesty** — a window named for N days spans N days.
  * **ADR-058 phase filtering** — ``apple_health`` is RAW_TIMESERIES and ``labs``
    is CROSS_PHASE in ``experiment.phase_taxonomy``; this file DERIVES both
    expectations from the taxonomy rather than restating them.
  * **Envelope parity** — the R13-F09 medical disclaimer and the empty-state
    payload.

Everything is driven through the real ``tool_get_cgm`` entry point with the
declared arguments, a frozen clock, and hand-rolled bounded fakes — never a
MagicMock inside a pagination-shaped read, never a real AWS or network call.

Arithmetic expectations are hand-derived in the test body and written as
literals, with the derivation shown in a comment — never "whatever the code
returned".
"""

from __future__ import annotations

import os

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")  # mcp.config requires these at import
os.environ.setdefault("USER_ID", "matthew")

import json  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from decimal import Decimal  # noqa: E402

import pytest  # noqa: E402
from experiment import phase_taxonomy  # noqa: E402

from mcp import core as mcore, tools_cgm as tc  # noqa: E402
from mcp.registry import TOOLS  # noqa: E402

# ──────────────────────────────────────────────────────────────────────────────
# Frozen clock
# ──────────────────────────────────────────────────────────────────────────────

NOW = datetime(2026, 8, 8, 17, 0, 0, tzinfo=timezone.utc)
TODAY = "2026-08-08"
_FROZEN = [NOW]


class _FrozenDatetime(datetime):
    """``datetime`` subclass with a pinned ``now()`` — a subclass rather than a
    Mock because the module calls ``strptime`` on the same name."""

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return _FROZEN[0].replace(tzinfo=None)
        return _FROZEN[0].astimezone(tz)

    @classmethod
    def utcnow(cls):
        return _FROZEN[0].replace(tzinfo=None)


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    _FROZEN[0] = NOW
    monkeypatch.setattr(tc, "datetime", _FrozenDatetime)
    yield


# ──────────────────────────────────────────────────────────────────────────────
# Bounded hand-rolled fakes
# ──────────────────────────────────────────────────────────────────────────────


def _condition_strings(expr) -> list:
    """Flatten the string leaves out of a boto3 ``Key(...)`` condition tree."""
    out: list = []
    for v in getattr(expr, "_values", ()):
        if isinstance(v, str):
            out.append(v)
        else:
            out.extend(_condition_strings(v))
    return out


def _pk_of(kwargs) -> str | None:
    for s in _condition_strings(kwargs.get("KeyConditionExpression")):
        if s.startswith("USER#"):
            return s
    return None


AH_PK = "USER#matthew#SOURCE#apple_health"
LABS_PK = "USER#matthew#SOURCE#labs"


class FakeDdb:
    """Bounded DynamoDB ``Table`` double.

    Dispatches on the real partition key and serves rows in the sk order a real
    query returns. ``paginate=True`` hands back exactly TWO pages (never more)
    so the ``LastEvaluatedKey`` contract can be exercised without a loop-shaped
    fake.
    """

    def __init__(self, rows_by_pk: dict | None = None, *, paginate: bool = False, preserve_order: bool = False):
        self.rows_by_pk = {k: list(v) for k, v in (rows_by_pk or {}).items()}
        self.paginate = paginate
        self.preserve_order = preserve_order
        self.query_calls: list = []

    def query(self, **kwargs):
        self.query_calls.append(kwargs)
        rows = self.rows_by_pk.get(_pk_of(kwargs), [])
        if not self.preserve_order:
            rows = sorted(rows, key=lambda r: r.get("sk", ""))
        else:
            rows = list(rows)
        if not self.paginate or len(rows) < 2:
            return {"Items": rows}
        if "ExclusiveStartKey" not in kwargs:
            return {"Items": rows[:1], "LastEvaluatedKey": {"pk": rows[0]["pk"], "sk": rows[0]["sk"]}}
        return {"Items": rows[1:]}


class _NoSuchKey(Exception):
    pass


class _S3Exceptions:
    NoSuchKey = _NoSuchKey


class _Body:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload


class FakeS3:
    """Bounded S3 double for the ``cgm_readings`` prefix.

    ``get_paginator('list_objects_v2').paginate`` yields ONE page per stored key
    and then stops — a finite generator over a dict the test wrote, not a mock
    that keeps answering. ``get_object`` raises the real ``NoSuchKey`` shape the
    module catches by name.
    """

    exceptions = _S3Exceptions()

    def __init__(self, objects: dict | None = None, *, unreadable: set | None = None, list_fails_for: set | None = None):
        self.objects = dict(objects or {})
        self.unreadable = set(unreadable or ())  # listed, but get_object raises
        self.list_fails_for = set(list_fails_for or ())  # year prefixes whose listing errors
        self.listed_prefixes: list = []
        self.fetched_keys: list = []

    def get_paginator(self, operation):
        assert operation == "list_objects_v2"
        outer = self

        class _Paginator:
            def paginate(self, Bucket, Prefix):  # noqa: N803 — boto3 kwarg casing
                outer.listed_prefixes.append(Prefix)
                if any(Prefix.endswith(p) for p in outer.list_fails_for):
                    raise RuntimeError("AccessDenied")
                for key in sorted(k for k in outer.objects if k.startswith(Prefix)):
                    yield {"Contents": [{"Key": key}]}

        return _Paginator()

    def get_object(self, Bucket, Key):  # noqa: N803 — boto3 kwarg casing
        self.fetched_keys.append(Key)
        if Key in self.unreadable or Key not in self.objects:
            raise _NoSuchKey(Key)
        return {"Body": _Body(json.dumps(self.objects[Key]).encode())}


@pytest.fixture
def ddb(monkeypatch):
    """``query_source`` reads ``mcp.core.table``; the fasting view's lab query reads
    ``mcp.tools_cgm.table``. Both imported the name by value, so both are patched —
    a re-export is not a patch point."""

    def _install(rows_by_pk, **kw):
        t = FakeDdb(rows_by_pk, **kw)
        monkeypatch.setattr(mcore, "table", t)
        monkeypatch.setattr(tc, "table", t)
        return t

    return _install


@pytest.fixture
def s3(monkeypatch):
    def _install(objects=None, **kw):
        c = FakeS3(objects, **kw)
        monkeypatch.setattr(tc, "s3_client", c)
        return c

    return _install


# ──────────────────────────────────────────────────────────────────────────────
# Row builders — field names copied from the WRITER, not invented
#   lambdas/ingestion/health_auto_export_lambda.py::process_blood_glucose
# ──────────────────────────────────────────────────────────────────────────────

WRITER_GLUCOSE_FIELDS = {
    "blood_glucose_avg",
    "blood_glucose_min",
    "blood_glucose_max",
    "blood_glucose_std_dev",
    "blood_glucose_readings_count",
    "blood_glucose_time_in_range_pct",
    "blood_glucose_time_in_optimal_pct",
    "blood_glucose_time_below_70_pct",
    "blood_glucose_time_above_140_pct",
    "cgm_source",
}


def _glucose_day(date, avg, *, mn=80, mx=150, sd=20, n=288, tir=96, above140=4, below70=0, source="dexcom_stelo", **extra):
    row = {
        "pk": AH_PK,
        "sk": f"DATE#{date}",
        "date": date,
        "blood_glucose_avg": avg,
        "blood_glucose_min": mn,
        "blood_glucose_max": mx,
        "blood_glucose_std_dev": sd,
        "blood_glucose_readings_count": n,
        "blood_glucose_time_in_range_pct": tir,
        "blood_glucose_time_above_140_pct": above140,
        "blood_glucose_time_below_70_pct": below70,
        "cgm_source": source,
    }
    row.update(extra)
    return row


def _partial_glucose_day(date, avg):
    """A day carrying ONLY the mean.

    Real shape, two ways: rows written before the time-in-range / below-70 fields
    were added to the writer, and any partial merge into an existing DATE# row.
    Everything else about the day is genuinely unmeasured.
    """
    return {"pk": AH_PK, "sk": f"DATE#{date}", "date": date, "blood_glucose_avg": avg}


def _reading(hh, mm, value, day="2026-05-01"):
    """One S3 CGM reading, in the writer's exact timestamp format
    (``parse_timestamp`` -> ``"%Y-%m-%d %H:%M:%S %z"``)."""
    return {"time": f"{day} {hh:02d}:{mm:02d}:00 -0700", "value": value, "meal_time": "Unspecified"}


def _cgm_key(date: str) -> str:
    """The S3 key the WRITER uses: health_auto_export_lambda.save_cgm_readings_to_s3
    builds ``raw/{USER_ID}/cgm_readings/{YYYY}/{MM}/{DD}.json``."""
    return f"raw/matthew/cgm_readings/{date[:4]}/{date[5:7]}/{date[8:10]}.json"


# A clean overnight day used by the fasting tests. Hand-derived below.
NIGHT_2026_05_01 = [
    _reading(0, 0, 100),
    _reading(1, 0, 95),
    _reading(2, 0, 90),
    _reading(2, 30, 85),
    _reading(3, 0, 85),
    _reading(4, 0, 88),
    _reading(5, 0, 92),
    _reading(12, 0, 150),  # postprandial, outside every nadir window
]


def _lab_draw(sk_date, draw_date, glucose, provider="Function Health"):
    return {
        "pk": LABS_PK,
        "sk": f"DATE#{sk_date}",
        "draw_date": draw_date,
        "lab_provider": provider,
        "biomarkers": {"glucose": {"value_numeric": glucose, "unit": "mg/dL", "flag": "normal"}},
    }


# ──────────────────────────────────────────────────────────────────────────────
# §1 — Registry parity + the dispatcher
# ──────────────────────────────────────────────────────────────────────────────


def test_registry_wires_get_cgm_to_this_module():
    wired = {name: spec for name, spec in TOOLS.items() if getattr(spec["fn"], "__module__", "") == tc.__name__}
    assert wired  # DERIVED — a second tool added here is covered automatically
    for name, spec in wired.items():
        assert callable(spec["fn"]) and spec["schema"]["name"] == name


def test_declared_view_enum_matches_the_dispatchers_valid_views():
    enum = set(TOOLS["get_cgm"]["schema"]["inputSchema"]["properties"]["view"]["enum"])
    accepted = set(tc.tool_get_cgm({"view": "__nope__"})["valid_views"])
    assert enum == accepted


def test_view_argument_is_normalised(ddb):
    ddb({AH_PK: [_glucose_day("2026-08-08", 100)]})
    out = tc.tool_get_cgm({"view": "  DASHBOARD "})
    assert "summary" in out


def test_unknown_view_envelope_names_the_alternatives(ddb):
    out = tc.tool_get_cgm({"view": "trends"})
    assert out["error"] == "Unknown view 'trends'."
    assert "hint" in out


def test_dashboard_honors_the_declared_days_argument(ddb):
    ddb({AH_PK: [_glucose_day("2026-08-08", 100)]})
    assert "days" in TOOLS["get_cgm"]["schema"]["inputSchema"]["properties"]  # the schema really declares it
    out = tc.tool_get_cgm({"view": "dashboard", "days": 7})
    # 7 days ending 2026-08-08 starts 2026-08-02 (or 08-01 inclusive) — anything but a 30-day span.
    assert out["period"]["start"] >= "2026-08-01"


def test_default_window_spans_the_number_of_days_it_is_named_for(ddb):
    ddb({AH_PK: [_glucose_day("2026-08-08", 100)]})
    out = tc.tool_get_cgm({"view": "dashboard"})
    start = datetime.strptime(out["period"]["start"], "%Y-%m-%d")
    end = datetime.strptime(out["period"]["end"], "%Y-%m-%d")
    assert out["period"]["end"] == TODAY
    assert (end - start).days + 1 == 30  # inclusive span


def test_default_window_is_derived_from_the_frozen_clock(ddb):
    """The exact default window, pinned to the frozen clock.

    Was ``2026-07-09`` — ``now - timedelta(days=30)`` against an INCLUSIVE
    ``sk BETWEEN``, i.e. a 31-day span behind a "30 day" name. #2221 subtracts 29;
    this literal is the record of that change.
    """
    ddb({AH_PK: [_glucose_day("2026-08-08", 100)]})
    out = tc.tool_get_cgm({"view": "dashboard"})
    assert out["period"] == {"start": "2026-07-10", "end": "2026-08-08"}  # 30 inclusive days ending today


# ──────────────────────────────────────────────────────────────────────────────
# §2 — dashboard: the arithmetic
# ──────────────────────────────────────────────────────────────────────────────


def test_dashboard_summary_is_hand_derived(ddb):
    ddb(
        {
            AH_PK: [
                _glucose_day("2026-05-01", 100, mn=80, mx=150, sd=20, n=288, tir=96, above140=4),
                _glucose_day("2026-05-02", 110, mn=85, mx=180, sd=30, n=288, tir=88, above140=12),
            ]
        }
    )
    out = tc.tool_get_cgm({"view": "dashboard", "start_date": "2026-05-01", "end_date": "2026-05-02"})
    s = out["summary"]
    assert s["total_days"] == 2 and s["cgm_days"] == 2 and s["manual_days"] == 0
    assert s["avg_glucose"] == 105.0  # (100 + 110) / 2
    assert s["avg_fasting_proxy"] == 82.5  # (80 + 85) / 2
    assert s["avg_variability_sd"] == 25.0  # (20 + 30) / 2
    assert s["avg_time_in_range_pct"] == 92.0  # (96 + 88) / 2
    assert s["avg_time_above_140_pct"] == 8.0  # (4 + 12) / 2
    assert [r["date"] for r in out["daily"]] == ["2026-05-01", "2026-05-02"]


def test_dashboard_thresholds_are_mg_dl_not_mmol_l(ddb):
    """Unit sanity on the flag constants.

    The writer converts mmol/L -> mg/dL at ingest (x18.0182), so everything stored
    is mg/dL. A day at 100 mg/dL (= 5.55 mmol/L) must sit exactly ON the 'optimal'
    bar and a day at 101 must cross it — which is only true if the constant is
    mg/dL. Against an mmol/L bar of 5.5 both days would flag; against a mg/dL bar
    misread as mmol/L neither ever would.
    """
    ddb({AH_PK: [_glucose_day("2026-05-01", 100)]})
    at_bar = tc.tool_get_cgm({"view": "dashboard", "start_date": "2026-05-01", "end_date": "2026-05-01"})
    assert at_bar["summary"]["avg_glucose"] == 100.0
    assert at_bar["clinical_flags"] == []  # `> 100`, so 100 itself is not flagged

    ddb({AH_PK: [_glucose_day("2026-05-01", 101)]})
    over = tc.tool_get_cgm({"view": "dashboard", "start_date": "2026-05-01", "end_date": "2026-05-01"})
    assert "101.0 > 100 mg/dL" in over["clinical_flags"][0]["message"]


def test_dashboard_clinical_flags_fire_on_their_own_thresholds(ddb):
    ddb({AH_PK: [_glucose_day("2026-05-01", 130, mn=105, sd=30, tir=70, above140=25)]})
    out = tc.tool_get_cgm({"view": "dashboard", "start_date": "2026-05-01", "end_date": "2026-05-01"})
    messages = " | ".join(f["message"] for f in out["clinical_flags"])
    assert "Mean glucose 130.0 > 100" in messages
    assert "variability SD 30.0 > 25" in messages
    assert "Time in range 70.0% < 90%" in messages
    assert "Fasting proxy 105.0 > 100" in messages  # min 105 is the fasting proxy
    assert all(f["severity"] == "warning" for f in out["clinical_flags"])


def test_dashboard_sd_flag_matches_the_target_it_publishes(ddb):
    ddb({AH_PK: [_glucose_day("2026-05-01", 95, sd=22, tir=95, above140=2)]})
    out = tc.tool_get_cgm({"view": "dashboard", "start_date": "2026-05-01", "end_date": "2026-05-01"})
    assert "SD <20" in out["note"]  # the target the response states
    assert any("variability" in f["message"] for f in out["clinical_flags"])


def test_dashboard_flags_hypoglycemia(ddb):
    ddb({AH_PK: [_glucose_day("2026-05-01", 92, mn=54, sd=18, tir=88, above140=0, below70=12)]})
    out = tc.tool_get_cgm({"view": "dashboard", "start_date": "2026-05-01", "end_date": "2026-05-01"})
    assert out["daily"][0]["time_below_70_pct"] == 12.0  # measured, and shown per-day
    assert "avg_time_below_70_pct" in out["summary"]
    assert any("below" in f["message"].lower() for f in out["clinical_flags"])


def test_dashboard_unmeasured_day_reports_absence_not_zero(ddb):
    ddb({AH_PK: [_glucose_day("2026-05-01", 100), _partial_glucose_day("2026-05-02", 104)]})
    out = tc.tool_get_cgm({"view": "dashboard", "start_date": "2026-05-01", "end_date": "2026-05-02"})
    partial = out["daily"][1]
    assert partial["avg"] == 104.0  # the one thing that WAS measured
    assert partial["min"] != 0.0, "0 mg/dL is not a glucose value"
    assert partial["time_in_range_pct"] != 0.0, "0% TIR is a clinical emergency, not a missing field"
    assert partial["readings"] != 0 or "readings" not in partial


def test_dashboard_aggregates_exclude_unmeasured_days(ddb):
    ddb({AH_PK: [_glucose_day("2026-05-01", 100, sd=20, tir=96, above140=4), _partial_glucose_day("2026-05-02", 104)]})
    out = tc.tool_get_cgm({"view": "dashboard", "start_date": "2026-05-01", "end_date": "2026-05-02"})
    s = out["summary"]
    # Today's behaviour, for the record: (96 + 0)/2 = 48.0, (20 + 0)/2 = 10.0, (4 + 0)/2 = 2.0.
    # Only ONE day measured time-in-range, and it measured 96%.
    assert s["avg_time_in_range_pct"] == 96.0
    assert s["avg_variability_sd"] == 20.0
    assert s["avg_time_above_140_pct"] == 4.0
    assert not any("Time in range" in f["message"] for f in out["clinical_flags"])


def test_dashboard_fasting_proxy_already_excludes_the_zeros(ddb):
    """The one aggregate that DOES filter absence — pinned as the correct shape the
    three above should match (line 99: `if r["min"] > 0`)."""
    ddb({AH_PK: [_glucose_day("2026-05-01", 100, mn=80), _partial_glucose_day("2026-05-02", 104)]})
    s = tc.tool_get_cgm({"view": "dashboard", "start_date": "2026-05-01", "end_date": "2026-05-02"})["summary"]
    assert s["avg_fasting_proxy"] == 80.0  # the single measured minimum, not (80 + 0)/2


def test_dashboard_fasting_proxy_is_none_when_no_day_measured_a_minimum(ddb):
    ddb({AH_PK: [_partial_glucose_day("2026-05-01", 104)]})
    s = tc.tool_get_cgm({"view": "dashboard", "start_date": "2026-05-01", "end_date": "2026-05-01"})["summary"]
    assert s["avg_fasting_proxy"] is None  # absent, not 0.0


def test_dashboard_mean_is_weighted_by_readings(ddb):
    ddb(
        {
            AH_PK: [
                _glucose_day("2026-05-01", 100, n=288, source="dexcom_stelo"),
                _glucose_day("2026-05-02", 190, n=1, source="manual"),
            ]
        }
    )
    s = tc.tool_get_cgm({"view": "dashboard", "start_date": "2026-05-01", "end_date": "2026-05-02"})["summary"]
    assert s["cgm_days"] == 1 and s["manual_days"] == 1  # the split IS reported
    # Unweighted: (100 + 190)/2 = 145.0.  Weighted by readings: (100*288 + 190*1)/289 = 100.3.
    assert s["avg_glucose"] == pytest.approx(100.3, abs=0.1)


def test_dashboard_counts_cgm_versus_manual_days(ddb):
    ddb({AH_PK: [_glucose_day("2026-05-01", 100), _glucose_day("2026-05-02", 105, source="manual")]})
    s = tc.tool_get_cgm({"view": "dashboard", "start_date": "2026-05-01", "end_date": "2026-05-02"})["summary"]
    assert s["cgm_days"] == 1 and s["manual_days"] == 1
    # `cgm_source` is the writer's own field name (health_auto_export_lambda line 336) and
    # "dexcom_stelo"/"manual" are the only two values _classify_cgm_source emits.
    assert "cgm_source" in WRITER_GLUCOSE_FIELDS


def test_dashboard_unknown_source_label_when_the_writer_field_is_absent(ddb):
    ddb({AH_PK: [_partial_glucose_day("2026-05-01", 104)]})
    out = tc.tool_get_cgm({"view": "dashboard", "start_date": "2026-05-01", "end_date": "2026-05-01"})
    assert out["daily"][0]["source"] == "unknown"  # honest label, not a fabricated device


def test_every_field_the_dashboard_reads_has_a_writer(ddb):
    """Reader/writer parity, derived from the row builder that mirrors the writer.

    Six independent instances of a reader naming a field no writer stores were
    found in tranche 2, each leaving a feature permanently dark. This pins the
    glucose set: every attribute the dashboard reads is one
    ``health_auto_export_lambda.process_blood_glucose`` actually writes.
    """
    read_fields = {
        "blood_glucose_avg",
        "blood_glucose_min",
        "blood_glucose_max",
        "blood_glucose_std_dev",
        "blood_glucose_readings_count",
        "blood_glucose_time_in_range_pct",
        "blood_glucose_time_above_140_pct",
        "blood_glucose_time_below_70_pct",
        "cgm_source",
    }
    assert read_fields <= WRITER_GLUCOSE_FIELDS


def test_dashboard_trend_halves_are_hand_derived(ddb):
    ddb({AH_PK: [_glucose_day(f"2026-05-0{i + 1}", v) for i, v in enumerate([100, 102, 104, 110, 112, 114])]})
    out = tc.tool_get_cgm({"view": "dashboard", "start_date": "2026-05-01", "end_date": "2026-05-06"})
    tr = out["trend"]
    # mid = 6 // 2 = 3.  first = (100+102+104)/3 = 102.0 ; second = (110+112+114)/3 = 112.0
    # pct = (112 - 102) / 102 * 100 = 9.8039... -> 9.8 ; > 2 -> "worsening"
    assert tr["first_half"] == 102.0 and tr["second_half"] == 112.0
    assert tr["pct_change"] == 9.8
    assert tr["direction"] == "worsening"


def test_dashboard_trend_direction_is_improving_when_glucose_falls(ddb):
    ddb({AH_PK: [_glucose_day(f"2026-05-0{i + 1}", v) for i, v in enumerate([114, 112, 110, 104, 102, 100])]})
    tr = tc.tool_get_cgm({"view": "dashboard", "start_date": "2026-05-01", "end_date": "2026-05-06"})["trend"]
    # pct = (102 - 112) / 112 * 100 = -8.9285... -> -8.9 ; < -2 -> "improving"
    assert tr["pct_change"] == -8.9 and tr["direction"] == "improving"


def test_dashboard_trend_is_absent_below_six_days(ddb):
    """Five days is not a trend — ADR-105. Pinned as CORRECT behaviour."""
    ddb({AH_PK: [_glucose_day(f"2026-05-0{i + 1}", 100 + i) for i in range(5)]})
    out = tc.tool_get_cgm({"view": "dashboard", "start_date": "2026-05-01", "end_date": "2026-05-05"})
    assert out["trend"] is None  # absent, not a fabricated "stable"


def test_dashboard_trend_halves_are_positional_not_calendar(ddb):
    """Documented, not xfail'd: the split is by POSITION in the list of days that
    have data, so six days scattered across a month split into two 3-day clusters
    24 days apart and the result is still labelled a percentage change over the
    period. The `period` and `total_days` fields are what disclose the sparsity.
    """
    dates = ["2026-05-01", "2026-05-02", "2026-05-03", "2026-05-27", "2026-05-28", "2026-05-29"]
    ddb({AH_PK: [_glucose_day(d, v) for d, v in zip(dates, [100, 102, 104, 110, 112, 114])]})
    out = tc.tool_get_cgm({"view": "dashboard", "start_date": "2026-05-01", "end_date": "2026-05-31"})
    assert out["trend"]["pct_change"] == 9.8  # identical to six consecutive days
    assert out["summary"]["total_days"] == 6  # the only signal that 25 days are missing
    assert out["period"] == {"start": "2026-05-01", "end": "2026-05-31"}


def test_dashboard_ignores_days_without_a_glucose_mean(ddb):
    """A step-only Apple Health day is not a zero-glucose day."""
    ddb({AH_PK: [{"pk": AH_PK, "sk": "DATE#2026-05-01", "date": "2026-05-01", "steps": 8000}, _glucose_day("2026-05-02", 100)]})
    out = tc.tool_get_cgm({"view": "dashboard", "start_date": "2026-05-01", "end_date": "2026-05-02"})
    assert out["summary"]["total_days"] == 1
    assert [r["date"] for r in out["daily"]] == ["2026-05-02"]


def test_dashboard_decimal_values_survive_json_serialisation(ddb):
    """DynamoDB hands numbers back as Decimal; a Decimal reaching json.dumps raises.

    ``mcp.core.query_source`` runs ``decimal_to_float`` — pinned here because the
    MCP transport serialises this dict directly.
    """
    ddb({AH_PK: [_glucose_day("2026-05-01", Decimal("101.4"), mn=Decimal("79.2"), sd=Decimal("21.5"), n=Decimal("288"))]})
    out = tc.tool_get_cgm({"view": "dashboard", "start_date": "2026-05-01", "end_date": "2026-05-01"})
    assert out["summary"]["avg_glucose"] == 101.4
    json.dumps(out)  # must not raise


def test_dashboard_survives_a_non_numeric_stored_value(ddb):
    ddb({AH_PK: [_glucose_day("2026-05-01", 100), _glucose_day("2026-05-02", 105, n="n/a")]})
    out = tc.tool_get_cgm({"view": "dashboard", "start_date": "2026-05-01", "end_date": "2026-05-02"})
    assert out["summary"]["total_days"] >= 1


# ──────────────────────────────────────────────────────────────────────────────
# §3 — ADR-058 phase filtering + envelope parity
# ──────────────────────────────────────────────────────────────────────────────


def test_partition_classes_are_what_the_taxonomy_says():
    """DERIVED from experiment.phase_taxonomy — the registry the tagger and wipe read."""
    assert phase_taxonomy.classify(AH_PK, "DATE#2026-05-01") == phase_taxonomy.RAW_TIMESERIES
    assert phase_taxonomy.classify(LABS_PK, "DATE#2026-05-01") == phase_taxonomy.CROSS_PHASE


def test_dashboard_apple_health_read_carries_the_phase_filter(ddb):
    """apple_health is RAW_TIMESERIES: rows are kept forever and never tombstoned,
    so the default filter (`phase = experiment OR attribute_not_exists(phase)`) is
    transparent today. Pinned because if the tagger ever starts stamping raw
    partitions, this is the exact query that would start hiding real sensor days.
    """
    t = ddb({AH_PK: [_glucose_day("2026-05-01", 100)]})
    tc.tool_get_cgm({"view": "dashboard", "start_date": "2026-05-01", "end_date": "2026-05-01"})
    call = next(c for c in t.query_calls if _pk_of(c) == AH_PK)
    assert "attribute_not_exists(#phase)" in call["FilterExpression"]
    assert call["ExpressionAttributeValues"][":phase_experiment"] == "experiment"


def test_fasting_lab_read_is_not_phase_filtered(ddb, s3):
    """labs is CROSS_PHASE — a filter here would truncate a clinical archive at
    every cycle reset."""
    s3({_cgm_key("2026-05-01"): NIGHT_2026_05_01})
    t = ddb({LABS_PK: [_lab_draw("2026-05-01", "2026-05-01", 95)]})
    tc.tool_get_cgm({"view": "fasting"})
    call = next(c for c in t.query_calls if _pk_of(c) == LABS_PK)
    assert "FilterExpression" not in call


def test_disclaimer_rides_on_every_successful_view(ddb, s3):
    ddb({AH_PK: [_glucose_day("2026-05-01", 100)]})
    out = tc.tool_get_cgm({"view": "dashboard", "start_date": "2026-05-01", "end_date": "2026-05-01"})
    assert out["_disclaimer"] == tc._CGM_DISCLAIMER
    assert "Not medical advice" in out["_disclaimer"]


def test_disclaimer_rides_on_the_error_envelope_too(ddb):
    ddb({AH_PK: []})
    out = tc.tool_get_cgm({"view": "dashboard", "start_date": "2026-05-01", "end_date": "2026-05-01"})
    assert out["error"].startswith("No Apple Health data")
    assert "_disclaimer" in out


def test_dashboard_distinguishes_no_apple_health_from_no_glucose(ddb):
    """Two different empty states, two different messages — pinned as correct."""
    ddb({AH_PK: []})
    assert tc.tool_get_cgm({"view": "dashboard", "start_date": "2026-05-01", "end_date": "2026-05-01"})["error"] == (
        "No Apple Health data in range."
    )
    ddb({AH_PK: [{"pk": AH_PK, "sk": "DATE#2026-05-01", "date": "2026-05-01", "steps": 8000}]})
    assert "Requires Dexcom Stelo" in tc.tool_get_cgm({"view": "dashboard", "start_date": "2026-05-01", "end_date": "2026-05-01"})["error"]


# ──────────────────────────────────────────────────────────────────────────────
# §4 — _load_cgm_readings (S3 key construction, parsing, SEC-3 guard)
# ──────────────────────────────────────────────────────────────────────────────


def test_reading_loader_builds_the_key_the_writer_writes(s3):
    c = s3({_cgm_key("2026-05-01"): [_reading(2, 30, 85)]})
    out = tc._load_cgm_readings("2026-05-01")
    assert c.fetched_keys == ["raw/matthew/cgm_readings/2026/05/01.json"]
    # hour decimal = 2 + 30/60 + 0/3600 = 2.5
    assert out == [(2.5, 85.0)]


def test_reading_loader_converts_hms_to_an_hour_decimal(s3):
    s3({_cgm_key("2026-05-01"): [{"time": "2026-05-01 07:30:36 -0700", "value": 111}]})
    # 7 + 30/60 + 36/3600 = 7 + 0.5 + 0.01 = 7.51
    assert tc._load_cgm_readings("2026-05-01") == [(7.51, 111.0)]


def test_reading_loader_sorts_by_time(s3):
    s3({_cgm_key("2026-05-01"): [_reading(5, 0, 92), _reading(1, 0, 95), _reading(3, 0, 85)]})
    assert [h for h, _ in tc._load_cgm_readings("2026-05-01")] == [1.0, 3.0, 5.0]


@pytest.mark.parametrize(
    "bad",
    ["../../config/board_of_directors", "2026-5-1", "2026-13-01", "2026-02-30", "", "2026-05-01T00:00:00", None, 20260501],
)
def test_reading_loader_rejects_anything_that_is_not_a_calendar_date(s3, bad):
    """SEC-3: date_str reaches an S3 key, so the regex + strptime gate is the only
    thing between a malformed argument and reading an unintended object."""
    c = s3({_cgm_key("2026-05-01"): [_reading(2, 30, 85)]})
    assert tc._load_cgm_readings(bad) == []
    assert c.fetched_keys == []  # no key was ever constructed


def test_reading_loader_skips_unusable_readings_without_losing_the_day(s3):
    s3(
        {
            _cgm_key("2026-05-01"): [
                {"time": "2026-05-01 01:00:00 -0700", "value": None},  # no value
                {"time": "", "value": 90},  # no timestamp
                {"time": "2026-05-01T02:00:00", "value": 91},  # ISO 'T' — not the writer's format
                {"time": "2026-05-01 03:00:00 -0700", "value": "88.5"},  # numeric string is fine
            ]
        }
    )
    # Only the last survives. The 'T' row is dropped because parts[1] does not exist —
    # the loader is tightly coupled to health_auto_export_lambda's "%Y-%m-%d %H:%M:%S %z"
    # writer format, and any future writer change would silently empty the fasting view
    # rather than error.
    assert tc._load_cgm_readings("2026-05-01") == [(3.0, 88.5)]


def test_reading_loader_returns_empty_for_a_day_with_no_object(s3):
    s3({})
    assert tc._load_cgm_readings("2026-05-01") == []


def test_reading_loader_returns_empty_when_s3_errors(s3, monkeypatch):
    c = s3({})

    def _boom(Bucket, Key):  # noqa: N803
        raise RuntimeError("access denied")

    monkeypatch.setattr(c, "get_object", _boom)
    assert tc._load_cgm_readings("2026-05-01") == []  # fail-soft, never raises out of the tool


def test_reading_loader_does_not_deduplicate_repeated_timestamps(s3):
    """Documented, not xfail'd.

    ``save_cgm_readings_to_s3`` dedups new readings against what is ALREADY in the
    S3 object, but not within a single delivered batch — so a webhook replay inside
    one payload can persist two entries with the same timestamp. The reader does no
    dedup of its own, so such a reading is counted twice in the overnight mean and
    twice toward the ``min_overnight_readings`` coverage gate.
    """
    dup = _reading(2, 0, 60)
    s3({_cgm_key("2026-05-01"): [_reading(1, 0, 100), dup, dict(dup)]})
    loaded = tc._load_cgm_readings("2026-05-01")
    assert len(loaded) == 3
    assert [v for _, v in loaded] == [100.0, 60.0, 60.0]


# ──────────────────────────────────────────────────────────────────────────────
# §5 — view = fasting (overnight nadir validation)
# ──────────────────────────────────────────────────────────────────────────────


def test_fasting_no_cgm_data_is_an_error_envelope(ddb, s3):
    s3({})
    ddb({})
    out = tc.tool_get_cgm({"view": "fasting"})
    assert out["error"] == "No CGM data found in S3."


def test_fasting_nadirs_are_hand_derived(ddb, s3):
    s3({_cgm_key("2026-05-01"): NIGHT_2026_05_01})
    ddb({LABS_PK: []})
    out = tc.tool_get_cgm({"view": "fasting"})
    on = out["distributions"]["overnight_nadir_00_06"]
    # Overnight window [0, 6): 100, 95, 90, 85 (02:30), 85 (03:00), 88, 92 -> 7 readings.
    #   nadir = 85 ; mean of the window = 635 / 7 = 90.714... (reported as overnight_avg per day)
    assert on["n"] == 1 and on["mean"] == 85.0
    # Deep window [2, 5): 90, 85, 85, 88 -> 4 readings (the >= 4 gate is met)
    #   deep nadir = 85 ; deep avg = 348 / 4 = 87.0
    deep = out["distributions"]["deep_nadir_02_05"]
    assert deep["n"] == 1 and deep["mean"] == 85.0
    assert out["cgm_coverage"] == {
        "first_date": "2026-05-01",
        "last_date": "2026-05-01",
        "total_cgm_days": 1,
        "days_with_valid_overnight": 1,
    }
    assert out["methodology"]["overnight_window"] == "00:00 - 06:00"
    assert out["methodology"]["deep_nadir_window"] == "02:00 - 05:00"
    assert out["methodology"]["min_readings_required"] == 6


def test_fasting_thin_night_is_excluded_from_the_distribution(ddb, s3):
    """Below `min_overnight_readings` the night contributes nothing — absence, not a
    one-reading "nadir". Pinned as CORRECT behaviour."""
    s3({_cgm_key("2026-05-01"): [_reading(3, 0, 85), _reading(3, 5, 86)]})
    ddb({LABS_PK: []})
    out = tc.tool_get_cgm({"view": "fasting"})
    assert out["error"] == "Insufficient overnight CGM readings across all days."


def test_fasting_deep_nadir_absent_when_the_window_is_thin(ddb, s3):
    s3(
        {
            _cgm_key("2026-05-01"): [
                _reading(0, 0, 100),
                _reading(0, 30, 99),
                _reading(1, 0, 95),
                _reading(1, 30, 94),
                _reading(2, 0, 90),
                _reading(5, 30, 92),
            ]
        }
    )
    ddb({LABS_PK: []})
    out = tc.tool_get_cgm({"view": "fasting"})
    # Only ONE reading falls in [2, 5) -> below the >= 4 gate -> no deep nadir at all.
    assert out["distributions"]["deep_nadir_02_05"] is None


def test_fasting_direct_same_day_validation_is_hand_derived(ddb, s3):
    s3({_cgm_key("2026-05-01"): NIGHT_2026_05_01})
    ddb({LABS_PK: [_lab_draw("2026-05-01", "2026-05-01", 95)]})
    out = tc.tool_get_cgm({"view": "fasting"})
    dv = out["direct_validations"][0]
    assert dv["lab_fasting_glucose"] == 95.0
    assert dv["cgm_overnight_nadir"] == 85.0
    assert dv["lab_minus_cgm_overnight"] == 10.0  # 95 - 85
    assert dv["lab_minus_cgm_deep"] == 10.0  # 95 - 85
    assert dv["cgm_daily_min"] == 85.0  # the 12:00 postprandial 150 is not a minimum
    # |10.0| <= 10 -> the "good agreement" band, per Stelo MARD ~9%.
    assert out["bias_analysis"]["confidence"] == "moderate"
    assert "Good agreement" in out["bias_analysis"]["interpretation"]


def test_fasting_direct_validations_keeps_a_stable_type_when_empty(ddb, s3):
    s3({_cgm_key("2026-05-01"): NIGHT_2026_05_01})
    ddb({LABS_PK: [_lab_draw("2026-06-01", "2026-06-01", 95)]})  # no same-day overlap
    out = tc.tool_get_cgm({"view": "fasting"})
    assert isinstance(out["direct_validations"], list) and out["direct_validations"] == []


def test_fasting_single_night_does_not_produce_a_distribution_or_a_verdict(ddb, s3):
    s3({_cgm_key("2026-05-01"): NIGHT_2026_05_01})
    ddb({LABS_PK: []})
    out = tc.tool_get_cgm({"view": "fasting"})
    on = out["distributions"]["overnight_nadir_00_06"]
    assert on["n"] == 1
    assert on["std_dev"] is None, "an SD over one observation is undefined, not 0"
    assert not any("strong metabolic consistency" in i for i in out["insights"])
    assert on.get("p90") is None


def test_fasting_two_nights_compute_a_real_std_dev(ddb, s3):
    second = [
        _reading(h, m, v, day="2026-05-02") for (h, m, v) in [(0, 0, 100), (1, 0, 98), (2, 0, 96), (3, 0, 95), (4, 0, 97), (5, 0, 99)]
    ]
    s3({_cgm_key("2026-05-01"): NIGHT_2026_05_01, _cgm_key("2026-05-02"): second})
    ddb({LABS_PK: []})
    out = tc.tool_get_cgm({"view": "fasting"})
    on = out["distributions"]["overnight_nadir_00_06"]
    # Nadirs 85 and 95 -> mean 90.0 ; sample SD = sqrt(((85-90)^2 + (95-90)^2)/(2-1))
    #                                            = sqrt(50) = 7.0710... -> round(.,1) = 7.1
    assert on["n"] == 2 and on["mean"] == 90.0 and on["std_dev"] == 7.1
    assert on["min"] == 85.0 and on["max"] == 95.0


def test_fasting_z_score_is_hand_derived_against_the_nadir_distribution(ddb, s3):
    second = [
        _reading(h, m, v, day="2026-05-02") for (h, m, v) in [(0, 0, 100), (1, 0, 98), (2, 0, 96), (3, 0, 95), (4, 0, 97), (5, 0, 99)]
    ]
    s3({_cgm_key("2026-05-01"): NIGHT_2026_05_01, _cgm_key("2026-05-02"): second})
    ddb({LABS_PK: [_lab_draw("2026-06-01", "2026-06-01", 97)]})
    sv = tc.tool_get_cgm({"view": "fasting"})["statistical_validations"][0]
    # z = (97 - 90.0) / 7.1 = 0.98591... -> round(.,2) = 0.99 ; |z| <= 1 and <= 2
    assert sv["vs_overnight_nadir"]["z_score"] == 0.99
    assert sv["vs_overnight_nadir"]["within_1sd"] is True
    assert sv["vs_overnight_nadir"]["within_2sd"] is True
    # percentile: nadirs <= 97 are 85 and 95 -> 2/2 -> 100.0%
    assert sv["vs_overnight_nadir"]["percentile_of_nadir_dist"] == 100.0


def test_fasting_bias_analysis_publishes_its_n(ddb, s3):
    s3({_cgm_key("2026-05-01"): NIGHT_2026_05_01})
    ddb({LABS_PK: [_lab_draw("2026-06-01", "2026-06-01", 88)]})
    bias = tc.tool_get_cgm({"view": "fasting"})["bias_analysis"]
    # 88 - 85 = 3.0 -> |3| <= 5 -> "Excellent agreement", confidence "high", off n=1 vs n=1.
    assert bias["confidence"] == "high"
    assert bias["n_lab_draws"] == 1 and bias["n_nights"] == 1


def test_fasting_lab_trend_uses_draw_date_order_not_row_order(ddb, s3):
    s3({_cgm_key("2026-05-01"): NIGHT_2026_05_01})
    ddb(
        {
            LABS_PK: [
                # sk order (what DynamoDB returns) is the IMPORT order; draw_date is the truth.
                _lab_draw("2026-06-10", "2026-06-01", 101),
                _lab_draw("2026-06-11", "2026-02-01", 88),  # backfilled older panel
                _lab_draw("2026-06-12", "2026-04-01", 92),
            ]
        }
    )
    insights = tc.tool_get_cgm({"view": "fasting"})["insights"]
    assert any("trending up" in i for i in insights), insights
    assert not any("positive trajectory" in i for i in insights)


def test_fasting_discovers_cgm_days_beyond_the_hardcoded_year_list(ddb, s3):
    """CORRECTION (#2221): as written under xfail this test requested the ``ddb``
    fixture but never INSTALLED it, so the run reached the real ``table.query`` and
    died on a botocore ClientError. The marker went green on an unpatched AWS call,
    not on the year-list bug it names. The double is installed now, so the only thing
    that can fail here is the discovery range.
    """
    ddb({LABS_PK: []})
    c = s3(
        {
            _cgm_key("2026-05-01"): NIGHT_2026_05_01,
            _cgm_key("2027-01-02"): [
                _reading(h, 0, v, day="2027-01-02") for h, v in [(0, 100), (1, 98), (2, 96), (3, 94), (4, 95), (5, 97)]
            ],
        }
    )
    out = tc.tool_get_cgm({"view": "fasting"})
    assert "2027/" in " ".join(c.listed_prefixes)
    assert out["cgm_coverage"]["total_cgm_days"] == 2
    assert out["cgm_coverage"]["last_date"] == "2027-01-02"


def test_fasting_lab_read_is_paginated(ddb, s3):
    s3({_cgm_key("2026-05-01"): NIGHT_2026_05_01})
    ddb(
        {LABS_PK: [_lab_draw("2026-02-01", "2026-02-01", 88), _lab_draw("2026-04-01", "2026-04-01", 92)]},
        paginate=True,
    )
    out = tc.tool_get_cgm({"view": "fasting"})
    assert len(out["lab_draws"]) == 2


def test_fasting_rejects_a_malformed_window_argument(ddb, s3):
    s3({_cgm_key("2026-05-01"): NIGHT_2026_05_01})
    ddb({LABS_PK: []})
    schema_props = set(TOOLS["get_cgm"]["schema"]["inputSchema"]["properties"])
    assert "nadir_start_hour" not in schema_props  # undeclared, yet load-bearing
    out = tc.tool_get_cgm({"view": "fasting", "nadir_start_hour": "midnight"})
    assert isinstance(out, dict) and "error" in out


def test_fasting_custom_window_arguments_are_honoured(ddb, s3):
    """The undeclared arguments DO work when numeric — pinned so the xfail above is
    unambiguously about validation, not about the feature."""
    s3({_cgm_key("2026-05-01"): NIGHT_2026_05_01})
    ddb({LABS_PK: []})
    out = tc.tool_get_cgm({"view": "fasting", "nadir_start_hour": 0, "nadir_end_hour": 2, "min_overnight_readings": 2})
    # Window [0, 2) holds 100 and 95 -> nadir 95, and the methodology block says so.
    assert out["distributions"]["overnight_nadir_00_06"]["mean"] == 95.0
    assert out["methodology"]["overnight_window"] == "00:00 - 02:00"
    assert out["methodology"]["min_readings_required"] == 2


def test_fasting_reports_the_daily_minimum_against_the_overnight_nadir(ddb, s3):
    """The insight that decides whether the platform's cheap 'daily min' fasting
    proxy is good enough — hand-derived on a day whose true minimum is at noon."""
    day = [
        _reading(0, 0, 100),
        _reading(1, 0, 98),
        _reading(2, 0, 96),
        _reading(3, 0, 95),
        _reading(4, 0, 97),
        _reading(5, 0, 99),
        _reading(12, 0, 70),  # a post-exercise low well outside the overnight window
    ]
    s3({_cgm_key("2026-05-01"): day})
    ddb({LABS_PK: []})
    out = tc.tool_get_cgm({"view": "fasting"})
    # overnight nadir 95, daily minimum 70 -> difference -25.0, i.e. the daily-min proxy
    # UNDERSTATES true fasting glucose by 25 mg/dL on this day.
    assert out["distributions"]["daily_minimum"]["mean"] == 70.0
    assert out["distributions"]["overnight_nadir_00_06"]["mean"] == 95.0
    assert any("current proxy slightly underestimates true fasting" in i for i in out["insights"])


def test_fasting_notes_the_absence_of_a_same_day_pair(ddb, s3):
    s3({_cgm_key("2026-05-01"): NIGHT_2026_05_01})
    ddb({LABS_PK: [_lab_draw("2026-06-01", "2026-06-01", 95)]})
    out = tc.tool_get_cgm({"view": "fasting"})
    assert any("No same-day CGM + lab data available" in i for i in out["insights"])


def test_fasting_survives_a_year_prefix_it_cannot_list(ddb, s3):
    """One unreadable year must not empty the whole view (line 190-191)."""
    c = s3({_cgm_key("2026-05-01"): NIGHT_2026_05_01}, list_fails_for={"2025/"})
    ddb({LABS_PK: []})
    out = tc.tool_get_cgm({"view": "fasting"})
    assert "2025/" in " ".join(c.listed_prefixes)  # it was attempted
    assert out["cgm_coverage"]["total_cgm_days"] == 1


def test_fasting_skips_a_listed_day_whose_object_will_not_load(ddb, s3):
    """A key present in the listing but unreadable contributes nothing — it does not
    become a zero-glucose night."""
    s3(
        {_cgm_key("2026-05-01"): NIGHT_2026_05_01, _cgm_key("2026-05-02"): []},
        unreadable={_cgm_key("2026-05-02")},
    )
    ddb({LABS_PK: []})
    out = tc.tool_get_cgm({"view": "fasting"})
    # Discovery counts 2 objects; only 1 yields a usable overnight window, and the
    # response says so rather than averaging a phantom night in.
    assert out["cgm_coverage"]["total_cgm_days"] == 2
    assert out["cgm_coverage"]["days_with_valid_overnight"] == 1
    assert out["distributions"]["overnight_nadir_00_06"]["n"] == 1


def _night(day, values):
    """(hour, value) pairs -> writer-format readings for one day."""
    return [_reading(h, m, v, day=day) for (h, m, v) in values]


def test_fasting_dawn_phenomenon_insight_and_deep_z_score(ddb, s3):
    """Two nights whose deep (02-05) and broad (00-06) nadirs genuinely diverge."""
    night2 = _night("2026-05-02", [(0, 0, 80), (1, 0, 95), (2, 0, 100), (2, 30, 99), (3, 0, 98), (4, 0, 97), (5, 0, 96)])
    s3({_cgm_key("2026-05-01"): NIGHT_2026_05_01, _cgm_key("2026-05-02"): night2})
    ddb({LABS_PK: [_lab_draw("2026-06-01", "2026-06-01", 95)]})
    out = tc.tool_get_cgm({"view": "fasting"})
    # overnight nadirs 85, 80 -> mean 82.5 ; deep nadirs 85, 97 -> mean 91.0
    #   divergence = 91.0 - 82.5 = +8.5 mg/dL -> the dawn-phenomenon insight fires
    assert out["distributions"]["overnight_nadir_00_06"]["mean"] == 82.5
    assert out["distributions"]["deep_nadir_02_05"]["mean"] == 91.0
    assert any("Dawn phenomenon" in i for i in out["insights"])
    # deep SD = sqrt(((85-91)^2 + (97-91)^2)/(2-1)) = sqrt(72) = 8.485 -> 8.5
    #   z_deep = (95 - 91.0) / 8.5 = 0.4705... -> 0.47
    sv = out["statistical_validations"][0]
    assert sv["vs_deep_nadir"]["z_score"] == 0.47
    assert sv["vs_deep_nadir"]["within_1sd"] is True


def test_fasting_high_overnight_variability_insight(ddb, s3):
    night2 = _night("2026-05-02", [(0, 0, 120), (1, 0, 115), (2, 0, 110), (2, 30, 112), (3, 0, 111), (4, 0, 108), (5, 0, 105)])
    s3({_cgm_key("2026-05-01"): NIGHT_2026_05_01, _cgm_key("2026-05-02"): night2})
    ddb({LABS_PK: []})
    out = tc.tool_get_cgm({"view": "fasting"})
    # nadirs 85, 105 -> mean 95.0 ; SD = sqrt(((85-95)^2 + (105-95)^2)/1) = sqrt(200) = 14.14 -> 14.1
    assert out["distributions"]["overnight_nadir_00_06"]["std_dev"] == 14.1
    assert any("High overnight nadir variability (SD 14.1" in i for i in out["insights"])


@pytest.mark.parametrize(
    "lab_glucose,expected_confidence,expected_phrase",
    [
        (88, "high", "Excellent agreement"),  # 88 - 85 =  3.0  -> |d| <=  5
        (95, "moderate", "Good agreement"),  # 95 - 85 = 10.0  -> |d| <= 10
        (100, "low", "Moderate discrepancy"),  # 100 - 85 = 15.0 -> |d| <= 20
        (110, "very_low", "Significant discrepancy"),  # 110 - 85 = 25.0 -> |d| >  20
    ],
)
def test_fasting_bias_bands_are_hand_derived(ddb, s3, lab_glucose, expected_confidence, expected_phrase):
    """The overnight nadir mean is 85.0 (one night), so `lab - 85` selects the band."""
    s3({_cgm_key("2026-05-01"): NIGHT_2026_05_01})
    ddb({LABS_PK: [_lab_draw("2026-06-01", "2026-06-01", lab_glucose)]})
    bias = tc.tool_get_cgm({"view": "fasting"})["bias_analysis"]
    assert bias["cgm_overnight_nadir_mean"] == 85.0
    assert bias["lab_minus_cgm_overnight"] == float(lab_glucose) - 85.0
    assert bias["confidence"] == expected_confidence
    assert expected_phrase in bias["interpretation"]


def test_fasting_board_commentary_is_static_text_not_a_computed_claim(ddb, s3):
    """The three board voices are fixed strings — pinned so a future edit cannot
    quietly turn them into generated narrative without a grounded-generation gate
    (ADR-104)."""
    s3({_cgm_key("2026-05-01"): NIGHT_2026_05_01})
    ddb({LABS_PK: []})
    out = tc.tool_get_cgm({"view": "fasting"})
    assert set(out["board_of_directors"]) == {"Attia", "Patrick", "Huberman"}
    assert "<90 mg/dL is optimal" in out["board_of_directors"]["Attia"]
    for text in out["board_of_directors"].values():
        assert "85" not in text and "95" not in text  # no fixture value leaked into the commentary
