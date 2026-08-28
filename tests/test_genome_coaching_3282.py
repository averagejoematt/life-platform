"""#3282 — the genome coach must decide from the STORED record, not from gene presence.

The defect this pins: selection gated on `if gene_key in snps` (presence of a gene,
which every human has) and then took the first coaching string an `or`-chain happened to
find. Nothing read the row's own risk label, one arm of a two-arm entry was unreachable,
and a row carrying a non-actionable label still produced a "variant detected" line.

PRIVACY (#1943 — genome identifiers are Tier 2 owner-only, this repo is public). Every
fixture below uses INVENTED placeholder gene keys and INVENTED field values. No real
gene, identifier, genotype, label reading or interpretation text appears here, and none
may be added. Wire fidelity is asserted structurally instead: `test_h` derives the
record's field set from `docs/SCHEMA.md` and checks the fixture carries exactly it, so
the fixture is provably the production SHAPE without carrying production CONTENT.
"""

import re
from pathlib import Path

import pytest
from health import genome_coaching as gc

_REPO = Path(__file__).resolve().parent.parent

# Invented placeholder gene keys — deliberately not any real symbol.
_PAIR_GENE = "PLACEHOLDERPAIR1"
_SINGLE_GENE = "PLACEHOLDERSINGLE1"
_SECOND_GENE = "PLACEHOLDERSINGLE2"
_THIRD_GENE = "PLACEHOLDERSINGLE3"
_PAGE_TWO_GENE = "PLACEHOLDERPAGETWO1"


def _record(gene, risk_level):
    """A stored row in the PRODUCTION SHAPE (docs/SCHEMA.md genome SNP fields) with
    entirely invented content. `test_h` proves the shape claim against the schema."""
    return {
        "pk": "USER#placeholder#SOURCE#genome",
        "sk": f"GENE#{gene}#SNP#placeholder-identifier",
        "gene": gene,
        "rsid": "placeholder-identifier",
        "genotype": "PLACEHOLDER-GENOTYPE",
        "summary": "placeholder interpretation line",
        "category": "miscellaneous",
        "risk_level": risk_level,
        "details": "placeholder extended interpretation",
        "actionable_recs": ["placeholder recommendation"],
        "related_biomarkers": ["placeholder_biomarker"],
        "report_date": "2020-01-01",
        "report_type": "comprehensive_snp_interpretation",
    }


def _pair_entry():
    """A catalog entry with a complementary pair of arms — the shape whose second arm
    was dead code before #3282."""
    return {
        "gene": _PAIR_GENE,
        "focus": "placeholder",
        "arms": [
            {"key": "slow_variant_coaching", "risk_levels": ("unfavorable", "mixed"), "coaching": "CAUTIONARY ARM TEXT"},
            {"key": "fast_variant_coaching", "risk_levels": ("favorable",), "coaching": "TOLERANT ARM TEXT"},
        ],
    }


def _single_entry(gene, text):
    return {
        "gene": gene,
        "focus": "placeholder",
        "arms": [{"key": "variant_coaching", "risk_levels": ("unfavorable", "mixed"), "coaching": text}],
    }


class _StubTable:
    """A table whose `query` replays a fixed list of pages, recording the kwargs it was
    called with. Page N+1 is only reachable by following LastEvaluatedKey."""

    def __init__(self, pages):
        self._pages = pages
        self.calls = []

    def query(self, **kwargs):
        self.calls.append(kwargs)
        start = kwargs.get("ExclusiveStartKey")
        idx = 0 if start is None else start["_page"]
        page = self._pages[idx]
        resp = {"Items": page}
        if idx + 1 < len(self._pages):
            resp["LastEvaluatedKey"] = {"_page": idx + 1}
        return resp


