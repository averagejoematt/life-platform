"""HS1 — the Human Story's timeline and episode index, built dark (owner brief 2026-11-08: "Proceed with the Human Story
timeline and episode index using only already-approved published material. Held installments and audio remain excluded.").

Three Python halves of the switch (the build half is www/tests/story_dark.test.mjs):
  * the producer writes the story's data file (story.json) ONLY with WEB_STORY=1 — off, the snapshot is unchanged;
  * what the file includes is fail-closed: an installment is in the index only when the platform records it approved
    AND published, and the owner's explicit exclusions hold even against a planted "published" state;
  * scripts/check_www_build.py's scan — which every deploy runs (`--scan-only`) — refuses a dist carrying story output.
Each with its mutation control.
"""

from __future__ import annotations

import copy
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))

import check_www_build  # noqa: E402
import publish_snapshot  # noqa: E402
from publish_snapshot_story import ABSENT_STORY, compose, exclusion_reason, story_enabled, validate  # noqa: E402

FIXTURES = os.path.join(REPO, "www", "content", "fixtures")


def _export(tmp_path, name, env_on: bool, monkeypatch):
    monkeypatch.delenv("WEB_ROOM", raising=False)
    if env_on:
        monkeypatch.setenv("WEB_STORY", "1")
    else:
        monkeypatch.delenv("WEB_STORY", raising=False)
    out = tmp_path / name
    manifest = publish_snapshot.run("fixture", str(out), FIXTURES, "https://example.invalid", 5.0)
    return manifest, out


def test_only_the_literal_one_turns_the_story_on():
    assert story_enabled({}) is False
    for v in ("", "0", "true", "yes", " 1"):
        assert story_enabled({"WEB_STORY": v}) is False
    assert story_enabled({"WEB_ROOM": "1"}) is False
    assert story_enabled({"WEB_STORY": "1"}) is True


def test_switch_off_writes_no_story_file_and_on_writes_it(tmp_path, monkeypatch):
    off_manifest, off = _export(tmp_path, "off", False, monkeypatch)
    assert not (off / "story.json").exists()
    assert "story.json" not in off_manifest["files"]
    on_manifest, on = _export(tmp_path, "on", True, monkeypatch)  # the control
    assert (on / "story.json").exists()
    assert "story.json" in on_manifest["files"]
    for name in sorted(os.listdir(off)):  # the story adds, never alters
        if name in ("manifest.json", "series"):
            continue
        assert (off / name).read_bytes() == (on / name).read_bytes(), name


def test_switch_off_over_a_story_export_removes_the_stale_story_file(tmp_path, monkeypatch):
    _export(tmp_path, "same", True, monkeypatch)
    _m, out = _export(tmp_path, "same", False, monkeypatch)
    assert not (out / "story.json").exists()


def test_the_fixture_index_holds_only_the_approved_published_installment(tmp_path, monkeypatch):
    _m, on = _export(tmp_path, "on", True, monkeypatch)
    data = json.loads((on / "story.json").read_text())
    assert [i["chapter_id"] for i in data["installments_index"]] == ["week-06"]
    assert set(data["installments_index"][0]) == {"chapter_id", "week", "date", "title"}  # no audio, no excerpt, no body
    text = (on / "story.json").read_text()
    for word in ("audio", "episode", "transcript", "excerpt", "body_html", "drafted_at", "held", "SENTINEL"):
        assert word not in text, word
    for w in data["story_weeks"]:
        assert set(w) == {"week", "start", "end", "chapter_id"}  # no status, no reason: a week is its days and its installment


# ── the approval rule, fail closed ────────────────────────────────────────────────────────────────────────────────
APPROVED = {"by": "owner", "at": "2026-09-08", "via": "chronicle-approve"}


def _chapter(cid, week, title, url, status="published", approved=APPROVED, date="2026-09-08"):
    return {
        "id": cid,
        "type": "chapter",
        "visibility": "public",
        "week": week,
        "title": title,
        "url_legacy": url,
        "status": status,
        "approved": approved,
        "date": date,
    }


def _api(*weeks):
    return {"genesis": "2026-09-06", "as_of": "2026-11-08", "weeks": list(weeks)}


def _week(n, status="published", title=None, url=None):
    start = f"2026-09-{6 + 7 * (n - 1):02d}" if n <= 3 else "2026-09-27"
    end = f"2026-09-{12 + 7 * (n - 1):02d}" if n <= 2 else "2026-10-03"
    return {"week": n, "start": start, "end": end, "status": status, "title": title, "url": url}


