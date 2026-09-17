#!/usr/bin/env python3
"""restart_cadence.py — the minimum cycle length, and the refusal that enforces it (#3601).

Lives outside `restart_pipeline.py` because that module sits against the 1000-line hard
ceiling (#1665) and the standing rule is EXTRACTION, never a baseline raise — the same
idiom `qa_check_coach_labs` and `gate_census_proofs` were split out under. Caught by the
guard on this change's own first push, which is what the ceiling is for.

It is also the better home: `check_cadence` is a PURE decision over three dates and one
flag, and it is the half worth testing exhaustively
(`tests/test_reset_cadence_refusal_3601.py`). The pipeline keeps the I/O and the exit.
"""

from __future__ import annotations

import datetime as _dt

# ── #3601: the minimum cycle length, and the refusal that enforces it ─────────
#
# MEASURED 2026-09-16 off CYCLE_GENESES itself, not restated from the issue:
#
#     17 cycles on record, 16 re-anchors over 158 days (2026-04-01 -> 2026-09-06)
#     gap days: median 5.5   mean 9.9   min 1   max 61
#     rate: 9.2 per QUARTER  (3.04 per 30 days)
#
# `docs/PROPORTIONALITY.md` row 86 prices the reset machinery against "a few times a
# quarter". The measured rate is ~3x that, and every reset-machinery demote trigger in
# that ledger has therefore been judged against the wrong cadence.
#
# THE WINDOW IS AN OWNER RULING, NOT A NUMBER PICKED HERE. Owner, 2026-09-05 (recorded
# on #3606, ruling 1): "Reset cadence: minimum cycle length 30 days. The reset tool
# refuses a re-anchor inside 30 days without an explicit override flag (#3601)."
#
# Why a refusal rather than a warning: the 2026-09-04 typo cost a SECOND full reset
# inside 24h (Session U), and cycle 15 lasted 3 days — so "Day 4 of cycle 15" never
# existed and every clause written against it was unfalsifiable for a whole cycle. A
# warning does not stop a typo; a non-zero exit does.
#
# The override is deliberately NOT a bare --force. `--reanchor-of <YYYY-MM-DD>` makes
# the operator NAME the genesis being superseded, so an intended correction states what
# it corrects and a mistyped date cannot satisfy it by accident.
MIN_CYCLE_DAYS = 30


class CadenceRefusal(Exception):
    """A re-anchor inside MIN_CYCLE_DAYS with no --reanchor-of naming the prior genesis."""


def check_cadence(new_genesis: str, prior_genesis: str, reanchor_of: str | None, *, today=None) -> str:
    """Pure decision (#3601). Returns the line to print; raises CadenceRefusal to abort.

    `prior_genesis` is the OUTGOING genesis — the one this reset supersedes. The age is
    measured from it to TODAY, not to `new_genesis`: a future-dated genesis is sanctioned
    (#931/#939) and the question is how long the cycle being ended actually ran.
    """
    today = today or _dt.date.today()
    try:
        prior = _dt.date.fromisoformat(str(prior_genesis)[:10])
    except (TypeError, ValueError):
        return f"    cadence check SKIPPED — prior genesis {prior_genesis!r} is not a readable date"
    age = (today - prior).days
    if age >= MIN_CYCLE_DAYS:
        return f"    OK — the outgoing cycle ({prior_genesis}) has run {age}d, at or past the {MIN_CYCLE_DAYS}d minimum"
    if reanchor_of:
        if str(reanchor_of)[:10] != prior.isoformat():
            raise CadenceRefusal(
                f"--reanchor-of {reanchor_of} does not name the genesis this reset supersedes.\n"
                f"The outgoing genesis is {prior.isoformat()} (running {age}d, under the {MIN_CYCLE_DAYS}d minimum).\n"
                "Name it exactly, or drop the flag and wait out the window. The flag exists so a deliberate\n"
                "correction STATES what it corrects — a value that does not match is a typo, not an override."
            )
        return (
            f"    OVERRIDE ACCEPTED — the outgoing cycle ({prior.isoformat()}) has run only {age}d, under the "
            f"{MIN_CYCLE_DAYS}d minimum, and --reanchor-of names it explicitly. This reset is recorded as a "
            "correction of that genesis, not as a new cycle's worth of evidence."
        )
    raise CadenceRefusal(
        f"MINIMUM CYCLE LENGTH ({MIN_CYCLE_DAYS}d) NOT MET.\n"
        f"  outgoing genesis : {prior.isoformat()}\n"
        f"  age today        : {age}d\n"
        f"  target genesis   : {new_genesis}\n"
        f"\nThe owner ruled a 30-day minimum on 2026-09-05 (#3606 ruling 1, #3601). Measured cadence when that\n"
        f"ruling was made: 16 re-anchors over 158d = 9.2/quarter, median gap 5.5d — and the 2026-09-04 typo cost\n"
        f"a second full reset inside 24h.\n"
        f"\nIf this IS a deliberate correction of {prior.isoformat()}, say so:\n"
        f"    --reanchor-of {prior.isoformat()}\n"
        f"Otherwise the cycle is still running and nothing here should be re-anchored."
    )


def preflight(target: str, old_genesis: str, reanchor_of: str | None, *, apply: bool, skip: bool) -> int | None:
    """The `[0a]` step: print the verdict, return an exit code to abort with, or None.

    The whole step lives here rather than inline in `restart_pipeline.main()` because that
    module is against the 1000-line hard ceiling and the rule is extraction (#1665).

    Gated on `apply`. A dry run is how an operator INSPECTS a proposed re-anchor, and
    refusing to let them look is how the refusal gets routed around with
    `--skip-cadence-preflight` out of habit — so a dry run says loudly what apply would do
    and returns None.
    """
    if skip:
        print("\n[0a] Cadence preflight SKIPPED (--skip-cadence-preflight)")
        return None
    print(f"\n[0a] Minimum cycle length — {MIN_CYCLE_DAYS}d, owner ruling 2026-09-05 (#3606 ruling 1, #3601)")
    # A RE-CONVERGE (no --genesis, so target == old_genesis) is not a re-anchor — it
    # re-runs the pipeline against the SAME genesis to fix a partial run, the documented
    # recovery path. The ruling is about how often the experiment STARTS OVER, not how
    # often the tooling is re-run.
    if target == old_genesis:
        print(f"    N/A — re-converging the CURRENT genesis ({target}); no new cycle is being started")
        return None
    try:
        print(check_cadence(target, old_genesis, reanchor_of))
        return None
    except CadenceRefusal as e:
        if not apply:
            print(f"    DRY-RUN — apply WOULD REFUSE:\n{e}")
            return None
        print(f"\n\u2717 CADENCE PREFLIGHT FAILED\n{e}")
        print(
            "\n   ABORTING before any reset step — nothing was fetched, written or deployed.\n"
            "   (escape hatch: --skip-cadence-preflight, but --reanchor-of is the honest route)"
        )
        return 6
