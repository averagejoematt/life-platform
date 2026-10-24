"""tests/test_calibration_cadence_5061.py — tape / photo / DEXA cadence, prompts and the dead-man (#5061, epic #5067).

Holds: the cycle from the charter cadence (ok / due / overdue / missed_2, and a new log resets it); the DEXA due date
and its #4639 link when no scan row is readable; a broken read is `read_failed`, never "nothing logged"; the prompt
goes out once per cycle (idempotency key + the write-once event claim) and a new log opens a new key; the dead-man
candidate; the May tracker's waist cell carries the tape cadence; the packet reads it. PRIVACY: no `lambdas/web/` or
`lambdas/emails/` module imports the cadence, the only published-tree module that names the photo partition is the
owner-gated viewer, and a cadence block carries no photo key or reading.

No clock is read: every `today` is a fixed date; the cycle length is derived from the same charter value the code reads (#4848).
"""

# premerge-gate: #5061: os.walk sweep of lambdas/web/ and lambdas/emails/ — no published-surface module reads the photo partition or imports the owner-only cadence

from __future__ import annotations

import io
import json
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT))

from coach import (
    coach_event_triggers as cet,  # noqa: E402
    coach_outbound,  # noqa: E402
)
from training import calibration_cadence as cc  # noqa: E402
from training.training_charter import charter_value  # noqa: E402

CYCLE = int(charter_value("calibration.tape_and_photos.every_weeks")) * 7
DEAD = int(charter_value("calibration.tape_and_photos.dead_man_missed_cycles"))
DEXA_DAYS = int(charter_value("calibration.dexa.every_weeks_approx")) * 7
GENESIS = "2026-09-06"
LAST = "2026-10-05"


def plus(d: str, n: int) -> str:
    return (date.fromisoformat(d) + timedelta(days=n)).isoformat()


def block(today, tape=(), photos=(), dexa=(), **kw):
    return cc.compute(today, {"tape": lambda: list(tape), "photos": lambda: list(photos), "dexa": lambda: list(dexa)}, anchor=GENESIS, **kw)


def row(today, logged, kind="tape"):
    return cc.cycle_state(kind, logged, today, CYCLE, anchor=GENESIS, dead_cycles=DEAD)


# ── the cycle ────────────────────────────────────────────────────────────────────
def test_the_cadence_is_the_charters():
    assert (CYCLE, DEAD) == (14, 2)


def test_ok_due_overdue_missed_2():
    due = plus(LAST, CYCLE)
    assert row(plus(due, -1), [LAST])["state"] == cc.OK
    r = row(due, [LAST])
    assert (r["state"], r["due_on"], r["missed_cycles"]) == (cc.DUE, due, 0)
    assert row(plus(due, 1), [LAST])["state"] == cc.OVERDUE
    assert row(plus(due, CYCLE), [LAST])["state"] == cc.OVERDUE  # one due day passed
    r = row(plus(due, CYCLE + 1), [LAST])
    assert (r["state"], r["missed_cycles"]) == (cc.MISSED_2, DEAD)


def test_a_new_log_resets_the_cycle_and_the_key():
    late = plus(LAST, CYCLE * 3)
    assert row(late, [LAST])["state"] == cc.MISSED_2
    fresh = row(late, [LAST, late])
    assert (fresh["state"], fresh["last_logged"], fresh["cycle_start"]) == (cc.OK, late, late)
    assert cc.prompt_key("tape", LAST) != cc.prompt_key("tape", late)
    assert cc.prompt_key("tape", LAST) == f"CALIB_PROMPT#tape#{LAST}"


def test_a_log_dated_after_today_is_ignored():
    assert row(LAST, [LAST, plus(LAST, 5)])["last_logged"] == LAST


def test_never_logged_anchors_on_genesis():
    r = row(plus(GENESIS, CYCLE), [])
    assert (r["state"], r["due_on"], r["last_logged"], r["anchored_on_genesis"]) == (cc.DUE, plus(GENESIS, CYCLE), None, True)
    assert "never logged" in block(plus(GENESIS, CYCLE))["kinds"]["tape"]["prompt"]


