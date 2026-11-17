"""tests/test_alarm_citation_subset_5934.py — the cause rule is live ⊆ declared, bounded by a
7-day staleness window on the declared side (#5934, tracker #6053).

`cause_mismatches` (#3501) required the declared `cause` SET to EQUAL the live qa-smoke
cause set. `qa-smoke-warnings` is a standing any-WARN alarm whose live cause line is the
union of several intermittent WARN ids, so on 2026-11-16 two consecutive runs read
`public_brief:cycle_liveness,reader_truth:verdict` then
`public_brief:cycle_liveness,weeks:absence_agreement` — no citation can equal both and the
scheduled `wrap-alarm-citations` leg was red by construction.

The matrix below is the 11-16 flip as a MUST-PASS, and each earlier incident that shaped the
gate as a MUST-FAIL control, so relaxing equality cannot quietly reopen one of them.
"""

import os
import sys
import types
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import alarm_citation_causes as acc  # noqa: E402
import check_alarm_citations as cac  # noqa: E402

WARN = "qa-smoke-warnings"
FAIL = "qa-smoke-failures"


def _lit(name, transitioned="2026-11-16T01:59:00+00:00"):
    return {"name": name, "updated": transitioned, "transitioned": transitioned, "by_construction": False}


_STANDING = {
    WARN: {
        "citation": "#5928 — `public_brief:cycle_liveness` holds; `reader_truth:verdict` intermittent; "
        "`weeks:absence_agreement` is #6113.",
        "cause": ["public_brief:cycle_liveness", "reader_truth:verdict", "weeks:absence_agreement"],
        "cause_observed": "2026-11-16",
    }
}


# ── MUST-PASS: the 2026-11-16 flip ────────────────────────────────────────────


def test_the_11_16_flip_passes_on_both_consecutive_runs():
    """MUST-PASS. Against the pre-#5934 equality rule BOTH runs are a mismatch."""
    alarms = [_lit(WARN)]
    run_a = {WARN: ["public_brief:cycle_liveness", "reader_truth:verdict"]}
    run_b = {WARN: ["public_brief:cycle_liveness", "weeks:absence_agreement"]}
    assert cac.cause_mismatches(alarms, _STANDING, run_a) == []
    assert cac.cause_mismatches(alarms, _STANDING, run_b) == []
    seen = {WARN: {"public_brief:cycle_liveness", "reader_truth:verdict", "weeks:absence_agreement"}}
    assert acc.stale_declared_causes(alarms, _STANDING, seen) == []


def test_the_11_16_flip_passes_the_whole_gate_end_to_end(monkeypatch, capsys):
    out_rc = _run_main(
        monkeypatch,
        citations=_STANDING,
        latest={WARN: ["public_brief:cycle_liveness", "weeks:absence_agreement"]},
        seen={WARN: {"public_brief:cycle_liveness", "reader_truth:verdict", "weeks:absence_agreement"}},
    )
    out = capsys.readouterr().out
    assert out_rc == 0, out


# ── MUST-FAIL controls: the incidents that shaped the gate ────────────────────


def test_3501_a_cause_that_changed_under_a_count_aggregated_alarm_still_reds():
    """09-05: cited `cross_surface:weight`, live `reader_truth:frozen_artifacts`, one episode."""
    alarms = [_lit(FAIL, "2026-09-03T18:31:55+00:00")]
    citations = {FAIL: {"citation": "#3598", "cause": "cross_surface:weight"}}
    live = {FAIL: ["reader_truth:frozen_artifacts"]}
    assert cac.cause_mismatches(alarms, citations, live) == [(FAIL, "cross_surface:weight", "reader_truth:frozen_artifacts")]


def test_a_new_id_joining_a_declared_union_reds_and_names_only_the_new_id():
    """Partial coverage is not coverage: the standing ids are explained, the newcomer is not."""
    live = {WARN: ["public_brief:cycle_liveness", "morning_checkin:weekday_liveness"]}
    assert cac.cause_mismatches([_lit(WARN)], _STANDING, live) == [
        (WARN, "public_brief:cycle_liveness,reader_truth:verdict,weeks:absence_agreement", "morning_checkin:weekday_liveness")
    ]


