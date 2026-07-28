"""tests/test_conversation_enrichment_1577.py — conversational capture becomes numeric signal (#1577).

Pins the four acceptance criteria, all offline (no Bedrock, no DynamoDB):

  AC1 — the sweep runs over the three conversational partitions on the journal
        enrichment Lambda's existing 6:30 AM cadence; every output row carries channel
        provenance (coach_checkin / habit_reflection / field_note); the Haiku cost is
        budget-gated (band-1 ``conversation_enrichment`` — an over-tier run reports an
        explicit paused status without a single model call).
  AC2 — signals are ANALYSIS-ONLY v1 (declared in conversation_enrichment.
        enrichment_policy, stamped on every enriched record as enriched_scope, and
        documented + fingerprinted in the Methods Registry): they never move
        character/flourishing scoring, and absence of conversation is "no data".
  AC3 — the hypothesis pipeline accepts conversation-sourced candidates with the
        channel labeled in candidate provenance (analyzer aggregation + engine prompt).
  AC4 — double-counting guarded: a takeaway routed into BOTH Notion and a check-in
        enriches once (content-hash equality or ≥40-char normalized containment), and
        the same takeaway across two conversational channels dedups too.
"""

import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "ingestion"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "intelligence"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "compute"))

import journal_analyzer_lambda as jal  # noqa: E402
from ai import (
    budget_guard,  # noqa: E402
    conversation_enrichment as ce,  # noqa: E402
)
from botocore.exceptions import ClientError  # noqa: E402

# ── Fixtures ─────────────────────────────────────────────────────────────────


class FakeTable:
    """Captures update_item calls; query is routed through a pk→rows map."""

    def __init__(self, rows_by_pk=None):
        self.rows_by_pk = rows_by_pk or {}
        self.updates = []

    def query(self, KeyConditionExpression=None, **kw):  # noqa: N803 — boto3 shape
        raise AssertionError("tests route reads through monkeypatched _query_between")

    def update_item(self, **kwargs):
        self.updates.append(kwargs)


def _checkin(answer, sk="CHECKIN#2026-07-20#abc12345", status="answered", **extra):
    it = {
        "pk": "COACH#mind_coach",
        "sk": sk,
        "coach_id": "mind",
        "coach_name": "the Mind coach",
        "question": "What's been taking up mental space this week?",
        "status": status,
        "answer": answer,
    }
    it.update(extra)
    return it


def _reflection(**extra):
    it = {
        "pk": "USER#matthew#SOURCE#habit_causality",
        "sk": "HABITDAY#2026-07-19#morning-walk",
        "date": "2026-07-19",
        "habit": "Morning Walk",
        "slug": "morning-walk",
        "channel": "claude_reflection",
        "why_missed": "the rain plus a 7am call meant the window just never opened up",
    }
    it.update(extra)
    return it


def _field_note(**extra):
    it = {
        "pk": "USER#matthew#SOURCE#field_notes",
        "sk": "WEEK#2026-W30",
        "week": "2026-W30",
        "ai_generated_at": "2026-07-20T14:00:00Z",
        "matthew_notes": "I think the sleep read is right — the late screens are doing more damage than the training load is.",
        "matthew_agreement": "mostly",
    }
    it.update(extra)
    return it


def _route_queries(monkeypatch, rows_by_prefix):
    """Route _query_between by (pk, sk_lo-prefix) → canned rows."""

    def fake(table, pk, sk_lo, sk_hi):
        for (want_pk, want_prefix), rows in rows_by_prefix.items():
            if pk == want_pk and sk_lo.startswith(want_prefix):
                return list(rows)
        return []

    monkeypatch.setattr(ce, "_query_between", fake)


def _haiku_caller(extraction, seen=None):
    def call(body):
        if seen is not None:
            seen.append(body)
        return {"content": [{"type": "text", "text": json.dumps(extraction)}]}

    return call


ANSWER = "Honestly the evenings are the problem because I keep doomscrolling until midnight and then everything slips."


# ── AC1: collection + channel provenance ─────────────────────────────────────


