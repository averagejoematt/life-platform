"""tests/test_panelcast_zeitgeist.py — #1178 free RSS zeitgeist for the Panel (offline).

The fetch (mocked urllib — no network in CI): title + first-sentence formatting,
per-feed/total caps, the tragedy keyword/category filter, fail-soft on dead feeds
and malformed XML, and the PANELCAST_ZEITGEIST kill switch. The wiring: headlines
flow into BOTH writer prompts (intro + weekly v1 + weekly v2 Elena pass) and into
the judge's ground truth; an empty fetch omits the block entirely and the
generation path is byte-identical to pre-#1178.
"""

import json
import logging
import os
import sys
import urllib.error

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

from emails import (
    coach_panel_podcast_lambda as panel,  # noqa: E402
    panelcast_zeitgeist as zg,  # noqa: E402
    podcast_script_v2 as psv2,  # noqa: E402
)

HEADLINES = [
    "England complete stunning comeback to reach final — Substitute's late double turns the semi-final around.",
    "Count Binface announces new policy platform — The satirical candidate promises croissants priced by law.",
]


# ── RSS fixtures + a urlopen mock ─────────────────────────────────────────────


def _rss(items) -> bytes:
    parts = ["<?xml version='1.0' encoding='UTF-8'?><rss version='2.0'><channel><title>feed</title>"]
    for it in items:
        cats = "".join(f"<category>{c}</category>" for c in it.get("categories", []))
        parts.append(f"<item><title>{it.get('title', '')}</title><description>{it.get('description', '')}</description>{cats}</item>")
    parts.append("</channel></rss>")
    return "".join(parts).encode("utf-8")


class _Resp:
    def __init__(self, raw):
        self._raw = raw

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _mock_feeds(monkeypatch, payload_by_url):
    """payload_by_url: url -> bytes (served) | Exception (raised). Returns the call log."""
    monkeypatch.setenv("PANELCAST_ZEITGEIST", "on")
    calls = []

    def _fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        calls.append({"url": url, "timeout": timeout})
        payload = payload_by_url[url]
        if isinstance(payload, Exception):
            raise payload
        return _Resp(payload)

    monkeypatch.setattr(zg.urllib.request, "urlopen", _fake_urlopen)
    return calls


def _feed_payloads(news=None, sport=None, culture=None):
    empty = _rss([])
    return {
        zg.ZEITGEIST_FEEDS[0]: news if news is not None else empty,
        zg.ZEITGEIST_FEEDS[1]: sport if sport is not None else empty,
        zg.ZEITGEIST_FEEDS[2]: culture if culture is not None else empty,
    }


# ── fetch_zeitgeist ───────────────────────────────────────────────────────────


def test_fetch_formats_title_plus_first_sentence_and_uses_timeout(monkeypatch):
    news = _rss(
        [
            {"title": "Quirky robot bakes 1,000 croissants", "description": "A bakery's new robot went viral. It also makes tea."},
            {"title": "Title only item"},
        ]
    )
    calls = _mock_feeds(monkeypatch, _feed_payloads(news=news))
    out = zg.fetch_zeitgeist()
    assert out[0] == "Quirky robot bakes 1,000 croissants — A bakery's new robot went viral."  # first sentence only
    assert out[1] == "Title only item"  # no description → title alone
    assert all(c["timeout"] == zg.FEED_TIMEOUT_SECONDS for c in calls) and len(calls) == 3


def test_fetch_caps_per_feed_and_total_and_dedups(monkeypatch):
    many = _rss([{"title": f"Benign story number {i}", "description": "Nice."} for i in range(10)])
    dup = _rss([{"title": "Benign story number 0", "description": "Nice."}] + [{"title": f"Sport story {i}"} for i in range(10)])
    _mock_feeds(monkeypatch, _feed_payloads(news=many, sport=dup, culture=many))
    out = zg.fetch_zeitgeist()
    assert len(out) <= zg.MAX_TOTAL == 12
    assert sum(1 for h in out if h.startswith("Benign story")) <= zg.MAX_PER_FEED + zg.MAX_PER_FEED  # ≤4 per feed
    assert out.count("Benign story number 0 — Nice.") == 1  # cross-feed dedup


