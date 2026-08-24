"""tests/test_input_manifest_contract_3049.py — #3049 / DIL-024, the
source-completeness contract for the five compute Lambdas.

WHAT #3049 ASKS FOR, AND WHERE EACH ACCEPTANCE LINE IS PINNED HERE
------------------------------------------------------------------
* "Each compute lambda records a per-run source-freshness manifest alongside its
  output"  ->  ``TestDeclarations`` (the set of five, resolved against
  ``cdk/stacks/compute_stack.py``) + ``TestChokepoint`` (the real
  ``compute_metadata.tag_record``, which is where every compute write picks the
  manifest up, for every declared output partition).
* "Outputs publish a partial-status per ADR-104 when any input was stale/missing"
  ->  ``TestRollup``, both directions.
* "Contract test injects a stale source and asserts the qualified output — a
  delayed connector cannot produce an unqualified complete-day score"  ->
  ``TestDelayedConnector``, which drives the real ``manifest_for`` against a fake
  table holding one late partition — for EACH of the five, not just one.
* "PT/DST boundary test on the freshness judgment"  ->  ``TestPacificFrame``,
  which pins BOTH US transitions and asserts the verdict FLIPS relative to the
  naive ``days * 24`` form at a threshold chosen to sit in the one-hour gap.
* "NO event-driven rebuild (crons stay — scope guard)"  ->
  ``test_no_new_event_wiring_in_compute_stack``.

MUTATION PROOF (both directions, as the issue asks)
---------------------------------------------------
Performed by hand against this file and reverted immediately; not a permanent
test, because both mutations break real production code. Observed, not predicted:

1. ``build_input_manifest``'s ``if degraded: status = MANIFEST_PARTIAL`` branch
   neutered to ``if False:`` (the contract can no longer say "partial") -> **6
   failed / 48 passed**, including both ``TestDelayedConnector`` qualification
   cases, all three ``TestRollup`` degradation cases, and
   ``TestChokepoint::test_tag_record_stamps_a_declared_output``.
2. ``judge_source``'s ``if age < threshold_hours: return STATUS_FRESH`` neutered
   to ``if False:`` (the contract can no longer say "complete") -> **10 failed /
   44 passed**, including ``TestRollup::test_all_fresh_inputs_make_the_run_complete``,
   ``TestDelayedConnector::test_the_same_run_with_every_connector_current_is_unqualified``
   and ``TestPacificFrame::test_spring_forward_verdict_flips_against_the_naive_form``.
3. ``compute_metadata.tag_record``'s ``stamp_output(record, source_id)`` call
   removed (the manifest is computed but never reaches a record) -> **2 failed /
   52 passed**, both in ``TestChokepoint``. This one matters on its own: the
   first two mutations prove the JUDGMENT is real, and only this one proves it is
   actually WIRED to the write.

No mutation is caught by another's headline test, which is the point: the
contract has to be able to say "complete" as well as "partial" as well as reach
the record, or it is decoration that always cries wolf.

WHAT THESE TESTS ALREADY CAUGHT
-------------------------------
``TestPacificFrame`` failed on the first run against a correct-looking
``age_hours`` that read ``now.astimezone(PACIFIC) - pacific_day_start(day)``.
Python's ``datetime.__sub__`` ignores tzinfo when both operands are aware and
share the same ``tzinfo`` OBJECT — which both of those do — so it silently
returned the naive wall-clock answer (47h across both 2026 transitions, where
the real elapsed times are 46h and 48h). The fix normalises both sides to UTC
first. That is the DST bug this acceptance line is for, found in this module's
own first draft.

TIME IS FROZEN EVERYWHERE. No fixture date is ever combined with the real clock —
every judgment in this file is driven by an explicit ``now=`` (the four
``*_behavior.py`` compute-test siblings' standing rule).
"""

import ast
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_LAMBDAS = os.path.join(_REPO, "lambdas")

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")

for _p in (_LAMBDAS,):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common import input_manifest as im  # noqa: E402
from common.pacific_time import PACIFIC  # noqa: E402
from ingestion.source_registry import DEFAULT_STALE_HOURS, SOURCE_REGISTRY  # noqa: E402

_COMPUTE_STACK = os.path.join(_REPO, "cdk", "stacks", "compute_stack.py")


def _pt(y, m, d, hh=0, mm=0):
    """An aware Pacific instant — the only way this file names a time."""
    return datetime(y, m, d, hh, mm, tzinfo=PACIFIC)