def test_an_approved_published_program_week_is_included_and_its_controls_exclude_it():
    c = _chapter("week-04", 1, "76% on Day Two", "/journal/posts/week-04/")
    served = {1: _week(1, title="76% on Day Two", url="/journal/posts/week-04/")}
    assert exclusion_reason(c, served) is None
    # each control flips ONE condition and must exclude
    assert exclusion_reason({**c, "status": "held"}, served)
    assert exclusion_reason({**c, "approved": None}, served)
    assert exclusion_reason({**c, "approved": {**APPROVED, "via": "auto"}}, served)
    assert exclusion_reason({**c, "week": 0}, served), "the prologue: no approval state is recorded for it"
    assert exclusion_reason({**c, "week": None}, served)
    assert exclusion_reason(c, {}), "the week list did not serve it: unknown is excluded"
    assert exclusion_reason(c, {1: {**served[1], "status": "held"}})
    assert exclusion_reason(c, {1: {**served[1], "url": "/journal/posts/week-99/"}})
    assert exclusion_reason(c, {1: {**served[1], "title": "Another"}})
    assert exclusion_reason({**c, "visibility": "held"}, served)


@pytest.mark.parametrize(
    "chapter",
    [
        _chapter("week-05", 2, "Eight Pounds and a Flag", "/journal/posts/week-05/"),  # the Week 2 installment
        _chapter("week-02", 0, "Prologue II", "/journal/posts/week-02/"),  # the unlisted page
        _chapter("week-02-alias", 1, "x", "/journal/posts/week-02/"),  # the unlisted page under any id
        _chapter("program-week-08", 8, "Week 8", "/journal/posts/week-11/"),  # the Week 8 draft, even if "published"
        _chapter("program-week-09", 9, "Week 9", "/journal/posts/week-12/"),  # the Week 9 draft
        _chapter("x-0516", 1, "x", "/journal/posts/x/", date="2026-05-16"),  # held, non-current-phase drafts
        _chapter("x-0901", 1, "x", "/journal/posts/y/", date="2026-09-01"),
    ],
)
def test_the_owner_exclusions_hold_even_against_a_planted_published_state(chapter):
    served = {chapter["week"]: {"week": chapter["week"], "status": "published", "title": chapter["title"], "url": chapter["url_legacy"]}}
    assert exclusion_reason(chapter, served) is not None


def test_compose_excludes_and_records_only_ids_and_reasons():
    public = {
        "chapter": [
            _chapter("week-04", 1, "76% on Day Two", "/journal/posts/week-04/"),
            _chapter("week-05", 2, "Eight Pounds and a Flag", "/journal/posts/week-05/"),
            _chapter("program-week-08", 8, "Week 8", None, status="held", approved=None),
        ]
    }
    api = _api(
        _week(1, title="76% on Day Two", url="/journal/posts/week-04/"),
        _week(2, title="Eight Pounds and a Flag", url="/journal/posts/week-05/"),
    )
    out = compose(api, public)
    assert [i["chapter_id"] for i in out["installments_index"]] == ["week-04"]
    assert {e["ref"] for e in out["story_exclusions"]} == {"week-05", "program-week-08"}
    assert all(set(e) == {"ref", "reason"} for e in out["story_exclusions"])
    assert "Eight Pounds" not in json.dumps(out["story_exclusions"])
    assert [w["chapter_id"] for w in out["story_weeks"]] == ["week-04", None]
    assert validate(copy.deepcopy(out), public) == out


def test_an_unserved_or_malformed_week_list_includes_nothing():
    public = {"chapter": [_chapter("week-04", 1, "76% on Day Two", "/journal/posts/week-04/")]}
    for bad in (None, {}, {"weeks": "x"}, {"weeks": [], "genesis": "soon"}):
        out = compose(bad, public)
        assert out["state"] == "absent" and out["installments_index"] == [] and out == ABSENT_STORY


def test_validate_refuses_an_installment_that_is_not_a_public_chapter():
    bad = {"state": "ok", "installments_index": [{"chapter_id": "ghost", "date": "2026-09-08", "title": "x"}], "story_weeks": []}
    with pytest.raises(ValueError, match="not a public chapter"):
        validate(bad, {"chapter": []})


# ── the deploy scan ───────────────────────────────────────────────────────────────────────────────────────────────
def _dist(tmp_path, html: str = "<!doctype html><p>ok</p>"):
    d = tmp_path / "dist"
    d.mkdir()
    (d / "index.html").write_text(html)
    return d


def test_the_deploy_scan_refuses_story_output_and_passes_a_clean_dist(tmp_path):
    assert check_www_build.room_paths(check_www_build.STORY_JS) == ["/story/timeline/", "/story/episodes/"]  # read off story_dark.js
    clean = _dist(tmp_path)
    (clean / "story").mkdir()
    (clean / "story" / "index.html").write_text("<p>the chapters</p>")
    assert check_www_build.story_leaks(str(clean)) == []
    assert check_www_build.room_leaks(str(clean)) == []
    # the controls: a story page, the data file, the marker — each must red the scan the deploy runs
    (clean / "story" / "timeline").mkdir()
    (clean / "story" / "timeline" / "index.html").write_text("<p>timeline</p>")
    (clean / "story.json").write_text("{}")
    (clean / "story" / "index.html").write_text('<section data-story-dark="entry"></section>')
    leaks = check_www_build.story_leaks(str(clean))
    assert any("a Human Story page" in x for x in leaks)
    assert any("data file" in x for x in leaks)
    assert any("marker" in x for x in leaks)
    assert any("Human Story" in x for x in check_www_build.scan(str(clean), require_noindex=False, forbidden_ids=set()))
