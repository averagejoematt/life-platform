"""tests/test_character_sheet_journal_890.py — #890: character-sheet daily journal fetch.

Notion journal rows are stored under templated sort keys
(`DATE#{date}#journal#{template}`, one per journal template, possibly several
per day) — never under the flat `DATE#{date}` key that `fetch_date("notion",
...)` looks up. Before #890, assemble_data() built `data["journal"]` from that
flat lookup, so it was always None and the engine's `journal.get("themes")`
branch inside interaction_quality was permanently dead code.

These tests seed the REAL templated key shape into the shared FakeDdbTable and
prove:
  1. the flat lookup indeed cannot see the rows (the pre-#890 dead path),
  2. assemble_data() now derives a dict-shaped journal view (merged, deduped
     themes) from the day's templated entries,
  3. themes flow end-to-end into character_engine.compute_relationships_raw's
     interaction_quality component — and the day counts as instrumented
     coverage (`_not_instrumented` is False) once themes are present.

All offline — the module-level boto3 table is monkeypatched.
"""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "lambdas"))
sys.path.insert(0, str(REPO_ROOT / "lambdas" / "compute"))

os.environ.setdefault("S3_BUCKET", "test-bucket")

import character_engine  # noqa: E402
import character_sheet_lambda as csl  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402

DATE = "2026-06-20"
NOTION_PK = "USER#matthew#SOURCE#notion"


def _journal_rows():
    """Two templated entries for the day — the real stored key shape."""
    return [
        {
            "pk": NOTION_PK,
            "sk": f"DATE#{DATE}#journal#morning",
            "enriched_themes": ["family connection", "work pressure"],
            "raw_text": "morning entry",
        },
        {
            "pk": NOTION_PK,
            "sk": f"DATE#{DATE}#journal#evening",
            "enriched_themes": ["family connection", "personal growth"],
            "raw_text": "evening entry",
        },
    ]


def _keyed_query_hook(table, **kwargs):
    """Honor pk equality + `sk BETWEEN :s AND :e` against the fake's store.

    fetch_journal_entries queries `pk = :pk AND sk BETWEEN :s AND :e` (plus the
    phase FilterExpression, irrelevant for untagged rows); fetch_range queries
    the same shape for other sources. Filtering properly keeps the notion rows
    from leaking into every other source's window query during assemble_data().
    """
    values = kwargs.get("ExpressionAttributeValues", {})
    pk = values.get(":pk")
    lo, hi = values.get(":s"), values.get(":e")
    items = [item for item in table.store.values() if item.get("pk") == pk and (lo is None or lo <= item.get("sk", "") <= hi)]
    return {"Items": items}


def _fake_table():
    return FakeDdbTable(rows=_journal_rows(), query_hook=_keyed_query_hook)


def _relationships_config():
    return {
        "pillars": {
            "relationships": {
                "components": {
                    "social_interaction_frequency": {"weight": 0.4},
                    "interaction_quality": {"weight": 0.3},
                    "buddy_engagement": {"weight": 0.15},
                    "social_mood_correlation": {"weight": 0.15},
                }
            }
        }
    }


def test_flat_notion_lookup_is_dead(monkeypatch):
    """The pre-#890 path: the flat DATE# key never exists for notion, so
    fetch_date returns None even when the day HAS journal entries."""
    monkeypatch.setattr(csl, "table", _fake_table())
    assert csl.fetch_date("notion", DATE) is None


def test_assemble_data_derives_journal_from_templated_entries(monkeypatch):
    monkeypatch.setattr(csl, "table", _fake_table())
    data = csl.assemble_data(DATE)

    assert len(data["journal_entries"]) == 2
    # Merged view: deduped, first-seen order preserved.
    assert data["journal"] == {"themes": ["family connection", "work pressure", "personal growth"]}


def test_themes_flow_to_interaction_quality_and_clear_not_instrumented(monkeypatch):
    """End-to-end: the previously-dead themes path is live — interaction_quality
    scores from the merged journal view, and the day counts as instrumented
    coverage for the Relationships pillar (#881's _not_instrumented clears)."""
    monkeypatch.setattr(csl, "table", _fake_table())
    data = csl.assemble_data(DATE)

    raw, details = character_engine.compute_relationships_raw(data, _relationships_config())

    # "family connection" matches the social-keyword list -> one social theme -> 33.
    assert details["interaction_quality"]["score"] == 33
    assert details["_not_instrumented"] is False


def test_merge_journal_view_empty_day_stays_falsy():
    """No entries -> None, preserving the old 'no journal record' contract, so
    a truly journal-less day still reads as not-instrumented downstream."""
    assert csl.merge_journal_view([]) is None
    assert csl.merge_journal_view(None) is None
    assert csl.merge_journal_view([{"sk": f"DATE#{DATE}#journal#morning"}]) is None


# ── #902: enriched_mood (1–5) → mood_avg (0–10) scale mapping ────────────────