class _FakeTable:
    """DDB ``Table`` stand-in that answers "newest DATE# row on this partition".

    Deliberately not a MagicMock: ``latest_source_day`` must terminate, and a
    partition the fixture did not populate must answer EMPTY (the ``missing``
    case) rather than a truthy mock. ``raise_for`` makes one partition
    unreadable so the ``unknown`` path is exercised on the real code path.
    """

    def __init__(self, latest_by_source=None, raise_for=()):
        self.latest = dict(latest_by_source or {})
        self.raise_for = set(raise_for)
        self.queries = []
        self.puts = []

    def query(self, **kwargs):
        self.queries.append(kwargs)
        expr = kwargs.get("KeyConditionExpression")
        # The pk value lives inside the boto3 condition object; pull it back out
        # the same way the real query would resolve it.
        pk = None
        for cond in getattr(expr, "_values", ()):
            values = getattr(cond, "_values", ())
            if len(values) == 2 and isinstance(values[1], str) and values[1].startswith("USER#"):
                pk = values[1]
        source = pk.rsplit("#", 1)[-1] if pk else None
        if source in self.raise_for:
            raise RuntimeError("simulated partition read failure")
        day = self.latest.get(source)
        return {"Items": [{"sk": f"DATE#{day}"}] if day else []}

    def put_item(self, Item=None, **kwargs):
        self.puts.append(Item)
        return {}


# ══════════════════════════════════════════════════════════════════════════════
# The declarations — guard the SET, not the instance
# ══════════════════════════════════════════════════════════════════════════════

#: The five Lambdas #3049 names, by CDK function_name.
EXPECTED_COMPUTE_IDS = {
    "character-sheet-compute",
    "adaptive-mode-compute",
    "daily-metrics-compute",
    "daily-insight-compute",
    "hypothesis-engine",
}


def _compute_stack_function_names():
    """Every ``function_name=`` literal in cdk/stacks/compute_stack.py."""
    tree = ast.parse(open(_COMPUTE_STACK, encoding="utf-8").read())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "function_name" and isinstance(node.value, ast.Constant):
            names.add(node.value.value)
    return names


class TestDeclarations:
    def test_the_declared_set_is_exactly_the_five_the_issue_names(self):
        assert set(im.COMPUTE_INPUTS) == EXPECTED_COMPUTE_IDS

    def test_every_declared_id_is_a_real_lambda_in_compute_stack(self):
        """A rename in CDK must not silently orphan a manifest declaration."""
        live = _compute_stack_function_names()
        assert live, "compute_stack.py yielded no function_name literals — the scan broke, not the stack"
        missing = sorted(EXPECTED_COMPUTE_IDS - live)
        assert not missing, f"declared compute ids not present in compute_stack.py: {missing}"

    def test_every_declared_input_is_a_registry_source(self):
        """The manifest can only judge what the registry states a cadence for."""
        for compute_id, sources in im.COMPUTE_INPUTS.items():
            for source in sources:
                assert source in SOURCE_REGISTRY, f"{compute_id} declares unknown source '{source}'"

    def test_no_lambda_declares_an_empty_input_set(self):
        for compute_id, sources in im.COMPUTE_INPUTS.items():
            assert sources, f"{compute_id} declares no inputs — that reads as 'unknown', never 'complete'"

    def test_thresholds_are_derived_from_the_registry_never_restated(self):
        """#2003 class: the manifest's threshold for a source IS the registry's."""
        for source in sorted({s for srcs in im.COMPUTE_INPUTS.values() for s in srcs}):
            override = SOURCE_REGISTRY[source].get("stale_hours")
            expected = int(override if override is not None else DEFAULT_STALE_HOURS)
            assert im.stale_after_hours(source) == expected

    def test_no_hardcoded_hour_threshold_lives_in_the_module(self):
        """Fail-closed to `unknown` means there is no fallback constant to drift.

        An unknown source id has no cadence anywhere, so the honest answer is
        None — not 48, not 24, not any number this module invented.
        """
        assert im.stale_after_hours("a-source-that-does-not-exist") is None

    def test_derived_compute_partitions_are_not_declared_as_inputs(self):
        """Compute OUTPUTS have no registry cadence; declaring one would force a
        second threshold table into existence. Scope note, pinned."""
        derived = {"computed_metrics", "habit_scores", "day_grade", "computed_insights", "character_sheet", "engagement_state"}
        for compute_id, sources in im.COMPUTE_INPUTS.items():
            overlap = derived & set(sources)
            assert not overlap, f"{compute_id} declares derived partition(s) {sorted(overlap)}"


