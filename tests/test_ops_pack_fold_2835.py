"""tests/test_ops_pack_fold_2835.py — the Monday ops-pack fold (#2835).

Three read-only Monday emails (traffic-digest, data-reconciliation, pip-audit)
became ONE: the two report jobs now deliver S3 JSON artifacts carrying a
pre-rendered ``html`` fragment, and the traffic-digest email — already the
de-facto weekly ops email (green report #1446, subscriber funnel #1954) —
embeds them. Contracts pinned here:

  * **pip-audit's delivery is the artifact.** Both keys (dated + latest) are
    written, the fragment is embeddable (no document wrapper), a dry run
    writes nothing, a failed write raises, and — critically — the #1336 SCA
    hard-fail still writes the artifact BEFORE raising, exactly as the old
    email went out before the raise.
  * **The pack embeds fail-soft with honest absence + loud staleness
    (ADR-104).** A missing/unreadable artifact renders "not collected"; an
    artifact older than its producer's cadence renders a STALE warning; a
    fresh one embeds verbatim. The section builder never raises.
  * **Inbox scannability survives the fold.** The severity the retired
    subjects carried rides the artifacts and is lifted into the pack subject
    (ops_subject_suffix) — a RED reconciliation week or a vulnerable scan is
    visible without opening the email.
  * **End-to-end:** the pack email demonstrably carries all three sections.

No AWS, no network — clients are fakes, artifacts are fixtures.
"""

from __future__ import annotations

import gzip
import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

# Read at import time (conftest supplies fake AWS creds).
os.environ.setdefault("S3_BUCKET", "test-bucket")

from operational import (
    pip_audit_lambda as pa,  # noqa: E402
    traffic_digest_lambda as td,  # noqa: E402
)


def _now():
    """Sampled per test at CALL time, never at import (#2223 wallclock rule)."""
    return datetime.now(timezone.utc)


# ══════════════════════════════════════════════════════════════════════════════
# pip-audit: artifact-as-delivery
# ══════════════════════════════════════════════════════════════════════════════


class _RecordingS3:
    def __init__(self, boom=False):
        self.puts: list[dict] = []
        self.boom = boom

    def put_object(self, **kw):
        if self.boom:
            raise RuntimeError("AccessDenied")
        self.puts.append(kw)


_CLEAN_RESULT = {"lambda": "garmin", "vulnerabilities": [], "packages_checked": 3, "status": "clean"}


@pytest.fixture()
def pip_env(monkeypatch):
    """Wire the pip-audit handler to fakes: no subprocess, no S3 download, no
    GitHub call — just the delivery path under test."""

    def _install(layer_gaps=None, s3_boom=False, audit_result=None):
        s3 = _RecordingS3(boom=s3_boom)
        monkeypatch.setattr(pa, "s3", s3)
        monkeypatch.setattr(pa, "ensure_pip_audit", lambda: True)
        monkeypatch.setattr(pa, "list_requirements_files", lambda: ["config/requirements/garmin.txt"])
        monkeypatch.setattr(pa, "download_requirements", lambda key, path: True)
        monkeypatch.setattr(pa, "audit_requirements_file", lambda path, name: dict(audit_result or _CLEAN_RESULT))
        monkeypatch.setattr(pa, "check_layer_manifest_coverage", lambda: list(layer_gaps or []))
        monkeypatch.setattr(pa, "check_alerts_enabled", lambda: {"status": "skipped", "reason": "no GitHub token in Lambda env"})
        return s3

    return _install


def test_pip_audit_writes_dated_and_latest_artifacts(pip_env):
    s3 = pip_env()
    resp = pa.lambda_handler({"force": True}, None)
    assert resp["statusCode"] == 200
    dated, latest = s3.puts
    assert dated["Key"].startswith("pip-audit/") and dated["Key"].endswith("_pip_audit.json")
    assert latest["Key"] == pa.LATEST_ARTIFACT_KEY
    assert latest["Body"] == dated["Body"], "the stable key and the dated archive must carry the same report"
    artifact = json.loads(latest["Body"])
    assert artifact["has_vulnerabilities"] is False
    assert artifact["hard_fail_reasons"] == []
    assert "Monthly pip-audit Report" in artifact["html"]
    assert "<!DOCTYPE" not in artifact["html"], "the section must be an embeddable fragment, not a document"
    # The pack's staleness check needs a parseable stamp.
    assert td.parse_iso_utc(artifact["generated_at"]) is not None


def test_pip_audit_dry_run_computes_but_writes_nothing(pip_env):
    """The manual-invoke hazard is now the latest.json overwrite (it changes
    what next Monday's ops pack embeds) — a dry run must leave S3 untouched."""
    s3 = pip_env()
    resp = pa.lambda_handler({"force": True, "dry_run": True}, None)
    assert resp["statusCode"] == 200
    assert s3.puts == []


