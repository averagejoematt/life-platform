"""tests/test_mcp_surface_index_3668.py — the derivation guards for #3668.

WHAT THIS FILE OWNS
-------------------
Two defect classes, guarded as SETS rather than instances (charter primitive 2):

1. **A served fact with no way to reach it.** The index must be DERIVED from the site
   API's own route tables, so a route shipped tomorrow appears tomorrow.
   ``test_a_planted_route_appears_in_the_index_without_an_edit`` plants a route into the
   source text and fails if the index does not carry it — the mutation that proves the
   guard bites is "replace the derivation with a hand-written list", which reds this test
   and nothing else.

2. **A reachable fact whose governing rule is invisible.** ``/api/source_freshness``
   reports *fresh through today* and the nutrition door reports *no data for three weeks*,
   and BOTH are correct: one reads the partition with ``include_pilot=True``, the other
   applies the ADR-058 filter. ``test_the_nutrition_specimen_is_reconcilable_not_a_contradiction``
   pins that live pair. The load-bearing NEGATIVE is in the same file: two surfaces under
   the SAME rule that disagree must NOT be handed a filter to blame it on.

Everything here is offline. The index derivation is pure source analysis — no AWS, no
network — which is also why it is safe to run inside the MCP Lambda on a warm container.
"""

from __future__ import annotations

import os
import re
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, _REPO)

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from deploy.endpoint_registry import discover_endpoint_paths  # noqa: E402
from mcp import (  # noqa: E402
    miss_log,
    surface_index,
    tools_surfaces as TS,  # noqa: E402
)

PLANTED = "/api/planted_route_3668"


@pytest.fixture(scope="module")
def live_index():
    return surface_index.build_index()


@pytest.fixture(scope="module")
def site_api_source():
    path = surface_index.site_api_path()
    assert path, "site_api_lambda.py must be resolvable from mcp/surface_index.py in both the repo and the bundle"
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# ── 1. The index is DERIVED, and a planted route proves it ───────────────────


def test_the_index_covers_exactly_the_router_s_own_endpoint_set(live_index):
    """One walk, two consumers (#1436). The index's key set is the endpoint set, renamed."""
    expected = {surface_index.surface_name(p) for p in discover_endpoint_paths()}
    assert set(live_index) == expected
    assert len(live_index) >= 100, f"only {len(live_index)} surfaces discovered — the walk broke, the router did not shrink"


def test_a_planted_route_appears_in_the_index_without_an_edit(site_api_source, live_index):
    """THE derivation guard. A route added to ROUTES must show up with no edit to
    mcp/surface_index.py — and the fallback question/`annotated: false` is what makes
    that structurally true rather than a promise nobody keeps.

    Mutation evidence: replacing `build_index`'s derived route set with a literal list of
    today's paths reds exactly this test.
    """
    assert PLANTED not in site_api_source, "the plant must not already exist in the real router"
    assert surface_index.surface_name(PLANTED) not in live_index

    planted_src = site_api_source.replace(
        'ROUTES = {\n    "/api/vitals": handle_vitals,',
        f'ROUTES = {{\n    "{PLANTED}": handle_vitals,\n    "/api/vitals": handle_vitals,',
        1,
    )
    assert planted_src != site_api_source, "the ROUTES anchor moved — update the plant"

    planted_index = surface_index.build_index(source=planted_src)
    name = surface_index.surface_name(PLANTED)
    assert name in planted_index, "a newly-registered route did NOT appear in the derived index"
    entry = planted_index[name]
    assert entry["owner_relevant"] is True
    assert entry["annotated"] is False, "an unannotated route must still be indexed, flagged as unannotated"
    assert entry["question"], "an unannotated route still needs a fallback question, never an empty string"
    assert "rule" in entry, "every reachable surface carries its governing rule, annotated or not"


