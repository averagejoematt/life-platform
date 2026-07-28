"""
tests/test_diary_claims_1841.py — the on-tape claims ledger (#1841, diary-360 story 1).

What these pin, in the order the story's ACs run:

  AC1  the close offers 0-3 claims, consent PER CLAIM, never auto
  AC2  admitted claims land in the prediction-store record shape with source=video_diary,
       an entry sk pointer, and a grade-by date frozen at admission
  AC3  /vlog step-0 surfaces claims due/overdue for grading
  AC4  graded claims ride the same track-record surfaces as every other prediction

plus the two invariants that make the whole thing honest: the LLM can only PROPOSE
(ADR-105 — the code-admit gate refuses everything ungradable), and a claim of Matthew's
can NEVER move a coach's calibration.
"""

import ast
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
sys.path.insert(0, os.path.join(_ROOT, "lambdas", "coach"))

from experiment import measurable_metrics as mm  # noqa: E402
from privacy import diary_claims as dc  # noqa: E402

SESSION_DATE = "2026-07-26"
SOURCE_SK = "DATE#2026-07-26#journal#video_diary#a1b2c3d4e5f6"


def _candidate(**over):
    """A minimal claim that SHOULD be admitted; override one field to break it."""
    base = {
        "claim": "I'll be under 300 pounds by Halloween",
        "consent": True,
        "metric": "weight_lbs",
        "threshold": 300,
        "condition": "lt",
        "horizon_days": 97,
        "confidence": "medium",
    }
    base.update(over)
    return base


# ══════════════════════════════════════════════════════════════════════════════
# AC1 — consent per claim, never auto
# ══════════════════════════════════════════════════════════════════════════════


class TestConsentIsPerClaimAndExplicit:
    def test_consent_true_admits(self):
        ok, reason, norm = dc.admit_claim(_candidate(), SESSION_DATE, SOURCE_SK)
        assert ok, reason
        assert norm["metric"] == "weight_lbs"

    def test_missing_consent_is_refused(self):
        ok, reason, norm = dc.admit_claim(_candidate(consent=None), SESSION_DATE, SOURCE_SK)
        assert not ok and norm is None
        assert "consent" in reason

    def test_truthy_is_not_consent(self):
        """Silence means no — and so does 'yes', 1, and 'true'. Only True is consent."""
        for sneaky in ("yes", 1, "true", [1], {"ok": True}):
            ok, reason, _ = dc.admit_claim(_candidate(consent=sneaky), SESSION_DATE, SOURCE_SK)
            assert not ok, f"{sneaky!r} must not read as consent"
            assert "exactly true" in reason

    def test_session_cap_is_three(self):
        assert dc.MAX_CLAIMS_PER_SESSION == 3


# ══════════════════════════════════════════════════════════════════════════════
# The code-admit gate (ADR-105) — the LLM proposes, this refuses
# ══════════════════════════════════════════════════════════════════════════════


