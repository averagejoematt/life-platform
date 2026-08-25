"""tests/test_coach_brief_input_gate_3107.py — #3107: the coach-brief change-gate,
moved UPSTREAM of the narrative orchestrator.

WHAT THIS FILE HAS TO PROVE, AND WHY A UNIT TEST OF THE HASH IS NOT ENOUGH
-------------------------------------------------------------------------
#2889 shipped a fingerprint that was correct in isolation and could never hit in
production, because one of the six things it hashed was the orchestrator's Haiku
output at temperature 0.3. Every unit test of `brief_fingerprint` passed the whole
time. The defect only existed at the seam.

So the load-bearing tests here drive the REAL `ai_calls._run_coach_v2_pipeline`
through a stubbed transport and count MODEL CALLS:

  * run twice with byte-identical deterministic inputs -> the second run makes
    ZERO model calls (no orchestrator Haiku, no generation Sonnet) and returns the
    first run's text;
  * mutate ANY one deterministic input -> the second run misses and generates.

A stubbed `call_anthropic` that raises on entry is the instrument: a test that
asserted "the cache returned text" would pass even if the pipeline had quietly
regenerated identical text, which is exactly the ambiguity that let the old gate
look alive for two months.
"""

import copy
import json
import os
import sys
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from ai import ai_calls  # noqa: E402
from coach import coach_brief_input_gate as gate  # noqa: E402
from common import generation_cache as gc  # noqa: E402

VOICE_SPEC = {
    "display_name": "Dr. Sarah Chen",
    "domain": "sleep",
    "few_shot_examples": [],
    "structural_voice_rules": {},
    "decision_style": {},
    "anti_pattern_detection": {},
}

ORCH_DIGEST = "orchestrator-state-digest-aaaa"
GENERATED = "Sleep looked steady this week. Keep the wind-down where it is."


class FakeTable:
    """An in-memory DDB stand-in with the three calls generation_cache makes."""

    def __init__(self):
        self.store = {}
        self.puts = 0

    def get_item(self, Key):  # noqa: N803 — boto3's casing
        item = self.store.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item else {}

    def put_item(self, Item):  # noqa: N803
        self.puts += 1
        self.store[(Item["pk"], Item["sk"])] = dict(Item)

    def update_item(self, **kwargs):
        return {}

    def query(self, **kwargs):
        raise RuntimeError("no DDB queries in tests")


