"""editorial_image.py — atmospheric free-license cover imagery for the narrative
Story surfaces (chronicle · podcast · blog) ONLY. Never for data/meal surfaces.

Design (per the approved visual-uplevel plan, Part II):
  * Source: Pexels (its license permits download + self-hosting, which our
    fetch-and-store-to-S3 model needs). Key in Secrets Manager: life-platform/pexels.
  * Query is a CONSTRAINED, evocative atmospheric pool (dawn light, fog road…),
    deterministically picked by a stable seed — never a literal "gym/salad" cliché,
    so an automatic pick still reads as tasteful editorial texture.
  * Fully fail-soft: ANY problem (kill-switch off, missing key, API/network error,
    no result) returns None and the caller publishes exactly as before. This module
    must never be able to break the daily chronicle/podcast generators.
  * Kill-switch: env EDITORIAL_IMAGES must equal "on" (default off).

Returns {"image_url": "/assets/images/editorial/<kind>-<slug>.jpg",
         "image_credit": "Photo by <name> on Pexels"} or None.

Bundled with the lambdas/ asset (NOT the layer) — no layer rebuild needed.
"""

import json
import logging
import os
import urllib.parse
import urllib.request

logger = logging.getLogger()

REGION = os.environ.get("AWS_REGION", "us-west-2")
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
PEXELS_SECRET_ID = "life-platform/pexels"  # noqa: S105 — a Secrets Manager id, not a credential. {"api_key": "..."}
EDITORIAL_PREFIX = "generated/assets/images/editorial"
PUBLIC_PREFIX = "/assets/images/editorial"  # CloudFront strips the generated/ origin path
# Pexels sits behind Cloudflare, which 403s the default Python-urllib User-Agent
# ("error code: 1010"). A real UA is required on BOTH the API call and the image fetch.
_UA = "averagejoematt.com/1.0 (+https://averagejoematt.com)"

# A curated pool of atmospheric, non-literal landscape moods. Deliberately NOT
# health/fitness imagery — these read as editorial texture (a magazine feature
# header), never as a claim about the day's data. Keep them calm + warm-leaning
# so the duotone CSS treatment lands cohesively with the ember/ink palette.
ATMOSPHERIC_QUERIES = [
    "dawn fog landscape",
    "quiet shoreline morning",
    "misty forest light",
    "mountain dusk horizon",
    "rain on window",
    "empty road morning light",
    "still lake reflection",
    "golden hour field",
    "overcast coastline",
    "first light hills",
    "winter morning mist",
    "desert dawn",
]


def enabled():
    """The kill-switch. Default OFF — imagery only runs when explicitly enabled."""
    return os.environ.get("EDITORIAL_IMAGES", "off").strip().lower() == "on"


def pick_query(seed):
    """Deterministic, tasteful query from a stable integer seed."""
    try:
        return ATMOSPHERIC_QUERIES[int(seed) % len(ATMOSPHERIC_QUERIES)]
    except Exception:
        return ATMOSPHERIC_QUERIES[0]


def _api_key(secrets_client):
    try:
        raw = secrets_client.get_secret_value(SecretId=PEXELS_SECRET_ID)["SecretString"]
        data = json.loads(raw)
        return (data.get("api_key") or data.get("API_KEY") or "").strip() or None
    except Exception as e:
        logger.info("[editorial_image] no Pexels key (%s) — skipping imagery", type(e).__name__)
        return None


def _search(api_key, query, seed):
    """Query Pexels, return (download_url, credit) or (None, None). Fail-soft."""
    url = "https://api.pexels.com/v1/search?" + urllib.parse.urlencode(
        {"query": query, "orientation": "landscape", "size": "large", "per_page": "15"}
    )
    req = urllib.request.Request(url, headers={"Authorization": api_key, "User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=12) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    photos = payload.get("photos") or []
    if not photos:
        return None, None
    photo = photos[int(seed) % len(photos)]
    src = photo.get("src") or {}
    dl = src.get("landscape") or src.get("large") or src.get("large2x") or src.get("original")
    name = photo.get("photographer") or "Pexels"
    credit = f"Photo by {name} on Pexels"
    return dl, credit


def fetch_and_store(kind, slug, seed, *, s3_client=None, secrets_client=None, bucket=None):
    """Fetch one atmospheric image and store it under generated/assets/images/editorial/.

    kind: "chronicle" | "podcast" | "blog". slug: a filesystem-safe id (e.g. "week-03").
    seed: any int (stable per post) → deterministic query + photo pick.
    Clients are created on demand if not supplied (so callers without a secrets
    client need no setup). Returns {"image_url","image_credit"} or None. NEVER raises.
    """
    if not enabled():
        return None
    bucket = bucket or S3_BUCKET
    safe_slug = "".join(c if (c.isalnum() or c in "-_") else "-" for c in str(slug)).strip("-") or "post"
    try:
        import boto3  # local import keeps the module importable in non-AWS test contexts

        if s3_client is None:
            s3_client = boto3.client("s3", region_name=REGION)
        if secrets_client is None:
            secrets_client = boto3.client("secretsmanager", region_name=REGION)
        api_key = _api_key(secrets_client)
        if not api_key:
            return None
        query = pick_query(seed)
        dl_url, credit = _search(api_key, query, seed)
        if not dl_url:
            return None
        with urllib.request.urlopen(urllib.request.Request(dl_url, headers={"User-Agent": _UA}), timeout=20) as r:
            img_bytes = r.read()
        if not img_bytes or len(img_bytes) < 1024:
            return None
        key = f"{EDITORIAL_PREFIX}/{kind}-{safe_slug}.jpg"
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=img_bytes,
            ContentType="image/jpeg",
            CacheControl="max-age=2592000",  # 30 days — these never change once chosen
        )
        logger.info("[editorial_image] stored %s (%d bytes, q=%r)", key, len(img_bytes), query)
        return {"image_url": f"{PUBLIC_PREFIX}/{kind}-{safe_slug}.jpg", "image_credit": credit}
    except Exception as e:
        logger.warning("[editorial_image] fetch failed (%s) — publishing without image", type(e).__name__)
        return None
