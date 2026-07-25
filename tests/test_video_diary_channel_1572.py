"""tests/test_video_diary_channel_1572.py — #1572 (epic #1564).

The transcript landing path: a "Video Diary" Notion template flows the EXISTING
journal pipeline (notion → enrichment → flourishing → character → hypothesis) with
`channel` provenance, and no second pipeline. Pins:

  AC2 — notion_lambda ingests Video Diary (dedicated SK suffix, multi-per-day,
        channel stamp); journal_enrichment does NOT whitelist templates.
  AC3 — channel provenance is carried on the entry + projected onto the
        flourishing row, and surfaces in get_mood / get_flourishing_trend.
  AC4 — one synthetic Video Diary entry produces a flourishing row, is eligible
        for the character-sheet journal view, and (given a causal hint) yields a
        HYPO_CANDIDATE.
  AC5 — regression guard: channel is provenance only; the enriched signals a
        diary contributes are the same ones typed journal already does.
"""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in (
    os.path.join(ROOT, "lambdas"),
    os.path.join(ROOT, "lambdas", "ingestion"),
    os.path.join(ROOT, "lambdas", "intelligence"),
    os.path.join(ROOT, "lambdas", "compute"),
    ROOT,
):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import flourishing as fl  # noqa: E402
import notion_lambda as nl  # noqa: E402


def _select(name):
    return {"type": "select", "select": {"name": name}}


def _date(d):
    return {"type": "date", "date": {"start": d}}


def _page(template, page_id="abcd1234-ef56-7890-1234-56789abcdef0", date="2026-07-25"):
    return {
        "id": page_id,
        "created_time": "2026-07-25T02:00:00.000Z",
        "last_edited_time": "2026-07-25T02:05:00.000Z",
        "properties": {"Date": _date(date), "Template": _select(template)},
    }


# ── AC2: notion ingestion ─────────────────────────────────────────────────────


def test_video_diary_registered_and_multi_per_day():
    assert nl.TEMPLATE_SK["Video Diary"] == "video_diary"
    assert "Video Diary" in nl.MULTI_PER_DAY


def test_build_sk_video_diary_uses_dedicated_stable_suffix():
    sk = nl.build_sk("2026-07-25", "Video Diary", page_id="abcd1234-ef56-7890-1234-56789abcdef0")
    # dedicated suffix + stable per-page id (dedup), NOT the generic journal fallback
    assert sk == "DATE#2026-07-25#journal#video_diary#56789abcdef0"
    assert "#journal#" in sk  # keeps it inside the shared journal pipeline surface
    # idempotent
    assert sk == nl.build_sk("2026-07-25", "Video Diary", page_id="abcd1234-ef56-7890-1234-56789abcdef0")


def test_parse_page_stamps_video_diary_channel(monkeypatch):
    monkeypatch.setattr(nl, "_archive_page_raw", lambda *a, **k: None)
    date_str, template, item = nl.parse_page(_page("Video Diary"), api_key=None)
    assert template == "Video Diary"
    assert item["channel"] == "video_diary"
    assert item["date"] == "2026-07-25"


def test_parse_page_typed_journal_channel_default(monkeypatch):
    monkeypatch.setattr(nl, "_archive_page_raw", lambda *a, **k: None)
    _, template, item = nl.parse_page(_page("Evening"), api_key=None)
    assert template == "Evening"
    assert item["channel"] == "journal"


def test_enrichment_does_not_whitelist_templates(monkeypatch):
    """The enricher's query keeps ANY `#journal#` entry — there is no template
    allowlist that would strand a Video Diary entry. Exercised through the real
    query_journal_entries filter with a mocked table."""
    import journal_enrichment_lambda as je

    mixed = [
        {"sk": "DATE#2026-07-25#journal#video_diary#56789abcdef0", "raw_text": "x"},
        {"sk": "DATE#2026-07-25#journal#evening", "raw_text": "y"},
        {"sk": "DATE#2026-07-25#WORKOUT#1", "raw_text": "z"},  # non-journal sibling, filtered out
    ]

    class _T:
        def query(self, **kw):
            return {"Items": mixed}

    monkeypatch.setattr(je, "table", _T())
    kept = je.query_journal_entries("2026-07-24", "2026-07-25")
    sks = [e["sk"] for e in kept]
    assert "DATE#2026-07-25#journal#video_diary#56789abcdef0" in sks  # video diary survives
    assert not any("WORKOUT" in s for s in sks)  # only journal entries kept


# ── AC3: channel provenance ───────────────────────────────────────────────────


def test_entry_channel_derivation():
    assert fl.entry_channel({"channel": "video_diary"}) == "video_diary"
    assert fl.entry_channel({"template": "Video Diary"}) == "video_diary"  # fallback from template
    assert fl.entry_channel({"template": "Evening"}) == "journal"
    assert fl.entry_channel({}) == "journal"
    # explicit stored channel wins over template
    assert fl.entry_channel({"channel": "journal", "template": "Video Diary"}) == "journal"


def test_flourishing_row_carries_channel_breakdown():
    row = fl.aggregate_entries(
        [
            {"enriched_at": "t", "channel": "video_diary", "enriched_values_lived": ["health"]},
            {"enriched_at": "t", "channel": "journal", "enriched_gratitude": ["a"]},
        ]
    )
    assert row["channels"] == ["journal", "video_diary"]
    assert row["channel_entry_counts"] == {"video_diary": 1, "journal": 1}