def test_tragedy_filter_drops_grim_items_by_title_description_and_category(monkeypatch):
    news = _rss(
        [
            {"title": "Dozens killed in bridge collapse", "description": "Rescuers search the scene."},  # title term
            {"title": "Village remembers a quiet man", "description": "His funeral drew hundreds."},  # description term
            {"title": "Region on edge", "description": "Tensions rise.", "categories": ["War in Europe"]},  # category term
            {"title": "Otter learns to skateboard", "description": "The zoo's new star."},  # benign → kept
        ]
    )
    _mock_feeds(monkeypatch, _feed_payloads(news=news))
    out = zg.fetch_zeitgeist()
    assert out == ["Otter learns to skateboard — The zoo's new star."]
    # And the guard is word-bounded — "warm-up" must not trip the "war" term.
    assert zg._TRAGEDY_RE.search("A gentle warm-up before the award show") is None


def test_fetch_is_fail_soft_on_dead_feed_and_malformed_xml(monkeypatch):
    ok = _rss([{"title": "A cheerful headline", "description": "Lovely."}])
    _mock_feeds(
        monkeypatch,
        {
            zg.ZEITGEIST_FEEDS[0]: urllib.error.URLError("connection refused"),  # dead feed → skipped
            zg.ZEITGEIST_FEEDS[1]: b"<rss><channel><item>this never closes",  # malformed XML → skipped
            zg.ZEITGEIST_FEEDS[2]: ok,
        },
    )
    assert zg.fetch_zeitgeist() == ["A cheerful headline — Lovely."]


def test_fetch_all_feeds_down_returns_empty_list(monkeypatch):
    boom = urllib.error.URLError("no network")
    _mock_feeds(monkeypatch, {u: boom for u in zg.ZEITGEIST_FEEDS})
    assert zg.fetch_zeitgeist() == []


def test_kill_switch_off_makes_no_network_call(monkeypatch):
    monkeypatch.setenv("PANELCAST_ZEITGEIST", "off")
    monkeypatch.setattr(
        zg.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network call despite kill switch"))
    )
    assert zg.fetch_zeitgeist() == []


# ── the prompt + ground-truth blocks ─────────────────────────────────────────


def test_prompt_block_carries_headlines_and_rules_and_omits_when_empty():
    block = zg.zeitgeist_prompt_block(HEADLINES)
    assert "OPTIONAL TOPICAL COLOR" in block
    assert all(h in block for h in HEADLINES)
    for rule in ("at MOST 1-2", "never load-bearing", "NO details beyond the headline", "missed", "grim", "No partisan advocacy"):
        assert rule in block
    assert zg.zeitgeist_prompt_block([]) == ""


def test_truth_block_labels_headlines_as_provided_and_omits_when_empty():
    block = zg.zeitgeist_truth_block(HEADLINES)
    assert "TOPICAL HEADLINES provided to the writer (real, not inventions — do not flag references to them)" in block
    assert all(h in block for h in HEADLINES)
    assert zg.zeitgeist_truth_block([]) == ""


# ── writer-prompt wiring: intro + weekly v1 + weekly v2 ──────────────────────


def _capture_invoke(monkeypatch, reply_text="[]"):
    import bedrock_client

    bodies = []
    monkeypatch.setattr(bedrock_client, "invoke", lambda body, **k: bodies.append(body) or {"content": [{"text": reply_text}]})
    return bodies


def test_intro_prompt_carries_block_and_omits_when_empty(monkeypatch):
    monkeypatch.setattr(panel, "_intro_guest", lambda: {"name": "Dr. Eli Marsh", "role": "PI", "philosophy": "", "expertise": []})
    bodies = _capture_invoke(monkeypatch)
    panel._build_intro_script({"characters": {}}, zeitgeist=list(HEADLINES))
    user = bodies[-1]["messages"][0]["content"]
    assert "OPTIONAL TOPICAL COLOR" in user and HEADLINES[0] in user

    panel._build_intro_script({"characters": {}})  # no zeitgeist → the block is absent entirely
    assert "OPTIONAL TOPICAL COLOR" not in bodies[-1]["messages"][0]["content"]


