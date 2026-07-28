"""test_coach_corrections.py — the #1689 corrections-ledger contract.

Pins: the pure item-builder's shape (pk/sk/Decimal-safety/error-class normalization),
the writer/reader idiom (table passed in, mockable with FakeDdbTable), and the
status-transition guard. Fully offline — mirrors tests/test_eval_retention.py.
"""

import os
import sys
from datetime import datetime, timezone
from decimal import Decimal

os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import pytest  # noqa: E402
from coach import coach_corrections as cc  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402


@pytest.fixture
def table():
    return FakeDdbTable()


# ── build_correction_item: pure, no AWS ─────────────────────────────────────
def test_build_correction_item_shape():
    item = cc.build_correction_item(
        {"surface": "coach_brief", "coach": "sleep_coach", "date": "2026-07-20", "pack_number": 3},
        "The 315 lbs baseline is stale — I'm 321.4 as of genesis.",
        "stale-baseline",
        now=datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc),
        correction_id="a1b2c3d4",
    )
    assert item["pk"] == "USER#matthew#SOURCE#coach_corrections"
    assert item["sk"] == "CORRECTION#2026-07-22#a1b2c3d4"
    assert item["correction_id"] == "a1b2c3d4"
    assert item["error_class"] == "stale-baseline"
    assert item["status"] == "open"
    assert item["created_at"] == "2026-07-22T12:00:00+00:00"
    assert item["correction_text"].startswith("The 315 lbs baseline")
    assert item["item_ref"]["coach"] == "sleep_coach"
    assert "error_class_raw" not in item


def test_build_correction_item_generates_id_and_now_when_omitted():
    item = cc.build_correction_item({"surface": "coach_brief"}, "text", "framing")
    assert item["sk"].startswith("CORRECTION#")
    prefix_len = len(cc.SK_PREFIX)
    date_part, id_part = item["sk"][prefix_len:].split("#")
    assert len(date_part) == 10  # YYYY-MM-DD
    assert len(id_part) == 8
    assert item["correction_id"] == id_part


@pytest.mark.parametrize("error_class", list(cc.ERROR_CLASSES))
def test_all_known_error_classes_pass_through_unchanged(error_class):
    item = cc.build_correction_item({}, "x", error_class)
    assert item["error_class"] == error_class
    assert "error_class_raw" not in item


def test_unknown_error_class_normalizes_to_other_without_dropping_it():
    item = cc.build_correction_item({}, "x", "some-brand-new-class-nobody-registered")
    assert item["error_class"] == "other"
    assert item["error_class_raw"] == "some-brand-new-class-nobody-registered"


def test_item_ref_numeric_fields_cast_to_decimal():
    item = cc.build_correction_item({"pack_number": 3.0, "confidence": 0.82}, "x", "checkable-metric")
    assert isinstance(item["item_ref"]["pack_number"], Decimal)
    assert isinstance(item["item_ref"]["confidence"], Decimal)
    assert item["item_ref"]["pack_number"] == Decimal("3.0")
    # No bare float ever reaches DDB attribute level
    assert not any(isinstance(v, float) for v in item["item_ref"].values())


def test_item_ref_none_becomes_empty_dict():
    item = cc.build_correction_item(None, "x", "other")
    assert item["item_ref"] == {}


# ── #1791: cycle stamp on write ──────────────────────────────────────────────
def test_build_correction_item_stores_cycle_when_given():
    item = cc.build_correction_item({}, "x", "other", cycle=10)
    assert item["cycle"] == 10


def test_build_correction_item_omits_cycle_when_not_given():
    # Honest-absent, not a fabricated 0/None literal — matches the pre-#1791 shape.
    item = cc.build_correction_item({}, "x", "other")
    assert "cycle" not in item


def test_write_correction_passes_cycle_through(table):
    sk = cc.write_correction(table, {}, "x", "other", cycle=11)
    got = cc.get_correction(table, sk)
    assert got["cycle"] == 11


def test_error_classes_tuple_has_other_fallback():
    assert "other" in cc.ERROR_CLASSES
    assert cc.ERROR_CLASSES == (
        "stale-baseline",
        "ungrounded-behavioral",
        "cross-coach-inconsistency",
        "framing",
        "checkable-metric",
        "hedged-safe",
        "defense-held",
        "other",
    )


