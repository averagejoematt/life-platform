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

CONFIRMED_BY_OWNER = True
"""Flipped to True on the owner's ruling of 2026-09-20 (session AO boot, recorded on #3715):
"the list is current, with one update — the calf lesion is resolved, no restriction". gate:owner
(#3715, acceptance box 5). An agent session may not flip this on its own — the flip below is
the owner's recorded answer, and the structural test pairs it with LAST_REVIEWED_BY_OWNER."""

LAST_REVIEWED_BY_OWNER: str | None = "2026-09-20"
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
        "confirmed": True,
        # Owner ruling 2026-09-20 (session AO boot, on #3715): "Resolved — no restriction; the
        # coach may load calves normally." Kept on the record rather than deleted so a future
        # session can see it WAS a constraint and WHEN it stopped being one.
        "status": "resolved",
        "resolved_on": "2026-09-20",
        "resolution_source": f"owner ruling recorded on {ISSUE}, 2026-09-20",
    },
]


def active_constraints() -> list[dict[str, Any]]:
    """The constraints a coach must still plan around: confirmed AND not resolved."""
    return [c for c in RECORDED_CONSTRAINTS if c.get("confirmed") and c.get("status", "active") != "resolved"]


def format_unconfirmed_notice() -> str:
    """The disclosure a session gives when it cannot verify TRAINING_CONTEXT.md is current.

    Pins acceptance box 4 ("a coach session that cannot read it says so and refuses to
    imply constraint coverage it does not have") in the wording the real 2026-09-08 session
    already used, generalised to however many constraints are on record.
    """
    names = ", ".join(c["id"] for c in RECORDED_CONSTRAINTS) or "none recorded"
    if CONFIRMED_BY_OWNER:
        active = ", ".join(c["id"] for c in active_constraints()) or "none active"
        return (
            f"Could not verify {S3_KEY} is current at {S3_URI}. "
            f"{len(RECORDED_CONSTRAINTS)} constraint(s) are on record ({names}), owner-confirmed "
            f"{LAST_REVIEWED_BY_OWNER} ({ISSUE}); active today: {active}. Anything that has moved since "
            f"{LAST_REVIEWED_BY_OWNER} is NOT on this record — ask before this session prescribes load."
        )
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
        "active_constraints": active_constraints(),
        "status_note": (
            f"UNCONFIRMED — drafted from the platform's own recorded history, not yet reviewed by the owner "
            f"({ISSUE}, gate:owner). Do not treat as cleared until confirmed_by_owner is True."
            if not CONFIRMED_BY_OWNER
            else f"CONFIRMED — owner-reviewed {LAST_REVIEWED_BY_OWNER}; {len(active_constraints())} active constraint(s)."
        ),
        "if_unreadable": format_unconfirmed_notice(),
    }


# ══════════════════════════════════════════════════════════════════════════════
# #4036 — THE OWNER-DISMISSAL RULE (the RULE lives here; the RECORD never does)
# ══════════════════════════════════════════════════════════════════════════════
#
# The derived note layer flags pain over-inclusively on purpose — its own reader says so:
# "pain_flag is over-inclusive by design — confirm or dismiss before loading that movement."
# Until #4036 there was nowhere for the second half of that sentence to land. On 2026-09-21
# Matthew said the right lower back flagged from the 2026-09-13 Romanian Deadlift note was
# "gone", and under the v0.3 program a tripped pain flag substitutes the movement pattern
# for two weeks — so a stale flag benches the lift against his own word.
#
# WHY THE RECORD IS NOT IN THIS FILE
#   `RECORDED_CONSTRAINTS` above is CODE. It ships inside the Lambda bundle, so an MCP write
#   at chat time cannot touch it — the #3675 inertness class in reverse: a value a chat turn
#   produces cannot live in a module a deploy produces. The dismissal is therefore a
#   DynamoDB record (`USER#matthew#SOURCE#training_constraints / DISMISSAL#<site>#<date>`,
#   CROSS_PHASE, owner-only Tier 2) written by ONE MCP action and read at runtime by
#   `plan_engine._tripwire_states` and `coach.critics.build_joints_packet`.
#
# WHAT LIVES HERE INSTEAD
#   The rule: what a dismissal IS (site + the date he said it + his verbatim words + the
#   flag instance it dismisses), how a record is shaped and validated, and — the whole
#   point — how it RE-ARMS. Both consumers derive their answer from `resolve_flags` below
#   rather than each implementing a date comparison, because two copies of that comparison
#   is how one of them silently keeps dismissing a flag the other has already re-armed.

