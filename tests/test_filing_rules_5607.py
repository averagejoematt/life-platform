"""#5607 (owner ruling 2026-11-03, item 6) — the filing-time rules for a graded call.

"Fix future filing: require measurable outcomes, frozen windows and properly tested conditions.
Do not adopt blanket rules rejecting known antecedents or two-branch forecasts; either can
support a valid future prediction. Do not invent criteria retrospectively."

The fixture wordings below are REAL cycle-17 rows (the #5611 inventory's read-only
misfiled-class scan of all 480 PREDICTION# rows), each with the spec it was actually filed
under. Under the old filing path every one of them was a graded call.
"""

# premerge-gate: 5607: two os.walk sweeps of lambdas/ mcp/ scripts/ deploy/ — every PREDICTION# writer is routed through the filing rules or named with a reason, and only filing paths import the rules (no grader or re-grade path can re-specify a stored row). Both fail on the diff that adds the writer/importer, so they belong before merge.
import ast
import copy
import os
import re
import sys

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "coach"))

from coach import (
    conditional_branches as cb,  # noqa: E402
    filing_rules as fr,  # noqa: E402
    prediction_emission as pe,  # noqa: E402
)


def _dir(metric, cond, days=14.0):
    return {"type": "directional", "metric": metric, "condition": cond, "threshold": None, "evaluation_window_days": days}


def _point(metric, value, days=14.0):
    return {"type": "point", "metric": metric, "condition": "within", "threshold": value, "tolerance": 5.0, "evaluation_window_days": days}


# ── class A: the outcome names no measurement (real wordings, with the spec each was filed under) ──
OPINIONS = [
    (
        "2026-10-15",
        "If October 5-6 protein stayed above 150.9 grams per day, carb reduction alone is the more likely driver and "
        "glucose-dynamics hypothesis gains credibility",
        _dir("total_protein_g", "up"),
    ),
    (
        "2026-10-15",
        "If October 5-6 protein dropped below 150.9 grams per day average, the protein-as-primary-driver hypothesis survives "
        "and the decline pattern is explained",
        _dir("total_protein_g", "down"),
    ),
    (
        "2026-10-26",
        "If protein on October 5–6 stayed above 150.9 g, carb reduction alone is the driver of glucose dynamics; if it dropped "
        "below 150.9 g, protein availability is the primary driver and recovery decline is explained by protein loss.",
        _dir("total_protein_g", "down"),
    ),
    (
        "2026-10-26",
        "If protein clears 170 g specifically, recovery will respond to protein as primary driver.",
        _dir("recovery_score", "up", 7.0),
    ),
    (
        "2026-11-02",
        "If logging resumes this week and recovery responds, system coherence is the rate-limiter",
        _dir("recovery_score", "up"),
    ),
    ("2026-10-15", "Protein recovery would lift the journaling silence", _dir("total_protein_g", "up")),
    (
        "2026-10-05",
        "Recovery climb from September 10 trough to 82.7% over last 30 days is most parsimoniously explained by regression toward "
        "the mean after an unusually low floor event, not by confirmed adaptation.",
        _dir("recovery_score", "up", 30.0),
    ),
    (
        "2026-11-02",
        "Nocturnal glucose dips trigger cortisol responses that fragment deep sleep, explaining why deep sleep drifts down even "
        "as sleep score climbs",
        _dir("deep_pct", "down"),
    ),
    (
        "2026-09-20",
        "If journaling resumes alongside protein recovery to ~145g, the fuel-cognition link gains credibility as explanation for "
        "the silence.",
        _point("total_protein_g", 145.0),
    ),
    (
        "2026-09-21",
        "If protein EWMA holds at 170g or above for seven consecutive days and step etiology is resolved, Zone 2 training "
        "escalation can resume.",
        _dir("total_protein_g", "up", 170.0),
    ),
    (
        "2026-09-17",
        "If tonight's sleep duration falls outside 5.7–9.0 hours, the model's assumption about upper-tail variance may be too "
        "narrow and requires further recalibration.",
        _dir("sleep_duration_hours", "down", 1.0),
    ),
    (
        "2026-10-08",
        "If recovery flattens or reverses in the next week, the sleep coach's parsimonious regression-to-mean read was correct.",
        _dir("recovery_score", "down"),
    ),
]