# ══════════════════════════════════════════════════════════════════════════════
# The per-source judgment
# ══════════════════════════════════════════════════════════════════════════════


class TestJudgeSource:
    NOW = _pt(2026, 8, 24, 9, 30)  # a normal (non-transition) Pacific morning

    def test_recent_day_is_fresh(self):
        status, age = im.judge_source("2026-08-24", now=self.NOW, threshold_hours=48)
        assert status == im.STATUS_FRESH
        assert age == pytest.approx(9.5)

    def test_day_past_its_threshold_is_stale(self):
        status, age = im.judge_source("2026-08-21", now=self.NOW, threshold_hours=48)
        assert status == im.STATUS_STALE
        assert age == pytest.approx(81.5)

    def test_no_row_at_all_is_missing(self):
        assert im.judge_source(None, now=self.NOW, threshold_hours=48) == (im.STATUS_MISSING, None)

    def test_a_paused_source_is_never_stale(self):
        """ADR-074 Garmin: off by design must not qualify anybody's output."""
        status, _ = im.judge_source("2026-01-01", now=self.NOW, threshold_hours=48, paused=True)
        assert status == im.STATUS_PAUSED

    def test_a_paused_source_with_fresh_data_is_fresh(self):
        """Freshness-first, exactly as ingestion.source_state resolves it — a
        re-enabled source flips back with no second edit anywhere."""
        status, _ = im.judge_source("2026-08-24", now=self.NOW, threshold_hours=48, paused=True)
        assert status == im.STATUS_FRESH

    def test_an_unjudgeable_threshold_is_unknown_not_fresh(self):
        assert im.judge_source("2026-08-24", now=self.NOW, threshold_hours=None) == (im.STATUS_UNKNOWN, None)

    def test_an_unparseable_day_is_unknown_not_fresh(self):
        assert im.judge_source("not-a-date", now=self.NOW, threshold_hours=48) == (im.STATUS_UNKNOWN, None)


# ══════════════════════════════════════════════════════════════════════════════
# The Pacific frame — the #3049 DST acceptance line
# ══════════════════════════════════════════════════════════════════════════════


def _naive_age_hours(latest_day, now):
    """The WRONG form this module refuses to use, written out so the tests can
    demonstrate that it actually disagrees rather than assert it in prose:
    whole calendar days times a flat 24, plus the wall-clock hours since midnight.
    """
    from datetime import date

    latest = date.fromisoformat(latest_day)
    return (now.date() - latest).days * 24 + now.hour + now.minute / 60.0