def _weekly_beats(zeitgeist=None):
    beats = {
        "week": 3,
        "date": "2026-08-01",
        "title": "Week 3",
        "chronicle": "A solid week.",
        "coach_reads": [{"id": "sleep_coach", "name": "Dr. Sarah Chen", "summary": "Sleep held steady.", "themes": []}],
        "guest": {"id": "sleep_coach", "name": "Dr. Sarah Chen", "summary": "Sleep held steady.", "themes": []},
        "presence_note": "",
        "phase_block": "week one, day three",
        "last_open_bet": None,
        "recent_topics": [],
        "prev_guest": "",
    }
    if zeitgeist is not None:
        beats["zeitgeist"] = zeitgeist
    return beats


def test_weekly_v1_prompt_carries_block_and_omits_when_empty(monkeypatch):
    bodies = _capture_invoke(monkeypatch, reply_text='{"turns": []}')
    panel._build_weekly_script(_weekly_beats(zeitgeist=list(HEADLINES)), {})
    user = bodies[-1]["messages"][0]["content"]
    assert "OPTIONAL TOPICAL COLOR" in user and HEADLINES[1] in user

    panel._build_weekly_script(_weekly_beats(), {})  # no zeitgeist key at all → unchanged prompt
    assert "OPTIONAL TOPICAL COLOR" not in bodies[-1]["messages"][0]["content"]


def test_weekly_v2_elena_prompt_carries_block(monkeypatch):
    class _Boom:
        def get_item(self, **k):
            raise RuntimeError("offline")

        def query(self, **k):
            raise RuntimeError("offline")

    bodies = []
    deps = {
        "table": _Boom(),
        "s3": None,  # guest_voice_spec fail-softs
        "bucket": "b",
        "user_id": "matthew",
        "writer_model": "writer",
        "invoke": lambda body, **k: bodies.append(body) or {"content": [{"text": "not json"}]},
        "extract_json": panel._extract_json,
        "elena_host_state": lambda: "",
        "episode_angle": lambda w: "angle",
        "logger": logging.getLogger("test"),
    }
    out = psv2.build_weekly_script_v2(_weekly_beats(zeitgeist=list(HEADLINES)), {}, deps)
    assert out == {}  # pass-1 parse fails → v1 fallback; we only wanted the prompt
    user = bodies[0]["messages"][0]["content"]
    assert "OPTIONAL TOPICAL COLOR" in user and HEADLINES[0] in user


# ── run wiring: Episode 0 is EVERGREEN — the intro path never touches the zeitgeist ──


def test_run_intro_is_evergreen_never_fetches_zeitgeist_or_feeds_headlines(monkeypatch):
    # #1182: ep0 carries no dated content so the reset can resurrect it without staleness.
    # The intro path must NOT fetch the zeitgeist, must pass an EMPTY list to the builder,
    # and must NOT append the topical ground-truth block. (Weeklies keep topical color —
    # asserted in test_run_weekly_* above.)
    fetches, builder_zg, judged_gt = [], [], []
    monkeypatch.setattr(panel._zeitgeist, "fetch_zeitgeist", lambda *a, **k: fetches.append(1) or list(HEADLINES))
    monkeypatch.setattr(panel, "_load_bible", lambda: {"characters": {"matthew": "an ordinary, technical, curious person"}})
    clean_script = [
        {"speaker": ("elena" if i % 2 == 0 else "eli"), "line": "I'm Elena Voss and this is a clean, number-free line of dialogue."}
        for i in range(10)
    ]
    monkeypatch.setattr(
        panel, "_build_intro_script", lambda bible, zeitgeist=None: builder_zg.append(zeitgeist) or [dict(t) for t in clean_script]
    )
    monkeypatch.setattr(panel._repair, "repair_structure", lambda turns, *a, **k: (turns, [], []))
    monkeypatch.setattr(panel, "_craft_check", lambda turns, *a, **k: [])
    monkeypatch.setattr(panel, "_qa_review", lambda turns, rubric, gt="": judged_gt.append(gt) or (True, []))
    monkeypatch.setattr(panel.s3, "put_object", lambda **k: {})

    out = panel._run_intro(dry_run=True)
    assert json.loads(out["body"])["qa_pass"] is True
    assert fetches == []  # EVERGREEN — the intro path never fetches the zeitgeist
    assert builder_zg == [[]]  # the writer always receives an empty list on the intro path
    assert "TOPICAL HEADLINES" not in judged_gt[0] and HEADLINES[0] not in judged_gt[0]
    # Matt's bio truth is still the ground truth — only the topical block is gone.
    assert "an ordinary, technical, curious person" in judged_gt[0]