def test_removing_a_route_removes_it_from_the_index(site_api_source):
    """The other direction: the index cannot outlive the route it describes."""
    trimmed = re.sub(r'^ +"/api/phenoage": .*\n', "", site_api_source, count=1, flags=re.MULTILINE)
    assert trimmed != site_api_source, "the /api/phenoage ROUTES line moved — update this removal"
    assert "phenoage" not in surface_index.build_index(source=trimmed)


# ── 2. Every reachable surface declares the rule it applied ──────────────────


def test_every_reachable_surface_declares_filter_date_basis_and_provenance(live_index):
    """#3668's second comment: data without its governing rule is what turned three
    correct payloads into three wrong conclusions in one night."""
    missing = []
    for name, entry in surface_index.reachable(live_index).items():
        rule = entry.get("rule") or {}
        for key in ("phase_filter", "phase_filter_meaning", "unfiltered_view", "date_basis", "row_provenance"):
            if not rule.get(key):
                missing.append(f"{name}.{key}")
    assert missing == [], f"surfaces returning data with no declared rule: {missing}"


def test_the_index_says_how_to_ask_for_the_unfiltered_view(live_index):
    """ "No data" must always be distinguishable from "data excluded by a rule you asked
    for" — which requires naming the escape hatch, not merely naming the filter."""
    for name, entry in surface_index.reachable(live_index).items():
        assert "include_pilot" in entry["rule"]["unfiltered_view"], name


def test_an_experiment_only_surface_says_empty_may_mean_excluded(live_index):
    experiment_only = [
        n for n, e in surface_index.reachable(live_index).items() if e["rule"]["phase_filter"] == surface_index.PHASE_EXPERIMENT_ONLY
    ]
    assert experiment_only, "no surface derived as experiment-only — the call analysis broke"
    meaning = live_index[experiment_only[0]]["rule"]["phase_filter_meaning"]
    assert "HIDDEN" in meaning and "never recorded" not in meaning.split("NOT")[0]


def test_undeclared_is_never_reported_as_unfiltered(live_index):
    """The fail-closed direction: a rule we could not derive reads UNKNOWN, never 'open'."""
    meaning = surface_index._PHASE_MEANING[surface_index.PHASE_UNDECLARED]
    assert "UNKNOWN" in meaning and "never as 'unfiltered'" in meaning


# ── 3. Two surfaces, two rules, one reconcilable difference ──────────────────


def test_the_nutrition_specimen_is_reconcilable_not_a_contradiction(live_index):
    """The live 2026-09-06 pair, pinned.

    `source_freshness` reads the partition with include_pilot=True and reported "fresh
    through 06 Sep". The nutrition door applies the ADR-058 filter and reported "no data
    16 Aug - 05 Sep". Six intervening days carry phase=pilot. Both right; nothing said so.
    """
    a, b = "source_freshness", "nutrition_overview"
    assert live_index[a]["rule"]["phase_filter"] == surface_index.PHASE_INCLUDES_PILOT
    assert live_index[b]["rule"]["phase_filter"] == surface_index.PHASE_EXPERIMENT_ONLY

    out = surface_index.explain_discrepancy(a, b, live_index)
    assert out["reconcilable"] is True
    assert "phase_filter" in out["differs_on"]
    # The explanation must NAME both rules, so a caller can say the sentence out loud.
    assert surface_index.PHASE_INCLUDES_PILOT in out["explanation"]
    assert surface_index.PHASE_EXPERIMENT_ONLY in out["explanation"]
    assert out["rules"][a]["phase_filter"] != out["rules"][b]["phase_filter"]


def test_same_rule_disagreement_is_reported_as_a_real_disagreement(live_index):
    """The load-bearing negative. Handing back "a filter explains it" when no filter
    differs would make this instrument a machine for excusing genuine contradictions."""
    out = surface_index.explain_discrepancy("habits", "habits", live_index)
    assert out["differs_on"] == []
    assert "REAL disagreement" in out["explanation"]
    assert "do not attribute it to a filter" in out["explanation"]


