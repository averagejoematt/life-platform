"""tests/test_journal_signal_wiring.py — journal Phase 1 cluster (#502/#503).

The data-source health review (J-1/J-3/J-4) found the journal enrichment
pipeline dead end-to-end: the notion ingester clobbered enrichment on every
re-ingest, and three consumers read field names the enricher never writes.
These tests pin the writer→reader contract:

  - _build_mind_data aggregates journal_entries with the enricher's REAL
    schema (enriched_mood/energy/stress, list fields) — a signal must land.
  - The sentiment-trajectory tool reads the written names.
  - edited_since_enrichment re-enriches Notion-edited entries and skips
    unedited ones (the #502 skip-logic contract).
  - preserve_enrichment copies enriched_*/defense_* across a re-ingest put.
"""

import os

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")

from decimal import Decimal  # noqa: E402

from ai_context import _build_mind_data  # noqa: E402
from ingestion.journal_enrichment_lambda import edited_since_enrichment  # noqa: E402
from ingestion.notion_lambda import preserve_enrichment  # noqa: E402

ENRICHED_ENTRY = {
    "sk": "DATE#2026-07-01#journal#evening",
    "template": "Evening",
    "enriched_mood": Decimal("4"),
    "enriched_energy": Decimal("3"),
    "enriched_stress": Decimal("2"),
    "enriched_sentiment": "positive",
    "enriched_themes": ["discipline", "family"],
    "enriched_avoidance_flags": ["skipped hard conversation"],
    "enriched_growth_signals": ["asked for feedback"],
    "enriched_at": "2026-07-02T14:35:00+00:00",
    "notion_last_edited": "2026-07-01T21:10:00.000Z",
}


# ── #503 J-4: the mind coach sees journal signals ─────────────────────────


def test_mind_data_signal_lands_from_journal_entries():
    data = {"journal_entries": [ENRICHED_ENTRY, dict(ENRICHED_ENTRY, enriched_mood=Decimal("2"), enriched_themes=["stress"])]}
    mind = _build_mind_data(data)
    assert mind["journal_entry_count"] == 2
    assert mind["enriched_mood"] == 3.0  # mean of 4 and 2
    assert mind["enriched_energy"] == 3.0
    assert mind["enriched_stress"] == 2.0
    assert mind["enriched_sentiment"] == "positive"
    assert "discipline" in mind["enriched_themes"] and "stress" in mind["enriched_themes"]
    assert mind["enriched_avoidance_flags"] == ["skipped hard conversation"]
    assert mind["enriched_growth_signals"] == ["asked for feedback"]


def test_mind_data_empty_journal_is_honest_absence():
    mind = _build_mind_data({"journal_entries": []})
    assert mind["journal_entry_count"] == 0
    assert mind["enriched_mood"] is None
    assert mind["enriched_themes"] == []


def test_mind_data_tolerates_unenriched_entries():
    # Raw entries with no enriched_* fields (the pre-backfill state) must not crash.
    mind = _build_mind_data({"journal_entries": [{"sk": "DATE#2026-07-01#journal#morning", "raw_text": "short"}]})
    assert mind["journal_entry_count"] == 1
    assert mind["enriched_mood"] is None


# ── #503 J-3: trajectory tool reads the written field names ───────────────


def test_trajectory_reads_written_enrichment_names(monkeypatch):
    import mcp.tools_journal as tj

    entries = []
    for i in range(1, 11):
        entries.append(
            dict(
                ENRICHED_ENTRY,
                sk=f"DATE#2026-06-{i:02d}#journal#evening",
                date=f"2026-06-{i:02d}",
                enriched_mood=Decimal(str(3 + (i % 2))),
            )
        )
    monkeypatch.setattr(tj, "_query_journal", lambda start, end, template=None: entries)
    result = tj.tool_get_journal_sentiment_trajectory({"start_date": "2026-06-01", "end_date": "2026-06-10"})
    assert "error" not in result, result.get("error")


# ── #820 R22-SCI-02: trajectory slopes carry r² + n, low-fit divergences are annotated ────


def _make_trajectory_entries(n=10):
    entries = []
    for i in range(1, n + 1):
        entries.append(
            dict(
                ENRICHED_ENTRY,
                sk=f"DATE#2026-06-{i:02d}#journal#evening",
                date=f"2026-06-{i:02d}",
                enriched_mood=Decimal(str(3 + (i % 2))),
                enriched_energy=Decimal(str(2 + (i % 3))),
                enriched_stress=Decimal(str(1 + (i % 2))),
            )
        )
    return entries


def test_trajectory_reports_r_squared_and_n_per_metric(monkeypatch):
    """Each trajectory (mood/energy/stress) surfaces r² and the n that fed its regression,
    additively alongside the existing slope/direction/avg fields (ADR-105 rule 1)."""
    import mcp.tools_journal as tj

    entries = _make_trajectory_entries(10)
    monkeypatch.setattr(tj, "_query_journal", lambda start, end, template=None: entries)
    result = tj.tool_get_journal_sentiment_trajectory({"start_date": "2026-06-01", "end_date": "2026-06-10"})
    assert "error" not in result, result.get("error")
    for metric in ("mood", "energy", "stress"):
        traj = result["trajectories"][metric]
        # Existing fields untouched.
        assert set(["slope", "direction", "avg"]).issubset(traj.keys())
        # New, additive fields.
        assert "r_squared" in traj
        assert "n" in traj
        assert traj["n"] >= 5


