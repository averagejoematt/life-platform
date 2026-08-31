"""
tests/test_coherence_sentinel.py — the Sentinel Lambda's orchestration.

The pure invariants are covered by test_coherence_invariants. Here we drive the
handler end-to-end with the data-adapters monkeypatched to a known-bad live
state (the C-3 all-inconclusive board + a 30-vs-86 narrative split) and assert
run_checks() surfaces the alarms and the digest renders — no AWS, no HTTP.
"""

import datetime as _dt
import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas", "operational"))

import coherence_sentinel_lambda as sentinel  # noqa: E402
from common import (
    constants as _constants,  # noqa: E402
    pacific_time,  # noqa: E402
)


def _pin_continuity(monkeypatch, genesis="2026-06-08", today="2026-07-01", surfaced=()):
    """Pin the SS-05 continuity gather to explicit fixture dates. The real gather
    reads the LIVE constants.EXPERIMENT_START_DATE and the wall clock (plus a real
    DDB get_item) — which made every run_checks() test silently dependent on
    "genesis <= today": a reset staging a FUTURE genesis (the sanctioned #931
    pre-start window) flipped check_experiment_continuity to ALARM and broke the
    OK-expecting tests. (#942 since bounded that: genesis ≤ PRE_START_GRACE_DAYS
    in the future → pre_start, beyond → ALARM.) Pinned mid-experiment dates keep
    each test about ITS invariant; the future-genesis boundary of the pure check
    is pinned in test_coherence_invariants.py::TestExperimentContinuity."""
    monkeypatch.setattr(sentinel, "_gather_experiment_continuity", lambda: (genesis, today, list(surfaced)))


def _pin_computed_checks(monkeypatch):
    """Drive the REAL `_gather_computed_checks` over records in LIVE shape (#2736).

    These three tests previously did `monkeypatch.setattr(sentinel,
    "_gather_computed_checks", lambda: [])` — substituting the exact broken return
    value of the function under test, which is why the suite stayed green for the
    life of the file while invariant 2 never executed a single check. The adapter
    read `score`/`grade`; the record has stored `total_score`/`letter_grade` since
    the oldest row in the partition. Only `_latest` (the DDB read) is stubbed here;
    the field names below are copied from live items, so a future rename breaks
    this test instead of silently emptying the invariant.
    """
    live = {
        "day_grade": {"sk": "DATE#2026-08-14", "date": "2026-08-14", "total_score": 39, "letter_grade": "F"},
        "character_sheet": {"sk": "DATE#2026-08-14", "date": "2026-08-14", "character_level": 1, "character_tier": "Foundation"},
    }
    monkeypatch.setattr(sentinel, "_latest", lambda source: live.get(source, {}))


def test_gather_computed_checks_reads_the_real_record_shape(monkeypatch):
    """The #2736 regression: the adapter must produce checks from a live-shaped
    record. Pre-fix this returned [] and invariant 2 reported a vacuous OK."""
    _pin_computed_checks(monkeypatch)
    checks = sentinel._gather_computed_checks()
    assert checks, "adapter found nothing to check against a live-shaped record"
    names = {c["name"] for c in checks}
    # #2793: the check name now carries the letters ("day_grade_letter_vs_score[F vs F]")
    # so an alarm reads as letters rather than ord() values.
    assert any(n.startswith("day_grade_letter_vs_score") for n in names)
    # and the invariant grades them rather than reporting an empty-set green
    f = sentinel.ci.check_computed_coherence(checks)
    assert f.status == sentinel.ci.OK
    assert "0 computed metrics" not in f.detail


def _patch_bad_state(monkeypatch):
    _pin_continuity(monkeypatch)
    # C-3 signature: many closed predictions, none decided.
    monkeypatch.setattr(
        sentinel,
        "_gather_predictions",
        lambda: [{"status": "inconclusive", "closed": True, "eval_type": "machine"} for _ in range(12)],
    )
    # 30-vs-86 recovery split across served narratives.
    monkeypatch.setattr(
        sentinel,
        "_gather_facts_and_narratives",
        lambda: (
            {"recovery_pct": 30, "hrv_ms": 25.2, "rhr_bpm": 58, "latest_weight": 300.8},
            ["Recovery sat at 30% today.", "With recovery up at 86 you're primed to push."],
            ["expert:training", "expert:nutrition"],
            {},
        ),
    )
    _pin_computed_checks(monkeypatch)
    monkeypatch.setattr(sentinel, "_gather_endpoint_specs", lambda: [])  # skip HTTP
    monkeypatch.setattr(sentinel, "_gather_counts", lambda: [])
    monkeypatch.setattr(sentinel, "_semantic_pass", lambda facts, narr: None)