def test_a_failed_read_is_read_failed_never_empty():
    def boom():
        raise RuntimeError("ddb down")

    b = cc.compute(plus(GENESIS, 99), {"tape": boom, "photos": lambda: [plus(GENESIS, 99)], "dexa": boom}, anchor=GENESIS)
    assert b["kinds"]["tape"]["state"] == cc.READ_FAILED and b["kinds"]["tape"]["error"] == "RuntimeError"
    assert b["kinds"]["dexa"]["state"] == cc.READ_FAILED
    assert b["kinds"]["tape"]["prompt"] is None and cc.deadman_kinds(b) == []


# ── DEXA ─────────────────────────────────────────────────────────────────────────
def test_dexa_due_date_is_last_scan_plus_the_charter_cadence():
    scan = "2026-03-30"
    d = block(plus(scan, DEXA_DAYS - 1), dexa=[scan])["kinds"]["dexa"]
    assert (d["due_on"], d["state"], d["last_logged"]) == (plus(scan, DEXA_DAYS), cc.OK, scan)
    assert block(plus(scan, DEXA_DAYS), dexa=[scan])["kinds"]["dexa"]["state"] == cc.DUE
    late = block(plus(scan, DEXA_DAYS * 5), dexa=[scan])["kinds"]["dexa"]
    assert late["state"] == cc.OVERDUE and "ingest" not in late  # a booked scan is never a behavioural dead-man


def test_dexa_with_no_readable_scan_names_the_ingest():
    d = block("2026-10-19", dexa=[])["kinds"]["dexa"]
    assert d["state"] == cc.UNKNOWN and d["due_on"] is None
    assert d["ingest"] == {"issue": 4639, "built": True, "command": cc.DEXA_INGEST_COMMAND}
    assert "#4639" in d["detail"] and "scripts/ingest_lab_report.py dexa" in d["detail"] and d["prompt"] is None


def test_the_dexa_prompt_names_the_built_ingest_never_not_built():
    """#4639 built the scan ingest (PR #4981): the overdue prompt names it, and never tells him to report the date by hand.
    Live 2026-10-24 the prompt still read "the labs/DEXA ingest (#4639) is not built"."""
    p = block(plus("2026-03-30", DEXA_DAYS + 1), dexa=["2026-03-30"])["kinds"]["dexa"]["prompt"]
    assert p and "scripts/ingest_lab_report.py dexa" in p and "2026-03-30" in p
    assert "not built" not in p
    assert "not built" not in json.dumps(block("2026-10-19", dexa=[]))


def test_the_registry_dexa_cadence_is_the_charter_cadence():
    """ONE DEXA due date (#5061): /api/status's due panel reads the registry's `cadence_months`, the owner prompt reads the
    charter's weeks. They must name the same cadence in the registry's 30-day months, or the site says "next due Mar 2027"
    while the coach says overdue since June (the state before this lane: 12 months against 12 weeks)."""
    from ingestion import source_registry as reg

    months = reg.SOURCE_REGISTRY["dexa"]["cadence_months"]
    assert months == round(DEXA_DAYS / reg.DAYS_PER_CADENCE_MONTH), (months, DEXA_DAYS)
    assert reg.due_months()["dexa"] == months


# ── prompts: once per cycle ──────────────────────────────────────────────────────
class Ledger:
    def __init__(self):
        self.rows = {}

    def put_item(self, Item, ConditionExpression=None):
        if Item["sk"] in self.rows:
            raise RuntimeError("ConditionalCheckFailedException")
        self.rows[Item["sk"]] = Item