def test_explain_discrepancy_reports_an_unknown_surface_rather_than_guessing(live_index):
    out = surface_index.explain_discrepancy("habits", "no_such_surface_3668", live_index)
    assert out["reconcilable"] is False
    assert "no_such_surface_3668" in out["error"]


# ── 4. The exclusion registry: written reasons, no ghosts, no hand-listed writes ──


def test_every_reader_only_exclusion_names_a_live_route_and_carries_a_reason(live_index):
    live_paths = discover_endpoint_paths()
    for path, reason in surface_index.READER_ONLY_SURFACES.items():
        assert path in live_paths, f"stale exclusion: {path} is not a route any more"
        assert len(reason) >= 40, f"{path} needs a written reason, not a label: {reason!r}"


def test_write_endpoints_are_excluded_by_derivation_not_by_listing(live_index):
    """A POST-only route is excluded because it is POST-only. Listing them by hand is the
    enumeration the charter's standing rule 1 forbids — and would rot the day one moved."""
    write_only = [n for n, e in live_index.items() if not e["owner_relevant"] and e["excluded_reason"].startswith("Write endpoint")]
    assert len(write_only) >= 8, f"expected the POST-only family to be derived, got {write_only}"
    for name in write_only:
        assert live_index[name]["path"] not in surface_index.READER_ONLY_SURFACES, f"{name} is hand-listed AND derived"


def test_an_excluded_surface_is_reported_as_excluded_not_as_absent():
    """ "Exists and is deliberately not for you" and "no such surface" are different
    answers, and conflating them is how the platform made an honest assistant wrong."""
    out = TS.tool_get_platform_surface({"name": "broadcast"})
    assert "excluded_reason" in out
    assert "no such surface" in out["honest_framing"].lower()


# ── 5. The waiter: read-only, privacy-tiered by REUSE, rule always attached ──


def test_the_waiter_never_serves_a_write_route(live_index):
    for name, entry in live_index.items():
        if entry["owner_relevant"]:
            assert "GET" in entry["methods"] or "OPTIONS" in entry["methods"], name


def test_the_strip_set_is_the_privacy_declaration_not_a_second_copy():
    """#2803/#2809: one ruling, many readers. A literal here would be the third copy."""
    from privacy.field_tiers import TIER_OWNER_ONLY, fields_at_tier

    assert TS._OWNER_ONLY_FIELDS == frozenset(fields_at_tier(TIER_OWNER_ONLY))
    assert TS._OWNER_ONLY_FIELDS, "the owner-only declaration came back empty — the waiter would serve unstripped"


def test_owner_only_fields_are_stripped_from_a_generic_passthrough():
    """The waiter is a "dump the row" path by construction, which is exactly the shape
    that handed Tier-2 withings fields into conversation context in #2809."""
    removed: set = set()
    payload = {"weight_lbs": 327.3, "vascular_age": 61, "rows": [{"metabolic_age": 55, "hrv": 42}]}
    out = TS._strip_owner_only(payload, removed)
    assert out == {"weight_lbs": 327.3, "rows": [{"hrv": 42}]}
    assert removed == {"vascular_age", "metabolic_age"}


def test_a_served_surface_carries_its_rule_and_its_vintage():
    """/api/methods is pure and deterministic (an in-code registry, no DB read), so this
    exercises the real dispatch path without needing AWS."""
    out = TS.tool_get_platform_surface({"name": "methods"})
    assert out["status"] == 200
    assert "rule" in out and out["rule"]["date_basis"]
    assert out["vintage"]["declared"] is True
    assert out["privacy"]["declaration"] == "lambdas/privacy/field_tiers.py"
    assert "stats" in out["data"]


def test_a_path_form_name_resolves_to_the_same_surface():
    assert TS.tool_get_platform_surface({"name": "/api/methods"})["surface"] == "methods"


