"""tests/test_inferred_fields_6286.py — behaviour of common.inferred_fields and its consumers (#6286).

Owner rulings (2026-11-26): a coach is never told it detected a psychological mechanism in him; his
explicit self-report outranks a model's inference about it; stored rows are not rewritten.
The tree-wide guard is tests/test_inferred_psych_fields_guard_6286.py.
"""

from __future__ import annotations

import os
import sys
from decimal import Decimal

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (os.path.join(REPO, "lambdas"), REPO):
    if p not in sys.path:
        sys.path.insert(0, p)
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from common import inferred_fields as IF  # noqa: E402

# Synthetic row — never a real reading.
LABELLED = {
    "enriched_defense_patterns": ["intellectualization"],
    "enriched_primary_defense": "rationalization",
    "enriched_avoidance_flags": ["a phone call"],
    "enriched_cognitive_patterns": ["catastrophizing"],
    "enriched_themes": ["work"],
}


# ── resolve_rating: both orders and the both-absent case ──────────────────────────────────────────


@pytest.mark.parametrize(
    "entry, metric, expected",
    [
        ({"morning_mood": 2, "enriched_mood": 5}, "mood", (2.0, "self_report")),  # both: his wins
        ({"enriched_mood": Decimal("4")}, "mood", (4.0, "model_inferred")),  # model only: marked
        ({"day_rating": 3}, "mood", (3.0, "self_report")),  # second self-report field
        ({}, "mood", (None, None)),  # neither
        ({"energy_eod": 4, "enriched_energy": 1}, "energy", (4.0, "self_report")),
        ({"stress_level": 1, "enriched_stress": 5}, "stress", (1.0, "self_report")),
        ({"enriched_stress": 3}, "stress", (3.0, "model_inferred")),
        ({"morning_mood": "n/a", "enriched_mood": 3}, "mood", (3.0, "model_inferred")),  # unparseable self-report is absence
        (None, "mood", (None, None)),
    ],
)
def test_resolve_rating(entry, metric, expected):
    assert IF.resolve_rating(entry, metric) == expected


def test_resolve_rating_rejects_an_unknown_metric():
    with pytest.raises(ValueError):
        IF.resolve_rating({}, "sleep")


def test_the_self_report_and_model_fields_share_one_scale_per_schema():
    """Every resolved field is 1-5 in docs/SCHEMA.md, so the substitution never rescales."""
    schema = open(os.path.join(REPO, "docs", "SCHEMA.md"), encoding="utf-8").read()
    for metric, fields in IF.SELF_REPORT_FIELDS.items():
        for f in fields + (IF.MODEL_SCORE_FIELDS[metric],):
            line = next((ln for ln in schema.splitlines() if ln.startswith(f"| `{f}` |")), None)
            assert line is not None and "1-5" in line, f"{f}: {line!r}"


# ── the sanctioned accessor ───────────────────────────────────────────────────────────────────────


def test_unreviewed_model_reading_carries_the_caveat():
    r = IF.unreviewed_model_reading([LABELLED, {"enriched_avoidance_flags": ["a phone call", "email"]}])
    assert r["provenance"] == "model_inferred_unreviewed"
    assert "may be wrong" in r["caveat"] and "Never state it" in r["caveat"]
    assert r["labels"] == {
        "defense": ["intellectualization", "rationalization"],
        "avoidance": ["a phone call", "email"],
        "cognitive_distortion": ["catastrophizing"],
    }
    assert IF.unreviewed_model_reading([{"enriched_themes": ["x"]}]) is None
    assert IF.unreviewed_model_reading(None) is None


def test_relabel_row_moves_labels_under_the_caveated_key():
    row = dict(LABELLED)
    IF.relabel_row(row)
    assert not IF.INFERRED_PSYCH_LABEL_FIELDS & set(row)
    assert row["enriched_themes"] == ["work"]
    assert row[IF.RELABEL_KEY]["caveat"] == IF.UNREVIEWED_CAVEAT
    clean = {"enriched_themes": ["work"]}
    assert IF.relabel_row(dict(clean)) == clean


def test_mcp_row_dumpers_relabel(monkeypatch):
    from mcp import tools_data as td

    row = td._strip_tier2("notion", dict(LABELLED))
    assert "enriched_defense_patterns" not in row and "enriched_avoidance_flags" not in row
    assert row["_model_reading_unreviewed"]["labels"]["defense"] == ["intellectualization", "rationalization"]


