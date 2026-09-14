"""tests/test_progress_capture_3758.py — a photo from his phone, stored owner-only (#3758).

WHAT IS ACTUALLY AT RISK HERE

Not correctness of a number. This is a capture path whose payload is a body photo, and
the two failure modes are asymmetric in a way worth naming before the assertions:

  * A photo that lands somewhere it should not is unrecoverable. It is Tier 2, owner-only,
    and there is no version of "we deleted it" that undoes a wrong prefix or a wrong chat.
    So the owner gate, the bot gate and the prefix are asserted here in their negative
    form — the tests that matter are the ones where NOTHING is stored.
  * A photo that silently fails to land is also unrecoverable, differently: the set is
    gone, discovered weeks later, and the comparison this feature exists for never
    happens. So every refusal path is asserted to TEXT HIM BACK. Silence is the one
    outcome this module may never produce.

Everything is injected — the S3 client, the table, the HTTP opener, the clock — so the
whole path runs offline. That is not a testing convenience, it is what makes the negative
cases testable at all: "did not store" is only a real assertion when a real store would
otherwise have happened.
"""

from __future__ import annotations

import io
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))

from coach import progress_capture as pc  # noqa: E402

JPEG = b"\xff\xd8\xff\xe0" + b"body bytes" * 40
OWNER_CHAT = 8675309
CHAT_IDS = [OWNER_CHAT, -100999]  # the group id is there on purpose — it must never win


class FakeS3:
    def __init__(self):
        self.puts = []

    def put_object(self, **kw):
        self.puts.append(kw)


class FakeTable:
    def __init__(self, items=None):
        self.items = dict(items or {})
        self.puts = []

    def get_item(self, Key):  # noqa: N803 — boto3 signature
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item else {}

    def put_item(self, Item):  # noqa: N803 — boto3 signature
        self.items[(Item["pk"], Item["sk"])] = Item
        self.puts.append(Item)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False


def opener_for(*, file_path="photos/file_7.jpg", body=JPEG, get_file_fails=False, download_fails=False):
    """A urlopen stand-in that answers getFile and the file download, and records calls."""
    calls = []

    def _open(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        calls.append(url)
        if "getFile" in url:
            if get_file_fails:
                raise RuntimeError("telegram said no")
            return FakeResponse(json.dumps({"ok": True, "result": {"file_path": file_path}}).encode())
        if download_fails:
            raise RuntimeError("download died")
        return FakeResponse(body)

    _open.calls = calls
    return _open


def order(**kw):
    o = {
        "kind": "progress_photo",
        "coach_id": "eli_marsh",
        "bot_key": "headcoach",
        "chat_id": OWNER_CHAT,
        "is_group": False,
        "caption": "/progress front",
        "photo": [
            {"file_id": "small", "file_unique_id": "u-small", "width": 90, "height": 120, "file_size": 1200},
            {"file_id": "large", "file_unique_id": "u-large", "width": 900, "height": 1200, "file_size": 240000},
        ],
    }
    o.update(kw)
    return o


def run(o, *, s3=None, table=None, opener=None, today="2026-09-14", experiment_start="2026-09-06"):
    return pc.handle(
        o,
        "bot-token",
        s3=s3 if s3 is not None else FakeS3(),
        table=table if table is not None else FakeTable(),
        bucket="matthew-life-platform",
        chat_ids=CHAT_IDS,
        today=today,
        experiment_start=experiment_start,
        opener=opener or opener_for(),
    )


# ══════════════════════════════════════════════════════════════════════════════
# 1. THE CAPTION
# ══════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "caption,expected",
    [
        ("/progress front", ("front", None)),
        ("/progress side", ("side", None)),
        ("/progress BACK", ("back", None)),
        ("  /progress   front  ", ("front", None)),
        ("/progress front 2026-09-06", ("front", "2026-09-06")),
        ("/Progress Side 2026-01-02", ("side", "2026-01-02")),
    ],
)
def test_valid_captions_parse(caption, expected):
    assert pc.parse_caption(caption) == expected


@pytest.mark.parametrize(
    "caption",
    [
        "",
        "front",
        "/progress",
        "/progress torso",
        "/progress front tomorrow",
        "/progress front 09-06-2026",
        "here is my /progress front",  # anchored: containing it is not commanding it
        "/progress front extra words",
    ],
)
def test_invalid_captions_do_not_parse(caption):
    assert pc.parse_caption(caption) is None


