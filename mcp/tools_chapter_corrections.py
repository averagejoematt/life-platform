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

#6193 adds the SECOND-EDITION actions on the same door (``lambdas/content/chapter_editions.py`` holds their rules; the
tool count is unchanged):

  * ``list_editions``    — every edition, archival rendering and first-edition evidence record (or one chapter's), with
                           whether each would render and why not (the switch, the evidence record, the gates).
  * ``propose_edition``  — write ONE edition (number 2..9) of a published chapter: its full text, its original
                           first-published day, the corrections it carries. Every publication gate runs first; a
                           finding refuses the proposal. Unapproved, it renders nowhere.
  * ``approve_edition``  — record Matthew's explicit approval on ONE edition (``approved`` exactly true): refused unless
                           the first edition's private evidence record exists (``scripts/chronicle_edition_backup.py``),
                           every carried correction is approved, and every gate passes again. Stamps ``revised_on``
                           (today, Pacific) and the platform's signature, once.
  * ``propose_archival`` / ``approve_archival`` — the same for an ARCHIVAL RENDERING of the first edition: separately
                           stored text, never derived from the original, gated at both steps; approval needs an approved
                           edition of the chapter. Without one, that chapter has no ``first-edition`` page. An optional
                           ``as_of`` day names when the rendered text stood, for a chapter rewritten after publication.
  * ``withdraw_edition`` / ``withdraw_archival`` — Matthew's per-chapter rollback (#6193 B7): ONE approved edition (or
                           rendering) stops serving, by an appended, dated withdrawal record (``approved`` exactly true,
                           never inferred). That chapter serves its first edition again; every other chapter is untouched;
                           a re-approval is a new edition number.