class TestCollection:
    def test_collects_all_three_channels_with_provenance(self, monkeypatch):
        _route_queries(
            monkeypatch,
            {
                ("COACH#mind_coach", "CHECKIN#"): [_checkin(ANSWER)],
                ("USER#matthew#SOURCE#habit_causality", "HABITDAY#"): [_reflection()],
                ("USER#matthew#SOURCE#field_notes", "WEEK#"): [_field_note()],
            },
        )
        got = ce.collect_conversational_items(FakeTable(), "2026-07-14", "2026-07-27", coach_ids=["mind"])
        assert sorted(c["channel"] for c in got) == ["coach_checkin", "field_note", "habit_reflection"]
        by_ch = {c["channel"]: c for c in got}
        assert by_ch["coach_checkin"]["text"] == ANSWER
        assert by_ch["coach_checkin"]["date"] == "2026-07-20"
        assert "why it was missed" in by_ch["habit_reflection"]["text"]
        assert by_ch["field_note"]["date"] == "2026-07-20"  # Monday of 2026-W30

    def test_open_and_skipped_checkins_are_never_collected(self, monkeypatch):
        """A skip is a boundary, not data (ADR-104) — it never reaches Haiku."""
        _route_queries(
            monkeypatch,
            {("COACH#mind_coach", "CHECKIN#"): [_checkin("", status="open"), _checkin("no thanks", status="skipped")]},
        )
        assert ce.collect_conversational_items(FakeTable(), "2026-07-14", "2026-07-27", coach_ids=["mind"]) == []

    def test_habitify_note_channel_is_not_conversational(self, monkeypatch):
        _route_queries(
            monkeypatch,
            {("USER#matthew#SOURCE#habit_causality", "HABITDAY#"): [_reflection(channel="habitify_note")]},
        )
        assert ce.collect_conversational_items(FakeTable(), "2026-07-14", "2026-07-27", coach_ids=[]) == []

    def test_field_note_without_response_is_not_collected(self, monkeypatch):
        fn = _field_note()
        del fn["matthew_notes"]
        _route_queries(monkeypatch, {("USER#matthew#SOURCE#field_notes", "WEEK#"): [fn]})
        assert ce.collect_conversational_items(FakeTable(), "2026-07-14", "2026-07-27", coach_ids=[]) == []

    def test_week_monday(self):
        assert ce.week_monday("2026-W30") == "2026-07-20"
        assert ce.week_monday("garbage") is None


class TestApplyEnrichment:
    def test_stamps_channel_scope_hash_and_schema(self):
        table = FakeTable()
        item = _checkin(ANSWER)
        ce.apply_enrichment(table, item, "coach_checkin", {"sentiment": "negative", "themes": ["evening spiral"]}, ANSWER)
        assert len(table.updates) == 1
        up = table.updates[0]
        vals = up["ExpressionAttributeValues"]
        names = set(up["ExpressionAttributeNames"].values())
        assert {"enriched_channel", "enriched_scope", "enriched_content_hash", "enriched_at", "enriched_schema_version"} <= names
        assert vals[":enriched_channel"] == "coach_checkin"
        assert vals[":enriched_scope"] == "analysis_only"  # AC2 — stamped on every output row
        assert vals[":enriched_content_hash"] == ce.content_hash(ANSWER)
        assert vals[":enriched_sentiment"] == "negative"

    def test_grounding_gate_drops_ungrounded_hint(self):
        """ADR-104: a causal hint whose quote is not verbatim in the answer dies
        deterministically before the write."""
        table = FakeTable()
        item = _checkin(ANSWER)
        enrichment = {
            "sentiment": "negative",
            "causal_hints": [
                {
                    "cause": "doomscrolling",
                    "effect": "everything slips",
                    "quote": "I keep doomscrolling until midnight and then everything slips.",
                },
                {"cause": "coffee", "effect": "bad sleep", "quote": "coffee at 6pm wrecked me"},  # NOT in the answer
            ],
        }
        ce.apply_enrichment(table, item, "coach_checkin", enrichment, ANSWER)
        vals = table.updates[0]["ExpressionAttributeValues"]
        kept = vals[":enriched_causal_hints"]
        assert len(kept) == 1 and kept[0]["cause"] == "doomscrolling"