def test_prompt_rides_the_event_sweep_once_per_cycle_and_a_new_log_reopens_it():
    today = plus(LAST, CYCLE)
    ledger = Ledger()
    first = cet.detect_calibration(block(today, tape=[LAST], photos=[plus(LAST, 1)]), today)
    assert f"CALIB_PROMPT#tape#{LAST}" in {e["event_id"] for e in first}
    ev = next(e for e in first if e["event_id"] == f"CALIB_PROMPT#tape#{LAST}")
    assert ev["provenance"] == coach_outbound.PROVENANCE_CALIBRATION and ev["evidence"]
    assert coach_outbound.claim_event(ledger, ev["event_id"]) is True
    again = cet.detect_calibration(block(plus(today, 1), tape=[LAST]), plus(today, 1))  # overdue the next day: same key
    assert coach_outbound.claim_event(ledger, next(e for e in again if e["kind"] == "calibration_prompt")["event_id"]) is False
    new = plus(today, 2)
    after = cet.detect_calibration(block(plus(new, CYCLE), tape=[LAST, new]), plus(new, CYCLE))
    assert coach_outbound.claim_event(ledger, f"CALIB_PROMPT#tape#{new}") is True
    assert any(e["event_id"] == f"CALIB_PROMPT#tape#{new}" for e in after)


def test_nothing_is_prompted_before_the_due_day():
    assert cet.detect_calibration(block(plus(LAST, CYCLE - 1), tape=[LAST], photos=[LAST]), plus(LAST, CYCLE - 1)) == []


def test_the_deadman_replaces_the_prompt_once_per_cycle_outside_the_ai_sweep():
    # #5203: the dead-man left the AI sweep (it stood down at budget tier >= 2) for coach.calibration_deadman_alert.
    from coach import calibration_deadman_alert as cda

    today = plus(LAST, CYCLE * 3)
    assert cet.detect_calibration(block(today, tape=[LAST], photos=[today]), today) == []
    d = cda.due(block(today, tape=[LAST], photos=[today]))
    assert [x["kind"] for x in d] == ["tape"] and d[0]["event_id"] == f"CALIB_DEADMAN#tape#{LAST}"
    assert cc.deadman_kinds(block(today, tape=[LAST], photos=[today])) == ["tape"]
    ledger = Ledger()
    assert coach_outbound.claim_event(ledger, d[0]["event_id"]) and not coach_outbound.claim_event(ledger, d[0]["event_id"])


def test_calibration_ranks_last_and_has_a_frame():
    assert coach_outbound.priority(coach_outbound.PROVENANCE_CALIBRATION) > coach_outbound.priority(coach_outbound.PROVENANCE_CELEBRATION)
    assert coach_outbound.event_frame(coach_outbound.PROVENANCE_CALIBRATION, "tape due")


def test_candidates_include_the_calibration_family():
    today = plus(LAST, CYCLE)
    found = cet.candidates({"calibration": block(today, tape=[LAST], photos=[LAST])}, today)
    assert sorted(e["event_id"] for e in found) == [f"CALIB_PROMPT#photos#{LAST}", f"CALIB_PROMPT#tape#{LAST}"]


# ── the readers over a table: dates only ─────────────────────────────────────────
class Table:
    def __init__(self, items):
        self.items = items
        self.projections = []

    def query(self, **kw):
        pk = kw["KeyConditionExpression"]._values[1]
        self.projections.append(kw.get("ProjectionExpression"))
        return {"Items": self.items.get(pk, [])}


def test_table_readers_return_dates_and_project_only_the_date_fields():
    t = Table(
        {
            "USER#matthew#SOURCE#measurements": [{"sk": "DATE#2026-10-05", "date": "2026-10-05"}],
            "USER#matthew#SOURCE#progress_photos": [
                {"sk": "DATE#2026-10-05#front", "date": "2026-10-05", "s3_key": "raw/x.jpg"},
                {"sk": "DATE#2026-10-05#side", "date": "2026-10-05"},
            ],
            "USER#matthew#SOURCE#dexa": [{"sk": "DATE#2026-03-30", "scan_date": "2026-03-30"}],
        }
    )
    r = cc.table_readers(t)
    assert r["tape"]() == ["2026-10-05"] and r["photos"]() == ["2026-10-05"] and r["dexa"]() == ["2026-03-30"]
    assert all(p == "sk, #d" for p in t.projections), "no key, pose path or reading is projected"
    assert "raw/x.jpg" not in json.dumps(cc.compute("2026-10-19", r, anchor=GENESIS))


