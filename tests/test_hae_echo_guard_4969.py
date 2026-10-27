"""#4969 — owner ruling 2026-10-27 (option c): a minute re-exported once with NO source tag and once
tagged with the watch's source is ONE reading, not two, on any day.

The fixture is the wire's structure: the four 2026-10-25 Health Auto Export deliveries that carried
`step_count` / `active_energy` for that UTC day — three from the old automation (EMPTY source tag,
stamps at the phone's second offsets) and the 22:02:52Z re-export after the reconfiguration (the
watch's tag, alone or combined with the phone, minute-aligned). Timestamps, source strings, units and
the per-delivery grouping are the archived bytes; every quantity is synthetic (see `_provenance`).
They are replayed through the real webhook handler against an in-memory S3 and a DynamoDB double that
applies each update, so the asserted number is what the row holds after the last delivery.

Capture-all is asserted alongside: the archive object and the `_rd_` map keep every copy; only the
day total stops counting the echo. Two real devices in one minute are never resolved against each
other, and an untagged minute no watch reading covers still counts.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
if LAMBDAS not in sys.path:
    sys.path.insert(0, LAMBDAS)

os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from ingestion import (  # noqa: E402
    health_auto_export_additive as additive,
    health_auto_export_echo as echo,
    health_auto_export_lambda as hae,
)
from ingestion.source_registry import raw_date_key  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "hae_echo_switchover_2026-10-25.json")
DAY = "2026-10-25"
_BEARER = "test-bearer-4969"
WATCH = "Matthew’s Apple Watch"  # the measured tag bytes: curly apostrophe + NO-BREAK SPACE
COMBINED = WATCH + "|Matt 17"
FIELD_OF = {"step_count": "steps", "active_energy": "active_calories"}


class _NoSuchKey(Exception):
    pass


class _S3Exceptions:
    NoSuchKey = _NoSuchKey


class FakeS3:
    exceptions = _S3Exceptions()

    def __init__(self):
        self.objects = {}

    def get_object(self, Bucket=None, Key=None, **_):
        if Key not in self.objects:
            raise _NoSuchKey(Key)
        body = self.objects[Key]

        class _B:
            def read(self_inner):
                return body.encode("utf-8")

        return {"Body": _B()}

    def put_object(self, Bucket=None, Key=None, Body=None, **_):
        self.objects[Key] = Body
        return {}


class ApplyingTable:
    """Applies `SET #a = :v` / `if_not_exists` clauses, so a replay leaves the row as the real merges would."""

    def __init__(self, stored=None):
        self.item = dict(stored or {})

    def get_item(self, Key=None, ProjectionExpression=None, ExpressionAttributeNames=None, **_):
        names = ExpressionAttributeNames or {}
        wanted = [names.get(p.strip(), p.strip()) for p in (ProjectionExpression or "").split(",") if p.strip()]
        item = {k: v for k, v in self.item.items() if not wanted or k in wanted}
        return {"Item": item} if item else {}

    def update_item(self, UpdateExpression=None, ExpressionAttributeNames=None, ExpressionAttributeValues=None, **_):
        for name_ph, guarded, plain in re.findall(
            r"(#[A-Za-z0-9]+) = (?:if_not_exists\(#[A-Za-z0-9]+, (:[A-Za-z0-9]+)\)|(:[A-Za-z0-9]+))", UpdateExpression
        ):
            name = ExpressionAttributeNames[name_ph]
            if guarded and name in self.item:
                continue
            self.item[name] = ExpressionAttributeValues[guarded or plain]
        return {}


@pytest.fixture
def wired(monkeypatch):
    def _wire(stored=None):
        s3, table = FakeS3(), ApplyingTable(stored)
        monkeypatch.setattr(hae, "s3_client", s3)
        monkeypatch.setattr(hae, "table", table)
        monkeypatch.setattr(hae, "get_api_key", lambda: _BEARER)
        return s3, table

    return _wire


def _deliveries():
    with open(FIXTURE) as fh:
        return json.load(fh)["deliveries"]


def _replay(deliveries):
    for d in deliveries:
        event = {"headers": {"authorization": f"Bearer {_BEARER}"}, "body": json.dumps(d["payload"])}
        assert hae.lambda_handler(event, None)["statusCode"] == 200


def _minute(stamp):
    return int(datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S %z").astimezone(timezone.utc).timestamp()) // 60


def _expected():
    """The independent expectation, straight from the fixture (not through the writer): per field, every
    unique (source, timestamp) reading — the naive sum — and the same minus each untagged reading whose UTC
    minute holds a watch-tagged reading. Also the counts the asserts below need."""
    readings = {}
    for d in _deliveries():
        for m in d["payload"]["data"]["metrics"]:
            for r in m["data"]:
                readings.setdefault(FIELD_OF[m["name"]], {}).setdefault((r["source"] or "", r["date"]), r["qty"])
    out = {}
    for field, by_key in readings.items():
        watch_minutes = {_minute(ts) for (src, ts) in by_key if "watch" in src.replace(" ", " ").lower()}
        echoes = {(src, ts) for (src, ts) in by_key if not src and _minute(ts) in watch_minutes}
        untagged_only = {(src, ts) for (src, ts) in by_key if not src and (src, ts) not in echoes}
        out[field] = {
            "naive": round(sum(by_key.values()), 2),
            "guarded": round(sum(q for k, q in by_key.items() if k not in echoes), 2),
            "readings": len(by_key),
            "echoes": len(echoes),
            "untagged_only": len(untagged_only),
            "untagged_only_sum": round(sum(by_key[k] for k in untagged_only), 2),
        }
    return out


# ── the 2026-10-25 switch-over, through the real handler ──────────────────────


def test_the_fixture_carries_the_measured_switchover_shape():
    """Guard the fixture itself: both metrics, untagged copies that share a minute with a tagged one (the
    issue's measured class), untagged readings no tagged reading covers, and the combined watch|phone tag."""
    exp = _expected()
    assert set(exp) == {"steps", "active_calories"}
    # The 10-25 archive measured 144 shared step minutes and 423 active-energy ones across five
    # deliveries; the fixture keeps the two deliveries that carry 58 + 159 of them, plus the reconfigured re-export.
    assert exp["steps"]["echoes"] == 58 and exp["active_calories"]["echoes"] == 159
    assert exp["steps"]["untagged_only"] > 0 and exp["active_calories"]["untagged_only"] > 0
    sources = {r["source"] for d in _deliveries() for m in d["payload"]["data"]["metrics"] for r in m["data"]}
    assert sources == {"", WATCH, COMBINED}


def test_switchover_day_counts_each_minute_once(wired):
    """THE FALSIFIER. Before the guard the day total is the naive sum over (source, timestamp) — both copies of
    every re-exported minute. After it, each untagged copy of a watch-tagged minute is left out of the total."""
    _, table = wired()
    exp = _expected()
    _replay(_deliveries())
    offenders = {
        f: (float(table.item[f]), e["guarded"], e["naive"]) for f, e in exp.items() if abs(float(table.item[f]) - e["guarded"]) > 0.01
    }
    assert not offenders, f"stored ≠ one-reading-per-minute total (stored, guarded, naive): {offenders}"
    assert all(e["naive"] - e["guarded"] > 1 for e in exp.values()), "the fixture no longer exercises the echo"


def test_a_second_replay_changes_nothing(wired):
    """Idempotent: the whole day re-sent (every reading already archived) leaves the guarded totals as they were."""
    _, table = wired()
    _replay(_deliveries())
    first = {f: float(table.item[f]) for f in ("steps", "active_calories")}
    _replay(_deliveries())
    assert {f: float(table.item[f]) for f in first} == first


def test_the_archive_keeps_every_copy(wired):
    """Capture-all: the additive archive object still holds the untagged bucket in full — the guard moves
    the TOTAL only, never what is stored."""
    s3, _ = wired()
    exp = _expected()
    _replay(_deliveries())
    for field, e in exp.items():
        obj = json.loads(s3.objects[raw_date_key("apple_health", DAY, sub=f"additive_{field}")])
        assert sum(len(tsq) for tsq in obj["readings"].values()) == e["readings"], field
        assert len(obj["readings"]["_unknown"]) == e["echoes"] + e["untagged_only"], field


def test_untagged_minutes_no_watch_reading_covers_still_count(wired):
    """The deliveries before the re-export, alone: every untagged reading counts exactly as before."""
    _, table = wired()
    exp = _expected()
    untagged = _deliveries()[:3]
    _replay(untagged)
    for field in exp:
        want = round(
            sum(r["qty"] for d in untagged for m in d["payload"]["data"]["metrics"] if FIELD_OF[m["name"]] == field for r in m["data"]), 2
        )
        assert float(table.item[field]) == pytest.approx(want, abs=0.01), field


def test_mutation_control_without_the_guard_the_replay_double_counts(wired, monkeypatch):
    """Mutation control: with the guard disabled (the archive's counted map = every reading) the same replay
    stores the naive double-counted total — so the falsifier above can fail, and fails on exactly this."""
    monkeypatch.setattr(echo, "counted_by_source", lambda readings: {s: dict(t) for s, t in readings.items()})
    _, table = wired()
    exp = _expected()
    _replay(_deliveries())
    for field, e in exp.items():
        assert float(table.item[field]) == pytest.approx(e["naive"], abs=0.01), field
        assert abs(float(table.item[field]) - e["guarded"]) > 1, field


# ── the rule, on the archive's {source: {ts: qty}} shape ──────────────────────


def _archive_total(readings):
    return additive.day_value("active_calories", readings, "kcal")


def test_two_real_devices_in_one_minute_both_count():
    """Never pick a winner between devices: WHOOP + watch, phone + watch, phone + untagged — all kept."""
    ts_w, ts_x = "2026-10-25 13:26:00 -0700", "2026-10-25 13:26:31 -0700"
    assert _archive_total({WATCH: {ts_w: 2.0}, "WHOOP": {ts_x: 3.0}}) == 5.0
    assert _archive_total({WATCH: {ts_w: 2.0}, "Matt 17": {ts_x: 3.0}}) == 5.0
    assert (
        _archive_total({"Matt 17": {ts_w: 2.0}, "_unknown": {ts_x: 3.0}}) == 5.0
    ), "an untagged copy of a NON-watch tag is out of the ruling"


def test_an_untagged_copy_of_a_watch_minute_counts_once():
    """Untagged + watch (or the combined watch|phone tag) in one UTC minute: the tagged reading counts, at a
    different second offset, at the identical stamp, and across a timezone offset that names the same minute."""
    tagged, untagged = "2026-10-25 13:26:00 -0700", "2026-10-25 13:26:14 -0700"
    assert _archive_total({WATCH: {tagged: 2.0}, "_unknown": {untagged: 3.0}}) == 2.0
    assert _archive_total({COMBINED: {tagged: 2.0}, "_unknown": {untagged: 3.0}}) == 2.0
    assert _archive_total({WATCH: {tagged: 2.0}, "_unknown": {tagged: 2.0}}) == 2.0
    assert _archive_total({WATCH: {tagged: 2.0}, "_unknown": {"2026-10-25 20:26:45 +0000": 3.0}}) == 2.0
    assert _archive_total({WATCH: {tagged: 2.0}, "_unknown": {"2026-10-25 13:27:00 -0700": 3.0}}) == 5.0, "the next minute is not an echo"


# ── the `_rd_` map path (watch sums / means), through the real handler ────────


def _daylight(stamps, source, qty):
    return {
        "data": {
            "metrics": [{"name": "time_in_daylight", "units": "min", "data": [{"date": s, "qty": qty, "source": source} for s in stamps]}]
        }
    }


UNTAGGED_STAMPS = ["2026-10-25 12:27:45 -0700", "2026-10-25 12:28:45 -0700", "2026-10-25 12:40:12 -0700"]
TAGGED_STAMPS = ["2026-10-25 12:27:00 -0700", "2026-10-25 12:28:00 -0700"]


def test_rd_map_counts_a_watch_minute_once_and_keeps_both_keys(wired):
    """A watch-only additive field (`_rd_daylight_minutes_apple`): an untagged delivery, then the watch-tagged
    re-export of two of its minutes. The total counts the two tagged readings + the one uncovered untagged
    reading; the `_rd_` map keeps all five keys and the `_rdc_` companion names each one's class."""
    _, table = wired()
    for payload in (_daylight(UNTAGGED_STAMPS, "", 4.0), _daylight(TAGGED_STAMPS, WATCH, 5.0)):
        assert (
            hae.lambda_handler({"headers": {"authorization": f"Bearer {_BEARER}"}, "body": json.dumps(payload)}, None)["statusCode"] == 200
        )
    assert float(table.item["daylight_minutes_apple"]) == pytest.approx(5.0 * 2 + 4.0)
    assert set(table.item["_rd_daylight_minutes_apple"]) == set(UNTAGGED_STAMPS) | set(TAGGED_STAMPS)
    classes = table.item[f"{echo.CLASS_MAP_PREFIX}daylight_minutes_apple"]
    assert {ts for ts, c in classes.items() if c == echo.UNTAGGED} == set(UNTAGGED_STAMPS)
    assert {ts for ts, c in classes.items() if c == echo.WATCH} == set(TAGGED_STAMPS)


def test_rd_map_mutation_control(wired, monkeypatch):
    """Mutation control for the `_rd_` path: no echo proven → the old sum of every key."""
    monkeypatch.setattr(echo, "echo_stamps", lambda classes: set())
    _, table = wired()
    for payload in (_daylight(UNTAGGED_STAMPS, "", 4.0), _daylight(TAGGED_STAMPS, WATCH, 5.0)):
        hae.lambda_handler({"headers": {"authorization": f"Bearer {_BEARER}"}, "body": json.dumps(payload)}, None)
    assert float(table.item["daylight_minutes_apple"]) == pytest.approx(4.0 * 3 + 5.0 * 2)


def test_rd_map_written_before_the_guard_is_never_collapsed(wired):
    """A stored `_rd_` key with no class (written before this guard) is never treated as an echo — the guard
    only applies where it can prove both copies."""
    stored = {"_rd_daylight_minutes_apple": {s: 4.0 for s in UNTAGGED_STAMPS}, "daylight_minutes_apple": 12.0}
    _, table = wired(stored=stored)
    hae.lambda_handler({"headers": {"authorization": f"Bearer {_BEARER}"}, "body": json.dumps(_daylight(TAGGED_STAMPS, WATCH, 5.0))}, None)
    assert float(table.item["daylight_minutes_apple"]) == pytest.approx(4.0 * 3 + 5.0 * 2)


def test_rd_mean_field_counts_a_watch_minute_once():
    """The averaged `_rd_` fields take the same rule: an echo does not double-weight its minute in the mean."""
    new = echo.reading_map(
        {"_unknown": {"2026-10-25 01:00:30 -0700": 90.0}, WATCH: {"2026-10-25 01:00:00 -0700": 40.0, "2026-10-25 02:00:00 -0700": 60.0}}
    )
    merged, value = echo.merge_field(new, {}, "hrv_sdnn_apple", mean=True)
    assert value == 50.0
    assert len(merged) == 3


def test_rd_two_devices_in_one_minute_both_count():
    """`_rd_` path: phone + watch in one minute are two readings (the tier-2 all-sources merge, unchanged)."""
    new = echo.reading_map({"Matt 17": {"2026-10-25 01:00:30 -0700": 97.0}, WATCH: {"2026-10-25 01:00:00 -0700": 95.0}})
    _, value = echo.merge_field(new, {}, "spo2_pct_apple", mean=True)
    assert value == 96.0


# ── scripts/hae_echo_rederive_4969.py — the driver's re-derivation of an already-written day ──


def _load_script():
    import importlib.util

    spec = importlib.util.spec_from_file_location("hae_echo_rederive_4969", os.path.join(ROOT, "scripts", "hae_echo_rederive_4969.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RecordingTable(ApplyingTable):
    def __init__(self, stored=None):
        super().__init__(stored)
        self.updates = []

    def update_item(self, Key=None, ConditionExpression=None, **kw):
        self.updates.append({"Key": Key, "ConditionExpression": ConditionExpression, **kw})
        return super().update_item(**kw)


@pytest.fixture
def written_before_the_guard(wired, monkeypatch):
    """The 2026-10-25 state as the live writer left it: the day replayed with the guard OFF."""
    s3, table = wired(stored={"total_calories_burned": 2222.22, "basal_calories": 1111.11})
    with monkeypatch.context() as m:
        m.setattr(echo, "counted_by_source", lambda readings: {s: dict(t) for s, t in readings.items()})
        _replay(_deliveries())
    rec = RecordingTable(table.item)
    return s3, rec


def test_rederive_dry_run_names_the_changed_fields_and_writes_nothing(written_before_the_guard, capsys):
    s3, table = written_before_the_guard
    before = dict(table.item)
    assert _load_script().main(["--date", DAY], s3=s3, table=table) == 0
    out = capsys.readouterr().out
    assert out.strip().splitlines()[-1] == "changed: active_calories, steps, total_calories_burned"
    exp = _expected()
    assert f"echoes {exp['steps']['echoes']:>5}" in out and f"echoes {exp['active_calories']['echoes']:>5}" in out
    assert table.updates == [] and table.item == before, "a dry run must not write"
    # counts only: no stored or re-derived health value is printed
    leaked = [
        v for f in ("steps", "active_calories", "total_calories_burned") for v in (float(before[f]), exp.get(f, {}).get("guarded")) if v
    ]
    assert not [v for v in leaked if f"{v:g}" in out or f"{v:.2f}" in out], "the dry run printed a health value"


def test_rederive_apply_sets_only_the_echo_fields_then_is_idempotent(written_before_the_guard, capsys):
    s3, table = written_before_the_guard
    archive_before = dict(s3.objects)
    script = _load_script()
    script.main(["--date", DAY, "--apply"], s3=s3, table=table)
    exp = _expected()
    assert len(table.updates) == 1 and table.updates[0]["ConditionExpression"] == "attribute_exists(sk)"
    assert set(table.updates[0]["ExpressionAttributeNames"].values()) == {"steps", "active_calories", "total_calories_burned"}
    for f in ("steps", "active_calories"):
        assert float(table.item[f]) == pytest.approx(exp[f]["guarded"], abs=0.01), f
    assert float(table.item["total_calories_burned"]) == pytest.approx(exp["active_calories"]["guarded"] + 1111.11, abs=0.01)
    assert s3.objects == archive_before, "the archive objects are capture-all: never written"
    capsys.readouterr()
    script.main(["--date", DAY, "--apply"], s3=s3, table=table)
    assert capsys.readouterr().out.strip().splitlines()[-1] == "changed: none"
    assert len(table.updates) == 1, "a second run writes nothing"


def test_rederive_rd_map_with_classes_and_without(capsys):
    """A `_rd_` map whose companion proves an echo is re-derived; one written before the guard is reported, untouched."""
    stamps = {"2026-10-25 12:27:45 -0700": Decimal("4"), "2026-10-25 12:27:00 -0700": Decimal("5")}
    item = {
        "pk": "x",
        "sk": f"DATE#{DAY}",
        "daylight_minutes_apple": Decimal("9"),
        "_rd_daylight_minutes_apple": dict(stamps),
        "_rdc_daylight_minutes_apple": {"2026-10-25 12:27:45 -0700": "untagged", "2026-10-25 12:27:00 -0700": "watch"},
        "stand_minutes_apple": Decimal("9"),
        "_rd_stand_minutes_apple": dict(stamps),
    }
    table = RecordingTable(item)
    _load_script().main(["--date", DAY, "--apply"], s3=FakeS3(), table=table)
    out = capsys.readouterr().out
    assert "changed: daylight_minutes_apple" in out
    assert float(table.item["daylight_minutes_apple"]) == 5.0 and float(table.item["stand_minutes_apple"]) == 9.0
    assert table.item["_rd_daylight_minutes_apple"] == stamps, "the map keeps every copy"
    assert "no-classes" in [ln.split()[-1] for ln in out.splitlines() if ln.startswith("stand_minutes_apple")]