DISMISSAL_SOURCE = "training_constraints"
DISMISSAL_PK = f"USER#matthew#SOURCE#{DISMISSAL_SOURCE}"
DISMISSAL_SK_PREFIX = "DISMISSAL#"
DISMISSAL_ISSUE = "#4036"

DISMISSAL_RULE: dict[str, Any] = {
    "issue": DISMISSAL_ISSUE,
    "what": (
        "An owner dismissal is Matthew's own statement that a flagged site is resolved. It is scoped to the "
        "SITE he named, dated the day he said it, carries his verbatim words, and names the flag instance it "
        "dismisses (the note date + the movement that carried the flag)."
    ),
    "is_not": (
        "A dismissal is NOT an absence. A dismissed flag never reads `clear` — the flag happened, and the row "
        "says `dismissed_by_owner` with the date and the words, so a reader can see a human overrode it."
    ),
    "re_arms": (
        "A derived-note pain flag on the same site with a note date AFTER the dismissal date trips again and "
        "marks the dismissal superseded. He never has to remember he once dismissed it."
    ),
    "undated_flag": (
        "A flag whose note date cannot be read is NOT dismissed: with nothing to compare, 'dismissed' would be "
        "an assumption wearing a verdict's clothes (the #3767 rule for safety conditions)."
    ),
    "store": f"{DISMISSAL_PK} / {DISMISSAL_SK_PREFIX}<site>#<YYYY-MM-DD> — CROSS_PHASE (ADR-077), Tier 2 owner-only",
}


def normalize_dismissal_key(text: str) -> str:
    """The match key for a site or a movement label: lowercase, non-alphanumerics collapsed.

    'Right lower back', 'right_lower_back' and 'RIGHT LOWER BACK' are one site; 'Romanian
    Deadlift (Barbell)' and 'romanian deadlift barbell' are one movement. The key is also
    what goes in the sk, so two spellings of the same site cannot become two records.
    """
    out: list[str] = []
    for ch in str(text or "").strip().lower():
        out.append(ch if ch.isalnum() else " ")
    return "_".join("".join(out).split())


def dismissal_sk(site: str, dismissed_on: str) -> str:
    """`DISMISSAL#<normalized site>#<YYYY-MM-DD>` — one record per site per day he says it."""
    return f"{DISMISSAL_SK_PREFIX}{normalize_dismissal_key(site)}#{str(dismissed_on)[:10]}"


def _is_iso_date(value: Any) -> bool:
    s = str(value or "")
    if len(s) != 10 or s[4] != "-" or s[7] != "-":
        return False
    try:
        y, m, d = int(s[0:4]), int(s[5:7]), int(s[8:10])
    except ValueError:
        return False
    return 1 <= m <= 12 and 1 <= d <= 31 and y >= 2000


def build_dismissal_record(
    *,
    site: str,
    dismissed_on: str,
    words: str,
    movements: list[str],
    flag_note_date: str,
    recorded_at: str,
) -> dict[str, Any]:
    """Validate an owner dismissal and return the DDB item body (no floats — Decimal-safe
    by construction: every value here is a string or a list of strings).

    Raises ValueError with the reason. A dismissal that cannot name the instance it
    dismisses is refused rather than stored: 'the back is fine' with no flag attached is a
    sentiment, and a safety override has to be checkable against the thing it overrode.
    """
    site = str(site or "").strip()
    words = str(words or "").strip()
    movements = [str(m).strip() for m in (movements or []) if str(m).strip()]
    if not site:
        raise ValueError("site is required — the body site he named, in his own words (e.g. 'right lower back')")
    if not words:
        raise ValueError("words is required and must be VERBATIM — the override is his statement, not a paraphrase of it")
    if not _is_iso_date(dismissed_on):
        raise ValueError("dismissed_on must be YYYY-MM-DD — the day he said it")
    if not _is_iso_date(flag_note_date):
        raise ValueError("flag_note_date must be YYYY-MM-DD — the note date of the flag instance being dismissed")
    if not movements:
        raise ValueError("movements must name at least one movement — the flag instance is (note date + movement)")
    if str(flag_note_date)[:10] > str(dismissed_on)[:10]:
        raise ValueError(
            f"refused: the flag instance is dated {flag_note_date}, AFTER the dismissal {dismissed_on} — "
            "a dismissal cannot precede the flag it dismisses (it would be superseded the moment it was written)"
        )
    return {
        "sk": dismissal_sk(site, dismissed_on),
        "site": site,
        "site_key": normalize_dismissal_key(site),
        "dismissed_on": str(dismissed_on)[:10],
        "words": words,
        "movements": movements,
        "movement_keys": sorted({normalize_dismissal_key(m) for m in movements}),
        "flag_note_date": str(flag_note_date)[:10],
        "recorded_at": recorded_at,
        "recorded_via": "get_exercise_notes/dismiss",
        "issue": DISMISSAL_ISSUE,
        "rule": DISMISSAL_RULE["re_arms"],
    }