def test_run_checks_surfaces_known_bugs(monkeypatch):
    _patch_bad_state(monkeypatch)
    findings, semantic = sentinel.run_checks()
    by_name = {f.name: f for f in findings}
    assert by_name["prediction_health"].is_alarm
    assert by_name["facts_agreement"].status in (sentinel.ci.WARN, sentinel.ci.ALARM)
    assert sentinel.ci.overall_status(findings) == sentinel.ci.ALARM


def test_digest_renders(monkeypatch):
    _patch_bad_state(monkeypatch)
    findings, semantic = sentinel.run_checks()
    digest = sentinel._digest(findings, semantic)
    assert "COHERENCE SENTINEL — ALARM" in digest
    assert "prediction_health" in digest


def test_facts_use_canonical_schema_closing_the_grounding_loop(monkeypatch):
    # The Sentinel grounds on the SAME canonical_facts the coaches do — so the
    # protein avg/target/floor are distinct (the 140/170/190 confusion) and HRV
    # is ms. Patch _latest to a known computed_metrics record; the narratives loop
    # fail-softs to empty (table is a stub here).
    monkeypatch.setattr(
        sentinel,
        "_latest",
        lambda src: {"recovery_pct": 30, "hrv_ms": 25.18, "protein_g_avg": 140.7, "protein_g_target": 190, "protein_g_floor": 170},
    )
    monkeypatch.setattr(sentinel, "table", None)  # narratives query → except → []
    facts, narratives, labels, overrides = sentinel._gather_facts_and_narratives()
    assert facts["protein_g_avg"] == 140.7
    assert facts["protein_g_target"] == 190 and facts["protein_g_floor"] == 170
    assert facts["hrv_ms"] == 25.2 and "as_of" not in facts  # ms, no stray non-numeric key


def test_facts_as_of_generation_queries_strictly_before_and_fail_softs(monkeypatch):
    # #2792: a coach generated on day D was grounded on the newest computed_metrics
    # BEFORE D (the compute writes completed days). The query bound must be strict.
    captured = {}

    class _T:
        def query(self, **kw):
            captured.update(kw)
            return {"Items": [{"recovery_pct": 40, "hrv_ms": 35.32, "rhr_bpm": 62}]}

    monkeypatch.setattr(sentinel, "table", _T())
    facts = sentinel._facts_as_of_generation("2026-08-15")
    assert facts["recovery_pct"] == 40
    expr = captured["KeyConditionExpression"].get_expression()
    lt = [v for v in expr["values"] if v.get_expression()["operator"] == "<"]
    assert lt and lt[0].get_expression()["values"][1] == "DATE#2026-08-15"

    class _Boom:
        def query(self, **kw):
            raise RuntimeError("ddb down")

    # Fail-soft: {} means the caller falls back to today's facts — the check can only
    # get STRICTER on a lookup failure, never blind.
    monkeypatch.setattr(sentinel, "table", _Boom())
    assert sentinel._facts_as_of_generation("2026-08-15") == {}


def test_gather_marks_stale_served_coach_rows_with_own_day_facts(monkeypatch):
    # #2792 live shape: today's generation HELD (ADR-108) for every V2 coach, so each
    # coach's latest OUTPUT# row is yesterday's. The gather must attach an own-day
    # facts override for those labels, and the checker must then read the honest
    # citation of yesterday's canonical as grounded-but-stale, not a contradiction.
    monkeypatch.setattr(sentinel, "_latest", lambda src: {"recovery_pct": 57, "hrv_ms": 39.76, "rhr_bpm": 61})
    # #2814: "yesterday" in the SENTINEL'S frame — Pacific. The UTC form this
    # replaced made the fixture disagree with the gather every PT evening
    # (17:00–24:00 PT), exactly the window the sentinel bug lived in.
    yesterday = (pacific_time.pacific_now() - _dt.timedelta(days=1)).strftime("%Y-%m-%d")

    class _T:
        def get_item(self, Key):
            return {}  # no EXPERT# rows in this fixture

        def query(self, **kw):
            return {"Items": [{"sk": f"OUTPUT#{yesterday}#daily_brief_x", "content": "Recovery at 40% this morning."}]}

    monkeypatch.setattr(sentinel, "table", _T())
    monkeypatch.setattr(sentinel, "_facts_as_of_generation", lambda d: {"recovery_pct": 40, "hrv_ms": 35.3, "rhr_bpm": 62})
    facts, narratives, labels, overrides = sentinel._gather_facts_and_narratives()
    coach_labels = [x for x in labels if x.startswith("coach:")]
    assert coach_labels, "fixture produced no coach narratives"
    assert all(x in overrides for x in coach_labels)
    ov = overrides[coach_labels[0]]
    assert ov["as_of"] == yesterday and ov["facts"]["recovery_pct"] == 40
    f = sentinel.ci.check_facts_agreement(narratives, facts, surfaces=labels, facts_overrides=overrides)
    assert f.status == sentinel.ci.OK
    assert "served stale" in f.detail


