"""tests/test_platform_memory_block.py — #1482: the platform_memory category
taxonomy (code registry, not prose) + conversation-derived memory injection
into coach prompt assembly.

Hermetic (FakeDdbTable, no AWS). Pins:
  - registry invariants (channels/tiers/retention/domains all valid);
  - cross-registry drift gates: the registry's `durable` flag agrees with
    phase_taxonomy's MEMORY_DURABLE/SCOPED split, and the local COACH_DOMAINS
    literal equals persona_registry.OPERATIONAL_SHORT_IDS;
  - selection semantics: only channel=="conversation" records (honest
    provenance), private tier never injected, per-record tier may only
    tighten, per-category retention windows, coach-domain narrowing, caps;
  - rendering: provenance line format, "(shared in confidence)" marking, the
    ADR-104 usage rules, hard char budget;
  - ADR-104: the block's numbers land in grounded_generation's allow-list;
  - ai_calls wiring: _run_coach_v2_pipeline injects {_memory_block} ABOVE the
    few-shot block (so _allowlist_prompt keeps its numbers allowed);
  - MCP write path: unknown categories rejected with the sanctioned list,
    aliases normalized, channel/provenance stamped by the platform (never
    writer-supplied), privacy_tier/domains validated.

Run with:   python3 -m pytest tests/test_platform_memory_block.py -v
"""

import os
import sys
from datetime import date

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "tests"))

import persona_registry  # noqa: E402
import phase_taxonomy  # noqa: E402
import platform_memory as pm  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402
from grounded_generation import allowed_numbers  # noqa: E402

import mcp.tools_memory as tm  # noqa: E402

TODAY = date(2026, 7, 19)


def _mem(category="life_context", d="2026-07-14", channel="conversation", **over):
    item = {
        "pk": "USER#matthew#SOURCE#platform_memory",
        "sk": f"MEMORY#{category}#{d}",
        "category": category,
        "date": d,
        "channel": channel,
        "provenance": "mcp",
        "summary": f"a {category} memory from {d}",
    }
    item.update(over)
    return item


# ── registry invariants ──────────────────────────────────────────────────────


def test_every_category_has_valid_spec_fields():
    assert pm.MEMORY_CATEGORIES, "registry must not be empty"
    for cat, spec in pm.MEMORY_CATEGORIES.items():
        assert spec["description"].strip(), cat
        assert spec["channels"], cat
        assert all(ch in pm.CHANNELS for ch in spec["channels"]), cat
        assert spec["privacy_tier"] in pm.PRIVACY_TIERS, cat
        assert isinstance(spec["retention_days"], int) and spec["retention_days"] > 0, cat
        domains = spec["coach_domains"]
        assert domains == pm.ALL_DOMAINS or (domains and domains <= pm.COACH_DOMAINS), cat
        assert isinstance(spec["durable"], bool), cat


def test_aliases_resolve_to_canonical_categories_only():
    for alias, target in pm.CATEGORY_ALIASES.items():
        assert alias not in pm.MEMORY_CATEGORIES, f"alias {alias} shadows a canonical category"
        assert target in pm.MEMORY_CATEGORIES, f"alias {alias} points at unknown {target}"
    assert pm.canonical_category("episodic_wins") == "what_worked"
    assert pm.canonical_category("failure_pattern") == "failure_patterns"
    assert pm.canonical_category("life_context") == "life_context"
    assert pm.canonical_category("made_up_category") is None
    assert pm.canonical_category(None) is None


def test_issue_1482_conversation_categories_are_sanctioned():
    convo = set(pm.conversation_categories())
    assert {"life_context", "constraints_preferences", "coaching_calibration", "failure_patterns", "what_worked"} <= convo
    # computed-only categories must NOT be conversation-writable
    assert "weekly_plate" not in convo
    assert "hypothesis_monitoring" not in convo


def test_taxonomy_summary_covers_every_category():
    summary = pm.taxonomy_summary()
    assert {e["category"] for e in summary} == set(pm.MEMORY_CATEGORIES)
    for e in summary:
        assert set(e) == {"category", "description", "channels", "privacy_tier", "retention_days", "conversation_writable"}