# ── AC1: budget gate ─────────────────────────────────────────────────────────


class TestBudgetGate:
    def test_feature_is_band_1_internal(self):
        assert budget_guard._FEATURE_CUTOFF["conversation_enrichment"] == 1

    def test_paused_run_makes_no_haiku_calls(self, monkeypatch):
        monkeypatch.setattr(budget_guard, "current_tier", lambda: 1)
        calls = []
        summary = ce.run(table=FakeTable(), caller=_haiku_caller({}, calls))
        assert summary["status"] == "paused_by_budget" and summary["tier"] == 1
        assert calls == []  # explicit pause, zero model calls

    def test_tier0_runs(self, monkeypatch):
        monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
        monkeypatch.setattr(ce, "fetch_journal_texts", lambda *a, **k: [])
        item = _checkin(ANSWER)
        monkeypatch.setattr(
            ce,
            "collect_conversational_items",
            lambda *a, **k: [{"item": item, "channel": "coach_checkin", "text": ANSWER, "date": "2026-07-20", "context": "q"}],
        )
        table = FakeTable()
        summary = ce.run(table=table, start_date="2026-07-14", end_date="2026-07-27", caller=_haiku_caller({"sentiment": "negative"}))
        assert summary["status"] == "ok" and summary["enriched"] == 1
        assert summary["scope"] == "analysis_only"
        assert table.updates  # the in-place write happened


# ── AC2: analysis-only scope ─────────────────────────────────────────────────


class TestAnalysisOnlyScope:
    def test_policy_declares_analysis_only(self):
        pol = ce.enrichment_policy()
        assert pol["scope"] == "analysis_only"
        assert pol["moves_character_scoring"] is False
        assert pol["moves_flourishing_scoring"] is False
        assert pol["seeds_hypothesis_candidates"] is True
        # #1708 added the 4th channel (a reaction to the weekly Horizons pick) under the
        # SAME analysis-only scope — same partition, same sweep, same gate.
        assert sorted(pol["channels"]) == ["coach_checkin", "field_note", "habit_reflection", "prescription_reaction"]

    def test_methods_registry_entry_says_so_and_fingerprint_matches(self):
        from experiment import methods_registry as mr

        entry = mr.get_stat("conversational_enrichment_scope")
        assert entry is not None, "#1577 AC2: the Methods Registry must carry the analysis-only declaration"
        assert "analysis" in entry["formula"].lower() and "analysis-only" in entry["limitations"].lower()
        assert entry["module"] == "conversation_enrichment" and entry["function"] == "enrichment_policy"
        assert (
            entry["fingerprint"] == entry["recorded_fingerprint"]
        ), "enrichment_policy changed without a Methods Registry re-review — scoring promotion must not happen silently"

    def test_flourishing_row_needs_enrichment_absence_is_no_data(self):
        """ADR-104 regression guard on the consumer side: no enriched entries ⇒ no
        flourishing row (None), never a zero row — and conversational records are
        NOT part of that projection (it aggregates only what it is handed from the
        notion journal partition)."""
        from health import flourishing

        assert flourishing.aggregate_entries([]) is None
        assert flourishing.aggregate_entries([{"answer": "x"}]) is None  # unenriched → no data


# ── AC3: channel-labeled candidate provenance ────────────────────────────────


HINT = {"cause": "late screens", "effect": "bad sleep", "quote": "the late screens are doing more damage"}


