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

from concurrent.futures import ThreadPoolExecutor
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


def _notes_timeline(rows: list) -> tuple[list, list, object]:
    """(timeline, pain_dates, latest_progression) from raw note rows. No I/O."""
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

    timeline: list = []
    latest_progression = None
    pain_dates: list = []
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
    return timeline, pain_dates, latest_progression


def _pain_notes(timeline: list) -> list:
    """`[{date, text}]` for every flagged entry — the per-site instance input (#4174)."""
    return [{"date": str(e.get("date") or "")[:10], "text": e.get("note_raw")} for e in (timeline or []) if e.get("pain_flag")]


def pain_flags_for_templates(template_ids, start: str, layer_status: str, max_workers: int = 8) -> dict:
    """The pain-flag record for MANY exercise templates at once — the stage-1 read (#4051).

    `plan_next_session` needs every flag the layer holds for the movements he actually
    PERFORMED in the lookback, and that set is ~27 templates on a live 28-day window.
    Calling `tool_get_exercise_notes` once per template would re-run `training_notes_health`
    27 times for one answer — and that health function is itself ~28 queries. So the status
    is INJECTED: the caller resolves it once (`mcp.core.derived_layer_status`) and this
    read stamps it on every entry it returns, which is the #3769 contract — no count from
    this layer travels without the layer's own status beside it — satisfied without a
    second identical health sweep inside the same call. The parse is `_notes_timeline`, the
    same one `tool_get_exercise_notes` uses, over a key spelled from the same `NOTES_SOURCE`.

    Returns `{template_id: {"pain_flag_any", "pain_dates", "sessions_with_notes",
    "layer_status"}}`, or `{"error": ..., "layer_status": ...}` for a template whose read
    RAISED — an unreadable template is reported, never folded into the clean ones (#3767).

    **`pain_flag_any` is NOT nulled on a degraded/dark layer here**, and that is deliberate:
    `pain_flag` on a degraded row is the DETERMINISTIC pass's own verdict (the lexicon hit),
    written before the semantic pass was even attempted. The layer's health qualifies the
    ABSENCE of flags — it cannot un-say a flag that is on the record. Today's live layer is
    `degraded` (`cap_exceeded x24`, the Haiku monthly cap), and the 2026-09-13 Romanian
    Deadlift flag is one of those degraded rows: withholding it would be the #3768 failure
    pointed the other way. The status rides along so a reader can tell the two apart.
    """
    ids = [str(t) for t in (template_ids or []) if str(t or "").strip()]
    out: dict = {}
    if not ids:
        return out

    def _one(tid: str) -> tuple[str, dict]:
        try:
            # The key is spelled at the query site, not behind a helper: both the #2845 model
            # and the #3769 derived-reader guard resolve the partition from the reading
            # FUNCTION, so hiding it behind an accessor makes a real read invisible to both.
            # Its twin is in `tool_get_exercise_notes`; `NOTES_SOURCE` is the one name.
            resp = table.query(
                KeyConditionExpression=Key("pk").eq(f"USER#matthew#SOURCE#{NOTES_SOURCE}#EXERCISE#{tid}") & Key("sk").gte(f"DATE#{start}"),
            )
            timeline, pain_dates, _ = _notes_timeline([decimal_to_float(it) for it in resp.get("Items", [])])
        except Exception as e:  # noqa: BLE001
            return tid, {"error": f"{type(e).__name__}: {e}", "layer_status": layer_status}
        return tid, {
            "pain_flag_any": bool(pain_dates),
            "pain_dates": [str(d)[:10] for d in pain_dates if d],
            # #4174: each flagged note with its own words — the dismissal rule is per SITE, and
            # the note layer knows no anatomy, so the words are how a note is tied to a site.
            "pain_notes": _pain_notes(timeline),
            "sessions_with_notes": len(timeline),
            "layer_status": layer_status,
        }

    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(ids)))) as pool:
        for tid, res in pool.map(_one, ids):
            out[tid] = res
    return out