def test_the_readers_parse_what_the_real_writers_store():
    """The pair pin (#2847): the photo index row is written by the REAL `progress_capture.store`; the tape row's shape is the
    ingestion writer's (`sk` DATE#<day> + `date`)."""
    from coach import progress_capture

    stored = []

    class FakeS3:
        def put_object(self, **kw):
            pass

    class FakeTable:
        def put_item(self, Item):
            stored.append(Item)

    progress_capture.store(b"\xff\xd8\xff", s3=FakeS3(), table=FakeTable(), bucket="b", date="2026-10-05", pose="front", file_unique_id="u")
    items = {
        "USER#matthew#SOURCE#progress_photos": stored,
        "USER#matthew#SOURCE#measurements": [{"sk": "DATE#2026-10-05", "date": "2026-10-05"}],
        "USER#matthew#SOURCE#dexa": [],
    }
    r = cc.table_readers(Table(items))
    assert r["photos"]() == ["2026-10-05"] and r["tape"]() == ["2026-10-05"]
    assert stored[0]["pk"] == "USER#matthew#SOURCE#progress_photos"


# ── the May tracker and the packet read it ──────────────────────────────────────
def test_may_tracker_waist_cell_carries_the_tape_cadence():
    from training import may_tracker as mt

    sunday = plus(GENESIS, 41)
    absent = mt.waist_section([], sunday)
    assert absent["state"] == mt.ABSENT and absent["cadence"]["state"] in (cc.OVERDUE, cc.MISSED_2)
    rows = [{"date": plus(sunday, -3), "waist_navel_in": 40.5}]
    got = mt.waist_section(rows, sunday)
    assert got["state"] == mt.MEASURED and got["cadence"]["last_logged"] == plus(sunday, -3) and got["cadence"]["state"] == cc.OK


def test_the_packet_reads_the_cadence():
    from mcp import tools_coach_packet as pkt

    assert "calibration_cadence" in pkt.SOURCES and "calibration_cadence" in pkt.READERS


# ── privacy: owner-only, never a photo on a published surface ───────────────────
PUBLISHED = ("lambdas/web", "lambdas/emails")
IMPORT_RE = re.compile(
    r"^\s*(?:from|import)\s+[\w.]*\b(?:calibration_(?:cadence|leg)|lab_priorities)\b|^\s*from\s+[\w.]+\s+import\s+[^#\n]*\b(?:calibration_(?:cadence|leg)|lab_priorities)\b",
    re.M,
)
LAB_PRIORITIES_RE = re.compile(r"PRIORITIES#current|lab_priorities")  # #5111
PHOTO_RE = re.compile(r"progress_photos|progress_capture")
OWNER_GATED_VIEWER = {"lambdas/web/progress_viewer_lambda.py"}  # the signed-link, HMAC-session viewer (#3760)


def scan(root: Path, pattern, trees=PUBLISHED):
    hits = []
    for tree in trees:
        for dp, _d, files in os.walk(root / tree):
            for f in files:
                if f.endswith(".py"):
                    p = Path(dp) / f
                    if pattern.search(p.read_text(encoding="utf-8", errors="replace")):
                        hits.append(str(p.relative_to(root)))
    return sorted(hits)


def test_no_published_module_imports_the_cadence():
    assert all((ROOT / t).is_dir() for t in PUBLISHED)
    assert scan(ROOT, IMPORT_RE) == []