def test_a_typo_is_a_capture_attempt_but_a_comment_is_not():
    """The line between a helpful bot and a noisy one."""
    assert pc.is_capture_attempt("/progress frnot") is True
    assert pc.is_capture_attempt("feeling good today") is False


# ══════════════════════════════════════════════════════════════════════════════
# 2. THE GATES — every one of these stores NOTHING
# ══════════════════════════════════════════════════════════════════════════════
def test_only_the_headcoach_bot_captures():
    s3, table = FakeS3(), FakeTable()
    out = run(order(bot_key="sleep"), s3=s3, table=table)
    assert out["reason"] == "not the capture bot"
    assert s3.puts == [] and table.puts == []


def test_a_group_chat_never_captures():
    s3, table = FakeS3(), FakeTable()
    out = run(order(is_group=True), s3=s3, table=table)
    assert out["ok"] is False and s3.puts == []
    assert out["reply"] == "", "a group must not even be answered — the reply itself would be the disclosure"


def test_a_chat_that_is_not_his_never_captures():
    s3, table = FakeS3(), FakeTable()
    out = run(order(chat_id=424242), s3=s3, table=table)
    assert out["ok"] is False and s3.puts == [] and table.puts == []


def test_the_group_id_on_the_roster_can_never_become_the_owner_chat():
    """`first_private_chat_id` filters negatives; this asserts the filter is load-bearing."""
    s3 = FakeS3()
    out = pc.handle(
        order(chat_id=-100999),
        "bot-token",
        s3=s3,
        table=FakeTable(),
        bucket="b",
        chat_ids=[-100999],  # ONLY the group is on the roster
        today="2026-09-14",
        opener=opener_for(),
    )
    assert out["ok"] is False and s3.puts == []


def test_a_photo_with_no_caption_gets_the_format_hint_and_stores_nothing():
    s3, table = FakeS3(), FakeTable()
    out = run(order(caption=""), s3=s3, table=table)
    assert out["ok"] is False
    assert "/progress front" in out["reply"], "he is standing in front of a mirror — silence is the wrong answer"
    assert s3.puts == [] and table.puts == []


def test_a_mistyped_progress_caption_gets_the_format_hint():
    s3 = FakeS3()
    out = run(order(caption="/progress frnot"), s3=s3)
    assert out["ok"] is False and out["reply"] == pc.FORMAT_HINT and s3.puts == []


def test_a_photo_captioned_about_something_else_is_left_alone():
    s3 = FakeS3()
    out = run(order(caption="the gym was packed today"), s3=s3)
    assert out["ok"] is True and out["reason"] == "not a capture command"
    assert out["reply"] == "", "every captioned photo answering back would make the bot unusable"
    assert s3.puts == []


# ══════════════════════════════════════════════════════════════════════════════
# 3. THE WIRE
# ══════════════════════════════════════════════════════════════════════════════
def test_the_largest_rendition_is_the_one_stored():
    """A thumbnail is silently lossy, and only becomes visible months later."""
    assert pc.largest_photo(order()["photo"])["file_id"] == "large"


def test_a_photo_array_with_no_file_id_is_refused():
    with pytest.raises(pc.Refused):
        pc.largest_photo([{"width": 10, "height": 10}])


def test_a_non_jpeg_payload_is_refused_on_its_magic_bytes_not_its_label():
    s3 = FakeS3()
    out = run(order(), s3=s3, opener=opener_for(body=b"\x89PNG\r\n\x1a\n" + b"x" * 100))
    assert out["ok"] is False and "photo I can store" in out["reply"] and s3.puts == []


def test_an_oversized_photo_is_refused():
    s3 = FakeS3()
    big = b"\xff\xd8\xff" + b"x" * (pc.MAX_BYTES + 1)
    out = run(order(), s3=s3, opener=opener_for(body=big))
    assert out["ok"] is False and "too large" in out["reply"] and s3.puts == []


def test_a_getfile_failure_is_refused_with_a_reply_and_stores_nothing():
    s3 = FakeS3()
    out = run(order(), s3=s3, opener=opener_for(get_file_fails=True))
    assert out["ok"] is False and out["reply"] and s3.puts == []


def test_a_download_failure_is_refused_with_a_reply_and_stores_nothing():
    s3 = FakeS3()
    out = run(order(), s3=s3, opener=opener_for(download_fails=True))
    assert out["ok"] is False and out["reply"] and s3.puts == []


