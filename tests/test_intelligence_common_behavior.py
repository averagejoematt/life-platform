#!/usr/bin/env python3
"""tests/test_intelligence_common_behavior.py — behavioral contracts of
`lambdas/intelligence/intelligence_common.py`, the coach-honesty engine.

Part of #1658 tranche 3. This module is the one ADR-104 (honest numbers /
behavioral-absence semantics) and ADR-105 (uncertainty + n on every statistical
claim) police most directly: it decides how much data a coach believes it has,
what voice that earns, which claims a narrative may make, and whether a
movement verdict is withheld. A defect here makes a coach state a confident
falsehood to Matthew.

What this file is hunting, in priority order:

  * **the gate that guards nothing** — the repo has hit that class ten times
    through 2026-08-08. Every guard here (`validate_coach_output`'s five
    checks, `apply_movement_honesty_guard`, `_pipe_confirmed_live`,
    `movement_assessability`, the maturity gate, the staleness directive) is
    mutation-proved: the test fails if the guard is deleted. Where a check's
    condition can never be true, that is stated as a finding, not smoothed over.
  * **reader/writer field-name mismatches** — every DDB field this module reads
    is checked against a real writer in the repo. Six independent instances of
    this class were found in tranche 2.
  * **ADR-058 phase treatment** — every partition read is checked against
    `phase_taxonomy`'s own classification rather than a restated list.
  * **crash paths** — an unguarded `float()`/`int()`, a `KeyError` escaping into
    a coach run, a `float` reaching `put_item`.

Nothing here reaches DynamoDB, S3, Bedrock or the network: every boundary is a
hand-rolled bounded fake wired onto the module attribute the code looks up. Every
clock is frozen; no fixture date is ever combined with a live `datetime.now()`.

Findings that reflect production defects are marked `xfail(strict=False)` with
the module, function, what it does, what it should do, and who it hurts. No
production code is modified by this file.
"""

import json
import os
import re
import sys
from datetime import datetime
from decimal import Decimal

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
if LAMBDAS not in sys.path:
    sys.path.insert(0, LAMBDAS)

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_import_err = None
try:
    from experiment import phase_taxonomy
    from intelligence import intelligence_common as ic
except ImportError as _e:  # pragma: no cover — only when the bundle layout changes
    _import_err = _e
    ic = None  # type: ignore

if _import_err is not None:  # pragma: no cover
    pytestmark = pytest.mark.skip(reason=f"intelligence_common unavailable: {_import_err}")  # type: ignore


# ──────────────────────────────────────────────────────────────────────────────
# Test doubles — all bounded, no MagicMock anywhere near a loop-shaped read
# ──────────────────────────────────────────────────────────────────────────────


def _condition_values(cond):
    """Pull the literal operands out of a boto3 `Key(...)` condition tree.

    The module builds real `Key("pk").eq(...) & Key("sk").between(...)` objects,
    so the fake matches on the serialized operands rather than re-implementing
    the DSL (the pattern tests/test_coach_quality_gate_behavior.py established).
    """
    values = []

    def walk(node):
        for v in getattr(node, "_values", ()):
            if hasattr(v, "_values"):
                walk(v)
            elif not hasattr(v, "name"):
                values.append(v)

    walk(cond)
    return values


def _pk_of(kwargs):
    vals = _condition_values(kwargs.get("KeyConditionExpression"))
    return vals[0] if vals else ""


class FakeTable:
    """In-memory stand-in for the boto3 Table this module holds as `ic.table`.

    `router(kwargs, pk) -> dict | None` is the only extension point; returning
    None falls through to the empty answer. Every collection is a finite list —
    nothing here can generate an unbounded page sequence.
    """

    def __init__(self, router=None, store=None):
        self.router = router
        self.store = dict(store or {})
        self.queries = []
        self.puts = []
        self.updates = []
        self.gets = []
        self.fail_pks = set()
        self.get_error = None

    def query(self, **kwargs):
        self.queries.append(kwargs)
        pk = _pk_of(kwargs)
        if pk in self.fail_pks:
            raise RuntimeError(f"ddb down for {pk}")
        if self.router is not None:
            answer = self.router(kwargs, pk)
            if answer is not None:
                return answer
        return {"Items": [], "Count": 0}

    def get_item(self, Key=None, **kwargs):
        key = Key if Key is not None else kwargs.get("Key", {})
        self.gets.append(key)
        if self.get_error is not None:
            raise self.get_error
        item = self.store.get((key.get("pk"), key.get("sk")))
        return {"Item": item} if item is not None else {}

    def put_item(self, Item=None, **kwargs):
        item = Item if Item is not None else kwargs.get("Item")
        self.puts.append(item)
        self.store[(item.get("pk"), item.get("sk"))] = item
        return {}

    def update_item(self, **kwargs):
        self.updates.append(kwargs)
        return {"Attributes": {"status": "completed"}}


class _Body:
    def __init__(self, text):
        self._t = text

    def read(self):
        return self._t.encode()


class FakeS3:
    """Bounded S3 double: a dict of key -> object, or a scripted error."""

    def __init__(self, objects=None, error=None):
        self.objects = dict(objects or {})
        self.error = error
        self.gets = []

    def get_object(self, Bucket=None, Key=None, **kwargs):
        self.gets.append(Key)
        if self.error is not None:
            raise self.error
        if Key not in self.objects:
            raise KeyError(Key)
        return {"Body": _Body(json.dumps(self.objects[Key]))}


def _freeze(monkeypatch, iso="2026-08-08T12:00:00+00:00"):
    """Freeze the module's clock. Returns the frozen instant.

    The module does `from datetime import datetime`, so the name is rebound on
    the module itself. Subclassing keeps `strptime`/arithmetic intact.
    """
    fixed = datetime.fromisoformat(iso)

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed if tz is None else fixed.astimezone(tz)

    monkeypatch.setattr(ic, "datetime", _FrozenDatetime)
    return fixed


@pytest.fixture
def wired(monkeypatch):
    """A frozen clock plus fake DDB/S3 on every boundary this module touches."""
    _freeze(monkeypatch)
    table = FakeTable()
    s3 = FakeS3()
    monkeypatch.setattr(ic, "table", table)
    monkeypatch.setattr(ic, "s3", s3)
    return table, s3


@pytest.fixture(autouse=True)
def _reset_module_caches():
    """The S3 loaders keep warm-container globals; a leaked cache would make
    these tests order-dependent."""
    ic._goals_cache = None
    ic._goals_cache_ts = 0
    ic._detection_rules_cache = None
    ic._detection_rules_cache_ts = 0
    yield
    ic._goals_cache = None
    ic._goals_cache_ts = 0
    ic._detection_rules_cache = None
    ic._detection_rules_cache_ts = 0


# ── repo scanners, for the reader/writer + dark-surface hunts ────────────────


def _live_py_files():
    """Every shipping .py file (lambdas/ + mcp/) — the one-bundle surface."""
    out = []
    for base in (os.path.join(ROOT, "lambdas"), os.path.join(ROOT, "mcp")):
        for dirpath, _dirs, files in os.walk(base):
            for f in files:
                if f.endswith(".py"):
                    out.append(os.path.join(dirpath, f))
    return out


def _live_references(symbol, exclude_basename="intelligence_common.py"):
    """Files in the shipping surface that REFERENCE `symbol` — AST-derived, so a
    same-named private sibling (`_update_prediction_status`), a comment or a
    docstring mention never counts as a caller (the technique
    tests/test_no_dead_intelligence_functions.py established)."""
    import ast

    hits = []
    for path in _live_py_files():
        if os.path.basename(path) == exclude_basename:
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=path)
        except (OSError, SyntaxError):  # pragma: no cover
            continue
        for node in ast.walk(tree):
            found = (
                (isinstance(node, ast.Name) and node.id == symbol)
                or (isinstance(node, ast.Attribute) and node.attr == symbol)
                or (isinstance(node, (ast.Import, ast.ImportFrom)) and any(a.name == symbol or a.asname == symbol for a in node.names))
            )
            if found:
                hits.append(os.path.relpath(path, ROOT))
                break
    return hits


def _live_string_literals_containing(token, exclude_basename="intelligence_common.py"):
    """Files whose *string literals* contain `token` — for DDB key hunts, where
    a writer is identified by the sk it constructs, not by a symbol name."""
    import ast

    hits = []
    for path in _live_py_files():
        if os.path.basename(path) == exclude_basename:
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=path)
        except (OSError, SyntaxError):  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and token in node.value:
                hits.append(os.path.relpath(path, ROOT))
                break
    return hits


# ══════════════════════════════════════════════════════════════════════════════
# DATA INVENTORY — the maturity gate's only input (#1203 / #2109)
# ══════════════════════════════════════════════════════════════════════════════


class TestInventoryPhaseTreatment:
    """`build_data_inventory` decides the coach's voice. Read with the ADR-058
    phase filter on a RAW_TIMESERIES partition and a fresh cycle answers "the
    cycle's age" instead of "the pipe's history" (#2109, measured: 137 rows
    unfiltered vs 1 filtered on cycle 12 Day 2)."""

    def _run(self, monkeypatch):
        _freeze(monkeypatch)
        table = FakeTable()
        monkeypatch.setattr(ic, "table", table)
        ic.build_data_inventory()
        return table

    def test_every_inventoried_partition_is_classifiable_by_the_taxonomy(self):
        """An unclassified partition makes `source_reads_cross_phase` fail soft
        to "keep the filter" — silently re-introducing the #2109 truncation."""
        for _label, partition in ic._INVENTORY_SOURCES:
            phase_taxonomy.classify(f"USER#matthew#SOURCE#{partition}")

    def test_the_phase_filter_is_applied_exactly_where_the_taxonomy_says(self, monkeypatch):
        """Mutation-proof for #2109: flipping `include_pilot=cross_phase` back to
        an unconditional filter fails this. The expectation is DERIVED from
        phase_taxonomy, so a partition added to `_INVENTORY_SOURCES` later
        inherits the right answer instead of a restated list."""
        table = self._run(monkeypatch)
        seen = set()
        for kwargs in table.queries:
            pk = _pk_of(kwargs)
            partition = pk.split("#SOURCE#", 1)[1]
            seen.add(partition)
            scoped = phase_taxonomy.classify(pk) == phase_taxonomy.EXPERIMENT_SCOPED
            filter_expr = kwargs.get("FilterExpression", "")
            has_phase_filter = "#phase" in str(filter_expr)
            assert has_phase_filter is scoped, f"{partition}: phase filter={has_phase_filter}, EXPERIMENT_SCOPED={scoped}"
        assert seen == {p for _l, p in ic._INVENTORY_SOURCES}

    def test_no_inventory_partition_is_experiment_scoped_today(self):
        """States the premise the docstring rests on, so the day one becomes
        scoped the derived test above starts asserting a filter instead."""
        scoped = [
            p for _l, p in ic._INVENTORY_SOURCES if phase_taxonomy.classify(f"USER#matthew#SOURCE#{p}") == phase_taxonomy.EXPERIMENT_SCOPED
        ]
        assert scoped == []

    def test_the_latest_record_probe_is_never_filtered(self, monkeypatch):
        """DynamoDB applies Limit BEFORE FilterExpression (#1203) — a filtered
        `Limit: 1` returns the newest row, discards it, and reports a live pipe
        as `latest: None`."""
        table = self._run(monkeypatch)
        limit_one = [q for q in table.queries if q.get("Limit") == 1]
        assert limit_one, "no newest-first probe issued"
        for kwargs in limit_one:
            assert "FilterExpression" not in kwargs
            assert kwargs.get("ScanIndexForward") is False


