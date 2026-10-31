"""tests/test_ops_pack_fold_2835.py — the Monday ops-pack fold (#2835).

Three read-only Monday emails (traffic-digest, data-reconciliation, pip-audit)
became ONE: the report jobs delivered S3 JSON artifacts carrying a
pre-rendered ``html`` fragment, and the traffic-digest email — already the
de-facto weekly ops email (green report #1446, subscriber funnel #1954) —
embeds them. The pip-audit job itself retired on 2026-10-30 (#5474: it could
never run pip on python3.12, #5473); the pack now points at the CI scan in
its place. Contracts pinned here:

  * **The pack embeds fail-soft with honest absence + loud staleness
    (ADR-104).** A missing/unreadable artifact renders "not collected"; an
    artifact older than its producer's cadence renders a STALE warning; a
    fresh one embeds verbatim. The section builder never raises.
  * **Inbox scannability survives the fold.** The severity the retired
    subjects carried rides the artifacts and is lifted into the pack subject
    (ops_subject_suffix) — a RED reconciliation week is visible without
    opening the email.
  * **End-to-end:** the pack email demonstrably carries the traffic body, the
    reconciliation section and the CI dependency-audit pointer.

No AWS, no network — clients are fakes, artifacts are fixtures.
"""

from __future__ import annotations

import gzip
import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

# Read at import time (conftest supplies fake AWS creds).
os.environ.setdefault("S3_BUCKET", "test-bucket")

from operational import traffic_digest_lambda as td  # noqa: E402


def _now():
    """Sampled per test at CALL time, never at import (#2223 wallclock rule)."""
    return datetime.now(timezone.utc)


# ══════════════════════════════════════════════════════════════════════════════
# the retired senders stay retired (the pip-audit Lambda itself retired on 2026-10-30, #5474)
# ══════════════════════════════════════════════════════════════════════════════


def test_data_reconciliation_module_holds_no_ses_client_or_send_path():
    src = open(os.path.join(os.path.dirname(__file__), "..", "lambdas", "operational", "data_reconciliation_lambda.py")).read()
    for token in ("sesv2", "send_email", "guarded_send_email", "EMAIL_RECIPIENT", "EMAIL_SENDER"):
        assert (
            token not in src
        ), f"data_reconciliation_lambda still carries {token!r} — the standalone send was supposed to be retired (#2835)"


# ══════════════════════════════════════════════════════════════════════════════
# The pack's fold: collect + section rendering
# ══════════════════════════════════════════════════════════════════════════════


class _ArtifactS3:
    """get_object fake keyed by S3 key; unknown keys raise like a real client."""

    def __init__(self, artifacts):
        self.artifacts = artifacts  # key -> bytes

    def get_object(self, Bucket, Key):
        if Key not in self.artifacts:
            raise RuntimeError(f"NoSuchKey: {Key}")
        return {"Body": io.BytesIO(self.artifacts[Key])}


def _fresh(now=None, html="<div>section-body</div>", age_days=0, **extra):
    art = {"generated_at": ((now or _now()) - timedelta(days=age_days)).isoformat(), "html": html}
    art.update(extra)
    return art


def test_collect_ops_artifact_reads_a_json_object():
    s3 = _ArtifactS3({"reconciliation/latest.json": json.dumps(_fresh()).encode()})
    art = td.collect_ops_artifact(s3, "reconciliation/latest.json")
    assert art["html"] == "<div>section-body</div>"


def test_collect_ops_artifact_is_fail_soft_on_missing_key_and_non_object():
    s3 = _ArtifactS3({"ops/not-an-object.json": b"[1, 2, 3]"})
    missing = td.collect_ops_artifact(s3, "reconciliation/latest.json")
    assert "unreadable" in missing["error"]
    not_object = td.collect_ops_artifact(s3, "ops/not-an-object.json")
    assert "not a JSON object" in not_object["error"]


def test_ops_section_embeds_a_fresh_artifact_verbatim():
    now = _now()
    html = td.build_ops_section_html("Data reconciliation", _fresh(now), 8, "weekly (Mon 07:30 UTC)", now=now)
    assert "Data reconciliation" in html
    assert "<div>section-body</div>" in html
    assert "STALE" not in html
    assert "weekly (Mon 07:30 UTC)" in html and "#2835" in html


def test_ops_section_renders_honest_absence_for_error_or_empty_artifacts():
    now = _now()
    for artifact in ({"error": "artifact x unreadable (NoSuchKey)"}, {}, None, _fresh(now, html=""), _fresh(now, html=None)):
        html = td.build_ops_section_html("Dependency audit", artifact, 38, "monthly", now=now)
        assert "not collected" in html, f"no honest-absence line for artifact {artifact!r}"
        assert "section-body" not in html


def test_ops_section_warns_loudly_when_the_producer_looks_dead():
    """A dead producer must be MORE visible in the pack than it was as a
    silently absent email — the whole point of folding the exempt sends."""
    now = _now()
    stale = td.build_ops_section_html("Data reconciliation", _fresh(now, age_days=20), 8, "weekly", now=now)
    assert "STALE" in stale and "20 days ago" in stale
    assert "<div>section-body</div>" in stale, "the stale section is still shown, dated"
    unstamped = td.build_ops_section_html("Data reconciliation", {"html": "<div>x</div>"}, 8, "weekly", now=now)
    assert "no readable generated_at" in unstamped


