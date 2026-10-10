"""tests/test_story_door_pace_flag_4674.py — #4674: "pace flag" is a cut term every final reader-surface check refuses,
and a week's chapter and Panel episode carry ONE title on BOTH Panel writers (the Story Desk path and the legacy writer).

Week 2's divergent episode title ("Nine Days and Counting" under the chapter "Nine Days and No Rest") came from the
LEGACY writer, so the legacy path is driven end to end here, not just the shared helper."""

from __future__ import annotations

import json
import os
import sys

for k, v in {
    "TABLE_NAME": "life-platform",
    "S3_BUCKET": "matthew-life-platform",
    "USER_ID": "matthew",
    "AWS_REGION": "us-west-2",
    "AWS_DEFAULT_REGION": "us-west-2",
    "EMAIL_RECIPIENT": "test@example.com",
    "EMAIL_SENDER": "noreply@example.com",
}.items():
    os.environ.setdefault(k, v)

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

from ai import gemini_tts  # noqa: E402
from content import story_checks  # noqa: E402
from emails import (
    coach_panel_podcast_lambda as panel,  # noqa: E402
    panelcast_desk,  # noqa: E402
)

CHAPTER = "Nine Days and No Rest"
OWN = "Nine Days and Counting"


def _cut_terms():
    with open(os.path.join(_REPO, "site", "data", "glossary.json"), encoding="utf-8") as f:
        g = json.load(f)
    entries = g if isinstance(g, list) else next(v for v in g.values() if isinstance(v, list) and v and isinstance(v[0], dict))
    return {e["term"] for e in entries if e.get("ruling") == "cut"}


# ── the vocabulary check ────────────────────────────────────────────────────


def test_pace_flag_is_cut_in_the_registry_and_the_story_door_copy_is_inside_it():
    assert "pace flag" in _cut_terms()
    assert set(story_checks._CUT_TERMS) <= _cut_terms()


def test_every_spelling_of_the_cut_term_is_refused_and_plain_prose_passes():
    for spelling in ("pace flag", "Pace_Flag", "pace-flag", "PACE-FLAG", "pace‑flag", "pace–flag", "pace  flag"):
        text = f"By Thursday the {spelling} is live, and the week reads differently."
        assert any("vocabulary:" in f for f in story_checks.story_door(text)), spelling
        assert any("vocabulary:" in f for f in story_checks.reader_surface(text)), spelling  # the final publish check
    plain = "By Thursday he was on pace, and the flag on the week read differently. Spaceflag and pace-flagged are words."
    assert story_checks.story_door("By Thursday he was on pace, and the week read differently.") == []
    assert not any("vocabulary:" in f for f in story_checks.reader_surface(plain))


def test_the_panel_door_refuses_the_cut_term_in_titles_excerpts_and_spoken_lines():
    """The Panel's final checks — door_reasons (desk title/excerpt hold), door_safe (legacy title/excerpt fall back to
    nothing) and the per-line safety gate both writers share — all route through reader_surface."""
    assert panelcast_desk.door_reasons("The pace-flag week") == ["story-door"]
    assert panelcast_desk.door_reasons(CHAPTER) == []
    assert panelcast_desk.door_safe("When the pace flag went up") == ""
    assert panelcast_desk.door_safe(CHAPTER) == CHAPTER
    assert "story-door" in panel._safety_gate("The pace_flag tripped on Thursday, Elena.")
    assert panel._safety_gate("He was on pace by Thursday, Elena.") == []


# ── one title: the helper ───────────────────────────────────────────────────


def test_the_episode_carries_the_chapters_title():
    assert panelcast_desk.episode_title({"title": CHAPTER}, {"title": OWN}) == CHAPTER
    assert panelcast_desk.episode_title({}, {"title": OWN}) == OWN  # fallback only when the chapter has none
    assert panelcast_desk.episode_title({"title": "Week 3"}, {"title": OWN}) == OWN  # the no-chapter placeholder is not a title


# ── one title: the desk path's two call sites ───────────────────────────────

_EP = {
    "title": OWN,
    "excerpt": "x",
    "turns": [{"speaker": "elena", "line": "Day 9."}, {"speaker": "coach", "line": "And he still has not rested."}],
    "guest": {"name": "Marcus Webb", "coach_id": "nutrition_coach", "persona_id": "marcus_webb"},
    "bet": {"claim": "recovery below 60 on Thursday"},
}


class _S3:
    def __init__(self):
        self.puts = []

    def put_object(self, **kw):
        self.puts.append(kw)

    def get_object(self, **_):
        raise KeyError("no episodes.json yet")


def _stub_publish(monkeypatch):
    """Every side effect after the gates, captured: what the feed index would be written with."""
    seen: dict = {}
    monkeypatch.setattr(gemini_tts, "synthesize_dialogue", lambda *a, **k: b"RIFF")
    monkeypatch.setattr(panel, "_gemini_voice", lambda pid: "voice")
    monkeypatch.setattr(panel, "_publish_episode_audio", lambda week, audio: {"url": "u", "bytes": 4, "duration_sec": 1})
    monkeypatch.setattr(panel, "s3", _S3())
    monkeypatch.setattr(panel, "_state_read", lambda: {})
    monkeypatch.setattr(panel, "_state_write", lambda st: seen.setdefault("state", st))
    monkeypatch.setattr(panel, "_write_indexes", lambda eps: seen.setdefault("episodes", eps))
    monkeypatch.setattr(panel, "_write_show_memory", lambda *a, **k: None)
    monkeypatch.setattr(panel, "_emit_published_metric", lambda: None)
    monkeypatch.setattr(panel, "_emit_outcome", lambda reason: None)
    monkeypatch.setattr(panel, "_notify_new_episode", lambda ep: None)
    return seen