class TestInventoryShape:
    def test_counts_and_latest_are_read_from_the_partition(self, monkeypatch):
        _freeze(monkeypatch)

        def router(kwargs, pk):
            if not pk.endswith("#whoop"):
                return None
            if kwargs.get("Select") == "COUNT":
                return {"Count": 42}
            return {"Items": [{"sk": "DATE#2026-08-07"}]}

        monkeypatch.setattr(ic, "table", FakeTable(router=router))
        inv = ic.build_data_inventory()
        assert inv["whoop"] == {"exists": True, "latest": "2026-08-07", "records": 42, "days_of_data": 42}

    def test_a_partition_with_no_rows_reports_absence_not_a_fabricated_zero_date(self, monkeypatch):
        _freeze(monkeypatch)
        monkeypatch.setattr(ic, "table", FakeTable())
        inv = ic.build_data_inventory()
        assert inv["whoop"]["exists"] is False
        assert inv["whoop"]["latest"] is None  # ADR-104: absence stays absent

    def test_one_failing_partition_does_not_poison_the_rest(self, monkeypatch):
        _freeze(monkeypatch)

        def router(kwargs, pk):
            if pk.endswith("#withings") and kwargs.get("Select") == "COUNT":
                return {"Count": 9}
            return None

        table = FakeTable(router=router)
        table.fail_pks.add("USER#matthew#SOURCE#whoop")
        monkeypatch.setattr(ic, "table", table)
        inv = ic.build_data_inventory()
        assert inv["whoop"] == {"exists": False, "latest": None, "records": 0, "days_of_data": 0}
        assert inv["withings"]["records"] == 9

    def test_the_ninety_day_window_is_derived_from_the_frozen_clock(self, monkeypatch):
        """Hand-derived: frozen at 2026-08-08, minus 90 days = 2026-05-10.
        (May 10 -> Aug 8 = 21 + 30 + 31 + 8 = 90.)"""
        _freeze(monkeypatch)
        table = FakeTable()
        monkeypatch.setattr(ic, "table", table)
        ic.build_data_inventory()
        count_q = next(q for q in table.queries if q.get("Select") == "COUNT")
        assert _condition_values(count_q["KeyConditionExpression"])[1:] == ["DATE#2026-05-10", "DATE#2026-08-08~"]

    def test_a_duplicated_partition_is_reachable_under_its_own_label(self):
        """`build_data_inventory`'s dedup branch copies `inventory[partition]`,
        but the dict is keyed by LABEL. Adding ("journal2", "notion") today
        would copy a missing key and publish `{}` for it — the guard against
        that is: every duplicated partition must also BE a label (or be the
        cgm exemption)."""
        seen, duplicated = set(), set()
        for _label, partition in ic._INVENTORY_SOURCES:
            if partition in seen:
                duplicated.add(partition)
            seen.add(partition)
        labels = {label for label, _p in ic._INVENTORY_SOURCES}
        for partition in duplicated:
            sharing = [label for label, p in ic._INVENTORY_SOURCES if p == partition]
            for label in sharing[1:]:
                assert label == "cgm" or partition in labels, f"{label} would copy a missing inventory key {partition}"


class TestCgmStaleness:
    """CGM is inventoried by counting `blood_glucose_avg` inside the
    apple_health partition — but `latest` is read from the UNFILTERED
    apple_health probe issued before that branch."""

    def _inventory(self, monkeypatch):
        _freeze(monkeypatch)

        def router(kwargs, pk):
            if not pk.endswith("#apple_health"):
                return None
            if kwargs.get("Limit") == 1:
                # HAE writes apple_health every day — this is always fresh.
                return {"Items": [{"sk": "DATE#2026-08-08"}]}
            if "blood_glucose_avg" in str(kwargs.get("FilterExpression", "")):
                return {"Count": 4}  # four glucose days, all a month old
            return {"Count": 90}

        monkeypatch.setattr(ic, "table", FakeTable(router=router))
        return ic.build_data_inventory()

    def test_the_cgm_record_count_comes_from_the_glucose_filtered_read(self, monkeypatch):
        inv = self._inventory(monkeypatch)
        assert inv["cgm"]["records"] == 4  # not the 90 apple_health days

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (P1, VERIFIED) intelligence_common.py:139-168 build_data_inventory: the "
            "`latest` probe runs BEFORE the cgm branch and is never re-issued with "
            "attribute_exists(blood_glucose_avg), so cgm inherits apple_health's latest date. "
            "apple_health is written daily by the HAE webhook, so cgm can never look stale — "
            "build_coach_preamble's >=3d / >=7d staleness directives are structurally "
            "unreachable for glucose. It should re-probe the newest glucose-bearing record. "
            "Hurts Matthew: the glucose coach opines confidently on a CGM that stopped weeks ago."
        ),
    )
    def test_cgm_latest_should_be_the_newest_glucose_bearing_record(self, monkeypatch):
        inv = self._inventory(monkeypatch)
        assert inv["cgm"]["latest"] != inv["apple_health"]["latest"]


# ══════════════════════════════════════════════════════════════════════════════
# DATA MATURITY — which voice a coach has earned
# ══════════════════════════════════════════════════════════════════════════════


class TestMaturityRegistry:
    def test_every_threshold_source_exists_as_an_inventory_label(self):
        """A threshold pointing at a label the inventory never produces reads
        `days_of_data` off `{}` -> 0 -> permanent ORIENTATION. Derived from both
        registries so a new domain can't silently land dark."""
        labels = {label for label, _p in ic._INVENTORY_SOURCES}
        for domain, spec in ic._MATURITY_THRESHOLDS.items():
            assert spec["source"] in labels, f"{domain} reads inventory['{spec['source']}'], which is never built"

    def test_every_threshold_is_ordered_and_carries_its_unit(self):
        for domain, spec in ic._MATURITY_THRESHOLDS.items():
            assert 0 < spec["orientation"] <= spec["established"], domain
            assert spec["unit"], domain

    def test_every_domain_gets_the_full_contract(self, monkeypatch):
        _freeze(monkeypatch)
        maturity = ic.build_data_maturity({})
        assert set(maturity) == set(ic._MATURITY_THRESHOLDS)
        for domain, row in maturity.items():
            assert set(row) == {"days", "phase", "threshold", "established_at", "unit", "target_date"}, domain


class TestMaturityGate:
    """Mutation-proof: collapse the three-way phase decision to any single value
    and one of these fails."""

    def _phase(self, monkeypatch, domain, days, extra=None):
        _freeze(monkeypatch)
        source = ic._MATURITY_THRESHOLDS[domain]["source"]
        inventory = {source: {"exists": days > 0, "records": days, "days_of_data": days}}
        inventory.update(extra or {})
        return ic.build_data_maturity(inventory)[domain]

    def test_below_the_orientation_threshold_is_orientation(self, monkeypatch):
        # sleep: orientation=7 -> 6 nights is below
        assert self._phase(monkeypatch, "sleep", 6)["phase"] == "orientation"

    def test_exactly_at_the_orientation_threshold_is_emerging(self, monkeypatch):
        assert self._phase(monkeypatch, "sleep", 7)["phase"] == "emerging"

    def test_one_below_established_is_still_emerging(self, monkeypatch):
        assert self._phase(monkeypatch, "sleep", 29)["phase"] == "emerging"

    def test_exactly_at_established_is_established(self, monkeypatch):
        assert self._phase(monkeypatch, "sleep", 30)["phase"] == "established"

    def test_absent_data_is_orientation_never_established(self, monkeypatch):
        """ADR-104: absence must not be read as a satisfied threshold."""
        _freeze(monkeypatch)
        maturity = ic.build_data_maturity({})
        assert {row["phase"] for row in maturity.values()} == {"orientation"}
        assert {row["days"] for row in maturity.values()} == {0}

    def test_the_orientation_target_date_is_hand_derivable_from_the_frozen_clock(self, monkeypatch):
        """sleep threshold 7, 3 nights logged -> 4 days out from 2026-08-08 =
        2026-08-12 -> "August 12"."""
        assert self._phase(monkeypatch, "sleep", 3)["target_date"] == "August 12"

    def test_emerging_and_established_publish_no_target_date(self, monkeypatch):
        assert self._phase(monkeypatch, "sleep", 10)["target_date"] is None
        assert self._phase(monkeypatch, "sleep", 40)["target_date"] is None

    def test_physical_stays_in_orientation_without_a_dexa_however_many_weigh_ins(self, monkeypatch):
        """The composite rule is load-bearing: body-composition claims need a
        DEXA, not a scale series."""
        row = self._phase(monkeypatch, "physical", 400, extra={"dexa": {"exists": False}})
        assert row["phase"] == "orientation"

    def test_physical_advances_once_a_dexa_exists(self, monkeypatch):
        assert self._phase(monkeypatch, "physical", 400, extra={"dexa": {"exists": True}})["phase"] == "established"

    def test_physical_with_a_dexa_but_thin_weight_series_stays_in_orientation(self, monkeypatch):
        assert self._phase(monkeypatch, "physical", 2, extra={"dexa": {"exists": True}})["phase"] == "orientation"


# ══════════════════════════════════════════════════════════════════════════════
# COACH PREAMBLE — the single injection point for context, staleness and privacy
# ══════════════════════════════════════════════════════════════════════════════


def _preamble(monkeypatch, **over):
    _freeze(monkeypatch)
    monkeypatch.setattr(ic, "table", over.pop("table", FakeTable()))
    args = {
        "coach_name": "Dr. Lisa Park",
        "domain": "sleep",
        "goals": {"targets": {}},
        "inventory": {},
        "maturity": {"sleep": {"phase": "orientation", "days": 3, "threshold": 7, "unit": "nights"}},
    }
    args.update(over)
    return ic.build_coach_preamble(**args)


class TestPreambleStalenessDirective:
    """P5.8's hard staleness warning is the thing that stops a coach opining on
    a pipe that died. Mutation-proof: delete the `stale_sources` block and both
    of the first two tests fail."""

    def _inv(self, latest):
        return {"whoop": {"exists": True, "latest": latest, "records": 40}}

    def test_a_source_seven_days_behind_gets_a_hard_do_not_claim_directive(self, monkeypatch):
        # frozen 2026-08-08, latest 2026-08-01 -> 7 days stale
        text = _preamble(monkeypatch, inventory=self._inv("2026-08-01"))
        assert "DATA STALENESS WARNINGS" in text
        assert "whoop hasn't reported in 7 days" in text
        assert "Do NOT make claims about whoop-related patterns" in text

    def test_the_inventory_line_carries_the_stale_marker(self, monkeypatch):
        text = _preamble(monkeypatch, inventory=self._inv("2026-08-01"))
        assert "STALE — 7 days since last record" in text

    def test_three_to_six_days_is_a_soft_note_and_raises_no_hard_warning(self, monkeypatch):
        # latest 2026-08-05 -> 3 days
        text = _preamble(monkeypatch, inventory=self._inv("2026-08-05"))
        assert "(⚠️ 3 days since last record)" in text
        assert "DATA STALENESS WARNINGS" not in text

    def test_a_fresh_source_raises_nothing(self, monkeypatch):
        text = _preamble(monkeypatch, inventory=self._inv("2026-08-07"))
        assert "days since last record" not in text
        assert "DATA STALENESS WARNINGS" not in text

    def test_an_unparseable_latest_never_crashes_the_coach_run(self, monkeypatch):
        """`latest: None` is exactly what a filtered Limit:1 probe produces
        (#1203) — a TypeError here would lose the whole narrative."""
        text = _preamble(monkeypatch, inventory={"whoop": {"exists": True, "latest": None, "records": 40}})
        assert "whoop: AVAILABLE" in text
        assert "days since last record" not in text

    def test_a_source_with_no_data_is_named_as_not_available(self, monkeypatch):
        text = _preamble(monkeypatch, inventory={"dexa": {"exists": False}})
        assert "dexa: not available" in text


class TestPreamblePrivacy:
    """Mental-health drivers and the binge pattern are injected into coach
    prompts. `feedback_sensitive_content` is absolute: those specifics never
    reach a published surface."""

    GOALS = {
        "targets": {},
        "mental_health_context": {"drivers": ["a private driver"], "coach_guidance": "be gentle"},
        "athlete_profile": {"type": "returning", "binge_eating_pattern": "a private pattern"},
    }

    def test_the_coaches_only_directive_travels_with_the_drivers(self, monkeypatch):
        """Mutation-proof: strip the header and the private list ships naked."""
        text = _preamble(monkeypatch, goals=self.GOALS)
        assert "a private driver" in text
        header = "MENTAL HEALTH CONTEXT (COACHES ONLY — do not reference specifics publicly):"
        assert header in text
        assert text.index(header) < text.index("a private driver")

    def test_no_mental_health_section_is_emitted_when_there_are_no_drivers(self, monkeypatch):
        text = _preamble(monkeypatch, goals={"targets": {}, "mental_health_context": {"coach_guidance": "x"}})
        assert "MENTAL HEALTH CONTEXT" not in text

    def test_the_behavioral_note_is_emitted_only_from_the_athlete_profile(self, monkeypatch):
        text = _preamble(monkeypatch, goals=self.GOALS)
        assert "BEHAVIORAL NOTE: a private pattern" in text


class TestPreambleTargetsAndVoice:
    def test_an_unset_target_is_named_not_invented(self, monkeypatch):
        text = _preamble(monkeypatch, goals={"targets": {"weight": {}}})
        assert "Weight goal: not yet set" in text
        assert "do NOT invent one" in text

    def test_a_set_target_is_rendered(self, monkeypatch):
        text = _preamble(monkeypatch, goals={"targets": {"weight": {"goal_lbs": 210}}})
        assert "Weight goal: 210" in text

    def test_a_non_dict_target_branch_degrades_to_not_set_without_crashing(self, monkeypatch):
        text = _preamble(monkeypatch, goals={"targets": {"weight": "210 lbs"}})
        assert "Weight goal: not yet set" in text

    def test_orientation_forbids_analytical_claims(self, monkeypatch):
        text = _preamble(monkeypatch)
        assert "ORIENTATION mode" in text
        assert "Do NOT make analytical claims" in text

    def test_emerging_forbids_definitive_language(self, monkeypatch):
        text = _preamble(monkeypatch, maturity={"sleep": {"phase": "emerging", "days": 12, "unit": "nights"}})
        assert "EMERGING mode" in text
        assert "Do NOT use definitive language" in text

    def test_established_unlocks_the_full_analytical_voice(self, monkeypatch):
        text = _preamble(monkeypatch, maturity={"sleep": {"phase": "established", "days": 40, "unit": "nights"}})
        assert "ESTABLISHED mode" in text

    def test_an_unknown_domain_falls_back_to_the_most_conservative_voice(self, monkeypatch):
        """ADR-104: a missing maturity row must not buy a coach the confident
        voice by default."""
        text = _preamble(monkeypatch, domain="nowhere", maturity={})
        assert "ORIENTATION mode" in text

    def test_the_zero_means_absence_rule_is_always_injected(self, monkeypatch):
        """The behavioral-absence half of ADR-104: 0 workouts means 'none
        happened', never 'give me your data'."""
        text = _preamble(monkeypatch)
        assert 'say "no training logged" NOT "provide your training data"' in text