# ── cross-registry drift gates ───────────────────────────────────────────────


def test_durable_flag_agrees_with_phase_taxonomy_split():
    for cat, spec in pm.MEMORY_CATEGORIES.items():
        if spec["durable"]:
            assert cat in phase_taxonomy.MEMORY_DURABLE_CATEGORIES, f"{cat} durable here but not cross_phase in phase_taxonomy"
        else:
            assert cat in phase_taxonomy.MEMORY_SCOPED_CATEGORIES, f"{cat} scoped here but not scoped in phase_taxonomy"


def test_phase_taxonomy_classifies_new_conversation_categories_cross_phase():
    pk = "USER#matthew#SOURCE#platform_memory"
    for cat in ("life_context", "constraints_preferences"):
        assert phase_taxonomy.classify(pk, f"MEMORY#{cat}#2026-07-14", category=cat) == phase_taxonomy.CROSS_PHASE


def test_coach_domains_literal_matches_persona_registry():
    assert pm.COACH_DOMAINS == set(persona_registry.OPERATIONAL_SHORT_IDS)


# ── selection semantics ──────────────────────────────────────────────────────


def test_only_conversation_channel_records_are_selected():
    records = [
        _mem("life_context", "2026-07-14"),
        _mem("coaching_calibration", "2026-07-13", channel="computed"),  # computed twin — excluded
        {**_mem("what_worked", "2026-07-12"), "channel": None},  # unstamped — excluded
    ]
    sel = pm.select_conversation_memories(records, coach_id="sleep_coach", today=TODAY)
    assert [e["category"] for e in sel] == ["life_context"]


def test_private_tier_is_never_injected_and_override_only_tightens():
    records = [
        _mem("life_context", "2026-07-14", privacy_tier="private"),  # tightened to private — excluded
        _mem("life_context", "2026-07-13", privacy_tier="public_ok"),  # attempt to LOOSEN — stays coach_context
    ]
    sel = pm.select_conversation_memories(records, coach_id="mind", today=TODAY)
    assert [e["date"] for e in sel] == ["2026-07-13"]
    block = pm.format_platform_memory_block(sel)
    assert "(shared in confidence)" in block, "loosening override must not strip the confidence marker"


def test_retention_window_is_per_category():
    old = "2026-01-01"  # 199 days before TODAY
    records = [
        _mem("failure_patterns", old),  # 180d window — expired
        _mem("life_context", old),  # 365d window — still relevant
        _mem("life_context", "2027-01-01"),  # future-dated — excluded
    ]
    sel = pm.select_conversation_memories(records, coach_id="mind", today=TODAY)
    assert [(e["category"], e["date"]) for e in sel] == [("life_context", old)]


def test_domain_narrowing_and_alias_category_records():
    records = [
        _mem("constraints_preferences", "2026-07-15", domains=["nutrition", "training"]),
        _mem("failure_pattern", "2026-07-14"),  # legacy singular alias in the stored record
    ]
    for_nutrition = pm.select_conversation_memories(records, coach_id="nutrition_coach", today=TODAY)
    assert [e["category"] for e in for_nutrition] == ["constraints_preferences", "failure_patterns"]
    for_sleep = pm.select_conversation_memories(records, coach_id="sleep", today=TODAY)
    assert [e["category"] for e in for_sleep] == ["failure_patterns"], "domain-narrowed record must not reach other coaches"


def test_newest_first_and_max_items_cap():
    records = [_mem("life_context", f"2026-07-{d:02d}") for d in range(1, 12)]
    sel = pm.select_conversation_memories(records, coach_id="mind", max_items=3, today=TODAY)
    assert [e["date"] for e in sel] == ["2026-07-11", "2026-07-10", "2026-07-09"]


def test_unknown_category_records_are_skipped():
    sel = pm.select_conversation_memories([_mem("not_a_category", "2026-07-14")], coach_id="mind", today=TODAY)
    assert sel == []


