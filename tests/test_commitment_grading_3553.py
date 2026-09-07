"""tests/test_commitment_grading_3553.py — #3553: the follow-through ledger must produce
verdicts, must say so when it cannot, and must have a reader that fails when it stops.

THE DEFECT (measured live 2026-09-06, boto3 census over the seven COACH# partitions)
  503 COMMITMENT# records · 58 with a deterministic check · 52 past their due date ·
  **0 kept / 0 broken for the instrument's entire life**, cycles 5 through 17. The
  platform publishes a commitment ledger. It had never scored a commitment.

  The grading bugs were an afternoon's work. The reason they lasted four months is the
  thing this file mostly guards: NOTHING READ THE GRADER. `coach-prediction-evaluator`
  logged `Commitment stats: kept=0 broken=0 unresolved=0 pending=N` on every run for 21
  consecutive days and no alarm, no test and no page ever looked at the line.

WHAT IS PINNED, and how each one is proved able to fail
  1. The dead-man (`commitments-ungraded`). Proved by DRIVING THE REAL EVALUATOR against
     a table that has due, checkable commitments and no metric data, capturing the
     metrics it actually emits, and asserting the alarm predicate BREACHES on them —
     then the mirror run with data, where a verdict comes out and the predicate clears.
     A guard that cannot be made to fail is not a guard; this one is made to fail here.
  2. The alarm and the predicate mean the same thing. The CloudWatch expression is
     evaluated against the same truth table as `deadman_breached()`, so a future edit to
     either side reds rather than quietly diverging.
  3. The write-time absence rule (ADR-104), against a DARK-SOURCE fixture.
  4. The reset contract: a 14-day commitment born 10 days before a reset — tombstoned,
     `phase=pilot`, exactly the shape that made all 58 live records unreachable —
     reaches a verdict.
  5. The public tally: a rate with its n and its Wilson interval, an unmeasured rate
     served as None rather than a comforting 0%, and the ungradeable set NAMED rather
     than dropped from the denominator.
"""

import json
import os
import sys
from datetime import datetime, timedelta

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import pytest  # noqa: E402
from coach import commitment_grading as cg  # noqa: E402

TODAY = "2026-09-06"


def _days_before(n):
    return (datetime.strptime(TODAY, "%Y-%m-%d") - timedelta(days=n)).strftime("%Y-%m-%d")


# ══════════════════════════════════════════════════════════════════════════════
# A. The dead-man, demonstrated FAILING on the real evaluator path
# ══════════════════════════════════════════════════════════════════════════════


class _FakeCw:
    def __init__(self):
        self.calls = []

    def put_metric_data(self, **kw):
        self.calls.append(kw)

    def value(self, name, outcome=None):
        for call in self.calls:
            for m in call.get("MetricData", []):
                if m["MetricName"] != name:
                    continue
                dims = {d["Name"]: d["Value"] for d in m.get("Dimensions", [])}
                if outcome is None and dims:
                    continue
                if outcome is not None and dims.get("Outcome") != outcome:
                    continue
                return m["Value"]
        return None


class _FakeTable:
    """The minimum DDB surface the grading pass touches: one COMMITMENT# partition per
    coach, one DATE#-keyed metric partition, and update_item writes we can read back."""

    def __init__(self, commitments=None, metric_rows=None):
        self.commitments = commitments or []
        self.metric_rows = metric_rows or []
        self.updates = {}
        self.store = {}

    def query(self, **kw):
        pk = kw["ExpressionAttributeValues"][":pk"]
        if pk.startswith("COACH#"):
            return {"Items": [c for c in self.commitments if c["pk"] == pk]}
        lo = kw["ExpressionAttributeValues"].get(":s", "")
        hi = kw["ExpressionAttributeValues"].get(":e", "")
        return {"Items": [r for r in self.metric_rows if r["pk"] == pk and lo <= r["sk"] <= hi]}

    def update_item(self, **kw):
        self.updates[kw["Key"]["sk"]] = kw["ExpressionAttributeValues"]

    def get_item(self, **kw):
        return {"Item": self.store[tuple(kw["Key"].values())]} if tuple(kw["Key"].values()) in self.store else {}

    def put_item(self, **kw):
        self.store[(kw["Item"]["pk"], kw["Item"]["sk"])] = kw["Item"]


