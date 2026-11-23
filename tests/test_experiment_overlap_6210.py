"""tests/test_experiment_overlap_6210.py — the proportional overlap rule (#6210, epic #6206).

Synthetic rows only. none / note / warning / acknowledged paths, washout overlap, legacy
rows, the stored acknowledgement, and that an observational experiment is never refused.
"""

import os
import sys

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "lambdas"))

import pytest  # noqa: E402
from experiment import experiment_overlap as eo  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402

import mcp.tools_lifestyle as tl  # noqa: E402

STOP = "run the full 21 days regardless of interim trend; abort only if recovery < 40% for 3 consecutive days"
REASON = "I am deliberately stacking these two because the first is a fixed baseline habit."


def _design(metric, washout=3):
    return {
        "baseline_days": 14,
        "washout_days": washout,
        "stopping_rule": STOP,
        "criterion": {"metric": metric, "direction": "higher", "min_effect": 2},
    }


def _active(eid, metric=None, kind="behavioral", start="2026-11-20", washout=3, **extra):
    row = {"experiment_id": eid, "name": eid, "status": "active", "start_date": start, "intervention_kind": kind}
    if metric:
        row["design"] = _design(metric, washout)
    row.update(extra)
    return row


def _new(metric=None, kind="behavioral", start="2026-11-22", **extra):
    return {"start_date": start, "design": _design(metric) if metric else None, "intervention_kind": kind, **extra}


# ── pure function ───────────────────────────────────────────────────────────────


def test_none_without_active_or_unrelated():
    assert eo.assess_overlap(_new("deep_pct"), [])["level"] == "none"
    r = eo.assess_overlap(_new("deep_pct"), [_active("a", "steps", start="2026-10-01")])
    assert r["level"] == "none" and r["conflicts"] == []


def test_family_only_is_a_note():
    r = eo.assess_overlap(_new("deep_pct"), [_active("a", "sleep_score", start="2026-10-01")])
    assert r["level"] == "note"
    assert r["conflicts"][0]["kind"] == "family" and r["conflicts"][0]["family"] == "sleep"


def test_same_metric_behavioural_is_warning():
    r = eo.assess_overlap(_new("deep_pct"), [_active("a", "deep_pct")])
    assert r["level"] == "warning"
    assert r["conflicts"][0]["kind"] == "metric" and r["conflicts"][0]["experiment_id"] == "a"


def test_same_metric_observational_new_is_note():
    r = eo.assess_overlap(_new("deep_pct", kind="observational"), [_active("a", "deep_pct")])
    assert r["level"] == "note"


def test_same_metric_active_observational_is_note():
    assert eo.assess_overlap(_new("deep_pct"), [_active("a", "deep_pct", kind="observational")])["level"] == "note"


def test_washout_overlap_is_warning_even_across_metrics():
    # active started 11-20 with 3 washout days -> washout ends 11-23; new starts 11-22
    r = eo.assess_overlap(_new("steps"), [_active("a", "deep_pct")])
    assert r["level"] == "warning" and r["conflicts"][0]["kind"] == "washout"
    # starting after the washout ended is fine (different family)
    assert eo.assess_overlap(_new("steps", start="2026-11-23"), [_active("a", "deep_pct")])["level"] == "none"


def test_legacy_rows_at_most_a_note():
    legacy = _active("old", None, tags=["sleep"], library_id="lib-1")
    assert eo.assess_overlap(_new("deep_pct", tags=["Sleep"]), [legacy])["level"] == "note"
    assert eo.assess_overlap(_new(None, library_id="lib-1"), [legacy])["level"] == "note"
    # a design-less NEW row against a designed active one: still no warning
    assert eo.assess_overlap(_new(None, tags=["x"]), [_active("a", "deep_pct", tags=["x"])])["level"] == "note"
    assert eo.assess_overlap(_new(None), [legacy])["level"] == "none"


