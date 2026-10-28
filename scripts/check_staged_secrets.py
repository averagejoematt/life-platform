#!/usr/bin/env python3
"""scripts/check_staged_secrets.py — the secret scan over what the wrap is about to commit (#5405).

THE DEFECT. Session CH's wrap commit 4907f0a5a went straight to `main` (a wrap is the one commit
class with no PR) and turned main's CI/CD red for ~71 min: the `lint` job's gitleaks step reported
`generic-api-key` in `handovers/HANDOVER_LATEST.md`. The gotcha line quoted a Python assignment of a
Secrets-Manager field-name constant, as the example of what trips gitleaks. Nothing leaked; it was a
false positive on documentation. But `/wrap` Phase 3 (`wrap_gates.py --verify`) ran every Docs-CI
gate and NOT the secret scan, gitleaks is not installed on the laptop, and the pre-commit hook does
not run it — so the commit reached the scanner only after it landed.

WHAT THIS DOES. Runs gitleaks, with the repo's `.gitleaks.toml`, over the diff the wrap is about to
commit. Phase 3 runs BEFORE `git add` (SKILL.md step (f) stages), so a literal `git diff --staged`
would be empty at the moment this gate runs. Instead the gate builds a THROWAWAY index — a copy of
the real one (so anything already staged rides along), plus the wrap's own stage list (`WRAP_PATHS`) — and points gitleaks at
it through `GIT_INDEX_FILE`. The real index is never touched. Run again after `git add` and the
throwaway index and the real one coincide, so it is also the staged-diff scan the issue asks for.

THE VERSION. Read from `.github/workflows/secret-scan.yml` (`GITLEAKS_VERSION`), the same pin CI
installs by checksum. A local binary of another version is scanned with anyway and the drift is
printed — default rules differ between releases, so a drift note is a caveat on a PASS, not a block.

THE BINARY IS NEVER FETCHED HERE. It is found, in order, at `$GITLEAKS_BIN`, on `PATH`, at
`/opt/homebrew/bin/gitleaks`, at `/usr/local/bin/gitleaks`. A gate that downloads and executes a
binary from the network inside `/wrap` would be the supply-chain hole the CI pin exists to close.

ABSENT BINARY => `UNVERIFIED`, exit 0 — by default. This matches every other fail-open leg in the
battery (`check_ci_warnings`, `check_alarm_census`, `closure_sweep`: a gate that cannot reach what it
judges prints UNVERIFIED and exits 0, and the session says so in the handover). The alternative,
blocking, would make every wrap on a machine without gitleaks impossible, which today is every
machine the wrap runs on — a gate that cannot be satisfied gets bypassed, and a bypassed gate is
worse than a loud one. It is NOT silent: the per-gate section prints the install line, and
`wrap_gates.py` repeats it in a closing `UNVERIFIED LEGS` line. `--require` (or
`WRAP_REQUIRE_GITLEAKS=1`) turns the absent binary into a FAIL for the session that has installed it
and wants the wrap to refuse without it.

EXIT. 0 clean / nothing to scan / UNVERIFIED; 1 a finding, a scanner error, or `--require` with no
binary. Findings are printed as `rule file:line` — never the matched text.

TESTS. `run_gitleaks` is the one seam that executes the binary; `scan()` takes a `runner` so
`tests/test_staged_secret_scan_5405.py` runs the whole leg without gitleaks installed.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / ".gitleaks.toml"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "secret-scan.yml"

INSTALL_HINT = "brew install gitleaks   (CI pins v{version}; or set GITLEAKS_BIN=/path/to/gitleaks)"
BIN_CANDIDATES = ("/opt/homebrew/bin/gitleaks", "/usr/local/bin/gitleaks")

# The paths SKILL.md step (f) stages — an edit or a NEW file under one of these is part of the wrap
# commit even before `git add` has run. Anything ALREADY staged rides along (the index copy). Other
# unstaged edits are NOT scanned: they are not in the commit, and a finding there would block the
# wrap on work it is not shipping.
WRAP_PATHS = ("handovers/HANDOVER_LATEST.md", "CLAUDE.md", "docs", "site/story/build/beats.json")


def pinned_version(workflow: Path = CI_WORKFLOW) -> str:
    """The gitleaks version CI installs — read from the workflow, never restated here."""
    m = re.search(r'^\s*GITLEAKS_VERSION:\s*"?([0-9][0-9.]*)"?\s*$', workflow.read_text(encoding="utf-8"), re.M)
    if not m:
        raise RuntimeError(f"{workflow} no longer declares GITLEAKS_VERSION — the pin this gate follows is gone")
    return m.group(1)


def find_gitleaks(env=None, which=None, isfile=os.path.isfile):
    """(path|None, why-not). `GITLEAKS_BIN` wins; a value pointing at nothing is reported, not skipped.

    `which` resolves at CALL time: a `shutil.which` default argument is bound when the def runs, so a
    test patching `shutil.which` never reached it and the absent-binary tests found a real gitleaks
    on any machine that has one installed (they pass in CI only because CI has none)."""
    env = os.environ if env is None else env
    which = which or shutil.which
    override = env.get("GITLEAKS_BIN")
    if override:
        if isfile(override) and os.access(override, os.X_OK):
            return override, ""
        return None, f"GITLEAKS_BIN={override} is not an executable file"
    found = which("gitleaks")
    if found:
        return found, ""
    for cand in BIN_CANDIDATES:
        if isfile(cand):
            return cand, ""
    return None, "gitleaks not found on PATH, in /opt/homebrew/bin or in /usr/local/bin"


def _git(root: Path, args, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, env=env, capture_output=True, text=True, timeout=120)


def run_gitleaks(argv, env, cwd):
    """The ONE place the binary runs. Returns (returncode, stdout, stderr)."""
    p = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=240)
    return p.returncode, p.stdout or "", p.stderr or ""


def binary_version(binary: str, runner=run_gitleaks, root: Path = ROOT) -> str:
    try:
        rc, out, _ = runner([binary, "version"], dict(os.environ), root)
    except (OSError, subprocess.SubprocessError):
        return ""
    m = re.search(r"([0-9]+\.[0-9]+\.[0-9]+)", out)
    return m.group(1) if rc == 0 and m else ""


def parse_findings(report_text: str) -> list:
    """gitleaks' JSON report -> [(rule, file, line)]. An empty / absent report is no findings."""
    if not report_text.strip():
        return []
    data = json.loads(report_text)
    return [(str(f.get("RuleID", "?")), str(f.get("File", "?")), int(f.get("StartLine") or 0)) for f in (data or [])]