class TestCodeAdmitsOnlyFalsifiableClaims:
    def test_unresolvable_metric_is_refused(self):
        ok, reason, _ = dc.admit_claim(_candidate(metric="vibes"), SESSION_DATE, SOURCE_SK)
        assert not ok
        assert "not deterministically resolvable" in reason

    def test_prose_metric_hint_is_normalized_not_guessed(self):
        ok, _, norm = dc.admit_claim(
            _candidate(metric="heart rate variability", threshold=None, condition=None, direction="up"),
            SESSION_DATE,
            SOURCE_SK,
        )
        assert ok
        assert norm["metric"] == "hrv"

    def test_no_threshold_and_no_direction_is_refused(self):
        """The motivating day-zero claim ('I normally coast on good habits') has no
        number and no direction — it stays a story, and the refusal says why."""
        ok, reason, _ = dc.admit_claim(
            _candidate(claim="I normally at least coast on a lot of the good habits", threshold=None, condition=None),
            SESSION_DATE,
            SOURCE_SK,
        )
        assert not ok
        assert "not falsifiable" in reason

    def test_direction_alone_routes_to_the_gradable_directional_spec(self):
        ok, _, norm = dc.admit_claim(
            _candidate(claim="my HRV will recover once I'm sleeping again", metric="hrv", threshold=None, condition=None),
            SESSION_DATE,
            SOURCE_SK,
        )
        assert ok
        assert norm["evaluation"]["type"] == "directional"
        assert norm["evaluation"]["condition"] == "up"

    def test_directional_spec_never_carries_a_dead_threshold(self):
        """C-3/#813: a threshold the evaluator will try and fail to compare against is
        what made 248/248 machine predictions permanently inconclusive."""
        _, _, norm = dc.admit_claim(_candidate(metric="hrv", threshold=None, condition=None, direction="up"), SESSION_DATE, SOURCE_SK)
        assert norm["evaluation"]["threshold"] is None

    def test_bad_condition_with_a_threshold_is_refused(self):
        ok, reason, _ = dc.admit_claim(_candidate(condition="approximately"), SESSION_DATE, SOURCE_SK)
        assert not ok
        assert "not gradable" in reason

    def test_condition_vocabulary_matches_the_evaluator(self):
        """The gate may only admit conditions `_evaluate_condition` actually grades."""
        import coach_prediction_evaluator as cpe

        src = ast.parse(open(os.path.join(_ROOT, "lambdas", "coach", "coach_prediction_evaluator.py")).read())
        graded = set()
        for node in ast.walk(src):
            if isinstance(node, ast.FunctionDef) and node.name == "_evaluate_condition":
                graded = {c.value for c in ast.walk(node) if isinstance(c, ast.Constant) and isinstance(c.value, str)}
        assert set(dc.VALID_CONDITIONS) <= graded, "the gate admits a condition the evaluator cannot grade"
        assert cpe is not None

    def test_qualitative_is_never_an_admissible_spec_type(self):
        """The evaluator SKIPS qualitative specs, so admitting one seeds a row that can
        never be graded — the exact v7.15.0 '100% inconclusive' failure."""
        assert "qualitative" not in dc.GRADABLE_SPEC_TYPES

    def test_non_integer_horizon_is_refused(self):
        ok, reason, _ = dc.admit_claim(_candidate(horizon_days="soon"), SESSION_DATE, SOURCE_SK)
        assert not ok
        assert "horizon_days" in reason

    def test_horizon_outside_bounds_is_refused(self):
        for bad in (dc.MIN_HORIZON_DAYS - 1, dc.MAX_HORIZON_DAYS + 1):
            ok, reason, _ = dc.admit_claim(_candidate(horizon_days=bad), SESSION_DATE, SOURCE_SK)
            assert not ok and "outside" in reason

    def test_non_numeric_threshold_is_refused(self):
        ok, reason, _ = dc.admit_claim(_candidate(threshold="about 300"), SESSION_DATE, SOURCE_SK)
        assert not ok
        assert "not numeric" in reason

    def test_empty_claim_text_is_refused(self):
        ok, reason, _ = dc.admit_claim(_candidate(claim="   "), SESSION_DATE, SOURCE_SK)
        assert not ok and "claim text is required" in reason

    def test_overlong_claim_is_refused(self):
        ok, reason, _ = dc.admit_claim(_candidate(claim="x" * (dc.MAX_CLAIM_CHARS + 1)), SESSION_DATE, SOURCE_SK)
        assert not ok and "exceeds" in reason

    def test_non_dict_candidate_is_refused(self):
        for junk in (None, "a claim", 42, ["claim"]):
            ok, _, norm = dc.admit_claim(junk, SESSION_DATE, SOURCE_SK)
            assert not ok and norm is None


# ══════════════════════════════════════════════════════════════════════════════
# AC2 — the record: source, entry pointer, frozen grade-by
# ══════════════════════════════════════════════════════════════════════════════


