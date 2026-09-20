"""#3917 — the `integration` marker's credential restore must work under `-n auto`, not only serially.

THE DEFECT. `tests/conftest.py` fakes the AWS env at import (#381) and the `integration` fixture
restores a snapshot `_REAL_AWS_ENV` around live tests. Under pytest-xdist every worker is a fresh
process forked AFTER the controller already faked its environment, so a worker's own snapshot
captured `testing` and "restoring" it restored the fake — a correct serial behaviour that did
nothing in the parallel lane CI actually runs (#3895 met it first).

THE FIX. The controller stashes the real values into `LP_REAL_AWS_ENV__<KEY>` env vars (which
workers inherit) before faking, writing the stash only when absent; `_REAL_AWS_ENV` is derived from
the stash. `test_a_worker_process_derives_the_snapshot_from_the_stash_not_the_fakes` reproduces the
worker condition WITHOUT xdist: a subprocess whose environment already carries the fakes and the
stash imports conftest and reports what it would restore. Mutation control: make `_REAL_AWS_ENV`
read `os.environ.get(key)` again (the pre-fix line) → that test reds with `restore == testing`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

_PROBE = """
import json, os, sys
sys.path.insert(0, %r)
import conftest  # applies the fakes at import, exactly as pytest's collection does
print(json.dumps({"restore": conftest._REAL_AWS_ENV, "live": {k: os.environ.get(k) for k in conftest._AWS_CRED_KEYS}}))
"""


def _probe(env: dict) -> dict:
    out = subprocess.run([sys.executable, "-c", _PROBE % HERE], env=env, capture_output=True, text=True, cwd=REPO, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


def _clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_") and not k.startswith("LP_REAL_AWS_ENV__")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def test_the_controller_stashes_the_real_credentials_before_faking():
    """A fresh process with real-looking credentials: the fakes go on, and the snapshot is the real value."""
    env = _clean_env()
    env["AWS_ACCESS_KEY_ID"] = "AKIA_REAL_FOR_TEST"
    env["AWS_SECRET_ACCESS_KEY"] = "real-secret"
    out = _probe(env)
    assert out["live"]["AWS_ACCESS_KEY_ID"] == "testing", "the fakes must still be applied at import"
    assert out["restore"]["AWS_ACCESS_KEY_ID"] == "AKIA_REAL_FOR_TEST"
    assert out["restore"]["AWS_SECRET_ACCESS_KEY"] == "real-secret"
    assert out["restore"]["AWS_PROFILE"] is None, "an absent key restores as absent, not as an empty string"


def test_a_worker_process_derives_the_snapshot_from_the_stash_not_the_fakes():
    """THE xdist CONDITION, reproduced: the environment ALREADY carries the fakes (the controller
    applied them) plus the controller's stash. Before #3917 this snapshot read `testing`."""
    env = _clean_env()
    env.update(
        {
            "AWS_ACCESS_KEY_ID": "testing",
            "AWS_SECRET_ACCESS_KEY": "testing",
            "AWS_SESSION_TOKEN": "testing",
            "AWS_SECURITY_TOKEN": "testing",
        }
    )
    env["LP_REAL_AWS_ENV__AWS_ACCESS_KEY_ID"] = "AKIA_REAL_FOR_TEST"
    env["LP_REAL_AWS_ENV__AWS_SECRET_ACCESS_KEY"] = "real-secret"
    env["LP_REAL_AWS_ENV__AWS_SESSION_TOKEN"] = "__unset__"
    env["LP_REAL_AWS_ENV__AWS_SECURITY_TOKEN"] = "__unset__"
    env["LP_REAL_AWS_ENV__AWS_PROFILE"] = "__unset__"
    out = _probe(env)
    assert out["restore"]["AWS_ACCESS_KEY_ID"] == "AKIA_REAL_FOR_TEST", out
    assert out["restore"]["AWS_SESSION_TOKEN"] is None
    assert out["restore"]["AWS_ACCESS_KEY_ID"] != "testing", "a worker that snapshots the fakes restores the fakes — the #3917 defect"


def test_a_worker_never_overwrites_the_controllers_stash():
    """The stash is written with setdefault: a second import in a faked process must not replace it."""
    env = _clean_env()
    env.update({"AWS_ACCESS_KEY_ID": "testing", "LP_REAL_AWS_ENV__AWS_ACCESS_KEY_ID": "AKIA_REAL_FOR_TEST"})
    for k in ("AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_SECURITY_TOKEN", "AWS_PROFILE"):
        env["LP_REAL_AWS_ENV__" + k] = "__unset__"
    assert _probe(env)["restore"]["AWS_ACCESS_KEY_ID"] == "AKIA_REAL_FOR_TEST"


@pytest.mark.integration
def test_integration_marker_restores_real_credentials_in_this_process():
    """Box 2, the live form: under `-n auto` this failed before the fix (the worker restored
    `testing`). Skips where no real credentials exist (CI's FAKE-creds parity run, a clean shell)."""
    stash = os.environ.get("LP_REAL_AWS_ENV__AWS_ACCESS_KEY_ID")
    expect_real = os.environ.get("LP_EXPECT_REAL_CREDS") == "1"  # the reproduction sets this so the pre-fix arm cannot skip
    if not expect_real and stash in (None, "__unset__", "", "testing"):
        pytest.skip("no real AWS credentials in this environment — nothing to restore")
    assert os.environ.get("AWS_ACCESS_KEY_ID") not in (None, "", "testing"), "the integration marker restored the FAKE (the #3917 defect)"
    if stash not in (None, "__unset__", ""):
        assert os.environ.get("AWS_ACCESS_KEY_ID") == stash
