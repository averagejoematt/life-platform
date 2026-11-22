"""tools_chapter_corrections.py — the owner's door for dated public corrections to published chapters (#6177).

``manage_chapter_corrections`` is the ONLY writer of the ``CHAPTER_CORRECTION#`` rows in the chronicle partition
(``lambdas/content/chapter_corrections.py`` holds the record's rules). Three actions:

  * ``list``    — every correction on record (or one chapter's), proposed and approved, with what would render.
  * ``propose`` — write ONE new correction, unapproved: written once under ``attribute_not_exists(sk)``. A proposal
                  renders nowhere. To change a proposal's words, propose a new one that ``supersedes`` it.
  * ``approve`` — record Matthew's explicit approval on ONE proposal: appends the approval entry and stamps the day
                  and the platform's signature, once (a second approve is refused). Only after he approved THIS
                  correction in the conversation; ``approved`` must be exactly true. The site shows it from the next
                  site build (the chapter page, the story list, the feed).

Nothing here edits a chapter, deletes a record or sends anything: no email, no notification.
"""

from __future__ import annotations

from datetime import datetime, timezone

from boto3.dynamodb.conditions import Key
from common.pacific_time import pacific_today
from content import chapter_corrections as CC

from mcp.config import USER_ID, logger, table as _table_ref

MCC_DESCRIPTION = (
    "#6177: dated PUBLIC corrections to published chapters, signed by the platform ('Correction, <date> — Average Joe "
    "Matt editorial record'), never by a persona. action='list' (optional chapter_id) shows every correction on record "
    "and whether it renders. action='propose' writes ONE unapproved correction: chapter_id (the v9 id, e.g. week-09), "
    "correction_id (lowercase slug), kind ('correction' | 'qualification'), published_said (what the chapter published), "
    "record_shows (what the record shows), evidence (where it is checked), optional supersedes (an earlier correction_id "
    "of the same chapter). A proposal renders nowhere. action='approve' records Matthew's approval on ONE proposal: "
    "chapter_id, correction_id, approved=true — ONLY after he explicitly approved THIS correction's exact words; never "
    "inferred. Approval dates it today (Pacific) and it appears on the site from the next build. Records are append-only: "
    "nothing is edited or deleted; replace one by proposing a new one that supersedes it."
)

