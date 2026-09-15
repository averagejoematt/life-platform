#!/usr/bin/env python3
"""scripts/check_no_verify_sites.py — the `--no-verify` SET guard (#3642).

THE PROBLEM THIS SOLVES
  `deploy/agent_commit.sh` bypasses the pre-commit hook with `git commit --no-verify`
  — deliberately (see the script's own header). Auditing "is every bypass site
  accounted for" by eye does not scale — #3642 was filed because two lanes
  independently hit a defect in the ONE registered execution site; an unregistered
  second one would be strictly worse and invisible to this class of guard entirely.

  CORRECTION (caught in review of PR #3799, before merge): #3642's own issue body
  describes `.claude/settings.json`'s bypass entries as a permission "grant ... that
  lets any lane bypass ad hoc." That is a misreading of the live config. All four
  matching entries — `Bash(git commit --no-verify:*)`, `Bash(git commit -n:*)`,
  `Bash(mv .git/hooks/pre-commit:*)`, `Bash(rm .git/hooks/pre-commit:*)` — sit in
  `.claude/settings.json`'s **`ask`** list, not `allow`. `ask` means Claude Code
  prompts the operator every single time before running one — that is a GUARD, the
  strongest posture short of outright denial, not an unattended grant. This module
  names the bucket for what it actually is (`ASK_GATED_BYPASS`) and checks the
  property that actually matters: the set of these affordances stays enumerated,
  and none of them silently migrates from `ask` to `allow` (a real posture
  escalation this guard should catch by name).

THE FIX
  Every line under `deploy/`, `scripts/`, `.claude/` (excluding `*.md`, which is
  prose, not code, and excluding `.claude/settings.json`'s own JSON body — that
  file is read structurally instead, see below) that mentions `--no-verify` is
  classified into one of three buckets:

    EXECUTION      — a line that actually RUNS `git commit ... --no-verify`. There
                     must be exactly ONE of these, and it must be the registered
                     site (deploy/agent_commit.sh).
    UNRELATED_FLAG — `--no-verify-boot` (deploy/build_bundle.py's bundle-boot
                     check, scripts/verify_bundle_boot.py's docstring) is a
                     DIFFERENT flag that merely shares the substring
                     `--no-verify`; it has nothing to do with git commit hooks.
    DOCUMENTATION  — a comment or an echoed/printed message that talks ABOUT the
                     bypass (why it's there, how to invoke it in an emergency)
                     without itself being the invocation.

  Separately, `.claude/settings.json` is parsed as JSON (not grepped as text) for
  every permission entry matching the same class of bypass affordance — both
  `git commit` spellings (`--no-verify` and its short form `-n`, #3642's own grep
  cannot see the latter) and both hook-file-removal spellings
  (`mv`/`rm .git/hooks/pre-commit`), since all four are the same affordance in
  different clothing:

    ASK_GATED_BYPASS — a bypass affordance found in the `ask` list. Expected
                     population today: 4. Fine to grow (a new documented
                     ask-gated affordance is not a regression); a floor below 4
                     fails (something disappeared from an "ask" gate that
                     should still be there).

  A `POSTURE ESCALATION` failure fires if any matching entry is found in a list
  OTHER than `ask` (most importantly `allow`) — that is the actual dangerous
  event: a bypass that used to prompt every time no longer does.

  A grep line matching none of the three buckets is UNREGISTERED and fails the
  gate by name. A population that resolves to zero total hits also fails — see
  `docs/REMEDIATION_TAXONOMY.md`'s guard-the-set-not-the-instance class and
  `tests/test_gate_census_2578.py` for the same shape elsewhere in the repo.

USAGE
  python3 scripts/check_no_verify_sites.py           # exit 1 on any unregistered hit
  python3 scripts/check_no_verify_sites.py --list    # print every hit + its bucket
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("deploy", "scripts", ".claude")
NEEDLE = "--no-verify"
SETTINGS_PATH = ".claude/settings.json"
# This guard's own source narrates the bypass by name (it has to, to explain what it's
# classifying) — that is prose ABOUT the audit, not a site the audit is auditing.
# Excluded, not classified, so the guard is not endlessly self-referential.
_SELF = "scripts/check_no_verify_sites.py"

# ── Buckets, each with a REASON — the registration the issue asked for ────────

EXECUTION = "EXECUTION"
ASK_GATED_BYPASS = "ASK_GATED_BYPASS"
UNRELATED_FLAG = "UNRELATED_FLAG"
DOCUMENTATION = "DOCUMENTATION"
UNREGISTERED = "UNREGISTERED"  # not a real bucket — the failure state

REASONS: dict[str, str] = {
    EXECUTION: (
        "the one place a commit actually bypasses the hook — deploy/agent_commit.sh's own "
        "format gate replaces the hook's useful half (black+ruff), so skipping the hook's OTHER "
        "job (the doc-sync sweep, wrong on a feature branch) is the deliberate point (#3642)."
    ),
    ASK_GATED_BYPASS: (
        "a hook-bypass affordance (git commit --no-verify/-n, or removing the pre-commit hook "
        "file outright) that Claude Code will only run after prompting the operator EVERY TIME — "
        "it lives in .claude/settings.json's `ask` list, not `allow`. This is a guard, not a "
        "grant; the property worth checking is that the set stays enumerated and none of these "
        "four migrates to `allow` unnoticed, not that they don't exist."
    ),
    UNRELATED_FLAG: (
        "`--no-verify-boot` (deploy/build_bundle.py, scripts/verify_bundle_boot.py) is the "
        "bundle-boot import check's own flag — a different feature that merely shares the "
        "substring `--no-verify`. Not a commit-hook bypass."
    ),
    DOCUMENTATION: (
        "a comment or an echoed/printed message that talks ABOUT the bypass (why it exists, how "
        "to invoke it by hand in a genuine emergency) without itself executing it."
    ),
}

# Matches all four known .claude/settings.json bypass affordances, in either
# `git commit` spelling or either hook-file-removal spelling — the same
# affordance in four clothings, per the issue's own follow-up (#3798).
_ASK_GATED_BYPASS_RE = re.compile(r"git commit (?:--no-verify|-n)\b|\.git/hooks/pre-commit")


@dataclass(frozen=True)
class Hit:
    path: str
    lineno: int
    text: str
    bucket: str


def _grep_hits() -> list[tuple[str, int, str]]:
    """Every `--no-verify` line under deploy/ scripts/ .claude/, excluding *.md
    (prose, not code) and .claude/settings.json (read structurally instead, see
    `_settings_json_bypass_hits`, since two of its four bypass entries — the `-n`
    short form and the hook-file-removal pair — contain no `--no-verify`
    substring at all and a text grep cannot see them)."""
    cmd = ["grep", "-rnI", "--", NEEDLE, *SCAN_DIRS]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    # grep exits 1 when it finds nothing — that IS a failure state here (a population
    # floor of zero means the derivation went blind), so don't swallow it silently.
    if proc.returncode not in (0, 1):
        raise RuntimeError(f"grep failed: {proc.stderr}")
    hits: list[tuple[str, int, str]] = []
    for line in proc.stdout.splitlines():
        if not line:
            continue
        path, lineno_s, text = line.split(":", 2)
        if path.endswith(".md") or path == _SELF or path == SETTINGS_PATH:
            continue
        hits.append((path, int(lineno_s), text))
    return hits


_EXECUTION_RE = re.compile(r"^\s*git\s+commit\b.*--no-verify")
_ECHO_RE = re.compile(r"^\s*echo\b")


def _classify(path: str, text: str) -> str:
    stripped = text.strip()

    if "--no-verify-boot" in text:
        return UNRELATED_FLAG

    if _EXECUTION_RE.match(stripped):
        return EXECUTION

    if stripped.startswith("#") or _ECHO_RE.match(stripped) or "echo(" in stripped or '"' in stripped or "print(" in stripped:
        # A comment, an echoed/printed message, or a docstring/print sentence
        # referencing the bypass — none of these RUN it.
        return DOCUMENTATION

    return UNREGISTERED


@dataclass(frozen=True)
class SettingsHit:
    list_name: str  # "ask", "allow", "deny", ...
    entry: str
    lineno: int | None


def _settings_json_bypass_hits(settings_path: Path | None = None) -> list[SettingsHit]:
    """Reads .claude/settings.json STRUCTURALLY (json.load, not grep) — the only
    reliable way to see entries like `Bash(git commit -n:*)` that share no
    substring with `--no-verify`, and the only way to know which LIST (ask vs.
    allow) an entry actually lives in, which is the property this guard cares
    about."""
    path = settings_path or (REPO_ROOT / SETTINGS_PATH)
    data = json.loads(path.read_text(encoding="utf-8"))
    perms = data.get("permissions", {})
    raw_lines = path.read_text(encoding="utf-8").splitlines()

    hits: list[SettingsHit] = []
    for list_name, entries in perms.items():
        for entry in entries:
            if not _ASK_GATED_BYPASS_RE.search(entry):
                continue
            lineno = None
            for i, raw in enumerate(raw_lines, start=1):
                if entry in raw:
                    lineno = i
                    break
            hits.append(SettingsHit(list_name, entry, lineno))
    return hits


def enumerate_sites() -> list[Hit]:
    """The full population, for `--list` and for eyeballing. Combines the grep-
    derived deploy/scripts hits with the structurally-parsed settings.json
    ask-gated bypass affordances (each reported as its real list name via the
    bucket, so an escalation to `allow` is visible here too, not just in
    `check()`'s failure messages)."""
    grep_sites = [Hit(path, lineno, text, _classify(path, text)) for path, lineno, text in _grep_hits()]
    settings_sites = [
        Hit(SETTINGS_PATH, sh.lineno or 0, f"[{sh.list_name}] {sh.entry}", ASK_GATED_BYPASS if sh.list_name == "ask" else UNREGISTERED)
        for sh in _settings_json_bypass_hits()
    ]
    return grep_sites + settings_sites


def check(hits: list[Hit] | None = None, settings_hits: list[SettingsHit] | None = None) -> list[str]:
    """Returns a list of failure messages; empty means the gate passes.

    `hits` is the grep-derived population (EXECUTION/UNRELATED_FLAG/DOCUMENTATION/
    UNREGISTERED). `settings_hits` is the structurally-parsed .claude/settings.json
    population (ask-gated bypass affordances, in ANY list) — kept as a separate
    parameter so a caller can plant a synthetic escalation (an entry moved to
    `allow`) without needing a real settings.json on disk.
    """
    if hits is None:
        hits = [h for h in enumerate_sites() if h.path != SETTINGS_PATH]
    if settings_hits is None:
        settings_hits = _settings_json_bypass_hits()

    failures: list[str] = []

    if not hits and not settings_hits:
        failures.append(
            "population floor: zero '--no-verify'/ask-gated-bypass hits found under "
            "deploy/ scripts/ .claude/ — the scan has gone blind (compare against #3642's known set)."
        )

    unregistered = [h for h in hits if h.bucket == UNREGISTERED]
    for h in unregistered:
        failures.append(f"UNREGISTERED --no-verify site: {h.path}:{h.lineno}: {h.text.strip()!r} — classify it or fix it.")

    executions = [h for h in hits if h.bucket == EXECUTION]
    if len(executions) != 1:
        failures.append(f"expected exactly 1 EXECUTION site, found {len(executions)}: {[(h.path, h.lineno) for h in executions]}")
    elif executions[0].path != "deploy/agent_commit.sh":
        failures.append(f"the registered EXECUTION site is deploy/agent_commit.sh — found a different one: {executions[0].path}")

    ask_hits = [sh for sh in settings_hits if sh.list_name == "ask"]
    escalated = [sh for sh in settings_hits if sh.list_name != "ask"]

    if len(ask_hits) < 4:
        failures.append(
            f"expected at least 4 ask-gated bypass affordances in {SETTINGS_PATH}'s 'ask' list, "
            f"found {len(ask_hits)}: {[sh.entry for sh in ask_hits]}"
        )

    for sh in escalated:
        failures.append(
            f"POSTURE ESCALATION: bypass affordance {sh.entry!r} found in {SETTINGS_PATH}'s "
            f"{sh.list_name!r} list, not 'ask' — a bypass that used to prompt every time no longer does."
        )

    return failures


def main(argv: list[str]) -> int:
    all_sites = enumerate_sites()

    if "--list" in argv:
        for h in all_sites:
            bucket_label = "ESCALATED" if h.bucket == UNREGISTERED and h.path == SETTINGS_PATH else h.bucket
            print(f"{bucket_label:16s} {h.path}:{h.lineno}: {h.text.strip()}")
        return 0

    failures = check()
    if failures:
        print("[check-no-verify-sites] FAILED:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    print(f"[check-no-verify-sites] OK — {len(all_sites)} site(s), all registered.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