class TestPacificFrame:
    """A US DST transition makes a Pacific calendar day 23 or 25 hours long. The
    manifest measures REAL elapsed hours; ``days * 24`` does not. The gap is one
    hour, twice a year, on a threshold denominated in hours — enough to flip a
    verdict silently, which is the #2506/#2675 class this platform keeps paying
    for.
    """

    # 2026-03-08 02:00 PST -> 03:00 PDT (spring forward; that day is 23h long)
    SPRING_LATEST = "2026-03-08"
    SPRING_NOW = _pt(2026, 3, 9, 23, 0)

    # 2026-11-01 02:00 PDT -> 01:00 PST (fall back; that day is 25h long)
    FALL_LATEST = "2026-11-01"
    FALL_NOW = _pt(2026, 11, 2, 23, 0)

    def test_spring_forward_age_is_real_elapsed_hours(self):
        assert im.age_hours(self.SPRING_LATEST, self.SPRING_NOW) == pytest.approx(46.0)
        assert _naive_age_hours(self.SPRING_LATEST, self.SPRING_NOW) == pytest.approx(47.0)

    def test_fall_back_age_is_real_elapsed_hours(self):
        assert im.age_hours(self.FALL_LATEST, self.FALL_NOW) == pytest.approx(48.0)
        assert _naive_age_hours(self.FALL_LATEST, self.FALL_NOW) == pytest.approx(47.0)

    def test_spring_forward_verdict_flips_against_the_naive_form(self):
        """At a 47h threshold the Pacific frame says fresh (46h elapsed) where
        the naive form says stale (47h). Real hours win."""
        status, age = im.judge_source(self.SPRING_LATEST, now=self.SPRING_NOW, threshold_hours=47)
        assert status == im.STATUS_FRESH
        assert age < 47
        assert _naive_age_hours(self.SPRING_LATEST, self.SPRING_NOW) >= 47

    def test_fall_back_verdict_flips_against_the_naive_form(self):
        """At the registry DEFAULT (48h) the Pacific frame says stale (48h
        elapsed) where the naive form would still call it fresh (47h)."""
        status, age = im.judge_source(self.FALL_LATEST, now=self.FALL_NOW, threshold_hours=DEFAULT_STALE_HOURS)
        assert status == im.STATUS_STALE
        assert age >= DEFAULT_STALE_HOURS
        assert _naive_age_hours(self.FALL_LATEST, self.FALL_NOW) < DEFAULT_STALE_HOURS

    def test_day_start_is_pacific_midnight_on_both_sides_of_a_transition(self):
        assert im.pacific_day_start("2026-03-08").utcoffset().total_seconds() == -8 * 3600
        assert im.pacific_day_start("2026-03-09").utcoffset().total_seconds() == -7 * 3600

    def test_as_of_day_defaults_to_the_pacific_day_not_the_utc_one(self, monkeypatch):
        """A PT-evening instant where the two calendars disagree (#2813 class).

        The standing sweep drives this too, via the ``pt_day_contract``
        registration; pinned here as well so this module's own file states the
        contract it depends on.
        """
        evening_pt = _pt(2026, 8, 24, 18, 30)
        assert evening_pt.astimezone(timezone.utc).date().isoformat() == "2026-08-25"

        class _Frozen(datetime):
            @classmethod
            def now(cls, tz=None):
                return evening_pt.astimezone(tz) if tz else evening_pt.replace(tzinfo=None)

        monkeypatch.setattr("common.pacific_time.datetime", _Frozen)
        manifest = im.build_input_manifest(("whoop",), table=_FakeTable({"whoop": "2026-08-24"}), now=evening_pt)
        assert manifest["as_of_day"] == "2026-08-24"


# ══════════════════════════════════════════════════════════════════════════════
# The roll-up — both directions
# ══════════════════════════════════════════════════════════════════════════════