class Harness:
    """Drives the real pipeline with counted, stubbed AWS + transport."""

    def __init__(self, monkeypatch, table=None):
        self.monkeypatch = monkeypatch
        self.table = table if table is not None else FakeTable()
        self.model_calls = 0
        self.invokes = []
        self.orch_digest = ORCH_DIGEST
        self.voice_spec = copy.deepcopy(VOICE_SPEC)
        self.comp_results = {"trends": {"sleep_efficiency": "flat"}}
        self.data = {"whoop": {"recovery": 61}}
        self.domain_data = {"whoop": {"recovery": 61}}
        self.generation_text = GENERATED
        self.allow_generation = True
        self.allow_orchestrator = True
        self.orch_calls = 0

        self.fake_lambda = MagicMock()
        self.fake_lambda.invoke.side_effect = self._invoke

        self.fake_s3 = MagicMock()
        self.fake_s3.get_object.side_effect = self._get_object

        resource = MagicMock()
        resource.Table.return_value = self.table
        fake_boto3 = MagicMock()
        fake_boto3.client.side_effect = lambda service, **kw: self.fake_lambda if service == "lambda" else self.fake_s3
        fake_boto3.resource.return_value = resource

        monkeypatch.setattr(ai_calls, "boto3", fake_boto3)
        monkeypatch.setattr(ai_calls, "call_anthropic", self._call_anthropic)
        monkeypatch.setattr(ai_calls, "_cw", MagicMock())
        # The corrections + canonical-facts reads are separate fail-soft paths; keep
        # them out of the way so the only variable under test is the gate.
        monkeypatch.setattr(ai_calls, "_coach_corrections_block", lambda *a, **kw: "")

    def _get_object(self, **kwargs):
        body = MagicMock()
        body.read.return_value = json.dumps(self.voice_spec).encode()
        return {"Body": body}

    def _call_anthropic(self, *a, **kw):
        if not self.allow_generation:
            raise AssertionError("a cache HIT must make zero model calls — the generation path was entered")
        self.model_calls += 1
        return self.generation_text

    def _invoke(self, **kwargs):
        fn = kwargs["FunctionName"]
        payload = json.loads(kwargs["Payload"]) if kwargs.get("Payload") else {}
        self.invokes.append((fn, payload))
        mock = MagicMock()
        if fn == "coach-narrative-orchestrator" and payload.get("mode") == gate.FINGERPRINT_MODE:
            body = {"coach_id": payload.get("coach_id"), gate.FINGERPRINT_MODE: self.orch_digest}
            mock.read.return_value = json.dumps({"body": json.dumps(body)}).encode()
        elif fn == "coach-narrative-orchestrator":
            if not self.allow_orchestrator:
                raise AssertionError("a cache HIT must skip the orchestrator leg entirely — its Haiku call was reached")
            self.model_calls += 1
            self.orch_calls += 1
            # THE FIXTURE MUST BE THE WIRE. The real orchestrator samples Haiku at
            # temperature 0.3, and #2889 measured 0 identical briefs in 56 consecutive
            # days. A fake that returned a constant brief would let the DOWNSTREAM cache
            # hit and would silently make every upstream assertion below vacuous, so this
            # brief varies per call exactly as the live one does.
            brief = {
                "generation_brief": {
                    "voice_guidance": {},
                    "decision_class_ceiling": "observational",
                    "narrative_beat": f"sampled-beat-{self.orch_calls}",
                }
            }
            mock.read.return_value = json.dumps({"body": json.dumps(brief)}).encode()
        elif fn == "coach-quality-gate":
            mock.read.return_value = json.dumps({"statusCode": 200, "passed": True, "score": 90}).encode()
        else:
            mock.read.return_value = b"{}"
        return {"Payload": mock}

    def forbid_model_calls(self):
        self.allow_generation = False
        self.allow_orchestrator = False

    def run(self):
        self.model_calls = 0
        self.invokes = []
        ai_calls._comp_results_cache = self.comp_results
        return ai_calls._run_coach_v2_pipeline("sleep_coach", self.domain_data, "sleep", self.data, "")

    def fn_names(self):
        return [fn for fn, _ in self.invokes]


@pytest.fixture
def harness(monkeypatch):
    h = Harness(monkeypatch)
    yield h
    ai_calls._comp_results_cache = None


# ══════════════════════════════════════════════════════════════════════════════
# 1. The mutation proofs — the seam, not the hash
# ══════════════════════════════════════════════════════════════════════════════


def test_identical_deterministic_inputs_make_zero_model_calls_on_the_second_run(harness):
    """THE acceptance criterion. Run 1 generates; run 2, with byte-identical
    deterministic inputs, must not reach a single model call — not the orchestrator's
    Haiku, not the generation Sonnet."""
    first = harness.run()
    assert first == GENERATED
    assert harness.model_calls >= 2, "run 1 must actually pay for the orchestrator AND the generation"
    assert "coach-narrative-orchestrator" in harness.fn_names()

    harness.forbid_model_calls()  # any model call from here is a test failure
    second = harness.run()
    assert second == GENERATED, "the hit must serve the stored gate-passed text"
    assert harness.model_calls == 0
    assert [fn for fn, p in harness.invokes if fn == "coach-narrative-orchestrator" and p.get("mode") != gate.FINGERPRINT_MODE] == []


def test_the_hit_still_records_the_day_downstream(harness):
    """A reused day must be indistinguishable downstream from a generated one —
    coach-state-updater still gets today's section, at zero Bedrock cost."""
    harness.run()
    harness.forbid_model_calls()
    harness.run()
    updates = [p for fn, p in harness.invokes if fn == "coach-state-updater"]
    assert updates, "the reuse path still owes the OUTPUT# record"
    assert updates[-1]["output_text"] == GENERATED
    assert updates[-1]["output_type"] == "daily_brief_sleep", "the state updater is told the PUBLIC output type, never the _inputs row"


def test_the_skip_metric_names_the_upstream_surface(harness, monkeypatch):
    surfaces = []
    monkeypatch.setattr(gc, "emit_skip_metric", lambda cw, ns, coach_id, surface=None: surfaces.append(surface))
    harness.run()
    harness.forbid_model_calls()
    harness.run()
    assert (
        surfaces == [gate.UPSTREAM_SURFACE] == ["coach_brief_inputs"]
    ), "an upstream skip must be attributable to THIS gate, not collapsed into coach_brief"


