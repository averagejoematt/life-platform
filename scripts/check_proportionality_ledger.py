#!/usr/bin/env python3
"""scripts/check_proportionality_ledger.py — the /wrap proportionality-ledger gate (#2380, enforced by #2761).

THE PROBLEM
  The #2380 gate was four lines of prose wedged into the header of wrap step (e10) — no
  step letter of its own, no script, no required handover line, no guardrail bullet. Its
  trigger was a conditional ("IF this session landed a NEW standing CI gate, scheduled
  writer, or watcher ...") that nothing ever evaluated, so it was a check that could not
  fail. Measured (#2761): zero `docs/PROPORTIONALITY.md` commits 2026-08-10 → 2026-08-16
  while four standing subsystems shipped with real rent (#2572, #2552, #2527, #2578), and
  zero `ledger:` lines in any handover of that week. The ledger became a snapshot exactly
  the way the gate's own last sentence predicted.

THE FIX (the #1332 shape: explicit line or fail, never silence)
  The conditional becomes unconditional and the assertion becomes a script. The gate
  passes only when at least one of these holds:
    - `docs/PROPORTIONALITY.md` has a diff this session (working tree / staged, or a
      commit since the previous `docs(wrap)` commit) — the row actually landed; or
    - the handover carries an explicit `**Ledger:**` line, one of:
        `**Ledger:** <subsystem> row added/updated`   (requires the diff above — a line
                                                       claiming a row the ledger never
                                                       saw is the silent pass this gate
                                                       exists to kill)
        `**Ledger:** omitted — <reason>`              (standing machinery shipped, row
                                                       deliberately deferred, on record)
        `**Ledger:** none — <reason>`                 (no standing machinery shipped)
  A handover with neither a diff nor a line FAILS — silent omission is not an outcome.

USAGE
  python3 scripts/check_proportionality_ledger.py [HANDOVER_PATH] [--diff auto|yes|no]
    HANDOVER_PATH defaults to handovers/HANDOVER_LATEST.md. `--diff` overrides the git
    diff detection (test hook; `auto` reads git). Exits 1 on a failing wrap input.
  If git is unreachable in `auto` mode the diff leg reads UNVERIFIED and only an explicit
  `**Ledger:**` line can pass — degrade is loud, never a silent green (#2938 class).
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HANDOVER = ROOT / "handovers" / "HANDOVER_LATEST.md"
LEDGER_REL = "docs/PROPORTIONALITY.md"

# A dedicated line (`**Ledger:** ...`, at line start, the (d)/(e)/(e3) house shape) or the
# original #2380 inline form (`ledger: omitted — <reason>` anywhere). Prose mentions like
# "the session ledger;" or "calibration ledger" carry no colon and never match.
LEDGER_LINE = re.compile(r"^\s*\*{0,2}ledger\*{0,2}\s*:\s*(.*)$", re.I)
INLINE_OMITTED = re.compile(r"\bledger\s*:\s*(omitted\b.*)$", re.I | re.M)
_DASH_REASON = r"\s*[-–—]\s*\S"  # hyphen / en-dash / em-dash, then a real reason


def find_ledger_claims(text: str) -> list:
    """Every ledger declaration in the handover (dedicated lines + inline omitted form)."""
    claims = []
    for line in text.splitlines():
        m = LEDGER_LINE.match(line)
        if m:
            claims.append(m.group(1).strip().strip("*").strip())
    if not claims:
        claims.extend(m.group(1).strip() for m in INLINE_OMITTED.finditer(text))
    return claims


def classify(claim: str) -> str:
    """'omitted' | 'none' | 'row' | 'malformed' for one ledger claim body.

    Exposed as a plain function (not folded into main()) so the regression test can prove
    the rule bites, per the check_doc_facts.py "vacuous scan" house style (#1189).
    """
    if re.match(rf"omitted{_DASH_REASON}", claim, re.I):
        return "omitted"
    if re.match(rf"none{_DASH_REASON}", claim, re.I):
        return "none"
    if re.match(r"(omitted|none)\b", claim, re.I):
        return "malformed"  # the form without a reason — an alibi, not a record
    if claim:
        return "row"
    return "malformed"


def ledger_diff_this_session(root: Path):
    """True/False for a docs/PROPORTIONALITY.md diff this session; None if git is unreachable.

    "This session" = anything uncommitted (worktree or index) plus anything committed
    since the most recent `docs(wrap)` commit — the session boundary every other wrap
    artifact already uses (#365).
    """
    try:
        porcelain = subprocess.run(["git", "status", "--porcelain", "--", LEDGER_REL], cwd=root, capture_output=True, text=True, timeout=30)
        if porcelain.returncode != 0:
            return None
        if porcelain.stdout.strip():
            return True
        last_wrap = subprocess.run(
            ["git", "log", "--format=%H", "--grep", r"^docs(wrap", "-n", "1"], cwd=root, capture_output=True, text=True, timeout=30
        )
        if last_wrap.returncode != 0:
            return None
        boundary = last_wrap.stdout.strip()
        if not boundary:
            return False  # no wrap commit in history — only the explicit line can pass
        since = subprocess.run(
            ["git", "log", "--format=%H", f"{boundary}..HEAD", "--", LEDGER_REL], cwd=root, capture_output=True, text=True, timeout=30
        )
        if since.returncode != 0:
            return None
        return bool(since.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return None


def evaluate(handover_text: str, ledger_diff) -> tuple:
    """(ok, messages) for one wrap input. Pure — the tests drive this directly.

    `ledger_diff` is True / False / None (None = git unreachable, UNVERIFIED)."""
    messages = []
    claims = find_ledger_claims(handover_text)

    if not claims:
        if ledger_diff is True:
            messages.append(f"OK — {LEDGER_REL} has a diff this session (the row landed).")
            messages.append("note: add a `**Ledger:** <subsystem> row added` line to the handover so the record names it.")
            return True, messages
        if ledger_diff is None:
            messages.append(f"UNVERIFIED — git unreachable, cannot check {LEDGER_REL} for a session diff.")
        messages.append(
            "FAIL — no `**Ledger:**` line in the handover and no docs/PROPORTIONALITY.md diff this session (#2380/#2761).\n"
            "  If standing machinery shipped (CI gate, scheduled writer, watcher, alarm, workflow): add its row\n"
            "  (posture + rent + demote trigger, ADR-103/144) or write `**Ledger:** omitted — <reason>`.\n"
            "  If nothing standing shipped: write `**Ledger:** none — no standing machinery shipped`.\n"
            "  Silent omission is how the ledger became a snapshot."
        )
        return False, messages

    ok = True
    for claim in claims:
        kind = classify(claim)
        if kind == "malformed":
            ok = False
            messages.append(f"FAIL — ledger line needs an explicit `— <reason>` after omitted/none, got: {claim!r}")
        elif kind in ("omitted", "none"):
            messages.append(f"OK — explicit ledger call on record: {claim!r}")
        elif kind == "row":
            if ledger_diff is True:
                messages.append(f"OK — ledger row claimed and {LEDGER_REL} has a diff this session: {claim!r}")
            elif ledger_diff is None:
                messages.append(f"UNVERIFIED — row claimed ({claim!r}) but git unreachable; verify the {LEDGER_REL} diff by hand.")
            else:
                ok = False
                messages.append(
                    f"FAIL — the handover claims a ledger row ({claim!r}) but {LEDGER_REL} has no diff this session.\n"
                    "  Land the row, or write `**Ledger:** omitted — <reason>` instead — a claimed row the ledger\n"
                    "  never saw is the exact silent pass this gate replaces."
                )
    return ok, messages


def main() -> int:
    args = [a for a in sys.argv[1:]]
    diff_mode = "auto"
    if "--diff" in args:
        i = args.index("--diff")
        try:
            diff_mode = args[i + 1]
        except IndexError:
            print("--diff requires auto|yes|no")
            return 2
        del args[i : i + 2]
    if diff_mode not in ("auto", "yes", "no"):
        print(f"unknown --diff mode {diff_mode!r} (want auto|yes|no)")
        return 2

    path = Path(args[0]) if args else DEFAULT_HANDOVER
    if not path.exists():
        print(f"{path} not found")
        return 1

    if diff_mode == "auto":
        ledger_diff = ledger_diff_this_session(ROOT)
    else:
        ledger_diff = diff_mode == "yes"

    ok, messages = evaluate(path.read_text(encoding="utf-8"), ledger_diff)
    for m in messages:
        print(m)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