class TestRollup:
    NOW = _pt(2026, 8, 24, 9, 40)
    SOURCES = ("whoop", "macrofactor", "withings")

    def _table(self, **latest):
        return _FakeTable(latest)

    def test_all_fresh_inputs_make_the_run_complete(self):
        manifest = im.build_input_manifest(
            self.SOURCES,
            table=self._table(whoop="2026-08-24", macrofactor="2026-08-23", withings="2026-08-22"),
            now=self.NOW,
        )
        assert manifest["status"] == im.MANIFEST_COMPLETE
        assert manifest["complete"] is True
        assert manifest["degraded"] == []
        assert im.manifest_note(manifest) is None

    def test_a_stale_input_makes_the_run_partial(self):
        manifest = im.build_input_manifest(
            self.SOURCES,
            # macrofactor's registry threshold is 96h; 2026-08-15 is ~226h old.
            table=self._table(whoop="2026-08-24", macrofactor="2026-08-15", withings="2026-08-22"),
            now=self.NOW,
        )
        assert manifest["status"] == im.MANIFEST_PARTIAL
        assert manifest["complete"] is False
        assert manifest["degraded"] == ["macrofactor"]
        assert manifest["sources"]["macrofactor"]["status"] == im.STATUS_STALE
        assert "macrofactor" in im.manifest_note(manifest)

    def test_a_missing_input_makes_the_run_partial(self):
        manifest = im.build_input_manifest(
            self.SOURCES,
            table=self._table(whoop="2026-08-24", withings="2026-08-22"),  # no macrofactor partition
            now=self.NOW,
        )
        assert manifest["status"] == im.MANIFEST_PARTIAL
        assert manifest["degraded"] == ["macrofactor"]
        assert manifest["sources"]["macrofactor"]["status"] == im.STATUS_MISSING
        assert manifest["sources"]["macrofactor"]["latest_day"] is None

    def test_an_unreadable_input_is_unknown_and_never_complete(self):
        """ "I could not look" is not "everything was fine" — the mistake
        health/pillar_absence.py already refuses to make."""
        manifest = im.build_input_manifest(
            self.SOURCES,
            table=_FakeTable({"whoop": "2026-08-24", "withings": "2026-08-22"}, raise_for=("macrofactor",)),
            now=self.NOW,
        )
        assert manifest["status"] == im.MANIFEST_UNKNOWN
        assert manifest["complete"] is False
        assert manifest["unobserved"] == ["macrofactor"]
        assert "unreadable" in manifest["sources"]["macrofactor"]["reason"]

    def test_a_degraded_input_outranks_an_unobserved_one(self):
        """Partial is the stronger, more actionable claim — it must not be
        masked by an unrelated read failure."""
        manifest = im.build_input_manifest(
            ("whoop", "macrofactor", "withings"),
            table=_FakeTable({"whoop": "2026-08-24", "macrofactor": "2026-08-01"}, raise_for=("withings",)),
            now=self.NOW,
        )
        assert manifest["status"] == im.MANIFEST_PARTIAL

    def test_no_table_is_unknown_not_complete(self):
        manifest = im.build_input_manifest(self.SOURCES, table=None, now=self.NOW)
        assert manifest["status"] == im.MANIFEST_UNKNOWN
        assert sorted(manifest["unobserved"]) == sorted(self.SOURCES)

    def test_an_empty_declaration_is_unknown_not_complete(self):
        assert im.build_input_manifest((), table=_FakeTable(), now=self.NOW)["status"] == im.MANIFEST_UNKNOWN
        assert im.manifest_for("not-a-real-lambda", table=_FakeTable(), now=self.NOW)["status"] == im.MANIFEST_UNKNOWN

    def test_paused_garmin_does_not_qualify_the_hypothesis_engine(self):
        """The one declared source that is paused by design (ADR-074)."""
        assert SOURCE_REGISTRY["garmin"].get("paused") is True
        manifest = im.manifest_for(
            "hypothesis-engine",
            table=_FakeTable({s: "2026-08-24" for s in im.COMPUTE_INPUTS["hypothesis-engine"] if s != "garmin"}),
            now=self.NOW,
        )
        assert manifest["sources"]["garmin"]["status"] == im.STATUS_PAUSED
        assert "garmin" not in manifest["degraded"]
        assert manifest["status"] == im.MANIFEST_COMPLETE

    def test_the_manifest_is_ddb_safe(self):
        """boto3 rejects float. Every number on the way to put_item is Decimal/int."""
        manifest = im.build_input_manifest(
            self.SOURCES,
            table=self._table(whoop="2026-08-24", macrofactor="2026-08-15", withings="2026-08-22"),
            now=self.NOW,
        )

        def _walk(obj, path="manifest"):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    _walk(v, f"{path}.{k}")
            elif isinstance(obj, (list, tuple)):
                for i, v in enumerate(obj):
                    _walk(v, f"{path}[{i}]")
            else:
                assert not isinstance(obj, float), f"{path} is a float — DynamoDB will reject it"

        _walk(manifest)
        assert isinstance(manifest["sources"]["whoop"]["age_hours"], Decimal)

    def test_the_read_is_cross_phase(self):
        """#2080: a newest-first Limit:1 read with the phase filter attached goes
        blind after every experiment reset. The pipe's health is not an
        experiment-generation question."""
        table = self._table(whoop="2026-08-24")
        im.build_input_manifest(("whoop",), table=table, now=self.NOW)
        assert table.queries, "no query issued"
        assert "FilterExpression" not in table.queries[0]


# ══════════════════════════════════════════════════════════════════════════════
# attach + note
# ══════════════════════════════════════════════════════════════════════════════


class TestAttachAndNote:
    NOW = _pt(2026, 8, 24, 9, 40)

    def test_attach_stamps_both_fields(self):
        manifest = im.build_input_manifest(("whoop",), table=_FakeTable({"whoop": "2026-08-24"}), now=self.NOW)
        item = {"pk": "x", "sk": "y"}
        assert im.attach_input_manifest(item, manifest) is item
        assert item["input_status"] == im.MANIFEST_COMPLETE
        assert item["input_manifest"]["sources"]["whoop"]["status"] == im.STATUS_FRESH

    def test_attaching_nothing_leaves_the_record_unstamped(self):
        """Absent is a DIFFERENT and equally honest claim from `unknown`: it
        means the record predates the contract."""
        item = {"pk": "x"}
        im.attach_input_manifest(item, None)
        assert "input_status" not in item
        assert "input_manifest" not in item

    def test_note_is_silent_on_a_complete_run(self):
        assert im.manifest_note({"status": im.MANIFEST_COMPLETE}) is None
        assert im.manifest_note(None) is None

    def test_note_names_the_degraded_sources(self):
        note = im.manifest_note({"status": im.MANIFEST_PARTIAL, "degraded": ["hevy", "macrofactor"]})
        assert "hevy" in note and "macrofactor" in note
        assert "qualified" in note

    def test_note_for_unknown_refuses_to_narrate_absence_as_completeness(self):
        note = im.manifest_note({"status": im.MANIFEST_UNKNOWN, "unobserved": ["whoop"]})
        assert "Absence of evidence" in note


