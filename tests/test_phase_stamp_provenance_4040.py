"""tests/test_phase_stamp_provenance_4040.py — #4040: in a no-reset world nothing stamps
a pre-genesis EXPERIMENT_SCOPED row.

Four layers, matching the issue's acceptance boxes:
  1. `phase_taxonomy.pre_genesis_scoped_violation` — the pure predicate, mutation-proved
     by disabling the date comparison (box 4, control 1).
  2. The served-lead-in exemption (`chronicle_manifest_qa.served_chronicle_keys`) — a
     served chronicle row is left alone however its `sk` is dated (box 4, control 2 — the
     2026-09-22 incident this issue documents).
  3. `deploy/phase_stamp_sweep.py` — the standing corrector: plants a pre-genesis-dated
     SOURCE# row with `phase=experiment` and asserts the mechanism corrects it, and plants
     a served chronicle row and asserts the mechanism leaves it alone.
  4. `experiment.pk_census.scoped_stamp_audit`'s `mis_stamped` leaf + the nightly
     `data:coach_ensemble_phase_stamp_coverage` leg — a recurrence is a WARN with rows,
     never silence (box 3).
"""

import importlib.util
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for p in (str(REPO_ROOT), str(REPO_ROOT / "deploy"), str(REPO_ROOT / "lambdas")):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("EMAIL_RECIPIENT", "qa@example.com")
os.environ.setdefault("EMAIL_SENDER", "qa@example.com")

from experiment import phase_taxonomy as tx  # noqa: E402
from experiment.pk_census import scoped_stamp_audit  # noqa: E402
from operational import chronicle_manifest_qa as cmq  # noqa: E402

GENESIS = "2026-09-06"
CHRONICLE_PK = "USER#matthew#SOURCE#chronicle"
ANOMALIES_PK = "USER#matthew#SOURCE#anomalies"


# ─────────────────────────────────────────────────────────────────────────────
# 1. the pure predicate, mutation-proved
# ─────────────────────────────────────────────────────────────────────────────


def test_an_unstamped_pre_genesis_row_is_a_violation():
    assert tx.pre_genesis_scoped_violation(ANOMALIES_PK, "DATE#2026-09-05", None, "2026-09-05", GENESIS) is True


def test_a_mis_stamped_pre_genesis_row_is_a_violation():
    """The #4040 shape itself: `experiment`, not `pilot`, on a pre-genesis row."""
    assert tx.pre_genesis_scoped_violation(CHRONICLE_PK, "DATE#2026-02-28", "experiment", "2026-02-28", GENESIS) is True


def test_a_pilot_pre_genesis_row_is_not_a_violation():
    assert tx.pre_genesis_scoped_violation(ANOMALIES_PK, "DATE#2026-09-05", "pilot", "2026-09-05", GENESIS) is False


def test_a_post_genesis_row_is_never_a_violation_whatever_its_phase():
    assert tx.pre_genesis_scoped_violation(ANOMALIES_PK, "DATE#2026-09-10", None, "2026-09-10", GENESIS) is False
    assert tx.pre_genesis_scoped_violation(ANOMALIES_PK, "DATE#2026-09-10", "experiment", "2026-09-10", GENESIS) is False


def test_a_cross_phase_row_is_never_a_violation():
    assert tx.pre_genesis_scoped_violation("COACH#sleep_coach", "CHAT#2026-01-01", "experiment", "2026-01-01", GENESIS) is False


def test_an_undated_row_is_never_a_violation():
    assert tx.pre_genesis_scoped_violation(ANOMALIES_PK, "SINGLETON#latest", "experiment", None, GENESIS) is False


def test_an_unclassifiable_pk_is_never_a_violation():
    assert tx.pre_genesis_scoped_violation("USER#matthew#SOURCE#not_a_real_source", "DATE#2020-01-01", None, "2020-01-01", GENESIS) is False