def test_gather_marks_stale_served_expert_rows_with_own_day_facts(monkeypatch):
    # #3366: the experts regenerate WEEKLY (Monday 14:00 UTC — the CDK rule is the
    # enforcing mechanism), so a served essay is up to ~7 days old BY DESIGN. The
    # gather must attach an own-day facts override for expert labels the same way
    # #2792 does for held coach rows — otherwise a Monday essay honestly citing
    # Monday's canonical recovery reads as a contradiction of Friday's facts.
    monkeypatch.setattr(sentinel, "_latest", lambda src: {"recovery_pct": 57, "hrv_ms": 39.76, "rhr_bpm": 61})
    # The essay's own generation day, mid-week in the PT frame (4 days back covers
    # every weekday the daily sentinel can observe a Monday-written essay on).
    monday = (pacific_time.pacific_now() - _dt.timedelta(days=4)).strftime("%Y-%m-%d")

    class _T:
        def get_item(self, Key):
            if Key.get("sk") == "EXPERT#integrator":
                return {"Item": {"generated_at": f"{monday}T14:03:00+00:00", "analysis": "Recovery at 40% this week."}}
            return {}  # the other EXPERT# rows absent in this fixture

        def query(self, **kw):
            return {"Items": []}  # no V2 coach rows in this fixture

    monkeypatch.setattr(sentinel, "table", _T())
    monkeypatch.setattr(sentinel, "_facts_as_of_generation", lambda d: {"recovery_pct": 40, "hrv_ms": 35.3, "rhr_bpm": 62})
    facts, narratives, labels, overrides = sentinel._gather_facts_and_narratives()
    assert labels == ["expert:integrator"], "fixture produced the wrong narrative set"
    assert "expert:integrator" in overrides
    ov = overrides["expert:integrator"]
    assert ov["as_of"] == monday and ov["facts"]["recovery_pct"] == 40
    f = sentinel.ci.check_facts_agreement(narratives, facts, surfaces=labels, facts_overrides=overrides)
    assert f.status == sentinel.ci.OK
    assert "served stale" in f.detail


def test_build_record_is_serializable_and_complete(monkeypatch):
    _patch_bad_state(monkeypatch)
    findings, semantic = sentinel.run_checks()
    digest = sentinel._digest(findings, semantic)
    worst = sentinel.ci.overall_status(findings)
    record = sentinel.build_record(findings, semantic, digest, worst)
    # The agent reads these keys to triage; they must all be present + JSON-safe.
    assert set(record) >= {"date", "status", "alarms", "findings", "digest"}
    assert "prediction_health" in record["alarms"]
    assert json.loads(json.dumps(record, default=str))  # round-trips


def test_semantic_incoherence_is_advisory_not_alarm_driving():
    # The Haiku semantic read is too noisy to drive a daily-emailing alarm (it lists
    # confirmations as "issues"). So a semantic-only flag with all deterministic
    # invariants green stays status=ok (the alarm won't fire), but semantic_incoherent
    # is recorded as advisory context for a human/agent to weigh.
    ok = [sentinel.ci.Finding("prediction_health", sentinel.ci.OK, 0.0, "fine")]
    semantic = {"coherent": False, "issues": ["borderline HRV variance"]}
    record = sentinel.build_record(ok, semantic, "digest", sentinel.ci.OK)
    assert record["status"] == sentinel.ci.OK  # deterministic drives the alarm
    assert record["deterministic_status"] == sentinel.ci.OK
    assert record["semantic_incoherent"] is True  # but the advisory flag is preserved


def test_deterministic_alarm_still_drives_status():
    bad = [sentinel.ci.Finding("facts_agreement", sentinel.ci.ALARM, 2.0, "two contradictions")]
    record = sentinel.build_record(bad, {"coherent": True, "issues": []}, "d", sentinel.ci.ALARM)
    assert record["status"] == sentinel.ci.ALARM