def test_3793_an_entry_with_no_cause_field_still_reds_through_undeclared_causes():
    """09-14: prose citation at a real-but-cured cause, no `cause` key, live channel naming another."""
    alarms = [_lit(FAIL, "2026-09-14T18:31:55+00:00")]
    citations = {FAIL: {"citation": "the labs frames, verified cured"}}
    live = {FAIL: ["cross_surface:vitals"]}
    assert cac.cause_mismatches(alarms, citations, live) == []  # nothing declared to compare...
    assert cac.undeclared_causes(alarms, citations, live) == [(FAIL, "cross_surface:vitals")]  # ...so the sibling reds


def test_a_declared_id_the_channel_has_not_named_in_the_window_reds():
    """MUST-FAIL. The accumulation guard: without it a citation could pre-declare every id."""
    citations = {WARN: dict(_STANDING[WARN], cause=_STANDING[WARN]["cause"] + ["public_brief:macrofactor_export_age"])}
    seen = {WARN: {"public_brief:cycle_liveness", "reader_truth:verdict", "weeks:absence_agreement"}}
    assert acc.stale_declared_causes([_lit(WARN)], citations, seen) == [(WARN, "public_brief:macrofactor_export_age")]


def test_a_self_clearing_run_over_a_cause_quiet_for_the_whole_window_reds():
    """The 2026-11-13 review shape, a week on: cited ids, latest run `none`, nothing seen since."""
    citations = {WARN: {"citation": "`reader_truth:confirm` `reader_truth:verdict`", "cause": "reader_truth:confirm,reader_truth:verdict"}}
    assert cac.cause_mismatches([_lit(WARN)], citations, {WARN: []}) == []
    assert acc.stale_declared_causes([_lit(WARN)], citations, {WARN: set()}) == [(WARN, "reader_truth:confirm,reader_truth:verdict")]


def test_the_stale_declaration_reds_the_whole_gate_end_to_end(monkeypatch, capsys):
    citations = {WARN: dict(_STANDING[WARN], cause=_STANDING[WARN]["cause"] + ["data:orphan_routine_drafts"])}
    rc = _run_main(
        monkeypatch,
        citations=citations,
        latest={WARN: ["public_brief:cycle_liveness"]},
        seen={WARN: {"public_brief:cycle_liveness", "reader_truth:verdict", "weeks:absence_agreement"}},
    )
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "data:orphan_routine_drafts" in out and "#5934" in out


def test_an_undeclared_live_id_reds_the_whole_gate_end_to_end(monkeypatch, capsys):
    rc = _run_main(
        monkeypatch,
        citations=_STANDING,
        latest={WARN: ["public_brief:cycle_liveness", "story_season:new_thing"]},
        seen={WARN: {"public_brief:cycle_liveness", "reader_truth:verdict", "weeks:absence_agreement", "story_season:new_thing"}},
    )
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "story_season:new_thing" in out


# ── UNKNOWN is never a red, in either direction ───────────────────────────────


def test_no_reading_for_the_alarm_is_unknown_in_both_directions():
    alarms = [_lit(WARN)]
    assert cac.cause_mismatches(alarms, _STANDING, {}) == []
    assert acc.stale_declared_causes(alarms, _STANDING, {}) == []
    assert acc.stale_declared_causes(alarms, _STANDING, None) == []


def test_a_two_tuple_reader_stub_degrades_the_stale_check_to_unknown(monkeypatch, capsys):
    """Older stubs return (latest, err); the stale leg must read that as UNKNOWN, never crash."""
    rc = _run_main(monkeypatch, citations=_STANDING, latest={WARN: ["public_brief:cycle_liveness"]}, seen=None, two_tuple=True)
    assert rc == 0, capsys.readouterr().out


def test_a_by_construction_alarm_is_exempt_from_both_directions():
    alarms = [dict(_lit(WARN), by_construction=True)]
    assert cac.cause_mismatches(alarms, _STANDING, {WARN: ["x:y"]}) == []
    assert acc.stale_declared_causes(alarms, _STANDING, {WARN: set()}) == []


# ── #3729: the read is paged by stream; latest is time-ordered, seen is a union ──


class _PagedLogs:
    def __init__(self, pages):
        self.pages = pages

    def filter_log_events(self, **kwargs):
        idx = 0 if kwargs.get("nextToken") is None else int(kwargs["nextToken"])
        events, nxt = self.pages[idx]
        out = {"events": [{"timestamp": ts, "message": m} for ts, m in events]}
        if nxt is not None:
            out["nextToken"] = str(nxt)
        return out


