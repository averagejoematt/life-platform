"""#1336 — pip_audit_lambda SCA layer-manifest coverage guard.

Proves the RED-on-missing-manifest behavior: every binary dependency layer referenced by a
`*_LAYER_ARN` in cdk/stacks/constants.py must have a pinned manifest under
lambdas/requirements/ that pip-audit can scan. The guard fails (returns the uncovered layer
names) on the pre-#1336 tree and passes once pillow.txt/lameenc.txt exist.
"""

import os
import pathlib
import sys

# pip_audit_lambda reads required env at import time — provide harmless test values first.
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "sender@example.com")

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO / "lambdas" / "operational"))

import pip_audit_lambda as pa  # noqa: E402

# Mirrors the real constants.py ARN literals, plus a cf-auth FUNCTION ARN that must NOT be
# mistaken for a layer.
CONSTANTS_STUB = """
PILLOW_LAYER_ARN = f"arn:aws:lambda:{REGION}:{ACCT}:layer:pillow-layer:{PILLOW_LAYER_VERSION}"
GARTH_LAYER_ARN = f"arn:aws:lambda:{REGION}:{ACCT}:layer:garth-layer:{GARTH_LAYER_VERSION}"
LAMEENC_LAYER_ARN = f"arn:aws:lambda:{REGION}:{ACCT}:layer:lameenc-layer:{LAMEENC_LAYER_VERSION}"
CF_AUTH_VERSION_ARN = f"arn:aws:lambda:us-east-1:{ACCT}:function:life-platform-cf-auth:2"
"""


def _write(d: pathlib.Path, name: str, body: str = "pkg==1.0\n") -> None:
    (d / name).write_text(body)


def test_layer_names_parsed_from_constants():
    names = pa._layer_names_from_constants(CONSTANTS_STUB)
    assert names == ["garth", "lameenc", "pillow"]
    # A cf-auth FUNCTION ARN is not a layer and must not be picked up.
    assert all("cf" not in n for n in names)


def test_red_when_manifest_missing(tmp_path):
    constants = tmp_path / "constants.py"
    constants.write_text(CONSTANTS_STUB)
    reqs = tmp_path / "requirements"
    reqs.mkdir()
    # Only garmin.txt present (covers garth); pillow + lameenc MISSING → RED.
    _write(reqs, "garmin.txt", "garth==0.4.47\n")
    missing = pa.check_layer_manifest_coverage(constants_path=constants, requirements_dir=reqs)
    assert missing == ["lameenc", "pillow"]


def test_green_when_all_manifests_present(tmp_path):
    constants = tmp_path / "constants.py"
    constants.write_text(CONSTANTS_STUB)
    reqs = tmp_path / "requirements"
    reqs.mkdir()
    _write(reqs, "garmin.txt", "garth==0.4.47\n")
    _write(reqs, "pillow.txt", "Pillow==11.2.1\n")
    _write(reqs, "lameenc.txt", "lameenc==1.8.4\n")
    assert pa.check_layer_manifest_coverage(constants_path=constants, requirements_dir=reqs) == []


def test_garth_covered_by_garmin_alias(tmp_path):
    constants = tmp_path / "constants.py"
    constants.write_text('GARTH_LAYER_ARN = "arn:aws:lambda:x:y:layer:garth-layer:2"\n')
    reqs = tmp_path / "requirements"
    reqs.mkdir()
    # No garth.txt, but garmin.txt pins garth — the alias covers it.
    _write(reqs, "garmin.txt", "garth==0.4.47\n")
    assert pa.check_layer_manifest_coverage(constants_path=constants, requirements_dir=reqs) == []


def test_red_on_real_constants_without_new_manifests(tmp_path):
    """Guard fails on TODAY's real constants.py when the pre-#1336 tree lacks the manifests."""
    real_constants = _REPO / "cdk" / "stacks" / "constants.py"
    reqs = tmp_path / "requirements"
    reqs.mkdir()
    _write(reqs, "garmin.txt", "garth==0.4.47\n")  # pre-#1336 state: no pillow/lameenc
    missing = pa.check_layer_manifest_coverage(constants_path=real_constants, requirements_dir=reqs)
    assert missing == ["lameenc", "pillow"]


def test_real_repo_tree_is_fully_covered():
    """After #1336 adds pillow.txt + lameenc.txt, the live tree must be fully covered."""
    missing = pa.check_layer_manifest_coverage()  # defaults → real constants.py + requirements/
    assert missing == [], f"uncovered deployed layers on the live tree: {missing}"


def test_missing_constants_is_non_fatal(tmp_path):
    """If constants.py can't be read (not bundled into the Lambda), degrade to [] + a log."""
    assert pa.check_layer_manifest_coverage(constants_path=tmp_path / "nope.py", requirements_dir=tmp_path) == []


def test_alerts_check_skips_without_token(monkeypatch):
    monkeypatch.delenv("GH_ALERTS_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    res = pa.check_alerts_enabled()
    assert res["status"] == "skipped"
    assert "GH_ALERTS_TOKEN" in res["reason"]
