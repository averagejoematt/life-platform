"""tests/test_withheld_marks_and_counts_off_the_wire.py — owner rulings 2026-11-06.

1. "Remove the per-item words_withheld flag." An item whose words are withheld reads like an item with no words,
   never marked — on the API (``narrative_publication``) and on the static site built from it (``publish_snapshot``).
2. "Review withheld counts in the dossier, docket and correction surfaces; eliminate values that disclose private
   activity." (The dossier/docket/ledger-export halves are pinned beside their own suites:
   test_coach_dossier.py, test_dispute_docket_1386.py, test_correction_history_5610.py.)
3. "Remove the Notion Journal source from public data_sources.json."
4. "Replace any production-derived journal count in the render-gate fixture with synthetic data."

Every value here is synthetic.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


ps = _load("publish_snapshot_withheld_marks", ROOT / "scripts" / "publish_snapshot.py")


# ── 1. the API: no per-item marker, anywhere in the gate ────────────────────────────────────────


def test_the_gate_module_carries_no_per_item_withheld_marker():
    import ast

    from web import narrative_publication as G

    tree = ast.parse((ROOT / "lambdas/web/narrative_publication.py").read_text())
    consts = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert not hasattr(G, "WORDS_WITHHELD_KEY") and "words_withheld" not in consts
    assert not any(c.endswith("_withheld") for c in consts), "a `<key>_withheld` marker is back"


def test_a_withheld_slot_reads_exactly_like_an_empty_one():
    """Invariance: a withheld row's slot and a slot built from no words are the same bytes. Mutation control:
    a servable row's value does show."""
    from web import narrative_publication as G

    held, blank, served = {}, {}, {}
    G.withheld_slot(held, {G.PUBLICATION_KEY: {"state": "withheld", "reason": "x"}}, "position_summary", "Private words.")
    G.withheld_slot(blank, {}, "position_summary", "")
    G.withheld_slot(served, {}, "position_summary", "Deep sleep held.")
    assert held == blank == {"position_summary": ""}
    assert served == {"position_summary": "Deep sleep held."}


def test_a_moves_day_the_gate_withheld_carries_no_withheld_state():
    src = (ROOT / "lambdas/coach/coach_moves.py").read_text()
    assert '{"withheld": dict(item["_publication"])}' not in src and "out_withheld" not in src


# ── 1b. the static site: every row without words reads the same ─────────────────────────────────


def _ledger(rows, monkeypatch):
    def fake_get(base, path, timeout):
        assert path.startswith("/api/ledger_export"), path
        return {"items": copy.deepcopy(rows), "pages": 1, "total": len(rows)}

    monkeypatch.setattr(ps, "_get", fake_get)
    ctx = ps.LiveContext("https://example.test", {"edition": {"as_of": "2026-11-02"}}, 1.0)
    ctx.coach_ids.add("sleep_coach")
    ps._live_ledger(ctx)
    return {p["id"]: p for p in ctx.objs["prediction"]}


def _row(pid, **over):
    row = {
        "item_id": f"sleep:{pid}",
        "prediction_id": pid,
        "coach_id": "sleep",
        "coach_name": "Synthetic Coach",
        "retired": False,
        "claim": "",
        "status": "confirmed",
        "kind": "number",
        "logged_date": "2026-09-11",
        "due_date": "2026-09-12",
        "settled_date": "2026-09-12",
        "grading": {"how": None, "outcome_notes": None, "actual_text": None, "tolerance_text": None},
    }
    row.update(over)
    return row


def test_every_row_without_words_reads_the_same_whatever_kept_them_off(monkeypatch):
    """Vary ONLY why a row has no words — the provenance gate's former flag, the dossier filter's former flag, or
    nothing at all — and the published object is the same (modulo its id). Mutation control: a row WITH words is
    quoted, and the snapshot never says "privacy"."""
    rows = [
        _row("pred_20260911_a", words_withheld=True),
        _row("pred_20260911_b", withheld=True),
        _row("pred_20260911_c"),
        _row("pred_20260911_d", claim="Recovery will hold above fifty tomorrow."),
    ]
    got = _ledger(rows, monkeypatch)

    def shape(p):
        return {k: v for k, v in p.items() if k not in ("id",)}

    a, b, c = (shape(got[f"sleep-pred_20260911_{x}"]) for x in "abc")
    assert a == b == c
    assert a["claim"] == ps.NO_WORDS_SENTENCE and a["claim_withheld"] == "no_words"
    assert (
        got["sleep-pred_20260911_d"]["claim"] == "Recovery will hold above fifty tomorrow."
        and got["sleep-pred_20260911_d"]["claim_withheld"] is None
    )
    assert "privacy" not in json.dumps(list(got.values())).lower()


def test_the_www_schema_and_page_name_no_privacy_hold():
    schema = (ROOT / "www/src/content.config.ts").read_text()
    assert 'claim_withheld: z.enum(["unsourced", "no_words"])' in schema
    page = (ROOT / "www/src/pages/system/ledger/[id].astro").read_text()
    # Owner ruling 2026-11-06: no per-row "No words published" chip either; the ledger index carries one sentence.
    assert "privacy filter" not in page and "No words published" not in page


# ── 3. the public catalogue no longer names the journal ─────────────────────────────────────────


def test_the_notion_journal_is_not_in_the_public_catalogue_but_still_ingested():
    from ingestion.source_registry import SOURCE_REGISTRY, catalog_entries

    assert "notion" in SOURCE_REGISTRY and SOURCE_REGISTRY["notion"]["catalog"] is False  # still a source, not advertised
    assert "notion" not in {r["id"] for r in catalog_entries()}
    import v4_build_data_sources as ds

    assert "notion" not in {r["id"] for r in ds.build()["sources"]}
    for rel in ("site/data/data_sources.json", "site/data/stack.json"):
        text = (ROOT / rel).read_text()
        assert not re.search(r'"id": "notion"|Journal entries|Notion journal', text), rel


# ── 4. the render-gate fixtures carry no production-shaped journal value ────────────────────────


def test_the_render_gate_fixtures_carry_no_production_journal_count():
    fx = ROOT / "tests/fixtures/render_gate"
    blob = {p.name: p.read_text() for p in fx.glob("*.json")}
    ch = json.loads(blob["challenges.json"])["challenges"]
    mined = [c for c in ch if c.get("source") == "journal_mining"]
    assert mined and all("Synthetic" in c["description"] for c in mined)
    assert not re.search(r"six times|fourteen days of journal|×\s*\d+\s*in\s*\d+d", blob["challenges.json"])
    presence = json.loads(blob["presence.json"])
    assert "notion" not in {c["id"] for c in presence["channels"]}  # the wire serves public channels only (2026-11-03)
    habits = json.loads(blob["habits.json"])
    assert "Journal" not in json.dumps(habits)
