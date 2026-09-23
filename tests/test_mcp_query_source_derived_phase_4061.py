"""tests/test_mcp_query_source_derived_phase_4061.py — the MCP read path derives its phase decision.

THE BUG (#4061)
  `mcp/core.py::query_source` defaulted `include_pilot=False` (the ADR-058 filter), and 46
  MCP call sites took that default. The restart tagger stamps every pre-genesis row
  `phase=pilot` (ADR-077), so every RAW_TIMESERIES / CROSS_PHASE partition an MCP tool read
  that way was truncated at the current genesis. Measured 2026-09-23: `SOURCE#strava`
  holds 230 rows for 2024-09-15..2025-05-10, every one `phase=pilot`, and every chat tool
  answered as though none existed. #4030/#4031/#4032 migrated three tools one instance at a
  time; the set was never guarded.

THE FIX
  The decision moved to the chokepoint: `include_pilot=None` (the new default on
  `query_source` / `parallel_query_sources` / `query_source_range`) asks
  `phase_filter.source_reads_cross_phase(source)`. An explicit bool still wins.

WHAT THIS FILE HOLDS
  1. The SET: every `query_source*` call in `mcp/` is enumerated by AST, so a call site added
     tomorrow is covered without anyone listing it. Each one either takes the derived default
     or carries an explicit `include_pilot=` that is RULED below with its reason; a literal
     `include_pilot=False` is ruled nowhere. Every literal source a call site names must be
     classified by the taxonomy, so the derived answer is a ruling and not a fallback.
  2. The public tool paths the issue names — `search_activities`, `find_days`,
     `get_training`, the benchmark and the correlation (zone-2) reads — return a planted
     `phase=pilot` Strava row, through the REAL `query_source` -> `_apply_phase_filter`
     wire (only `mcp.core.table` is faked, and it applies the exact FilterExpression the
     core mints with DynamoDB's own semantics).
  3. Regression control: an EXPERIMENT_SCOPED partition keeps the filter — a planted pilot
     `computed_metrics` row stays hidden from `get_acwr_status`, and every scoped source
     stays filtered at the helper.
  4. Mutation control: restore the pre-#4061 default and every public-path assertion reds.
  5. Box 4: an activity with no measured distance (a WHOOP-synced trainer walk) is no
     longer dropped without a word by `search_activities` / `find_days`.
"""

from __future__ import annotations

import ast
import inspect
import os
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from experiment import phase_taxonomy  # noqa: E402

import mcp.core as core  # noqa: E402
from mcp.registry import TOOLS  # noqa: E402

MCP_DIR = REPO / "mcp"

# ── 1. the SET ────────────────────────────────────────────────────────────────

READER_FNS = frozenset(
    {
        "query_source",
        "parallel_query_sources",
        "query_source_range",
        "query_source_cross_phase",
        "parallel_query_sources_cross_phase",
    }
)

# (module, enclosing function) -> why an explicit include_pilot is right there. Anything
# not listed must take the derived default. `False` appears in no ruling.
RULED_EXPLICIT = {
    # the tool exposes `include_pilot` as a caller argument (default True) — the user's switch wins
    ("tools_hevy.py", "tool_get_workouts"): "user-facing include_pilot argument",
    # uid lookup must find a workout from any cycle; equal to the derived answer for hevy
    ("tools_hevy.py", "tool_get_workout_detail"): "uid lookup across every cycle",
    # withings is RAW_TIMESERIES, so True equals the derived answer; predates #4061
    ("tools_benchmark.py", "_weight_on_or_after"): "cross-phase weight read, equal to the derived answer",
    ("tools_benchmark.py", "_current_weight_and_rate"): "cross-phase weight read, equal to the derived answer",
    # the pass-through alias itself
    ("core.py", "query_source_range"): "alias forwarding its own parameter",
    ("core.py", "query_source_cross_phase"): "alias pinning the derived default",
    ("core.py", "parallel_query_sources_cross_phase"): "alias pinning the derived default",
}


