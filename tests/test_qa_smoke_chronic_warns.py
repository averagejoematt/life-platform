"""#1958 — qa-smoke-warnings must be clearable: chronic timing warns leave the
alarmed WarnCount.

The defect: WarnCount's honest daily floor was 4-11 (five OPTIONAL registry
sources with no record on an event-driven day, plus the MCP cache-warm
partial), monitoring_stack alarms WarnCount >= 1 over an 86400s Maximum
window, so qa-smoke-warnings sat red 15+ consecutive nights and a red carried
no information (ADR-105: thresholds come from the metric's real distribution).

The fix under test: `Check.warn(chronic=True)` — set ONLY at the enumerated
known-recurring timing call sites — routes those warns into a separate,
deliberately NON-alarmed ChronicWarnCount metric via `qa_check.split_warns`,
the single chokepoint both check modules (qa_smoke_lambda and
qa_check_reader_truth) share. WarnCount becomes the alarmed count and can
reach 0 on a healthy night; the alarm itself (threshold, statistic, and the
load-bearing 24h Maximum window) is untouched.

Guard-the-set discipline (the #1917/#1953 lesson, 4 recurrences): the chronic
set is asserted two ways —
  * derived: an AST scan finds every `.warn(..., chronic=True)` call site in
    the operational package, so a new chronic opt-out cannot appear silently;
  * negative: a NOVEL warn class (the shape of #1953's qa_predict_dark) still
    lands on the alarmed side, because `chronic` defaults to False.

Every functional test here FAILS against the pre-#1958 tree (Check.warn had
no `chronic`, emf_summary_line had no ChronicWarnCount).
"""

import ast
import inspect
import json
import os
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]

# qa_smoke_lambda reads these at import time (conftest supplies fake AWS creds).
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("EMAIL_RECIPIENT", "qa@example.com")
os.environ.setdefault("EMAIL_SENDER", "qa@example.com")

sys.path.insert(0, str(REPO / "lambdas"))

import qa_smoke_lambda as qa  # noqa: E402
from operational.qa_check import CONTENT_TRUTH, Check, emf_summary_line, split_warns  # noqa: E402

OPERATIONAL = REPO / "lambdas" / "operational"
MONITORING = REPO / "cdk" / "stacks" / "monitoring_stack.py"

# The ONE enumerated registry of sanctioned chronic call sites, by (file,
# enclosing function). Extending the chronic set means extending THIS list in
# the same PR — the AST scan below fails on any silent drift in either
# direction. #1958 entries are the known-recurring timing class:
#   check_ddb_freshness   — an OPTIONAL (event-driven/manual) source with no
#                           record yesterday; derived from the registry's
#                           qa_tier facet, recurs on a healthy platform.
#   check_mcp_tool_calls  — the cache-warm partial (warmer cadence vs the
#                           10:30 PT sweep).
# #2378 entries (the alarm sat structurally red 21+ days AFTER the #1958
# split because these recurred nightly on the alarmed side):
#   check_score_sanity / _range_check — a null on an OPTIONAL dashboard
#                           metric ("may not have synced") + the hydration
#                           None branch: the same event-driven timing class.
#                           (_range_check is nested inside check_score_sanity,
#                           so the AST scan attributes its site to BOTH
#                           enclosing functions — both entries are the same
#                           two call sites, not four.)
#   check_canary_precision — the fail-soft unreadable branch, pinned to the
#                           filed grant gap #1956; un-chronic when it lands.
#   check_coach_ensemble_phase_stamp_coverage — the unstamped-rows warn,
#                           pinned to the filed backfill gap #1970; the
#                           errored branch stays alarmed.
SANCTIONED_CHRONIC_SITES = {
    ("qa_smoke_lambda.py", "check_ddb_freshness"),
    ("qa_smoke_lambda.py", "check_mcp_tool_calls"),
    ("qa_check_outputs.py", "check_score_sanity"),
    ("qa_check_outputs.py", "_range_check"),
    ("qa_smoke_lambda.py", "check_canary_precision"),
    ("qa_smoke_lambda.py", "check_coach_ensemble_phase_stamp_coverage"),
}


# ---------------------------------------------------------------------------
# 1. The vocabulary: Check.warn's chronic flag
# ---------------------------------------------------------------------------


