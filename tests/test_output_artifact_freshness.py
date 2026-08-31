"""tests/test_output_artifact_freshness.py — the dead-man switch on off-platform jobs.

WHY THIS EXISTS (2026-08-31)
  The laptop's daily memory backup is the first job the platform depends on that runs
  entirely outside it: launchd, one machine, output to S3. Every existing control missed
  the failure that matters. `tests/test_backup_agent_path_contract.py` catches a broken
  LaunchAgent binding, but only when a human runs it locally — its live assertions skip
  in CI. And when the job stops there is no log line and no test failure to catch,
  because nothing runs. The last log entry simply stops, and a log that stops is
  indistinguishable from a log nobody has read yet.

  The control that closes that is an age check on the OUTPUT, from outside. These tests
  hold its two load-bearing properties:

    1. It must FAIL when the job dies — for any reason, since the whole point is to close
       the class (moved checkout / revoked credential / unloaded agent) rather than an
       instance.
    2. It must never report FRESH when it cannot see. A check that answers green while
       blind is worse than no check, because it also removes the operator's suspicion.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "_output_artifact_registry", ROOT / "lambdas" / "operational" / "output_artifact_registry.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


reg = _load()
KEY = "claude_memory_backup"


class FakeS3:
    """Minimal S3 stand-in. `error` makes head_object raise like botocore does."""

    def __init__(self, last_modified=None, payload=None, error=None):
        self.last_modified = last_modified
        self.payload = payload if payload is not None else {"memory_files": 380}
        self.error = error

    def head_object(self, Bucket, Key):  # noqa: N803 - boto3 kwarg names
        if self.error:
            raise self.error
        return {"LastModified": self.last_modified}

    def get_object(self, Bucket, Key):  # noqa: N803
        class _B:
            def __init__(self, data):
                self._d = data

            def read(self):
                return json.dumps(self._d).encode()

        return {"Body": _B(self.payload)}


def _client_error(code):
    err = Exception(f"simulated {code}")
    err.response = {"Error": {"Code": code}}  # type: ignore[attr-defined]
    return err


NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


# ── Property 1: it fails when the job dies ────────────────────────────────────
def test_a_recent_heartbeat_is_fresh():
    r = reg.check_artifact(KEY, FakeS3(last_modified=NOW - timedelta(hours=3)), NOW)
    assert r["status"] == reg.STATUS_FRESH
    assert r["age_hours"] == 3.0


def test_a_heartbeat_older_than_the_threshold_is_stale():
    """The whole point. 36h tolerates one missed window and trips on the second."""
    r = reg.check_artifact(KEY, FakeS3(last_modified=NOW - timedelta(hours=37)), NOW)
    assert r["status"] == reg.STATUS_STALE
    assert "37h ago" in r["detail"]
    assert r["runbook"] in r["detail"], "a stale alert must carry the runbook, not just the fact"


def test_the_boundary_is_where_the_registry_says_it_is():
    """Mutation guard: a threshold nobody tests is a threshold that can silently move."""
    hours = reg.OUTPUT_ARTIFACTS[KEY]["max_age_hours"]
    assert reg.check_artifact(KEY, FakeS3(last_modified=NOW - timedelta(hours=hours - 0.5)), NOW)["status"] == reg.STATUS_FRESH
    assert reg.check_artifact(KEY, FakeS3(last_modified=NOW - timedelta(hours=hours + 0.5)), NOW)["status"] == reg.STATUS_STALE


def test_a_successful_run_that_backed_up_nothing_is_not_fresh():
    """'Backed up nothing, successfully' must never read as healthy — the producer's own
    liveness gate should prevent it, so this is the second line of defence."""
    s3 = FakeS3(last_modified=NOW - timedelta(hours=1), payload={"memory_files": 0})
    r = reg.check_artifact(KEY, s3, NOW)
    assert r["status"] == reg.STATUS_STALE
    assert "ZERO memory file" in r["detail"]


# ── Property 2: blindness is never freshness ─────────────────────────────────
@pytest.mark.parametrize(
    "code,expect_in_detail",
    [
        ("404", "never completed a run"),
        ("NoSuchKey", "never completed a run"),
        ("AccessDenied", "this CHECK is broken"),
        ("SlowDown", "reporting unknown rather than fresh"),
    ],
)
def test_every_read_failure_is_unknown_never_fresh(code, expect_in_detail):
    r = reg.check_artifact(KEY, FakeS3(error=_client_error(code)), NOW)
    assert r["status"] == reg.STATUS_UNKNOWN, f"{code} must not read as fresh"
    assert r["age_hours"] is None
    assert expect_in_detail in r["detail"]


def test_access_denied_is_distinguished_from_a_dead_backup():
    """Different cause, different fix. Telling the operator the backup is stale when the
    truth is 'this check cannot see' sends them to the wrong machine."""
    denied = reg.check_artifact(KEY, FakeS3(error=_client_error("AccessDenied")), NOW)
    dead = reg.check_artifact(KEY, FakeS3(last_modified=NOW - timedelta(hours=99)), NOW)
    assert denied["status"] != dead["status"]
    assert "role_policies" in denied["detail"], "the fix for a blind check is an IAM grant; say so"


def test_not_ok_includes_unknown_as_well_as_stale():
    """Excluding `unknown` from the needs-attention set would restore the silent green."""
    results = [
        {"status": reg.STATUS_FRESH, "key": "a"},
        {"status": reg.STATUS_STALE, "key": "b"},
        {"status": reg.STATUS_UNKNOWN, "key": "c"},
    ]
    assert {r["key"] for r in reg.not_ok(results)} == {"b", "c"}


# ── The registry is the single definition, and both consumers derive from it ──
def test_registry_entries_are_complete():
    for key, spec in reg.OUTPUT_ARTIFACTS.items():
        for field in ("label", "bucket", "key", "max_age_hours", "produced_by", "why", "runbook"):
            assert spec.get(field), f"{key} is missing {field}"
        assert spec["max_age_hours"] > 0


def test_both_consumers_derive_from_the_registry_not_a_copy():
    """#392: a hand-maintained mirror of the source registry drifted worst of the three
    copies. This surface must not grow a second list."""
    checker = (ROOT / "lambdas" / "emails" / "freshness_checker_lambda.py").read_text(encoding="utf-8")
    tool = (ROOT / "mcp" / "tools_labs.py").read_text(encoding="utf-8")
    for body, who in ((checker, "freshness_checker_lambda"), (tool, "tools_labs")):
        assert "output_artifact_registry" in body, f"{who} must import the registry"
        assert "_backup_heartbeat.json" not in body, f"{who} must not hard-code the artifact key — derive it"


def test_the_producer_writes_the_key_the_registry_reads():
    """The producer and the consumer agree on ONE path, or the switch watches nothing."""
    script = (ROOT / "setup" / "claude_memory_backup.sh").read_text(encoding="utf-8")
    spec = reg.OUTPUT_ARTIFACTS[KEY]
    assert spec["key"] in script, f"the backup script must write {spec['key']}"
    assert spec["bucket"] in script or "$BUCKET" in script


def test_the_heartbeat_is_only_written_on_a_successful_sync():
    """A heartbeat written unconditionally would prove the script STARTED, not that the
    backup happened — turning the dead-man switch into a liveness check on bash."""
    script = (ROOT / "setup" / "claude_memory_backup.sh").read_text(encoding="utf-8")
    idx_sync = script.index('if "$AWS" s3 sync "$MEMORY_DIR/"')
    idx_hb = script.index("_backup_heartbeat.json")
    assert idx_sync < idx_hb, "the heartbeat write must sit inside the success branch of the sync"


def test_the_iam_grant_exists_and_is_scoped_to_the_prefix():
    """Without the grant the check is blind — honest, but blind. And an over-broad grant
    on a read-only checker is how least-privilege erodes one convenience at a time."""
    pol = (ROOT / "cdk" / "stacks" / "role_policies_operational.py").read_text(encoding="utf-8")
    assert "S3ReadOutputArtifactHeartbeats" in pol
    assert 'resources=[f"{BUCKET_ARN}/claude-memory-backup/*"]' in pol, "grant must be prefix-scoped, not bucket-wide"
    seg = pol[pol.index("S3ReadOutputArtifactHeartbeats") : pol.index("S3ReadOutputArtifactHeartbeats") + 600]
    assert "s3:PutObject" not in seg and "s3:DeleteObject" not in seg, "the checker reads; it must not write"


@pytest.mark.skipif(
    not (Path.home() / ".claude" / "projects").exists(),
    reason="no local Claude Code state (e.g. CI)",
)
def test_the_registry_threshold_is_compatible_with_the_producers_schedule():
    """A threshold shorter than the job's own period would alarm every day by construction."""
    plist = (ROOT / "setup" / "com.matthewwalker.claude-memory-backup.plist").read_text(encoding="utf-8")
    assert "StartCalendarInterval" in plist, "the producer must be on a schedule for an age check to mean anything"
    assert reg.OUTPUT_ARTIFACTS[KEY]["max_age_hours"] > 24, "a daily job needs a threshold above 24h"


