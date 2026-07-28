"""qa_archive.py — generation-time archive of every AI surface's published text (#1441).

AI generations were point-in-time: nothing recorded what a reader actually saw on
any AI surface, so post-hoc investigation of a bad generation was screenshot
archaeology. This module is the ONE writer for the durable archive: every AI
surface calls `archive_text()` at the moment its final, gate-passed text is
published (DDB write / reader response), and the copy lands in S3 under

    generated/qa_archive/text/{YYYY-MM-DD}/{surface}[--variant]--{HHMMSS}--{uuid8}.json

Key design (date-first) is deliberate: the D3 weekly review pack (#1442) lists a
date range across ALL surfaces with 7 prefix listings — no per-surface fan-out.
The screenshot leg lives beside it under generated/qa_archive/screenshots/
(uploaded by the daily standalone visual-qa sweep — reader-rendered pages, the
closest honest "screenshot at generation time" without a browser-in-Lambda).

Retention: 90 listed days via the lifecycle pair `qa-archive-expire-90d` +
`qa-archive-clean-delete-markers` (deploy/apply_s3_lifecycle.sh — the bucket's
lifecycle source of truth). The bucket is VERSIONED, so the rule pair delete-
markers the current version at 90d, expires the noncurrent bytes 7d later, and
sweeps the expired marker — bytes are fully gone ≈ day 97 (see the script's
header for why a bare Days-90 rule would have retained 100% of bytes forever).
The prefix rides inside generated/, ADR-046, so CloudFront/site sync can never
touch it and lifecycle expiration coexists with the DeleteObject deny on
generated/*.

Cost (measured basis, #1441 acceptance): text is trivial — the six surfaces
produce ≈25 KB/day (8 coach briefs ≈2.5 KB each at max_tokens=600, a handful of
board answers ≤1.2 KB, weekly chronicle ≈20 KB, weekly SoM ≈3 KB, weekly field
notes ≈4 KB, quarterly memoirs ≈4 KB×12) → <2.5 MB steady state at 90 days.
Screenshots dominate: 8 AI pages (the qa_manifest ai_surface facet — count is
test-pinned in tests/test_qa_archive.py) × ~0.5–1 MB full-page PNG daily ≈
500–750 MB steady state ≈ $0.012–0.018/mo storage + ~$0.001/mo PUTs —
comfortably inside the issue's ~$1/mo band. Verify real sizes after a week:
    aws s3 ls s3://matthew-life-platform/generated/qa_archive/ --recursive --summarize

Contract (mirrors eval_retention.py):
- `archive_text()` is FAIL-SOFT: it must never raise into a generation path. A
  lost archive copy costs one log line, never a reader-facing surface. The S3
  client carries tight timeouts + a single retry attempt because board_ask runs
  this inline in the reader-facing response path — a slow S3 must degrade to a
  lost copy, never a hung reader request.
- Readers (`list_day` / `read_entry`) raise loudly — the review pack wants
  failures visible, not silently-empty weeks.

Writer IAM: each surface's role gets s3:PutObject on generated/qa_archive/text/*
(cdk/stacks/role_policies.py; the daily-brief role's generated/* grant already
covers the coach_brief surface; the screenshot leg's grant lives on the
github-actions-diagnosis-role, scoped to .../screenshots/*).
"""

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone

logger = logging.getLogger()

BUCKET = os.environ.get("BUCKET_NAME", "matthew-life-platform")
TEXT_PREFIX = "generated/qa_archive/text/"
SCREENSHOT_PREFIX = "generated/qa_archive/screenshots/"

# The known AI surfaces — a superset of eval_retention.SURFACES (asserted in
# tests/test_qa_archive.py so the two registries can never drift apart). An
# UNKNOWN surface name still archives (fail-soft beats a dropped record when a
# new surface forgets to register) — it just logs a warning.
SURFACES = ("board_ask", "chronicle", "memoir", "state_of_matthew", "field_notes", "coach_brief")

_TEXT_CAP = 100_000  # chars — the full chronicle markdown is ~20k; nothing legitimate approaches this
_SEGMENT_RE = re.compile(r"[^a-z0-9_-]+")