class TestEntryPointerAndRecordShape:
    def test_non_video_diary_source_sk_is_refused(self):
        for bad in ("", "DATE#2026-07-26#journal#evening", "nonsense", "DATE#2026-07-26#journal#solo_recording#abc123abc123"):
            ok, reason, _ = dc.admit_claim(_candidate(), SESSION_DATE, bad)
            assert not ok, f"{bad!r} must not pass as a video-diary entry sk"
            assert "video-diary entry sk" in reason

    def test_pointer_date_must_match_the_session_date(self):
        ok, reason, _ = dc.admit_claim(_candidate(), "2026-07-27", SOURCE_SK)
        assert not ok
        assert "does not match the session date" in reason

    def test_grade_by_is_stated_date_plus_horizon_frozen(self):
        _, _, norm = dc.admit_claim(_candidate(horizon_days=30), SESSION_DATE, SOURCE_SK)
        assert norm["grade_by"] == "2026-08-25"

    def test_record_carries_source_pointer_and_grade_by(self):
        _, _, norm = dc.admit_claim(_candidate(), SESSION_DATE, SOURCE_SK)
        rec = dc.build_claim_record(norm, SESSION_DATE, SOURCE_SK, "2026-07-26T05:00:00Z")
        assert rec["pk"] == "USER#matthew#SOURCE#diary_claims"
        assert rec["sk"].startswith("PREDICTION#2026-07-26#")
        assert rec["source"] == "video_diary"
        assert rec["source_sk"] == SOURCE_SK
        assert rec["source_pk"] == "USER#matthew#SOURCE#notion"
        assert rec["grade_by"] == norm["grade_by"]
        assert rec["status"] == "pending"
        assert rec["created_date"] == SESSION_DATE, "the evaluator anchors its window on created_date"

    def test_ungraded_outcome_fields_are_absent_not_null(self):
        """ADR-104: an ungraded claim has no outcome — not a null one."""
        _, _, norm = dc.admit_claim(_candidate(), SESSION_DATE, SOURCE_SK)
        rec = dc.build_claim_record(norm, SESSION_DATE, SOURCE_SK, "2026-07-26T05:00:00Z")
        for absent in ("outcome", "outcome_date", "outcome_notes", "called_back_at"):
            assert absent not in rec

    def test_record_is_private_by_default(self):
        _, _, norm = dc.admit_claim(_candidate(), SESSION_DATE, SOURCE_SK)
        rec = dc.build_claim_record(norm, SESSION_DATE, SOURCE_SK, "2026-07-26T05:00:00Z")
        assert rec["visibility"] == "private"

    def test_sk_is_the_idempotency_handle(self):
        """Re-logging the same claim on the same day derives the same key — an overwrite,
        never a second row."""
        a = dc.claim_sk(SESSION_DATE, "I'll be under 300 pounds by Halloween")
        b = dc.claim_sk(SESSION_DATE, "  I'll   be under 300 POUNDS by Halloween ")
        assert a == b
        assert a != dc.claim_sk(SESSION_DATE, "something else entirely")

    def test_confidence_scale_matches_the_coach_store(self):
        """A diary claim scored on a different scale than a coach prediction would
        silently corrupt any pooled Brier score (calibration_core reads this field)."""
        import coach_state_updater as csu

        for word in ("low", "medium", "high", "very low", "very high"):
            assert dc.parse_confidence(word) == csu._parse_confidence(word), word
        assert dc.parse_confidence("85%") == csu._parse_confidence("85%")
        assert dc.parse_confidence(None) == csu._parse_confidence(None)


# ══════════════════════════════════════════════════════════════════════════════
# AC3 — due / overdue for grading
# ══════════════════════════════════════════════════════════════════════════════


def _stored(**over):
    _, _, norm = dc.admit_claim(_candidate(**over.pop("candidate", {})), SESSION_DATE, SOURCE_SK)
    rec = dc.build_claim_record(norm, SESSION_DATE, SOURCE_SK, "2026-07-26T05:00:00Z")
    rec.update(over)
    return rec


class TestDueForGrading:
    def test_claim_before_its_deadline_is_not_due(self):
        rec = _stored(grade_by="2026-12-01")
        assert dc.due_for_grading([rec], "2026-11-30") == []

    def test_claim_at_its_deadline_is_due(self):
        rec = _stored(grade_by="2026-12-01")
        due = dc.due_for_grading([rec], "2026-12-01")
        assert len(due) == 1
        assert due[0]["days_overdue"] == 0

    def test_overdue_sorts_oldest_deadline_first(self):
        a = _stored(grade_by="2026-12-01", claim_id="a", sk="PREDICTION#a")
        b = _stored(grade_by="2026-10-01", claim_id="b", sk="PREDICTION#b")
        due = dc.due_for_grading([a, b], "2026-12-05")
        assert [c["claim_id"] for c in due] == ["b", "a"]
        assert due[0]["days_overdue"] == 65

    def test_already_called_back_stops_resurfacing(self):
        rec = _stored(grade_by="2026-12-01", called_back_at="2026-12-02T00:00:00Z")
        assert dc.due_for_grading([rec], "2026-12-05") == []

    def test_deadline_reached_with_verdict_pending_is_still_surfaced_honestly(self):
        """The evaluator floors windows at a domain minimum, so a claim can hit its own
        deadline before the machine will decide. Say so — don't hide the row."""
        rec = _stored(grade_by="2026-12-01")
        due = dc.due_for_grading([rec], "2026-12-01")
        assert due[0]["status"] == "pending"
        assert due[0]["machine_verdict"] == "still pending"

    def test_graded_claim_reports_its_verdict(self):
        rec = _stored(grade_by="2026-12-01", status="refuted", outcome="refuted", outcome_date="2026-12-01")
        due = dc.due_for_grading([rec], "2026-12-02")
        assert due[0]["machine_verdict"] == "decided"
        assert due[0]["outcome"] == "refuted"

    def test_unparseable_dates_never_crash_the_priming_call(self):
        assert dc.due_for_grading([_stored(grade_by=None)], "2026-12-01") == []
        assert dc.due_for_grading([_stored()], "not-a-date") == []


