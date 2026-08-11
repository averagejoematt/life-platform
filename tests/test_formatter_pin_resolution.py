"""tests/test_formatter_pin_resolution.py — #2570: the local format gate must EXECUTE
the black/ruff CI pins, and must fail closed rather than substitute another.

WHAT WENT WRONG. CI's format gate installs an exact pair (`.github/workflows/
ci-lint.yml`: `pip install black==… ruff==…`). The pre-commit hook resolved those
tools off bare `PATH`. On 2026-08-11 the PATH black was 25.9.0 against CI's 26.3.1
and the two disagreed on a real file (`lambdas/ai/ai_calls.py`): the hook refused a
commit CI would have passed, and the reformat it demanded produced a tree CI's gate
then rejected. Both directions wrong.

SCOPE — this file is the RESOLUTION half only. Whether the declared pins AGREE with
each other is already CQ-01's job, and tests/test_ci_pin_consistency.py owns it
(#2570 extended that file to derive its declaration surface from the tracked tree
so the Makefile and friends stopped being invisible to it). Adding a second parallel
pin guard is a mistake this repo has already made once; what has never been guarded
is which binary the hook actually runs.

Everything here is hermetic: no network, and no dependency on any particular machine
having .venv-black installed. The declared pin is read from requirements-dev.txt —
one file, deliberately not a tree sweep, so this stays a behaviour suite rather than
a second repo-shape ratchet.
"""

import os
import re
import shutil
import stat
import subprocess
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIB = os.path.join(_REPO, "deploy", "lib", "pinned_formatters.sh")
_INSTALLER = os.path.join(_REPO, "scripts", "install_hooks.sh")
_AGENT_COMMIT = os.path.join(_REPO, "deploy", "agent_commit.sh")
_REQ = os.path.join(_REPO, "requirements-dev.txt")

_TOOLS = ("black", "ruff")


def _declared_pin(tool):
    """The version requirements-dev.txt declares — the single source the resolver reads."""
    with open(_REQ, encoding="utf-8") as f:
        found = re.findall(rf"^{re.escape(tool)}==([0-9][0-9A-Za-z.+\-]*)\s*$", f.read(), re.MULTILINE)
    assert len(found) == 1, f"expected exactly one {tool} pin in requirements-dev.txt, found {found}"
    return found[0]


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _hook_body():
    """The literal pre-commit body scripts/install_hooks.sh writes (quoted heredoc,
    so it is copied byte-for-byte). Same extraction deploy/session_postflight.py
    uses for its hook-freshness check."""
    m = re.search(r"cat > \"\$HOOK_FILE\" << 'EOF'\n(.*?)\nEOF\n", _read(_INSTALLER), re.S)
    assert m, "install_hooks.sh heredoc markers not found — installer format changed, update this test"
    return m.group(1)


# NB: "the resolver and its callers must hardcode no version" lives with the other
# declaration-surface checks in tests/test_ci_pin_consistency.py
# (test_pin_readers_hardcode_no_version) — it is a statement about declarations, and
# that file is where declarations are guarded.


def test_hook_body_resolves_the_pinned_formatters():
    body = _hook_body()
    assert "deploy/lib/pinned_formatters.sh" in body, "the pre-commit hook no longer sources the pinned-formatter resolver (#2570)"
    for tool in _TOOLS:
        assert f"resolve_pinned_formatter {tool}" in body, f"the pre-commit hook does not resolve a pinned {tool} (#2570)"
    # The regression shape: trusting whatever is on PATH, and skipping the gate when
    # it isn't there. Both spellings must stay gone.
    assert "command -v black" not in body, "the pre-commit hook is resolving black off PATH again (#2570)"
    assert "command -v ruff" not in body, "the pre-commit hook is resolving ruff off PATH again (#2570)"
    assert "skipping format gate" not in body, "the pre-commit hook fails OPEN on a missing formatter again (#2570)"


