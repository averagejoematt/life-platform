"""tests/test_correction_promotion.py — S6 pattern-extraction → gate-promotion
PROPOSALS (#1698, epic #1687 Path 3).

Covers lambdas/correction_promotion.py + the review-pack surface
(lambdas/emails/ai_review_pack_lambda.py::_promotion_section):

  AC1 — a ledger with a recurring class produces a promotion proposal; a
        one-off correction does NOT (and a single-coach recurrence does not —
        the cross-coach spread is part of the threshold).
  AC2 — proposals appear in the review pack with class + recurrence count +
        example refs (and the explicit proposal-only governance note).
  AC3 — NO auto-promotion: the analysis path is strictly read-only (no puts /
        updates / deletes against the table, ledger statuses untouched) and a
        source scan pins that no write call exists in the module at all.

Plus the determinism details the issue locked: exact error_class clustering,
normalized item_ref dedupe (re-logging the same correction counts once),
"other" sub-clustered by its raw label, non-promotable classes, and the
status filter (applied-to-prompt counts, applied-to-gate does not).

Run:  python3 -m pytest tests/test_correction_promotion.py -v
"""

import inspect
import os
import sys
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "lambdas"))
sys.path.insert(0, os.path.join(REPO, "lambdas", "emails"))
sys.path.insert(0, HERE)

import ai_review_pack_lambda as arp  # noqa: E402
import coach_corrections as cc  # noqa: E402
import correction_promotion as cp  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402


def _correction(error_class, coach, *, ref_extra=None, status="open", day=20, cid="00000000", surface="coach_brief"):
    """One deterministic ledger row (built via the real #1689 builder)."""
    ref = {"surface": surface, "coach": coach}
    if ref_extra:
        ref.update(ref_extra)
    item = cc.build_correction_item(
        ref,
        f"corrected a {error_class} error by {coach}",
        error_class,
        now=datetime(2026, 7, day, 12, 0, 0, tzinfo=timezone.utc),
        correction_id=cid,
    )
    if status != "open":
        item["status"] = status
    return item


# ── AC1: recurrence proposes; one-offs (and single-coach runs) do not ─────────


def test_recurring_class_across_coaches_produces_a_proposal():
    rows = [
        _correction("stale-baseline", "nutrition", ref_extra={"date": "2026-07-18"}, day=18, cid="aaaa0001"),
        _correction("stale-baseline", "strength", ref_extra={"date": "2026-07-19"}, day=19, cid="aaaa0002"),
        _correction("stale-baseline", "nutrition", ref_extra={"date": "2026-07-20"}, day=20, cid="aaaa0003"),
    ]
    proposals = cp.promotion_proposals(rows)
    assert len(proposals) == 1
    p = proposals[0]
    assert p["error_class"] == "stale-baseline"
    assert p["recurrence"] == 3
    assert p["coach_count"] == 2
    assert p["coaches"] == ["nutrition", "strength"]
    # example refs are real ledger sks, newest-first, bounded
    assert len(p["example_refs"]) == 3
    assert all(r.startswith("CORRECTION#2026-07-") for r in p["example_refs"])
    assert p["example_refs"][0].startswith("CORRECTION#2026-07-20")
    assert "candidate for a hard deterministic gate" in p["statement"]
    assert "recurred 3 times across 2 coaches" in p["statement"]


def test_one_off_correction_does_not_propose():
    rows = [_correction("checkable-metric", "nutrition", cid="bbbb0001")]
    assert cp.promotion_proposals(rows) == []


def test_below_threshold_recurrence_does_not_propose():
    rows = [
        _correction("framing", "nutrition", ref_extra={"date": "2026-07-19"}, day=19, cid="cccc0001"),
        _correction("framing", "strength", ref_extra={"date": "2026-07-20"}, day=20, cid="cccc0002"),
    ]
    assert cp.promotion_proposals(rows) == []


def test_single_coach_recurrence_does_not_propose():
    # 3 recurrences but ONE coach — prompt-memory's job, not a gate's (min_coaches=2).
    rows = [
        _correction("framing", "nutrition", ref_extra={"date": f"2026-07-{d}"}, day=d, cid=f"dddd000{i}")
        for i, d in enumerate((18, 19, 20), start=1)
    ]
    assert cp.promotion_proposals(rows) == []


# ── clustering determinism details ────────────────────────────────────────────


