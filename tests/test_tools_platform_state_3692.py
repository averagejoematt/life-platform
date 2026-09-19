"""tests/test_tools_platform_state_3692.py — get_platform_state (#3692).

The tool is the conversational half of /method/state/ (#3691). The property that
matters is not "it returns JSON" — it is that the spoken answer and the page cannot
disagree, and that a section the generator could not compute is reported as a gap
rather than rounded up to a number (ADR-104).

So the fixture is the COMMITTED artifact, site/data/platform_state.json — the same
bytes the page renders — and the summary assertions are composed from that file's own
board fields rather than from a hand-typed sentence. A wording change that stopped
matching the page's headline fields fails here.

Network is never touched: `_fetch` is the single seam and every test replaces it.
"""

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for _k in ("AWS_REGION", "USER_ID", "TABLE_NAME", "DYNAMODB_TABLE", "S3_BUCKET"):
    os.environ.setdefault(_k, "x")

import mcp.tools_platform_state as tps  # noqa: E402

ARTIFACT = ROOT / "site" / "data" / "platform_state.json"


@pytest.fixture
def doc():
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


@pytest.fixture
def served(monkeypatch, doc):
    """Serve the committed artifact in place of the published URL."""
    monkeypatch.setattr(tps, "_fetch", lambda *a, **k: json.loads(json.dumps(doc)))
    return doc


# ── the section set is derived from the artifact, never typed here ──────────────


def test_sections_are_the_artifacts_own_provenance_bearing_keys(doc):
    """The nine joined sources, identified by the `source` stamp the generator puts on
    each one — so a tenth section is selectable the day it ships and a renamed one
    cannot leave a stale name behind."""
    sections = tps.available_sections(doc)
    assert len(sections) == 9, sections
    assert set(sections) <= set(doc)
    for name in sections:
        assert "source" in doc[name] and "as_of" in doc[name]
    # run metadata is not a joined source
    assert "generated_at" not in sections and "healthy" not in sections and "about" not in sections


def test_an_added_section_needs_no_edit_here_or_in_the_tool(doc):
    """The derivation, exercised: a synthetic tenth section appears without a code change."""
    doc["velocity"] = {"source": "scripts/whatever.py", "as_of": "2026-09-19T00:00:00Z", "n": 1}
    assert "velocity" in tps.available_sections(doc)


# ── the summary is the page's headline, composed from the same fields ───────────


def test_summary_carries_the_same_four_figures_the_page_puts_in_its_headline(served):
    """/method/state/ renders actionable · P1 open · reader-facing · from audits, over
    total_open, plus the generation stamp. The sentence is built from those values."""
    board = served["board"]
    summary = tps.build_summary(served)
    for value in (
        board["actionable"],
        (board.get("by_prio") or {}).get("P1", 0),
        board["reader_facing"],
        board["from_review_total"],
        board["total_open"],
    ):
        assert str(value) in summary, f"{value!r} missing from: {summary}"
    assert served["generated_at"] in summary


def test_summary_states_the_degraded_sections_rather_than_hiding_them(doc):
    doc["degraded_sections"] = ["cost", "grades"]
    summary = tps.build_summary(doc)
    assert "2 section(s) not computed this run" in summary
    assert "cost" in summary and "grades" in summary


def test_a_board_that_could_not_be_computed_is_named_not_zeroed(doc):
    doc["board"] = {"error": "gh rate limited", "data": None}
    summary = tps.build_summary(doc)
    assert "could not be computed" in summary and "gh rate limited" in summary
    assert "0 actionable" not in summary


# ── the tool ────────────────────────────────────────────────────────────────────


def test_all_returns_every_section_with_the_summary_and_provenance(served):
    out = tps.tool_get_platform_state({"section": "all"})
    assert out["section"] == "all"
    assert set(out["data"]) == set(tps.available_sections(served))
    assert out["generated_at"] == served["generated_at"]
    assert out["summary"] == tps.build_summary(served)
    assert out["source"] == tps.STATE_URL
    assert out["renders_at"].endswith("/method/state/")


def test_no_argument_defaults_to_all(served):
    assert tps.tool_get_platform_state()["section"] == "all"
    assert tps.tool_get_platform_state({})["section"] == "all"


def test_one_section_returns_that_section_verbatim(served):
    out = tps.tool_get_platform_state({"section": "board"})
    assert out["section"] == "board"
    assert out["data"] == served["board"]
    # the summary travels with every answer, so a single-section read still states the whole
    assert out["summary"] == tps.build_summary(served)


def test_an_unknown_section_lists_what_is_available_instead_of_guessing(served):
    out = tps.tool_get_platform_state({"section": "burndown"})
    assert "unknown section" in out["error"]
    assert "all" in out["sections_available"]
    assert "board" in out["sections_available"]
    assert "data" not in out


def test_a_failed_fetch_is_an_error_never_a_stale_value(monkeypatch):
    import urllib.error

    monkeypatch.setattr(tps, "_fetch", lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("dns")))
    out = tps.tool_get_platform_state({"section": "board"})
    assert "could not read the build readout" in out["error"]
    assert "data" not in out and "summary" not in out


def test_an_unexpected_payload_shape_is_refused(monkeypatch):
    monkeypatch.setattr(tps, "_fetch", lambda *a, **k: {"generated_at": "2026-09-19T00:00:00Z"})
    assert "not in the expected shape" in tps.tool_get_platform_state()["error"]


def test_age_hours_is_none_rather_than_a_guess_when_the_stamp_is_unusable():
    assert tps.age_hours(None) is None
    assert tps.age_hours("not a date") is None
    assert tps.age_hours("2026-09-19T00:00:00Z") is not None