# ── class B: retrospective — every one of the 13 real rows ─────────────────────────────────────
RETROSPECTIVE = [
    ("2026-09-18", "Evening carb reduction without caloric compensation would crater recovery between 2026-09-14 and 2026-09-17."),
    ("2026-09-18", "Recovery would hold above the EWMA (69.8%) while carbs dropped."),
    (
        "2026-09-23",
        "If the two dark days between September 19th and today saw dinner skipped entirely, protein likely collapsed to "
        "approximately 46g for those days from morning smoothie and mid-day bar alone.",
    ),
    (
        "2026-09-24",
        "If dinner was disrupted during the logging gap, protein likely collapsed to somewhere around half the daily target or below.",
    ),
    ("2026-09-28", "If dinner was disrupted during the September 19th stretch, protein collapsed to half the daily target or below."),
    (
        "2026-09-29",
        "If dinner was disrupted between September 19th and 26th, protein likely collapsed well below the 170g floor, possibly to "
        "half the daily target.",
    ),
    (
        "2026-09-30",
        "If dinner was skipped or reduced during the September 19-26 window, daily protein fell well below 170g, possibly to "
        "smoothie and bar levels only.",
    ),
    ("2026-09-30", "Protein likely collapsed well below the 170g floor during the September 19–26 gap if dinner was the casualty"),
    (
        "2026-10-01",
        "If dinner was disrupted for four days without backup plan activation, protein intake likely collapsed well below 170 g floor.",
    ),
    (
        "2026-10-01",
        "Protein intake collapsed during the September 19-26 logging gap and the four subsequent days without logging, "
        "particularly if dinner was disrupted.",
    ),
    (
        "2026-10-05",
        "If dinner was not logged during September 19–26, protein likely collapsed well below 170g floor, possibly to 95g or lower.",
    ),
    (
        "2026-10-12",
        "If dinner was genuinely disrupted for six days (September 19-26), protein likely collapsed well below the 170g floor "
        "during that window.",
    ),
    (
        "2026-10-12",
        "If dinners went unlogged rather than uneaten during September 19-26, the running average is understated and actual "
        "intake is closer to target.",
    ),
]


class TestMeasurableOutcome:
    def test_every_misfiled_opinion_files_as_an_observation_with_its_reason(self):
        offenders = []
        for day, claim, spec in OPINIONS:
            v = fr.validate_filing(claim, spec, day, timeframe_hint="2 weeks")
            f = v["filing"]
            ok = (
                not v["gradeable"]
                and v["eval_spec"]["type"] == "qualitative"
                and f["verdict"] == fr.OBSERVATION
                and f["reason"] in fr.REASONS
                and f["reason_text"] == fr.REASONS[f["reason"]]
                and f["filing_rules_version"] == fr.FILING_RULES_VERSION
            )
            if not ok:
                offenders.append((claim, f))
        assert not offenders, offenders

    def test_the_15_october_call_is_a_judgement_not_its_antecedents_metric(self):
        claim, spec = OPINIONS[0][1], OPINIONS[0][2]
        v = fr.validate_filing(claim, spec, "2026-10-15", timeframe_hint="2 weeks")
        assert v["filing"]["reason"] == "outcome_is_judgement"

    def test_a_metric_named_only_in_the_condition_is_not_the_outcome(self):
        v = fr.validate_filing(
            "If protein stays above 150 g this week, I will feel sharper within two weeks", _dir("total_protein_g", "up"), "2026-11-03"
        )
        assert v["filing"]["reason"] == "outcome_metric_from_condition"

    def test_the_direction_is_read_off_the_outcome_clause_not_the_extractor(self):
        v = fr.validate_filing("Recovery score will fall over the next two weeks", _dir("recovery_score", "up"), "2026-11-03")
        assert v["gradeable"]
        assert v["eval_spec"]["condition"] == "down"

    def test_a_plain_measurable_call_with_a_window_files_gradeable_with_a_frozen_window(self):
        v = fr.validate_filing("HRV will rise over the next two weeks", _dir("hrv", "up"), "2026-11-03")
        assert v["gradeable"]
        spec = v["eval_spec"]
        assert spec["type"] == "directional" and spec["condition"] == "up"
        assert spec["evaluation_window_days"] == 14
        assert (spec["window_start"], spec["window_end"]) == ("2026-11-03", "2026-11-17")
        assert v["filing"]["window_basis"] == "outcome_clause"