def test_family_registry_and_training_prefix():
    assert eo.family_of("hrv_rmssd") == "recovery_hr" and eo.family_of("weight_lbs") == "body_weight_intake"
    assert eo.family_of("cgm_mean_glucose") == "glucose" and eo.family_of("steps") == "activity"
    assert eo.family_of("training_volume") == "training" and eo.family_of("nonsense") is None and eo.family_of(None) is None


def test_validators():
    assert eo.normalize_kind(None) == "behavioral" and eo.normalize_kind("Observational") == "observational"
    with pytest.raises(ValueError):
        eo.normalize_kind("both")
    assert eo.validate_acknowledgement(None) is None and eo.validate_acknowledgement("   ") is None
    for bad in ("too short", "x" * 301):
        with pytest.raises(ValueError):
            eo.validate_acknowledgement(bad)


def test_closing_caveat_both_directions():
    ack = {"conflicts": [{"experiment_id": "a", "name": "Alpha", "kind": "metric"}]}
    b = {"experiment_id": "b", "name": "Beta", "overlap_acknowledged": ack}
    a = {"experiment_id": "a", "name": "Alpha"}
    assert "Alpha" in eo.closing_caveat(b, [a, b])
    assert "Beta" in eo.closing_caveat(a, [a, b])
    assert eo.closing_caveat({"experiment_id": "c"}, [a, b]) is None


# ── tool_create_experiment ──────────────────────────────────────────────────────


class _S3:
    def put_object(self, **kw):
        pass


def _seed(monkeypatch, *rows):
    table = FakeDdbTable()
    monkeypatch.setattr(tl, "table", table)
    monkeypatch.setattr(tl, "s3_client", _S3())
    table._query_hook = lambda t, **kw: {"Items": [i for i in t.store.values() if str(i.get("sk", "")).startswith("EXP#")]}
    for r in rows:
        table.put_item(Item={"pk": tl.EXPERIMENTS_PK, "sk": f"EXP#{r['experiment_id']}", **r})
    return table


def _create(**over):
    args = {"name": "Magnesium", "hypothesis": "deep sleep rises", "start_date": "2026-11-22", "design": _design("deep_pct")}
    args.update(over)
    return tl.tool_create_experiment(args)


def _stored(table, resp):
    return table.get_item(Key={"pk": tl.EXPERIMENTS_PK, "sk": f"EXP#{resp['experiment_id']}"})["Item"]


def test_create_none_and_kind_stored(monkeypatch):
    table = _seed(monkeypatch)
    resp = _create()
    assert resp["overlap"]["level"] == "none" and resp["intervention_kind"] == "behavioral"
    assert _stored(table, resp)["intervention_kind"] == "behavioral"
    assert "overlap_acknowledged" not in _stored(table, resp)


def test_create_note_is_returned_and_allowed(monkeypatch):
    _seed(monkeypatch, _active("a", "sleep_score", start="2026-10-01"))
    resp = _create()
    assert resp["created"] and resp["overlap"]["level"] == "note"


def test_create_warning_refused_without_ack(monkeypatch):
    table = _seed(monkeypatch, _active("a", "deep_pct"))
    with pytest.raises(ValueError, match="overlap refused"):
        _create()
    assert not [i for i in table.store.values() if i.get("name") == "Magnesium"]


def test_create_warning_with_ack_stores_it(monkeypatch):
    table = _seed(monkeypatch, _active("a", "deep_pct"))
    resp = _create(acknowledge_overlap=REASON)
    assert resp["created"] and resp["overlap"]["level"] == "warning"
    ack = _stored(table, resp)["overlap_acknowledged"]
    assert ack["reason"] == REASON and ack["conflicts"][0]["experiment_id"] == "a" and ack["acknowledged_at"]


def test_create_short_ack_rejected(monkeypatch):
    _seed(monkeypatch, _active("a", "deep_pct"))
    with pytest.raises(ValueError, match="20-300"):
        _create(acknowledge_overlap="ok go")


