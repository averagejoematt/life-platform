"""No unresolved merge-conflict markers may reach main.

WHY THIS EXISTS (2026-08-08): a reconcile of PR #2200 left literal conflict
markers in `docs/TESTING.md` and they merged to main unnoticed. The rebase
conflicted on the doc-sync literal; the resolution ran
`deploy/sync_doc_metadata.py --apply`, which rewrote the numeric literal on BOTH
sides of the conflict — making the two sides byte-identical — and then `git add`
staged the file with its markers intact. Every existing gate passed:

  * `sync_doc_metadata.py --check` passed, because the literal it greps for was
    present (twice) and correct.
  * lint/format/test gates never look at markdown prose.
  * `check_main_green.py` reported GREEN.

So the failure mode is specifically "a conflict whose two sides are identical",
which is exactly the doc-literal conflict class this repo hits on nearly every
concurrent PR — the most likely conflict here is the one least likely to look
wrong. Nothing in the repo grepped for the markers themselves. Now something does.

The file SET is derived from `git ls-files`, never hardcoded (the standing
"guard the SET, not the instance" rule — a hardcoded path list would stop
covering new files the moment one was added).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Built at runtime so this guard file can never match itself.
_CONFLICT_PREFIXES = ("<" * 7, "=" * 7, ">" * 7)

# Binary/opaque suffixes: a byte sequence inside them is not a conflict marker.
_SKIP_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".svg",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".eot",
    ".zip",
    ".gz",
    ".pdf",
    ".mp4",
    ".mov",
    ".mp3",
    ".wav",
}


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [p for p in out.split("\0") if p]


def _offending_lines(path: Path) -> list[tuple[int, str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []  # not decodable as text -> not our business
    hits = []
    for n, line in enumerate(text.splitlines(), start=1):
        stripped = line.rstrip()
        for prefix in _CONFLICT_PREFIXES:
            # "=======" is only a marker on a line of its own; "<<<<<<< " and
            # ">>>>>>> " carry a label. Requiring that shape keeps rows of ===
            # used as markdown/ASCII rules from false-positiving.
            if stripped == prefix or line.startswith(prefix + " "):
                hits.append((n, stripped[:80]))
                break
    return hits


def test_no_unresolved_conflict_markers_in_tracked_files():
    """A tracked file carrying a conflict marker is an unfinished merge."""
    self_rel = str(Path(__file__).resolve().relative_to(REPO_ROOT))
    findings: list[str] = []

    for rel in _tracked_files():
        if rel == self_rel:
            continue
        path = REPO_ROOT / rel
        if path.suffix.lower() in _SKIP_SUFFIXES or not path.is_file():
            continue
        for lineno, snippet in _offending_lines(path):
            findings.append(f"{rel}:{lineno}: {snippet}")

    assert not findings, "unresolved merge-conflict markers on tracked files:\n" + "\n".join(findings)


def test_the_guard_actually_detects_a_marker(tmp_path):
    """Mutation-proof: the detector fires on a real conflict block.

    Without this, a refactor that broke `_offending_lines` would leave the guard
    above silently passing on everything — the exact 'a guard that does not
    guard' class this repo keeps rediscovering.
    """
    sample = tmp_path / "conflicted.md"
    sample.write_text(
        "\n".join(
            [
                "intro line",
                _CONFLICT_PREFIXES[0] + " HEAD",
                "ours",
                _CONFLICT_PREFIXES[1],
                "theirs",
                _CONFLICT_PREFIXES[2] + " some-branch",
                "tail line",
            ]
        ),
        encoding="utf-8",
    )
    hits = _offending_lines(sample)
    assert [n for n, _ in hits] == [2, 4, 6]


@pytest.mark.parametrize(
    "benign",
    [
        "===== a five-equals rule =====",
        "| col | col |",
        "some prose mentioning a rebase",
        "=" * 60,  # the repo's own banner rules, printed by deploy scripts
    ],
)
def test_guard_does_not_fire_on_benign_lines(tmp_path, benign):
    """Banner rules made of '=' are everywhere in this repo's script output."""
    sample = tmp_path / "benign.md"
    sample.write_text(benign + "\n", encoding="utf-8")
    assert _offending_lines(sample) == []
