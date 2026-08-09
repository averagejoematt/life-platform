#!/usr/bin/env python3
"""tests/test_analyzer_gate_all_paths_2421.py — #2421: every reader-bound path of
`ai_expert_analyzer_lambda.py` passes the ADR-104 grounding chokepoint.

The #2390 invoke-site census measured 4 of the module's 6 model calls reaching readers
with NO chokepoint: the Mode-B correction (which rewrote the text AFTER the gate had
run, so even the gated path published a post-gate mutation), the weekly-priority
synthesis behind `/api/weekly_priority`, `EXPERT#experiment_arc`, and
`EXPERT#integrator_month`. All four now route through the module's single `_gate_prose`
helper and inherit #2391's regenerate-once-then-HOLD posture.

Pinned here:

  * a fabricated number in the weekly-priority synthesis HOLDS — `generate_synthesis`
    returns None and writes nothing, so the prior EXPERT#integrator record keeps serving;
  * the same for the month rollup (the second of the four paths asked for);
  * the Mode-B rewrite is RE-GATED — a rewrite that satisfies the Mode-B validator but
    fabricates a number is discarded, and the already-gated draft stays in the cache
    (the whole finding: no mutation after the last gate pass can persist);
  * a clean response on each path still publishes (the gate is not a blanket refusal);
  * `_gate_prose` is a registered SURFACES entry and the #2390 census counts the module
    covered with no exemption — and stripping the chokepoint call deregisters it, which
    is what the wiring guard and the census bucket red on (mutation proof).

Offline by construction: the model seam (`common.retry_utils.call_anthropic_raw`) is
monkeypatched and DynamoDB is a dict; no AWS, no Bedrock.
"""

import json
import os
import sys

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "lambdas", "intelligence"), os.path.join(_REPO, "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_import_err = None
try:
    import ai_expert_analyzer_lambda as az
    from common import retry_utils
except ImportError as _e:  # pragma: no cover — only when the bundle layout changes
    _import_err = _e
    az = None  # type: ignore

if _import_err is not None:  # pragma: no cover
    pytestmark = pytest.mark.skip(reason=f"ai_expert_analyzer_lambda unavailable: {_import_err}")  # type: ignore

MODULE = "lambdas/intelligence/ai_expert_analyzer_lambda.py"

# A number that appears in NO prompt these tests build — the #2290 fabrication class.
FABRICATED = "You averaged 8412 steps across the week."
CLEAN = "Hold the evening walk and let the pattern speak for itself."


class FakeTable:
    """Dict-backed DDB double: only the four calls these paths make."""

    def __init__(self):
        self.items: dict = {}
        self.writes: list = []

    def put_item(self, Item):
        self.writes.append(Item)
        self.items[(Item["pk"], Item["sk"])] = dict(Item)

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues):
        row = self.items.setdefault((Key["pk"], Key["sk"]), dict(Key))
        row["analysis"] = ExpressionAttributeValues[":a"]

    def get_item(self, Key):
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item else {}

    def query(self, **kwargs):
        return {"Items": []}


class FakeModel:
    """Queued replies in order (the last repeats); records every request body."""

    def __init__(self, *replies):
        self.replies = list(replies) or [""]
        self.requests: list = []

    def __call__(self, req, timeout=None):
        self.requests.append(json.loads(req.data.decode()))
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return {"content": [{"type": "text", "text": reply}]}

    @property
    def calls(self):
        return len(self.requests)