class TestPreambleGoalsSections:
    """Every optional goals block is emitted only when its data exists — an
    empty section header with nothing under it reads to the model as an
    assertion of absence."""

    FULL = {
        "mission": "12-month recomposition",
        "philosophy": "slow is smooth",
        "athlete_profile": {
            "type": "returning lifter",
            "prior_transformation": {"start_weight": 300, "end_weight": 220, "duration_months": 14, "outcome": "regained"},
        },
        "targets": {
            "training": {"current_phase": "Base", "phases": [{"phase": "base", "months": "1-3", "structure": "3x/wk", "notes": "easy"}]},
            "nutrition": {"eating_window": {"type": "IF", "window": "12-8", "note": "no late meals"}},
        },
        "failure_mode": {"pattern": "all-or-nothing", "early_warning_signals": ["skipped logging"], "coach_response": "name it early"},
        "coach_communication": {"do_not": ["moralize about food"]},
        "known_constraints": ["shift work"],
    }

    def test_every_supplied_block_is_rendered(self, monkeypatch):
        text = _preamble(monkeypatch, goals=self.FULL)
        assert "MATTHEW'S MISSION:\n12-month recomposition" in text
        assert "PHILOSOPHY: slow is smooth" in text
        assert "ATHLETE CONTEXT: returning lifter" in text
        assert "Prior transformation: 300→220 lbs in 14 months" in text
        assert "TRAINING PHASE: base (months 1-3)" in text
        assert "EATING WINDOW: IF (12-8)" in text
        assert "FAILURE MODE PATTERN: all-or-nothing" in text
        assert "⚠️ skipped logging" in text
        assert "DO NOT:\n  - moralize about food" in text
        assert "KNOWN CONSTRAINTS:\n  - shift work" in text

    def test_the_training_phase_lookup_is_case_insensitive(self, monkeypatch):
        """`current_phase` is authored by hand; a case mismatch would silently
        drop the whole training-phase block."""
        assert "TRAINING PHASE" in _preamble(monkeypatch, goals=self.FULL)

    def test_a_current_phase_with_no_matching_entry_emits_no_block(self, monkeypatch):
        goals = {"targets": {"training": {"current_phase": "Peaking", "phases": [{"phase": "base"}]}}}
        assert "TRAINING PHASE" not in _preamble(monkeypatch, goals=goals)

    def test_the_legacy_coach_briefing_still_fills_the_mission_slot(self, monkeypatch):
        text = _preamble(monkeypatch, goals={"targets": {}, "coach_briefing": "legacy briefing"})
        assert "MATTHEW'S MISSION:\nlegacy briefing" in text

    def test_absent_blocks_leave_no_empty_headers(self, monkeypatch):
        text = _preamble(monkeypatch, goals={"targets": {}})
        for header in (
            "PHILOSOPHY:",
            "ATHLETE CONTEXT:",
            "TRAINING PHASE:",
            "EATING WINDOW:",
            "FAILURE MODE PATTERN:",
            "DO NOT:",
            "KNOWN CONSTRAINTS:",
        ):
            assert header not in text


class TestPreambleCredibility:
    def test_the_credibility_block_reads_the_coach_credibility_singleton(self, monkeypatch):
        table = FakeTable(
            store={
                ("USER#matthew", "SOURCE#coach_credibility#sleep"): {
                    "label": "reliable",
                    "accuracy_pct": Decimal("71"),
                    "predictions_resolved": Decimal("14"),
                    "calibration": "well-calibrated",
                }
            }
        )
        text = _preamble(monkeypatch, table=table)
        # PIN (P3, cosmetic): `_decimal_to_float` turns the stored integral
        # Decimals into floats, so the prompt reads "14.0 predictions resolved,
        # 71.0% accuracy" rather than whole numbers.
        assert "Track record: reliable (14.0 predictions resolved, 71.0% accuracy)" in text
        assert "Calibration: well-calibrated" in text

    def test_an_over_confident_calibration_adds_the_corrective_note(self, monkeypatch):
        table = FakeTable(
            store={("USER#matthew", "SOURCE#coach_credibility#sleep"): {"label": "developing", "calibration": "over-confident"}}
        )
        text = _preamble(monkeypatch, table=table)
        assert "Consider being more measured in your confidence levels" in text

    def test_a_missing_record_degrades_to_nascent_without_crashing(self, monkeypatch):
        text = _preamble(monkeypatch)
        assert "Track record: nascent (0 predictions resolved, 0% accuracy)" in text

    def test_a_ddb_outage_never_loses_the_preamble(self, monkeypatch):
        table = FakeTable()
        table.get_error = RuntimeError("ddb down")
        text = _preamble(monkeypatch, table=table)
        assert "Track record: nascent" in text

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (P2, VERIFIED) intelligence_common.py:1629 load_credibility reads "
            "USER#matthew / SOURCE#coach_credibility#{coach_id}, and NO module in lambdas/ or "
            "mcp/ writes that key — #1239 deleted compute_all_credibility, the only writer, and "
            "left the reader. So every coach prompt permanently carries 'Track record: nascent "
            "(0 predictions resolved, 0% accuracy)' and the over-confident corrective is "
            "structurally unreachable. It should be written by whatever computes credibility "
            "(compute_credibility, itself uncalled). Hurts Matthew: a coach with a real track "
            "record is told, every day, that it has none."
        ),
    )
    def test_something_in_the_repo_writes_the_credibility_record_it_reads(self):
        assert _live_string_literals_containing("coach_credibility")


class TestPreambleActionHistory:
    def test_previous_actions_are_capped_at_five(self, monkeypatch):
        history = [{"status": "open", "action_text": f"a{i}", "issued_week": "2026-W32"} for i in range(9)]
        text = _preamble(monkeypatch, action_history=history)
        assert text.count("STATUS: OPEN") == 5

    def test_no_action_section_when_there_is_no_history(self, monkeypatch):
        assert "YOUR PREVIOUS ACTIONS" not in _preamble(monkeypatch)


# ══════════════════════════════════════════════════════════════════════════════
# THE VALIDATOR — five advertised checks
# ══════════════════════════════════════════════════════════════════════════════

_MATURITY_EMERGING = {"physical": {"phase": "emerging", "days": 10, "unit": "days"}}


def _validate(narrative, inventory=None, maturity=None, domain="physical", all_narratives=None):
    return ic.validate_coach_output("physical_coach", domain, narrative, inventory or {}, maturity or _MATURITY_EMERGING, all_narratives)


class TestNullClaimCheck:
    """Mutation-proof for check 1: delete the `_NULL_CLAIM_PHRASES` loop and the
    first two tests fail."""

    INV = {"dexa": {"exists": True, "records": 3, "latest": "2026-07-02"}}

    def test_a_null_claim_about_a_source_that_has_data_is_an_error(self):
        flags = _validate("Your body composition remains unknown for now.", self.INV)
        errors = [f for f in flags if f["check"] == "null_claim_vs_data"]
        assert errors and errors[0]["severity"] == "error"
        assert "3 records" in errors[0]["detail"]

    def test_the_flag_carries_the_offending_text_for_the_reviewer(self):
        flags = _validate("Your body composition remains unknown for now.", self.INV)
        assert "body composition" in flags[0]["source_text"].lower()

    def test_the_same_claim_is_clean_when_the_source_really_is_empty(self):
        assert _validate("Your body composition remains unknown.", {"dexa": {"exists": False, "records": 0}}) == []

    def test_a_source_that_exists_with_zero_records_is_not_treated_as_data(self):
        """ADR-104: `exists` without records is not evidence."""
        assert _validate("Your body composition remains unknown.", {"dexa": {"exists": True, "records": 0}}) == []

    def test_every_phrase_in_the_registry_is_wired_to_the_check(self):
        """Derived over `_NULL_CLAIM_PHRASES` — a phrase added to the list but
        never matchable would be a dead entry in a live guard."""
        for phrase in ic._NULL_CLAIM_PHRASES:
            narrative = f"On body composition: {phrase} right now."
            flags = _validate(narrative, self.INV)
            assert any(f["check"] == "null_claim_vs_data" for f in flags), phrase

    def test_every_domain_keyword_in_the_map_resolves_to_an_inventory_source(self):
        """`_CLAIM_DOMAIN_MAP` values are inventory LABELS; one that the
        inventory never produces makes that keyword's check permanently dark."""
        labels = {label for label, _p in ic._INVENTORY_SOURCES}
        for keyword, sources in ic._CLAIM_DOMAIN_MAP.items():
            for src in sources:
                assert src in labels, f"{keyword} -> {src}, never built by build_data_inventory"

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (P2, VERIFIED) intelligence_common.py:633-637 validate_coach_output check 1 "
            "uses text_lower.index(phrase), which finds only the FIRST occurrence of each "
            "phrase. A narrative that says 'no data' once about a genuinely empty source and "
            "again about a source with 90 records is never flagged for the second. It should "
            "scan every occurrence (re.finditer). Hurts Matthew: the false claim later in a "
            "long narrative is the one that ships."
        ),
    )
    def test_a_second_occurrence_of_a_phrase_is_also_checked(self):
        narrative = (
            "On bloodwork there is no data for this cycle, so I will wait. "
            "Now, a long stretch of unrelated commentary to push the next claim "
            "well outside the fifty-character context window of the first one. "
            "For sleep, no data has come through from the wearable this week."
        )
        inventory = {"labs": {"exists": False, "records": 0}, "whoop": {"exists": True, "records": 90, "latest": "2026-08-08"}}
        assert [f for f in _validate(narrative, inventory) if f["check"] == "null_claim_vs_data"]


class TestStaleActionCheck:
    """Mutation-proof for check 2."""

    def test_asking_for_a_scan_that_already_exists_is_an_error(self):
        flags = _validate("Action: obtain a DEXA scan this month.", {"dexa": {"exists": True, "records": 1}})
        stale = [f for f in flags if f["check"] == "stale_action"]
        assert stale and stale[0]["severity"] == "error"

    def test_asking_for_data_that_genuinely_is_missing_is_clean(self):
        flags = _validate("Action: obtain a DEXA scan this month.", {"dexa": {"exists": False}})
        assert [f for f in flags if f["check"] == "stale_action"] == []

    def test_the_action_window_is_bounded_so_a_distant_keyword_does_not_trip_it(self):
        """The check reads 80 chars after the phrase; a source named far later
        in the paragraph is a different sentence, not this ask."""
        narrative = "Action: get a full night of rest tonight." + " padding." * 12 + " Your dexa scan is on file."
        assert [f for f in _validate(narrative, {"dexa": {"exists": True, "records": 1}}) if f["check"] == "stale_action"] == []

    def test_one_clause_can_raise_two_separate_errors(self):
        """PIN (P3): 'provide your' sits in BOTH `_NULL_CLAIM_PHRASES` and the
        local action_phrases list, so a single sentence writes 2 errors into the
        intelligence_quality record. Documented, not fixed — the error COUNT
        overstates the number of distinct problems."""
        flags = _validate("Please provide your food log for the week.", {"macrofactor": {"exists": True, "records": 30}})
        assert {f["check"] for f in flags} == {"null_claim_vs_data", "stale_action"}


class TestOverconfidenceCheck:
    """Mutation-proof for check 5."""

    ORIENTATION = {"glucose": {"phase": "orientation", "days": 2, "unit": "CGM days"}}

    def test_definitive_language_in_orientation_is_flagged(self):
        flags = _validate("Your pattern shows a clean overnight curve.", maturity=self.ORIENTATION, domain="glucose")
        over = [f for f in flags if f["check"] == "overconfidence"]
        assert over and over[0]["severity"] == "warning"
        assert "2 CGM days" in over[0]["detail"]

    def test_hedged_language_in_orientation_is_clean(self):
        flags = _validate("An early signal suggests a clean overnight curve.", maturity=self.ORIENTATION, domain="glucose")
        assert [f for f in flags if f["check"] == "overconfidence"] == []

    def test_the_same_sentence_is_allowed_once_the_domain_is_established(self):
        maturity = {"glucose": {"phase": "established", "days": 60, "unit": "CGM days"}}
        flags = _validate("Your pattern shows a clean overnight curve.", maturity=maturity, domain="glucose")
        assert [f for f in flags if f["check"] == "overconfidence"] == []

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (P2, VERIFIED) intelligence_common.py:731 validate_coach_output check 5 runs "
            "ONLY when phase == 'orientation'. EMERGING_VOICE (line 219) explicitly instructs "
            '\'Do NOT use definitive language like "your pattern is" or "this shows"\' — and '
            "nothing checks it, so the emerging voice rule is prompt-only (the "
            "reference_prompt_structural_guarantees class). It should also flag definitive "
            "language in emerging. Hurts Matthew: a coach with 8 nights of data can assert a "
            "confirmed pattern and pass validation."
        ),
    )
    def test_definitive_language_is_also_flagged_in_the_emerging_phase(self):
        maturity = {"glucose": {"phase": "emerging", "days": 8, "unit": "CGM days"}}
        flags = _validate("The data confirms your overnight curve is flat.", maturity=maturity, domain="glucose")
        assert [f for f in flags if f["check"] == "overconfidence"]