def test_the_read_returns_latest_from_48h_and_the_union_from_the_stale_window(monkeypatch):
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    hour = 3_600_000
    pages = [
        # Page 1 holds the NEWEST line (stream order is not time order, #3729)...
        ([(now_ms - 1 * hour, "[QA] CAUSE warn aaaa public_brief:cycle_liveness,weeks:absence_agreement")], 1),
        # ...page 2 an older in-48h run and a 5-day-old one only the stale window should see.
        (
            [
                (now_ms - 3 * hour, "[QA] CAUSE warn bbbb public_brief:cycle_liveness,reader_truth:verdict"),
                (now_ms - 120 * hour, "[QA] CAUSE warn cccc public_brief:macrofactor_export_age"),
            ],
            None,
        ),
    ]
    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=lambda *a, **k: _PagedLogs(pages)))
    latest, err, seen = cac.fetch_qa_smoke_causes()
    assert err is None
    assert latest == {WARN: ["public_brief:cycle_liveness", "weeks:absence_agreement"]}
    assert seen == {
        WARN: {"public_brief:cycle_liveness", "weeks:absence_agreement", "reader_truth:verdict", "public_brief:macrofactor_export_age"}
    }


def test_only_lines_older_than_48h_leave_the_latest_map_unknown(monkeypatch):
    """A run older than the 48h latest window must not become 'the latest run' — the
    pre-#5934 window — while still counting as a sighting for the stale window."""
    old = int(datetime.now(timezone.utc).timestamp() * 1000) - 100 * 3_600_000
    pages = [([(old, "[QA] CAUSE warn cccc reader_truth:verdict")], None)]
    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=lambda *a, **k: _PagedLogs(pages)))
    latest, err, seen = cac.fetch_qa_smoke_causes()
    assert err is None and latest == {} and seen == {WARN: {"reader_truth:verdict"}}


def test_a_failed_read_returns_no_seen_map(monkeypatch):
    class _Boom:
        def filter_log_events(self, **kwargs):
            raise RuntimeError("AccessDenied")

    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=lambda *a, **k: _Boom()))
    assert cac.fetch_qa_smoke_causes() == ({}, "AccessDenied", None)


# ── a declared id is a sentence, not a bare token ─────────────────────────────


def test_a_declared_id_the_prose_never_names_is_flagged():
    citations = {WARN: {"citation": "#5928 — standing warns", "cause": "reader_truth:verdict"}}
    assert acc.unexplained_declared_ids(citations, set(cac.QA_SMOKE_CAUSE_ALARMS.values())) == [(WARN, "reader_truth:verdict")]


def test_a_free_prose_cause_on_an_alarm_with_no_channel_is_out_of_scope():
    citations = {"ai-canary-overall": {"citation": "#1", "cause": "vendor transient, Bedrock 503"}}
    assert acc.unexplained_declared_ids(citations, set(cac.QA_SMOKE_CAUSE_ALARMS.values())) == []


def test_the_committed_registry_explains_every_declared_id():
    unexplained = acc.unexplained_declared_ids(cac.load_citations(), set(cac.QA_SMOKE_CAUSE_ALARMS.values()))
    assert not unexplained, f"declared cause ids with no sentence naming them in docs/alarm_citations.json: {unexplained}"


def test_3258_a_cause_sentence_claiming_no_recurrence_still_needs_its_derivation():
    citations = {WARN: {"citation": "`reader_truth:verdict` — fixed, no recurrence since", "cause": "reader_truth:verdict"}}
    assert cac.unfalsifiable_negatives(citations) == [(WARN, "no recurrence")]


# ── helpers ───────────────────────────────────────────────────────────────────


def _run_main(monkeypatch, *, citations, latest, seen, two_tuple=False):
    transitioned = (datetime.now(timezone.utc) - timedelta(hours=6)).replace(microsecond=0).isoformat()
    monkeypatch.setattr(cac, "fetch_alarms", lambda: ([_lit(WARN, transitioned)], None))
    monkeypatch.setattr(cac, "load_citations", lambda: citations)
    monkeypatch.setattr(cac, "load_alarm_audience", lambda: {})
    monkeypatch.setattr(cac, "fetch_alarm_history", lambda *a, **k: ([], None))
    monkeypatch.setattr(cac, "fetch_all_alarm_names", lambda *a, **k: ({WARN}, None))
    monkeypatch.setattr(cac, "fetch_issue_states", lambda refs: ({str(r): "OPEN" for r in refs}, None))
    result = (latest, None) if two_tuple else (latest, None, seen)
    monkeypatch.setattr(cac, "fetch_qa_smoke_causes", lambda *a, **k: result)
    monkeypatch.setattr(sys, "argv", ["check_alarm_citations.py"])
    return cac.main()