def test_observational_never_refused(monkeypatch):
    table = _seed(monkeypatch, _active("a", "deep_pct"))
    resp = _create(intervention_kind="observational")
    assert resp["created"] and resp["overlap"]["level"] == "note"
    assert _stored(table, resp)["intervention_kind"] == "observational"


def test_invalid_kind_rejected(monkeypatch):
    _seed(monkeypatch)
    with pytest.raises(ValueError, match="intervention_kind"):
        _create(intervention_kind="both")


def test_legacy_active_row_never_refuses(monkeypatch):
    _seed(monkeypatch, _active("old", None, tags=["sleep"]))
    resp = _create(tags=["sleep"])
    assert resp["created"] and resp["overlap"]["level"] == "note"


def test_end_experiment_summary_carries_caveat_verdict_untouched(monkeypatch):
    _seed(monkeypatch, _active("a", "deep_pct"))
    resp = _create(acknowledge_overlap=REASON)
    monkeypatch.setattr(tl, "_run_design_analysis", lambda *a, **k: {"verdict": "supported", "summary": "Result."})
    out = tl.tool_end_experiment({"experiment_id": resp["experiment_id"], "outcome": "done", "end_date": "2026-12-14"})
    assert out["analysis"]["verdict"] == "supported"
    assert out["analysis"]["summary"].startswith("Result. Caveat: ran alongside a")
    # and the earlier experiment's close names the later one
    out_a = tl.tool_end_experiment({"experiment_id": "a", "outcome": "done", "end_date": "2026-12-14"})
    assert "Magnesium" in out_a["analysis"]["summary"]


# ── three-state result: a failed check is never "no overlap" (owner ruling 2026-11-22) ─────────


def _broken_read(monkeypatch, *rows):
    table = _seed(monkeypatch, *rows)

    def _boom(t, **kw):
        raise ConnectionError("secret-table-name should not leak")

    table._query_hook = _boom
    return table


def test_read_failure_observational_proceeds_warned_and_stored_indeterminate(monkeypatch):
    table = _broken_read(monkeypatch)
    resp = _create(intervention_kind="observational")
    assert resp["created"] and resp["overlap"]["check_status"] == "indeterminate" and resp["overlap"]["level"] == "indeterminate"
    assert "WITHOUT overlap clearance" in resp["overlap_warning"]
    stored = _stored(table, resp)["overlap"]
    assert stored["check_status"] == "indeterminate" and stored["error_class"] == "ConnectionError"
    assert "secret-table-name" not in str(resp) and "secret-table-name" not in str(stored)


def test_read_failure_behavioral_refused_with_distinguishable_error(monkeypatch):
    table = _broken_read(monkeypatch)
    with pytest.raises(ValueError, match="overlap check could not be completed: ConnectionError; retry, or pass acknowledge_overlap"):
        _create()
    assert not [i for i in table.store.values() if i.get("name") == "Magnesium"]


def test_read_failure_behavioral_acknowledged_stores_indeterminate_not_cleared(monkeypatch):
    table = _broken_read(monkeypatch)
    resp = _create(acknowledge_overlap=REASON)
    assert resp["created"] and resp["overlap"]["check_status"] == "indeterminate"
    row = _stored(table, resp)
    assert row["overlap_acknowledged"]["check_status"] == "indeterminate"
    assert row["overlap_acknowledged"]["reason"] == REASON and row["overlap_acknowledged"]["conflicts"] == []
    assert row["overlap"]["check_status"] == "indeterminate"


def test_malformed_existing_row_is_indeterminate_not_none(monkeypatch):
    bad = _active("bad", "deep_pct")
    bad["design"] = {"criterion": "not-a-dict", "washout_days": 3}
    _seed(monkeypatch, bad)
    with pytest.raises(ValueError, match=r"OverlapCheckIncomplete \(row bad, field design.criterion\)"):
        _create()
    _seed(monkeypatch, bad)
    assert _create(intervention_kind="observational")["overlap"]["check_status"] == "indeterminate"