class TestCrossCoachContradiction:
    """Mutation-proof for check 4."""

    def test_two_coaches_citing_different_values_for_one_unit_are_flagged(self):
        flags = _validate("Your fasting glucose sat at 92 mg/dL.", all_narratives={"nutrition": "Post-meal you hit 180 mg/dL."})
        contra = [f for f in flags if f["check"] == "cross_coach_contradiction"]
        assert contra and contra[0]["severity"] == "warning"

    def test_the_coachs_own_narrative_is_never_compared_against_itself(self):
        narrative = "Glucose ranged from 92 mg/dL to 180 mg/dL."
        flags = _validate(narrative, all_narratives={"physical": narrative}, domain="physical")
        assert [f for f in flags if f["check"] == "cross_coach_contradiction"] == []

    def test_matching_values_raise_nothing(self):
        flags = _validate("Fasting glucose 92 mg/dL.", all_narratives={"nutrition": "Fasting glucose 92 mg/dL."})
        assert [f for f in flags if f["check"] == "cross_coach_contradiction"] == []

    def test_two_legitimately_different_readings_of_one_unit_are_a_false_positive(self):
        """PIN (P2): the check compares any two numbers sharing a unit suffix,
        with no metric identity. A resting HR and a peak HR are both bpm and are
        reported as a contradiction — noise that trains the reviewer to ignore
        the check."""
        flags = _validate("Your resting heart rate is 55 bpm.", all_narratives={"training": "You peaked at 165 bpm."})
        assert [f for f in flags if f["check"] == "cross_coach_contradiction"]

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (P2, VERIFIED) intelligence_common.py:705/709 validate_coach_output check 4: "
            "the numeric-claim regex ends in `\\b` after an alternation containing `%`. `%` is a "
            "non-word character, so `22%` followed by a space or end-of-string has no word "
            "boundary and NEVER matches — every percentage claim (body fat, adherence, recovery) "
            "is invisible to the cross-coach check while mg/dL, bpm, ms, lbs, kcal and g all "
            "match. The `%` alternative should be outside the \\b (or the pattern should use a "
            "lookahead). Hurts Matthew: two coaches can publish different body-fat percentages "
            "on the same day and the contradiction check reports green."
        ),
    )
    def test_percentage_claims_are_compared_too(self):
        flags = _validate("Your body fat is 22% right now.", all_narratives={"nutrition": "Body fat is closer to 26% by my read."})
        assert [f for f in flags if f["check"] == "cross_coach_contradiction"]


class TestValidatorSurfaceIsHonestAboutItself:
    def _all_emitted_checks(self):
        """Drive every documented check with a narrative built to trip it and
        collect the check names that can actually fire."""
        emitted = set()
        inventory = {
            "dexa": {"exists": True, "records": 3, "latest": "2026-07-02"},
            "garmin": {"exists": True, "records": 40, "latest": "2026-08-08"},
            "apple_health": {"exists": True, "records": 90, "latest": "2026-08-08"},
        }
        orientation = {"physical": {"phase": "orientation", "days": 2, "unit": "days"}}
        for narrative, extra in (
            ("Your body composition remains unknown.", {}),
            ("Action: obtain a DEXA scan.", {}),
            ("You walked 12,000 steps yesterday.", {}),  # check 3 — SOT
            ("Weight is 250 lbs.", {"all_narratives": {"nutrition": "Weight is 244 lbs."}}),
            ("Your pattern shows real progress.", {}),
        ):
            for flag in ic.validate_coach_output(
                "physical_coach", "physical", narrative, inventory, orientation, extra.get("all_narratives")
            ):
                emitted.add(flag["check"])
        return emitted

    def test_the_four_live_checks_all_fire(self):
        assert self._all_emitted_checks() >= {
            "null_claim_vs_data",
            "stale_action",
            "cross_coach_contradiction",
            "overconfidence",
        }

    def test_a_steps_claim_with_both_step_sources_present_produces_no_flag(self):
        """States the dark branch concretely: check 3 parses the step count,
        confirms both sources exist, and then does nothing."""
        inventory = {"garmin": {"exists": True, "records": 40}, "apple_health": {"exists": True, "records": 90}}
        assert [f for f in _validate("You walked 12,000 steps yesterday.", inventory) if "sot" in f["check"]] == []

    def test_a_malformed_step_figure_does_not_crash_the_validator(self):
        """The check runs int() on the regex group — a crash here would lose a
        whole coach narrative, not just a check."""
        inventory = {"garmin": {"exists": True, "records": 1}, "apple_health": {"exists": True, "records": 1}}
        for narrative in ("You walked 1,,2,3 steps.", "You walked 0 steps.", "12,345,678 steps logged."):
            ic.validate_coach_output("c", "physical", narrative, inventory, _MATURITY_EMERGING)

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (P1, VERIFIED) intelligence_common.py:690-700 validate_coach_output check 3 "
            "('SOT violation') is a no-op: it parses the step count into a discarded expression, "
            "confirms garmin and apple_health both exist, and then executes `pass` with a "
            "'deferred to full implementation' comment. write_quality_results nevertheless "
            "records checks_run=5, so the intelligence_quality partition asserts a check that "
            "cannot produce a flag — the gate reports green while dark (the ADR-125/#1927 "
            "class). It should either compare the cited figure against the garmin source of "
            "truth or be removed and checks_run derived. Hurts Matthew: a coach can cite Apple "
            "Health's step count as fact while CLAUDE.md names garmin the SOT, and the honesty "
            "layer scores it clean."
        ),
    )
    def test_the_advertised_check_count_matches_the_checks_that_can_fire(self, wired):
        table, _s3 = wired
        ic.write_quality_results("2026-08-08", "physical_coach", "physical", [])
        assert table.puts[0]["checks_run"] == len(self._all_emitted_checks())


class TestWriteQualityResults:
    def test_the_record_lands_on_the_intelligence_quality_partition(self, wired):
        table, _s3 = wired
        ic.write_quality_results("2026-08-08", "physical_coach", "physical", [])
        item = table.puts[0]
        assert item["pk"] == "USER#matthew"
        assert item["sk"] == "SOURCE#intelligence_quality#2026-08-08#physical_coach"
        assert item["validated_at"] == "2026-08-08T12:00:00+00:00"

    def test_errors_and_warnings_are_counted_separately(self, wired):
        table, _s3 = wired
        flags = [{"severity": "error"}, {"severity": "error"}, {"severity": "warning"}]
        ic.write_quality_results("2026-08-08", "c", "d", flags)
        assert (table.puts[0]["errors"], table.puts[0]["warnings"]) == (2, 1)

    def test_no_float_ever_reaches_put_item(self, wired):
        """boto3 rejects Python floats; a float in a flag payload would raise
        inside the writer and lose the quality record entirely."""
        table, _s3 = wired
        ic.write_quality_results("2026-08-08", "c", "d", [{"severity": "warning", "score": 0.5, "nested": {"x": [1.25]}}])

        def walk(node):
            if isinstance(node, dict):
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)
            else:
                assert not isinstance(node, float), node

        walk(table.puts[0])
        assert isinstance(table.puts[0]["flags"][0]["score"], Decimal)

    def test_a_write_failure_is_swallowed_so_the_narrative_still_ships(self, wired):
        table, _s3 = wired

        def boom(**_kwargs):
            raise RuntimeError("throttled")

        table.put_item = boom
        ic.write_quality_results("2026-08-08", "c", "d", [])  # must not raise

    def test_a_flag_without_a_severity_raises_before_the_try_block(self, wired):
        """PIN (P3, latent): the severity tally runs OUTSIDE the try, so a flag
        shaped by a future caller without `severity` raises KeyError into the
        coach run rather than being logged. No current producer emits such a
        flag — pinned so a new one is a deliberate decision."""
        with pytest.raises(KeyError):
            ic.write_quality_results("2026-08-08", "c", "d", [{"check": "x"}])


# ══════════════════════════════════════════════════════════════════════════════
# MOVEMENT HONESTY GUARD (DI-1.3 / C-4 #494)
# ══════════════════════════════════════════════════════════════════════════════


def _ingest_health_vocabulary():
    """The statuses `ingest_health.evaluate_source_health` can actually return,
    read off the writer rather than restated here — a rename there must not
    leave `_PIPE_HEALTHY_STATUSES` silently matching nothing."""
    path = os.path.join(ROOT, "lambdas", "ingestion", "ingest_health.py")
    with open(path, encoding="utf-8") as fh:
        return set(re.findall(r'"status":\s*"(\w+)"', fh.read()))


class TestPipeConfirmedLive:
    def test_the_writers_vocabulary_still_contains_every_unlocking_status(self):
        """Reader/writer contract: if evaluate_source_health stopped emitting
        'ok', the C-4 rest branch would be permanently dark."""
        assert ic._PIPE_HEALTHY_STATUSES <= _ingest_health_vocabulary()

    def test_only_the_registered_statuses_unlock_the_verdict(self):
        """Derived over the writer's whole vocabulary — mutation-proof for
        `_pipe_confirmed_live`: widening the set fails here."""
        for status in _ingest_health_vocabulary():
            expected = status in ic._PIPE_HEALTHY_STATUSES
            assert ic._pipe_confirmed_live({"strava": status}, "strava") is expected, status

    def test_a_missing_or_none_sentinel_is_never_confirmed(self):
        assert ic._pipe_confirmed_live({}, "strava") is False
        assert ic._pipe_confirmed_live({"strava": None}, "strava") is False
        assert ic._pipe_confirmed_live(None, "strava") is False

    def test_another_sources_health_never_unlocks_stravas_verdict(self):
        assert ic._pipe_confirmed_live({"garmin": "ok"}, "strava") is False


class TestMovementAssessability:
    def test_a_live_strava_is_assessable(self):
        assert ic.movement_assessability({"strava": "live", "garmin": "live", "steps": "live"})["assessable"] is True

    def test_every_note_source_reports_its_own_unavailable_state(self):
        """Derived over `_MOVEMENT_NOTE_SOURCES` so a source added to the tuple
        cannot be silently dropped from the note."""
        states = {src: "paused" for src in ic._MOVEMENT_NOTE_SOURCES}
        result = ic.movement_assessability(states)
        assert [s for s, _st in result["unavailable"]] == list(ic._MOVEMENT_NOTE_SOURCES)
        for src in ic._MOVEMENT_NOTE_SOURCES:
            assert src in result["note"]

    def test_a_non_live_strava_without_pipe_health_withholds_the_verdict(self):
        result = ic.movement_assessability({"strava": "paused", "garmin": "stale", "steps": "missing"})
        assert result["assessable"] is False
        assert result["assessable_as_rest"] is False
        assert result["note"].startswith("movement sources unavailable")

    def test_a_healthy_pipe_with_no_records_is_honest_rest_not_a_gap(self):
        result = ic.movement_assessability({"strava": "stale", "garmin": "stale", "steps": "missing"}, {"strava": "ok"})
        assert (result["assessable"], result["assessable_as_rest"]) == (True, True)
        assert "genuine behavioral rest, not a data gap" in result["rest_note"]
        assert result["note"] == ""  # the unavailability note is not doubled up

    def test_a_failing_pipe_with_no_records_still_withholds(self):
        for status in _ingest_health_vocabulary() - ic._PIPE_HEALTHY_STATUSES:
            result = ic.movement_assessability({"strava": "paused"}, {"strava": status})
            assert result["assessable"] is False, status

    def test_state_labels_are_humanised_in_the_note(self):
        assert "garmin: rate-limited" in ic.movement_assessability({"garmin": "rate_limited"})["note"]

    def test_the_unqualified_rest_note_branch_can_never_be_reached(self):
        """DEAD BRANCH (P3, VERIFIED) intelligence_common.py:1174-1178: the
        `else` that emits a rest note WITHOUT a source list requires
        `assessable_as_rest and not unavailable`. But assessable_as_rest
        requires strava to be non-live, and strava is in `_MOVEMENT_NOTE_SOURCES`,
        so a non-live strava always lands in `unavailable` — the two conditions
        are mutually exclusive. Derived from the module's own registry so it
        stays true if the note-source tuple changes."""
        assert "strava" in ic._MOVEMENT_NOTE_SOURCES
        for state in ("paused", "stale", "rate_limited", "missing"):
            result = ic.movement_assessability({"strava": state}, {"strava": "ok"})
            assert result["assessable_as_rest"] is True
            assert result["unavailable"], state
            assert "no activity logged" in result["rest_note"]

    def test_an_absent_movement_state_is_read_as_live(self):
        """PIN (P2): `states.get(src, "live")` plus `None in _MOVEMENT_LIVE_STATES`
        means BOTH an omitted source-state map and an explicit None read as
        LIVE — an unknown pipe state buys the confident verdict. Reachable:
        ai_expert_analyzer_lambda.py:1360 passes `_td.get("movement_source_state")`,
        which is None whenever the key is absent from the thread payload.
        ADR-104 would read an unknown state as unavailable, not live."""
        assert ic.movement_assessability(None)["assessable"] is True
        assert ic.movement_assessability({})["assessable"] is True
        assert ic.movement_assessability({"strava": None})["assessable"] is True
        assert None in ic._MOVEMENT_LIVE_STATES