def index_fingerprint(root: Path) -> str:
    """sha256 of the real index file — lets a caller prove the scan did not move it."""
    idx = Path(_git(root, ["rev-parse", "--path-format=absolute", "--git-path", "index"]).stdout.strip())
    return hashlib.sha256(idx.read_bytes()).hexdigest() if idx.is_file() else ""


def build_throwaway_index(root: Path, workdir: Path) -> dict:
    """Env for git/gitleaks that sees 'the wrap commit, as if `git add` had run'; the real index is untouched."""
    real = Path(_git(root, ["rev-parse", "--path-format=absolute", "--git-path", "index"]).stdout.strip())
    tmp_index = workdir / "index"
    if real.is_file():
        shutil.copyfile(real, tmp_index)
    env = {**os.environ, "GIT_INDEX_FILE": str(tmp_index)}
    if not real.is_file():
        _git(root, ["read-tree", "HEAD"], env=env)
    present = [p for p in WRAP_PATHS if (root / p).exists()]
    if present:
        _git(root, ["add", "-A", "--", *present], env=env)
    return env


def scan(root: Path = ROOT, *, binary=None, runner=run_gitleaks, require: bool = False, env=None, config: Path = None) -> tuple:
    """(exit_code, [lines]) — the whole leg. `runner` is the seam the tests replace."""
    version = pinned_version()
    lines: list = []
    if binary is None:
        binary, why = find_gitleaks(env)
        if binary is None:
            lines.append(f"UNVERIFIED — gitleaks not installed: {why}.")
            lines.append(f"  install: {INSTALL_HINT.format(version=version)}")
            lines.append("  This wrap commit has NOT been secret-scanned; CI will scan it only after it lands on main (#5405).")
            if require:
                lines.append("  --require / WRAP_REQUIRE_GITLEAKS=1 is set: refusing to pass an unscanned diff.")
                return 1, lines
            lines.append("  (exit 0: absent binary is UNVERIFIED like every other fail-open wrap leg; --require makes it block.)")
            return 0, lines

    have = binary_version(binary, runner, root)
    if have and have != version:
        lines.append(f"note: local gitleaks is v{have}, CI pins v{version} — default rules can differ between releases.")

    with tempfile.TemporaryDirectory(prefix="wrap-secrets-5405-") as tmp:
        work = Path(tmp)
        scan_env = build_throwaway_index(root, work)
        names = _git(root, ["diff", "--cached", "--name-only"], env=scan_env).stdout.split()
        if not names:
            lines.append("nothing staged or modified — no diff to scan.")
            return 0, lines
        report = work / "report.json"
        argv = [
            binary,
            "git",
            "--pre-commit",
            "--staged",
            "--config",
            str(config or CONFIG),
            "--report-format",
            "json",
            "--report-path",
            str(report),
            "--redact",
            "--no-banner",
            str(root),
        ]
        try:
            rc, out, err = runner(argv, scan_env, root)
        except (OSError, subprocess.SubprocessError) as e:
            lines.append(f"FAIL — could not run {binary}: {e}")
            return 1, lines
        try:
            findings = parse_findings(report.read_text(encoding="utf-8") if report.is_file() else "")
        except (ValueError, TypeError) as e:
            lines.append(f"FAIL — gitleaks wrote a report this gate cannot read ({e}).")
            return 1, lines

    if findings or rc == 1:
        lines.append(f"FAIL — gitleaks reports {len(findings)} finding(s) in the diff this wrap would commit (exit {rc}):")
        for rule, fname, ln in findings:
            lines.append(f"  {rule}  {fname}:{ln}")
        lines.append("  CI's `lint` gitleaks step scans every pushed commit and would red main on this (4907f0a5a, #5405).")
        lines.append("  Reword the line (never quote a credential-shaped assignment, even as an example) — do not allowlist.")
        return 1, lines
    if rc != 0:
        lines.append(f"FAIL — gitleaks exited {rc} (neither clean nor findings): {(err or out).strip()[:300]}")
        return 1, lines
    lines.append(f"OK — gitleaks (.gitleaks.toml) found nothing in {len(names)} file(s) of the wrap diff.")
    return 0, lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--require", action="store_true", help="an absent gitleaks binary FAILS instead of printing UNVERIFIED")
    args = ap.parse_args(argv)
    require = args.require or os.environ.get("WRAP_REQUIRE_GITLEAKS") == "1"
    rc, lines = scan(require=require)
    print("\n".join(lines))
    return rc


if __name__ == "__main__":
    sys.exit(main())