# ══════════════════════════════════════════════════════════════════════════════
# 4. THE HAPPY PATH, AND WHAT IT WRITES
# ══════════════════════════════════════════════════════════════════════════════
def test_a_valid_photo_is_stored_under_the_owner_only_prefix():
    s3, table = FakeS3(), FakeTable()
    out = run(order(), s3=s3, table=table)

    assert out["ok"] is True and out["reason"] == "stored"
    put = s3.puts[0]
    assert put["Key"] == "raw/matthew/progress_photos/2026/09/2026-09-14-front.jpg"
    assert put["ContentType"] == "image/jpeg"
    assert put["Body"] == JPEG
    assert "ACL" not in put, "an explicit ACL on a Tier-2 object is how a private prefix stops being private"


def test_the_index_row_carries_the_week_and_the_hash():
    import hashlib

    table = FakeTable()
    out = run(order(), table=table)
    row = table.puts[0]

    assert row["pk"] == "USER#matthew#SOURCE#progress_photos"
    assert row["sk"] == "DATE#2026-09-14#front"
    assert row["week_n"] == 2, "2026-09-14 is day 9 of a 2026-09-06 genesis — week 2"
    assert row["sha256"] == hashlib.sha256(JPEG).hexdigest()
    assert row["bytes"] == len(JPEG)
    assert row["s3_key"] == out["s3_key"]
    assert row["telegram_file_unique_id"] == "u-large"


def test_the_reply_names_the_week_and_the_key():
    out = run(order())
    assert "front" in out["reply"] and "2026-09-14" in out["reply"] and "week 2" in out["reply"]


def test_a_back_dated_caption_stores_against_the_named_day():
    s3, table = FakeS3(), FakeTable()
    out = run(order(caption="/progress front 2026-09-06"), s3=s3, table=table)
    assert s3.puts[0]["Key"] == "raw/matthew/progress_photos/2026/09/2026-09-06-front.jpg"
    assert table.puts[0]["week_n"] == 1
    assert out["ok"] is True


def test_the_object_lands_before_the_row():
    """Of the two half-states only one is recoverable, so the order is the contract."""
    seen = []

    class OrderedS3(FakeS3):
        def put_object(self, **kw):
            seen.append("s3")
            super().put_object(**kw)

    class OrderedTable(FakeTable):
        def put_item(self, Item):  # noqa: N803
            seen.append("ddb")
            super().put_item(Item)

    run(order(), s3=OrderedS3(), table=OrderedTable())
    assert seen == ["s3", "ddb"]


def test_a_photo_off_cycle_stores_with_no_week():
    table = FakeTable()
    out = run(order(caption="/progress front 2026-08-01"), table=table, experiment_start="2026-09-06")
    assert "week_n" not in table.puts[0]
    assert "off-cycle" in out["reply"]


# ══════════════════════════════════════════════════════════════════════════════
# 5. IDEMPOTENCE
# ══════════════════════════════════════════════════════════════════════════════
def test_a_resend_of_the_same_photo_stores_nothing_and_says_so():
    s3, table = FakeS3(), FakeTable()
    run(order(), s3=s3, table=table)
    op = opener_for()
    out = run(order(), s3=s3, table=table, opener=op)

    assert out["reason"] == "already stored"
    assert "Already stored" in out["reply"]
    assert len(s3.puts) == 1 and len(table.puts) == 1
    assert op.calls == [], "a redelivery must not re-download megabytes to learn it has nothing to do"


def test_a_retake_of_the_same_pose_and_day_replaces_it():
    """A different file for the same slot is him taking it again, and take two is the one."""
    s3, table = FakeS3(), FakeTable()
    run(order(), s3=s3, table=table)

    retake = order()
    retake["photo"] = [{"file_id": "large2", "file_unique_id": "u-retake", "width": 900, "height": 1200, "file_size": 250000}]
    out = run(retake, s3=s3, table=table)

    assert out["reason"] == "stored"
    assert len(s3.puts) == 2 and s3.puts[0]["Key"] == s3.puts[1]["Key"]
    assert table.items[("USER#matthew#SOURCE#progress_photos", "DATE#2026-09-14#front")]["telegram_file_unique_id"] == "u-retake"


def test_an_unreadable_index_is_treated_as_absent_not_as_a_duplicate():
    """Failing the other way would drop a real photo on a transient DDB blip."""

    class BrokenRead(FakeTable):
        def get_item(self, Key):  # noqa: N803
            raise RuntimeError("ddb is having a day")

    s3, table = FakeS3(), BrokenRead()
    out = run(order(), s3=s3, table=table)
    assert out["reason"] == "stored" and len(s3.puts) == 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
