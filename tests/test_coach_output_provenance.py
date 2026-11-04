"""tests/test_coach_output_provenance.py — a coach v2 read is stamped with the source families of the context it was
written from, and the public dashboard serves it only when they are all public (owner ruling 2026-11-03).

Synthetic fixtures only: every sentence below is written for the test ("the evening walks stayed flat"); no owner data.

THE CONTRACT IS DERIVED, NOT HAND-LISTED. The pipeline's prompt is parsed (AST) and every name its system prompt, user
message and corrections block interpolate must be classified in ``PROMPT_INPUTS``; the stamp reads those same variables
(``prompt_blocks(locals())``). The orchestrator's ``_gather_all_state`` return dict must equal ``STATE_PARTS``. The
domain-data families are the keys each builder actually reads (recorded at run time).
"""

from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT / "tests"))

from coach import coach_output_provenance as cop  # noqa: E402
from common import narrative_provenance as NP  # noqa: E402

PUBLIC_READ = "The evening walks stayed flat this week, per the watch."
# Families the registries name on purpose without a narrative_provenance classification (withheld until classified).
UNCLASSIFIED_ON_PURPOSE = {NP.UNRECORDED, "computed_insights", "social_posts", "chronicle", "coach_corrections"}


def _fn(path: str, name: str) -> ast.FunctionDef:
    tree = ast.parse((ROOT / path).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{path}::{name} not found")


def _public_record(*families: str) -> dict:
    return NP.stamp(families or ("whoop", "persona"), producer="test")


# ── the derived contract ───────────────────────────────────────────────────────────────────────────────────────────


def _interpolated_names() -> set:
    fn = _fn("lambdas/ai/ai_calls.py", "_run_coach_v2_pipeline")
    names: set = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in ("system_prompt", "user_message", "user_message_full") for t in node.targets
        ):
            names |= {n.id for n in ast.walk(node.value) if isinstance(n, ast.Name)}
    return names - {"user_message", "json", "int", "round", "chr", "str", "len"}


def test_every_name_the_prompt_interpolates_is_classified_and_nothing_else():
    names = _interpolated_names()
    assert {"_facts_block", "_journal_mood_block", "_data_inventory", "domain_data", "brief", "corrections_block"} <= names, names
    assert names == set(cop.PROMPT_INPUTS), (
        f"interpolated but unclassified: {sorted(names - set(cop.PROMPT_INPUTS))}; "
        f"classified but no longer interpolated: {sorted(set(cop.PROMPT_INPUTS) - names)}"
    )


def test_the_stamp_reads_the_same_variables_the_prompt_interpolates():
    fn = _fn("lambdas/ai/ai_calls.py", "_run_coach_v2_pipeline")
    calls = [
        n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "pipeline_provenance"
    ]
    assert len(calls) == 1, "one stamp per generation"
    (kw,) = calls[0].keywords
    assert kw.arg is None and ast.unparse(kw.value) == "_cop.prompt_blocks(locals())"
    assigned = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)} | {a.arg for a in fn.args.args}
    for name, spec in cop.PROMPT_INPUTS.items():
        if isinstance(spec, str):
            assert cop._VARIABLE_OF.get(spec, name) in assigned, f"{name}: the stamp would not find the variable"
    # and the record reaches BOTH writers: the reuse cache and the state updater
    src = ast.unparse(fn)
    assert "_gate.store(output, pacific_today(), provenance=_prov)" in src and "provenance=_prov)" in src.split("record_output(")[-1]


def test_the_builder_registry_is_the_pipelines():
    tree = ast.parse((ROOT / "lambdas/ai/ai_calls.py").read_text())
    seen = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("call_") and node.name.endswith("_coach_v2"):
            ret = next(n for n in ast.walk(node) if isinstance(n, ast.Return))
            seen[ret.value.args[0].value] = ret.value.args[1].func.id
    assert seen == cop.BUILDERS


def test_every_orchestrator_state_component_has_a_resolver():
    fn = _fn("lambdas/coach/coach_narrative_orchestrator.py", "_gather_all_state")
    ret = [n for n in ast.walk(fn) if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict)][-1]
    assert {k.value for k in ret.value.keys} == set(cop.STATE_PARTS)


