"""lambdas/emails/chronicle_personas.py — the chronicle's PERSONA# layer, split
out of wednesday_chronicle_lambda.py (#1654).

One cohesive unit: everything that reads or writes a ``PERSONA#<slug>`` partition
and the editorial pass built on top of it.

  * Elena Voss (``PERSONA#elena``, #537) — her persistent notebook rendered as
    prompt obligations (open threads, the promise ledger, running motifs, her
    receipts-backed stance), and the async invoke that refreshes that memory
    after a week publishes.
  * Margaret Calloway (``PERSONA#margaret``, #548) — her red pen: the due-callback
    cross-reference she critiques against, the published editor's-note ledger that
    drives the <=1/month gate, the Haiku call both her critique and Elena's
    revision ride, and the pass that ties them together.

They belong together because they share one storage convention (the PERSONA#
partitions), one failure posture (fail-soft — a persona lookup must never cost a
week), and one consumer: the handler's draft->publish path. Nothing here decides
whether a week ships; it only shapes the prose.

No public contract changed by the move: ``wednesday_chronicle_lambda`` keeps a
delegator of the same name and signature for every function below, and each
helper reads the facade's live (possibly monkeypatched) module state through the
per-call ``_g`` globals hand-off used by the other chronicle_* modules — including
``datetime``, so a test that freezes the clock on the facade still freezes it here.
The facade's own names are re-read through ``_g`` at call time too, so patching
e.g. ``wednesday_chronicle_lambda._due_callback_promises`` still takes effect
inside the edit pass. This module does NOT import the facade — no import cycle.
"""

import json
import os

from experiment.phase_filter import singleton_visible  # ADR-058 / #946 / #1200

# Elena's memory partition (#537) — her callback ledger is Margaret's critique
# input. Margaret's own small partition (published editor's-note history, for
# the <=1/month gate) follows the same PERSONA#<slug> convention.
_ELENA_PERSONA_PK = "PERSONA#elena"
_MARGARET_PERSONA_PK = "PERSONA#margaret"


# ══════════════════════════════════════════════════════════════════════════════
# ELENA — the persistent notebook (#537)
# ══════════════════════════════════════════════════════════════════════════════


def _elena_notebook_block(current_week, *, _g):
    """#537: Elena's persistent memory (PERSONA#elena, maintained post-publish by
    elena-state-updater) rendered as prompt obligations: open threads with ages,
    the promise ledger (due/overdue callbacks — the payoff is ENFORCED here, not
    hoped for), running motifs, and her editorial stance with receipts. This is
    structured continuity on top of the raw prior-installment dump. Fail-soft ""."""
    table = _g["table"]
    logger = _g["logger"]
    try:
        from boto3.dynamodb.conditions import Key as _Key

        pk = _ELENA_PERSONA_PK
        parts = []

        stance = table.get_item(Key={"pk": pk, "sk": "STANCE#latest"}).get("Item") or {}
        # #1200: a reset tombstones PERSONA#elena singletons — never carry a wiped
        # cycle's stance into the current draft (the phantom-citation failure #946 names).
        if stance.get("headline_stance") and not stance.get("grounding_flag") and singleton_visible(stance):
            parts.append("YOUR EDITORIAL STANCE (it evolves only with receipts — never claim a change you can't back):")
            parts.append(f"  {stance['headline_stance']}")
            for p in (stance.get("positions") or [])[:5]:
                parts.append(f"  - position: {p}")
            if stance.get("how_my_stance_changed"):
                parts.append(f"  How my read changed after last week: {stance['how_my_stance_changed']}")

        resp = table.query(KeyConditionExpression=_Key("pk").eq(pk) & _Key("sk").begins_with("THREAD#"), ScanIndexForward=False, Limit=60)
        # #1200: drop tombstoned/non-current-phase threads so cycle-N threads don't leak into cycle-N+1 drafts.
        open_threads = [t for t in resp.get("Items", []) if t.get("status") == "open" and singleton_visible(t)][:8]
        if open_threads:
            parts.append("OPEN STORY THREADS (advance, resolve, or complicate — a thread stuck 3+ weeks must move or close):")
            for t in open_threads:
                opened = int(t.get("opened_week") or current_week)
                last_ref = int(t.get("last_referenced_week") or opened)
                stale = " [STALE — close it or complicate it THIS week]" if (current_week - last_ref) >= 3 else ""
                parts.append(f"  - [opened wk {opened}, age {max(0, current_week - opened)} wk]{stale} {t.get('slug')}: {t.get('summary')}")

        resp = table.query(KeyConditionExpression=_Key("pk").eq(pk) & _Key("sk").begins_with("CALLBACK#"), ScanIndexForward=False, Limit=60)
        # #1200: a wiped cycle's promises must not be "paid off" in the new cycle's draft.
        pending = [c for c in resp.get("Items", []) if c.get("status") == "pending" and singleton_visible(c)]
        due = sorted(
            (c for c in pending if int(c.get("due_by_week") or 10**6) <= current_week), key=lambda c: int(c.get("due_by_week") or 0)
        )
        upcoming = sorted(
            (c for c in pending if int(c.get("due_by_week") or 10**6) > current_week), key=lambda c: int(c.get("due_by_week") or 0)
        )
        if due:
            parts.append("PROMISES DUE (you made these to readers — PAY EACH OFF this week, or explicitly extend it in-text):")
            for c in due[:5]:
                overdue = current_week - int(c.get("due_by_week") or current_week)
                tag = f"OVERDUE by {overdue} wk" if overdue > 0 else "due now"
                parts.append(f"  - [made wk {c.get('made_in_week')}, {tag}] {c.get('promise')}")
        if upcoming:
            parts.append("PROMISES OUTSTANDING (not yet due — keep them alive, don't pay them off early without reason):")
            for c in upcoming[:4]:
                parts.append(f"  - [due wk {c.get('due_by_week')}] {c.get('promise')}")

        motif_state = table.get_item(Key={"pk": pk, "sk": "MOTIF#state"}).get("Item") or {}
        if not singleton_visible(motif_state):  # #1200: don't carry a wiped cycle's running motifs
            motif_state = {}
        motifs = [m.get("phrase") if isinstance(m, dict) else str(m) for m in (motif_state.get("motifs") or [])[:6]]
        motifs = [m for m in motifs if m]
        if motifs:
            parts.append("YOUR RUNNING MOTIFS (yours to reuse sparingly — at most one per installment): " + "; ".join(motifs))

        if not parts:
            return ""
        return "\n\n=== YOUR NOTEBOOK (persistent memory — carried across installments) ===\n" + "\n".join(parts)
    except Exception as e:
        logger.warning(f"[elena-notebook] block build failed (fail-soft): {e}")
        return ""


