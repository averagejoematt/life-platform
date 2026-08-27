#!/usr/bin/env python3
"""scripts/wrap_gates.py — the /wrap gate battery in ONE pass (#3007, asserting #3006).

THE PROBLEM
  /wrap ran ~12 gate scripts sequentially, each a separate round-trip, and its step
  ordering sent the session back to re-edit `handovers/HANDOVER_LATEST.md` ~10 times —
  once per gate's marker line. The whole battery is ~10s of wall clock (measured
  2026-08-22); the cost was sequencing and attention, and the measured failure mode was
  whole-wrap collapse: 20 missing marker lines in a 25-handover window, all in 4 wraps.

THE SHAPE (gather → write → verify → commit)
  --gather (default)  Run every gate that does NOT read the finished handover, in
                      parallel (they are independent; several are network-bound), report
                      ALL failures together, and print a draft marker-line block with
                      each script-determined outcome pre-filled. The session writes the
                      handover ONCE, pasting and correcting the draft.
  --verify            Run the gates that DO read the finished handover — the #3006 line
                      assertion, the residual-queue gate, the proportionality-ledger
                      gate, and the beat validators — reporting all failures together.
                      Must exit 0 before the wrap commit (step (f)).

  Every gate's own semantics are preserved: this runner invokes the same scripts the
  lettered wrap steps document, with the same bare (blocking-default) invocations, and
  passes each script's exit code through unchanged into the combined verdict. Degrade
  behaviour (`UNVERIFIED`, fail-open on missing gh/AWS) belongs to the scripts and is
  SURFACED verbatim in this runner's per-gate output, never swallowed: a gate that
  fail-opens still prints its skip note here, and the draft line says `unverified`.

USAGE
  python3 scripts/wrap_gates.py            # gather phase (before writing the handover)
  python3 scripts/wrap_gates.py --verify   # verify phase (after writing it, before (f))
  python3 scripts/wrap_gates.py --list     # print the battery and exit
Exit 0 iff every gate in the requested phase passed (by its own exit code).
"""

import argparse
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_handover_lines  # noqa: E402  (same directory; the ONE marker derivation, #3006)
import check_main_green  # noqa: E402  (same directory; the ONE head-coverage state vocabulary, #3212)

TIMEOUT = 300  # seconds per gate; the whole battery is ~10s in practice


class Gate:
    def __init__(self, name, step, cmd, marker=None, ok_when=None):
        self.name = name  # short id, e.g. "main-green"
        self.step = step  # wrap.md step letter, e.g. "e2" — the doc anchor
        self.cmd = cmd  # argv list, run from repo root
        self.marker = marker  # handover marker this gate's outcome feeds, or None
        self.ok_when = ok_when  # optional (returncode, stdout) -> bool override


def _stash_ok(rc, out):
    return rc == 0 and not out.strip()


def _hooks_ok(rc, out):
    # session_postflight prints a "hook freshness" line; 🔴 means stale/not installed.
    return rc == 0 and "🔴" not in out


# ── the gather battery: every gate that does not read the finished handover ──────────
GATHER = [
    Gate("main-green", "e2", ["python3", "scripts/check_main_green.py"], marker="Main"),
    Gate("stash", "e5", ["git", "stash", "list"], marker="Stash/hooks", ok_when=_stash_ok),
    Gate("hooks", "e5", ["python3", "deploy/session_postflight.py"], marker="Stash/hooks", ok_when=_hooks_ok),
    Gate("backlog-hygiene", "e7", ["python3", "scripts/check_backlog_hygiene.py"]),
    Gate("alarm-citations", "e10", ["python3", "scripts/check_alarm_citations.py"], marker="Alarms"),
    Gate("ci-warnings", "e11", ["python3", "scripts/check_ci_warnings.py"], marker="CI warnings"),
    Gate("doc-links", "e", ["python3", "scripts/check_doc_links.py"]),
    Gate("doc-tombstones", "e", ["python3", "scripts/check_doc_tombstones.py"]),
    Gate("doc-index", "e", ["python3", "scripts/check_doc_index.py"]),
    Gate("adr-index", "e", ["python3", "scripts/generate_adr_index.py", "--check"]),
]

# ── the verify battery: gates that read the finished handover (run after writing it) ──
VERIFY = [
    Gate("handover-lines", "f", ["python3", "scripts/check_handover_lines.py"]),
    Gate("residual-queue", "e4", ["python3", "scripts/check_residual_queue.py"]),
    Gate("proportionality-ledger", "e12", ["python3", "scripts/check_proportionality_ledger.py"]),
    Gate("content-policy", "d", ["python3", "scripts/content_policy_scan.py"]),
    Gate("beats-schema", "d", ["python3", "scripts/validate_beats.py"]),
]


def run_gate(gate: Gate):
    try:
        p = subprocess.run(gate.cmd, cwd=ROOT, capture_output=True, text=True, timeout=TIMEOUT)
        out = (p.stdout or "") + (p.stderr or "")
        ok = gate.ok_when(p.returncode, out) if gate.ok_when else p.returncode == 0
        return gate, ok, p.returncode, out
    except (OSError, subprocess.SubprocessError) as e:
        return gate, False, None, f"(runner) could not execute {' '.join(gate.cmd)}: {e}"


# #3212: check_main_green.py ends with one machine-readable line naming the state it
# concluded about main's HEAD — `HEAD-COVERAGE: <state> <sha8>`. Parsing that declared
# contract (and the state CONSTANTS behind it) is how this runner stays accurate without
# phrase-matching the gate's prose, which is the failure mode every suppressor in this
# repo has eventually hit.
_HEAD_COV_RE = re.compile(r"^" + re.escape(check_main_green.HEAD_COVERAGE_PREFIX) + r"\s+(\S+)(?:\s+([0-9a-f?]{1,40}))?\s*$", re.M)


