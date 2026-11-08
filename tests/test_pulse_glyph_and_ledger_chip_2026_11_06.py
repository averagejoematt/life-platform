"""Owner rulings 2026-11-06: the journal glyph leaves both pulse producers and the fixtures, and the ledger's
repetitive "No words published" chip gives way to one page-level sentence. All values synthetic.

The rest of these rulings are pinned beside their own suites: `retracted` in test_coach_dossier.py,
`names_withheld` in test_food_name_allowlist_5112.py, the readers in tests/js/.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT / "scripts"))


def _names(rel: str) -> set:
    tree = ast.parse((ROOT / rel).read_text())
    out = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    out |= {a.arg for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) for a in n.args.args}
    out |= {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and len(n.value) < 20}
    return out


def test_neither_pulse_producer_can_build_a_journal_glyph():
    api, static = _names("lambdas/web/site_api_pulse.py"), _names("lambdas/content/site_writer.py")
    assert "_journal_activity" not in api and "journal" not in api and "written_today" not in api
    assert not {"_journal_derived_glyphs", "journal_data", "mood_data", "written_today"} & static


def test_the_static_pulse_is_the_same_object_with_no_journal_input_to_vary():
    from content import site_writer

    p = site_writer._compute_pulse(vitals={}, journey={}, training={})
    assert "journal" not in p["pulse"]["glyphs"] and p["pulse"]["signals_total"] == len(p["pulse"]["glyphs"])


def test_the_render_gate_pulse_fixture_has_no_journal_glyph():
    glyphs = json.loads((ROOT / "tests/fixtures/render_gate/pulse.json").read_text())["pulse"]["glyphs"]
    assert "journal" not in glyphs and glyphs, "the fixture still carries the public glyphs"


def test_no_shipped_reader_names_the_journal_glyph():
    for js in ("v7_home.js", "v7_week.js", "v7_numbers.js"):
        assert "glyphs.journal" not in (ROOT / "site/assets/js" / js).read_text(), js


def test_the_ledger_has_no_per_row_no_words_text_and_one_page_sentence():
    index = (ROOT / "www/src/pages/system/ledger/index.astro").read_text()
    detail = (ROOT / "www/src/pages/system/ledger/[id].astro").read_text()
    assert "No words published" not in index + detail
    assert index.count("data-no-words-note") == 1 and "no publishable commentary" in index
    assert 'p.claim_withheld !== "no_words" && (' in index, "a no-words row draws no words slot"
    assert 'p.claim_withheld === "no_words" ? "" : p.claim' in index, "the search must not match the shared sentence"
    # Mutation control: the public instrument hold keeps its chip.
    assert 'p.claim_withheld === "unsourced" && <p class="chip"' in detail


def test_the_snapshot_contract_and_the_site_schema_agree_on_claim_withheld():
    import publish_snapshot_contract as contract

    src = (ROOT / "scripts/publish_snapshot_contract.py").read_text()
    contract_values = set(re.search(r'"claim_withheld": \("enum:([^"]+)"', src).group(1).split("|"))
    schema = (ROOT / "www/src/content.config.ts").read_text()
    schema_values = set(re.findall(r'"(\w+)"', re.search(r"claim_withheld: z\.enum\(\[([^\]]+)\]\)", schema).group(1)))
    assert contract_values == schema_values == {"unsourced", "no_words"}
    assert contract is not None