def test_every_key_a_builder_reads_is_mapped():
    from ai import ai_context

    for coach_id, builder in cop.BUILDERS.items():
        rec = cop._KeyRecorder({})
        getattr(ai_context, builder)(rec)  # an empty day must not raise — else keys_read falls back to 'everything'
        unmapped = sorted(k for k in rec.read if k not in cop.DATA_KEY_FAMILIES)
        assert not unmapped, f"{coach_id} reads unmapped data keys {unmapped}"


def test_every_computation_engine_source_and_private_metric_is_mapped():
    from common.metric_truth import resolved_source_id

    tree = ast.parse((ROOT / "lambdas/coach/coach_computation_engine.py").read_text())
    node = next(n for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "SOURCE_METRICS")
    sources = {k.value if isinstance(k, ast.Constant) else resolved_source_id("steps") for k in node.value.keys}
    assert sources <= set(cop.COMPUTATION_SOURCE_FAMILIES), sources - set(cop.COMPUTATION_SOURCE_FAMILIES)
    metrics = {e.value for v in node.value.values for e in v.elts}
    assert {m for m in metrics if m.startswith("som_")} <= set(cop.COMPUTATION_METRIC_FAMILIES)


def test_every_named_family_is_classified_or_deliberately_not():
    named: set = set(cop.PRESENCE_FAMILIES.values()) | set(cop.RECALL_KIND_FAMILIES.values())
    for table in (cop.DATA_KEY_FAMILIES, cop.COACH_INPUT_FIELD_FAMILIES, cop.COMPUTATION_SOURCE_FAMILIES, cop.COMPUTATION_METRIC_FAMILIES):
        for fams in table.values():
            named |= set(fams)
    named |= {f for spec in cop.PROMPT_INPUTS.values() if isinstance(spec, tuple) for f in spec}
    for kw in ("journal_mood_block", "cycle_boundary_block", "memory_block", "corrections_block"):
        named |= set(cop.RUNTIME_RESOLVERS[kw]("a non-empty block"))
    named |= set(cop.RUNTIME_RESOLVERS["facts_block"]("FACTS\nMODEL EXPECTATIONS"))
    unclassified = {f for f in named if NP.classify(f) is None}
    assert (
        unclassified == UNCLASSIFIED_ON_PURPOSE
    ), f"newly unclassified {unclassified - UNCLASSIFIED_ON_PURPOSE}; now classified (revisit) {UNCLASSIFIED_ON_PURPOSE - unclassified}"


# ── the pipeline stamp ─────────────────────────────────────────────────────────────────────────────────────────────


def _blocks(**over):
    """A generation whose every input is public (the inventory left out — it states the journal's presence)."""
    base = dict(
        brief={"generation_brief": {}, "provenance": _public_record("whoop", "persona", "prediction_ledger")},
        facts_block="AUTHORITATIVE FACTS: resting HR 60",
        journal_mood_block="",
        cycle_boundary_block="",
        memory_block="",
        recall=("", []),
        data_inventory="",
        domain_data={"hrv": 50, "morning_note": None},
        comp_results={"trends": {"whoop": {"hrv": {"direction": "flat"}}}},
        corrections_block="",
    )
    base.update(over)
    return base


SLEEP_DATA = {"whoop": {"hrv": 50}, "sleep": {"sleep_score": 80}, "eightsleep": {}}


def test_a_public_only_context_is_publishable():
    rec = cop.pipeline_provenance("sleep_coach", SLEEP_DATA, **_blocks())
    assert NP.eligibility(rec) == (True, NP.ELIGIBLE), rec["families"]
    assert {"whoop", "eightsleep", "computed_metrics", "persona", "morning_note"} <= set(rec["families"])


def test_the_inventorys_journal_row_makes_every_read_private():
    from coach.coach_brief_input_gate import data_inventory

    fams = cop.pipeline_families("sleep_coach", SLEEP_DATA, **_blocks(data_inventory=data_inventory({})))
    assert fams["journal_presence"] == ["data_inventory"]
    assert NP.eligibility(NP.stamp(fams, producer="t")) == (False, NP.R_PRIVATE)


