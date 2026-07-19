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


# ── Hook freshness (#1326) ────────────────────────────────────────────────────
# Exists because the INSTALLED .git/hooks/pre-commit is a local, untracked file
# — `git pull` never refreshes it. #818 deleted scripts/update_architecture_header.sh
# and retired its indirection, but an already-installed hook kept calling the
# deleted script for weeks, masked by a `[[ -f ]]` fail-open guard: the doc-sync
# half of the hook went silently dead. This guard hashes the heredoc body
# scripts/install_hooks.sh writes and compares it to what's actually installed.


def _fake_installer(tmp_path, body):
    installer_dir = tmp_path / "scripts"
    installer_dir.mkdir()
    installer_path = installer_dir / "install_hooks.sh"
    # Mirrors the real installer's shape closely enough for the regex: a quoted
    # heredoc (`<< 'EOF'`) assigned to a file named via $HOOK_FILE.
    installer_path.write_text(
        "#!/usr/bin/env bash\n"
        'HOOK_FILE="$HOOK_DIR/pre-commit"\n'
        "cat > \"$HOOK_FILE\" << 'EOF'\n"
        f"{body}\nEOF\n"
        'chmod +x "$HOOK_FILE"\n'
    )
    return installer_path


def test_fresh_hook_matches_installer_returns_none(tmp_path):
    body = "#!/usr/bin/env bash\necho hello\nexit 0"
    _fake_installer(tmp_path, body)
    hook_path = tmp_path / "installed-hook"
    hook_path.write_text(body + "\n")  # heredocs terminate with a trailing newline
    assert sp.check_hook_freshness(root=str(tmp_path), hook_path=str(hook_path)) is None


def test_stale_hook_is_flagged(tmp_path):
    _fake_installer(tmp_path, "#!/usr/bin/env bash\necho NEW BEHAVIOR\nexit 0")
    hook_path = tmp_path / "installed-hook"
    hook_path.write_text("#!/usr/bin/env bash\necho OLD BEHAVIOR — calls a since-deleted script\nexit 0\n")
    problem = sp.check_hook_freshness(root=str(tmp_path), hook_path=str(hook_path))
    assert problem is not None
    assert "STALE" in problem


def test_missing_hook_is_flagged_not_installed(tmp_path):
    _fake_installer(tmp_path, "#!/usr/bin/env bash\necho hello\nexit 0")
    hook_path = tmp_path / "does-not-exist"
    problem = sp.check_hook_freshness(root=str(tmp_path), hook_path=str(hook_path))
    assert problem is not None
    assert "NOT installed" in problem


def test_missing_installer_is_out_of_scope_returns_none(tmp_path):
    # No scripts/install_hooks.sh under this root at all — nothing to compare
    # against, so this isn't this check's problem to report.
    hook_path = tmp_path / "installed-hook"
    hook_path.write_text("whatever\n")
    assert sp.check_hook_freshness(root=str(tmp_path), hook_path=str(hook_path)) is None


def test_real_installer_heredoc_is_extractable_and_matches_a_real_install(tmp_path):
    """Pins the extraction regex against the REAL scripts/install_hooks.sh (not
    just synthetic fixtures) and proves the stale-vs-fresh distinction end to end:
    a throwaway pre-#818-shaped hook is flagged STALE, then writing the body
    install_hooks.sh's heredoc actually produces (what a real reinstall writes,
    byte for byte — the heredoc is quoted, so bash copies it verbatim with no
    interpolation) makes the same check go green. This is the #1326 AC4
    regression guard: fails on stale, passes after a fresh install."""
    repo_root = os.path.join(os.path.dirname(__file__), "..")
    installer_path = os.path.join(repo_root, "scripts", "install_hooks.sh")

    with open(installer_path) as f:
        body = sp._extract_installer_heredoc(f.read())
    assert body.startswith("#!/usr/bin/env bash")
    assert body.endswith("\n")
    assert "update_architecture_header.sh" not in body  # #818: retired, must not resurrect

    hook_path = tmp_path / "pre-commit"

    # Simulate the pre-#818 stale hook shape that #1326 found still installed.
    hook_path.write_text(
        "#!/usr/bin/env bash\n"
        "# pre-commit hook — format gate + auto-update ARCHITECTURE.md header counts\n"
        'if [[ -f "$PROJ_ROOT/scripts/update_architecture_header.sh" ]]; then\n'
        '  bash "$PROJ_ROOT/scripts/update_architecture_header.sh"\n'
        "fi\n"
        "exit 0\n"
    )
    stale = sp.check_hook_freshness(root=repo_root, hook_path=str(hook_path))
    assert stale is not None and "STALE" in stale

    # "Reinstall": write the exact bytes install_hooks.sh's heredoc produces —
    # never touches the real .git/hooks/pre-commit belonging to this checkout.
    hook_path.write_text(body)
    fresh = sp.check_hook_freshness(root=repo_root, hook_path=str(hook_path))
    assert fresh is None