# ── Which failures may repaint the headline verdict ──────────────────────────
def test_only_a_confirmed_stale_artifact_escalates_the_headline_status():
    """A dead backup turns get_freshness_status red. A BLIND check does not.

    The first version escalated on `unknown` too, and it was wrong in a way worth
    recording. `status`'s documented tiers are defined over SOURCE freshness, so widening
    them to cover the reachability of a monitoring dependency silently changes what an
    existing field means for every caller already reading it. It also made the verdict
    depend on S3 being reachable from wherever the tool runs: seven test modules call this
    tool and three flipped to yellow the moment the check landed. The available fix was to
    stub S3 in one more module each time — and needing to patch the caller repeatedly is
    the design telling you it is wrong.

    A blind check is still a real problem; it is just not a stale data source, and it is
    surfaced as itself (`output_artifacts_not_ok`) and paged from the freshness-checker
    Lambda, where both `stale` and `unknown` reach the operator.
    """
    body = (ROOT / "mcp" / "tools_labs.py").read_text(encoding="utf-8")
    seg = body[body.index("_stale_art = ") : body.index("_stale_art = ") + 400]
    assert 'overall = "red"' in seg, "a confirmed-stale artifact must force red"
    assert 'overall == "green"' not in seg, "an `unknown` artifact must not repaint the source verdict"


def test_the_paging_path_keeps_the_strict_reading():
    """Asymmetry on purpose: the Lambda alerts on unknown too. Assert it, so a future
    'consistency' cleanup cannot quietly relax the side that pages."""
    body = (ROOT / "lambdas" / "emails" / "freshness_checker_lambda.py").read_text(encoding="utf-8")
    assert "artifacts_not_ok" in body, "the checker must fold BOTH stale and unknown into its alert"
    assert "not_ok" in body
