#!/usr/bin/env python3
"""scripts/check_pip_audit.py — the ONE pip-audit runner for every scanned manifest (#5473).

THE DEFECT THIS OWNS
--------------------
Third-party code reaches a running Lambda only inside the binary layers (pillow-layer,
lameenc-layer, and the retired garth-layer), whose contents are pinned in
`lambdas/requirements/{pillow,lameenc,garmin}.txt`. CI's enforced pip-audit step skipped
those manifests because the scheduled `life-platform-pip-audit` Lambda was meant to scan
them. It never did: the python3.12 Lambda runtime ships no pip, every manifest errored
with `No module named pip`, and the report still said 0 vulnerabilities. 41 Pillow
advisories (6 critical) sat on `pillow.txt` for a week, found only by a `git push` banner.

So the scan moves to where pip exists (GitHub Actions), and this script is what both CI
legs run:

  --layers                 every `lambdas/requirements/*.txt` that pins at least one
                           package, in EXACT-PIN mode (`--disable-pip --no-deps`): the
                           manifest is the measured contents of the live layer, so the
                           scan queries exactly those pins and resolves nothing. Run by
                           the weekly layer-manifest workflow (schedule + dispatch + PRs
                           touching the manifests).
  --resolve FILE [FILE …]  RESOLVE mode (pip-audit's default `-r`): for the dev and CDK
                           manifests, whose transitive set is not written down. Run by
                           ci-lint's blocking "Dependency Security Scan" step.

FAIL-LOUD CONTRACT (#5473 box 3 — a scan that cannot run never reads "0 vulnerabilities")
-----------------------------------------------------------------------------------------
Each manifest gets one verdict, and only CLEAN is green:

  CLEAN       pip-audit exited 0, its JSON parsed, and (exact-pin mode) every pinned name
              came back as a scanned dependency.
  VULNERABLE  at least one advisory not covered by an allowlist entry for this manifest.
  ERROR       anything else — pip-audit missing, a non-JSON stdout, a non-zero exit with
              no finding, zero dependencies reported for a manifest that pins packages, a
              pinned name the scan did not return, or a dependency pip-audit skipped
              (exact-pin mode). An ERROR exits non-zero exactly like a finding.
  EMPTY       the manifest pins nothing (the stdlib-only Lambda groups) — listed, never
              scanned, never red.

THE ALLOWLIST (`.github/pip-audit-allowlist.txt`)
--------------------------------------------------
One advisory ID per line; everything after `#` is the rationale. An entry may be SCOPED
to named manifests with `scope=<path>[,<path>…]` — it is then honoured only when scanning
those manifests, so a waiver for a retired layer cannot also silence the same advisory on
the dev toolchain. A scope naming a manifest that does not exist is an error (a stale
waiver is a bug, not a no-op). Before #5473 the ci-lint step parsed this file in inline
bash; it now calls this script, so there is one parser.

Exit status: 0 all CLEAN/EMPTY · 1 any VULNERABLE or ERROR · 2 usage / allowlist error.
Nothing here touches AWS. The only network is pip-audit's own advisory lookups.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST_PATH = REPO_ROOT / ".github" / "pip-audit-allowlist.txt"
LAYER_REQUIREMENTS_DIR = REPO_ROOT / "lambdas" / "requirements"

CLEAN, VULNERABLE, ERROR, EMPTY = "CLEAN", "VULNERABLE", "ERROR", "EMPTY"

# A requirement line's package name: everything before the first specifier/extra/marker.
_REQ_NAME_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")


def normalize(name: str) -> str:
    """PEP 503 normalization, so `Pillow`/`pillow` and `curl_cffi`/`curl-cffi` match."""
    return re.sub(r"[-_.]+", "-", name).lower()


def pinned_names(text: str) -> list[str]:
    """Normalized package names of every requirement line (comments, blanks and pip
    options such as `-r`/`--hash` continuation lines skipped)."""
    names = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        m = _REQ_NAME_RE.match(line)
        if m:
            names.append(normalize(m.group(1)))
    return names


# ── allowlist ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AllowEntry:
    vuln_id: str
    scopes: tuple[str, ...] = ()
    line_no: int = 0

    def applies_to(self, manifest: str) -> bool:
        return not self.scopes or manifest in self.scopes


class AllowlistError(ValueError):
    pass


def parse_allowlist(text: str) -> list[AllowEntry]:
    """Parse the allowlist. The first token is the ID; an optional `scope=a,b` token
    restricts it; any other token before the `#` is a malformed line (raised, not
    guessed — the pre-#5473 bash parser concatenated stray tokens INTO the ID)."""
    entries = []
    for no, raw in enumerate(text.splitlines(), start=1):
        tokens = raw.split("#", 1)[0].split()
        if not tokens:
            continue
        vuln_id, rest = tokens[0], tokens[1:]
        scopes: list[str] = []
        for tok in rest:
            if not tok.startswith("scope="):
                raise AllowlistError(f"line {no}: unexpected token {tok!r} (only `scope=<manifest>[,<manifest>]` may follow the ID)")
            scopes.extend(p for p in tok[len("scope=") :].split(",") if p)
        if any(t.startswith("scope=") for t in rest) and not scopes:
            raise AllowlistError(f"line {no}: empty scope= for {vuln_id}")
        entries.append(AllowEntry(vuln_id=vuln_id, scopes=tuple(scopes), line_no=no))
    return entries


def stale_scopes(entries: list[AllowEntry], root: Path = REPO_ROOT) -> list[str]:
    """Scope paths that name no file — a waiver pointing at nothing."""
    return [f"line {e.line_no}: {e.vuln_id} scope={s} (no such file)" for e in entries for s in e.scopes if not (root / s).is_file()]


def ignore_ids_for(manifest: str, entries: list[AllowEntry]) -> list[str]:
    return sorted({e.vuln_id for e in entries if e.applies_to(manifest)})


# ── one scan ────────────────────────────────────────────────────────────────────


@dataclass
class ScanResult:
    manifest: str
    verdict: str
    packages: int = 0
    findings: list[dict] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)
    detail: str = ""


Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


