"""#3509 — the four infrastructure facts nothing owned, and the proof each new rule can FAIL.

`grep -n -i 'canary|eventbridge|async lambda|dlq' scripts/check_doc_facts.py` returned nothing
before this lane: ARCHITECTURE.md could say the canary runs "every 30 min" (CDK: `rate(4 hours)`),
"~50 EventBridge rules" (88), "DLQ coverage: all async Lambdas" (five have none), and
source_registry.py could call `slo-source-freshness` "paging" (`to_digest=True`) — all under a
green gate.

Every test here plants the ACTUAL wrong literal from the issue and asserts the rule reds, then
asserts the corrected literal passes. A rule nobody has watched fail is not known to be able to
fail (#1189/#2578), and this repo keeps finding gates whose green came from being unable to go red.
"""

import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"_{name}_3509", ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


infra = _load("doc_facts_infra")
cdf = _load("check_doc_facts")
EXEMPT = cdf.line_is_exempt


def _scratch(tmp_path, text: str) -> Path:
    p = tmp_path / "planted.md"
    p.write_text(text, encoding="utf-8")
    return p


# ── fact 1: the EventBridge rule count ───────────────────────────────────────


def test_eventbridge_rule_count_is_derived_from_the_model():
    counts = json.loads((ROOT / "model" / "platform_model.json").read_text(encoding="utf-8"))["meta"]["counts"]
    assert infra.eventbridge_rule_count() == counts["schedules"]
    assert infra.eventbridge_rule_count() > 50, "a count at or under the old ~50 claim would make the fix untestable"


def test_eventbridge_rules_is_a_ground_truth_key_with_a_pattern():
    assert "eventbridge_rules" in cdf._ground_truth()
    patterns = next(pats for key, pats, _ in cdf.FACT_SPECS if key == "eventbridge_rules")
    truth = infra.eventbridge_rule_count()
    stale = "CDK owns all Lambda IAM roles + ~50 EventBridge rules."
    fixed = f"CDK owns all Lambda IAM roles + {truth} EventBridge schedule rules."
    matched = [int(mo.group(1)) for pat in patterns for mo in re.finditer(pat, stale)]
    assert matched == [50], "the doc's own stale phrasing must be matched by the pattern"
    assert [int(mo.group(1)) for pat in patterns for mo in re.finditer(pat, fixed)] == [truth]


# ── fact 2: the canary cadence — the `rate(...)` blind spot ──────────────────


def test_the_cron_map_really_is_blind_to_rate_and_the_new_map_is_not():
    """The founding instrument defect: `_cdk_cron_map()` filters to `cron(`, so no `rate(...)`
    schedule on the platform was ever diffed against a doc."""
    assert "life-platform-canary" not in cdf._cdk_cron_map()
    assert infra.cdk_schedule_map()["life-platform-canary"] == ["rate(4 hours)"]


def test_rate_rule_reds_on_the_original_every_30_min_claim(tmp_path):
    smap = infra.cdk_schedule_map()
    stale = _scratch(tmp_path, "- `life-platform-canary` — synthetic health check every 30 min\n")
    hits = infra.rate_schedule_hits([stale], smap, EXEMPT)
    assert len(hits) == 1 and "claims every 30 min" in hits[0]

    fixed = _scratch(tmp_path, "- `life-platform-canary` — synthetic round-trip on `rate(4 hours)`, i.e. every 4 hours\n")
    assert infra.rate_schedule_hits([fixed], smap, EXEMPT) == []


def test_rate_rule_reds_on_a_wrong_rate_literal(tmp_path):
    smap = infra.cdk_schedule_map()
    planted = _scratch(tmp_path, "- `life-platform-dlq-consumer` drains on `rate(30 minutes)`\n")
    hits = infra.rate_schedule_hits([planted], smap, EXEMPT)
    assert len(hits) == 1 and "claims rate(30 minutes)" in hits[0] and "rate(6 hours)" in hits[0]


def test_rate_rule_abstains_where_it_must(tmp_path):
    """Precision: a historical frame, an ambiguous multi-function line, and a cron-scheduled
    function (whose human interval this rule deliberately does not try to parse)."""
    smap = infra.cdk_schedule_map()
    for text in (
        "- `life-platform-canary` was every 30 min before the cadence was lowered\n",
        "- `life-platform-canary` and `life-platform-dlq-consumer` both run every 30 min\n",
        "- `daily-brief` goes out every 30 min\n",  # cron-scheduled: PROSE half abstains
    ):
        assert infra.rate_schedule_hits([_scratch(tmp_path, text)], smap, EXEMPT) == [], text


def test_the_live_corpus_is_clean_for_the_rate_rule():
    surface = infra.scan_infra_surface(cdf._scan_files())
    assert infra.rate_schedule_hits(surface, infra.cdk_schedule_map(), EXEMPT) == []


# ── fact 3: the DLQ exception set ────────────────────────────────────────────