def tool_get_exercise_notes(args):
    """Per-exercise note timeline (the arc) + signals + pain flags — and, on `action`, the
    OWNER-ONLY dismissal of one of those flags (#4036, see the block at the end of this file).

    The write lives on this tool rather than on one of its own (which is what #4036's design
    note reached for first) because minting a tool moves `mcp_tools`, a generated count that
    lives ONLY in `lambdas/web/platform_counts.py` and that no branch may carry (#3101/#3984)
    — the stale-number gate would red this PR on six doc headers the reconcile job owns. The
    issue's acceptance sanctions "a new action on an existing owner tool", and this is the
    tool that owns the pain-flag surface: its own `note` is the sentence the action answers.
    `action` defaults to `read`, so every existing caller is unchanged. Because the write rides
    a read verb, `mcp/audit.py::WRITE_TOOLS_BEHIND_READ_VERB` names this tool (#4401): every
    call — read or dismiss — is classified a write, so the dismissal lands in the #753 trail."""
    args = args or {}
    action = str(args.get("action") or "read").strip().lower()
    if action == "dismiss":
        return _dismiss_pain_flag(args)
    if action in ("dismissals", "list_dismissals"):
        return _list_dismissals()
    if action == "deload":
        return _record_deload_word(args)
    if action in ("deloads", "list_deloads"):
        return _list_deload_words()
    if action in ("disruption", "disruption_end", "disruptions"):
        return {"disruption": _record_disruption, "disruption_end": _end_disruption, "disruptions": _list_disruptions}[action](args)
    if action == "travel_kit":  # #5104: the travel food kit (a read)
        return _travel_kit(args)
    if action in ("fitness_test", "fitness_tests"):  # #5078: the battery's owner write + its read (mcp/tools_fitness_tests.py)
        from mcp import tools_fitness_tests as ftt

        return (ftt.action_log if action == "fitness_test" else ftt.action_list)(args)
    if action != "read":
        return {
            "error": f"Unknown action '{action}'.",
            "valid_actions": [
                "read",
                "dismiss",
                "dismissals",
                "deload",
                "deloads",
                *_DISRUPTION_ACTIONS,
                "travel_kit",
                "fitness_test",
                "fitness_tests",
            ],
        }
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

    # The parse is shared with `pain_flags_for_templates` (#4051) — corrections, the #3918
    # occurrence keys and the legacy-row dedupe live in ONE place, so the two readers of
    # this partition cannot disagree about what a row says.
    timeline, pain_dates, latest_progression = _notes_timeline([decimal_to_float(it) for it in resp.get("Items", [])])

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