def test_agent_commit_uses_the_same_resolver():
    text = _read(_AGENT_COMMIT)
    assert "deploy/lib/pinned_formatters.sh" in text, "deploy/agent_commit.sh no longer uses the shared resolver (#2570)"
    for tool in _TOOLS:
        assert f"resolve_pinned_formatter {tool}" in text, f"deploy/agent_commit.sh does not resolve a pinned {tool} (#2570)"
    assert "format gate SKIPPED" not in text, "deploy/agent_commit.sh fails OPEN on a missing formatter again (#2570)"


# ── The resolver's own behaviour, proved with shims ───────────────────────────


def _make_shim(dirpath, tool, version):
    """A fake formatter that reports `version` and passes every other invocation."""
    os.makedirs(dirpath, exist_ok=True)
    path = os.path.join(dirpath, tool)
    banner = f"{tool}, {version} (compiled: no)" if tool == "black" else f"{tool} {version}"
    with open(path, "w", encoding="utf-8") as f:
        f.write("#!/bin/sh\n" f'if [ "$1" = "--version" ]; then echo "{banner}"; exit 0; fi\n' "exit 0\n")
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _run_resolver(tool, requirements_text, candidate=None, extra_env=None):
    """Source the real library and ask it to resolve `tool`. Returns CompletedProcess."""
    with tempfile.TemporaryDirectory() as td:
        req = os.path.join(td, "requirements-dev.txt")
        with open(req, "w", encoding="utf-8") as f:
            f.write(requirements_text)
        env = dict(os.environ)
        env["PINNED_FORMATTER_REQUIREMENTS"] = req
        if candidate:
            env[f"PINNED_FORMATTER_BIN_{tool.upper()}"] = candidate
        env.update(extra_env or {})
        script = f'. "{_LIB}"\nresolve_pinned_formatter {tool}\n'
        return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env, cwd=_REPO)


def test_resolver_reports_the_declared_pin():
    """The pin the resolver enforces is the one requirements-dev.txt declares."""
    proc = subprocess.run(
        ["bash", "-c", f'. "{_LIB}"\npinned_formatter_version black\npinned_formatter_version ruff\n'],
        capture_output=True,
        text=True,
        cwd=_REPO,
    )
    assert proc.returncode == 0, proc.stderr
    reported = proc.stdout.split()
    expected = [_declared_pin("black"), _declared_pin("ruff")]
    assert reported == expected, f"resolver reported {reported} but requirements-dev.txt declares {expected}"


def test_resolver_accepts_a_binary_at_the_declared_version():
    """Positive control for the mutation tests below — the shim mechanism works."""
    for tool in _TOOLS:
        with tempfile.TemporaryDirectory() as bindir:
            shim = _make_shim(bindir, tool, "9.9.9")
            proc = _run_resolver(tool, f"{tool}==9.9.9\n", candidate=shim)
            assert proc.returncode == 0, f"{tool}: resolver rejected a binary reporting the declared pin\n{proc.stderr}"
            assert proc.stdout.strip() == shim, f"{tool}: resolver returned {proc.stdout.strip()!r}, expected the shim"


def test_resolver_rejects_a_binary_at_the_wrong_version():
    """MUTATION PROOF (#2570 acceptance): point the gate at a deliberately different
    version and the guard must go red. Run against the REAL declared pin with the
    exact versions that caused the incident — black 25.9.0 vs CI's 26.3.1, and the
    matching ruff skew — so this is the incident, not an analogue of it."""
    skewed = {"black": "25.9.0", "ruff": "0.14.0"}
    for tool in _TOOLS:
        real_pin = _declared_pin(tool)
        assert skewed[tool] != real_pin, f"{tool}: pick a different skew version, {skewed[tool]} is now the real pin"
        with tempfile.TemporaryDirectory() as bindir:
            shim = _make_shim(bindir, tool, skewed[tool])
            # No requirements override: this reads the repo's real pin.
            env = dict(os.environ, **{f"PINNED_FORMATTER_BIN_{tool.upper()}": shim})
            proc = subprocess.run(
                ["bash", "-c", f'. "{_LIB}"\nresolve_pinned_formatter {tool}\n'],
                capture_output=True,
                text=True,
                env=env,
                cwd=_REPO,
            )
            assert proc.returncode != 0, f"{tool}: resolver ACCEPTED {skewed[tool]} while the pin is {real_pin} — the guard is dead"
            assert skewed[tool] in proc.stderr, f"{tool}: the refusal must report what the rejected candidate actually was\n{proc.stderr}"
            assert real_pin in proc.stderr, f"{tool}: the refusal must report the pin it wanted\n{proc.stderr}"
            assert not proc.stdout.strip(), f"{tool}: a refusal must emit no binary path (a caller would run it)"