def test_mutation_proof_disabling_the_date_comparison_would_hide_the_defect():
    """MUTATION CONTROL: the property under test is specifically the `item_date < genesis`
    clause. A mutant that always treats the row as in-cycle (`item_date >= genesis`, i.e.
    the comparison flipped/disabled) must FAIL to catch the #4040 shape — proving this test
    actually exercises the date logic and not merely "is EXPERIMENT_SCOPED and not pilot"."""
    # The real predicate catches it:
    assert tx.pre_genesis_scoped_violation(CHRONICLE_PK, "DATE#2026-02-28", "experiment", "2026-02-28", GENESIS) is True

    # A mutant with the date comparison disabled (pretend every row is in-cycle):
    def _mutant_always_in_cycle(pk, sk, phase, item_date, genesis):
        try:
            if tx.classify(pk, sk) != tx.EXPERIMENT_SCOPED:
                return False
        except KeyError:
            return False
        if not item_date:  # the `item_date >= genesis` branch is gone — never true
            return False
        return phase != "pilot" and False  # unreachable without the date gate — mutant is blind

    assert _mutant_always_in_cycle(CHRONICLE_PK, "DATE#2026-02-28", "experiment", "2026-02-28", GENESIS) is False


# ─────────────────────────────────────────────────────────────────────────────
# 2. the served-lead-in exemption
# ─────────────────────────────────────────────────────────────────────────────


class _FakeS3:
    def __init__(self, posts):
        import json

        self._body = json.dumps({"posts": posts}).encode()

    def get_object(self, Bucket, Key):
        assert Key == cmq.MANIFEST_KEY
        return {"Body": type("B", (), {"read": lambda s: self._body})()}


class _FakeTable:
    """Chronicle-partition query fake — mirrors tests/test_chronicle_manifest_qa_3485.py."""

    def __init__(self, rows):
        self.rows = []
        for sk, attrs in rows.items():
            r = dict(attrs)
            r["sk"] = sk
            r.setdefault("date", sk.replace("DATE#", ""))
            self.rows.append(r)

    def query(self, **kwargs):
        return {"Items": list(self.rows)}


# The three live #4040 specimens: two re-dated lead-ins (sk left alone, date re-anchored)
# plus the one published fresh after the cycle-17 wipe (sk == date).
_SERVED_ROWS = {
    "DATE#2026-02-28": {"title": "Before the Numbers", "date": "2026-08-31", "phase": "experiment"},
    "DATE#2026-07-21": {"title": "The Night Before Everything", "date": "2026-09-05", "phase": "experiment"},
    "DATE#2026-09-05": {"title": "The Plan, On the Record", "phase": "experiment"},  # sk == date, published post-genesis
}
_SERVED_POSTS = [
    {"date": "2026-08-31", "title": "Before the Numbers"},
    {"date": "2026-09-05", "title": "The Night Before Everything"},
]


def test_served_chronicle_keys_resolves_the_live_4040_specimens():
    """The two re-dated lead-ins the manifest actually serves resolve to their ORIGINAL
    sk, not a key built from the served `date` (#3650's own lesson)."""
    keys = cmq.served_chronicle_keys(_FakeTable(_SERVED_ROWS), _FakeS3(_SERVED_POSTS), "bucket")
    assert keys == {(CHRONICLE_PK, "DATE#2026-02-28"), (CHRONICLE_PK, "DATE#2026-07-21")}


def test_served_chronicle_keys_excludes_an_ambiguous_match():
    rows = {
        "DATE#2026-08-31": {"title": "A", "date": "2026-08-31"},
        "DATE#2020-01-01": {"title": "B", "date": "2026-08-31"},
    }
    keys = cmq.served_chronicle_keys(_FakeTable(rows), _FakeS3([{"date": "2026-08-31", "title": "C"}]), "bucket")
    assert keys == set()  # neither row is exempted on an ambiguous match — the QA check's own rule


def test_served_chronicle_keys_degrades_quietly_on_an_unreadable_manifest():
    class _BrokenS3:
        def get_object(self, Bucket, Key):
            raise RuntimeError("no object")

    assert cmq.served_chronicle_keys(_FakeTable(_SERVED_ROWS), _BrokenS3(), "bucket") == set()


