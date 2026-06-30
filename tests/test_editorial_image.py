"""Tests for lambdas/editorial_image.py — the atmospheric free-license cover-image
helper. Focus: it is fail-soft (never raises), honours the kill-switch, picks a
constrained/deterministic query, and stores to the editorial prefix on success."""

import importlib.util
import io
import json
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import pytest

_MOD_PATH = Path(__file__).resolve().parents[1] / "lambdas" / "editorial_image.py"


def _load():
    spec = importlib.util.spec_from_file_location("editorial_image", _MOD_PATH)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def ei(monkeypatch):
    monkeypatch.setenv("EDITORIAL_IMAGES", "on")
    return _load()


def test_killswitch_default_off(monkeypatch):
    monkeypatch.delenv("EDITORIAL_IMAGES", raising=False)
    m = _load()
    assert m.enabled() is False
    # disabled → no fetch, returns None, never touches clients
    assert m.fetch_and_store("chronicle", "week-01", 1, s3_client=object(), secrets_client=object()) is None


def test_pick_query_is_constrained_and_deterministic(ei):
    q1 = ei.pick_query(5)
    assert q1 == ei.pick_query(5 + len(ei.ATMOSPHERIC_QUERIES))  # stable, wraps
    assert q1 in ei.ATMOSPHERIC_QUERIES
    # the pool must NOT contain literal health/fitness clichés (truthfulness guard)
    joined = " ".join(ei.ATMOSPHERIC_QUERIES).lower()
    for banned in ("gym", "salad", "workout", "scale", "food", "meal", "fitness"):
        assert banned not in joined


def test_missing_key_is_failsoft(ei):
    secrets = mock.Mock()
    secrets.get_secret_value.side_effect = Exception("no such secret")
    out = ei.fetch_and_store("chronicle", "week-02", 2, s3_client=mock.Mock(), secrets_client=secrets)
    assert out is None


def test_pexels_error_is_failsoft(ei):
    secrets = mock.Mock()
    secrets.get_secret_value.return_value = {"SecretString": json.dumps({"api_key": "K"})}
    s3 = mock.Mock()
    with mock.patch("urllib.request.urlopen", side_effect=Exception("network down")):
        out = ei.fetch_and_store("chronicle", "week-03", 3, s3_client=s3, secrets_client=secrets)
    assert out is None
    s3.put_object.assert_not_called()


@contextmanager
def _resp(body_bytes):
    yield io.BytesIO(body_bytes)


def test_happy_path_stores_to_editorial_prefix(ei):
    secrets = mock.Mock()
    secrets.get_secret_value.return_value = {"SecretString": json.dumps({"api_key": "K"})}
    s3 = mock.Mock()
    search_json = json.dumps({"photos": [{"width": 1600, "height": 900, "alt": "quiet landscape at dawn", "src": {"landscape": "https://images.pexels.com/x.jpg"}, "photographer": "Jane Doe"}]}).encode()
    image_bytes = b"\xff\xd8\xff" + b"x" * 5000  # > 1024, looks like a jpeg

    def fake_urlopen(req, timeout=0):
        url = req.full_url if hasattr(req, "full_url") else req
        return _resp(image_bytes if "images.pexels.com" in str(url) else search_json)

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        out = ei.fetch_and_store("chronicle", "week-04", 4, s3_client=s3, secrets_client=secrets)

    assert out is not None
    assert out["image_url"] == "/assets/images/editorial/chronicle-week-04.jpg"
    assert "Jane Doe" in out["image_credit"] and "Pexels" in out["image_credit"]
    # stored under the editorial prefix with a jpeg content-type
    s3.put_object.assert_called_once()
    kw = s3.put_object.call_args.kwargs
    assert kw["Key"] == "generated/assets/images/editorial/chronicle-week-04.jpg"
    assert kw["ContentType"] == "image/jpeg"


def test_tiny_image_rejected(ei):
    secrets = mock.Mock()
    secrets.get_secret_value.return_value = {"SecretString": json.dumps({"api_key": "K"})}
    s3 = mock.Mock()
    search_json = json.dumps({"photos": [{"width": 1600, "height": 900, "alt": "quiet landscape at dawn", "src": {"landscape": "https://images.pexels.com/x.jpg"}, "photographer": "Jo"}]}).encode()

    def fake_urlopen(req, timeout=0):
        url = req.full_url if hasattr(req, "full_url") else req
        return _resp(b"tiny" if "images.pexels.com" in str(url) else search_json)

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        out = ei.fetch_and_store("chronicle", "week-05", 5, s3_client=s3, secrets_client=secrets)
    assert out is None
    s3.put_object.assert_not_called()


def test_slug_is_sanitised(ei):
    secrets = mock.Mock()
    secrets.get_secret_value.return_value = {"SecretString": json.dumps({"api_key": "K"})}
    s3 = mock.Mock()
    search_json = json.dumps({"photos": [{"width": 1600, "height": 900, "alt": "quiet landscape at dawn", "src": {"landscape": "https://images.pexels.com/x.jpg"}, "photographer": "Jo"}]}).encode()
    img = b"\xff\xd8\xff" + b"y" * 4000

    def fake_urlopen(req, timeout=0):
        url = req.full_url if hasattr(req, "full_url") else req
        return _resp(img if "images.pexels.com" in str(url) else search_json)

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        out = ei.fetch_and_store("podcast", "wk 7/../x", 7, s3_client=s3, secrets_client=secrets)
    # no path traversal / spaces survive into the S3 key
    assert ".." not in out["image_url"] and " " not in out["image_url"]