def test_warn_defaults_to_not_chronic():
    """The safety direction: a NEW warn call site is alarmed unless it
    explicitly opts out — a novel warn class can never be born muted."""
    c = Check("novel:thing", "Novel", CONTENT_TRUTH).warn("something new happened")
    assert c.chronic is False


def test_warn_chronic_true_sets_the_flag():
    c = Check("DDB:withings", "Data Freshness", CONTENT_TRUTH).warn("no record (optional)", chronic=True)
    assert c.chronic is True
    assert c.passed is None  # still a warn in every other respect


def test_ok_fail_pause_are_never_chronic():
    assert Check("a", "x", CONTENT_TRUTH).ok("fine").chronic is False
    assert Check("b", "x", CONTENT_TRUTH).fail("broken").chronic is False
    assert Check("c", "x", CONTENT_TRUTH).pause("later").chronic is False


# ---------------------------------------------------------------------------
# 2. split_warns — the single classification chokepoint
# ---------------------------------------------------------------------------


def test_split_warns_partitions_and_excludes_non_warns():
    checks = [
        Check("p", "x", CONTENT_TRUTH).ok("green"),
        Check("f", "x", CONTENT_TRUTH).fail("red"),
        Check("z", "x", CONTENT_TRUTH).pause("paused"),
        Check("novel", "x", CONTENT_TRUTH).warn("new class"),
        Check("DDB:strava", "x", CONTENT_TRUTH).warn("no record (optional)", chronic=True),
        Check("DDB:notion", "x", CONTENT_TRUTH).warn("no record (optional)", chronic=True),
    ]
    alarmed, chronic = split_warns(checks)
    assert [c.name for c in alarmed] == ["novel"]
    assert sorted(c.name for c in chronic) == ["DDB:notion", "DDB:strava"]


def test_a_chronic_only_night_yields_alarmed_warncount_zero():
    """Acceptance 1+3 (#1958), functionally: a night whose only warns are the
    chronic timing set emits WarnCount=0 — the alarm can actually clear."""
    checks = [Check(f"DDB:{s}", "Data Freshness", CONTENT_TRUTH).warn("no record (optional)", chronic=True) for s in ("withings", "strava")]
    alarmed, chronic = split_warns(checks)
    doc = json.loads(
        emf_summary_line(passed=15, warned=len(alarmed), failed=0, paused=2, timestamp_ms=1_700_000_000_000, warned_chronic=len(chronic))
    )
    assert doc["WarnCount"] == 0, "chronic-only warns must not increment the alarmed WarnCount (#1958)"
    assert doc["ChronicWarnCount"] == 2
    assert doc["RunCompleted"] == 1


def test_a_novel_warn_class_still_increments_the_alarmed_metric():
    """The negative direction (the #1953 interaction): a brand-new warn class —
    e.g. qa_predict_dark's dark-during-live-cycle day 1 — carries information
    and MUST keep alarming, chronic reclassification notwithstanding."""
    checks = [
        Check("DDB:withings", "Data Freshness", CONTENT_TRUTH).warn("no record (optional)", chronic=True),
        Check("predict_week:freshness", "Predict-the-Week Freshness", CONTENT_TRUTH).warn(
            "predict-the-week is DARK during a live-cycle week (day 1 of the dark streak)"
        ),
    ]
    alarmed, chronic = split_warns(checks)
    doc = json.loads(
        emf_summary_line(passed=15, warned=len(alarmed), failed=0, paused=0, timestamp_ms=1_700_000_000_000, warned_chronic=len(chronic))
    )
    assert doc["WarnCount"] == 1, "a novel warn class stopped incrementing the alarmed WarnCount — the alarm went blind"
    assert doc["ChronicWarnCount"] == 1


# ---------------------------------------------------------------------------
# 3. The EMF document
# ---------------------------------------------------------------------------


def test_emf_declares_chronic_warn_count_as_a_metric():
    doc = json.loads(emf_summary_line(passed=1, warned=0, failed=0, paused=0, timestamp_ms=1_700_000_000_000, warned_chronic=3))
    names = {m["Name"] for m in doc["_aws"]["CloudWatchMetrics"][0]["Metrics"]}
    assert "ChronicWarnCount" in names, "ChronicWarnCount missing from the EMF metric declaration — value would never extract"
    assert "WarnCount" in names
    assert doc["ChronicWarnCount"] == 3