def _is_slot_tag(name: str) -> bool:
    """`anchor:hinge:moderate`, `accessory:leg_curl:accessory` — the routine generator's
    rationale tags, which a drafted row carries as its label (#4519). No exercise name has a colon."""
    return ":" in str(name or "")


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

    # #4519: a program SLOT TAG ('anchor:hinge:moderate') is not an exercise. A flag is derived
    # from an exercise's notes, so the dismissal names that exercise — refused by name here
    # rather than by the note reader's opaque "no exercise matching".
    if _is_slot_tag(record["movements"][0]):
        return {
            "error": f"refused: {record['movements'][0]!r} is a program slot tag, not an exercise — a pain flag is derived "
            "from one exercise's notes; dismiss it by that exercise's name (plan_next_session's by_site row names it as "
            "`exercise`, e.g. 'Romanian Deadlift (Barbell)')",
            "wrote": False,
        }

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

    # #4174: the preview resolves per SITE. This record covers the note it pinned (and any
    # note whose words name the site) — every other flagged note on the movement stays open
    # and is named here, so the chat asks about it instead of assuming it was covered.
    # #4519: resolved BEFORE the write — a record that would dismiss no tripped instance is
    # refused by name, never stored as an override the engines then silently ignore.
    instances = tcr.expand_instances(
        [
            {
                "movement": record["movements"][0],
                "exercise": notes.get("exercise"),
                "note_dates": pain_dates,
                "notes": _pain_notes(notes.get("timeline") or []),
            }
        ],
        [record],
    )
    resolution = next((r for r in tcr.resolve_flags(instances, [record]) if r.get("site_key") == record["site_key"]), None)
    if not (resolution or {}).get("dismissed"):
        return {
            "error": f"refused: no tripped flag matches site {record['site']!r} / movement {record['movements'][0]!r} "
            f"(flag note {record['flag_note_date']})"
            + (f" — it would read {resolution['state']}: {resolution['detail']}" if resolution else ""),
            "why": "a dismissal is stored only when it dismisses a tripped flag instance the engines will resolve (#4519)",
            "wrote": False,
        }
    still_open = [i for i in instances if i.get("site") != record["site_key"] and i.get("note_dates")]

    table.put_item(
        Item={
            # literal (orphan-gate greppable); == training_context_registry.DISMISSAL_PK
            "pk": "USER#matthew#SOURCE#training_constraints",
            **record,
        }
    )
    return {
        "status": "dismissed",
        "wrote": True,
        "sk": record["sk"],
        "record": record,
        "reads_as": resolution,
        "still_open": [
            {
                "movement": i["movement"],
                "note_dates": i["note_dates"],
                "why": "these flagged notes name no dismissed site — they need a dismissal of their own (#4174)",
            }
            for i in still_open
        ],
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


# ══════════════════════════════════════════════════════════════════════════════
# #5070 — the deload is the owner's call (ruling 2026-10-18)
# ══════════════════════════════════════════════════════════════════════════════
# No schedule, no automatic deload: fatigue signals RECOMMEND (plan_next_session's `deload_recommendation`), and a
# deload applies only on a record of his word — `USER#matthew#SOURCE#training_constraints / DELOAD#<start_date>`,
# the same partition and the same chat path as the pain-flag dismissal, so this is one more ACTION on this existing
# owner tool (no new tool, so no generated count moves). The rule and the record shape live in `training.deload_word`.


def _deload_records() -> list:
    """Every recorded deload word, newest first. Paginated (#3729) — read by `mcp.tools_plan._deload_records`."""
    from training import deload_word

    items: list = []
    kwargs = {
        "KeyConditionExpression": Key("pk").eq(deload_word.DELOAD_PK) & Key("sk").begins_with(deload_word.DELOAD_SK_PREFIX),
        "ScanIndexForward": False,
    }
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return [decimal_to_float(i) for i in items]


def _list_deload_words():
    """action='deloads' — every recorded deload word (OWNER-ONLY: verbatim words)."""
    from training import deload_word

    return {
        "count": len(_deload_records()),
        "store": deload_word.DELOAD_STORE,
        "policy": deload_word.policy(),
        "deloads": [
            {k: r.get(k) for k in ("sk", "start_date", "days", "sets_pct", "loads", "words", "recorded_at")} for r in _deload_records()
        ],
    }


def _record_deload_word(args):
    """action='deload' — record the owner's word that a deload starts on `start_date` (default today, Pacific)."""
    from datetime import datetime, timezone

    from training import deload_word

    try:
        record = deload_word.build_deload_record(
            start_date=args.get("start_date") or pacific_now().date().isoformat(),
            words=args.get("words") or "",
            days=args.get("days"),
            sets_pct=args.get("sets_pct"),
            recorded_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
    except ValueError as e:
        return {"error": f"refused: {e}", "policy": deload_word.policy(), "wrote": False}
    table.put_item(
        Item={
            # literal (orphan-gate greppable); == training.deload_word.DELOAD_PK
            "pk": "USER#matthew#SOURCE#training_constraints",
            **record,
        }
    )
    return {
        "status": "recorded",
        "wrote": True,
        "sk": record["sk"],
        "record": record,
        "next": (
            "Call plan_next_session — for the days in this window the served session is a deload "
            f"({record['sets_pct']} % sets, loads held, {record['days']} days) and `deload_recommendation.applied` reads true."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════════
# #5088 — disruption mode is the owner's switch (ruling 2026-10-18: a late-December trip)
# ══════════════════════════════════════════════════════════════════════════════
# The same partition and the same chat path as the deload word: `USER#matthew#SOURCE#training_constraints /
# MODE#disruption#<start_date>` with `until`, `template` (travel|busy) and `words` VERBATIM. ON holds habits instead of
# targets; OFF (`disruption_end`) starts the step-back-up week. The coach OFFERS it (plan_next_session's
# `disruption.offer`) and never writes it. The rule and the record shape live in `training.disruption`.
_DISRUPTION_ACTIONS = ("disruption", "disruption_end", "disruptions")


def _disruption_records() -> list:
    """Every disruption record, newest first. Paginated — read by `mcp.tools_plan._disruption_records`."""
    from training import disruption

    items: list = []
    kwargs = {
        "KeyConditionExpression": Key("pk").eq(disruption.DISRUPTION_PK) & Key("sk").begins_with(disruption.DISRUPTION_SK_PREFIX),
        "ScanIndexForward": False,
    }
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return [decimal_to_float(i) for i in items]


def _list_disruptions(args=None):
    """action='disruptions' — every record and today's state (OWNER-ONLY: verbatim words)."""
    from training import disruption
    from training.routine_generator import _load_json

    records = _disruption_records()
    movements = (_load_json("movement_catalog.json") or {}).get("movements") or {}
    return {
        "templates": disruption.templates_preview(movements),
        "count": len(records),
        "store": disruption.DISRUPTION_STORE,
        "today": disruption.state(records, pacific_now().date().isoformat()),
        "policy": disruption.policy(),
        "records": records,
        "travel_food": _travel_food_reminder(),
    }


def _travel_food_reminder() -> dict:
    """#5104: the travel food kit's dated reminder row (dates only), beside the travel templates it goes with."""
    from health import travel_food

    return travel_food.calibration_row(pacific_now().date().isoformat())


def _positive_int(v, name: str):
    if v is None or v == "":
        return None, None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None, f"{name} must be a whole number, got {v!r}"
    return (n, None) if n > 0 else (None, f"{name} must be positive, got {v!r}")


def _travel_kit(args=None):
    """action='travel_kit' (#5104, OWNER-ONLY READ) — the travel food kit: the day plan at today's resolved travel-day
    target (and at the maintenance-week target: the trip is a planned maintenance week), the grocery list, the packing
    list and the hotel/restaurant playbook, all built by `health.travel_food` from the charter. The maintenance target is
    `maintenance_kcal` when given, else #5107's own estimate (`health.maintenance_week.estimate` over
    `tools_nutrition.expenditure_reconciliation`, the seam the titration leg reads); an estimate that is not actionable
    leaves the kit's `maintenance_pending` with the reason. Nothing is written."""
    from health import calorie_target, maintenance_week, travel_food

    from mcp import tools_nutrition

    args = args or {}
    maint, err = _positive_int(args.get("maintenance_kcal"), "maintenance_kcal")
    days, err2 = _positive_int(args.get("trip_days"), "trip_days")
    if err or err2:
        return {"error": err or err2}
    today = pacific_now().date().isoformat()
    target = calorie_target.resolve(today, day_type="travel")
    if maint is not None:
        source = {"source": "argument", "kcal": maint}
    else:
        est = maintenance_week.estimate(tools_nutrition.expenditure_reconciliation(today))
        maint = est.get("kcal")
        source = {"source": "health.maintenance_week.estimate (#5107)", **est}
    kit = travel_food.build(target.get("kcal"), maintenance_kcal=maint, days=days)
    if maint is None and source.get("reason"):
        kit["maintenance_pending"] = f"no actionable maintenance estimate (#5107): {source['reason']}"
    kit["maintenance_estimate"] = source
    kit["calorie_target"] = {k: target.get(k) for k in ("kcal", "source", "provenance", "day_type")}
    kit["reminder"] = travel_food.calibration_row(today)
    return kit


def _now_z() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _put_disruption(record: dict) -> None:
    # literal (orphan-gate greppable); == training.disruption.DISRUPTION_PK
    table.put_item(Item={"pk": "USER#matthew#SOURCE#training_constraints", **record})


def _record_disruption(args):
    """action='disruption' — his word that the mode is ON from `start_date` (default today, Pacific) through `until`."""
    from common.pacific_time import shift_day_key
    from training import disruption, life_disruption

    start = args.get("start_date") or pacific_now().date().isoformat()
    template = str(args.get("template") or "").strip().lower()
    until = args.get("until") or ""
    if not until and life_disruption.template(template).get("lapse"):  # #5122: the lapse protocol's own length
        until = shift_day_key(str(start)[:10], disruption.template_max_days(template) - 1)
    try:
        record = disruption.build_disruption_record(
            start_date=start, until=until, words=args.get("words") or "", template=template, recorded_at=_now_z()
        )
    except ValueError as e:
        return {"error": f"refused: {e}", "policy": disruption.policy(), "wrote": False}
    _put_disruption(record)
    return {
        "status": "recorded",
        "wrote": True,
        "sk": record["sk"],
        "record": record,
        "holds": disruption.holds(record["template"]),
        "whole_day": life_disruption.mode([record], record["start_date"]) if life_disruption.is_whole_day(record["template"]) else None,
        "next": "plan_next_session reads `disruption.active: true` for these days; the drafted session is the short one.",
    }


def _end_disruption(args):
    """action='disruption_end' — his word that the mode is OFF from `ended_on` (default today): the step-back-up starts."""
    from training import disruption

    ended_on = args.get("ended_on") or pacific_now().date().isoformat()
    rec = disruption.active_record(_disruption_records(), ended_on)
    if rec is None:
        return {"error": f"refused: no disruption mode covers {ended_on}", "wrote": False}
    try:
        record = disruption.end_record(rec, ended_on=ended_on, words=args.get("words") or "", recorded_at=_now_z())
    except ValueError as e:
        return {"error": f"refused: {e}", "wrote": False}
    record.pop("pk", None)
    _put_disruption(record)
    return {"status": "ended", "wrote": True, "sk": record["sk"], "record": record, "step_back_up": disruption.policy().get("step_back_up")}
