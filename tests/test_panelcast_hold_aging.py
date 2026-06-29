"""tests/test_panelcast_hold_aging.py — SS-02 podcast HOLD-aging escape (offline).

A soft (quality) HOLD must not strand an episode in panelcast-holds/ forever, while a
hard safety/sensitivity HOLD must NEVER auto-release. Tests the hold-class tagging +
the sweep's decision matrix (re-generate a quality hold after a window; skip safety,
too-fresh, abandoned, retry-capped, and already-published). No AWS/Bedrock/TTS.
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


class _FakeS3:
    """Minimal in-memory S3 keyed by object key (bytes bodies)."""

    def __init__(self):
        self.store = {}

    def put_object(self, Bucket, Key, Body, **kw):
        self.store[Key] = Body if isinstance(Body, bytes) else Body.encode("utf-8")

    def get_object(self, Bucket, Key, **kw):
        if Key not in self.store:
            raise Exception(f"NoSuchKey {Key}")
        return {"Body": io.BytesIO(self.store[Key])}

    def delete_object(self, Bucket, Key, **kw):
        self.store.pop(Key, None)

    def head_object(self, Bucket, Key, **kw):
        if Key not in self.store:
            raise Exception("404")
        return {}


def _iso_days_ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")


def _hold_key(week):
    return f"{panel.HOLD_PREFIX}/wk{week}.json"


def _seed_hold(fs, week, hold_class, age_days, retry_count=0):
    rec = {
        "week": week,
        "reasons": ["test"],
        "draft": {"turns": []},
        "held_at": _iso_days_ago(age_days),
        "first_held_at": _iso_days_ago(age_days),
        "hold_class": hold_class,
        "retry_count": retry_count,
    }
    fs.store[_hold_key(week)] = json.dumps(rec).encode("utf-8")


def _wire(monkeypatch, fs, *, week=3, published=False):
    monkeypatch.setattr(panel, "s3", fs)
    monkeypatch.setattr(panel, "_select_week_post", lambda: {"week": week, "date": "2026-06-29", "title": f"Week {week}"})
    monkeypatch.setattr(panel, "_episode_published", lambda w: published)
    monkeypatch.setattr(panel, "_set_pending", lambda *a, **k: None)


# ── hold-class tagging + aging metadata ────────────────────────────────────────


def test_hold_tags_class_and_inits_metadata(monkeypatch):
    fs = _FakeS3()
    monkeypatch.setattr(panel, "s3", fs)
    monkeypatch.setattr(panel, "_set_pending", lambda *a, **k: None)
    monkeypatch.setattr(panel.boto3, "client", lambda *a, **k: type("X", (), {"publish": lambda *a, **k: None})())
    panel._hold_and_alert(5, ["editor: weak"], {"turns": []}, hold_class="quality")
    rec = json.loads(fs.store[_hold_key(5)])
    assert rec["hold_class"] == "quality"
    assert rec["retry_count"] == 0
    assert rec["first_held_at"]


def test_re_hold_preserves_first_held_and_bumps_retry(monkeypatch):
    fs = _FakeS3()
    monkeypatch.setattr(panel, "s3", fs)
    monkeypatch.setattr(panel, "_set_pending", lambda *a, **k: None)
    monkeypatch.setattr(panel.boto3, "client", lambda *a, **k: type("X", (), {"publish": lambda *a, **k: None})())
    _seed_hold(fs, 5, "quality", age_days=4, retry_count=1)
    first_before = json.loads(fs.store[_hold_key(5)])["first_held_at"]
    panel._hold_and_alert(5, ["editor: still weak"], {"turns": []}, hold_class="quality")
    rec = json.loads(fs.store[_hold_key(5)])
    assert rec["first_held_at"] == first_before  # original retained
    assert rec["retry_count"] == 2  # bumped


def test_unknown_hold_class_defaults_to_safety(monkeypatch):
    fs = _FakeS3()
    monkeypatch.setattr(panel, "s3", fs)
    monkeypatch.setattr(panel, "_set_pending", lambda *a, **k: None)
    monkeypatch.setattr(panel.boto3, "client", lambda *a, **k: type("X", (), {"publish": lambda *a, **k: None})())
    panel._hold_and_alert(5, ["??"], {}, hold_class="bogus")
    assert json.loads(fs.store[_hold_key(5)])["hold_class"] == "safety"


# ── sweep decision matrix ──────────────────────────────────────────────────────


def test_sweep_skips_safety_hold(monkeypatch):
    fs = _FakeS3()
    _wire(monkeypatch, fs, week=3)
    _seed_hold(fs, 3, "safety", age_days=9)
    called = []
    monkeypatch.setattr(panel, "_run_weekly", lambda *a, **k: called.append(1) or {})
    out = panel._sweep_held_episodes(dry_run=False)
    assert out["swept"] == []
    assert "human review" in out["skipped"]
    assert called == []  # never regenerated


def test_sweep_skips_too_fresh(monkeypatch):
    fs = _FakeS3()
    _wire(monkeypatch, fs, week=3)
    _seed_hold(fs, 3, "quality", age_days=1)  # < 48h window
    monkeypatch.setattr(panel, "_run_weekly", lambda *a, **k: {"body": json.dumps({"published": True})})
    out = panel._sweep_held_episodes(dry_run=False)
    assert out["swept"] == [] and "too fresh" in out["skipped"]


def test_sweep_skips_abandoned(monkeypatch):
    fs = _FakeS3()
    _wire(monkeypatch, fs, week=3)
    _seed_hold(fs, 3, "quality", age_days=30)  # > MAX_DAYS
    out = panel._sweep_held_episodes(dry_run=False)
    assert out["swept"] == [] and "abandoned" in out["skipped"]


def test_sweep_skips_retry_capped(monkeypatch):
    fs = _FakeS3()
    _wire(monkeypatch, fs, week=3)
    _seed_hold(fs, 3, "quality", age_days=4, retry_count=panel.HOLD_MAX_RETRIES)
    out = panel._sweep_held_episodes(dry_run=False)
    assert out["swept"] == [] and "retry cap" in out["skipped"]


def test_sweep_cleans_already_published(monkeypatch):
    fs = _FakeS3()
    _wire(monkeypatch, fs, week=3, published=True)
    _seed_hold(fs, 3, "quality", age_days=4)
    out = panel._sweep_held_episodes(dry_run=False)
    assert out.get("cleaned_stale_hold") is True
    assert _hold_key(3) not in fs.store  # hold removed


def test_sweep_retries_eligible_quality_hold(monkeypatch):
    fs = _FakeS3()
    _wire(monkeypatch, fs, week=3)
    _seed_hold(fs, 3, "quality", age_days=4)  # past window, under cap, not abandoned
    monkeypatch.setattr(panel, "_run_weekly", lambda *a, **k: {"body": json.dumps({"week": 3, "published": True})})
    out = panel._sweep_held_episodes(dry_run=False)
    assert out["retried"] is True and out["published"] is True
    assert _hold_key(3) not in fs.store  # cleaned up after a successful publish


def test_sweep_dry_run_does_not_regenerate(monkeypatch):
    fs = _FakeS3()
    _wire(monkeypatch, fs, week=3)
    _seed_hold(fs, 3, "quality", age_days=4)
    called = []
    monkeypatch.setattr(panel, "_run_weekly", lambda *a, **k: called.append(1) or {})
    out = panel._sweep_held_episodes(dry_run=True)
    assert out["would_retry"] is True and called == []
    assert _hold_key(3) in fs.store  # untouched


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
