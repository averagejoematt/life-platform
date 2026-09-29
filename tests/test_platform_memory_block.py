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

from ai import platform_memory as pm  # noqa: E402
from ai.grounded_generation import allowed_numbers  # noqa: E402
from coach import persona_registry  # noqa: E402
from experiment import phase_taxonomy  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402

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

    from ai import ai_calls

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


# ── #4077 — the `training` category: write + read-back through the MCP handler ──


def test_training_category_is_sanctioned_and_conversation_writable():
    assert pm.canonical_category("training") == "training"
    assert "training" in pm.conversation_categories()
    assert "training" in pm.sanctioned_categories()


def test_training_category_write_then_read_back_through_mcp_handler(monkeypatch):
    """The issue's own acceptance: a training constraint written and read back through
    the MCP handler — `write_platform_memory` used to reject 'training' outright."""
    fake = FakeDdbTable(filter_by_pk=True)
    monkeypatch.setattr(tm, "_table_ref", fake)

    written = tm.tool_write_platform_memory(
        {"category": "training", "content": {"summary": "RDL gate: hold to 40kg until the back flag clears"}}
    )
    assert written["status"] == "stored"
    assert written["category"] == "training"
    assert written["channel"] == "conversation"  # honest provenance — a chat write

    read_back = tm.tool_read_platform_memory({"category": "training", "days": 365})
    assert read_back["count"] == 1
    assert read_back["records"][0]["summary"] == "RDL gate: hold to 40kg until the back flag clears"
    assert read_back["records"][0]["category"] == "training"


def test_mcp_valid_categories_derived_from_registry():
    assert tm.VALID_CATEGORIES == set(pm.MEMORY_CATEGORIES)


# ── #4171 — writes are ADDITIVE: a same-day note never erases the earlier one ────────────
#
# Live, 2026-09-26 02:16:35Z: approving queued write 20260926T021548Z-6ef85360 (a training
# note) landed on MEMORY#training#2026-09-25 and silently replaced the injury note stored
# there at 02:15:00Z. The fixture below IS that wire — the two writes, 60 s apart — against a
# table that honours the calls the tool makes (conditional puts on sk, a BETWEEN /
# begins_with key condition, ScanIndexForward, Limit), so "both survive" is read back from
# the store, not inferred from a return value.

import ast  # noqa: E402
import inspect  # noqa: E402
from datetime import datetime, timezone  # noqa: E402


class _ConditionalCheckFailedException(Exception):
    pass


