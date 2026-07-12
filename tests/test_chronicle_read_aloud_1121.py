"""#1121 — chronicle audio: per-article read-aloud join with a reset-safe key.

The reset key-invalidation class (ADR-077), pinned end-to-end:

  Producer (lambdas/emails/chronicle_podcast_lambda.py)
    1. Reads the LIVE chronicle manifest (generated/journal/posts.json), never
       the dead pre-v4 site/chronicle/posts.json that froze the show on the
       pre-reset back catalogue.
    2. Keys episodes by the article's publication DATE (ep-{date}.mp3) — week
       numbers repeat across resets, so a week key let a new cycle's Week N
       inherit the PRIOR cycle's MP3 through the idempotency check.
    3. Verifies content identity by title: the ±3-day DDB search alone once
       landed on a neighboring unpublished draft and would have voiced it
       under this article's name. Mismatch → honest skip, no episode.

  Join (site/assets/js/read_aloud.js, wired in dispatches.js)
    4. Per-article exact-date match against /podcast/episodes.json; a dangling
       key (stale pre-reset feed, missing episode) resolves to undefined so the
       reader renders NO player — honest-empty, never another cycle's voice.
       Executed for real via node (fixture-driven), not just string-pinned.
"""

import json
import os
import shutil
import subprocess
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import chronicle_podcast_lambda as cpl  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402

READ_ALOUD_JS = os.path.join(_REPO, "site", "assets", "js", "read_aloud.js")
DISPATCHES_JS = open(os.path.join(_REPO, "site", "assets", "js", "dispatches.js"), encoding="utf-8").read()


# ── producer: fakes ───────────────────────────────────────────────────────────


class FakeS3:
    """Dict-backed get/put/head — just enough surface for the lambda."""

    def __init__(self, objects=None):
        self.objects = dict(objects or {})
        self.puts = []

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise KeyError(Key)

        class _Body:
            def __init__(self, b):
                self._b = b

            def read(self):
                return self._b

        return {"Body": _Body(self.objects[Key])}

    def put_object(self, Bucket, Key, Body, **kw):
        body = Body if isinstance(Body, (bytes, bytearray)) else str(Body).encode("utf-8")
        self.objects[Key] = bytes(body)
        self.puts.append(Key)

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise KeyError(Key)
        return {"ContentLength": len(self.objects[Key])}


def _manifest(posts):
    return json.dumps({"posts": posts}).encode("utf-8")


def _ddb_row(date, title, md="Some prose.\n\nMore prose."):
    return {"pk": "USER#matthew#SOURCE#chronicle", "sk": f"DATE#{date}", "title": title, "content_markdown": md}


@pytest.fixture()
def wired(monkeypatch):
    """Wire the lambda to fakes; return (s3, set_table) for per-test seeding."""
    s3 = FakeS3()
    monkeypatch.setattr(cpl, "s3", s3)
    monkeypatch.setattr(cpl, "_synthesize", lambda text: b"MP3" + str(len(text)).encode())

    def set_table(rows):
        monkeypatch.setattr(cpl, "table", FakeDdbTable(rows=rows))

    set_table([])
    return s3, set_table


# ── 1. reads the live manifest, never the dead feed ──────────────────────────


def test_published_posts_reads_live_journal_manifest(wired):
    s3, _ = wired
    s3.objects["generated/journal/posts.json"] = _manifest([{"week": 0, "date": "2026-07-11", "title": "T"}])
    # the dead feed is present and DIFFERENT — it must not be what we read
    s3.objects["site/chronicle/posts.json"] = _manifest([{"week": 5, "date": "2026-05-03", "title": "Stale"}])
    posts = cpl._published_posts()
    assert [p["date"] for p in posts] == ["2026-07-11"]


def test_no_silent_fallback_to_dead_feed(wired):
    s3, _ = wired
    s3.objects["site/chronicle/posts.json"] = _manifest([{"week": 5, "date": "2026-05-03", "title": "Stale"}])
    # live manifest missing → the handler must 503, not voice the dead feed
    out = cpl.lambda_handler({}, None)
    assert out["statusCode"] == 503


# ── 2. reset-safe per-article keys ────────────────────────────────────────────


def test_episode_key_is_the_article_date_not_the_week():
    assert cpl._episode_slug("2026-07-06") == "ep-2026-07-06"
    src = open(os.path.join(_REPO, "lambdas", "emails", "chronicle_podcast_lambda.py"), encoding="utf-8").read()
    assert "wk{week}" not in src, "week-keyed artifacts reintroduce the reset collision (#1121)"