def _commitment(cid="c1", *, created=None, window=7, metric="hrv", direction="up", coach="physical_coach", **extra):
    rec = {
        "pk": f"COACH#{coach}",
        "sk": f"COMMITMENT#{cid}",
        "commitment_id": cid,
        "coach_id": coach,
        "created_date": created or _days_before(30),
        "window_days": window,
        "status": "pending",
        "action_check": ({"metric": metric, "direction": direction} if metric else None),
    }
    rec.update(extra)
    return rec


def _rising_whoop(end_date, n=20):
    """`n` daily hrv readings ending on `end_date`, rising well past the noise band."""
    end = datetime.strptime(end_date, "%Y-%m-%d")
    return [
        {
            "pk": "USER#matthew#SOURCE#whoop",
            "sk": "DATE#" + (end - timedelta(days=n - 1 - i)).strftime("%Y-%m-%d"),
            "hrv": 40.0 + i * 2.0,
        }
        for i in range(n)
    ]


@pytest.fixture
def ev(monkeypatch):
    """The REAL evaluator module with its table + CloudWatch handles swapped."""
    from coach import coach_prediction_evaluator as _ev

    return _ev


def _run(ev, monkeypatch, table, cw):
    monkeypatch.setattr(ev, "table", table)
    monkeypatch.setattr(ev, "_cw", cw)
    pending, _corpus = ev._fetch_commitments()
    stats = ev._evaluate_commitments(pending, TODAY, {})
    cg.emit_liveness(cw, stats, ev.logger)
    return stats