def test_ops_section_never_raises_on_hostile_shapes():
    for artifact in ({"html": 42}, {"generated_at": "not-a-date", "html": "<div>x</div>"}, {"error": None, "html": []}):
        td.build_ops_section_html("t", artifact, 8, "weekly", now=_now())  # must not raise


def test_ops_subject_suffix_carries_the_retired_subjects_scannability():
    assert td.ops_subject_suffix({"severity": "RED — Investigate Gaps"}) == " · recon RED"
    assert td.ops_subject_suffix({"severity": "YELLOW — Monitor"}) == " · recon YELLOW"
    assert td.ops_subject_suffix({"severity": "GREEN — Full Coverage"}) == ""
    assert td.ops_subject_suffix({"error": "unreadable"}) == ""
    # #5474: no `deps VULNERABLE` bit any more — a vulnerable layer is a red CI run, not a Monday subject
    assert "VULNERABLE" not in td.ops_subject_suffix({"severity": "RED", "has_vulnerabilities": True})


# ══════════════════════════════════════════════════════════════════════════════
# End-to-end: the pack email carries all three sections
# ══════════════════════════════════════════════════════════════════════════════

_CF_HEADER = "#Version: 1.0\n#Fields: date time c-ip cs-method cs(Host) cs-uri-stem sc-status cs(Referer) cs(User-Agent)\n"
_CF_ROW = "\t".join(["2026-08-24", "12:00:00", "1.1.1.1", "GET", "averagejoematt.com", "/", "200", "-", "Mozilla/5.0 (Mac)"])


class _PackS3:
    """One fake for both roles the handler uses s3 for: CF log listing/reads
    (the log bucket) and artifact get_object (the platform bucket)."""

    def __init__(self, artifacts):
        self.artifacts = artifacts
        self._log = gzip.compress((_CF_HEADER + _CF_ROW).encode())

    def get_paginator(self, name):
        return self

    def paginate(self, Bucket, Prefix, **_kw):  # #5433: Delimiter/StartAfter ignored, one flat page
        yield {"Contents": [{"Key": "cf/log1.gz", "LastModified": datetime.now(timezone.utc)}]}

    def get_object(self, Bucket, Key):
        if Key.startswith("cf/"):
            return {"Body": io.BytesIO(self._log)}
        if Key not in self.artifacts:
            raise RuntimeError(f"NoSuchKey: {Key}")
        return {"Body": io.BytesIO(self.artifacts[Key])}


class _CW:
    def put_metric_data(self, **kw):
        pass


class _SES:
    def __init__(self):
        self.sent: list[dict] = []

    def send_email(self, **kw):
        self.sent.append(kw)
        return {"MessageId": "fake"}


class _Boto3:
    def __init__(self, clients):
        self._clients = clients

    def client(self, name, region_name=None, **_kw):  # #5433: the log client passes config=
        return self._clients[name]


def _run_pack(monkeypatch, artifacts):
    recon_html = json.dumps(_fresh(html="<div>RECON-SECTION Weekly Data Reconciliation</div>", severity="YELLOW — Monitor"))
    defaults = {td.RECON_ARTIFACT_KEY: recon_html.encode()}
    ses = _SES()
    fake = _Boto3({"s3": _PackS3(defaults if artifacts is None else artifacts), "cloudwatch": _CW(), "sesv2": ses})
    monkeypatch.setattr(td, "LOG_BUCKET", "fake-log-bucket")
    monkeypatch.setattr(td, "boto3", fake)
    resp = td.lambda_handler({}, None)
    assert resp["statusCode"] == 200
    (email,) = ses.sent
    return email["Content"]["Simple"]["Subject"]["Data"], email["Content"]["Simple"]["Body"]["Html"]["Data"]


def test_pack_email_carries_the_traffic_body_the_reconciliation_fold_and_the_ci_audit_pointer(monkeypatch):
    """#2835 acceptance, as amended by #5474: one email — the traffic body, the reconciliation section, and (in place
    of the retired pip-audit fold) the pointer at the CI dependency scan — in one send."""
    subject, body = _run_pack(monkeypatch, None)
    assert subject.startswith("Weekly ops pack — ")
    assert "recon YELLOW" in subject and "deps" not in subject
    # Traffic section (native)
    assert "Top pages" in body
    # Folded sections, embedded verbatim
    assert "Data reconciliation — weekly source coverage" in body
    assert "RECON-SECTION Weekly Data Reconciliation" in body
    assert "Dependency audit — CI" in body and td.CI_DEPENDENCY_AUDIT_URL in body
    assert "pip-audit/latest.json" not in body and "PIP-SECTION" not in body
    # The green report still rides along
    assert "Weekly green report" in body


def test_pack_email_survives_missing_artifacts_with_honest_absence(monkeypatch):
    subject, body = _run_pack(monkeypatch, {})
    assert subject.startswith("Weekly ops pack — ")
    assert "recon" not in subject and "deps" not in subject
    assert body.count("not collected") >= 1
    assert "Data reconciliation — weekly source coverage" in body
    assert "Dependency audit — CI" in body  # static: it needs no artifact, so it is never "not collected"
