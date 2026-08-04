"""tests/test_podcast_parity_1243.py — #1243: the Prologue read-aloud orphan
regression guard.

The join in site/assets/js/read_aloud.js (#1121) is honest-empty on a miss —
correct when an article genuinely has no audio, but indistinguishable from an
ORPHANED episode: audio rendered under an article's OLD publish date that
never got re-rendered after a genesis re-anchor (ADR-077). #1243's live
evidence was exactly this shape: /podcast/episodes.json carried the sole
episode "The Plan, On the Record" dated 2026-07-11 while the live journal
article of the same title had been re-anchored to a later date — the episode
never regenerated, so the reader's player silently never appeared on the
cycle's top story.

operational.qa_check_podcast_parity.assess_podcast_parity is the deterministic
guard: any episode whose TITLE matches a live journal article, but whose DATE
does not, is flagged. Fixtures below reconstruct the actual #1243 evidence
shape (title match / date mismatch) alongside the healthy and no-match cases.
"""

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from operational import qa_check_podcast_parity as qcp  # noqa: E402 — the SOURCE module (a re-export is not a patch point)

# ── the #1243 evidence shape, reconstructed ────────────────────────────────

_ORPHANED_POSTS = {
    "posts": [
        {"week": 0, "title": "The Plan, On the Record", "date": "2026-08-02", "excerpt": "..."},
    ]
}
_ORPHANED_EPISODES = {
    "episodes": [
        {"week": 0, "title": "The Plan, On the Record", "date": "2026-07-11", "url": "/podcast/ep-2026-07-11.mp3"},
    ]
}

_HEALTHY_EPISODES = {
    "episodes": [
        {"week": 0, "title": "The Plan, On the Record", "date": "2026-08-02", "url": "/podcast/ep-2026-08-02.mp3"},
    ]
}


# ── the pure assessor ───────────────────────────────────────────────────────


def test_assessor_fails_on_the_actual_1243_evidence_shape():
    ok, msg = qcp.assess_podcast_parity(_ORPHANED_POSTS, _ORPHANED_EPISODES)
    assert ok is False
    assert "The Plan, On the Record" in msg
    assert "2026-07-11" in msg and "2026-08-02" in msg


def test_assessor_passes_when_title_and_date_both_match():
    ok, msg = qcp.assess_podcast_parity(_ORPHANED_POSTS, _HEALTHY_EPISODES)
    assert ok is True
    assert "1" in msg


def test_assessor_passes_when_episode_has_no_same_title_article():
    """A back-catalogue episode whose article rotated out of the current-cycle
    manifest (ADR-077 phase taxonomy) is NOT a defect — it's archived, not
    orphaned. Only a live title collision with a mismatched date is a defect."""
    posts = {"posts": [{"title": "Before the Numbers", "date": "2026-07-28", "excerpt": "x"}]}
    episodes = {"episodes": [{"title": "A Retired Season-1 Episode", "date": "2026-02-22", "url": "/podcast/wk0.mp3"}]}
    ok, _ = qcp.assess_podcast_parity(posts, episodes)
    assert ok is True


def test_assessor_matches_case_and_whitespace_insensitively():
    posts = {"posts": [{"title": "  The Plan, On the Record  ", "date": "2026-08-02"}]}
    episodes = {"episodes": [{"title": "the plan, on the record", "date": "2026-08-02", "url": "/podcast/ep-2026-08-02.mp3"}]}
    ok, _ = qcp.assess_podcast_parity(posts, episodes)
    assert ok is True


def test_assessor_reports_every_orphan_not_just_the_first():
    posts = {
        "posts": [
            {"title": "A", "date": "2026-08-01"},
            {"title": "B", "date": "2026-08-02"},
        ]
    }
    episodes = {
        "episodes": [
            {"title": "A", "date": "2026-07-01", "url": "/podcast/ep-a.mp3"},
            {"title": "B", "date": "2026-07-02", "url": "/podcast/ep-b.mp3"},
        ]
    }
    ok, msg = qcp.assess_podcast_parity(posts, episodes)
    assert ok is False
    assert "'A'" in msg and "'B'" in msg


def test_assessor_fails_on_malformed_posts_payload():
    ok, msg = qcp.assess_podcast_parity({"posts": "not-a-list"}, _HEALTHY_EPISODES)
    assert ok is False
    assert "posts" in msg


def test_assessor_fails_on_malformed_episodes_payload():
    ok, msg = qcp.assess_podcast_parity(_ORPHANED_POSTS, {"episodes": None})
    assert ok is False
    assert "episodes" in msg


def test_assessor_ignores_entries_missing_title_or_date():
    posts = {"posts": [{"title": "No Date"}, {"date": "2026-08-01"}]}
    episodes = {"episodes": [{"title": "No Date", "date": "2026-08-01", "url": "/x.mp3"}]}
    ok, _ = qcp.assess_podcast_parity(posts, episodes)
    assert ok is True  # neither malformed post has both fields, so nothing to compare


# ── the check wrapper — fetch wiring + fail-soft ────────────────────────────


def _run_check(monkeypatch, posts_resp, episodes_resp):
    calls = {"n": 0}

    def fake_fetch(path, timeout=15):
        calls["n"] += 1
        resp = posts_resp if path == "/journal/posts.json" else episodes_resp
        if isinstance(resp, Exception):
            raise resp
        return resp

    # Patch the SOURCE module (operational.qa_check_podcast_parity), never a
    # re-export — a re-export is not a patch point.
    monkeypatch.setattr(qcp, "_fetch_site_json", fake_fetch)
    checks = qcp.check_podcast_parity()
    assert len(checks) == 1
    return checks[0]


def test_check_passes_on_a_healthy_live_pair(monkeypatch):
    c = _run_check(monkeypatch, _ORPHANED_POSTS, _HEALTHY_EPISODES)
    assert c.passed is True


def test_check_fails_on_the_actual_1243_regression(monkeypatch):
    c = _run_check(monkeypatch, _ORPHANED_POSTS, _ORPHANED_EPISODES)
    assert c.passed is False
    assert c.chronic is not True  # novel content-truth defect — must hold the alarm
    assert "The Plan, On the Record" in c.message


def test_check_warns_fail_soft_on_fetch_error(monkeypatch):
    c = _run_check(monkeypatch, TimeoutError("timed out"), _HEALTHY_EPISODES)
    assert c.passed is None  # warn — a fetch blip must never red the nightly


def test_check_wired_into_qa_smoke_lambda():
    """qa_smoke_lambda re-exports check_podcast_parity and calls it in
    lambda_handler — the same contract check_content_cadence's wiring pins
    (#1972)."""
    qa_smoke_path = os.path.join(_REPO, "lambdas", "operational", "qa_smoke_lambda.py")
    src = open(qa_smoke_path, encoding="utf-8").read()
    assert "from operational.qa_check_podcast_parity import" in src
    assert "check_podcast_parity" in src
    assert "all_checks += check_podcast_parity()" in src