def test_reset_drill_new_cycle_week_never_inherits_prior_cycle_audio(wired):
    """The R2.2/R2.3 drill shape: a prior cycle's 'Week 1' MP3 already exists.
    The new cycle's Week 1 article (same week number, different date) must get
    its OWN render + its own key — never the stale object."""
    s3, set_table = wired
    s3.objects["generated/podcast/ep-2026-04-08.mp3"] = b"OLD-CYCLE-AUDIO"  # prior cycle wk1
    s3.objects["generated/journal/posts.json"] = _manifest([{"week": 1, "date": "2026-07-19", "title": "The First Week", "excerpt": "x"}])
    set_table([_ddb_row("2026-07-19", "The First Week")])
    out = cpl.lambda_handler({}, None)
    assert out["statusCode"] == 200
    eps = json.loads(s3.objects["generated/podcast/episodes.json"])["episodes"]
    assert [e["url"] for e in eps] == ["/podcast/ep-2026-07-19.mp3"]
    assert s3.objects["generated/podcast/ep-2026-07-19.mp3"] != b"OLD-CYCLE-AUDIO"
    assert "generated/podcast/ep-2026-07-19.mp3" in s3.puts  # freshly rendered


def test_two_same_week_articles_get_distinct_episodes(wired):
    """The live pre-start state: two curated prologues, both week 0."""
    s3, set_table = wired
    s3.objects["generated/journal/posts.json"] = _manifest(
        [
            {"week": 0, "date": "2026-07-06", "title": "Before the Numbers"},
            {"week": 0, "date": "2026-07-11", "title": "The Plan, On the Record"},
        ]
    )
    set_table([_ddb_row("2026-07-06", "Before the Numbers"), _ddb_row("2026-07-11", "The Plan, On the Record")])
    cpl.lambda_handler({}, None)
    eps = json.loads(s3.objects["generated/podcast/episodes.json"])["episodes"]
    assert [e["url"] for e in eps] == ["/podcast/ep-2026-07-11.mp3", "/podcast/ep-2026-07-06.mp3"]  # newest first, distinct
    feed = s3.objects["generated/podcast/feed.xml"].decode("utf-8")
    assert "measured-life-2026-07-11" in feed and "measured-life-2026-07-06" in feed
    assert "measured-life-wk" not in feed  # guids are per-article too


# ── 3. content identity verified by title (no neighboring-draft voicing) ─────


def test_content_for_rejects_neighboring_record_with_different_title(wired):
    _, set_table = wired
    # The real 2026-07-12 incident shape: the article dated 07-06 has no DDB row,
    # but an UNPUBLISHED pilot draft sits one day away at 07-07.
    set_table([_ddb_row("2026-07-07", "The Ghost in the Machine")])
    assert cpl._content_for("2026-07-06", "Before the Numbers") is None


def test_content_for_accepts_offset_record_with_matching_title(wired):
    _, set_table = wired
    set_table([_ddb_row("2026-07-07", "Before the Numbers", md="MD-BODY")])
    assert cpl._content_for("2026-07-06", "Before the Numbers") == "MD-BODY"


def test_unverified_content_means_honest_empty_not_wrong_audio(wired):
    s3, set_table = wired
    s3.objects["generated/journal/posts.json"] = _manifest([{"week": 0, "date": "2026-07-06", "title": "Before the Numbers"}])
    set_table([_ddb_row("2026-07-07", "The Ghost in the Machine")])
    out = cpl.lambda_handler({}, None)
    assert out["statusCode"] == 200
    eps = json.loads(s3.objects["generated/podcast/episodes.json"])["episodes"]
    assert eps == []  # nothing indexed → the join dangles → the reader shows no player


def test_narration_carries_no_week_number(wired):
    """Week numbers repeat across cycles — they must not be baked into the
    permanent audio artifact's spoken intro."""
    s3, set_table = wired
    spoken = []
    cpl._synthesize = lambda text: (spoken.append(text), b"MP3")[1]
    s3.objects["generated/journal/posts.json"] = _manifest([{"week": 1, "date": "2026-07-19", "title": "The First Week"}])
    set_table([_ddb_row("2026-07-19", "The First Week")])
    cpl.lambda_handler({}, None)
    assert spoken and "issue 1" not in spoken[0]
    assert spoken[0].startswith("The Measured Life: The First Week.")


