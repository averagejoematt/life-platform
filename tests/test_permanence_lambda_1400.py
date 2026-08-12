#!/usr/bin/env python3
"""tests/test_permanence_lambda_1400.py — the nightly run's write discipline (#1400).

The handler is the only place in the Permanence Contract that touches the
world, so this file is about *when it does not*: a dry run must build the whole
archive and publish nothing, a frozen contract must stop overwriting the
rolling copy, and a state that has not changed must not mail anyone.

Everything is offline — the AWS clients are injected by monkeypatching
``_clients``, so no boto3 session is ever constructed.
"""

from __future__ import annotations

import io
import json
import os
import sys
from datetime import timedelta, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.path.join(ROOT, "lambdas") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from operational import (
    continuity_watch as watch,  # noqa: E402
    permanence_lambda as pl,  # noqa: E402
    public_archive_registry as reg,  # noqa: E402
)

BUCKET_OBJECTS = {
    "generated/pulse.json": b'{"pulse":1}',
    "site/index.html": b"<h1>home</h1>",
    "generated/qa_archive/text/2026-08-01/x.json": b'{"internal":1}',
}


class _FakeS3:
    def __init__(self, objects, continuity=None):
        self.objects = dict(objects)
        self.puts: list[dict] = []
        if continuity is not None:
            self.objects[reg.ARCHIVE_CONTINUITY_KEY] = json.dumps(continuity).encode()

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):  # noqa: N803
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        return {"Contents": [{"Key": k, "Size": len(self.objects[k])} for k in keys], "IsTruncated": False}

    def get_object(self, Bucket, Key):  # noqa: N803
        if Key not in self.objects:
            raise KeyError(Key)
        return {"Body": io.BytesIO(self.objects[Key])}

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
        self.objects[kwargs["Key"]] = kwargs["Body"]
        return {}

    def put_keys(self) -> list[str]:
        return [p["Key"] for p in self.puts]


def _days_ago(n: int) -> str:
    """A date relative to *now*, never a literal.

    Deliberate: a hard-coded 2026-08-10 in a silence test is a time bomb — it
    reads as `active` today and as `triggered` in three months, and the failure
    lands on whoever is unlucky rather than whoever changed something.
    """
    from datetime import datetime

    return (datetime.now(timezone.utc).date() - timedelta(days=n)).isoformat()


class _FakeTable:
    def __init__(self, days_ago):
        self.last_day = None if days_ago is None else _days_ago(days_ago)

    def query(self, **kwargs):
        if self.last_day is None:
            return {"Items": []}
        item = {"sk": f"DATE#{self.last_day}"}
        if "steps" in (kwargs.get("ProjectionExpression") or ""):
            item["steps"] = 5000
        return {"Items": [item]}


class _FakeSes:
    def __init__(self):
        self.sent: list[dict] = []

    def send_email(self, **kwargs):
        self.sent.append(kwargs)
        return {"MessageId": "real"}


class _FakeSecrets:
    def __init__(self, contacts=None):
        self.contacts = contacts

    def get_secret_value(self, SecretId):  # noqa: N803
        if self.contacts is None:
            raise RuntimeError("no such secret")
        return {"SecretString": json.dumps({"contacts": self.contacts})}


@pytest.fixture(autouse=True)
def _offline_defaults(monkeypatch):
    """No inter-fetch politeness pause under test, and no secret cache bleeding
    a previous test's contact list into the next one."""
    from common import secret_cache

    monkeypatch.setattr(pl.public_archive, "FETCH_PAUSE_SECONDS", 0)
    secret_cache.invalidate()
    yield
    secret_cache.invalidate()


def _wire(monkeypatch, *, days_ago=1, continuity=None, contacts=None):
    s3 = _FakeS3(BUCKET_OBJECTS, continuity=continuity)
    ses = _FakeSes()
    table = _FakeTable(days_ago)
    secrets = _FakeSecrets(contacts)
    monkeypatch.setattr(pl, "_clients", lambda: (table, s3, ses, secrets))
    monkeypatch.setattr(pl.public_archive, "default_fetch", lambda url: (200, b'{"ok":true}'))
    monkeypatch.setattr(pl.public_archive, "FETCH_PAUSE_SECONDS", 0)
    return s3, ses


def _body(result):
    return json.loads(result["body"])


# ── the write gate ──────────────────────────────────────────────────────────
def test_a_dry_run_builds_everything_and_publishes_nothing(monkeypatch):
    s3, ses = _wire(monkeypatch)
    result = pl.lambda_handler({"dry_run": True}, None)
    body = _body(result)
    assert body["dry_run"] is True
    assert body["archive_bytes"] > 0, "a dry run must still build the archive — that is the point of it"
    assert body["entry_count"] > 0
    assert body["published"] == []
    assert s3.put_keys() == []
    assert ses.sent == []