def _call_sites():
    sites = []
    for path in sorted(MCP_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
            if name not in READER_FNS:
                continue
            enclosing, cur = None, node
            while cur in parents:
                cur = parents[cur]
                if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    enclosing = cur.name
                    break
            kw = next((k for k in node.keywords if k.arg == "include_pilot"), None)
            # positional include_pilot is the 5th arg of query_source / parallel_query_sources
            positional = len(node.args) >= (4 if name == "query_source_range" else 5)
            src = node.args[0] if node.args else None
            sites.append(
                {
                    "file": path.name,
                    "line": node.lineno,
                    "fn": enclosing,
                    "reader": name,
                    "include_pilot": kw,
                    "positional_pilot": positional,
                    "literal_source": src.value if isinstance(src, ast.Constant) and isinstance(src.value, str) else None,
                    "literal_list": (
                        [e.value for e in src.elts if isinstance(e, ast.Constant)] if isinstance(src, (ast.List, ast.Tuple)) else None
                    ),
                }
            )
    return sites


SITES = _call_sites()


def test_the_set_is_not_vacuous():
    """The issue measured 46 default-taking sites; the enumeration must see at least that many."""
    derived = [s for s in SITES if s["include_pilot"] is None and not s["positional_pilot"]]
    assert len(derived) >= 46, f"only {len(derived)} derived call sites found — the AST walk is not seeing mcp/"


def test_every_call_site_takes_the_derived_default_or_is_ruled():
    unruled = [
        f"{s['file']}:{s['line']} {s['fn']}() {s['reader']}"
        for s in SITES
        if (s["include_pilot"] is not None or s["positional_pilot"]) and (s["file"], s["fn"]) not in RULED_EXPLICIT
    ]
    assert not unruled, (
        "explicit include_pilot at an unruled MCP read site — drop it (the decision is derived from the "
        "taxonomy, #4061) or rule it in RULED_EXPLICIT with the reason:\n  " + "\n  ".join(unruled)
    )


def test_no_call_site_hard_codes_the_phase_filter_on():
    hard = [
        f"{s['file']}:{s['line']}"
        for s in SITES
        if s["include_pilot"] is not None and isinstance(s["include_pilot"].value, ast.Constant) and s["include_pilot"].value.value is False
    ]
    assert not hard, f"include_pilot=False hard-codes the ADR-058 filter regardless of the source's class: {hard}"


def test_every_ruling_still_names_a_live_call_site():
    live = {(s["file"], s["fn"]) for s in SITES}
    dead = sorted(k for k in RULED_EXPLICIT if k not in live)
    assert not dead, f"RULED_EXPLICIT entries with no call site left: {dead}"


def test_every_literal_source_is_classified_by_the_taxonomy():
    """The derived answer for an unknown source is the conservative 'keep the filter' — a
    fallback, not a ruling. Every source a call site names literally must be classified."""
    names = set()
    for s in SITES:
        if s["literal_source"]:
            names.add(s["literal_source"])
        for n in s["literal_list"] or []:
            names.add(n)
    assert names, "no literal sources found — the enumeration is broken"
    unclassified = []
    for n in sorted(names):
        try:
            phase_taxonomy.classify(f"USER#matthew#SOURCE#{n}")
        except Exception:  # noqa: BLE001
            unclassified.append(n)
    assert not unclassified, f"MCP reads a source the taxonomy has never ruled on: {unclassified}"


@pytest.mark.parametrize("fn_name", ["query_source", "parallel_query_sources", "query_source_range"])
def test_the_chokepoint_defaults_to_derive(fn_name):
    sig = inspect.signature(getattr(core, fn_name))
    assert sig.parameters["include_pilot"].default is None, f"{fn_name} must default include_pilot=None (derive)"


# ── the wire ───────────────────────────────────────────────────────────────────

PROFILE = {"pk": "USER#matthew", "sk": "PROFILE#v1", "max_heart_rate": 185, "resting_heart_rate_baseline": 60}
_PHASE_EXPR = core._PHASE_FILTER_EXPRESSION


def _strava_pilot_day():
    """2024-10-01 in the live wire shape (read 2026-09-23): phase=pilot, 6 activities; two of the walks."""
    return {
        "pk": "USER#matthew#SOURCE#strava",
        "sk": "DATE#2024-10-01",
        "date": "2024-10-01",
        "phase": "pilot",
        "source": "strava",
        "activity_count": 2,
        "total_distance_miles": 3.0,
        "total_elevation_gain_feet": 40.0,
        "total_moving_time_seconds": 7255,
        "activities": [
            {
                "name": "Lunch Walk",
                "sport_type": "Walk",
                "device_name": "Garmin Epix Gen2",
                "trainer": False,
                "manual": False,
                "distance_miles": 3.0,
                "total_elevation_gain_feet": 40.0,
                "moving_time_seconds": 3656,
                "average_heartrate": 118,
                "strava_id": "PILOT-GARMIN",
            },
            {
                "name": "Lunch Walk",
                "sport_type": "Walk",
                "device_name": "WHOOP",
                "trainer": True,
                "manual": False,
                "moving_time_seconds": 3599,
                "average_heartrate": 115,
                "strava_id": "PILOT-WHOOP",
            },
        ],
    }


def _computed_metrics(date, phase, acwr):
    return {
        "pk": "USER#matthew#SOURCE#computed_metrics",
        "sk": f"DATE#{date}",
        "date": date,
        "phase": phase,
        "acwr": acwr,
        "acute_load_7d": 10.0,
        "chronic_load_28d": 9.0,
        "acwr_zone": "safe",
    }


def _withings(date, lbs):
    # Deliberately UNSTAMPED (passes the filter either way), so the benchmark assertion — and
    # its mutation control — turns on the Strava read alone, not on the weight read.
    return {"pk": "USER#matthew#SOURCE#withings", "sk": f"DATE#{date}", "date": date, "weight_lbs": lbs}


TRAINING_REFERENCE = {
    "pk": "USER#matthew#SOURCE#training_reference",
    "sk": "DATE#2024-09-01",
    "date": "2024-09-01",
    "bands": {},
    "proven_curve": [],
}


def _eval_key(cond, item):
    expr = cond.get_expression()
    op, vals = expr["operator"], expr["values"]
    if op == "AND":
        return _eval_key(vals[0], item) and _eval_key(vals[1], item)
    actual = str(item.get(vals[0].name, ""))
    if op == "=":
        return actual == vals[1]
    if op == "BETWEEN":
        return vals[1] <= actual <= vals[2]
    if op == "begins_with":
        return actual.startswith(vals[1])
    raise AssertionError(f"fake table: unhandled key operator {op!r}")


class _FakeTable:
    def __init__(self, rows):
        self.rows = rows

    def get_item(self, Key):  # noqa: N803 — boto3's parameter name
        return {"Item": PROFILE} if Key == {"pk": PROFILE["pk"], "sk": PROFILE["sk"]} else {}

    def put_item(self, **_kw):
        return {}

    def query(self, **kwargs):
        rows = [r for r in self.rows if _eval_key(kwargs["KeyConditionExpression"], r)]
        fe = kwargs.get("FilterExpression")
        if fe is not None:
            assert fe == _PHASE_EXPR, f"unexpected FilterExpression {fe!r}"
            field = kwargs["ExpressionAttributeNames"]["#phase"]
            wanted = kwargs["ExpressionAttributeValues"][":phase_experiment"]
            rows = [r for r in rows if field not in r or r[field] == wanted]
        return {"Items": rows}


ROWS = [
    _strava_pilot_day(),
    _computed_metrics("2024-10-01", "pilot", 1.7),
    _withings("2024-09-20", 330.0),
    _withings("2024-09-27", 329.0),
    _withings("2024-10-01", 328.0),
    TRAINING_REFERENCE,
]


_TOOL_MODULES = ("mcp.tools_data", "mcp.tools_training", "mcp.tools_correlation", "mcp.tools_benchmark", "mcp.helpers")


@pytest.fixture
def wired(monkeypatch):
    fake = _FakeTable(list(ROWS))
    monkeypatch.setattr(core, "table", fake)
    monkeypatch.setattr(core, "_PROFILE_CACHE", None, raising=False)
    monkeypatch.setattr(core, "get_profile", lambda: dict(PROFILE))
    for mod in _TOOL_MODULES:
        m = sys.modules.get(mod) or __import__(mod, fromlist=["_"])
        if hasattr(m, "get_profile"):
            monkeypatch.setattr(m, "get_profile", lambda: dict(PROFILE))
        if hasattr(m, "table"):  # a module that bound `table` at import must not reach real DynamoDB
            monkeypatch.setattr(m, "table", fake)
    yield fake


def _old_default(monkeypatch):
    """The pre-#4061 chokepoint: `None` meant the ADR-058 filter, whatever the source."""
    monkeypatch.setattr(core, "_resolve_include_pilot", lambda source, ip: ((False if ip is None else bool(ip)), False))


# ── 2. the public tool paths ──────────────────────────────────────────────────


def _check_search_activities():
    out = TOOLS["search_activities"]["fn"]({"start_date": "2024-09-15", "end_date": "2025-05-10", "sport_type": "walk"})
    ids = {a.get("strava_id") for a in out["activities"]}
    assert {"PILOT-GARMIN", "PILOT-WHOOP"} <= ids, f"search_activities lost the pilot walks: {out}"


def _check_find_days():
    out = TOOLS["find_days"]["fn"]({"source": "strava", "start_date": "2024-09-15", "end_date": "2025-05-10"})
    assert [d["date"] for d in out] == ["2024-10-01"], f"find_days lost the pilot day: {out}"


def _check_get_training():
    out = TOOLS["get_training"]["fn"]({"view": "load", "start_date": "2024-09-20", "end_date": "2024-10-05"})
    assert "error" not in out, f"get_training(load) saw no cardio data: {out}"


def _check_zone2():
    out = TOOLS["get_zone2_breakdown"]["fn"]({"start_date": "2024-09-15", "end_date": "2024-10-05"})
    assert "error" not in out, f"get_zone2_breakdown saw no Strava data: {out}"


def _check_benchmark():
    out = TOOLS["get_benchmark"]["fn"]({"view": "pace", "date": "2024-10-05"})
    assert out.get("walks_wk_current"), f"get_benchmark(pace) counted no walks: {out}"


def _check_daily_snapshot():
    out = TOOLS["get_daily_snapshot"]["fn"]({"view": "summary", "date": "2024-10-01"})
    assert "strava" in out, f"get_daily_snapshot(summary) lost the pilot day: {sorted(out)}"


PUBLIC_PATHS = {
    "get_daily_snapshot": _check_daily_snapshot,
    "search_activities": _check_search_activities,
    "find_days": _check_find_days,
    "get_training": _check_get_training,
    "get_zone2_breakdown": _check_zone2,
    "get_benchmark": _check_benchmark,
}


def test_the_planted_row_is_what_the_filter_would_hide():
    """Vacuity guard: strava is RAW_TIMESERIES and the planted row is phase=pilot."""
    assert phase_taxonomy.classify("USER#matthew#SOURCE#strava") == phase_taxonomy.RAW_TIMESERIES
    assert _strava_pilot_day()["phase"] == "pilot"


@pytest.mark.parametrize("tool", sorted(PUBLIC_PATHS))
def test_a_pre_genesis_strava_row_reaches_the_public_tool(wired, tool):
    PUBLIC_PATHS[tool]()


@pytest.mark.parametrize("tool", sorted(PUBLIC_PATHS))
def test_mutation_restoring_the_old_default_reds_every_public_path(wired, monkeypatch, tool):
    _old_default(monkeypatch)
    with pytest.raises(AssertionError):
        PUBLIC_PATHS[tool]()


@pytest.mark.parametrize("source", sorted(phase_taxonomy.RAW_TIMESERIES_SOURCES + phase_taxonomy.CROSS_PHASE_SOURCES))
def test_every_never_hidden_source_reads_its_pilot_rows(monkeypatch, source):
    row = {"pk": f"USER#matthew#SOURCE#{source}", "sk": "DATE#2024-10-01", "date": "2024-10-01", "phase": "pilot"}
    monkeypatch.setattr(core, "table", _FakeTable([row]))
    assert len(core.query_source(source, "2024-09-01", "2024-10-31")) == 1


# ── 3. the regression control ─────────────────────────────────────────────────


@pytest.mark.parametrize("source", sorted(phase_taxonomy.SCOPED_SOURCES))
def test_every_experiment_scoped_source_keeps_the_filter(monkeypatch, source):
    rows = [
        {"pk": f"USER#matthew#SOURCE#{source}", "sk": "DATE#2024-10-01", "date": "2024-10-01", "phase": "pilot"},
        {"pk": f"USER#matthew#SOURCE#{source}", "sk": "DATE#2024-10-02", "date": "2024-10-02", "phase": "experiment"},
    ]
    monkeypatch.setattr(core, "table", _FakeTable(rows))
    assert [r["date"] for r in core.query_source(source, "2024-09-01", "2024-10-31")] == ["2024-10-02"]


def test_get_acwr_status_still_hides_a_pilot_computed_metrics_row(wired):
    out = TOOLS["get_acwr_status"]["fn"]({"date": "2024-10-01", "days_back": 7})
    assert "error" in out and "computed_metrics" in out["error"], out


def test_an_explicit_include_pilot_still_wins(monkeypatch):
    monkeypatch.setattr(core, "table", _FakeTable([_strava_pilot_day()]))
    assert core.query_source("strava", "2024-09-01", "2024-10-31", include_pilot=False) == []
    rows = [_computed_metrics("2024-10-01", "pilot", 1.7)]
    monkeypatch.setattr(core, "table", _FakeTable(rows))
    assert len(core.query_source("computed_metrics", "2024-09-01", "2024-10-31", include_pilot=True)) == 1


def test_a_derived_read_drops_superseded_rows(monkeypatch):
    rows = [dict(_strava_pilot_day(), tombstone=True)]
    monkeypatch.setattr(core, "table", _FakeTable(rows))
    assert core.query_source("strava", "2024-09-01", "2024-10-31") == []
    assert len(core.query_source("strava", "2024-09-01", "2024-10-31", include_pilot=True)) == 1


def test_parallel_query_sources_derives_per_source(monkeypatch):
    rows = [_strava_pilot_day(), _computed_metrics("2024-10-01", "pilot", 1.7)]
    monkeypatch.setattr(core, "table", _FakeTable(rows))
    got = core.parallel_query_sources(["strava", "computed_metrics"], "2024-09-01", "2024-10-31")
    assert len(got["strava"]) == 1 and got["computed_metrics"] == []


# ── 5. box 4: unmeasured distance is said, not dropped ────────────────────────


def test_search_activities_ranks_the_unmeasured_walk_last_and_says_so(wired):
    out = TOOLS["search_activities"]["fn"]({"start_date": "2024-09-15", "end_date": "2025-05-10", "sport_type": "walk"})
    assert [a["strava_id"] for a in out["activities"]] == ["PILOT-GARMIN", "PILOT-WHOOP"]
    assert out["unmeasured"]["matched_without_distance_miles"] == 1
    assert "WHOOP" in out["unmeasured"]["note"]


def test_search_activities_counts_what_a_min_distance_filter_could_not_evaluate(wired):
    out = TOOLS["search_activities"]["fn"](
        {"start_date": "2024-09-15", "end_date": "2025-05-10", "sport_type": "walk", "min_distance_miles": 1}
    )
    assert [a["strava_id"] for a in out["activities"]] == ["PILOT-GARMIN"]
    assert out["unmeasured"]["excluded_by_min_filter_unmeasured"] == {"distance_miles": 1}


def test_search_activities_fully_measured_answer_carries_no_block(wired, monkeypatch):
    day = _strava_pilot_day()
    day["activities"] = day["activities"][:1]
    wired.rows = [day]
    out = TOOLS["search_activities"]["fn"]({"start_date": "2024-09-15", "end_date": "2025-05-10"})
    assert "unmeasured" not in out


def test_find_days_row_says_what_its_distance_total_leaves_out(wired):
    out = TOOLS["find_days"]["fn"]({"source": "strava", "start_date": "2024-09-15", "end_date": "2025-05-10"})
    assert out[0]["activities_without_distance"] == 1
