"""
tests/test_qa_archive.py — the generation-time AI-surface archive (#1441).

Covers:
  - lambdas/qa_archive.py     key/body builders (pure), fail-soft archive_text,
                              surface-registry parity with eval_retention
  - tests/qa_manifest.py      ai_surface facet + the ai-screens emitter (slug
                              rule must mirror tests/visual_qa.py capture_page)
  - deploy/s3_lifecycle.json       the 90-day qa-archive rule is DECLARED (the
                              JSON is the bucket's full-config source of truth —
                              applied verbatim by deploy/apply_s3_lifecycle.sh;
                              an undeclared rule is deleted on the next apply run)

Run with:   python3 -m pytest tests/test_qa_archive.py -v
"""

import json
import os
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "lambdas"))
sys.path.insert(0, HERE)

import qa_manifest  # noqa: E402
from common import qa_archive  # noqa: E402
from experiment import eval_retention  # noqa: E402

NOW = datetime(2026, 7, 20, 14, 30, 5, tzinfo=timezone.utc)

# #2811 — the archive's DAY (and the time segment beside it) is the PACIFIC rendering
# of the instant. Expectations are computed through the module's OWN frame rather than
# hand-typed, so a fixture can never quietly encode the frame the code is being fixed
# out of. `_PT_DAY`/`_PT_HMS` are what `build_key` must produce for `NOW`.
_PT = NOW.astimezone(qa_archive.PACIFIC)
_PT_DAY = _PT.strftime("%Y-%m-%d")
_PT_HMS = _PT.strftime("%H%M%S")


# ── build_key ─────────────────────────────────────────────────────────────────


def test_build_key_is_date_first_under_text_prefix():
    key = qa_archive.build_key("chronicle", now=NOW)
    assert key.startswith(f"generated/qa_archive/text/{_PT_DAY}/chronicle--{_PT_HMS}--")
    assert key.endswith(".json")


def test_build_key_includes_variant_segment():
    key = qa_archive.build_key("coach_brief", variant="sleep", now=NOW)
    assert f"/{_PT_DAY}/coach_brief--sleep--{_PT_HMS}--" in key


def test_build_key_and_body_agree_on_the_pacific_day_after_17_00_pt():
    """#2811 — the whole reason this module moved frames, at an instant where the two
    calendars DISAGREE (so the test cannot go vacuously green like the 14:30Z one).

    2026-07-21T02:30Z is 2026-07-20 19:30 PT. A generation published on the PT evening
    of the 20th belongs in the 20th's review-pack day, and its body must say the same
    day its own key partitions on. `archived_at` stays the raw instant — frame-free.
    """
    evening = datetime(2026, 7, 21, 2, 30, 0, tzinfo=timezone.utc)
    assert evening.astimezone(qa_archive.PACIFIC).strftime("%Y-%m-%d") == "2026-07-20"
    assert evening.strftime("%Y-%m-%d") == "2026-07-21", "precondition: the calendars must disagree here"

    key = qa_archive.build_key("chronicle", now=evening)
    body = qa_archive.build_body("chronicle", "text", now=evening)
    assert key.startswith("generated/qa_archive/text/2026-07-20/")
    assert body["date"] == "2026-07-20"
    assert body["archived_at"] == evening.isoformat()


def test_build_key_sanitizes_hostile_segments():
    key = qa_archive.build_key("Weird Surface!", variant="../escape", now=NOW)
    day_part = key[len(qa_archive.TEXT_PREFIX) :]
    date_dir, leaf = day_part.split("/", 1)
    assert date_dir == "2026-07-20"
    assert "/" not in leaf  # no path traversal out of the day prefix
    assert ".." not in leaf
    assert leaf.startswith("weird-surface--escape--")


def test_build_key_unique_per_call():
    assert qa_archive.build_key("chronicle", now=NOW) != qa_archive.build_key("chronicle", now=NOW)


# ── build_body ────────────────────────────────────────────────────────────────


def test_build_body_shape():
    body = qa_archive.build_body("board_ask", "the answer", meta={"q": "why?"}, variant="dr_chen", now=NOW)
    assert body == {
        "schema": 1,
        "surface": "board_ask",
        "variant": "dr_chen",
        "date": "2026-07-20",
        "archived_at": NOW.isoformat(),
        "text": "the answer",
        "meta": {"q": "why?"},
    }


def test_build_body_caps_text():
    body = qa_archive.build_body("chronicle", "x" * (qa_archive._TEXT_CAP + 500), now=NOW)
    assert len(body["text"]) == qa_archive._TEXT_CAP


# ── archive_text ──────────────────────────────────────────────────────────────


def test_archive_text_puts_json_document(monkeypatch):
    s3 = MagicMock()
    monkeypatch.setattr(qa_archive, "_s3", s3)
    key = qa_archive.archive_text("state_of_matthew", "narrative text", meta={"narrated": True})
    assert key is not None and key.startswith(qa_archive.TEXT_PREFIX)
    kwargs = s3.put_object.call_args.kwargs
    assert kwargs["Bucket"] == qa_archive.BUCKET
    assert kwargs["Key"] == key
    assert kwargs["ContentType"] == "application/json"
    doc = json.loads(kwargs["Body"].decode("utf-8"))
    assert doc["surface"] == "state_of_matthew"
    assert doc["text"] == "narrative text"
    assert doc["meta"] == {"narrated": True}