def test_pip_audit_sca_hard_fail_still_writes_the_artifact_before_raising(pip_env):
    """#1336 semantics through the fold: the run must page (raise → Errors →
    DLQ digest) AND the operator must still get the detail — previously the
    email went out before the raise; now the artifact must land before it."""
    s3 = pip_env(layer_gaps=["pillow"])
    with pytest.raises(RuntimeError, match="SCA guard RED"):
        pa.lambda_handler({"force": True}, None)
    assert len(s3.puts) == 2, "the artifact must be delivered before the hard-fail raise"
    artifact = json.loads(s3.puts[-1]["Body"])
    assert artifact["hard_fail_reasons"], "the artifact must name why the run hard-failed"
    assert artifact["has_vulnerabilities"] is True  # the synthetic SCA-UNSCANNED-LAYER finding
    assert "SCA-UNSCANNED-LAYER" in artifact["html"]


def test_pip_audit_raises_when_the_artifact_cannot_be_delivered(pip_env):
    """The artifact IS the delivery — a silent write failure would age into a
    stale line in the pack with no page."""
    pip_env(s3_boom=True)
    with pytest.raises(RuntimeError, match="AccessDenied"):
        pa.lambda_handler({"force": True}, None)


def test_pip_audit_module_holds_no_ses_client_or_send_path():
    """The retired send must be GONE, not dormant: no SES client, no send
    helper — so the #2222 derived sender set and the DIL-025 census both drop
    this module naturally rather than carrying a sender that never fires."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "lambdas", "operational", "pip_audit_lambda.py")).read()
    for token in ("sesv2", "send_email", "guarded_send_email", "EMAIL_RECIPIENT", "EMAIL_SENDER"):
        assert token not in src, f"pip_audit_lambda still carries {token!r} — the standalone send was supposed to be retired (#2835)"


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
    s3 = _ArtifactS3({"pip-audit/latest.json": b"[1, 2, 3]"})
    missing = td.collect_ops_artifact(s3, "reconciliation/latest.json")
    assert "unreadable" in missing["error"]
    not_object = td.collect_ops_artifact(s3, "pip-audit/latest.json")
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
    assert td.ops_subject_suffix({"severity": "RED — Investigate Gaps"}, {}) == " · recon RED"
    assert td.ops_subject_suffix({"severity": "YELLOW — Monitor"}, {"has_vulnerabilities": True}) == " · recon YELLOW · deps VULNERABLE"
    assert td.ops_subject_suffix({"severity": "GREEN — Full Coverage"}, {"has_vulnerabilities": False}) == ""
    assert td.ops_subject_suffix({"error": "unreadable"}, {"error": "unreadable"}) == ""


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

    def paginate(self, Bucket, Prefix):
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

    def client(self, name, region_name=None):
        return self._clients[name]


def _run_pack(monkeypatch, artifacts):
    recon_html = json.dumps(_fresh(html="<div>RECON-SECTION Weekly Data Reconciliation</div>", severity="YELLOW — Monitor"))
    pip_html = json.dumps(_fresh(html="<div>PIP-SECTION Monthly pip-audit Report</div>", has_vulnerabilities=True))
    defaults = {td.RECON_ARTIFACT_KEY: recon_html.encode(), td.PIP_AUDIT_ARTIFACT_KEY: pip_html.encode()}
    ses = _SES()
    fake = _Boto3({"s3": _PackS3(defaults if artifacts is None else artifacts), "cloudwatch": _CW(), "sesv2": ses})
    monkeypatch.setattr(td, "LOG_BUCKET", "fake-log-bucket")
    monkeypatch.setattr(td, "boto3", fake)
    resp = td.lambda_handler({}, None)
    assert resp["statusCode"] == 200
    (email,) = ses.sent
    return email["Content"]["Simple"]["Subject"]["Data"], email["Content"]["Simple"]["Body"]["Html"]["Data"]


def test_pack_email_carries_all_three_sections(monkeypatch):
    """#2835 acceptance: one email, three folded reports — the traffic body,
    the reconciliation section, and the pip-audit section, in one send."""
    subject, body = _run_pack(monkeypatch, None)
    assert subject.startswith("Weekly ops pack — ")
    assert "recon YELLOW" in subject and "deps VULNERABLE" in subject
    # Traffic section (native)
    assert "Top pages" in body
    # Folded sections, embedded verbatim
    assert "Data reconciliation — weekly source coverage" in body
    assert "RECON-SECTION Weekly Data Reconciliation" in body
    assert "Dependency audit — pip-audit" in body
    assert "PIP-SECTION Monthly pip-audit Report" in body
    # The green report still rides along
    assert "Weekly green report" in body


def test_pack_email_survives_missing_artifacts_with_honest_absence(monkeypatch):
    subject, body = _run_pack(monkeypatch, {})
    assert subject.startswith("Weekly ops pack — ")
    assert "recon" not in subject and "deps" not in subject
    assert body.count("not collected") >= 2
    assert "Data reconciliation — weekly source coverage" in body
    assert "Dependency audit — pip-audit" in body