class TestFrozenWindow:
    def test_a_vague_direction_claim_without_a_window_is_an_observation(self):
        v = fr.validate_filing("HRV will rise.", _dir("hrv", "up"), "2026-11-03")
        assert not v["gradeable"]
        assert v["filing"]["reason"] == "no_stated_window"

    def test_the_extractors_stated_timeframe_is_a_window(self):
        v = fr.validate_filing("HRV will rise.", _dir("hrv", "up"), "2026-11-03", timeframe_hint="2 weeks")
        assert v["gradeable"] and v["filing"]["window_basis"] == "timeframe_hint"

    def test_the_frozen_window_end_is_the_day_the_grader_closes_it(self):
        """The stored window_end is computed with the grader's own clamp, so the grader never re-derives
        a different one: prediction_windows.due_date(row) == window_end."""
        from coach import prediction_windows as pw

        v = fr.validate_filing("Recovery score will fall tomorrow", _dir("recovery_score", "down"), "2026-11-03")
        spec = v["eval_spec"]
        assert spec["evaluation_window_days"] == 1  # stored as stated
        assert pw.due_date("2026-11-03", spec, pe.infer_subdomain("recovery_score")) == spec["window_end"]

    def test_every_real_retrospective_row_files_as_an_observation(self):
        graded = [
            c for d, c in RETROSPECTIVE if fr.validate_filing(c, _dir("total_protein_g", "down"), d, timeframe_hint="2 weeks")["gradeable"]
        ]
        assert not graded, graded

    def test_a_retrospective_number_claim_says_the_reading_already_existed(self):
        v = fr.validate_filing("Protein will come in around 46 g on 2026-09-20.", _point("total_protein_g", 46.0), "2026-09-23")
        assert v["filing"]["reason"] == "retrospective"
        assert "the reading already existed" in v["filing"]["reason_text"]

    def test_a_target_day_equal_to_the_filing_day_is_retrospective(self):
        v = fr.validate_filing("Protein will come in around 46 g on 2026-09-23.", _point("total_protein_g", 46.0), "2026-09-23")
        assert v["filing"]["reason"] == "retrospective"


def _readings(values):
    def lookup(metric, start, end):
        lookup.calls.append((metric, start, end))
        return values

    lookup.calls = []
    return lookup