# ══════════════════════════════════════════════════════════════════════════════
# The write chokepoint — every declared output, through the real tag_record
# ══════════════════════════════════════════════════════════════════════════════


class TestChokepoint:
    """The manifest is stamped by ``compute_metadata.tag_record``, the one place
    every compute write already passes through. These drive the REAL tag_record.
    """

    def setup_method(self):
        im.reset_run_manifests()

    def teardown_method(self):
        im.reset_run_manifests()

    def test_every_declared_output_maps_to_a_declared_lambda(self):
        for source_id, compute_id in im.MANIFEST_OUTPUTS.items():
            assert compute_id in im.COMPUTE_INPUTS, f"output '{source_id}' maps to undeclared '{compute_id}'"

    def test_every_declared_lambda_has_at_least_one_stamped_output(self):
        """Guard the SET: a Lambda that declares inputs but stamps nothing would
        do all the work and publish none of it."""
        covered = set(im.MANIFEST_OUTPUTS.values())
        assert covered == set(im.COMPUTE_INPUTS), sorted(set(im.COMPUTE_INPUTS) - covered)

    def test_the_stamped_outputs_are_the_partitions_the_five_actually_write(self):
        """Pinned by name so a renamed partition cannot silently stop being stamped."""
        assert set(im.MANIFEST_OUTPUTS) == {
            "character_sheet",
            "adaptive_mode",
            "engagement_state",
            "computed_metrics",
            "day_grade",
            "habit_scores",
            "computed_insights",
            "hypotheses",
        }

    def test_a_side_record_is_not_stamped(self):
        """Receipts, achievements, ledgers and platform_memory share the
        chokepoint and must pass through untouched."""
        for source_id in ("character_receipt", "achievements", "milestones", "platform_memory", "whoop"):
            rec = {"pk": "x"}
            im.stamp_output(rec, source_id, table=_FakeTable({"whoop": "2026-08-24"}))
            assert "input_status" not in rec, source_id

    def test_tag_record_stamps_a_declared_output(self, monkeypatch):
        """Through the real ``compute_metadata.tag_record``."""
        from common import compute_metadata

        monkeypatch.setattr(compute_metadata, "_emit_write_metric", lambda *_a, **_k: None)
        monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "daily-metrics-compute")
        fresh = {s: "2026-08-23" for s in im.COMPUTE_INPUTS["daily-metrics-compute"]}
        fresh["whoop"] = "2026-08-01"  # the delayed connector
        monkeypatch.setattr(im, "_ambient_table", lambda: _FakeTable(fresh))

        item = compute_metadata.tag_record({"pk": "p", "sk": "DATE#2026-08-23"}, source_id="computed_metrics")
        assert item["input_status"] == im.MANIFEST_PARTIAL
        assert item["input_manifest"]["sources"]["whoop"]["status"] == im.STATUS_STALE

    def test_tag_record_is_inert_outside_a_lambda(self, monkeypatch):
        """A unit test calling tag_record must never become a DynamoDB round trip."""
        from common import compute_metadata

        monkeypatch.setattr(compute_metadata, "_emit_write_metric", lambda *_a, **_k: None)
        monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)

        def _explode():
            raise AssertionError("_ambient_table must not be reached outside a Lambda")

        monkeypatch.setattr(im, "_ambient_table", _explode)
        item = compute_metadata.tag_record({"pk": "p", "sk": "DATE#2026-08-23"}, source_id="computed_metrics")
        assert "input_status" not in item

    def test_a_broken_manifest_never_breaks_the_write(self, monkeypatch):
        from common import compute_metadata

        monkeypatch.setattr(compute_metadata, "_emit_write_metric", lambda *_a, **_k: None)
        monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "daily-metrics-compute")
        monkeypatch.setattr(im, "manifest_for", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        monkeypatch.setattr(im, "_ambient_table", lambda: _FakeTable({}))
        item = compute_metadata.tag_record({"pk": "p", "sk": "DATE#2026-08-23"}, source_id="computed_metrics")
        assert item["run_id"]  # the write still carries its normal provenance
        assert "input_status" not in item

    def test_one_run_gives_all_three_daily_metrics_partitions_the_same_answer(self, monkeypatch):
        """computed_metrics / day_grade / habit_scores must not be able to
        disagree about the same question at the same instant."""
        from common import compute_metadata

        monkeypatch.setattr(compute_metadata, "_emit_write_metric", lambda *_a, **_k: None)
        monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "daily-metrics-compute")
        table = _FakeTable({s: "2026-08-23" for s in im.COMPUTE_INPUTS["daily-metrics-compute"]})
        monkeypatch.setattr(im, "_ambient_table", lambda: table)

        statuses = {
            sid: compute_metadata.tag_record({"pk": "p", "sk": "DATE#2026-08-23"}, source_id=sid)["input_status"]
            for sid in ("computed_metrics", "day_grade", "habit_scores")
        }
        assert len(set(statuses.values())) == 1, statuses
        # ...and it cost ONE pass over the inputs, not three.
        assert len(table.queries) == len(im.COMPUTE_INPUTS["daily-metrics-compute"])

    def test_the_cache_cannot_serve_yesterdays_judgment_after_midnight(self, monkeypatch):
        """A warm container that survives a PT midnight must re-judge. The cache
        key carries the Pacific day precisely so it cannot not."""
        monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "adaptive-mode-compute")
        table = _FakeTable({s: "2026-08-23" for s in im.COMPUTE_INPUTS["adaptive-mode-compute"]})
        monkeypatch.setattr(im, "_ambient_table", lambda: table)

        monkeypatch.setattr(im, "pacific_today", lambda: "2026-08-24")
        first = im.current_run_manifest("adaptive-mode-compute")
        n_after_first = len(table.queries)
        im.current_run_manifest("adaptive-mode-compute")
        assert len(table.queries) == n_after_first, "same day should reuse the cached judgment"

        monkeypatch.setattr(im, "pacific_today", lambda: "2026-08-25")
        second = im.current_run_manifest("adaptive-mode-compute")
        assert len(table.queries) > n_after_first, "a new PT day must re-judge"
        assert first["as_of_day"] != second["as_of_day"]