def _head_coverage(out: str) -> tuple:
    """(state, sha8) from the gate's HEAD-COVERAGE line, or (None, "") if absent."""
    m = _HEAD_COV_RE.search(out or "")
    return (m.group(1), m.group(2) or "") if m else (None, "")


def _last_line(out: str) -> str:
    lines = [ln.strip() for ln in out.strip().splitlines() if ln.strip()]
    # The HEAD-COVERAGE contract line is machine output, not the decode a human needs.
    lines = [ln for ln in lines if not ln.startswith(check_main_green.HEAD_COVERAGE_PREFIX)] or lines
    return lines[-1] if lines else ""


def _sha_from(out: str) -> str:
    m = re.search(r"\b([0-9a-f]{7,40})\b", out)
    return m.group(1)[:9] if m else "<sha>"


def draft_lines(results) -> list:
    """The draft marker-line block: script-determined outcomes pre-filled, the rest
    placeholders the session fills while writing the handover ONCE. Marker names come
    from the same wrap.md derivation check_handover_lines asserts with (#3006)."""
    by_name = {g.name: (ok, out) for g, ok, _, out in results}
    markers = check_handover_lines.derive_markers(check_handover_lines.DEFAULT_WRAP.read_text(encoding="utf-8"))

    def unverified(out):
        return "UNVERIFIED" in out

    filled = {}
    if "main-green" in by_name:
        ok, out = by_name["main-green"]
        cov_state, head8 = _head_coverage(out)
        if ok and cov_state in check_main_green.ZR_NOT_A_FAILURE:
            # #3212: green, but HEAD minted no CI/CD run of its own for a REASON the gate
            # proved benign. The marker must say so — the old draft line ("green (<sha>)")
            # silently attributed the verdict to a sha that is not HEAD.
            filled["Main"] = (
                f"green ({_sha_from(out)}) — HEAD {head8} minted no CI/CD run of its own: {cov_state} (expected, not a swallow)"
            )
        elif ok:
            filled["Main"] = f"green ({_sha_from(out)})"
        elif cov_state == check_main_green.ZR_INDETERMINATE:
            filled["Main"] = (
                f"<undetermined — HEAD {head8} has no CI/CD run and the swallow discriminator could not read: {_last_line(out)[:80]}>"
            )
        else:
            filled["Main"] = f"<red|stranded — decode: {_last_line(out)[:100]}>"
    if "stash" in by_name and "hooks" in by_name:
        s_ok, _ = by_name["stash"]
        h_ok, _ = by_name["hooks"]
        filled["Stash/hooks"] = "clean" if (s_ok and h_ok) else "<what was found + what you did about it>"
    if "alarm-citations" in by_name:
        ok, out = by_name["alarm-citations"]
        if unverified(out):
            filled["Alarms"] = "unverified — AWS unreachable"
        elif ok:
            filled["Alarms"] = f"<from batch output: {_last_line(out)[:100]}>"
        else:
            filled["Alarms"] = "<uncited — fix or cite, see batch output>"
    if "ci-warnings" in by_name:
        ok, out = by_name["ci-warnings"]
        if unverified(out):
            filled["CI warnings"] = "unverified — GitHub unreachable"
        elif ok:
            filled["CI warnings"] = f"<from batch output: {_last_line(out)[:100]}>"
        else:
            filled["CI warnings"] = "<N — one-line triage per warning>"

    placeholders = {
        "Build beat": "<beat id | none — one-clause reason>",
        "Docs": "<pages updated | none needed — one-clause reason>",
        "Decisions": "<ADR-NNN filed | none needed — one-clause reason>",
        "Incidents": "<N row(s) added — one-clause list | none>",
        "Closures": "<#N, #M commented | none — no issues closed this session>",
        "Backlog": "<Now n actionable (promoted #N); Later sweep — calls made>",
        "Ledger": "<subsystem> row added | omitted — <reason> | none — no standing machinery shipped>",
    }
    lines = []
    for name in markers:
        value = filled.get(name, placeholders.get(name, "<outcome>"))
        lines.append(f"**{name}:** {value}")
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verify", action="store_true", help="run the handover-reading gates (after the handover is written)")
    ap.add_argument("--list", action="store_true", help="print the battery and exit")
    args = ap.parse_args(argv)

    battery = VERIFY if args.verify else GATHER
    phase = "verify" if args.verify else "gather"
    if args.list:
        for g in GATHER:
            print(f"gather  ({g.step})  {g.name}: {' '.join(g.cmd)}")
        for g in VERIFY:
            print(f"verify  ({g.step})  {g.name}: {' '.join(g.cmd)}")
        return 0

    with ThreadPoolExecutor(max_workers=len(battery)) as pool:
        results = list(pool.map(run_gate, battery))

    failures = []
    for gate, ok, rc, out in results:
        verdict = "PASS" if ok else "FAIL"
        print(f"── [{verdict}] {gate.name} (step ({gate.step}), exit {rc}) ──")
        body = out.strip()
        if body:
            print(body)
        if not ok:
            failures.append(gate)
        print()

    if phase == "gather":
        print("── draft marker lines — paste into handovers/HANDOVER_LATEST.md and CORRECT; ──")
        print("── placeholders in <> are the session's to fill (the draft is a start, not a record) ──")
        for line in draft_lines(results):
            print(line)
        print()

    if failures:
        print(f"{phase.upper()} FAIL — {len(failures)} gate(s) red: " + ", ".join(f"{g.name} (step ({g.step}))" for g in failures))
        print("Each step in .claude/skills/wrap/SKILL.md documents its own remediation; fix and re-run this batch.")
        return 1
    print(f"{phase.upper()} OK — all {len(results)} gates passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