class TestTheDeadManFails:
    def test_the_dead_man_BREACHES_when_the_grader_returns_no_verdict(self, ev, monkeypatch):
        """THE DEMONSTRATION. Two due, checkable commitments; no metric data anywhere —
        the live 2026-09-06 shape, where 37 of 58 checkable records bound to a source
        dark since 2026-06-24. The grader returns nothing, and the alarm's own predicate
        says so off the metrics the evaluator actually emitted."""
        table = _FakeTable(commitments=[_commitment("c1"), _commitment("c2", coach="sleep_coach")])
        cw = _FakeCw()
        stats = _run(ev, monkeypatch, table, cw)

        assert stats["graded"] == 0 and stats["due_checkable"] == 2
        assert cw.value(cg.DEADMAN_METRIC_DUE) == 2.0
        assert cw.value(cg.DEADMAN_METRIC_GRADED) == 0.0
        assert cg.deadman_breached(cw.value(cg.DEADMAN_METRIC_DUE), cw.value(cg.DEADMAN_METRIC_GRADED)) is True

    def test_the_dead_man_CLEARS_the_moment_a_real_verdict_comes_out(self, ev, monkeypatch):
        """The mirror. Same corpus, but the metric was actually observed inside the
        commitment's own window — a verdict comes out and the alarm is quiet. Without
        this half the test above would pass on a predicate hard-wired to True."""
        due = _days_before(23)  # created 30d ago, 7-day window
        table = _FakeTable(commitments=[_commitment("c1")], metric_rows=_rising_whoop(due))
        cw = _FakeCw()
        stats = _run(ev, monkeypatch, table, cw)

        assert stats["kept"] == 1 and stats["graded"] == 1
        assert cw.value(cg.DEADMAN_METRIC_GRADED, outcome="kept") == 1.0
        assert cg.deadman_breached(cw.value(cg.DEADMAN_METRIC_DUE), cw.value(cg.DEADMAN_METRIC_GRADED)) is False

    def test_a_quiet_ledger_with_nothing_due_is_not_a_breach(self, ev, monkeypatch):
        """`graded == 0` alone must not fire — the ledger is allowed a quiet fortnight.
        It is the CONJUNCTION with due>0 that means the grader is dark."""
        table = _FakeTable(commitments=[_commitment("c1", created=_days_before(2))])
        cw = _FakeCw()
        stats = _run(ev, monkeypatch, table, cw)
        assert (stats["due_checkable"], stats["graded"]) == (0, 0)
        assert cg.deadman_breached(0, 0) is False

    def test_the_metrics_are_emitted_on_a_totally_empty_run(self, ev, monkeypatch):
        """An alarm with no daily datapoint cannot tell healthy from dead. Both gauges
        must be present even when there is nothing at all to say."""
        cw = _FakeCw()
        cg.emit_liveness(cw, {}, ev.logger)
        assert cw.value(cg.DEADMAN_METRIC_DUE) == 0.0 and cw.value(cg.DEADMAN_METRIC_GRADED) == 0.0

    def test_a_FAILED_pass_emits_nothing_so_the_missing_data_breach_can_hear_it(self, ev, monkeypatch):
        """The subtle half. This lane is fail-soft, so a crash raises nothing a Lambda
        Errors alarm would see. Emitting a comforting due=0 would read as "nothing was
        due" — absence rendered as health, the same class of lie #3553 is about. The
        handler stays silent, and `treat_missing_data=BREACHING` turns that silence into
        the breach."""
        cw = _FakeCw()
        monkeypatch.setattr(ev, "table", _FakeTable())
        monkeypatch.setattr(ev, "_cw", cw)
        monkeypatch.setattr(ev, "_fetch_commitments", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        monkeypatch.setattr(ev, "_fetch_predictions", lambda: ([], []))
        monkeypatch.setattr(ev, "_detect_stance_events", lambda *a, **k: {})
        out = ev.lambda_handler({}, None)
        assert out["statusCode"] == 200 and out["commitment_stats"] == {}
        assert cw.value(cg.DEADMAN_METRIC_DUE) is None and cw.value(cg.DEADMAN_METRIC_GRADED) is None

    def test_a_cloudwatch_outage_never_sinks_the_grading_pass(self, ev):
        class _Broken:
            def put_metric_data(self, **kw):
                raise RuntimeError("cloudwatch down")

        assert cg.emit_liveness(_Broken(), {"due_checkable": 3, "graded": 0}, ev.logger)["due_checkable"] == 3


class TestTheAlarmAndThePredicateAgree:
    """The CDK expression and `deadman_breached()` are the same rule stated twice — in
    CloudWatch metric-math and in Python. Drive both against one table so an edit to
    either side reds instead of quietly meaning something new."""

    TRUTH = [(0, 0, False), (0, 5, False), (3, 0, True), (3, 1, False), (1, 0, True), (52, 0, True)]

    def _eval_expression(self, due, graded):
        """A literal reading of DEADMAN_EXPRESSION — deliberately parsed, not
        re-implemented, so a changed expression string cannot pass by accident."""
        expr = cg.DEADMAN_EXPRESSION
        assert expr == "IF(due > 0 AND graded < 1, 1, 0)", f"expression changed to {expr!r} — re-derive this reader"
        return 1 if (due > 0 and graded < 1) else 0

    @pytest.mark.parametrize("due,graded,expected", TRUTH)
    def test_python_and_cloudwatch_return_the_same_verdict(self, due, graded, expected):
        assert cg.deadman_breached(due, graded) is expected
        assert (self._eval_expression(due, graded) >= 1) is expected

    def test_the_cdk_alarm_is_built_from_these_constants_not_from_literals(self):
        """Static read of the stack module — no CDK install needed. The alarm must
        reference the module's constants; a hand-typed copy is how the two halves of a
        dead-man drift apart."""
        src = open(os.path.join(_REPO, "cdk", "stacks", "monitoring_prediction_alarms.py")).read()
        # The NAME is a literal there (alarm_discovery.py resolves names statically and
        # cannot see an attribute), so the lockstep is asserted here instead.
        assert cg.DEADMAN_ALARM_NAME == "commitments-ungraded"
        assert f'alarm_name="{cg.DEADMAN_ALARM_NAME}"' in src
        assert "commitment_grading.DEADMAN_EXPRESSION" in src
        assert "commitment_grading.DEADMAN_DAYS" in src
        assert "commitment_grading.DEADMAN_METRIC_DUE" in src and "commitment_grading.DEADMAN_METRIC_GRADED" in src
        # BREACHING is load-bearing: an evaluator that stops running emits nothing, and
        # a NOT_BREACHING dead-man would go quiet exactly when it is needed.
        assert "TreatMissingData.BREACHING" in src.split("def add_commitment_alarms")[1]


# ══════════════════════════════════════════════════════════════════════════════
# B. The write-time absence rule (ADR-104) — a dark-source fixture
# ══════════════════════════════════════════════════════════════════════════════


class TestBornUngradeable:
    def _write(self, monkeypatch, *, alive, commitments):
        import coach_state_updater as su

        written = []
        monkeypatch.setattr(su, "_put_item", lambda item: written.append(item) or True)
        monkeypatch.setattr(su, "_metric_has_recent_data", lambda metric, cache: alive)
        created, checkable = su._create_commitment_records("nutrition_coach", "2026-09-06", commitments)
        return written, created, checkable

    _PROTEIN = [
        {
            "commitment_natural": "Hit the 190g daily protein target every day this week.",
            "action_check": "total_protein_g",
            "direction": "up",
            "timeframe_hint": "this week",
        }
    ]

    def test_a_dark_source_makes_the_record_born_ungradeable_not_pending(self, monkeypatch):
        """The live case: 37 of the 58 checkable commitments bind to total_protein_g,
        whose source has recorded nothing since 2026-06-24. `pending` promised a verdict
        that could never arrive."""
        written, created, checkable = self._write(monkeypatch, alive=False, commitments=self._PROTEIN)
        assert (created, checkable) == (1, 0)
        rec = written[0]
        assert rec["status"] == cg.STATUS_UNGRADEABLE
        assert rec["outcome"] == cg.STATUS_UNGRADEABLE and rec["outcome_date"] == "2026-09-06"
        assert "macrofactor" in rec["outcome_notes"] and "dark" in rec["outcome_notes"]

    def test_the_check_is_KEPT_on_the_record_not_erased(self, monkeypatch):
        """Do not fix it by hiding it: the reader must still see WHAT it would have been
        graded on, flagged not gradeable."""
        written, _, _ = self._write(monkeypatch, alive=False, commitments=self._PROTEIN)
        assert written[0]["action_check"] == {"metric": "total_protein_g", "direction": "up", "gradeable": False}

    def test_a_live_source_is_still_born_pending_and_checkable(self, monkeypatch):
        written, created, checkable = self._write(monkeypatch, alive=True, commitments=self._PROTEIN)
        assert (created, checkable) == (1, 1)
        assert written[0]["status"] == cg.STATUS_PENDING and written[0]["outcome_notes"] is None
        assert written[0]["action_check"] == {"metric": "total_protein_g", "direction": "up"}

    def test_a_paused_source_is_refused_with_the_registrys_own_sentence(self):
        """The reason comes from `source_registry.availability_facet`, never reworded
        here — #3516's rule that a paused source's absence is a hole in the record."""
        from ingestion import source_registry as sr

        reason = cg.birth_block_reason("steps", "garmin", sr.availability_facet("garmin"), True, lookback_days=30, min_points=5)
        assert reason and "paused" in reason and "hole in the record" in reason

    def test_an_unmapped_metric_can_never_be_gradeable(self):
        assert "no source" in (cg.birth_block_reason("vibes", None, {}, True, lookback_days=30, min_points=5) or "")

    def test_a_live_mapped_observed_metric_is_not_blocked(self):
        from ingestion import source_registry as sr

        assert cg.birth_block_reason("hrv", "whoop", sr.availability_facet("whoop"), True, lookback_days=30, min_points=5) is None


# ══════════════════════════════════════════════════════════════════════════════
# C. The reset contract — a commitment whose window outlives its phase
# ══════════════════════════════════════════════════════════════════════════════


class TestSurvivesAReset:
    def test_a_14_day_commitment_born_10_days_before_a_reset_still_reaches_a_verdict(self, ev, monkeypatch):
        """#3553 acceptance box 3, in the exact shape the live corpus is in: tombstoned
        by a restart, `phase=pilot`, its window closed on the far side of the reset.
        Every one of the 58 checkable records looked like this, and the phase-filtered
        fetch meant not one of them was ever seen."""
        created = _days_before(24)  # 14-day window closed 10 days ago
        due = _days_before(10)
        rec = _commitment(
            "c_reset",
            created=created,
            window=14,
            phase="pilot",
            tombstone=True,
            tombstoned_reason="experiment_restart_2026-09-06",
        )
        table = _FakeTable(commitments=[rec], metric_rows=_rising_whoop(due))
        cw = _FakeCw()
        stats = _run(ev, monkeypatch, table, cw)
        assert stats["kept"] == 1, "a tombstoned commitment must still be graded on its own window"
        assert table.updates["COMMITMENT#c_reset"][":status"] == cg.STATUS_KEPT

    def test_the_fetch_asks_for_the_whole_corpus_not_the_current_phase(self, ev, monkeypatch):
        seen = []

        class _Spy(_FakeTable):
            def query(self, **kw):
                seen.append(kw)
                return super().query(**kw)

        monkeypatch.setattr(ev, "table", _Spy())
        monkeypatch.setattr(ev, "_cw", _FakeCw())
        ev._fetch_commitments()
        assert seen and not any("FilterExpression" in kw for kw in seen)


# ══════════════════════════════════════════════════════════════════════════════
# D. The verdicts themselves — kept means kept, broken means broken
# ══════════════════════════════════════════════════════════════════════════════


class TestVerdicts:
    def _grade(self, ev, monkeypatch, rows, **kw):
        table = _FakeTable(commitments=[_commitment("c1", **kw)], metric_rows=rows)
        stats = _run(ev, monkeypatch, table, _FakeCw())
        return stats, table

    def test_a_metric_that_moved_the_committed_way_reads_kept(self, ev, monkeypatch):
        stats, table = self._grade(ev, monkeypatch, _rising_whoop(_days_before(23)))
        assert stats["kept"] == 1
        assert table.updates["COMMITMENT#c1"][":outcome"] == "kept"

    def test_a_metric_that_moved_the_other_way_reads_broken(self, ev, monkeypatch):
        rows = _rising_whoop(_days_before(23))
        for i, r in enumerate(rows):
            r["hrv"] = 80.0 - i * 2.0
        stats, _ = self._grade(ev, monkeypatch, rows)
        assert stats["broken"] == 1

    def test_an_unobservable_metric_reads_ungradeable_with_its_n_and_the_floor(self, ev, monkeypatch):
        stats, table = self._grade(ev, monkeypatch, [])
        assert stats["ungradeable"] == 1 and stats["unresolved"] == 0
        reason = json.loads(table.updates["COMMITMENT#c1"][":notes"])["reason"]
        assert "0 observation(s)" in reason and "floor is 9" in reason
        assert "Not a verdict on follow-through" in reason

    def test_the_grace_period_still_runs_before_ungradeable_is_terminal(self, ev, monkeypatch):
        """Inside 2x the window a late reading can still decide it — the same grace the
        prediction path gives (#2221). Terminalising on day one would be its own lie."""
        stats, table = self._grade(ev, monkeypatch, [], created=_days_before(10))
        assert stats["pending"] == 1 and stats["ungradeable"] == 0
        assert table.updates == {}

    def test_a_metric_less_commitment_still_expires_to_unresolved(self, ev, monkeypatch):
        """`unresolved` is a LAPSE (a human could have closed it); `ungradeable` is an
        absence of evidence. #3553 keeps them distinct."""
        stats, _ = self._grade(ev, monkeypatch, [], metric=None)
        assert stats["unresolved"] == 1 and stats["ungradeable"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# E. The public tally — every number with its n (ADR-105)
# ══════════════════════════════════════════════════════════════════════════════


def _row(status, metric="total_protein_g"):
    return {"status": status, "action_check": ({"metric": metric, "direction": "up"} if metric else None)}


class TestPublicTally:
    def test_the_rate_carries_its_n_and_its_wilson_interval(self):
        out = cg.tally([_row("kept")] * 5 + [_row("broken")] * 9)
        assert (out["kept"], out["broken"], out["graded"]) == (5, 9, 14)
        assert out["follow_through_pct"] == 35.7
        lo, hi = out["follow_through_ci95"]
        assert lo < 35.7 < hi and 0 <= lo and hi <= 100
        assert hi - lo > 20, "a 14-sample rate must not be served as if it were precise"

    def test_an_ungraded_ledger_serves_None_not_a_comforting_zero(self):
        """The exact shape #3553 was filed for: 480 records and no verdicts must not
        render as '0% follow-through'. Unmeasured is not zero (ADR-104)."""
        out = cg.tally([_row("pending")] * 400 + [_row("ungradeable")] * 80)
        assert out["follow_through_pct"] is None and out["follow_through_ci95"] is None
        assert out["graded"] == 0 and out["ungradeable"] == 80

    def test_the_ungradeable_set_is_named_not_dropped(self):
        out = cg.tally([_row("ungradeable")] * 3 + [_row("ungradeable", "steps")] + [_row("kept")])
        assert out["ungradeable_by_metric"] == {"total_protein_g": 3, "steps": 1}
        assert out["checkable"] == 5 and out["total"] == 5

    def test_a_metric_less_record_is_counted_but_never_called_checkable(self):
        out = cg.tally([_row("unresolved", None), _row("kept")])
        assert (out["total"], out["checkable"], out["unresolved"]) == (2, 1, 1)

    def test_an_unknown_status_falls_to_pending_rather_than_inventing_a_bucket(self):
        assert cg.tally([{"status": "weird"}])["pending"] == 1

    def test_an_empty_ledger_is_all_zeroes_and_no_rate(self):
        out = cg.tally([])
        assert out["total"] == 0 and out["follow_through_pct"] is None


# ══════════════════════════════════════════════════════════════════════════════
# F. The reader-facing surface — /api/predictions serves the follow-through block
# ══════════════════════════════════════════════════════════════════════════════


class TestScorecardApi:
    """The block `/coaching/scorecard/` renders the kept/broken tiles from. It rides in
    the SAME payload as the prediction scorecard because the two answer the two halves
    of one reader question, and because a ledger shown without its verdicts is the whole
    defect #3553 names."""

    def _serve(self, rollup, monkeypatch):
        """`/api/predictions` with the rollup `coach-prediction-evaluator` writes."""
        from web import site_api_coach as api

        from tests.fakes import FakeDdbTable

        got = {"Item": rollup} if rollup is not None else {}
        monkeypatch.setattr(
            api,
            "table",
            FakeDdbTable(query_hook=lambda _t, **kw: {"Items": []}, get_item_hook=lambda _t, key, **kw: got),
        )
        return json.loads(api.handle_predictions({"queryStringParameters": {"coach_id": "sleep"}})["body"])

    def _rollup(self, career, season=None):
        return {
            "pk": cg.ROLLUP_PK,
            "sk": cg.ROLLUP_SK,
            "as_of": TODAY,
            **cg.build_tally(career if season is None else career + season),
        }

    def test_the_payload_carries_kept_broken_with_n_and_a_wilson_interval(self, monkeypatch):
        rows = [{"status": "kept", "action_check": {"metric": "steps", "direction": "up"}} for _ in range(5)]
        rows += [{"status": "broken", "action_check": {"metric": "steps", "direction": "up"}} for _ in range(9)]
        block = self._serve(self._rollup(rows), monkeypatch)["commitments"]
        assert block["as_of"] == TODAY, "the reader is told WHEN it was last graded"
        assert block["lifetime"]["kept"] == 5 and block["lifetime"]["broken"] == 9
        assert block["lifetime"]["graded"] == 14 and block["lifetime"]["follow_through_pct"] == 35.7
        assert len(block["lifetime"]["follow_through_ci95"]) == 2

    def test_the_ungradeable_records_are_served_named_not_filtered_out(self, monkeypatch):
        rows = [{"status": "ungradeable", "action_check": {"metric": "total_protein_g", "direction": "up"}} for _ in range(37)]
        block = self._serve(self._rollup(rows), monkeypatch)["commitments"]
        assert block["lifetime"]["ungradeable"] == 37
        assert block["lifetime"]["ungradeable_by_metric"] == {"total_protein_g": 37}
        assert block["lifetime"]["follow_through_pct"] is None, "no verdicts means no rate — never a comforting 0%"

    def test_a_tombstoned_record_counts_toward_career_but_not_this_season(self, monkeypatch):
        """The same season-derived-from-career shape the prediction scorecard uses — a
        reset wipes the SEASON honestly, never the record."""
        rows = [
            {"status": "kept", "phase": "pilot", "tombstone": True, "action_check": {"metric": "steps", "direction": "up"}},
            {"status": "broken", "action_check": {"metric": "steps", "direction": "up"}},
        ]
        block = self._serve(self._rollup(rows), monkeypatch)["commitments"]
        assert block["lifetime"]["graded"] == 2 and block["season"]["graded"] == 1

    def test_the_scorecard_costs_ONE_extra_read_not_a_second_partition_fan_out(self, monkeypatch):
        """#1527's guard is why this is a rollup at all: re-scanning the seven
        COMMITMENT# partitions here doubled the handler's fan-out to 16 queries against
        a 9-worker pool and blew the concurrency budget in CI. The tally must cost one
        GetItem, and it must not add a single Query."""
        from web import site_api_coach as api

        from tests.fakes import FakeDdbTable

        gets, queries = [], []

        def _q(_t, **kw):
            queries.append(kw)
            return {"Items": []}

        def _g_hook(_t, key, **kw):
            gets.append(key)
            return {"Item": self._rollup([{"status": "kept", "action_check": {"metric": "steps", "direction": "up"}}])}

        monkeypatch.setattr(api, "table", FakeDdbTable(query_hook=_q, get_item_hook=_g_hook))
        body = json.loads(api.handle_predictions({"queryStringParameters": {"coach_id": "sleep"}})["body"])
        assert body["commitments"]["lifetime"]["kept"] == 1
        assert len(queries) == 1, f"one coach must mean one PREDICTION# query, got {len(queries)}"
        assert {"pk": cg.ROLLUP_PK, "sk": cg.ROLLUP_SK} in gets

    def test_no_rollup_yet_serves_null_never_a_zeroed_ledger(self, monkeypatch):
        """Before the evaluator's first post-deploy run there IS no tally. An absent
        artifact must read as absent, not as 'the coaches have kept nothing'."""
        assert self._serve(None, monkeypatch)["commitments"] is None

    def test_a_commitment_read_failure_never_takes_the_prediction_scorecard_down(self, monkeypatch):
        from web import site_api_coach as api

        from tests.fakes import FakeDdbTable

        monkeypatch.setattr(api, "table", FakeDdbTable(query_hook=lambda _t, **kw: {"Items": []}))
        monkeypatch.setattr(api, "_commitment_block", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        resp = api.handle_predictions({"queryStringParameters": {"coach_id": "sleep"}})
        assert resp["statusCode"] == 200
        assert json.loads(resp["body"])["commitments"] is None, "an unreadable ledger serves null, never a zeroed one"


# ══════════════════════════════════════════════════════════════════════════════
# G. The rollup itself — the grader publishes what it graded, dated
# ══════════════════════════════════════════════════════════════════════════════


class TestRollup:
    def test_this_runs_verdicts_are_applied_before_the_tally_is_published(self, ev, monkeypatch):
        """The DDB status writes are per-record and the in-memory rows still carry the
        PRE-run status, so a tally built straight off the corpus would be a day stale on
        the day it matters most — the day the ledger first grades anything."""
        due = _days_before(23)
        table = _FakeTable(commitments=[_commitment("c1")], metric_rows=_rising_whoop(due))
        cw = _FakeCw()
        monkeypatch.setattr(ev, "table", table)
        monkeypatch.setattr(ev, "_cw", cw)
        pending, corpus = ev._fetch_commitments()
        stats = ev._evaluate_commitments(pending, TODAY, {})
        assert corpus[0]["status"] == "pending", "the fetched row is pre-verdict — that is the trap"
        payload = cg.write_tally(table, corpus, stats["applied"], TODAY, ev.logger)
        assert payload["lifetime"]["kept"] == 1 and payload["lifetime"]["pending"] == 0
        assert payload["as_of"] == TODAY
        assert table.store[(cg.ROLLUP_PK, cg.ROLLUP_SK)]["as_of"] == TODAY

    def test_the_fetch_hands_back_the_whole_corpus_not_just_the_pending_set(self, ev, monkeypatch):
        """The rollup needs every status; the loop already pages them all, so the
        second list is free rather than a second scan."""
        monkeypatch.setattr(ev, "table", _FakeTable(commitments=[_commitment("c1"), _commitment("c2", status="kept")]))
        pending, corpus = ev._fetch_commitments()
        assert [c["commitment_id"] for c in pending] == ["c1"]
        assert sorted(c["commitment_id"] for c in corpus) == ["c1", "c2"]

    def test_a_rollup_write_failure_never_sinks_the_grading_pass(self, ev):
        class _Broken(_FakeTable):
            def put_item(self, **kw):
                raise RuntimeError("throttled")

        payload = cg.write_tally(_Broken(), [{"sk": "COMMITMENT#x", "status": "kept"}], {}, TODAY, ev.logger)
        assert payload["lifetime"]["kept"] == 1  # computed and returned even though the write died
