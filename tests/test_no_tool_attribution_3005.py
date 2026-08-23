"""#3005 — the no-tool-attribution guard.

The owner's 2026-08-12 authorship decision (CLAUDE.md "Authorship") bans
tool-attribution trailers on commits and PRs. Four tracked files were found still
instructing the old convention — one of them driving the unattended remediation
agent — and nothing enforced the ban: it held only because CLAUDE.md is in context
at interactive sessions.

Guard choice (recorded per the issue's acceptance): a TEST, not a commit-msg hook
or CI step — it runs in every lane including the #3025 pre-merge full suite, needs
no per-clone hook installation (the hook is generated and untracked, so a hook
check protects only clones that re-ran install_hooks.sh), and mutation-proves at
the predicate level.

Two halves:
1. Instruction surface — no tracked file outside the allowlist may mention the
   trailer at all. The allowlist is exactly the files that state the BAN.
2. Reachable history — no commit message on the current branch since the decision
   date may carry the trailer.

`.claude/worktrees/**` copies are deliberately out of scope: they are separate
worktree checkouts (never listed by `git ls-files` here), stale snapshots of old
briefs, not a live instruction surface.
"""

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Files allowed to contain the trailer string because they STATE the ban.
ALLOWLIST = {
    "CLAUDE.md",  # the owner decision itself, which quotes the banned trailer
    "tests/test_no_tool_attribution_3005.py",  # this guard
}

BAN_DATE = "2026-08-12"

# The instruction-surface pattern: any mention of the trailer name.
_MENTION = re.compile(r"co-authored-by", re.IGNORECASE)

# The history pattern: an actual trailer crediting a Claude model.
_TRAILER = re.compile(r"^\s*co-authored-by:.*\bclaude\b", re.IGNORECASE | re.MULTILINE)

_TEXT_SUFFIXES = {".md", ".py", ".sh", ".yml", ".yaml", ".txt", ".json", ".toml", ".cfg", ".ini"}


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout


def message_carries_trailer(message: str) -> bool:
    """True when a commit message carries a Claude tool-attribution trailer."""
    return bool(_TRAILER.search(message))


def file_mentions_trailer(text: str) -> bool:
    """True when file content mentions the trailer name at all."""
    return bool(_MENTION.search(text))


def test_predicates_fire_on_planted_positives():
    # Mutation proof (CONVENTIONS §9): the guard must be able to fail.
    planted = "fix(x): a change\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\n"
    assert message_carries_trailer(planted)
    assert message_carries_trailer("subject\n\nco-authored-by: CLAUDE opus <x@y>")
    assert file_mentions_trailer("changes carry a `Co-Authored-By` trailer")


def test_predicates_pass_benign_content():
    assert not message_carries_trailer("fix(x): co-authored the design doc with the team")
    # A non-Claude co-author trailer is a human credit, not a tool attribution.
    assert not message_carries_trailer("subject\n\nCo-Authored-By: Jane Doe <jane@example.com>")
    assert not file_mentions_trailer("commits carry the work, not the tooling")


def test_no_tracked_file_instructs_the_trailer():
    try:
        tracked = _git("ls-files").splitlines()
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("not a git checkout")
    offenders = []
    for rel in tracked:
        if rel in ALLOWLIST or Path(rel).suffix not in _TEXT_SUFFIXES:
            continue
        path = REPO_ROOT / rel
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if file_mentions_trailer(text):
            offenders.append(rel)
    assert not offenders, (
        f"tracked files mention the banned tool-attribution trailer: {offenders} — "
        "the owner decision (CLAUDE.md 'Authorship', 2026-08-12) bans instructing it; "
        "state the ban without the literal, or add a ban-stating file to ALLOWLIST"
    )


def test_reachable_history_carries_no_trailer_since_ban():
    try:
        log = _git("log", f"--since={BAN_DATE}", "--format=%H%n%B%x00")
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("not a git checkout")
    offenders = []
    for entry in log.split("\x00"):
        entry = entry.strip()
        if not entry:
            continue
        sha, _, body = entry.partition("\n")
        if message_carries_trailer(body):
            offenders.append(sha[:12])
    assert not offenders, (
        f"commits since {BAN_DATE} carry a Claude tool-attribution trailer: {offenders} — "
        "banned by the owner decision recorded in CLAUDE.md 'Authorship'"
    )