def test_only_the_owner_gated_viewer_names_the_photo_partition_in_a_published_tree():
    assert set(scan(ROOT, PHOTO_RE)) <= OWNER_GATED_VIEWER
    src = (ROOT / "lambdas/web/progress_viewer_lambda.py").read_text()
    assert "progress_access" in src, "the viewer must stay behind the signed-link gate"


def test_no_published_module_names_the_lab_priorities_row():  # #5111: the seam is owner-only
    assert scan(ROOT, LAB_PRIORITIES_RE) == []


def test_the_sweep_catches_a_planted_reader(tmp_path):
    for t in PUBLISHED:
        (tmp_path / t).mkdir(parents=True)
    (tmp_path / "lambdas/web/a.py").write_text("from training import calibration_cadence\n")
    (tmp_path / "lambdas/emails/b.py").write_text("KEY = 'raw/matthew/progress_photos/x'\n")
    (tmp_path / "lambdas/web/c.py").write_text("from training import lab_priorities\n")
    assert scan(tmp_path, LAB_PRIORITIES_RE) == ["lambdas/web/c.py"]
    assert scan(tmp_path, IMPORT_RE) == ["lambdas/web/a.py", "lambdas/web/c.py"] and scan(tmp_path, PHOTO_RE) == ["lambdas/emails/b.py"]


def test_the_block_is_owner_tier_and_carries_no_media_path():
    b = block("2026-10-19", tape=[LAST], photos=[LAST], dexa=["2026-03-30"])
    assert b["tier"] == "owner_only"
    assert not re.search(r"\.jpe?g|raw/matthew", json.dumps(b))


# ── photos: no GPS EXIF is ever stored (owner rule; #5061 box 4) ───────────────────
def _seg(marker: int, payload: bytes) -> bytes:
    return bytes([0xFF, marker]) + (len(payload) + 2).to_bytes(2, "big") + payload


def _camera_jpeg() -> tuple[bytes, bytes]:
    """(a JPEG carrying EXIF with a GPS IFD, XMP and a comment; the same JPEG as it must be stored)."""
    app0 = _seg(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
    exif = _seg(0xE1, b"Exif\x00\x00MM\x00*\x00\x00\x00\x08GPSLatitude 47.6062 GPSLongitude -122.3321")
    xmp = _seg(0xE1, b"http://ns.adobe.com/xap/1.0/\x00<exif:GPSLatitude>47,36.37N</exif:GPSLatitude>")
    com = _seg(0xFE, b"taken at home")
    icc = _seg(0xE2, b"ICC_PROFILE\x00\x01\x01profile")
    dqt = _seg(0xDB, b"\x00" + bytes(64))
    scan = _seg(0xDA, b"\x01\x01\x00\x00\x3f\x00") + b"\x12\x34\xff\x00\x56" * 50 + b"\xff\xd9"
    soi = b"\xff\xd8"
    return soi + app0 + exif + xmp + com + icc + dqt + scan, soi + app0 + icc + dqt + scan


def test_a_stored_progress_photo_carries_no_gps_exif():
    from coach import progress_capture as pc

    raw, want = _camera_jpeg()
    got = pc.strip_metadata(raw)
    assert got == want
    assert b"GPS" not in got and b"Exif" not in got and b"taken at home" not in got
    assert pc.strip_metadata(got) == got  # idempotent: an already-clean photo is stored byte-for-byte


def test_the_download_path_strips_before_returning_and_refuses_an_unreadable_header():
    """The bytes `download` hands to `store` are the stripped ones; a header it cannot walk is refused (he is texted),
    never stored uninspected."""
    from coach import progress_capture as pc

    raw, want = _camera_jpeg()

    def opener(body):
        return lambda req, timeout=None: io.BytesIO(body)  # urlopen-shaped: a context manager with .read()

    assert pc.download("t", "photos/f.jpg", opener=opener(raw)) == want
    with pytest.raises(pc.Refused):
        pc.download("t", "photos/f.jpg", opener=opener(b"\xff\xd8\xff\xe1\xff\xff truncated"))