def test_dlq_derivation_resolves_every_construct_and_every_spread():
    derived, records, unresolved = infra.dlq_exception_set()
    assert unresolved == [], "an unreadable **spread would silently invent or hide exceptions"
    assert len(records) > 100, "the create_platform_lambda walk went blind"
    # Verified against live AWS on 2026-09-04 (`aws lambda list-functions` -> 11 functions with a
    # null DeadLetterConfig, of which these five are async-invoked).
    assert derived == {
        "life-platform-delete-user-data",
        "life-platform-dlq-consumer",
        "life-platform-mcp-warmer",
        "life-platform-remediation-dispatcher",
        "telegram-coach-worker",
    }


def test_dlq_rule_reds_on_the_original_all_async_lambdas_claim(tmp_path):
    derived, records, _ = infra.dlq_exception_set()
    stale = _scratch(tmp_path, "DLQ coverage: all async Lambdas -> `life-platform-ingestion-dlq`.\n")
    hits = infra.dlq_exception_hits(stale, derived, records, [])
    assert len(hits) == 1 and "DLQ exception set is stale" in hits[0]


def test_dlq_rule_is_a_dead_man_when_the_sentence_disappears(tmp_path):
    derived, records, _ = infra.dlq_exception_set()
    gone = _scratch(tmp_path, "Failure handling is described elsewhere.\n")
    hits = infra.dlq_exception_hits(gone, derived, records, [])
    assert len(hits) == 1 and "has nothing to check" in hits[0]


def test_dlq_rule_passes_on_the_shipped_sentence():
    assert infra.dlq_exception_hits() == []


# ── fact 4: the route an alarm actually takes ────────────────────────────────


def test_freshness_alarm_routing_is_derived_from_to_digest():
    assert infra.alarm_routing()[infra.FRESHNESS_ALARM] == "digest"


def test_route_rule_reds_on_the_original_paging_prose(tmp_path):
    routing = infra.alarm_routing()
    stale = _scratch(tmp_path, "sources into StaleSourceCount and page the slo-source-freshness alarm on a rest state\n")
    hits = infra.alarm_route_hits([stale], routing, EXEMPT)
    assert len(hits) == 1 and "documented as paging" in hits[0]

    fixed = _scratch(tmp_path, "sources into StaleSourceCount and fire slo-source-freshness (`to_digest=True`)\n")
    assert infra.alarm_route_hits([fixed], routing, EXEMPT) == []


def test_route_rule_does_not_read_the_webpage_sense_of_page(tmp_path):
    """The three corpus lines that made a naive `\\bpage[sd]?\\b` unusable, plus the sentence that
    correctly NAMES the real pager — `\\b` matches inside `paging-pipeline-dead`, `(?<![\\w-])` does not."""
    routing = infra.alarm_routing()
    for text in (
        "check `slo-source-freshness` anyway: the /status/ page.\n",
        "held `qa-smoke-failures` in ALARM): the home page's protagonist\n",
        "`slo-source-freshness` digests; a dead pipeline is paging-pipeline-dead at >=8\n",
    ):
        assert infra.alarm_route_hits([_scratch(tmp_path, text)], routing, EXEMPT) == [], text


def test_route_rule_ignores_the_urgent_class(tmp_path):
    """`urgent` is a second immediate-notification class, so "urgent-topic-routed, which is what
    pages" (whoop_lambda.py) is TRUE — only the `digest` class is policed."""
    routing = infra.alarm_routing()
    urgent = [n for n, r in routing.items() if r == "urgent"]
    assert urgent, "no urgent-routed alarm found — the exclusion this test proves would be vacuous"
    text = f"0 -> `{urgent[0]}`, urgent-topic-routed, which is what pages\n"
    assert infra.alarm_route_hits([_scratch(tmp_path, text)], routing, EXEMPT) == []


def test_registry_must_cite_to_digest_not_restate_the_route(tmp_path):
    stale = tmp_path / "source_registry.py"
    stale.write_text(
        "  - freshness_checker_lambda.py  (StaleSourceCount -> the paging\n    slo-source-freshness alarm)\n", encoding="utf-8"
    )
    hits = infra.registry_route_citation_hits({infra.FRESHNESS_ALARM: "digest"}, stale)
    assert len(hits) == 1 and "without citing" in hits[0]

    fixed = tmp_path / "fixed_registry.py"
    fixed.write_text("    slo-source-freshness alarm — `to_digest=True` in monitoring_stack.py\n", encoding="utf-8")
    assert infra.registry_route_citation_hits({infra.FRESHNESS_ALARM: "digest"}, fixed) == []


def test_registry_citation_rule_reds_in_the_other_direction_too(tmp_path):
    """The dead-man half: if the alarm stops being digest-routed, the citation becomes the lie."""
    cites = tmp_path / "source_registry.py"
    cites.write_text("    slo-source-freshness alarm — `to_digest=True` in monitoring_stack.py\n", encoding="utf-8")
    hits = infra.registry_route_citation_hits({infra.FRESHNESS_ALARM: "paging"}, cites)
    assert len(hits) == 1 and "whose CDK routing is now `paging`" in hits[0]

    gone = infra.registry_route_citation_hits({}, cites)
    assert len(gone) == 1 and "is blind" in gone[0]


def test_the_live_tree_passes_both_route_rules():
    routing = infra.alarm_routing()
    assert infra.alarm_route_hits(infra.scan_infra_surface(cdf._scan_files()), routing, EXEMPT) == []
    assert infra.registry_route_citation_hits(routing) == []