def test_the_mind_coachs_journal_inputs_are_private():
    data = {"journal_entries": [{"enriched_mood": 3}], "state_of_mind": {"som_avg_valence": 0.1}}
    fams = cop.pipeline_families("mind_coach", data, **_blocks())
    assert {"journal", "state_of_mind"} <= set(fams) and fams["journal"] == ["domain_data"]
    jm = cop.pipeline_families("sleep_coach", SLEEP_DATA, **_blocks(journal_mood_block="JOURNAL MOOD: steady"))
    assert jm["mood_read"] == ["journal_mood_block"]


@pytest.mark.parametrize(
    "over, carrier",
    [
        ({"memory_block": "MEMORY: shared in chat"}, "platform_memory"),
        ({"recall": ("PRECEDENTS", [{"kind": "journal"}])}, "journal"),
        ({"comp_results": {"trends": json.dumps({"apple_health": {"som_avg_valence": {}}})}}, "state_of_mind"),
    ],
)
def test_a_private_block_makes_the_read_private(over, carrier):
    rec = cop.pipeline_provenance("sleep_coach", SLEEP_DATA, **_blocks(**over))
    assert carrier in rec["families"] and NP.eligibility(rec) == (False, NP.R_PRIVATE)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b.pop("corrections_block"),  # an input not supplied
        lambda b: b.update(extra_block="x"),  # an input nobody classified
        lambda b: b.update(brief={"generation_brief": {}}),  # a brief with no record
        lambda b: b.update(recall=("PRECEDENTS", [{"kind": "coach_output"}])),  # a stored read's snippet
    ],
)
def test_an_unknown_input_fails_closed(mutate):
    b = _blocks()
    mutate(b)
    rec = cop.pipeline_provenance("sleep_coach", SLEEP_DATA, **b)
    assert NP.UNRECORDED in rec["families"] and NP.eligibility(rec)[0] is False


def test_an_unknown_data_key_is_withheld():
    rec = cop.pipeline_provenance("nonexistent_coach", SLEEP_DATA, **_blocks())
    assert NP.UNRECORDED in rec["families"], "no builder known -> its inputs are not known either"
    assert cop.data_key_families("a_new_partition") == ("data:a_new_partition",) and NP.classify("data:a_new_partition") is None


def test_prompt_blocks_reads_the_generation_variables():
    env = {
        "generation_brief": {"provenance": _public_record()},
        "brief": {"inner": "never read for provenance"},
        "_recall_block": "",
        "_recall_precedents": [],
        "_facts_block": "",
        "domain_data": {},
    }
    out = cop.prompt_blocks(env)
    assert out["brief"] is env["generation_brief"] and out["recall"] == ("", []) and "corrections_block" not in out


# ── the orchestrator's brief ───────────────────────────────────────────────────────────────────────────────────────


def _state(**over):
    stamped = {"pk": "COACH#sleep_coach", "sk": "X", "provenance": _public_record("whoop", "persona")}
    state = {k: None for k in cop.STATE_PARTS}
    state.update(
        graded_record={"block": "Nothing resolved yet", "cited": [], "notes": []},
        target_compressed=stamped,
        other_compressed={"mind_coach": stamped},
        ensemble_digest=stamped,
        open_threads=[stamped],
        active_predictions=[],
        evaluated_prediction_count=0,
        commitment_record={},
        computation_results={"trends": {"whoop": {}}},
        narrative_arc={"current_phase": "early_baseline"},  # the built-in default (no pk)
    )
    state.update(over)
    return state


def test_a_brief_built_from_stamped_public_rows_is_publishable():
    rec = cop.brief_provenance(_state())
    assert NP.eligibility(rec) == (True, NP.ELIGIBLE), rec["families"]


def test_a_brief_reading_a_row_with_no_record_is_unrecorded():
    rec = cop.brief_provenance(_state(other_compressed={"mind_coach": {"pk": "COACH#mind_coach", "summary": "x"}}))
    assert NP.UNRECORDED in rec["families"] and not NP.is_publishable(rec)