class TestCandidateChannelProvenance:
    def test_conversational_tuple_carries_channel(self):
        cands = jal.build_hypo_candidates([("2026-07-20", {"enriched_causal_hints": [HINT]}, "coach_checkin")])
        assert len(cands) == 1
        c = cands[0]
        assert c["channels"] == ["coach_checkin"]
        assert c["channel_mentions"] == {"coach_checkin": 1}
        assert c["quotes"][0]["channel"] == "coach_checkin"

    def test_journal_and_checkin_merge_with_both_channels(self):
        cands = jal.build_hypo_candidates(
            [
                ("2026-07-19", {"enriched_causal_hints": [dict(HINT, quote="screens wrecked my sleep again")]}),
                ("2026-07-20", {"enriched_causal_hints": [HINT]}, "coach_checkin"),
            ]
        )
        assert len(cands) == 1
        c = cands[0]
        assert c["channels"] == ["coach_checkin", "journal"]
        assert c["mentions"] == 2 and c["channel_mentions"] == {"journal": 1, "coach_checkin": 1}

    def test_plain_journal_tuples_default_to_journal_channel(self):
        c = jal.build_hypo_candidates([("2026-07-19", {"enriched_causal_hints": [HINT]})])[0]
        assert c["channels"] == ["journal"]

    def test_engine_prompt_block_names_the_channel(self):
        import hypothesis_engine_lambda as eng

        block = eng.format_journal_candidates(
            [
                {
                    "cause": "late screens",
                    "effect": "bad sleep",
                    "cause_metric": None,
                    "effect_metric": "total_sleep_hrs",
                    "mentions": 2,
                    "channels": ["coach_checkin", "journal"],
                    "quotes": [{"date": "2026-07-20", "quote": "the late screens are doing more damage", "channel": "coach_checkin"}],
                }
            ]
        )
        assert "[heard via coach check-in]" in block  # a hypothesis born from a check-in says so
        assert "coach check-in quote (2026-07-20)" in block
        assert "JOURNAL-DERIVED CANDIDATES" in block  # the #506 anchor string stays

    def test_engine_block_without_channels_stays_plain(self):
        import hypothesis_engine_lambda as eng

        block = eng.format_journal_candidates(
            [
                {
                    "cause": "hard workout",
                    "effect": "low recovery",
                    "cause_metric": "workout",
                    "effect_metric": "recovery",
                    "mentions": 3,
                    "quotes": [{"date": "2026-07-01", "quote": "legs day wrecked my recovery"}],
                }
            ]
        )
        cand_line = next(ln for ln in block.splitlines() if ln.startswith("- "))
        assert "heard via" not in cand_line  # no conversational channel ⇒ no [heard via ...] tag on the line
        assert "journal quote (2026-07-01)" in cand_line

    def test_enriched_conversational_records_only_returns_enriched(self, monkeypatch):
        enriched = _checkin(ANSWER, enriched_at="2026-07-21T13:30:00+00:00")
        raw = _checkin("Still thinking about it, honestly nothing concrete yet today.", sk="CHECKIN#2026-07-21#def67890")
        _route_queries(monkeypatch, {("COACH#mind_coach", "CHECKIN#"): [enriched, raw]})
        got = ce.enriched_conversational_records(FakeTable(), "2026-07-14", "2026-07-27", coach_ids=["mind"])
        assert len(got) == 1
        date, item, channel = got[0]
        assert item["sk"] == enriched["sk"] and channel == "coach_checkin" and date == "2026-07-20"


# ── AC4: double-counting guard ───────────────────────────────────────────────