def test_the_desk_path_publishes_the_chapters_title(monkeypatch):
    """Call site 2 (the published record). Reverting it to the episode's own title publishes OWN and fails here."""
    seen = _stub_publish(monkeypatch)
    out = panel._publish_desk_episode(2, {"date": "2026-09-15", "title": CHAPTER}, dict(_EP), dry_run=False)
    assert json.loads(out["body"])["published"] is True
    assert [e["title"] for e in seen["episodes"]] == [f"EP2 · {CHAPTER}"]


def test_the_desk_path_door_checks_the_title_it_will_publish(monkeypatch):
    """Call site 1 (the hold check). The chapter title is what gets published, so it is what the door reads: a cut
    term in the CHAPTER title holds even though the episode's own title is clean. Reverting the check to the episode's
    own title lets it through to PUBLISH and fails here."""
    clean = panel._publish_desk_episode(2, {"date": "2026-09-15", "title": CHAPTER}, dict(_EP), dry_run=True)
    assert "PUBLISH" in json.dumps(clean)  # mutation control
    held = panel._publish_desk_episode(2, {"date": "2026-09-15", "title": "The Pace Flag Week"}, dict(_EP), dry_run=True)
    assert "HOLD" in json.dumps(held) and "story-door" in json.dumps(held)


# ── one title: the legacy writer, end to end ────────────────────────────────


def _six_turns():
    lines = ["Nine days.", "No rest day.", "Why not?", "He liked the streak.", "And the body?", "It kept score."]
    return [{"speaker": panel.ELENA if i % 2 == 0 else "marcus_webb", "line": s} for i, s in enumerate(lines)]


def _stub_legacy(monkeypatch, post, script):
    seen = _stub_publish(monkeypatch)
    beats = {
        "week": post["week"],
        "date": post["date"],
        "title": post.get("title", f"Week {post['week']}"),
        "chronicle": "Nine days without a rest day.",
        "coach_reads": [{"name": "Marcus Webb", "summary": "He has not rested."}],
        "guest": {"id": "marcus_webb", "name": "Marcus Webb"},
    }
    monkeypatch.setattr(panel, "_select_week_post", lambda: post)
    monkeypatch.setattr(panel, "_episode_exists", lambda week: None)
    monkeypatch.setattr(panel, "_desk_episode", lambda p: None)  # no desk script: the LEGACY writer runs
    monkeypatch.setattr(panel, "_load_bible", lambda: {})
    monkeypatch.setattr(panel, "_gather_week", lambda p, st: dict(beats))
    monkeypatch.setattr(panel, "_sensitivity_hold_reasons", lambda b: [])
    monkeypatch.setattr(panel._zeitgeist, "fetch_zeitgeist", lambda: [])
    monkeypatch.setattr(panel._zeitgeist, "zeitgeist_truth_block", lambda z: "")
    monkeypatch.setattr(panel, "_build_weekly_script_v2", lambda b, bible: dict(script, turns=_six_turns()))
    monkeypatch.setattr(panel, "_editor_review", lambda turns, bible: {"verdict": "pass"})
    monkeypatch.setattr(panel, "_weekly_gate", lambda turns, allowed, gid: (list(turns), []))
    monkeypatch.setattr(panel._repair, "repair_structure", lambda clean, *a, **k: (clean, 0, 0))
    monkeypatch.setattr(panel._repair, "log_ledger", lambda *a, **k: None)
    monkeypatch.setattr(panel, "_craft_check", lambda clean: [])
    monkeypatch.setattr(panel._craft, "punch_up_script", lambda clean, *a, **k: (clean, False))
    monkeypatch.setattr(panel, "_qa_review", lambda clean, rubric, gt: (True, []))
    monkeypatch.setattr(panel, "_craft_judge", lambda clean, rubric: (True, [], []))
    return seen


def test_the_legacy_writer_publishes_the_chapters_title_not_its_own(monkeypatch):
    """The week-2 specimen: the legacy writer's own episode_title used to win over the chapter. Reverting the legacy
    call site to prefer script['episode_title'] publishes "EP2 · Nine Days and Counting" and fails here."""
    post = {"week": 2, "date": "2026-09-15", "title": CHAPTER}
    seen = _stub_legacy(monkeypatch, post, {"episode_title": OWN, "pull_quote": "It kept score."})
    out = panel._run_weekly(force=True, dry_run=False)
    assert json.loads(out["body"])["published"] is True
    assert [e["title"] for e in seen["episodes"]] == [f"EP2 · {CHAPTER}"]


def test_the_legacy_writer_falls_back_to_its_own_title_only_without_a_chapter(monkeypatch):
    post = {"week": 3, "date": "2026-09-22", "title": "Week 3"}  # _select_week_post's no-chapter placeholder
    seen = _stub_legacy(monkeypatch, post, {"episode_title": OWN, "pull_quote": "It kept score."})
    panel._run_weekly(force=True, dry_run=False)
    assert [e["title"] for e in seen["episodes"]] == [f"EP3 · {OWN}"]


def test_the_legacy_writer_drops_a_chapter_title_carrying_a_cut_term(monkeypatch):
    """door_safe on the legacy title is the Panel's final check there: a cut term publishes the bare number."""
    post = {"week": 2, "date": "2026-09-15", "title": "The Pace-Flag Week"}
    seen = _stub_legacy(monkeypatch, post, {"episode_title": OWN, "pull_quote": "It kept score."})
    panel._run_weekly(force=True, dry_run=False)
    assert [e["title"] for e in seen["episodes"]] == ["EP2"]