MCC_INPUT = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["list", "propose", "approve"], "description": "list, propose one, or approve one."},
        "chapter_id": {"type": "string", "description": "The chapter's v9 id (week-NN, as in /story/week-NN/)."},
        "correction_id": {"type": "string", "description": "propose/approve: the correction's id (lowercase letters, digits, hyphens)."},
        "kind": {"type": "string", "enum": ["correction", "qualification"], "description": "propose: correction or qualification."},
        "published_said": {"type": "string", "description": "propose: what the chapter published, in one or two sentences."},
        "record_shows": {"type": "string", "description": "propose: what the record shows, in one or two sentences."},
        "evidence": {"type": "string", "description": "propose: the evidence reference a reader can check (public records only)."},
        "supersedes": {"type": "string", "description": "propose: optional — the correction_id this one replaces (same chapter)."},
        "approved": {
            "type": "boolean",
            "description": "approve: MUST be exactly true, and only after Matthew explicitly approved THIS correction. Never inferred.",
        },
        "note": {"type": "string", "description": "approve: optional short note kept in the approval history."},
    },
    "required": ["action"],
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rows(chapter_id: str | None = None) -> list:
    prefix = CC.SK_PREFIX + (f"{chapter_id}#" if chapter_id else "")
    kw = {"KeyConditionExpression": Key("pk").eq(CC.pk(USER_ID)) & Key("sk").begins_with(prefix)}
    out: list = []
    while True:
        resp = _table_ref.query(**kw)
        out.extend(resp.get("Items") or [])
        if not resp.get("LastEvaluatedKey"):
            return out
        kw["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def _listing(rows: list) -> dict:
    public = {(c["chapter_id"], c["id"]): c for c in CC.public_view(rows)}
    items = []
    for r in sorted(rows, key=lambda r: str(r.get("sk"))):
        key = (r.get("chapter_id"), r.get("correction_id"))
        items.append(
            {
                "chapter_id": r.get("chapter_id"),
                "correction_id": r.get("correction_id"),
                "kind": r.get("kind"),
                "published_said": r.get("published_said"),
                "record_shows": r.get("record_shows"),
                "evidence": r.get("evidence"),
                "supersedes": r.get("supersedes"),
                "proposed_at": r.get("proposed_at"),
                "approved": bool(r.get("approvals")),
                "dated_on": r.get("dated_on"),
                "signature": r.get("signature"),
                "renders": key in public,
                "superseded_by": (public.get(key) or {}).get("superseded_by"),
            }
        )
    return {"corrections": items, "count": len(items), "rendering": len(public)}


def _propose(args: dict) -> dict:
    try:
        item = CC.new_proposal(
            chapter_id=str(args.get("chapter_id") or "").strip(),
            correction_id=str(args.get("correction_id") or "").strip(),
            kind=str(args.get("kind") or "").strip(),
            published_said=args.get("published_said"),
            record_shows=args.get("record_shows"),
            evidence=args.get("evidence"),
            proposed_at=_now(),
            supersedes=(str(args["supersedes"]).strip() or None) if args.get("supersedes") else None,
            user_id=USER_ID,
        )
    except CC.CorrectionError as exc:
        return {"error": f"{exc}. Nothing was stored."}
    if item["supersedes"]:
        prior = _table_ref.get_item(Key={"pk": item["pk"], "sk": CC.sk(item["chapter_id"], item["supersedes"])}).get("Item")
        if not prior:
            return {"error": f"supersedes names no correction of {item['chapter_id']}: {item['supersedes']}. Nothing was stored."}
    try:
        _table_ref.put_item(Item=item, ConditionExpression="attribute_not_exists(sk)")
    except Exception as exc:  # noqa: BLE001
        if "ConditionalCheckFailed" in str(exc) or "ConditionalCheckFailed" in type(exc).__name__:
            return {
                "error": f"{item['correction_id']} already exists for {item['chapter_id']}; records are append-only. Nothing was stored."
            }
        logger.warning(f"[#6177] correction proposal write failed: {type(exc).__name__}")
        return {"error": f"the proposal could not be stored ({type(exc).__name__}). Nothing was stored."}
    return {"stored": True, "approved": False, "renders": False, "chapter_id": item["chapter_id"], "correction_id": item["correction_id"]}


def _approve(args: dict) -> dict:
    if args.get("approved") is not True:
        return {"error": "approved must be exactly true, given only after Matthew explicitly approved this correction. Nothing was stored."}
    chapter_id = str(args.get("chapter_id") or "").strip()
    correction_id = str(args.get("correction_id") or "").strip()
    key = {"pk": CC.pk(USER_ID), "sk": CC.sk(chapter_id, correction_id)}
    item = _table_ref.get_item(Key=key, ConsistentRead=True).get("Item")
    if not item or item.get("record_type") != CC.RECORD_TYPE:
        return {"error": f"no proposed correction {correction_id} for {chapter_id}. Nothing was stored."}
    if item.get("approvals"):
        return {"error": f"{correction_id} is already approved (dated {item.get('dated_on')}). Nothing was stored."}
    day = pacific_today()
    try:
        entry = CC.approval(at=_now(), dated_on=day, note=str(args.get("note") or ""))
        sig = CC.signature(item["kind"], day)
        CC.validate({**item, "approvals": [entry], "dated_on": day, "signature": sig})  # what will be served, checked first
    except CC.CorrectionError as exc:
        return {"error": f"{exc}. Nothing was stored."}
    try:
        _table_ref.update_item(
            Key=key,
            UpdateExpression="SET approvals = list_append(approvals, :a), approved_at = :at, dated_on = :d, signature = :s",
            ConditionExpression="attribute_exists(sk) AND size(approvals) = :zero",
            ExpressionAttributeValues={":a": [entry], ":at": entry["at"], ":d": day, ":s": sig, ":zero": 0},
        )
    except Exception as exc:  # noqa: BLE001
        if "ConditionalCheckFailed" in str(exc) or "ConditionalCheckFailed" in type(exc).__name__:
            return {"error": f"{correction_id} changed under the approval (already approved?). Nothing was stored."}
        logger.warning(f"[#6177] correction approval write failed: {type(exc).__name__}")
        return {"error": f"the approval could not be stored ({type(exc).__name__}). Nothing was stored."}
    return {"stored": True, "approved": True, "chapter_id": chapter_id, "correction_id": correction_id, "dated_on": day, "signature": sig}


def tool_manage_chapter_corrections(args):
    """List, propose or approve a dated public correction to a published chapter."""
    args = args or {}
    action = str(args.get("action") or "list").strip()
    if action == "list":
        chapter_id = str(args.get("chapter_id") or "").strip() or None
        if chapter_id and not CC.CHAPTER_ID.match(chapter_id):
            return {"error": "chapter_id must be week-NN."}
        return _listing(_rows(chapter_id))
    if action == "propose":
        return _propose(args)
    if action == "approve":
        return _approve(args)
    return {"error": f"unknown action {action!r}: list, propose or approve."}