def test_persist_writes_latest_and_dated_and_is_fail_soft(monkeypatch):
    puts = []
    monkeypatch.setattr(sentinel._s3, "put_object", lambda **kw: puts.append(kw["Key"]))
    record = {"date": "2026-06-28", "status": "alarm", "alarms": ["prediction_health"], "findings": [], "digest": "x"}
    sentinel._persist(record)
    assert "coherence-log/latest.json" in puts
    assert "coherence-log/2026-06-28.json" in puts

    # A persist failure must NOT propagate — detection already emitted metrics.
    def _boom(**kw):
        raise RuntimeError("s3 down")

    monkeypatch.setattr(sentinel._s3, "put_object", _boom)
    sentinel._persist(record)  # no raise


def _patch_empty_post_reset_board(monkeypatch, age_days):
    """A freshly-reset cycle (ADR-077): every cycle-scoped surface is legitimately
    empty. All the endpoint specs' required keys are present-but-empty containers
    (never None), so only the non_degenerate gate is in play."""
    monkeypatch.setattr(sentinel, "_gather_predictions", lambda: [])
    monkeypatch.setattr(sentinel, "_gather_facts_and_narratives", lambda: ({}, [], [], {}))
    _pin_computed_checks(monkeypatch)
    monkeypatch.setattr(sentinel, "_gather_counts", lambda: [])
    monkeypatch.setattr(sentinel, "_semantic_pass", lambda facts, narr: None)
    monkeypatch.setattr(sentinel, "_experiment_age_days", lambda: age_days)
    # freshly-reset cycle: genesis just passed, nothing surfaced to readers yet;
    # today derives from the pinned genesis + the test's age, never the wall clock
    _today = (_dt.date.fromisoformat("2026-06-08") + _dt.timedelta(days=age_days)).isoformat()
    _pin_continuity(monkeypatch, genesis="2026-06-08", today=_today, surfaced=())
    empty_payload = {
        "overall": {"total": 0},
        "predictions": [],
        "nutrition": {},
        "coaches": [],
        "vitals": {},
    }
    monkeypatch.setattr(sentinel, "_get_json", lambda path: empty_payload)


def test_post_reset_empty_board_reports_ok(monkeypatch):
    # BUG-05 / #379 — replay: a reset just happened (age=1 day), every public
    # endpoint is a legitimately empty shell. The sentinel must NOT alarm.
    _patch_empty_post_reset_board(monkeypatch, age_days=1)
    findings, _ = sentinel.run_checks()
    shape_findings = [f for f in findings if f.name.startswith("endpoint_shape:")]
    assert shape_findings, "expected the default endpoint specs to run"
    assert all(f.status == sentinel.ci.OK for f in shape_findings)
    assert sentinel.ci.overall_status(findings) == sentinel.ci.OK


def test_same_empty_board_alarms_once_past_the_grace_window(monkeypatch):
    # Identical degenerate payloads, but well past the reset (age=30 days) — this
    # is the genuine handle_predictions signature and must still alarm exactly
    # as before the gate was added.
    _patch_empty_post_reset_board(monkeypatch, age_days=30)
    findings, _ = sentinel.run_checks()
    shape_findings = [f for f in findings if f.name.startswith("endpoint_shape:")]
    assert any(f.is_alarm for f in shape_findings)
    assert sentinel.ci.overall_status(findings) == sentinel.ci.ALARM


def test_healthy_state_is_ok(monkeypatch):
    _pin_continuity(monkeypatch, surfaced=[{"name": "experiment_arc_week_count", "week": 4}])
    monkeypatch.setattr(
        sentinel,
        "_gather_predictions",
        lambda: [{"status": "confirmed", "closed": True, "eval_type": "directional"} for _ in range(6)]
        + [{"status": "pending", "closed": False, "eval_type": "directional"} for _ in range(10)],
    )
    monkeypatch.setattr(
        sentinel,
        "_gather_facts_and_narratives",
        lambda: ({"recovery_pct": 30, "hrv_ms": 25.2}, ["Recovery was 30% today; HRV 25 ms."], ["expert:sleep"], {}),
    )
    _pin_computed_checks(monkeypatch)
    monkeypatch.setattr(sentinel, "_gather_endpoint_specs", lambda: [])
    monkeypatch.setattr(sentinel, "_gather_counts", lambda: [])
    monkeypatch.setattr(sentinel, "_semantic_pass", lambda facts, narr: None)
    findings, _ = sentinel.run_checks()
    assert sentinel.ci.overall_status(findings) == sentinel.ci.OK