class TestConditions:
    CALL = "If protein averaged above 150 g on October 5-6, recovery score will rise over the next two weeks."

    def test_a_known_antecedent_files_gradeable_with_the_antecedent_evaluated_at_filing(self):
        lookup = _readings([("2026-10-05", 160.0), ("2026-10-06", 155.0)])
        v = fr.validate_filing(self.CALL, _dir("recovery_score", "up"), "2026-10-15", antecedent_readings=lookup)
        assert v["gradeable"]
        spec = v["eval_spec"]
        assert spec["type"] == "conditional" and len(spec["branches"]) == 1
        ante = spec["branches"][0]["antecedent"]
        assert (ante["metric"], ante["op"], ante["threshold"]) == ("total_protein_g", "gt", 150.0)
        assert (ante["window_start"], ante["window_end"]) == ("2026-10-05", "2026-10-06")
        assert ante["known_at_filing"] is True and ante["held_at_filing"] is True and ante["observed_at_filing"] == 157.5
        assert lookup.calls == [("total_protein_g", "2026-10-05", "2026-10-06")]
        assert spec["branches"][0]["outcome"]["metric"] == "recovery_score"

    def test_a_known_antecedent_that_did_not_hold_is_recorded_not_rejected(self):
        v = fr.validate_filing(
            self.CALL, _dir("recovery_score", "up"), "2026-10-15", antecedent_readings=_readings([("2026-10-05", 120.0)])
        )
        assert v["filing"]["reason"] == "condition_known_false"
        assert v["filing"]["branches"][0]["antecedent"]["held_at_filing"] is False

    def test_a_known_antecedent_with_no_reader_is_left_for_the_grader(self):
        v = fr.validate_filing(self.CALL, _dir("recovery_score", "up"), "2026-10-15")
        assert v["gradeable"]
        assert v["eval_spec"]["branches"][0]["antecedent"]["held_at_filing"] is None

    def test_a_two_branch_forecast_with_measurable_branches_files_both(self):
        claim = (
            "If protein averages at least 170 g this week, recovery score will rise over the next two weeks; "
            "if not, recovery score will fall over the next two weeks."
        )
        v = fr.validate_filing(claim, _dir("recovery_score", "up"), "2026-11-03")
        assert v["gradeable"], v["filing"]
        b = v["eval_spec"]["branches"]
        assert len(b) == 2 and v["filing"]["branch_count"] == 2
        assert (b[0]["antecedent"]["op"], b[1]["antecedent"]["op"]) == ("gte", "lt")
        assert b[0]["antecedent"]["window_end"] == b[1]["antecedent"]["window_end"] == "2026-11-09"
        assert (b[0]["outcome"]["condition"], b[1]["outcome"]["condition"]) == ("up", "down")

    def test_a_two_branch_forecast_with_an_opinion_branch_is_an_observation(self):
        claim = "If protein averages at least 170 g this week, recovery score will rise over the next two weeks; if not, the protein hypothesis fails."
        assert not fr.validate_filing(claim, _dir("recovery_score", "up"), "2026-11-03")["gradeable"]

    def test_a_condition_with_no_threshold_is_not_checkable(self):
        v = fr.validate_filing(
            "If carb reduction is recommended without simultaneous protein escalation, recovery will decline within 4–6 days.",
            _dir("recovery_score", "down", 4.0),
            "2026-09-20",
        )
        assert v["filing"]["reason"] == "condition_not_checkable"

    def test_a_run_condition_is_stored_as_a_run(self):
        v = fr.validate_filing(
            "Once protein holds at 145 g or above for three consecutive days, deep sleep will improve over the next two weeks.",
            _dir("deep_pct", "up"),
            "2026-11-03",
        )
        ante = v["eval_spec"]["branches"][0]["antecedent"]
        assert (ante["aggregate"], ante["run_days"], ante["op"], ante["threshold"]) == ("run", 3, "gte", 145.0)