def _invoke_elena_state_updater(date_str, *, _g):
    """#537: async-invoke the post-publish state extraction. Publish paths only —
    a draft never updates her memory. Fail-soft: a missed invoke means her
    notebook ages a week, never a failed publish."""
    boto3 = _g["boto3"]
    logger = _g["logger"]
    try:
        lam = boto3.client("lambda", region_name="us-west-2")
        lam.invoke(
            FunctionName=os.environ.get("ELENA_STATE_UPDATER_NAME", "elena-state-updater"),
            InvocationType="Event",
            Payload=json.dumps({"date": date_str}).encode(),
        )
        logger.info(f"[elena-state] invoked for {date_str}")
    except Exception as e:
        logger.warning(f"[elena-state] invoke failed (non-fatal): {e}")


# ══════════════════════════════════════════════════════════════════════════════
# #548: MARGARET CALLOWAY'S RED PEN — critique + conditional revision, pre-publish
# ══════════════════════════════════════════════════════════════════════════════


def _due_callback_promises(week_num, limit=5, *, _g):
    """#548: promises due THIS WEEK from Elena's ledger (#537, PERSONA#elena
    CALLBACK# items) — Margaret's critique input ('you owe the reader the
    follow-up you promised'). Fail-soft []: a lookup failure just means her
    critique runs without the ledger cross-reference."""
    table = _g["table"]
    logger = _g["logger"]
    try:
        from boto3.dynamodb.conditions import Key as _Key

        resp = table.query(
            KeyConditionExpression=_Key("pk").eq(_ELENA_PERSONA_PK) & _Key("sk").begins_with("CALLBACK#"),
            ScanIndexForward=False,
            Limit=60,
        )
        # #1200: honor restart tombstones — a wiped cycle's promises aren't owed in the new cycle.
        pending = [c for c in resp.get("Items", []) if c.get("status") == "pending" and singleton_visible(c)]
        due = [c for c in pending if int(c.get("due_by_week") or 10**6) <= week_num]
        return [c["promise"] for c in due[:limit] if c.get("promise")]
    except Exception as e:
        logger.warning(f"[margaret] due-callback query failed (fail-soft): {e}")
        return []


