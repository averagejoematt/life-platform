"""prod_write_guard — the Python twin of deploy/lib/prod_write_guard.sh (#6116).

A test run cannot reach a real AWS write through a Python deploy entry point. Every writing script under deploy/
calls `install_prod_write_guard()` as the first statement of its `if __name__ == "__main__":` block
(tests/test_prod_write_guard_6116.py derives the set from the text and fails on one that does not).

Outside a test runner `install_prod_write_guard()` does NOTHING (returns None): a CI deploy job and an attended run
are unchanged. Under one — PYTEST_CURRENT_TEST, the session marker LP_TEST_SESSION (tests/conftest.py) or a pytest
ancestor process, exactly the shell guard's three signals — it:
  * refuses every botocore operation that is not a read (Get*/List*/Describe*/Head*/Scan/Query/BatchGet*/...) with
    exit 97 and one line on stderr, BEFORE the request is built, unless the client's endpoint is a loopback URL
    named in LP_TEST_AWS_IS_STUB (a local stub server);
  * puts deploy/lib/prod_write_guard_bin/ first on PATH, so `aws` / `npx cdk deploy` run through subprocess meet the
    shell guard's rule (refused unless the resolved executable is named in LP_TEST_AWS_IS_STUB).
Reads stay allowed so a dry-run path behaves as it did (the session's credentials are fakes in any case).

Inside the pytest process itself (a test importing a deploy module and calling main()) it does nothing: that process
runs under tests/conftest.py's hermetic credentials, and patching botocore there would break moto and Stubber.
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from urllib.parse import urlparse

EXIT_CODE = 97
SESSION_ENV = "LP_TEST_SESSION"
STUB_ENV = "LP_TEST_AWS_IS_STUB"
SHIM_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prod_write_guard_bin")

_READ_OPERATION = re.compile(r"^(Get|List|Describe|Head|Scan|Query|BatchGet|Select|Lookup|Search|Filter|Simulate|Estimate|Validate)")
_PYTEST_MODULE = re.compile(r"(^|\s)-m\s*(pytest|py\.test)(\s|$)")
_PYTEST_SCRIPT = re.compile(r"(^|\s)\S*/(pytest|py\.test)(\s|$)")


def is_pytest_command(args: str) -> bool:
    """Is this command line (`ps -o args=`) a pytest process? The program must BE pytest or python (as the shell twin)."""
    first = os.path.basename(args.split(" ", 1)[0]) if args else ""
    if first in ("pytest", "py.test"):
        return True
    if not first.lower().startswith("python"):
        return False
    return bool(_PYTEST_MODULE.search(args) or _PYTEST_SCRIPT.search(" " + args + " "))


def _ancestor_pytest(pid: int) -> str | None:
    for _ in range(64):
        if pid <= 1:
            return None
        try:
            line = subprocess.run(["ps", "-o", "ppid=", "-o", "args=", "-p", str(pid)], capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        line = line.strip()
        if not line:
            return None
        ppid, _, args = line.partition(" ")
        if is_pytest_command(args.strip()):
            return f"ancestor pid {pid} is pytest"
        try:
            pid = int(ppid)
        except ValueError:
            return None
    return None


def runner_context_reason(environ=None, ppid: int | None = None) -> str | None:
    """Why this process counts as running under a test runner, or None when it does not."""
    env = os.environ if environ is None else environ
    if env.get("PYTEST_CURRENT_TEST"):
        return "PYTEST_CURRENT_TEST is set"
    if env.get(SESSION_ENV):
        return f"{SESSION_ENV} is set"
    return _ancestor_pytest(os.getppid() if ppid is None else ppid)


def is_read_operation(operation_name: str) -> bool:
    return bool(_READ_OPERATION.match(operation_name or ""))


def declared_stub_endpoint(endpoint_url: str | None, environ=None) -> bool:
    """True when the client talks to a loopback endpoint the test named in LP_TEST_AWS_IS_STUB."""
    env = os.environ if environ is None else environ
    if not endpoint_url:
        return False
    host = urlparse(endpoint_url).hostname or ""
    if host not in ("127.0.0.1", "localhost", "::1"):
        return False
    declared = {entry.strip().rstrip("/") for entry in env.get(STUB_ENV, "").split(",") if entry.strip()}
    return endpoint_url.rstrip("/") in declared


def refuse(what: str, reason: str) -> None:
    """One line on the process's real stderr, then exit EXIT_CODE at once (os._exit: no `except`/`finally` in the
    caller can swallow it and carry on to the next write)."""
    sys.stdout.flush()
    stream = sys.__stderr__ or sys.stderr
    stream.write(
        f"prod_write_guard: REFUSED `{what}` — running under a test runner ({reason}) and the endpoint is not a declared "
        f"stub, so real AWS is unreachable (a test with a local stub endpoint sets {STUB_ENV}=<endpoint url>) — #6116\n"
    )
    stream.flush()
    os._exit(EXIT_CODE)


def _guard_client_class(client_cls, reason: str) -> None:
    original = client_cls._make_api_call
    if getattr(original, "_lp_prod_write_guard", False):
        return

    def guarded(self, operation_name, api_params):
        if not is_read_operation(operation_name) and not declared_stub_endpoint(getattr(self.meta, "endpoint_url", None)):
            refuse(f"{self.meta.service_model.service_name} {operation_name}", reason)
        return original(self, operation_name, api_params)

    setattr(guarded, "_lp_prod_write_guard", True)
    client_cls._make_api_call = guarded


class _GuardBotocoreOnImport:
    """A one-shot meta-path finder: when the script first imports botocore.client, guard its BaseClient. The twin itself
    never imports botocore — it acts only if (and when) the script loads it, so a script that imports boto3 lazily
    inside main() is covered as well as one that imported it at module level."""

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def find_spec(self, name, path=None, target=None):
        if name != "botocore.client":
            return None
        sys.meta_path.remove(self)
        spec = importlib.util.find_spec(name)
        if spec is None or spec.loader is None:
            return spec
        loader, reason = spec.loader, self.reason
        original_exec = loader.exec_module

        def exec_module(module):
            original_exec(module)
            _guard_client_class(module.BaseClient, reason)

        loader.exec_module = exec_module
        return spec


def _guard_botocore(reason: str) -> None:
    loaded = sys.modules.get("botocore.client")
    if loaded is not None:
        _guard_client_class(loaded.BaseClient, reason)
    elif not any(isinstance(f, _GuardBotocoreOnImport) for f in sys.meta_path):
        sys.meta_path.insert(0, _GuardBotocoreOnImport(reason))


def install_prod_write_guard(environ=None) -> str | None:
    """Arm the guard when this process runs under a test runner; return the reason, or None (nothing changed)."""
    if "_pytest" in sys.modules:
        return None
    env = os.environ if environ is None else environ
    reason = runner_context_reason(env)
    if reason is None:
        return None
    env.setdefault(SESSION_ENV, "1")
    if SHIM_DIR not in env.get("PATH", "").split(os.pathsep):
        env["PATH"] = SHIM_DIR + os.pathsep + env.get("PATH", "")
    _guard_botocore(reason)
    return reason
