#!/usr/bin/env python3
"""scripts/hooks/session_preflight.py — SessionStart: the state a session must not guess.

WHY
  Session E lost three of its four rework cycles to gates that were knowable at boot. The
  canonical evidence: `wrap_gates.py` printed COACH_STANCE.md at 0d headroom in the boot
  output, and that exact doc redded a PR an hour later. Session F pre-flighted the same
  four classes and lost zero.

  Sessions also repeatedly BOOT ON A RED MAIN inherited from the previous wrap, and find a
  stranded production deploy lease every single session — in three of them, approving the
  lease would have rolled back live-deployed fixes.

WHAT IT PRINTS
  Only things a session would otherwise guess or discover expensively: main's real state,
  any waiting deploy lease, worktree hygiene, and the corpus gate. Everything is derived
  live; nothing is remembered. Each line degrades to an explicit "unverified" rather than
  a silent omission — a check that cannot run must say so, because a blank line reads as
  a pass (the #2578 class this repo has paid for repeatedly).

NEVER BLOCKS
  SessionStart output is context, not a gate. It always exits 0.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hooklib import ROOT, gh, git  # noqa: E402


def _main_green() -> str:
    code, out = git("rev-parse", "--abbrev-ref", "HEAD")
    branch = out if code == 0 else "?"
    code, out = gh(
        "api",
        "repos/averagejoematt/life-platform/actions/runs?branch=main&per_page=8",
        "--jq",
        '[.workflow_runs[]|select(.name=="CI/CD")][0]|"\\(.conclusion // .status) \\(.head_sha[0:9])"',
    )
    if code != 0 or not out or out.startswith("null"):
        state = "UNVERIFIED (could not query — this is not a pass)"
    else:
        state = out
    return f"branch={branch}  main CI/CD={state}"


def _waiting_lease() -> str:
    code, out = gh(
        "api",
        "repos/averagejoematt/life-platform/actions/runs?status=waiting&per_page=10",
        "--jq",
        '[.workflow_runs[]|"\\(.head_sha[0:9]) \\(.created_at)"]|join("; ")',
    )
    if code != 0:
        return "UNVERIFIED (could not query)"
    if not out or out == "null":
        return "none"
    return f"{out}  — dispose it: approve or REJECT, never leave waiting"


def _worktrees() -> str:
    code, out = git("worktree", "list")
    if code != 0:
        return "UNVERIFIED"
    lines = [ln for ln in out.splitlines() if ln.strip()]
    # Path containment, NOT a substring test: `<repo>-worktrees/` starts with `<repo>`,
    # so `str(ROOT) in path` called eleven external worktrees "inside the repo". A
    # pre-flight that cries wolf every session is a pre-flight nobody reads.
    inside = []
    for ln in lines:
        cand = Path(ln.split()[0])
        if cand == ROOT:
            continue
        try:
            cand.relative_to(ROOT)
            inside.append(ln)
        except ValueError:
            pass
    note = f"{len(lines)} total"
    if inside:
        note += f"; {len(inside)} INSIDE the repo — repo-wide sweeps walk them"
    return note


def _boot_brief() -> list[str]:
    """The boot contract (#3314): the architecture facts a session reads FROM THE MODEL,
    rendered by scripts/boot_brief.py. Loaded by path (this hook runs outside any
    package). A failure prints an explicit UNVERIFIED line — never a blank."""
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location("_boot_brief", ROOT / "scripts" / "boot_brief.py")
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        sys.modules[spec.name] = mod  # spec-loaded modules must be registered before exec
        spec.loader.exec_module(mod)
        return mod.render_lines(mod.load_model())
    except Exception as exc:  # noqa: BLE001 — fail open, say so
        return [f"  model       UNVERIFIED (boot brief failed: {type(exc).__name__}: {exc})"]


def main() -> int:
    print("── session pre-flight " + "─" * 46)
    print(f"  main        {_main_green()}")
    print(f"  deploy lease {_waiting_lease()}")
    print(f"  worktrees   {_worktrees()}")
    for line in _boot_brief():
        print(line)
    print("  gates       python3 scripts/wrap_gates.py           (headroom per lane)")
    print("              python3 scripts/skill_lint.py --offline  (skill corpus)")
    print("─" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())