class TestMovementHonestyGuard:
    UNDERTRAINED = "You are under-training this week and it shows in your recovery."
    NOT_ASSESSABLE = {"assessable": False, "assessable_as_rest": False, "note": "movement sources unavailable (strava: paused)"}

    def test_an_undertraining_verdict_is_withheld_when_movement_is_unreadable(self):
        """Mutation-proof: delete the guard body and this fails."""
        out = ic.apply_movement_honesty_guard(self.UNDERTRAINED, self.NOT_ASSESSABLE)
        assert "under-training" not in out
        assert "not assessable" in out
        assert "strava: paused" in out

    def test_the_logged_hevy_training_is_still_reported(self):
        """The withheld verdict is only the NEAT/aerobic one — strength work
        that DID happen must not disappear with it."""
        out = ic.apply_movement_honesty_guard(self.UNDERTRAINED, self.NOT_ASSESSABLE, hevy_present=True, hevy_summary="4 sessions, 96 sets")
        assert "Logged training this period: 4 sessions, 96 sets." in out

    def test_hevy_present_without_a_summary_still_states_that_training_happened(self):
        out = ic.apply_movement_honesty_guard(self.UNDERTRAINED, self.NOT_ASSESSABLE, hevy_present=True)
        assert "Strength training was logged this period (Hevy)." in out

    def test_an_assessable_picture_passes_the_verdict_through_untouched(self):
        assert ic.apply_movement_honesty_guard(self.UNDERTRAINED, {"assessable": True}) == self.UNDERTRAINED

    def test_a_summary_with_nothing_to_withhold_is_untouched(self):
        text = "Recovery is trending up and sleep debt is falling."
        assert ic.apply_movement_honesty_guard(text, self.NOT_ASSESSABLE) == text

    def test_an_empty_assessability_dict_is_a_no_op(self):
        assert ic.apply_movement_honesty_guard(self.UNDERTRAINED, {}) == self.UNDERTRAINED

    def test_every_withheld_phrasing_the_pattern_claims_is_actually_caught(self):
        """Mutation-proof over the guard's own regex: each alternative must
        actually fire on realistic coach prose."""
        for phrase in (
            "you are under-training",
            "you are undertraining",
            "this is a sedentary week",
            "too few workouts logged",
            "you are not moving enough",
            "low training stimulus",
            "lack of activity",
            "insufficient training",
            "barely training",
            "mostly rest days",
            "you risk detraining",
            "over-resting is the risk",
        ):
            out = ic.apply_movement_honesty_guard(f"My read: {phrase} this period.", self.NOT_ASSESSABLE)
            assert "not assessable" in out, phrase

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (P2, VERIFIED) intelligence_common.py:1121 _UNDERTRAINING_PATTERN is a "
            "phrase list, so semantically identical verdicts phrased outside it pass the guard "
            "untouched ('you barely moved', 'your movement has been minimal', 'almost nothing "
            "logged all week'). It reports the guard as applied while the same false claim "
            "ships. A structural check (withhold any adequacy VERDICT when not assessable, "
            "rather than matching its wording) is the fix — the "
            "reference_prompt_structural_guarantees class. Hurts Matthew: he is told he was "
            "sedentary during a week the platform could not see."
        ),
    )
    def test_paraphrased_undertraining_verdicts_are_also_withheld(self):
        for phrase in ("you barely moved", "your movement has been minimal", "almost nothing was logged all week"):
            out = ic.apply_movement_honesty_guard(f"My read: {phrase}.", self.NOT_ASSESSABLE)
            assert "not assessable" in out, phrase


# ══════════════════════════════════════════════════════════════════════════════
# COACH THREADS — persistent memory + the #1203 Limit-before-Filter trap
# ══════════════════════════════════════════════════════════════════════════════


class LimitThenFilterTable:
    """A fake with REAL DynamoDB read semantics: `Limit` bounds the rows read
    from the index, and only then does `FilterExpression` remove rows from that
    page (#1203). Bounded — `rows` is a finite list, never a generator."""

    def __init__(self, rows, current_phase="experiment"):
        self.rows = list(rows)
        self.current_phase = current_phase
        self.queries = []

    def query(self, **kwargs):
        self.queries.append(kwargs)
        page = sorted(self.rows, key=lambda r: r["sk"], reverse=not kwargs.get("ScanIndexForward", True))
        limit = kwargs.get("Limit")
        if limit is not None:
            page = page[:limit]
        if "FilterExpression" in kwargs:
            page = [r for r in page if r.get("phase") in (None, self.current_phase)]
        return {"Items": page}

    def put_item(self, Item=None, **_kwargs):
        return {}


def _thread_rows():
    """Four pilot-tagged (pre-reset) entries newer than three live ones — the
    shape the table holds in the days after a cycle genesis."""
    rows = []
    for day, phase in (
        ("2026-08-07", "pilot"),
        ("2026-08-06", "pilot"),
        ("2026-08-05", "pilot"),
        ("2026-08-04", "pilot"),
        ("2026-08-03", None),
        ("2026-08-02", None),
        ("2026-08-01", None),
    ):
        row = {
            "pk": "USER#matthew",
            "sk": f"SOURCE#coach_thread#sleep#{day}",
            "week": "2026-W32",
            "position_summary": f"pos {day}",
            "predictions": [],
        }
        if phase:
            row["phase"] = phase
        rows.append(row)
    return rows


class TestCoachThreadReads:
    def test_the_thread_read_is_scoped_to_one_coach_newest_first(self, wired):
        table, _s3 = wired
        ic.read_coach_thread("sleep", limit=4)
        kwargs = table.queries[0]
        assert _condition_values(kwargs["KeyConditionExpression"]) == ["USER#matthew", "SOURCE#coach_thread#sleep#"]
        assert kwargs["ScanIndexForward"] is False
        assert kwargs["Limit"] == 4

    def test_the_thread_partition_is_phase_filtered_as_the_taxonomy_requires(self, wired):
        """SOURCE#coach_thread is EXPERIMENT_SCOPED — the filter is correct
        here; it's the pairing with Limit that is not."""
        table, _s3 = wired
        ic.read_coach_thread("sleep")
        assert phase_taxonomy.classify("USER#matthew", "SOURCE#coach_thread#sleep#2026-08-08") == phase_taxonomy.EXPERIMENT_SCOPED
        assert "#phase" in str(table.queries[0]["FilterExpression"])

    def test_a_read_failure_degrades_to_no_memory_rather_than_crashing(self, monkeypatch):
        table = FakeTable()
        table.fail_pks.add("USER#matthew")
        monkeypatch.setattr(ic, "table", table)
        assert ic.read_coach_thread("sleep") == []

    def test_decimals_are_converted_for_the_prompt_layer(self, monkeypatch):
        rows = [{"pk": "USER#matthew", "sk": "SOURCE#coach_thread#sleep#2026-08-07", "predictions": [{"confidence": Decimal("0.8")}]}]
        monkeypatch.setattr(ic, "table", FakeTable(router=lambda kw, pk: {"Items": rows}))
        assert ic.read_coach_thread("sleep")[0]["predictions"][0]["confidence"] == 0.8

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (P1, VERIFIED) intelligence_common.py:1266-1274 read_coach_thread combines "
            "Limit with the ADR-058 FilterExpression. DynamoDB applies Limit BEFORE the filter "
            "(#1203 — the mechanism this file's own build_data_inventory docstring documents at "
            "line 135), so when the newest `limit` thread rows are pilot-tagged (every cycle "
            "reset) the read returns fewer rows than exist, or none at all, while live entries "
            "sit just past the page. It should page until `limit` VISIBLE rows are collected, "
            "or bound with a key floor (phase_taxonomy.cycle_read_floor) instead of a filter. "
            "Hurts Matthew: build_thread_prompt_block then tells a coach with months of history "
            "'This is your first assessment', and compute_credibility reports n=0."
        ),
    )
    def test_live_entries_beyond_the_first_page_are_still_reachable(self, monkeypatch):
        monkeypatch.setattr(ic, "table", LimitThenFilterTable(_thread_rows()))
        assert ic.read_coach_thread("sleep", limit=4) != []


class TestThreadPromptBlock:
    def _wire(self, monkeypatch, entries):
        monkeypatch.setattr(ic, "read_coach_thread", lambda coach_id, limit=4: entries)

    def test_no_history_returns_the_personality_seed_and_says_so(self, monkeypatch):
        self._wire(monkeypatch, [])
        block = ic.build_thread_prompt_block(
            "sleep", personality={"tendencies": ["skeptical"], "arc_seed": "seed", "signature_behavior": "sig"}
        )
        assert "This is your first assessment" in block
        assert "skeptical" in block

    def test_no_history_and_no_personality_returns_nothing_rather_than_a_stub(self, monkeypatch):
        self._wire(monkeypatch, [])
        assert ic.build_thread_prompt_block("sleep") == ""

    def test_prior_positions_predictions_and_surprises_are_all_replayed(self, monkeypatch):
        self._wire(
            monkeypatch,
            [
                {
                    "week": "2026-W32",
                    "position_summary": "I think sleep debt is building",
                    "predictions": [{"text": "HRV falls", "confidence": "high", "status": "refuted", "outcome_note": "it rose"}],
                    "surprises": ["a 90% recovery"],
                    "stance_changes": [{"from": "worried", "to": "curious", "reason": "the data"}],
                    "emotional_investment": "invested",
                    "open_questions": ["is the late caffeine the driver?"],
                }
            ],
        )
        block = ic.build_thread_prompt_block("sleep")
        assert 'Week 2026-W32 position: "I think sleep debt is building"' in block
        assert '(high confidence): "HRV falls" (REFUTED — it rose)' in block
        assert 'Week 2026-W32 surprise: "a 90% recovery"' in block
        assert '"worried" → "curious"' in block
        assert "Your emotional investment level: INVESTED" in block
        assert "is the late caffeine the driver?" in block

    def test_the_investment_level_is_read_from_the_newest_entry(self, monkeypatch):
        """`entries[0]` is 'latest' only because read_coach_thread queries
        newest-first — pinned so a change to that ordering is caught here."""
        self._wire(monkeypatch, [{"emotional_investment": "concerned"}, {"emotional_investment": "detached"}])
        assert "Your emotional investment level: CONCERNED" in ic.build_thread_prompt_block("sleep")

    def test_the_thread_usage_rules_always_ship_with_the_history(self, monkeypatch):
        self._wire(monkeypatch, [{"position_summary": "p"}])
        assert "If a prediction resolved: explicitly call it out" in ic.build_thread_prompt_block("sleep")

    def test_the_personality_seed_still_ships_alongside_an_existing_thread(self, monkeypatch):
        self._wire(monkeypatch, [{"position_summary": "p"}])
        block = ic.build_thread_prompt_block("sleep", personality={"tendencies": ["skeptical"], "signature_behavior": "asks for n"})
        assert "YOUR PERSONALITY:\n- skeptical" in block
        assert "Signature behavior: asks for n" in block


class TestWriteCoachThread:
    def test_the_entry_lands_keyed_by_coach_and_frozen_date(self, wired):
        table, _s3 = wired
        assert ic.write_coach_thread("sleep", {"position_summary": "p"}) is True
        item = table.puts[0]
        assert item["sk"] == "SOURCE#coach_thread#sleep#2026-08-08"
        assert item["date"] == "2026-08-08"
        assert item["week"] == ic._iso_week("2026-08-08")

    def test_missing_optional_fields_become_empty_collections_not_nulls(self, wired):
        table, _s3 = wired
        ic.write_coach_thread("sleep", {})
        item = table.puts[0]
        assert item["predictions"] == [] and item["surprises"] == [] and item["learning_log"] == []
        assert item["emotional_investment"] == "observing"

    def test_floats_in_an_entry_are_decimalised_before_the_write(self, wired):
        table, _s3 = wired
        ic.write_coach_thread("sleep", {"predictions": [{"confidence": 0.75}]})
        assert isinstance(table.puts[0]["predictions"][0]["confidence"], Decimal)

    def test_a_write_failure_is_reported_as_false_not_raised(self, monkeypatch):
        _freeze(monkeypatch)
        table = FakeTable()

        def boom(**_kwargs):
            raise RuntimeError("throttled")

        table.put_item = boom
        monkeypatch.setattr(ic, "table", table)
        assert ic.write_coach_thread("sleep", {}) is False


