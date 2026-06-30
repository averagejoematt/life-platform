"""cover_pipeline_lambda.py — fetch + cache a book cover (spec §8).

On add: Open Library Covers (by ISBN/OLID) → Google Books (by ISBN/title) →
**designed placeholder**. The chosen image is always DOWNLOADED and stored to
S3 under `generated/covers/<bookId>.jpg` — we NEVER hot-link a third-party URL
(spec §8). `BOOK#<bookId>.coverS3Key` + `coverSource` are then updated.

Safe-write note (ADR-046): the spec says cache to `covers/`, but platform law
requires Lambda-generated files under the `generated/` prefix (CloudFront-routed,
delete-protected). We honor both: key = `generated/covers/<bookId>.jpg`, public
URL = `/covers/<bookId>.jpg` (the edge strips `generated/`).

Event: {"bookId"?, "isbn13"?, "olid"?, "title"?, "author"?}  (bookId derived if
absent). Fail-soft: a fetch failure falls through to the placeholder, so a book
ALWAYS gets a cover. Bundled with lambdas/ (Pillow via the standalone pillow-layer);
imports no shared-layer modules.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request

import boto3

from reading import cover_placeholder, reading_keys as rk, reading_store

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-west-2")
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
COVER_PREFIX = "generated/covers"  # ADR-046 generated/ prefix
PUBLIC_PREFIX = "/covers"  # CloudFront strips generated/

# Open Library + Google Books both 403 the bare Python-urllib UA from behind their
# CDNs — send a real User-Agent on every call (the editorial_image Cloudflare lesson).
_UA = "averagejoematt.com/1.0 (+https://averagejoematt.com)"
_MIN_BYTES = 1024  # smaller than this = a 1x1 tracking pixel / empty 200, treat as miss

s3 = boto3.client("s3", region_name=REGION)


def _get_bytes(url: str, timeout: int = 15) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            data = resp.read()
        return data if data and len(data) >= _MIN_BYTES else None
    except Exception as e:  # noqa: BLE001 — any miss is fine; we fall through
        logger.info("[cover] fetch miss %s (%s)", url, type(e).__name__)
        return None


def _open_library(isbn13: str | None, olid: str | None) -> bytes | None:
    # ?default=false → 404 instead of returning a blank placeholder image
    if olid:
        b = _get_bytes(f"https://covers.openlibrary.org/b/olid/{urllib.parse.quote(olid)}-L.jpg?default=false")
        if b:
            return b
    if isbn13:
        b = _get_bytes(f"https://covers.openlibrary.org/b/isbn/{urllib.parse.quote(isbn13)}-L.jpg?default=false")
        if b:
            return b
    return None


def _google_books(isbn13: str | None, title: str | None, author: str | None) -> bytes | None:
    if isbn13:
        q = f"isbn:{isbn13}"
    elif title:
        q = f"intitle:{title}" + (f"+inauthor:{author}" if author else "")
    else:
        return None
    url = "https://www.googleapis.com/books/v1/volumes?" + urllib.parse.urlencode({"q": q, "maxResults": 1})
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        logger.info("[cover] google books miss (%s)", type(e).__name__)
        return None
    items = payload.get("items") or []
    if not items:
        return None
    links = (items[0].get("volumeInfo") or {}).get("imageLinks") or {}
    img_url = links.get("thumbnail") or links.get("smallThumbnail")
    if not img_url:
        return None
    return _get_bytes(img_url.replace("http://", "https://"))


def fetch_cover(book_id: str, *, isbn13=None, olid=None, title=None, author=None) -> tuple[bytes, str]:
    """Return (jpeg_bytes, source). Always succeeds — placeholder is the floor."""
    data = _open_library(isbn13, olid)
    if data:
        return data, "openlibrary"
    data = _google_books(isbn13, title, author)
    if data:
        return data, "googlebooks"
    return cover_placeholder.render(title or "", author or ""), "placeholder"


def process_book(book: dict, *, store=True) -> dict:
    """Resolve identifiers, fetch+cache the cover, update BOOK#.coverS3Key."""
    bid = book.get("bookId") or rk.book_id(
        isbn13=book.get("isbn13"), olid=book.get("olid"), title=book.get("title"), author=book.get("author")
    )
    data, source = fetch_cover(bid, isbn13=book.get("isbn13"), olid=book.get("olid"), title=book.get("title"), author=book.get("author"))
    key = f"{COVER_PREFIX}/{bid}.jpg"
    s3.put_object(Bucket=S3_BUCKET, Key=key, Body=data, ContentType="image/jpeg", CacheControl="max-age=2592000")
    if store:
        reading_store.update_cover_key(bid, key, source)
    return {"bookId": bid, "coverS3Key": key, "coverUrl": f"{PUBLIC_PREFIX}/{bid}.jpg", "coverSource": source, "bytes": len(data)}


def lambda_handler(event, context=None):
    """Entry: a single book dict, or {"books": [...]}. Per-book try/except so one
    bad book never kills the batch; a top-level guard structures any unexpected error."""
    try:
        event = event or {}
        books = event.get("books") if isinstance(event.get("books"), list) else [event]
        results, errors = [], []
        for book in books:
            if not isinstance(book, dict):
                continue
            try:
                results.append(process_book(book))
            except Exception as e:  # noqa: BLE001 — isolate per-book failures
                logger.exception("[cover] failed for %s", book.get("title"))
                errors.append({"title": book.get("title"), "error": type(e).__name__})
        return {"statusCode": 200, "body": json.dumps({"processed": results, "errors": errors})}
    except Exception as e:  # noqa: BLE001 — top-level resilience (I4): log + structured error
        logger.exception("[cover] handler failed")
        return {"statusCode": 500, "body": json.dumps({"error": type(e).__name__})}
