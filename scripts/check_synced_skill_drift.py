#!/usr/bin/env python3
"""scripts/check_synced_skill_drift.py — does the claude.ai synced copy of a chat skill match its repo source? (#5086)

WHY
  Claude Desktop and mobile run the coach-session skill from a copy held by the claude.ai account,
  which the desktop app syncs DOWN to this machine under ``~/.claude/skills/synced/<org>_<account>/``
  (a second, identical copy sits in the desktop app's skills-plugin cache). Nothing tied that copy to
  the repo: by 2026-10-18 it still described the retired v0.4 four-session program while the repo's
  ``docs/coaching/COACH_SESSION.md`` had moved on, and the two had diverged both ways. The repo source
  is now ``.claude/skills/<skill>/SKILL.md``; this check says whether every synced copy found matches it.

WHAT IS COMPARED
  The ``name`` and ``description`` frontmatter fields and the body, normalised: whitespace runs
  collapsed (line breaks included, so a re-wrapped paragraph is not drift) and blank lines dropped. Other frontmatter keys (``allowed-tools`` is
  a Claude Code key the upload strips) are ignored. A copy that differs after that is DRIFT.

WHERE THE COPIES COME FROM (first that applies)
  ``--synced PATH`` (repeatable) > ``$SYNCED_SKILL_PATHS`` (``os.pathsep``-separated) > discovery under
  ``--home`` (default ``~``): ``.claude/skills/synced/*/<skill>/SKILL.md`` and
  ``Library/Application Support/Claude/local-agent-mode-sessions/skills-plugin/*/*/skills/<skill>/SKILL.md``.
  None found (CI, or a machine without the desktop app) -> ``skipped: no synced copy on this machine``,
  exit 0 — the check has nothing to compare and says so; it never reads that as "in sync".

EXIT
  0 every copy found matches, or none was found (skipped, stated); 1 drift in at least one copy; 2 the
  repo source is missing.

THE SYNC IS ONE-WAY, DOWN — this script never writes a synced copy. The account copy is replaced by an
upload in the claude.ai UI (``docs/coaching/SYNCED_SKILLS.md``); ``--package OUT.zip`` builds the
upload (``<skill>/SKILL.md`` with only ``name`` + ``description`` in its frontmatter).
"""

from __future__ import annotations

import argparse
import difflib
import importlib.util
import json
import os
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SKILL = "coach-session"
ENV_VAR = "SYNCED_SKILL_PATHS"
SKIPPED = "skipped: no synced copy on this machine"
COMPARED_FIELDS = ("name", "description")
_DISCOVERY = (
    ".claude/skills/synced/*/{skill}/SKILL.md",
    "Library/Application Support/Claude/local-agent-mode-sessions/skills-plugin/*/*/skills/{skill}/SKILL.md",
)


