"""The SBOM step's own shell, executed against a broken install (3848).

This is a **local reproduction of the CI step's shell, not the CI run**. `ci-lint.yml` is
`workflow_call`-only, so it cannot be exercised from a branch; what this harness can do
honestly is take the step's `run:` text *out of the workflow file itself* (never a copy —
a copy would drift and pass forever) and execute it under `bash` with a stubbed `curl`,
`sleep` and `syft` on PATH.

The must-fail control the issue asks for is the parametrised `test_broken_install_*` set:
with the installer download broken exactly the way 2026-09-16 broke it
(`curl: (35) Recv failure: Connection reset by peer`), the step must exit non-zero and name
the missing SBOM — where the pre-fix step exited 0 with `continue-on-error` and reported
success. `test_prefix_shape_would_have_passed_silently` runs the OLD shell under the same
stub and shows it is the shell, not the stub, that changed the verdict.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parent.parent
CI_LINT = REPO / ".github" / "workflows" / "ci-lint.yml"

# The step exactly as it stood before 3848 — `curl … | sh` with no pipefail and no
# assertions. Kept only as the control arm; nothing in the repo runs this shape.
PRE_FIX_SHELL = """\
curl -sSfL "https://raw.githubusercontent.com/anchore/syft/${SYFT_VERSION}/install.sh" \\
  | sh -s -- -b "$RUNNER_TEMP/bin" "$SYFT_VERSION"
"$RUNNER_TEMP/bin/syft" version
"$RUNNER_TEMP/bin/syft" scan dir:. -q \\
  -o "spdx-json=sbom.spdx.json" \\
  -o "cyclonedx-json=sbom.cyclonedx.json"
echo "SBOM generated: sbom.spdx.json (SPDX) + sbom.cyclonedx.json (CycloneDX)"
"""


def sbom_step() -> dict:
    doc = yaml.safe_load(CI_LINT.read_text())
    steps = doc["jobs"]["lint"]["steps"]
    matches = [s for s in steps if "Generate SBOM" in (s.get("name") or "")]
    assert len(matches) == 1, f"expected exactly one Generate SBOM step, found {len(matches)}"
    return matches[0]


# ── stubs ────────────────────────────────────────────────────────────────────────────
# Each stub is a tiny shell script placed on PATH ahead of the real tool.

_STUB_SLEEP = "#!/bin/sh\nexit 0\n"

# curl that always fails the way the runner failed on 2026-09-16.
_STUB_CURL_RESET = """#!/bin/sh
echo "curl: (35) Recv failure: Connection reset by peer" >&2
exit 35
"""

# curl that succeeds but writes a ZERO-BYTE file — a truncated/aborted transfer.
_STUB_CURL_EMPTY = """#!/bin/sh
out=""
while [ $# -gt 0 ]; do
  case "$1" in -o) out="$2"; shift 2 ;; *) shift ;; esac
done
: > "$out"
exit 0
"""


def _stub_curl_writing(installer_body: str) -> str:
    """curl that succeeds and delivers `installer_body` as the install.sh."""
    return (
        "#!/bin/sh\n"
        'out=""\n'
        "while [ $# -gt 0 ]; do\n"
        '  case "$1" in -o) out="$2"; shift 2 ;; *) shift ;; esac\n'
        "done\n"
        "cat > \"$out\" <<'INSTALLER_EOF'\n" + installer_body + "\nINSTALLER_EOF\n"
        "exit 0\n"
    )


# Upstream's real failure shape: install.sh does not `set -e`, and its install_asset()
# `return`s 0 on an empty asset path — so it can exit 0 having installed nothing.
_INSTALLER_NOOP = '#!/bin/sh\necho "[info] checking github for release tag"\nexit 0\n'


def _installer_installing(syft_body: str) -> str:
    return (
        "#!/bin/sh\n"
        'dir="./bin"\n'
        "while [ $# -gt 0 ]; do\n"
        '  case "$1" in -b) dir="$2"; shift 2 ;; *) shift ;; esac\n'
        "done\n"
        'mkdir -p "$dir"\n'
        "cat > \"$dir/syft\" <<'SYFT_EOF'\n" + syft_body + "\nSYFT_EOF\n"
        'chmod +x "$dir/syft"\n'
        "exit 0\n"
    )


_SYFT_GOOD = """#!/bin/sh
case "$1" in
  version) echo "syft 1.49.0 (stub)" ; exit 0 ;;
esac
# emulate `scan dir:. -o spdx-json=FILE -o cyclonedx-json=FILE`
while [ $# -gt 0 ]; do
  case "$1" in
    -o) echo '{"stub":"sbom"}' > "${2#*=}" ; shift 2 ;;
    *) shift ;;
  esac