def _default_runner(cmd: list[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(cmd, capture_output=True, text=True, timeout=900)


def pip_audit_command(manifest_path: Path, exact_pins: bool, ignore_ids: list[str]) -> list[str]:
    cmd = [sys.executable, "-m", "pip_audit", "-r", str(manifest_path), "--format", "json", "--desc", "on"]
    if exact_pins:
        # The manifest IS the deployed layer's full resolved contents: query those pins,
        # resolve nothing (a resolve on the runner would audit a different set).
        cmd += ["--disable-pip", "--no-deps"]
    for vid in ignore_ids:
        cmd += ["--ignore-vuln", vid]
    return cmd


def classify(manifest: str, pins: list[str], proc, exact_pins: bool, ignored: list[str]) -> ScanResult:
    """Turn one pip-audit run into a verdict. Pure — the tests drive it with fakes."""
    stdout = proc.stdout or ""
    stderr_tail = (proc.stderr or "").strip()[-400:]
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return ScanResult(
            manifest, ERROR, ignored=ignored, detail=f"pip-audit exit {proc.returncode}, stdout not JSON; stderr: {stderr_tail}"
        )
    deps = data.get("dependencies") if isinstance(data, dict) else None
    if not isinstance(deps, list):
        return ScanResult(manifest, ERROR, ignored=ignored, detail="pip-audit JSON has no `dependencies` list")

    findings = []
    skipped = []
    for dep in deps:
        if dep.get("skip_reason"):
            skipped.append(f"{dep.get('name')}: {dep.get('skip_reason')}")
        for v in dep.get("vulns") or []:
            key = (dep.get("name", "?"), v.get("id", "?"))
            prior = next((f for f in findings if (f["package"], f["id"]) == key), None)
            if prior:  # pip-audit repeats an ID once per fix range; one finding, merged fixes
                prior["fix_versions"] = sorted(set(prior["fix_versions"]) | set(v.get("fix_versions") or []))
                continue
            findings.append(
                {
                    "package": key[0],
                    "version": dep.get("version", "?"),
                    "id": key[1],
                    "aliases": v.get("aliases") or [],
                    "fix_versions": sorted(v.get("fix_versions") or []),
                }
            )
    scanned = {normalize(d.get("name", "")) for d in deps if not d.get("skip_reason")}
    result = ScanResult(manifest, CLEAN, packages=len(scanned), findings=findings, ignored=ignored)

    if findings:
        result.verdict = VULNERABLE
        return result
    if proc.returncode != 0:
        result.verdict = ERROR
        result.detail = f"pip-audit exit {proc.returncode} with no finding; stderr: {stderr_tail}"
        return result
    if not scanned:
        result.verdict = ERROR
        result.detail = f"0 dependencies scanned for a manifest that pins {len(pins)}"
        return result
    if exact_pins:
        missing = sorted(set(pins) - scanned)
        if missing or skipped:
            result.verdict = ERROR
            result.detail = "not scanned: " + ", ".join(missing + skipped)
    elif skipped:
        result.detail = "skipped by pip-audit (resolve mode, not failed): " + ", ".join(skipped)
    return result


def scan_manifest(
    path: Path, entries: list[AllowEntry], exact_pins: bool, runner: Runner = _default_runner, root: Path = REPO_ROOT
) -> ScanResult:
    rel = path.resolve().relative_to(root.resolve()).as_posix() if path.resolve().is_relative_to(root.resolve()) else str(path)
    try:
        pins = pinned_names(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return ScanResult(rel, ERROR, detail=f"unreadable: {exc}")
    if not pins:
        return ScanResult(rel, EMPTY, detail="pins no third-party package")
    ignored = ignore_ids_for(rel, entries)
    try:
        proc = runner(pip_audit_command(path, exact_pins, ignored))
    except (OSError, subprocess.SubprocessError) as exc:
        return ScanResult(rel, ERROR, ignored=ignored, detail=f"pip-audit did not run: {exc}")
    return classify(rel, pins, proc, exact_pins, ignored)


def layer_manifests(requirements_dir: Path = LAYER_REQUIREMENTS_DIR) -> list[Path]:
    """Every per-Lambda manifest — the scan decides which are EMPTY, so a newly pinned
    manifest joins the scan without anyone listing it."""
    return sorted(requirements_dir.glob("*.txt"))


# ── report ──────────────────────────────────────────────────────────────────────


def render(results: list[ScanResult], mode: str) -> tuple[str, str]:
    """(plain log text, markdown step summary)."""
    log, md = [], [f"## pip-audit — {mode} (#5473)", "", "| manifest | verdict | packages scanned | detail |", "|---|---|---|---|"]
    for r in results:
        bits = []
        if r.findings:
            bits.append(
                "; ".join(f"{f['package']}=={f['version']} {f['id']} (fix: {', '.join(f['fix_versions']) or 'none'})" for f in r.findings)
            )
        if r.ignored:
            bits.append("allowlisted: " + ", ".join(r.ignored))
        if r.detail:
            bits.append(r.detail)
        detail = " · ".join(bits)
        label = "SCANNED" if r.verdict in (CLEAN, VULNERABLE) else r.verdict
        shown = r.verdict if label == "SCANNED" else ""
        log.append(f"{label:<8} {shown:<10} {r.manifest:<42} packages={r.packages:<3} {detail}".rstrip())
        md.append(f"| `{r.manifest}` | {r.verdict} | {r.packages if r.verdict != EMPTY else '—'} | {detail.replace('|', '/')} |")
    scanned = [r for r in results if r.verdict in (CLEAN, VULNERABLE)]
    red = [r for r in results if r.verdict in (VULNERABLE, ERROR)]
    tail = (
        f"{len(scanned)} manifest(s) scanned ({sum(r.packages for r in scanned)} packages), "
        f"{sum(1 for r in results if r.verdict == EMPTY)} empty, {len(red)} red"
    )
    log.append(tail)
    md += ["", tail]
    return "\n".join(log), "\n".join(md) + "\n"


def main(argv: list[str] | None = None, runner: Runner = _default_runner) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--layers", action="store_true", help="scan every lambdas/requirements/*.txt in exact-pin mode")
    group.add_argument("--resolve", nargs="+", metavar="FILE", help="scan these manifests in resolve mode")
    ap.add_argument("--allowlist", default=str(ALLOWLIST_PATH))
    ap.add_argument("--requirements-dir", default=str(LAYER_REQUIREMENTS_DIR), help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    try:
        allow_text = Path(args.allowlist).read_text(encoding="utf-8") if Path(args.allowlist).is_file() else ""
        entries = parse_allowlist(allow_text)
    except AllowlistError as exc:
        print(f"::error title=pip-audit allowlist malformed::{exc}")
        return 2
    stale = stale_scopes(entries)
    if stale:
        print("::error title=pip-audit allowlist scope names no manifest::" + "; ".join(stale))
        return 2

    if args.layers:
        mode, exact, paths = "layer manifests (exact pins)", True, layer_manifests(Path(args.requirements_dir))
        if not paths:
            print(f"::error::no manifests found under {args.requirements_dir} — a scan of nothing is not a pass")
            return 1
    else:
        mode, exact, paths = (
            "dev + CDK manifests (resolved)",
            False,
            [REPO_ROOT / p if not os.path.isabs(p) else Path(p) for p in args.resolve],
        )

    results = [scan_manifest(p, entries, exact, runner) for p in paths]
    log, md = render(results, mode)
    print(log)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(md)

    red = [r for r in results if r.verdict in (VULNERABLE, ERROR)]
    for r in red:
        title = "Dependency vulnerability (blocking)" if r.verdict == VULNERABLE else "pip-audit could not scan (blocking)"
        print(f"::error title={title}::{r.manifest}: {r.verdict}")
    if red:
        print(
            "Fix: bump the dependency (for a layer manifest, rebuild the layer — editing the pin deploys nothing, see "
            "lambdas/requirements/README.md), or, if unfixable/inapplicable, add the advisory ID to "
            ".github/pip-audit-allowlist.txt with a rationale + removal path (scope= it to the manifest it applies to)."
        )
        return 1
    print("pip-audit clean (allowlisted IDs excluded).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
