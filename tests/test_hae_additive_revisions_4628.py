"""#4628, the writer row recorded 2026-10-18 — a reading re-delivered with a CHANGED quantity.

The phone sometimes re-sends a reading's timestamp with a new quantity: 17 of 20,833 additive
readings delivered 2026-10-10..23 (read-only replay of the raw archive, 2026-10-23), in both
directions. The #4962 writer kept the first-seen quantity and threw the revision away — against
the owner's capture-all rule (2026-10-04) — and a replay of the raw archive could not reproduce the
writer's order, because LastModified is whole seconds and two deliveries of 2026-10-15 00:47:23Z
tie on it.

The fixture is the wire: two real re-delivery pairs from the raw archive (see its `_provenance`):
  * 2026-10-21 walking/running distance — the later delivery (03:14:39Z, 70 min after the first)
    replaces nine minutes the first carried as one flat repeated value with distinct per-minute
    values (8 up, 1 down);
  * 2026-10-12 basal energy — the later delivery (64 min after) re-sends 133 readings and lowers
    one of them, 2.78 -> 1.18 kcal.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in (os.path.join(ROOT, "lambdas"), os.path.join(ROOT, "scripts"), os.path.dirname(__file__)):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import hae_additive_backfill_4628 as backfill  # noqa: E402
from ingestion import (  # noqa: E402
    health_auto_export_additive as additive,
    health_auto_export_lambda as hae,
)
from ingestion.source_registry import raw_date_key  # noqa: E402
from operational import hae_additive_integrity_qa as integ  # noqa: E402
from test_hae_additive_sum_4628 import ApplyingTable, FakeS3  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "hae_additive_revisions_4628.json")
_BEARER = "test-bearer-4628-revisions"


def _pairs():
    with open(FIXTURE) as fh:
        return {p["metric"]: p for p in json.load(fh)["pairs"]}


def _readings(delivery):
    (metric,) = delivery["payload"]["data"]["metrics"]
    return {r["date"]: r["qty"] for r in metric["data"]}


def _changed(pair):
    a, b = (_readings(d) for d in pair["deliveries"])
    return {ts: (a[ts], b[ts]) for ts in a if ts in b and a[ts] != b[ts]}


def _expected(pair):
    """Independent of the writer: per timestamp, the quantity of the LATEST delivery that carried it."""
    latest = {}
    for d in pair["deliveries"]:
        latest.update(_readings(d))
    return latest


class MetaS3(FakeS3):
    """FakeS3 that also keeps each object's Metadata, LastModified and a listing."""

    def __init__(self):
        super().__init__()
        self.meta, self.modified = {}, {}

    def put_object(self, Bucket=None, Key=None, Body=None, Metadata=None, **_):
        self.meta[Key] = dict(Metadata or {})
        return super().put_object(Bucket=Bucket, Key=Key, Body=Body)

    def get_object(self, Bucket=None, Key=None, **kw):
        resp = super().get_object(Bucket=Bucket, Key=Key, **kw)
        resp["Metadata"] = self.meta.get(Key, {})
        return resp


@pytest.fixture
def wired(monkeypatch):
    s3, table = MetaS3(), ApplyingTable()
    monkeypatch.setattr(hae, "s3_client", s3)
    monkeypatch.setattr(hae, "table", table)
    monkeypatch.setattr(hae, "get_api_key", lambda: _BEARER)
    return s3, table


def _deliver(delivery):
    event = {"headers": {"authorization": f"Bearer {_BEARER}"}, "body": json.dumps(delivery["payload"])}
    assert hae.lambda_handler(event, None)["statusCode"] == 200


def test_a_revised_reading_takes_the_newest_quantity_and_every_version_is_kept(wired):
    """Each pair's two real deliveries through the REAL handler, in arrival order: each changed
    timestamp holds the later delivery's quantity, both versions sit in the archive's `revisions`, and
    the stored day value is the sum the later delivery describes. Before the fix the first-seen
    quantity was kept and the revision was discarded — this test fails on the #4962 writer."""
    for metric in ("walking_running_distance", "basal_energy_burned"):
        _check_pair(wired, _pairs()[metric])


def _check_pair(wired, pair):
    s3, table = wired
    metric = pair["metric"]
    changed = _changed(pair)
    assert changed, "the fixture lost its revised readings — nothing is exercised"
    field = hae.METRIC_MAP[metric]["field"]

    for d in pair["deliveries"]:
        _deliver(d)

    obj = json.loads(s3.objects[raw_date_key("apple_health", pair["day"], sub=f"additive_{field}")])
    ((src, readings),) = obj["readings"].items()
    offenders = {ts: (readings[ts], new) for ts, (_, new) in changed.items() if readings[ts] != new}
    assert not offenders, f"a revised reading kept a stale quantity (kept, newest): {offenders}"
    assert {ts: [q for _, q in v] for ts, v in obj["revisions"][src].items()} == {ts: [old, new] for ts, (old, new) in changed.items()}

    want = additive.day_value(field, {src: _expected(pair)}, obj["units"])
    first_seen = additive.day_value(field, {src: {**_readings(pair["deliveries"][1]), **_readings(pair["deliveries"][0])}}, obj["units"])
    assert want != first_seen, "the fixture's revisions no longer move the day value"
    assert float(table.item[field]) == pytest.approx(want, abs=1e-9)