# ══════════════════════════════════════════════════════════════════════════════
# AC4 — the same track-record surfaces, with n (ADR-105)
# ══════════════════════════════════════════════════════════════════════════════


class TestTrackRecord:
    def test_hit_rate_is_absent_not_zero_with_nothing_graded(self):
        tr = dc.track_record([_stored(), _stored()])
        assert tr["hit_rate_pct"] is None, "a rate over zero graded claims is absent, not 0%"
        assert tr["n_decided"] == 0

    def test_hit_rate_and_n(self):
        recs = [_stored(status="confirmed"), _stored(status="refuted"), _stored(status="pending")]
        tr = dc.track_record(recs)
        assert tr["n_total"] == 3
        assert tr["n_decided"] == 2
        assert tr["hit_rate_pct"] == 50.0

    def test_small_n_is_flagged(self):
        tr = dc.track_record([_stored(status="confirmed")])
        assert "too few" in tr["n_caveat"]

    def test_interpretation_is_correlative_not_causal(self):
        tr = dc.track_record([])
        assert "not causal" in tr["interpretation"].lower()

    def test_get_predictions_reads_the_claims_partition(self):
        """AC4: graded claims ride the same ledger surface as coach predictions."""
        src = open(os.path.join(_ROOT, "mcp", "tools_coach_intelligence.py")).read()
        tree = ast.parse(src)
        strings = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "tool_get_predictions":
                # Skip the docstring — it NAMES the legacy store to explain why it is not
                # read (the same exclusion tests/test_predictions_one_store_726.py makes).
                body = node.body[1:] if isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) else node.body
                strings = [c.value for stmt in body for c in ast.walk(stmt) if isinstance(c, ast.Constant) and isinstance(c.value, str)]
        assert any("diary_claims" in s for s in strings), "the ledger must include the subject's own on-tape claims"
        assert any("COACH#" in s for s in strings), "#726: the canonical coach store is still read"
        assert not any("coach_thread" in s for s in strings), "#726: never the legacy embedded arrays"

    def test_public_prediction_surfaces_do_NOT_read_the_claims_partition(self):
        """Privacy: diary content is private by default. The public /api/predictions and
        /api/calibration path reads COACH# partitions only — a claim of his never crosses
        to the website without an explicit consent marker (deliberately not wired)."""
        src = open(os.path.join(_ROOT, "lambdas", "web", "site_api_coach.py")).read()
        assert "diary_claims" not in src


# ══════════════════════════════════════════════════════════════════════════════
# The evaluator wiring — one grader, and no coach calibration to corrupt
# ══════════════════════════════════════════════════════════════════════════════