def test_healthy_read_never_reports_indeterminate(monkeypatch):
    _seed(monkeypatch)
    assert _create()["overlap"] == {
        "level": "none",
        "check_status": "checked",
        "conflicts": [],
        "reason": "no active experiment shares a metric or outcome family.",
    }
    for active, expect in (
        (_active("a", "sleep_score", start="2026-10-01"), "note"),
        (_active("b", "deep_pct"), "warning"),
    ):
        r = eo.assess_overlap(_new("deep_pct"), [active])
        assert r["level"] == expect and r["check_status"] == "checked"
    table = _seed(monkeypatch, _active("a", "deep_pct"))
    resp = _create(acknowledge_overlap=REASON)
    assert _stored(table, resp)["overlap_acknowledged"]["check_status"] == "checked" and _stored(table, resp)["overlap"] == {
        "check_status": "checked"
    }
    assert "overlap_warning" not in resp


def test_closing_caveat_read_failure_is_recorded_not_implied_clean(monkeypatch):
    table = _seed(monkeypatch)
    table._query_hook = lambda t, **kw: (_ for _ in ()).throw(TimeoutError("x"))
    analysis = {"verdict": "supported", "summary": "Result."}
    eo.attach_closing_caveat(table, tl.EXPERIMENTS_PK, {"experiment_id": "z"}, analysis)
    assert analysis["overlap_caveat_check"] == "not_run: TimeoutError" and "did not run" in analysis["summary"]
    assert analysis["verdict"] == "supported" and "overlap_caveat" not in analysis


def test_closing_caveat_healthy_leaves_analysis_unchanged(monkeypatch):
    table = _seed(monkeypatch)
    analysis = {"verdict": "supported", "summary": "Result."}
    eo.attach_closing_caveat(table, tl.EXPERIMENTS_PK, {"experiment_id": "z"}, analysis)
    assert "overlap_caveat_check" not in analysis and analysis["summary"] == "Result."


# ── pagination, malformed active rows, close of an uncleared experiment ───────────────────────


class _Pages:
    """Table double returning pages; `pages` is a list of item lists, LEK set on all but the last."""

    def __init__(self, pages, fail_at=None, endless=False):
        self.pages, self.fail_at, self.endless, self.calls = pages, fail_at, endless, 0

    def query(self, **kw):
        i = self.calls
        self.calls += 1
        if self.fail_at is not None and i == self.fail_at:
            raise TimeoutError("mid-way")
        if self.endless:
            return {"Items": [], "LastEvaluatedKey": {"pk": "p", "sk": str(i)}}
        resp = {"Items": self.pages[i]}
        if i < len(self.pages) - 1:
            resp["LastEvaluatedKey"] = {"pk": "p", "sk": str(i)}
        return resp


NOW = __import__("datetime").datetime(2026, 11, 22, 12)


def _check(table, design=None, kind="behavioral", ack=None):
    return eo.check_creation(table, "pk", "2026-11-22", design or _design("deep_pct"), kind, None, [], ack, NOW)


def test_pagination_conflict_on_page_two_is_found():
    t = _Pages([[], [_active("a", "deep_pct")]])
    with pytest.raises(ValueError, match="overlap refused"):
        _check(t)
    assert t.calls == 2


def test_pagination_midway_error_is_indeterminate_not_partial_checked():
    t = _Pages([[], [_active("a", "deep_pct")]], fail_at=1)
    o, _ = _check(t, kind="observational")
    assert o["check_status"] == "indeterminate" and o["error_class"] == "TimeoutError"


def test_pagination_cap_is_indeterminate():
    t = _Pages([], endless=True)
    o, _ = _check(t, kind="observational")
    assert o["check_status"] == "indeterminate" and "pagination" in o["reason"] and t.calls == eo.MAX_PAGES