# ── 6. The miss log fires on a miss and stays silent on a hit ────────────────


class _Spy:
    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return miss_log.build_record(**kwargs)


def test_a_miss_is_recorded_and_a_hit_is_not(monkeypatch):
    """#3668's fourth acceptance box, both halves. Today a failed question leaves no
    trace at all — the cycle-number question vanished and the platform never learned it
    had been asked."""
    spy = _Spy()
    monkeypatch.setattr(TS.miss_log, "record_miss", spy)

    hit = TS.tool_get_platform_surface({"name": "methods"})
    assert hit["status"] == 200
    assert spy.calls == [], "an ANSWERED request must write nothing to the miss log"

    miss = TS.tool_get_platform_surface({"name": "acwr", "question": "what is my ACWR right now?"})
    assert "error" in miss
    assert len(spy.calls) == 1
    call = spy.calls[0]
    assert call["reason"] == miss_log.REASON_NO_SUCH_SURFACE
    assert call["asked_for"] == "acwr"
    assert call["question"] == "what is my ACWR right now?"


def test_an_excluded_surface_records_a_miss_with_its_reason(monkeypatch):
    spy = _Spy()
    monkeypatch.setattr(TS.miss_log, "record_miss", spy)
    TS.tool_get_platform_surface({"name": "broadcast"})
    assert len(spy.calls) == 1
    assert spy.calls[0]["reason"] == miss_log.REASON_READER_ONLY
    assert spy.calls[0]["detail"], "the exclusion reason must be carried into the log, not just into the response"


def test_the_miss_log_is_fail_open(monkeypatch):
    """A miss log that can break a tool call turns "I could not answer that" into "the
    platform is down"."""

    def _boom():
        raise RuntimeError("s3 wedged")

    monkeypatch.setattr(miss_log, "_client", _boom)
    rec = miss_log.record_miss(reason=miss_log.REASON_NO_SUCH_SURFACE, asked_for="acwr")
    assert rec is not None
    assert rec["_durable"] is False and rec["_key"] is None


def test_the_miss_record_keeps_an_unknown_reason_verbatim():
    """A log that silently reclassifies is the instrument this issue exists to fix."""
    rec = miss_log.build_record(reason="something_new", asked_for="x")
    assert rec["reason"] == "other"
    assert rec["reason_raw"] == "something_new"


def test_the_miss_log_writes_inside_the_already_granted_append_only_prefix():
    """mcp-audit/* already has PutObject-only on the MCP role and a DeleteObject Deny in
    deploy/bucket_policy.json. A new prefix would have needed both, and forgetting either
    is how an audit trail becomes deletable."""
    assert miss_log.MISS_PREFIX.startswith("mcp-audit/")
    policy = open(os.path.join(_REPO, "deploy", "bucket_policy.json"), encoding="utf-8").read()
    assert "matthew-life-platform/mcp-audit/*" in policy
    role_src = open(os.path.join(_REPO, "cdk", "stacks", "role_policies_serve.py"), encoding="utf-8").read()
    assert '"mcp-audit/*"' in role_src


# ── 7. The hot-path named tools ──────────────────────────────────────────────


def test_the_cycle_tool_returns_experiment_stamp_s_cycle_and_cannot_drift():
    """#3668's ground truth: the number is authoritative in three places that agree. A
    fourth derivation is how one journal entry ended up with four cycle numbers."""
    from experiment.phase_taxonomy import experiment_stamp
    from web.site_api_data import CYCLE_GENESES

    from mcp.tools_platform import tool_get_experiment_cycle

    out = tool_get_experiment_cycle({})
    stamp = experiment_stamp()
    assert out["cycle"] == stamp["cycle"], "the tool derived a cycle number of its own — that is the defect"
    assert out["phase"] == stamp["phase"]
    assert out["cycle_genesis"] == CYCLE_GENESES[out["cycle"]]
    assert out["authority"]["cycles_on_record"] == len(CYCLE_GENESES)


