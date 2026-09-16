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

import importlib.util
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


# ── #3805: the gate checked the FILE, not the ROW ────────────────────────────
# `docs/PROPORTIONALITY.md` carries a MACHINE-WRITTEN literal — the `gate_census_count`
# fact, `<n> declared gates`, rewritten by deploy/sync_census_fact.py on any PR that adds
# a source-scanning guard. So "the file has a diff this session" was satisfiable by a bot
# bumping a counter, and every session that adds a guard bumps it.
#
# Demonstrated on branch spike/xdist-3025, whose ONLY change to that file was
# `639 declared gates` -> `640`: the gate printed OK and validated a ledger claim that
# belonged to a DIFFERENT session. The gate's shape was right and its evidence was not the
# thing it claimed to check (#3805).
#
# The repo already had the correct pattern one file over: deploy/doc_restamp_guard.py
# (#2986, "no manufactured freshness") HOLDS a date re-stamp when the run neither
# re-derived a literal nor found regenerated content. Same idea here — a counter-only diff
# is cosmetic and must not satisfy a claim that a ROW landed.
#
# The excluded pattern is DERIVED from deploy/sync_census_fact.py's own _RULE rather than
# re-typed, so a change to what the bot owns moves this exclusion with it.
def _sync_owned_patterns(root: Path):
    """Regexes for the lines sync tooling owns in the ledger — derived, never hardcoded."""
    pats = []
    try:
        spec = importlib.util.spec_from_file_location("_scf_3805", root / "deploy" / "sync_census_fact.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        doc, pattern, _tmpl = mod._RULE
        if doc.endswith(LEDGER_REL.split("/")[-1]):
            pats.append(re.compile(pattern))
    except Exception:  # noqa: BLE001 — a missing derivation must not make the gate pass
        return None
    # A bare date re-stamp is cosmetic for the same reason (#2986's class).
    pats.append(re.compile(r"^\s*[-*+]?\s*\*?\*?(?:Last (?:updated|re-read)|Re-read)\*?\*?:?\s*\d{4}-\d{2}-\d{2}"))
    return pats


def _substantive_ledger_lines(diff_text: str, patterns):
    """Added/removed ledger lines that are NOT sync-owned. Empty == a cosmetic diff."""
    out = []
    for line in diff_text.splitlines():
        if not line or line[0] not in "+-" or line[:3] in ("+++", "---"):
            continue
        body = line[1:].strip()
        if not body:
            continue
        # A line whose ONLY difference is the machine-written literal is cosmetic. Blank the
        # owned span and compare: if what remains is identical on both sides of the diff, the
        # bot wrote it. Judged per-line because the ledger is one row per line.
        blanked = body
        for pat in patterns:
            blanked = pat.sub("<sync-owned>", blanked)
        out.append((line[0], blanked))
    plus = [b for sign, b in out if sign == "+"]
    minus = [b for sign, b in out if sign == "-"]
    # Whatever appears on BOTH sides after blanking is a counter bump, not a new row.
    for b in list(plus):
        if b in minus:
            plus.remove(b)
            minus.remove(b)
    return plus + minus


def handover_touched_this_session(root: Path, handover_rel: str):
    """True when the handover itself moved this session (#3805 box 2).

    `handovers/HANDOVER_LATEST.md` belongs to the PREVIOUS session until the current one
    overwrites it at wrap. Without this anchor the gate can pair LAST session's ledger claim
    with THIS session's counter bump and print OK — neither half anchored to the other.
    """
    return _path_moved_this_session(root, handover_rel)


def _path_moved_this_session(root: Path, rel: str):
    """True/False/None — the session-boundary diff test, for one path."""
    try:
        porcelain = subprocess.run(["git", "status", "--porcelain", "--", rel], cwd=root, capture_output=True, text=True, timeout=30)
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
            return False
        since = subprocess.run(
            ["git", "log", "--format=%H", f"{boundary}..HEAD", "--", rel], cwd=root, capture_output=True, text=True, timeout=30
        )
        if since.returncode != 0:
            return None
        return bool(since.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return None


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
        # #3805: derive the sync-owned exclusions FIRST. If we cannot tell which lines the
        # bot owns, we cannot tell a real row from a counter bump — and that is UNVERIFIED,
        # not False. Ordering matters and CI caught it: in a shallow checkout there is no
        # reachable `docs(wrap` commit, so an earlier version returned False here before the
        # derivation was ever consulted, which is a VERDICT reached without the evidence.
        patterns = _sync_owned_patterns(root)
        if patterns is None:
            return None  # the derivation is unavailable — UNVERIFIED, never a silent pass

        last_wrap = subprocess.run(
            ["git", "log", "--format=%H", "--grep", r"^docs(wrap", "-n", "1"], cwd=root, capture_output=True, text=True, timeout=30
        )
        if last_wrap.returncode != 0:
            return None
        boundary = last_wrap.stdout.strip()
        if not boundary and not porcelain.stdout.strip():
            return False  # no wrap commit in history — only the explicit line can pass
        chunks = []
        got = subprocess.run(["git", "diff", "HEAD", "--", LEDGER_REL], cwd=root, capture_output=True, text=True, timeout=30)
        if got.returncode == 0:
            chunks.append(got.stdout)
        if boundary:
            committed = subprocess.run(
                ["git", "diff", f"{boundary}..HEAD", "--", LEDGER_REL], cwd=root, capture_output=True, text=True, timeout=30
            )
            if committed.returncode != 0:
                return None
            chunks.append(committed.stdout)
        return bool(_substantive_ledger_lines("\n".join(chunks), patterns))
    except (OSError, subprocess.SubprocessError):
        return None


def evaluate(handover_text: str, ledger_diff, handover_is_this_session=None) -> tuple:
    """(ok, messages) for one wrap input. Pure — the tests drive this directly.

    `ledger_diff` is True / False / None (None = git unreachable, UNVERIFIED)."""
    messages = []
    claims = find_ledger_claims(handover_text)

    # #3805 box 2: the claim and the diff must belong to the SAME session.
    # handovers/HANDOVER_LATEST.md is the PREVIOUS session's until this one overwrites it at
    # wrap, so without this anchor the gate can validate last session's ledger claim with
    # this session's counter bump — which is exactly what happened on spike/xdist-3025.
    if claims and handover_is_this_session is False:
        messages.append(
            f"UNANCHORED — the handover claims a ledger row but {DEFAULT_HANDOVER} has not "
            "changed this session, so the claim belongs to a PREVIOUS session and this "
            "session's diff cannot validate it (#3805). Write this session's handover first."
        )
        return False, messages

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

    handover_is_this_session = _path_moved_this_session(ROOT, str(path)) if diff_mode == "auto" else None
    ok, messages = evaluate(path.read_text(encoding="utf-8"), ledger_diff, handover_is_this_session)
    for m in messages:
        print(m)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