@pytest.mark.parametrize(
    "label,mutate",
    [
        ("orchestrator_inputs", lambda h: setattr(h, "orch_digest", "orchestrator-state-digest-CHANGED")),
        ("comp_results", lambda h: h.comp_results.__setitem__("trends", {"sleep_efficiency": "rising"})),
        ("domain_data", lambda h: h.domain_data.__setitem__("whoop", {"recovery": 42})),
        ("data_inventory", lambda h: h.data.__setitem__("labs", [{"panel": "lipids"}])),
        ("voice_spec", lambda h: h.voice_spec.__setitem__("display_name", "Dr. Someone Else")),
    ],
)
def test_any_changed_deterministic_input_misses_and_regenerates(harness, label, mutate):
    """The other half of the proof. A gate that never misses is not a cache, it is a
    staleness bug — each named part must be able to bust it on its own."""
    harness.run()
    mutate(harness)
    harness.allow_generation = True
    second = harness.run()
    assert second == GENERATED
    assert harness.model_calls >= 2, f"changing {label} must force a full regeneration, orchestrator included"
    assert "coach-narrative-orchestrator" in harness.fn_names()


def test_a_changed_prompt_template_busts_the_gate(harness, monkeypatch):
    """The hit skips the orchestrator, so the orchestrator's CODE is inside what is
    being cached over. A prompt-template edit that the deployed bundle carries must
    bust the gate, or the platform serves pre-deploy text after a deploy."""
    harness.run()
    monkeypatch.setattr(gate, "prompt_template_hash", lambda root=None: "a-different-template-hash")
    harness.allow_generation = True
    harness.run()
    assert harness.model_calls >= 2


# ══════════════════════════════════════════════════════════════════════════════
# 2. Fail-closed — every uncertainty resolves to "regenerate"
# ══════════════════════════════════════════════════════════════════════════════


def test_an_unavailable_orchestrator_digest_disables_the_gate_rather_than_matching(harness):
    """Two consecutive failed digest fetches must NOT look like 'nothing changed'.
    Folding an absent digest in as None would be stable across failures — the exact
    shape that serves yesterday's text as today's."""
    harness.orch_digest = None
    harness.run()
    harness.allow_generation = True
    harness.run()
    assert harness.model_calls >= 2, "no upstream row may be written or matched from a run whose digest was unavailable"
    assert not any(
        sk.endswith(gate.UPSTREAM_SUFFIX) for _, sk in harness.table.store
    ), "a degraded run must not write an upstream cache row"


def test_upstream_parts_raises_rather_than_hashing_an_absent_digest():
    with pytest.raises(ValueError, match="orchestrator input digest"):
        gate.upstream_parts("sleep_coach", "sleep", {}, {}, "inv", "", {}, None, "tmpl")
    with pytest.raises(ValueError, match="prompt template hash"):
        gate.upstream_parts("sleep_coach", "sleep", {}, {}, "inv", "", {}, "digest", None)


def test_fetch_digest_returns_none_on_failure_and_on_a_missing_key():
    client = MagicMock()
    client.invoke.side_effect = RuntimeError("lambda unavailable")
    assert gate.fetch_orchestrator_input_digest(client, "sleep_coach") is None

    empty = MagicMock()
    payload = MagicMock()
    payload.read.return_value = json.dumps({"body": json.dumps({"coach_id": "sleep_coach"})}).encode()
    empty.invoke.return_value = {"Payload": payload}
    assert gate.fetch_orchestrator_input_digest(empty, "sleep_coach") is None


def test_fetch_digest_asks_for_fingerprint_mode_and_parses_a_string_body():
    client = MagicMock()
    payload = MagicMock()
    payload.read.return_value = json.dumps({"body": json.dumps({gate.FINGERPRINT_MODE: "abc123"})}).encode()
    client.invoke.return_value = {"Payload": payload}
    assert gate.fetch_orchestrator_input_digest(client, "sleep_coach") == "abc123"
    sent = json.loads(client.invoke.call_args.kwargs["Payload"])
    assert sent == {"coach_id": "sleep_coach", "mode": gate.FINGERPRINT_MODE}
    assert client.invoke.call_args.kwargs["InvocationType"] == "RequestResponse"


