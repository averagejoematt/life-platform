"""restart_work_contract.py — the per-step WORK contract of the reset pipeline (#3598).

The 2026-09-04 reset ran `restart_chronicle_handler.py`, which reported
`html_files_archived=0 / html_files_already_archived=29` and exited 0. The pipeline
read exit 0 as success. It was not: the archive step had found 29 pages of input and
acted on none of them, because its destination key had no cycle segment and every
reused slug collided with the 2026-07-10 archival. No reset since cycle 4 had
archived a page, and every one of them reported green.

The contract this module states is the one the pipeline was missing: **a step that
finds input and does nothing must say why, or it is red.** Each `restart_*` step
emits one machine-readable line per unit of work —

    WORK_CONTRACT {"step": "...", "input_count": N, "acted_count": M, "skipped_count": K, "reason": ...}

— and `restart_pipeline.run_step` parses every such line out of the step's stdout.
`input_count > 0` with `acted_count == 0` and no named `reason` fails the step even
when its process exited 0. A named reason is the step's own, computed statement of
why zero was the right number ("every in-scope row already carries this genesis's
tombstone"), never a default string.

Deliberately NOT a registry of derived artifacts and NOT a new workflow (both rejected
in the forensic RCA's rent register): two functions, one line format, zero rent.
"""

from __future__ import annotations

import json

WORK_CONTRACT_PREFIX = "WORK_CONTRACT "

# The exit code run_step returns for a contract violation on a process that exited 0.
# Distinct from every sub-script's own exit codes (1..6 are all taken by the pipeline)
# so a log reader can tell "the step failed" from "the step did nothing and hid it".
WORK_CONTRACT_EXIT = 75


def work_report(step: str, *, input_count: int, acted_count: int, skipped_count: int = 0, reason: str | None = None) -> dict:
    """Build + print one WORK_CONTRACT line; returns the record.

    `reason` is REQUIRED for the record to pass when input_count > 0 and
    acted_count == 0 — pass it only when the step has computed why zero is right.
    """
    rec = {
        "step": str(step),
        "input_count": int(input_count),
        "acted_count": int(acted_count),
        "skipped_count": int(skipped_count),
        "reason": (str(reason) if reason else None),
    }
    print(WORK_CONTRACT_PREFIX + json.dumps(rec, sort_keys=True))
    return rec


def parse_work_reports(stdout: str) -> list[dict]:
    """Every WORK_CONTRACT record in a step's stdout, in order. Malformed lines are
    ignored (a step that prints a broken line is a bug in the step, not a reason
    to abort a reset half-way — the ABSENCE of a report is never a failure here
    either; only a report that says "input, no action, no reason" is)."""
    out: list[dict] = []
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line.startswith(WORK_CONTRACT_PREFIX):
            continue
        try:
            rec = json.loads(line[len(WORK_CONTRACT_PREFIX) :])
        except ValueError:
            continue
        if isinstance(rec, dict) and "input_count" in rec and "acted_count" in rec:
            out.append(rec)
    return out


def violation(rec: dict) -> str | None:
    """The one rule: input > 0 and acted == 0 without a named reason is a violation.
    Returns a human sentence naming it, else None."""
    try:
        inp = int(rec.get("input_count") or 0)
        acted = int(rec.get("acted_count") or 0)
    except (TypeError, ValueError):
        return f"step {rec.get('step')!r}: unreadable counts {rec!r}"
    if inp > 0 and acted == 0 and not rec.get("reason"):
        return (
            f"step {rec.get('step')!r}: found {inp} input item(s) and acted on 0 with no named reason "
            f"(skipped={rec.get('skipped_count')})"
        )
    return None


def violations(stdout: str) -> list[str]:
    """All violations in a step's stdout (empty list == the contract holds)."""
    return [v for v in (violation(r) for r in parse_work_reports(stdout)) if v]


def work_contract_rc(step_name: str, stdout: str, log: list[str] | None = None) -> int:
    """The pipeline's verdict on a step that exited 0: WORK_CONTRACT_EXIT when any
    report violates the contract (printed + appended to `log`), else 0."""
    found = violations(stdout)
    if not found:
        return 0
    for v in found:
        line = f"✗ WORK CONTRACT ({step_name}): {v}"
        print(line)
        if log is not None:
            log.append(line)
    return WORK_CONTRACT_EXIT