def test_enriched_mood_scale_map_full_domain():
    """The 1–5 domain maps linearly onto the engine's 0–10 scale: 1→0, 3→5,
    5→10. This is the documented decision — a neutral mood (3) lands at the
    midpoint the consumer's (mood/10)*100 turns into 50%."""
    assert csl._enriched_mood_to_10(1) == 0.0
    assert csl._enriched_mood_to_10(3) == 5.0
    assert csl._enriched_mood_to_10(5) == 10.0
    assert csl._enriched_mood_to_10(2) == 2.5
    assert csl._enriched_mood_to_10(4) == 7.5
    # Bad / absent input is tolerated.
    assert csl._enriched_mood_to_10(None) is None
    assert csl._enriched_mood_to_10("n/a") is None


def test_merge_journal_view_averages_and_maps_mood():
    """A day's enriched_mood values (1–5) are averaged then mapped to 0–10.
    Moods 5 and 3 -> mapped 10 and 5 -> avg 7.5 on the mood_avg key the engine
    reads."""
    entries = [
        {"sk": f"DATE#{DATE}#journal#morning", "enriched_mood": 5, "enriched_themes": ["family connection"]},
        {"sk": f"DATE#{DATE}#journal#evening", "enriched_mood": 3},
    ]
    view = csl.merge_journal_view(entries)
    assert view["mood_avg"] == 7.5
    assert view["themes"] == ["family connection"]


def test_mood_only_day_is_no_longer_falsy():
    """A day with mood but no themes now yields a view (mood_avg set) instead of
    None — that's exactly the previously-dead signal #902 revives."""
    view = csl.merge_journal_view([{"sk": f"DATE#{DATE}#journal#morning", "enriched_mood": 4}])
    assert view == {"mood_avg": 7.5}


def _journal_rows_with_mood():
    """Templated entries carrying enriched_mood AND a social signal — the
    conditions social_mood_correlation gates on (mood + social_score both
    present)."""
    return [
        {
            "pk": NOTION_PK,
            "sk": f"DATE#{DATE}#journal#morning",
            "enriched_themes": ["family connection"],
            "enriched_mood": 5,
            "social_connection_score": 8,
            "raw_text": "morning entry",
        },
        {
            "pk": NOTION_PK,
            "sk": f"DATE#{DATE}#journal#evening",
            "enriched_mood": 3,
            "raw_text": "evening entry",
        },
    ]


def test_social_mood_correlation_gets_non_null_input(monkeypatch):
    """End-to-end #902: with enriched_mood populated (and a social signal
    present) social_mood_correlation is no longer None.

    Moods 5,3 -> mapped 10,5 -> mood_avg 7.5; the consumer computes
    (7.5/10)*100 = 75.0."""
    table = FakeDdbTable(rows=_journal_rows_with_mood(), query_hook=_keyed_query_hook)
    monkeypatch.setattr(csl, "table", table)
    data = csl.assemble_data(DATE)

    assert data["journal"]["mood_avg"] == 7.5

    raw, details = character_engine.compute_relationships_raw(data, _relationships_config())
    assert details["social_mood_correlation"]["score"] == 75.0


# ── #910: categorical enriched_social_quality → social_score bridge (end-to-end)


def _journal_rows_with_social_quality():
    """Templated entries carrying only the categorical enriched_social_quality
    (the field the enrichment lambda actually emits) — NO numeric
    social_connection_score anywhere, the real-world condition #910 fixes. Mood
    is included so the mood-gated social_mood_correlation can also be exercised."""
    return [
        {
            "pk": NOTION_PK,
            "sk": f"DATE#{DATE}#journal#morning",
            "enriched_themes": ["family connection"],
            "enriched_social_quality": "deep",
            "enriched_mood": 5,
            "raw_text": "morning entry",
        },
        {
            "pk": NOTION_PK,
            "sk": f"DATE#{DATE}#journal#evening",
            "enriched_social_quality": "meaningful",
            "enriched_mood": 3,
            "raw_text": "evening entry",
        },
    ]


def test_social_quality_revives_both_social_components(monkeypatch):
    """End-to-end #910: with ONLY the categorical enriched_social_quality stored
    (no numeric field), social_interaction_frequency AND social_mood_correlation
    are both non-null through the real assemble_data path.

    Quality deep,meaningful -> mapped 10, 6.67 -> avg 8.33 -> *10 -> 83.3.
    Moods 5,3 -> mapped 10,5 -> mood_avg 7.5 -> (7.5/10)*100 = 75.0."""
    table = FakeDdbTable(rows=_journal_rows_with_social_quality(), query_hook=_keyed_query_hook)
    monkeypatch.setattr(csl, "table", table)
    data = csl.assemble_data(DATE)

    raw, details = character_engine.compute_relationships_raw(data, _relationships_config())
    assert details["social_interaction_frequency"]["score"] == 83.3
    assert details["social_mood_correlation"]["score"] == 75.0
    assert details["_not_instrumented"] is False