class _MemoryWireTable(FakeDdbTable):
    """FakeDdbTable that honours what tools_memory actually sends."""

    def __init__(self, rows=None):
        super().__init__(rows=rows, filter_by_pk=True)

    def put_item(self, Item=None, **kwargs):
        cond = kwargs.get("ConditionExpression")
        exists = self._key_of(Item) in self.store
        if cond == "attribute_not_exists(sk)" and exists:
            raise _ConditionalCheckFailedException("The conditional request failed: attribute_not_exists(sk)")
        if cond == "attribute_exists(sk)" and not exists:
            raise _ConditionalCheckFailedException("The conditional request failed: attribute_exists(sk)")
        if cond not in (None, "attribute_not_exists(sk)", "attribute_exists(sk)"):
            raise AssertionError(f"unexpected condition {cond!r}")
        return super().put_item(Item=Item, **kwargs)

    def update_item(self, Key=None, UpdateExpression=None, ConditionExpression=None, ExpressionAttributeValues=None, **kwargs):
        """#4355: the ONLY update this wire needs to honour is delete_platform_memory's
        tombstone — attribute_exists(sk) AND attribute_not_exists(deleted_at), a generic
        `SET a = :x, b = :y`. A different shape is a caller error, not a silent no-op."""
        self.updates.append(
            {
                "Key": Key,
                "UpdateExpression": UpdateExpression,
                "ConditionExpression": ConditionExpression,
                "ExpressionAttributeValues": ExpressionAttributeValues,
            }
        )
        item = self.store.get(self._key_of(Key))
        if ConditionExpression == "attribute_exists(sk) AND attribute_not_exists(deleted_at)":
            if item is None or item.get("deleted_at"):
                raise _ConditionalCheckFailedException(
                    "The conditional request failed: attribute_exists(sk) AND attribute_not_exists(deleted_at)"
                )
        elif ConditionExpression is not None:
            raise AssertionError(f"unexpected update condition {ConditionExpression!r}")
        assert UpdateExpression and UpdateExpression.startswith("SET "), f"unexpected UpdateExpression {UpdateExpression!r}"
        for assignment in UpdateExpression[len("SET ") :].split(","):
            field, _, value_ref = assignment.strip().partition("=")
            item[field.strip()] = ExpressionAttributeValues[value_ref.strip()]
        return {}

    def delete_item(self, **kwargs):  # pragma: no cover — proves the tool never reaches this
        raise AssertionError(
            "delete_platform_memory must never call dynamodb:DeleteItem (#4355) — the MCP "
            "role has no grant on the platform_memory partition; use update_item (a tombstone)"
        )

    def query(self, **kwargs):
        self.query_calls.append(kwargs)
        eav = kwargs["ExpressionAttributeValues"]
        kce = kwargs["KeyConditionExpression"]
        rows = [i for i in self.store.values() if i.get("pk") == eav[":pk"]]
        if "BETWEEN" in kce:
            rows = [r for r in rows if eav[":s"] <= r["sk"] <= eav[":e"]]
        elif "begins_with" in kce:
            rows = [r for r in rows if r["sk"].startswith(eav[":p"])]
        else:  # pragma: no cover — a new key-condition shape must be taught to the wire
            raise AssertionError(f"unexpected key condition {kce!r}")
        rows.sort(key=lambda r: r["sk"], reverse=not kwargs.get("ScanIndexForward", True))
        limit = kwargs.get("Limit")
        if limit:
            rows = rows[:limit]
        return {"Items": [dict(r) for r in rows]}


class _Clock:
    """Sequenced `datetime.now()` — each write stamps the next instant from the wire."""

    def __init__(self, *instants):
        self._instants = list(instants)

    def now(self, tz=None):
        cur = self._instants.pop(0) if len(self._instants) > 1 else self._instants[0]
        return cur if tz is None else cur.astimezone(tz)


_T_INJURY = datetime(2026, 9, 26, 2, 15, 0, tzinfo=timezone.utc)  # the injury note, stored_at
_T_MACHINES = datetime(2026, 9, 26, 2, 16, 35, tzinfo=timezone.utc)  # the approved queued note, 95 s later
_INJURY = "No current injuries or ailments (as of 2026-09-25)"
_MACHINES = "Seated leg curl and calf press are my machines, not lying curl / standing calf raise."


def _wire_0925(monkeypatch, *instants):
    """A wire table on the 2026-09-25 Pacific day with a sequenced clock (see `_Clock`)."""
    fake = _MemoryWireTable()
    monkeypatch.setattr(tm, "_table_ref", fake)
    # 02:15Z on 09-26 UTC is 19:15 PT on 09-25 — the date both notes keyed on.
    monkeypatch.setattr(tm, "pacific_now", lambda: datetime(2026, 9, 25, 19, 15, 0))
    monkeypatch.setattr(tm, "datetime", _Clock(*(instants or (_T_INJURY, _T_MACHINES))))
    return fake


def _training_rows(fake):
    return sorted((r for r in fake.store.values() if r["sk"].startswith("MEMORY#training#")), key=lambda r: r["stored_at"])


def test_issue_4171_the_second_same_day_note_never_erases_the_first(monkeypatch):
    """THE fixture: the two 09-25 writes, 60 s apart, on the same category-day."""
    fake = _wire_0925(monkeypatch)
    first = tm.tool_write_platform_memory({"category": "training", "content": {"summary": _INJURY}})
    second = tm.tool_write_platform_memory({"category": "training", "content": {"summary": _MACHINES}})
    assert first["status"] == "stored" and second["status"] == "stored"
    assert first["sk"] != second["sk"], "a second same-day note must get its OWN key"
    assert first["sk"].startswith("MEMORY#training#2026-09-25#") and second["sk"].startswith("MEMORY#training#2026-09-25#")

    rows = _training_rows(fake)
    assert [r["summary"] for r in rows] == [_INJURY, _MACHINES], "both notes are in the store — the first was not erased"
    assert [r["stored_at"] for r in rows] == [_T_INJURY.isoformat(), _T_MACHINES.isoformat()]

    read = tm.tool_read_platform_memory({"category": "training", "days": 365})
    assert read["count"] == 2
    assert [r["summary"] for r in read["records"]] == [_MACHINES, _INJURY], "newest stored first; both served"
    assert all(r["sk"] for r in read["records"]), "each record carries its sk — the handle replace_key / delete key take"