class TestUpdatePredictionStatus:
    def test_a_matching_prediction_is_rewritten_with_its_outcome(self, monkeypatch):
        _freeze(monkeypatch)
        entry = {
            "pk": "USER#matthew",
            "sk": "SOURCE#coach_thread#sleep#2026-08-07",
            "predictions": [{"prediction_id": "p1", "status": "pending"}],
        }
        table = FakeTable()
        monkeypatch.setattr(ic, "table", table)
        monkeypatch.setattr(ic, "read_coach_thread", lambda coach_id, limit=10: [entry])
        assert ic.update_prediction_status("sleep", "p1", "confirmed", "it happened") is True
        written = table.puts[0]["predictions"][0]
        assert written["status"] == "confirmed"
        assert written["outcome_note"] == "it happened"
        assert written["evaluated_at"] == "2026-08-08T12:00:00+00:00"

    def test_a_write_failure_is_reported_false_rather_than_raised(self, monkeypatch):
        _freeze(monkeypatch)
        table = FakeTable()

        def boom(**_kwargs):
            raise RuntimeError("throttled")

        table.put_item = boom
        monkeypatch.setattr(ic, "table", table)
        monkeypatch.setattr(ic, "read_coach_thread", lambda coach_id, limit=10: [{"predictions": [{"prediction_id": "p1"}]}])
        assert ic.update_prediction_status("sleep", "p1", "confirmed") is False

    def test_an_unknown_prediction_id_is_reported_false_and_writes_nothing(self, monkeypatch):
        _freeze(monkeypatch)
        table = FakeTable()
        monkeypatch.setattr(ic, "table", table)
        monkeypatch.setattr(ic, "read_coach_thread", lambda coach_id, limit=10: [{"predictions": [{"prediction_id": "other"}]}])
        assert ic.update_prediction_status("sleep", "p1", "confirmed") is False
        assert table.puts == []

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (P1, VERIFIED) intelligence_common.py:1282 update_prediction_status has NO "
            "caller in lambdas/ or mcp/ — coach_prediction_evaluator has its own private "
            "_update_prediction_status (coach_prediction_evaluator.py:865) which writes to "
            "COACH#{coach}/PREDICTION#{id}, a DIFFERENT store from the SOURCE#coach_thread "
            "entries compute_credibility grades. So no thread prediction is ever resolved: "
            "stamp_thread_predictions writes status='pending' and nothing ever changes it. "
            "Either the evaluator should also settle thread predictions or the thread's "
            "credibility should read the COACH# store. Hurts Matthew: coach credibility can "
            "never move off its floor, so 'YOUR CREDIBILITY: nascent' is a permanent constant."
        ),
    )
    def test_the_thread_prediction_store_has_a_live_resolver(self):
        assert _live_references("update_prediction_status")


class TestIsoWeek:
    def test_the_week_label_uses_the_iso_year_not_the_calendar_year(self):
        """Regression pin for the `%Y-W%V` trap: 2027-01-01 belongs to ISO week
        2026-W53. `%Y-W%V` would render it 2027-W53, splitting one ISO week
        across two buckets and sorting them wrongly. `isocalendar()[0]` is the
        ISO year, so this module is correct — pinned so it stays that way."""
        assert ic._iso_week("2027-01-01") == "2026-W53"
        assert ic._iso_week("2026-12-28") == "2026-W53"
        assert datetime(2027, 1, 1).strftime("%Y-W%V") == "2027-W53"  # the trap, for contrast

    def test_dates_in_one_iso_week_share_one_bucket_across_the_year_boundary(self):
        assert ic._iso_week("2026-12-28") == ic._iso_week("2027-01-03")

    def test_week_numbers_are_zero_padded_so_they_sort(self):
        assert ic._iso_week("2026-03-02") == "2026-W10"
        assert ic._iso_week("2026-01-05") == "2026-W02"


# ══════════════════════════════════════════════════════════════════════════════
# PREDICTION STAMPING (ADR-106 — only code owns identity + deadlines)
# ══════════════════════════════════════════════════════════════════════════════

TODAY = "2026-08-08"


@pytest.fixture
def no_prior(monkeypatch):
    monkeypatch.setattr(ic, "read_coach_thread", lambda coach_id, limit=10: [])


class TestTimeframeWindows:
    def test_the_documented_horizons_map_to_hand_derived_dates(self, no_prior):
        # 2026-08-08 + 14 = 08-22; + 30 = 09-07 (23 days left in August, then 7);
        # + 3 = 08-11; + 21 = 08-29
        for timeframe, expected in (
            ("", "2026-08-22"),
            ("in 2 weeks", "2026-08-22"),
            ("in 3 weeks", "2026-08-29"),
            ("by next month", "2026-09-07"),
            ("in 3 days", "2026-08-11"),
        ):
            out = ic.stamp_thread_predictions(
                "sleep", [{"text": f"claim {timeframe}", "metric": "hrv", "timeframe": timeframe}], today=TODAY
            )
            assert out[0]["target_date"] == expected, timeframe

    def test_a_zero_window_is_pushed_to_a_strictly_future_date(self, no_prior):
        out = ic.stamp_thread_predictions("sleep", [{"text": "claim now", "timeframe": "in 0 days"}], today=TODAY)
        assert out[0]["target_date"] == "2026-08-09"

    def test_an_unparseable_horizon_silently_becomes_the_fourteen_day_default(self):
        """PIN (P2, ADR-105): a claim whose horizon the mapper cannot read is
        stamped with an INVENTED two-week deadline and carries no marker saying
        so, so the grader treats an unbounded claim as a dated forecast. An
        honest shape would record `timeframe_parsed: False`."""
        assert ic._timeframe_to_window_days("whenever the weather turns") == 14
        assert ic._timeframe_to_window_days("soon") == 14
        assert ic._timeframe_to_window_days(None) == 14


class TestStampIdentity:
    def test_a_model_authored_id_and_date_are_stripped(self, no_prior):
        out = ic.stamp_thread_predictions(
            "sleep",
            [
                {
                    "prediction_id": "pred_20240101_bogus",
                    "target_date": "2020-01-01",
                    "text": "HRV will rise",
                    "confidence": "high",
                    "metric": "hrv",
                }
            ],
            today=TODAY,
        )
        assert out[0]["prediction_id"] == "pred_20260808_hrv_will_rise"
        assert out[0]["target_date"] > TODAY

    def test_a_textless_prediction_is_dropped_rather_than_stamped(self, no_prior):
        assert ic.stamp_thread_predictions("sleep", [{"text": "   "}, {"confidence": "high"}], today=TODAY) == []

    def test_a_prediction_of_pure_punctuation_is_dropped(self, no_prior):
        """`_prediction_slug` strips to empty — a record with an empty semantic
        key would collide with every other empty one."""
        assert ic.stamp_thread_predictions("sleep", [{"text": "???"}], today=TODAY) == []

    def test_a_missing_confidence_defaults_to_medium_and_is_stated(self, no_prior):
        out = ic.stamp_thread_predictions("sleep", [{"text": "recovery improves"}], today=TODAY)
        assert out[0]["confidence"] == "medium"

    def test_a_metricless_claim_is_still_stamped_with_a_deadline(self, no_prior):
        """PIN: the docstring says a target_date is stamped 'whenever a metric
        is present', but the code stamps unconditionally — so a claim with no
        metric becomes an expirable record the grader cannot decide."""
        out = ic.stamp_thread_predictions("sleep", [{"text": "you will feel better"}], today=TODAY)
        assert out[0]["metric"] is None
        assert out[0]["target_date"] == "2026-08-22"
        assert out[0]["status"] == "pending"

    def test_a_reemitted_claim_keeps_its_original_id_and_deadline(self, monkeypatch):
        prior = {
            "prediction_id": "pred_20260801_hrv_will_rise",
            "semantic_key": "hrv_will_rise",
            "target_date": "2026-08-15",
            "first_seen": "2026-08-01",
            "status": "pending",
        }
        monkeypatch.setattr(ic, "read_coach_thread", lambda coach_id, limit=10: [{"predictions": [prior]}])
        out = ic.stamp_thread_predictions("sleep", [{"text": "HRV will rise", "confidence": "low"}], today=TODAY)
        assert out[0]["prediction_id"] == "pred_20260801_hrv_will_rise"
        assert out[0]["target_date"] == "2026-08-15"
        assert out[0]["first_seen"] == "2026-08-01"
        assert out[0]["reaffirmed_on"] == TODAY

    def test_a_resolved_prior_claim_is_not_carried_forward(self, monkeypatch):
        prior = {"prediction_id": "old", "semantic_key": "hrv_will_rise", "target_date": "2026-08-15", "status": "confirmed"}
        monkeypatch.setattr(ic, "read_coach_thread", lambda coach_id, limit=10: [{"predictions": [prior]}])
        out = ic.stamp_thread_predictions("sleep", [{"text": "HRV will rise"}], today=TODAY)
        assert out[0]["prediction_id"] == "pred_20260808_hrv_will_rise"

    def test_a_prior_lookup_failure_still_produces_a_valid_stamp(self, monkeypatch):
        def boom(coach_id, limit=10):
            raise RuntimeError("ddb down")

        monkeypatch.setattr(ic, "read_coach_thread", boom)
        out = ic.stamp_thread_predictions("sleep", [{"text": "HRV will rise", "metric": "hrv"}], today=TODAY)
        assert out[0]["target_date"] == "2026-08-22"

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (P2, VERIFIED) intelligence_common.py:1390 _prediction_slug truncates to the "
            "first 40 characters, so two distinct claims sharing a 40-char prefix collapse to "
            "one semantic_key and `stamped[key] = rec` (line 1480) silently drops the first. "
            "'Your resting heart rate will fall below 55 bpm' and '...below 60 bpm' differ only "
            "past char 40. It should hash the full text (or key on text+metric). Hurts Matthew: "
            "a forecast the coach actually made is never recorded and never graded."
        ),
    )
    def test_two_claims_differing_past_forty_characters_stay_distinct(self, no_prior):
        out = ic.stamp_thread_predictions(
            "sleep",
            [
                {"text": "Your resting heart rate will fall below 55 bpm", "metric": "rhr"},
                {"text": "Your resting heart rate will fall below 60 bpm", "metric": "rhr"},
            ],
            today=TODAY,
        )
        assert len(out) == 2

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (P2, VERIFIED) intelligence_common.py:1462-1463 stamp_thread_predictions "
            "carries a prior open prediction forward with `target_date: carried.get('target_date')` "
            "and `first_seen: carried.get('first_seen') or carried.get('target_date')`. A prior "
            "written before #725 has no target_date, so the re-emitted record gets "
            "target_date=None — ungradeable, permanently pending, and re-carried every day "
            "forever; and when only first_seen is missing, first_seen is back-filled from a "
            "FUTURE date. It should re-stamp a missing deadline from today's timeframe and "
            "leave first_seen honestly unknown. Hurts Matthew: a zombie prediction inflates "
            "predictions_total and never resolves."
        ),
    )
    def test_a_carried_prediction_without_a_deadline_is_restamped_not_nulled(self, monkeypatch):
        prior = {"prediction_id": "legacy", "semantic_key": "hrv_will_rise", "status": "pending"}
        monkeypatch.setattr(ic, "read_coach_thread", lambda coach_id, limit=10: [{"predictions": [prior]}])
        out = ic.stamp_thread_predictions("sleep", [{"text": "HRV will rise"}], today=TODAY)
        assert out[0]["target_date"] is not None
        assert out[0]["first_seen"] is None or out[0]["first_seen"] <= TODAY


# ══════════════════════════════════════════════════════════════════════════════
# CREDIBILITY (#538 — Brier-backed, ADR-105)
# ══════════════════════════════════════════════════════════════════════════════


