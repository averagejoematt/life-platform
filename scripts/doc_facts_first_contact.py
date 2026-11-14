#!/usr/bin/env python3
"""scripts/doc_facts_first_contact.py — the #5937 first-contact rules for check_doc_facts.py.

WHY THIS MODULE EXISTS
  The 2026-11-13 `/review full` (devex-1, r2:devex-1, r2:devex-5) found three statements a
  fresh agent reads FIRST in CLAUDE.md, all wrong, under a green `check_doc_facts.py`:

    CLAUDE.md  "Deploy (manual approval, GitHub Environment `production`)"
               -> ci-cd.yml's header: code ships on green, NO manual approval (ADR-158,
                  #4256); only the additive-IAM job `deploy-iam` waits on the click
    CLAUDE.md  "black --check lambdas/ mcp/ cdk/ tests/ scripts/ deploy/"
               -> ci-lint.yml's Format gate also checks `qa/`
    CLAUDE.md  "**Status:** ... (Verified 2026-11-02)"
               -> 11 days and 191 commits behind main at review time; nothing aged it

  Each rule below is keyed to the file that is the truth (the ci-cd.yml header comment,
  the ci-lint.yml Format gate step, git history), and each fails LOUD when it cannot find
  its own anchor — a rule that returns [] because its regex stopped matching is a rule
  that can no longer fail (#1189/#2578).

  Rules 1 and 2 are BLOCKING hits. Rule 3 (the status-stamp age) is WARN-ONLY by the
  issue's contract — it is printed and never folded into the failing list, because the
  fix for it is a /wrap step, not a code change, and a gate that reds every lane between
  wraps would be ignored.
"""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLAUDE_MD = ROOT / "CLAUDE.md"
CI_CD_YML = ROOT / ".github" / "workflows" / "ci-cd.yml"
CI_LINT_YML = ROOT / ".github" / "workflows" / "ci-lint.yml"

# ── rule 1: "manual approval" must name IAM in the same sentence ──────────────
# Keyed to ci-cd.yml's header comment: while that header says code ships with NO manual
# approval, a CLAUDE.md sentence may only say "manual approval" if it also names the one
# job that still has it (`deploy-iam` / IAM). If the header stops saying so, the rule
# reds rather than silently policing a premise that is no longer true.
HEADER_NO_APPROVAL_RE = re.compile(r"NO manual approval", re.I)
MANUAL_APPROVAL_RE = re.compile(r"manual approval", re.I)
NAMES_IAM_RE = re.compile(r"deploy-iam|\bIAM\b")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z`*(\[])")


def _header_comment(text: str) -> str:
    """The leading `#` comment block of a workflow file (stops at the first non-comment line)."""
    out = []
    for line in text.splitlines():
        if line.startswith("#"):
            out.append(line)
        elif line.strip():
            break
    return "\n".join(out)


def manual_approval_hits(claude_text: str, ci_cd_text: str, rel: str = "CLAUDE.md") -> list[str]:
    header = _header_comment(ci_cd_text)
    if not HEADER_NO_APPROVAL_RE.search(header):
        return [
            f"{CI_CD_YML.relative_to(ROOT)}: header comment no longer says 'NO manual approval' — the #5937 "
            "manual-approval rule is keyed to it; re-key the rule to the new deploy contract"
        ]
    hits = []
    for lineno, line in enumerate(claude_text.splitlines(), 1):
        if not MANUAL_APPROVAL_RE.search(line):
            continue
        for sentence in _SENTENCE_SPLIT.split(line):
            if MANUAL_APPROVAL_RE.search(sentence) and not NAMES_IAM_RE.search(sentence):
                hits.append(
                    f"{rel}:{lineno}: says 'manual approval' without naming deploy-iam/IAM in the same sentence — "
                    "ci-cd.yml: code ships on green, only deploy-iam waits on the click (ADR-158, #4256, #5937)\n"
                    f"      | {sentence.strip()[:120]}"
                )
    return hits


# ── rule 2: the documented format command is ci-lint.yml's Format gate ────────
DOC_BLACK_RE = re.compile(r"`black --check([^`]*)`")