def _wire_weekly(monkeypatch, zeitgeist_result):
    """Offline _run_weekly harness (mirrors test_panelcast_repair) with a stubbed fetch."""
    panel._content_filter_cache = {"blocked_vices": [], "blocked_vice_keywords": []}
    fetches, judged_gt, builder_beats = [], [], []
    monkeypatch.setattr(panel._zeitgeist, "fetch_zeitgeist", lambda *a, **k: fetches.append(1) or list(zeitgeist_result))
    script = {
        "turns": [
            {"speaker": ("elena" if i % 2 == 0 else "coach"), "line": f"A clean, safe, number-free line of dialogue, take {'x' * (i + 1)}."}
            for i in range(8)
        ],
        "open_bet": "sleep stays steady",
        "last_bet_result": {"outcome": "none"},
        "pull_quote": "a quiet good week",
        "episode_title": "Quiet Good Week",
    }
    monkeypatch.setattr(panel, "_select_week_post", lambda: {"week": 3, "date": "2026-08-01", "title": "Week 3"})
    monkeypatch.setattr(panel, "_episode_exists", lambda w: False)
    monkeypatch.setattr(panel, "_load_bible", lambda: {})
    monkeypatch.setattr(panel, "_state_read", lambda: {})
    monkeypatch.setattr(panel, "_gather_week", lambda post, state: _weekly_beats())
    monkeypatch.setattr(panel, "_build_weekly_script_v2", lambda b, bb: builder_beats.append(b) or {})
    monkeypatch.setattr(panel, "_build_weekly_script", lambda b, bb: json.loads(json.dumps(script)))
    monkeypatch.setattr(panel, "_editor_review", lambda turns, bible: {"verdict": "pass", "issues": [], "pull_quote": ""})
    monkeypatch.setattr(panel, "_qa_review", lambda turns, rubric, gt="": judged_gt.append(gt) or (True, []))
    monkeypatch.setattr(panel, "_publish_episode_audio", lambda *a, **k: (_ for _ in ()).throw(AssertionError("published in dry run")))
    return fetches, judged_gt, builder_beats


def test_run_weekly_fetches_once_and_feeds_builders_and_ground_truth(monkeypatch):
    fetches, judged_gt, builder_beats = _wire_weekly(monkeypatch, HEADLINES)
    out = panel._run_weekly(force=False, dry_run=True)
    assert json.loads(out["body"])["would"] == "PUBLISH"
    assert fetches == [1]  # ONE fetch per run
    assert builder_beats[0]["zeitgeist"] == list(HEADLINES)  # both builders read beats["zeitgeist"]
    assert "TOPICAL HEADLINES provided to the writer" in judged_gt[0] and HEADLINES[1] in judged_gt[0]
    assert "Dr. Sarah Chen: Sleep held steady." in judged_gt[0]  # the real material is still the ground truth


def test_run_weekly_empty_fetch_leaves_generation_path_unchanged(monkeypatch):
    fetches, judged_gt, builder_beats = _wire_weekly(monkeypatch, [])
    out = panel._run_weekly(force=False, dry_run=True)
    assert json.loads(out["body"])["would"] == "PUBLISH"  # generation proceeds exactly as before
    assert builder_beats[0]["zeitgeist"] == []
    assert "TOPICAL HEADLINES" not in judged_gt[0]