class TestGrader:
    """coach.conditional_branches — the antecedent tested on its window; only the held branch graded."""

    @staticmethod
    def _spec(claim, day, lookup=None):
        return fr.validate_filing(claim, _dir("recovery_score", "up"), day, antecedent_readings=lookup)["eval_spec"]

    @staticmethod
    def _io(protein_rows):
        def get_source_data(source, cache, end, lookback_days=30, include_pilot=False):
            get_source_data.calls += 1
            return [{"date": d, "total_protein_g": v} for d, v in protein_rows]

        get_source_data.calls = 0
        return get_source_data, lambda records, metric: [(r["date"], r[metric]) for r in records if metric in r]

    CLAIM = (
        "If protein averages at least 170 g this week, recovery score will rise over the next two weeks; "
        "if not, recovery score will fall over the next two weeks."
    )

    def test_the_branch_whose_condition_held_is_the_one_graded(self):
        spec = self._spec(self.CLAIM, "2026-11-03")
        gsd, ems = self._io([("2026-11-0%d" % d, 150.0) for d in range(3, 10)])
        graded = []
        graders = {"directional": lambda p, s, c, t: graded.append(s) or {"status": "confirmed", "reason": "moved", "beats_null": True}}
        r = cb.grade({"created_date": "2026-11-03"}, spec, {}, "2026-11-20", gsd, ems, graders)
        assert r["status"] == "confirmed" and r["branch_graded"] == 1
        assert graded[0]["condition"] == "down" and r["rule_spec"] is graded[0]
        assert "Condition held" in r["reason"]

    def test_no_condition_held_means_never_tested_so_expired(self):
        spec = self._spec("If protein averages at least 170 g this week, recovery score will rise over the next two weeks.", "2026-11-03")
        gsd, ems = self._io([("2026-11-04", 150.0)])
        r = cb.grade({"created_date": "2026-11-03"}, spec, {}, "2026-11-20", gsd, ems, {"directional": None})
        assert r["status"] == "expired"

    def test_an_open_condition_window_is_pending(self):
        spec = self._spec(self.CLAIM, "2026-11-03")
        gsd, ems = self._io([])
        assert cb.grade({"created_date": "2026-11-03"}, spec, {}, "2026-11-05", gsd, ems, {})["status"] == "pending"

    def test_a_verdict_recorded_at_filing_is_never_re_derived(self):
        claim = "If protein averaged above 150 g on October 5-6, recovery score will rise over the next two weeks."
        spec = self._spec(claim, "2026-10-15", _readings([("2026-10-05", 160.0)]))
        gsd, ems = self._io([("2026-10-05", 10.0)])  # a later read that would say "did not hold"
        graders = {"directional": lambda p, s, c, t: {"status": "refuted", "reason": "flat", "beats_null": False}}
        r = cb.grade({"created_date": "2026-10-15"}, spec, {}, "2026-11-01", gsd, ems, graders)
        assert r["status"] == "refuted" and gsd.calls == 0

    def test_the_evaluator_routes_a_branched_conditional_here(self, monkeypatch):
        import coach_prediction_evaluator as ev

        seen = {}
        monkeypatch.setattr(ev.conditional_branches, "grade", lambda *a: seen.setdefault("args", a) and {"status": "pending"})
        spec = self._spec(self.CLAIM, "2026-11-03")
        ev._evaluate_conditional({"created_date": "2026-11-03"}, spec, {}, "2026-11-20")
        assert seen["args"][1] is spec
        assert set(seen["args"][-1]) == {"directional", "point", "machine"}