def test_issue_4171_the_write_path_has_no_unconditional_put():
    """Derivation guard for the mutation control: restoring `table.put_item(Item=item)` (the
    unconditional put that erased the injury note) is caught here, not only by the fixture."""
    tree = ast.parse(inspect.getsource(tm.tool_write_platform_memory))
    puts = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "put_item"]
    assert puts, "the write path must still write"
    for call in puts:
        kws = {k.arg for k in call.keywords}
        assert "ConditionExpression" in kws, f"unconditional put_item at line {call.lineno} — a race could clobber a same-day note"


def test_issue_4171_an_identical_replay_converges_on_one_row(monkeypatch):
    fake = _wire_0925(monkeypatch)
    first = tm.tool_write_platform_memory({"category": "training", "content": {"summary": _INJURY}})
    replay = tm.tool_write_platform_memory({"category": "training", "content": {"summary": _INJURY}})
    assert first["status"] == "stored"
    assert replay["status"] == "unchanged" and replay["sk"] == first["sk"], replay
    assert len(_training_rows(fake)) == 1, "a replay is not a second note (#3114 CONTENT_KEY)"
    assert _training_rows(fake)[0]["stored_at"] == _T_INJURY.isoformat(), "the replay did not touch the original row"


def test_issue_4171_replace_key_rewrites_one_named_row_and_only_that_row(monkeypatch):
    fake = _wire_0925(monkeypatch, _T_INJURY, _T_MACHINES, datetime(2026, 9, 26, 2, 20, 56, tzinfo=timezone.utc))
    first = tm.tool_write_platform_memory({"category": "training", "content": {"summary": _INJURY}})
    second = tm.tool_write_platform_memory({"category": "training", "content": {"summary": _MACHINES}})

    out = tm.tool_write_platform_memory(
        {"category": "training", "content": {"summary": "Right knee niggle since 09-24; no other injuries"}, "replace_key": first["sk"]}
    )
    assert out["status"] == "replaced" and out["replaced_key"] == first["sk"] and out["date"] == "2026-09-25"
    rows = {r["sk"]: r for r in _training_rows(fake)}
    assert set(rows) == {first["sk"], second["sk"]}, "a replace neither adds a row nor removes the other"
    assert rows[first["sk"]]["summary"].startswith("Right knee niggle") and "replaced_at" in rows[first["sk"]]
    assert rows[second["sk"]]["summary"] == _MACHINES, "the other same-day note is untouched"


def test_issue_4171_replace_key_refuses_an_absent_key_a_foreign_category_and_a_disagreeing_date(monkeypatch):
    fake = _wire_0925(monkeypatch)
    first = tm.tool_write_platform_memory({"category": "training", "content": {"summary": _INJURY}})
    before = {k: dict(v) for k, v in fake.store.items()}

    absent = tm.tool_write_platform_memory(
        {"category": "training", "content": {"summary": "x"}, "replace_key": "MEMORY#training#2026-09-25#0000000000"}
    )
    assert "error" in absent and "nothing to replace" in absent["error"], absent
    foreign = tm.tool_write_platform_memory({"category": "life_context", "content": {"summary": "x"}, "replace_key": first["sk"]})
    assert "error" in foreign and "does not name a 'life_context' record" in foreign["error"], foreign
    disagree = tm.tool_write_platform_memory(
        {"category": "training", "content": {"summary": "x"}, "replace_key": first["sk"], "date": "2026-09-24"}
    )
    assert "error" in disagree and "disagrees" in disagree["error"], disagree
    assert {k: dict(v) for k, v in fake.store.items()} == before, "a refused replace writes nothing"


