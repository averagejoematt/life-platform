"""
tools_training_notes.py — the derived note-signal layer's surface: read, and one owner write.

get_exercise_notes returns the per-exercise note timeline the coach reads as a trajectory
(the arc, not the latest line). pain_flag is surfaced prominently — this is the §7
pre-flight pain surface. Raw notes stay sovereign; the read only reads the derived
`training_notes` projection (written by the on-ingest extractor in hevy_backfill_lambda).

`action='dismiss'` (#4036) is the one WRITE here, and it writes a different partition:
`USER#matthew#SOURCE#training_constraints`, the owner's dismissal of a pain flag. It is the
second half of this layer's own instruction — "pain_flag is over-inclusive by design —
confirm or dismiss before loading that movement" — and until #4036 only the first half
existed anywhere. See the block at the end of this file.
"""

from datetime import timedelta

from boto3.dynamodb.conditions import Key
from common.pacific_time import pacific_now  # #2817: THE Pacific frame — DATE#/day keys name Pacific calendar days
from training.training_notes import DEGRADE_UNRECORDED, dedupe_head_rows, head_sk_base
from training.training_notes_keys import PREFLIGHT_LOOKBACK_DAYS  # #3972: the one number, not a restated 180

from mcp.config import table
from mcp.core import LAYER_DARK, decimal_to_float, derived_layer_status

NOTES_SOURCE = "training_notes"


def _resolve_template_id(exercise: str, lookback_days: int) -> tuple[str | None, str | None]:
    """Resolve a human exercise name → (template_id, matched_name) via recent raw Hevy
    workouts. If `exercise` already looks like a template id, pass it through."""
    ex = (exercise or "").strip()
    if not ex:
        return None, None
    # Heuristic: a Hevy template id is hex (8) or a uuid — no spaces. A name has spaces
    # or isn't a bare id. Try direct first only if it has no spaces and isn't obviously words.
    looks_like_id = (" " not in ex) and (len(ex) >= 8) and (all(c in "0123456789abcdefABCDEF-" for c in ex))
    if looks_like_id:
        return ex, None

    start = (pacific_now().date() - timedelta(days=lookback_days)).isoformat()
    today = pacific_now().date().isoformat()
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq("USER#matthew#SOURCE#hevy") & Key("sk").between(f"DATE#{start}", f"DATE#{today}~"),
            ProjectionExpression="exercises",
        )
    except Exception:
        return None, None
    needle = ex.lower()
    best = None
    for it in resp.get("Items", []):
        for e in decimal_to_float(it).get("exercises", []) or []:
            nm = (e.get("name") or e.get("title") or "").lower()
            tid = e.get("template_id")
            if tid and (needle in nm or nm in needle):
                best = (str(tid), e.get("name") or e.get("title"))
                if needle == nm:
                    return best  # exact wins immediately
    return best or (None, None)