An edition's text opens with its title line and its summary line (#6193 B4); a title line that is not the chapter's
published title (read from the chapter's own public page) refuses the proposal — an edition never retitles a chapter.

An edition approval writes ONE row of its own: it never changes the chronicle row, the journal page, the feed manifest or
a delivery marker, and it never invokes a sender — no feed item, no new date, no subscriber mail.

Nothing here edits a chapter, deletes a record or sends anything: no email, no notification.
"""

from __future__ import annotations

import html
import re
import urllib.request
from datetime import datetime, timezone

from boto3.dynamodb.conditions import Key
from common.pacific_time import pacific_today
from content import chapter_corrections as CC, chapter_editions as CE, private_call_check

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
    "nothing is edited or deleted; replace one by proposing a new one that supersedes it. #6193 second editions (same "
    "rules, nothing renders until approved and the switch is on): action='list_editions' (optional chapter_id); "
    "'propose_edition' chapter_id, edition (2-9), text (the full chapter, markdown), first_published (the original "
    "YYYY-MM-DD), optional carries (approved correction_ids it makes); 'approve_edition' chapter_id, edition, approved=true, sha256 "
    "— refused until the first edition's private backup AND its restore rehearsal are recorded (scripts/chronicle_edition_backup.py --apply); "
    "'propose_archival' chapter_id, archival_id (1-99), text (a privacy-safe rendering of the first edition, never the raw "
    "original), optional as_of (YYYY-MM-DD the rendered text stood, for a chapter rewritten after publication); "
    "'approve_archival' chapter_id, archival_id, approved=true, sha256 (of the exact approved text). An edition's text opens "
    "with its title line (the chapter's published title in quotation marks) and its summary as one italic line; the summary "
    "becomes the chapter's summary everywhere while the edition is served. 'withdraw_edition' chapter_id, edition, "
    "approved=true (or 'withdraw_archival' chapter_id, archival_id, approved=true) — ONLY after Matthew explicitly asked to "
    "withdraw it: that chapter serves its first edition again, others untouched, a re-approval is a new number. Every text "
    "passes the publication gates (content filter, private calls, truth checks) at proposal and approval. No feed item, no "
    "new date, no mail."
)

MCC_INPUT = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": [
                "list",
                "propose",
                "approve",
                "list_editions",
                "propose_edition",
                "approve_edition",
                "propose_archival",
                "approve_archival",
                "withdraw_edition",
                "withdraw_archival",
            ],
            "description": "Corrections: list, propose, approve. Second editions (#6193): list_editions, propose/approve/withdraw_edition, propose/approve/withdraw_archival.",
        },
        "chapter_id": {"type": "string", "description": "The chapter's v9 id (week-NN, as in /story/week-NN/)."},
        "correction_id": {"type": "string", "description": "propose/approve: the correction's id (lowercase letters, digits, hyphens)."},
        "kind": {"type": "string", "enum": ["correction", "qualification"], "description": "propose: correction or qualification."},
        "published_said": {"type": "string", "description": "propose: what the chapter published, in one or two sentences."},
        "record_shows": {"type": "string", "description": "propose: what the record shows, in one or two sentences."},
        "evidence": {"type": "string", "description": "propose: the evidence reference a reader can check (public records only)."},
        "supersedes": {"type": "string", "description": "propose: optional — the correction_id this one replaces (same chapter)."},
        "approved": {
            "type": "boolean",
            "description": "approve*/withdraw*: MUST be exactly true, and only after Matthew explicitly approved THIS act. Never inferred.",
        },
        "note": {"type": "string", "description": "approve: optional short note kept in the approval history."},
        "edition": {
            "type": "integer",
            "description": "propose_edition/approve_edition: the edition number, 2-9 (the published chapter is the first).",
        },
        "archival_id": {"type": "integer", "description": "propose/approve/withdraw_archival: the rendering's number, 1-99."},
        "as_of": {
            "type": "string",
            "description": "propose_archival: optional YYYY-MM-DD the rendered text stood, when it is not the first edition (a rewrite).",
        },
        "text": {"type": "string", "description": "propose_edition/propose_archival: the full text, in the chronicle's markdown."},
        "first_published": {"type": "string", "description": "propose_edition: the chapter's original publication day, YYYY-MM-DD."},
        "carries": {"type": "array", "items": {"type": "string"}, "description": "propose_edition: correction_ids this edition makes."},
        "sha256": {
            "type": "string",
            "description": "approve_edition/approve_archival: the SHA-256 of the exact text Matthew approved; must equal the stored text's.",
        },
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


# ── #6193: second editions and the first edition's archival rendering ─────────────────────────────


def _edition_rows(chapter_id: str | None = None) -> list:
    prefix = CE.SK_PREFIX + (f"{chapter_id}#" if chapter_id else "")
    kw = {"KeyConditionExpression": Key("pk").eq(CE.pk(USER_ID)) & Key("sk").begins_with(prefix)}
    out: list = []
    while True:
        resp = _table_ref.query(**kw)
        out.extend(resp.get("Items") or [])
        if not resp.get("LastEvaluatedKey"):
            return out
        kw["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def _tainted():
    """``web.narrative_publication.is_tainted`` over the complete withheld-call record, read now, OR'd with the words of
    every coach output row the provenance policy withholds (``web.withheld_outputs``, #6193) — or None when either cannot
    be read (the gates then refuse: nothing is proposed or approved unchecked)."""
    try:
        from web import narrative_publication as NPub, publication_snapshot as PS, withheld_outputs as WO  # noqa: PLC0415

        NPub.begin_request()
        PS.begin_request(_table_ref)
        PS.complete()
        WO.load(_table_ref)
        return WO.with_outputs(NPub.is_tainted, _table_ref)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[#6193] publication record unreadable: {type(exc).__name__}")
        return None


def _filter_hits(text: str) -> list:
    from privacy import privacy_guard  # noqa: PLC0415 — the chronicle's publish gate; no vocabulary raises (fail closed)

    return privacy_guard.find_violations(text)


def _private_calls():
    """#6199: the calls and asks the publication policy classifies, read now — or None when they cannot be read (the
    gates then refuse: an edition is never proposed or approved with the private-call check unrun)."""
    try:
        return private_call_check.load(_table_ref)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[#6199] private-call check: the coach calls could not be read ({type(exc).__name__}: {exc}) — refusing")
        return None


def _gate(text) -> list:
    return CE.gate_findings(text, tainted=_tainted(), private_calls=private_call_check.for_text(_private_calls()), filter_hits=_filter_hits)


def _int_arg(args: dict, key: str):
    v = args.get(key)
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _put_once(item: dict, what: str) -> dict | None:
    try:
        _table_ref.put_item(Item=item, ConditionExpression="attribute_not_exists(sk)")
    except Exception as exc:  # noqa: BLE001
        if "ConditionalCheckFailed" in str(exc) or "ConditionalCheckFailed" in type(exc).__name__:
            return {"error": f"{what} already exists; records are append-only (propose a new number). Nothing was stored."}
        logger.warning(f"[#6193] {what} write failed: {type(exc).__name__}")
        return {"error": f"{what} could not be stored ({type(exc).__name__}). Nothing was stored."}
    return None


def _approve_once(key: dict, sets: str, values: dict, what: str) -> dict | None:
    try:
        _table_ref.update_item(
            Key=key,
            UpdateExpression="SET approvals = list_append(approvals, :a), " + sets,
            ConditionExpression="attribute_exists(sk) AND size(approvals) = :zero",
            ExpressionAttributeValues={**values, ":zero": 0},
        )
    except Exception as exc:  # noqa: BLE001
        if "ConditionalCheckFailed" in str(exc) or "ConditionalCheckFailed" in type(exc).__name__:
            return {"error": f"{what} changed under the approval (already approved?). Nothing was stored."}
        logger.warning(f"[#6193] {what} approval write failed: {type(exc).__name__}")
        return {"error": f"the approval could not be stored ({type(exc).__name__}). Nothing was stored."}
    return None


def _hash_mismatch(args: dict, item: dict) -> dict | None:
    """The approval binds to the exact bytes he approved: ``sha256`` must be given and equal the stored text's."""
    given = str(args.get("sha256") or "").strip().lower()
    if not CE.SHA256.match(given):
        return {"error": "sha256 (the SHA-256 of the exact text Matthew approved) is required. Nothing was stored."}
    if given != item.get("text_sha256"):
        return {
            "error": f"the stored text hashes to {item.get('text_sha256')}, not the approved {given}; the approval does not "
            "bind to these bytes. Propose the approved text as a new edition number. Nothing was stored."
        }
    return None


def _refused(findings: list) -> dict:
    return {"error": "the publication gates refused the text. Nothing was stored.", "findings": findings}


#: The chapter's own public page, whose heading is the published title an edition must keep (#6193 B4).
CHAPTER_PAGE = "https://averagejoematt.com/story/{chapter_id}/"


def _published_title(chapter_id: str) -> str | None:
    """The chapter's published title, read off its public page's heading (read-only HTTPS); None when unreadable."""
    try:
        req = urllib.request.Request(CHAPTER_PAGE.format(chapter_id=chapter_id), headers={"User-Agent": "averagejoematt-mcp editions/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:  # nosec B310 — fixed https URL
            page = r.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[#6193] published title unreadable for {chapter_id}: {type(exc).__name__}")
        return None
    m = re.search(r"<h1[^>]*>([\s\S]*?)</h1>", page)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", m.group(1))).split()) if m else None


def _propose_edition(args: dict) -> dict:
    try:
        item = CE.new_edition(
            chapter_id=str(args.get("chapter_id") or "").strip(),
            edition=_int_arg(args, "edition"),
            text=args.get("text"),
            first_published=str(args.get("first_published") or "").strip(),
            proposed_at=_now(),
            carries=args.get("carries") or [],
            user_id=USER_ID,
        )
    except CE.EditionError as exc:
        return {"error": f"{exc}. Nothing was stored."}
    retitled = CE.title_problem(item["text"], _published_title(item["chapter_id"]))
    if retitled:
        return {"error": f"{retitled}. Nothing was stored."}
    findings = _gate(item["text"])
    if findings:
        return _refused(findings)
    err = _put_once(item, f"edition {item['edition']} of {item['chapter_id']}")
    if err:
        return err
    return {
        "stored": True,
        "approved": False,
        "renders": False,
        "chapter_id": item["chapter_id"],
        "edition": item["edition"],
        "sha256": item["text_sha256"],
    }


def _approve_edition(args: dict) -> dict:
    if args.get("approved") is not True:
        return {"error": "approved must be exactly true, given only after Matthew explicitly approved this edition. Nothing was stored."}
    chapter_id, edition = str(args.get("chapter_id") or "").strip(), _int_arg(args, "edition")
    try:
        CE.ordinal(edition)
        key = {"pk": CE.pk(USER_ID), "sk": CE.sk_edition(chapter_id, edition)}
    except (CE.EditionError, TypeError) as exc:
        return {"error": f"{exc}. Nothing was stored."}
    item = _table_ref.get_item(Key=key, ConsistentRead=True).get("Item")
    if not item or item.get("record_type") != CE.EDITION_TYPE:
        return {"error": f"no proposed edition {edition} of {chapter_id}. Nothing was stored."}
    if item.get("approvals"):
        return {"error": f"edition {edition} of {chapter_id} is already approved (revised {item.get('revised_on')}). Nothing was stored."}
    bound = _hash_mismatch(args, item)
    if bound:
        return bound
    original = _table_ref.get_item(Key={"pk": key["pk"], "sk": CE.sk_original(chapter_id)}, ConsistentRead=True).get("Item")
    try:
        CE.validate_original(original)
    except CE.EditionError:
        return {
            "error": f"the first edition of {chapter_id} has no private backup on record; run scripts/chronicle_edition_backup.py "
            "--apply for it first (the original is kept before anything changes). Nothing was stored."
        }
    restore = _table_ref.get_item(Key={"pk": key["pk"], "sk": CE.sk_restore(chapter_id)}, ConsistentRead=True).get("Item")
    try:
        CE.validate_restore(restore, original)  # rehearsal §6: the restore path verified, not merely the files present
    except CE.EditionError as exc:
        return {
            "error": f"{exc}: run scripts/chronicle_edition_backup.py --chapter {chapter_id} --verify-restore --apply first. "
            "Nothing was stored."
        }
    approved_corrections = {c["id"] for c in CC.public_view(_rows(chapter_id)) if c["chapter_id"] == chapter_id}
    missing = [c for c in item.get("carries") or [] if c not in approved_corrections]
    if missing:
        return {"error": f"carried corrections not approved for {chapter_id}: {', '.join(missing)}. Nothing was stored."}
    findings = _gate(item.get("text"))
    if findings:
        return _refused(findings)
    day = pacific_today()
    try:
        entry = CE.approval(at=_now(), dated_on=day, sha256=item["text_sha256"], note=str(args.get("note") or ""))
        sig = CE.signature(edition, day)
        CE.validate_edition({**item, "approvals": [entry], "approved_at": entry["at"], "revised_on": day, "signature": sig})
    except (CE.EditionError, CC.CorrectionError) as exc:
        return {"error": f"{exc}. Nothing was stored."}
    err = _approve_once(
        key,
        "approved_at = :at, revised_on = :d, signature = :s",
        {":a": [entry], ":at": entry["at"], ":d": day, ":s": sig},
        f"edition {edition} of {chapter_id}",
    )
    if err:
        return err
    return {
        "stored": True,
        "approved": True,
        "chapter_id": chapter_id,
        "edition": edition,
        "revised_on": day,
        "signature": sig,
        "renders": CE.LIVE,
        "note": None if CE.LIVE else "approved and recorded; nothing renders while content.chapter_editions.LIVE is False",
    }


def _propose_archival(args: dict) -> dict:
    try:
        item = CE.new_archival(
            chapter_id=str(args.get("chapter_id") or "").strip(),
            archival_id=_int_arg(args, "archival_id"),
            text=args.get("text"),
            proposed_at=_now(),
            as_of=(str(args["as_of"]).strip() or None) if args.get("as_of") else None,
            user_id=USER_ID,
        )
    except CE.EditionError as exc:
        return {"error": f"{exc}. Nothing was stored."}
    findings = _gate(item["text"])
    if findings:
        return _refused(findings)
    err = _put_once(item, f"archival rendering {item['archival_id']} of {item['chapter_id']}")
    if err:
        return err
    return {
        "stored": True,
        "approved": False,
        "renders": False,
        "chapter_id": item["chapter_id"],
        "archival_id": item["archival_id"],
        "as_of": item["as_of"],
        "sha256": item["text_sha256"],
    }


def _withdraw(args: dict, kind: str) -> dict:
    """#6193 B7: withdraw ONE approved edition or rendering — an appended, dated record, only on his explicit word."""
    what = "edition" if kind == "edition" else "archival rendering"
    if args.get("approved") is not True:
        return {
            "error": f"approved must be exactly true, given only after Matthew explicitly asked to withdraw this {what}. Nothing was stored."
        }
    chapter_id = str(args.get("chapter_id") or "").strip()
    n = _int_arg(args, "edition" if kind == "edition" else "archival_id")
    try:
        item = CE.new_withdrawal(
            chapter_id=chapter_id, kind=kind, number=n, at=_now(), dated_on=pacific_today(), note=str(args.get("note") or "")
        )
    except CE.EditionError as exc:
        return {"error": f"{exc}. Nothing was stored."}
    target_sk = CE.sk_edition(chapter_id, n) if kind == "edition" else CE.sk_archival(chapter_id, n)
    target = _table_ref.get_item(Key={"pk": item["pk"], "sk": target_sk}, ConsistentRead=True).get("Item")
    if not target or not target.get("approvals"):
        return {"error": f"there is no approved {what} {n} of {chapter_id} to withdraw. Nothing was stored."}
    err = _put_once(item, f"the withdrawal of {what} {n} of {chapter_id}")
    if err:
        return err
    return {
        "stored": True,
        "withdrawn": True,
        "chapter_id": chapter_id,
        "kind": kind,
        "number": n,
        "withdrawn_on": item["withdrawn_on"],
        "note": f"{chapter_id} serves its first edition from the next Site API read and site build; other chapters are untouched; "
        "a re-approval is a new number",
    }


def _approve_archival(args: dict) -> dict:
    if args.get("approved") is not True:
        return {"error": "approved must be exactly true, given only after Matthew explicitly approved this rendering. Nothing was stored."}
    chapter_id, n = str(args.get("chapter_id") or "").strip(), _int_arg(args, "archival_id")
    if not CE.CHAPTER_ID.match(chapter_id) or not isinstance(n, int) or not 1 <= n <= 99:
        return {"error": "chapter_id (week-NN) and archival_id (1-99) are required. Nothing was stored."}
    key = {"pk": CE.pk(USER_ID), "sk": CE.sk_archival(chapter_id, n)}
    item = _table_ref.get_item(Key=key, ConsistentRead=True).get("Item")
    if not item or item.get("record_type") != CE.ARCHIVAL_TYPE:
        return {"error": f"no proposed archival rendering {n} of {chapter_id}. Nothing was stored."}
    if item.get("approvals"):
        return {"error": f"archival rendering {n} of {chapter_id} is already approved. Nothing was stored."}
    bound = _hash_mismatch(args, item)
    if bound:
        return bound
    approved_editions = [r for r in _edition_rows(chapter_id) if r.get("record_type") == CE.EDITION_TYPE and r.get("approvals")]
    if not approved_editions:
        return {"error": f"{chapter_id} has no approved second edition; the first edition is still its current text. Nothing was stored."}
    findings = _gate(item.get("text"))
    if findings:
        return _refused(findings)
    day = pacific_today()
    try:
        entry = CE.approval(at=_now(), dated_on=day, sha256=item["text_sha256"], note=str(args.get("note") or ""))
        CE.validate_archival({**item, "approvals": [entry], "approved_at": entry["at"], "approved_on": day})
    except (CE.EditionError, CC.CorrectionError) as exc:
        return {"error": f"{exc}. Nothing was stored."}
    err = _approve_once(
        key, "approved_at = :at, approved_on = :d", {":a": [entry], ":at": entry["at"], ":d": day}, f"archival rendering {n}"
    )
    if err:
        return err
    return {"stored": True, "approved": True, "chapter_id": chapter_id, "archival_id": n, "approved_on": day, "renders": CE.LIVE}


def _list_editions(chapter_id: str | None) -> dict:
    rows = _edition_rows(chapter_id)
    served = {
        e["chapter_id"]: e
        for e in CE.public_view(
            rows, tainted=_tainted(), private_calls=private_call_check.for_text(_private_calls()), filter_hits=_filter_hits, log=logger.info
        )
    }
    items = []
    for r in sorted(rows, key=lambda r: str(r.get("sk"))):
        cid, kind = r.get("chapter_id"), r.get("record_type")
        s = served.get(cid) or {}
        if kind == CE.EDITION_TYPE:
            n = int(r.get("edition") or 0)
            renders = bool(s) and s.get("edition") == n
        elif kind == CE.ARCHIVAL_TYPE:
            n = int(r.get("archival_id") or 0)
            renders = bool(s.get("archival")) and s["archival"]["archival_id"] == n
        elif kind == CE.WITHDRAWAL_TYPE:
            n, renders = int(r.get("number") or 0), False
        else:
            n, renders = 1, False
        items.append(
            {
                "chapter_id": cid,
                "sk": r.get("sk"),
                "kind": {
                    CE.EDITION_TYPE: "edition",
                    CE.ARCHIVAL_TYPE: "archival",
                    CE.ORIGINAL_TYPE: "first-edition evidence",
                    CE.WITHDRAWAL_TYPE: f"withdrawal of {r.get('kind')}",
                    CE.RESTORE_TYPE: "restore rehearsal (passed)",
                }.get(kind, kind),
                "number": n,
                "first_published": r.get("first_published"),
                "carries": r.get("carries"),
                "proposed_at": r.get("proposed_at"),
                "approved": bool(r.get("approvals")),
                "revised_on": r.get("revised_on") or r.get("approved_on") or r.get("withdrawn_on"),
                "as_of": r.get("as_of"),
                "backed_up_at": r.get("backed_up_at"),
                "words": CE.word_count(r.get("text")) if r.get("text") else None,
                "sha256": r.get("text_sha256"),
                "would_render": renders,
                "renders": renders and CE.LIVE,
            }
        )
    return {"switch_live": CE.LIVE, "records": items, "count": len(items), "chapters_with_an_edition": sorted(served)}


def tool_manage_chapter_corrections(args):
    """List, propose or approve a dated public correction to a published chapter — or (#6193) a second edition of one."""
    args = args or {}
    action = str(args.get("action") or "list").strip()
    editions = {
        "propose_edition": _propose_edition,
        "approve_edition": _approve_edition,
        "propose_archival": _propose_archival,
        "approve_archival": _approve_archival,
        "withdraw_edition": lambda a: _withdraw(a, "edition"),
        "withdraw_archival": lambda a: _withdraw(a, "archival"),
    }
    if action in editions:
        return editions[action](args)
    if action == "list_editions":
        chapter_id = str(args.get("chapter_id") or "").strip() or None
        if chapter_id and not CE.CHAPTER_ID.match(chapter_id):
            return {"error": "chapter_id must be week-NN."}
        return _list_editions(chapter_id)
    if action == "list":
        chapter_id = str(args.get("chapter_id") or "").strip() or None
        if chapter_id and not CC.CHAPTER_ID.match(chapter_id):
            return {"error": "chapter_id must be week-NN."}
        return _listing(_rows(chapter_id))
    if action == "propose":
        return _propose(args)
    if action == "approve":
        return _approve(args)
    return {
        "error": f"unknown action {action!r}: list, propose, approve, list_editions, propose_edition, approve_edition, withdraw_edition, propose_archival, approve_archival or withdraw_archival."
    }