class TestDedup:
    def test_hash_equality_dedups(self):
        assert ce.is_duplicate_takeaway(ANSWER, [f"  {ANSWER.upper()}  "])  # normalization: case + whitespace

    def test_containment_dedups_the_routed_takeaway(self):
        journal = "Evening pages. " + ANSWER + " Tomorrow I set a hard cutoff at ten."
        assert ce.is_duplicate_takeaway(ANSWER, [journal])

    def test_short_overlap_is_not_a_duplicate(self):
        assert not ce.is_duplicate_takeaway("Slept fine, felt good.", ["Slept fine, felt good. " + "x" * 200])
        assert not ce.is_duplicate_takeaway(ANSWER, ["A completely different entry about training and food."])

    def test_run_dedups_notion_routed_checkin_without_haiku(self, monkeypatch):
        """AC4 end-to-end: the takeaway lives in BOTH the journal and a check-in —
        the check-in is marked deduped and never enriched."""
        monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
        monkeypatch.setattr(ce, "fetch_journal_texts", lambda *a, **k: ["Journal entry. " + ANSWER + " More prose."])
        item = _checkin(ANSWER)
        monkeypatch.setattr(
            ce,
            "collect_conversational_items",
            lambda *a, **k: [{"item": item, "channel": "coach_checkin", "text": ANSWER, "date": "2026-07-20", "context": "q"}],
        )
        calls = []
        table = FakeTable()
        summary = ce.run(table=table, start_date="2026-07-14", end_date="2026-07-27", caller=_haiku_caller({}, calls))
        assert summary["deduped"] == 1 and summary["enriched"] == 0
        assert calls == []  # zero Haiku spend on a duplicate
        up = table.updates[0]
        assert "enrichment_deduped_at" in up["UpdateExpression"]
        assert up["ExpressionAttributeValues"][":r"] == "journal_duplicate"

    def test_run_dedups_same_takeaway_across_two_conversational_channels(self, monkeypatch):
        monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
        monkeypatch.setattr(ce, "fetch_journal_texts", lambda *a, **k: [])
        first = _checkin(ANSWER)
        second = dict(_field_note(), matthew_notes=ANSWER)
        monkeypatch.setattr(
            ce,
            "collect_conversational_items",
            lambda *a, **k: [
                {"item": first, "channel": "coach_checkin", "text": ANSWER, "date": "2026-07-20", "context": "q"},
                {"item": second, "channel": "field_note", "text": ANSWER, "date": "2026-07-20", "context": "fn"},
            ],
        )
        calls = []
        summary = ce.run(
            table=FakeTable(), start_date="2026-07-14", end_date="2026-07-27", caller=_haiku_caller({"sentiment": "negative"}, calls)
        )
        assert summary["enriched"] == 1 and summary["deduped"] == 1
        assert len(calls) == 1  # exactly one Haiku call for the pair

    def test_previously_deduped_record_is_skipped_next_run(self, monkeypatch):
        monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
        monkeypatch.setattr(ce, "fetch_journal_texts", lambda *a, **k: [])
        item = _checkin(ANSWER, enrichment_deduped_at="2026-07-21T13:30:00+00:00")
        monkeypatch.setattr(
            ce,
            "collect_conversational_items",
            lambda *a, **k: [{"item": item, "channel": "coach_checkin", "text": ANSWER, "date": "2026-07-20", "context": "q"}],
        )
        table = FakeTable()
        summary = ce.run(table=table, start_date="2026-07-14", end_date="2026-07-27", caller=_haiku_caller({}))
        assert summary["skipped"] == 1 and summary["enriched"] == 0 and summary["deduped"] == 0
        assert table.updates == []  # no re-marking, no enrichment


# ── Sweep mechanics ──────────────────────────────────────────────────────────


class TestSweep:
    def test_word_floor_skips_thin_answers(self, monkeypatch):
        monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
        monkeypatch.setattr(ce, "fetch_journal_texts", lambda *a, **k: [])
        item = _checkin("fine I guess")
        monkeypatch.setattr(
            ce,
            "collect_conversational_items",
            lambda *a, **k: [{"item": item, "channel": "coach_checkin", "text": "fine I guess", "date": "2026-07-20", "context": "q"}],
        )
        summary = ce.run(table=FakeTable(), start_date="2026-07-14", end_date="2026-07-27", caller=_haiku_caller({}))
        assert summary["skipped"] == 1 and summary["enriched"] == 0

    def test_already_enriched_current_schema_skips(self, monkeypatch):
        monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
        monkeypatch.setattr(ce, "fetch_journal_texts", lambda *a, **k: [])
        item = _checkin(ANSWER, enriched_at="2026-07-21T13:30:00+00:00", enriched_schema_version=ce.SCHEMA_VERSION)
        monkeypatch.setattr(
            ce,
            "collect_conversational_items",
            lambda *a, **k: [{"item": item, "channel": "coach_checkin", "text": ANSWER, "date": "2026-07-20", "context": "q"}],
        )
        summary = ce.run(table=FakeTable(), start_date="2026-07-14", end_date="2026-07-27", caller=_haiku_caller({}))
        assert summary["skipped"] == 1 and summary["enriched"] == 0

    def test_parse_extraction_tolerates_fences(self):
        raw = {"content": [{"type": "text", "text": '```json\n{"sentiment": "mixed"}\n```'}]}
        assert ce.parse_extraction(raw) == {"sentiment": "mixed"}
        assert ce.parse_extraction({"content": [{"type": "text", "text": "not json"}]}) is None

    def test_unparseable_extraction_counts_as_error(self, monkeypatch):
        monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
        monkeypatch.setattr(ce, "fetch_journal_texts", lambda *a, **k: [])
        item = _checkin(ANSWER)
        monkeypatch.setattr(
            ce,
            "collect_conversational_items",
            lambda *a, **k: [{"item": item, "channel": "coach_checkin", "text": ANSWER, "date": "2026-07-20", "context": "q"}],
        )
        summary = ce.run(
            table=FakeTable(),
            start_date="2026-07-14",
            end_date="2026-07-27",
            caller=lambda body: {"content": [{"type": "text", "text": "NOT JSON"}]},
        )
        assert summary["errors"] == 1 and summary["enriched"] == 0