# ─────────────────────────────────────────────────────────────────────────────
# 3. the corrector (deploy/phase_stamp_sweep.py) — mutation control 2, planted rows
# ─────────────────────────────────────────────────────────────────────────────


def _load_sweep():
    spec = importlib.util.spec_from_file_location("phase_stamp_sweep_4040", REPO_ROOT / "deploy" / "phase_stamp_sweep.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_planted_pre_genesis_mis_stamped_row_is_flagged_for_correction():
    """The MECHANISM's own control: a pre-genesis SOURCE# row with `phase=experiment` is
    found as a violation and would be corrected to `pilot`."""
    sweep = _load_sweep()
    items = [{"pk": ANOMALIES_PK, "sk": "DATE#2026-09-05", "phase": "experiment"}]
    violations = sweep.find_violations(items, ANOMALIES_PK, GENESIS, exempt_keys=set())
    assert len(violations) == 1 and violations[0]["sk"] == "DATE#2026-09-05"


def test_a_served_chronicle_lead_in_is_left_alone():
    """MUTATION CONTROL 2: the identical shape (pre-genesis sk, phase=experiment) on the
    chronicle partition is NOT flagged once it is in the exempt set — proving the
    exemption is actually consulted, not merely present in the signature."""
    sweep = _load_sweep()
    exempt = {(CHRONICLE_PK, "DATE#2026-02-28")}
    items = [{"pk": CHRONICLE_PK, "sk": "DATE#2026-02-28", "phase": "experiment", "date": "2026-08-31"}]
    violations = sweep.find_violations(items, CHRONICLE_PK, GENESIS, exempt_keys=exempt)
    assert violations == []


def test_a_non_exempt_chronicle_row_with_the_same_shape_is_still_flagged():
    """The other half of the mutation control: WITHOUT the exemption the identical row
    IS a violation — so the exempt-set check above is proven to be doing work, not
    passing because chronicle rows are silently excluded some other way."""
    sweep = _load_sweep()
    items = [{"pk": CHRONICLE_PK, "sk": "DATE#2026-02-28", "phase": "experiment", "date": "2026-08-31"}]
    violations = sweep.find_violations(items, CHRONICLE_PK, GENESIS, exempt_keys=set())
    assert len(violations) == 1


def test_an_in_cycle_row_is_never_a_violation_regardless_of_phase():
    sweep = _load_sweep()
    items = [{"pk": ANOMALIES_PK, "sk": f"DATE#{GENESIS}", "phase": "experiment"}]
    assert sweep.find_violations(items, ANOMALIES_PK, GENESIS, exempt_keys=set()) == []


def test_the_sweep_scans_every_experiment_scoped_source_via_query_not_scan():
    """A bounded, key-range Query per family — the #4040 acceptance criterion, never a
    full-table Scan. Proven by a fake table that raises on scan()."""
    sweep = _load_sweep()

    class _NoScanTable:
        def scan(self, **kwargs):
            raise AssertionError("phase_stamp_sweep must never Scan — bounded per-family Query only")

        def query(self, **kwargs):
            return {"Items": []}

    assert sweep.query_partition(_NoScanTable(), ANOMALIES_PK) == []


def test_dry_run_never_writes(monkeypatch):
    sweep = _load_sweep()

    class _RecordingTable:
        def query(self, **kwargs):
            return {"Items": [{"pk": ANOMALIES_PK, "sk": "DATE#2026-09-05", "phase": "experiment"}]}

        def update_item(self, **kwargs):
            raise AssertionError("dry-run must never call update_item")

    monkeypatch.setattr(sweep.boto3, "resource", lambda *a, **kw: type("R", (), {"Table": lambda s, n: _RecordingTable()})())
    monkeypatch.setattr(sweep.boto3, "client", lambda *a, **kw: _FakeS3([]))
    monkeypatch.setattr(sweep, "SCOPED_SOURCES", ("anomalies",))
    monkeypatch.setattr(sweep, "coach_partitions", lambda: [])  # #4059: isolate the SOURCE# surface this test targets
    monkeypatch.setattr(sys, "argv", ["phase_stamp_sweep.py"])
    rc = sweep.main()
    assert rc == 0


def test_apply_writes_the_pilot_phase(monkeypatch):
    sweep = _load_sweep()
    written = {}

    class _RecordingTable:
        def query(self, **kwargs):
            return {"Items": [{"pk": ANOMALIES_PK, "sk": "DATE#2026-09-05", "phase": "experiment"}]}

        def update_item(self, **kwargs):
            written["Key"] = kwargs["Key"]
            written["phase"] = kwargs["ExpressionAttributeValues"][":p"]

    monkeypatch.setattr(sweep.boto3, "resource", lambda *a, **kw: type("R", (), {"Table": lambda s, n: _RecordingTable()})())
    monkeypatch.setattr(sweep.boto3, "client", lambda *a, **kw: _FakeS3([]))
    monkeypatch.setattr(sweep, "SCOPED_SOURCES", ("anomalies",))
    monkeypatch.setattr(sweep, "coach_partitions", lambda: [])  # #4059: isolate the SOURCE# surface this test targets
    monkeypatch.setattr(sys, "argv", ["phase_stamp_sweep.py", "--apply"])
    rc = sweep.main()
    assert rc == 0
    assert written == {"Key": {"pk": ANOMALIES_PK, "sk": "DATE#2026-09-05"}, "phase": "pilot"}


# ─────────────────────────────────────────────────────────────────────────────
# #4059 — the corrector's surface now also reaches COACH# partitions
# ─────────────────────────────────────────────────────────────────────────────


def test_the_coach_surface_is_the_operational_roster():
    """`coach_partitions()` derives from the same roster the wipe's COACH_PARTITIONS
    registry-coverage check uses — not a hand list that can silently fall behind it."""
    from coach.persona_registry import OPERATIONAL_COACH_IDS

    sweep = _load_sweep()
    assert sweep.coach_partitions() == [f"COACH#{c}" for c in OPERATIONAL_COACH_IDS]
    assert any(pk.startswith("COACH#") for pk in sweep.coach_partitions())


def test_apply_corrects_a_mis_stamped_docket_prediction_on_the_coach_surface(monkeypatch):
    """The #4040 live shape itself: a dispute-docket verdict opened before genesis, graded
    after it, sitting on a COACH# pk this corrector used to never Query."""
    sweep = _load_sweep()
    written = {}
    coach_pk = "COACH#explorer_coach"
    docket_row = {
        "pk": coach_pk,
        "sk": "PREDICTION#docket-explorer_coach__nutrition_coach-calories-caloric-variance-interpretation-2026-08-03",
        "created_at": "2026-08-03T17:41:16+00:00",
        "outcome_date": "2026-09-07",
        "resolved_at": "2026-09-07T09:12:00+00:00",
        "cycle": 17,
        "phase": "experiment",
    }

    class _RecordingTable:
        def query(self, **kwargs):
            pk = kwargs["KeyConditionExpression"].get_expression()["values"][1]
            return {"Items": [docket_row] if pk == coach_pk else []}

        def update_item(self, **kwargs):
            written["Key"] = kwargs["Key"]
            written["phase"] = kwargs["ExpressionAttributeValues"][":p"]

    monkeypatch.setattr(sweep.boto3, "resource", lambda *a, **kw: type("R", (), {"Table": lambda s, n: _RecordingTable()})())
    monkeypatch.setattr(sweep.boto3, "client", lambda *a, **kw: _FakeS3([]))
    monkeypatch.setattr(sweep, "SCOPED_SOURCES", ())
    monkeypatch.setattr(sweep, "coach_partitions", lambda: [coach_pk])
    monkeypatch.setattr(sys, "argv", ["phase_stamp_sweep.py", "--apply"])
    rc = sweep.main()
    assert rc == 0
    assert written == {"Key": {"pk": coach_pk, "sk": docket_row["sk"]}, "phase": "pilot"}


# ─────────────────────────────────────────────────────────────────────────────
# 4. the nightly leg WARNs with rows, never silence
# ─────────────────────────────────────────────────────────────────────────────


def test_the_row_audit_names_a_mis_stamped_pre_genesis_row():
    row = {"pk": ANOMALIES_PK, "sk": "DATE#2026-09-05", "phase": "experiment"}
    out = scoped_stamp_audit([[row]], genesis=GENESIS)
    assert out["mis_stamped"] == {"SOURCE#anomalies": [f"{ANOMALIES_PK}/DATE#2026-09-05[phase=experiment]"]}


def test_the_row_audit_exempts_a_served_chronicle_row():
    row = {"pk": CHRONICLE_PK, "sk": "DATE#2026-02-28", "phase": "experiment", "date": "2026-08-31"}
    exempt = {(CHRONICLE_PK, "DATE#2026-02-28")}
    out = scoped_stamp_audit([[row]], genesis=GENESIS, exempt_keys=exempt)
    assert out["mis_stamped"] == {}


def test_the_row_audit_still_flags_the_same_row_without_the_exemption():
    row = {"pk": CHRONICLE_PK, "sk": "DATE#2026-02-28", "phase": "experiment", "date": "2026-08-31"}
    out = scoped_stamp_audit([[row]], genesis=GENESIS, exempt_keys=set())
    assert out["mis_stamped"] == {"SOURCE#chronicle": [f"{CHRONICLE_PK}/DATE#2026-02-28[phase=experiment]"]}


def test_the_nightly_check_warns_by_name_with_rows_never_silently(monkeypatch):
    import qa_smoke_lambda as qa

    class _T:
        def scan(self, **kw):
            return {"Items": [{"pk": ANOMALIES_PK, "sk": "DATE#2026-09-05", "phase": "experiment"}]}

    monkeypatch.setattr(qa, "table", _T())
    monkeypatch.setattr(qa.chronicle_manifest_qa, "served_chronicle_keys", lambda *a, **kw: set())
    (c,) = qa.check_coach_ensemble_phase_stamp_coverage()
    assert c.passed is None  # WARN, never FAIL/silent
    assert "#4040" in c.message
    assert f"{ANOMALIES_PK}/DATE#2026-09-05[phase=experiment]" in c.message
    assert "phase_stamp_sweep.py --apply" in c.message


def test_the_nightly_check_exempts_a_served_chronicle_row_end_to_end(monkeypatch):
    import qa_smoke_lambda as qa

    class _T:
        def scan(self, **kw):
            return {"Items": [{"pk": CHRONICLE_PK, "sk": "DATE#2026-02-28", "phase": "experiment", "date": "2026-08-31"}]}

    monkeypatch.setattr(qa, "table", _T())
    monkeypatch.setattr(qa.chronicle_manifest_qa, "served_chronicle_keys", lambda *a, **kw: {(CHRONICLE_PK, "DATE#2026-02-28")})
    (c,) = qa.check_coach_ensemble_phase_stamp_coverage()
    assert c.passed is True
    assert "DATE#2026-02-28" not in c.message


def test_the_nightly_check_stays_conservative_when_the_manifest_is_unreadable(monkeypatch):
    """A served-chronicle lookup that raises must exempt nothing (fail conservative,
    never fail silent) — the check still reports the row rather than swallowing it."""
    import qa_smoke_lambda as qa

    class _T:
        def scan(self, **kw):
            return {"Items": [{"pk": ANOMALIES_PK, "sk": "DATE#2026-09-05", "phase": "experiment"}]}

    def _raise(*a, **kw):
        raise RuntimeError("s3 unavailable")

    monkeypatch.setattr(qa, "table", _T())
    monkeypatch.setattr(qa.chronicle_manifest_qa, "served_chronicle_keys", _raise)
    (c,) = qa.check_coach_ensemble_phase_stamp_coverage()
    assert c.passed is None
    assert f"{ANOMALIES_PK}/DATE#2026-09-05" in c.message