# ══════════════════════════════════════════════════════════════════════════════
# 3. The downstream ADR-126 gate still works (#3073 regression)
# ══════════════════════════════════════════════════════════════════════════════


def test_the_downstream_cache_still_serves_when_the_upstream_gate_is_unavailable(harness, monkeypatch):
    """#3073's surfaces share this machinery. The upstream gate is an ADDITION, not a
    replacement — with the digest gone, the old gate must still be able to hit."""
    harness.orch_digest = None
    harness.run()
    assert any(sk == gc.cache_sk("sleep_coach", "daily_brief_sleep") for _, sk in harness.table.store)

    # Force the downstream fingerprint to match by pinning the one non-deterministic
    # part (the orchestrator's brief) — which is precisely why it needed #3107.
    hits = []
    monkeypatch.setattr(gc, "check_reuse_or_explain", lambda t, c, o, p: hits.append(o) or ("fp", GENERATED, "2026-08-20"))
    harness.allow_generation = False  # the orchestrator still runs; only the Sonnet generation must not
    assert harness.run() == GENERATED
    assert hits[-1] == "daily_brief_sleep", "the downstream row is the one that served it"


def test_store_writes_both_rows_and_only_the_gates_that_ran():
    both = gate.BriefCacheGate(MagicMock(), FakeTable(), MagicMock(), "LifePlatform/AI", "sleep_coach", "daily_brief_sleep")
    both.up_fp, both.down_fp = "up", "down"
    both.store("text", "2026-08-24")
    assert sorted(sk for _, sk in both.table.store) == [
        gc.cache_sk("sleep_coach", "daily_brief_sleep"),
        gc.cache_sk("sleep_coach", "daily_brief_sleep_inputs"),
    ]

    one = gate.BriefCacheGate(MagicMock(), FakeTable(), MagicMock(), "LifePlatform/AI", "sleep_coach", "daily_brief_sleep")
    one.down_fp = "down"
    one.store("text", "2026-08-24")
    assert [sk for _, sk in one.table.store] == [gc.cache_sk("sleep_coach", "daily_brief_sleep")]


def test_no_table_means_no_cache_never_a_raised_pipeline():
    g = gate.BriefCacheGate(MagicMock(), None, MagicMock(), "LifePlatform/AI", "sleep_coach", "daily_brief_sleep")
    assert g.check_upstream("sleep", {}, {}, "inv", "", {}, "2026-08-24") is None
    assert g.check_downstream("sys", {}, {}, {}, "inv", "", "2026-08-24") is None
    g.store("text", "2026-08-24")  # must not raise


# ══════════════════════════════════════════════════════════════════════════════
# 4. The parts registry, the template hash, and the extracted inventory
# ══════════════════════════════════════════════════════════════════════════════


def test_the_part_names_live_here_not_at_the_call_site():
    """Same discipline as generation_cache.brief_parts (#2889): a caller cannot
    quietly drop a part, because dropping one NARROWS the fingerprint — the direction
    that serves stale output as fresh."""
    parts = gate.upstream_parts("sleep_coach", "sleep", {"t": 1}, {"d": 2}, "inv", "corr", {"v": 3}, "digest", "tmpl")
    assert set(parts) == {
        "coach_id",
        "domain_label",
        "comp_results",
        "domain_data",
        "data_inventory",
        "corrections",
        "voice_spec",
        "orchestrator_inputs",
        "prompt_template",
    }
    assert "brief" not in parts, "the orchestrator's temp-0.3 sample is exactly what must NOT be in an input fingerprint (#3107)"


def test_the_orchestrator_digest_ignores_bookkeeping_but_not_state():
    base = {"compressed": {"focus": "sleep debt"}, "_generated_at": "2026-08-24T10:00:00Z", "as_of": "2026-08-24"}
    later = {"compressed": {"focus": "sleep debt"}, "_generated_at": "2026-08-25T10:00:00Z", "as_of": "2026-08-25"}
    changed = {"compressed": {"focus": "recovery"}, "_generated_at": "2026-08-24T10:00:00Z", "as_of": "2026-08-24"}
    assert gate.orchestrator_input_digest(base) == gate.orchestrator_input_digest(later)
    assert gate.orchestrator_input_digest(base) != gate.orchestrator_input_digest(changed)


