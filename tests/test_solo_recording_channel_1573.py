"""tests/test_solo_recording_channel_1573.py — #1573 (epic #1564).

The solo-recording transcription leg: a recording made WITHOUT Claude in the room
is transcribed LOCALLY (Whisper on Matthew's machine — audio never leaves) and
lands as a "Solo Recording" Notion page that flows the EXISTING journal pipeline
(notion → enrichment → flourishing → character → hypothesis) with a distinct
`channel="solo_recording"` provenance — no second pipeline (the #1572 principle,
extended). Pins:

  AC1 — scripts/transcribe_solo.py builds a Solo Recording Notion page whose body
        is the transcript and whose properties carry only a POINTER to the source
        recording — the audio/video bytes are never uploaded.
  AC2 — notion_lambda ingests Solo Recording (dedicated SK suffix, multi-per-day,
        channel stamp); journal_enrichment does NOT whitelist templates.
  AC3 — channel provenance is carried on the entry + projected onto the
        flourishing row, and surfaces in get_mood / get_flourishing_trend
        distinctly from journal AND video_diary.
  AC4 — one synthetic Solo Recording entry produces a flourishing row and is
        eligible for the character-sheet journal view (dry-run, like #1572).
  AC5 — regression guard: channel is provenance only; the enriched signals a solo
        recording contributes are the same ones typed journal already does.
"""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in (
    os.path.join(ROOT, "lambdas"),
    os.path.join(ROOT, "lambdas", "ingestion"),
    os.path.join(ROOT, "lambdas", "intelligence"),
    os.path.join(ROOT, "lambdas", "compute"),
    os.path.join(ROOT, "scripts"),
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
import transcribe_solo as ts  # noqa: E402


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


# ── AC1: local transcription script → Notion landing (pointer, not audio) ──────


def test_script_channel_constants_match_pipeline():
    """The script's Template/channel literals MUST match the ingestion lambda +
    flourishing so the landed page keys the right channel."""
    assert ts.SOLO_TEMPLATE == "Solo Recording"
    assert ts.SOLO_CHANNEL == fl.CHANNEL_SOLO_RECORDING == "solo_recording"
    assert nl.TEMPLATE_SK[ts.SOLO_TEMPLATE] == ts.SOLO_CHANNEL


def test_build_notion_payload_lands_solo_template_with_transcript_body():
    payload = ts.build_notion_page_payload(
        database_id="db123",
        date_str="2026-07-25",
        transcript="Talked through my training week alone into the mic.",
        source_file="/Users/matthew/Recordings/2026-07-25-solo.m4a",
        duration_seconds=182.4,
    )
    assert payload["parent"] == {"database_id": "db123"}
    assert payload["properties"]["Template"] == {"select": {"name": "Solo Recording"}}
    assert payload["properties"]["Date"]["date"]["start"] == "2026-07-25"
    # transcript is the page BODY
    body = payload["children"][0]["paragraph"]["rich_text"][0]["text"]["content"]
    assert "Talked through my training week" in body


def test_build_notion_payload_records_pointer_not_audio_bytes():
    """AC2: only a POINTER (basename + duration) is recorded — never the file
    bytes, never an absolute path leaking the whole tree."""
    payload = ts.build_notion_page_payload(
        database_id="db123",
        date_str="2026-07-25",
        transcript="x",
        source_file="/Users/matthew/Recordings/2026-07-25-solo.m4a",
        duration_seconds=182.4,
    )
    src = payload["properties"]["Source File"]["rich_text"][0]["text"]["content"]
    assert src == "2026-07-25-solo.m4a"  # basename pointer only
    assert payload["properties"]["Duration (s)"]["number"] == 182.4
    blob = ts.json.dumps(payload)
    assert "/Users/matthew/Recordings" not in blob  # absolute path never lands
    assert "audio" not in payload["properties"]  # no bytes/base64 uploaded


def test_build_notion_payload_chunks_long_transcript():
    """A transcript longer than one Notion text object splits into multiple blocks
    (each ≤ the 2000-char cap) — nothing is dropped."""
    long_text = "word " * 800  # 4000 chars
    payload = ts.build_notion_page_payload("db", "2026-07-25", long_text, "a.m4a")
    assert len(payload["children"]) >= 2
    joined = "".join(b["paragraph"]["rich_text"][0]["text"]["content"] for b in payload["children"])
    assert joined == long_text


def test_transcribe_rejects_unknown_engine():
    try:
        ts.transcribe("a.m4a", "cloud-api", "base")
        assert False, "expected ValueError"
    except ValueError as e:
        assert "unknown engine" in str(e)


def test_transcribe_whisper_cpp_requires_binary():
    try:
        ts.transcribe("a.m4a", "whisper.cpp", "model.bin", binary=None)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "--binary" in str(e)


# ── AC2: notion ingestion ─────────────────────────────────────────────────────


def test_solo_recording_registered_and_multi_per_day():
    assert nl.TEMPLATE_SK["Solo Recording"] == "solo_recording"
    assert "Solo Recording" in nl.MULTI_PER_DAY


def test_build_sk_solo_recording_uses_dedicated_stable_suffix():
    sk = nl.build_sk("2026-07-25", "Solo Recording", page_id="abcd1234-ef56-7890-1234-56789abcdef0")
    assert sk == "DATE#2026-07-25#journal#solo_recording#56789abcdef0"
    assert "#journal#" in sk  # stays inside the shared journal pipeline surface
    # idempotent
    assert sk == nl.build_sk("2026-07-25", "Solo Recording", page_id="abcd1234-ef56-7890-1234-56789abcdef0")


def test_parse_page_stamps_solo_recording_channel(monkeypatch):
    monkeypatch.setattr(nl, "_archive_page_raw", lambda *a, **k: None)
    date_str, template, item = nl.parse_page(_page("Solo Recording"), api_key=None)
    assert template == "Solo Recording"
    assert item["channel"] == "solo_recording"
    assert item["date"] == "2026-07-25"


def test_enrichment_does_not_whitelist_solo_recording(monkeypatch):
    """The enricher keeps ANY `#journal#` entry — no template allowlist strands a
    solo-recording transcript."""
    import journal_enrichment_lambda as je

    mixed = [
        {"sk": "DATE#2026-07-25#journal#solo_recording#56789abcdef0", "raw_text": "x"},
        {"sk": "DATE#2026-07-25#journal#evening", "raw_text": "y"},
        {"sk": "DATE#2026-07-25#WORKOUT#1", "raw_text": "z"},
    ]

    class _T:
        def query(self, **kw):
            return {"Items": mixed}

    monkeypatch.setattr(je, "table", _T())
    kept = je.query_journal_entries("2026-07-24", "2026-07-25")
    sks = [e["sk"] for e in kept]
    assert "DATE#2026-07-25#journal#solo_recording#56789abcdef0" in sks
    assert not any("WORKOUT" in s for s in sks)


# ── AC3: channel provenance (distinct from journal AND video_diary) ───────────


def test_entry_channel_derivation():
    assert fl.entry_channel({"channel": "solo_recording"}) == "solo_recording"
    assert fl.entry_channel({"template": "Solo Recording"}) == "solo_recording"  # fallback from template
    # video_diary and typed journal are unaffected by the new channel
    assert fl.entry_channel({"template": "Video Diary"}) == "video_diary"
    assert fl.entry_channel({"template": "Evening"}) == "journal"
    assert fl.entry_channel({}) == "journal"
    # explicit stored channel wins over template
    assert fl.entry_channel({"channel": "journal", "template": "Solo Recording"}) == "journal"


def test_flourishing_row_carries_three_way_channel_breakdown():
    row = fl.aggregate_entries(
        [
            {"enriched_at": "t", "channel": "solo_recording", "enriched_values_lived": ["health"]},
            {"enriched_at": "t", "channel": "video_diary", "enriched_gratitude": ["a"]},
            {"enriched_at": "t", "channel": "journal", "enriched_gratitude": ["b"]},
        ]
    )
    assert row["channels"] == ["journal", "solo_recording", "video_diary"]
    assert row["channel_entry_counts"] == {"solo_recording": 1, "video_diary": 1, "journal": 1}


def test_get_mood_surfaces_solo_recording_channel(monkeypatch):
    from mcp import tools_journal as tj

    items = [
        {
            "date": "2026-07-25",
            "template": "Solo Recording",
            "channel": "solo_recording",
            "enriched_mood": 4,
            "enriched_themes": ["growth"],
        },
        {"date": "2026-07-24", "template": "Evening", "channel": "journal", "enriched_mood": 3},
    ]
    monkeypatch.setattr(tj, "_query_journal", lambda *a, **k: items)
    out = tj._get_mood_trend({})
    assert out["channels_present"] == ["journal", "solo_recording"]
    assert "solo-recording" in out["channel_note"]
    day = {d["date"]: d for d in out["trend"]}
    assert day["2026-07-25"]["channels"] == ["solo_recording"]


def test_get_flourishing_trend_surfaces_solo_recording(monkeypatch):
    from decimal import Decimal

    from mcp import tools_journal as tj

    rows = [
        {
            "pk": "USER#matthew#SOURCE#flourishing",
            "sk": "DATE#2026-07-25",
            "date": "2026-07-25",
            "values_lived_count": Decimal(2),
            "channels": ["journal", "solo_recording"],
            "enrichment_model": "claude-haiku-4-5",
        }
    ]

    class _T:
        def query(self, **kw):
            return {"Items": rows}

    monkeypatch.setattr(tj, "table", _T())
    out = tj.tool_get_flourishing_trend({"days": 30})
    assert out["channels_present"] == ["journal", "solo_recording"]


# ── AC4: end-to-end for one synthetic Solo Recording entry ────────────────────


def _enriched_solo_entry():
    return {
        "pk": "USER#matthew#SOURCE#notion",
        "sk": "DATE#2026-07-25#journal#solo_recording#56789abcdef0",
        "date": "2026-07-25",
        "template": "Solo Recording",
        "channel": "solo_recording",
        "enriched_at": "2026-07-25T03:00:00Z",
        "enriched_mood": 4,
        "enriched_themes": ["personal growth", "solitude"],
        "enriched_values_lived": ["discipline", "reflection"],
        "enriched_gratitude": ["the quiet morning"],
    }


def test_e2e_solo_recording_produces_flourishing_row():
    row = fl.aggregate_entries([_enriched_solo_entry()])
    assert row is not None
    assert "solo_recording" in row["channels"]
    assert row["values_lived_count"] == 2


def test_e2e_solo_recording_eligible_for_character_sheet():
    import character_sheet_lambda as cs

    entry = _enriched_solo_entry()
    lo, hi = "DATE#2026-07-25#journal#", "DATE#2026-07-25#journal#zzz"
    assert lo <= entry["sk"] <= hi  # in the character-sheet journal SK range
    view = cs.merge_journal_view([entry])
    assert view is not None
    assert "personal growth" in view["themes"]
    assert "mood_avg" in view


# ── AC5: no new scoring signal ────────────────────────────────────────────────


def test_channel_is_provenance_only_not_a_scoring_signal():
    base = {"enriched_at": "t", "enriched_values_lived": ["health"], "enriched_ownership": 4}
    solo = fl.aggregate_entries([{**base, "channel": "solo_recording"}])
    typed = fl.aggregate_entries([{**base, "channel": "journal"}])
    signal_keys = ("values_lived_count", "ownership_score", "gratitude_count", "growth_signals_count")
    assert {k: solo.get(k) for k in signal_keys} == {k: typed.get(k) for k in signal_keys}
    assert solo["channels"] != typed["channels"]  # ...only provenance differs