class TestEvaluatorWiring:
    def test_evaluator_scans_the_claims_partition(self):
        import coach_prediction_evaluator as cpe

        assert cpe.DIARY_CLAIMS_PK == "USER#matthew#SOURCE#diary_claims"
        src = open(os.path.join(_ROOT, "lambdas", "coach", "coach_prediction_evaluator.py")).read()
        tree = ast.parse(src)
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_fetch_predictions":
                names = {c.id for c in ast.walk(node) if isinstance(c, ast.Name)}
        assert "DIARY_CLAIMS_PK" in names, "_fetch_predictions must include the claims partition"

    def test_claim_record_carries_empty_coach_id(self):
        """The evaluator's `if bayesian_update and coach_id` guard is what keeps a claim
        of Matthew's out of a coach's Bayesian confidence. It only holds if coach_id is
        falsy on the record."""
        _, _, norm = dc.admit_claim(_candidate(), SESSION_DATE, SOURCE_SK)
        rec = dc.build_claim_record(norm, SESSION_DATE, SOURCE_SK, "2026-07-26T05:00:00Z")
        assert rec["coach_id"] == ""
        assert not rec["coach_id"]

    def test_learning_record_is_skipped_without_a_coach(self):
        """Otherwise a claim would write a LEARNING# row onto a `COACH#` partition with no
        coach — a phantom every coach hit-rate surface would then count."""
        import coach_prediction_evaluator as cpe

        calls = []

        class _Table:
            def put_item(self, **kw):
                calls.append(kw)

        original = cpe.table
        cpe.table = _Table()
        try:
            cpe._write_learning_record("", "2026-08-01", {"prediction_id": "x", "status": "refuted"})
            assert calls == [], "no LEARNING# row may be written for a coachless claim"
            cpe._write_learning_record("mind_coach", "2026-08-01", {"prediction_id": "x", "status": "refuted"})
            assert len(calls) == 1, "a real coach still gets its LEARNING# trail"
        finally:
            cpe.table = original

    def test_subdomain_maps_into_the_evaluator_window_vocabulary(self):
        """A subdomain the evaluator doesn't know silently clamps the window to the
        conservative 21-day 'training' default (#813)."""
        import coach_prediction_evaluator as cpe

        for metric in mm.METRIC_SOURCES:
            sub = mm.metric_subdomain(metric)
            assert sub in cpe.SUBDOMAIN_TO_DOMAIN, f"{metric} -> subdomain {sub!r} is not a window-enforcement key"


# ══════════════════════════════════════════════════════════════════════════════
# Registry / taxonomy / reset coverage
# ══════════════════════════════════════════════════════════════════════════════


class TestRegistration:
    def test_partition_is_phase_classified_and_wiped(self):
        from experiment import phase_taxonomy as pt

        assert pt.classify("USER#matthew#SOURCE#diary_claims", "PREDICTION#2026-07-26#x") == pt.EXPERIMENT_SCOPED
        sys.path.insert(0, os.path.join(_ROOT, "deploy"))
        import restart_intelligence_wipe as wipe

        assert "diary_claims" in {src for src, _mode, _extra in wipe.PARTITIONS}

    def test_metric_subdomain_map_has_not_drifted_from_the_dockets_copy(self):
        """`dispute_docket` still carries its own copy of this map pending its collapse
        onto measurable_metrics. Until then, pin them identical — a silent divergence
        would give the same metric two different evaluation windows."""
        from coach import dispute_docket as dd

        assert dd._METRIC_SUBDOMAIN == mm.METRIC_SUBDOMAIN

    def test_tool_is_registered(self):
        src = open(os.path.join(_ROOT, "mcp", "registry.py")).read()
        assert '"manage_diary_claims"' in src
        assert "tool_manage_diary_claims" in src

    def test_vlog_command_wires_both_ends_of_the_loop(self):
        """AC1 + AC3 live in the command file — the close that offers claims and the
        step-0 priming that calls them back."""
        src = open(os.path.join(_ROOT, ".claude", "commands", "vlog.md")).read()
        step0, close = src.split("### 3. Close = route the takeaways")
        assert "manage_diary_claims" in step0, "step 0 must surface claims due for grading (AC3)"
        assert "due" in step0
        assert "manage_diary_claims" in close, "the close must offer claim registration (AC1)"
        assert "consent" in close.lower()


# ══════════════════════════════════════════════════════════════════════════════
# The MCP tool body — the write path end to end
# ══════════════════════════════════════════════════════════════════════════════

from decimal import Decimal  # noqa: E402

from fakes import FakeDdbTable  # noqa: E402

_ENTRY_ROW = {"pk": "USER#matthew#SOURCE#notion", "sk": SOURCE_SK, "channel": "video_diary"}


def _tool(monkeypatch, rows=None, entry_present=True):
    """Wire tools_journal.table to a fake that dispatches on the queried pk."""
    import mcp.tools_journal as tj

    claim_rows = list(rows or [])

    def _query_hook(_t, **kw):
        pk_val = kw["KeyConditionExpression"]._values[0]._values[1]
        if pk_val == "USER#matthew#SOURCE#notion":
            return {"Items": [_ENTRY_ROW] if entry_present else []}
        return {"Items": claim_rows}

    fake = FakeDdbTable(query_hook=_query_hook)
    monkeypatch.setattr(tj, "table", fake)
    return tj, fake