# ── AC1: the 6:30 AM cadence wiring (journal_enrichment_lambda) ──────────────


class TestCadenceWiring:
    def test_conversations_only_event_runs_the_sweep(self, monkeypatch):
        from ingestion import journal_enrichment_lambda as je

        seen = {}

        def fake_run(table=None, start_date=None, end_date=None, force=False, **kw):
            seen.update({"start": start_date, "end": end_date, "force": force})
            return {"status": "ok", "enriched": 0, "skipped": 0, "deduped": 0, "errors": 0}

        monkeypatch.setattr(ce, "run", fake_run)
        resp = je.lambda_handler({"conversations_only": True, "date": "2026-07-20"}, None)
        body = json.loads(resp["body"])
        assert body["status"] == "ok"
        assert seen == {"start": "2026-07-20", "end": "2026-07-20", "force": False}

    def test_default_cadence_lets_module_pick_its_wider_window(self, monkeypatch):
        from ingestion import journal_enrichment_lambda as je

        seen = {}

        def fake_run(table=None, start_date=None, end_date=None, force=False, **kw):
            seen.update({"start": start_date, "end": end_date})
            return {"status": "ok"}

        monkeypatch.setattr(ce, "run", fake_run)
        je.lambda_handler({"conversations_only": True}, None)
        assert seen["start"] is None  # module default: DEFAULT_LOOKBACK_DAYS ending today
        assert seen["end"]  # the handler's computed end date passes through


# ── ADR-077 (#1790): the conversational seam never reads or writes across a ──
# ── reset boundary — with_phase_filter on the query, tombstone-safe writes  ──


class FakeConditionalTable:
    """Honors ConditionExpression like real DynamoDB, keyed on a caller-supplied
    tombstoned-keys set — proves apply_enrichment/mark_deduped genuinely refuse
    to land on a row that's tombstoned, not just skip it in Python."""

    def __init__(self, tombstoned_keys=()):
        self.tombstoned_keys = set(tombstoned_keys)
        self.updates = []

    def update_item(self, Key, ConditionExpression=None, **kw):  # noqa: N803 — boto3 shape
        key = (Key["pk"], Key["sk"])
        if ConditionExpression and key in self.tombstoned_keys:
            raise ClientError(
                {"Error": {"Code": "ConditionalCheckFailedException", "Message": "The conditional request failed"}}, "UpdateItem"
            )
        self.updates.append({"Key": Key, **kw})