def test_emf_warned_chronic_defaults_to_zero():
    """Back-compat: existing callers/tests that don't pass warned_chronic keep
    working and honestly report zero chronic warns."""
    doc = json.loads(emf_summary_line(passed=1, warned=2, failed=0, paused=0, timestamp_ms=1_700_000_000_000))
    assert doc["WarnCount"] == 2
    assert doc["ChronicWarnCount"] == 0


# ---------------------------------------------------------------------------
# 4. The real check functions classify as designed (not just the vocabulary)
# ---------------------------------------------------------------------------


class _NoItemTable:
    """DDB table stub: every get_item finds nothing (yesterday has no record)."""

    def get_item(self, Key):  # noqa: N803 — boto3 surface
        return {}


class _ErrorTable:
    def get_item(self, Key):  # noqa: N803 — boto3 surface
        raise RuntimeError("ProvisionedThroughputExceededException (simulated)")


def test_optional_source_missing_day_is_chronic_required_is_fail(monkeypatch):
    """Run the REAL check_ddb_freshness against a no-records-yesterday table:
    every OPTIONAL source's missing-day warn must be chronic (derived from the
    registry's qa_tier facet — the whole branch, not a name list), while a
    REQUIRED source's missing day stays a FAIL."""
    import ingestion.source_registry as reg

    monkeypatch.setattr(reg, "qa_required", lambda: [("whoop", "Recovery, sleep, HRV")])
    monkeypatch.setattr(reg, "qa_optional", lambda: [("withings", "Weight"), ("strava", "Activities")])
    monkeypatch.setattr(reg, "qa_paused", lambda: [])
    monkeypatch.setattr(qa, "table", _NoItemTable())

    checks = qa.check_ddb_freshness()
    by_name = {c.name: c for c in checks}

    assert by_name["DDB:whoop"].passed is False, "REQUIRED source missing a day must stay a FAIL"
    for name in ("DDB:withings", "DDB:strava"):
        assert by_name[name].passed is None, f"{name} should warn on a missing optional day"
        assert by_name[name].chronic is True, f"{name}'s missing-day warn must be chronic (#1958) — it recurs on a healthy platform"

    alarmed, chronic = split_warns(checks)
    assert alarmed == [], "the optional-source timing warns leaked into the alarmed WarnCount"
    assert len(chronic) == 2


def test_optional_source_ddb_error_stays_alarmed(monkeypatch):
    """A DDB ERROR on an optional source is a real novel fault, not a timing
    condition — it must stay on the alarmed side. This is why chronic rides the
    warn CONDITION, not the check name."""
    import ingestion.source_registry as reg

    monkeypatch.setattr(reg, "qa_required", lambda: [])
    monkeypatch.setattr(reg, "qa_optional", lambda: [("withings", "Weight")])
    monkeypatch.setattr(reg, "qa_paused", lambda: [])
    monkeypatch.setattr(qa, "table", _ErrorTable())

    checks = qa.check_ddb_freshness()
    alarmed, chronic = split_warns(checks)
    assert [c.name for c in alarmed] == ["DDB:withings"], "a DDB error on an optional source must increment the alarmed WarnCount"
    assert chronic == []


# --- #2378: the sites that kept the alarm structurally red AFTER #1958 ------


class _S3JsonStub:
    """S3 stub returning one fixed JSON document for any get_object."""

    class exceptions:
        class NoSuchKey(Exception):
            pass

    def __init__(self, payload):
        self._payload = payload

    def get_object(self, Bucket=None, Key=None):  # noqa: N803 — boto3 surface
        import io

        return {"Body": io.BytesIO(json.dumps(self._payload).encode())}


def _score_sanity_with(monkeypatch, payload):
    from operational import qa_check_outputs as qco

    monkeypatch.setattr(qco, "s3", _S3JsonStub(payload))
    return {c.name: c for c in qco.check_score_sanity()}


def test_optional_metric_null_is_chronic_out_of_range_stays_fail(monkeypatch):
    """#2378: a null on an OPTIONAL dashboard metric ("may not have synced")
    is the sweep-hour timing class — chronic. An out-of-range VALUE and a
    null on a required metric keep their hard-FAIL semantics."""
    by_name = _score_sanity_with(
        monkeypatch,
        {
            "date": "2026-01-01",  # stale on purpose; dashboard:date is not under test
            "readiness": {"score": 55},
            "sleep": {"score": None},
            "hrv": {"value": None},
            "glucose": {"avg": 9999},  # out of range — must stay FAIL
            "weight": {"current": 320},
            "day_grade": {"letter": "B", "score": 80, "components": {"hydration": None}},
        },
    )
    for name in ("value:sleep", "value:hrv"):
        assert by_name[name].passed is None, f"{name} null should warn"
        assert by_name[name].chronic is True, f"{name}'s optional-null warn must be chronic (#2378)"
    assert by_name["value:glucose"].passed is False, "an out-of-range value must stay a FAIL, never chronic"
    assert by_name["score:hydration"].passed is None
    assert by_name["score:hydration"].chronic is True, "hydration-null (HAE webhook timing) must be chronic (#2378)"