def test_a_real_run_publishes_the_three_standing_objects(monkeypatch):
    s3, _ses = _wire(monkeypatch)
    body = _body(pl.lambda_handler({}, None))
    assert set(s3.put_keys()) == {reg.ARCHIVE_TARBALL_KEY, reg.ARCHIVE_MANIFEST_KEY, reg.ARCHIVE_CONTINUITY_KEY}
    assert body["published"] == s3.put_keys()
    types = {p["Key"]: p["ContentType"] for p in s3.puts}
    assert types[reg.ARCHIVE_TARBALL_KEY] == "application/gzip"
    assert types[reg.ARCHIVE_MANIFEST_KEY] == "application/json"


def test_the_stable_address_is_overwritten_not_rotated(monkeypatch):
    """The whole promise is that the URL is the same tomorrow. A dated-only
    scheme would break every link a reader saved."""
    s3, _ses = _wire(monkeypatch)
    pl.lambda_handler({}, None)
    pl.lambda_handler({}, None)
    tarballs = [k for k in s3.put_keys() if k.endswith(".tar.gz")]
    assert tarballs == [reg.ARCHIVE_TARBALL_KEY, reg.ARCHIVE_TARBALL_KEY]


def test_published_manifest_carries_the_continuity_summary(monkeypatch):
    s3, _ses = _wire(monkeypatch)
    pl.lambda_handler({}, None)
    manifest = json.loads([p for p in s3.puts if p["Key"] == reg.ARCHIVE_MANIFEST_KEY][0]["Body"])
    assert manifest["continuity"]["state"] == watch.STATE_ACTIVE
    assert manifest["continuity"]["path"] == reg.ARCHIVE_CONTINUITY_PUBLIC_PATH
    assert manifest["archive"]["sha256"]


def test_published_continuity_carries_the_terms_and_the_archive_pointer(monkeypatch):
    """One document a reader can fetch to learn the state, the promise, and
    where the bytes are — without a second request."""
    s3, _ses = _wire(monkeypatch)
    pl.lambda_handler({}, None)
    doc = json.loads([p for p in s3.puts if p["Key"] == reg.ARCHIVE_CONTINUITY_KEY][0]["Body"])
    assert doc["terms"]["version"]
    assert [c["id"] for c in doc["terms"]["clauses"]][:2] == ["P1", "P2"]
    assert doc["archive"]["path"] == reg.ARCHIVE_PUBLIC_PATH
    assert doc["archive"]["sha256"]
    assert doc["state"] == watch.STATE_ACTIVE


def test_the_published_continuity_document_leaks_no_infrastructure(monkeypatch):
    s3, _ses = _wire(monkeypatch)
    pl.lambda_handler({}, None)
    blob = [p for p in s3.puts if p["Key"] == reg.ARCHIVE_CONTINUITY_KEY][0]["Body"].decode()
    for needle in ("matthew-life-platform", "arn:aws", ".amazonaws.com", "s3://", "generated/"):
        assert needle not in blob, f"the published continuity document leaks {needle!r}"


# ── the freeze ──────────────────────────────────────────────────────────────
def test_tripping_the_switch_seals_a_dated_edition_and_stops_the_rolling_copy(monkeypatch):
    s3, ses = _wire(monkeypatch, days_ago=200, continuity={"state": watch.STATE_WARNING})
    body = _body(pl.lambda_handler({}, None))
    assert body["state"] == watch.STATE_TRIGGERED
    assert body["frozen"] is True
    sealed = [k for k in s3.put_keys() if k.startswith(reg.ARCHIVE_PREFIX + "final-")]
    assert len(sealed) == 1, "the trigger must seal exactly one dated final edition"
    assert reg.ARCHIVE_TARBALL_KEY in s3.put_keys(), "the last rolling write happens on the trigger run itself"
    assert len(ses.sent) == 1


def test_a_frozen_contract_stops_overwriting_on_subsequent_nights(monkeypatch):
    s3, ses = _wire(
        monkeypatch,
        days_ago=200,
        continuity={"state": watch.STATE_TRIGGERED, "frozen": True, "triggered_at": "2026-06-01T00:00:00Z"},
    )
    body = _body(pl.lambda_handler({}, None))
    assert body["frozen"] is True
    assert reg.ARCHIVE_TARBALL_KEY not in s3.put_keys(), "a frozen archive must not be overwritten"
    assert reg.ARCHIVE_MANIFEST_KEY not in s3.put_keys()
    assert reg.ARCHIVE_CONTINUITY_KEY in s3.put_keys(), "the clock keeps publishing — that is how a reader sees it is frozen"
    assert not [k for k in s3.put_keys() if "final-" in k], "the final edition is sealed once, not re-sealed nightly"
    assert ses.sent == [], "an unchanged state must not mail anyone"