class TestComputeCredibility:
    def _wire(self, monkeypatch, predictions):
        monkeypatch.setattr(ic, "read_coach_thread", lambda coach_id, limit=20: [{"predictions": predictions}])

    def test_no_history_reports_the_floor_with_its_n_not_a_flattering_default(self, monkeypatch):
        self._wire(monkeypatch, [])
        result = ic.compute_credibility("sleep")
        assert result["label"] == "nascent"
        assert result["predictions_resolved"] == 0
        assert result["calibration"] == "insufficient_data"
        assert result["brier"] is None  # ADR-104: no score is invented from no data

    def test_pending_predictions_are_counted_but_never_scored(self, monkeypatch):
        self._wire(monkeypatch, [{"status": "pending", "confidence": "high"} for _ in range(6)])
        result = ic.compute_credibility("sleep")
        assert (result["predictions_total"], result["pending"], result["predictions_resolved"]) == (6, 6, 0)

    def test_a_resolved_track_record_is_scored_with_its_n(self, monkeypatch):
        # 8 confirmed + 4 refuted -> n=12, accuracy = 8/12 = 66.7%
        self._wire(
            monkeypatch,
            [{"status": "confirmed", "confidence": "high"} for _ in range(8)]
            + [{"status": "refuted", "confidence": "medium"} for _ in range(4)],
        )
        result = ic.compute_credibility("sleep")
        assert (result["confirmed"], result["refuted"], result["predictions_resolved"]) == (8, 4, 12)
        assert result["accuracy_pct"] == round(100 * 8 / 12, 1)

    def test_every_field_the_preamble_and_the_site_read_is_always_present(self, monkeypatch):
        self._wire(monkeypatch, [])
        for field in (
            "score",
            "label",
            "accuracy_pct",
            "calibration",
            "brier",
            "brier_skill",
            "reliability_bins",
            "predictions_total",
            "predictions_resolved",
            "confirmed",
            "refuted",
            "pending",
        ):
            assert field in ic.compute_credibility("sleep")

    def test_an_unresolved_accuracy_is_flattened_to_zero_percent(self, monkeypatch):
        """PIN (P3, ADR-104): calibration_core returns accuracy_pct=None for
        n=0 — an honest 'unknown'. compute_credibility replaces it with 0, and
        the preamble renders '0% accuracy'. The n=0 alongside it is the only
        thing keeping that from reading as a measured failure."""
        self._wire(monkeypatch, [])
        result = ic.compute_credibility("sleep")
        assert result["accuracy_pct"] == 0
        assert result["predictions_resolved"] == 0

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (P1, VERIFIED) intelligence_common.py:1587 compute_credibility has NO caller "
            "in lambdas/ or mcp/ and its result is never persisted; the only live credibility "
            "read (load_credibility, line 1629) reads SOURCE#coach_credibility#, which no module "
            "writes. Combined with the unresolvable thread predictions above, the credibility "
            "surface is dark end to end: it can only report 'nascent', never rise or fall. It "
            "should be invoked by the daily coach pipeline and its output stored under the key "
            "load_credibility reads. Hurts Matthew: the coaching layer's self-assessment is a "
            "constant that looks like a measurement."
        ),
    )
    def test_compute_credibility_has_a_live_caller(self):
        assert _live_references("compute_credibility")


class TestLoadCredibility:
    def test_a_stored_record_is_returned_decimal_free(self, wired):
        table, _s3 = wired
        table.store[("USER#matthew", "SOURCE#coach_credibility#sleep")] = {"label": "reliable", "score": Decimal("70")}
        assert ic.load_credibility("sleep") == {"label": "reliable", "score": 70}

    def test_a_missing_record_returns_the_conservative_floor(self, wired):
        assert ic.load_credibility("sleep") == {"label": "nascent", "score": 30}

    def test_a_ddb_outage_returns_the_same_floor_rather_than_raising(self, wired):
        table, _s3 = wired
        table.get_error = RuntimeError("ddb down")
        assert ic.load_credibility("sleep") == {"label": "nascent", "score": 30}

    def test_the_coach_roster_is_covered_by_the_maturity_registry(self):
        """`COACH_IDS_ALL` and `_MATURITY_THRESHOLDS` are two registries for the
        same roster — a coach in one and not the other has either no voice gate
        or no credibility record."""
        assert set(ic.COACH_IDS_ALL) == set(ic._MATURITY_THRESHOLDS)


# ══════════════════════════════════════════════════════════════════════════════
# BUILDER'S PARADOX SCORE
# ══════════════════════════════════════════════════════════════════════════════


def _paradox_router(todoist=None, strava_count=0, notion_count=0, habitify=None, garmin=None):
    rows = {
        "USER#matthew#SOURCE#todoist": ("Items", todoist or []),
        "USER#matthew#SOURCE#strava": ("Count", strava_count),
        "USER#matthew#SOURCE#notion": ("Count", notion_count),
        "USER#matthew#SOURCE#habitify": ("Items", habitify or []),
        "USER#matthew#SOURCE#garmin": ("Items", garmin or []),
    }

    def router(kwargs, pk):
        if pk not in rows:
            return None
        kind, value = rows[pk]
        return {kind: value, "Items": value if kind == "Items" else [], "Count": value if kind == "Count" else 0}

    return router


class TestBuildersParadox:
    def _run(self, monkeypatch, **kw):
        _freeze(monkeypatch)
        table = FakeTable(router=_paradox_router(**kw))
        monkeypatch.setattr(ic, "table", table)
        return ic.compute_builders_paradox_score(days=7), table

    def test_the_window_is_derived_from_the_frozen_clock(self, monkeypatch):
        """2026-08-08 minus 7 days = 2026-08-01."""
        _result, table = self._run(monkeypatch)
        todoist_q = next(q for q in table.queries if _pk_of(q).endswith("#todoist"))
        assert _condition_values(todoist_q["KeyConditionExpression"])[1:] == ["DATE#2026-08-01", "DATE#2026-08-08~"]

    def test_a_balanced_week_scores_healthy_with_hand_derived_components(self, monkeypatch):
        """workouts 3 -> min(25, 15) = 15; journal 2 -> 10; habits 0.80 -> 80% ->
        80*0.25 = 20; steps 8000 -> 8000/320 = 25 (capped). health = 70.
        platform_tasks 0 -> intensity 0 -> raw = 0/70*100 = 0 -> score 0."""
        result, _table = self._run(
            monkeypatch,
            strava_count=3,
            notion_count=2,
            habitify=[{"completion_pct": Decimal("0.80")}],
            garmin=[{"steps": 8000}],
        )
        assert result["health_score"] == 70
        assert result["platform_intensity"] == 0
        assert (result["score"], result["label"]) == (0, "healthy")

    def test_habit_adherence_is_averaged_across_the_window(self, monkeypatch):
        """0.50 and 0.75 -> 50% and 75% -> mean 62.5 -> round() is banker's, 62."""
        result, _table = self._run(monkeypatch, habitify=[{"completion_pct": Decimal("0.50")}, {"completion_pct": Decimal("0.75")}])
        assert result["habit_adherence_pct"] == 62

    def test_an_already_percentage_scaled_habit_value_is_not_multiplied_again(self, monkeypatch):
        result, _table = self._run(monkeypatch, habitify=[{"completion_pct": 80}])
        assert result["habit_adherence_pct"] == 80

    def test_the_tier0_field_is_accepted_as_a_fallback(self, monkeypatch):
        result, _table = self._run(monkeypatch, habitify=[{"tier0_pct": Decimal("0.60")}])
        assert result["habit_adherence_pct"] == 60

    def test_a_non_numeric_habit_value_never_crashes_the_score(self, monkeypatch):
        result, _table = self._run(monkeypatch, habitify=[{"completion_pct": "n/a"}])
        assert result["habit_adherence_pct"] == 0

    def test_a_query_failure_degrades_that_component_to_zero_not_the_whole_score(self, monkeypatch):
        _freeze(monkeypatch)
        table = FakeTable(router=_paradox_router(strava_count=4))
        table.fail_pks.add("USER#matthew#SOURCE#garmin")
        monkeypatch.setattr(ic, "table", table)
        result = ic.compute_builders_paradox_score(days=7)
        assert result["workouts"] == 4
        assert result["avg_steps"] == 0

    def test_every_component_query_fails_soft_independently(self, monkeypatch):
        """PIN (P2, ADR-104): each source's failure silently becomes a ZERO in
        the published components — a broken pipe and a genuinely idle week are
        indistinguishable in the interpretation string, which states both as
        fact ('0 workouts, 0 journal entries')."""
        _freeze(monkeypatch)
        table = FakeTable()
        table.fail_pks.update(f"USER#matthew#SOURCE#{s}" for s in ("todoist", "strava", "notion", "habitify", "garmin"))
        monkeypatch.setattr(ic, "table", table)
        result = ic.compute_builders_paradox_score(days=7)
        assert (result["platform_tasks"], result["workouts"], result["journal_entries"]) == (0, 0, 0)
        assert "0 workouts" in result["interpretation"]

    def test_a_platform_heavy_week_with_no_health_signal_scores_displaced(self, monkeypatch):
        """Hand-derived: tasks 20 -> intensity min(100, 60) = 60; health 0 ->
        raw = 60/max(1, 60) * 100 = 100 -> score 100 -> 'displaced'. (The row
        carries the writer's real field, `completed_count` — #2271.)"""
        result, _table = self._run(monkeypatch, todoist=[{"completed_count": 20}])
        assert (result["platform_intensity"], result["score"], result["label"]) == (60, 100, "displaced")
        assert "consuming the time and energy it was designed to protect" in result["interpretation"]

    def test_a_tipping_week_names_the_trend(self, monkeypatch):
        """workouts 1 -> 5; steps 3200 -> 10; health 15. tasks 3 -> intensity 9.
        raw = 9/24*100 = 37.5 -> round -> 38 -> 'tipping'."""
        result, _table = self._run(monkeypatch, todoist=[{"completed_count": 3}], strava_count=1, garmin=[{"steps": 3200}])
        assert (result["health_score"], result["platform_intensity"], result["score"]) == (15, 9, 38)
        assert result["label"] == "tipping"
        assert "outpacing health behaviors" in result["interpretation"]

    def test_a_non_numeric_task_count_never_crashes_the_score(self, monkeypatch):
        result, _table = self._run(monkeypatch, todoist=[{"completed_count": "many"}])
        assert result["platform_tasks"] == 0

    def test_an_open_task_list_is_never_counted_as_completed_work(self, monkeypatch):
        """#2271: the `tasks` fallback counted the LENGTH of an OPEN task list as
        tasks COMPLETED. No todoist record has ever carried a `tasks` key, so the
        branch was dark — but it was an inversion waiting for a writer, and it is
        now deleted. An open list contributes nothing."""
        result, _table = self._run(monkeypatch, todoist=[{"tasks": [{"id": i} for i in range(30)]}])
        assert result["platform_tasks"] == 0

    def test_the_interpretation_names_every_component_it_scored(self, monkeypatch):
        result, _table = self._run(monkeypatch, strava_count=3, notion_count=1)
        assert "3 workouts" in result["interpretation"]
        assert "1 journal entries" in result["interpretation"]

    def test_completed_todoist_tasks_are_actually_counted(self, monkeypatch):
        """#2271 (was xfail): compute_builders_paradox_score read `tasks_completed`,
        a name the todoist writer has never emitted, so platform_tasks was
        structurally 0 and the one metric built to catch the platform eating
        Matthew's life reported 'balanced' every single day."""
        real_row = {
            "pk": "USER#matthew#SOURCE#todoist",
            "sk": "DATE#2026-08-07",
            "completed_count": Decimal("17"),
            "active_count": Decimal("40"),
            "completed_tasks": [{"task_id": str(i)} for i in range(17)],
        }
        result, _table = self._run(monkeypatch, todoist=[real_row])
        assert result["platform_tasks"] == 17

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (P1, VERIFIED) intelligence_common.py:1046-1068 compute_builders_paradox_score "
            "maps a total data absence (every component 0) to score=50, which falls in the "
            "'tipping' band and prints 'Platform activity is outpacing health behaviors — watch "
            "this trend' alongside '0 platform tasks completed, 0 workouts'. That is an "
            "assertion about behaviour derived from no observations — the ADR-104 "
            "behavioural-absence violation in its purest form. It should return an explicit "
            "'insufficient data' label with no score. Hurts Matthew: on any day the pipes are "
            "quiet the coach tells him the platform is winning, citing nothing."
        ),
    )
    def test_no_data_is_reported_as_no_data_not_as_a_midpoint_verdict(self, monkeypatch):
        result, _table = self._run(monkeypatch)
        assert result["label"] not in ("tipping", "displaced")
        assert "outpacing" not in result["interpretation"]

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (P2, VERIFIED) intelligence_common.py:1027 compute_builders_paradox_score "
            "builds its step series with `if i.get('steps')`, which is falsy for a genuine "
            "0-step day, so zero-movement days are dropped from the mean instead of pulling it "
            "down. It should filter on presence (`'steps' in i`), not truth. Hurts Matthew: a "
            "week with two sedentary days reports the average of the active ones — the health "
            "side of the paradox ratio is systematically flattered."
        ),
    )
    def test_a_zero_step_day_is_averaged_in_rather_than_dropped(self, monkeypatch):
        # steps 0, 0, 9000 -> honest mean 3000; the code returns 9000
        result, _table = self._run(monkeypatch, garmin=[{"steps": 0}, {"steps": 0}, {"steps": 9000}])
        assert result["avg_steps"] == 3000

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (P2, VERIFIED, ADR-105) intelligence_common.py:1013-1014 + 1072-1083 "
            "compute_builders_paradox_score publishes habit_adherence_pct and avg_steps as "
            "point estimates with no sample size — line 1014 computes `len(pcts)` and discards "
            "it in a statement with no effect. A 7-day window that observed one habit row and "
            "one step row is presented identically to one that observed seven. ADR-105 requires "
            "n on every statistical claim. Hurts Matthew: a mean over n=1 reads as a weekly "
            "average."
        ),
    )
    def test_the_averaged_components_publish_their_sample_size(self, monkeypatch):
        result, _table = self._run(monkeypatch, habitify=[{"completion_pct": Decimal("0.5")}], garmin=[{"steps": 5000}])
        assert {"habit_days", "step_days"} & set(result)


# ══════════════════════════════════════════════════════════════════════════════
# ACTION LIFECYCLE
# ══════════════════════════════════════════════════════════════════════════════