def test_issue_4171_overwrite_true_is_refused_and_overwrite_false_is_additive(monkeypatch):
    fake = _wire_0925(monkeypatch)
    tm.tool_write_platform_memory({"category": "training", "content": {"summary": _INJURY}})
    refused = tm.tool_write_platform_memory({"category": "training", "content": {"summary": _MACHINES}, "overwrite": True})
    assert "error" in refused and "replace_key" in refused["error"], refused
    assert len(_training_rows(fake)) == 1, "the refused call wrote nothing"
    ok = tm.tool_write_platform_memory({"category": "training", "content": {"summary": _MACHINES}, "overwrite": False})
    assert ok["status"] == "stored"
    assert [r["summary"] for r in _training_rows(fake)] == [_INJURY, _MACHINES]


def test_issue_4171_the_registry_schema_offers_replace_key_and_no_overwrite():
    from mcp.registry import TOOLS

    props = TOOLS["write_platform_memory"]["schema"]["inputSchema"]["properties"]
    assert "replace_key" in props and props["replace_key"]["type"] == "string"
    assert "overwrite" not in props, "the default-overwrite flag is what erased the 09-25 note"
    dprops = TOOLS["delete_platform_memory"]["schema"]["inputSchema"]
    assert "key" in dprops["properties"] and dprops["required"] == ["category"]


def test_issue_4171_every_reader_sees_both_same_day_records(monkeypatch):
    """The acceptance's second box: read_platform_memory, the coach memory block's selector,
    and list_memory_categories all serve BOTH same-day rows (a 3-segment legacy row and a
    4-segment note row side by side)."""
    fake = _wire_0925(monkeypatch)
    legacy = _mem("training", "2026-09-25", summary=_INJURY, stored_at=_T_INJURY.isoformat())
    fake._seed(legacy)  # the pre-#4171 one-row-per-day shape, as every existing row is keyed
    tm.tool_write_platform_memory({"category": "training", "content": {"summary": _MACHINES}})

    read = tm.tool_read_platform_memory({"category": "training", "days": 365})
    assert read["count"] == 2 and {r["summary"] for r in read["records"]} == {_INJURY, _MACHINES}

    picked = pm.select_conversation_memories(list(fake.store.values()), coach_id="training", today=date(2026, 9, 26))
    assert {p["record"]["summary"] for p in picked} == {_INJURY, _MACHINES}, "the coach block selector keeps both"
    assert all(p["date"] == "2026-09-25" for p in picked)

    # A note row with no duplicate `date` attribute is dated from the sk's DATE segment (index 2),
    # not from its last segment (the content hash).
    undated = {k: v for k, v in _mem("training", "2026-09-25", summary="undated").items() if k != "date"}
    undated["sk"] = "MEMORY#training#2026-09-25#abcdef0123"
    fake._seed(undated)
    census = tm.tool_list_memory_categories({"days": 365})
    (training,) = [c for c in census["categories"] if c["category"] == "training"]
    assert training["count"] == 3 and training["latest_date"] == "2026-09-25"


def test_issue_4171_delete_by_exact_key_and_the_legacy_date_form_both_work(monkeypatch):
    fake = _wire_0925(monkeypatch)
    fake._seed(_mem("training", "2026-09-24", summary="legacy"))
    note = tm.tool_write_platform_memory({"category": "training", "content": {"summary": _MACHINES}})

    wrong_cat = tm.tool_delete_platform_memory({"category": "life_context", "key": note["sk"]})
    assert "error" in wrong_cat and len(fake.store) == 2
    assert "error" in tm.tool_delete_platform_memory({"category": "training"}), "date or key is required"

    out = tm.tool_delete_platform_memory({"category": "training", "key": note["sk"]})
    assert out["status"] == "deleted" and out["sk"] == note["sk"] and out["date"] == "2026-09-25"
    legacy = tm.tool_delete_platform_memory({"category": "training", "date": "2026-09-24"})
    assert legacy["status"] == "deleted" and legacy["sk"] == "MEMORY#training#2026-09-24"
    # #4355: SOFT delete — the MCP role has no dynamodb:DeleteItem on this partition, so
    # both rows survive in the store, tombstoned, never removed.
    assert len(fake.store) == 2
    assert fake.deletes == []


