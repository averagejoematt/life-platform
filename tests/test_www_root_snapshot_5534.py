"""tests/test_www_root_snapshot_5534.py — the production-root snapshot and its rollback rehearsal
(owner ask, 2026-11-01): capture reads site/ and writes only under backups/; rehearse never targets
site/; restore is refused without --apply; the manifest names every key and ETag.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(_REPO, "deploy", "www_root_snapshot.sh")

STUB = r"""#!/usr/bin/env bash
# a recording aws: head-object answers from a fixture, cp/sync are logged, nothing leaves the machine
echo "$*" >> "$AWS_LOG"
case "$1 $2" in
  "s3api head-object")
    key=""; for ((i=1;i<=$#;i++)); do [ "${!i}" = "--key" ] && j=$((i+1)) && key="${!j}"; done
    case "$key" in
      site/index.html|backups/*/index.html) printf '"etag-index"\t6642\n' ;;
      site/404.html|backups/*/404.html) printf '"etag-404"\t11030\n' ;;
      *) exit 254 ;;
    esac ;;
  "s3 cp")
    if [ "$4" = "-" ] || [ "$3" = "-" ]; then :; fi
    # a manifest read: emit the fixture manifest
    case "$3" in *manifest.json) [ "$4" = "-" ] && cat "$MANIFEST_FIXTURE" ;; esac ;;
  "s3 sync") : ;;
  *) : ;;
esac
"""


def _env(tmp_path, owned):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    aws = bindir / "aws"
    aws.write_text(STUB)
    aws.chmod(aws.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "aws.log"
    log.write_text("")
    owned_path = tmp_path / "owned_paths.json"
    owned_path.write_text(json.dumps(owned))
    fixture = tmp_path / "manifest.json"
    fixture.write_text(
        json.dumps(
            {
                "stamp": "S",
                "objects": [
                    {"key": "index.html", "etag": "etag-index", "size": 6642},
                    {"key": "404.html", "etag": "etag-404", "size": 11030},
                ],
            }
        )
    )
    env = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "AWS_LOG": str(log),
        "OWNED_PATHS": str(owned_path),
        "MANIFEST_FIXTURE": str(fixture),
        "BUCKET": "test-bucket",
    }
    return env, log


OWNED = {"static_routes": ["/", "/story/"], "files": ["404.html", "sitemap.xml"]}


def _run(args, env):
    return subprocess.run(["bash", SCRIPT, *args], capture_output=True, text=True, env=env)


def test_restore_is_refused_without_apply_and_calls_no_aws(tmp_path):
    env, log = _env(tmp_path, OWNED)
    r = _run(["restore", "20260101T000000Z"], env)
    assert r.returncode == 2 and "REFUSED" in r.stderr
    assert log.read_text() == "", "a refused restore touches nothing"
    r = _run(["restore", "20260101T000000Z", "--apply", "--print"], env)
    assert r.returncode == 0 and "PRINT ONLY" in r.stdout and "s3://test-bucket/site/" in r.stdout
    assert log.read_text() == "", "--print runs nothing"


def test_capture_derives_the_keys_from_owned_paths_and_writes_only_under_backups(tmp_path):
    env, log = _env(tmp_path, OWNED)
    r = _run(["capture"], env)
    assert r.returncode == 0, r.stderr
    calls = log.read_text().splitlines()
    copies = [c for c in calls if c.startswith("s3 cp s3://test-bucket/site/")]
    assert {c.split()[2] for c in copies} == {
        "s3://test-bucket/site/index.html",
        "s3://test-bucket/site/404.html",
    }, "the two present keys are copied"
    assert all(" s3://test-bucket/backups/root-snapshots/" in c for c in copies), "every destination is under backups/"
    assert not any(
        " s3://test-bucket/site/" in c.split(" ", 3)[3] for c in copies if len(c.split(" ", 3)) > 3
    ), "nothing is written under site/"
    assert "story/index.html (absent" in r.stdout and "sitemap.xml (absent" in r.stdout, "absent keys are named, not invented"
    assert "2 object(s) captured, 2 absent" in r.stdout
    manifest_puts = [c for c in calls if c.startswith("s3 cp ") and c.rstrip().endswith("manifest.json --only-show-errors")]
    assert len(manifest_puts) == 1


def test_rehearse_restores_into_the_scratch_prefix_and_compares_etags(tmp_path):
    env, log = _env(tmp_path, OWNED)
    r = _run(["rehearse", "S"], env)
    assert r.returncode == 0, r.stdout + r.stderr
    calls = log.read_text().splitlines()
    syncs = [c for c in calls if c.startswith("s3 sync ")]
    assert syncs and all("s3://test-bucket/backups/root-restore-rehearsal/S/" in c for c in syncs)
    assert not any("s3://test-bucket/site/" in c for c in syncs), "the rehearsal never targets site/"
    assert r.stdout.count("✓ restored (rehearsal)") == 2 and "0 problem(s)" in r.stdout


def test_verify_reports_live_drift_per_key(tmp_path):
    env, log = _env(tmp_path, OWNED)
    r = _run(["verify", "S"], env)
    assert r.returncode == 0 and "live unchanged since capture" in r.stdout and "0 problem(s), 0 changed" in r.stdout


def test_bash_syntax_and_usage():
    assert subprocess.run(["bash", "-n", SCRIPT]).returncode == 0
    r = subprocess.run(["bash", SCRIPT], capture_output=True, text=True)
    assert r.returncode == 3 and "capture" in r.stderr