# ── 4. the front-end join: fixture-executed via node ─────────────────────────

_NODE = shutil.which("node")

# The live pre-start state (2026-07-12, genesis Day 1, cycle 5): 2 curated
# prologues; the read-aloud feed still holds season-1 episodes (Feb–May) —
# every one a dangling key against the current articles.
STALE_SEASON1_FEED = [
    {"week": 5, "date": "2026-05-03", "url": "/podcast/wk5.mp3"},
    {"week": 0, "date": "2026-02-22", "url": "/podcast/wk0.mp3"},
    {"week": -1, "date": "2026-04-01", "url": "/podcast/wk-1.mp3"},
]


def _run_join(ent, episodes):
    script = (
        f"import {{ readAloudFor }} from {json.dumps('file://' + READ_ALOUD_JS)};\n"
        f"const out = readAloudFor({json.dumps(ent)}, {json.dumps(episodes)});\n"
        "console.log(JSON.stringify(out === undefined ? null : out));\n"
    )
    r = subprocess.run([_NODE, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip())


@pytest.mark.skipif(_NODE is None, reason="node not installed")
def test_dangling_key_resolves_to_honest_empty():
    # both live prologues vs the stale season-1 feed → no match, no player
    for date in ("2026-07-06", "2026-07-11"):
        assert _run_join({"id": date, "week": 0, "date": date}, STALE_SEASON1_FEED) is None


@pytest.mark.skipif(_NODE is None, reason="node not installed")
def test_same_week_number_alone_never_matches():
    # season-1 wk0 exists; the current wk0 article must NOT inherit it (the
    # original bug class: bare-week join → another cycle's voice)
    ent = {"id": "2026-07-06", "week": 0, "date": "2026-07-06"}
    assert _run_join(ent, STALE_SEASON1_FEED) is None


@pytest.mark.skipif(_NODE is None, reason="node not installed")
def test_exact_date_match_returns_this_articles_episode():
    feed = STALE_SEASON1_FEED + [{"week": 0, "date": "2026-07-06", "url": "/podcast/ep-2026-07-06.mp3"}]
    got = _run_join({"id": "2026-07-06", "week": 0, "date": "2026-07-06"}, feed)
    assert got and got["url"] == "/podcast/ep-2026-07-06.mp3"


@pytest.mark.skipif(_NODE is None, reason="node not installed")
def test_two_same_week_articles_resolve_to_their_own_audio():
    feed = [
        {"week": 0, "date": "2026-07-06", "url": "/podcast/ep-2026-07-06.mp3"},
        {"week": 0, "date": "2026-07-11", "url": "/podcast/ep-2026-07-11.mp3"},
    ]
    assert _run_join({"id": "2026-07-06", "week": 0, "date": "2026-07-06"}, feed)["url"] == "/podcast/ep-2026-07-06.mp3"
    assert _run_join({"id": "2026-07-11", "week": 0, "date": "2026-07-11"}, feed)["url"] == "/podcast/ep-2026-07-11.mp3"


@pytest.mark.skipif(_NODE is None, reason="node not installed")
def test_entry_without_a_date_is_honest_empty():
    assert _run_join({"id": "1", "week": 1}, STALE_SEASON1_FEED) is None


# ── 5. wiring pins over dispatches.js (house string-presence pattern) ─────────


def _podcast_episode_body():
    i = DISPATCHES_JS.index("async function podcastEpisode")
    j = DISPATCHES_JS.index("\n}", i)
    return DISPATCHES_JS[i:j]


def test_chronicle_join_reads_the_read_aloud_feed_via_the_pure_join():
    body = _podcast_episode_body()
    code = "\n".join(ln for ln in body.splitlines() if not ln.strip().startswith("//"))
    assert '"/podcast/episodes.json"' in code
    assert "readAloudFor(" in code
    assert "/panelcast/" not in code  # the borrowed-panel join is gone (comments excluded)
    assert 'import { readAloudFor } from "/assets/js/read_aloud.js"' in DISPATCHES_JS


def test_week_window_join_is_gone():
    assert "gap <= 14" not in DISPATCHES_JS, "the week+window join is the reset-unsafe class (#1121)"


def test_missing_episode_renders_no_player():
    # the listen block only exists inside the episode-truthy branch
    i = DISPATCHES_JS.index("#1121 honest-empty")
    j = i + 800
    block = DISPATCHES_JS[i:j]
    assert "const listen = episode" in block and ': "";' in block