def _margaret_last_note_date(*, _g):
    """The date of Margaret's last published editor's note (PERSONA#margaret
    NOTE#latest), or None. Drives the <=1/month deterministic gate."""
    table = _g["table"]
    logger = _g["logger"]
    try:
        item = table.get_item(Key={"pk": _MARGARET_PERSONA_PK, "sk": "NOTE#latest"}).get("Item")
        return (item or {}).get("date")
    except Exception as e:
        logger.warning(f"[margaret] last-note lookup failed (fail-soft): {e}")
        return None


def _record_margaret_note(date_str, week_num, note, *, _g):
    """Persist a published editor's note so the next run's <=1/month gate sees it."""
    table = _g["table"]
    logger = _g["logger"]
    datetime = _g["datetime"]
    timezone = _g["timezone"]
    try:
        item = {
            "pk": _MARGARET_PERSONA_PK,
            "sk": f"NOTE#{date_str}",
            "date": date_str,
            "week_number": week_num,
            "note": note,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        table.put_item(Item=item)
        table.put_item(Item={**item, "sk": "NOTE#latest"})
    except Exception as e:
        logger.warning(f"[margaret] failed to record editor's note (non-fatal): {e}")


def _margaret_haiku_call(system, user, *, _g):
    """One Haiku call (Bedrock via retry_utils) — used for both Margaret's
    critique and Elena's Haiku-tier revision. Kept to Haiku per the #548
    +2-calls/week budget (Elena's own Sonnet voice is reserved for the
    weekly draft itself)."""
    from common import retry_utils

    return retry_utils.call_anthropic_api(
        prompt=user,
        max_tokens=1500,
        system=system,
        temperature=0.3,
        timeout=60,
        model=_g["AI_MODEL_HAIKU"],
    )


def _run_margaret_edit_pass(raw_installment, week_num, date_str, elena_prompt, allowed_numbers, *, _g):
    """#548: Margaret Calloway's red pen. A critique + conditional revision pass
    over Elena's already-drafted, already-grounded (ADR-104) installment —
    post-draft, pre-publish. Tier-1 paused (matches coach_narrative — narrative
    embellishments pause before the flagship chronicle itself, which survives
    to tier 2). At most 2 Haiku calls total; fail-soft everywhere — any failure
    (budget pause, bad JSON, a rejected revision) simply returns Elena's draft
    untouched.

    The three persona helpers it needs are reached through `_g` (the facade's
    delegators), not by direct module-local call, so a test that monkeypatches
    them on `wednesday_chronicle_lambda` still intercepts them here."""
    logger = _g["logger"]
    try:
        from ai.budget_guard import allow as _budget_allow

        if not _budget_allow("chronicle_editor"):
            logger.info("[margaret] budget tier pauses the editor pass — keeping Elena's draft as-is")
            return raw_installment
    except ImportError:
        pass

    try:
        from ai import margaret_editor_pass as _mep

        board_loader = _g.get("board_loader")
        config = board_loader.load_board(_g["s3"], _g["S3_BUCKET"]) if _g["_HAS_BOARD_LOADER"] else None
        narrator = _mep.build_narrator(config)
        due_callbacks = _g["_due_callback_promises"](week_num)
        note_eligible = _mep.editors_note_eligible(_g["_margaret_last_note_date"](), date_str)
        _haiku = _g["_margaret_haiku_call"]

        result = _mep.run_pass(
            raw_installment,
            week_num,
            due_callbacks,
            allowed_numbers,
            note_eligible,
            narrator,
            critique_fn=_haiku,
            # Elena revises in her own voice — elena_prompt IS the system prompt;
            # the revise callable ignores the (unused) system arg run_pass passes it.
            revise_fn=lambda _system, user: _haiku(elena_prompt, user),
        )
        if result["revised"]:
            logger.info(f"[margaret] Week {week_num} revised ({result['revision_reason']})")
        elif result["critique"] is not None:
            logger.info(f"[margaret] Week {week_num} critique kept as-is ({result['revision_reason']})")
        if result["editors_note"]:
            _g["_record_margaret_note"](date_str, week_num, result["editors_note"])
            logger.info(f"[margaret] editor's note published for Week {week_num}")
        return result["final_text"]
    except ImportError as e:
        logger.warning(f"[margaret] edit-pass module unavailable (fail-soft): {e}")
        return raw_installment
    except Exception as e:
        logger.warning(f"[margaret] edit pass failed (fail-soft, keeping Elena's draft): {e}")
        return raw_installment