def test_resolver_never_falls_back_to_path():
    """Fail CLOSED. Even with a perfectly good tool on PATH, an unmatched pin must
    produce a refusal — the silent PATH fallback IS the bug."""
    for tool in _TOOLS:
        proc = _run_resolver(tool, f"{tool}==0.0.0-no-such-release\n")
        assert proc.returncode != 0, f"{tool}: resolver fell back to a non-pinned binary — #2570 regression"
        assert "0.0.0-no-such-release" in proc.stderr
        assert "requirements-dev.txt" in proc.stderr, "the refusal must say where the pin comes from"
        assert "venv-black" in proc.stderr, "the refusal must say how to install the pin"


def test_resolver_refuses_when_no_pin_is_declared():
    for tool in _TOOLS:
        proc = _run_resolver(tool, "# no pins here\n")
        assert proc.returncode != 0, f"{tool}: resolver silently continued with no declared pin"
        assert "no '" in proc.stderr and "==<version>' pin found" in proc.stderr


# ── The real hook body, end to end ────────────────────────────────────────────


def _throwaway_repo(td, pin_version, shim_version):
    """A minimal git repo carrying the real resolver, a requirements file pinning
    `pin_version`, a .venv-black whose shims report `shim_version`, and one staged
    Python file for the gate to look at."""
    subprocess.run(["git", "init", "-q", td], check=True, capture_output=True)
    os.makedirs(os.path.join(td, "deploy", "lib"), exist_ok=True)
    shutil.copy(_LIB, os.path.join(td, "deploy", "lib", "pinned_formatters.sh"))
    with open(os.path.join(td, "requirements-dev.txt"), "w", encoding="utf-8") as f:
        f.write(f"black=={pin_version}\nruff=={pin_version}\n")
    for tool in _TOOLS:
        _make_shim(os.path.join(td, ".venv-black", "bin"), tool, shim_version)
    os.makedirs(os.path.join(td, "scripts"), exist_ok=True)
    staged = os.path.join(td, "scripts", "sample.py")
    with open(staged, "w", encoding="utf-8") as f:
        f.write("x = 1\n")
    subprocess.run(["git", "-C", td, "add", "scripts/sample.py"], check=True, capture_output=True)
    hook = os.path.join(td, "pre-commit")
    with open(hook, "w", encoding="utf-8") as f:
        f.write(_hook_body() + "\n")
    os.chmod(hook, os.stat(hook).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return hook


def test_hook_body_passes_when_the_pinned_formatters_are_present():
    with tempfile.TemporaryDirectory() as td:
        hook = _throwaway_repo(td, pin_version="9.9.9", shim_version="9.9.9")
        proc = subprocess.run(["bash", hook], cwd=td, capture_output=True, text=True)
        assert proc.returncode == 0, f"hook rejected a tree whose formatters match the pin\nSTDOUT:{proc.stdout}\nSTDERR:{proc.stderr}"
        assert "9.9.9 clean on staged Python" in proc.stdout, proc.stdout


def test_hook_body_fails_closed_when_the_pinned_formatter_is_missing():
    """MUTATION PROOF, end to end: same repo, only the installed version changed.
    The hook must refuse rather than quietly use the 1.2.3 it can see."""
    with tempfile.TemporaryDirectory() as td:
        hook = _throwaway_repo(td, pin_version="9.9.9", shim_version="1.2.3")
        proc = subprocess.run(["bash", hook], cwd=td, capture_output=True, text=True)
        assert proc.returncode != 0, f"hook FAILED OPEN on a version-skewed formatter — #2570 regression\nSTDOUT:{proc.stdout}"
        assert "FAILED CLOSED" in proc.stderr, proc.stderr
        assert "9.9.9" in proc.stderr and "1.2.3" in proc.stderr, proc.stderr