# ── write_correction: mockable table ────────────────────────────────────────
def test_write_correction_puts_and_returns_sk(table):
    sk = cc.write_correction(
        table,
        {"surface": "coach_brief", "coach": "mind_coach"},
        "You didn't log an eating window today; I can't ground that claim.",
        "ungrounded-behavioral",
    )
    assert sk.startswith("CORRECTION#")
    assert len(table.puts) == 1
    assert table.puts[0]["sk"] == sk
    assert table.puts[0]["error_class"] == "ungrounded-behavioral"


def test_write_correction_raises_on_ddb_error():
    def _fail(*_a, **_kw):
        raise RuntimeError("simulated DDB outage")

    failing_table = FakeDdbTable(put_item_hook=_fail)
    with pytest.raises(RuntimeError):
        cc.write_correction(failing_table, {}, "x", "framing")


# ── get_correction / list_corrections / update_status ──────────────────────
def test_get_correction_round_trip(table):
    sk = cc.write_correction(table, {"surface": "x"}, "text", "framing")
    got = cc.get_correction(table, sk)
    assert got is not None
    assert got["sk"] == sk
    assert got["correction_text"] == "text"


def test_get_correction_missing_returns_none(table):
    assert cc.get_correction(table, "CORRECTION#2026-01-01#deadbeef") is None


def test_list_corrections_filters_by_status_and_error_class():
    rows = [
        cc.build_correction_item({}, "a", "stale-baseline", correction_id="aaaaaaaa"),
        cc.build_correction_item({}, "b", "framing", correction_id="bbbbbbbb"),
        {**cc.build_correction_item({}, "c", "stale-baseline", correction_id="cccccccc"), "status": "applied-to-gate"},
    ]
    t = FakeDdbTable(rows=rows)
    all_rows = cc.list_corrections(t)
    assert len(all_rows) == 3

    stale = cc.list_corrections(t, error_class="stale-baseline")
    assert {r["correction_id"] for r in stale} == {"aaaaaaaa", "cccccccc"}

    open_only = cc.list_corrections(t, status="open")
    assert {r["correction_id"] for r in open_only} == {"aaaaaaaa", "bbbbbbbb"}

    open_stale = cc.list_corrections(t, status="open", error_class="stale-baseline")
    assert [r["correction_id"] for r in open_stale] == ["aaaaaaaa"]


def test_list_corrections_respects_limit():
    rows = [cc.build_correction_item({}, str(i), "other", correction_id=f"{i:08d}") for i in range(5)]
    t = FakeDdbTable(rows=rows)
    assert len(cc.list_corrections(t, limit=2)) == 2
    assert len(cc.list_corrections(t, limit=100)) == 5


def test_list_corrections_queries_the_partition_key():
    t = FakeDdbTable(rows=[])
    cc.list_corrections(t)
    assert len(t.query_calls) == 1


def test_list_corrections_paginates_beyond_one_page():
    # #1796: a single unpaginated Query page used to silently cap the ledger —
    # once the partition outgrew one page, the OLDEST corrections (queried
    # newest-first) were simply never seen, including retractions whose
    # subjects would then reappear on the public dossier with no signal.
    page1 = [cc.build_correction_item({}, "newer", "other", correction_id=f"{i:08d}") for i in range(3)]
    page2 = [cc.build_correction_item({}, "older", "other", correction_id=f"{i:08d}") for i in range(3, 6)]

    def _hook(table, **kw):
        if "ExclusiveStartKey" not in kw:
            return {"Items": page1, "LastEvaluatedKey": {"sk": "cursor"}}
        return {"Items": page2}

    t = FakeDdbTable(query_hook=_hook)
    got = cc.list_corrections(t, limit=100)
    assert len(got) == 6
    assert {i["correction_text"] for i in got} == {"newer", "older"}


def test_list_corrections_stops_paginating_once_limit_reached():
    calls = []

    def _hook(table, **kw):
        calls.append(kw)
        idx = len(calls)
        return {
            "Items": [cc.build_correction_item({}, f"page{idx}", "other", correction_id=f"{idx:08d}")],
            "LastEvaluatedKey": {"sk": f"cursor{idx}"},
        }

    t = FakeDdbTable(query_hook=_hook)
    got = cc.list_corrections(t, limit=1)
    assert len(got) == 1
    assert len(calls) == 1  # stopped after the first page — never fetched one it didn't need