def test_a_private_upstream_row_makes_the_brief_private():
    private = {"pk": "COACH#mind_coach", "provenance": NP.stamp(["journal"], producer="t")}
    assert NP.eligibility(cop.brief_provenance(_state(other_compressed={"mind_coach": private}))) == (False, NP.R_PRIVATE)


def test_rendered_parts_decide_and_unknown_parts_fail_closed():
    state = _state(journal_mood={"mood_trend": "flat"})
    assert NP.is_publishable(cop.brief_provenance(state, rendered={"journal_mood": None})), "gathered but not rendered"
    assert "mood_read" in cop.brief_provenance(state, rendered={"journal_mood": {"mood_trend": "flat"}})["families"]
    assert NP.UNRECORDED in cop.brief_provenance({**_state(), "a_new_part": 1})["families"]
    assert NP.UNRECORDED in cop.brief_provenance(_state(), fallback={})["families"], "a fallback brief with no record"
    eng = cop.brief_provenance(_state(), rendered={"engagement_signal": {"presence_class": "quiet"}})
    assert "journal_presence" in eng["families"], "the presence signal is computed over the journal channel too"


def test_records_never_enter_the_orchestrator_prompt():
    from coach import coach_narrative_orchestrator as orch

    state = _state(voice_state={"pk": "p", "recent_openings": [], "provenance": NP.stamp(["journal"], producer="t")})
    state.update(influence_graph={}, narrative_arc={}, open_threads=[], current_stance=None, site_protocols={})
    blocks = orch._build_user_message(cop.without_records(state), "sleep_coach", "2026-11-05")
    text = "".join(b["text"] for b in blocks)
    assert '"provenance"' not in text and "families" not in text


# ── transport: the reuse cache and the state updater ───────────────────────────────────────────────────────────────


class _CacheTable:
    def __init__(self):
        self.items = {}

    def put_item(self, Item):  # noqa: N803
        self.items[(Item["pk"], Item["sk"])] = Item

    def get_item(self, Key):  # noqa: N803
        it = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": it} if it else {}

    def update_item(self, **kw):
        return {}


class _Lambda:
    def __init__(self):
        self.payloads = []

    def invoke(self, FunctionName, InvocationType, Payload):  # noqa: N803
        self.payloads.append(json.loads(Payload))


def test_a_reused_read_is_recorded_with_its_own_stored_record(monkeypatch):
    from decimal import Decimal

    from coach import coach_brief_input_gate as gate
    from common import generation_cache as gc

    t, lam = _CacheTable(), _Lambda()
    rec = _public_record()
    gc.store_entry(t, "sleep_coach", "daily_brief_sleep", "fp", "text", "2026-11-02", provenance={**rec, "v": Decimal(1)})
    monkeypatch.setattr(gc, "check_reuse_or_explain", lambda *a: ("fp", "text", "2026-11-02"))
    monkeypatch.setattr(gc, "emit_skip_metric", lambda *a, **k: None)
    g = gate.BriefCacheGate(lam, t, None, "ns", "sleep_coach", "daily_brief_sleep")
    g._hit("daily_brief_sleep", {}, "coach_brief", "2026-11-05")
    (payload,) = lam.payloads
    assert payload["provenance"]["families"] == rec["families"] and payload["provenance"]["v"] == 1
    # a cache row written before the stamp: no record travels, and the updater stamps it unrecorded
    t.items.clear()
    gc.store_entry(t, "sleep_coach", "daily_brief_sleep", "fp", "text", "2026-11-02")
    g._hit("daily_brief_sleep", {}, "coach_brief", "2026-11-05")
    assert lam.payloads[-1]["provenance"] is None
    assert not NP.is_publishable(cop.updater_record(lam.payloads[-1]["provenance"]))


@pytest.fixture
def updater(monkeypatch):
    import coach_state_updater as su
    from coach import coach_checkin
    from test_coach_state_updater import FakeCloudWatch, FakeS3, FakeTable, _extraction

    t = FakeTable()
    monkeypatch.setattr(su, "table", t)
    monkeypatch.setattr(su, "s3", FakeS3(body={}))
    monkeypatch.setattr(su, "_cw", FakeCloudWatch())
    monkeypatch.setattr(coach_checkin, "read_cycle", lambda ssm_client=None: 12)
    ext = _extraction(
        threads_opened=[{"thread_slug": "walks", "summary": "walks flat"}],
        commitments_made=[{"commitment_natural": "Walk after dinner", "timeframe_hint": "this week"}],
        public_summary=PUBLIC_READ,
    )
    monkeypatch.setattr(su, "_call_haiku", lambda **k: ext)
    return su, t