def tool_get_exercise_notes(args):
    """Per-exercise note timeline (the arc) + signals + pain flags — and, on `action`, the
    OWNER-ONLY dismissal of one of those flags (#4036, see the block at the end of this file).

    The write lives on this tool rather than on one of its own (which is what #4036's design
    note reached for first) because minting a tool moves `mcp_tools`, a generated count that
    lives ONLY in `lambdas/web/platform_counts.py` and that no branch may carry (#3101/#3984)
    — the stale-number gate would red this PR on six doc headers the reconcile job owns. The
    issue's acceptance sanctions "a new action on an existing owner tool", and this is the
    tool that owns the pain-flag surface: its own `note` is the sentence the action answers.
    `action` defaults to `read`, so every existing caller is unchanged."""
    args = args or {}
    action = str(args.get("action") or "read").strip().lower()
    if action == "dismiss":
        return _dismiss_pain_flag(args)
    if action in ("dismissals", "list_dismissals"):
        return _list_dismissals()
    if action != "read":
        return {"error": f"Unknown action '{action}'.", "valid_actions": ["read", "dismiss", "dismissals"]}
    exercise = args.get("exercise") or args.get("template_id") or ""
    lookback_days = int(args.get("lookback_days") or PREFLIGHT_LOOKBACK_DAYS)
    if not exercise:
        return {"error": "Provide 'exercise' (name) or 'template_id'."}

    template_id, matched = _resolve_template_id(exercise, lookback_days)
    if not template_id:
        return {"error": f"No exercise matching {exercise!r} found in the last {lookback_days}d of workouts.", "exercise": exercise}

    start = (pacific_now().date() - timedelta(days=lookback_days)).isoformat()
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"USER#matthew#SOURCE#{NOTES_SOURCE}#EXERCISE#{template_id}")
            & Key("sk").gte(f"DATE#{start}"),
        )
    except Exception as e:
        return {"error": f"query failed: {e}", "template_id": template_id}

    rows = [decimal_to_float(it) for it in resp.get("Items", [])]
    # Corrections win on read (sk …#CORRECTION) and survive recompute.
    corrections = {r["sk"].replace("#CORRECTION", ""): r for r in rows if r.get("sk", "").endswith("#CORRECTION")}
    # #3918: the head key is one per (workout, template, OCCURRENCE), so a workout that
    # logged this template twice now yields TWO entries instead of one. A legacy row (no
    # suffix) reads as occurrence 0 and yields to the new-scheme row for the same
    # occurrence while the re-key is pending — a migrated record is never listed twice.
    grouped: dict[str, list] = {}
    for r in rows:
        grouped.setdefault(head_sk_base(r.get("sk", "")), []).append(r)
    ordered = []
    for base in sorted(grouped):
        for occ, row in sorted(dedupe_head_rows(grouped[base]).items()):
            ordered.append((occ, row))

    timeline = []
    latest_progression = None
    pain_dates = []
    for occurrence, r in ordered:
        # A correction written against the pre-migration key still applies to the record
        # it corrected — it is found by the head's `migrated_from_sk`.
        ov = corrections.get(r.get("sk", "")) or corrections.get(str(r.get("migrated_from_sk") or ""))
        signals = (ov or {}).get("signals", r.get("signals", []))
        pain = (ov or {}).get("pain_flag", r.get("pain_flag", False))
        entry = {
            "date": r.get("date"),
            "workout_uid": r.get("workout_uid"),
            # Which logging of this template within that workout (0-based). Two entries
            # with the same date + workout_uid are two real, separately-noted blocks.
            "occurrence": occurrence,
            "note_raw": r.get("note_raw"),
            "signals": signals,
            "pain_flag": pain,
            "sentiment": (ov or {}).get("sentiment", r.get("sentiment")),
            "degraded": r.get("degraded", False),
            # #3699: a degraded row says WHY on the row itself. A row with no reason field
            # is not "unknown" — it is a record written before the extractor could say, and
            # it is reported as such rather than re-extracted (a re-derived signal in a
            # measured partition is indistinguishable from an original one, forever).
            "degraded_reason": (
                r.get("degraded_reason")
                or (f"{DEGRADE_UNRECORDED}: written before #3699 added the reason field; not re-derived" if r.get("degraded") else None)
            ),
            "corrected": bool(ov),
        }
        timeline.append(entry)
        if pain:
            pain_dates.append(r.get("date"))
        for s in signals:
            if s.get("class") == "progression" and s.get("value"):
                latest_progression = s["value"]

    # #3767: say whether the layer could be read at all, BEFORE reporting counts from it.
    # The health function has existed since this layer shipped and its docstring says "hook
    # into get_freshness_status"; it was hooked into the freshness TOOL and never into the
    # reader whose zeros it qualifies.
    try:
        from training.training_notes import training_notes_health

        health = training_notes_health(table)
    except Exception as e:  # noqa: BLE001
        health = {"checked": False, "error": f"{type(e).__name__}: {e}"}
    status, reason = derived_layer_status(health)
    dark = status in (LAYER_DARK, "unknown")

    out = {
        "exercise": matched or exercise,
        "template_id": template_id,
        "lookback_days": lookback_days,
        # The contract: a count from an unreadable layer is None, never 0. A caller that
        # sees null knows to ask get_exercise_history (the MEASURED sets) instead of
        # concluding the movement has no history.
        "sessions_with_notes": None if dark else len(timeline),
        "pain_flag_any": None if dark else bool(pain_dates),  # PROMINENT — the pre-flight pain surface (§7)
        "pain_dates": pain_dates,
        "latest_progression": latest_progression,
        "layer_status": status,
        "layer_health": health,
        "note": (
            "Derived note-signal layer (inferred, confidence-tagged); raw Hevy notes are sovereign. "
            "pain_flag is over-inclusive by design — confirm or dismiss before loading that movement."
        ),
    }
    if dark:
        out["layer_reason"] = reason
        out["measured_alternative"] = "get_exercise_history reads the raw logged sets and is unaffected by this layer."
        # No timeline key at all rather than an empty list: an empty list is a claim.
    else:
        out["timeline"] = timeline
        if reason:
            out["layer_reason"] = reason
    return out


# ══════════════════════════════════════════════════════════════════════════════
# #4036 — the other half of "confirm or dismiss before loading that movement"
# ══════════════════════════════════════════════════════════════════════════════
# The layer above flags pain over-inclusively on purpose and says so in its own `note`.
# The dismissal half had nowhere to land until now: `training_context_registry` ships in
# the bundle, so a chat turn cannot edit it (the #3675 inertness class in reverse). So the
# dismissal is a DDB record — `USER#matthew#SOURCE#training_constraints /
# DISMISSAL#<site>#<YYYY-MM-DD>`, CROSS_PHASE (ADR-077), Tier 2 owner-only — written here
# and read at runtime by `plan_engine._tripwire_states` and `critics.build_joints_packet`.
#
# It is TWO ACTIONS on this existing tool rather than a tool of its own — #4036's acceptance
# sanctions either, and the count of MCP tools is a generated literal that lives only in
# `lambdas/web/platform_counts.py`, which no branch may carry (#3101/#3984): minting one here
# would red the stale-number gate on six doc headers the reconcile job owns and this lane may
# not touch. The rule (what a dismissal is, how it re-arms) is not restated here either: it is
# imported from the registry, so this surface cannot disagree with the engines that consume
# what it writes.


