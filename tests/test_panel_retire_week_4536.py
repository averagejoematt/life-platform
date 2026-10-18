"""tests/test_panel_retire_week_4536.py — #4536: retire a held Panel week BY NAME (owner ruling 2026-10-18).

Weeks 5 and 6 sit on the body-number SAFETY hold (human review only). The owner ruled "retire weeks 5 and 6",
so week 7's episode is the next one. Retire is a MARKER beside the hold record — never a release:

  * `{"week": N, "retire": true}` writes `panelcast-holds/wk{N}.retired.json` and leaves the hold untouched;
  * `dry_run` reports and writes nothing;
  * a retired week is skipped by `_select_week_post`, the hold sweep (SKIP "retired") and the weekly run;
  * `{"unretire": true}` removes the marker and the week is held as before;
  * qa-smoke's story_season:episode_or_hold reads a retired week as accounted for (not a FAIL).

Offline: an in-memory S3 stub (no AWS, no Bedrock, no TTS), and the qa check is graded at a fixed `now`.
"""

import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

from emails import coach_panel_podcast_lambda as panel  # noqa: E402
from operational import story_season_qa as ssq  # noqa: E402

EP_KEY = f"{panel.PREFIX}/episodes.json"


class _NoSuchKey(Exception):
    response = {"Error": {"Code": "NoSuchKey"}}


class _FakeS3:
    """In-memory S3 that records every mutating call."""

    def __init__(self):
        self.store = {}
        self.writes = []

    def put_object(self, Bucket, Key, Body, **kw):
        self.writes.append(("put", Key))
        self.store[Key] = Body if isinstance(Body, bytes) else Body.encode("utf-8")

    def get_object(self, Bucket, Key, **kw):
        if Key not in self.store:
            raise _NoSuchKey(Key)
        return {"Body": io.BytesIO(self.store[Key])}

    def delete_object(self, Bucket, Key, **kw):
        self.writes.append(("delete", Key))
        self.store.pop(Key, None)

    def list_objects_v2(self, Bucket, Prefix, **kw):
        return {"Contents": [{"Key": k} for k in sorted(self.store) if k.startswith(Prefix)], "IsTruncated": False}


HOLD = {
    "week": 6,
    "reasons": ["body-number", "story-door"],
    "draft": {"turns": []},
    "held_at": "2026-10-18",
    "first_held_at": "2026-10-18",
    "hold_class": "safety",
    "retry_count": 0,
}
PENDING = {"week": 6, "reason": "held_for_review", "display": panel.HELD_DISPLAY, "noted_at": "2026-10-18T04:31:00+00:00"}


def _seed(fs):
    for wk in (5, 6):
        fs.store[f"{panel.HOLD_PREFIX}/wk{wk}.json"] = json.dumps({**HOLD, "week": wk}).encode()
    fs.store[EP_KEY] = json.dumps(
        {"episodes": [{"week": 4, "date": "2026-10-02", "url": "/panelcast/wk4.wav"}], "pending": PENDING}
    ).encode()


def _wire(monkeypatch, fs):
    monkeypatch.setattr(panel, "s3", fs)
    monkeypatch.setattr(panel, "_invalidate_cdn", lambda: None)
    monkeypatch.setattr(panel, "EXPERIMENT_START_DATE", "2026-09-06")
    monkeypatch.setattr(
        panel,
        "_published_posts",
        lambda: [
            {"week": 4, "date": "2026-10-02", "title": "Week 4"},
            {"week": 5, "date": "2026-10-09", "title": "Week 5"},
            {"week": 6, "date": "2026-10-16", "title": "Week 6"},
        ],
    )


def _body(resp):
    return json.loads(resp["body"])


def test_retire_writes_the_marker_and_nothing_else_in_holds(monkeypatch):
    fs = _FakeS3()
    _seed(fs)
    _wire(monkeypatch, fs)
    holds_before = {k: v for k, v in fs.store.items() if k.startswith(panel.HOLD_PREFIX)}

    out = _body(panel.lambda_handler({"week": 6, "retire": True}, None))

    assert out["retired"] is True and out["hold_found"] is True
    marker = json.loads(fs.store[f"{panel.HOLD_PREFIX}/wk6.retired.json"])
    assert marker["retired_by"] == "owner ruling 2026-10-18"
    assert marker["hold_reasons"] == ["body-number", "story-door"] and marker["hold_class"] == "safety"
    assert marker["retired_at"] and marker["reason"]
    # the hold records are byte-identical and nothing under panelcast-holds/ was deleted
    for k, v in holds_before.items():
        assert fs.store[k] == v
    assert not [w for w in fs.writes if w[0] == "delete"]
    assert {k for _, k in fs.writes} == {f"{panel.HOLD_PREFIX}/wk6.retired.json", EP_KEY}
    # public face: the week is listed retired (no reasons), the "held for review" line naming it is gone
    doc = json.loads(fs.store[EP_KEY])
    assert [r["week"] for r in doc["retired"]] == [6] and "hold_reasons" not in doc["retired"][0]
    assert "pending" not in doc and doc["episodes"][0]["week"] == 4


def test_dry_run_retire_writes_nothing(monkeypatch):
    fs = _FakeS3()
    _seed(fs)
    _wire(monkeypatch, fs)
    before = dict(fs.store)
    out = _body(panel.lambda_handler({"week": 5, "retire": True, "dry_run": True}, None))
    assert out["dry_run"] is True and out["would"] == "RETIRE" and out["marker"]["hold_class"] == "safety"
    assert fs.writes == [] and fs.store == before