# ══════════════════════════════════════════════════════════════════════════════
# The delayed connector — the issue's headline acceptance
# ══════════════════════════════════════════════════════════════════════════════


class TestDelayedConnector:
    NOW = _pt(2026, 8, 24, 9, 40)

    def test_a_late_connector_qualifies_the_stored_day_score(self):
        """The whole issue in one test: whoop arrives late, and the day score
        that gets written says so."""
        fresh = {s: "2026-08-23" for s in im.COMPUTE_INPUTS["daily-metrics-compute"]}
        fresh["whoop"] = "2026-08-15"  # ~9 days dark against a 48h threshold
        manifest = im.manifest_for("daily-metrics-compute", table=_FakeTable(fresh), now=self.NOW)

        assert manifest["status"] == im.MANIFEST_PARTIAL
        assert "whoop" in manifest["degraded"]

        item = {"pk": "USER#matthew#SOURCE#computed_metrics", "sk": "DATE#2026-08-23", "day_grade_score": Decimal("88")}
        im.attach_input_manifest(item, manifest)
        assert item["input_status"] == im.MANIFEST_PARTIAL
        assert item["input_manifest"]["sources"]["whoop"]["status"] == im.STATUS_STALE

    def test_the_same_run_with_every_connector_current_is_unqualified(self):
        """The other direction — a contract that can only ever say 'partial' is
        decoration, not a contract."""
        table = _FakeTable({s: "2026-08-23" for s in im.COMPUTE_INPUTS["daily-metrics-compute"]})
        manifest = im.manifest_for("daily-metrics-compute", table=table, now=self.NOW)
        assert manifest["status"] == im.MANIFEST_COMPLETE

        item = {"pk": "USER#matthew#SOURCE#computed_metrics", "sk": "DATE#2026-08-23"}
        im.attach_input_manifest(item, manifest)
        assert item["input_status"] == im.MANIFEST_COMPLETE

    def test_every_declared_lambda_can_be_qualified_by_a_late_connector(self):
        """Not just daily-metrics: each of the five, driven end to end."""
        for compute_id, sources in im.COMPUTE_INPUTS.items():
            late = sorted(s for s in sources if s != "garmin")[0]
            latest = {s: "2026-08-23" for s in sources}
            latest[late] = "2026-01-01"
            manifest = im.manifest_for(compute_id, table=_FakeTable(latest), now=self.NOW)
            assert manifest["status"] == im.MANIFEST_PARTIAL, compute_id
            assert late in manifest["degraded"], compute_id


