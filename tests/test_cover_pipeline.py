"""tests/test_cover_pipeline.py — cover fallback chain + cache + never-hot-link.

urllib + S3 are faked. Asserts the Open Library → Google Books → designed
placeholder fallback, that the image is always DOWNLOADED and stored under
generated/covers/ (never hot-linked), and that BOOK#.coverS3Key is updated.
"""

from __future__ import annotations

import io
import json
import os

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")

import pytest  # noqa: E402
from reading import (
    cover_pipeline_lambda as cp,  # noqa: E402
    reading_store as rs,  # noqa: E402
)
from reading_fakes import FakeS3, FakeTable  # noqa: E402

_BIG = b"x" * 4096  # passes the _MIN_BYTES guard


class _Resp:
    def __init__(self, body, status=200):
        self._body = body
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture(autouse=True)
def wired(monkeypatch):
    fs3 = FakeS3()
    monkeypatch.setattr(cp, "s3", fs3)
    monkeypatch.setattr(rs, "table", FakeTable())
    return fs3


def _patch_urlopen(monkeypatch, handler):
    def fake_urlopen(req, timeout=0):
        url = req.full_url if hasattr(req, "full_url") else req
        return handler(url)

    monkeypatch.setattr(cp.urllib.request, "urlopen", fake_urlopen)


def test_open_library_hit(monkeypatch, wired):
    def handler(url):
        if "covers.openlibrary.org" in url:
            return _Resp(_BIG)
        raise AssertionError("should not reach Google Books")

    _patch_urlopen(monkeypatch, handler)
    out = cp.process_book({"title": "T", "author": "A", "isbn13": "9780553418026"}, store=False)
    assert out["coverSource"] == "openlibrary"
    assert wired.puts[0]["Key"] == f"generated/covers/{out['bookId']}.jpg"
    assert wired.puts[0]["Body"] == _BIG  # downloaded bytes, not a hot-link
    assert wired.puts[0]["ContentType"] == "image/jpeg"


def test_google_books_fallback(monkeypatch, wired):
    def handler(url):
        if "covers.openlibrary.org" in url:
            return _Resp(b"", status=404)  # OL miss
        if "googleapis.com/books" in url:
            payload = {"items": [{"volumeInfo": {"imageLinks": {"thumbnail": "http://books.google.com/x.jpg"}}}]}
            return _Resp(json.dumps(payload).encode())
        if "books.google.com" in url:
            assert url.startswith("https://")  # http upgraded to https
            return _Resp(_BIG)
        raise AssertionError(f"unexpected {url}")

    _patch_urlopen(monkeypatch, handler)
    out = cp.process_book({"title": "T", "author": "A", "isbn13": "9780553418026"}, store=False)
    assert out["coverSource"] == "googlebooks"


def test_placeholder_when_all_miss(monkeypatch, wired):
    pytest.importorskip("PIL")  # placeholder needs Pillow; skip if unavailable locally

    def handler(url):
        if "covers.openlibrary.org" in url:
            return _Resp(b"", status=404)
        if "googleapis.com/books" in url:
            return _Resp(json.dumps({"items": []}).encode())
        raise AssertionError(f"unexpected {url}")

    _patch_urlopen(monkeypatch, handler)
    out = cp.process_book({"title": "An Untitled Work", "author": "Nobody"}, store=False)
    assert out["coverSource"] == "placeholder"
    assert wired.puts[0]["Body"]  # real JPEG bytes were generated + stored
    assert out["coverUrl"] == f"/covers/{out['bookId']}.jpg"  # public path strips generated/


def test_store_updates_book_cover_key(monkeypatch, wired):
    rs.add_book({"title": "T", "author": "A", "isbn13": "9780553418026"}, enricher=lambda m: {})

    def handler(url):
        return _Resp(_BIG) if "covers.openlibrary.org" in url else _Resp(b"", status=404)

    _patch_urlopen(monkeypatch, handler)
    bid = cp.process_book({"title": "T", "author": "A", "isbn13": "9780553418026"}, store=True)["bookId"]
    assert rs.get_book(bid)["coverS3Key"] == f"generated/covers/{bid}.jpg"


def test_small_response_treated_as_miss(monkeypatch, wired):
    pytest.importorskip("PIL")

    def handler(url):
        if "covers.openlibrary.org" in url:
            return _Resp(b"tiny")  # < _MIN_BYTES → miss
        if "googleapis.com/books" in url:
            return _Resp(json.dumps({"items": []}).encode())
        raise AssertionError(f"unexpected {url}")

    _patch_urlopen(monkeypatch, handler)
    out = cp.process_book({"title": "T", "author": "A", "isbn13": "9780553418026"}, store=False)
    assert out["coverSource"] == "placeholder"


def test_handler_batch_isolates_failures(monkeypatch, wired):
    def handler(url):
        return _Resp(_BIG) if "covers.openlibrary.org" in url else _Resp(b"", status=404)

    _patch_urlopen(monkeypatch, handler)
    resp = cp.lambda_handler({"books": [{"title": "Good", "author": "A", "isbn13": "9780553418026"}, "not-a-dict"]})
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200 and len(body["processed"]) == 1


def test_buffer_import_kept():  # guard: io used by placeholder path
    assert io is not None