def test_flourishing_row_writer_persists_channels():
    class _Put:
        item = None

        def put_item(self, Item):
            self.item = Item

    t = _Put()
    ok = fl.write_flourishing_row(
        t, "matthew", "2026-07-25", [{"enriched_at": "t", "channel": "video_diary", "enriched_gratitude": ["a"]}], "m", 2
    )
    assert ok and t.item["channels"] == ["video_diary"]
    assert t.item["channel_entry_counts"] == {"video_diary": 1}


def test_get_mood_surfaces_channel(monkeypatch):
    from mcp import tools_journal as tj

    items = [
        {"date": "2026-07-25", "template": "Video Diary", "channel": "video_diary", "enriched_mood": 4, "enriched_themes": ["growth"]},
        {"date": "2026-07-24", "template": "Evening", "channel": "journal", "enriched_mood": 3},
    ]
    monkeypatch.setattr(tj, "_query_journal", lambda *a, **k: items)
    out = tj._get_mood_trend({})
    assert out["channels_present"] == ["journal", "video_diary"]
    assert "video-diary" in out["channel_note"]
    day = {d["date"]: d for d in out["trend"]}
    assert day["2026-07-25"]["channels"] == ["video_diary"]


def test_get_flourishing_trend_surfaces_channels(monkeypatch):
    from decimal import Decimal

    from mcp import tools_journal as tj

    rows = [
        {
            "pk": "USER#matthew#SOURCE#flourishing",
            "sk": "DATE#2026-07-25",
            "date": "2026-07-25",
            "values_lived_count": Decimal(2),
            "channels": ["journal", "video_diary"],
            "enrichment_model": "claude-haiku-4-5",
        }
    ]

    class _T:
        def query(self, **kw):
            return {"Items": rows}

    monkeypatch.setattr(tj, "table", _T())
    out = tj.tool_get_flourishing_trend({"days": 30})
    assert out["channels_present"] == ["journal", "video_diary"]


# ── AC4: end-to-end for one synthetic Video Diary entry ───────────────────────


def _enriched_video_diary_entry():
    """A Video Diary entry as it exists post-ingest + post-enrichment, carrying a
    grounded causal hint whose cause/effect both map to tracked metrics."""
    return {
        "pk": "USER#matthew#SOURCE#notion",
        "sk": "DATE#2026-07-25#journal#video_diary#56789abcdef0",
        "date": "2026-07-25",
        "template": "Video Diary",
        "channel": "video_diary",
        "enriched_at": "2026-07-25T03:00:00Z",
        "enriched_mood": 4,
        "enriched_themes": ["personal growth", "health anxiety"],
        "enriched_values_lived": ["discipline", "health"],
        "enriched_gratitude": ["the morning walk"],
        "enriched_causal_hints": [
            {
                "cause": "poor sleep last night",
                "effect": "low energy all day",
                "quote": "My energy was shot all day because I barely slept.",
            }
        ],
    }


def test_e2e_video_diary_produces_flourishing_row():
    entry = _enriched_video_diary_entry()
    row = fl.aggregate_entries([entry])
    assert row is not None
    assert "video_diary" in row["channels"]
    assert row["values_lived_count"] == 2


def test_e2e_video_diary_eligible_for_character_sheet():
    """The entry is in the character-sheet journal SK range AND collapses into a
    non-empty journal view (themes + mood_avg) — i.e. input-eligible."""
    import character_sheet_lambda as cs

    entry = _enriched_video_diary_entry()
    # #890 query range in fetch_journal_entries: DATE#{d}#journal# .. DATE#{d}#journal#zzz
    lo, hi = "DATE#2026-07-25#journal#", "DATE#2026-07-25#journal#zzz"
    assert lo <= entry["sk"] <= hi
    view = cs.merge_journal_view([entry])
    assert view is not None
    assert "personal growth" in view["themes"]
    assert "mood_avg" in view  # enriched_mood mapped onto the engine scale


def test_e2e_video_diary_yields_hypo_candidate():
    import journal_analyzer_lambda as ja

    entry = _enriched_video_diary_entry()
    cands = ja.build_hypo_candidates([(entry["date"], entry)])
    assert len(cands) == 1
    cand = cands[0]
    assert cand["cause_metric"] == "total_sleep_hrs"
    assert cand["effect_metric"] == "energy"
    assert cand["status"] == "testable"
    assert cand["quotes"][0]["quote"].startswith("My energy was shot")


# ── AC5: no new scoring signal ────────────────────────────────────────────────


def test_channel_is_provenance_only_not_a_scoring_signal():
    """A diary entry and a typed entry with identical enrichment produce identical
    flourishing signal values — channel changes provenance, never the score."""
    base = {"enriched_at": "t", "enriched_values_lived": ["health"], "enriched_ownership": 4}
    diary = fl.aggregate_entries([{**base, "channel": "video_diary"}])
    typed = fl.aggregate_entries([{**base, "channel": "journal"}])
    signal_keys = ("values_lived_count", "ownership_score", "gratitude_count", "growth_signals_count")
    assert {k: diary.get(k) for k in signal_keys} == {k: typed.get(k) for k in signal_keys}
    # ...only the provenance differs
    assert diary["channels"] != typed["channels"]