class TestPhaseFilterOnTheSingleQueryHelper:
    """`_query_between` is the ONE query helper for all three conversational
    partitions plus the journal dedup corpus (module docstring) — wiring
    with_phase_filter here is the single fix that closes the read-side gap for
    every caller at once."""

    def test_query_between_applies_the_phase_filter(self):
        captured = {}

        class _Table:
            def query(self, **kwargs):
                captured.update(kwargs)
                return {"Items": []}

        items = ce._query_between(_Table(), "COACH#mind_coach", "CHECKIN#2026-07-14", "CHECKIN#2026-07-27#~")
        assert items == []
        assert "phase" in captured.get("FilterExpression", "")
        assert captured["ExpressionAttributeNames"]["#phase"] == "phase"
        assert ":phase_experiment" in captured["ExpressionAttributeValues"]

    def test_paginated_query_still_carries_the_filter_on_every_page(self):
        pages = [
            {"Items": [{"sk": "CHECKIN#2026-07-14#a"}], "LastEvaluatedKey": {"pk": "x", "sk": "y"}},
            {"Items": [{"sk": "CHECKIN#2026-07-15#b"}]},
        ]
        seen_kwargs = []

        class _Table:
            def query(self, **kwargs):
                seen_kwargs.append(kwargs)
                return pages.pop(0)

        items = ce._query_between(_Table(), "COACH#mind_coach", "CHECKIN#2026-07-14", "CHECKIN#2026-07-27#~")
        assert len(items) == 2
        assert all("FilterExpression" in kw for kw in seen_kwargs)


class TestWriteTimeTombstoneGuard:
    """Defense-in-depth on top of the phase-filtered read: a reset can land
    between collection and the Haiku round-trip, so the write itself must
    refuse to enrich (or mark-deduped) a row that's since been tombstoned."""

    def test_apply_enrichment_refuses_a_since_tombstoned_row(self):
        item = _checkin(ANSWER)
        table = FakeConditionalTable(tombstoned_keys={(item["pk"], item["sk"])})
        ok = ce.apply_enrichment(table, item, ce.CHANNEL_COACH_CHECKIN, {"sentiment": "negative", "causal_hints": []}, ANSWER)
        assert ok is False
        assert table.updates == []

    def test_apply_enrichment_writes_normally_when_not_tombstoned(self):
        item = _checkin(ANSWER)
        table = FakeConditionalTable()
        ok = ce.apply_enrichment(table, item, ce.CHANNEL_COACH_CHECKIN, {"sentiment": "negative", "causal_hints": []}, ANSWER)
        assert ok is True
        assert len(table.updates) == 1

    def test_mark_deduped_refuses_a_since_tombstoned_row(self):
        item = _checkin(ANSWER)
        table = FakeConditionalTable(tombstoned_keys={(item["pk"], item["sk"])})
        ok = ce.mark_deduped(table, item, "journal_duplicate", ANSWER)
        assert ok is False
        assert table.updates == []

    def test_run_counts_a_since_tombstoned_enrichment_as_skipped_not_enriched(self, monkeypatch):
        monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
        monkeypatch.setattr(ce, "fetch_journal_texts", lambda *a, **k: [])
        item = _checkin(ANSWER)
        monkeypatch.setattr(
            ce,
            "collect_conversational_items",
            lambda *a, **k: [{"item": item, "channel": ce.CHANNEL_COACH_CHECKIN, "text": ANSWER, "date": "2026-07-20", "context": "q"}],
        )
        table = FakeConditionalTable(tombstoned_keys={(item["pk"], item["sk"])})
        summary = ce.run(
            table=table,
            start_date="2026-07-14",
            end_date="2026-07-27",
            caller=_haiku_caller({"sentiment": "negative", "causal_hints": []}),
        )
        assert summary["enriched"] == 0
        assert summary["skipped"] == 1
        assert table.updates == []

    def test_run_counts_a_since_tombstoned_dedup_as_skipped_not_deduped(self, monkeypatch):
        monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
        monkeypatch.setattr(ce, "fetch_journal_texts", lambda *a, **k: [ANSWER])  # forces the journal-dedup path
        item = _checkin(ANSWER)
        monkeypatch.setattr(
            ce,
            "collect_conversational_items",
            lambda *a, **k: [{"item": item, "channel": ce.CHANNEL_COACH_CHECKIN, "text": ANSWER, "date": "2026-07-20", "context": "q"}],
        )
        table = FakeConditionalTable(tombstoned_keys={(item["pk"], item["sk"])})
        summary = ce.run(table=table, start_date="2026-07-14", end_date="2026-07-27", caller=_haiku_caller({}))
        assert summary["deduped"] == 0
        assert summary["skipped"] == 1
        assert table.updates == []