class TestManageDiaryClaimsTool:
    def test_log_admits_and_writes_a_decimal_safe_record(self, monkeypatch):
        tj, fake = _tool(monkeypatch)
        out = tj.tool_manage_diary_claims(
            {"action": "log", "date": SESSION_DATE, "source_sk": SOURCE_SK, "claims": [_candidate()]},
        )
        assert out["status"] == "logged"
        assert len(out["admitted"]) == 1 and out["refused"] == []
        item = fake.puts[0]
        assert item["pk"] == "USER#matthew#SOURCE#diary_claims"
        assert item["phase"], "ADR-058: every experiment-scoped write carries a phase stamp"
        # boto3 rejects float — every number must have been cast on the way out.
        assert isinstance(item["confidence"], Decimal)
        assert isinstance(item["evaluation"]["threshold"], Decimal)
        assert not any(isinstance(v, float) for v in item.values())

    def test_log_reports_refusals_instead_of_swallowing_them(self, monkeypatch):
        tj, fake = _tool(monkeypatch)
        out = tj.tool_manage_diary_claims(
            {
                "action": "log",
                "date": SESSION_DATE,
                "source_sk": SOURCE_SK,
                "claims": [_candidate(), _candidate(claim="I'll feel better", metric="vibes")],
            },
        )
        assert len(out["admitted"]) == 1
        assert len(out["refused"]) == 1
        assert "not deterministically resolvable" in out["refused"][0]["reason"]
        assert len(fake.puts) == 1, "a refused claim must not be written"

    def test_log_refuses_when_the_entry_is_not_ingested_yet(self, monkeypatch):
        """ADR-104: report the honest state, never write a claim pointing at nothing."""
        tj, fake = _tool(monkeypatch, entry_present=False)
        out = tj.tool_manage_diary_claims(
            {"action": "log", "date": SESSION_DATE, "source_sk": SOURCE_SK, "claims": [_candidate()]},
        )
        assert "refused" in out["error"]
        assert fake.puts == []

    def test_log_enforces_the_session_cap(self, monkeypatch):
        tj, fake = _tool(monkeypatch)
        out = tj.tool_manage_diary_claims(
            {"action": "log", "date": SESSION_DATE, "source_sk": SOURCE_SK, "claims": [_candidate()] * 4},
        )
        assert "cap is 3" in out["error"]
        assert fake.puts == []

    def test_log_with_no_claims_writes_nothing(self, monkeypatch):
        """Zero is a perfectly good number of claims."""
        tj, fake = _tool(monkeypatch)
        out = tj.tool_manage_diary_claims({"action": "log", "date": SESSION_DATE, "source_sk": SOURCE_SK, "claims": []})
        assert out["status"] == "nothing_admitted"
        assert fake.puts == []

    def test_due_returns_the_priming_list(self, monkeypatch):
        tj, _ = _tool(monkeypatch, rows=[_stored(grade_by="2026-10-01")])
        out = tj.tool_manage_diary_claims({"action": "due", "today": "2026-10-02"})
        assert out["count"] == 1
        assert out["due"][0]["days_overdue"] == 1
        assert out["track_record"]["n_total"] == 1

    def test_due_is_the_zero_arg_default(self, monkeypatch):
        tj, _ = _tool(monkeypatch, rows=[])
        out = tj.tool_manage_diary_claims({})
        assert out["count"] == 0 and out["due"] == []

    def test_called_back_stamps_the_row(self, monkeypatch):
        tj, fake = _tool(monkeypatch, rows=[_stored()])
        sk = dc.claim_sk(SESSION_DATE, _candidate()["claim"])
        out = tj.tool_manage_diary_claims({"action": "called_back", "sk": sk})
        assert out["status"] == "called_back"
        assert "called_back_at" in fake.updates[0]["UpdateExpression"]

    def test_called_back_requires_a_real_claim_sk(self, monkeypatch):
        tj, fake = _tool(monkeypatch)
        out = tj.tool_manage_diary_claims({"action": "called_back", "sk": "QUOTE#2026-07-26#abc"})
        assert "error" in out
        assert fake.updates == []

    def test_unknown_action_is_refused(self, monkeypatch):
        tj, _ = _tool(monkeypatch)
        out = tj.tool_manage_diary_claims({"action": "delete_everything"})
        assert "Unknown action" in out["error"]