# ── #4355: delete_platform_memory is refused by IAM — the MCP role has no ────────────
# dynamodb:DeleteItem on platform_memory. Fix: an UpdateItem tombstone (deleted_at /
# deleted_reason) that every reader of the partition skips, never a DynamoDB delete.


def test_issue_4355_delete_is_a_tombstone_not_a_dynamodb_delete(monkeypatch):
    fake = _wire_0925(monkeypatch, _T_INJURY, datetime(2026, 9, 26, 2, 20, 0, tzinfo=timezone.utc))
    note = tm.tool_write_platform_memory({"category": "training", "content": {"summary": _INJURY}})
    out = tm.tool_delete_platform_memory({"category": "training", "key": note["sk"], "reason": "typo"})
    assert out["status"] == "deleted" and out["sk"] == note["sk"] and "deleted_at" in out
    row = fake.store[("USER#matthew#SOURCE#platform_memory", note["sk"])]
    assert row["deleted_at"] == out["deleted_at"]
    assert row["deleted_reason"] == "typo"
    assert row["summary"] == _INJURY, "a tombstone marks the row, it does not erase its content"
    assert fake.deletes == [], "dynamodb:DeleteItem must never be called (#4355)"
    # Every update the tool sent was conditional — never an unconditional tombstone that
    # could clobber a race.
    assert all(u["ConditionExpression"] for u in fake.updates)


def test_issue_4355_delete_defaults_reason_and_is_idempotently_not_found_on_replay(monkeypatch):
    fake = _wire_0925(monkeypatch)
    note = tm.tool_write_platform_memory({"category": "training", "content": {"summary": _INJURY}})
    first = tm.tool_delete_platform_memory({"category": "training", "key": note["sk"]})
    assert first["status"] == "deleted"
    row = fake.store[("USER#matthew#SOURCE#platform_memory", note["sk"])]
    assert row["deleted_reason"] == "mcp_delete", "an unstated reason still leaves an honest default trail"
    again = tm.tool_delete_platform_memory({"category": "training", "key": note["sk"]})
    assert again["status"] == "not_found", "a second delete of an already-tombstoned row removes nothing"
    assert row["deleted_at"] == first["deleted_at"], "the replay must not restamp the tombstone's own instant"


def test_issue_4355_delete_of_a_never_written_row_is_not_found(monkeypatch):
    _wire_0925(monkeypatch)
    out = tm.tool_delete_platform_memory({"category": "training", "date": "2026-09-01"})
    assert out["status"] == "not_found"


def test_issue_4355_the_delete_path_never_calls_delete_item():
    """Derivation guard (mutation control): restoring `table.delete_item(...)` — the
    IAM-refused call the live incident reported — is caught here even before the wire's
    own AssertionError would fire. Mutation-proved: reintroducing a `table.delete_item(`
    call into this function makes this assertion fail (see the PR's pasted VERIFY run)."""
    tree = ast.parse(inspect.getsource(tm.tool_delete_platform_memory))
    calls = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "delete_item" not in calls, "delete_platform_memory must tombstone via update_item, never dynamodb:DeleteItem (#4355)"
    assert "update_item" in calls


def test_issue_4355_read_platform_memory_skips_a_soft_deleted_note(monkeypatch):
    fake = _wire_0925(monkeypatch)
    fake._seed(_mem("training", "2026-09-20", summary="gone", deleted_at="2026-09-21T00:00:00+00:00", deleted_reason="x"))
    fake._seed(_mem("training", "2026-09-21", summary="kept"))
    read = tm.tool_read_platform_memory({"category": "training", "days": 30})
    assert read["count"] == 1
    assert [r["summary"] for r in read["records"]] == ["kept"]


def test_issue_4355_list_memory_categories_does_not_census_a_soft_deleted_note(monkeypatch):
    fake = _wire_0925(monkeypatch)
    fake._seed(_mem("training", "2026-09-20", summary="gone", deleted_at="2026-09-21T00:00:00+00:00"))
    fake._seed(_mem("training", "2026-09-21", summary="kept"))
    census = tm.tool_list_memory_categories({"days": 365})
    (training,) = [c for c in census["categories"] if c["category"] == "training"]
    assert training["count"] == 1 and training["latest_date"] == "2026-09-21"