def _parse_frontmatter(text: str) -> tuple[dict[str, str] | None, str]:
    """skill_lint's hand parser (no PyYAML — the reason is in that module's docstring)."""
    spec = importlib.util.spec_from_file_location("_skill_lint", Path(__file__).resolve().parent / "skill_lint.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod.parse_frontmatter(text)


def normalise(text: str) -> list[str]:
    """The comparable form: `name: …` and `description: …` lines, then the body's non-blank lines
    with every whitespace run collapsed to one space. Compared as one text (`_same`)."""
    fields, body = _parse_frontmatter(text.replace("\r\n", "\n"))
    fields = fields or {}
    head = [f"{k}: " + _ws(fields.get(k, "")) for k in COMPARED_FIELDS]
    return head + [ln for ln in (_ws(raw) for raw in body.splitlines()) if ln]


def _ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _same(a: list[str], b: list[str]) -> bool:
    """Equal as one whitespace-normalised text, so a paragraph re-wrapped by an editor or the upload is
    not drift; the line form is kept only for the diff a real difference prints."""
    return " ".join(a) == " ".join(b)


def repo_source(skill: str, root: Path = ROOT) -> Path:
    return root / ".claude" / "skills" / skill / "SKILL.md"


def find_copies(skill: str, explicit: list[str] | None, home: Path) -> list[Path]:
    if explicit:
        return [Path(p).expanduser() for p in explicit]
    env = os.environ.get(ENV_VAR, "").strip()
    if env:
        return [Path(p).expanduser() for p in env.split(os.pathsep) if p.strip()]
    found: list[Path] = []
    for pattern in _DISCOVERY:
        found.extend(sorted(home.glob(pattern.format(skill=skill))))
    return found


def compare(source: Path, copy: Path, context: int = 2) -> dict:
    """{'path', 'state': in_sync|drift|unreadable, 'added', 'removed', 'diff'} for one copy."""
    want = normalise(source.read_text(encoding="utf-8"))
    try:
        have = normalise(copy.read_text(encoding="utf-8"))
    except OSError as e:
        return {"path": str(copy), "state": "unreadable", "error": type(e).__name__, "added": 0, "removed": 0, "diff": []}
    if _same(want, have):
        return {"path": str(copy), "state": "in_sync", "added": 0, "removed": 0, "diff": []}
    diff = list(difflib.unified_diff(have, want, fromfile=f"synced:{copy}", tofile=f"repo:{source}", lineterm="", n=context))
    added = sum(1 for d in diff if d.startswith("+") and not d.startswith("+++"))
    removed = sum(1 for d in diff if d.startswith("-") and not d.startswith("---"))
    return {"path": str(copy), "state": "drift", "added": added, "removed": removed, "diff": diff}


def package(source: Path, skill: str, out: Path) -> Path:
    """The claude.ai upload: a zip holding `<skill>/SKILL.md`, frontmatter reduced to name + description."""
    fields, body = _parse_frontmatter(source.read_text(encoding="utf-8"))
    fields = fields or {}
    head = "---\n" + "".join(f"{k}: {json.dumps(fields.get(k, ''), ensure_ascii=False)}\n" for k in COMPARED_FIELDS) + "---\n"
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{skill}/SKILL.md", head + body)
    return out


def run(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skill", default=DEFAULT_SKILL)
    ap.add_argument("--synced", action="append", help="a synced SKILL.md to compare (repeatable)")
    ap.add_argument("--home", default=str(Path.home()), help="where discovery looks (default ~)")
    ap.add_argument("--root", default=str(ROOT), help=argparse.SUPPRESS)
    ap.add_argument("--diff-lines", type=int, default=40, help="diff lines printed per drifted copy (0 = all)")
    ap.add_argument("--package", metavar="OUT.zip", help="build the claude.ai upload zip from the repo source and exit")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    source = repo_source(args.skill, Path(args.root))
    if not source.is_file():
        print(f"FAIL: no repo source at {source}", file=sys.stderr)
        return 2
    if args.package:
        print(f"packaged {source} -> {package(source, args.skill, Path(args.package))}")
        return 0

    copies = find_copies(args.skill, args.synced, Path(args.home).expanduser())
    copies = [c for c in copies if c.exists()] if not args.synced else copies
    if not copies:
        print(json.dumps({"skill": args.skill, "state": "skipped", "reason": SKIPPED}) if args.json else SKIPPED)
        return 0
    results = [compare(source, c) for c in copies]
    bad = [r for r in results if r["state"] != "in_sync"]
    if args.json:
        print(json.dumps({"skill": args.skill, "source": str(source), "copies": results, "drift": len(bad)}, indent=2))
    else:
        for r in results:
            if r["state"] == "in_sync":
                print(f"in sync: {r['path']}")
                continue
            if r["state"] == "unreadable":
                print(f"DRIFT (unreadable, {r['error']}): {r['path']}")
                continue
            print(f"DRIFT: {r['path']} (+{r['added']} -{r['removed']} normalised lines vs {source.relative_to(Path(args.root))})")
            shown = r["diff"] if args.diff_lines == 0 else r["diff"][: args.diff_lines]
            print("\n".join(f"    {d}" for d in shown))
            if len(shown) < len(r["diff"]):
                print(f"    ... {len(r['diff']) - len(shown)} more diff lines (--diff-lines 0 for all)")
        print(f"{args.skill}: {len(results) - len(bad)} of {len(results)} synced copies match the repo source")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(run())