def test_retire_refuses_a_published_week_and_a_bad_week(monkeypatch):
    fs = _FakeS3()
    _seed(fs)
    _wire(monkeypatch, fs)
    assert _body(panel.lambda_handler({"week": 4, "retire": True}, None))["retire"] == "refused"
    assert panel.lambda_handler({"retire": True}, None)["statusCode"] == 400
    assert fs.writes == []


def test_retired_week_is_skipped_by_selection_sweep_and_weekly_run(monkeypatch):
    fs = _FakeS3()
    _seed(fs)
    _wire(monkeypatch, fs)
    assert panel._select_week_post()["week"] == 6  # control: before the retire, week 6 is the current week
    panel.lambda_handler({"week": 5, "retire": True}, None)
    panel.lambda_handler({"week": 6, "retire": True}, None)
    fs.writes.clear()

    post = panel._select_week_post()
    assert post["week"] == 4 and post["skipped_retired"] == [6, 5]

    sweep = panel._sweep_held_episodes()
    assert sweep == {"swept": [], "week": 6, "skipped": "retired"}

    monkeypatch.setattr(panel, "_desk_episode", lambda post: (_ for _ in ()).throw(AssertionError("generated a retired week")))
    assert _body(panel._run_weekly(force=False, week=6)) == {"week": 6, "retired": True}
    assert _body(panel._run_weekly(force=True, week=5, approved=True)) == {"week": 5, "retired": True}
    assert _body(panel._run_weekly(force=False, dry_run=True, week=6))["would"] == "SKIP"
    assert fs.writes == []


def test_sweep_skips_retired_when_it_is_the_selected_week(monkeypatch):
    fs = _FakeS3()
    _seed(fs)
    _wire(monkeypatch, fs)
    panel.lambda_handler({"week": 6, "retire": True}, None)
    monkeypatch.setattr(panel, "_select_week_post", lambda: {"week": 6, "date": "2026-10-16"})
    assert panel._sweep_held_episodes()["skipped"] == "retired"


def test_unretire_restores_the_hold_exactly(monkeypatch):
    fs = _FakeS3()
    _seed(fs)
    _wire(monkeypatch, fs)
    panel.lambda_handler({"week": 6, "retire": True}, None)
    before = dict(fs.store)
    assert _body(panel.lambda_handler({"week": 6, "unretire": True, "dry_run": True}, None))["was_retired"] is True
    assert fs.store == before  # dry-run unretire writes nothing

    out = _body(panel.lambda_handler({"week": 6, "unretire": True}, None))
    assert out["unretired"] is True
    assert f"{panel.HOLD_PREFIX}/wk6.retired.json" not in fs.store
    assert json.loads(fs.store[f"{panel.HOLD_PREFIX}/wk6.json"]) == {**HOLD, "week": 6}
    doc = json.loads(fs.store[EP_KEY])
    assert "retired" not in doc and doc["pending"]["week"] == 6 and doc["pending"]["reason"] == "held_for_review"
    assert panel._select_week_post()["week"] == 6 and not panel._panel_retire().is_retired(vars(panel), 6)


def test_a_publish_keeps_the_retired_weeks_listed(monkeypatch):
    fs = _FakeS3()
    _seed(fs)
    _wire(monkeypatch, fs)
    panel.lambda_handler({"week": 5, "retire": True}, None)
    panel._write_indexes(
        [
            {"week": 7, "date": "2026-10-21", "url": "/panelcast/wk7.wav", "title": "Week 7"},
            {"week": 4, "date": "2026-10-02", "url": "/panelcast/wk4.wav", "title": "Week 4"},
        ]
    )
    assert [r["week"] for r in json.loads(fs.store[EP_KEY])["retired"]] == [5]


# ── qa-smoke story_season:episode_or_hold ────────────────────────────────────────

NOW = datetime(2026, 10, 19, 18, 30, tzinfo=timezone.utc)  # fixed instant, never the clock


def _weeks():
    pub = {5: datetime(2026, 10, 9, 18, 0, tzinfo=timezone.utc), 6: datetime(2026, 10, 18, 4, 29, tzinfo=timezone.utc)}
    return {wk: {"published": when, "dates": [when.date().isoformat()], "sks": []} for wk, when in pub.items()}


def test_episode_or_hold_reads_retired_weeks_as_accounted_for():
    doc = {"episodes": [{"week": 4}], "retired": [{"week": 5, "retired_at": "2026-10-18T18:00:00+00:00"}, {"week": 6, "retired_at": "x"}]}
    missing, escalated, sanctioned = ssq.episode_findings(_weeks(), doc, NOW + timedelta(days=3))
    assert missing == [] and escalated == []
    assert any("week 5 retired by name" in s for s in sanctioned) and any("week 6 retired by name" in s for s in sanctioned)


def test_episode_or_hold_control_without_the_retired_list_fails():
    """The mutation control's other half: the same weeks with no `retired` list are a bare miss."""
    missing, _, _ = ssq.episode_findings(_weeks(), {"episodes": [{"week": 4}]}, NOW + timedelta(days=3))
    assert len(missing) == 2


def test_the_chapter_never_says_a_retired_week_has_no_episode_yet():
    from web import site_api_edition as ed

    retired = ed._podcast_part({"episodes": [], "retired": [{"week": 6, "retired_at": "x"}]}, 6, lambda _: None)
    plain = ed._podcast_part({"episodes": []}, 6, lambda _: None)
    assert "yet" not in json.dumps(retired) and "yet" in json.dumps(plain)
