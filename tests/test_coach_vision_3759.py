"""tests/test_coach_vision_3759.py — the weekly coach-vision observation (#3759, epic #3743).

Offline, no AWS: the pure module (`coach.coach_vision`) is driven directly, and the Lambda's
`run()` is driven end-to-end with a fake table, a fake S3 reader and a recording fake for
`bedrock_client.invoke`. What the tests pin, box by box:

  1. the run reads this week's set + the prior one, sends IMAGES through the invoke body,
     and writes ONE owner-only record (Decimal-safe) on the photo set's date;
  2. the record carries the qualitative deltas, the band as low–high with the literal label
     'visual estimate, not a measurement', the nearest DEXA + the tape trend it was anchored
     to, and the model id;
  3. the budget guard pauses it with the reader-narrative band (tier 2) and a paused run
     writes nothing — a negative control, not an assertion that the feature is listed;
  4. the two consumers are field-selective and carry the label; the thread lines withhold a
     stale record.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# mcp.config reads these at import (the MCP tool test below); the same defaults tests/test_layer_status_contract_3769.py sets.
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ai import budget_guard  # noqa: E402
from coach import (
    coach_vision as cv,  # noqa: E402
    coach_vision_lambda as lam,  # noqa: E402
)
from fakes import FakeDdbTable  # noqa: E402

TODAY = "2026-10-12"  # a Monday; the protocol set was captured on Sunday
NOW = datetime(2026, 10, 12, 17, 0, tzinfo=timezone.utc)
PREFIX = "raw/matthew/progress_photos"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def _index_row(date, pose, week_n=None, sha="abc"):
    row = {
        "pk": cv.PHOTO_INDEX_PK,
        "sk": f"DATE#{date}#{pose}",
        "date": date,
        "pose": pose,
        "s3_key": f"{PREFIX}/{date[:4]}/{date[5:7]}/{date}-{pose}.jpg",
        "sha256": f"{sha}-{date}-{pose}",
        "bytes": 100,
    }
    if week_n is not None:
        row["week_n"] = week_n
    return row


def _rows():
    return [
        *[_index_row("2026-09-27", p, week_n=4) for p in cv.POSES],
        *[_index_row("2026-10-11", p, week_n=6) for p in cv.POSES],
    ]


def _dexa(scan_date, pct):
    return {"pk": cv.DEXA_PK, "sk": f"DATE#{scan_date}", "scan_date": scan_date, "body_composition": {"body_fat_pct": Decimal(str(pct))}}


def _tape(date, waist, chest=None):
    row = {"pk": cv.MEASUREMENTS_PK, "sk": f"DATE#{date}", "date": date, "waist_navel_in": Decimal(str(waist))}
    if chest is not None:
        row["chest_in"] = Decimal(str(chest))
    return row


class _Table(FakeDdbTable):
    """A pk-dispatching fake: `query` answers by the `:pk` value the handler passes."""

    def query(self, **kwargs):
        self.query_calls.append(kwargs)
        pk = (kwargs.get("ExpressionAttributeValues") or {}).get(":pk")
        sk = (kwargs.get("ExpressionAttributeValues") or {}).get(":sk")
        items = [i for i in self.store.values() if i.get("pk") == pk]
        if sk is not None:
            items = [i for i in items if i.get("sk") == sk]
        items.sort(key=lambda i: str(i.get("sk")), reverse=not kwargs.get("ScanIndexForward", True))
        limit = kwargs.get("Limit")
        return {"Items": items[:limit] if limit else items}


class _S3:
    def __init__(self):
        self.keys = []

    def get_object(self, Bucket, Key):
        self.keys.append(Key)

        class _Body:
            def read(self_inner):
                return JPEG

        return {"Body": _Body()}


def _good_reply():
    return {
        "qualitative": "Shoulders read a touch fuller than the 2026-09-27 set and the waist looks narrower, in line with the tape at 34.5 in.",
        "deltas": ["waist narrower", "shoulders fuller"],
        "body_fat_low_pct": 20,
        "body_fat_high_pct": 24,
        "confidence": "low",
    }


def _recording_invoke(calls, reply=None):
    def invoke(body, model_name=None):
        calls.append({"body": body, "model_name": model_name})
        return {"content": [{"type": "text", "text": json.dumps(reply or _good_reply())}], "stop_reason": "end_turn"}

    return invoke


@pytest.fixture
def world():
    table = _Table(
        rows=[
            *_rows(),
            _dexa("2026-09-20", 24.3),
            _dexa("2025-01-10", 31.0),
            _tape("2026-08-30", 35.25, 41.0),
            _tape("2026-10-04", 34.5, 41.0),
        ]
    )
    return table, _S3()


# ── sets ──────────────────────────────────────────────────────────────────────
def test_sets_group_by_stamped_week_and_pick_this_week_plus_prior():
    sets = cv.group_sets(_rows())
    assert [s["as_of"] for s in sets] == ["2026-09-27", "2026-10-11"]
    current, prior = cv.pick_sets(sets, TODAY)
    assert current["as_of"] == "2026-10-11" and prior["as_of"] == "2026-09-27"
    assert set(current["poses"]) == set(cv.POSES)


def test_a_set_older_than_the_window_is_not_this_week():
    sets = cv.group_sets([_index_row("2026-09-27", p, week_n=4) for p in cv.POSES])
    assert cv.pick_sets(sets, TODAY) == (None, None)


def test_a_retake_replaces_the_earlier_pose_and_an_unknown_pose_is_dropped():
    rows = [
        _index_row("2026-10-10", "front", week_n=6),
        _index_row("2026-10-11", "front", week_n=6),
        _index_row("2026-10-11", "top", week_n=6),
    ]
    (s,) = cv.group_sets(rows)
    assert s["poses"]["front"]["date"] == "2026-10-11" and "top" not in s["poses"]


def test_the_prefix_comes_from_the_registry_facet_and_keys_are_checked_against_it():
    from ingestion.source_registry import SOURCE_REGISTRY

    assert cv.photo_prefix() == SOURCE_REGISTRY["progress_photos"]["raw_layout"]["prefix"]
    assert cv.key_is_under_prefix(f"{cv.photo_prefix()}/2026/10/2026-10-11-front.jpg", cv.photo_prefix())
    assert not cv.key_is_under_prefix("raw/matthew/withings/2026/10/x.json", cv.photo_prefix())
    assert not cv.key_is_under_prefix(f"{cv.photo_prefix()}/../secret.jpg", cv.photo_prefix())


# ── anchors ───────────────────────────────────────────────────────────────────
def test_nearest_dexa_is_nearest_in_time_not_latest():
    items = [_dexa("2025-01-10", 31.0), _dexa("2026-09-20", 24.3), _dexa("2026-12-01", 22.0)]
    assert cv.nearest_dexa(items, "2026-10-11")["scan_date"] == "2026-09-20"
    assert cv.nearest_dexa(items, "2026-11-25")["scan_date"] == "2026-12-01"
    assert cv.nearest_dexa([{"scan_date": "2026-09-20"}], "2026-10-11") is None  # no figure, no anchor


def test_tape_trend_reads_the_two_latest_sessions_and_says_so_with_one():
    t = cv.tape_trend([_tape("2026-08-30", 35.25), _tape("2026-10-04", 34.5), _tape("2026-10-20", 34.0)], "2026-10-11")
    assert t["latest"]["session_date"] == "2026-10-04" and t["previous"]["session_date"] == "2026-08-30"
    assert t["waist_delta_in"] == -0.75
    one = cv.tape_trend([_tape("2026-10-04", 34.5)], "2026-10-11")
    assert "previous" not in one and "waist_delta_in" not in one
    assert cv.tape_trend([], "2026-10-11") is None


# ── the request ───────────────────────────────────────────────────────────────
def test_the_body_carries_both_sets_as_labelled_images_and_the_anchors(world):
    table, s3 = world
    calls = []
    out = lam.run(table=table, s3=s3, bucket="b", today=TODAY, invoke_fn=_recording_invoke(calls), allow_fn=lambda f: True, now=NOW)
    assert out["status"] == "written", out
    (call,) = calls
    content = call["body"]["messages"][0]["content"]
    images = [b for b in content if b.get("type") == "image"]
    assert len(images) == 6, "three poses × two sets"
    assert all(base64.b64decode(b["source"]["data"]) == JPEG for b in images)
    assert all(b["source"]["media_type"] == "image/jpeg" for b in images)
    text = " ".join(b["text"] for b in content if b.get("type") == "text")
    assert "THIS WEEK's set, captured 2026-10-11" in text and "PRIOR set, captured 2026-09-27" in text
    assert "Nearest DEXA scan (2026-09-20): body fat 24.3%" in text
    assert "waist at navel 34.5 in" in text and "change -0.75 in" in text
    assert "visual estimate, not a measurement" in text.lower() or "VISUAL ESTIMATE" in text
    assert call["body"]["output_config"]["format"]["schema"] == cv.OBSERVATION_SCHEMA
    assert call["model_name"] == cv.model_for("coach_vision")
    assert sorted(s3.keys) == sorted(r["s3_key"] for r in _rows())


# ── the record ────────────────────────────────────────────────────────────────
def test_the_record_carries_every_field_the_box_names_and_is_decimal_safe(world):
    table, s3 = world
    out = lam.run(table=table, s3=s3, bucket="b", today=TODAY, invoke_fn=_recording_invoke([]), allow_fn=lambda f: True, now=NOW)
    assert out == {"status": "written", "pk": cv.RECORD_PK, "sk": "DATE#2026-10-11", "model_id": cv.model_for("coach_vision")}
    (item,) = table.puts
    assert item["pk"] == "USER#matthew#SOURCE#coach_vision" and item["sk"] == "DATE#2026-10-11"
    est = item["body_fat_estimate"]
    assert est["label"] == "visual estimate, not a measurement"
    assert est["low_pct"] == Decimal("20.0") and est["high_pct"] == Decimal("24.0") and est["confidence"] == "low"
    assert item["deltas"] == ["waist narrower", "shoulders fuller"]
    assert item["qualitative"].startswith("Shoulders read a touch fuller") and item["qualitative_withheld_reason"] is None
    assert item["anchors"]["dexa"] == {"scan_date": "2026-09-20", "body_fat_pct": Decimal("24.3"), "days_from_set": 21}
    assert item["anchors"]["tape_trend"]["waist_delta_in"] == Decimal("-0.75")
    assert item["model_id"] == cv.model_for("coach_vision")
    assert item["set_dates"] == {"current": "2026-10-11", "prior": "2026-09-27"}
    assert set(item["photo_keys"]["current"]) == set(cv.POSES) and set(item["photo_keys"]["prior"]) == set(cv.POSES)
    assert item["data_class"] == "visual_estimate" and item["created_at"] == "2026-10-12T17:00:00Z"

    def _no_float(v):
        if isinstance(v, float):
            raise AssertionError("a float reached the DDB item")
        if isinstance(v, dict):
            for x in v.values():
                _no_float(x)
        if isinstance(v, list):
            for x in v:
                _no_float(x)

    _no_float(item)


def test_a_fabricated_number_withholds_the_text_and_keeps_the_band(world):
    table, s3 = world
    reply = dict(_good_reply(), qualitative="Looks about 19 percent now, leaner than on 2026-10-01.")
    out = lam.run(table=table, s3=s3, bucket="b", today=TODAY, invoke_fn=_recording_invoke([], reply), allow_fn=lambda f: True, now=NOW)
    assert out["status"] == "written"
    (item,) = table.puts
    assert item["qualitative"] is None
    assert "fabricated_number" in item["qualitative_withheld_reason"] and "fabricated_date" in item["qualitative_withheld_reason"]
    assert item["body_fat_estimate"]["low_pct"] == Decimal("20.0")


def test_an_implausible_or_off_schema_reply_raises_and_writes_nothing(world):
    table, s3 = world
    bad = dict(_good_reply(), body_fat_low_pct=30, body_fat_high_pct=25)
    with pytest.raises(cv.CoachVisionFailure, match="implausible band"):
        lam.run(table=table, s3=s3, bucket="b", today=TODAY, invoke_fn=_recording_invoke([], bad), allow_fn=lambda f: True, now=NOW)
    with pytest.raises(cv.CoachVisionFailure, match="off-schema"):
        lam.run(
            table=table,
            s3=s3,
            bucket="b",
            today=TODAY,
            invoke_fn=_recording_invoke([], {"qualitative": "x"}),
            allow_fn=lambda f: True,
            now=NOW,
        )
    assert table.puts == []


# ── failures are loud: the Monday job must never go dark behind a green Invocations alarm ──
def test_an_inference_failure_raises_out_of_the_handler_with_its_cause(world):
    """AccessDenied / throttle / model-access: the run RAISES (Errors datapoint + DLQ), writes nothing.

    The absence alarm counts Invocations and bedrock_client emits no failure metric, so a
    swallowed exception here would be invisible for as long as it lasted.
    """
    table, s3 = world

    class _Denied(Exception):
        pass

    def invoke(body, model_name=None):
        raise _Denied("AccessDeniedException: not authorized to invoke the model")

    with pytest.raises(cv.CoachVisionFailure, match="inference failed: _Denied: AccessDeniedException") as info:
        lam.run(table=table, s3=s3, bucket="b", today=TODAY, invoke_fn=invoke, allow_fn=lambda f: True, now=NOW)
    assert isinstance(info.value.__cause__, _Denied)
    assert table.puts == []
    assert "raises" in lam.__doc__ and "CoachVisionFailure" in lam.__doc__


def test_every_photo_unreadable_raises_but_one_unreadable_photo_only_drops_that_image(world):
    table, s3 = world

    class _DeadS3(_S3):
        def get_object(self, Bucket, Key):
            raise PermissionError(f"AccessDenied: {Key}")

    with pytest.raises(cv.CoachVisionFailure, match="no readable photo in this week's set"):
        lam.run(table=table, s3=_DeadS3(), bucket="b", today=TODAY, invoke_fn=_recording_invoke([]), allow_fn=lambda f: True, now=NOW)
    assert table.puts == []

    class _OneBadS3(_S3):
        def get_object(self, Bucket, Key):
            if Key.endswith("2026-10-11-side.jpg"):
                raise PermissionError(f"AccessDenied: {Key}")
            return super().get_object(Bucket, Key)

    calls = []
    out = lam.run(
        table=table, s3=_OneBadS3(), bucket="b", today=TODAY, invoke_fn=_recording_invoke(calls), allow_fn=lambda f: True, now=NOW
    )
    assert out["status"] == "written"
    (item,) = table.puts
    assert set(item["photo_keys"]["current"]) == {"front", "back"} and set(item["photo_keys"]["prior"]) == set(cv.POSES)
    assert sum(1 for c in calls[0]["body"]["messages"][0]["content"] if c["type"] == "image") == 5


def test_a_budget_pause_is_the_one_soft_outcome_after_the_set_is_known(world):
    """The negative control for the two tests above: paused returns, does not raise, writes nothing."""
    table, s3 = world
    calls = []
    out = lam.run(table=table, s3=s3, bucket="b", today=TODAY, invoke_fn=_recording_invoke(calls), allow_fn=lambda f: False, now=NOW)
    assert out["status"] == "paused" and out["as_of"] == "2026-10-11" and calls == [] and table.puts == []


def test_the_run_is_idempotent_on_the_set_and_re_observes_a_retake(world):
    table, s3 = world
    calls = []
    lam.run(table=table, s3=s3, bucket="b", today=TODAY, invoke_fn=_recording_invoke(calls), allow_fn=lambda f: True, now=NOW)
    again = lam.run(table=table, s3=s3, bucket="b", today=TODAY, invoke_fn=_recording_invoke(calls), allow_fn=lambda f: True, now=NOW)
    assert again["status"] == "already_observed" and len(calls) == 1 and len(table.puts) == 1
    # A retake after the run: a different key for the same date/pose → observed again.
    row = _index_row("2026-10-11", "front", week_n=6)
    row["s3_key"] = row["s3_key"].replace("-front.jpg", "-front-retake.jpg")
    table.put_item(Item=row)
    table.puts.clear()
    third = lam.run(table=table, s3=s3, bucket="b", today=TODAY, invoke_fn=_recording_invoke(calls), allow_fn=lambda f: True, now=NOW)
    assert third["status"] == "written" and len(calls) == 2


def test_no_set_this_week_writes_nothing_and_calls_no_model():
    table = _Table(rows=[_index_row("2026-09-27", p, week_n=4) for p in cv.POSES])
    calls = []
    out = lam.run(table=table, s3=_S3(), bucket="b", today=TODAY, invoke_fn=_recording_invoke(calls), allow_fn=lambda f: True, now=NOW)
    assert out["status"] == "no_set" and calls == [] and table.puts == []


def test_a_key_outside_the_registry_prefix_is_never_read(world):
    table, s3 = world
    row = _index_row("2026-10-11", "side", week_n=6)
    row["s3_key"] = "raw/matthew/withings/2026/10/not-a-photo.json"
    table.put_item(Item=row)
    calls = []
    lam.run(table=table, s3=s3, bucket="b", today=TODAY, invoke_fn=_recording_invoke(calls), allow_fn=lambda f: True, now=NOW)
    assert "raw/matthew/withings/2026/10/not-a-photo.json" not in s3.keys
    item = table.puts[-1]  # puts[0] is the test's own seed of the bad row
    assert "side" not in item["photo_keys"]["current"]


def test_a_first_set_with_no_prior_is_observed_alone():
    table = _Table(rows=[_index_row("2026-10-11", p, week_n=6) for p in cv.POSES])
    calls = []
    out = lam.run(table=table, s3=_S3(), bucket="b", today=TODAY, invoke_fn=_recording_invoke(calls), allow_fn=lambda f: True, now=NOW)
    assert out["status"] == "written"
    (item,) = table.puts
    assert item["set_dates"]["prior"] is None and item["photo_keys"]["prior"] == {}
    assert item["anchors"]["dexa"] is None and item["anchors"]["tape_trend"] is None
    content = calls[0]["body"]["messages"][0]["content"]
    assert sum(1 for b in content if b.get("type") == "image") == 3


# ── the budget band ───────────────────────────────────────────────────────────
def _at_tier(monkeypatch, tier):
    monkeypatch.setattr(budget_guard, "current_tier", lambda: tier)
    monkeypatch.setitem(budget_guard._cache, "readable", True)


@pytest.mark.parametrize("tier,runs", [(0, True), (1, True), (2, False), (3, False)])
def test_it_runs_through_the_internal_pause_and_stops_with_the_reader_narrative(monkeypatch, world, tier, runs):
    """ADR-125 band 2: outlives every internal/dev AI feature, pauses with the narrative."""
    _at_tier(monkeypatch, tier)
    table, s3 = world
    calls = []
    out = lam.run(table=table, s3=s3, bucket="b", today=TODAY, invoke_fn=_recording_invoke(calls), now=NOW)
    if runs:
        assert out["status"] == "written" and len(calls) == 1
    else:
        assert out["status"] == "paused" and calls == [] and table.puts == []
        assert "reader-narrative" in out["reason"]


def test_the_feature_is_declared_in_band_two_beside_the_coach_narrative():
    assert budget_guard._FEATURE_CUTOFF["coach_vision"] == budget_guard._FEATURE_CUTOFF["coach_narrative"] == 2


# ── the consumers ─────────────────────────────────────────────────────────────
def _record():
    return {
        "as_of": "2026-10-11",
        "set_dates": {"current": "2026-10-11", "prior": "2026-09-27"},
        "qualitative": "Waist reads narrower.",
        "qualitative_withheld_reason": None,
        "deltas": ["waist narrower"],
        "body_fat_estimate": {"low_pct": Decimal("20.0"), "high_pct": Decimal("24.0"), "label": cv.ESTIMATE_LABEL, "confidence": "low"},
        "anchors": {
            "dexa": {"scan_date": "2026-09-20", "body_fat_pct": Decimal("24.3")},
            "tape_trend": {"latest": {"session_date": "2026-10-04", "waist_navel_in": Decimal("34.5")}, "waist_delta_in": Decimal("-0.75")},
        },
        "model_id": "claude-haiku-4-5-20251001",
        "photo_keys": {"current": {"front": "k"}},
        "pk": cv.RECORD_PK,
        "sk": "DATE#2026-10-11",
    }


def test_select_fields_is_field_selective_and_never_leaks_plumbing():
    out = cv.select_fields(_record(), ["body_fat_estimate", "model_id", "photo_keys", "pk"])
    assert set(out) == {"body_fat_estimate", "model_id"}
    assert out["body_fat_estimate"]["label"] == cv.ESTIMATE_LABEL
    assert set(cv.select_fields(_record())) == set(cv.DEFAULT_FIELDS)
    assert set(cv.select_fields(_record(), ["nonsense"])) == set(cv.DEFAULT_FIELDS)


def test_thread_lines_carry_the_label_and_the_anchors_and_withhold_a_stale_record():
    lines = cv.thread_lines(_record(), "2026-10-13")
    joined = "\n".join(lines)
    assert "visual estimate, not a measurement" in joined
    assert "Body fat 20-24%" in joined and "DEXA of 2026-09-20: 24.3% measured" in joined and "waist 34.5 in (-0.75 in" in joined
    assert "2026-09-27 set" in joined
    assert cv.thread_lines(_record(), "2026-11-20") == [], "older than THREAD_MAX_AGE_DAYS is withheld"
    assert cv.thread_lines(None, "2026-10-13") == []
    withheld = dict(_record(), qualitative=None, qualitative_withheld_reason="withheld by the grounding gate: fabricated_number")
    assert "withheld by the grounding gate" in "\n".join(cv.thread_lines(withheld, "2026-10-13"))


def test_thread_block_reads_the_newest_record_and_fails_soft():
    table = _Table(rows=[dict(_record(), sk="DATE#2026-10-04", as_of="2026-10-04"), _record()])
    block = cv.thread_block(table, "2026-10-13")
    assert block.startswith("COACH VISION (owner-only") and "2026-10-11 set" in block
    assert cv.thread_block(_Table(rows=[]), "2026-10-13") == ""

    class _Broken:
        def query(self, **kw):
            raise RuntimeError("throttled")

    assert cv.thread_block(_Broken(), "2026-10-13") == ""
    assert cv.thread_block(table, None) == ""


def test_the_mcp_tool_is_field_selective_and_honest_about_the_layer(monkeypatch):
    import mcp.tools_coach_vision as tool

    monkeypatch.setattr(tool, "table", _Table(rows=[_record()]))
    monkeypatch.setattr(tool, "pacific_today", lambda: "2026-10-13")
    out = tool.tool_get_coach_vision({"fields": ["body_fat_estimate", "anchors", "pk"]})
    assert out["layer_status"] == "ok" and out["records_returned"] == 1
    (rec,) = out["records"]
    assert set(rec) == {"body_fat_estimate", "anchors"}
    assert rec["body_fat_estimate"]["label"] == cv.ESTIMATE_LABEL and rec["body_fat_estimate"]["low_pct"] == 20.0
    assert out["label"] == cv.ESTIMATE_LABEL

    empty = tool.tool_get_coach_vision({})
    assert empty["records_returned"] == 1  # the fixture table is pk-dispatching; the empty case below uses its own table
    monkeypatch.setattr(tool, "table", _Table(rows=[]))
    none = tool.tool_get_coach_vision({})
    assert none["records"] == [] and none["records_returned"] == 0 and "note" in none

    class _Broken:
        def query(self, **kw):
            raise RuntimeError("throttled")

    monkeypatch.setattr(tool, "table", _Broken())
    down = tool.tool_get_coach_vision({})
    assert down["layer_status"] == "unavailable" and down["records_returned"] is None and "records" not in down


def test_the_telegram_facts_addendum_rides_the_domain_seat(monkeypatch):
    """The owner's coach thread is a sanctioned consumer: the block joins `domain`, which is
    what `_grounder_for` feeds the grounder, so the band is citable without a finding."""
    from coach import telegram_worker_lambda as tw

    monkeypatch.setattr(tw, "_table", lambda: _Table(rows=[_record()]))
    monkeypatch.setattr(tw, "display_name", lambda *a, **k: "Elena")
    monkeypatch.setattr(tw, "_thread_today", lambda pid: [])
    monkeypatch.setattr(tw, "_facts", lambda: {})
    monkeypatch.setattr(tw, "_memory_block", lambda pid: "")
    monkeypatch.setattr(tw, "_current_moment_line", lambda: "")
    monkeypatch.setattr(tw, "_pacific_now", lambda: datetime(2026, 10, 13, 9, 0))
    monkeypatch.setattr(tw, "_colleagues_block", lambda *a, **k: "")
    import coach.coach_domain_facts as cdf

    monkeypatch.setattr(cdf, "domain_facts_block", lambda *a, **k: "DOMAIN PACK")
    a = tw._assemble("elena", "physical")
    assert "COACH VISION (owner-only" in a["domain"] and "visual estimate, not a measurement" in a["domain"]
    assert a["domain"].startswith("DOMAIN PACK")
    assert "COACH VISION" in a["facts_block"]


def test_the_mcp_input_literal_is_pinned_to_the_owner_field_set():
    """The schema is a pure literal (the catalog generator evaluates it by AST), so it is
    held to the module's field set here instead of being derived at import."""
    import mcp.tools_coach_vision as tool

    assert tuple(tool.GET_COACH_VISION_INPUT["properties"]["fields"]["items"]["enum"]) == cv.OWNER_FIELDS
    assert ", ".join(cv.DEFAULT_FIELDS) in tool.GET_COACH_VISION_INPUT["properties"]["fields"]["description"]