def test_low_hydration_value_stays_alarmed(monkeypatch):
    """The low-but-present hydration branch is a data anomaly, not a timing
    condition — it must stay on the alarmed side."""
    by_name = _score_sanity_with(
        monkeypatch,
        {
            "date": "2026-01-01",
            "day_grade": {"letter": "B", "score": 80, "components": {"hydration": 5}},
        },
    )
    c = by_name["score:hydration"]
    assert c.passed is None and c.chronic is False, "a LOW hydration value must remain alarmed"


class _CanaryS3Denied:
    class exceptions:
        class NoSuchKey(Exception):
            pass

    def get_object(self, Bucket=None, Key=None):  # noqa: N803 — boto3 surface
        raise RuntimeError("AccessDenied (simulated) — no s3:GetObject on ai-canary-log/*")


def test_canary_unreadable_branch_is_chronic(monkeypatch):
    """#2378: the fail-soft unreadable branch is pinned to the filed grant gap
    #1956 and recurred nightly — chronic until the grant lands."""
    monkeypatch.setattr(qa, "s3", _CanaryS3Denied())
    (c,) = qa.check_canary_precision()
    assert c.passed is None
    assert c.chronic is True, "the #1956 unreadable branch must be chronic (#2378)"
    assert "#1956" in c.message


class _UnstampedTable:
    def query(self, **kw):
        return {"Items": [{"sk": "BRIEF#2026-08-03"}]}


class _ErroringTable:
    def query(self, **kw):
        raise RuntimeError("boom (simulated)")


def test_phase_stamp_gap_is_chronic_but_check_error_stays_alarmed(monkeypatch):
    """#2378: the known #1970 unstamped-rows gap (own operator backfill tool)
    is chronic; the check ERRORING is a novel fault and stays alarmed."""
    monkeypatch.setattr(qa, "table", _UnstampedTable())
    (c,) = qa.check_coach_ensemble_phase_stamp_coverage()
    assert c.passed is None
    assert c.chronic is True, "the #1970 unstamped-rows warn must be chronic (#2378)"

    monkeypatch.setattr(qa, "table", _ErroringTable())
    (c,) = qa.check_coach_ensemble_phase_stamp_coverage()
    assert c.passed is None
    assert c.chronic is False, "the check ERRORING must stay on the alarmed side"


# ---------------------------------------------------------------------------
# 5. Guard the SET — derived by AST scan, both directions
# ---------------------------------------------------------------------------


def _chronic_true_call_sites():
    """Every `<expr>.warn(..., chronic=True)` in the operational package, as
    (file, enclosing function) — derived from source, never from memory. Any
    non-literal or non-boolean chronic kwarg is reported too, so a dynamic
    value can't slip under the literal-True match."""
    sites, suspicious = [], []
    for path in sorted(OPERATIONAL.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(func):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "warn"):
                    continue
                for kw in node.keywords:
                    if kw.arg != "chronic":
                        continue
                    if isinstance(kw.value, ast.Constant) and kw.value.value is True:
                        sites.append((path.name, func.name))
                    elif not (isinstance(kw.value, ast.Constant) and kw.value.value is False):
                        suspicious.append((path.name, func.name, ast.unparse(kw.value)))
    return sites, suspicious


def test_chronic_call_sites_are_exactly_the_sanctioned_set():
    sites, suspicious = _chronic_true_call_sites()
    assert not suspicious, f"chronic= must be a literal True/False at every call site, found dynamic values: {suspicious}"
    assert set(sites) == SANCTIONED_CHRONIC_SITES, (
        f"chronic=True call sites drifted from the sanctioned #1958 set.\n"
        f"  found:      {sorted(set(sites))}\n"
        f"  sanctioned: {sorted(SANCTIONED_CHRONIC_SITES)}\n"
        "A NEW chronic site mutes a warn class from the qa-smoke-warnings alarm — that is an explicit, "
        "reviewed decision: update SANCTIONED_CHRONIC_SITES in the same PR or keep the warn alarmed."
    )
    # Guard the guard: the scan must actually find the two known sites.
    assert len(sites) >= 2, f"AST scan found only {len(sites)} chronic sites — the scan itself is broken"