@pytest.fixture
def table(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(az, "table", t)
    return t


@pytest.fixture
def model(monkeypatch):
    def _install(*replies):
        m = FakeModel(*replies)
        monkeypatch.setattr(retry_utils, "call_anthropic_raw", m)
        monkeypatch.setattr(az, "_get_api_key", lambda: "sk-test")
        return m

    return _install


@pytest.fixture(autouse=True)
def hermetic(monkeypatch):
    """No canonical-facts read, no persona/intelligence side trips, no presence I/O."""
    az._CANON_FACTS_CACHE.clear()
    monkeypatch.setattr(az, "_load_canonical_facts", lambda: {})
    monkeypatch.setattr(az, "_load_engagement_signal", lambda: {})
    monkeypatch.setattr(az, "_presence_block", lambda: "")
    yield
    az._CANON_FACTS_CACHE.clear()


def _synth(priority):
    return json.dumps({"weekly_priority": priority, "cross_domain_notes": {}, "disagreements": []})


def _month(narrative):
    return json.dumps({"narrative": narrative, "headline": "A steady month"})


# ── the four paths ───────────────────────────────────────────────────────────
class TestWeeklyPriorityIsGated:
    def test_a_fabricated_number_holds_the_synthesis(self, table, model):
        """`/api/weekly_priority` is the cockpit's headline verdict. A fabricated
        figure that survives the one corrective rewrite must never be written — the
        prior EXPERT#integrator record keeps serving (#2391 posture, #2421 path)."""
        table.items[(az.CACHE_PK, "EXPERT#integrator")] = {"pk": az.CACHE_PK, "sk": "EXPERT#integrator", "analysis": "Yesterday's read."}
        m = model(_synth(FABRICATED), _synth("Recovery climbed 41 points this week."))
        assert az.generate_synthesis({"sleep": "s", "training": "t"}) is None
        assert m.calls >= 2, "the gate must attempt exactly one corrective rewrite before holding"
        assert table.writes == [], "a held synthesis writes nothing"
        assert table.items[(az.CACHE_PK, "EXPERT#integrator")]["analysis"] == "Yesterday's read."

    def test_a_clean_priority_still_publishes(self, table, model):
        model(_synth(CLEAN))
        out = az.generate_synthesis({"sleep": "s", "training": "t"})
        assert out is not None and out["weekly_priority"] == CLEAN
        assert table.items[(az.CACHE_PK, "EXPERT#integrator")]["analysis"] == CLEAN

    def test_a_corrected_rewrite_publishes_the_WHOLE_reparsed_record(self, table, model):
        """The rewrite comes back as raw JSON. Publishing the corrected priority beside
        the notes it was NOT generated with would be the post-gate-mutation bug again."""
        fixed = json.dumps({"weekly_priority": CLEAN, "cross_domain_notes": {"sleep": "steady"}, "disagreements": []})
        model(_synth(FABRICATED), fixed)
        out = az.generate_synthesis({"sleep": "s", "training": "t"})
        assert out["weekly_priority"] == CLEAN
        assert out["cross_domain_notes"] == {"sleep": "steady"}


class TestMonthRollupIsGated:
    @pytest.fixture(autouse=True)
    def _week_notes(self, table):
        """The rollup needs >=2 trailing WEEK# field notes before it prompts at all."""
        pk = az.USER_PREFIX + "field_notes"
        for wk in ("2026-W31", "2026-W32"):
            table.items[(pk, f"WEEK#{wk}")] = {"pk": pk, "sk": f"WEEK#{wk}", "note": "A quiet week.", "iso_week": wk}
        table.query = lambda **kw: {"Items": [v for k, v in table.items.items() if k[0] == pk]}

    def test_a_fabricated_number_holds_the_rollup(self, table, model):
        m = model(_month(FABRICATED), _month("Deep sleep averaged 3.7 hours."))
        assert az.generate_month_rollup() is None
        assert m.calls >= 2
        assert table.writes == [], "a held month rollup writes nothing"

    def test_a_clean_rollup_still_publishes(self, table, model):
        model(_month(CLEAN))
        out = az.generate_month_rollup()
        assert out is not None and out["narrative"] == CLEAN
        assert table.items[(az.CACHE_PK, "EXPERT#integrator_month")]["narrative"] == CLEAN


class TestModeBRewriteIsReGated:
    """The whole #2421 finding: the Mode-B correction runs AFTER the grounding gate,
    so before this change the one path that WAS gated still published a post-gate
    mutation. The rewrite is now re-gated and a failing rewrite is discarded."""

    @pytest.fixture(autouse=True)
    def _mode_b(self, monkeypatch):
        monkeypatch.setattr(az, "_HAS_INTELLIGENCE_COMMON", True)
        monkeypatch.setattr(az, "_persona_core", None)
        monkeypatch.setattr(az, "gather_data_for_expert", lambda key: {})
        monkeypatch.setattr(az, "build_prompt", lambda *a, **k: "PROMPT")
        monkeypatch.setattr(az, "build_data_inventory", lambda: {})
        monkeypatch.setattr(az, "build_data_maturity", lambda inv: {})
        monkeypatch.setattr(az, "_load_prior_analysis", lambda key: ("", ""))
        import intelligence.intelligence_common as ic

        # The Mode-B validator: the draft has one error, every rewrite has none. Mode B
        # would therefore ACCEPT any rewrite — only the grounding re-gate can refuse it.
        seen: list = []
        monkeypatch.setattr(
            ic,
            "validate_coach_output",
            lambda **kw: seen.append(kw["narrative"])
            or ([] if len(seen) > 1 else [{"severity": "error", "detail": "d", "source_text": "s"}]),
        )
        monkeypatch.setattr(ic, "write_quality_results", lambda *a, **k: None)

    def test_a_rewrite_that_fabricates_a_number_is_discarded(self, table, model):
        """Mode B is happy (0 errors < 1), the grounding gate is not — the cached,
        already-gated draft survives untouched."""
        model(CLEAN, FABRICATED, FABRICATED)
        assert az.generate_and_cache("sleep") == CLEAN
        assert table.items[(az.CACHE_PK, "EXPERT#sleep")]["analysis"] == CLEAN

    def test_a_grounded_rewrite_is_still_applied(self, table, model):
        better = "Protein held its floor without a single missed evening."
        model(CLEAN, better)
        assert az.generate_and_cache("sleep") == better
        assert table.items[(az.CACHE_PK, "EXPERT#sleep")]["analysis"] == better


# ── registration + census: the designed exit from UNGATED_READER_KNOWN ───────
class TestRegisteredSurfaceAndCensus:
    def test_the_single_chokepoint_is_registered_and_arms_four_classes(self):
        from grounding_wiring import SURFACES, scan_tree

        key = f"{MODULE}::_gate_prose"
        assert key in SURFACES, "the module's chokepoint must be a registered grounding surface"
        assert {"numbers", "freshness", "behavioral", "night"} <= scan_tree()[key]

    def test_census_counts_the_module_as_covered_with_no_exemption(self):
        import test_invoke_site_census_2390 as census

        assert MODULE not in census.UNGATED_READER_KNOWN, "the module must exit the tracked-defect table via SURFACES"
        assert MODULE not in census.DECLARED_OVERLAPS, "#2421 retired the PARTIAL_COVERAGE overlap"
        assert MODULE not in census.EXEMPTIONS, "acceptance: the module resolves WITHOUT an exemption"
        assert MODULE in census.SITES, "precondition: the module still references a model seam"
        assert census.classify(MODULE, census.SURFACE_MODULES) == ["surfaces"]

    def test_stripping_the_gate_deregisters_the_surface(self):
        """Mutation proof: remove the chokepoint call and the derivation loses the
        surface — what the wiring guard's stale-entry check and the census bucket red on."""
        from grounding_wiring import scan_source

        src = open(os.path.join(_REPO, MODULE), encoding="utf-8").read()
        assert f"{MODULE}::_gate_prose" in scan_source(MODULE, src), "precondition: the scan is not vacuous"
        assert f"{MODULE}::_gate_prose" not in scan_source(MODULE, src.replace("grounding_findings(", "disabled_findings("))