def _dirs(arg_tail: str) -> list[str]:
    return [tok for tok in arg_tail.split() if not tok.startswith("-")]


def ci_format_dirs(ci_lint_text: str) -> list[str] | None:
    """The dirs of the `run: black --check …` line inside ci-lint.yml's `Format gate` step."""
    in_step = False
    for line in ci_lint_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- name:"):
            in_step = stripped.startswith("- name: Format gate")
            continue
        if in_step and stripped.startswith("run: black --check"):
            return _dirs(stripped[len("run: black --check") :])
    return None


def format_command_hits(claude_text: str, ci_lint_text: str, rel: str = "CLAUDE.md") -> list[str]:
    truth = ci_format_dirs(ci_lint_text)
    if not truth:
        return [
            f"{CI_LINT_YML.relative_to(ROOT)}: could not find the 'Format gate' step's `black --check` run line — "
            "the #5937 format-command rule went blind"
        ]
    hits, seen = [], 0
    for lineno, line in enumerate(claude_text.splitlines(), 1):
        for mo in DOC_BLACK_RE.finditer(line):
            seen += 1
            claimed = _dirs(mo.group(1))
            if claimed != truth:
                hits.append(
                    f"{rel}:{lineno}: format command checks {' '.join(claimed)}, ci-lint.yml's Format gate checks "
                    f"{' '.join(truth)} (#5937)\n      | {mo.group(0)[:120]}"
                )
    if not seen:
        hits.append(f"{rel}: no `black --check …` command found — the #5937 format-command rule went blind")
    return hits


# ── rule 3 (WARN-ONLY): the status pointer's Verified stamp vs main ───────────
# Measured against HEAD's commit date, not the wall clock, so the verdict is a property
# of the tree being checked. BOTH thresholds must be exceeded: a quiet week is not stale,
# and a 200-commit day the wrap is about to stamp is not stale either.
STATUS_STAMP_RE = re.compile(r"^\*\*Status:\*\*[^\n]*\(Verified (\d{4}-\d{2}-\d{2})\)", re.MULTILINE)
STATUS_STAMP_MAX_DAYS = 7
STATUS_STAMP_MAX_COMMITS = 100


def status_stamp(claude_text: str) -> str | None:
    mo = STATUS_STAMP_RE.search(claude_text)
    return mo.group(1) if mo else None


def status_stamp_warnings(
    stamp: str | None,
    head_date: str,
    commits_since: int,
    max_days: int = STATUS_STAMP_MAX_DAYS,
    max_commits: int = STATUS_STAMP_MAX_COMMITS,
) -> list[str]:
    """Pure: the warning(s) for a stamp `stamp`, HEAD dated `head_date`, `commits_since` commits after it."""
    import datetime as _dt

    if stamp is None:
        return ["CLAUDE.md: no `**Status:** … (Verified YYYY-MM-DD)` line — the #5937 status-stamp age check went blind"]
    age = (_dt.date.fromisoformat(head_date) - _dt.date.fromisoformat(stamp)).days
    if age > max_days and commits_since > max_commits:
        return [
            f"CLAUDE.md: status pointer Verified {stamp} trails main by {age}d and {commits_since} commits "
            f"(advisory: > {max_days}d AND > {max_commits} commits) — run /wrap to refresh the handover + pointer (#5937)"
        ]
    return []


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def live_status_stamp_warnings() -> tuple[list[str], str | None]:
    """(warnings, skip_notice). A shallow clone cannot count commits, so it is a loud SKIP, never a pass."""
    stamp = status_stamp(CLAUDE_MD.read_text(encoding="utf-8"))
    if stamp is None:
        return status_stamp_warnings(None, "1970-01-01", 0), None
    try:
        if _git("rev-parse", "--is-shallow-repository") == "true":
            return [], "shallow clone — commit count since the CLAUDE.md status stamp is unknowable here"
        head_date = _git("log", "-1", "--format=%cs", "HEAD")
        commits = int(_git("rev-list", "--count", f"--since={stamp}T23:59:59", "HEAD"))
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError) as exc:
        return [], f"git unavailable for the status-stamp age check ({exc.__class__.__name__})"
    return status_stamp_warnings(stamp, head_date, commits), None