def test_a_new_signal_thaws_the_archive(monkeypatch):
    s3, _ses = _wire(
        monkeypatch,
        days_ago=1,
        continuity={"state": watch.STATE_TRIGGERED, "frozen": True, "triggered_at": "2026-06-01T00:00:00Z"},
    )
    body = _body(pl.lambda_handler({}, None))
    assert body["state"] == watch.STATE_ACTIVE
    assert body["frozen"] is False
    assert reg.ARCHIVE_TARBALL_KEY in s3.put_keys()


def test_an_unreadable_table_reports_unknown_and_changes_nothing(monkeypatch):
    """A DynamoDB outage must not be able to freeze the archive or mail
    anyone. The archive still rebuilds; the clock says it could not measure."""

    class _BrokenTable:
        def query(self, **kwargs):
            raise RuntimeError("ddb down")

    s3 = _FakeS3(BUCKET_OBJECTS)
    ses = _FakeSes()
    monkeypatch.setattr(pl, "_clients", lambda: (_BrokenTable(), s3, ses, _FakeSecrets(None)))
    monkeypatch.setattr(pl.public_archive, "default_fetch", lambda url: (200, b"{}"))
    body = _body(pl.lambda_handler({}, None))
    assert body["state"] == watch.STATE_UNKNOWN
    assert body["frozen"] is False
    assert ses.sent == []
    assert reg.ARCHIVE_TARBALL_KEY in s3.put_keys(), "the archive is independent of the clock and must still publish"


# ── the notification ────────────────────────────────────────────────────────
def test_a_transition_mails_the_configured_contacts(monkeypatch):
    s3, ses = _wire(
        monkeypatch,
        days_ago=40,
        continuity={"state": watch.STATE_ACTIVE},
        contacts=["someone@example.test", "another@example.test"],
    )
    body = _body(pl.lambda_handler({}, None))
    assert body["state"] == watch.STATE_NOTICE
    assert len(ses.sent) == 1
    assert ses.sent[0]["Destination"]["ToAddresses"] == ["someone@example.test", "another@example.test"]
    assert body["notification"]["contacts_configured"] is True


def test_missing_contacts_fall_back_to_the_operator_and_say_so(monkeypatch):
    """Honest reporting: the contract claims the contacts are told. If no
    contacts exist, the run must record that rather than imply they were."""
    s3, ses = _wire(monkeypatch, days_ago=40, continuity={"state": watch.STATE_ACTIVE}, contacts=None)
    body = _body(pl.lambda_handler({}, None))
    assert len(ses.sent) == 1
    assert ses.sent[0]["Destination"]["ToAddresses"] == [pl.EMAIL_RECIPIENT]
    assert body["notification"]["contacts_configured"] is False


def test_a_dry_run_suppresses_the_transition_mail(monkeypatch):
    s3, ses = _wire(monkeypatch, days_ago=40, continuity={"state": watch.STATE_ACTIVE}, contacts=["x@example.test"])
    body = _body(pl.lambda_handler({"dry_run": True}, None))
    assert ses.sent == []
    assert body["notification"]["sent"] is False


def test_a_failed_send_does_not_lose_the_published_state(monkeypatch):
    class _BrokenSes:
        def send_email(self, **kwargs):
            raise RuntimeError("ses down")

    s3 = _FakeS3(BUCKET_OBJECTS, continuity={"state": watch.STATE_ACTIVE})
    monkeypatch.setattr(pl, "_clients", lambda: (_FakeTable(40), s3, _BrokenSes(), _FakeSecrets(None)))
    monkeypatch.setattr(pl.public_archive, "default_fetch", lambda url: (200, b"{}"))
    body = _body(pl.lambda_handler({}, None))
    assert body["notification"]["sent"] is False
    assert body["notification"]["reason"] == "send_failed"
    assert reg.ARCHIVE_CONTINUITY_KEY in s3.put_keys()


