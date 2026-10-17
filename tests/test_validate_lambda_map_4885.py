"""tests/test_validate_lambda_map_4885.py — deploy/validate_lambda_map.sh, extracted from ci-cd.yml (#4885)."""

import json
import os
import pathlib
import shutil
import subprocess

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
_SCRIPT = _REPO / "deploy" / "validate_lambda_map.sh"

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")


def _run(tmp_path, sources, present):
    for rel in present:
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x")
    m = tmp_path / "map.json"
    m.write_text(json.dumps({"lambdas": {s: {} for s in sources}}))
    env = dict(os.environ, LAMBDA_MAP=str(m))
    return subprocess.run(["bash", str(_SCRIPT)], cwd=tmp_path, env=env, capture_output=True, text=True)


def test_all_present_passes(tmp_path):
    r = _run(tmp_path, ["a/x.py", "b/y.py"], ["a/x.py", "b/y.py"])
    assert r.returncode == 0 and "all source files present" in r.stdout


def test_missing_fails_and_counts(tmp_path):
    r = _run(tmp_path, ["a/x.py", "b/y.py", "c/z.py"], ["a/x.py"])
    assert r.returncode == 1
    assert "MISSING source: b/y.py" in r.stdout and "references 2 missing" in r.stdout


def test_real_map_is_valid():
    r = subprocess.run(["bash", str(_SCRIPT)], cwd=_REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