def _run(su, provenance):
    event = {"coach_id": "sleep_coach", "output_text": "The evening walks stayed flat.", "generation_date": "2026-11-05"}
    if provenance is not None:
        event["provenance"] = provenance
    su.lambda_handler(event, None)


def test_the_updater_stamps_every_row_it_derives_from_the_read(updater):
    su, t = updater
    _run(su, _public_record("whoop"))
    by_prefix = {p["sk"].split("#")[0]: p for p in t.puts}
    for prefix in ("OUTPUT", "THREAD", "COMMITMENT", "TRACE", "VOICE"):
        assert NP.is_publishable(by_prefix[prefix]), prefix
        assert {"whoop", "persona"} <= set(by_prefix[prefix]["provenance"]["families"])
    assert "provenance" not in by_prefix["RELATIONSHIP"], "rule-based over graded signals, not the read's text"


@pytest.mark.parametrize("provenance, reason", [(None, NP.R_UNKNOWN), (NP.stamp(["journal_presence"], producer="t"), NP.R_PRIVATE)])
def test_an_unrecorded_or_private_read_is_stamped_withheld(updater, provenance, reason):
    su, t = updater
    _run(su, provenance)
    (out,) = [p for p in t.puts if p["sk"].startswith("OUTPUT#")]
    assert NP.eligibility(out) == (False, reason)


# ── the public dashboard ───────────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def dashboard(monkeypatch):
    from coach import audience_guard, authoritative_grades as ag
    from web import narrative_publication as npub, site_api_lambda as L, trail_corrections

    monkeypatch.setattr(ag, "verdict_corrections", lambda table, coach_id: [])
    monkeypatch.setattr(trail_corrections, "ledger_withholds", lambda coach_id, row: False)

    def serve(provenance):
        row = {
            "pk": "COACH#sleep_coach",
            "sk": "OUTPUT#2026-11-05#daily_brief_sleep",
            "public_summary": PUBLIC_READ,
            "created_at": "2026-11-05T17:05:00+00:00",
            "derived_from": {"as_of": "2026-11-05T17:05:00+00:00", "predictions": []},
        }
        if provenance is not None:
            row["provenance"] = provenance
        t = _CacheTable()
        t.put_item(Item=row)
        gated = npub.wrap(t).get_item(Key={"pk": row["pk"], "sk": row["sk"]})["Item"]
        entry: dict = {}
        L._serve_position_summary(entry, npub.wrap(t), gated, audience_guard.public_blurb(gated))
        return entry

    return serve


def test_a_stamped_public_only_read_is_served_on_the_dashboard(dashboard):
    record = cop.updater_record(cop.pipeline_provenance("sleep_coach", SLEEP_DATA, **_blocks()))
    entry = dashboard(record)
    assert entry["position_summary"] == PUBLIC_READ and entry["summary_state"] == "current"
    assert "position_summary_withheld" not in entry


def test_a_read_whose_context_carried_a_private_family_is_withheld(dashboard):
    from coach.coach_brief_input_gate import data_inventory

    record = cop.updater_record(cop.pipeline_provenance("sleep_coach", SLEEP_DATA, **_blocks(data_inventory=data_inventory({}))))
    entry = dashboard(record)
    assert entry["position_summary"] == "" and entry["position_summary_withheld"] == NP.PUBLIC_WITHHELD_REASON


def test_negative_control_the_same_read_without_a_stamp_is_withheld(dashboard):
    entry = dashboard(None)
    assert entry["position_summary"] == "" and entry["position_summary_withheld"] == NP.PUBLIC_WITHHELD_REASON


def test_a_read_from_an_unknown_block_is_withheld(dashboard):
    record = cop.updater_record(cop.pipeline_provenance("sleep_coach", SLEEP_DATA, **_blocks(extra_block="x")))
    assert dashboard(record)["position_summary"] == ""
