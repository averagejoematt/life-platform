"""tests/test_chronicle_recap.py — Elena's "previously on" recap (backend serial phase 3).

Covers the recap loop:
  * build_recap grounds ONLY in published installments + arc (the deterministic
    date cross-check drops any beat citing a non-published date),
  * the raw-vitals guard (a recap is narrative, never a data readout),
  * thin-history (<2 published installments → story_so_far only),
  * privacy gate + fail-soft (a recap error never aborts the chronicle),
  * the approve lambda commits RECAP#latest + RECAP#{date} from draft_recap_json,
  * the /api/recap endpoint: honest-null, payload, and stale-record withhold,
  * RECAP# under the chronicle partition is EXPERIMENT_SCOPED (reset-safe).

All offline — call_anthropic + DynamoDB are mocked / fail through.
"""

import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

import chronicle_approve_lambda as approve  # noqa: E402
import phase_taxonomy  # noqa: E402
import wednesday_chronicle_lambda as chron  # noqa: E402
from web import site_api_coach as capi  # noqa: E402

PUBLISHED = [
    {
        "date": "2026-06-24",
        "week_number": 2,
        "title": "The Week That Decided",
        "status": "published",
        "content_markdown": "Week two prose.",
    },
    {"date": "2026-06-17", "week_number": 1, "title": "Monday Was a 49", "status": "published", "content_markdown": "Week one prose."},
]


def _data(prev=None, arc=None):
    return {"prev_installments": prev if prev is not None else list(PUBLISHED), "narrative_arc": arc, "experiment_arc": None}


def _mock_llm(monkeypatch, payload):
    monkeypatch.setattr(chron, "get_anthropic_key", lambda: "k")
    monkeypatch.setattr(
        chron, "call_anthropic", lambda system, user, key: json.dumps(payload) if isinstance(payload, (dict, list)) else payload
    )


# ── build_recap: shape + grounding ───────────────────────────────────────────


def test_build_recap_returns_shape(monkeypatch):
    _mock_llm(
        monkeypatch,
        {
            "story_so_far": "Matthew began measuring everything, and the data started talking back.",
            "recent_beats": [
                {"week": 2, "date": "2026-06-24", "beat": "The week the habits finally held."},
                {"week": 1, "date": "2026-06-17", "beat": "A rough Monday set the tone."},
            ],
            "where_we_are_now": "Two weeks in, the baseline is forming.",
            "threads_to_watch": ["Will sleep hold?", "Protein adherence."],
        },
    )
    r = chron.build_recap(_data())
    assert r["story_so_far"].startswith("Matthew began")
    assert len(r["recent_beats"]) == 2
    assert r["as_of"] == "2026-06-24" and r["as_of_week"] == 2
    assert r["experiment_day"] and r["author"] == "Elena Voss"
    assert set(r) >= {"story_so_far", "recent_beats", "where_we_are_now", "threads_to_watch", "grounded_in"}


def test_date_cross_check_drops_unpublished_beat(monkeypatch):
    _mock_llm(
        monkeypatch,
        {
            "story_so_far": "The story so far, grounded.",
            "recent_beats": [
                {"week": 2, "date": "2026-06-24", "beat": "Real, published week."},
                {"week": 9, "date": "2026-09-01", "beat": "An invented future week."},
            ],
            "where_we_are_now": "here",
            "threads_to_watch": [],
        },
    )
    r = chron.build_recap(_data())
    dates = [b["date"] for b in r["recent_beats"]]
    assert dates == ["2026-06-24"]  # the fabricated 2026-09-01 beat is dropped


def test_raw_vitals_guard_drops_beat_and_rejects_story(monkeypatch):
    # A beat smuggling a vital is dropped...
    _mock_llm(
        monkeypatch,
        {
            "story_so_far": "Clean narrative prose.",
            "recent_beats": [{"week": 2, "date": "2026-06-24", "beat": "He hit 232 lbs this week."}],
            "where_we_are_now": "",
            "threads_to_watch": [],
        },
    )
    r = chron.build_recap(_data())
    assert r["recent_beats"] == []
    # ...and a story_so_far citing a vital rejects the whole recap.
    _mock_llm(
        monkeypatch, {"story_so_far": "His HRV climbed to 45 ms.", "recent_beats": [], "where_we_are_now": "", "threads_to_watch": []}
    )
    assert chron.build_recap(_data()) is None