def test_reader_truth_half_routes_through_the_same_default():
    """#1944 split the reader-truth pair out of qa_smoke_lambda; both halves
    build the same Check class, so every reader-truth warn is alarmed unless it
    ever explicitly (and test-visibly, above) opts out. Assert the module has
    zero chronic opt-outs today."""
    sites, _ = _chronic_true_call_sites()
    assert not [s for s in sites if s[0] == "qa_check_reader_truth.py"]
    assert not [s for s in sites if s[0] == "reader_truth_qa.py"]


# ---------------------------------------------------------------------------
# 6. The handler wires the split into the EMF line
# ---------------------------------------------------------------------------


def test_lambda_handler_feeds_split_warns_into_the_emf_line():
    """Statically prove the handler (a) calls split_warns, and (b) passes the
    alarmed side as `warned=` and the chronic side as `warned_chronic=` — not
    the raw total, which would silently restore the unclearable alarm."""
    src = inspect.getsource(qa.lambda_handler)
    tree = ast.parse(src)

    calls_split = any(
        isinstance(n, ast.Call) and (getattr(n.func, "id", None) == "split_warns" or getattr(n.func, "attr", None) == "split_warns")
        for n in ast.walk(tree)
    )
    assert calls_split, "lambda_handler never calls split_warns — the chronic classification is dead code (#1958)"

    emf_calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and (getattr(n.func, "id", None) == "emf_summary_line" or getattr(n.func, "attr", None) == "emf_summary_line")
    ]
    assert emf_calls, "lambda_handler no longer calls emf_summary_line — see test_qa_smoke_metrics.py"
    kw = {k.arg: ast.unparse(k.value) for k in emf_calls[0].keywords}
    assert "warned_chronic" in kw, "emf_summary_line call missing warned_chronic= — ChronicWarnCount would always read 0 (#1958)"
    assert "warns_chronic" in kw["warned_chronic"]
    assert "warns_alarmed" in kw.get("warned", ""), (
        f"emf_summary_line's warned= must be the ALARMED side (warns_alarmed), got {kw.get('warned')!r} — "
        "passing the total re-creates the unclearable qa-smoke-warnings alarm (#1958)"
    )


# ---------------------------------------------------------------------------
# 7. monitoring_stack: the alarm is untouched, and nothing alarms the chronic metric
# ---------------------------------------------------------------------------


def test_no_alarm_watches_chronic_warn_count():
    """ChronicWarnCount is DELIBERATELY unalarmed — its honest floor is the
    whole reason for the split; alarming it would re-create #1958 under a new
    name. (test_qa_smoke_metrics.py continues to assert the qa-smoke-warnings
    alarm on WarnCount, threshold/statistic/period unchanged.)"""
    tree = ast.parse(MONITORING.read_text())
    offenders = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) in ("_alarm", "_heartbeat_alarm")
        and any(isinstance(a, ast.Constant) and a.value == "ChronicWarnCount" for a in list(node.args) + [k.value for k in node.keywords])
    ]
    assert not offenders, f"monitoring_stack.py alarms ChronicWarnCount (lines {offenders}) — that re-creates the unclearable alarm (#1958)"


def test_qa_smoke_warnings_alarm_window_untouched():
    """The 24h Maximum window is load-bearing (standing memory): assert the
    qa-smoke-warnings _alarm call still carries period=86400 / Maximum / 1."""
    tree = ast.parse(MONITORING.read_text())
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and getattr(node.func, "id", None) == "_alarm"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == "qa-smoke-warnings"
        ):
            values = [a.value for a in node.args if isinstance(a, ast.Constant)]
            assert 86400 in values, "qa-smoke-warnings lost its 86400s period — the 24h Maximum window is load-bearing"
            assert "Maximum" in values, "qa-smoke-warnings lost its Maximum statistic"
            assert "WarnCount" in values, "qa-smoke-warnings no longer watches WarnCount"
            return
    pytest.fail("qa-smoke-warnings _alarm call not found in monitoring_stack.py")