def test_issue_4355_coach_memory_selector_skips_a_soft_deleted_note():
    """The stage-1 / coach chat-context reader (ai.platform_memory.select_conversation_memories,
    which mcp.tools_plan._training_memory_constraints and the coach prompt block both read
    through) must not keep quoting a tombstoned note."""
    gone = _mem("training", "2026-09-20", summary="gone")
    gone["deleted_at"] = "2026-09-21T00:00:00+00:00"
    kept = _mem("training", "2026-09-21", summary="kept")
    picked = pm.select_conversation_memories([gone, kept], coach_id="training", today=date(2026, 9, 22))
    assert [p["record"]["summary"] for p in picked] == ["kept"]


def test_issue_4355_a_reader_that_ignores_the_tombstone_would_red_here(monkeypatch):
    """Mutation control (pasted in the PR): commenting out the `deleted_at` skip in
    `select_conversation_memories` (or in `tool_read_platform_memory`) makes the two tests
    above fail, because THIS is the only place either checks it — proving the guard is
    load-bearing rather than redundant with some other filter."""
    src = inspect.getsource(pm.select_conversation_memories)
    assert "deleted_at" in src, "select_conversation_memories must skip deleted_at rows (#4355)"
    src2 = inspect.getsource(tm.tool_read_platform_memory)
    assert "deleted_at" in src2 or "_DELETED_AT_FIELD" in src2


# ── #4355 acceptance box 2 — "guard the SET": every MCP tool handler that calls
# dynamodb:DeleteItem must either have that action in the MCP role's synthesized IAM
# policy for the partition it targets, or must not call delete_item at all. Both sides
# are DERIVED (AST), never hand-enumerated — a new delete_item call anywhere in mcp/*.py
# joins the scan the day it's written, and the granted LeadingKeys set is read straight
# out of cdk/stacks/role_policies_serve.py, never copied by hand.

import glob as _glob  # noqa: E402

_MCP_DIR = os.path.join(_REPO, "mcp")
_ROLE_POLICIES_SERVE = os.path.join(_REPO, "cdk", "stacks", "role_policies_serve.py")

# Best-effort resolution of a `pk=<expr>` source to its literal partition string, for the
# handful of idioms mcp/*.py's delete_item call sites actually use today (a zero-arg
# helper returning an f-string, or a module-level constant built the same way — both
# hand-verified against the actual USER_ID='matthew' this deploys with). An expression
# this doesn't recognise resolves to None, and the closure test below treats "None" as
# UNRESOLVED, never as "covered" — no guess ever reads as a pass.
_KNOWN_PK_LITERALS: dict[tuple[str, str], str] = {
    ("tools_journal.py", "_quotes_pk()"): "USER#matthew#SOURCE#journal_quotes",
    ("tools_sick_days.py", "SICK_DAYS_PK"): "USER#matthew#SOURCE#sick_days",
}

# The residual this sweep found and is NOT fixing here (different tools, out of #4355's
# scope — filed as #4377/#4378). Pinned by (file, pk-expression) so a change to EITHER
# side is visible: if the set shrinks, close the matching issue and shrink this pin; if it
# grows, a NEW unauthorized delete_item call needs a look before merge.
_KNOWN_DELETE_ITEM_IAM_GAPS: dict[tuple[str, str], str] = {
    ("tools_journal.py", "_quotes_pk()"): "#4377 — mark_journal_quote(action='unmark')",
    ("tools_sick_days.py", "SICK_DAYS_PK"): "#4378 — manage_sick_days clear action",
}


def _mcp_delete_item_sites():
    """(file, lineno, pk_source) for every `<table>.delete_item(` call across mcp/*.py."""
    out = []
    for path in sorted(_glob.glob(os.path.join(_MCP_DIR, "*.py"))):
        src = open(path, encoding="utf-8").read()
        for node in ast.walk(ast.parse(src, filename=path)):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "delete_item"):
                continue
            pk_source = "<unresolved>"
            for kw in node.keywords:
                if kw.arg == "Key" and isinstance(kw.value, ast.Dict):
                    for k, v in zip(kw.value.keys, kw.value.values):
                        if isinstance(k, ast.Constant) and k.value == "pk":
                            pk_source = ast.unparse(v)
            out.append((os.path.basename(path), node.lineno, pk_source))
    return out


