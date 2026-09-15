"""training_context_registry.py — one durable home for standing training constraints (#3715).

WHY THIS EXISTS

A live coaching session on 2026-09-08 opened with:

    "Couldn't read TRAINING_CONTEXT.md. It isn't in my context, nothing's in uploads, and
    the Filesystem mount only exposes /Users/matthewwalker/Documents/claude/Jason and
    /cowork, both empty. So injuries and equipment below come from data and prior context,
    not the doc. If the calf lesion or anything else has moved, tell me."

That session degraded honestly — it said what it could not read and named the assumption.
That is correct and is NOT the bug. The bug is that the file it was told to read had no
owner: `TRAINING_CONTEXT.md` existed nowhere in the repo, nowhere on disk, and the
Filesystem-mount root it tried (a leftover from the 2026-08-30 `~/Documents/Claude` →
`~/dev` repo move) was empty. A standing injury constraint like the calf lesion was
surviving purely as conversational context — present in a long session, silently gone in
a fresh one. The failure mode is not a wrong number; it is a session prescribed against an
injury nobody re-stated.

THE HOME (and why it is not a tracked file)

`docs/coaching/README.md` (#3043, 2026-08-23) already drew this line for the sibling docs
(`TRAINING_CALIBRATION.md`, `TRAINING_PROGRAM.md`, `PROVEN_BLUEPRINT.md`): this repo is
deliberately public, so owner-personal specifics do not live in the tracked tree — they
live at the owner-only, delete-protected S3 prefix `s3://matthew-life-platform/config/
coaching/`, read with `aws s3 cp ... -`. A standing-injury list is the same class of
owner-personal specific (arguably more sensitive than the calibration prose it sits
beside), so `TRAINING_CONTEXT.md`'s canonical bytes belong at that SAME prefix
(`S3_KEY` below), not as a tracked file — putting the actual document in git would repeat
the exact mistake #3043 already fixed once.

What IS tracked, and is the charter's "registry" primitive for this vocabulary (one
executable source of truth, `docs/CHARTER.md` #2843): this module. `RECORDED_CONSTRAINTS`
below is every standing constraint already on the record anywhere in the platform's own
history — right now that is exactly one entry, the calf lesion named in issue #3715's own
Evidence block, which is itself already public (the issue lives in a public repo). Nothing
below is invented: no site, no severity, no equipment list beyond what a real session or
issue already stated. An invented constraint in a safety document is worse than a missing
one.

THE CORRECTED READ PATH (acceptance box 2)

The Filesystem-mount trap is a LOCAL Claude Desktop setting
(`claude_desktop_config.json` → the filesystem extension's allowed roots), not a repo
file — no PR can fix it, and this one does not try. The fix that IS in scope: stop
depending on that fragile, machine-local mount at all. `docs/coaching/COACH_SESSION.md`
already tells every session (chat, Desktop, Claude Code — anything with AWS access) to
read the three sibling docs with a plain `aws s3 cp` command, which does not care what a
Desktop extension happens to have mounted this week. This module's `S3_KEY` is now the
fourth entry in that same list (see the COACH_SESSION.md diff in the same PR) — the
correction IS "use the read path that already works for the other three," not a new
mechanism.

STATUS: gate:owner (acceptance box 5). `CONFIRMED_BY_OWNER = False` until Matthew has
reviewed the constraint list below and the rendered document at `S3_KEY`. No agent session
may flip this — an unconfirmed constraint list must not become load-bearing on its own
say-so, the same posture `lambdas/training/owner_redlines.py` (#3753) takes for the
posture/tripwire registry. `tests/test_training_context_registry_3715.py` pins the
honest-degradation contract (acceptance box 4) and the derivation between this module and
COACH_SESSION.md's prose (no hand-typed second copy of the S3 key).

RENDERING THE S3 OBJECT

This module has no AWS credentials and does not call boto3 or the CLI — writing to S3 is
an infrastructure mutation this agent is not permitted to make. `scripts/
render_training_context_md.py` renders the markdown body FROM `RECORDED_CONSTRAINTS`
below (so the S3 document derives from this registry rather than being a hand-typed
duplicate that can drift from it) and prints it to stdout; a human with owner S3 write
credentials pipes that into
`aws s3 cp - s3://matthew-life-platform/config/coaching/TRAINING_CONTEXT.md` once ready,
then reviews it and flips `CONFIRMED_BY_OWNER` in a follow-up PR.
"""