# ── no owner-only health data in a log line (CodeQL py/clear-text-logging, PR #4829) ──────
# The band, the photo keys and the observation text are owner-only; CloudWatch is not the
# owner-only store. The guard is DERIVED from the modules' source: every logger call and
# every `_fail(...)` reason (which `_fail` logs at ERROR) is parsed, and no argument may read
# a sensitive field. Shapes allowed because they carry no value: `len(...)` (a count),
# `decode_error(...)` (decoder message + position only, ai/structured_json.py) and
# `x is not None` / `x is None` (the grounded flag).
_VALUE_FREE_SUMMARIES = {"len", "decode_error"}
_LOG_GUARDED_MODULES = ("lambdas/coach/coach_vision_lambda.py", "lambdas/coach/coach_vision.py")
_LOG_METHODS = {"debug", "info", "warning", "warn", "error", "exception", "critical", "log"}
_SENSITIVE_LOG_TOKENS = {
    "low_pct",
    "high_pct",
    "body_fat_estimate",
    "body_fat_low_pct",
    "body_fat_high_pct",
    "band",
    "low",
    "high",
    "photo_keys",
    "key",
    "keys_now",
    "sent",
    "qualitative",
    "observation",
    "text",
    "parsed",
}


def _sensitive_log_reads(source: str, filename: str = "<src>") -> list:
    """`[(filename, lineno, token)]` for every log/_fail argument that reads a sensitive field."""
    import ast

    def is_log_call(node) -> bool:
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr in _LOG_METHODS and isinstance(f.value, ast.Name):
            return f.value.id in {"logger", "log", "logging"}
        return isinstance(f, ast.Name) and f.id == "_fail"

    def tokens(node):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _VALUE_FREE_SUMMARIES:
            return  # a count / a decoder position carries no value
        if isinstance(node, ast.Compare) and all(isinstance(op, (ast.Is, ast.IsNot)) for op in node.ops):
            if all(isinstance(c, ast.Constant) and c.value is None for c in node.comparators):
                return  # a presence flag carries no value
        if isinstance(node, ast.Name):
            yield node.lineno, node.id
        elif isinstance(node, ast.Attribute):
            yield node.lineno, node.attr
        elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
            yield node.lineno, node.slice.value
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            for a in node.args[:1]:
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    yield node.lineno, a.value
        for child in ast.iter_child_nodes(node):
            yield from tokens(child)

    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and is_log_call(node):
            for arg in list(node.args[1:] if not isinstance(node.func, ast.Name) else node.args) + [k.value for k in node.keywords]:
                out += [(filename, ln, t) for ln, t in tokens(arg) if t in _SENSITIVE_LOG_TOKENS]
    return out