def test_duplicate_item_ref_counts_once():
    # The same corrected item logged 3 times (case/whitespace variants) + one other
    # distinct item = recurrence 2, below threshold → no proposal.
    same = {"date": "2026-07-19", "pack_number": 4}
    rows = [
        _correction("stale-baseline", "nutrition", ref_extra=same, day=19, cid="eeee0001"),
        _correction("stale-baseline", "Nutrition ", ref_extra={"date": "2026-07-19", "pack_number": 4}, day=19, cid="eeee0002"),
        _correction("stale-baseline", "NUTRITION", ref_extra=dict(same), day=20, cid="eeee0003"),
        _correction("stale-baseline", "strength", ref_extra={"date": "2026-07-20"}, day=20, cid="eeee0004"),
    ]
    clusters = cp.cluster_corrections(rows)
    assert clusters["stale-baseline"]["recurrence"] == 2
    assert cp.promotion_proposals(rows) == []


def test_normalize_item_ref_is_case_whitespace_and_order_insensitive():
    a = cp.normalize_item_ref({"surface": "coach_brief", "coach": " Nutrition "})
    b = cp.normalize_item_ref({"coach": "nutrition", "surface": "COACH_BRIEF"})
    assert a == b != ()
    assert cp.normalize_item_ref(None) == ()
    assert cp.normalize_item_ref({}) == ()
    assert cp.normalize_item_ref({"coach": None, "surface": "  "}) == ()


def test_refless_corrections_count_separately_but_share_one_coach_bucket():
    # Distinct ref-less corrections each count (sk fallback) — but they all fall in
    # the single "(unspecified)" coach bucket, so alone they can never propose.
    rows = [
        cc.build_correction_item(None, f"c{i}", "framing", now=datetime(2026, 7, 15 + i, tzinfo=timezone.utc), correction_id=f"ffff000{i}")
        for i in range(1, 5)
    ]
    clusters = cp.cluster_corrections(rows)
    assert clusters["framing"]["recurrence"] == 4
    assert clusters["framing"]["coaches"] == [cp.UNSPECIFIED_COACH]
    assert cp.promotion_proposals(rows) == []


def test_non_promotable_classes_never_propose():
    rows = [
        _correction(cls, coach, ref_extra={"date": f"2026-07-{d}"}, day=d, cid=f"abab00{d}{i}")
        for cls in ("hedged-safe", "defense-held")
        for i, (coach, d) in enumerate([("nutrition", 18), ("strength", 19), ("recovery", 20)], start=1)
    ]
    assert cp.promotion_proposals(rows) == []


def test_status_filter_prompt_applied_counts_gate_applied_does_not():
    base = [
        _correction("stale-baseline", "nutrition", ref_extra={"date": "2026-07-18"}, day=18, cid="baba0001"),
        _correction("stale-baseline", "strength", ref_extra={"date": "2026-07-19"}, day=19, cid="baba0002"),
    ]
    third_prompt = _correction(
        "stale-baseline", "nutrition", ref_extra={"date": "2026-07-20"}, day=20, cid="baba0003", status="applied-to-prompt"
    )
    third_gate = _correction(
        "stale-baseline", "nutrition", ref_extra={"date": "2026-07-20"}, day=20, cid="baba0004", status="applied-to-gate"
    )
    assert len(cp.promotion_proposals(base + [third_prompt])) == 1  # graduation is FROM prompt-memory
    assert cp.promotion_proposals(base + [third_gate]) == []  # already gated — excluded


def test_other_subclusters_by_raw_label():
    # Recurring UNRECOGNIZED class surfaces under its raw label; unrelated free-form
    # "other" corrections never lump into one false cluster.
    rows = [
        _correction("sarcasm", "nutrition", ref_extra={"date": "2026-07-18"}, day=18, cid="caca0001"),
        _correction("sarcasm", "strength", ref_extra={"date": "2026-07-19"}, day=19, cid="caca0002"),
        _correction("sarcasm", "nutrition", ref_extra={"date": "2026-07-20"}, day=20, cid="caca0003"),
        _correction("something-else", "recovery", ref_extra={"date": "2026-07-20"}, day=20, cid="caca0004"),
    ]
    # the #1689 builder normalizes unknown classes to "other" + error_class_raw
    assert all(r["error_class"] == "other" for r in rows)
    proposals = cp.promotion_proposals(rows)
    assert len(proposals) == 1
    assert proposals[0]["error_class"] == "other:sarcasm"
    assert proposals[0]["recurrence"] == 3


# ── AC3: no auto-promotion — strictly read-only ───────────────────────────────


