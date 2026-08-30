#!/usr/bin/env python3
"""scripts/check_operating_knowledge_ledger.py — the operating-knowledge ledger guard (#2848).

THE PROBLEM
  The operator's Claude Code memory directory holds the platform's most expensive
  knowledge and lives on one laptop, outside git. #2848 requires every durable RULE in it
  to have a home in this repo and every non-rule to be NAMED as deliberately not homed.
  `docs/OPERATING_KNOWLEDGE_LEDGER.md` is that registry — one row per memory file. A
  registry nobody re-derives rots the same way its predecessor did: Appendix A of
  `docs/OPERATING_DISCIPLINE.md` was current for exactly one day.

TWO HALVES, HONESTLY SEPARATED
  --offline (default; what CI runs via tests/test_operating_knowledge_ledger_2848.py):
    the ledger is consistent with ITSELF — every file in its committed snapshot block has
    exactly one row and vice versa, every row's type matches the file's prefix, every
    homed/already-homed/superseded row cites at least one repo path git tracks, every
    narrative/off-repo row states a reason, and the coverage counts equal the rows. This
    half cannot see the memory directory and does not pretend to.
  --live (the /wrap step (c) reflex, run where the memory dir exists):
    lists every *.md in the memory directory that has no ledger row (UNLEDGERED) and
    every ledger row whose file is gone (GONE). Exit 0 clean · 1 findings · 2 could not
    look (no such directory) — "I could not look" is never a pass.

USAGE
  python3 scripts/check_operating_knowledge_ledger.py              # offline consistency, exit 1 on errors
  python3 scripts/check_operating_knowledge_ledger.py --live       # compare against the live memory dir
  python3 scripts/check_operating_knowledge_ledger.py --live --memory-dir <dir>
"""

from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys
from collections import Counter

REPO = pathlib.Path(__file__).resolve().parent.parent
LEDGER = "docs/OPERATING_KNOWLEDGE_LEDGER.md"

RULE_TYPES = ("feedback", "reference", "security")
TYPES = RULE_TYPES + ("project", "user", "index")

CITING_STATUSES = frozenset({"homed-here", "already-homed", "superseded"})
REASON_STATUSES = frozenset({"narrative", "off-repo"})
ALLOWED_STATUS = {
    "feedback": CITING_STATUSES | REASON_STATUSES,
    "reference": CITING_STATUSES | REASON_STATUSES,
    "security": CITING_STATUSES | REASON_STATUSES,
    "project": CITING_STATUSES | REASON_STATUSES | {"index"},
    "user": frozenset({"user"}),
    "index": frozenset({"index"}),
}

_ROW = re.compile(r"^\|\s*`([^`|]+\.md)`\s*\|\s*(\w+)\s*\|(.*?)\|\s*([\w-]+)\s*\|\s*$", re.MULTILINE)
_SNAPSHOT = re.compile(r"<!-- LEDGER-SNAPSHOT:START -->\s*```\n(.*?)```\s*<!-- LEDGER-SNAPSHOT:END -->", re.DOTALL)
_COVERAGE = re.compile(r"<!-- LEDGER-COVERAGE:START -->(.*?)<!-- LEDGER-COVERAGE:END -->", re.DOTALL)
_TOTAL = re.compile(r"\*\*Files in the memory index snapshot:\s*(\d+)\*\*")
_COUNT_PAIR = re.compile(r"([\w-]+)\s+(\d+)")
_BACKTICKED = re.compile(r"`([^`\n]+)`")
_PATH_SHAPED = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._/-]*$")
_TOP_LEVEL = frozenset(
    {".claude", ".github", "cdk", "config", "deploy", "docs", "lambdas", "mcp", "model", "scripts", "seeds", "setup", "site", "tests"}
)
_ROOT_FILES = frozenset({"CLAUDE.md", "CONTRIBUTING.md", "README.md", "Makefile"})


def type_of(filename: str) -> str:
    """A memory file's type is its filename prefix; anything else is the index itself."""
    for t in ("feedback", "reference", "security", "project", "user"):
        if filename.startswith(t + "_"):
            return t
    return "index"


def parse_rows(text: str) -> list[tuple[str, str, str, str]]:
    """(file, type, home, status) for every ledger row."""
    return [(f, t, home.strip(), status) for f, t, home, status in _ROW.findall(text)]


def parse_snapshot(text: str) -> list[str]:
    m = _SNAPSHOT.search(text)
    if not m:
        return []
    return [line.strip() for line in m.group(1).splitlines() if line.strip()]


def repo_paths_in(cell: str) -> list[str]:
    """Backticked tokens in a home cell that name a path in this repo."""
    out = []
    for tok in _BACKTICKED.findall(cell):
        tok = tok.strip()
        if not _PATH_SHAPED.match(tok):
            continue
        head = tok.split("/", 1)[0]
        if (head in _TOP_LEVEL and "/" in tok) or tok in _ROOT_FILES:
            out.append(tok)
    return out