def test_thin_history_blanks_beats(monkeypatch):
    _mock_llm(
        monkeypatch,
        {
            "story_so_far": "It begins.",
            "recent_beats": [{"week": 1, "date": "2026-06-17", "beat": "first"}],
            "where_we_are_now": "early",
            "threads_to_watch": ["a"],
        },
    )
    one = [{"date": "2026-06-17", "week_number": 1, "title": "Monday Was a 49", "status": "published", "content_markdown": "x"}]
    r = chron.build_recap(_data(prev=one))
    assert r["story_so_far"] == "It begins."
    assert r["recent_beats"] == [] and r["threads_to_watch"] == []  # <2 published → blanked


def test_no_published_history_returns_none(monkeypatch):
    _mock_llm(monkeypatch, {"story_so_far": "x", "recent_beats": [], "where_we_are_now": "", "threads_to_watch": []})
    drafts = [{"date": "2026-06-24", "week_number": 2, "status": "draft", "content_markdown": "x"}]
    assert chron.build_recap(_data(prev=drafts)) is None  # a draft is not published history


def test_privacy_gate_drops_recap(monkeypatch):
    _mock_llm(monkeypatch, {"story_so_far": "ok", "recent_beats": [], "where_we_are_now": "", "threads_to_watch": []})

    def _boom(text, context=""):
        raise chron.privacy_guard.PrivacyViolation([("x", "real name")])

    monkeypatch.setattr(chron.privacy_guard, "assert_clean", _boom)
    assert chron.build_recap(_data()) is None


def test_build_recap_is_failsoft(monkeypatch):
    monkeypatch.setattr(chron, "get_anthropic_key", lambda: "k")

    def _raise(system, user, key):
        raise RuntimeError("bedrock down")

    monkeypatch.setattr(chron, "call_anthropic", _raise)
    assert chron.build_recap(_data()) is None  # never propagates


def test_parse_recap_json_handles_fence():
    assert chron._parse_recap_json('{"story_so_far": "a"}')["story_so_far"] == "a"
    fenced = '```json\n{"story_so_far": "b"}\n```'
    assert chron._parse_recap_json(fenced)["story_so_far"] == "b"
    assert chron._parse_recap_json("not json") is None


# ── approve: commits the recap at publish ─────────────────────────────────────


def test_commit_recap_writes_latest_and_dated(monkeypatch):
    writes = []
    monkeypatch.setattr(approve.table, "put_item", lambda Item: writes.append(Item))
    recap = {"story_so_far": "s", "recent_beats": [], "as_of": "2026-06-24", "experiment_day": 11}
    item = {"date": "2026-06-24", "sk": "DATE#2026-06-24", "draft_recap_json": json.dumps(recap)}
    approve._commit_recap(item)
    sks = sorted(w["sk"] for w in writes)
    assert sks == ["RECAP#2026-06-24", "RECAP#latest"]
    assert all(w["pk"] == approve.CHRONICLE_PK and w["source"] == "chronicle_recap" for w in writes)


def test_commit_recap_noop_without_draft(monkeypatch):
    writes = []
    monkeypatch.setattr(approve.table, "put_item", lambda Item: writes.append(Item))
    approve._commit_recap({"date": "2026-06-24", "sk": "DATE#2026-06-24"})  # no draft_recap_json
    assert writes == []


# ── /api/recap endpoint ───────────────────────────────────────────────────────


def test_endpoint_honest_null_when_absent(monkeypatch):
    monkeypatch.setattr(capi.table, "get_item", lambda Key: {})
    resp = capi.handle_recap()
    assert json.loads(resp["body"])["recap"] is None


def test_endpoint_returns_recap(monkeypatch):
    rec = {
        "story_so_far": "s",
        "recent_beats": [{"week": 2, "date": "2026-06-24", "beat": "b"}],
        "experiment_day": 11,
        "as_of": "2026-06-24",
    }
    monkeypatch.setattr(capi.table, "get_item", lambda Key: {"Item": rec})
    monkeypatch.setattr(capi, "_current_day_n", lambda: 16)
    body = json.loads(capi.handle_recap()["body"])
    assert body["recap"]["story_so_far"] == "s"
    assert body["recap"]["recent_beats"][0]["date"] == "2026-06-24"


def test_endpoint_withholds_stale_record(monkeypatch):
    rec = {"story_so_far": "stale", "experiment_day": 400, "as_of": "2027-01-01"}
    monkeypatch.setattr(capi.table, "get_item", lambda Key: {"Item": rec})
    monkeypatch.setattr(capi, "_current_day_n", lambda: 16)
    assert json.loads(capi.handle_recap()["body"])["recap"] is None  # day 400 > current 16 → withheld


# ── reset safety ──────────────────────────────────────────────────────────────


def test_recap_is_experiment_scoped():
    assert phase_taxonomy.classify("USER#matthew#SOURCE#chronicle", "RECAP#latest") == phase_taxonomy.EXPERIMENT_SCOPED
