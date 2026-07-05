"""Tests for the chronicle email portrait byline (#593): engraved portraits replace the
coach emoji when a signed PNG exists, with a fail-soft emoji fallback."""

import importlib

cel = importlib.import_module("chronicle_email_sender_lambda")


def _reset_manifest(monkeypatch, index):
    monkeypatch.setattr(cel, "_PORTRAIT_MANIFEST", index)


def test_portrait_img_when_manifest_has_coach(monkeypatch):
    _reset_manifest(monkeypatch, {"dr. marcus webb": "marcus_webb"})
    member = {"name": "Dr. Marcus Webb", "emoji": "\U0001f957"}
    html = cel._coach_portrait_img(member)
    assert "<img" in html
    assert "/assets/portraits/marcus_webb-96-ondark.png" in html
    assert 'alt="\U0001f957"' in html  # emoji preserved as alt for image-blocked clients


def test_no_portrait_returns_empty_for_unknown_coach(monkeypatch):
    _reset_manifest(monkeypatch, {"dr. marcus webb": "marcus_webb"})
    member = {"name": "The Chair", "emoji": "\U0001f3af"}
    assert cel._coach_portrait_img(member) == ""


def test_byline_falls_back_to_emoji(monkeypatch):
    # empty manifest → the `or member['emoji']` fallback keeps today's behaviour
    _reset_manifest(monkeypatch, {})
    member = {"name": "The Chair", "emoji": "\U0001f3af"}
    assert (cel._coach_portrait_img(member) or member["emoji"]) == "\U0001f3af"


def test_manifest_load_is_failsoft(monkeypatch):
    # S3 read raising (fake creds in CI) must yield an empty index, never propagate
    monkeypatch.setattr(cel, "_PORTRAIT_MANIFEST", None)

    class _Boom:
        def get_object(self, **kw):
            raise RuntimeError("no S3 in test")

    monkeypatch.setattr(cel, "_s3", _Boom())
    assert cel._load_portrait_manifest() == {}