def _mcp_server_delete_item_leading_keys():
    """LeadingKeys values `dynamodb:DeleteItem` is scoped to for the mcp_server() IAM role,
    derived from cdk/stacks/role_policies_serve.py's own source — never hand-copied.
    Returns None if an UNCONDITIONAL DeleteItem grant is found (covers every partition)."""
    tree = ast.parse(open(_ROLE_POLICIES_SERVE, encoding="utf-8").read(), filename=_ROLE_POLICIES_SERVE)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "mcp_server")
    leading_keys: set[str] = set()
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "PolicyStatement"):
            continue
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        actions_node = kw.get("actions")
        actions = [a.value for a in getattr(actions_node, "elts", []) if isinstance(a, ast.Constant)]
        if "dynamodb:DeleteItem" not in actions:
            continue
        cond = kw.get("conditions")
        if cond is None:
            return None  # an unconditional DeleteItem grant — covers everything
        for _c_key, c_val in zip(getattr(cond, "keys", []), getattr(cond, "values", [])):
            for kk, vv in zip(getattr(c_val, "keys", []), getattr(c_val, "values", [])):
                if isinstance(kk, ast.Constant) and kk.value == "dynamodb:LeadingKeys":
                    leading_keys |= {e.value for e in getattr(vv, "elts", []) if isinstance(e, ast.Constant)}
    return leading_keys


def test_issue_4355_delete_item_scan_finds_the_known_mcp_sites():
    """Guard the guard: if this finds nothing, the AST scan silently stopped working."""
    sites = _mcp_delete_item_sites()
    files = {f for f, _ln, _pk in sites}
    assert files == {"tools_journal.py", "tools_sick_days.py"}, (
        f"expected exactly the two known-uncovered delete_item sites (mark_journal_quote, "
        f"manage_sick_days), found files={sorted(files)} — delete_platform_memory should have "
        "left this scan by tombstoning instead (#4355); a NEW file appearing here needs the "
        "same IAM-coverage look this test gives the other two."
    )


def test_issue_4355_delete_platform_memory_no_longer_calls_delete_item():
    """The specific #4355 fix, seen from the census side: tools_memory.py must have ZERO
    delete_item call sites left (it tombstones via update_item now)."""
    sites = _mcp_delete_item_sites()
    assert "tools_memory.py" not in {f for f, _ln, _pk in sites}


def test_issue_4355_every_mcp_delete_item_call_is_iam_covered_or_a_named_residual():
    """The closure: an uncovered delete_item call site must be EITHER absent, OR named in
    `_KNOWN_DELETE_ITEM_IAM_GAPS` with a filed follow-up issue — never silently passing."""
    granted = _mcp_server_delete_item_leading_keys()
    assert granted, "expected the mcp_server() role's scoped DynamoDBMealPrune DeleteItem grant to still exist"
    uncovered = []
    for file_name, lineno, pk_source in _mcp_delete_item_sites():
        literal = _KNOWN_PK_LITERALS.get((file_name, pk_source))
        covered = literal is not None and literal in granted
        if not covered:
            uncovered.append((file_name, pk_source, lineno))
    uncovered_keys = {(f, pk) for f, pk, _ln in uncovered}
    assert uncovered_keys == set(_KNOWN_DELETE_ITEM_IAM_GAPS), (
        "the set of IAM-uncovered delete_item call sites in mcp/*.py changed:\n"
        f"  now:      {sorted(uncovered_keys)}\n"
        f"  expected: {sorted(_KNOWN_DELETE_ITEM_IAM_GAPS)}\n"
        "A NEW entry means a handler calls dynamodb:DeleteItem the MCP role cannot perform — "
        "either grant it (cdk/stacks/role_policies_serve.py::mcp_server(), scoped by "
        "dynamodb:LeadingKeys) or stop calling delete_item (the #4355 tombstone pattern). A "
        "MISSING entry means a known gap (#4377/#4378) was fixed — shrink _KNOWN_DELETE_ITEM_IAM_GAPS "
        "and _KNOWN_PK_LITERALS to match, or close the issue."
    )