from __future__ import annotations

from typing import Any

S3_BUCKET = "matthew-life-platform"
S3_KEY = "config/coaching/TRAINING_CONTEXT.md"
S3_URI = f"s3://{S3_BUCKET}/{S3_KEY}"

ISSUE = "#3715"

CONFIRMED_BY_OWNER = False
"""Flip to True only after Matthew has reviewed RECORDED_CONSTRAINTS AND the rendered
document at S3_URI. gate:owner (#3715, acceptance box 5). Must not be flipped to True by
an agent session — see the structural test that pairs this with LAST_REVIEWED_BY_OWNER."""

LAST_REVIEWED_BY_OWNER: str | None = None
"""ISO date Matthew last reviewed the constraint list. None means never."""


# ── What is already on the record — nothing inferred beyond this ────────────
# Every entry states its own source verbatim so staleness (and provenance) is visible
# rather than implied. `detail` is deliberately thin: only what the cited source actually
# said, never a clinical elaboration this agent has no standing to add.
RECORDED_CONSTRAINTS: list[dict[str, Any]] = [
    {
        "id": "calf_lesion",
        "kind": "injury",
        "detail": (
            "A calf lesion, named by Matthew in a live coaching session as a standing constraint the coach should "
            "know about. No site/severity/duration beyond 'calf lesion' is recorded anywhere in the platform's own "
            "history as of this writing — the session that surfaced it explicitly said it could not verify current "
            "status and asked to be told if it had changed."
        ),
        "source": f"issue {ISSUE} Evidence block, quoting the 2026-09-08 coaching session",
        "dated": "2026-09-08",
        "confirmed": False,
    },
]


def format_unconfirmed_notice() -> str:
    """The disclosure a session gives when it cannot verify TRAINING_CONTEXT.md is current.

    Pins acceptance box 4 ("a coach session that cannot read it says so and refuses to
    imply constraint coverage it does not have") in the wording the real 2026-09-08 session
    already used, generalised to however many constraints are on record.
    """
    names = ", ".join(c["id"] for c in RECORDED_CONSTRAINTS) or "none recorded"
    return (
        f"Could not verify {S3_KEY} is current at {S3_URI}. "
        f"{len(RECORDED_CONSTRAINTS)} standing constraint(s) are on record from prior sessions/issues "
        f"({names}) but are NOT owner-confirmed (gate:owner, {ISSUE}) — treat them as a hypothesis, not "
        "clearance. If any of these, or anything else, has moved, say so before this session prescribes load."
    )


def summary() -> dict[str, Any]:
    """The block a coach protocol embeds — never a bare 'constraints: ok' without provenance."""
    return {
        "s3_uri": S3_URI,
        "confirmed_by_owner": CONFIRMED_BY_OWNER,
        "last_reviewed_by_owner": LAST_REVIEWED_BY_OWNER,
        "constraints": RECORDED_CONSTRAINTS,
        "status_note": (
            f"UNCONFIRMED — drafted from the platform's own recorded history, not yet reviewed by the owner "
            f"({ISSUE}, gate:owner). Do not treat as cleared until confirmed_by_owner is True."
            if not CONFIRMED_BY_OWNER
            else f"CONFIRMED — owner-reviewed {LAST_REVIEWED_BY_OWNER}."
        ),
        "if_unreadable": format_unconfirmed_notice(),
    }