def test_update_status_writes_expected_expression(table):
    sk = cc.write_correction(table, {}, "x", "framing")
    assert cc.update_status(table, sk, "applied-to-prompt") is True
    assert len(table.updates) == 1
    call = table.updates[0]
    assert call["Key"] == {"pk": cc.PK, "sk": sk}
    assert call["ExpressionAttributeValues"][":s"] == "applied-to-prompt"


def test_update_status_rejects_unknown_status(table):
    sk = cc.write_correction(table, {}, "x", "framing")
    with pytest.raises(ValueError):
        cc.update_status(table, sk, "resolved-forever")
    assert len(table.updates) == 0


@pytest.mark.parametrize("status", list(cc.STATUSES))
def test_all_known_statuses_accepted(table, status):
    sk = cc.write_correction(table, {}, "x", "framing")
    assert cc.update_status(table, sk, status) is True


# ── S5 (#1697): prompt-memory injection — read/scope/render/bound ────────────
def _corr(cid, *, coach, surface="coach_brief", cls="stale-baseline", text="t", status="open", date="2026-07-22"):
    """Build one persisted-shape correction row for the S5 read tests."""
    return cc.build_correction_item(
        {"surface": surface, "coach": coach},
        text,
        cls,
        now=datetime.fromisoformat(f"{date}T12:00:00+00:00"),
        correction_id=cid,
    ) | {"status": status}


def test_open_corrections_for_scopes_to_the_requested_coach():
    # Each coach must see ONLY its own corrections — never the global list.
    rows = [
        _corr("aaaaaaaa", coach="metabolic_coach", text="315 lbs is stale — baseline is 321.4"),
        _corr("bbbbbbbb", coach="sleep_coach", text="don't cite 8h as a streak"),
    ]
    t = FakeDdbTable(rows=rows)
    metab = cc.open_corrections_for(t, surface="coach_brief", coach="metabolic_coach")
    assert [c["correction_id"] for c in metab] == ["aaaaaaaa"]
    sleep = cc.open_corrections_for(t, surface="coach_brief", coach="sleep_coach")
    assert [c["correction_id"] for c in sleep] == ["bbbbbbbb"]
    # A coach with no corrections gets an empty list (→ empty block, no injection).
    assert cc.open_corrections_for(t, surface="coach_brief", coach="mind_coach") == []


def test_open_corrections_for_excludes_non_open_status():
    rows = [
        _corr("aaaaaaaa", coach="metabolic_coach", status="open"),
        _corr("bbbbbbbb", coach="metabolic_coach", status="applied-to-gate"),
    ]
    t = FakeDdbTable(rows=rows)
    got = cc.open_corrections_for(t, surface="coach_brief", coach="metabolic_coach")
    assert [c["correction_id"] for c in got] == ["aaaaaaaa"]


def test_open_corrections_for_is_newest_first_and_bounded():
    # Rolling bounded window: newest-first, capped at `limit` (no unbounded re-injection).
    rows = [_corr(f"{i:08d}", coach="metabolic_coach", date=f"2026-07-{10 + i:02d}", text=f"correction {i}") for i in range(6)]
    t = FakeDdbTable(rows=rows)
    got = cc.open_corrections_for(t, surface="coach_brief", coach="metabolic_coach", limit=3)
    assert len(got) == 3
    # Newest date (2026-07-15, i=5) first; oldest of the window (2026-07-13, i=3) last.
    assert [c["correction_id"] for c in got] == ["00000005", "00000004", "00000003"]


def test_render_corrections_block_empty_is_empty_string():
    assert cc.render_corrections_block([]) == ""


def test_render_corrections_block_tags_class_and_lists_text():
    block = cc.render_corrections_block(
        [
            {"error_class": "stale-baseline", "correction_text": "315 lbs is stale — baseline is 321.4"},
            {"error_class": "ungrounded-behavioral", "correction_text": "you didn't 'maintain your window'"},
        ]
    )
    assert "DO NOT REPEAT" in block
    assert "[stale-baseline] 315 lbs is stale" in block
    assert "[ungrounded-behavioral]" in block