def test_low_fit_divergence_gets_qualifier(monkeypatch):
    """A divergence gated purely on slope magnitude gets an honest low-fit qualifier
    (ADR-105 rule 1) when the weaker contributing regression's r² is below the
    documented floor (r² < 0.09, i.e. |r| < 0.3 — the weak/moderate boundary already
    used in tools_habits.py / tools_training.py)."""
    import mcp.tools_journal as tj

    entries = _make_trajectory_entries(10)
    monkeypatch.setattr(tj, "_query_journal", lambda start, end, template=None: entries)

    # compute_slope() calls _linear_regression once per field, in mood/energy/stress order.
    # Force a mood-up/energy-down divergence (crosses the ±0.03 threshold) with a poor fit
    # on both contributing slopes, and a stress slope too small to trigger its own branch.
    canned = iter(
        [
            (0.1, 1.0, 0.02),  # mood: rising, very low fit
            (-0.1, 1.0, 0.05),  # energy: falling, low fit
            (0.0, 1.0, 0.9),  # stress: flat, high fit (irrelevant here)
        ]
    )
    monkeypatch.setattr(tj, "_linear_regression", lambda vals: next(canned))

    result = tj.tool_get_journal_sentiment_trajectory({"start_date": "2026-06-01", "end_date": "2026-06-10"})
    assert "error" not in result, result.get("error")
    divergence = next(d for d in result["divergences"] if d["type"] == "mood_up_energy_down")
    assert "Low fit" in divergence["signal"]
    assert "r²=0.02" in divergence["signal"]
    assert divergence["mood_r_squared"] == 0.02
    assert divergence["energy_r_squared"] == 0.05


def test_high_fit_divergence_has_no_qualifier(monkeypatch):
    """The same divergence, but with well-fitting slopes, ships with no low-fit annotation."""
    import mcp.tools_journal as tj

    entries = _make_trajectory_entries(10)
    monkeypatch.setattr(tj, "_query_journal", lambda start, end, template=None: entries)

    canned = iter(
        [
            (0.1, 1.0, 0.9),  # mood: rising, strong fit
            (-0.1, 1.0, 0.85),  # energy: falling, strong fit
            (0.0, 1.0, 0.9),  # stress
        ]
    )
    monkeypatch.setattr(tj, "_linear_regression", lambda vals: next(canned))

    result = tj.tool_get_journal_sentiment_trajectory({"start_date": "2026-06-01", "end_date": "2026-06-10"})
    assert "error" not in result, result.get("error")
    divergence = next(d for d in result["divergences"] if d["type"] == "mood_up_energy_down")
    assert "Low fit" not in divergence["signal"]
    assert divergence["mood_r_squared"] == 0.9


# ── #502: edit-aware skip logic ───────────────────────────────────────────


def test_unedited_enriched_entry_is_not_stale():
    assert edited_since_enrichment(ENRICHED_ENTRY) is False


def test_entry_edited_after_enrichment_is_stale():
    edited = dict(ENRICHED_ENTRY, notion_last_edited="2026-07-03T09:00:00.000Z")
    assert edited_since_enrichment(edited) is True


def test_missing_or_garbage_timestamps_fall_back_to_skip():
    assert edited_since_enrichment(dict(ENRICHED_ENTRY, notion_last_edited=None)) is False
    assert edited_since_enrichment(dict(ENRICHED_ENTRY, notion_last_edited="not-a-date")) is False
    assert edited_since_enrichment({"enriched_at": None, "notion_last_edited": "2026-07-03T09:00:00Z"}) is False


# ── #502 J-1: re-ingestion preserves enrichment ───────────────────────────


class _FakeTable:
    def __init__(self, existing):
        self._existing = existing

    def get_item(self, Key):
        return {"Item": self._existing} if self._existing else {}


def test_preserve_enrichment_copies_enriched_and_defense_fields(monkeypatch):
    import ingestion.notion_lambda as nl

    existing = dict(
        ENRICHED_ENTRY,
        pk="USER#matthew#SOURCE#notion",
        enriched_defense_patterns=["intellectualization"],
        defense_enriched_at="2026-07-02T14:36:00+00:00",
        raw_text="old text",
    )
    monkeypatch.setattr(nl, "table", _FakeTable(existing))
    fresh = {"pk": "USER#matthew#SOURCE#notion", "sk": ENRICHED_ENTRY["sk"], "raw_text": "new text"}
    preserve_enrichment(fresh)
    assert fresh["enriched_mood"] == Decimal("4")
    assert fresh["enriched_at"] == ENRICHED_ENTRY["enriched_at"]
    assert fresh["enriched_defense_patterns"] == ["intellectualization"]
    assert fresh["defense_enriched_at"] == "2026-07-02T14:36:00+00:00"
    # Ingested attributes win over the stored copy — only enrichment is grafted.
    assert fresh["raw_text"] == "new text"


def test_preserve_enrichment_noop_when_no_existing_item(monkeypatch):
    import ingestion.notion_lambda as nl

    monkeypatch.setattr(nl, "table", _FakeTable(None))
    fresh = {"pk": "USER#matthew#SOURCE#notion", "sk": "DATE#2026-07-04#journal#morning", "raw_text": "hi"}
    preserve_enrichment(fresh)
    assert "enriched_mood" not in fresh