def test_the_cycle_tool_answers_for_a_past_date_from_the_registry():
    from web.site_api_data import CYCLE_GENESES

    from mcp.tools_platform import tool_get_experiment_cycle

    # The two the owner's journal got right and could not confirm.
    assert tool_get_experiment_cycle({"date": "2026-08-10"})["cycle"] == 13
    assert tool_get_experiment_cycle({"date": "2026-07-19"})["cycle"] == 8
    assert CYCLE_GENESES[13] == "2026-08-10" and CYCLE_GENESES[8] == "2026-07-19"


def test_the_cycle_tool_reports_an_ssm_disagreement_rather_than_resolving_it():
    """During a countdown the reset bumps SSM before genesis, so SSM legitimately names
    the NEXT cycle. That is disclosed, never reconciled away."""
    from mcp.tools_platform import tool_get_experiment_cycle

    cross = tool_get_experiment_cycle({})["authority"]["ssm_cross_check"]
    assert cross["param"] == "/life-platform/experiment-cycle"
    assert "status" in cross  # fail-soft: a cross-check must never be why an answer fails


def test_the_hot_path_tools_go_through_the_waiter_not_a_second_reader():
    """A named tool that re-implemented the fetch would carry a second copy of the rule
    declaration — the drift this whole issue is about."""
    import inspect

    from mcp import tools_platform

    src = inspect.getsource(tools_platform)
    assert "tool_get_platform_surface" in src
    assert "table.query" not in src and "boto3" not in src


def test_the_habit_tool_annotates_a_zero_instead_of_letting_it_speak():
    from mcp.tools_platform import tool_get_habit_completion

    out = tool_get_habit_completion({})
    assert "reading_this_honestly" in out
    assert "date basis" in out["reading_this_honestly"]
    assert "phase=pilot" in out["reading_this_honestly"]


# ── 8. Registry + audit wiring ───────────────────────────────────────────────


def test_the_five_new_tools_are_registered():
    from mcp.registry import TOOLS

    for name in ("describe_platform_surfaces", "get_platform_surface", "get_experiment_cycle", "get_habit_completion", "get_platform_cost"):
        assert name in TOOLS, f"{name} is not registered"
        assert callable(TOOLS[name]["fn"])
        assert TOOLS[name]["schema"]["name"] == name


def test_the_new_verbs_are_classified_as_reads():
    """mcp/audit.py classifies unknown verbs as WRITES (fail-safe). `describe` reads
    source text and touches no partition, so it belongs in READ_VERBS explicitly."""
    from mcp.audit import is_write_tool

    assert is_write_tool("describe_platform_surfaces") is False
    assert is_write_tool("get_platform_surface") is False


def test_the_index_tool_reports_its_own_derivation_and_its_own_known_gap():
    out = TS.tool_describe_platform_surfaces({})
    assert out["counts"]["routes_discovered"] == len(surface_index.cached_index())
    assert out["counts"]["reachable"] + out["counts"]["excluded"] == out["counts"]["routes_discovered"]
    assert "AST-derived" in out["index_is_derived"]
    # The provenance gap is MEASURED and stated, not quietly omitted (ADR-104).
    assert out["counts"]["provenance_undeclared"] > 0
    assert str(out["counts"]["provenance_undeclared"]) in out["known_gap"]


def test_the_endpoint_registry_is_staged_into_the_mcp_bundle():
    """mcp/surface_index.py runs the SAME walk at runtime, not a copy of it — which
    requires deploy/endpoint_registry.py to be in the bundle."""
    src = open(os.path.join(_REPO, "deploy", "build_bundle.py"), encoding="utf-8").read()
    stage_mcp = src.split("def stage_mcp(")[1].split("\ndef ")[0]
    assert "endpoint_registry.py" in stage_mcp