def test_no_log_line_in_the_coach_vision_modules_carries_owner_only_health_data():
    offenders = []
    for rel in _LOG_GUARDED_MODULES:
        offenders += _sensitive_log_reads((ROOT / rel).read_text(), rel)
    assert not offenders, "owner-only data in a log line (log pk/sk, model, grounded flag, counts only): " + ", ".join(
        f"{f}:{ln} reads {t!r}" for f, ln, t in offenders
    )

    # Mutation control: the reverted shape (the band in the write log line) must be caught,
    # and so must a photo key in a warning and a band value in a `_fail` reason.
    reverted = (
        (ROOT / _LOG_GUARDED_MODULES[0])
        .read_text()
        .replace(
            'record["model_id"],\n        record["qualitative"] is not None,',
            'record["model_id"],\n        record["body_fat_estimate"]["low_pct"],\n        record["qualitative"] is not None,',
        )
    )
    assert "low_pct" in reverted, "mutation control did not apply — the write log line moved; update the anchor"
    assert any(t == "low_pct" for _, _, t in _sensitive_log_reads(reverted))
    assert _sensitive_log_reads('logger.warning("x %s", ref["key"])')
    assert _sensitive_log_reads('_fail(f"implausible band {low}-{high}")')
    assert not _sensitive_log_reads('logger.info("%s grounded=%s n=%d", pk, rec["qualitative"] is not None, len(sent))')