def _build(monkeypatch, catalog, pages, week=1):
    monkeypatch.setattr(gc, "GENOME_INSIGHTS", catalog)
    monkeypatch.setattr(gc, "pacific_now", lambda: _FakeNow(week))
    table = _StubTable(pages)
    return table, gc.build_genome_coaching_context(table, "USER#placeholder#SOURCE#")


class _FakeNow:
    def __init__(self, week):
        self._week = week

    def isocalendar(self):
        return (2026, self._week, 1)


# ── A. presence is not a phenotype ───────────────────────────────────────────────


def test_a_a_present_gene_with_no_actionable_label_emits_nothing(monkeypatch):
    """The row EXISTS and every field is populated — the old code emitted a variant line
    on exactly this input. ADR-104: absence of an actionable finding is an answer."""
    catalog = [_single_entry(_SINGLE_GENE, "SHOULD NOT BE EMITTED")]
    _, out = _build(monkeypatch, catalog, [[_record(_SINGLE_GENE, "neutral")]])
    assert out == "", "a non-actionable stored label must emit nothing, not a variant line"

    _, out = _build(monkeypatch, catalog, [[_record(_SINGLE_GENE, "favorable")]])
    assert out == "", "a favorable stored label must not produce a 'risk variant' assertion"


def test_a_b_an_actionable_label_does_emit(monkeypatch):
    """The positive control for test_a_a — the silence above is a decision, not a
    selector that never fires."""
    catalog = [_single_entry(_SINGLE_GENE, "ACTIONABLE ARM TEXT")]
    for label in ("unfavorable", "mixed"):
        _, out = _build(monkeypatch, catalog, [[_record(_SINGLE_GENE, label)]])
        assert "ACTIONABLE ARM TEXT" in out, f"an actionable stored label ({label}) must emit its arm"


def test_a_c_a_row_with_no_label_at_all_emits_nothing(monkeypatch):
    catalog = [_single_entry(_SINGLE_GENE, "SHOULD NOT BE EMITTED")]
    row = _record(_SINGLE_GENE, "unfavorable")
    row.pop("risk_level")
    _, out = _build(monkeypatch, catalog, [[row]])
    assert out == "", "an unlabelled row is not evidence of a variant"


# ── B. both arms of a pair are selectable — the or-chain must-fail ───────────────


def test_b_each_arm_of_a_pair_is_selected_by_its_own_stored_label():
    """One fixture per arm. Restoring the `or`-order fallback chain — 'take the first
    coaching string defined on the entry' — reds the second assertion, because that
    chain cannot reach the second arm for any input whatsoever."""
    entry = _pair_entry()
    assert gc.select_coaching_arm(entry, [_record(_PAIR_GENE, "unfavorable")]) == "CAUTIONARY ARM TEXT"
    assert gc.select_coaching_arm(entry, [_record(_PAIR_GENE, "favorable")]) == "TOLERANT ARM TEXT"
    assert gc.select_coaching_arm(entry, [_record(_PAIR_GENE, "neutral")]) == ""


def test_b_b_the_pair_resolves_end_to_end_through_the_public_entrypoint(monkeypatch):
    """The same contract through the real query/rotate/render path, not just the helper —
    a selector that is right in isolation and unwired is the #2703 shape."""
    _, out = _build(monkeypatch, [_pair_entry()], [[_record(_PAIR_GENE, "favorable")]])
    assert "TOLERANT ARM TEXT" in out and "CAUTIONARY ARM TEXT" not in out


# ── C. no arm the catalog defines may be unreachable ─────────────────────────────