def test_a_stale_re_send_and_a_whole_replay_change_nothing(wired):
    """A version already delivered never moves the value again: the FIRST delivery re-sent after the
    revision (a client retry), then both deliveries again, leave the reading and the row unchanged."""
    s3, table = wired
    pair = _pairs()["walking_running_distance"]
    for d in pair["deliveries"]:
        _deliver(d)
    key = raw_date_key("apple_health", pair["day"], sub="additive_distance_walk_run_miles")
    before, stored = s3.objects[key], float(table.item["distance_walk_run_miles"])
    for d in [pair["deliveries"][0], *pair["deliveries"]]:
        _deliver(d)
    assert s3.objects[key] == before
    assert float(table.item["distance_walk_run_miles"]) == stored


def test_the_raw_delivery_is_stamped_with_its_receipt_time(wired):
    """The raw archive carries the handler's receipt time at microsecond resolution as S3 metadata, so
    a replay can order two deliveries LastModified cannot (the 2026-10-15 00:47:23Z tie)."""
    s3, _ = wired
    _deliver(_pairs()["basal_energy_burned"]["deliveries"][0])
    ((raw_key, meta),) = [(k, m) for k, m in s3.meta.items() if k.startswith("raw/matthew/health_auto_export/")]
    stamp = meta["received-at"]
    assert datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%fZ") and stamp == additive.received_stamp(
        datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    )


def test_the_backfill_replays_in_receipt_order_not_lastmodified_order():
    """Both deliveries listed with the SAME LastModified second; the receipt metadata says the
    lexically-second key arrived first. The replay follows the metadata, so the newest version is the
    one the metadata names — the LastModified listing order alone would pick the other."""
    pair = _pairs()["walking_running_distance"]
    a, b = pair["deliveries"]
    tie = datetime(2026, 10, 21, 3, 14, 39, tzinfo=timezone.utc)
    s3 = MetaS3()
    for d, received in ((a, tie + timedelta(microseconds=900)), (b, tie + timedelta(microseconds=100))):
        s3.put_object(Key=d["archived_as"], Body=json.dumps(d["payload"]), Metadata={"received-at": additive.received_stamp(received)})
    keys = sorted([(a["archived_as"], "2026-10-21", tie), (b["archived_as"], "2026-10-21", tie)])
    payloads = backfill.read_payloads(s3, "matthew-life-platform", keys, workers=2)
    assert [p[0] for p in payloads] == [b["archived_as"], a["archived_as"]]
    replayed, _ = backfill.replay(payloads)
    slot = replayed[pair["day"]]["distance_walk_run_miles"]
    ((src, readings),) = slot["readings"].items()
    assert {ts: readings[ts] for ts in _changed(pair)} == {ts: old for ts, (old, _) in _changed(pair).items()}

    # no metadata (every delivery before this change): LastModified, then the listed key order
    legacy = MetaS3()
    for d in (a, b):
        legacy.put_object(Key=d["archived_as"], Body=json.dumps(d["payload"]))
    legacy.meta.clear()
    replayed, _ = backfill.replay(backfill.read_payloads(legacy, "matthew-life-platform", keys, workers=2))
    ((src, readings),) = replayed[pair["day"]]["distance_walk_run_miles"]["readings"].items()
    assert {ts: readings[ts] for ts in _changed(pair)} == {ts: new for ts, (_, new) in _changed(pair).items()}


def test_the_integrity_check_never_reds_a_downward_revision():
    """The basal pair LOWERS one reading. The writer stores the newest version; the nightly check's
    delivered side counts each timestamp at its smallest version, so the writer's honest value is not
    a shortfall — the check's old first-seen rule would have named it one."""
    pair = _pairs()["basal_energy_burned"]
    payloads = [d["payload"] for d in pair["deliveries"]]
    stored = sum(_expected(pair).values())
    first_seen = sum({**_readings(pair["deliveries"][1]), **_readings(pair["deliveries"][0])}.values())
    assert stored < first_seen * (1 - integ.REL_TOL) - 0.01, "the old first-seen delivered side would red this day"
    delivered = integ.delivered_day_values(payloads, [pair["day"]])
    counts = integ.shortfall_counts(delivered, {(pair["day"], "basal_calories"): stored})
    assert counts["checked"] == 1 and counts["short"] == 0
    assert integ.shortfall_counts(delivered, {(pair["day"], "basal_calories"): stored - 5})["short"] == 1