_s3 = None


def _get_s3():
    global _s3
    if _s3 is None:
        import boto3
        from botocore.config import Config

        _s3 = boto3.client(
            "s3",
            region_name=os.environ.get("AWS_REGION", "us-west-2"),
            # Tight budget: archive_text() runs inline in reader-facing paths
            # (board_ask) — under S3 latency the fail-soft contract must degrade
            # to a lost copy in ≤ ~8s worst case, never a hung reader request.
            config=Config(connect_timeout=3, read_timeout=5, retries={"max_attempts": 1}),
        )
    return _s3


def _clean_segment(value, fallback="unknown"):
    """Key-safe segment: lowercase, [a-z0-9_-] only, never empty."""
    cleaned = _SEGMENT_RE.sub("-", str(value).lower()).strip("-")
    return cleaned[:64] or fallback


def build_key(surface, variant=None, now=None):
    """Pure: the S3 key for one archived generation. Date-first so the D3 review
    pack lists a week with 7 prefix listings across ALL surfaces."""
    now = now or datetime.now(timezone.utc)
    parts = [_clean_segment(surface)]
    if variant:
        parts.append(_clean_segment(variant))
    parts.append(now.strftime("%H%M%S"))
    parts.append(uuid.uuid4().hex[:8])
    return f"{TEXT_PREFIX}{now.date().isoformat()}/{'--'.join(parts)}.json"


def build_body(surface, text, meta=None, variant=None, now=None):
    """Pure: the archived JSON document. Split from archive_text() so the shape
    is unit-testable without AWS."""
    now = now or datetime.now(timezone.utc)
    return {
        "schema": 1,
        "surface": surface,
        "variant": variant,
        "date": now.date().isoformat(),
        "archived_at": now.isoformat(),
        "text": (text or "")[:_TEXT_CAP],
        "meta": meta or {},
    }


def archive_text(surface, text, meta=None, variant=None):
    """Archive one published AI generation. FAIL-SOFT: never raises, returns the
    S3 key on success or None.

    surface  one of SURFACES (unknown names archive anyway, with a warning)
    text     the final text the reader-facing record carries (post-gate)
    meta     small JSON-safe dict of context (question, week, output_type, ...)
    variant  sub-surface discriminator (coach_id, persona, ...) — lands in the key
    """
    try:
        if not text:
            logger.info(f"[qa_archive] {surface}: empty text — nothing archived")
            return None
        if surface not in SURFACES:
            logger.warning(f"[qa_archive] unknown surface {surface!r} (known: {SURFACES}) — archiving anyway")
        now = datetime.now(timezone.utc)
        key = build_key(surface, variant=variant, now=now)
        body = build_body(surface, text, meta=meta, variant=variant, now=now)
        _get_s3().put_object(
            Bucket=BUCKET,
            Key=key,
            Body=json.dumps(body, default=str).encode("utf-8"),
            ContentType="application/json",
        )
        return key
    except Exception as e:  # noqa: BLE001 — the archive is never load-bearing
        logger.warning(f"[qa_archive] archive_text({surface}) failed (non-fatal): {e}")
        return None


def list_day(date_str, kind="text"):
    """Keys archived for one YYYY-MM-DD day (kind: "text" | "screenshots").
    Raises on AWS errors — the D3 review pack wants loud failures."""
    prefix = {"text": TEXT_PREFIX, "screenshots": SCREENSHOT_PREFIX}[kind] + f"{date_str}/"
    keys, token = [], None
    while True:
        kwargs = {"Bucket": BUCKET, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        resp = _get_s3().list_objects_v2(**kwargs)
        keys.extend(obj["Key"] for obj in resp.get("Contents", []))
        token = resp.get("NextContinuationToken")
        if not token:
            return keys


def read_entry(key):
    """One archived text document, parsed. Raises on AWS/JSON errors (loud)."""
    resp = _get_s3().get_object(Bucket=BUCKET, Key=key)
    return json.loads(resp["Body"].read())
