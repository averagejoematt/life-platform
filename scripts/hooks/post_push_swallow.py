#!/usr/bin/env python3
"""scripts/hooks/post_push_swallow.py — PostToolUse: record a push, then check it late.

THE INCIDENT
  GitHub silently drops push events. Five in one night; one swallowed the WRAP commit
  itself, landing stale derived artifacts that nothing surfaced for ~7h. A guard wired on
  push cannot see a push that mints no runs — the only detection is asking, afterwards,
  whether any run exists at that sha.

WHY IT IS DEFERRED, NOT IMMEDIATE
  Runs take ~60-90s to appear, and a hook blocks the session while it runs. So this hook
  never waits: it RECORDS the sha, and on any later invocation checks the ones that are
  now old enough. The check drains itself, costs nothing when there is nothing pending,
  and reports at the next natural pause.

THE CONFOUND, HANDLED
  A `GITHUB_TOKEN` push (the reconcile bot) legitimately mints zero runs AND touches
  lambdas/**, so it looks identical to a swallow. Any zero-run detector without that
  discriminator pages after every merge and gets ignored. This one only records pushes
  made from an interactive session, and reports "unverified" rather than "swallowed" when
  it cannot tell — absence of proof is stated as such, never upgraded to proof of absence.

HEARD, AND NARROW (#4260)
  Findings reach the model as PostToolUse `additionalContext` (see _hooklib.emit) — the
  stderr they used to go to is the debug log. settings.json runs this hook only on a
  `git push` (`if: Bash(git push *)` / `Bash(git -C *)`), and it re-checks the command
  itself before it reads any state, so an ordinary Bash call costs no state I/O. The
  deferred check therefore drains at the NEXT push — the natural cadence of a lane. The
  pushed sha is read in the checkout the push ran in (the command's `cd`/`git -C`, else the
  payload cwd), not the session's checkout: a lane's push used to record main's HEAD.
"""

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hooklib import bash_command, command_cwd, emit, gh, git, ok, read_payload, state_path  # noqa: E402

_PUSH = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?push\b")
SETTLE_SECONDS = 90
STATE = "pending_pushes.json"


def _load() -> tuple[list[dict], str | None]:
    """Returns (rows, error). A missing file (nothing recorded yet) is NOT an error —
    only a state dir/file that exists but can't be read is. See the module contract
    above: absence of proof is stated as such, never swallowed into silence."""
    try:
        text = state_path(STATE).read_text()
    except FileNotFoundError:
        return [], None
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"
    try:
        return json.loads(text), None
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"


def _save(rows: list[dict]) -> str | None:
    """Returns an error string on failure, None on success — never swallows."""
    try:
        state_path(STATE).write_text(json.dumps(rows))
        return None
    except Exception as e:
        return f"{type(e).__name__}: {e}"


def main() -> int:
    cmd = bash_command(read_payload())
    push = _PUSH.search(cmd)
    if not push:
        return ok()  # settings' `if` should already have filtered this; no state I/O either way

    now = time.time()
    rows, load_err = _load()
    findings = []
    if load_err:
        findings.append(f"push record UNVERIFIED — could not read hook state ({load_err})")

    code, sha = git("rev-parse", "HEAD", cwd=command_cwd(cmd, push.end()))
    if code == 0 and len(sha) == 40 and not any(r.get("sha") == sha for r in rows):
        rows.append({"sha": sha, "at": now})

    due = [r for r in rows if now - r.get("at", 0) >= SETTLE_SECONDS]
    pending = [r for r in rows if now - r.get("at", 0) < SETTLE_SECONDS]

    for r in due:
        sha = r["sha"]
        # The FULL 40-char sha: a short sha misses `pull_request` runs (#3103).
        code, out = gh("api", f"repos/averagejoematt/life-platform/actions/runs?head_sha={sha}", "--jq", ".total_count")
        if code != 0 or not out.isdigit():
            findings.append(f"{sha[:12]}: UNVERIFIED — could not query runs (absence of proof, not proof of absence)")
        elif int(out) == 0:
            findings.append(f"{sha[:12]}: ZERO runs {int(now - r['at'])}s after push — treat as SWALLOWED")
            findings.append("  recovery ladder: close/reopen the PR -> supersede-PR -> integration train")
        # A nonzero count is the healthy case and says nothing.

    save_err = _save(pending)
    if save_err:
        findings.append(f"push record UNVERIFIED — could not write hook state ({save_err})")

    if findings:
        return emit("push event check", findings, event="PostToolUse")
    return ok()


if __name__ == "__main__":
    sys.exit(main())
