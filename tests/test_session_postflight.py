"""tests/test_session_postflight.py — the asset-completeness guard.

This guard exists because a cdk deploy shipped a Lambda zip MISSING every root
lambdas/*.py module (the coherence-sentinel ran "green" off a stale artifact while
actually throwing ImportModuleError). CDK skips re-uploading an asset whose hash
already exists in S3, so a corrupt zip poisons every lambda on that hash. The check
downloads each canary's deployed zip and asserts its imported root module(s) are
present. These tests pin that logic against in-memory zips.
"""

import io
import os
import sys
import urllib.request
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "deploy"))

import session_postflight as sp  # noqa: E402


def _zip_bytes(names):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in names:
            z.writestr(n, "x")
    return buf.getvalue()


class _Body:
    def __init__(self, data):
        self._d = data

    def read(self):
        return self._d

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _wire(monkeypatch, zips):
    class _CL:
        def get_function(self, FunctionName):
            return {"Code": {"Location": "http://assets/" + FunctionName}}

    monkeypatch.setattr(sp, "_lambda", lambda: _CL())
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=0: _Body(zips[url.rsplit("/", 1)[1]]))


def test_flags_the_lambda_whose_zip_is_missing_a_root_module(monkeypatch):
    # sentinel zip is complete; analyzer zip is the broken 2-entry shape (no root modules).
    _wire(
        monkeypatch,
        {
            "life-platform-coherence-sentinel": _zip_bytes(
                ["operational/coherence_sentinel_lambda.py", "coherence_invariants.py", "canonical_facts.py"]
            ),
            "ai-expert-analyzer": _zip_bytes(["intelligence/ai_expert_analyzer_lambda.py"]),  # missing canonical_facts.py
        },
    )
    problems = dict(sp.check_asset_completeness())
    assert "ai-expert-analyzer" in problems and "canonical_facts.py" in problems["ai-expert-analyzer"]
    assert "life-platform-coherence-sentinel" not in problems


def test_all_complete_returns_empty(monkeypatch):
    _wire(
        monkeypatch,
        {
            "life-platform-coherence-sentinel": _zip_bytes(
                ["operational/coherence_sentinel_lambda.py", "coherence_invariants.py", "canonical_facts.py"]
            ),
            "ai-expert-analyzer": _zip_bytes(["intelligence/ai_expert_analyzer_lambda.py", "canonical_facts.py"]),
        },
    )
    assert sp.check_asset_completeness() == []


def test_download_error_is_fail_soft_not_a_false_alarm(monkeypatch):
    class _CL:
        def get_function(self, FunctionName):
            raise RuntimeError("transient AWS error")

    monkeypatch.setattr(sp, "_lambda", lambda: _CL())
    # A describe/download failure must skip the canary, never report it as missing.
    assert sp.check_asset_completeness() == []