def test_gate_promotion_proposals_reads_ledger_and_never_writes():
    rows = [
        _correction("stale-baseline", "nutrition", ref_extra={"date": "2026-07-18"}, day=18, cid="dada0001"),
        _correction("stale-baseline", "strength", ref_extra={"date": "2026-07-19"}, day=19, cid="dada0002"),
        _correction("stale-baseline", "recovery", ref_extra={"date": "2026-07-20"}, day=20, cid="dada0003"),
    ]
    table = FakeDdbTable(rows=rows)
    proposals = cp.gate_promotion_proposals(table)
    assert len(proposals) == 1 and proposals[0]["recurrence"] == 3
    # READ-ONLY: the ledger was queried, never mutated — no gate can flip on.
    assert table.query_calls, "expected the ledger to be read via query"
    assert table.puts == []
    assert table.updates == []
    assert table.deletes == []
    # and every correction's status is exactly as seeded (still "open")
    assert all(item["status"] == "open" for item in table.store.values())


def test_module_has_no_write_path_at_all():
    # The structural half of "no auto-promotion": no write CALL of any kind exists in
    # the module's code — not put_item/update_item/delete_item, not the ledger's own
    # update_status transition, not a batch writer. AST-walked (attribute/name
    # references in code, so the docstring explaining the guarantee doesn't trip it).
    import ast

    tree = ast.parse(inspect.getsource(cp))
    write_tokens = {"put_item", "update_item", "delete_item", "update_status", "batch_writer", "put_parameter"}
    referenced = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    referenced |= {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    offending = referenced & write_tokens
    assert not offending, f"correction_promotion must be read-only but references {sorted(offending)}"


# ── AC2: proposals surface in the weekly review pack ──────────────────────────


def _proposal():
    return {
        "error_class": "stale-baseline",
        "recurrence": 3,
        "coaches": ["nutrition", "strength"],
        "coach_count": 2,
        "example_refs": ["CORRECTION#2026-07-20#dada0003", "CORRECTION#2026-07-19#dada0002"],
        "statement": "class `stale-baseline` recurred 3 times across 2 coaches → candidate for a hard deterministic gate",
    }


def test_review_pack_renders_proposal_with_class_count_and_refs():
    dates = arp.week_dates(end=date(2026, 7, 20))
    html = arp.build_html(dates, {}, {}, read_errors=0, proposals=[_proposal()])
    assert "Gate-promotion proposals" in html
    assert "stale-baseline" in html  # the class chip
    assert "recurred 3&times; across 2 coaches" in html  # the recurrence count
    assert "CORRECTION#2026-07-20#dada0003" in html  # example refs
    assert "CORRECTION#2026-07-19#dada0002" in html
    # the governance note: proposal only, human authors the gate (ADR-104/105)
    assert "Proposal only" in html
    assert "human-authored gate PR" in html


def test_review_pack_omits_section_when_no_proposals():
    dates = arp.week_dates(end=date(2026, 7, 20))
    for proposals in (None, []):
        html = arp.build_html(dates, {}, {}, read_errors=0, proposals=proposals)
        assert "Gate-promotion proposals" not in html


def test_review_pack_wiring_computes_proposals_read_only():
    # compute_promotion_proposals goes ledger → proposals through the REAL bundled
    # module, and stays read-only end-to-end (the review-pack path can't flip a gate).
    rows = [
        _correction("stale-baseline", "nutrition", ref_extra={"date": "2026-07-18"}, day=18, cid="fafa0001"),
        _correction("stale-baseline", "strength", ref_extra={"date": "2026-07-19"}, day=19, cid="fafa0002"),
        _correction("stale-baseline", "recovery", ref_extra={"date": "2026-07-20"}, day=20, cid="fafa0003"),
    ]
    table = FakeDdbTable(rows=rows)
    proposals = arp.compute_promotion_proposals(table)
    assert proposals is not None and len(proposals) == 1
    assert proposals[0]["error_class"] == "stale-baseline"
    assert table.puts == [] and table.updates == [] and table.deletes == []
    # and the rendered pack carries the section
    html = arp.build_html(arp.week_dates(end=date(2026, 7, 20)), {}, {}, read_errors=0, proposals=proposals)
    assert "Gate-promotion proposals" in html


def test_thresholds_are_the_documented_named_constants():
    # The issue-locked defaults: recurred ≥3 times across ≥2 coaches, ≤3 example refs.
    assert cp.PROMOTION_MIN_RECURRENCE == 3
    assert cp.PROMOTION_MIN_COACHES == 2
    assert cp.MAX_EXAMPLE_REFS == 3
    assert set(cp.NON_PROMOTABLE_CLASSES) == {"hedged-safe", "defense-held"}
    assert set(cp.COUNTED_STATUSES) == {"open", "applied-to-prompt"}
    # every named class constant is a real ledger vocabulary member (#1689)
    assert set(cp.NON_PROMOTABLE_CLASSES) <= set(cc.ERROR_CLASSES)
    assert set(cp.COUNTED_STATUSES) <= set(cc.STATUSES)