# ── rendering ────────────────────────────────────────────────────────────────


def test_block_carries_provenance_header_line_format_and_rules():
    sel = pm.select_conversation_memories(
        [_mem("life_context", "2026-07-14", summary="work trip Tue-Fri, hotel gym only")], coach_id="training", today=TODAY
    )
    block = pm.format_platform_memory_block(sel)
    assert block.startswith("CONVERSATION-DERIVED CONTEXT")
    assert "NOT sensor data" in block
    assert "- [2026-07-14 · life_context] work trip Tue-Fri, hotel gym only (shared in confidence)" in block
    assert '"you mentioned"' in block  # the honest-citation rule
    assert "the data wins" in block  # data-over-memory rule


def test_block_respects_hard_char_budget():
    records = [_mem("life_context", f"2026-07-{d:02d}", summary="x" * 150) for d in range(1, 10)]
    sel = pm.select_conversation_memories(records, coach_id="mind", max_items=9, today=TODAY)
    block = pm.format_platform_memory_block(sel, max_chars=1000)
    assert 0 < len(block) <= 1000
    assert 1 <= block.count("- [") < 9, "char budget must drop trailing lines"


def test_record_text_falls_back_to_compact_fields_and_collapses_newlines():
    rec = _mem("what_worked", "2026-07-14")
    del rec["summary"]
    rec.update({"what": "early protein\nbefore training", "outcome": "best week yet"})
    assert pm._record_text(rec) == "early protein before training"


def test_empty_selection_renders_empty_block():
    assert pm.format_platform_memory_block([]) == ""


# ── platform_memory_block end-to-end (fake table) ────────────────────────────


def _begins_with_prefix(kce):
    """Extract the begins_with prefix from a boto3 Key condition tree."""
    exp = kce.get_expression()
    for v in exp["values"]:
        if hasattr(v, "get_expression"):
            e = v.get_expression()
            if e["operator"] == "begins_with":
                return e["values"][1]
    return None


class DdbSemanticsFake:
    """DynamoDB-faithful query double for THIS partition's trap (PR #1581 review):
    rows sorted by sk, begins_with honored, and Limit applied BEFORE any
    FilterExpression — the exact behaviors that made a partition-wide descending
    Limit-200 read category-alphabetical and starvation-prone."""

    def __init__(self, rows):
        self.rows = sorted(rows, key=lambda r: r["sk"])

    def query(self, KeyConditionExpression=None, ScanIndexForward=True, Limit=None, **_ignored_filter_kwargs):
        prefix = _begins_with_prefix(KeyConditionExpression) if KeyConditionExpression is not None else None
        items = [r for r in self.rows if prefix is None or r["sk"].startswith(prefix)]
        if not ScanIndexForward:
            items = items[::-1]
        if Limit:
            items = items[:Limit]
        return {"Items": items}


def _computed_flood(n=210):
    """>200 computed rows in a category that sorts AFTER the conversation ones
    ('intention_tracking' — written daily by daily_insight_compute in prod)."""
    from datetime import timedelta

    return [
        _mem("intention_tracking", (date(2026, 1, 1) + timedelta(days=i)).isoformat(), channel="computed", provenance="computed")
        for i in range(n)
    ]


def test_platform_memory_block_end_to_end():
    table = FakeDdbTable(rows=[_mem("life_context", "2026-07-14", summary="new puppy — sleep is fragmented on purpose")])
    block = pm.platform_memory_block(coach_id="sleep_coach", table=table, today=TODAY)
    assert "new puppy — sleep is fragmented on purpose" in block
    assert "life_context" in block
    # FakeDdbTable answers EVERY per-category query with all rows — the (pk, sk)
    # dedup must render the record exactly once.
    assert block.count("- [") == 1