class TestOpenActions:
    ROWS = [
        {"pk": "USER#matthew", "sk": "SOURCE#coach_actions#a1", "domain": "sleep", "issued_date": "2026-08-01", "status": "open"},
        {"pk": "USER#matthew", "sk": "SOURCE#coach_actions#a2", "domain": "training", "issued_date": "2026-08-05", "status": "open"},
        {"pk": "USER#matthew", "sk": "SOURCE#coach_actions#a3", "domain": "sleep", "issued_date": "2026-08-03", "status": "open"},
    ]

    def _wire(self, monkeypatch):
        table = FakeTable(router=lambda kw, pk: {"Items": list(self.ROWS)})
        monkeypatch.setattr(ic, "table", table)
        return table

    def test_open_actions_are_requested_with_an_explicit_status_filter(self, monkeypatch):
        table = self._wire(monkeypatch)
        ic.get_open_actions()
        kwargs = table.queries[0]
        assert ":open" in kwargs["ExpressionAttributeValues"]
        assert kwargs["ExpressionAttributeNames"]["#st"] == "status"

    def test_results_are_returned_newest_first(self, monkeypatch):
        self._wire(monkeypatch)
        assert [a["issued_date"] for a in ic.get_open_actions()] == ["2026-08-05", "2026-08-03", "2026-08-01"]

    def test_the_domain_filter_is_applied_client_side(self, monkeypatch):
        self._wire(monkeypatch)
        assert {a["domain"] for a in ic.get_open_actions("sleep")} == {"sleep"}

    def test_a_query_failure_returns_no_actions_rather_than_raising(self, monkeypatch):
        table = FakeTable()
        table.fail_pks.add("USER#matthew")
        monkeypatch.setattr(ic, "table", table)
        assert ic.get_open_actions() == []

    def test_history_is_capped_at_the_requested_limit(self, monkeypatch):
        self._wire(monkeypatch)
        assert len(ic.get_action_history(limit=2)) == 2

    def test_history_is_also_domain_filtered(self, monkeypatch):
        self._wire(monkeypatch)
        assert [a["sk"] for a in ic.get_action_history("sleep")] == ["SOURCE#coach_actions#a3", "SOURCE#coach_actions#a1"]

    def test_history_failure_also_degrades_to_empty(self, monkeypatch):
        table = FakeTable()
        table.fail_pks.add("USER#matthew")
        monkeypatch.setattr(ic, "table", table)
        assert ic.get_action_history() == []


class TestCompleteAction:
    def test_completion_stamps_the_frozen_date_and_the_method(self, wired):
        table, _s3 = wired
        ic.complete_action("a1", method="detected")
        kwargs = table.updates[0]
        assert kwargs["Key"] == {"pk": "USER#matthew", "sk": "SOURCE#coach_actions#a1"}
        assert kwargs["ExpressionAttributeValues"][":cd"] == "2026-08-08"
        assert kwargs["ExpressionAttributeValues"][":cm"] == "detected"

    def test_a_follow_up_note_is_only_written_when_supplied(self, wired):
        table, _s3 = wired
        ic.complete_action("a1")
        assert "follow_up_note" not in table.updates[0]["UpdateExpression"]
        ic.complete_action("a2", note="he did it")
        assert table.updates[1]["ExpressionAttributeValues"][":fn"] == "he did it"

    def test_a_failure_is_raised_to_the_caller_rather_than_swallowed(self, wired):
        table, _s3 = wired

        def boom(**_kwargs):
            raise RuntimeError("throttled")

        table.update_item = boom
        with pytest.raises(RuntimeError):
            ic.complete_action("a1")

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (P2, VERIFIED) intelligence_common.py:903-912 complete_action issues an "
            "unconditional update_item, and DynamoDB update_item UPSERTS. Completing an action "
            "id that does not exist silently CREATES a SOURCE#coach_actions# row whose only "
            "attributes are status=completed + completion_date — a phantom completed action with "
            "no text, domain or issue date, which then flows into get_action_history and the "
            "coach preamble. It should carry ConditionExpression=attribute_exists(pk). Hurts "
            "Matthew: the accountability record can gain completions for work never assigned."
        ),
    )
    def test_completing_an_unknown_action_does_not_mint_a_phantom_record(self, wired):
        table, _s3 = wired
        ic.complete_action("does-not-exist")
        assert "ConditionExpression" in table.updates[0]


# ══════════════════════════════════════════════════════════════════════════════
# CONFIG LOADERS — the poisoned-cache class
# ══════════════════════════════════════════════════════════════════════════════

GOALS_KEY = "config/user_goals.json"


class TestGoalsLoader:
    def test_a_successful_load_is_returned_and_cached(self, monkeypatch):
        s3 = FakeS3({GOALS_KEY: {"mission": "recomp"}})
        monkeypatch.setattr(ic, "s3", s3)
        assert ic.load_goals_config()["mission"] == "recomp"
        assert ic.load_goals_config()["mission"] == "recomp"
        assert s3.gets == [GOALS_KEY]  # second call served from the warm cache

    def test_a_failed_load_is_never_cached(self, monkeypatch):
        """The tranche-2 poisoned-cache class: one transient throttle must not
        pin the defaults for the container's whole lifetime."""
        s3 = FakeS3(error=RuntimeError("throttled"))
        monkeypatch.setattr(ic, "s3", s3)
        assert ic.load_goals_config()["coach_briefing"] == "No goals configuration found."
        monkeypatch.setattr(ic, "s3", FakeS3({GOALS_KEY: {"mission": "recomp"}}))
        assert ic.load_goals_config()["mission"] == "recomp"

    def test_the_cache_expires_on_the_ttl(self, monkeypatch):
        import time as _time

        clock = {"t": 1_000_000.0}
        monkeypatch.setattr(_time, "time", lambda: clock["t"])
        s3 = FakeS3({GOALS_KEY: {"mission": "first"}})
        monkeypatch.setattr(ic, "s3", s3)
        ic.load_goals_config()
        clock["t"] += ic._GOALS_CACHE_TTL + 1
        s3.objects[GOALS_KEY] = {"mission": "second"}
        assert ic.load_goals_config()["mission"] == "second"
        assert len(s3.gets) == 2

    def test_the_fallback_config_carries_the_live_experiment_anchors(self, monkeypatch):
        """Derived from constants, never a literal date — a re-anchor must not
        leave a stale genesis in the coach's mission block."""
        from common.constants import EXPERIMENT_BASELINE_WEIGHT_LBS, EXPERIMENT_START_DATE

        monkeypatch.setattr(ic, "s3", FakeS3(error=RuntimeError("no such key")))
        config = ic.load_goals_config()
        assert config["start_date"] == EXPERIMENT_START_DATE
        assert config["start_weight_lbs"] == EXPERIMENT_BASELINE_WEIGHT_LBS


class TestDetectionRulesLoader:
    def test_a_successful_load_is_cached(self, monkeypatch):
        s3 = FakeS3({"config/action_detection_rules.json": {"rules": [{"id": "r1"}], "version": "3"}})
        monkeypatch.setattr(ic, "s3", s3)
        assert ic._load_detection_rules()["version"] == "3"
        ic._load_detection_rules()
        assert len(s3.gets) == 1

    def test_a_failed_load_returns_an_empty_ruleset_and_is_not_cached(self, monkeypatch):
        monkeypatch.setattr(ic, "s3", FakeS3(error=RuntimeError("throttled")))
        assert ic._load_detection_rules() == {"rules": [], "expiry_days": 14, "version": "0"}
        monkeypatch.setattr(ic, "s3", FakeS3({"config/action_detection_rules.json": {"rules": [], "version": "9"}}))
        assert ic._load_detection_rules()["version"] == "9"

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (P3, VERIFIED) intelligence_common.py:798 _load_detection_rules has no "
            "caller in lambdas/ or mcp/ — the action-completion detection loop (Workstream 3) "
            "that consumed config/action_detection_rules.json was removed by #1239 and the "
            "loader plus its cache globals were left behind, shipping in every bundle (#781). "
            "It should be deleted or wired. Hurts Matthew indirectly: coach actions are never "
            "auto-detected as complete, so the accountability loop stays manual."
        ),
    )
    def test_the_detection_rules_loader_has_a_live_caller(self):
        assert _live_references("_load_detection_rules")


# ══════════════════════════════════════════════════════════════════════════════
# PROFILE + THREAD EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════


class TestFetchProfile:
    def test_the_canonical_profile_key_is_the_only_one_used(self, wired):
        table, _s3 = wired
        table.store[("USER#matthew", "PROFILE#v1")] = {"height_in": Decimal("74")}
        assert ic.fetch_profile(table) == {"height_in": 74}
        assert table.gets[0] == {"pk": "USER#matthew", "sk": "PROFILE#v1"}

    def test_a_missing_profile_is_an_empty_dict_not_a_crash(self, wired):
        table, _s3 = wired
        assert ic.fetch_profile(table) == {}

    def test_a_ddb_outage_returns_an_empty_profile(self, wired):
        table, _s3 = wired
        table.get_error = RuntimeError("ddb down")
        assert ic.fetch_profile(table) == {}


class TestExtractThreadFromNarrative:
    """The parse path. `common.retry_utils.call_anthropic_raw` is stubbed, so no
    HTTP request is ever issued."""

    def _extract(self, monkeypatch, payload, error=None):
        def fake_call(req, timeout=30):
            if error is not None:
                raise error
            return {"content": [{"type": "text", "text": payload}]}

        monkeypatch.setattr("common.retry_utils.call_anthropic_raw", fake_call)
        monkeypatch.setattr(ic, "read_coach_thread", lambda coach_id, limit=10: [])
        return ic.extract_thread_from_narrative("sleep", "The full narrative text about sleep debt.", "fake-key")

    def test_a_clean_payload_is_parsed_and_its_predictions_are_code_stamped(self, monkeypatch):
        payload = json.dumps(
            {
                "position_summary": "I'm watching your sleep debt build.",
                "predictions": [{"prediction_id": "model_authored", "text": "HRV will rise", "confidence": "high"}],
                "surprises": [],
                "emotional_investment": "engaged",
                "open_questions": [],
            }
        )
        result = self._extract(monkeypatch, payload)
        assert result["position_summary"] == "I'm watching your sleep debt build."
        assert result["predictions"][0]["prediction_id"] != "model_authored"
        assert result["predictions"][0]["prediction_id"].startswith("pred_")

    def test_a_fenced_payload_is_unwrapped(self, monkeypatch):
        payload = '```json\n{"position_summary": "I see it.", "predictions": []}\n```'
        assert self._extract(monkeypatch, payload)["position_summary"] == "I see it."

    def test_unparseable_json_falls_back_to_a_word_boundary_truncation(self, monkeypatch):
        result = self._extract(monkeypatch, "not json at all")
        assert result["position_summary"] == "The full narrative text about sleep debt."
        assert result["predictions"] == []
        assert result["emotional_investment"] == "observing"

    def test_an_inference_failure_never_loses_the_coach_run(self, monkeypatch):
        result = self._extract(monkeypatch, "", error=RuntimeError("bedrock down"))
        assert result["predictions"] == [] and result["surprises"] == []

    def test_a_third_person_summary_is_rejected_by_the_voice_register_guard(self, monkeypatch):
        payload = json.dumps({"position_summary": "The sleep coach believes debt is building.", "predictions": []})
        result = self._extract(monkeypatch, payload)
        assert "sleep coach" not in result["position_summary"].lower()

    def test_the_request_bypasses_the_bedrock_chokepoint(self, monkeypatch):
        """PIN (P2): ADR-062 routes ALL Claude inference through
        `bedrock_client.invoke()` so the ADR-063 budget guard can gate it. This
        function still builds a raw api.anthropic.com request with an x-api-key
        header, so it is neither budget-tiered nor IAM-authed. Pinned rather
        than fixed — a migration is its own change."""
        captured = {}

        def fake_call(req, timeout=30):
            captured["url"] = req.full_url
            captured["headers"] = {k.lower(): v for k, v in req.headers.items()}
            return {"content": [{"type": "text", "text": "{}"}]}

        monkeypatch.setattr("common.retry_utils.call_anthropic_raw", fake_call)
        monkeypatch.setattr(ic, "read_coach_thread", lambda coach_id, limit=10: [])
        ic.extract_thread_from_narrative("sleep", "narrative", "fake-key")
        assert captured["url"] == "https://api.anthropic.com/v1/messages"
        assert captured["headers"]["x-api-key"] == "fake-key"

    def test_the_narrative_sent_for_extraction_is_bounded(self, monkeypatch):
        """A 2,000-character cap keeps the parse call cheap and predictable."""
        captured = {}

        def fake_call(req, timeout=30):
            captured["body"] = req.data.decode()
            return {"content": [{"type": "text", "text": "{}"}]}

        monkeypatch.setattr("common.retry_utils.call_anthropic_raw", fake_call)
        monkeypatch.setattr(ic, "read_coach_thread", lambda coach_id, limit=10: [])
        ic.extract_thread_from_narrative("sleep", "x" * 5000, "fake-key")
        assert "x" * 2000 in captured["body"]
        assert "x" * 2001 not in captured["body"]