def test_archive_text_is_fail_soft_on_aws_error(monkeypatch):
    s3 = MagicMock()
    s3.put_object.side_effect = RuntimeError("kaboom")
    monkeypatch.setattr(qa_archive, "_s3", s3)
    assert qa_archive.archive_text("chronicle", "text") is None  # never raises


def test_archive_text_skips_empty_text(monkeypatch):
    s3 = MagicMock()
    monkeypatch.setattr(qa_archive, "_s3", s3)
    assert qa_archive.archive_text("chronicle", "") is None
    assert qa_archive.archive_text("chronicle", None) is None
    s3.put_object.assert_not_called()


def test_archive_text_unknown_surface_still_archives(monkeypatch):
    s3 = MagicMock()
    monkeypatch.setattr(qa_archive, "_s3", s3)
    assert qa_archive.archive_text("brand_new_surface", "text") is not None
    s3.put_object.assert_called_once()


def test_archive_text_meta_survives_non_json_values(monkeypatch):
    """default=str: a Decimal/datetime in meta must not kill the archive."""
    from decimal import Decimal

    s3 = MagicMock()
    monkeypatch.setattr(qa_archive, "_s3", s3)
    key = qa_archive.archive_text("field_notes", "text", meta={"n": Decimal("1.5"), "at": NOW})
    assert key is not None
    s3.put_object.assert_called_once()


# ── registry parity ───────────────────────────────────────────────────────────


def test_every_eval_retention_surface_is_a_qa_archive_surface():
    """The two per-surface registries must never drift apart: every gated surface
    (eval_retention) is also an archived surface (#1441)."""
    assert set(eval_retention.SURFACES) <= set(qa_archive.SURFACES)


# ── the screenshot leg (manifest facet + emitter) ─────────────────────────────


def test_ai_surface_pages_declared():
    flagged = [p["path"] for p in qa_manifest.MANIFEST if p.get("ai_surface")]
    # The reader-visible AI-narrative pages as of #1441. A page joining or
    # leaving this set is a deliberate archive-coverage decision — update both.
    assert set(flagged) == {
        "/story/chronicle/",
        "/story/journal/",
        "/coaching/",
        "/coaching/by-coach/",
        "/coaching/lab-notes/",
        "/coaching/qa/",
        "/coaching/read/",
        "/method/board/",
    }


def test_ai_screenshot_slugs_mirror_visual_qa_slug_rule():
    """qa_manifest.ai_screenshot_slugs() must produce the exact slug visual_qa's
    capture_page uses to name the PNG (path.strip('/').replace('/', '-') or
    'home') — asserted against the literal in tests/visual_qa.py so a slug-rule
    change there breaks THIS test, not silently the S3 upload step."""
    with open(os.path.join(HERE, "visual_qa.py")) as f:
        src = f.read()
    assert 'slug = path.strip("/").replace("/", "-") or "home"' in src
    for p in qa_manifest.MANIFEST:
        if p.get("ai_surface"):
            expected = p["path"].strip("/").replace("/", "-") or "home"
            assert expected in qa_manifest.ai_screenshot_slugs()


# ── lifecycle rule declared in the source of truth ────────────────────────────


def test_lifecycle_script_declares_90d_qa_archive_rules():
    """deploy/apply_s3_lifecycle.sh PUTs deploy/s3_lifecycle.json verbatim, which
    REPLACES the whole bucket config on each run — if a qa-archive rule ever drops
    out of the JSON, the next apply run silently deletes the retention. Pin BOTH
    rules, and pin the versioned-bucket mechanics: a bare Days-90 expiration on
    this versioned bucket only writes a delete marker, and the overlapping
    generated/ rule's NewerNoncurrentVersions:1 carve-out would keep the
    (write-once) data version's bytes forever. The qa-archive rule must therefore
    carry its own NoncurrentVersionExpiration WITHOUT a keep-newest carve-out,
    plus a separate expired-delete-marker sweep rule. (#2799/DIL-026 externalized
    the rules from the script's heredoc into this JSON — the declared source is
    now the file both the apply script and deploy/drift_sentinel.py's
    check_s3_lifecycle read, so this guard reads the same JSON, not script text.)"""
    with open(os.path.join(REPO, "deploy", "s3_lifecycle.json")) as f:
        rules = {r["ID"]: r for r in json.load(f)["Rules"]}

    assert "qa-archive-expire-90d" in rules, "qa-archive-expire-90d rule missing from deploy/s3_lifecycle.json"
    rule = rules["qa-archive-expire-90d"]
    assert rule["Filter"] == {"Prefix": "generated/qa_archive/"}
    assert rule["Expiration"] == {"Days": 90}
    assert (
        "NoncurrentVersionExpiration" in rule
    ), "qa-archive rule must expire noncurrent versions (versioned bucket — else bytes are retained forever)"
    assert isinstance(rule["NoncurrentVersionExpiration"].get("NoncurrentDays"), int)
    assert (
        "NewerNoncurrentVersions" not in rule["NoncurrentVersionExpiration"]
    ), "no keep-newest carve-out: qa_archive keys are write-once, the newest noncurrent version IS the bytes"

    assert "qa-archive-clean-delete-markers" in rules, "qa-archive-clean-delete-markers rule missing (expired delete markers would accrete)"
    rule2 = rules["qa-archive-clean-delete-markers"]
    assert rule2["Filter"] == {"Prefix": "generated/qa_archive/"}
    assert rule2["Expiration"] == {"ExpiredObjectDeleteMarker": True}


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