def test_flood_fixture_reproduces_the_old_partition_scan_trap():
    """Sanity for the regression below: under the OLD partition-wide descending
    Limit-200 read, the computed flood fills the window (category-alphabetical
    order + Limit-before-Filter) and the conversation record never comes back."""
    from boto3.dynamodb.conditions import Key

    rows = _computed_flood() + [_mem("coaching_calibration", "2026-07-10", summary="quarterly review crunch — go easy on volume")]
    fake = DdbSemanticsFake(rows)
    old_window = fake.query(
        KeyConditionExpression=Key("pk").eq("USER#matthew#SOURCE#platform_memory") & Key("sk").begins_with("MEMORY#"),
        ScanIndexForward=False,
        Limit=200,
    )["Items"]
    assert len(old_window) == 200
    assert all(r["category"] != "coaching_calibration" for r in old_window), "fixture no longer reproduces the starvation trap"


def test_conversation_record_surfaces_past_200_plus_computed_rows():
    """PR #1581 review (MAJOR) regression: per-category begins_with queries mean
    a lone conversation memory still reaches the block past 200+ computed rows
    that fill a descending partition-wide window first."""
    rows = _computed_flood() + [_mem("coaching_calibration", "2026-07-10", summary="quarterly review crunch — go easy on volume")]
    block = pm.platform_memory_block(coach_id="training", table=DdbSemanticsFake(rows), today=TODAY)
    assert "quarterly review crunch — go easy on volume" in block
    assert "intention_tracking" not in block, "computed-channel rows must never render"


def test_legacy_alias_sk_record_surfaces_via_alias_prefix_query():
    """A conversation record stored under the legacy singular sk spelling
    (MEMORY#failure_pattern#…, pre-normalization) is still read and rendered
    under its canonical category."""
    rows = _computed_flood() + [_mem("failure_pattern", "2026-07-11", summary="late-night snacking after skipped lunches")]
    block = pm.platform_memory_block(coach_id="nutrition", table=DdbSemanticsFake(rows), today=TODAY)
    assert "late-night snacking after skipped lunches" in block
    assert "failure_patterns" in block


def test_platform_memory_block_is_fail_soft():
    class Boom:
        def query(self, **kwargs):
            raise RuntimeError("ddb down")

    assert pm.platform_memory_block(coach_id="mind", table=Boom(), today=TODAY) == ""
    assert pm.platform_memory_block(coach_id="mind", table=FakeDdbTable(), today=TODAY) == ""


# ── ADR-104: injected memories are valid grounding sources ───────────────────


def test_block_numbers_enter_the_fabrication_allow_list():
    sel = pm.select_conversation_memories(
        [_mem("constraints_preferences", "2026-07-15", summary="can only train 45 minutes on weekdays, 2 sessions max")],
        coach_id="training",
        today=TODAY,
    )
    block = pm.format_platform_memory_block(sel)
    allowed = allowed_numbers("You are a coach.\n" + block, "TRAINING DATA: {}")
    assert 45.0 in allowed and 2.0 in allowed


def test_ai_calls_injects_memory_block_above_few_shot_block():
    """Wiring gate: the coach v2 pipeline must build the block fail-soft and place
    {_memory_block} in the system prompt BEFORE {few_shot_block}, so
    _allowlist_prompt (which strips only the few-shot text) keeps its numbers in
    the ADR-104 allow-list."""
    import inspect

    import ai_calls

    src = inspect.getsource(ai_calls._run_coach_v2_pipeline)
    assert "platform_memory_block" in src, "coach prompt assembly no longer injects platform memory (#1482)"
    assert "{_memory_block}" in src
    assert src.index("{_memory_block}") < src.index("{few_shot_block}"), "memory block must sit above the few-shot block (ADR-104)"


# ── MCP write path: taxonomy enforcement + honest provenance ─────────────────


def test_mcp_write_rejects_unknown_category_with_sanctioned_list(monkeypatch):
    fake = FakeDdbTable()
    monkeypatch.setattr(tm, "_table_ref", fake)
    out = tm.tool_write_platform_memory({"category": "vibes", "content": {"summary": "nope"}})
    assert "error" in out
    assert out["sanctioned_categories"] == pm.sanctioned_categories()
    assert "life_context" in out["conversation_categories"]
    assert fake.puts == []