# ── #1791: date/cycle provenance stamp + reset-awareness ────────────────────
def test_render_corrections_block_stamps_date_and_cycle():
    row = cc.build_correction_item(
        {}, "the baseline is stale", "stale-baseline", now=datetime(2026, 7, 22, 12, tzinfo=timezone.utc), cycle=10
    )
    block = cc.render_corrections_block([row])
    assert "(logged 2026-07-22, cycle 10)" in block
    assert "the baseline is stale" in block


def test_render_corrections_block_omits_stamp_pieces_it_does_not_have():
    # No created_at, no cycle -> no parenthetical at all (never fabricated).
    block = cc.render_corrections_block([{"error_class": "other", "correction_text": "x"}])
    assert "(" not in block.split("\n")[1]  # the rendered row, not the header


def _row_line(block):
    """The rendered correction line (not the explanatory header) — line 1."""
    return block.split("\n")[1]


def test_render_corrections_block_flags_prior_cycle_when_superseded():
    row = cc.build_correction_item({}, "baseline is 315 lbs", "stale-baseline", now=datetime(2026, 7, 20, tzinfo=timezone.utc), cycle=10)
    stale = cc.render_corrections_block([row], current_cycle=11)
    assert "PRIOR CYCLE" in _row_line(stale)
    assert "re-verify" in _row_line(stale).lower()

    # Same row, but the current cycle HASN'T moved on from it -> no flag on the row.
    current = cc.render_corrections_block([row], current_cycle=10)
    assert "PRIOR CYCLE" not in _row_line(current)


def test_render_corrections_block_never_flags_when_cycle_unknown():
    # A row with no cycle stamp (pre-#1791, or an SSM-unreachable write) is never
    # flagged stale — absence of provenance isn't evidence of staleness.
    row = cc.build_correction_item({}, "x", "other", now=datetime(2026, 7, 20, tzinfo=timezone.utc))
    assert "PRIOR CYCLE" not in _row_line(cc.render_corrections_block([row], current_cycle=11))


def test_corrections_prompt_block_passes_current_cycle_through_to_render(table):
    sk = cc.write_correction(table, {"surface": "coach_brief"}, "315 lbs is stale", "stale-baseline", cycle=9)
    got = cc.get_correction(table, sk)
    got["status"] = "open"
    t2 = FakeDdbTable(rows=[got])
    block = cc.corrections_prompt_block(t2, surface="coach_brief", current_cycle=11)
    assert "PRIOR CYCLE" in _row_line(block)
    assert "cycle 9" in _row_line(block)


# ── #1791: the review-on-reset primitive ─────────────────────────────────────
def test_stale_cycle_corrections_flags_only_older_cycles():
    rows = [
        cc.build_correction_item({}, "old", "other", correction_id="aaaaaaaa", cycle=9),
        cc.build_correction_item({}, "current", "other", correction_id="bbbbbbbb", cycle=11),
        cc.build_correction_item({}, "no-cycle", "other", correction_id="cccccccc"),
    ]
    stale = cc.stale_cycle_corrections(rows, current_cycle=11)
    assert [r["correction_id"] for r in stale] == ["aaaaaaaa"]


def test_stale_cycle_corrections_empty_when_current_cycle_unknown():
    rows = [cc.build_correction_item({}, "x", "other", cycle=9)]
    assert cc.stale_cycle_corrections(rows, current_cycle=None) == []


def test_corrections_prompt_block_end_to_end_scopes_and_renders():
    rows = [
        _corr("aaaaaaaa", coach="metabolic_coach", text="315 lbs is stale — baseline is 321.4"),
        _corr("bbbbbbbb", coach="sleep_coach", text="sleep-only correction"),
    ]
    t = FakeDdbTable(rows=rows)
    metab = cc.corrections_prompt_block(t, surface="coach_brief", coach="metabolic_coach")
    assert "315 lbs is stale" in metab
    assert "sleep-only correction" not in metab  # scoped — no cross-coach leak
    # A coach with no open corrections → empty string (nothing injected).
    assert cc.corrections_prompt_block(t, surface="coach_brief", coach="mind_coach") == ""


def test_open_corrections_for_does_not_transition_status():
    # Reading for injection must NOT flip open → applied-to-prompt (rolling window).
    rows = [_corr("aaaaaaaa", coach="metabolic_coach")]
    t = FakeDdbTable(rows=rows)
    cc.open_corrections_for(t, surface="coach_brief", coach="metabolic_coach")
    assert t.updates == []  # no status write happened on read