def test_c_every_arm_in_the_shipped_catalog_is_reachable():
    """Adding a new `*_coaching` arm that no stored label can select must red the build
    rather than silently narrowing the rotation. Checked against the REAL catalog."""
    seen_keys = 0
    for entry in gc.GENOME_INSIGHTS:
        arms = entry.get("arms")
        assert arms, "every catalog entry must declare at least one arm"
        claimed = set()
        for arm in arms:
            key = arm.get("key", "")
            assert key.endswith("_coaching"), "an arm's key names the coaching it selects"
            assert arm.get("coaching"), f"arm {key} must carry text"
            labels = set(arm.get("risk_levels") or ())
            assert labels, f"arm {key} declares no selecting label — it is dead on arrival"
            assert labels <= set(gc.STORED_RISK_LABELS), f"arm {key} names a label the schema does not define"
            assert not (labels & claimed), f"arm {key} is shadowed by an earlier arm — unreachable"
            claimed |= labels
            seen_keys += 1
            # Reachability is DEMONSTRATED, not argued: drive the selector.
            for label in sorted(labels):
                got = gc.select_coaching_arm(entry, [_record("PLACEHOLDERGENE", label)])
                assert got == arm["coaching"], f"arm {key} is not selectable by its own declared label {label}"
    assert seen_keys >= len(gc.GENOME_INSIGHTS), "every entry contributes at least one arm to the check"


def test_c_b_a_dead_arm_is_detected(monkeypatch):
    """The negative control for test_c: an arm whose labels are entirely claimed by an
    earlier arm is unreachable, and the reachability check must say so."""
    entry = {
        "gene": _PAIR_GENE,
        "focus": "placeholder",
        "arms": [
            {"key": "variant_coaching", "risk_levels": ("unfavorable", "mixed", "favorable"), "coaching": "FIRST"},
            {"key": "second_variant_coaching", "risk_levels": ("favorable",), "coaching": "SHADOWED"},
        ],
    }
    monkeypatch.setattr(gc, "GENOME_INSIGHTS", [entry])
    with pytest.raises(AssertionError, match="shadowed"):
        test_c_every_arm_in_the_shipped_catalog_is_reachable()


# ── D. several rows for one gene resolve deterministically ───────────────────────


def test_d_rows_on_both_sides_resolve_by_declaration_order_not_row_order():
    """A gene can carry several stored rows and they need not agree. The old lookup kept
    whichever row the query returned LAST, so the emitted arm depended on sort-key order.
    Declaration order decides now, and the cautionary arm is declared first."""
    entry = _pair_entry()
    rows = [_record(_PAIR_GENE, "favorable"), _record(_PAIR_GENE, "unfavorable")]
    assert gc.select_coaching_arm(entry, rows) == "CAUTIONARY ARM TEXT"
    assert gc.select_coaching_arm(entry, list(reversed(rows))) == "CAUTIONARY ARM TEXT"


# ── E. the query pages to exhaustion ─────────────────────────────────────────────


def test_e_a_gene_on_the_second_page_is_visible_to_the_coach(monkeypatch):
    """The production query truncated at a page boundary and dropped the LastEvaluatedKey
    on the floor, so genes past page one were invisible for a paging reason rather than a
    biological one. Reverting to a single un-followed query reds this."""
    catalog = [_single_entry(_PAGE_TWO_GENE, "PAGE TWO ARM TEXT")]
    table, out = _build(
        monkeypatch,
        catalog,
        [[_record(_SINGLE_GENE, "neutral")], [_record(_PAGE_TWO_GENE, "unfavorable")]],
    )
    assert len(table.calls) == 2, "the second page must be fetched"
    assert table.calls[1].get("ExclusiveStartKey"), "page two must be requested from the returned key"
    assert "PAGE TWO ARM TEXT" in out


def test_e_b_no_row_limit_is_imposed_on_the_query(monkeypatch):
    """`Limit` was the truncation. Its absence is part of the contract, not an accident."""
    table, _ = _build(monkeypatch, [_single_entry(_SINGLE_GENE, "T")], [[_record(_SINGLE_GENE, "unfavorable")]])
    assert all("Limit" not in call for call in table.calls), "the coach must not cap the rows it reads"