# ══════════════════════════════════════════════════════════════════════════════
# Consuming surfaces render the honest label
# ══════════════════════════════════════════════════════════════════════════════


class TestConsumers:
    def test_site_api_character_publishes_the_manifest(self):
        from web.site_api_character import _public_input_manifest

        out = _public_input_manifest(
            {
                "input_manifest": {
                    "status": im.MANIFEST_PARTIAL,
                    "complete": False,
                    "as_of_day": "2026-08-24",
                    "degraded": ["hevy"],
                    "unobserved": [],
                    "sources": {
                        "hevy": {"status": im.STATUS_STALE, "latest_day": "2026-08-10", "age_hours": 340.0, "stale_after_hours": 168}
                    },
                }
            }
        )
        assert out["status"] == im.MANIFEST_PARTIAL
        assert out["degraded"] == ["hevy"]
        assert "hevy" in out["note"]
        assert out["sources"]["hevy"]["stale_after_hours"] == 168

    def test_site_api_character_says_nothing_for_a_pre_contract_record(self):
        from web.site_api_character import _public_input_manifest

        assert _public_input_manifest({"character_level": 4}) is None

    def test_the_brief_renders_the_qualification(self):
        from emails.brief_data_status import build_data_status_banner_html, qualified_compute_outputs

        rows = qualified_compute_outputs(
            {
                "Day grade": {
                    "input_status": im.MANIFEST_PARTIAL,
                    "input_manifest": {"status": im.MANIFEST_PARTIAL, "degraded": ["whoop"]},
                },
                "Character sheet": {"input_status": im.MANIFEST_COMPLETE, "input_manifest": {"status": im.MANIFEST_COMPLETE}},
                "Brief mode": None,
            }
        )
        assert [r["label"] for r in rows] == ["Day grade"]
        html = build_data_status_banner_html([], [], compute_partial=rows)
        assert "Computed on partial input" in html
        assert "whoop" in html

    def test_the_brief_is_silent_when_every_output_is_complete(self):
        from emails.brief_data_status import build_data_status_banner_html, qualified_compute_outputs

        rows = qualified_compute_outputs(
            {"Day grade": {"input_status": im.MANIFEST_COMPLETE, "input_manifest": {"status": im.MANIFEST_COMPLETE}}}
        )
        assert rows == []
        assert build_data_status_banner_html([], [], compute_partial=rows) == ""

    def test_the_brief_ignores_pre_contract_records(self):
        from emails.brief_data_status import qualified_compute_outputs

        assert qualified_compute_outputs({"Day grade": {"day_grade_score": 88}}) == []

    def test_the_brief_banner_is_unchanged_when_no_manifest_is_passed(self):
        """Backward compatibility: the #2326 caller shape still works."""
        from emails.brief_data_status import build_data_status_banner_html

        assert build_data_status_banner_html([], []) == ""


# ══════════════════════════════════════════════════════════════════════════════
# Scope guard — the issue's explicit "do NOT build this"
# ══════════════════════════════════════════════════════════════════════════════


def test_no_new_event_wiring_in_compute_stack():
    """#3049 scope guard: "NO event-driven rebuild (crons stay — the manifest
    makes the blindness visible)". The five Lambdas keep exactly the cron
    schedules they had; this pins the count of ``schedule=`` cron expressions and
    asserts no ``EventPattern``/``on_event``-style rebuild trigger was smuggled in
    alongside the manifest.
    """
    src = open(_COMPUTE_STACK, encoding="utf-8").read()
    for forbidden in ("EventPattern", "event_pattern", "on_cloud_trail_event", "add_event_source"):
        assert forbidden not in src, f"#3049 scope guard: {forbidden} appeared in compute_stack.py"
    tree = ast.parse(src)
    scheduled = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.keyword)
        and n.arg == "schedule"
        and isinstance(n.value, ast.Constant)
        and str(n.value.value).startswith("cron(")
    ]
    assert len(scheduled) >= len(EXPECTED_COMPUTE_IDS), "compute Lambdas lost their cron schedules"