# ── observability ───────────────────────────────────────────────────────────
def test_the_run_emits_the_heartbeat_metric(monkeypatch, capsys):
    _wire(monkeypatch)
    pl.lambda_handler({}, None)
    emf = [line for line in capsys.readouterr().out.splitlines() if '"ArchiveBuilt"' in line]
    assert len(emf) == 1, "exactly one EMF line per run — the heartbeat alarm counts samples"
    doc = json.loads(emf[0])
    assert doc["ArchiveBuilt"] == 1
    assert doc["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "LifePlatform/Permanence"
    assert doc["ContinuityState"] == pl.STATE_CODES[watch.STATE_ACTIVE]
    assert doc["ContinuityDaysSilent"] == 1


def test_unknown_state_is_not_encoded_as_a_healthy_zero():
    """A failed measurement graphed as `active` would be the worst possible
    chart on the worst possible day."""
    assert pl.STATE_CODES[watch.STATE_UNKNOWN] == -1
    assert pl.STATE_CODES[watch.STATE_ACTIVE] == 0
    assert pl.STATE_CODES[watch.STATE_UNKNOWN] not in {v for k, v in pl.STATE_CODES.items() if k != watch.STATE_UNKNOWN}


def test_every_contract_state_has_a_metric_code():
    for state in (watch.STATE_UNKNOWN, watch.STATE_ACTIVE, watch.STATE_NOTICE, watch.STATE_WARNING, watch.STATE_TRIGGERED):
        assert state in pl.STATE_CODES


# ── the API blackout guard ──────────────────────────────────────────────────
def test_a_total_api_outage_does_not_overwrite_a_good_archive(monkeypatch):
    """An hour of site outage must not replace a complete archive with a hollow
    one. Yesterday's copy is the only thing this run exists to protect."""
    s3, _ses = _wire(monkeypatch)
    monkeypatch.setattr(pl.public_archive, "default_fetch", lambda url: (503, b""))
    body = _body(pl.lambda_handler({}, None))
    assert body["api_blackout"] is True
    assert body["archive_published"] is False
    assert reg.ARCHIVE_TARBALL_KEY not in s3.put_keys()
    assert reg.ARCHIVE_MANIFEST_KEY not in s3.put_keys()
    assert reg.ARCHIVE_CONTINUITY_KEY in s3.put_keys(), "the clock is independent of the site and keeps publishing"


def test_a_blackout_withholds_the_heartbeat_datapoint(monkeypatch, capsys):
    """`ArchiveBuilt=0` would be worse than useless — the alarm counts samples,
    not values, so a zero would keep it green while the archive went stale. The
    metric must be absent from the emission entirely."""
    _wire(monkeypatch)
    monkeypatch.setattr(pl.public_archive, "default_fetch", lambda url: (503, b""))
    pl.lambda_handler({}, None)
    lines = [line for line in capsys.readouterr().out.splitlines() if '"ApiRoutesCaptured"' in line]
    assert len(lines) == 1
    doc = json.loads(lines[0])
    assert "ArchiveBuilt" not in doc
    names = {m["Name"] for m in doc["_aws"]["CloudWatchMetrics"][0]["Metrics"]}
    assert "ArchiveBuilt" not in names
    assert "ApiRoutesMissed" in names and doc["ApiRoutesMissed"] == len(reg.ARCHIVE_ROUTES)


def test_a_partial_capture_still_publishes(monkeypatch):
    """Partial is not blackout. A manifest saying 57/115 is legible; a missing
    archive is not, and the reader is better served by the honest partial."""
    calls = {"n": 0}

    def _flaky(url):
        calls["n"] += 1
        return (200, b'{"ok":true}') if calls["n"] % 2 else (500, b"")

    s3, _ses = _wire(monkeypatch)
    monkeypatch.setattr(pl.public_archive, "default_fetch", _flaky)
    body = _body(pl.lambda_handler({}, None))
    assert body["api_blackout"] is False
    assert body["archive_published"] is True
    assert 0 < body["api_captured"] < body["api_declared"]
    manifest = json.loads([p for p in s3.puts if p["Key"] == reg.ARCHIVE_MANIFEST_KEY][0]["Body"])
    assert manifest["api"]["routes_captured"] == body["api_captured"]


def test_a_blackout_never_seals_a_final_edition(monkeypatch):
    """The sealed edition is the last thing anyone gets. It must never be an
    empty archive produced on a night the site happened to be down."""
    s3, _ses = _wire(monkeypatch, days_ago=200, continuity={"state": watch.STATE_WARNING})
    monkeypatch.setattr(pl.public_archive, "default_fetch", lambda url: (503, b""))
    body = _body(pl.lambda_handler({}, None))
    assert body["state"] == watch.STATE_TRIGGERED
    assert not [k for k in s3.put_keys() if "final-" in k]