def _dismissal_records() -> list:
    """Every dismissal on the record, newest first. Paginated — a partition read that stops
    at the first page reports a stale world as the live one (#3729)."""
    from training import training_context_registry as tcr

    items: list = []
    kwargs = {
        "KeyConditionExpression": Key("pk").eq(tcr.DISMISSAL_PK) & Key("sk").begins_with(tcr.DISMISSAL_SK_PREFIX),
        "ScanIndexForward": False,
    }
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return [decimal_to_float(i) for i in items]


def _list_dismissals():
    """Every owner dismissal on the record (action='dismissals').

    OWNER-ONLY. The records carry his verbatim words; nothing public reads this partition
    (`privacy.field_tiers.SOURCE_TIERS['training_constraints'] = TIER_OWNER_ONLY`).
    """
    from training import training_context_registry as tcr

    records = _dismissal_records()
    return {
        "count": len(records),
        "store": tcr.DISMISSAL_RULE["store"],
        "rule": tcr.DISMISSAL_RULE,
        "dismissals": [
            {
                "sk": r.get("sk"),
                "site": r.get("site"),
                "dismissed_on": r.get("dismissed_on"),
                "words": r.get("words"),
                "movements": r.get("movements") or [],
                "flag_note_date": r.get("flag_note_date"),
                "recorded_at": r.get("recorded_at"),
            }
            for r in records
        ],
        "how_to_use": (
            "A dismissal does not make a flag disappear — plan_next_session reads the tripwire as "
            "`dismissed_by_owner` with the date and his words, and it re-arms on its own if a later note "
            "flags the same movement. Ask him again before dismissing a site he has already re-flagged."
        ),
        "_disclaimer": (
            "For personal health tracking only. Not medical advice. Descriptive of Matthew's own n=1 history. "
            "Consult a qualified healthcare provider before making health decisions based on this data."
        ),
    }


def _dismiss_pain_flag(args):
    """action='dismiss' — the owner overrides one flag instance, in his own words."""
    from datetime import datetime, timezone

    from training import training_context_registry as tcr

    try:
        record = tcr.build_dismissal_record(
            site=args.get("site") or "",
            dismissed_on=(args.get("dismissed_on") or pacific_now().date().isoformat()),
            words=args.get("words") or "",
            movements=args.get("movements") or [m for m in (args.get("movement"), args.get("exercise")) if m][:1],
            flag_note_date=args.get("flag_note_date") or "",
            recorded_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
    except ValueError as e:
        return {"error": f"refused: {e}", "rule": tcr.DISMISSAL_RULE}

    # The dismissal must point at a flag that EXISTS. An override of nothing is not an
    # override — the same ADR-104 grounding rule manage_diary_claims applies to a claim
    # that cannot name its entry. Reported honestly, and nothing is written.
    notes = tool_get_exercise_notes({"exercise": record["movements"][0], "lookback_days": PREFLIGHT_LOOKBACK_DAYS})
    if notes.get("error"):
        return {"error": f"refused: could not read the note layer for {record['movements'][0]!r} ({notes['error']})", "wrote": False}
    if notes.get("pain_flag_any") is None:
        return {
            "error": f"refused: the derived note layer is {notes.get('layer_status')!r} for {record['movements'][0]!r} — "
            "its silence is not evidence of a flag to dismiss (#3768)",
            "wrote": False,
        }
    pain_dates = [str(d)[:10] for d in (notes.get("pain_dates") or [])]
    if record["flag_note_date"] not in pain_dates:
        return {
            "error": f"refused: no pain flag dated {record['flag_note_date']} on {record['movements'][0]!r} "
            f"(flagged note dates in the last {PREFLIGHT_LOOKBACK_DAYS}d: {pain_dates or 'none'})",
            "why": "a dismissal names the instance it dismisses, so it can be checked against it later",
            "wrote": False,
        }

    table.put_item(
        Item={
            # literal (orphan-gate greppable); == training_context_registry.DISMISSAL_PK
            "pk": "USER#matthew#SOURCE#training_constraints",
            **record,
        }
    )
    resolution = tcr.resolve_flag(movement=record["movements"][0], note_dates=pain_dates, dismissals=[record])
    return {
        "status": "dismissed",
        "wrote": True,
        "sk": record["sk"],
        "record": record,
        "reads_as": resolution,
        "next": (
            "Call plan_next_session — the pain_flag_named_site tripwire now reads `dismissed_by_owner` with this "
            "date and these words, and the joints/tendons critic will not veto the dismissed instance."
        ),
        "re_arms": tcr.DISMISSAL_RULE["re_arms"],
        "_disclaimer": (
            "For personal health tracking only. Not medical advice. Descriptive of Matthew's own n=1 history. "
            "Consult a qualified healthcare provider before making health decisions based on this data."
        ),
    }