class TestEveryPathFiles:
    def test_the_record_builder_runs_the_rules_when_its_caller_did_not(self):
        rec = pe.build_prediction_record("sleep_coach", "2026-11-03", "HRV will rise.", _dir("hrv", "up"), 0.6, "observational")
        assert rec["status"] == pe.OBSERVATION_STATUS and rec["filing"]["reason"] == "no_stated_window"
        assert rec["filing_rules_version"] == fr.FILING_RULES_VERSION

    def test_a_filed_conditional_is_pending_and_deterministic(self):
        v = fr.validate_filing(TestGrader.CLAIM, _dir("recovery_score", "up"), "2026-11-03")
        rec = pe.build_prediction_record(
            "explorer_coach", "2026-11-03", TestGrader.CLAIM, v["eval_spec"], 0.6, "observational", filing=v["filing"]
        )
        assert (rec["status"], rec["gradeable_by"]) == ("pending", pe.GRADEABLE_BY_DETERMINISTIC)
        assert rec["evaluation"]["type"] == "conditional"

    def test_the_updater_files_through_the_rules(self):
        src = open(os.path.join(_REPO, "lambdas", "coach", "coach_state_updater.py")).read()
        assert re.search(r"_validate_filing\(\s*claim,\s*eval_spec,\s*generation_date", src)
        assert 'filing=_filed["filing"]' in src

    def test_every_prediction_writer_is_routed_or_named(self):
        """Guard the SET: every module that builds a PREDICTION# sort key for a write is either routed
        through the filing rules or named here with the reason it is not."""
        routed = {
            "lambdas/coach/prediction_emission.py": "build_prediction_record runs/stamps the rules (coach_state_updater files through it)",
            "lambdas/privacy/diary_claims.py": "admit_claim refuses a claim that fails the rules",
        }
        named = {
            "lambdas/coach/dispute_docket.py": "a docket position: written already resolved from a code-validated criterion (validate_criterion)",
            "lambdas/coach/advice_links.py": "a key builder for links to an existing call; writes no prediction",
            "lambdas/web/trail_corrections.py": "reads an existing row by key; writes no prediction",
            "deploy/seed_genesis_preregistration.py": "the one-shot genesis pre-registration seeder; the experiment is terminal (no reset)",
        }
        pat = re.compile(r"""["']sk["']\s*:\s*f?["']PREDICTION#|SK_PREFIX\s*=\s*["']PREDICTION#""")
        found = set()
        for top in ("lambdas", "mcp", "scripts", "deploy"):
            for root, _dirs, files in os.walk(os.path.join(_REPO, top)):
                if "archive" in root:
                    continue
                for f in files:
                    if f.endswith(".py"):
                        path = os.path.join(root, f)
                        if pat.search(open(path, encoding="utf-8").read()):
                            found.add(os.path.relpath(path, _REPO))
        assert found == set(routed) | set(named), sorted(found ^ (set(routed) | set(named)))
        for path in routed:
            assert "filing_rules" in open(os.path.join(_REPO, path)).read(), path


_IMPORTS_RULES = re.compile(
    r"^\s*(?:from\s+[\w.]*\s+import\s+[^\n]*\bfiling_rules\b|from\s+[\w.]*filing_rules\s+import|import\s+[\w.]*filing_rules)", re.M
)


class TestNoRetrospectiveInvention:
    """(d) the rules run at filing only — they never touch an existing row."""

    SRC = os.path.join(_REPO, "lambdas", "coach", "filing_rules.py")

    def test_the_rules_module_is_pure(self):
        tree = ast.parse(open(self.SRC).read())
        imported = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert not any(m.split(".")[0] in ("boto3", "botocore") for m in imported)
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert not names & {"put_item", "update_item", "delete_item", "query", "scan", "get_item", "batch_writer"}

    def test_validate_filing_never_mutates_its_input(self):
        spec = _dir("recovery_score", "up")
        before = copy.deepcopy(spec)
        fr.validate_filing(TestGrader.CLAIM, spec, "2026-11-03")
        fr.validate_filing(OPINIONS[0][1], spec, "2026-10-15")
        assert spec == before

    def test_only_filing_paths_import_the_rules(self):
        """No grader, re-grade or correction path can re-specify a stored row with these rules."""
        allowed = {
            "lambdas/coach/filing_rules.py",
            "lambdas/coach/prediction_emission.py",
            "lambdas/coach/coach_state_updater.py",
            "lambdas/privacy/diary_claims.py",
        }
        importers = set()
        for top in ("lambdas", "mcp", "scripts", "deploy"):
            for root, _dirs, files in os.walk(os.path.join(_REPO, top)):
                for f in files:
                    if f.endswith(".py"):
                        path = os.path.join(root, f)
                        if _IMPORTS_RULES.search(open(path, encoding="utf-8").read()):
                            importers.add(os.path.relpath(path, _REPO))
        assert importers <= allowed, sorted(importers - allowed)