def test_e_c_paging_is_bounded(monkeypatch):
    """A LastEvaluatedKey that never clears must terminate, loudly, not spin."""

    class _Endless:
        def __init__(self):
            self.calls = 0

        def query(self, **kwargs):
            self.calls += 1
            return {"Items": [_record(_SINGLE_GENE, "unfavorable")], "LastEvaluatedKey": {"_page": 0}}

    table = _Endless()
    monkeypatch.setattr(gc, "GENOME_INSIGHTS", [_single_entry(_SINGLE_GENE, "T")])
    monkeypatch.setattr(gc, "pacific_now", lambda: _FakeNow(1))
    gc.build_genome_coaching_context(table, "USER#placeholder#SOURCE#")
    assert table.calls == gc._MAX_QUERY_PAGES


# ── F. the stated rotation number is the rendered one ────────────────────────────


def test_f_the_declared_cap_is_the_number_actually_rendered(monkeypatch):
    """The comment said 2-3 per week and the slice said 2. One number now, used twice."""
    assert gc._ROTATION_WINDOW >= gc._INSIGHTS_PER_WEEK
    catalog = [
        _single_entry(_SINGLE_GENE, "ONE"),
        _single_entry(_SECOND_GENE, "TWO"),
        _single_entry(_THIRD_GENE, "THREE"),
    ]
    rows = [_record(g, "unfavorable") for g in (_SINGLE_GENE, _SECOND_GENE, _THIRD_GENE)]
    _, out = _build(monkeypatch, catalog, [rows], week=3)
    lines = [ln for ln in out.splitlines() if ln.startswith("- ")]
    assert len(lines) == gc._INSIGHTS_PER_WEEK


def test_f_b_a_silent_slot_does_not_halve_the_week(monkeypatch):
    """The window is wider than the cap so a slot with nothing to say is skipped over
    rather than consuming one of the week's two lines."""
    catalog = [
        _single_entry(_SINGLE_GENE, "ONE"),
        _single_entry(_SECOND_GENE, "TWO"),
        _single_entry(_THIRD_GENE, "THREE"),
    ]
    rows = [
        _record(_SINGLE_GENE, "neutral"),  # silent
        _record(_SECOND_GENE, "unfavorable"),
        _record(_THIRD_GENE, "unfavorable"),
    ]
    _, out = _build(monkeypatch, catalog, [rows], week=3)
    lines = [ln for ln in out.splitlines() if ln.startswith("- ")]
    assert len(lines) == gc._INSIGHTS_PER_WEEK
    assert "ONE" not in out


# ── G. a gene with no stored row at all ──────────────────────────────────────────


def test_g_a_gene_with_no_stored_row_emits_nothing(monkeypatch):
    catalog = [_single_entry(_SECOND_GENE, "SHOULD NOT BE EMITTED")]
    _, out = _build(monkeypatch, catalog, [[_record(_SINGLE_GENE, "unfavorable")]])
    assert out == ""


# ── H. the fixture is the wire ───────────────────────────────────────────────────


def _documented_snp_fields():
    """Field names of the genome SNP record, read out of docs/SCHEMA.md's own table."""
    text = (_REPO / "docs" / "SCHEMA.md").read_text(encoding="utf-8")
    start = text.index("**SNP record fields:**")
    end = text.index("**Summary record", start)
    return {m.group(1) for m in re.finditer(r"^\|\s*`([a-z_]+)`\s*\|", text[start:end], re.MULTILINE)}


def test_h_the_fixture_carries_exactly_the_documented_record_shape():
    """Wire fidelity without wire content: the fixture's field set is checked against the
    schema doc, so a field added to (or renamed on) the real record reds this test —
    while every VALUE in the fixture stays invented (#1943)."""
    documented = _documented_snp_fields()
    assert len(documented) >= 10, "the schema table did not parse — the shape claim would be vacuous"
    fixture_fields = set(_record(_SINGLE_GENE, "unfavorable")) - {"pk", "sk"}
    assert fixture_fields == documented, f"fixture shape drifted from docs/SCHEMA.md: {fixture_fields ^ documented}"