done
exit 0
"""

# A syft that reports success and writes nothing — the third assertion's target.
_SYFT_SILENT = """#!/bin/sh
case "$1" in version) echo "syft 1.49.0 (stub)" ; exit 0 ;; esac
exit 0
"""


def _run_shell(script: str, tmp_path: Path, stubs: dict[str, str]) -> subprocess.CompletedProcess:
    bindir = tmp_path / "stubbin"
    bindir.mkdir(parents=True, exist_ok=True)
    for name, body in stubs.items():
        p = bindir / name
        p.write_text(body)
        p.chmod(0o755)

    workdir = tmp_path / "work"
    workdir.mkdir(exist_ok=True)
    runner_temp = tmp_path / "runner_temp"
    runner_temp.mkdir(exist_ok=True)

    env = dict(os.environ)
    env["PATH"] = f"{bindir}:{env['PATH']}"
    env["RUNNER_TEMP"] = str(runner_temp)
    env["SYFT_VERSION"] = "v1.49.0"
    env["SYFT_CHECK_FOR_APP_UPDATE"] = "false"

    script_path = tmp_path / "step.sh"
    script_path.write_text(script)
    # GitHub runs `run:` blocks as `bash -e {0}` — NOT pipefail. Reproduced exactly.
    return subprocess.run(
        ["bash", "-e", str(script_path)],
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


# ── the guard ────────────────────────────────────────────────────────────────────────


def test_step_has_no_continue_on_error() -> None:
    assert "continue-on-error" not in sbom_step(), (
        "the SBOM step is swallowed again — every assertion below becomes decorative the "
        "moment a failure is converted to `success` (3848)"
    )


def test_step_shell_sets_pipefail() -> None:
    """The 2026-09-16 root shape: without pipefail, `curl | sh` reports sh's exit 0."""
    run = sbom_step()["run"]
    assert "set -euo pipefail" in run, "the step's shell must set pipefail (3848)"
    assert "| sh -s" not in run, "the `curl | sh` pipeline is the founding defect — do not reintroduce it"


@pytest.mark.parametrize(
    "label,curl_stub,expect_fragment",
    [
        ("connection-reset", _STUB_CURL_RESET, "syft installer unfetchable"),
        ("empty-download", _STUB_CURL_EMPTY, "syft installer unfetchable"),
    ],
)
def test_broken_install_fails_loudly(tmp_path: Path, label: str, curl_stub: str, expect_fragment: str) -> None:
    """MUST-FAIL CONTROL: installer download broken -> non-zero exit and a named ::error::."""
    proc = _run_shell(
        sbom_step()["run"],
        tmp_path / label,
        {"curl": curl_stub, "sleep": _STUB_SLEEP},
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode != 0, f"[{label}] step exited 0 with a broken install:\n{out}"
    assert expect_fragment in out, f"[{label}] no named error in output:\n{out}"
    assert "SBOM generated:" not in proc.stdout, f"[{label}] the success line printed anyway:\n{out}"


def test_installer_exiting_zero_without_installing_fails(tmp_path: Path) -> None:
    """Upstream install.sh can exit 0 having installed nothing — exit 0 is not evidence."""
    proc = _run_shell(
        sbom_step()["run"],
        tmp_path,
        {"curl": _stub_curl_writing(_INSTALLER_NOOP), "sleep": _STUB_SLEEP},
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode != 0, f"step exited 0 though no syft binary was installed:\n{out}"
    assert "syft not installed" in out, out
    assert "SBOM generated:" not in proc.stdout, out


def test_scan_producing_no_output_fails(tmp_path: Path) -> None:
    """syft present and exiting 0, but neither SBOM file written."""
    proc = _run_shell(
        sbom_step()["run"],
        tmp_path,
        {
            "curl": _stub_curl_writing(_installer_installing(_SYFT_SILENT)),
            "sleep": _STUB_SLEEP,
        },
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode != 0, f"step exited 0 with no SBOM files on disk:\n{out}"
    assert "SBOM: output missing" in out, out


def test_healthy_install_still_passes(tmp_path: Path) -> None:
    """The guard must not be a permanent red: a working install reaches the success line."""
    workroot = tmp_path / "ok"
    proc = _run_shell(
        sbom_step()["run"],
        workroot,
        {
            "curl": _stub_curl_writing(_installer_installing(_SYFT_GOOD)),
            "sleep": _STUB_SLEEP,
        },
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"healthy path failed:\n{out}"
    assert "SBOM generated:" in proc.stdout, out
    for name in ("sbom.spdx.json", "sbom.cyclonedx.json"):
        f = workroot / "work" / name
        assert f.exists() and f.stat().st_size > 0, f"{name} not written by the healthy path"


def test_prefix_shape_would_have_passed_silently(tmp_path: Path) -> None:
    """The control's control: the PRE-fix shell, same stub, is the one that goes quiet.

    This is what makes the four asserts above evidence rather than decoration — under an
    identical broken-curl stub the old `curl | sh` shell does NOT report the installer
    failure at all. It still exits non-zero at the `syft version` line — in CI (bash 5) that
    is the exit 127 the 2026-09-16 log recorded and `continue-on-error: true` converted to
    `success`; under macOS's bash 3.2 the same missing-command condition exits 1. The exit
    VALUE is shell-version dependent, so only its non-zero-ness is asserted here.
    """
    proc = _run_shell(PRE_FIX_SHELL, tmp_path, {"curl": _STUB_CURL_RESET, "sleep": _STUB_SLEEP})
    out = proc.stdout + proc.stderr
    assert "syft installer unfetchable" not in out, "the pre-fix shell cannot name this failure"
    assert "No such file or directory" in out, f"expected the 2026-09-16 symptom, got:\n{out}"
    assert proc.returncode != 0, f"expected a non-zero exit (the one CI swallowed), got {proc.returncode}"


def test_bash_available() -> None:
    assert shutil.which("bash"), "this harness needs bash — GitHub runs `run:` blocks under it"