# ── #2814: the sentinel's own day frame is Pacific, in EVERY invocation context ──
#
# The only schedule is cron(45 18 ? * * *) = 10:45/11:45 AM PT — inside the window
# where the UTC and Pacific calendars agree — so every SCHEDULED run computed the
# right frame by accident. Any off-schedule invoke between 17:00 PDT and midnight
# PT (manual verification invokes are real: 08-15 14:52 PT; diagnostics are
# routine) anchored the surface-agreement instrument on TOMORROW's date — the
# #2675 class (a UTC clock inside a PT instrument). One frozen instant is the
# wire for every test below: 2026-08-17T02:30Z == 19:30 PDT **2026-08-16**. The
# sentinel must read it as 08-16 everywhere it names or counts a day.

_EVENING_UTC = _dt.datetime(2026, 8, 17, 2, 30, tzinfo=_dt.timezone.utc)  # 19:30 PDT 2026-08-16


class _FrozenDatetime(_dt.datetime):
    """`datetime` frozen at _EVENING_UTC. Patching this over sentinel.datetime
    controls the UTC path the UNFIXED code read — these tests were watched
    failing (returning 2026-08-17) against the pre-#2814 sentinel."""

    @classmethod
    def now(cls, tz=None):
        return _EVENING_UTC.astimezone(tz) if tz is not None else _EVENING_UTC.replace(tzinfo=None)


def _freeze_evening_clock(monkeypatch):
    """ONE instant, both frames: the sentinel's own datetime AND the canonical
    Pacific helper derive from the same frozen wire time."""
    monkeypatch.setattr(sentinel, "datetime", _FrozenDatetime)
    monkeypatch.setattr(pacific_time, "pacific_now", lambda: _EVENING_UTC.astimezone(pacific_time.PACIFIC))


def test_today_is_the_pacific_day_at_pt_evening(monkeypatch):
    # Unfixed: datetime.now(timezone.utc) → "2026-08-17" (tomorrow's frame).
    _freeze_evening_clock(monkeypatch)
    assert sentinel._today() == "2026-08-16"


def test_fresh_floor_and_stale_marking_use_the_pacific_frame(monkeypatch):
    """A coach OUTPUT# row dated the CURRENT Pacific day, read at 19:30 PT: it is
    today's row. The unfixed gather called the UTC tomorrow "today", so the row
    tripped the #2792 stale-served branch and was judged against override facts
    it should never have been given."""
    _freeze_evening_clock(monkeypatch)
    monkeypatch.setattr(sentinel, "_latest", lambda src: {"recovery_pct": 57, "hrv_ms": 39.76, "rhr_bpm": 61})

    class _T:
        def get_item(self, Key):
            return {}  # no EXPERT# rows in this fixture

        def query(self, **kw):
            return {"Items": [{"sk": "OUTPUT#2026-08-16#daily_brief_x", "content": "Recovery at 57% this evening."}]}

    monkeypatch.setattr(sentinel, "table", _T())
    calls = []
    monkeypatch.setattr(sentinel, "_facts_as_of_generation", lambda d: calls.append(d) or {})
    facts, narratives, labels, overrides = sentinel._gather_facts_and_narratives()
    assert any(x.startswith("coach:") for x in labels), "today's row fell below the fresh floor — wrong day frame"
    assert overrides == {}, f"today's row was marked stale-served (frame is a day ahead): {overrides}"
    assert not calls, "own-day facts were looked up for a same-day row"


def test_experiment_age_counts_pacific_days(monkeypatch):
    # Genesis 7 calendar days before the UTC date of the frozen instant, but 6
    # before its PACIFIC day. The post-reset grace window must count PT days —
    # the UTC count ages a fresh cycle a day early every PT evening.
    _freeze_evening_clock(monkeypatch)
    monkeypatch.setattr(_constants, "EXPERIMENT_START_DATE", "2026-08-10")
    assert sentinel._experiment_age_days() == 6


def test_quiet_source_staleness_counts_pacific_days(monkeypatch):
    # days-silent for a behavioural source is (PT today − last DATE#); the UTC
    # frame inflates it by one every PT evening. 2026-06-01 → 08-16 = 76 days
    # (far past every registry threshold, so the entry is always emitted and the
    # assertion is purely about the frame, not the cutoff).
    _freeze_evening_clock(monkeypatch)
    from ingestion.source_registry import behavioral_source_keys

    key = sorted(behavioral_source_keys())[0]  # any real behavioural source
    monkeypatch.setattr(sentinel, "_latest", lambda src: {"sk": "DATE#2026-06-01"})
    out = sentinel._quiet_behavioral_sources([key])
    assert out and out[0]["last_date"] == "2026-06-01"
    assert out[0]["days"] == 76, f"staleness counted in the wrong frame: {out[0]['days']}"