# ── MCP mood trend: self-report first, model fallback marked ──────────────────────────────────────


def _trend(monkeypatch, items):
    from mcp import tools_journal as tj

    monkeypatch.setattr(tj, "_query_journal", lambda *a, **k: items)
    out = tj._get_mood_trend({})
    return out, {d["date"]: d for d in out["trend"]}


def test_mood_trend_self_report_wins_within_an_entry(monkeypatch):
    _, day = _trend(monkeypatch, [{"date": "2026-01-02", "template": "Morning", "morning_mood": 2, "enriched_mood": 5}])
    assert (day["2026-01-02"]["mood"], day["2026-01-02"]["mood_source"]) == (2.0, "self_report")


def test_mood_trend_model_only_is_marked(monkeypatch):
    out, day = _trend(monkeypatch, [{"date": "2026-01-02", "template": "Morning", "enriched_stress": 3}])
    assert (day["2026-01-02"]["stress"], day["2026-01-02"]["stress_source"]) == (3.0, "model_inferred")
    assert out["summary"]["stress"]["days_model_inferred"] == 1
    assert out["summary"]["stress"]["days_self_reported"] == 0
    assert "rating_provenance" in out


def test_mood_trend_both_absent_leaves_the_day_unscored(monkeypatch):
    _, day = _trend(monkeypatch, [{"date": "2026-01-02", "template": "Morning", "raw_text": "words"}])
    assert "mood" not in day["2026-01-02"] and "mood_source" not in day["2026-01-02"]


def test_mood_trend_a_self_report_beats_a_later_evening_model_score(monkeypatch):
    items = [
        {"date": "2026-01-02", "template": "Morning", "morning_mood": 2},
        {"date": "2026-01-02", "template": "Evening", "enriched_mood": 5},
    ]
    _, day = _trend(monkeypatch, items)
    assert (day["2026-01-02"]["mood"], day["2026-01-02"]["mood_source"]) == (2.0, "self_report")


def test_mood_trend_a_self_report_replaces_an_earlier_model_score(monkeypatch):
    items = [
        {"date": "2026-01-02", "template": "Morning", "enriched_mood": 5},
        {"date": "2026-01-02", "template": "Weekly", "day_rating": 3},
    ]
    _, day = _trend(monkeypatch, items)
    assert (day["2026-01-02"]["mood"], day["2026-01-02"]["mood_source"]) == (3.0, "self_report")


# ── the journal coach prompt ──────────────────────────────────────────────────────────────────────


def test_journal_coach_prompt_carries_no_detected_label_or_directive(monkeypatch):
    from ai import ai_calls
    from emails.daily_brief_signals import extract_journal_signals

    entry = dict(LABELLED, raw_text="Synthetic entry text about a long day.", template="evening")
    data = {"journal_entries": [entry], "journal_signals": extract_journal_signals([entry]), "date": "2026-01-02"}
    seen = {}

    def fake_call(prompt, *a, **k):
        seen["prompt"] = prompt
        return "reflection || tactic"

    monkeypatch.setattr(ai_calls, "call_anthropic", fake_call)
    monkeypatch.setattr(ai_calls, "_ground_legacy_output", lambda label, out, *a, **k: out)
    monkeypatch.setattr(ai_calls, "_build_weight_context", lambda *a, **k: "synthetic weight context")
    ai_calls.call_journal_coach(data, {"primary_obstacles": []}, api_key="x")
    prompt = seen["prompt"]
    for forbidden in ("DETECTED", "Challenge one", "AVOIDANCE FLAGS", "Name what's being avoided", "without softening"):
        assert forbidden not in prompt, forbidden
    for label in ("intellectualization", "rationalization", "a phone call", "catastrophizing"):
        assert label not in prompt, label
    assert "Do not label a psychological mechanism" in prompt


def test_mood_read_prefers_his_rating():
    from health import mood_read

    entries = [{"date": f"2026-01-0{i}", "morning_mood": 1, "enriched_mood": 5} for i in range(1, 7)]
    sig = mood_read.journal_signal(entries)
    assert sig["mood_trend"]["avg"] == 1.0