def test_pagination_complete_empty_is_checked_none():
    o, _ = _check(_Pages([[], []]))
    assert o["level"] == "none" and o["check_status"] == "checked"


@pytest.mark.parametrize(
    "mutate,field",
    [
        (lambda r: r.update(design="garbage"), "design"),
        (lambda r: r.update(design={"criterion": "x"}), "design.criterion"),
        (lambda r: r["design"].update(washout_days="abc"), "design.washout_days"),
        (lambda r: r["design"].update(washout_days=True), "design.washout_days"),
        (lambda r: r.pop("start_date"), "start_date"),
        (lambda r: r.update(start_date="not-a-date"), "start_date"),
        (lambda r: r.pop("status"), "status"),
        (lambda r: r.update(status="paused"), "status"),
    ],
)
def test_malformed_active_row_is_indeterminate_naming_row_and_field(mutate, field):
    row = _active("bad", "steps", start="2026-10-01")
    mutate(row)
    o, _ = _check(_Pages([[row]]), kind="observational")
    assert o["check_status"] == "indeterminate" and f"row bad, field {field}" in o["reason"]
    with pytest.raises(ValueError, match=f"row bad, field {field}"):
        _check(_Pages([[row]]))


def test_status_is_case_insensitive_and_only_canonical_inactive_skipped():
    done = _active("d", "deep_pct", status="Completed ")
    gone = _active("g", "deep_pct", status="ABANDONED")
    assert _check(_Pages([[done, gone]]))[0]["level"] == "none"
    live = _active("l", "deep_pct", status=" Active")
    with pytest.raises(ValueError, match="overlap refused"):
        _check(_Pages([[live]]))


def test_legacy_active_row_without_design_stays_note_at_most():
    legacy = {"experiment_id": "old", "status": "active", "tags": ["sleep"]}
    o, _ = eo.check_creation(_Pages([[legacy]]), "pk", "2026-11-22", _design("deep_pct"), "behavioral", None, ["sleep"], None, NOW)
    assert o["level"] == "note" and o["check_status"] == "checked"


def test_close_of_uncleared_experiment_carries_not_verified_caveat(monkeypatch):
    table = _broken_read(monkeypatch)
    resp = _create(acknowledge_overlap=REASON)
    table._query_hook = lambda t, **kw: {"Items": [i for i in t.store.values() if str(i.get("sk", "")).startswith("EXP#")]}
    monkeypatch.setattr(tl, "_run_design_analysis", lambda *a, **k: {"verdict": "supported", "summary": "Result."})
    out = tl.tool_end_experiment({"experiment_id": resp["experiment_id"], "outcome": "done", "end_date": "2026-12-14"})
    a = out["analysis"]
    assert a["verdict"] == "supported" and a["overlap_caveat"] == "overlap not verified at creation"
    assert a["summary"] == "Result. overlap not verified at creation."
    assert REASON not in str(a)  # the owner's words never ride the public analysis


def test_close_of_checked_and_pre_pr_rows_is_unchanged(monkeypatch):
    table = _seed(
        monkeypatch, {"experiment_id": "pre", "name": "pre", "status": "active", "start_date": "2026-11-01", "design": _design("steps")}
    )
    monkeypatch.setattr(tl, "_run_design_analysis", lambda *a, **k: {"verdict": "supported", "summary": "Result."})
    out = tl.tool_end_experiment({"experiment_id": "pre", "outcome": "done", "end_date": "2026-12-14"})
    assert out["analysis"] == {"verdict": "supported", "summary": "Result."}
    resp = _create()
    assert _stored(table, resp)["overlap"] == {"check_status": "checked"}
    out = tl.tool_end_experiment({"experiment_id": resp["experiment_id"], "outcome": "done", "end_date": "2026-12-14"})
    assert out["analysis"] == {"verdict": "supported", "summary": "Result."}