def test_mcp_write_normalizes_alias_and_stamps_provenance(monkeypatch):
    fake = FakeDdbTable()
    monkeypatch.setattr(tm, "_table_ref", fake)
    out = tm.tool_write_platform_memory({"category": "episodic_wins", "content": {"summary": "walked every day of the trip"}})
    assert out["status"] == "stored"
    assert out["category"] == "what_worked"
    assert out["channel"] == "conversation"
    item = fake.puts[0]
    assert item["sk"].startswith("MEMORY#what_worked#")
    assert item["channel"] == "conversation" and item["provenance"] == "mcp"


def test_mcp_write_meta_fields_beat_content_collisions(monkeypatch):
    fake = FakeDdbTable()
    monkeypatch.setattr(tm, "_table_ref", fake)
    tm.tool_write_platform_memory(
        {"category": "life_context", "content": {"summary": "s", "pk": "EVIL#", "channel": "computed", "provenance": "spoofed"}}
    )
    item = fake.puts[0]
    assert item["pk"] == "USER#matthew#SOURCE#platform_memory"
    assert item["channel"] == "conversation" and item["provenance"] == "mcp"


def test_mcp_write_computed_only_category_is_not_stamped_conversation(monkeypatch):
    fake = FakeDdbTable()
    monkeypatch.setattr(tm, "_table_ref", fake)
    out = tm.tool_write_platform_memory({"category": "journey_milestone", "content": {"summary": "sub-290"}})
    assert out["channel"] == "computed"


def test_mcp_write_validates_privacy_tier_and_domains(monkeypatch):
    fake = FakeDdbTable()
    monkeypatch.setattr(tm, "_table_ref", fake)
    assert "error" in tm.tool_write_platform_memory({"category": "life_context", "content": {"summary": "s"}, "privacy_tier": "secret"})
    assert "error" in tm.tool_write_platform_memory({"category": "life_context", "content": {"summary": "s"}, "domains": ["cardio"]})
    out = tm.tool_write_platform_memory(
        {"category": "life_context", "content": {"summary": "s"}, "privacy_tier": "private", "domains": ["nutrition_coach"]}
    )
    assert out["status"] == "stored"
    item = fake.puts[-1]
    assert item["privacy_tier"] == "private"
    assert item["domains"] == ["nutrition"], "suffixed coach ids must normalize to bare domains"


def test_mcp_write_content_smuggled_domains_and_tier_are_validated(monkeypatch):
    """PR #1581 review (minor): domains/privacy_tier inside `content` hit the same
    validation as the top-level args — no silent all-coach exclusion via a bad list."""
    fake = FakeDdbTable()
    monkeypatch.setattr(tm, "_table_ref", fake)
    assert "error" in tm.tool_write_platform_memory({"category": "life_context", "content": {"summary": "s", "domains": ["cardio"]}})
    assert fake.puts == []
    out = tm.tool_write_platform_memory(
        {"category": "life_context", "content": {"summary": "s", "domains": ["mind_coach"], "privacy_tier": "private"}}
    )
    assert out["status"] == "stored"
    item = fake.puts[-1]
    assert item["domains"] == ["mind"]
    assert item["privacy_tier"] == "private"


def test_mcp_read_accepts_alias(monkeypatch):
    fake = FakeDdbTable()
    monkeypatch.setattr(tm, "_table_ref", fake)
    tm.tool_read_platform_memory({"category": "failure_pattern"})
    call = fake.query_calls[0]
    assert call["ExpressionAttributeValues"][":s"].startswith("MEMORY#failure_patterns#")


def test_mcp_list_categories_returns_the_taxonomy(monkeypatch):
    fake = FakeDdbTable(rows=[_mem("life_context", "2026-07-14")])
    monkeypatch.setattr(tm, "_table_ref", fake)
    out = tm.tool_list_memory_categories({})
    assert {e["category"] for e in out["taxonomy"]} == set(pm.MEMORY_CATEGORIES)


def test_mcp_valid_categories_derived_from_registry():
    assert tm.VALID_CATEGORIES == set(pm.MEMORY_CATEGORIES)