def _dismissal_matches(dismissal: dict[str, Any], *, movement: str | None, site: str | None) -> bool:
    """Does this dismissal cover this flag? By MOVEMENT first — the only identifier the flag
    layer and the dismissal share, because the derived note layer is keyed per exercise and
    knows no anatomy — and by SITE when a caller has one (`pain_flag_sites` carries movement
    labels today, so the site leg is the forward-compatible half, not the live one)."""
    keys = {str(k) for k in (dismissal.get("movement_keys") or [])}
    if not keys:
        keys = {normalize_dismissal_key(m) for m in (dismissal.get("movements") or [])}
    site_key = str(dismissal.get("site_key") or normalize_dismissal_key(dismissal.get("site", "")))
    for candidate in (movement, site):
        if not candidate:
            continue
        k = normalize_dismissal_key(candidate)
        if k and (k in keys or k == site_key):
            return True
    return False


def resolve_flag(
    *,
    movement: str | None,
    note_dates: list[str] | None,
    dismissals: list[dict[str, Any]] | None,
    site: str | None = None,
) -> dict[str, Any] | None:
    """The ONE date comparison. Returns None when no dismissal covers this flag, else a row.

    `note_dates` are the flag's own note dates (the derived layer's `pain_dates`). The
    latest one decides:
      * latest note <= the dismissal date  -> `dismissed_by_owner`
      * latest note  > the dismissal date  -> `re_armed`, and the dismissal is `superseded`
      * no readable note date              -> `undated_flag`: NOT dismissed (see DISMISSAL_RULE)
    """
    covering = [d for d in (dismissals or []) if _dismissal_matches(d, movement=movement, site=site)]
    if not covering:
        return None
    latest = max(covering, key=lambda d: str(d.get("dismissed_on") or ""))
    dismissed_on = str(latest.get("dismissed_on") or "")[:10]
    dates = sorted(str(d)[:10] for d in (note_dates or []) if _is_iso_date(d))
    row: dict[str, Any] = {
        "movement": movement,
        "site": latest.get("site"),
        "dismissed_on": dismissed_on,
        "words": latest.get("words"),
        "sk": latest.get("sk"),
        "flag_note_date": latest.get("flag_note_date"),
        "latest_note_date": dates[-1] if dates else None,
    }
    if not dates:
        row["state"] = "undated_flag"
        row["dismissed"] = False
        row["superseded"] = False
        row["detail"] = DISMISSAL_RULE["undated_flag"]
        return row
    # THE comparison this whole issue turns on. Remove it and a dismissal never expires.
    if dates[-1] > dismissed_on:
        row["state"] = "re_armed"
        row["dismissed"] = False
        row["superseded"] = True
        row["detail"] = (
            f"a note dated {dates[-1]} is AFTER the owner's {dismissed_on} dismissal of {latest.get('site')!r} — "
            "the flag re-armed and the dismissal is superseded"
        )
        return row
    row["state"] = "dismissed_by_owner"
    row["dismissed"] = True
    row["superseded"] = False
    row["detail"] = f"owner dismissed {latest.get('site')!r} on {dismissed_on}: {str(latest.get('words'))!r}"
    return row


def resolve_flags(instances: list[dict[str, Any]] | None, dismissals: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """`resolve_flag` over every flagged instance. `instances` are
    `{"movement": <label>, "note_dates": [...], "site": <optional>}`; unmatched flags are
    omitted, so an empty list means no dismissal is in play at all."""
    out: list[dict[str, Any]] = []
    for inst in instances or []:
        res = resolve_flag(
            movement=(inst or {}).get("movement"),
            note_dates=(inst or {}).get("note_dates"),
            site=(inst or {}).get("site"),
            dismissals=dismissals,
        )
        if res is not None:
            out.append(res)
    return out