def test_prompt_template_hash_is_stable_changes_with_the_bytes_and_fails_to_none(tmp_path):
    real = gate.prompt_template_hash()
    assert real and real == gate.prompt_template_hash()

    for rel in gate.PROMPT_SOURCE_MODULES:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("# stand-in\n", encoding="utf-8")
    before = gate.prompt_template_hash(str(tmp_path))
    assert before and before != real
    (tmp_path / gate.PROMPT_SOURCE_MODULES[0]).write_text("# stand-in, edited\n", encoding="utf-8")
    assert gate.prompt_template_hash(str(tmp_path)) != before

    (tmp_path / gate.PROMPT_SOURCE_MODULES[0]).unlink()
    assert gate.prompt_template_hash(str(tmp_path)) is None, "an unreadable source must disable the gate, never fall back to a constant"


def test_the_prompt_sources_are_the_modules_the_hit_actually_skips():
    """A source list that drifts from the code the gate caches over is the whole bug
    class in miniature — it would look correct and cache over unhashed prompt bytes."""
    assert (
        "coach/coach_narrative_orchestrator.py" in gate.PROMPT_SOURCE_MODULES
    ), "a hit skips this module's Haiku call — its bytes must be hashed"
    assert "ai/ai_calls.py" in gate.PROMPT_SOURCE_MODULES, "this module builds the coach system prompt + user message"
    assert "coach/coach_brief_input_gate.py" in gate.PROMPT_SOURCE_MODULES, "the orchestrator SYSTEM_PROMPT literal lives here now"
    root = os.path.join(os.path.dirname(__file__), "..", "lambdas")
    for rel in gate.PROMPT_SOURCE_MODULES:
        assert os.path.exists(os.path.join(root, rel)), f"{rel} is listed but does not exist — the hash would silently be None"


def test_the_extracted_data_inventory_is_byte_identical_to_the_prompt_it_feeds():
    """Extracting this loop out of `ai_calls` must not have changed one byte: the
    string is BOTH a fingerprint part and a live prompt fragment, and a drift between
    them would bust the cache every day while looking fine."""
    out = gate.data_inventory({"whoop": {"recovery": 61}, "labs": [], "garmin": {"steps": 9000}})
    assert out.splitlines() == [
        "  - DEXA body composition: not available",
        "  - Lab bloodwork: not available",
        "  - Body measurements: not available",
        "  - MacroFactor nutrition: not available",
        "  - Whoop recovery/sleep: AVAILABLE",
        "  - Garmin steps: AVAILABLE",
        "  - Strava activities: not available",
        "  - Eight Sleep bed temp: not available",
        "  - CGM glucose: not available",
    ]
    assert gate.data_inventory(None) == gate.data_inventory({})


def test_upstream_output_type_is_a_distinct_row():
    assert gate.upstream_output_type("daily_brief_sleep") == "daily_brief_sleep_inputs"
    assert gate.upstream_output_type("daily_brief_sleep") != "daily_brief_sleep", "the two gates must not overwrite each other's row"


# ══════════════════════════════════════════════════════════════════════════════
# 5. The orchestrator's fingerprint-only mode
# ══════════════════════════════════════════════════════════════════════════════


def test_fingerprint_mode_returns_a_digest_without_a_single_model_call(monkeypatch):
    from coach import coach_narrative_orchestrator as orch

    state = {"compressed": {"focus": "sleep debt"}}
    monkeypatch.setattr(orch, "_gather_all_state", lambda coach_id: state)
    monkeypatch.setattr(
        orch, "_call_haiku", lambda **kw: (_ for _ in ()).throw(AssertionError("fingerprint mode must never reach the model"))
    )
    out = orch.lambda_handler({"coach_id": "sleep_coach", "mode": gate.FINGERPRINT_MODE}, None)
    assert out == {"coach_id": "sleep_coach", gate.FINGERPRINT_MODE: gate.orchestrator_input_digest(state)}


def test_the_orchestrator_still_re_exports_its_system_prompt():
    """The literal moved modules to pay for the dispatch; `orch.SYSTEM_PROMPT` is a
    public-enough name that moving it must be invisible."""
    from coach import coach_narrative_orchestrator as orch

    assert orch.SYSTEM_PROMPT is gate.ORCHESTRATOR_SYSTEM_PROMPT
    assert "Narrative Orchestrator" in orch.SYSTEM_PROMPT and "generation_brief schema" in orch.SYSTEM_PROMPT
