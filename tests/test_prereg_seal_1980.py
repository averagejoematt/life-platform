"""tests/test_prereg_seal_1980.py — #1980: the sealed pre-registration reaches a page.

The sealed, SHA-256-stamped pre-registration artifacts genesis_prereg_stamp.py
publishes to S3 were live (200 OK) but linked from NOWHERE on the site — the
platform's strongest skeptic-facing artifact, reachable only by guessing the URL.
This file pins three things:

  1. `web.site_api_common.prereg_seal_meta()` derives the CURRENT genesis's stamp
     key the same way `deploy/genesis_prereg_stamp.py` builds it (parity test,
     so the two literal formats can't silently drift), reads the stamp verbatim
     (never recomputes the hash), and is honest-empty when no stamp is published.
  2. `/api/calibration` and `/api/predictions` (the two pages the issue names)
     carry that seal in their live response — both the success path AND the
     exception fallback.
  3. THE REGRESSION GUARD (AC3): the current genesis's published prereg objects
     are referenced by at least one qa_manifest page — checked both structurally
     (the page declares the right api_dep) and materially (that api_dep's real
     handler response actually carries the artifact URL + hash). Negative-tested
     both ways below: strip the manifest declaration, and separately, strip the
     handler's payload — each must fail the guard on its own.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

REPO_ROOT = Path(__file__).resolve().parent.parent
_HERE = os.path.dirname(os.path.abspath(__file__))
for p in (str(REPO_ROOT), str(REPO_ROOT / "lambdas"), str(REPO_ROOT / "lambdas" / "web"), str(REPO_ROOT / "deploy"), _HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import qa_manifest  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402
from web import (
    site_api_coach as api,  # noqa: E402
    site_api_common as common,  # noqa: E402
)


def _load(module_name: str, rel_path: str):
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, REPO_ROOT / rel_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


gps = _load("genesis_prereg_stamp", "deploy/genesis_prereg_stamp.py")


def _body(resp):
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])


def _reset_seal_cache(monkeypatch):
    """The seal cache is per-warm-container (module globals) — reset it so tests
    don't leak the previous test's monkeypatched S3 result into the next."""
    monkeypatch.setattr(common, "_prereg_seal_cache", None)
    monkeypatch.setattr(common, "_prereg_seal_attempted", False)


def _real_stamp():
    """The current genesis's stamp, exactly as committed by
    deploy/generated/genesis_preregistration.sha256.json — the same file
    deploy/genesis_prereg_stamp.py publishes verbatim to S3 (#1378)."""
    stamp = gps.load_stamp()
    assert stamp is not None, "no committed prereg stamp — nothing to check against"
    return stamp


# ─────────────────────────────────────────────────────────────────────────────
# 1. prereg_seal_meta(): derived key parity, verbatim read, honest-empty
# ─────────────────────────────────────────────────────────────────────────────


def test_stamp_key_format_matches_the_publisher_exactly():
    """site_api_common's DUPLICATED key builder (deploy/ isn't in the lambda
    bundle, #781) must never drift from genesis_prereg_stamp.stamp_key()."""
    for genesis in ("2026-07-27", "2027-01-04"):
        assert common._prereg_stamp_key(genesis) == gps.stamp_key(genesis)


def test_prereg_seal_meta_reads_the_real_stamp_verbatim(monkeypatch):
    _reset_seal_cache(monkeypatch)
    real = _real_stamp()
    monkeypatch.setattr(
        common, "_load_s3_json", lambda key, name: dict(real) if key == common._prereg_stamp_key(common.EXPERIMENT_START) else {}
    )
    seal = common.prereg_seal_meta()
    assert seal is not None
    assert seal["sha256"] == real["sha256"], "the hash must be READ from the stamp, never recomputed"
    assert seal["artifact_url"] == real["public_artifact_url"]
    assert seal["stamp_url"] == real["public_stamp_url"]
    assert seal["verify"] == real["verify"]
    assert "shasum -a 256" in seal["verify"]


def test_prereg_seal_meta_derives_the_genesis_never_hardcoded(monkeypatch):
    """AC2: the key requested from S3 is built from EXPERIMENT_START, so a
    restart_pipeline.py re-anchor changes the looked-up key with zero code edits."""
    _reset_seal_cache(monkeypatch)
    seen_keys = []

    def _spy(key, name):
        seen_keys.append(key)
        return {}

    monkeypatch.setattr(common, "_load_s3_json", _spy)
    common.prereg_seal_meta()
    assert seen_keys == [f"generated/experiments/prereg/genesis-{common.EXPERIMENT_START}.sha256.json"]
    # And a different genesis (post-reset) would look up a DIFFERENT key —
    # never the same literal path regardless of EXPERIMENT_START.
    monkeypatch.setattr(common, "EXPERIMENT_START", "2099-01-01")
    _reset_seal_cache(monkeypatch)
    monkeypatch.setattr(common, "_load_s3_json", _spy)
    common.prereg_seal_meta()
    assert seen_keys[-1] == "generated/experiments/prereg/genesis-2099-01-01.sha256.json"


def test_prereg_seal_meta_honest_empty_when_unpublished(monkeypatch):
    """A freshly re-anchored cycle whose --with-preregistration hasn't landed
    yet must render nothing, never a guessed/broken link."""
    _reset_seal_cache(monkeypatch)
    monkeypatch.setattr(common, "_load_s3_json", lambda key, name: {})
    assert common.prereg_seal_meta() is None


def test_prereg_seal_meta_rejects_a_genesis_mismatched_stamp(monkeypatch):
    """Defense in depth: even if S3 somehow served a stamp for the WRONG
    genesis under the expected key, the honesty check refuses it."""
    _reset_seal_cache(monkeypatch)
    wrong = dict(_real_stamp(), genesis="1999-01-01")
    monkeypatch.setattr(common, "_load_s3_json", lambda key, name: wrong)
    assert common.prereg_seal_meta() is None


# ─────────────────────────────────────────────────────────────────────────────
# 2. The two named endpoints carry the seal, success path AND fallback
# ─────────────────────────────────────────────────────────────────────────────


def _empty_table_hook(table, **kw):
    return {"Items": []}


def test_handle_calibration_carries_the_seal(monkeypatch):
    _reset_seal_cache(monkeypatch)
    real = _real_stamp()
    monkeypatch.setattr(
        common, "_load_s3_json", lambda key, name: dict(real) if key == common._prereg_stamp_key(common.EXPERIMENT_START) else {}
    )
    monkeypatch.setattr(api, "table", FakeDdbTable(query_hook=_empty_table_hook))
    data = _body(api.handle_calibration({}))
    assert data["prereg_seal"]["sha256"] == real["sha256"]
    assert data["prereg_seal"]["artifact_url"] == real["public_artifact_url"]


def test_handle_predictions_carries_the_seal(monkeypatch):
    _reset_seal_cache(monkeypatch)
    real = _real_stamp()
    monkeypatch.setattr(
        common, "_load_s3_json", lambda key, name: dict(real) if key == common._prereg_stamp_key(common.EXPERIMENT_START) else {}
    )
    monkeypatch.setattr(api, "table", FakeDdbTable(query_hook=_empty_table_hook))
    data = _body(api.handle_predictions({}))
    assert data["prereg_seal"]["sha256"] == real["sha256"]
    assert data["prereg_seal"]["artifact_url"] == real["public_artifact_url"]


def _boom_parallel_fetch(jobs):
    # _parallel_fetch itself swallows per-job exceptions (shaped-empty
    # degradation by design), so to reach handle_calibration/handle_predictions'
    # OWN top-level except we must fail the call they make directly, not a job
    # inside it.
    raise RuntimeError("simulated fetch-layer outage")


def test_handle_calibration_carries_the_seal_on_the_exception_fallback(monkeypatch):
    """The seal is computed before the DDB fetch and passed into BOTH return
    paths — an upstream failure must not blank the seal along with it."""
    _reset_seal_cache(monkeypatch)
    real = _real_stamp()
    monkeypatch.setattr(
        common, "_load_s3_json", lambda key, name: dict(real) if key == common._prereg_stamp_key(common.EXPERIMENT_START) else {}
    )
    monkeypatch.setattr(api, "_parallel_fetch", _boom_parallel_fetch)
    data = _body(api.handle_calibration({}))
    assert data["platform"] == {}  # the fallback shape still holds
    assert data["prereg_seal"]["sha256"] == real["sha256"]


def test_handle_predictions_carries_the_seal_on_the_exception_fallback(monkeypatch):
    _reset_seal_cache(monkeypatch)
    real = _real_stamp()
    monkeypatch.setattr(
        common, "_load_s3_json", lambda key, name: dict(real) if key == common._prereg_stamp_key(common.EXPERIMENT_START) else {}
    )
    monkeypatch.setattr(api, "_parallel_fetch", _boom_parallel_fetch)
    data = _body(api.handle_predictions({}))
    assert data["overall"] == {}
    assert data["prereg_seal"]["sha256"] == real["sha256"]


# ─────────────────────────────────────────────────────────────────────────────
# 3. THE REGRESSION GUARD (AC3) — negative-tested both ways
# ─────────────────────────────────────────────────────────────────────────────

_SEAL_ENDPOINTS = {"/api/calibration", "/api/predictions"}


def _pages_declaring_a_seal_endpoint(manifest):
    """qa_manifest pages whose declared api_deps include an endpoint that
    renders the prereg seal."""
    return [p["path"] for p in manifest if set(p.get("api_deps") or []) & _SEAL_ENDPOINTS]


def assert_current_genesis_prereg_is_referenced(manifest, endpoint_payloads, stamp):
    """The #1980 AC3 regression guard: the current genesis's published
    /experiments/prereg/* objects (the artifact the endpoint links to) must be
    reachable from at least one qa_manifest page — both DECLARED (the page
    lists a seal-carrying api_dep) and MATERIAL (that endpoint's actual
    response embeds the artifact URL + matching hash, not just a stub key).

    `endpoint_payloads` is an iterable of `prereg_seal` dicts (or None/{}) —
    one per seal-carrying endpoint actually queried.
    """
    referencing_pages = _pages_declaring_a_seal_endpoint(manifest)
    if not referencing_pages:
        raise AssertionError(
            "no qa_manifest page declares an api_dep that renders the prereg seal — "
            f"{stamp['public_artifact_url']} would be reachable only by guessing the URL"
        )
    carried = any(
        payload and payload.get("artifact_url") == stamp["public_artifact_url"] and payload.get("sha256") == stamp["sha256"]
        for payload in endpoint_payloads
    )
    if not carried:
        raise AssertionError(
            f"the current genesis's sealed artifact ({stamp['public_artifact_url']}) is declared as a page "
            "dependency but is NOT actually carried by that endpoint's response — reachable only by guessing the URL"
        )
    return referencing_pages


def test_regression_guard_passes_for_the_real_wiring(monkeypatch):
    """The guard is GREEN against the actual manifest + actual handler output —
    proof the fix works, not just that the guard function is well-formed."""
    _reset_seal_cache(monkeypatch)
    real = _real_stamp()
    monkeypatch.setattr(
        common, "_load_s3_json", lambda key, name: dict(real) if key == common._prereg_stamp_key(common.EXPERIMENT_START) else {}
    )
    monkeypatch.setattr(api, "table", FakeDdbTable(query_hook=_empty_table_hook))
    cal = _body(api.handle_calibration({}))
    pred = _body(api.handle_predictions({}))
    referencing = assert_current_genesis_prereg_is_referenced(qa_manifest.MANIFEST, [cal.get("prereg_seal"), pred.get("prereg_seal")], real)
    assert "/method/calibration/" in referencing
    assert "/method/predictions/" in referencing


def test_regression_guard_fails_when_no_page_declares_the_dependency():
    """Negative test #1 — strip BOTH pages' api_deps from a copy of the
    manifest (simulating the pre-fix state the issue describes) and prove the
    guard actually reds, not just that it would in theory."""
    real = _real_stamp()
    stripped = [dict(p, api_deps=[d for d in (p.get("api_deps") or []) if d not in _SEAL_ENDPOINTS]) for p in qa_manifest.MANIFEST]
    payloads = [{"artifact_url": real["public_artifact_url"], "sha256": real["sha256"]}]
    with pytest.raises(AssertionError, match="reachable only by guessing the URL"):
        assert_current_genesis_prereg_is_referenced(stripped, payloads, real)


def test_regression_guard_fails_when_the_endpoint_omits_the_seal():
    """Negative test #2 — the manifest still declares the dependency, but the
    endpoint's actual response never carries the seal (the pre-fix code path:
    /api/calibration and /api/predictions served with no prereg_seal key)."""
    real = _real_stamp()
    with pytest.raises(AssertionError, match="NOT actually carried"):
        assert_current_genesis_prereg_is_referenced(qa_manifest.MANIFEST, [None, {}], real)


def test_regression_guard_fails_on_a_stale_or_wrong_hash():
    """Negative test #3 — an endpoint carries SOME seal, but it doesn't match
    the current genesis's real stamp (a stale cache, or a different cycle's
    artifact linked by mistake) — the guard must not accept a look-alike."""
    real = _real_stamp()
    stale_payload = {"artifact_url": real["public_artifact_url"], "sha256": "0" * 64}
    with pytest.raises(AssertionError, match="NOT actually carried"):
        assert_current_genesis_prereg_is_referenced(qa_manifest.MANIFEST, [stale_payload], real)
