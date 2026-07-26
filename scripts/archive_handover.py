#!/usr/bin/env python3
"""scripts/archive_handover.py — /wrap step (a): archive the outgoing handover (#1650).

THE PROBLEM
  `handovers/` grew to 489 tracked session transcripts on `main` — the second-largest
  directory in the repo and pure process exhaust (docs/ENGINEERING_STANDARDS.md §1:
  "Session handovers ... are engineering-log, not product — keep only the live pointer
  in-tree"). The old wrap ritual did `git mv handovers/HANDOVER_LATEST.md
  handovers/HANDOVER_<date>_<slug>.md`, i.e. it added one more file to `main` every
  session — an unbounded ratchet in the wrong direction.

THE FIX (owner decision on #1650, 2026-07-25 — archive branch in THIS repo)
  The dated handovers live on the `session-archive` branch. This script appends the
  outgoing `HANDOVER_LATEST.md` to that branch and leaves `main`'s working tree alone;
  the wrap then overwrites `handovers/HANDOVER_LATEST.md` in place with the new session's
  handover. `main` therefore carries exactly one handover, forever.

WHY PLUMBING, NOT A CHECKOUT
  The commit is built with `read-tree` / `update-index` / `write-tree` / `commit-tree`
  against a TEMPORARY index. `session-archive` is never checked out, `HEAD` never moves,
  and the working tree is never touched — which matters because wraps routinely run with
  several concurrent worktrees active (the documented worktree-pollution incident class).

USAGE
  python3 scripts/archive_handover.py --slug cycle-11-reset            # archive + push
  python3 scripts/archive_handover.py --slug foo --dry-run             # preview only
  python3 scripts/archive_handover.py --slug foo --no-push             # local ref only
  python3 scripts/archive_handover.py --name HANDOVER_2026-07-26_x.md  # explicit target

  Exit 0 = archived (or already identical — the script is idempotent). Exit 1 = refused,
  with the reason on stderr; nothing is written on any refusal.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LATEST_NAME = "HANDOVER_LATEST.md"
ARCHIVE_BRANCH = "session-archive"
ARCHIVE_DIR = "handovers"
REMOTE = "origin"

# `HANDOVER_<YYYY-MM-DD>_<Slug>.md` — the naming convention every dated handover follows.
NAME_RE = re.compile(r"^HANDOVER_(\d{4}-\d{2}-\d{2})_[A-Za-z0-9][A-Za-z0-9._-]*\.md$")
DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
SLUG_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def git(*args: str, env: dict[str, str] | None = None, check: bool = True) -> str:
    """Run a git command in the repo and return its stripped stdout."""
    proc = subprocess.run(
        ["git", *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if check and proc.returncode != 0:
        raise RuntimeError("git %s failed (%d): %s" % (" ".join(args), proc.returncode, proc.stderr.strip()))
    return proc.stdout.strip()


def _rev_parse(ref: str) -> str | None:
    """The sha `ref` resolves to, or None if it does not exist."""
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", ref + "^{commit}"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    out = proc.stdout.strip()
    return out or None


def resolve_base(fetch: bool = True) -> tuple[str | None, str | None]:
    """(base_commit, source_ref) for the archive branch — remote wins over local.

    Returns (None, None) when the branch does not exist anywhere yet; the caller then
    decides whether to seed it (--allow-create).
    """
    if fetch:
        # Best-effort: an offline wrap must still be able to build the commit locally.
        subprocess.run(
            ["git", "fetch", REMOTE, ARCHIVE_BRANCH],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
    for ref in (f"{REMOTE}/{ARCHIVE_BRANCH}", ARCHIVE_BRANCH):
        sha = _rev_parse(ref)
        if sha:
            return sha, ref
    return None, None


def derive_name(text: str, slug: str | None, date: str | None) -> str:
    """The dated archive filename for this handover.

    Date comes from --date, else the first YYYY-MM-DD in the handover's first 40 lines
    (its title/verified line). Slug comes from --slug, else the handover's H1 title.
    """
    if not date:
        head = "\n".join(text.splitlines()[:40])
        m = DATE_RE.search(head)
        if not m:
            raise ValueError("no YYYY-MM-DD found in the handover's first 40 lines — pass --date")
        date = m.group(1)
    if not slug:
        m = re.search(r"^#\s+(.+)$", text, re.M)
        if not m:
            raise ValueError("no H1 title found in the handover — pass --slug")
        slug = m.group(1)
    slug = SLUG_SAFE_RE.sub("-", slug.strip()).strip("-.")[:60]
    if not slug:
        raise ValueError("slug reduced to empty after sanitising — pass an explicit --slug")
    return f"HANDOVER_{date}_{slug}.md"


def existing_blob(base: str, path: str) -> str | None:
    """The blob sha already stored at `path` on the archive branch, or None."""
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{base}:{path}"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    out = proc.stdout.strip()
    return out or None


def build_commit(base: str | None, path: str, blob: str, message: str) -> str:
    """Write a commit adding `blob` at `path` on top of `base` (temp index; no checkout)."""
    fd, index_path = tempfile.mkstemp(prefix="archive_handover_index_")
    os.close(fd)
    os.unlink(index_path)  # git wants to create the index itself
    env = dict(os.environ, GIT_INDEX_FILE=index_path)
    try:
        if base:
            git("read-tree", base, env=env)
        else:
            git("read-tree", "--empty", env=env)
        git("update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", env=env)
        tree = git("write-tree", env=env)
    finally:
        if os.path.exists(index_path):
            os.unlink(index_path)
    args = ["commit-tree", tree]
    if base:
        args += ["-p", base]
    args += ["-m", message]
    return git(*args)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Archive the outgoing handover onto the session-archive branch (#1650).")
    ap.add_argument("--file", help="handover to archive (default: handovers/HANDOVER_LATEST.md)")
    ap.add_argument("--slug", help="session slug for the archive filename (default: derived from the H1 title)")
    ap.add_argument("--date", help="YYYY-MM-DD for the archive filename (default: derived from the handover)")
    ap.add_argument("--name", help="explicit archive filename, overrides --slug/--date")
    ap.add_argument("--dry-run", action="store_true", help="print what would happen; write nothing")
    ap.add_argument("--no-push", action="store_true", help="update the local ref only, do not push")
    ap.add_argument("--no-fetch", action="store_true", help="skip the pre-flight fetch of the archive branch")
    ap.add_argument("--force", action="store_true", help="overwrite an existing, differing archive entry")
    ap.add_argument("--allow-create", action="store_true", help="seed the archive branch if it does not exist yet")
    args = ap.parse_args(argv)

    # Resolved here, not at import time: ROOT is monkeypatchable (tests) and a wrap may
    # run the script from any cwd.
    src = Path(args.file) if args.file else ROOT / ARCHIVE_DIR / LATEST_NAME
    if not src.is_file():
        print(f"❌ no handover at {src}", file=sys.stderr)
        return 1
    text = src.read_text(encoding="utf-8")
    if not text.strip():
        print(f"❌ {src} is empty — refusing to archive a blank handover", file=sys.stderr)
        return 1

    try:
        name = args.name or derive_name(text, args.slug, args.date)
    except ValueError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    if not NAME_RE.match(name):
        print(f"❌ '{name}' is not of the form HANDOVER_<YYYY-MM-DD>_<Slug>.md", file=sys.stderr)
        return 1
    path = f"{ARCHIVE_DIR}/{name}"

    base, base_ref = resolve_base(fetch=not args.no_fetch)
    if base is None and not args.allow_create:
        print(
            f"❌ branch '{ARCHIVE_BRANCH}' not found locally or on {REMOTE} — "
            f"fetch it (`git fetch {REMOTE} {ARCHIVE_BRANCH}`) or pass --allow-create to seed it",
            file=sys.stderr,
        )
        return 1

    blob_now = existing_blob(base, path) if base else None
    if args.dry_run:
        print(f"[dry-run] archive {src} → {ARCHIVE_BRANCH}:{path}")
        print(f"[dry-run] base = {base_ref or '(new branch)'} {base or ''}")
        if blob_now:
            print(f"[dry-run] NOTE: {path} already exists on {ARCHIVE_BRANCH}" + ("" if args.force else " — would refuse without --force"))
        print("[dry-run] push: " + ("no (--no-push)" if args.no_push else f"{REMOTE} {ARCHIVE_BRANCH}"))
        return 0

    blob = git("hash-object", "-w", "--", str(src))
    if blob_now == blob:
        print(f"✅ {path} is already on {ARCHIVE_BRANCH} with identical content — nothing to do")
        return 0
    if blob_now and not args.force:
        print(
            f"❌ {path} already exists on {ARCHIVE_BRANCH} with different content — pass --force or choose another --slug", file=sys.stderr
        )
        return 1

    message = f"docs(session-archive): {name}\n\nArchived from main's handovers/HANDOVER_LATEST.md by /wrap step (a) (#1650)."
    commit = build_commit(base, path, blob, message)
    # update-ref with the old value is a compare-and-swap: a concurrent wrap that moved the
    # branch under us fails loudly here instead of silently dropping its commit.
    if base:
        git("update-ref", f"refs/heads/{ARCHIVE_BRANCH}", commit, base)
    else:
        git("update-ref", f"refs/heads/{ARCHIVE_BRANCH}", commit)
    print(f"✅ archived {src.name} → {ARCHIVE_BRANCH}:{path} ({commit[:8]})")

    if args.no_push:
        print(f"   (--no-push: local ref only — run `git push {REMOTE} {ARCHIVE_BRANCH}` to publish)")
        return 0
    proc = subprocess.run(
        ["git", "push", REMOTE, f"refs/heads/{ARCHIVE_BRANCH}:refs/heads/{ARCHIVE_BRANCH}"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        print(f"❌ push failed: {proc.stderr.strip()}", file=sys.stderr)
        print(f"   the commit is safe on the local '{ARCHIVE_BRANCH}' ref — re-run the push once resolved", file=sys.stderr)
        return 1
    print(f"✅ pushed {ARCHIVE_BRANCH} to {REMOTE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