def git_tracked(path: str) -> bool:
    """Tracked at HEAD, or staged in the index (a file added in the commit under test)."""
    try:
        head = subprocess.run(["git", "ls-tree", "HEAD", "--", path], cwd=REPO, capture_output=True, text=True, timeout=30)
        idx = subprocess.run(["git", "status", "--porcelain", "--", path], cwd=REPO, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - environment
        return True
    if head.returncode == 0 and head.stdout.strip():
        return True
    return idx.returncode == 0 and any(line and not line.startswith("??") for line in idx.stdout.splitlines())


def ledger_errors(text: str, tracked=git_tracked) -> list[str]:
    """Pure decision function: every way the ledger can disagree with itself.

    `tracked` is injected so the rule can be mutation-proven without a git repo.
    """
    errors: list[str] = []
    rows = parse_rows(text)
    snapshot = parse_snapshot(text)
    if not snapshot:
        return ["no LEDGER-SNAPSHOT block — the ledger states no denominator"]
    if not rows:
        return ["no ledger rows parsed — the table shape changed and the extractor has gone blind"]

    seen: Counter[str] = Counter(f for f, *_ in rows)
    for f, n in seen.items():
        if n > 1:
            errors.append(f"{f} has {n} rows")
    row_files = set(seen)
    snap_files = set(snapshot)
    for f in sorted(snap_files - row_files):
        errors.append(f"snapshot file has no ledger row: {f}")
    for f in sorted(row_files - snap_files):
        errors.append(f"ledger row not in snapshot: {f}")

    for f, t, home, status in rows:
        expected = type_of(f)
        if t != expected:
            errors.append(f"{f}: type column says {t!r}, filename says {expected!r}")
            continue
        if status not in ALLOWED_STATUS[t]:
            errors.append(f"{f}: status {status!r} not allowed for type {t!r}")
            continue
        if status in CITING_STATUSES:
            paths = repo_paths_in(home)
            if not paths:
                errors.append(f"{f}: status {status!r} but the home cell cites no repo path")
            else:
                for p in paths:
                    if not tracked(p):
                        errors.append(f"{f}: cited path is not tracked by git: {p}")
        elif status in REASON_STATUSES:
            if len(home.lstrip("—- ").strip()) < 15:
                errors.append(f"{f}: status {status!r} needs a stated reason in the home cell")

    total = _TOTAL.search(text)
    if not total:
        errors.append("no '**Files in the memory index snapshot: N**' line")
    elif int(total.group(1)) != len(snapshot):
        errors.append(f"snapshot declares {total.group(1)} files, block lists {len(snapshot)}")

    cov = _COVERAGE.search(text)
    if not cov:
        errors.append("no LEDGER-COVERAGE block")
    else:
        by_type = Counter(t for _, t, _, _ in rows)
        rule_rows = [r for r in rows if r[1] in RULE_TYPES]
        proj_rows = [r for r in rows if r[1] == "project"]
        lines = [ln for ln in cov.group(1).splitlines() if ln.strip()]
        want = {
            "Files in the memory index snapshot": (len(rows), Counter({t: by_type[t] for t in TYPES})),
            "Rule-class files": (len(rule_rows), Counter(r[3] for r in rule_rows)),
            "Program/session files": (len(proj_rows), Counter(r[3] for r in proj_rows)),
        }
        for label, (n, breakdown) in want.items():
            line = next((ln for ln in lines if label in ln), None)
            if line is None:
                errors.append(f"coverage block has no '{label}' line")
                continue
            head_n = re.search(r"\*\*[^*]*?:\s*(\d+)\*\*", line)
            if not head_n or int(head_n.group(1)) != n:
                errors.append(f"coverage '{label}' says {head_n.group(1) if head_n else '?'}, rows say {n}")
            tail = line.split("**", 2)[-1]
            for key, val in _COUNT_PAIR.findall(tail):
                if key in breakdown or key in ALLOWED_STATUS["project"] | set(TYPES):
                    if breakdown.get(key, 0) != int(val):
                        errors.append(f"coverage '{label}' says {key} {val}, rows say {breakdown.get(key, 0)}")
    return errors


def live_findings(memory_dir: pathlib.Path, text: str) -> tuple[list[str], list[str]]:
    """(UNLEDGERED, GONE): memory files with no row, and rows whose file is gone."""
    live = sorted(p.name for p in memory_dir.glob("*.md"))
    rows = {f for f, *_ in parse_rows(text)}
    unledgered = [f for f in live if f not in rows]
    gone = sorted(rows - set(live))
    return unledgered, gone


def default_memory_dir() -> pathlib.Path | None:
    """Claude Code keys the project memory dir on the PRIMARY checkout's absolute path."""
    try:
        common = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=REPO, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if common.returncode != 0:
        return None
    primary = (REPO / common.stdout.strip()).resolve().parent
    encoded = str(primary).replace("/", "-")
    return pathlib.Path.home() / ".claude" / "projects" / encoded / "memory"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--live", action="store_true", help="compare the ledger against the live memory directory")
    ap.add_argument("--memory-dir", type=pathlib.Path, default=None, help="override the derived memory directory")
    args = ap.parse_args(argv)

    text = (REPO / LEDGER).read_text(encoding="utf-8")
    if not args.live:
        errors = ledger_errors(text)
        rows = parse_rows(text)
        print(f"[ledger] {len(rows)} rows · {len(parse_snapshot(text))} snapshot files · {len(errors)} error(s)")
        for e in errors:
            print("  ", e)
        return 1 if errors else 0

    mem = args.memory_dir or default_memory_dir()
    if mem is None or not mem.is_dir():
        print(f"[ledger --live] could not look: memory dir not found ({mem}) — pass --memory-dir")
        return 2
    unledgered, gone = live_findings(mem, text)
    live_n = len(list(mem.glob("*.md")))
    print(f"[ledger --live] {mem}: {live_n} live files · {len(unledgered)} unledgered · {len(gone)} gone")
    for f in unledgered:
        print(f"UNLEDGERED: {f}  ({type_of(f)}) — add a row to {LEDGER}: home, or the reason it has none")
    for f in gone:
        print(f"GONE: {f} — ledger row exists, memory file does not; drop the row or restore the file")
    return 1 if (unledgered or gone) else 0


if __name__ == "__main__":
    sys.exit(main())
